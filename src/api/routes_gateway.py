"""
src/api/routes_gateway.py
——————————————————————————
全渠道消息网关路由 (Omnichannel Gateway Router)

架构定位：
  本模块是整个 IM 消息系统唯一的「城门」。
  所有渠道（Telegram、WhatsApp、企微……）的 Webhook 流量统一流入此处，
  由网关完成「平台专属 payload → UniversalMessage → 业务调度 → 平台专属回复」
  的全程转化，业务层对平台细节保持零感知。

端点：
  POST /webhook/{platform}/receive
    path param: platform — 渠道标识符（小写），如 telegram / whatsapp
    body: 原始 Webhook JSON（由各平台直接推送，无需预处理）

数据流（The Pipeline）：
  ┌───────────────────────────────────────────────────────────┐
  │  Telegram/WhatsApp/企微 Webhook                           │
  │       ↓ raw JSON                                          │
  │  routes_gateway  POST /webhook/{platform}/receive         │
  │       ↓ 查找注册表，实例化 Adapter                         │
  │  adapter.parse_incoming(raw)                              │
  │       ↓ UniversalMessage（平台无关）                       │
  │  dispatcher.dispatch(msg)   ← 业务层在此，完全看不到 TG    │
  │       ↓ reply_text (str)                                  │
  │  adapter.send_text(reply_channel_id, reply_text)          │
  │       ↓ 平台专属 API 调用                                  │
  │  200 OK {"status": "processed"}                           │
  └───────────────────────────────────────────────────────────┘

安全说明：
  - Telegram Webhook 安全验证：建议在 Nginx/Cloudflare 层限制来源 IP 为 TG IP 段，
    或通过 X-Telegram-Bot-Api-Secret-Token 请求头验证（可在此中间件扩展）。
  - 生产环境应为每个渠道设置独立 secret_token 并在此处校验。
"""

from __future__ import annotations

import traceback
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Request, status
from fastapi.responses import JSONResponse

from src.core.logger import logger
from src.services.messaging.adapters import ADAPTER_REGISTRY
from src.services.messaging.contract import UniversalMessage, UniversalResponse
from src.services.messaging import dispatcher

router = APIRouter(prefix="/webhook", tags=["Omnichannel Gateway"])


# ================================================================== #
# POST /webhook/{platform}/receive                                     #
# ================================================================== #
@router.post(
    "/{platform}/receive",
    status_code=status.HTTP_200_OK,
    summary="全渠道 Webhook 统一接收端点",
    description=(
        "接收任意已注册平台的 Webhook 推送。"
        "通过路径参数 `{platform}` 动态路由至对应适配器，"
        "转化为 UniversalMessage 后驱动业务逻辑，最终原路发回回复。"
    ),
    response_description="处理结果摘要",
)
async def receive_webhook(
    platform: str = Path(
        ...,
        description="渠道标识符（小写），如 telegram / whatsapp / wechat",
        examples=["telegram"],
    ),
    request: Request = None,
) -> JSONResponse:
    """
    全渠道统一接收路由。

    核心保证：此函数对 Telegram 一无所知。
    它只知道「给我一个 Adapter，解析出 UniversalMessage，交给调度器」。
    """

    # ---- 1. 查找适配器 -------------------------------------------- #
    adapter_class = ADAPTER_REGISTRY.get(platform.lower())
    if adapter_class is None:
        registered = list(ADAPTER_REGISTRY.keys())
        logger.warning(f"[Gateway] 未知平台: '{platform}'，已注册: {registered}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform '{platform}' is not registered. Available: {registered}",
        )

    # ---- 2. 读取原始 Payload -------------------------------------- #
    try:
        raw_payload: dict = await request.json()
    except Exception as exc:
        logger.error(f"[Gateway] 读取 request body 失败: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON body: {exc}",
        )

    # ---- 3. 实例化适配器 ------------------------------------------ #
    # 注意：适配器的构造依赖环境变量（如 TELEGRAM_BOT_TOKEN），
    # 若 Token 未配置会在此处抛出 ValueError，返回 500 以触发告警。
    try:
        adapter = adapter_class()
    except ValueError as exc:
        logger.error(f"[Gateway] 适配器初始化失败 platform={platform}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Adapter configuration error: {exc}",
        )

    # ---- 4. 解析为 UniversalMessage ------------------------------- #
    try:
        msg: UniversalMessage = await adapter.parse_incoming(raw_payload)
    except ValueError as exc:
        # 平台推送了网关无法识别的 Update 结构（如 bot 自己发送的 echo）
        logger.warning(
            f"[Gateway] parse_incoming 解析失败 platform={platform}: {exc} "
            f"| payload_keys={list(raw_payload.keys())}"
        )
        # 返回 200 而非 4xx：Telegram 等平台在非 200 时会无限重试推送
        return JSONResponse(
            content={"status": "ignored", "reason": str(exc)},
            status_code=status.HTTP_200_OK,
        )

    # ---- 5. 业务调度 —— 完全平台无关 ------------------------------ #
    # dispatcher 只看 UniversalMessage，永远不知道这条消息来自 Telegram
    response: UniversalResponse | None = None
    try:
        response = await dispatcher.dispatch(msg)
    except Exception as exc:
        logger.error(
            f"[Gateway] dispatcher.dispatch 异常: {exc}\n{traceback.format_exc()}"
        )
        response = UniversalResponse(text="系统繁忙，请稍后重试。")

    # ---- 6. 智能出站路由（通过 Adapter，业务层仍不感知平台）--------- #
    # 核心判断：UniversalResponse.has_buttons 决定走哪条发送通道
    send_mode = "none"
    if response is not None:
        try:
            if response.has_buttons:
                # 激活按钮卡片通道
                await adapter.send_action_card(
                    msg.reply_channel_id,
                    response.text,
                    response.buttons,
                )
                send_mode = "action_card"
            else:
                # 纯文本通道
                await adapter.send_text(msg.reply_channel_id, response.text)
                send_mode = "text"
        except Exception as exc:
            # 发送失败不影响 Webhook 确认（避免平台重试导致消息重复）
            logger.error(
                f"[Gateway] 出站发送失败 mode={send_mode} platform={platform} "
                f"chat_id={msg.reply_channel_id}: {exc}"
            )

    # ---- 7. 向平台返回 200 确认（务必快速响应！）------------------- #
    return JSONResponse(content={
        "status"     : "processed",
        "platform"   : platform,
        "message_id" : msg.message_id,
        "client_id"  : msg.client_id,
        "msg_type"   : msg.message_type.value,
        "send_mode"  : send_mode,
        "replied"    : response is not None,
    })


# ================================================================== #
# GET /webhook/platforms — 查询已注册渠道（运维用）                     #
# ================================================================== #
@router.get(
    "/platforms",
    summary="查询已注册的渠道列表",
    tags=["Omnichannel Gateway"],
    include_in_schema=True,
)
async def list_platforms() -> dict[str, Any]:
    """返回当前网关已注册的所有渠道标识符。"""
    return {
        "registered_platforms": list(ADAPTER_REGISTRY.keys()),
        "total": len(ADAPTER_REGISTRY),
    }
