from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from src.api.runtime_config import RuntimeConfigProvider
from src.api.runtime_paths import (
    LegacyRuntimeMigrationRequired,
    RuntimeMode,
    RuntimePathsInitializationConflict,
    initialize_runtime_paths,
    resolve_runtime_paths,
    temporary_test_runtime_paths,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

_READINESS_MAPPING = {
    "RESERVATION_ROLLOUT_READINESS_WINDOW": "24h",
    "RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS": "2",
    "RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS": "2",
    "RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS": "1",
    "RESERVATION_ROLLOUT_MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE": "1",
    "RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE": "1",
    "RESERVATION_ROLLOUT_MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE": "1",
    "RESERVATION_ROLLOUT_MAXIMUM_ZERO_PLAN_CONFLICT_RATE": "0",
    "RESERVATION_ROLLOUT_MAXIMUM_PARTIAL_PLAN_RATE": "0",
    "RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE": "0",
    "RESERVATION_ROLLOUT_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE": "0",
    "RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE": "0",
    "RESERVATION_ROLLOUT_MAXIMUM_CLEANUP_WARNING_RATE": "0",
}

_CONTROL_MAPPING = {
    "RESERVATION_ROLLOUT_CONTROL_ENABLED": "true",
    "RESERVATION_ROLLOUT_GENERATION": "canary-g1",
    "RESERVATION_ROLLOUT_TENANT_ALLOWLIST": "tenant-a",
    "RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS": "1000",
    "RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS": "0",
    "RESERVATION_ROLLOUT_ASSIGNMENT_SECRET": "test-only-secret",
    "RESERVATION_ROLLOUT_KILL_SWITCH": "false",
    "RESERVATION_ROLLOUT_ROLLBACK_WINDOW": "24h",
    "RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS": "2",
    "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_DIAGNOSTIC_COVERAGE_RATE": "0.9",
    "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_PLANNING_COVERAGE_RATE": "0.9",
    "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_TERMINAL_COVERAGE_RATE": "0.9",
    "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE": "0.1",
    "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE": "0.1",
    "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE": "0.1",
    "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE": "0.1",
    "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE": "0.1",
    "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE": "0.1",
}


def _safe_subprocess_environment(temp_root: Path) -> dict[str, str]:
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


def _run_probe(code: str, temp_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=REPOSITORY_ROOT,
        env=_safe_subprocess_environment(temp_root),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


class RuntimePathsContractTests(unittest.TestCase):
    def test_packaged_root_uses_declared_appdirs_contract(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "user-data"
            install = Path(directory) / "install"
            install.mkdir()

            def factory(application: str, vendor: str) -> str:
                calls.append((application, vendor))
                return str(root)

            paths = resolve_runtime_paths(
                mode=RuntimeMode.PACKAGED,
                packaged_install_root=install,
                user_data_dir_factory=factory,
            )

        self.assertEqual(calls, [("DopaMatrix", "DopaMatrixOrg")])
        self.assertEqual(paths.runtime_root, root.resolve())
        self.assertTrue(paths.settings_db_path.is_absolute())
        self.assertTrue(paths.tenant_data_dir.is_absolute())
        self.assertTrue(paths.internal_output_root.is_absolute())

    def test_source_and_test_roots_are_explicit_and_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = resolve_runtime_paths(
                mode=RuntimeMode.SOURCE_DEVELOPMENT,
                source_root=base / "source-root",
            )
            test = resolve_runtime_paths(
                mode=RuntimeMode.TEST,
                runtime_root=base / "test-root",
            )
        self.assertEqual(source.runtime_root, (base / "source-root").resolve())
        self.assertEqual(test.runtime_root, (base / "test-root").resolve())
        self.assertNotEqual(source.runtime_root, test.runtime_root)

    def test_initialization_is_idempotent_and_conflicts_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            first_root = Path(directory) / "first"
            with temporary_test_runtime_paths(first_root) as installed:
                same = initialize_runtime_paths(
                    mode=RuntimeMode.TEST,
                    runtime_root=first_root,
                )
                self.assertIs(same, installed)
                with self.assertRaisesRegex(
                    RuntimePathsInitializationConflict,
                    "RUNTIME_PATHS_INITIALIZATION_CONFLICT",
                ):
                    initialize_runtime_paths(
                        mode=RuntimeMode.TEST,
                        runtime_root=Path(directory) / "other",
                    )

    def test_fresh_packaged_install_is_not_falsely_blocked_or_mutated(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            install = base / "install"
            install.mkdir()
            (install / "backend.exe").write_bytes(b"resource")
            (install / "data").mkdir()
            (install / "output").mkdir()
            before = sorted(path.relative_to(install) for path in install.rglob("*"))
            paths = resolve_runtime_paths(
                mode=RuntimeMode.PACKAGED,
                runtime_root=base / "runtime",
                packaged_install_root=install,
            )
            after = sorted(path.relative_to(install) for path in install.rglob("*"))
        self.assertEqual(before, after)
        self.assertEqual(paths.runtime_root, (base / "runtime").resolve())

    def test_meaningful_legacy_state_requires_migration_without_mutation(self):
        cases = {
            "global-db": ("dopamatrix.db", b"db"),
            "tenant-sidecar": ("data/dopamatrix_tenant.db-wal", b"wal"),
            "output": ("output/final.mp4", b"video"),
        }
        for label, (relative, content) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                install = base / "install"
                target = install / relative
                target.parent.mkdir(parents=True)
                target.write_bytes(content)
                with self.assertRaisesRegex(
                    LegacyRuntimeMigrationRequired,
                    "LEGACY_RUNTIME_MIGRATION_REQUIRED",
                ):
                    resolve_runtime_paths(
                        mode=RuntimeMode.PACKAGED,
                        runtime_root=base / "runtime",
                        packaged_install_root=install,
                    )
                self.assertEqual(target.read_bytes(), content)
                self.assertFalse((base / "runtime").exists())


class BootstrapContractTests(unittest.TestCase):
    def test_operator_prefix_exits_before_application_graph_import(self):
        with tempfile.TemporaryDirectory() as directory:
            result = _run_probe(
                f"""
                import json, runpy, sys
                sys.argv = [r'{REPOSITORY_ROOT / 'main.py'}', 'operator', '--help']
                exit_code = None
                try:
                    runpy.run_path(r'{REPOSITORY_ROOT / 'main.py'}', run_name='__main__')
                except SystemExit as exc:
                    exit_code = exc.code
                print(json.dumps({{
                    'exit_code': exit_code,
                    'fastapi': 'fastapi' in sys.modules,
                    'database': 'src.api.database' in sys.modules,
                    'routes': 'src.api.routes_dsl' in sys.modules,
                    'uvicorn': 'uvicorn' in sys.modules,
                }}))
                """,
                Path(directory),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(observed["exit_code"], 0)
        self.assertFalse(observed["fastapi"])
        self.assertFalse(observed["database"])
        self.assertFalse(observed["routes"])
        self.assertFalse(observed["uvicorn"])
        self.assertEqual(result.stderr, "")
        self.assertIn("Usage: backend.exe operator", result.stdout)

    def test_normal_source_import_constructs_fastapi_app_without_lifespan(self):
        with tempfile.TemporaryDirectory() as directory:
            result = _run_probe(
                f"""
                import appdirs, dotenv, json, sys
                from unittest.mock import patch
                from src.api.bootstrap import BootstrapDecision
                from src.api.runtime_paths import initialize_runtime_paths, RuntimeMode
                appdirs.user_log_dir = lambda *args, **kwargs: r'{Path(directory) / 'logs'}'
                dotenv.load_dotenv = lambda *args, **kwargs: False
                sys.argv = ['main-import-probe']
                paths = initialize_runtime_paths(
                    mode=RuntimeMode.SOURCE_DEVELOPMENT,
                    runtime_root=r'{Path(directory) / 'runtime'}',
                )
                with patch(
                    'src.api.bootstrap.prepare_bootstrap',
                    return_value=BootstrapDecision(paths, False),
                ):
                    import main
                print(json.dumps({{
                    'app_type': type(main.app).__name__,
                    'mode': main._bootstrap_decision.runtime_paths.mode.value,
                }}))
                """,
                Path(directory),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(observed, {"app_type": "FastAPI", "mode": "SOURCE_DEVELOPMENT"})


class RuntimeAuthorityIntegrationTests(unittest.TestCase):
    def test_database_and_tenant_engine_bind_to_absolute_test_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            result = _run_probe(
                f"""
                import json
                from pathlib import Path
                from src.api.runtime_paths import initialize_runtime_paths, RuntimeMode
                paths = initialize_runtime_paths(mode=RuntimeMode.TEST, runtime_root=r'{root}')
                from src.api import database
                tenant = database.get_tenant_engine('Tenant-A')
                print(json.dumps({{
                    'global': str(Path(database.engine.url.database).resolve()),
                    'tenant': str(Path(tenant.url.database).resolve()),
                    'canonical': database.canonical_tenant_id('Tenant-A'),
                }}))
                tenant.dispose()
                database.engine.dispose()
                """,
                Path(directory),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(Path(observed["global"]), (root / "dopamatrix.db").resolve())
        self.assertEqual(
            Path(observed["tenant"]),
            (root / "data" / "dopamatrix_tenant-a.db").resolve(),
        )
        self.assertEqual(observed["canonical"], "tenant-a")

    def test_routes_matrix_import_does_not_create_output_or_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            result = _run_probe(
                f"""
                import json
                from pathlib import Path
                from src.api.runtime_paths import initialize_runtime_paths, RuntimeMode
                paths = initialize_runtime_paths(mode=RuntimeMode.TEST, runtime_root=r'{root}')
                from src.api import routes_matrix
                print(json.dumps({{
                    'output_exists': paths.internal_output_root.exists(),
                    'exports_exists': (paths.internal_output_root / 'exports').exists(),
                }}))
                """,
                Path(directory),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout.strip().splitlines()[-1]),
            {"output_exists": False, "exports_exists": False},
        )

    def test_render_nodes_use_injected_internal_output_root(self):
        from src.core.context import WorkflowContext
        from src.nodes.compositor import FFmpegCompositorNode
        from src.nodes.subtitle import SubtitleNode
        from src.nodes.tts_node import TTSNode

        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "authoritative-output"
            context = WorkflowContext(task_id="task-a", test_language="en")
            context.config.update(
                {
                    "execution_id": "exec-a",
                    "file_sid": "file-a",
                    "internal_output_root": str(output_root),
                    "translations": {"en": "safe subtitle"},
                    "subtitle_start": 0,
                    "subtitle_end": 1,
                }
            )
            master = FFmpegCompositorNode._master_output_path(context)
            final = FFmpegCompositorNode._final_output_path(context, "en")
            SubtitleNode().execute(context)
            tts = TTSNode(output_dir=str(output_root))

            self.assertEqual(Path(master).parent, output_root)
            self.assertEqual(Path(final).parent, output_root)
            self.assertEqual(Path(context.variants["en"]["subtitle_ass"]).parent, output_root)
            self.assertEqual(tts._output_dir, output_root)

    def test_production_boundaries_inject_one_internal_output_root(self):
        import run_matrix_factory
        from src.api import routes_dsl

        factory_source = inspect.getsource(run_matrix_factory._run_single_matrix)
        worker_source = inspect.getsource(routes_dsl.render_worker)
        for source in (factory_source, worker_source):
            self.assertIn("get_runtime_paths().internal_output_root", source)
            self.assertIn('context.config["internal_output_root"]', source)
        self.assertIn("TTSNode(output_dir=str(internal_output_root))", factory_source)
        self.assertIn("TTSNode(output_dir=str(internal_output_root))", worker_source)

    def test_delivery_root_remains_external_and_dynamic(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime"
            delivery = Path(directory) / "operator-delivery"
            with temporary_test_runtime_paths(runtime) as paths:
                from src.api.delivery_output import (
                    derive_tenant_delivery_root,
                    get_delivery_root,
                    save_delivery_root,
                )

                save_delivery_root(delivery)
                stored = Path(get_delivery_root())
                tenant_root = derive_tenant_delivery_root(stored, "tenant-a")
                self.assertEqual(stored, delivery.resolve())
                self.assertNotEqual(stored, paths.internal_output_root)
                self.assertTrue(tenant_root.is_relative_to(stored))


class RuntimeConfigAndReservationCompatibilityTests(unittest.TestCase):
    def test_provider_separates_static_snapshot_from_dynamic_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = resolve_runtime_paths(
                mode=RuntimeMode.TEST,
                runtime_root=directory,
            )
            original = {"STATIC": "before"}
            dynamic = {"delivery_root": "first"}
            provider = RuntimeConfigProvider.create(
                paths=paths,
                static_operational_mapping=original,
                dynamic_machine_setting_reader=dynamic.get,
            )
            original["STATIC"] = "after"
            dynamic["delivery_root"] = "second"
            self.assertEqual(provider.static_operational_mapping["STATIC"], "before")
            self.assertEqual(provider.read_dynamic_machine_setting("delivery_root"), "second")
            with self.assertRaises(TypeError):
                provider.static_operational_mapping["STATIC"] = "mutated"

    def test_reservation_loaders_preserve_mapping_and_environment_semantics(self):
        from src.api.reservation_lease import load_reservation_lease_configuration
        from src.api.reservation_rollout_control import (
            load_reservation_rollout_control_configuration,
        )
        from src.api.reservation_rollout_readiness import (
            load_reservation_rollout_readiness_configuration,
        )

        lease_mapping = {
            "RESERVATION_LEASE_TTL_SECONDS": "180",
            "RESERVATION_HEARTBEAT_INTERVAL_SECONDS": "45",
        }
        with patch.dict(os.environ, lease_mapping, clear=True):
            env_lease = load_reservation_lease_configuration()
        self.assertEqual(env_lease, load_reservation_lease_configuration(lease_mapping))

        readiness = load_reservation_rollout_readiness_configuration(_READINESS_MAPPING)
        control = load_reservation_rollout_control_configuration(_CONTROL_MAPPING)
        self.assertIsNotNone(readiness)
        self.assertIsNotNone(control)
        self.assertEqual(
            load_reservation_rollout_readiness_configuration({}),
            None,
        )
        self.assertEqual(load_reservation_rollout_control_configuration({}), None)


if __name__ == "__main__":
    unittest.main()
