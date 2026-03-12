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
# Webhook 发射器（防爆型，永不崩溃主流程）                              #
# ------------------------------------------------------------------ #

def _fire_webhook(
    task_id:      int,
    session_id:   str,
    final_status: str,           # "completed" | "failed"
    test_language: str = "en",
    assets_count:  int = 0,
    cost_usd:      float = 0.0,
) -> None:
    """
    向 WEBHOOK_URL 发送任务终态通知。

    设计原则：
      - WEBHOOK_URL 未配置 → 直接跳过，不打日志（减少噪音）
      - 任何网络/超时错误 → 仅打印警告，绝不 raise，绝不影响调用方
      - 超时 3 秒（优先用 httpx；若未安装则 fallback 到 urllib）
      - Payload 紧凑：task_id / session_id / status / test_language /
                       assets_count / estimated_cost_usd
    """
    webhook_url: str = os.getenv("WEBHOOK_URL", "").strip()
    if not webhook_url:
        return  # 未配置，静默跳过

    payload = {
        "task_id":            task_id,
        "session_id":         session_id,
        "status":             final_status,
        "test_language":      test_language,
        "assets_count":       assets_count,
        "estimated_cost_usd": round(cost_usd, 6),
    }

    try:
        # ── 优先使用 httpx（项目已有依赖）──────────────────────────────
        import httpx
        with httpx.Client(timeout=3.0) as client:
            resp = client.post(webhook_url, json=payload)
        print(
            f"[webhook] 📡 task_id={task_id} → {webhook_url} "
            f"status={resp.status_code}"
        )

    except ImportError:
        # ── Fallback: 标准库 urllib（httpx 未安装时）──────────────────
        import json
        import urllib.request
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                print(
                    f"[webhook] 📡 task_id={task_id} → {webhook_url} "
                    f"status={resp.status}"
                )
        except Exception as exc:
            print(f"[webhook] ⚠️  urllib 发送失败（已忽略）: {exc}")

    except Exception as exc:
        # ── 任意其他异常（网络超时、DNS 失败等）→ 仅打印，不崩溃 ─────
        print(f"[webhook] ⚠️  task_id={task_id} Webhook 发送失败（已忽略）: {exc}")


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
) -> None:
    """
    矩阵批量生成后台任务。

    生命周期：queued → processing → completed | failed
    任务终态后自动触发 Webhook（若已配置 WEBHOOK_URL）。

    Args:
        task_id:            video_tasks 表的主键
        session_id:         日志追踪用
        prompt:             剧本提示词
        batch_size:         矩阵变体数量
        aspect_ratio:       画幅比例
        test_language:      测试语言（仅生成该语种的 TTS+字幕+变体）
        target_duration:    目标视频时长（秒），固定枚举：15 | 30 | 60
    """
    # ── 必须在函数内部导入，避免 FastAPI 启动时触发多进程相关副作用 ──
    from dotenv import load_dotenv
    load_dotenv()

    from run_matrix_factory import run_matrix_factory
    from src.api.database import SessionLocal
    from src.api.models import VideoTask, VideoAsset, LocalAsset, TaskHistory
    import time  # 引入 time 模块以计算精准耗时

    db = SessionLocal()
    start_time = time.time() # 记录任务真实开始时间

    # 用于 Webhook 的终态变量（在 finally 块使用）
    _final_status:  str   = "failed"
    _assets_count:  int   = 0
    _cost_usd:      float = 0.0

    try:
        # 1. 标记任务为 processing
        task: Optional[VideoTask] = db.get(VideoTask, task_id)
        if task is None:
            print(f"[services] ⚠️  task_id={task_id} 在数据库中不存在，终止。")
            return

        task.status = "processing"
        db.commit()
        print(
            f"[services] 🚀 task_id={task_id} | session={session_id} "
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
                history_assets.append({"path": file_path, "hash": fh})
                print(f"[services]   📦 [{lang}] {file_path}  MD5={fh[:8]}…")

            total_tokens  += result.get("llm_tokens_used",      0) or 0
            total_tts_sec += result.get("tts_duration_seconds", 0.0) or 0.0

        # 4. 批量写入资产指纹
        if asset_rows:
            db.add_all(asset_rows)

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
            
            print(f"[services] 🔄 疲劳值闭环：更新了 {len(local_assets)} 个有效任务消耗素材。")

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
            print(f"[services] 🕒 往 task_history 表写入了 1 条历史归档记录")

        # 5. 更新任务状态 & 成本
        cost = _estimate_cost(total_tokens, total_tts_sec)
        task.status               = "completed"
        task.finished_at          = _now()
        task.llm_tokens_used      = total_tokens
        task.tts_duration_seconds = total_tts_sec
        task.estimated_cost_usd   = cost
        db.commit()

        _final_status = "completed"
        _assets_count = len(asset_rows)
        _cost_usd     = cost

        print(
            f"[services] ✅ task_id={task_id} 完成。"
            f"  资产数={_assets_count}  "
            f"  预估成本=${_cost_usd:.4f} USD"
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
            pass  # DB 本身也出问题时静默处理

    finally:
        db.close()

        # 6. 发射 Webhook（任务终态后，防爆，不阻塞，不崩溃）
        _fire_webhook(
            task_id=task_id,
            session_id=session_id,
            final_status=_final_status,
            test_language=test_language,
            assets_count=_assets_count,
            cost_usd=_cost_usd,
        )
