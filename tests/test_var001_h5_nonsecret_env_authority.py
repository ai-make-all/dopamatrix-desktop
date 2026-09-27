from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.api.runtime_paths import RuntimeMode
from src.api.secret_store import CF_API_TOKEN
from src.services import llm_provider, reporting, tracking_adapter


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _probe_environment(temp_root: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not (
            key.startswith("RESERVATION_")
            or key.endswith("_SECRET")
            or key.endswith("_TOKEN")
            or key.endswith("_API_KEY")
        )
    }
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
    environment["LOCALAPPDATA"] = str(temp_root / "local-app-data")
    environment["APPDATA"] = str(temp_root / "roaming-app-data")
    return environment


def _run_cost_probe(*, frozen: bool) -> dict[str, float]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        probe = textwrap.dedent(
            f"""
            import json, os, sys
            os.environ['LLM_COST_PER_TOKEN'] = '9.25'
            os.environ['TTS_COST_PER_SEC'] = '8.75'
            sys.frozen = {frozen!r}
            from src.api import services
            print(json.dumps({{
                'llm': services._LLM_COST_PER_TOKEN,
                'tts': services._TTS_COST_PER_SEC,
            }}))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=REPOSITORY_ROOT,
            env=_probe_environment(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


class CostRateAuthorityTests(unittest.TestCase):
    def test_packaged_import_ignores_hostile_cost_environment(self) -> None:
        self.assertEqual(
            _run_cost_probe(frozen=True),
            {"llm": 0.000002, "tts": 0.000016},
        )

    def test_source_development_import_preserves_cost_environment(self) -> None:
        self.assertEqual(
            _run_cost_probe(frozen=False),
            {"llm": 9.25, "tts": 8.75},
        )


class LlmNonSecretAuthorityTests(unittest.TestCase):
    def test_packaged_ignores_endpoint_and_model_environment(self) -> None:
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.dict(
                os.environ,
                {
                    "OPENAI_BASE_URL": "https://hostile.example.invalid/v1",
                    "LLM_MODEL": "hostile-model",
                },
                clear=False,
            ),
        ):
            default_provider = llm_provider.OpenAIProvider()
            explicit_provider = llm_provider.OpenAIProvider(
                base_url="https://explicit.example.invalid/v1",
                model="explicit-model",
            )

        self.assertIsNone(default_provider._base_url)
        self.assertEqual(default_provider.model, "gpt-4o-mini")
        self.assertEqual(
            explicit_provider._base_url,
            "https://explicit.example.invalid/v1",
        )
        self.assertEqual(explicit_provider.model, "explicit-model")

    def test_source_development_preserves_endpoint_and_model_environment(self) -> None:
        with (
            patch.object(sys, "frozen", False, create=True),
            patch.dict(
                os.environ,
                {
                    "OPENAI_BASE_URL": "https://development.example.invalid/v1",
                    "LLM_MODEL": "development-model",
                },
                clear=False,
            ),
        ):
            provider = llm_provider.OpenAIProvider()

        self.assertEqual(
            provider._base_url,
            "https://development.example.invalid/v1",
        )
        self.assertEqual(provider.model, "development-model")


class ReportingNonSecretAuthorityTests(unittest.TestCase):
    def test_packaged_ignores_reporting_chat_environment(self) -> None:
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.dict(
                os.environ,
                {
                    "INTERNAL_OPS_CHAT_ID": "synthetic-internal-chat",
                    "CLIENT_REPORTING_CHAT_ID": "synthetic-client-chat",
                },
                clear=False,
            ),
            patch.object(reporting, "TelegramAdapter", side_effect=ValueError("bounded")),
        ):
            router = reporting.NotificationRouter()

        self.assertIsNone(router.adapter)
        self.assertIsNone(router.internal_chat_id)
        self.assertIsNone(router.default_client_chat_id)

    def test_source_development_preserves_reporting_chat_environment(self) -> None:
        with (
            patch.object(sys, "frozen", False, create=True),
            patch.dict(
                os.environ,
                {
                    "INTERNAL_OPS_CHAT_ID": "synthetic-internal-chat",
                    "CLIENT_REPORTING_CHAT_ID": "synthetic-client-chat",
                },
                clear=False,
            ),
            patch.object(reporting, "TelegramAdapter", side_effect=ValueError("bounded")),
        ):
            router = reporting.NotificationRouter()

        self.assertEqual(router.internal_chat_id, "synthetic-internal-chat")
        self.assertEqual(router.default_client_chat_id, "synthetic-client-chat")


class TrackingNonSecretAuthorityTests(unittest.TestCase):
    def test_packaged_ignores_tracking_environment_and_uses_secure_token_path(self) -> None:
        packaged_paths = SimpleNamespace(mode=RuntimeMode.PACKAGED)
        with (
            patch.object(tracking_adapter, "get_runtime_paths", return_value=packaged_paths),
            patch.object(
                tracking_adapter,
                "_read_machine_setting",
                return_value="true",
            ) as read_setting,
            patch.object(
                tracking_adapter,
                "load_runtime_secret",
                return_value="synthetic-secure-token",
            ) as load_secret,
            patch.dict(
                os.environ,
                {
                    "SHORT_LINK_BASE_URL": "https://hostile.example.invalid/t/",
                    "CF_ACCOUNT_ID": "hostile-account",
                    "CF_NAMESPACE_ID": "hostile-namespace",
                    "CF_API_TOKEN": "synthetic-hostile-env-token",
                },
                clear=False,
            ),
        ):
            adapter = tracking_adapter.CloudflareKVAdapter()

        self.assertEqual(adapter.base_url, "https://dopa.mx/t/")
        self.assertIsNone(adapter._account_id)
        self.assertIsNone(adapter._namespace_id)
        self.assertTrue(adapter._mock_mode)
        read_setting.assert_called_once_with("cloudflare_tracking_enabled")
        load_secret.assert_called_once_with(CF_API_TOKEN)
        self.assertEqual(adapter._api_token, "synthetic-secure-token")

    def test_packaged_explicit_tracking_arguments_remain_authoritative(self) -> None:
        packaged_paths = SimpleNamespace(mode=RuntimeMode.PACKAGED)
        with (
            patch.object(tracking_adapter, "get_runtime_paths", return_value=packaged_paths),
            patch.object(tracking_adapter, "_read_machine_setting") as read_setting,
            patch.object(tracking_adapter, "load_runtime_secret") as load_secret,
            patch.dict(
                os.environ,
                {
                    "SHORT_LINK_BASE_URL": "https://hostile.example.invalid/t/",
                    "CF_ACCOUNT_ID": "hostile-account",
                    "CF_NAMESPACE_ID": "hostile-namespace",
                },
                clear=False,
            ),
        ):
            adapter = tracking_adapter.CloudflareKVAdapter(
                api_token="synthetic-explicit-token",
                enabled=True,
                account_id="explicit-account",
                namespace_id="explicit-namespace",
                base_url="https://explicit.example.invalid/t/",
            )

        self.assertEqual(adapter.base_url, "https://explicit.example.invalid/t/")
        self.assertEqual(adapter._account_id, "explicit-account")
        self.assertEqual(adapter._namespace_id, "explicit-namespace")
        self.assertFalse(adapter._mock_mode)
        read_setting.assert_not_called()
        load_secret.assert_not_called()

    def test_source_development_preserves_tracking_environment(self) -> None:
        development_paths = SimpleNamespace(mode=RuntimeMode.SOURCE_DEVELOPMENT)
        with (
            patch.object(tracking_adapter, "get_runtime_paths", return_value=development_paths),
            patch.object(
                tracking_adapter,
                "load_runtime_secret",
                return_value="synthetic-development-token",
            ) as load_secret,
            patch.dict(
                os.environ,
                {
                    "SHORT_LINK_BASE_URL": "https://development.example.invalid/t/",
                    "CF_ACCOUNT_ID": "development-account",
                    "CF_NAMESPACE_ID": "development-namespace",
                },
                clear=False,
            ),
        ):
            adapter = tracking_adapter.CloudflareKVAdapter()

        self.assertEqual(adapter.base_url, "https://development.example.invalid/t/")
        self.assertEqual(adapter._account_id, "development-account")
        self.assertEqual(adapter._namespace_id, "development-namespace")
        self.assertFalse(adapter._mock_mode)
        load_secret.assert_called_once_with(
            CF_API_TOKEN,
            development_environment_key="CF_API_TOKEN",
        )


if __name__ == "__main__":
    unittest.main()
