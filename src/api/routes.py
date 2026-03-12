"""
src/api/routes.py
———————————————————
ClipFlow — 核心 API 路由。

端点列表：
  POST   /tasks/submit        提交矩阵生成任务（秒回！返回 202 + queued）
  GET    /tasks/{task_id}     查询任务详情（含资产指纹列表）
  GET    /tasks/              最近任务列表（最多 20 条）
"""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from .database import get_db
from .models import VideoTask, VideoAsset
from .schemas import (
    VideoTaskCreate,
    VideoTaskResponse,
    VideoTaskStatusResponse,
    VideoAssetResponse,
    TaskSubmitAck,
)
from .services import run_matrix_job

router = APIRouter(prefix="/tasks", tags=["Tasks"])


# ================================================================== #
# POST /tasks/submit                                                   #
# ================================================================== #
@router.post(
    "/submit",
    response_model=TaskSubmitAck,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交矩阵生成任务",
    description=(
        "创建一条 VideoTask 记录，状态立即设为 'queued'，直接返回 202 Accepted。"
        "实际渲染在后台 BackgroundTask 中异步执行，"
        "通过 GET /tasks/{task_id} 轮询状态。"
    ),
)
def submit_task(
    payload: VideoTaskCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> TaskSubmitAck:
    # 1. 生成 session_id
    session_id: str = payload.session_id or uuid.uuid4().hex[:12]

    # 2. 防止重复提交
    existing = db.query(VideoTask).filter(VideoTask.session_id == session_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"session_id '{session_id}' 已存在，请换一个或不传（自动生成）。",
        )

    # 3. 写入数据库（初始状态 queued）
    task = VideoTask(
        session_id = session_id,
        prompt     = payload.prompt,
        batch_size = payload.batch_size,
        status     = "queued",          # ← 注意：由 pending 改为 queued
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 4. 把实际运行逻辑投入后台（BackgroundTask 拿到 task.id 后内部独立开 Session）
    background_tasks.add_task(
        run_matrix_job,
        task_id           = task.id,
        session_id        = session_id,
        prompt            = payload.prompt,
        batch_size        = payload.batch_size,
        aspect_ratio      = payload.aspect_ratio,
        test_language     = payload.test_language,
        target_duration   = payload.target_duration,
        output_dir        = payload.output_dir,
    )

    print(
        f"[routes] ✅ 任务已入队 task_id={task.id} session={session_id}"
        + f" ratio={payload.aspect_ratio} lang={payload.test_language} duration={payload.target_duration}s"
    )

    # 5. 秒回 202（HTTP 请求绝不阻塞 2 分钟！）
    return TaskSubmitAck(
        task_id=task.id,
        session_id=session_id,
        status="queued",
        message="任务已提交至后台矩阵工厂，请通过 GET /tasks/{task_id} 轮询进度。",
    )


# ================================================================== #
# GET /tasks/{task_id}                                                 #
# ================================================================== #
@router.get(
    "/{task_id}",
    response_model=VideoTaskResponse,
    summary="查询任务详情",
    description="返回任务状态与全部关联的视频资产（含 file_hash / perceptual_hash）。",
)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
) -> VideoTaskResponse:
    task = (
        db.query(VideoTask)
        .options(selectinload(VideoTask.assets))   # 一次查询加载关联资产，避免 N+1
        .filter(VideoTask.id == task_id)
        .first()
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"task_id={task_id} 不存在。",
        )
    return VideoTaskResponse.model_validate(task)


# ================================================================== #
# GET /tasks/  — 最近任务列表                                           #
# ================================================================== #
@router.get(
    "/",
    response_model=List[VideoTaskStatusResponse],
    summary="最近任务列表",
    description="返回最近 20 条任务的简要状态（不含资产详情，用于仪表盘轮询）。",
)
def list_tasks(
    db: Session = Depends(get_db),
) -> List[VideoTaskStatusResponse]:
    tasks = (
        db.query(VideoTask)
        .order_by(VideoTask.created_at.desc())
        .limit(20)
        .all()
    )
    return [VideoTaskStatusResponse.model_validate(t) for t in tasks]
