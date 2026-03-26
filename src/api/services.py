"""
src/api/services.py
———————————————————
矩阵任务执行服务层。

职责：
  - 作为 FastAPI BackgroundTask 的入口，将矩阵生成任务异步化
  - 管理任务生命周期：queued → processing → completed | failed
  - 为每个生成的变体视频计算 MD5 file_hash，写入 video_assets 表
  - 估算任务成本（LLM Token + TTS 时长）并写入 video_tasks 表
  - 任务终态后发射 Webhook（WEBHOOK_URL 环境变量控制，可选）

关键设计：
  - 本模块函数「不」接收外部 Session，内部独立创建 SessionLocal()
    → 避免 FastAPI 请求 Session 与后台线程共享导致的 SQLAlchemy 状态污染
  - ProcessPoolExecutor 由 run_matrix_factory 内部管理，此层仅做结果收集
  - Webhook 发射使用 httpx 同步客户端（在后台线程中调用），3 秒超时，
    发送失败绝不影响任务状态和主流程
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.logger import logger

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
# Webhook 发射器 V2（tenacity 指数退避重试，防爆型）                    #
# ------------------------------------------------------------------ #

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def _send_webhook_async(webhook_url: str, payload: dict) -> None:
    """
    异步 POST 结案报告，带 tenacity 指数退避重试。

    重试策略：最多 3 次，首次等待 2s，指数增长，最长 10s。
    任何 HTTP 4xx/5xx 均会触发 raise_for_status → 触发重试。
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        logger.info(f"[webhook] 正在向 {webhook_url} 发送结案报告…")
        response = await client.post(webhook_url, json=payload)
        response.raise_for_status()
        logger.info(f"[webhook] Webhook 发送成功！HTTP {response.status_code}")


def _fire_webhook(
    task_id:        int,
    session_id:     str,
    final_status:   str,            # "completed" | "failed"
    assets:         list[dict],     # [{"path": ..., "hash": ...}, ...]
    cost_usd:       float = 0.0,
    webhook_url:    Optional[str] = None,
    client_payload: Optional[dict] = None,
) -> None:
    """
    同步包装器：组装结案报告并调用异步发送函数。

    URL 优先级：per-task webhook_url > 环境变量 WEBHOOK_URL。
    任何网络/重试耗尽异常均被捕获，绝不影响调用方。
    """
    url: str = (webhook_url or "").strip() or os.getenv("WEBHOOK_URL", "").strip()
    if not url:
        return  # 未配置，静默跳过

    report: dict[str, Any] = {
        "task_id":            task_id,
        "session_id":         session_id,
        "status":             final_status,
        "assets":             assets,
        "estimated_cost_usd": round(cost_usd, 6),
        "client_payload":     client_payload,
    }

    try:
        # run_matrix_job 是同步函数，运行于 FastAPI 的线程池 worker 中，
        # 不存在已运行的事件循环，可以安全使用 asyncio.run()。
        asyncio.run(_send_webhook_async(url, report))
    except Exception as exc:
        # 重试 3 次后仍失败 → 记录警告，绝不崩溃主流程
        logger.warning(
            f"[webhook] task_id={task_id} Webhook 最终发送失败（已忽略）: {exc}"
        )


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
) -> None:
    """
    矩阵批量生成后台任务。

    生命周期：queued → processing → completed | failed
    任务终态后自动触发 Webhook（per-task webhook_url 优先，回退 WEBHOOK_URL 环境变量）。

    Args:
        task_id:            video_tasks 表的主键
        session_id:         日志追踪用
        prompt:             剧本提示词
        batch_size:         矩阵变体数量
        aspect_ratio:       画幅比例
        test_language:      测试语言（仅生成该语种的 TTS+字幕+变体）
        target_duration:    目标视频时长（秒），固定枚举：15 | 30 | 60
        webhook_url:        渲染完成后的结案报告推送地址（可选）
        client_payload:     调用方透传上下文，在 Webhook 中原样返回（可选）
    """
    # load_env() 在 main.py 启动时已全局加载一次；此处补充调用确保
    # 直接调用本函数（如测试场景）时也能正确获取环境变量。
    from src.utils.env_utils import load_env
    load_env()

    from run_matrix_factory import run_matrix_factory
    from src.api.database import SessionLocal
    from src.api.models import VideoTask, VideoAsset, LocalAsset, TaskHistory

    base_url = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

    db = SessionLocal()
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

        # 2. 运行矩阵工厂（内部多进程；此线程阻塞等待全部完成）
        results: list[dict] = run_matrix_factory(
            batch_size=batch_size,
            user_prompt=prompt,
            aspect_ratio=aspect_ratio,
            test_language=test_language,
            target_duration=target_duration,
            output_dir=output_dir,
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
            local_assets = db.query(LocalAsset).filter(LocalAsset.id.in_(unique_ids)).all()
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

    finally:
        db.close()

        # 6. 发射 Webhook（任务终态后，tenacity 重试，防爆，不崩溃）
        _fire_webhook(
            task_id=task_id,
            session_id=session_id,
            final_status=_final_status,
            assets=_webhook_assets,
            cost_usd=_cost_usd,
            webhook_url=webhook_url,
            client_payload=client_payload,
        )
