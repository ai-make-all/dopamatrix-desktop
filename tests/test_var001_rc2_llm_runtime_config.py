from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import settings_router
from src.api.policy_profiles import load_applied_runtime_config_provider
from src.api.runtime_config import (
    DEFAULT_LLM_MODEL,
    DEFAULT_OPENAI_BASE_URL,
    LLM_MODEL_SETTING_KEY,
    OPENAI_BASE_URL_SETTING_KEY,
    LlmOperationalSettingsError,
    read_llm_operational_settings,
    save_llm_operational_settings,
    temporary_runtime_config_provider,
)
from src.api.runtime_paths import RuntimeMode, resolve_runtime_paths
from src.api.secret_store import OPENAI_API_KEY, SecretDecryptionFailed, SecretStore
from src.services import llm_provider


class _FakeProtector:
    scheme = "test-protector-v1"

    def protect(self, plaintext: bytes) -> bytes:
        return b"R2" + bytes(value ^ 0xA5 for value in plaintext)

    def unprotect(self, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(b"R2"):
            raise SecretDecryptionFailed()
        return bytes(value ^ 0xA5 for value in ciphertext[2:])


class LlmOperationalPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "dopamatrix.db"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_custom_values_persist_trim_and_blank_values_restore_defaults(self) -> None:
        saved = save_llm_operational_settings(
            self.db_path,
            openai_base_url="  https://api.gptsapi.net/v1  ",
            llm_model="  provider-model  ",
        )
        self.assertEqual(saved.openai_base_url, "https://api.gptsapi.net/v1")
        self.assertEqual(saved.llm_model, "provider-model")
        self.assertEqual(read_llm_operational_settings(self.db_path), saved)

        defaults = save_llm_operational_settings(
            self.db_path,
            openai_base_url="  ",
            llm_model="\t",
        )
        self.assertIsNone(defaults.openai_base_url)
        self.assertEqual(defaults.llm_model, DEFAULT_LLM_MODEL)
        with closing(sqlite3.connect(self.db_path)) as connection:
            rows = connection.execute(
                "SELECT key_name FROM app_settings WHERE key_name IN (?, ?);",
                (OPENAI_BASE_URL_SETTING_KEY, LLM_MODEL_SETTING_KEY),
            ).fetchall()
        self.assertEqual(rows, [])

    def test_invalid_or_credential_bearing_urls_are_rejected(self) -> None:
        for value in (
            "api.example.com/v1",
            "ftp://example.com",
            "not-a-url",
            "https://user:password@example.com/v1",
            "https://example.com/a path",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    LlmOperationalSettingsError,
                    "^OPENAI_BASE_URL_INVALID$",
                ):
                    save_llm_operational_settings(
                        self.db_path,
                        openai_base_url=value,
                        llm_model="model",
                    )


class LlmSettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "dopamatrix.db"
        self.store = SecretStore(self.db_path, _FakeProtector())
        app = FastAPI()
        app.include_router(settings_router.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temporary.cleanup()

    def test_api_separates_nonsecret_config_from_dpapi_secret(self) -> None:
        secret = "synthetic-rc2-api-key"
        with patch.object(
            settings_router,
            "get_default_secret_store",
            return_value=self.store,
        ):
            config_response = self.client.post(
                "/settings/llm/config",
                json={
                    "openai_base_url": " https://api.gptsapi.net/v1 ",
                    "llm_model": " provider-model ",
                },
            )
            secret_response = self.client.post(
                "/settings/llm",
                json={"api_key": secret},
            )
            read_response = self.client.get("/settings/llm")

        self.assertEqual(config_response.status_code, 200)
        self.assertEqual(config_response.json()["restart_required"], True)
        self.assertEqual(secret_response.status_code, 200)
        payload = read_response.json()
        self.assertEqual(payload["provider"], "OpenAI / Compatible API")
        self.assertEqual(payload["openai_base_url"], "https://api.gptsapi.net/v1")
        self.assertEqual(payload["llm_model"], "provider-model")
        self.assertTrue(payload["is_configured"])
        self.assertNotIn("api_key", payload)
        self.assertNotIn(secret, read_response.text)
        self.assertEqual(self.store.get_secret(OPENAI_API_KEY), secret)
        with closing(sqlite3.connect(self.db_path)) as connection:
            nonsecret_values = connection.execute(
                "SELECT key_value FROM app_settings;"
            ).fetchall()
        self.assertNotIn(secret, {row[0] for row in nonsecret_values})

    def test_api_rejects_invalid_base_url_without_persisting_it(self) -> None:
        with patch.object(
            settings_router,
            "get_default_secret_store",
            return_value=self.store,
        ):
            response = self.client.post(
                "/settings/llm/config",
                json={"openai_base_url": "ftp://example.com", "llm_model": "model"},
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "OPENAI_BASE_URL_INVALID")


class PackagedLlmResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.paths = resolve_runtime_paths(
            mode=RuntimeMode.TEST,
            runtime_root=self.root,
        )
        self.store = SecretStore(self.paths.settings_db_path, _FakeProtector())
        llm_provider.invalidate_api_key_cache()

    def tearDown(self) -> None:
        llm_provider.invalidate_api_key_cache()
        self.temporary.cleanup()

    def test_packaged_operational_settings_win_over_hostile_environment(self) -> None:
        save_llm_operational_settings(
            self.paths.settings_db_path,
            openai_base_url="https://configured.example/v1",
            llm_model="configured-model",
        )
        loaded = load_applied_runtime_config_provider(self.paths, self.store)
        with (
            temporary_runtime_config_provider(loaded),
            patch.object(sys, "frozen", True, create=True),
            patch.dict(
                os.environ,
                {
                    "OPENAI_BASE_URL": "https://development.example.invalid/v1",
                    "LLM_MODEL": "development-model",
                },
            ),
        ):
            provider = llm_provider.OpenAIProvider()

        self.assertEqual(provider._base_url, "https://configured.example/v1")
        self.assertEqual(provider.model, "configured-model")

    def test_explicit_caller_arguments_win_over_packaged_operational_settings(self) -> None:
        save_llm_operational_settings(
            self.paths.settings_db_path,
            openai_base_url="https://configured.example/v1",
            llm_model="configured-model",
        )
        loaded = load_applied_runtime_config_provider(self.paths, self.store)
        with (
            temporary_runtime_config_provider(loaded),
            patch.object(sys, "frozen", True, create=True),
        ):
            provider = llm_provider.OpenAIProvider(
                base_url=" https://explicit.example/v1 ",
                model=" explicit-model ",
            )
        self.assertEqual(provider._base_url, "https://explicit.example/v1")
        self.assertEqual(provider.model, "explicit-model")

    def test_startup_mapping_is_immutable_until_configuration_reload(self) -> None:
        save_llm_operational_settings(
            self.paths.settings_db_path,
            openai_base_url="https://first.example/v1",
            llm_model="first-model",
        )
        first = load_applied_runtime_config_provider(self.paths, self.store)
        save_llm_operational_settings(
            self.paths.settings_db_path,
            openai_base_url="https://second.example/v1",
            llm_model="second-model",
        )
        self.assertEqual(
            first.static_operational_mapping[OPENAI_BASE_URL_SETTING_KEY],
            "https://first.example/v1",
        )
        restarted = load_applied_runtime_config_provider(self.paths, self.store)
        self.assertEqual(
            restarted.static_operational_mapping[OPENAI_BASE_URL_SETTING_KEY],
            "https://second.example/v1",
        )
        self.assertEqual(
            restarted.static_operational_mapping[LLM_MODEL_SETTING_KEY],
            "second-model",
        )

    def test_packaged_absent_settings_ignore_environment_and_use_defaults(self) -> None:
        loaded = load_applied_runtime_config_provider(self.paths, self.store)
        with (
            temporary_runtime_config_provider(loaded),
            patch.object(sys, "frozen", True, create=True),
            patch.dict(
                os.environ,
                {
                    "OPENAI_BASE_URL": "https://development.example.invalid/v1",
                    "LLM_MODEL": "development-model",
                },
            ),
        ):
            provider = llm_provider.OpenAIProvider()
        self.assertEqual(provider._base_url, DEFAULT_OPENAI_BASE_URL)
        self.assertEqual(provider.model, DEFAULT_LLM_MODEL)

    def test_real_sdk_none_uses_hostile_env_but_packaged_default_blocks_it(self) -> None:
        hostile = "https://development.example.invalid/v1"
        loaded = load_applied_runtime_config_provider(self.paths, self.store)
        with patch.dict(os.environ, {"OPENAI_BASE_URL": hostile}, clear=False):
            dependency_client = llm_provider.openai.OpenAI(
                api_key="synthetic-no-network-key",
                base_url=None,
            )
            try:
                self.assertEqual(str(dependency_client.base_url).rstrip("/"), hostile)
            finally:
                dependency_client.close()

            with (
                temporary_runtime_config_provider(loaded),
                patch.object(sys, "frozen", True, create=True),
            ):
                provider = llm_provider.OpenAIProvider()
                packaged_client = llm_provider.openai.OpenAI(
                    api_key="synthetic-no-network-key",
                    base_url=provider._base_url,
                )
            try:
                self.assertEqual(provider._base_url, DEFAULT_OPENAI_BASE_URL)
                self.assertEqual(
                    str(packaged_client.base_url).rstrip("/"),
                    DEFAULT_OPENAI_BASE_URL,
                )
                self.assertNotEqual(
                    str(packaged_client.base_url).rstrip("/"),
                    hostile,
                )
            finally:
                packaged_client.close()

    def test_real_sdk_configured_proxy_wins_over_hostile_environment(self) -> None:
        proxy = "https://api.gptsapi.net/v1"
        hostile = "https://development.example.invalid/v1"
        save_llm_operational_settings(
            self.paths.settings_db_path,
            openai_base_url=proxy,
            llm_model="configured-model",
        )
        loaded = load_applied_runtime_config_provider(self.paths, self.store)
        with (
            temporary_runtime_config_provider(loaded),
            patch.object(sys, "frozen", True, create=True),
            patch.dict(os.environ, {"OPENAI_BASE_URL": hostile}, clear=False),
        ):
            provider = llm_provider.OpenAIProvider()
            packaged_client = llm_provider.openai.OpenAI(
                api_key="synthetic-no-network-key",
                base_url=provider._base_url,
            )
        try:
            effective = str(packaged_client.base_url).rstrip("/")
            self.assertEqual(provider._base_url, proxy)
            self.assertEqual(effective, proxy)
            self.assertNotEqual(effective, hostile)
            self.assertNotEqual(effective, DEFAULT_OPENAI_BASE_URL)
        finally:
            packaged_client.close()

    def test_provider_constructs_client_with_configured_endpoint_and_model(self) -> None:
        self.store.set_secret(OPENAI_API_KEY, "synthetic-provider-secret")
        save_llm_operational_settings(
            self.paths.settings_db_path,
            openai_base_url="https://configured.example/v1",
            llm_model="configured-model",
        )
        loaded = load_applied_runtime_config_provider(self.paths, self.store)
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: response)
            )
        )
        captured_request: dict[str, object] = {}

        def create_completion(**kwargs):
            captured_request.update(kwargs)
            return response

        client.chat.completions.create = create_completion
        with (
            temporary_runtime_config_provider(loaded),
            patch.object(sys, "frozen", True, create=True),
            patch.object(llm_provider, "get_default_secret_store", return_value=self.store),
            patch.object(llm_provider.openai, "OpenAI", return_value=client) as constructor,
        ):
            result = llm_provider.OpenAIProvider().generate_script("prompt", "system")

        self.assertEqual(result, {"ok": True})
        constructor.assert_called_once_with(
            api_key="synthetic-provider-secret",
            base_url="https://configured.example/v1",
        )
        self.assertEqual(captured_request["model"], "configured-model")


if __name__ == "__main__":
    unittest.main()
