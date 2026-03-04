"""
src/api/services.py
———————————————————
矩阵任务执行服务层。

职责：
  - 作为 FastAPI BackgroundTask 的入口，将矩阵生成任务异步化
  - 管理任务生命周期：pending → processing → completed | failed
  - 为每个生成的变体视频计算 MD5 file_hash，写入 video_assets 表
  - 估算任务成本（LLM Token + TTS 时长）并写入 video_tasks 表

关键设计：
  - 本模块函数「不」接收外部 Session，内部独立创建 SessionLocal()
    → 避免 FastAPI 请求 Session 与后台线程共享导致的 SQLAlchemy 状态污染
  - ProcessPoolExecutor 由 run_matrix_factory 内部管理，此层仅做结果收集
"""

from __future__ import annotations

import hashlib
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Optional

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
    task_id:    int,
    session_id: str,
    prompt:     str,
    batch_size: int,
) -> None:
    """
    矩阵批量生成后台任务。

    此函数运行于 FastAPI BackgroundTasks 线程中（非子进程）。
    内部调用 run_matrix_factory，后者负责 ProcessPoolExecutor 调度。

    Args:
        task_id:    video_tasks 表的主键（用于回写执行结果）
        session_id: 父任务的 session_id（日志追踪用）
        prompt:     剧本提示词
        batch_size: 矩阵变体数量
    """
    # ── 必须在函数内部导入，避免 FastAPI 启动时触发多进程相关副作用 ──
    from dotenv import load_dotenv
    load_dotenv()

    from run_matrix_factory import run_matrix_factory          # 复用现有引擎，零重写
    from src.api.database import SessionLocal
    from src.api.models import VideoTask, VideoAsset

    db = SessionLocal()

    try:
        # 1. 标记任务为 processing
        task: Optional[VideoTask] = db.get(VideoTask, task_id)
        if task is None:
            print(f"[services] ⚠️  task_id={task_id} 在数据库中不存在，终止。")
            return

        task.status = "processing"
        db.commit()
        print(f"[services] 🚀 task_id={task_id} | session={session_id} | 开始运行矩阵工厂…")

        # 2. 运行矩阵工厂（内部多进程；此线程阻塞等待全部完成）
        results: list[dict] = run_matrix_factory(
            batch_size=batch_size,
            user_prompt=prompt,
        )

        # 3. 统计成本 & 收集资产
        total_tokens: int   = 0
        total_tts_sec: float = 0.0
        asset_rows: list[VideoAsset] = []

        for result in results:
            if not result.get("success"):
                continue

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
                    perceptual_hash = "",       # Phase 5.3 imagehash 集成后填充
                    created_at      = _now(),
                )
                asset_rows.append(asset)
                print(f"[services]   📦 [{lang}] {file_path}  MD5={fh[:8]}…")

            # 读取成本字段（如有）
            total_tokens  += result.get("llm_tokens_used",      0) or 0
            total_tts_sec += result.get("tts_duration_seconds", 0.0) or 0.0

        # 4. 批量写入资产指纹
        if asset_rows:
            db.add_all(asset_rows)

        # 5. 更新任务状态 & 成本
        task.status               = "completed"
        task.finished_at          = _now()
        task.llm_tokens_used      = total_tokens
        task.tts_duration_seconds = total_tts_sec
        task.estimated_cost_usd   = _estimate_cost(total_tokens, total_tts_sec)
        db.commit()

        print(
            f"[services] ✅ task_id={task_id} 完成。"
            f"  资产数={len(asset_rows)}  "
            f"  预估成本=${task.estimated_cost_usd:.4f} USD"
        )

    except Exception:
        tb = traceback.format_exc()
        print(f"[services] ❌ task_id={task_id} 执行异常:\n{tb}")
        try:
            task = db.get(VideoTask, task_id)
            if task:
                task.status      = "failed"
                task.finished_at = _now()
                db.commit()
        except Exception:
            pass  # DB 本身也出问题时静默处理，避免无限递归

    finally:
        db.close()
