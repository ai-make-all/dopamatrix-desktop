from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
import traceback
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import routes_gateway, settings_router
from src.api import secret_store as secret_store_module
from src.api.database import get_tenant_engine
from src.api.runtime_paths import RuntimeMode, temporary_test_runtime_paths
from src.api.secret_store import (
    CF_API_TOKEN,
    DPAPI_CURRENT_USER_V1,
    KNOWN_SECRET_KEYS,
    OPENAI_API_KEY,
    PEXELS_API_KEY,
    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
    TELEGRAM_BOT_TOKEN,
    OpenAISecretMigrationConflict,
    OpenAISecretMigrationResult,
    SecretDecryptionFailed,
    SecretEncryptionFailed,
    SecretKeyUnrecognized,
    SecretSchemeUnsupported,
    SecretStatus,
    SecretStore,
    SecretValueCorrupt,
    WindowsDpapiProtector,
    inspect_openai_secret_state,
    load_runtime_secret,
    migrate_legacy_openai_secret,
    read_openai_secret_for_use,
    replace_openai_secret,
)
from src.services import asset_provider, llm_provider, reporting, tracking_adapter
from src.services.messaging.adapters import telegram_adapter
from src.services.messaging.contract import MessageType, UniversalMessage, UniversalResponse


class FakeProtector:
    scheme = "test-protector-v1"

    def protect(self, plaintext: bytes) -> bytes:
        return b"T1" + bytes(value ^ 0xA5 for value in plaintext)

    def unprotect(self, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(b"T1"):
            raise SecretDecryptionFailed()
        return bytes(value ^ 0xA5 for value in ciphertext[2:])


class FailingProtector(FakeProtector):
    def protect(self, plaintext: bytes) -> bytes:
        raise SecretEncryptionFailed()


def create_legacy_row(db_path: Path, value: str) -> None:
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app_settings "
            "(key_name TEXT PRIMARY KEY, key_value TEXT);"
        )
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key_name, key_value) VALUES (?, ?);",
            ("openai_api_key", value),
        )


def legacy_value(db_path: Path) -> str | None:
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT key_value FROM app_settings WHERE key_name = 'openai_api_key';"
        ).fetchone()
        return None if row is None else row[0]


class SecretStoreFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "global.db"
        self.store = SecretStore(self.db_path, FakeProtector())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_schema_is_idempotent_and_exact(self) -> None:
        self.store.ensure_schema()
        self.store.ensure_schema()
        with closing(sqlite3.connect(self.db_path)) as conn:
            columns = conn.execute("PRAGMA table_info(secure_settings);").fetchall()
        self.assertEqual(
            [column[1] for column in columns],
            ["key_name", "encryption_scheme", "ciphertext", "updated_at"],
        )
        self.assertEqual(columns[0][5], 1)

    def test_registry_is_fixed_and_unknown_key_is_rejected(self) -> None:
        self.assertEqual(
            KNOWN_SECRET_KEYS,
            {
                OPENAI_API_KEY,
                RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
                PEXELS_API_KEY,
                TELEGRAM_BOT_TOKEN,
                CF_API_TOKEN,
            },
        )
        with self.assertRaisesRegex(SecretKeyUnrecognized, "SECRET_KEY_UNRECOGNIZED"):
            self.store.set_secret("arbitrary_secret", "synthetic")

    def test_set_get_status_delete_and_assignment_capability(self) -> None:
        key = RESERVATION_ROLLOUT_ASSIGNMENT_SECRET
        self.assertEqual(self.store.get_status(key), SecretStatus.ABSENT)
        self.store.set_secret(key, "synthetic-assignment-value")
        self.assertEqual(self.store.get_secret(key), "synthetic-assignment-value")
        self.assertEqual(self.store.get_status(key), SecretStatus.PRESENT)
        self.store.delete_secret(key)
        self.assertIsNone(self.store.get_secret(key))
        self.assertEqual(self.store.get_status(key), SecretStatus.ABSENT)

    def test_ciphertext_is_blob_and_plaintext_is_absent_from_sqlite(self) -> None:
        synthetic = "synthetic-at-rest-value-74a31"
        self.store.set_secret(OPENAI_API_KEY, synthetic)
        raw_database = self.db_path.read_bytes()
        self.assertNotIn(synthetic.encode(), raw_database)
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT encryption_scheme, typeof(ciphertext), ciphertext "
                "FROM secure_settings WHERE key_name = ?;",
                (OPENAI_API_KEY,),
            ).fetchone()
        self.assertEqual(row[0], FakeProtector.scheme)
        self.assertEqual(row[1], "blob")
        self.assertIsInstance(row[2], bytes)
        self.assertEqual(self.store.get_secret(OPENAI_API_KEY), synthetic)

    def test_unknown_scheme_and_corrupt_ciphertext_fail_closed(self) -> None:
        self.store.ensure_schema()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO secure_settings VALUES (?, ?, ?, ?);",
                (OPENAI_API_KEY, "unknown-v9", sqlite3.Binary(b"cipher"), "now"),
            )
        with self.assertRaisesRegex(SecretSchemeUnsupported, "SECRET_SCHEME_UNSUPPORTED"):
            self.store.get_secret(OPENAI_API_KEY)

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE secure_settings SET encryption_scheme = ?, ciphertext = ? "
                "WHERE key_name = ?;",
                (FakeProtector.scheme, sqlite3.Binary(b"broken"), OPENAI_API_KEY),
            )
        with self.assertRaisesRegex(SecretDecryptionFailed, "SECRET_DECRYPTION_FAILED"):
            self.store.get_secret(OPENAI_API_KEY)
        self.assertEqual(self.store.get_status(OPENAI_API_KEY), SecretStatus.ERROR)

    def test_error_text_and_repr_do_not_contain_synthetic_secret(self) -> None:
        synthetic = "synthetic-never-log-92bb"
        failing = SecretStore(self.db_path, FailingProtector())
        with self.assertRaises(SecretEncryptionFailed) as raised:
            failing.set_secret(OPENAI_API_KEY, synthetic)
        self.assertNotIn(synthetic, str(raised.exception))
        self.assertNotIn(synthetic, repr(raised.exception))

    def test_secure_settings_is_global_only(self) -> None:
        with temporary_test_runtime_paths(self.root / "runtime") as paths:
            global_store = SecretStore(paths.settings_db_path, FakeProtector())
            global_store.ensure_schema()
            tenant = f"h2-{uuid.uuid4().hex}"
            engine = get_tenant_engine(tenant)
            tenant_db = paths.tenant_database_path(tenant)
            engine.dispose()
            with closing(sqlite3.connect(paths.settings_db_path)) as conn:
                global_tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table';"
                    )
                }
            with closing(sqlite3.connect(tenant_db)) as conn:
                tenant_tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table';"
                    )
                }
        self.assertIn("secure_settings", global_tables)
        self.assertNotIn("secure_settings", tenant_tables)


class OpenAIMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "settings.db"
        self.store = SecretStore(self.db_path, FakeProtector())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_no_legacy_no_secure_is_unconfigured(self) -> None:
        self.assertEqual(
            migrate_legacy_openai_secret(self.store),
            OpenAISecretMigrationResult.UNCONFIGURED,
        )
        state = inspect_openai_secret_state(self.store)
        self.assertFalse(state.is_configured)
        self.assertEqual(state.secret_status, SecretStatus.ABSENT)

    def test_legacy_only_migrates_verifies_and_deletes_plaintext(self) -> None:
        create_legacy_row(self.db_path, "synthetic-legacy-a")
        self.assertEqual(
            migrate_legacy_openai_secret(self.store),
            OpenAISecretMigrationResult.MIGRATED,
        )
        self.assertEqual(self.store.get_secret(OPENAI_API_KEY), "synthetic-legacy-a")
        self.assertIsNone(legacy_value(self.db_path))

    def test_secure_only_validates_and_is_idempotent(self) -> None:
        self.store.set_secret(OPENAI_API_KEY, "synthetic-secure-a")
        for _ in range(2):
            self.assertEqual(
                migrate_legacy_openai_secret(self.store),
                OpenAISecretMigrationResult.SECURE_ONLY,
            )

    def test_identical_legacy_is_removed_without_overwrite(self) -> None:
        self.store.set_secret(OPENAI_API_KEY, "synthetic-same")
        create_legacy_row(self.db_path, "synthetic-same")
        self.assertEqual(
            migrate_legacy_openai_secret(self.store),
            OpenAISecretMigrationResult.REDUNDANT_LEGACY_REMOVED,
        )
        self.assertEqual(self.store.get_secret(OPENAI_API_KEY), "synthetic-same")
        self.assertIsNone(legacy_value(self.db_path))

    def test_conflicting_values_are_preserved_and_feature_fails_closed(self) -> None:
        self.store.set_secret(OPENAI_API_KEY, "synthetic-secure")
        create_legacy_row(self.db_path, "synthetic-legacy")
        self.assertEqual(
            migrate_legacy_openai_secret(self.store),
            OpenAISecretMigrationResult.MIGRATION_CONFLICT,
        )
        self.assertEqual(self.store.get_secret(OPENAI_API_KEY), "synthetic-secure")
        self.assertEqual(legacy_value(self.db_path), "synthetic-legacy")
        with self.assertRaises(OpenAISecretMigrationConflict):
            read_openai_secret_for_use(self.store)

    def test_encryption_failure_preserves_only_legacy_value(self) -> None:
        create_legacy_row(self.db_path, "synthetic-preserved")
        failing = SecretStore(self.db_path, FailingProtector())
        self.assertEqual(
            migrate_legacy_openai_secret(failing),
            OpenAISecretMigrationResult.ERROR,
        )
        self.assertEqual(legacy_value(self.db_path), "synthetic-preserved")
        self.assertEqual(failing.get_status(OPENAI_API_KEY), SecretStatus.ABSENT)

    def test_corrupt_secure_never_falls_back_to_legacy(self) -> None:
        self.store.ensure_schema()
        create_legacy_row(self.db_path, "synthetic-legacy-fallback")
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO secure_settings VALUES (?, ?, ?, ?);",
                (OPENAI_API_KEY, FakeProtector.scheme, sqlite3.Binary(b"bad"), "now"),
            )
        self.assertEqual(
            migrate_legacy_openai_secret(self.store),
            OpenAISecretMigrationResult.ERROR,
        )
        self.assertEqual(legacy_value(self.db_path), "synthetic-legacy-fallback")
        with self.assertRaises(SecretDecryptionFailed):
            read_openai_secret_for_use(self.store)

    def test_explicit_replacement_resolves_conflict_atomically(self) -> None:
        self.store.set_secret(OPENAI_API_KEY, "synthetic-old-secure")
        create_legacy_row(self.db_path, "synthetic-old-legacy")
        replace_openai_secret(self.store, "synthetic-new-authority")
        self.assertEqual(
            read_openai_secret_for_use(self.store),
            "synthetic-new-authority",
        )
        self.assertIsNone(legacy_value(self.db_path))


class OpenAISettingsAndProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "settings.db"
        self.store = SecretStore(self.db_path, FakeProtector())
        self.app = FastAPI()
        self.app.include_router(settings_router.router)
        self.client = TestClient(self.app)
        llm_provider.invalidate_api_key_cache()

    def tearDown(self) -> None:
        llm_provider.invalidate_api_key_cache()
        self.client.close()
        self.temporary.cleanup()

    def test_post_writes_secure_only_get_returns_status_and_invalidates_cache(self) -> None:
        synthetic = "synthetic-api-setting-4a"
        create_legacy_row(self.db_path, "synthetic-old-plaintext")
        llm_provider._api_key_cache[OPENAI_API_KEY] = "synthetic-cached-old"
        with patch.object(settings_router, "get_default_secret_store", return_value=self.store):
            response = self.client.post("/settings/llm", json={"api_key": synthetic})
            status_response = self.client.get("/settings/llm")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        payload = status_response.json()
        self.assertEqual(
            payload,
            {
                "is_configured": True,
                "secret_status": "PRESENT",
                "migration_required": False,
            },
        )
        self.assertNotIn("api_key", payload)
        self.assertNotIn(synthetic, status_response.text)
        self.assertEqual(self.store.get_secret(OPENAI_API_KEY), synthetic)
        self.assertIsNone(legacy_value(self.db_path))
        self.assertNotIn(OPENAI_API_KEY, llm_provider._api_key_cache)

    def test_post_failure_response_is_secret_safe(self) -> None:
        synthetic = "synthetic-api-never-echo-5b"
        failing = SecretStore(self.db_path, FailingProtector())
        with patch.object(settings_router, "get_default_secret_store", return_value=failing):
            response = self.client.post("/settings/llm", json={"api_key": synthetic})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "LLM_SECRET_SAVE_FAILED")
        self.assertNotIn(synthetic, response.text)

    def test_provider_loads_secure_key_and_preserves_cache_invalidation(self) -> None:
        self.store.set_secret(OPENAI_API_KEY, "synthetic-provider-key")
        with patch.object(llm_provider, "get_default_secret_store", return_value=self.store):
            self.assertEqual(
                llm_provider._load_api_key_from_db(OPENAI_API_KEY),
                "synthetic-provider-key",
            )
            self.store.set_secret(OPENAI_API_KEY, "synthetic-provider-new")
            self.assertEqual(
                llm_provider._load_api_key_from_db(OPENAI_API_KEY),
                "synthetic-provider-key",
            )
            llm_provider.invalidate_api_key_cache(OPENAI_API_KEY)
            self.assertEqual(
                llm_provider._load_api_key_from_db(OPENAI_API_KEY),
                "synthetic-provider-new",
            )

    def test_provider_has_no_openai_environment_fallback(self) -> None:
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-env-must-not-win"}),
            patch.object(llm_provider, "get_default_secret_store", return_value=self.store),
        ):
            self.assertEqual(llm_provider._load_api_key_from_db(OPENAI_API_KEY), "")

    def test_provider_corruption_fails_with_bounded_message(self) -> None:
        self.store.ensure_schema()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO secure_settings VALUES (?, ?, ?, ?);",
                (OPENAI_API_KEY, FakeProtector.scheme, sqlite3.Binary(b"bad"), "now"),
            )
        with patch.object(llm_provider, "get_default_secret_store", return_value=self.store):
            with self.assertRaisesRegex(ValueError, "LLM_SECRET_UNAVAILABLE"):
                llm_provider._load_api_key_from_db(OPENAI_API_KEY)

    def test_conflict_blocks_provider_loader_and_openai_client_construction(self) -> None:
        legacy_secret = "synthetic-provider-conflict-legacy-a"
        secure_secret = "synthetic-provider-conflict-secure-b"
        self.store.set_secret(OPENAI_API_KEY, secure_secret)
        create_legacy_row(self.db_path, legacy_secret)
        self.assertEqual(
            migrate_legacy_openai_secret(self.store),
            OpenAISecretMigrationResult.MIGRATION_CONFLICT,
        )

        # Match the lifespan behavior before any provider request is accepted.
        llm_provider.invalidate_api_key_cache(OPENAI_API_KEY)
        with (
            patch.object(llm_provider, "get_default_secret_store", return_value=self.store),
            patch.object(llm_provider.openai, "OpenAI") as client_constructor,
        ):
            with self.assertRaisesRegex(ValueError, "^LLM_SECRET_UNAVAILABLE$") as load_error:
                llm_provider._load_api_key_from_db(OPENAI_API_KEY)

            provider = llm_provider.OpenAIProvider()
            with self.assertRaisesRegex(ValueError, "^LLM_SECRET_UNAVAILABLE$") as provider_error:
                provider.generate_script("prompt", "system")

        client_constructor.assert_not_called()
        for surface in (
            str(load_error.exception),
            repr(load_error.exception),
            str(provider_error.exception),
            repr(provider_error.exception),
        ):
            self.assertNotIn(legacy_secret, surface)
            self.assertNotIn(secure_secret, surface)


class OptionalCredentialSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = SecretStore(self.root / "settings.db", FakeProtector())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_packaged_source_uses_secure_store_not_environment(self) -> None:
        self.store.set_secret(PEXELS_API_KEY, "synthetic-secure-pexels")
        packaged_paths = SimpleNamespace(mode=RuntimeMode.PACKAGED)
        with (
            patch("src.api.secret_store.get_runtime_paths", return_value=packaged_paths),
            patch.dict(os.environ, {"PEXELS_API_KEY": "synthetic-env-pexels"}),
        ):
            value = load_runtime_secret(
                PEXELS_API_KEY,
                development_environment_key="PEXELS_API_KEY",
                store=self.store,
            )
        self.assertEqual(value, "synthetic-secure-pexels")

    def test_source_development_optional_secret_may_use_environment(self) -> None:
        dev_paths = SimpleNamespace(mode=RuntimeMode.SOURCE_DEVELOPMENT)
        with (
            patch("src.api.secret_store.get_runtime_paths", return_value=dev_paths),
            patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "synthetic-dev-token"}),
        ):
            value = load_runtime_secret(
                TELEGRAM_BOT_TOKEN,
                development_environment_key="TELEGRAM_BOT_TOKEN",
                store=self.store,
            )
        self.assertEqual(value, "synthetic-dev-token")

    def test_pexels_and_telegram_consumers_use_central_source(self) -> None:
        with patch.object(
            asset_provider,
            "load_runtime_secret",
            return_value="synthetic-pexels-consumer",
        ):
            provider = asset_provider.PexelsProvider(output_dir=str(self.root / "clips"))
        self.assertEqual(provider._api_key, "synthetic-pexels-consumer")

        with patch.object(
            telegram_adapter,
            "load_runtime_secret",
            return_value="synthetic-telegram-consumer",
        ):
            adapter = telegram_adapter.TelegramAdapter()
        self.assertEqual(adapter._token, "synthetic-telegram-consumer")

    def test_packaged_pexels_and_telegram_ignore_environment_values(self) -> None:
        self.store.set_secret(PEXELS_API_KEY, "synthetic-packaged-pexels")
        self.store.set_secret(TELEGRAM_BOT_TOKEN, "synthetic-packaged-telegram")
        packaged_paths = SimpleNamespace(mode=RuntimeMode.PACKAGED)
        with (
            patch.object(secret_store_module, "get_runtime_paths", return_value=packaged_paths),
            patch.object(secret_store_module, "get_default_secret_store", return_value=self.store),
            patch.dict(
                os.environ,
                {
                    "PEXELS_API_KEY": "synthetic-env-pexels-ignored",
                    "TELEGRAM_BOT_TOKEN": "synthetic-env-telegram-ignored",
                },
            ),
        ):
            pexels = asset_provider.PexelsProvider(output_dir=str(self.root / "packaged-clips"))
            telegram = telegram_adapter.TelegramAdapter()
        self.assertEqual(pexels._api_key, "synthetic-packaged-pexels")
        self.assertEqual(telegram._token, "synthetic-packaged-telegram")

    def test_missing_telegram_secret_disables_only_reporting(self) -> None:
        with patch.object(reporting, "TelegramAdapter", side_effect=ValueError("bounded")):
            router = reporting.NotificationRouter()
        self.assertIsNone(router.adapter)

    def test_telegram_http_exception_redacts_token_and_chained_context(self) -> None:
        synthetic_token = "synthetic-telegram-token-never-log-r2"
        adapter = telegram_adapter.TelegramAdapter(bot_token=synthetic_token)
        request = httpx.Request("POST", adapter._api_url("sendMessage"))
        raw_error = httpx.ConnectError(
            f"connection failed for {request.url}",
            request=request,
        )

        with (
            patch.object(
                telegram_adapter.httpx.AsyncClient,
                "post",
                new=AsyncMock(side_effect=raw_error),
            ),
            patch.object(telegram_adapter.logger, "warning") as warning_log,
            patch.object(telegram_adapter.logger, "error") as error_log,
        ):
            try:
                asyncio.run(adapter.send_text("chat", "hello"))
            except telegram_adapter.TelegramRequestFailed as exc:
                rendered_traceback = "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
                self.assertEqual(str(exc), "TELEGRAM_REQUEST_FAILED")
                self.assertNotIn(synthetic_token, str(exc))
                self.assertNotIn(synthetic_token, repr(exc))
                self.assertNotIn(synthetic_token, rendered_traceback)
                self.assertTrue(exc.__suppress_context__)
            else:  # pragma: no cover - assertion guard
                self.fail("TelegramRequestFailed was not raised")

        warning_log.assert_not_called()
        error_log.assert_not_called()

    def test_telegram_success_response_remains_supported(self) -> None:
        adapter = telegram_adapter.TelegramAdapter(bot_token="synthetic-telegram-success")
        response = httpx.Response(
            200,
            request=httpx.Request("POST", adapter._api_url("sendMessage")),
            json={"ok": True, "result": {"message_id": 1}},
        )
        with patch.object(
            telegram_adapter.httpx.AsyncClient,
            "post",
            new=AsyncMock(return_value=response),
        ):
            asyncio.run(adapter.send_text("chat", "hello"))

    def test_reporting_and_gateway_logs_and_public_response_redact_token(self) -> None:
        synthetic_token = "synthetic-telegram-upstream-never-log-r2"
        tokenized_url = f"https://api.telegram.org/bot{synthetic_token}/sendMessage"

        class LeakyReportingAdapter:
            async def send_text(self, chat_id: str, text: str) -> None:
                raise RuntimeError(tokenized_url)

        notification_router = object.__new__(reporting.NotificationRouter)
        notification_router.adapter = LeakyReportingAdapter()
        notification_router.internal_chat_id = "internal-chat"
        notification_router.default_client_chat_id = None
        with patch.object(reporting.logger, "error") as reporting_error:
            asyncio.run(
                notification_router.dispatch(
                    reporting.NotificationTier.L1_OPERATOR,
                    "message",
                )
            )
        self.assertNotIn(synthetic_token, repr(reporting_error.call_args_list))

        class LeakyGatewayAdapter:
            async def parse_incoming(self, raw_payload: dict) -> UniversalMessage:
                return UniversalMessage(
                    source_platform="telegram",
                    client_id="client",
                    reply_channel_id="chat",
                    message_type=MessageType.TEXT,
                    content="hello",
                )

            async def send_text(self, chat_id: str, text: str) -> None:
                raise RuntimeError(tokenized_url)

            async def send_action_card(self, chat_id: str, text: str, buttons: list) -> None:
                raise RuntimeError(tokenized_url)

        app = FastAPI()
        app.include_router(routes_gateway.router)
        with (
            patch.dict(
                routes_gateway.ADAPTER_REGISTRY,
                {"telegram": LeakyGatewayAdapter},
            ),
            patch.object(
                routes_gateway.dispatcher,
                "dispatch",
                new=AsyncMock(return_value=UniversalResponse(text="reply")),
            ),
            patch.object(routes_gateway.logger, "error") as gateway_error,
            TestClient(app) as client,
        ):
            response = client.post(
                "/webhook/telegram/receive",
                json={"message": {"text": "hello"}},
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(synthetic_token, response.text)
        self.assertNotIn(synthetic_token, repr(gateway_error.call_args_list))

    def test_packaged_cloudflare_requires_explicit_enable_and_complete_config(self) -> None:
        packaged_paths = SimpleNamespace(mode=RuntimeMode.PACKAGED)
        with (
            patch.object(tracking_adapter, "get_runtime_paths", return_value=packaged_paths),
            patch.object(tracking_adapter, "_read_machine_setting", return_value=None),
        ):
            token_only = tracking_adapter.CloudflareKVAdapter(
                api_token="synthetic-token-only",
                account_id="account",
                namespace_id="namespace",
            )
        self.assertTrue(token_only._mock_mode)

        with (
            patch.object(tracking_adapter, "get_runtime_paths", return_value=packaged_paths),
            patch.object(tracking_adapter, "_read_machine_setting", return_value="true"),
            patch.object(
                tracking_adapter,
                "load_runtime_secret",
                return_value="synthetic-secure-cloudflare",
            ),
            patch.dict(os.environ, {"CF_API_TOKEN": "synthetic-env-cloudflare-ignored"}),
        ):
            enabled = tracking_adapter.CloudflareKVAdapter(
                account_id="account",
                namespace_id="namespace",
            )
        self.assertFalse(enabled._mock_mode)
        self.assertEqual(enabled._api_token, "synthetic-secure-cloudflare")


@unittest.skipUnless(sys.platform == "win32", "Windows DPAPI integration only")
class WindowsDpapiIntegrationTests(unittest.TestCase):
    def test_current_user_round_trip_corruption_and_scheme_failure(self) -> None:
        synthetic = b"synthetic-dpapi-roundtrip-83f1"
        protector = WindowsDpapiProtector()
        self.assertEqual(protector.scheme, DPAPI_CURRENT_USER_V1)
        ciphertext = protector.protect(synthetic)
        self.assertNotEqual(ciphertext, synthetic)
        self.assertEqual(protector.unprotect(ciphertext), synthetic)
        corrupted = bytearray(ciphertext)
        corrupted[len(corrupted) // 2] ^= 0x01
        with self.assertRaises(SecretDecryptionFailed):
            protector.unprotect(bytes(corrupted))

        with tempfile.TemporaryDirectory() as temporary:
            store = SecretStore(Path(temporary) / "settings.db", protector)
            store.ensure_schema()
            with closing(sqlite3.connect(store.db_path)) as conn, conn:
                conn.execute(
                    "INSERT INTO secure_settings VALUES (?, ?, ?, ?);",
                    (OPENAI_API_KEY, "unknown-v99", sqlite3.Binary(ciphertext), "now"),
                )
            with self.assertRaises(SecretSchemeUnsupported):
                store.get_secret(OPENAI_API_KEY)


if __name__ == "__main__":
    unittest.main()
