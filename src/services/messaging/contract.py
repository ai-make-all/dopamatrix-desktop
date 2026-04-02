"""
src/services/messaging/contract.py
————————————————————————————————————
全渠道标准契约 (The Omnichannel Contract)

设计原则：
  - UniversalMessage 是整个消息系统唯一的「语言」。
    业务层（RAG 自动回复、工单系统、Tier-0 大脑）永远只看这个模型，
    对底层平台（Telegram / WhatsApp / 企微 / SMS）完全无感知。

  - BaseIMAdapter 是平台适配器的铁律合约。
    每新增一个渠道，只需新建一个子类并实现三个抽象方法即可接入全局。
    无需修改任何业务层代码 —— 依赖倒置原则 (DIP) 的完整体现。

  - raw_metadata 字段：平台专属字段的"密封舱"。
    允许存入原始平台数据供调试或高阶功能使用，但业务核心逻辑禁止读取它。
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ================================================================== #
# 枚举：消息类型                                                        #
# ================================================================== #
class MessageType(str, Enum):
    TEXT        = "text"
    IMAGE       = "image"
    AUDIO       = "audio"
    VIDEO       = "video"
    DOCUMENT    = "document"
    ACTION      = "action"       # 按钮回调 / Inline Keyboard 回调
    UNKNOWN     = "unknown"


# ================================================================== #
# 核心契约模型：UniversalMessage                                        #
# ================================================================== #
class UniversalMessage(BaseModel):
    """
    平台无关的统一消息载体。

    业务层的唯一输入格式。任何与平台相关的字段都被屏蔽在 raw_metadata 中，
    业务逻辑只操作本模型的标准字段。
    """

    # 全局唯一消息 ID（由网关层生成，与平台 message_id 无关）
    message_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="网关层生成的全局唯一消息 ID",
    )

    # 工单 ID：由工单系统在下游分配，网关入口为 None
    ticket_id: Optional[str] = Field(
        default=None,
        description="关联的工单 ID，由业务层在下游填入",
    )

    # 渠道标识符：小写字母，如 'telegram' / 'whatsapp' / 'wechat'
    source_platform: str = Field(
        description="消息来源平台标识，小写，如 'telegram'",
    )

    # 平台无关的客户 ID：网关层负责归一化（如 str(tg_user_id)）
    client_id: str = Field(
        description="平台无关的客户唯一标识，由适配器归一化",
    )

    # 回复目标：与 client_id 不同，某些平台（如 TG 群组）chat_id ≠ user_id
    reply_channel_id: str = Field(
        description="回复目标的渠道 ID（如 Telegram chat_id），用于 send_text 等回调",
    )

    # 消息类型
    message_type: MessageType = Field(
        default=MessageType.TEXT,
        description="归一化消息类型",
    )

    # 文本内容（TEXT 类型的核心字段；其他类型可存 caption 或留空）
    content: str = Field(
        default="",
        description="消息文本内容或 caption",
    )

    # 媒体资源 URL（图片/音频/视频类型时填入，由适配器负责解析）
    media_url: Optional[str] = Field(
        default=None,
        description="媒体文件 URL（适配器解析后的可访问地址）",
    )

    # 接收时间戳（UTC）
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="消息到达网关的 UTC 时间戳",
    )

    # 平台原始 payload 密封舱 —— 业务逻辑禁止依赖此字段！
    raw_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="平台原始字段密封舱，仅供调试，业务层禁止读取",
    )

    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}


# ================================================================== #
# 适配器抽象基类：BaseIMAdapter                                         #
# ================================================================== #
class BaseIMAdapter(ABC):
    """
    即时通讯平台适配器铁律合约。

    每个渠道必须实现三个方法，形成完整的「收-发」闭环：
      - parse_incoming : 入站解析（raw platform payload → UniversalMessage）
      - send_text      : 外发纯文本
      - send_action_card: 外发按钮卡片（Inline Keyboard / Quick Reply 等）

    业务层调用方式示例：
        msg: UniversalMessage = adapter.parse_incoming(raw)
        # ... 业务处理 ...
        await adapter.send_text(msg.reply_channel_id, reply_text)
    """

    # ---- 入站解析 -------------------------------------------- #
    @abstractmethod
    async def parse_incoming(self, raw_payload: dict) -> UniversalMessage:
        """
        将平台原始 Webhook payload 解析为 UniversalMessage。

        实现要求：
          - 必须填充 source_platform / client_id / reply_channel_id /
            message_type / content 五个核心字段
          - raw_metadata 可选存入平台原始字段（用于调试溯源）
          - 解析失败时抛出 ValueError，由网关层统一处理为 400
        """
        ...

    # ---- 外发文本 -------------------------------------------- #
    @abstractmethod
    async def send_text(self, chat_id: str, text: str) -> None:
        """
        向指定渠道 ID 发送纯文本消息。

        Args:
            chat_id: 平台渠道 ID（由 UniversalMessage.reply_channel_id 传入）
            text:    要发送的文本内容
        """
        ...

    # ---- 外发按钮卡片 ----------------------------------------- #
    @abstractmethod
    async def send_action_card(
        self,
        chat_id: str,
        text: str,
        buttons: List[Dict[str, str]],
    ) -> None:
        """
        向指定渠道 ID 发送带按钮的交互卡片。

        Args:
            chat_id: 平台渠道 ID
            text:    卡片正文（问题描述或说明）
            buttons: 按钮列表，格式为 [{"label": "...", "value": "..."}, ...]
                     适配器负责将通用格式转换为平台专属结构
                     （如 TG InlineKeyboard / WA Quick Reply Buttons）
        """
        ...


# ================================================================== #
# 出站响应 DTO：UniversalResponse                                       #
# ================================================================== #
class UniversalResponse(BaseModel):
    """
    业务层向网关返回的统一出站响应载体 (Outbound DTO)。

    网关的智能路由逻辑：
      - buttons 为 None 或空列表 → 调用 adapter.send_text()
      - buttons 有值             → 调用 adapter.send_action_card()

    这样业务层（dispatcher）只需构造此对象，
    无需感知底层平台是用 InlineKeyboard 还是 Quick Reply 还是其他机制实现按钮。
    """

    text: str = Field(
        description="要回复的纯文本 / HTML 内容",
    )
    buttons: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description='交互按钮列表，如 [{"label": "呼叫支援", "value": "escalate"}]',
    )

    @property
    def has_buttons(self) -> bool:
        """快捷判断：是否携带按钮（网关智能路由入口）。"""
        return bool(self.buttons)
