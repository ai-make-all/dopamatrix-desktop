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
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session, sessionmaker

from .database import get_db, get_tenant_engine
from .dsl_adapter import compile_plan_to_timeline
from src.api.ws_manager import manager as ws_manager
from .dsl_parser import DSLParserNode
from .models import LocalAsset
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


def _is_blind_fission(payload: RenderDSLRequest) -> bool:
    """极速闭眼裂变：batch≥1 + 非空 prompt + 空 timeline。"""
    return (
        payload.batch_size >= 1
        and bool(payload.prompt and payload.prompt.strip())
        and len(payload.timeline) == 0
    )


def _script_data_has_scenes(data: Optional[dict]) -> bool:
    if not data or not isinstance(data, dict):
        return False
    scenes = data.get("scenes")
    return isinstance(scenes, list) and len(scenes) > 0


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
    script_data_prefetch: Optional[dict] = None,
    director_mode: str = "auto",
    dsl_payload: Optional[StoryDSLPayload] = None,
    enable_tts: bool = True,
    enable_subtitles: bool = True,
) -> list[dict]:
    """
    后台渲染主 Worker（Phase 9.2 导演中枢 + 双离合台词 + 闭眼裂变）。

    blind_dsl=True 时在本线程内由 DirectorNode 生成 timeline/script_data，
    再经 DSLParserNode 编译为 CompilationPlan；各矩阵子线程独立调用大模型，
    利用采样随机性产生差异化文案与打标。

    混合模态（prompt 非空）：
      离合器 A — 若 script_data_prefetch 含有效 scenes，则跳过导演 LLM 文案，
                 直接写入 context 供 TTS；
      离合器 B — 否则调用 DirectorNode.execute，由 LLM 写入 script_data。

    纯积木模式（prompt 为空）：注入 default 变体，仅合流 BGM/SFX。
    """
    logger.info(
        "[render_worker] 开始渲染 task_id=%s aspect=%s duration=%ds tenant=%s mode=%s",
        task_id, aspect_ratio, target_duration, tenant_id,
        "hybrid" if prompt else "dsl-only",
    )

    collected_assets: list[dict] = []

    try:
        working_plan: Optional[CompilationPlan] = plan
        blueprint_script: Optional[dict] = None

        if blind_dsl:
            if not prompt or not str(prompt).strip():
                logger.error(
                    "[render_worker] blind_dsl 需要非空 prompt，task_id=%s", task_id,
                )
                return []
            langs = [test_language] if test_language else ["en"]
            director = DirectorNode()
            bp = director.draft_blueprint(
                str(prompt).strip(),
                director_mode,
                target_duration,
                langs,
                llm_temperature=0.92,
            )
            if _script_data_has_scenes(script_data_prefetch):
                bp["script_data"] = script_data_prefetch  # type: ignore[assignment]
                logger.info(
                    "[render_worker] task_id=%s 离合器 A：沿用前端 script_data，"
                    "导演线程仅负责 timeline 寻址",
                    task_id,
                )
            else:
                logger.info(
                    "[render_worker] task_id=%s 离合器 B：导演线程生成 timeline + script_data",
                    task_id,
                )
            blueprint_script = bp.get("script_data")

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

            dsl_payload = StoryDSLPayload(engine_type=engine_type, timeline=beat_nodes)
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
                "[render_worker] task_id=%s 混合编排：导演/台词 → TTS → Subtitle → Compositor",
                task_id,
            )

            if blind_dsl:
                context.set_asset("script_data", blueprint_script or {})
            elif _script_data_has_scenes(script_data_prefetch):
                context.set_asset("script_data", script_data_prefetch)
                logger.info(
                    "[render_worker] task_id=%s 离合器 A：使用请求体 script_data，"
                    "跳过大模型文案",
                    task_id,
                )
            else:
                context.set_asset("script", prompt)
                DirectorNode().execute(context)

            # TTSNode 读取 script_data，将 MP3 + VTT 写入 context.variants[lang]
            if enable_tts:
                TTSNode().execute(context)
            else:
                logger.info(
                    "[render_worker] task_id=%s enable_tts=False，跳过 TTS 播音节点，"
                    "仅保留 BGM 音轨",
                    task_id,
                )

            # ── TranslationBridge（内联）：聚合旁白文本 → SubtitleNode 降级兜底 ──
            # SubtitleNode 精准模式依赖 vtt_path（TTSNode 已写入），但若 VTT 为空
            # 则降级读取 context.config["translations"] + subtitle_start/end。
            # 此段逻辑与 run_matrix_factory.py 中的 TranslationBridgeNode 保持一致。
            if enable_subtitles:
                script_data: dict = context.get_asset("script_data") or {}
                _translations: dict = {}
                _total_duration: float = 0.0
                for _scene in script_data.get("scenes", []):
                    _total_duration += float(_scene.get("duration", 0))
                    for _lang, _text in _scene.get("narrations", {}).items():
                        if _text and _text.strip():
                            _translations.setdefault(_lang, []).append(_text.strip())
                context.config["translations"] = {
                    lang: "\n".join(lines) for lang, lines in _translations.items()
                }
                context.config["subtitle_start"] = 0.0
                context.config["subtitle_end"] = _total_duration if _total_duration > 0 else 5.0
                logger.debug(
                    "[render_worker] task_id=%s TranslationBridge: langs=%s subtitle_end=%.1fs",
                    task_id,
                    list(context.config["translations"].keys()),
                    context.config["subtitle_end"],
                )
                # SubtitleNode：精准模式（VTT → 逐句 ASS）或降级模式（单 Dialogue）
                # 写入 context.variants[lang]["subtitle_ass"]
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

        # ── 5. 引擎点火 ────────────────────────────────────────────────
        render_ok = _run_compositor(FFmpegCompositorNode(), context)

        # ── 6. 收集输出资产 & 疲劳值回写 ──────────────────────────────────
        if render_ok:
            # 从 context.variants 读取每个语种的最终变体路径
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
                    })
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
    script_data_prefetch: Optional[dict] = None,
    director_mode: str = "auto",
    enable_tts: bool = True,
    enable_subtitles: bool = True,
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
                None,    # plan：由 render_worker 内部动态解析，此处不固化蓝图
                task_id,
                aspect_ratio, target_duration, tenant_id,
                prompt, batch_size, test_language,
                sid,   # file_sid: 唯一文件名后缀
                True,  # suppress_completed_ws
                blind_dsl=blind_dsl,
                engine_type=engine_type,
                script_data_prefetch=script_data_prefetch,
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
def draft_blueprint_endpoint(body: DraftBlueprintRequest) -> dict[str, Any]:
    return DirectorNode().draft_blueprint(
        body.prompt,
        body.mode,
        body.duration,
        body.langs,
        available_tags=body.available_tags,
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
        user_hard_tags=payload.user_hard_tags,
    )

    _worker_kw: dict[str, Any] = {
        "blind_dsl": is_blind,
        "engine_type": payload.engine_type,
        "script_data_prefetch": payload.script_data,
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
        user_hard_tags=payload.user_hard_tags,
    )

    _worker_kw: dict[str, Any] = {
        "blind_dsl": is_blind,
        "engine_type": payload.engine_type,
        "script_data_prefetch": payload.script_data,
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
