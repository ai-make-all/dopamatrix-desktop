"""
src/services/tracking_adapter.py
—————————————————————————————————
Phase 9.12 — Cloudflare KV 短链归因适配器

职责：
  - 为每个 APPROVED 视频变体生成唯一短链接（短码 → CF KV 持久化）
  - 短链格式：{BASE_SHORT_URL}/{short_code}（默认域名 https://dopa.mx/t/）
  - 当前实现：本地 UUID 模拟 + 日志记录（CF KV 写入逻辑预留，开启即可激活）
  - 环境变量：CF_ACCOUNT_ID、CF_NAMESPACE_ID、CF_API_TOKEN、SHORT_LINK_BASE_URL

接入 CF KV 的方式：
  1. 设置上述四个环境变量
  2. 取消 _write_to_cf_kv 方法中的注释代码块
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://dopa.mx/t/"


class CloudflareKVAdapter:
    """
    Cloudflare KV 短链生成适配器。

    generate_short_link(target_url, variant_id) → str
      返回可公开访问的短链接 URL。

    当 CF_API_TOKEN 环境变量存在时，自动激活真实 KV 写入；
    否则仅本地生成短码并写日志（Mock 模式，不影响 ZIP 导出流程）。
    """

    def __init__(self) -> None:
        self.base_url: str = os.getenv("SHORT_LINK_BASE_URL", _DEFAULT_BASE_URL).rstrip("/") + "/"
        self._account_id: Optional[str] = os.getenv("CF_ACCOUNT_ID")
        self._namespace_id: Optional[str] = os.getenv("CF_NAMESPACE_ID")
        self._api_token: Optional[str] = os.getenv("CF_API_TOKEN")
        self._mock_mode: bool = not bool(self._api_token)
        if self._mock_mode:
            logger.info(
                "[TrackingAdapter] CF_API_TOKEN 未配置，运行于 Mock 模式 — "
                "短链仅本地生成，不会写入 Cloudflare KV。"
            )

    # ── 公开接口 ─────────────────────────────────────────────────────────

    def generate_short_link(self, target_url: str, variant_id: str) -> str:
        """
        为指定目标 URL 生成归因短链接。

        Args:
            target_url:  长链接（含 UTM 参数），如 https://your-domain.com/landing?vid=xxx
            variant_id:  变体唯一标识（asset_hash 或任意 UUID 字符串），仅用于日志溯源。

        Returns:
            短链接字符串，如 https://dopa.mx/t/a3f8e1
        """
        short_code = uuid.uuid4().hex[:6]
        short_link = f"{self.base_url}{short_code}"

        if self._mock_mode:
            logger.info(
                "🔗 [Tracking/Mock] 短链已生成: %s → %s (Variant: %.8s)",
                short_link, target_url, variant_id,
            )
            return short_link

        # ── 真实 CF KV 写入 ───────────────────────────────────────────────
        self._write_to_cf_kv(short_code, target_url, variant_id)
        logger.info(
            "🔗 [Tracking/CF] 短链已写入 KV: %s → %s (Variant: %.8s)",
            short_link, target_url, variant_id,
        )
        return short_link

    # ── 内部方法 ─────────────────────────────────────────────────────────

    def _write_to_cf_kv(self, short_code: str, target_url: str, variant_id: str) -> None:
        """
        将 short_code → target_url 的映射写入 Cloudflare KV Namespace。

        使用同步 httpx 调用（适合 FastAPI 非 async 端点）。
        若需切换为 async，请改用 httpx.AsyncClient 并 await。
        """
        try:
            import httpx  # 延迟导入，避免未安装时在 mock 模式下报错
        except ImportError as exc:
            logger.error("[Tracking] httpx 未安装，无法写入 CF KV: %s", exc)
            raise RuntimeError("httpx 未安装，无法写入 Cloudflare KV") from exc

        url = (
            f"https://api.cloudflare.com/client/v4/accounts/{self._account_id}"
            f"/storage/kv/namespaces/{self._namespace_id}/values/{short_code}"
        )
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "text/plain",
        }
        try:
            resp = httpx.put(url, content=target_url, headers=headers, timeout=10.0)
            resp.raise_for_status()
        except Exception as exc:
            logger.error(
                "[Tracking] CF KV 写入失败 (short_code=%s, variant=%.8s): %s",
                short_code, variant_id, exc,
            )
            raise
