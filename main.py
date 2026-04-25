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

import asyncio
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

# ── 生产环境（PyInstaller 打包）：将工作目录切换到可执行文件所在目录 ──────────
# 必须在所有其他代码之前执行，确保 clipflow.db / .env / output/ 等相对路径
# 全部解析到安装目录（如 C:\ClipFlow\），而非系统默认工作目录。
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

# ── 最早加载 .env ─────────────────────────────────────────────────────────────
# 必须在任何读取 os.environ 的模块（OpenAI SDK、数据库 URL 等）导入之前完成。
# ThreadPoolExecutor 线程共享同一 os.environ，加载一次即对全部线程生效。
from src.utils.env_utils import load_env
load_env()

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from pyngrok import ngrok

from src.core.logger import setup_logger, logger
from src.api.database import engine, Base
from src.api.schemas import HealthResponse
from src.api import routes as task_routes
from src.api import routes_assets
from src.api import routes_history
from src.api import routes_gateway
from src.api import routes_video
from src.api import routes_ws
from src.api import settings_router
from src.api.ws_manager import manager as ws_manager

setup_logger()


# ================================================================== #
# Lifespan — 启动 & 关闭钩子                                           #
# ================================================================== #
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理：启动时建表 + 开启内网穿透，关闭时清理隧道资源。"""
    _public_url: str | None = None

    # ---- Zero Trust：生产包启动时静默销毁 .env（防止 API Key 泄露） ---- #
    if getattr(sys, "frozen", False):
        _env_path = os.path.join(os.path.dirname(sys.executable), ".env")
        if os.path.exists(_env_path):
            try:
                os.remove(_env_path)
                logger.info("[Zero Trust] 检测到生产环境中残留的 .env 文件，已自动销毁。")
            except Exception as _e:
                logger.warning(f"[Zero Trust] 尝试销毁 .env 时出现异常（已忽略）: {_e}")

    # ---- 启动阶段 ---- #
    logger.info("[ClipFlow] 正在初始化数据库表结构…")
    Base.metadata.create_all(bind=engine)
    logger.info("[ClipFlow] 数据库就绪 ✓")

    # ---- 注入事件循环到 WebSocket 广播中枢 ---- #
    # asyncio.get_running_loop() 在 lifespan（async 上下文）中安全可用。
    # 注入后，运行于 ThreadPoolExecutor 的渲染任务可通过 ws_manager.broadcast_sync()
    # 跨线程安全地向前端推送实时进度。
    ws_manager.set_event_loop(asyncio.get_running_loop())
    logger.info("[ClipFlow] WebSocket 事件总线事件循环已注入 ✓")

    # ---- Ngrok 内网穿透 ---- #
    # ngrok.connect 是同步调用，在 lifespan 启动阶段（服务器尚未接受请求时）
    # 执行不会影响请求处理；若需严格非阻塞可改用 run_in_executor。
    try:
        loop = asyncio.get_event_loop()
        http_tunnel = await loop.run_in_executor(
            None, lambda: ngrok.connect(8000, bind_tls=True)
        )
        _public_url = http_tunnel.public_url
        os.environ["PUBLIC_BASE_URL"] = _public_url
        logger.info("=" * 60)
        logger.info(f"🌍 [内网穿透] Ngrok 公网地址已映射: {_public_url}")
        logger.info("=" * 60)
    except Exception as exc:
        logger.warning(f"[内网穿透] Ngrok 启动失败，将继续使用本地地址: {exc}")

    yield  # 应用运行中

    # ---- 关闭阶段 ---- #
    if _public_url:
        try:
            ngrok.disconnect(_public_url)
            ngrok.kill()
            logger.info("[内网穿透] Ngrok 隧道已断开，进程已清理。")
        except Exception as exc:
            logger.warning(f"[内网穿透] Ngrok 关闭时出现异常（可忽略）: {exc}")
    logger.info("[ClipFlow] 应用已关闭。")


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
# 视频基因舱详情接口 — manifest 查询 & 资产元信息
app.include_router(routes_video.router, prefix="/api/v1")
# Omnichannel Gateway — 全渠道 IM 消息网关（Telegram / WhatsApp / 企微等统一入口）
app.include_router(routes_gateway.router, prefix="/api/v1")
# BYOK 设置接口 — 前端写入 / 读取 LLM API Key
app.include_router(settings_router.router, prefix="/api/v1")
# 统一事件总线 — 鉴权 REST 接口（买票：POST /api/v1/auth/ws-ticket）
app.include_router(routes_ws.auth_router, prefix="/api/v1")
# 统一事件总线 — WebSocket 实时推送端点（持票上船：WS /ws/events?ticket=xxx，无 /api/v1 前缀）
app.include_router(routes_ws.ws_router)
# [STRESS_TEST] 压测专用路由 — 测试完成后注释掉此行（同时注释掉 routes_ws.py 中的 test_router 相关代码）
app.include_router(routes_ws.test_router, prefix="/api/v1")


# ================================================================== #
# 系统管理路由（私有，不对外文档暴露）                                   #
# ================================================================== #
_system_router = APIRouter(prefix="/api/v1/system", include_in_schema=False)


@_system_router.post("/shutdown")
async def system_shutdown() -> JSONResponse:
    """
    私有关机端点 — 仅供 Tauri 前端在窗口关闭时调用。

    执行策略（两阶段）：
      1. 立即返回 200，确保 HTTP 响应能被 Rust 端收到。
      2. 异步延迟 0.5 秒后，使用 taskkill /F /T /PID 斩杀自身进程树
         （/T 参数会连同 ProcessPoolExecutor 派生的全部子进程一起终止）。
      3. 非 Windows 平台回退到 os._exit(0)。
    """
    async def _deferred_exit() -> None:
        await asyncio.sleep(0.5)
        pid = os.getpid()
        logger.info(f"[shutdown] 收到优雅关机指令，PID={pid}，正在终止进程树…")
        if sys.platform == "win32":
            # /F 强制  /T 包含全部子进程  /PID 精准锁定自身
            subprocess.Popen(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            os._exit(0)

    asyncio.create_task(_deferred_exit())
    return JSONResponse(content={"status": "shutting_down"})


app.include_router(_system_router)


# ================================================================== #
# 开发入口（直接 python main.py 时使用）                                 #
# ================================================================== #
if __name__ == "__main__":
    import uvicorn

    is_prod = getattr(sys, "frozen", False)

    if is_prod:
        # 生产环境（PyInstaller 打包）：直接传 FastAPI 实例，不能传字符串
        uvicorn.run(app, host="127.0.0.1", port=8000, log_config=None)
    else:
        # 开发环境
        uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)