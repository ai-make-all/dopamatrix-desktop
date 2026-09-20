"""Cloudflare KV tracking-link adapter with explicit packaged enablement."""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from contextlib import closing
from typing import Optional

from src.api.runtime_paths import RuntimeMode, get_runtime_paths
from src.api.secret_store import CF_API_TOKEN, SecretStoreError, load_runtime_secret


logger = logging.getLogger(__name__)
_DEFAULT_BASE_URL = "https://dopa.mx/t/"
_ENABLE_SETTING = "cloudflare_tracking_enabled"


def _read_machine_setting(key_name: str) -> str | None:
    """Bounded non-secret machine-setting read; absence is safe-disabled."""
    try:
        with closing(sqlite3.connect(get_runtime_paths().settings_db_path)) as conn:
            row = conn.execute(
                "SELECT key_value FROM app_settings WHERE key_name = ?;",
                (key_name,),
            ).fetchone()
            return None if row is None else str(row[0])
    except sqlite3.Error:
        return None


def _is_enabled(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class CloudflareKVAdapter:
    """Generate local links by default and write KV only when fully enabled.

    In packaged mode a secure token is necessary but never sufficient:
    ``cloudflare_tracking_enabled`` must also be true and the non-secret
    account/namespace configuration must be complete. Source development keeps
    its historical environment convenience.
    """

    def __init__(
        self,
        *,
        api_token: str | None = None,
        enabled: str | bool | None = None,
        account_id: str | None = None,
        namespace_id: str | None = None,
        base_url: str | None = None,
    ) -> None:
        mode = get_runtime_paths().mode
        self.base_url = (
            base_url or os.getenv("SHORT_LINK_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/") + "/"
        self._account_id: Optional[str] = account_id or os.getenv("CF_ACCOUNT_ID")
        self._namespace_id: Optional[str] = namespace_id or os.getenv("CF_NAMESPACE_ID")

        if mode is RuntimeMode.PACKAGED:
            self._enabled = _is_enabled(
                _read_machine_setting(_ENABLE_SETTING) if enabled is None else enabled
            )
            try:
                self._api_token = api_token or (
                    load_runtime_secret(CF_API_TOKEN) if self._enabled else None
                )
            except (SecretStoreError, OSError):
                self._api_token = None
        elif mode is RuntimeMode.SOURCE_DEVELOPMENT:
            try:
                self._api_token = api_token or load_runtime_secret(
                    CF_API_TOKEN,
                    development_environment_key="CF_API_TOKEN",
                )
            except (SecretStoreError, OSError):
                self._api_token = None
            # Preserve source-development convenience while tests remain
            # deterministic unless they inject a token explicitly.
            self._enabled = bool(self._api_token) if enabled is None else _is_enabled(enabled)
        else:
            self._api_token = api_token
            self._enabled = bool(api_token) if enabled is None else _is_enabled(enabled)

        self._mock_mode = not bool(
            self._enabled
            and self._api_token
            and self._account_id
            and self._namespace_id
        )
        if self._mock_mode:
            logger.info("[TrackingAdapter] Cloudflare tracking is safely disabled")

    def generate_short_link(self, target_url: str, variant_id: str) -> str:
        short_code = uuid.uuid4().hex[:6]
        short_link = f"{self.base_url}{short_code}"
        if self._mock_mode:
            logger.info(
                "[Tracking/Mock] link generated variant=%.8s",
                variant_id,
            )
            return short_link

        self._write_to_cf_kv(short_code, target_url, variant_id)
        logger.info("[Tracking/CF] KV write completed variant=%.8s", variant_id)
        return short_link

    def _write_to_cf_kv(self, short_code: str, target_url: str, variant_id: str) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("CLOUDFLARE_CLIENT_UNAVAILABLE") from exc

        url = (
            f"https://api.cloudflare.com/client/v4/accounts/{self._account_id}"
            f"/storage/kv/namespaces/{self._namespace_id}/values/{short_code}"
        )
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "text/plain",
        }
        try:
            response = httpx.put(url, content=target_url, headers=headers, timeout=10.0)
            response.raise_for_status()
        except Exception as exc:
            logger.error(
                "[Tracking] Cloudflare KV write failed variant=%.8s error=%s",
                variant_id,
                type(exc).__name__,
            )
            raise RuntimeError("CLOUDFLARE_WRITE_FAILED") from exc
