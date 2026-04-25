"""
src/api/routes_ws.py
——————————————————————————————————————————————————————————————————————————
统一事件总线 — 路由层 v2（一次性船票鉴权 + 用户定向推送）

本模块导出两个独立 Router，在 main.py 中分别挂载：

  auth_router  → app.include_router(auth_router, prefix="/api/v1")
    POST /api/v1/auth/ws-ticket      ← 买票（REST）

  ws_router    → app.include_router(ws_router)          ← 无前缀
    WS   /ws/events?ticket=xxx       ← 持票上船（WebSocket）

完整鉴权流程：
  ①  前端  POST /api/v1/auth/ws-ticket  （携带 X-Local-User: alice）
      ↓  返回 {"ticket": "a3f1c0b2..."}  （UUID4 hex，10s 有效）
  ②  前端  new WebSocket('ws://host/ws/events?ticket=a3f1c0b2...')
      ↓  服务端 consume_ticket(ticket)   →  alice
      ↓  鉴权失败  →  close(1008)  立即断开
      ↓  鉴权成功  →  connect(ws, user_id="alice")  进入定向推送池
  ③  后端渲染任务  broadcast_sync(msg, user_id="alice")  精准投递

WebSocket 关闭码语义：
  1008 (Policy Violation) — 票号无效、已过期或已被消费。
"""

from __future__ import annotations

import logging
import random
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from starlette.status import WS_1008_POLICY_VIOLATION

from .ws_manager import manager as ws_manager

logger = logging.getLogger(__name__)


# ====================================================================== #
# auth_router — REST 鉴权接口（挂载于 /api/v1）                            #
# ====================================================================== #

auth_router = APIRouter(prefix="/auth", tags=["WS Auth"])


@auth_router.post(
    "/ws-ticket",
    summary="申请 WebSocket 一次性鉴权船票",
    description=(
        "为当前用户（由 `X-Local-User` 请求头标识）签发一张 10 秒有效的"
        "一次性 WebSocket 鉴权船票。\n\n"
        "**调用流程：**\n"
        "1. 前端 `POST /api/v1/auth/ws-ticket`（携带 `X-Local-User` 头）\n"
        "2. 获取 `ticket` 字符串\n"
        "3. `new WebSocket('ws://host/ws/events?ticket=<ticket>')`\n\n"
        "**注意：** 每张票只能使用一次，消费后立即失效，请勿缓存复用。"
    ),
    response_description="包含一次性船票字符串的 JSON 对象",
)
async def issue_ws_ticket(request: Request) -> JSONResponse:
    """
    签发 WebSocket 一次性鉴权船票。

    读取 X-Local-User 请求头作为用户标识（与现有多租户架构保持一致）。
    若请求头缺失，降级使用 "default"，保证单机开发场景可正常使用。
    """
    user_id: str = request.headers.get("X-Local-User", "default") or "default"
    ticket: str = ws_manager.issue_ticket(user_id)

    logger.info("[WsAuth] 为 user=%s 签发船票 %s...", user_id, ticket[:8])

    return JSONResponse(
        content={"ticket": ticket},
        status_code=200,
    )


# ====================================================================== #
# ws_router — WebSocket 事件流（挂载于根路径，无 /api/v1 前缀）             #
# ====================================================================== #

ws_router = APIRouter(tags=["EventBus WebSocket"])


