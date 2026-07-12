"""
src/api/routes_dsl.py
——————————————————————————————————————————————————————————————————————
Story DSL 接口集  (Phase 4.1 → Phase 5.2)

端点
─────────────────────────────────────────────────────────────────────
  POST  /tasks/draft-blueprint 【Phase 9.2】战术板同步起草：
                             DirectorNode.draft_blueprint，返回融合 JSON
                            （timeline + script_data，供前端点亮）。

  POST  /tasks/enhance-prompt 【Phase 9.4】魔法扩写：
                             OpenAIProvider + prompt_enhance.jinja，
                             返回 enhanced_prompt（BYOK 兼容）。

  POST  /tasks/submit-dsl    【Phase 5.2 升级】全链路渲染入口：
                             DSL 解析 + 蓝图适配 + 后台渲染三合一。
                             接口立即返回 202（含 CompilationPlan 快照
                             + task_id），FFmpeg 渲染通过 BackgroundTasks
                             异步执行，进度由 WS 事件总线推送。

  POST  /tasks/render-dsl    【Phase 5.1】纯渲染触发端点：直接接收
                             RenderDSLRequest（含渲染配置字段），
                             与 submit-dsl 共用同一 render_worker。

内部工具函数
─────────────────────────────────────────────────────────────────────
  render_worker(plan, task_id, ...)   — 后台渲染主 Worker
  _run_compositor(compositor, ctx)    — 底层 FFmpeg 调用封装（异常日志）
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from .database import get_db, get_tenant_engine
from .dsl_adapter import compile_plan_to_timeline
from src.api.ws_manager import manager as ws_manager
from .dsl_parser import DSLParserNode
from .models import LocalAsset, TaskHistory
from .schemas import (
    CompilationPlan,
    CompilationPlanSummary,
    DSLBeatNode,
    DSLSubmitResponse,
    DraftBlueprintRequest,
    EnhancePromptRequest,
    RenderDSLAck,
    RenderDSLRequest,
    StoryDSLPayload,
)
from src.services.llm_provider import OpenAIProvider
from src.utils.prompt_loader import prompt_loader
from src.core.context import WorkflowContext
from src.nodes.compositor import FFmpegCompositorNode
from src.nodes.cover_node import CoverNode
from src.nodes.director_node import DirectorNode
from src.nodes.subtitle import SubtitleNode
from src.nodes.tts_node import TTSNode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["Story DSL"])


def _parse_plan_from_db(tenant_id: str, payload: StoryDSLPayload) -> CompilationPlan:
    """在 Worker 线程内打开租户库会话，执行 DSLParserNode。"""
    _tenant_engine = get_tenant_engine(tenant_id)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_tenant_engine)
    with _SessionLocal() as db:
        return DSLParserNode(db).parse_and_resolve(payload)


def _fetch_available_tags(tenant_id: str) -> list[str]:
    """
    从租户素材库查询所有 LocalAsset 的不重复标签列表。

    供 DirectorNode.draft_blueprint 注入 Jinja 模板，约束 LLM 的
    semantic_tags 只能从库内真实存在的标签中挑选，杜绝幻觉捏造。
    """
    _engine = get_tenant_engine(tenant_id)
    _Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    tag_set: set[str] = set()
    try:
        with _Session() as db:
            rows = (
                db.query(LocalAsset.tags)
                .filter(
                    LocalAsset.is_deleted.is_(False),
                    LocalAsset.tags.isnot(None),
                )
                .all()
            )
            for (tags,) in rows:
                if isinstance(tags, list):
                    tag_set.update(
                        t for t in tags if isinstance(t, str) and t.strip()
                    )
    except Exception:
        logger.warning(
            "[routes_dsl] _fetch_available_tags 查询失败，返回空标签库", exc_info=True
        )
    result = sorted(tag_set)
    logger.debug("[routes_dsl] _fetch_available_tags tenant=%s tags=%d", tenant_id, len(result))
    return result


def _is_blind_fission(payload: RenderDSLRequest) -> bool:
    """极速闭眼裂变：batch≥1 + 非空 prompt + 空 timeline。"""
    return (
        payload.batch_size >= 1
        and bool(payload.prompt and payload.prompt.strip())
        and len(payload.timeline) == 0
    )


# ================================================================== #
# 后台渲染 Worker  (Phase 5.2)                                        #
# ================================================================== #

def render_worker(
    plan: Optional[CompilationPlan],
    task_id: str,
    aspect_ratio: str = "9:16",
    target_duration: int = 15,
    tenant_id: str = "default",
    prompt: Optional[str] = None,
    batch_size: int = 1,
    test_language: str = "en",
    file_sid: Optional[str] = None,
    suppress_completed_ws: bool = False,
    *,
    blind_dsl: bool = False,
    engine_type: str = "content",
    director_mode: str = "auto",
    dsl_payload: Optional[StoryDSLPayload] = None,
    enable_tts: bool = True,
    enable_subtitles: bool = True,
) -> list[dict]:
    """
    后台渲染主 Worker（Phase 9.11.2 单轨线性架构）。

    blind_dsl=True 时在本线程内由 DirectorNode 生成含 script_text 的 timeline，
    再经 DSLParserNode 编译为 CompilationPlan；各矩阵子线程独立调用大模型，
    利用采样随机性产生差异化文案与打标。

    单轨线性架构要点：
      - 每个 Beat 的 script_text 直接驱动 TTS，不再依赖独立 script_data 根节点。
      - context.assets["tts_script"] = {lang: "聚合全文"} 作为 TTSNode 的唯一入口。
      - 无 Beat 台词时（纯积木模式），DirectorNode 兜底生成后同样写入 tts_script。

    纯积木模式（prompt 为空）：注入 default 变体，仅合流 BGM/SFX。
    """
    logger.info(
        "[render_worker] 开始渲染 task_id=%s aspect=%s duration=%ds tenant=%s mode=%s",
        task_id, aspect_ratio, target_duration, tenant_id,
        "hybrid" if prompt else "dsl-only",
    )

    collected_assets: list[dict] = []
    _start_time: float = time.time()

    try:
        working_plan: Optional[CompilationPlan] = plan

        if blind_dsl:
            if not prompt or not str(prompt).strip():
                logger.error(
                    "[render_worker] blind_dsl 需要非空 prompt，task_id=%s", task_id,
                )
                return []
            langs = [test_language] if test_language else ["en"]
            director = DirectorNode()

            # 注入可用标签菜单（防幻觉）：从租户库实时抽取真实存在的 Faceted Tags
            _available_tags = _fetch_available_tags(tenant_id)
            logger.info(
                "[render_worker] task_id=%s 标签菜单注入：%d 个可用标签供 LLM 约束",
                task_id, len(_available_tags),
            )

            bp = director.draft_blueprint(
                str(prompt).strip(),
                director_mode,
                target_duration,
                langs,
                available_tags=_available_tags,
                llm_temperature=0.92,
            )
            # 单轨模式：script_text 已内聚于各 Beat，无需独立 script_data 根节点
            logger.info(
                "[render_worker] task_id=%s 单轨闭眼裂变：DirectorNode 生成含 script_text 的 timeline",
                task_id,
            )

            beat_nodes: list[DSLBeatNode] = []
            for i, row in enumerate(bp.get("timeline") or []):
                if not isinstance(row, dict):
                    continue
                try:
                    beat_nodes.append(DSLBeatNode.model_validate(row))
                except Exception:
                    logger.warning(
                        "[render_worker] task_id=%s timeline[%d] 非法，跳过: %r",
                        task_id, i, row,
                    )
            if not beat_nodes:
                logger.error(
                    "[render_worker] task_id=%s blind_dsl 无有效 Beat，终止。", task_id,
                )
                return []

            dsl_payload = StoryDSLPayload(
                engine_type=engine_type,
                timeline=beat_nodes,
                meta=bp.get("meta") or None,
            )
            working_plan = _parse_plan_from_db(tenant_id, dsl_payload)
            logger.info(
                "[render_worker] task_id=%s blind_dsl 解析 resolved=%d/%d unresolved=%s",
                task_id,
                working_plan.summary.resolved_beats,
                working_plan.summary.total_beats,
                working_plan.unresolved_beats or "[]",
            )
            if working_plan.summary.resolved_beats == 0:
                logger.error(
                    "[render_worker] task_id=%s blind_dsl 无可渲染 Beat：%s",
                    task_id,
                    working_plan.unresolved_beats,
                )
                return []
        else:
            if dsl_payload is not None:
                # 动态运行时寻址：Worker 线程内独立重新执行资产抽卡，
                # 确保批量并发时各子任务命中不同素材（_score_candidates + random.choice）
                working_plan = _parse_plan_from_db(tenant_id, dsl_payload)
                logger.info(
                    "[render_worker] task_id=%s 动态寻址完成 resolved=%d/%d",
                    task_id,
                    working_plan.summary.resolved_beats,
                    working_plan.summary.total_beats,
                )
                if working_plan.summary.resolved_beats == 0:
                    logger.error(
                        "[render_worker] task_id=%s 动态寻址无可渲染 Beat，终止。", task_id,
                    )
                    return []
            elif plan is not None:
                working_plan = plan
            else:
                logger.error(
                    "[render_worker] task_id=%s 缺少 CompilationPlan 或 StoryDSLPayload（非 blind_dsl）",
                    task_id,
                )
                return []

        # ── 1. CompilationPlan → Timeline ─────────────────────────────
        assert working_plan is not None, "working_plan must be resolved before this point"
        timeline = compile_plan_to_timeline(
            working_plan, target_duration=target_duration,
        )

        if not timeline.tracks:
            logger.error(
                "[render_worker] task_id=%s Timeline 主视频轨为空，终止渲染。",
                task_id,
            )
            try:
                ws_manager.broadcast_sync(
                    {
                        "type": "WS_UPDATE",
                        "payload": {
                            "taskId": task_id,
                            "status": "failed",
                            "error": "主视频轨为空：beat 无视频素材或 semantic_tags 未命中库内视频，请检查战术板装填。",
                        },
                    },
                    user_id=tenant_id,
                )
            except Exception:
                logger.warning("[render_worker] WS failed 广播异常 task_id=%s", task_id)
            return []

        # ── 2. 初始化 WorkflowContext，将 Timeline 注入数据总线 ─────────
        context = WorkflowContext(
            session_id=task_id,
            aspect_ratio=aspect_ratio,
            target_duration=target_duration,
            tenant_id=tenant_id,
            batch_size=batch_size,
            test_language=test_language,
        )
        context.set_asset("timeline", timeline)

        # ── 3. 指纹隔离：对齐 run_matrix_factory 命名约定 ────────────────
        # compositor.py 读取 context.config["session_id"] 作为文件名后缀：
        #   master_video_{sid}.mp4  /  final_{lang}_{sid}.mp4
        # file_sid 由 render_batch_worker 传入（确保批量子任务文件名唯一），
        # 单任务模式下 file_sid=None，回退到 task_id[:8]。
        sid8 = file_sid or task_id[:8]
        context.config["session_id"] = sid8
        context.config["enable_tts"] = enable_tts
        context.config["enable_subtitles"] = enable_subtitles
        if suppress_completed_ws:
            context.config["ws_suppress_completed"] = True
        os.makedirs("output", exist_ok=True)

        # ── 4. 动态模态路由 ────────────────────────────────────────────
        if prompt:
            logger.info(
                "[render_worker] task_id=%s 混合编排：单轨台词 → TTS → Subtitle → Compositor",
                task_id,
            )

            # 单轨原位提取：从 dsl_payload.timeline 各 Beat 的 script_text 聚合
            _active_payload = dsl_payload
            _beat_texts = [
                b.script_text.strip()
                for b in (_active_payload.timeline if _active_payload else [])
                if b.script_text and b.script_text.strip()
            ]

            if _beat_texts:
                _tts_lang = test_language or "en"
                context.set_asset("tts_script", {_tts_lang: "\n".join(_beat_texts)})
                logger.info(
                    "[render_worker] task_id=%s 单轨模式：聚合 %d 个 Beat script_text "
                    "→ tts_script[%s] len=%d",
                    task_id, len(_beat_texts), _tts_lang,
                    sum(len(t) for t in _beat_texts),
                )
            else:
                # 无 Beat 台词 → DirectorNode 兜底生成（写入 context.assets["tts_script"]）
                logger.info(
                    "[render_worker] task_id=%s Beat 无 script_text，导演节点兜底生成台词",
                    task_id,
                )
                context.set_asset("script", prompt)
                DirectorNode().execute(context)

            # TTSNode 读取 tts_script，将 MP3 + VTT 写入 context.variants[lang]
            if enable_tts:
                TTSNode().execute(context)
            else:
                logger.info(
                    "[render_worker] task_id=%s enable_tts=False，跳过 TTS 播音节点，"
                    "仅保留 BGM 音轨",
                    task_id,
                )

            # ── TranslationBridge（内联）：从 tts_script + Beat 时长计算字幕时间轴 ──
            if enable_subtitles:
                tts_script: dict = context.get_asset("tts_script") or {}
                _translations: dict = {
                    lang: text
                    for lang, text in tts_script.items()
                    if text and str(text).strip()
                }
                # Beat 时长累加；若 LLM 未提供 duration，回退至 target_duration
                _beats_for_dur = _active_payload.timeline if _active_payload else []
                _total_duration = sum(
                    float(b.duration) for b in _beats_for_dur if b.duration
                )
                if _total_duration <= 0:
                    _total_duration = float(target_duration)

                context.config["translations"] = _translations
                context.config["subtitle_start"] = 0.0
                context.config["subtitle_end"] = _total_duration
                logger.debug(
                    "[render_worker] task_id=%s TranslationBridge: langs=%s subtitle_end=%.1fs",
                    task_id,
                    list(_translations.keys()),
                    _total_duration,
                )
                SubtitleNode().execute(context)
            else:
                logger.info(
                    "[render_worker] task_id=%s enable_subtitles=False，跳过字幕烧录节点",
                    task_id,
                )

            # 确认字幕文件已注入 context
            target_lang = getattr(context, "test_language", "en") or "en"
            _subtitle_ass = (context.variants.get(target_lang) or {}).get("subtitle_ass", "")
            if _subtitle_ass:
                logger.debug(
                    "[render_worker] task_id=%s 字幕文件已写入 context: lang=%s path=%s",
                    task_id, target_lang, _subtitle_ass,
                )
            else:
                logger.warning(
                    "[render_worker] task_id=%s SubtitleNode 未生成字幕（lang=%s），"
                    "Compositor 将跳过字幕轨道。",
                    task_id, target_lang,
                )
        else:
            logger.info("[render_worker] task_id=%s 纯积木模式：注入 default 变体触发 BGM/SFX 混音", task_id)
            # ADR-1 延后混音：无 TTS 时手动注入 default 变体，
            # 驱动 compositor._render_variant 进入 BGM/SFX 合流阶段。
            context.variants = {"default": {}}

        # ── 5. 渲染前安检（Pre-flight Check）────────────────────────────
        # 统计有效主视频层（layer_index == 0）数量；归零则熔断，绝不下发 FFmpeg。
        _valid_main_clips = sum(
            1
            for _beat in (working_plan.beats if working_plan else [])
            if _beat.resolved and any(lyr.layer_index == 0 for lyr in _beat.layers)
        )
        if _valid_main_clips == 0:
            logger.error(
                "❌ 任务 %s 缺乏主视觉素材，触发安全熔断！引擎拦截渲染，不调用 FFmpeg。",
                task_id,
            )
            try:
                ws_manager.broadcast_sync(
                    {
                        "type": "WS_UPDATE",
                        "payload": {
                            "taskId": task_id,
                            "status": "failed",
                            "error": (
                                "严重缺料：未找到匹配的主视觉视频。"
                                "请检查素材库标签覆盖，或向素材库添加「通用空镜」兜底素材。"
                            ),
                        },
                    },
                    user_id=tenant_id,
                )
            except Exception:
                logger.warning(
                    "[render_worker] 熔断 WS failed 广播异常 task_id=%s", task_id
                )
            return []

        # ── 5b. 引擎点火 ───────────────────────────────────────────────
        render_ok = _run_compositor(FFmpegCompositorNode(), context)

        # ── 5c. 封面抽帧（Phase 9.8.2）─────────────────────────────────
        # CoverNode 为非关键路径：失败只记录日志，不回滚渲染结果。
        if render_ok:
            logger.info(
                "[render_worker] task_id=%s 渲染完成，启动 CoverNode 封面抽帧...",
                task_id,
            )
            cover_ok = _run_cover_node(CoverNode(), context)
            _cover_path: str = context.get_asset("cover_path") or ""
            if cover_ok:
                logger.info(
                    "[render_worker] task_id=%s CoverNode ✅ 封面生成成功: %s",
                    task_id, _cover_path,
                )
            else:
                logger.warning(
                    "[render_worker] task_id=%s CoverNode ⚠️ 封面抽帧失败，"
                    "前端将显示缺省占位块。",
                    task_id,
                )
        else:
            _cover_path = ""

        # ── 6. 收集输出资产 ─────────────────────────────────────────────
        # 提取社交元数据，随资产一并写入 WS payload，前端无需二次 API 请求即可渲染 HUD
        _social_fields: dict = {}
        if dsl_payload is not None and dsl_payload.meta is not None:
            try:
                _meta_dump = dsl_payload.meta.model_dump()
                _social_fields = {
                    k: _meta_dump[k]
                    for k in ("social_title", "social_caption", "social_hashtags")
                    if _meta_dump.get(k)
                }
            except Exception:
                pass

        if render_ok:
            for _variant_assets in context.variants.values():
                _fp = _variant_assets.get("final_video", "")
                if _fp and os.path.exists(_fp):
                    _h = hashlib.md5()
                    try:
                        with open(_fp, "rb") as _f:
                            _h.update(_f.read(65536))
                    except OSError:
                        _h.update(_fp.encode())
                    collected_assets.append({
                        "file_path": _fp,
                        "file_hash": _h.hexdigest(),
                        "cover_path": _cover_path,  # ← CoverNode 执行完毕后才填入，时序正确
                        **_social_fields,
                    })

        # ── 6b. WS 最终 completed 推送（CoverNode 已执行完毕，封面路径已就绪）──
        # suppress_completed_ws=True 时由 render_batch_worker 统一推送，此处跳过。
        if render_ok and not suppress_completed_ws:
            _ws_status = "completed" if collected_assets else "failed"
            _ws_payload: dict = {
                "taskId": task_id,
                "status": _ws_status,
                "generation_mode": director_mode,
            }
            if collected_assets:
                _ws_payload["assets"] = collected_assets
            try:
                ws_manager.broadcast_sync(
                    {"type": "WS_UPDATE", "payload": _ws_payload},
                    user_id=tenant_id,
                )
                logger.info(
                    "[render_worker] ✅ WS completed 推送完成 task_id=%s assets=%d cover=%s",
                    task_id, len(collected_assets), bool(_cover_path),
                )
            except Exception as _ws_exc:
                logger.warning(
                    "[render_worker] WS completed 广播异常（不阻断主流程）: %r", _ws_exc
                )

        # ── 6c. 历史记录写入 TaskHistory ──────────────────────────────────
        if render_ok and collected_assets:
            try:
                _elapsed = round(time.time() - _start_time, 1)
                _prompt_details: dict[str, Any] = {
                    "meta": (
                        dsl_payload.meta.model_dump()
                        if dsl_payload is not None and dsl_payload.meta is not None
                        else None
                    ),
                    "timeline": [
                        b.model_dump() for b in (working_plan.beats if working_plan else [])
                    ],
                }
                _details_json: str = json.dumps(
                    _prompt_details,
                    ensure_ascii=False,
                )
                _history_prompt = prompt or ""
                _history_record = TaskHistory(
                    task_id=task_id,
                    prompt=_history_prompt,
                    batch_size=batch_size,
                    duration=_elapsed,
                    output_assets=collected_assets,
                    prompt_details=_details_json,
                    created_at=datetime.utcnow(),
                )
                _hist_engine = get_tenant_engine(tenant_id)
                _HistSession = sessionmaker(
                    autocommit=False, autoflush=False, bind=_hist_engine
                )
                with _HistSession() as _db:
                    _db.add(_history_record)
                    _db.commit()
                logger.info(
                    "[render_worker] ✅ 历史记录写入成功: task_id=%s duration=%.1fs",
                    task_id, _elapsed,
                )
            except Exception as e:
                logger.error(
                    "[render_worker] ❌ 历史记录写入数据库失败: task_id=%s error=%s",
                    task_id, str(e), exc_info=True,
                )

        # ── 6d. 疲劳值回写 ────────────────────────────────────────────────
        if render_ok and working_plan:
            try:
                used_asset_ids: set[int] = set()
                for beat in working_plan.beats:
                    for layer in beat.layers:
                        if layer.asset_id:
                            used_asset_ids.add(layer.asset_id)

                if used_asset_ids:
                    _tenant_engine = get_tenant_engine(tenant_id)
                    _SessionLocal = sessionmaker(
                        autocommit=False, autoflush=False, bind=_tenant_engine
                    )
                    with _SessionLocal() as db:
                        now = datetime.utcnow()
                        assets = (
                            db.query(LocalAsset)
                            .filter(
                                LocalAsset.id.in_(used_asset_ids),
                                LocalAsset.is_deleted.is_(False),
                            )
                            .all()
                        )
                        for asset in assets:
                            asset.usage_count = (asset.usage_count or 0) + 1  # type: ignore[assignment]
                            asset.last_used_at = now  # type: ignore[assignment]
                        db.commit()
                    logger.info(
                        "[render_worker] task_id=%s 疲劳值回写成功，共刷新 %d 个弹药资产。",
                        task_id, len(assets),
                    )
                else:
                    logger.debug(
                        "[render_worker] task_id=%s plan.beats 中无 asset_id，跳过疲劳值回写。",
                        task_id,
                    )
            except Exception:
                logger.exception(
                    "[render_worker] task_id=%s 疲劳值回写失败，请排查事务。", task_id
                )

    except Exception:
        logger.exception(
            "[render_worker] 渲染任务异常 task_id=%s", task_id
        )

    return collected_assets


def render_batch_worker(
    dsl_payload: Optional[StoryDSLPayload],
    task_id: str,
    aspect_ratio: str = "9:16",
    target_duration: int = 15,
    tenant_id: str = "default",
    prompt: Optional[str] = None,
    batch_size: int = 1,
    test_language: str = "en",
    *,
    blind_dsl: bool = False,
    engine_type: str = "content",
    director_mode: str = "auto",
    enable_tts: bool = True,
    enable_subtitles: bool = True,
    resolved_plan: Optional[CompilationPlan] = None,
) -> None:
    """
    批量矩阵渲染 Worker（Phase 5.9）。

    在 ThreadPoolExecutor 内并行运行 `batch_size` 个 `render_worker` 子任务，
    每个子任务分配唯一的 file_sid（文件名指纹），但全部共用同一 task_id 作为
    WS 事件标识，使前端队列只产生一张卡片。

    子任务均设置 suppress_completed_ws=True，不单独发送 completed 事件；
    所有子任务完成后，本函数统一向 task_id 推送一次含全部资产的 completed 事件，
    QueueView 的轮播逻辑随即展示 batch_size 个视频。
    """
    logger.info(
        "[render_batch_worker] 批量渲染启动 task_id=%s batch=%d",
        task_id, batch_size,
    )

    sub_sids = [uuid.uuid4().hex[:8] for _ in range(batch_size)]
    all_assets: list[dict] = []

    with ThreadPoolExecutor(max_workers=batch_size) as pool:
        future_map = {
            pool.submit(
                render_worker,
                None if blind_dsl else resolved_plan,
                task_id,
                aspect_ratio, target_duration, tenant_id,
                prompt, batch_size, test_language,
                sid,   # file_sid: 唯一文件名后缀
                True,  # suppress_completed_ws
                blind_dsl=blind_dsl,
                engine_type=engine_type,
                director_mode=director_mode,
                dsl_payload=None if blind_dsl else dsl_payload,
                enable_tts=enable_tts,
                enable_subtitles=enable_subtitles,
            ): sid
            for sid in sub_sids
        }

        for future in as_completed(future_map):
            sid = future_map[future]
            try:
                assets = future.result()
                if assets:
                    all_assets.extend(assets)
                    logger.info(
                        "[render_batch_worker] 子任务完成 sid=%s assets=%d",
                        sid, len(assets),
                    )
                else:
                    logger.warning(
                        "[render_batch_worker] 子任务无产出 sid=%s", sid,
                    )
            except Exception:
                logger.exception(
                    "[render_batch_worker] 子任务异常 sid=%s", sid,
                )

    # 所有子任务完成 → 推送一次 completed 事件，携带全部资产
    final_status = "completed" if all_assets else "failed"
    try:
        ws_manager.broadcast_sync(
            {
                "type": "WS_UPDATE",
                "payload": {
                    "taskId": task_id,
                    "status": final_status,
                    "generation_mode": director_mode,
                    **({"assets": all_assets} if all_assets else {}),
                },
            },
            user_id=tenant_id,
        )
        logger.info(
            "[render_batch_worker] task_id=%s %s，共 %d 个资产。",
            task_id, final_status, len(all_assets),
        )
    except Exception:
        logger.exception(
            "[render_batch_worker] WS 广播失败 task_id=%s", task_id,
        )


def _run_compositor(
    compositor: FFmpegCompositorNode,
    context: WorkflowContext,
) -> bool:
    """
    FFmpegCompositorNode 调用封装层。

    独立为函数的目的：BackgroundTasks 线程内的未捕获异常会被 Starlette
    静默丢弃，此处显式捕获并记录完整栈帧，保证渲染失败时有迹可查。

    Returns:
        True  — FFmpeg 渲染成功落盘；
        False — 渲染期间抛出异常，已记录完整栈帧。
    """
    try:
        compositor.execute(context)
        return True
    except Exception:
        logger.exception(
            "[_run_compositor] FFmpeg 渲染失败 session_id=%s", context.session_id
        )
        return False


def _run_cover_node(cover: CoverNode, context: WorkflowContext) -> bool:
    """
    CoverNode 调用封装层（Phase 9.8.2）。

    封面抽帧为非关键路径——失败不阻断渲染主流程，仅记录日志。
    Returns:
        True  — 封面 JPEG 已生成并写入 context.assets["cover_path"]；
        False — 抽帧失败，context 不含 cover_path（前端降级显示占位）。
    """
    try:
        cover.execute(context)
        return bool(context.get_asset("cover_path"))
    except Exception:
        logger.exception(
            "[_run_cover_node] CoverNode 异常（不阻断主流程） session_id=%s",
            context.session_id,
        )
        return False


# ================================================================== #
# POST /tasks/draft-blueprint  — 战术板同步蓝图  (Phase 9.2)         #
# ================================================================== #


@router.post(
    "/draft-blueprint",
    status_code=status.HTTP_200_OK,
    summary="导演同步起草蓝图（timeline + script_data）",
    description=(
        "同步调用 DirectorNode.draft_blueprint，返回单次 LLM 融合结构：\n"
        "视觉 timeline（DSL Beat 意向）与 script_data（TTS 台词轨），"
        "供战术板预览与微调后再走 submit-dsl。"
    ),
)
def draft_blueprint_endpoint(
    body: DraftBlueprintRequest,
    request: Request,
) -> dict[str, Any]:
    # 如果前端没有提供可用标签，从租户库自动查询并注入（防幻觉菜单供给）
    available_tags: list[str] = list(body.available_tags or [])
    if not available_tags:
        _tenant_id = request.headers.get("X-Local-User", "default") or "default"
        available_tags = _fetch_available_tags(_tenant_id)
        logger.info(
            "[routes_dsl] draft-blueprint 自动注入标签菜单：%d 个可用标签（tenant=%s）",
            len(available_tags), _tenant_id,
        )

    return DirectorNode().draft_blueprint(
        body.prompt,
        body.mode,
        body.duration,
        body.langs,
        available_tags=available_tags,
        user_hard_tags=body.user_hard_tags,
    )


# ================================================================== #
# POST /tasks/enhance-prompt  — 魔法扩写  (Phase 9.4)                  #
# ================================================================== #


@router.post(
    "/enhance-prompt",
    status_code=status.HTTP_200_OK,
    summary="魔法扩写与自动打标",
    description=(
        "将用户极简短句扩写为生动视频提示词，并从可用标签库中挑选 "
        "1~3 个 `@标签` 追加在文末。复用 OpenAIProvider（BYOK）与 JSON 契约。"
    ),
)
def enhance_prompt_endpoint(body: EnhancePromptRequest) -> dict[str, str]:
    system_prompt = prompt_loader.render_prompt(
        "prompt_enhance.jinja",
        available_tags=body.available_tags,
    )
    provider = OpenAIProvider()
    try:
        result = provider.generate_script(
            prompt=body.prompt.strip(),
            system_prompt=system_prompt,
            temperature=0.7,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        logger.exception("[routes_dsl] enhance-prompt LLM 调用失败")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    enhanced = result.get("enhanced_prompt") if isinstance(result, dict) else None
    if not enhanced or not str(enhanced).strip():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM 返回缺少 enhanced_prompt 字段或内容为空。",
        )
    return {"enhanced_prompt": str(enhanced).strip()}


# ================================================================== #
# POST /tasks/submit-dsl  — 全链路渲染入口  (Phase 5.2 升级)         #
# ================================================================== #

@router.post(
    "/submit-dsl",
    response_model=DSLSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Story DSL 全链路渲染（三合一）",
    description=(
        "接收 Story DSL Payload，一次调用完成：\n\n"
        "1. **DSL 解析**：执行双轨寻址（locked / smart），返回完整 CompilationPlan 蓝图\n"
        "2. **蓝图适配**：将 CompilationPlan → Timeline / Track / Clip 对象树\n"
        "3. **后台渲染**：通过 `BackgroundTasks` 异步触发 FFmpegCompositorNode\n\n"
        "接口立即返回 **202 Accepted**，响应体包含：\n"
        "- 完整的 `CompilationPlan` 蓝图（供前端核对寻址结果）\n"
        "- `task_id`：渲染任务 UUID，同步作为 WS `taskId` 和输出文件名后缀\n"
        "- `render_status: \"rendering\"`\n\n"
        "渲染进度通过 **WebSocket 事件总线**（`WS_UPDATE`）实时推送。\n\n"
        "**容错策略**：若所有 Beat 均寻址失败，返回 `422` 并给出具体原因，"
        "不会下发无效的渲染任务。"
    ),
)
def submit_dsl(
    payload: RenderDSLRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> DSLSubmitResponse:
    """
    Story DSL 三合一端点：解析 + 适配 + 后台渲染。

    同步部分（毫秒级，不阻塞响应）：
      1. 校验 payload（Pydantic 自动完成）
      2. DSLParserNode 执行双轨寻址 → CompilationPlan
      3. 前置校验：resolved_beats > 0
      4. 生成 task_id（UUID），注册 render_worker 至 BackgroundTasks
      5. 立即返回 202 + DSLSubmitResponse

    异步部分（BackgroundTasks 线程）：
      6. render_worker: compile_plan_to_timeline → WorkflowContext
      7. FFmpegCompositorNode.execute → FFmpeg 子进程渲染
      8. WS 事件总线推送 running / progress / completed / failed
    """
    is_blind = _is_blind_fission(payload)

    logger.info(
        "[routes_dsl] submit-dsl 请求 engine=%s beats=%d blind=%s aspect=%s duration=%ds",
        payload.engine_type,
        len(payload.timeline),
        is_blind,
        payload.aspect_ratio,
        payload.target_duration,
    )

    if not is_blind and not payload.timeline:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="timeline 不能为空，请至少提供一个 Beat 节点。",
        )

    plan: Optional[CompilationPlan] = None

    if is_blind:
        plan = CompilationPlan(
            engine_type=payload.engine_type,
            beats=[],
            unresolved_beats=[],
            summary=CompilationPlanSummary(
                total_beats=0,
                resolved_beats=0,
                unresolved_beats=0,
            ),
        )
        logger.info("[routes_dsl] 极速闭眼裂变：timeline 留空，DSL 解析推迟至 Worker 线程。")
    else:
        # ── Step 1: DSL 解析 → CompilationPlan ───────────────────────────
        try:
            dsl_payload = StoryDSLPayload(
                engine_type=payload.engine_type,
                timeline=payload.timeline,
                meta=payload.meta,
                user_hard_tags=payload.user_hard_tags,
            )
            parser = DSLParserNode(db)
            plan = parser.parse_and_resolve(dsl_payload)
        except Exception as exc:
            logger.exception("[routes_dsl] DSLParserNode 内部异常")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"DSL 解析引擎内部错误：{exc}",
            ) from exc

        logger.info(
            "[routes_dsl] 蓝图解析完成 resolved=%d/%d unresolved=%s",
            plan.summary.resolved_beats,
            plan.summary.total_beats,
            plan.unresolved_beats or "[]",
        )

        # ── Step 2: 前置校验 — 至少有一个可渲染的主视频 Beat ───────────────
        if plan.summary.resolved_beats == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "所有 Beat 寻址失败，无可渲染素材。"
                    f"未解析的 Beats：{plan.unresolved_beats}"
                ),
            )

    assert plan is not None

    # ── Step 3: 生成唯一 task_id，按 batch_size 选择 worker ──────────────
    task_id    = payload.session_id or str(uuid.uuid4())
    batch_size = payload.batch_size

    # 原始 DSL Payload（未执行寻址），下发给 Worker 实现运行时动态抽卡
    dsl_payload_for_worker: Optional[StoryDSLPayload] = None if is_blind else StoryDSLPayload(
        engine_type=payload.engine_type,
        timeline=payload.timeline,
        meta=payload.meta,
        user_hard_tags=payload.user_hard_tags,
    )

    _worker_kw: dict[str, Any] = {
        "blind_dsl": is_blind,
        "engine_type": payload.engine_type,
        "director_mode": payload.mode,
        "enable_tts": payload.enable_tts,
        "enable_subtitles": payload.enable_subtitles,
    }

    if batch_size > 1:
        background_tasks.add_task(
            render_batch_worker,
            dsl_payload_for_worker,
            task_id,
            payload.aspect_ratio, payload.target_duration, payload.tenant_id,
            payload.prompt, batch_size, payload.test_language,
            **_worker_kw,
        )
    else:
        background_tasks.add_task(
            render_worker,
            None,
            task_id,
            payload.aspect_ratio, payload.target_duration, payload.tenant_id,
            payload.prompt, 1, payload.test_language,
            None,
            False,
            **{**_worker_kw, "dsl_payload": dsl_payload_for_worker},
        )

    logger.info(
        "[routes_dsl] 渲染任务已下发 task_id=%s batch=%d blind=%s resolved=%d/%d",
        task_id, batch_size, is_blind,
        plan.summary.resolved_beats,
        plan.summary.total_beats,
    )

    # ── Step 4: 返回 CompilationPlan 快照 + 任务元数据 ─────────────────
    return DSLSubmitResponse(
        **plan.model_dump(),
        task_id=task_id,
        task_ids=[task_id],
        render_status="rendering",
        message=(
            f"渲染任务已下发（task_id={task_id[:8]}…，batch={batch_size}，"
            f"blind_dsl={is_blind}），全部完成后由事件总线推送含所有资产的 completed 事件。"
        ),
    )


# ================================================================== #
# POST /tasks/render-dsl  — 纯渲染触发端点  (Phase 5.1，保持不变)    #
# ================================================================== #

# ================================================================== #
# POST /tasks/submit-manual  - pure manual DSL submit endpoint
# ================================================================== #

@router.post(
    "/submit-manual",
    response_model=DSLSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Story DSL 手工编排渲染入口",
    description=(
        "接收前端手工编排好的 RenderDSLRequest，直接通过 DSLParserNode "
        "解析 CompilationPlan 并下发后台渲染。该端点不执行 blind fission "
        "判断，也不依赖 DirectorNode。"
    ),
)
def submit_manual(
    payload: RenderDSLRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> DSLSubmitResponse:
    logger.info(
        "[routes_dsl] submit-manual request engine=%s beats=%d aspect=%s duration=%ds",
        payload.engine_type,
        len(payload.timeline),
        payload.aspect_ratio,
        payload.target_duration,
    )

    if not payload.timeline:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="timeline cannot be empty for manual submit.",
        )

    try:
        dsl_payload = StoryDSLPayload(
            engine_type=payload.engine_type,
            timeline=payload.timeline,
            meta=payload.meta,
            user_hard_tags=payload.user_hard_tags,
        )
        parser = DSLParserNode(db)
        plan = parser.parse_and_resolve(dsl_payload)
    except Exception as exc:
        logger.exception("[routes_dsl] submit-manual DSLParserNode failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DSL parser failed: {exc}",
        ) from exc

    if plan.summary.resolved_beats == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No renderable beats were resolved. "
                f"Unresolved beats: {plan.unresolved_beats}"
            ),
        )

    task_id = payload.session_id or str(uuid.uuid4())
    batch_size = payload.batch_size
    worker_kwargs: dict[str, Any] = {
        "blind_dsl": False,
        "engine_type": payload.engine_type,
        "director_mode": payload.mode,
        "enable_tts": payload.enable_tts,
        "enable_subtitles": payload.enable_subtitles,
    }

    if batch_size > 1:
        background_tasks.add_task(
            render_batch_worker,
            dsl_payload,
            task_id,
            payload.aspect_ratio, payload.target_duration, payload.tenant_id,
            None, batch_size, payload.test_language,
            **{**worker_kwargs, "resolved_plan": plan},
        )
    else:
        background_tasks.add_task(
            render_worker,
            plan,
            task_id,
            payload.aspect_ratio, payload.target_duration, payload.tenant_id,
            None, 1, payload.test_language,
            None,
            False,
            **worker_kwargs,
            dsl_payload=dsl_payload,
        )

    logger.info(
        "[routes_dsl] submit-manual dispatched task_id=%s batch=%d resolved=%d/%d",
        task_id,
        batch_size,
        plan.summary.resolved_beats,
        plan.summary.total_beats,
    )

    return DSLSubmitResponse(
        **plan.model_dump(),
        task_id=task_id,
        task_ids=[task_id],
        render_status="rendering",
        message=(
            f"Manual render task dispatched (task_id={task_id[:8]}, "
            f"batch={batch_size})."
        ),
    )


@router.post(
    "/render-dsl",
    response_model=RenderDSLAck,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Story DSL 渲染触发（纯渲染，无蓝图快照）",
    description=(
        "接收带渲染配置的 DSL Payload，仅下发渲染任务并返回轻量 Ack。\n\n"
        "与 `submit-dsl` 的区别：响应体不含 CompilationPlan 蓝图快照，"
        "适用于前端已完成 Dry-run 核对、只需触发渲染的场景。\n\n"
        "渲染进度同样通过 **WebSocket 事件总线**（`WS_UPDATE`）实时推送。"
    ),
)
def render_dsl(
    payload: RenderDSLRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> RenderDSLAck:
    """
    Story DSL 纯渲染触发端点（共用 render_worker，与 submit-dsl 渲染逻辑一致）。
    """
    is_blind = _is_blind_fission(payload)

    logger.info(
        "[routes_dsl] render-dsl 请求 engine=%s beats=%d blind=%s aspect=%s duration=%ds",
        payload.engine_type,
        len(payload.timeline),
        is_blind,
        payload.aspect_ratio,
        payload.target_duration,
    )

    if not is_blind and not payload.timeline:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="timeline 不能为空，请至少提供一个 Beat 节点。",
        )

    plan: Optional[CompilationPlan] = None

    if is_blind:
        plan = CompilationPlan(
            engine_type=payload.engine_type,
            beats=[],
            unresolved_beats=[],
            summary=CompilationPlanSummary(
                total_beats=0,
                resolved_beats=0,
                unresolved_beats=0,
            ),
        )
    else:
        try:
            dsl_payload = StoryDSLPayload(
                engine_type=payload.engine_type,
                timeline=payload.timeline,
                meta=payload.meta,
                user_hard_tags=payload.user_hard_tags,
            )
            parser = DSLParserNode(db)
            plan = parser.parse_and_resolve(dsl_payload)
        except Exception as exc:
            logger.exception("[routes_dsl] DSLParserNode 内部异常")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"DSL 解析引擎内部错误：{exc}",
            ) from exc

        if plan.summary.resolved_beats == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "所有 Beat 寻址失败，无可渲染素材。"
                    f"未解析的 Beats：{plan.unresolved_beats}"
                ),
            )

    assert plan is not None

    task_id    = payload.session_id or str(uuid.uuid4())
    batch_size = payload.batch_size

    # 原始 DSL Payload（未执行寻址），下发给 Worker 实现运行时动态抽卡
    dsl_payload_for_worker: Optional[StoryDSLPayload] = None if is_blind else StoryDSLPayload(
        engine_type=payload.engine_type,
        timeline=payload.timeline,
        meta=payload.meta,
        user_hard_tags=payload.user_hard_tags,
    )

    _worker_kw: dict[str, Any] = {
        "blind_dsl": is_blind,
        "engine_type": payload.engine_type,
        "director_mode": payload.mode,
        "enable_tts": payload.enable_tts,
        "enable_subtitles": payload.enable_subtitles,
    }

    if batch_size > 1:
        background_tasks.add_task(
            render_batch_worker,
            dsl_payload_for_worker,
            task_id,
            payload.aspect_ratio, payload.target_duration, payload.tenant_id,
            payload.prompt, batch_size, payload.test_language,
            **_worker_kw,
        )
    else:
        background_tasks.add_task(
            render_worker,
            None,
            task_id,
            payload.aspect_ratio, payload.target_duration, payload.tenant_id,
            payload.prompt, 1, payload.test_language,
            None,
            False,
            **{**_worker_kw, "dsl_payload": dsl_payload_for_worker},
        )

    logger.info(
        "[routes_dsl] render-dsl 渲染已下发 task_id=%s batch=%d blind=%s resolved=%d/%d",
        task_id, batch_size, is_blind,
        plan.summary.resolved_beats,
        plan.summary.total_beats,
    )

    return RenderDSLAck(
        session_id=task_id,
        status="processing",
        message=(
            f"渲染任务已下发（batch={batch_size}，blind_dsl={is_blind}），"
            "请通过 WebSocket 事件总线监听进度。"
        ),
    )
