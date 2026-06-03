"""
src/api/routes_history.py
———————————————————
ClipFlow — 历史记录查询 API。

端点列表：
  GET /history/          → 全量历史（倒序）
  GET /tasks/today       → 今日任务（今日态水合，用于 QueueView 刷新恢复）
"""
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .database import get_db
from .models import TaskHistory

router      = APIRouter(prefix="/history", tags=["History"])
tasks_router = APIRouter(prefix="/tasks",   tags=["Tasks"])


# ── 公共序列化辅助 ─────────────────────────────────────────────────────────────
def _serialize_record(record: TaskHistory) -> dict:
    return {
        "id":             record.id,
        "task_id":        record.task_id,
        "prompt":         record.prompt,
        "batch_size":     record.batch_size,
        "duration":       record.duration,
        "output_assets":  record.output_assets or [],
        "prompt_details": record.prompt_details or None,
        "created_at":     record.created_at.isoformat() if record.created_at else None,
    }


# ================================================================== #
# GET /api/v1/history/                                                #
# ================================================================== #
@router.get(
    "/",
    summary="查询历史记录",
    description="按照创建时间倒序返回所有的成功任务记录。"
)
def get_history(db: Session = Depends(get_db)):
    records = db.query(TaskHistory).order_by(TaskHistory.created_at.desc()).all()
    return [_serialize_record(r) for r in records]


# ================================================================== #
# GET /api/v1/tasks/today                                             #
# ================================================================== #
@tasks_router.get(
    "/today",
    summary="今日任务列表",
    description=(
        "返回今日（UTC 整天）该租户的所有完成任务记录，含 output_assets JSON。\n\n"
        "用于 QueueView 的今日态水合：页面刷新后前端调用此接口，"
        "将今日完成任务灌入 useQueueStore 的 completedTasks，避免刷新丢失数据。"
    ),
)
def get_tasks_today(db: Session = Depends(get_db)) -> list:
    # 以 UTC 今日 00:00:00 ~ 明日 00:00:00 为范围
    now_utc     = datetime.now(timezone.utc)
    day_start   = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)
    day_end     = day_start + timedelta(days=1)

    records = (
        db.query(TaskHistory)
        .filter(
            TaskHistory.created_at >= day_start,
            TaskHistory.created_at <  day_end,
        )
        .order_by(TaskHistory.created_at.desc())
        .all()
    )
    return [_serialize_record(r) for r in records]