@ws_router.websocket("/ws/events")
async def events_websocket_endpoint(
    websocket: WebSocket,
    ticket: str = Query(
        default=None,
        description="由 POST /api/v1/auth/ws-ticket 签发的一次性鉴权船票",
    ),
) -> None:
    """
    统一事件总线 WebSocket 订阅端点（v2：需持票上船）。

    鉴权三步曲：
      1. 提取 query param `ticket`（缺失则直接拒绝）。
      2. consume_ticket(ticket) 原子消费：
           - 有效  → 返回 user_id，继续建立连接。
           - 无效/过期/已消费  → close(1008)，立即断开。
      3. 鉴权成功，以 user_id 注册到多租户连接池，进入消息接收循环。

    连接生命周期：
      accept → 注册 → receive loop → disconnect（任何退出路径均执行）

    异常处理：
      - WebSocketDisconnect：客户端主动断开，INFO 日志，不上报错误。
      - 其他 Exception：网络异常等，WARNING 日志，静默捕获保证服务稳定。
      - finally：幂等执行 disconnect，确保连接池不泄漏。
    """
    client_host: str = websocket.client.host if websocket.client else "unknown"

    # ── 第一步：票号存在性检查 ─────────────────────────────────────────
    if not ticket:
        logger.warning(
            "[EventBus] 客户端 %s 未携带船票，拒绝连接（code=1008）。", client_host
        )
        await websocket.close(code=WS_1008_POLICY_VIOLATION)
        return

    # ── 第二步：原子消费船票，获取 user_id ────────────────────────────
    user_id: str | None = ws_manager.consume_ticket(ticket)
    if user_id is None:
        logger.warning(
            "[EventBus] 客户端 %s 船票无效或已过期 ticket=%s...，拒绝连接（code=1008）。",
            client_host, ticket[:8],
        )
        await websocket.close(code=WS_1008_POLICY_VIOLATION)
        return

    # ── 第三步：鉴权成功，握手并注册 ─────────────────────────────────
    await ws_manager.connect(websocket, user_id)
    logger.info(
        "[EventBus] 用户 %s（来自 %s）持票上船成功，进入事件流。",
        user_id, client_host,
    )

    try:
        # ── 消息接收循环（客户端断开时 receive_text 抛出 WebSocketDisconnect） ──
        while True:
            raw_msg: str = await websocket.receive_text()
            # 当前版本：客户端→服务端方向仅记录 DEBUG 日志
            # 未来扩展点：解析 type 字段，实现频道订阅、心跳 ACK 等控制平面指令
            logger.debug(
                "[EventBus] user=%s 发来消息（当前忽略）: %r",
                user_id, raw_msg[:200],
            )

    except WebSocketDisconnect as exc:
        logger.info(
            "[EventBus] 用户 %s 正常断开连接（code=%s）。", user_id, exc.code
        )

    except Exception as exc:
        logger.warning(
            "[EventBus] 用户 %s 连接异常断开: %r", user_id, exc
        )

    finally:
        # 无论何种退出路径，均确保从连接池中移除（disconnect 内部有幂等保护）
        ws_manager.disconnect(websocket, user_id)


# ====================================================================== #
# [STRESS_TEST] test_router — 压测专用路由（挂载于 /api/v1/test）         #
#                                                                        #
# ⚠️  测试完成后注释掉以下全部内容（直到文件末尾的向后兼容别名之前），     #
#    并在 main.py 中同步注释掉对应的 include_router 行。                  #
# ====================================================================== #

test_router = APIRouter(prefix="/test", tags=["[STRESS_TEST] WS Flood Test"])


