"""
src/api/routes_history.py
———————————————————
ClipFlow — 历史记录查询 API。
"""
from typing import List, Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .database import get_db
from .models import TaskHistory

router = APIRouter(prefix="/history", tags=["History"])

@router.get(
    "/",
    summary="查询历史记录",
    description="按照创建时间倒序返回所有的成功任务记录。"
)
def get_history(db: Session = Depends(get_db)):
    """返回 TaskHistory 列表"""
    history_records = db.query(TaskHistory).order_by(TaskHistory.created_at.desc()).all()
    
    result = []
    for record in history_records:
        result.append({
            "id": record.id,
            "task_id": record.task_id,
            "prompt": record.prompt,
            "batch_size": record.batch_size,
            "duration": record.duration,
            "output_assets": record.output_assets,
            "created_at": record.created_at.isoformat() if record.created_at else None
        })
    return result
