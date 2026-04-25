"""
src/api/ws_manager.py
——————————————————————————————————————————————————————————————————————————
统一事件总线 — WebSocket 广播中枢 v2（安全鉴权 + 定向推送）

架构升级说明（v1 → v2）：
  v1：List[WebSocket] 全局广播，无鉴权。
  v2：
    ① 引入"一次性船票 (One-Time Ticket)"机制，阻断未鉴权连接。
    ② 连接池从 List 升级为 Dict[user_id → List[WebSocket]]，实现多租户隔离。
    ③ broadcast / broadcast_sync 支持定向推送（传 user_id）或全员广播（不传）。

信封协议（不变）：
  {"type": str, "payload": dict}
  已知 type：WS_UPDATE | ALERT | COPILOT_PROPOSAL

船票生命周期：
  前端          →  POST /api/v1/auth/ws-ticket      →  获取 ticket（10s 有效）
  前端          →  WS  /ws/events?ticket=xxx        →  consume_ticket 原子消费
  鉴权成功      →  user_id 绑定 WebSocket 连接      →  进入定向推送池
  10s 内未使用  →  ticket 自动过期，被 GC 清除      →  需重新申请

设计约束：
  - 禁止引入 Redis。ticket 存储使用内存 dict + monotonic 时间戳。
  - threading.Lock 保证 TicketStore 的 issue/consume 操作在跨线程场景下原子安全。
  - 连接池操作（connect/disconnect/broadcast）均在 asyncio 主线程执行，无需加锁。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import Future
from typing import Dict, List, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


# ====================================================================== #
# TicketStore — 一次性船票存储（内存实现，禁用 Redis）                     #
# ====================================================================== #

class TicketStore:
    """
    一次性船票池（One-Time Ticket Store）。

    设计目标：
      - 极简：仅使用 Python 原生 dict + threading.Lock，零外部依赖。
      - 安全：每张船票仅能被消费一次（consume 后立即删除，防止重放攻击）。
      - 自洁：issue 时顺带清理已过期的僵尸票，防止内存无限增长。

    并发模型：
      - issue_ticket 可能来自 async 路由（主线程），consume_ticket 同样如此。
      - 未来若从同步线程调用，threading.Lock 提供线程安全保障。
    """

    #: 船票有效期（秒）。10 秒足够前端完成"拿票→建连"的 RTT，同时控制攻击面。
    TICKET_TTL_SECONDS: int = 10

    def __init__(self) -> None:
        # 结构：{ ticket_str: (user_id, expire_at_monotonic) }
        self._store: Dict[str, tuple[str, float]] = {}
        self._lock  = threading.Lock()

    # ------------------------------------------------------------------ #
    # 公开接口                                                              #
    # ------------------------------------------------------------------ #

    def issue_ticket(self, user_id: str) -> str:
        """
        为指定用户签发一张新的一次性船票。

        每次调用均生成全新 UUID4 hex 票号，旧票不受影响（支持同一用户多端并发）。
        调用时附带清理过期票，避免内存泄漏。

        Args:
            user_id: 请求建立 WS 连接的用户标识（来自 X-Local-User 请求头）。

        Returns:
            32 位小写 hex 字符串票号（UUID4 无连字符）。
        """
        ticket = uuid.uuid4().hex
        expire_at = time.monotonic() + self.TICKET_TTL_SECONDS

        with self._lock:
            self._purge_expired_unsafe()          # 顺手 GC，不单独加锁
            self._store[ticket] = (user_id, expire_at)

        logger.debug(
            "[TicketStore] 签发船票 user=%s ticket=%s...（TTL=%ds）",
            user_id, ticket[:8], self.TICKET_TTL_SECONDS,
        )
        return ticket

    def consume_ticket(self, ticket: str) -> Optional[str]:
        """
        原子消费一张船票，返回绑定的 user_id。

        原子性保证：
          在 Lock 保护范围内完成"查找 → 删除 → 校验过期"三步，
          确保同一 ticket 在任何并发场景下只能被成功消费一次。

        Args:
            ticket: 前端通过 WS query param 传入的票号字符串。

        Returns:
            有效时返回对应的 user_id；ticket 不存在或已过期则返回 None。
        """
        with self._lock:
            entry = self._store.get(ticket)
            if entry is None:
                logger.warning("[TicketStore] 无效票号（不存在或已被消费）: %s...", ticket[:8])
                return None

            user_id, expire_at = entry
            # 无论是否过期，立即删除——防止重放攻击，即使攻击者抢先到达也只成功一次
            del self._store[ticket]

        if time.monotonic() > expire_at:
            logger.warning(
                "[TicketStore] 船票已过期，拒绝上船 user=%s ticket=%s...",
                user_id, ticket[:8],
            )
            return None

        logger.info(
            "[TicketStore] 船票核销成功，欢迎上船 user=%s ticket=%s...",
            user_id, ticket[:8],
        )
        return user_id

    # ------------------------------------------------------------------ #
    # 内部维护                                                              #
    # ------------------------------------------------------------------ #

    def _purge_expired_unsafe(self) -> None:
        """清除所有已过期的票（调用方须持有 self._lock）。"""
        now = time.monotonic()
        expired_keys = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired_keys:
            del self._store[k]
        if expired_keys:
            logger.debug("[TicketStore] GC 清除 %d 张过期船票。", len(expired_keys))

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# ====================================================================== #
# ConnectionManager — 多租户 WebSocket 连接池（升级版）                    #
# ====================================================================== #

class ConnectionManager:
    """
    WebSocket 连接管理器（全局单例）。

    v2 升级点：
      - active_connections 从 List[WebSocket] 升级为 Dict[str, List[WebSocket]]
        实现按 user_id 的连接池隔离（同一用户可多端在线）。
      - connect / disconnect 均需传入 user_id 以维护正确的 bucket。
      - broadcast / broadcast_sync 新增可选 user_id 参数，支持定向推送。
      - 内置 TicketStore，通过 issue_ticket / consume_ticket 代理访问。

    线程模型（不变）：
      - connect / disconnect / broadcast：asyncio 主事件循环线程。
      - broadcast_sync：任意线程（通过 run_coroutine_threadsafe 桥接）。
    """

    def __init__(self) -> None:
        # 多租户连接池：{ user_id: [WebSocket, ...] }
        # defaultdict 确保访问不存在的 user_id 时自动创建空列表，无需提前初始化。
        self.active_connections: Dict[str, List[WebSocket]] = defaultdict(list)

        # 主线程事件循环引用（lifespan 注入）
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # 一次性船票存储（内聚在 Manager 内，对外统一暴露）
        self._ticket_store = TicketStore()

    # ================================================================== #
    # 船票代理接口（对外统一使用 manager.xxx_ticket 调用）                   #
    # ================================================================== #

    def issue_ticket(self, user_id: str) -> str:
        """签发一次性 WebSocket 鉴权船票（代理到 TicketStore）。"""
        return self._ticket_store.issue_ticket(user_id)

    def consume_ticket(self, ticket: str) -> Optional[str]:
        """原子消费船票，返回 user_id 或 None（代理到 TicketStore）。"""
        return self._ticket_store.consume_ticket(ticket)

    # ================================================================== #
    # 连接生命周期                                                          #
    # ================================================================== #

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        """
        完成握手并将连接注册至对应用户的 bucket。

        Args:
            websocket: FastAPI WebSocket 实例。
            user_id:   经船票鉴权后确认的用户标识。
        """
        await websocket.accept()
        self.active_connections[user_id].append(websocket)
        logger.info(
            "[EventBus] 用户 %s 建立 WS 连接，该用户当前连接数: %d，全局连接总数: %d",
            user_id,
            len(self.active_connections[user_id]),
            self._total_connections(),
        )

    def disconnect(self, websocket: WebSocket, user_id: Optional[str] = None) -> None:
        """
        从连接池移除指定连接（幂等，不存在时静默忽略）。

        Args:
            websocket: 需要移除的 WebSocket 实例。
            user_id:   已知时直接定位 bucket（快速路径）；
                       未知时遍历所有 bucket（慢速兜底路径）。
        """
        if user_id is not None and user_id in self.active_connections:
            # 快速路径：已知 bucket
            bucket = self.active_connections[user_id]
            if websocket in bucket:
                bucket.remove(websocket)
            # 清理空 bucket，避免 defaultdict 无限膨胀
            if not bucket:
                del self.active_connections[user_id]
        else:
            # 慢速兜底路径：遍历所有 bucket（仅在 user_id 缺失时触发，属罕见路径）
            for uid, bucket in list(self.active_connections.items()):
                if websocket in bucket:
                    bucket.remove(websocket)
                    if not bucket:
                        del self.active_connections[uid]
                    break

        logger.info(
            "[EventBus] WS 连接断开（user=%s），全局剩余连接总数: %d",
            user_id or "unknown",
            self._total_connections(),
        )

    # ================================================================== #
    # 广播 — 异步版本                                                        #
    # ================================================================== #

    async def broadcast(
        self,
        message: dict,
        user_id: Optional[str] = None,
    ) -> None:
        """
        向目标连接推送消息（协程版本，async 上下文专用）。

        Args:
            message: 信封格式消息 {"type": str, "payload": dict}。
            user_id: 指定时为定向推送（仅推给该用户的所有连接）；
                     为 None 时全员广播（所有用户的所有连接）。
        """
        # 根据 user_id 决定推送目标
        if user_id is not None:
            # 定向推送：复制 bucket，防止迭代期间被 disconnect 修改
            pairs: List[tuple[WebSocket, str]] = [
                (ws, user_id)
                for ws in list(self.active_connections.get(user_id, []))
            ]
        else:
            # 全员广播：展平所有 bucket
            pairs = [
                (ws, uid)
                for uid, bucket in list(self.active_connections.items())
                for ws in bucket
            ]

        if not pairs:
            return

        dead: List[tuple[WebSocket, str]] = []
        for ws, uid in pairs:
            try:
                await ws.send_json(message)
            except Exception as exc:
                logger.warning(
                    "[EventBus] 推送至 user=%s 失败，标记死亡连接: %r", uid, exc
                )
                dead.append((ws, uid))

        # 事后清理死亡连接
        for ws, uid in dead:
            self.disconnect(ws, uid)

    # ================================================================== #
    # 广播 — 同步版本（ThreadPoolExecutor 线程专用，同步→异步桥梁）           #
    # ================================================================== #

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        注入主线程事件循环。必须在 lifespan 启动阶段调用。

        Args:
            loop: asyncio.get_running_loop()（在 async 上下文中获取）。
        """
        self._loop = loop
        logger.info(
            "[EventBus] 主线程事件循环已注入（id=%d），broadcast_sync 桥梁就绪。",
            id(loop),
        )

    def broadcast_sync(
        self,
        message: dict,
        user_id: Optional[str] = None,
    ) -> None:
        """
        线程安全的同步推送（同步→异步跨上下文桥梁）。

        FFmpeg 渲染、矩阵工厂等任务运行于 ThreadPoolExecutor，无法直接 await。
        此方法通过 asyncio.run_coroutine_threadsafe 将 broadcast() 协程调度
        到主事件循环执行，5 秒超时防止工作线程永久挂起。

        Args:
            message: 信封格式消息 {"type": str, "payload": dict}。
            user_id: 同 broadcast()，传入则定向推送，不传则全员广播。
                     services.py 中推荐传入 tenant_id 实现精准投递。
        """
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_event_loop()
                logger.warning("[EventBus] broadcast_sync 降级获取事件循环，建议在 lifespan 中注入。")
            except RuntimeError:
                logger.error("[EventBus] broadcast_sync: 无法获取事件循环，消息丢弃。")
                return

        if not loop.is_running():
            logger.warning("[EventBus] broadcast_sync: 事件循环未运行，消息丢弃。")
            return

        future: Future = asyncio.run_coroutine_threadsafe(
            self.broadcast(message, user_id), loop
        )
        try:
            future.result(timeout=5.0)
        except TimeoutError:
            logger.error("[EventBus] broadcast_sync: 广播超时（>5s），请检查主事件循环健康状态。")
        except Exception as exc:
            logger.error("[EventBus] broadcast_sync: 广播异常: %r", exc)

    # ================================================================== #
    # 工具方法                                                              #
    # ================================================================== #

    @staticmethod
    def make_envelope(event_type: str, payload: dict) -> dict:
        """
        构建标准信封消息。

        Args:
            event_type: 事件类型（"WS_UPDATE" | "ALERT" | "COPILOT_PROPOSAL" | ...）
            payload:    业务数据字典。

        Returns:
            {"type": event_type, "payload": payload}
        """
        return {"type": event_type, "payload": payload}

    def _total_connections(self) -> int:
        """返回所有用户的连接总数（调试用）。"""
        return sum(len(v) for v in self.active_connections.values())

    def __repr__(self) -> str:
        return (
            f"<ConnectionManager "
            f"users={len(self.active_connections)} "
            f"total_connections={self._total_connections()} "
            f"pending_tickets={len(self._ticket_store)} "
            f"loop_injected={self._loop is not None}>"
        )


# ====================================================================== #
# 全局单例                                                                 #
# 整个应用通过 `from src.api.ws_manager import manager` 统一引用。         #
# ====================================================================== #
manager = ConnectionManager()
