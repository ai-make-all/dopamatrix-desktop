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
from unittest.mock import Mock, patch

from src.api.services import _resolve_matrix_base_url
from src.utils.env_utils import load_env


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = REPOSITORY_ROOT / "main.py"
TAURI_CONFIG_PATH = REPOSITORY_ROOT / "web_ui/src-tauri/tauri.conf.json"


def _subprocess_environment(temp_root: Path) -> dict[str, str]:
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
    environment.pop("PUBLIC_BASE_URL", None)
    return environment


class PackagedDotenvBoundaryTests(unittest.TestCase):
    def test_frozen_load_env_returns_before_import_or_search_and_preserves_env(self):
        marker = "DOPAMATRIX_H5_SYNTHETIC_MARKER"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "install" / "backend.exe"
            executable.parent.mkdir()
            adjacent = executable.parent / ".env"
            ancestor = root / ".env"
            adjacent.write_text(f"{marker}=adjacent\n", encoding="utf-8")
            ancestor.write_text(f"{marker}=ancestor\n", encoding="utf-8")
            original_import = __import__

            def guarded_import(name, *args, **kwargs):
                if name == "dotenv" or name.startswith("dotenv."):
                    raise AssertionError("packaged load_env imported dotenv")
                return original_import(name, *args, **kwargs)

            old_marker = os.environ.pop(marker, None)
            try:
                with (
                    patch.object(sys, "frozen", True, create=True),
                    patch.object(sys, "executable", str(executable)),
                    patch("builtins.__import__", side_effect=guarded_import),
                    patch(
                        "pathlib.Path.exists",
                        side_effect=AssertionError("packaged load_env searched paths"),
                    ),
                ):
                    load_env()
                self.assertNotIn(marker, os.environ)
                self.assertTrue(adjacent.is_file())
                self.assertTrue(ancestor.is_file())
            finally:
                os.environ.pop(marker, None)
                if old_marker is not None:
                    os.environ[marker] = old_marker

    def test_source_development_load_env_remains_explicit_override_false(self):
        load_dotenv = Mock(return_value=True)
        fake_module = SimpleNamespace(load_dotenv=load_dotenv)
        with (
            patch.object(sys, "frozen", False, create=True),
            patch.dict(sys.modules, {"dotenv": fake_module}),
        ):
            load_env()
        load_dotenv.assert_called_once_with(override=False)


