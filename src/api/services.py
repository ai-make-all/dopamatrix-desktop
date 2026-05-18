"""
src/api/services.py
———————————————————
矩阵任务执行服务层。

职责：
  - 作为 FastAPI BackgroundTask 的入口，将矩阵生成任务异步化
  - 管理任务生命周期：queued → processing → completed | failed
  - 为每个生成的变体视频计算 MD5 file_hash，写入 video_assets 表
  - 估算任务成本（LLM Token + TTS 时长）并写入 video_tasks 表
  - 任务终态后直接调用 reporting.notify_task_result 推送 Telegram 战报

关键设计：
  - 本模块函数接收 tenant_id，内部通过 get_tenant_engine(tenant_id) 创建专属 Session
    → 避免 FastAPI 请求 Session 与后台线程共享；同时实现多租户物理 DB 隔离
  - ProcessPoolExecutor 由 run_matrix_factory 内部管理，此层仅做结果收集
  - 战报推送为进程内直接方法调用（无 HTTP 跳转），失败绝不影响任务状态和主流程
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

from src.core.logger import logger
from src.services.reporting import notify_task_result
from src.api.ws_manager import manager as ws_manager

# ── 确保子进程输出兼容 Windows GBK 终端 ──────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ------------------------------------------------------------------ #
# 成本费率常量（可通过 .env 覆盖）                                      #
# ------------------------------------------------------------------ #
_LLM_COST_PER_TOKEN: float = float(os.getenv("LLM_COST_PER_TOKEN", "0.000002"))   # USD/token
_TTS_COST_PER_SEC:   float = float(os.getenv("TTS_COST_PER_SEC",   "0.000016"))   # USD/sec


# ------------------------------------------------------------------ #
# 工具函数                                                              #
# ------------------------------------------------------------------ #

def _md5_file(path: str) -> str:
    """计算文件的 MD5 十六进制哈希值；文件不存在时返回空字符串。"""
    if not os.path.isfile(path):
        return ""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _estimate_cost(tokens: int, tts_seconds: float) -> float:
    return round(tokens * _LLM_COST_PER_TOKEN + tts_seconds * _TTS_COST_PER_SEC, 6)


# ------------------------------------------------------------------ #
# 核心后台任务函数                                                       #
# ------------------------------------------------------------------ #

def run_matrix_job(
    task_id:           int,
    session_id:        str,
    prompt:            str,
    batch_size:        int,
    aspect_ratio:      str = "9:16",
    test_language:     str = "en",
    target_duration:   int = 15,
    output_dir:        Optional[str] = None,
    webhook_url:       Optional[str] = None,
    client_payload:    Optional[dict] = None,
    tenant_id:         str = "default",
    script_mode:       str = "auto",
) -> None:
    """
    矩阵批量生成后台任务。

    生命周期：queued → processing → completed | failed
    任务终态后直接调用 reporting.notify_task_result 向 Telegram 群推送战报。

    Args:
        task_id:            video_tasks 表的主键
        session_id:         日志追踪用
        prompt:             剧本提示词
        batch_size:         矩阵变体数量
        aspect_ratio:       画幅比例
        test_language:      测试语言（仅生成该语种的 TTS+字幕+变体）
        target_duration:    目标视频时长（秒），固定枚举：15 | 30 | 60
        webhook_url:        保留参数，暂未使用（预留外部回调扩展口）
        client_payload:     调用方透传上下文，战报中原样展示触发用户信息（可选）
    """
    # load_env() 在 main.py 启动时已全局加载一次；此处补充调用确保
    # 直接调用本函数（如测试场景）时也能正确获取环境变量。
    from src.utils.env_utils import load_env
    load_env()

    from run_matrix_factory import run_matrix_factory
    from src.api.database import get_tenant_engine
    from src.api.models import VideoTask, VideoAsset, LocalAsset, TaskHistory
    from sqlalchemy.orm import sessionmaker

    base_url = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

    engine = get_tenant_engine(tenant_id)
    TenantSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TenantSessionLocal()
    start_time = time.time()

    # 用于 Webhook 的终态变量（在 finally 块使用）
    _final_status:   str        = "failed"
    _webhook_assets: list[dict] = []
    _cost_usd:       float      = 0.0

    try:
        # 1. 标记任务为 processing
        task: Optional[VideoTask] = db.get(VideoTask, task_id)
        if task is None:
            logger.warning(f"[services] task_id={task_id} 在数据库中不存在，终止。")
            return

        task.status = "processing"
        db.commit()
        logger.info(
            f"[services] task_id={task_id} | session={session_id} "
            f"| lang={test_language} | 开始运行矩阵工厂…"
        )

        # ── WS 广播①：任务开始运行 ────────────────────────────────────────
        # 状态映射：后端 "processing" → 前端 TaskStatus "running"
        # startTime 使用毫秒级 Unix 时间戳，与前端 QueueTask.startTime 对齐。
        ws_manager.broadcast_sync(
            ws_manager.make_envelope(
                "WS_UPDATE",
                {
                    "taskId":    str(task_id),
                    "status":    "running",
                    "prompt":    prompt,
                    "startTime": int(start_time * 1000),
                },
            )
        )

        # 2. 运行矩阵工厂（内部多进程；此线程阻塞等待全部完成）
        results: list[dict] = run_matrix_factory(
            batch_size=batch_size,
            user_prompt=prompt,
            aspect_ratio=aspect_ratio,
            test_language=test_language,
            target_duration=target_duration,
            output_dir=output_dir,
            script_mode=script_mode,
            tenant_id=tenant_id,
        )

        # 3. 统计成本 & 收集资产
        total_tokens:   int   = 0
        total_tts_sec:  float = 0.0
        asset_rows: list[VideoAsset] = []
        used_asset_ids: list[int] = []
        history_assets: list[dict] = [] # 用于存入 TaskHistory.output_assets

        for result in results:
            if not result.get("success"):
                # 将 worker 的失败原因写入日志文件，便于打包后排查（print 在 --windowed 模式下无效）
                logger.error(
                    f"[services] task_id={task_id} worker session={result.get('session_id', '?')} "
                    f"失败: {result.get('error', 'unknown')} | "
                    f"traceback: {result.get('traceback', '')[:500]}"
                )
                continue

            # Only append used assets for successful result variations to prevent false fatigue deductions
            used_asset_ids.extend(result.get("used_asset_ids", []))

            variants: dict[str, str] = result.get("assets", {}).get("variants", {})

            # 每个 worker 的所有语言变体共用同一份 manifest（脚本/BGM 相同，只有语音不同）
            manifest_json: str = json.dumps(
                result.get("video_manifest") or {},
                ensure_ascii=False,
            )

            for lang, file_path in variants.items():
                if not file_path:
                    continue

                fh = _md5_file(file_path)
                asset = VideoAsset(
                    task_id         = task_id,
                    file_path       = file_path,
                    language        = lang,
                    file_hash       = fh,
                    perceptual_hash = "",
                    manifest_data   = manifest_json,
                    created_at      = _now(),
                )
                asset_rows.append(asset)
                logger.info(f"[services] [{lang}] {file_path}  MD5={fh[:8]}…")

            total_tokens  += result.get("llm_tokens_used",      0) or 0
            total_tts_sec += result.get("tts_duration_seconds", 0.0) or 0.0

        # 4. 批量写入资产指纹，flush 后取得自增主键以拼装绝对下载链接
        if asset_rows:
            db.add_all(asset_rows)
            db.flush()  # 推入 DB 生成 asset.id，暂不提交事务
            for asset in asset_rows:
                history_assets.append({
                    "path": asset.file_path,
                    "hash": asset.file_hash,
                    "download_url": f"{base_url}/api/v1/tasks/assets/{asset.id}/download",
                })

        # 4.5. 疲劳值反写闭环（事务一致性保护）
        if used_asset_ids:
            # 去重
            unique_ids = list(set(used_asset_ids))
            local_assets = (
                db.query(LocalAsset)
                .filter(LocalAsset.id.in_(unique_ids), LocalAsset.is_deleted.is_(False))
                .all()
            )
            for la in local_assets:
                # 每个 ID 的实际使用次数（因为同一素材在多进程可能被使用多次）
                usage_increment = used_asset_ids.count(la.id)
                la.usage_count += usage_increment
                la.last_used_at = _now()
                # 满 10 次则疲劳耗竭
                if la.usage_count >= 10:
                    la.is_exhausted = True
            
            logger.info(f"[services] 疲劳值闭环：更新了 {len(local_assets)} 个有效任务消耗素材。")

        # 4.6 写入 TaskHistory 记录历史
        if history_assets:
            # 使用精准的系统时间差，保留 1 位小数
            real_duration = round(time.time() - start_time, 1)
            history_record = TaskHistory(
                task_id=session_id, # 根据业务需求，通常用可以对外暴露的 session_id 或 UUID
                prompt=prompt,
                batch_size=batch_size,
                duration=real_duration, 
                output_assets=history_assets,
                created_at=_now()
            )
            db.add(history_record)
            logger.info("[services] 往 task_history 表写入了 1 条历史归档记录")

        # 5. 更新任务状态 & 成本
        cost = _estimate_cost(total_tokens, total_tts_sec)
        task.status               = "completed"
        task.finished_at          = _now()
        task.llm_tokens_used      = total_tokens
        task.tts_duration_seconds = total_tts_sec
        task.estimated_cost_usd   = cost
        db.commit()

        _final_status   = "completed"
        _webhook_assets = history_assets   # [{"path": ..., "hash": ...}, ...]
        _cost_usd       = cost

        logger.info(
            f"任务 {task_id} 执行成功，总耗时: {time.time() - start_time:.2f} 秒  "
            f"资产数={len(_webhook_assets)}  预估成本=${_cost_usd:.4f} USD"
        )

        # ── WS 广播②：任务完成 ───────────────────────────────────────────
        # assets 字段携带所有已生成视频的路径与哈希，与前端 QueueTask.assets 结构对齐：
        #   Array<{ file_path: string; file_hash: string }>
        ws_manager.broadcast_sync(
            ws_manager.make_envelope(
                "WS_UPDATE",
                {
                    "taskId": str(task_id),
                    "status": "completed",
                    "assets": [
                        {"file_path": a.file_path, "file_hash": a.file_hash}
                        for a in asset_rows
                    ],
                },
            )
        )

    except Exception as e:
        logger.exception(f"任务 {task_id} 发生未知崩溃！耗时: {time.time() - start_time:.2f} 秒")
        try:
            task = db.get(VideoTask, task_id)
            if task:
                task.status      = "failed"
                task.finished_at = _now()
                db.commit()
        except Exception:
            pass  # DB 本身也出问题时静默处理

        # ── WS 广播③：任务失败 ───────────────────────────────────────────
        # 即使 DB 操作失败，也尽力向前端推送失败状态，确保 UI 不会无限 pending。
        try:
            ws_manager.broadcast_sync(
                ws_manager.make_envelope(
                    "WS_UPDATE",
                    {
                        "taskId": str(task_id),
                        "status": "failed",
                    },
                )
            )
        except Exception as ws_exc:
            logger.warning(f"[services] task_id={task_id} WS 失败广播发送异常（已忽略）: {ws_exc}")

    finally:
        db.close()

        # 6. 直接调用战报播报服务（进程内方法调用，无 HTTP 开销）
        # run_matrix_job 运行于 FastAPI 线程池 worker，无事件循环，asyncio.run() 安全。
        _report_payload: dict[str, Any] = {
            "task_id":            task_id,
            "session_id":         session_id,
            "status":             _final_status,
            "assets":             _webhook_assets,
            "estimated_cost_usd": round(_cost_usd, 6),
            "client_payload":     client_payload,
        }
        try:
            asyncio.run(notify_task_result(_report_payload))
        except Exception as exc:
            logger.warning(f"[Reporting] task_id={task_id} 战报推送失败（已忽略）: {exc}")