def run_ws_flood_test(user_id: str) -> None:  # [STRESS_TEST]
    """
    [STRESS_TEST] 真实 WebSocket 洪流压测发球机。

    通过后端真实的 broadcast_sync → asyncio 桥梁 → WebSocket 管道，
    向指定用户推送 500 个模拟任务的全状态流转，验证：
      ① 一次性船票鉴权后的持续连接稳定性
      ② 前端 Worker + RecycleScroller 的异步渲染承载力
      ③ broadcast_sync 在高频调用下的队列积压与超时行为

    两阶段压测策略
    ──────────────
    Phase 1 — 瞬间批量入队（500 条 pending）：
      不加任何延迟，模拟任务队列爆发式涌入的最坏场景。

    Phase 2 — 逐任务状态流转（running → completed）：
      每个任务先发 running，sleep 随机 0.01~0.05s 后发 completed，
      模拟真实渲染任务完成的时序抖动。

    测试完成后应注释掉：
      1. 本函数（run_ws_flood_test）
      2. POST /test/flood-ws 端点
      3. main.py 中的 test_router include_router 行
    """
    # 本次压测的批次 ID，用于跨阶段关联同一批任务
    batch_id = uuid.uuid4().hex[:6]
    task_ids  = [f"flood_{batch_id}_{i:03d}" for i in range(500)]
    start_epoch_ms = int(time.time() * 1000)

    logger.info("[STRESS_TEST] 压测开始 batch=%s user=%s", batch_id, user_id)

    # ── Phase 1：瞬间推送 500 条 pending ────────────────────────────────────
    for i, task_id in enumerate(task_ids):
        ws_manager.broadcast_sync(
            message={
                "type": "WS_UPDATE",
                "payload": {
                    # 严格匹配前端 WsUpdatePayload 结构
                    "taskId":    task_id,
                    "status":    "pending",
                    "prompt":    (
                        f"[STRESS_TEST] 压测任务 #{i:03d}｜batch={batch_id}｜"
                        "模拟赛博朋克风格渲染，含多巴胺色彩 + 阿拉伯语唇形同步..."
                    ),
                    "startTime": start_epoch_ms,
                },
            },
            user_id=user_id,
        )

    logger.info("[STRESS_TEST] Phase 1 完成，已推送 500 条 pending — batch=%s", batch_id)

    # ── Phase 2：逐任务流转 running → completed ──────────────────────────────
    for i, task_id in enumerate(task_ids):
        # Step A: 推送 running
        ws_manager.broadcast_sync(
            message={
                "type": "WS_UPDATE",
                "payload": {
                    "taskId":    task_id,
                    "status":    "running",
                    "startTime": int(time.time() * 1000),
                },
            },
            user_id=user_id,
        )

        # 模拟渲染时长（0.01 ~ 0.05s），引入真实时序抖动
        time.sleep(random.uniform(0.01, 0.05))

        # Step B: 推送 completed（附带 mock 资产路径，匹配前端 assets 结构）
        mock_hash = uuid.uuid4().hex[:8]
        ws_manager.broadcast_sync(
            message={
                "type": "WS_UPDATE",
                "payload": {
                    "taskId": task_id,
                    "status": "completed",
                    "assets": [
                        {
                            "file_path": f"/mock/output/flood_{batch_id}/{task_id}.mp4",
                            "file_hash": mock_hash,
                        }
                    ],
                },
            },
            user_id=user_id,
        )

    logger.info(
        "[STRESS_TEST] Phase 2 完成，500 条任务全部流转至 completed — batch=%s", batch_id
    )


@test_router.post(
    "/flood-ws",
    summary="[STRESS_TEST] 启动真实 WS 洪流压测",
    description=(
        "通过后端真实 WebSocket 管道向指定用户推送 500 个模拟任务的完整状态流转。\n\n"
        "**压测两阶段：**\n"
        "1. Phase 1：瞬间推送 500 条 `pending` 消息（无延迟，测试批量入队峰值）\n"
        "2. Phase 2：逐任务推送 `running` → `completed`（含 0.01~0.05s 随机延迟）\n\n"
        "⚠️ **本接口仅用于开发压测，生产部署前请注释掉相关代码（标记 `[STRESS_TEST]`）。**"
    ),
    tags=["[STRESS_TEST] WS Flood Test"],
    status_code=202,
    include_in_schema=True,  # 压测期间可见；上线前改为 False 或删除整段
)
async def flood_ws(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """
    [STRESS_TEST] 接受压测请求，立即返回 202，后台异步执行洪流推送。

    Header:
      X-Local-User — 广播目标用户 ID（与 WS 连接时鉴权的 user_id 保持一致）
    """
    user_id: str = request.headers.get("X-Local-User", "default") or "default"
    batch_preview = uuid.uuid4().hex[:6]

    logger.info(
        "[STRESS_TEST] 收到压测请求，user=%s，即将在后台启动 flood batch≈%s",
        user_id, batch_preview,
    )

    # BackgroundTasks 在当前请求响应后、同一 uvicorn worker 线程池中执行
    background_tasks.add_task(run_ws_flood_test, user_id)

    return JSONResponse(
        status_code=202,
        content={
            "message":  "[STRESS_TEST] 压测已启动，500 条 WS 消息将实时推送至前端",
            "user_id":  user_id,
            "endpoint": "POST /api/v1/test/flood-ws",
        },
    )


# ──────────────────────────────────────────────────────────────────────
# 向后兼容别名（保持旧版 `from .routes_ws import router` 不报错）
# 注意：main.py 已更新为分别挂载 auth_router 和 ws_router，
# 此别名仅作过渡保险，新代码请直接使用 auth_router / ws_router。
# ──────────────────────────────────────────────────────────────────────
router = ws_router
