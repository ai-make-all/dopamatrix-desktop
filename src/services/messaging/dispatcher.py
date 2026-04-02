"""
src/services/messaging/dispatcher.py
————————————————————————————————————
全渠道消息调度器 (Universal Message Dispatcher)

这是业务逻辑层的「守门员」。

核心原则：
  - 调度器只接受 UniversalMessage，对来源平台完全盲目。
  - 调度器返回 UniversalResponse，携带 text + 可选 buttons。
    网关层根据 has_buttons 自动选择 send_text / send_action_card 通道，
    业务层无需关心底层平台如何渲染按钮。

当前调度逻辑（Tier-0 快速路由）：
  1. 关键字触发 → 直接返回标准应答（速度最快，零 LLM 成本）
     - "帮助" / "help" 类 → 携带功能快捷按钮卡片
     - "人工客服"         → 携带确认按钮卡片
  2. 按钮回调（ACTION） → 处理用户点击，按需携带后续引导按钮
  3. 媒体类消息         → 纯文本告知，转入处理队列
  4. 其余文本           → Tier-1 RAG 自动回复（携带兜底按钮）
  5. 未知类型           → 优雅降级

扩展点：
  - 接入工单系统：在此处 create_or_update_ticket(msg)
  - 接入 RAG：await llm_provider.generate_reply(msg.content, context)
  - 接入人工坐席路由：await escalate_to_agent(msg)
"""

from __future__ import annotations

from typing import Optional

from src.core.logger import logger
from .contract import MessageType, UniversalMessage, UniversalResponse


# ---- Tier-0 纯文本关键字触发表（无 LLM 成本，无按钮）-------------- #
_TIER0_PLAIN: dict[str, str] = {
    "你好"  : "您好！我是 ClipFlow 智能助手，请问有什么可以帮您？",
    "hello" : "Hello! I'm ClipFlow Assistant. How can I help you today?",
    "hi"    : "Hello! I'm ClipFlow Assistant. How can I help you today?",
}

# ---- Tier-0 携带按钮的关键字触发表 -------------------------------- #
_HELP_BUTTONS = [
    {"label": "📋 查询任务状态", "value": "check_status"},
    {"label": "💰 视频报价",    "value": "pricing"},
    {"label": "🎧 人工客服",    "value": "escalate"},
]

_ESCALATE_BUTTONS = [
    {"label": "✅ 确认转接",   "value": "escalate_confirm"},
    {"label": "❌ 继续自助",   "value": "self_service"},
]

_RAG_FALLBACK_BUTTONS = [
    {"label": "🎧 联系人工客服", "value": "escalate"},
    {"label": "🔄 重新提问",    "value": "retry"},
]


