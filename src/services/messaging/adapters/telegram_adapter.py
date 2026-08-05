"""
src/services/messaging/adapters/telegram_adapter.py
————————————————————————————————————————————————————
Telegram 渠道适配器 (TelegramAdapter)

职责：
  - parse_incoming : 将 Telegram Webhook Update JSON 解析为平台无关的 UniversalMessage
  - send_text      : 调用 Telegram Bot API sendMessage 发送纯文本
  - send_action_card: 调用 sendMessage + InlineKeyboardMarkup 发送按钮卡片

技术选型：
  - 使用 httpx.AsyncClient 直接调用 Telegram Bot API（无额外依赖，轻量可控）
  - Bot Token 从环境变量 TELEGRAM_BOT_TOKEN 读取
  - 所有 API 调用带超时保护（默认 10s），网络失败抛出 RuntimeError

Telegram Update 结构参考（仅解析最常用的 message 和 callback_query）：
  {
    "update_id": 123456789,
    "message": {
      "message_id": 1,
      "from": {"id": 987654321, "first_name": "Alice"},
      "chat": {"id": -1001234567890, "type": "group"},
      "text": "Hello DopaMatrix"
    }
  }
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from src.core.logger import logger
from ..contract import BaseIMAdapter, MessageType, UniversalMessage


# ================================================================== #
# 常量                                                                  #
# ================================================================== #
_TG_API_BASE = "https://api.telegram.org/bot{token}/{method}"
_DEFAULT_TIMEOUT = 10.0  # 秒


class TelegramAdapter(BaseIMAdapter):
    """
    Telegram Bot Webhook 适配器。

    实例化时读取 TELEGRAM_BOT_TOKEN 环境变量；也可通过构造函数显式传入 token
    （方便多 Bot 实例并存，如为不同租户分配独立 Bot）。
    """

    def __init__(self, bot_token: Optional[str] = None) -> None:
        self._token: str = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not self._token:
            raise ValueError(
                "TelegramAdapter: TELEGRAM_BOT_TOKEN 未配置。"
                "请在 .env 或环境变量中设置 TELEGRAM_BOT_TOKEN=<your_bot_token>。"
            )

    # ------------------------------------------------------------------ #
    # 工具方法                                                              #
    # ------------------------------------------------------------------ #
    def _api_url(self, method: str) -> str:
        return _TG_API_BASE.format(token=self._token, method=method)

    async def _post(self, method: str, payload: Dict[str, Any]) -> dict:
        """向 Telegram Bot API 发 POST 请求，统一处理错误。"""
        url = self._api_url(method)
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(
                f"TelegramAdapter.{method} 调用失败: "
                f"[{data.get('error_code')}] {data.get('description')}"
            )
        return data.get("result", {})

    # ------------------------------------------------------------------ #
    # parse_incoming — 核心解析方法                                         #
    # ------------------------------------------------------------------ #
    async def parse_incoming(self, raw_payload: dict) -> UniversalMessage:
        """
        将 Telegram Webhook Update 解析为 UniversalMessage。

        支持两种 Update 类型：
          - message       : 普通文本/媒体消息
          - callback_query: Inline Keyboard 按钮点击回调

        完全屏蔽 Telegram 专属字段（update_id、from、entities 等），
        业务层收到的 UniversalMessage 与 Telegram 零耦合。
        """
        # ---- callback_query（按钮回调）--------------------------------- #
        if "callback_query" in raw_payload:
            cq: dict = raw_payload["callback_query"]
            user   = cq.get("from", {})
            chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
            return UniversalMessage(
                source_platform  = "telegram",
                client_id        = str(user.get("id", "")),
                reply_channel_id = chat_id,
                message_type     = MessageType.ACTION,
                content          = cq.get("data", ""),
                raw_metadata     = {"callback_query_id": cq.get("id"), "update": raw_payload},
            )

        # ---- message（普通消息）--------------------------------------- #
        message: dict = raw_payload.get("message")
        if not message:
            raise ValueError(
                f"TelegramAdapter.parse_incoming: "
                f"无法识别的 Update 结构，缺少 'message' 或 'callback_query' 字段。"
                f" update_id={raw_payload.get('update_id')}"
            )

        user    = message.get("from", {})
        chat    = message.get("chat", {})
        chat_id = str(chat.get("id", ""))

        # 消息类型归一化
        if "text" in message:
            msg_type = MessageType.TEXT
            content  = message["text"]
            media_url: Optional[str] = None

        elif "photo" in message:
            msg_type  = MessageType.IMAGE
            content   = message.get("caption", "")
            # TG photo 是数组，取分辨率最大的最后一张
            photo     = message["photo"][-1]
            media_url = await self._resolve_file_url(photo.get("file_id", ""))

        elif "voice" in message or "audio" in message:
            msg_type  = MessageType.AUDIO
            content   = message.get("caption", "")
            file_id   = (message.get("voice") or message.get("audio", {})).get("file_id", "")
            media_url = await self._resolve_file_url(file_id)

        elif "video" in message:
            msg_type  = MessageType.VIDEO
            content   = message.get("caption", "")
            media_url = await self._resolve_file_url(message["video"].get("file_id", ""))

        elif "document" in message:
            msg_type  = MessageType.DOCUMENT
            content   = message.get("caption", "")
            media_url = await self._resolve_file_url(message["document"].get("file_id", ""))

        else:
            msg_type  = MessageType.UNKNOWN
            content   = ""
            media_url = None

        return UniversalMessage(
            source_platform  = "telegram",
            client_id        = str(user.get("id", "")),
            reply_channel_id = chat_id,
            message_type     = msg_type,
            content          = content,
            media_url        = media_url,
            # 密封平台字段，业务层禁止依赖
            raw_metadata     = {
                "tg_message_id"  : message.get("message_id"),
                "tg_chat_type"   : chat.get("type"),
                "tg_username"    : user.get("username"),
                "tg_first_name"  : user.get("first_name"),
                "update_id"      : raw_payload.get("update_id"),
            },
        )

    async def _resolve_file_url(self, file_id: str) -> Optional[str]:
        """将 Telegram file_id 解析为可访问的 HTTPS 文件 URL。"""
        if not file_id:
            return None
        try:
            result = await self._post("getFile", {"file_id": file_id})
            file_path: str = result.get("file_path", "")
            return f"https://api.telegram.org/file/bot{self._token}/{file_path}"
        except Exception as exc:
            logger.warning(f"[TelegramAdapter] 解析 file_id={file_id} 失败: {exc}")
            return None

    # ------------------------------------------------------------------ #
    # send_text                                                            #
    # ------------------------------------------------------------------ #
    async def send_text(self, chat_id: str, text: str) -> None:
        """
        向指定 chat_id 发送纯文本消息。

        使用 Markdown V2 以外的 HTML parse_mode 避免特殊字符转义问题。
        """
        await self._post("sendMessage", {
            "chat_id"    : chat_id,
            "text"       : text,
            "parse_mode" : "HTML",
        })
        logger.debug(f"[TelegramAdapter] send_text → chat_id={chat_id}, len={len(text)}")

    # ------------------------------------------------------------------ #
    # send_action_card                                                     #
    # ------------------------------------------------------------------ #
    async def send_action_card(
        self,
        chat_id: str,
        text: str,
        buttons: List[Dict[str, str]],
    ) -> None:
        """
        发送带 Inline Keyboard 按钮的卡片消息。

        通用 buttons 格式:
          - 回调按钮: {"label": "人工客服", "value": "escalate"}
          - URL 跳转: {"label": "立即下载", "url": "https://..."}

        优先判断 "url" 键：有则生成 url 按钮，否则生成 callback_data 按钮。
        每行最多 2 个按钮，自动换行。
        """
        # 将平铺的按钮列表按每行 2 个分组
        keyboard_rows = []
        for i in range(0, len(buttons), 2):
            row = [
                {"text": btn["label"], "url": btn["url"]}
                if "url" in btn
                else {"text": btn["label"], "callback_data": btn["value"]}
                for btn in buttons[i : i + 2]
            ]
            keyboard_rows.append(row)

        await self._post("sendMessage", {
            "chat_id"      : chat_id,
            "text"         : text,
            "parse_mode"   : "HTML",
            "reply_markup" : {"inline_keyboard": keyboard_rows},
        })
        logger.debug(
            f"[TelegramAdapter] send_action_card → chat_id={chat_id}, "
            f"buttons={len(buttons)}"
        )