class PackagedNetworkAuthorityTests(unittest.TestCase):
    def test_packaged_matrix_base_ignores_legacy_environment(self):
        with patch.dict(
            os.environ,
            {"PUBLIC_BASE_URL": "https://legacy-dev.example.invalid/root/"},
            clear=False,
        ):
            self.assertEqual(
                _resolve_matrix_base_url(frozen=True),
                "http://127.0.0.1:8000",
            )
            self.assertEqual(
                _resolve_matrix_base_url(frozen=False),
                "https://legacy-dev.example.invalid/root",
            )

    def test_packaged_lifespan_neither_imports_ngrok_nor_mutates_env_or_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe = textwrap.dedent(
                f"""
                import asyncio, builtins, json, os, sys
                from pathlib import Path
                from unittest.mock import patch
                from src.api.bootstrap import BootstrapDecision
                from src.api.runtime_paths import RuntimeMode, RuntimePaths, temporary_test_runtime_paths

                base = Path({str(root)!r})
                install = base / 'install'
                install.mkdir(parents=True)
                env_path = install / '.env'
                env_path.write_text('DOPAMATRIX_H5_SHOULD_NOT_LOAD=1\\n', encoding='utf-8')
                sys.argv = ['packaged-h5-probe']
                sys.frozen = True
                sys.executable = str(install / 'backend.exe')
                os.environ.pop('PUBLIC_BASE_URL', None)
                os.environ.pop('DOPAMATRIX_H5_SHOULD_NOT_LOAD', None)

                packaged = RuntimePaths(
                    mode=RuntimeMode.PACKAGED,
                    runtime_root=base / 'packaged-runtime',
                    settings_db_path=base / 'packaged-runtime' / 'dopamatrix.db',
                    tenant_data_dir=base / 'packaged-runtime' / 'data',
                    internal_output_root=base / 'packaged-runtime' / 'output',
                )
                original_import = builtins.__import__
                blocked_imports = []
                def guarded_import(name, *args, **kwargs):
                    if name == 'dotenv' or name.startswith('dotenv.') or name == 'pyngrok' or name.startswith('pyngrok.'):
                        blocked_imports.append(name)
                        raise AssertionError('forbidden packaged import: ' + name)
                    return original_import(name, *args, **kwargs)

                class Migration:
                    value = 'NOT_FOUND'
                provider = type('Provider', (), {{
                    'static_operational_status': type('Status', (), {{'value': 'SAFE_OFF_MISSING'}})(),
                    'static_operational_error_code': None,
                }})()

                with temporary_test_runtime_paths(base / 'installed-test-runtime'):
                    with patch('src.api.bootstrap.prepare_bootstrap', return_value=BootstrapDecision(packaged, False)), patch('src.api.runtime_mutation.acquire_server_runtime_mutation_barrier'), patch('src.api.runtime_mutation.release_server_runtime_mutation_barrier'), patch('appdirs.user_log_dir', return_value=str(base / 'logs')), patch('builtins.__import__', side_effect=guarded_import):
                        import main
                        main.initialize_application_schema = lambda _engine: None
                        main.initialize_secret_storage = lambda: Migration()
                        main.invalidate_api_key_cache = lambda _key: None
                        main.install_runtime_config_provider = lambda value: value
                        main.ws_manager.set_event_loop = lambda _loop: None
                        with patch('src.api.policy_profiles.load_applied_runtime_config_provider', return_value=provider), patch('src.api.secret_store.get_default_secret_store', return_value=object()):
                            async def exercise():
                                async with main._application_lifespan(main.app):
                                    return True
                            completed = asyncio.run(exercise())

                print(json.dumps({{
                    'completed': completed,
                    'blocked_imports': blocked_imports,
                    'dotenv_imported': 'dotenv' in sys.modules,
                    'ngrok_imported': any(name == 'pyngrok' or name.startswith('pyngrok.') for name in sys.modules),
                    'public_base_url_present': 'PUBLIC_BASE_URL' in os.environ,
                    'dotenv_marker_present': 'DOPAMATRIX_H5_SHOULD_NOT_LOAD' in os.environ,
                    'env_file_still_exists': env_path.is_file(),
                }}))
                """
            )
            result = subprocess.run(
                [sys.executable, "-c", probe],
                cwd=REPOSITORY_ROOT,
                env=_subprocess_environment(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(
            observed,
            {
                "completed": True,
                "blocked_imports": [],
                "dotenv_imported": False,
                "ngrok_imported": False,
                "public_base_url_present": False,
                "dotenv_marker_present": False,
                "env_file_still_exists": True,
            },
        )


class StaticPackageContractTests(unittest.TestCase):
    def test_tauri_resources_keep_media_tools_and_remove_dotenv(self):
        config = json.loads(TAURI_CONFIG_PATH.read_text(encoding="utf-8"))
        bundle = config["bundle"]
        self.assertEqual(bundle["externalBin"], ["bin/backend"])
        self.assertEqual(
            bundle["resources"],
            ["bin/ffmpeg.exe", "bin/ffprobe.exe"],
        )
        self.assertNotIn(".env", bundle["resources"])

    def test_operator_dispatch_and_local_bind_contract_remain_ordered(self):
        source = MAIN_PATH.read_text(encoding="utf-8")
        operator = source.index("if __name__ == \"__main__\" and is_operator_invocation")
        bootstrap = source.index("_bootstrap_decision = prepare_bootstrap")
        dotenv = source.index("from src.utils.env_utils import load_env")
        fastapi = source.index("from fastapi import APIRouter, FastAPI")
        self.assertLess(operator, bootstrap)
        self.assertLess(operator, dotenv)
        self.assertLess(operator, fastapi)
        self.assertNotIn("os.remove(_env_path)", source)
        self.assertIn('uvicorn.run(app, host="127.0.0.1", port=8000', source)
        self.assertIn('uvicorn.run("main:app", host="127.0.0.1", port=8000', source)


if __name__ == "__main__":
    unittest.main()
