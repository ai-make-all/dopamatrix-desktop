"""
src/services/reporting.py
—————————————————————————
出片战报播报服务 — 分级事件路由架构（Tiered Event Routing）

职责：
  - 定义三级通知层级（L1 操作级 / L2 里程碑 / L3 深度洞察）
  - 通过 NotificationRouter 根据 tier + tenant_id 决定消息收件人
  - 将"出片通知"降级为 L1，只发内部运营群，彻底消除客户侧通知疲劳
  - 为多租户客户专属群组预留无需重构的扩展口

通知路由规则：
  L1_OPERATOR  → INTERNAL_OPS_CHAT_ID（内部运营群，如菲律宾团队）
  L2_MILESTONE → CLIENT_REPORTING_CHAT_ID + INTERNAL_OPS_CHAT_ID（抄送）
  L3_ANALYTIC  → CLIENT_REPORTING_CHAT_ID + INTERNAL_OPS_CHAT_ID（抄送）

环境变量：
  INTERNAL_OPS_CHAT_ID      — 内部操作员群 chat_id（L1 收件人）
  CLIENT_REPORTING_CHAT_ID  — 默认客户群 chat_id（L2/L3 收件人，MVP 阶段）
  TELEGRAM_BOT_TOKEN        — Bot Token（由 TelegramAdapter 自动读取）
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Dict, List, Optional

from src.core.logger import logger
from src.services.messaging.adapters.telegram_adapter import TelegramAdapter


# ================================================================== #
# 通知层级枚举                                                          #
# ================================================================== #

class NotificationTier(str, Enum):
    L1_OPERATOR  = "l1_operator"   # 内部操作级：单条出片、队列状态。仅发给内部运营团队。
    L2_MILESTONE = "l2_milestone"  # 交付里程碑：今日批量投放完毕等。发给客户 + 内部抄送。
    L3_ANALYTIC  = "l3_analytic"   # 深度洞察：周报、情绪转化率分析等。发给客户 + 内部抄送。


# ================================================================== #
# 分级路由调度器                                                        #
# ================================================================== #

class NotificationRouter:
    """
    根据 NotificationTier 和 tenant_id 决定将消息发送给哪些 chat_id。

    多租户扩展口：_get_target_chat_ids 中留有数据库查询钩子，
    待 tenant 表建立后，将 default_client_chat_id 替换为
    `await db.get_client_chat_group(tenant_id)` 即可，无需其他改动。
    """

    def __init__(self) -> None:
        self.adapter = TelegramAdapter()
        # L1 收件人：内部运营群（菲律宾团队 / 研发值班）
        self.internal_chat_id = os.getenv("INTERNAL_OPS_CHAT_ID", "").strip() or None
        # L2/L3 默认收件人：客户汇报群（MVP 阶段单租户使用）
        self.default_client_chat_id = os.getenv("CLIENT_REPORTING_CHAT_ID", "").strip() or None

    async def _get_target_chat_ids(
        self,
        tier: NotificationTier,
        tenant_id: Optional[str],
    ) -> List[str]:
        """
        核心路由逻辑：根据事件层级和租户返回目标 chat_id 列表。

        扩展说明：
          L2/L3 的客户群目前从 CLIENT_REPORTING_CHAT_ID 环境变量读取。
          多租户上线后，替换为：
            client_chat = await db.get_client_chat_group(tenant_id)
        """
        targets: List[str] = []

        if tier == NotificationTier.L1_OPERATOR:
            # 纯内部事件，绝不触达客户
            if self.internal_chat_id:
                targets.append(self.internal_chat_id)

        elif tier in (NotificationTier.L2_MILESTONE, NotificationTier.L3_ANALYTIC):
            # 客户侧主收件人
            # TODO(multi-tenant): 替换为 await db.get_client_chat_group(tenant_id)
            if self.default_client_chat_id:
                targets.append(self.default_client_chat_id)
            # 内部抄送，方便客服跟进交付进度
            if self.internal_chat_id and self.internal_chat_id not in targets:
                targets.append(self.internal_chat_id)

        return targets

    async def dispatch(
        self,
        tier: NotificationTier,
        text: str,
        buttons: Optional[List[Dict[str, str]]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        """
        统一发送出口。

        遍历目标 chat_id 列表逐一发送，单个目标失败不阻断其他目标。
        """
        target_chats = await self._get_target_chat_ids(tier, tenant_id)

        if not target_chats:
            logger.warning(
                f"[Reporting] tier={tier.value} tenant={tenant_id or 'default'} "
                f"— 无可用目标 chat_id，跳过发送。"
                f"请检查 INTERNAL_OPS_CHAT_ID / CLIENT_REPORTING_CHAT_ID 环境变量。"
            )
            return

        for chat_id in target_chats:
            try:
                if buttons:
                    await self.adapter.send_action_card(chat_id, text, buttons)
                else:
                    await self.adapter.send_text(chat_id, text)
                logger.debug(f"[Reporting] tier={tier.value} → chat_id={chat_id} 发送成功")
            except Exception as exc:
                logger.error(f"[Reporting] 发送至 chat_id={chat_id} 失败: {exc}")


# ================================================================== #
# 公开业务函数                                                          #
# ================================================================== #

async def notify_task_result(payload: dict, tenant_id: Optional[str] = None) -> None:
    """
    矩阵工厂出片结案通知（L1_OPERATOR 级）。

    定级理由：单条任务出片属于内部颗粒度操作事件，不应直接触达客户。
    客户侧汇报应在 L2 里程碑聚合后（如"今日全部50条投放完毕"）统一推送。

    payload 结构（与 services.py 中的 _report_payload 保持一致）：
      {
        "task_id":            int,
        "session_id":         str,
        "status":             "completed" | "failed",
        "assets":             [{"path": ..., "hash": ..., "download_url": ...}],
        "estimated_cost_usd": float,
        "client_payload":     {"test_user": ..., ...} | None,
      }
    """
    router = NotificationRouter()

    task_id      = payload.get("task_id")
    status       = payload.get("status")
    cost         = payload.get("estimated_cost_usd", 0)
    trigger_user = (payload.get("client_payload") or {}).get("test_user", "System")

    if status == "completed":
        assets       = payload.get("assets", [])
        download_url = assets[0].get("download_url") if assets else None

        text = (
            f"⚡️ <b>[DopaMatrix · OPS] 出片通知</b>\n\n"
            f"🆔 任务编号: <code>#{task_id}</code>\n"
            f"✅ 渲染状态: <b>COMPLETED</b>\n"
            f"👤 触发用户: <code>{trigger_user}</code>\n"
            f"💰 算力消耗: <code>${cost}</code>\n\n"
            f"👇 母带变体已就绪，内部预览："
        )

        buttons: List[Dict[str, str]] = []
        if download_url:
            buttons.append({"label": "📥 预览 / 下载成片", "url": download_url})

        await router.dispatch(
            tier=NotificationTier.L1_OPERATOR,
            text=text,
            buttons=buttons or None,
            tenant_id=tenant_id,
        )
        logger.info(f"[Reporting 🚀] L1 出片战报已发送 | task_id={task_id}")

    elif status == "failed":
        text = (
            f"❌ <b>[DopaMatrix · OPS] 任务异常报警</b>\n\n"
            f"任务 <code>#{task_id}</code> 处理失败，请研发团队介入排查。\n"
            f"触发用户: <code>{trigger_user}</code>"
        )
        await router.dispatch(
            tier=NotificationTier.L1_OPERATOR,
            text=text,
            tenant_id=tenant_id,
        )
        logger.info(f"[Reporting ⚠️] L1 异常告警已发送 | task_id={task_id}")
