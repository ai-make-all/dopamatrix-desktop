"""
main.py  —  ClipFlow FastAPI 应用入口
—————————————————————————————————————
职责：
  1. 初始化 FastAPI 实例（含 lifespan 生命周期管理）
  2. 在应用启动时自动创建 SQLite 数据表
  3. 注册全部路由（当前仅健康检查，Phase 5 路由将在 src/api/routes.py 中追加）
  4. 暴露 CORS，便于本地前端 / GrowthOS 直接调用

运行方式：
  uvicorn main:app --reload --port 8000
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.database import engine, Base
from src.api.schemas import HealthResponse
from src.api import routes as task_routes
from src.api import routes_assets
from src.api import routes_history


# ================================================================== #
# Lifespan — 启动 & 关闭钩子                                           #
# ================================================================== #
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理：启动时建表，关闭时可做清理。"""
    # ---- 启动阶段 ---- #
    print("[ClipFlow] 正在初始化数据库表结构…")
    Base.metadata.create_all(bind=engine)
    print("[ClipFlow] 数据库就绪 ✓")

    yield  # 应用运行中

    # ---- 关闭阶段（预留） ---- #
    print("[ClipFlow] 应用已关闭。")


# ================================================================== #
# FastAPI 实例                                                          #
# ================================================================== #
app = FastAPI(
    title="ClipFlow — Headless Render Engine",
    description=(
        "纯粹的高并发音视频渲染引擎，通过标准化 Headless API 向外暴露能力，"
        "供 GrowthOS 等上层业务系统无缝接入。"
    ),
    version="0.5.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---- CORS（允许本地前端 & GrowthOS 直接调用）-------------------- #
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 生产环境请收紧为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 静态文件：挂载 output 目录，前端可直接通过 URL 播放视频 ---- #
_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(_OUTPUT_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=_OUTPUT_DIR), name="output")


# ================================================================== #
# 路由 — 健康检查                                                        #
# ================================================================== #
@app.get(
    "/health",
    response_model=HealthResponse,
    summary="健康检查",
    tags=["System"],
)
async def health_check() -> HealthResponse:
    """
    返回引擎运行状态。
    GrowthOS / 监控系统可定期 ping 此接口确认服务存活。
    """
    return HealthResponse(
        status="ClipFlow Engine is running",
        version="0.5.0",
        db="connected",
    )


# ================================================================== #
# Phase 5 & DAM 路由挂载                                                #
# ================================================================== #
app.include_router(task_routes.router, prefix="/api/v1")
app.include_router(routes_assets.router, prefix="/api/v1")
app.include_router(routes_history.router, prefix="/api/v1")


# ================================================================== #
# 开发入口（直接 python main.py 时使用）                                 #
# ================================================================== #
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