async def dispatch(msg: UniversalMessage) -> Optional[UniversalResponse]:
    """
    接收 UniversalMessage，返回 UniversalResponse（None 表示静默处理，不回复）。

    业务层对 source_platform 完全盲目 —— 这里没有任何 Telegram/WhatsApp 字样。
    网关层根据 response.has_buttons 自动选择出站通道。
    """
    logger.info(
        f"[Dispatcher] ← platform={msg.source_platform} "
        f"client={msg.client_id} type={msg.message_type} "
        f"ticket={msg.ticket_id or 'NEW'} "
        f"content='{msg.content[:60]}'"
    )

    # ---- 按钮回调（ACTION）---------------------------------------- #
    if msg.message_type == MessageType.ACTION:
        return await _handle_action(msg)

    # ---- 媒体消息（IMAGE / AUDIO / VIDEO / DOCUMENT）-------------- #
    if msg.message_type in (
        MessageType.IMAGE, MessageType.AUDIO,
        MessageType.VIDEO, MessageType.DOCUMENT,
    ):
        logger.info(
            f"[Dispatcher] 媒体消息已入队，media_url={msg.media_url}, "
            f"client={msg.client_id}"
        )
        return UniversalResponse(text="收到您发送的媒体文件，已转入处理队列，稍后会有专员跟进。")

    # ---- 未知类型 -------------------------------------------------- #
    if msg.message_type == MessageType.UNKNOWN:
        return UniversalResponse(text="抱歉，暂时无法识别该消息类型，请发送文字消息或联系人工客服。")

    # ---- 文本消息 TEXT -------------------------------------------- #
    text = msg.content.strip()
    text_lower = text.lower()

    # Tier-0：纯文本关键字匹配
    for keyword, reply in _TIER0_PLAIN.items():
        if keyword.lower() in text_lower:
            logger.debug(f"[Dispatcher] Tier-0 plain 命中: '{keyword}'")
            return UniversalResponse(text=reply)

    # Tier-0：携带按钮的关键字匹配
    if any(k in text_lower for k in ("help", "帮助", "menu", "菜单")):
        logger.debug("[Dispatcher] Tier-0 help 命中 → action_card")
        return UniversalResponse(
            text="您好！以下是我能为您提供的服务，请选择：",
            buttons=_HELP_BUTTONS,
        )

    if any(k in text_lower for k in ("人工客服", "人工", "escalate", "agent")):
        logger.debug("[Dispatcher] Tier-0 escalate 命中 → action_card")
        return UniversalResponse(
            text="是否需要转接人工客服？转接后将由专属客服继续为您服务。",
            buttons=_ESCALATE_BUTTONS,
        )

    # Tier-1：RAG 自动回复（接入真实 LLM 时替换）
    return await _rag_auto_reply(msg)


async def _handle_action(msg: UniversalMessage) -> UniversalResponse:
    """
    处理 Inline Keyboard / Quick Reply 按钮回调。

    每个 action value 对应一条业务分支，可按需携带下一步引导按钮，
    形成完整的多轮对话状态机。
    """
    action_value = msg.content
    logger.info(f"[Dispatcher] ACTION callback: value='{action_value}' client={msg.client_id}")

    if action_value == "escalate":
        return UniversalResponse(
            text="是否确认转接人工客服？",
            buttons=_ESCALATE_BUTTONS,
        )

    if action_value == "escalate_confirm":
        return UniversalResponse(text="正在为您转接人工客服，请稍候…预计等待 2 分钟。")

    if action_value == "self_service":
        return UniversalResponse(
            text="好的！请继续描述您的问题，我会尽力为您解答。",
            buttons=_RAG_FALLBACK_BUTTONS,
        )

    if action_value == "check_status":
        return UniversalResponse(text="请告知您的任务 ID，我将立即查询进度。")

    if action_value == "pricing":
        return UniversalResponse(
            text="ClipFlow 视频生成按以下标准计费：\n• 15s 视频：¥0.5\n• 30s 视频：¥0.9\n• 60s 视频：¥1.6\n\n如需批量定价，请联系客服。",
            buttons=[{"label": "🎧 联系客服", "value": "escalate"}],
        )

    if action_value == "retry":
        return UniversalResponse(text="请重新描述您的问题，我将再次为您查询。")

    # 未知 action —— 优雅降级
    return UniversalResponse(
        text=f"已收到您的操作（{action_value}），正在处理中…",
    )


async def _rag_auto_reply(msg: UniversalMessage) -> UniversalResponse:
    """
    RAG 自动回复桩 (Stub)，返回带兜底按钮的 UniversalResponse。

    生产接入步骤：
      1. 从向量库检索与 msg.content 相关的知识片段
      2. 拼接为 system_prompt + context
      3. 调用 LLM Provider 生成自然语言回复
      4. 将 ticket_id 写入工单系统，追踪对话记录
      5. 将 LLM 回复 + 兜底按钮封装为 UniversalResponse 返回
    """
    logger.info(f"[Dispatcher] Tier-1 RAG 桩被触发，query='{msg.content[:80]}'")
    return UniversalResponse(
        text=(
            f"感谢您的提问！\n"
            f"您的咨询已记录（ID: {msg.message_id[:8]}），"
            f"我们的智能助手正在分析中，请稍后…"
        ),
        buttons=_RAG_FALLBACK_BUTTONS,
    )
