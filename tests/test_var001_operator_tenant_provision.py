from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import closing, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.api.operator_cli import OPERATOR_COMMAND_NOT_IMPLEMENTED, run_operator_cli
from src.api.operator_tenant_provision import (
    BACKUP_NAMESPACE_NOT_CONFIGURED,
    OPERATOR_APPROVAL_REF_INVALID,
    OPERATOR_DELIVERY_NAMESPACE_COLLISION,
    OPERATOR_RUNTIME_MUTATION_BUSY,
    OPERATOR_TENANT_COLLISION,
    OPERATOR_TENANT_INVALID,
    OPERATOR_TENANT_PARTIAL_PROVISIONING_REVIEW_REQUIRED,
    _default_verifier,
    provision_tenant,
    validate_approved_tenant_identity,
)
from src.api.runtime_mutation import RuntimeMutationBarrierBusy
from src.api.runtime_paths import RuntimeMode, RuntimePaths, temporary_test_runtime_paths


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
APPROVED = {
    "ph-elv-0001": "elv0001",
    "ph-bty-0001": "bty0001",
    "ph-hwh-0001": "hwh0001",
}


def _paths(root: Path) -> RuntimePaths:
    root.mkdir(parents=True, exist_ok=True)
    data = root / "data"
    data.mkdir()
    return RuntimePaths(RuntimeMode.TEST, root, root / "dopamatrix.db", data, root / "output")


def _stub_initializer(paths: RuntimePaths, *, add_business_row: bool = False):
    def initialize(tenant: str) -> None:
        database = paths.tenant_database_path(tenant)
        with closing(sqlite3.connect(database)) as connection:
            for table in (
                "video_tasks",
                "reservation_run_diagnostics",
                "reservation_rollout_breakers",
                "video_assets",
                "local_assets_inventory",
                "task_history",
                "variant_approvals",
                "variant_status_audits",
                "fingerprint_identities",
                "fingerprint_occurrences",
                "fingerprint_reservations",
            ):
                connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY);')
            connection.execute(
                "CREATE TABLE fingerprint_ledger_schema_version "
                "(component TEXT PRIMARY KEY, schema_version INTEGER NOT NULL);"
            )
            connection.execute(
                "INSERT INTO fingerprint_ledger_schema_version VALUES ('fingerprint_ledger', 2);"
            )
            if add_business_row:
                connection.execute("INSERT INTO video_assets DEFAULT VALUES;")
            connection.commit()

    return initialize


def _stub_verifier(database: Path) -> None:
    if not database.is_file():
        raise AssertionError("missing initialized database")


class TenantIdentityAndApprovalTests(unittest.TestCase):
    def test_exact_three_id_mapping(self):
        for tenant, short_code in APPROVED.items():
            with self.subTest(tenant=tenant):
                identity = validate_approved_tenant_identity(tenant)
                self.assertEqual(identity.canonical_id, tenant)
                self.assertEqual(identity.short_code, short_code)

    def test_nonapproved_and_sanitizer_aliases_fail_before_runtime_initialization(self):
        invalid = (
            "PH-ELV-0001",
            " ph-elv-0001",
            "ph-elv-0001 ",
            "ph_elv_0001",
            "ph-elv-001",
            "ph-elv-00001",
            "ph-elv-0000",
            "ph-elv-10000",
            "ph-elv-0002",
            "ph-bty-0002",
            "ph-hwh-0002",
            "ph-gam-0001",
            "us-elv-0001",
            "ph-elv-0001/../x",
            "ph-bty-0002",
            "ph-demo-0001",
            "default",
            "v15_acceptance",
        )
        for tenant in invalid:
            with self.subTest(tenant=tenant):
                called = False

                def forbidden_paths():
                    nonlocal called
                    called = True
                    raise AssertionError("runtime initialization occurred")

                result = provision_tenant(tenant, "APPROVAL", paths_initializer=forbidden_paths)
                self.assertEqual(result.exit_code, 3)
                self.assertEqual(result.error_code, OPERATOR_TENANT_INVALID)
                self.assertFalse(called)

    def test_approval_ref_is_one_to_256_and_control_character_free(self):
        for value in ("", "   ", "x" * 257, "line\nfeed", "tab\tvalue", "nul\x00value"):
            with self.subTest(value_length=len(value)):
                result = provision_tenant(
                    "ph-elv-0001",
                    value,
                    paths_initializer=lambda: (_ for _ in ()).throw(AssertionError()),
                )
                self.assertEqual(result.exit_code, 3)
                self.assertEqual(result.error_code, OPERATOR_APPROVAL_REF_INVALID)
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            for value in ("A", "x" * 256):
                with self.subTest(value_length=len(value)):
                    result = provision_tenant(
                        "ph-elv-0001",
                        value,
                        paths_initializer=lambda: paths,
                        barrier_factory=lambda unused: nullcontext(),
                        delivery_root_reader=lambda unused: None,
                        initializer=_stub_initializer(paths),
                        verifier=_stub_verifier,
                    )
                    self.assertEqual(result.exit_code, 0)
                    paths.tenant_database_path("ph-elv-0001").unlink()

    def test_tenant_code_is_not_in_public_grammar(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        exit_code = run_operator_cli(
            (
                "tenant",
                "provision",
                "--tenant",
                "ph-elv-0001",
                "--approval-ref",
                "A",
                "--tenant-code",
                "elv0001",
            ),
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("OPERATOR_INVALID_ARGUMENT", stderr.getvalue())


class ProvisioningBarrierAndCollisionTests(unittest.TestCase):
    def test_db_wal_shm_and_case_normalized_collisions_are_hard_failures(self):
        names = (
            "dopamatrix_ph-elv-0001.db",
            "dopamatrix_ph-elv-0001.db-wal",
            "dopamatrix_ph-elv-0001.db-shm",
            "DOPAMATRIX_PH-ELV-0001.DB",
            "DOPAMATRIX_PH-ELV-0001.DB-WAL",
            "DOPAMATRIX_PH-ELV-0001.DB-SHM",
        )
        for name in names:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                paths = _paths(Path(directory))
                target = paths.tenant_data_dir / name
                target.write_bytes(b"preserve")
                initialized = False

                def forbidden(_tenant: str):
                    nonlocal initialized
                    initialized = True

                result = provision_tenant(
                    "ph-elv-0001",
                    "A",
                    paths_initializer=lambda: paths,
                    barrier_factory=lambda unused: nullcontext(),
                    delivery_root_reader=lambda unused: None,
                    initializer=forbidden,
                )
                self.assertEqual(result.exit_code, 4)
                self.assertEqual(result.error_code, OPERATOR_TENANT_COLLISION)
                self.assertFalse(initialized)
                self.assertEqual(target.read_bytes(), b"preserve")

    def test_authoritative_recheck_occurs_while_barrier_is_held(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            target = paths.tenant_database_path("ph-elv-0001")

            class Barrier:
                def __enter__(self):
                    target.write_bytes(b"racing allocation")
                    return self

                def __exit__(self, *unused):
                    return None

            result = provision_tenant(
                "ph-elv-0001",
                "A",
                paths_initializer=lambda: paths,
                barrier_factory=lambda unused: Barrier(),
                delivery_root_reader=lambda unused: None,
                initializer=lambda unused: self.fail("initializer ran"),
            )
            self.assertEqual(result.error_code, OPERATOR_TENANT_COLLISION)
            self.assertEqual(target.read_bytes(), b"racing allocation")

    def test_lock_contention_is_state_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))

            def busy(_paths):
                raise RuntimeMutationBarrierBusy()

            result = provision_tenant(
                "ph-elv-0001",
                "A",
                paths_initializer=lambda: paths,
                barrier_factory=busy,
            )
            self.assertEqual(result.exit_code, 4)
            self.assertEqual(result.error_code, OPERATOR_RUNTIME_MUTATION_BUSY)
            self.assertFalse(paths.tenant_database_path("ph-elv-0001").exists())

    def test_real_cross_process_lock_blocks_then_release_allows_provision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            paths = _paths(root)
            code = textwrap.dedent(
                f"""
                import sys
                from src.api.runtime_mutation import acquire_runtime_mutation_barrier
                from src.api.runtime_paths import RuntimeMode, initialize_runtime_paths
                paths = initialize_runtime_paths(mode=RuntimeMode.TEST, runtime_root={str(root)!r})
                with acquire_runtime_mutation_barrier(paths):
                    print('READY', flush=True)
                    sys.stdin.readline()
                """
            )
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
            holder = subprocess.Popen(
                [sys.executable, "-u", "-c", code],
                cwd=REPOSITORY_ROOT,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            try:
                self.assertEqual(holder.stdout.readline().strip(), "READY")
                blocked = provision_tenant(
                    "ph-elv-0001",
                    "A",
                    paths_initializer=lambda: paths,
                    delivery_root_reader=lambda unused: None,
                    initializer=lambda unused: self.fail("initializer ran while locked"),
                )
                self.assertEqual(blocked.exit_code, 4)
                self.assertEqual(blocked.error_code, OPERATOR_RUNTIME_MUTATION_BUSY)
                self.assertFalse(paths.tenant_database_path("ph-elv-0001").exists())
            finally:
                assert holder.stdin is not None
                holder.stdin.write("release\n")
                holder.stdin.flush()
                holder.stdin.close()
                holder.wait(timeout=15)
            self.assertEqual(holder.returncode, 0, holder.stderr.read())

            succeeded = provision_tenant(
                "ph-elv-0001",
                "A",
                paths_initializer=lambda: paths,
                delivery_root_reader=lambda unused: None,
                initializer=_stub_initializer(paths),
                verifier=_stub_verifier,
            )
            self.assertEqual(succeeded.exit_code, 0)

    def test_existing_complete_tenant_is_conflict_not_idempotent_success(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            database = paths.tenant_database_path("ph-elv-0001")
            database.write_bytes(b"existing-complete")
            result = provision_tenant(
                "ph-elv-0001",
                "A",
                paths_initializer=lambda: paths,
                barrier_factory=lambda unused: nullcontext(),
            )
            self.assertEqual(result.exit_code, 4)
            self.assertEqual(result.error_code, OPERATOR_TENANT_COLLISION)
            self.assertEqual(database.read_bytes(), b"existing-complete")


class NamespaceAuthorityTests(unittest.TestCase):
    def test_no_backup_authority_does_not_block_or_touch_historical_path(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            original_exists = Path.exists

            def guarded_exists(path: Path) -> bool:
                if "dopamatrix-backups" in str(path).lower():
                    raise AssertionError("historical backup path was accessed")
                return original_exists(path)

            original_iterdir = Path.iterdir

            def guarded_iterdir(path: Path):
                if "dopamatrix-backups" in str(path).lower():
                    raise AssertionError("historical backup path was scanned")
                return original_iterdir(path)

            with (
                patch.object(Path, "exists", autospec=True, side_effect=guarded_exists) as exists,
                patch.object(Path, "iterdir", new=guarded_iterdir),
            ):
                result = provision_tenant(
                    "ph-elv-0001",
                    "A",
                    paths_initializer=lambda: paths,
                    barrier_factory=lambda unused: nullcontext(),
                    delivery_root_reader=lambda unused: None,
                    initializer=_stub_initializer(paths),
                    verifier=_stub_verifier,
                )
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.data["backup_namespace"], BACKUP_NAMESPACE_NOT_CONFIGURED)
            accessed = tuple(str(call.args[0]) for call in exists.call_args_list if call.args)
            self.assertFalse(any("dopamatrix-backups" in value.lower() for value in accessed))
            self.assertFalse((paths.runtime_root / "backup").exists())

    def test_delivery_unconfigured_is_not_a_blocker_or_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory) / "runtime")
            delivery = Path(directory) / "delivery-does-not-exist"
            result = provision_tenant(
                "ph-elv-0001",
                "A",
                paths_initializer=lambda: paths,
                barrier_factory=lambda unused: nullcontext(),
                delivery_root_reader=lambda unused: None,
                initializer=_stub_initializer(paths),
                verifier=_stub_verifier,
            )
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.data["delivery_namespace"], "NOT_CONFIGURED")
            self.assertFalse(delivery.exists())

    def test_configured_delivery_absent_is_allowed_without_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            delivery = base / "delivery"
            result = provision_tenant(
                "ph-elv-0001",
                "A",
                paths_initializer=lambda: paths,
                barrier_factory=lambda unused: nullcontext(),
                delivery_root_reader=lambda unused: str(delivery),
                initializer=_stub_initializer(paths),
                verifier=_stub_verifier,
            )
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.data["delivery_namespace"], "AVAILABLE")
            self.assertFalse(delivery.exists())

    def test_configured_delivery_root_exists_with_no_tenant_namespace_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            delivery = base / "delivery"
            delivery.mkdir()
            before = tuple(delivery.iterdir())
            result = provision_tenant(
                "ph-elv-0001",
                "A",
                paths_initializer=lambda: paths,
                barrier_factory=lambda unused: nullcontext(),
                delivery_root_reader=lambda unused: str(delivery),
                initializer=_stub_initializer(paths),
                verifier=_stub_verifier,
            )
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(tuple(delivery.iterdir()), before)

    def test_delivery_exact_and_case_collision_are_preserved(self):
        for tenant_name in ("ph-elv-0001", "PH-ELV-0001"):
            with self.subTest(tenant_name=tenant_name), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                paths = _paths(base / "runtime")
                namespace = base / "delivery" / "tenants" / tenant_name
                namespace.mkdir(parents=True)
                marker = namespace / "preserve.bin"
                marker.write_bytes(b"unchanged")
                result = provision_tenant(
                    "ph-elv-0001",
                    "A",
                    paths_initializer=lambda: paths,
                    barrier_factory=lambda unused: nullcontext(),
                    delivery_root_reader=lambda unused: str(base / "delivery"),
                    initializer=lambda unused: self.fail("initializer ran"),
                )
                self.assertEqual(result.exit_code, 4)
                self.assertEqual(result.error_code, OPERATOR_DELIVERY_NAMESPACE_COLLISION)
                self.assertEqual(marker.read_bytes(), b"unchanged")

    def test_backup_commands_remain_placeholders(self):
        for arguments in (
            ("backup", "create", "--tenant", "ph-elv-0001", "--destination", "X:\\new"),
            ("backup", "verify", "--bundle", "X:\\bundle"),
        ):
            with self.subTest(arguments=arguments):
                stdout, stderr = io.StringIO(), io.StringIO()
                exit_code = run_operator_cli(arguments, stdout=stdout, stderr=stderr)
                self.assertEqual(exit_code, 4)
                self.assertIn(OPERATOR_COMMAND_NOT_IMPLEMENTED, stderr.getvalue())


class ProvisioningVerificationAndOutputTests(unittest.TestCase):
    def test_initializer_failure_without_artifact_is_subsystem_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            calls = 0

            def fail_once(unused: str):
                nonlocal calls
                calls += 1
                raise RuntimeError("synthetic")

            result = provision_tenant(
                "ph-elv-0001",
                "A",
                paths_initializer=lambda: paths,
                barrier_factory=lambda unused: nullcontext(),
                delivery_root_reader=lambda unused: None,
                initializer=fail_once,
            )
            self.assertEqual(result.exit_code, 8)
            self.assertEqual(calls, 1)
            self.assertFalse(paths.tenant_database_path("ph-elv-0001").exists())

    def test_initializer_partial_and_verifier_failure_preserve_database(self):
        for fail_in_verifier in (False, True):
            with self.subTest(fail_in_verifier=fail_in_verifier), tempfile.TemporaryDirectory() as directory:
                paths = _paths(Path(directory))
                database = paths.tenant_database_path("ph-elv-0001")
                initializer_calls = 0
                verifier_calls = 0

                def initialize(unused: str):
                    nonlocal initializer_calls
                    initializer_calls += 1
                    database.write_bytes(b"partial-preserve")
                    if not fail_in_verifier:
                        raise RuntimeError("synthetic")

                def verify(unused: Path):
                    nonlocal verifier_calls
                    verifier_calls += 1
                    raise ValueError("synthetic verification failure")

                result = provision_tenant(
                    "ph-elv-0001",
                    "A",
                    paths_initializer=lambda: paths,
                    barrier_factory=lambda unused: nullcontext(),
                    delivery_root_reader=lambda unused: None,
                    initializer=initialize,
                    verifier=verify,
                )
                self.assertEqual(result.exit_code, 7)
                self.assertEqual(
                    result.error_code,
                    OPERATOR_TENANT_PARTIAL_PROVISIONING_REVIEW_REQUIRED,
                )
                self.assertEqual(database.read_bytes(), b"partial-preserve")
                self.assertEqual(initializer_calls, 1)
                self.assertEqual(verifier_calls, 1 if fail_in_verifier else 0)

    def test_independent_verifier_rejects_schema_business_and_ledger_faults_without_repair(self):
        cases = (
            "application-table",
            "rollout-index",
            "business",
            "ledger-version",
            "ledger-table",
            "ledger-metadata",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                paths = _paths(Path(directory))
                tenant = f"verification-{case}"
                database = paths.tenant_database_path(tenant)
                with temporary_test_runtime_paths(paths.runtime_root):
                    from src.api.database import get_tenant_engine

                    engine = get_tenant_engine(tenant)
                    engine.dispose()
                with closing(sqlite3.connect(database)) as connection:
                    if case == "application-table":
                        connection.execute("DROP TABLE video_assets;")
                    elif case == "rollout-index":
                        connection.execute("DROP INDEX ix_video_tasks_rollout_readiness;")
                    elif case == "business":
                        connection.execute(
                            "INSERT INTO fingerprint_identities "
                            "(fingerprint_type, fingerprint_version, fingerprint_digest, "
                            "digest_algorithm, source_hash_algorithm, canonical_payload, created_at) "
                            "VALUES ('synthetic', 1, 'synthetic', 'sha256', 'sha256', '{}', "
                            "'2026-01-01 00:00:00');"
                        )
                    elif case == "ledger-version":
                        connection.execute(
                            "UPDATE fingerprint_ledger_schema_version SET schema_version=1;"
                        )
                    elif case == "ledger-table":
                        connection.execute("DROP TABLE fingerprint_reservations;")
                    elif case == "ledger-metadata":
                        connection.execute("DELETE FROM fingerprint_ledger_schema_version;")
                    connection.commit()
                before = database.read_bytes()
                with self.assertRaises(ValueError):
                    _default_verifier(database)
                self.assertEqual(database.read_bytes(), before)

    def test_nonzero_business_data_causes_command_exit_7_and_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            database = paths.tenant_database_path("ph-elv-0001")

            def initialize_with_business_row(tenant: str):
                with temporary_test_runtime_paths(paths.runtime_root):
                    from src.api.database import get_tenant_engine

                    engine = get_tenant_engine(tenant)
                    engine.dispose()
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute(
                        "INSERT INTO fingerprint_identities "
                        "(fingerprint_type, fingerprint_version, fingerprint_digest, "
                        "digest_algorithm, source_hash_algorithm, canonical_payload, created_at) "
                        "VALUES ('synthetic', 1, 'synthetic', 'sha256', 'sha256', '{}', "
                        "'2026-01-01 00:00:00');"
                    )
                    connection.commit()

            result = provision_tenant(
                "ph-elv-0001",
                "A",
                paths_initializer=lambda: paths,
                barrier_factory=lambda unused: nullcontext(),
                delivery_root_reader=lambda unused: None,
                initializer=initialize_with_business_row,
            )
            self.assertEqual(result.exit_code, 7)
            self.assertEqual(
                result.error_code,
                OPERATOR_TENANT_PARTIAL_PROVISIONING_REVIEW_REQUIRED,
            )
            with closing(sqlite3.connect(database)) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM fingerprint_identities;"
                ).fetchone()[0]
            self.assertEqual(count, 1)

    def test_real_initializer_and_verifier_succeed_for_each_approved_tenant_in_fresh_process(self):
        for tenant, short_code in APPROVED.items():
            with self.subTest(tenant=tenant), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "runtime"
                code = textwrap.dedent(
                    f"""
                    import json
                    from src.api.runtime_paths import RuntimeMode, initialize_runtime_paths
                    from src.api.operator_cli import run_operator_cli
                    initialize_runtime_paths(mode=RuntimeMode.TEST, runtime_root={str(root)!r})
                    raise SystemExit(run_operator_cli((
                        '--json', 'tenant', 'provision', '--tenant', {tenant!r},
                        '--approval-ref', 'H4-4-TEST'
                    )))
                    """
                )
                environment = dict(os.environ)
                environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=REPOSITORY_ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=60,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                payload = json.loads(result.stdout)
                self.assertEqual(payload["status"], "PROVISIONED")
                self.assertEqual(payload["data"]["tenant"], tenant)
                self.assertEqual(payload["data"]["tenant_short_code"], short_code)
                self.assertEqual(payload["data"]["backup_namespace"], "NOT_CONFIGURED")
                database = root / "data" / f"dopamatrix_{tenant}.db"
                self.assertTrue(database.is_file())
                self.assertFalse(Path(str(database) + "-wal").exists())
                self.assertFalse(Path(str(database) + "-shm").exists())

    def test_cli_human_and_json_output_are_bounded(self):
        outcome = type(
            "Outcome",
            (),
            {
                "error_code": None,
                "status": "PROVISIONED",
                "message": "TENANT PROVISIONED: ph-elv-0001",
                "data": {
                    "tenant": "ph-elv-0001",
                    "tenant_short_code": "elv0001",
                    "database_path": "data/dopamatrix_ph-elv-0001.db",
                },
                "exit_code": 0,
            },
        )()
        for json_mode in (False, True):
            stdout, stderr = io.StringIO(), io.StringIO()
            arguments = (
                *(('--json',) if json_mode else ()),
                "tenant",
                "provision",
                "--tenant",
                "ph-elv-0001",
                "--approval-ref",
                "A",
            )
            with patch("src.api.operator_tenant_provision.provision_tenant", return_value=outcome):
                exit_code = run_operator_cli(arguments, stdout=stdout, stderr=stderr)
            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertNotIn(str(REPOSITORY_ROOT), stdout.getvalue())
            if json_mode:
                self.assertEqual(len(stdout.getvalue().splitlines()), 1)
                self.assertEqual(json.loads(stdout.getvalue())["schema_version"], 1)
            else:
                self.assertEqual(stdout.getvalue(), "TENANT PROVISIONED: ph-elv-0001\n")

    def test_cli_failure_output_contract_for_representative_categories(self):
        failures = (
            (3, OPERATOR_TENANT_INVALID),
            (3, OPERATOR_APPROVAL_REF_INVALID),
            (4, OPERATOR_TENANT_COLLISION),
            (4, OPERATOR_RUNTIME_MUTATION_BUSY),
            (7, OPERATOR_TENANT_PARTIAL_PROVISIONING_REVIEW_REQUIRED),
            (8, "OPERATOR_TENANT_PROVISION_SUBSYSTEM_FAILED"),
        )
        for exit_code, error_code in failures:
            outcome = SimpleNamespace(
                error_code=error_code,
                status="ERROR",
                message="bounded failure",
                data={},
                exit_code=exit_code,
            )
            for json_mode in (False, True):
                with self.subTest(exit_code=exit_code, json_mode=json_mode):
                    stdout, stderr = io.StringIO(), io.StringIO()
                    arguments = (
                        *(('--json',) if json_mode else ()),
                        "tenant",
                        "provision",
                        "--tenant",
                        "ph-elv-0001",
                        "--approval-ref",
                        "A",
                    )
                    with patch(
                        "src.api.operator_tenant_provision.provision_tenant",
                        return_value=outcome,
                    ):
                        observed = run_operator_cli(arguments, stdout=stdout, stderr=stderr)
                    self.assertEqual(observed, exit_code)
                    self.assertNotIn("Traceback", stdout.getvalue() + stderr.getvalue())
                    if json_mode:
                        self.assertEqual(stderr.getvalue(), "")
                        self.assertEqual(len(stdout.getvalue().splitlines()), 1)
                        payload = json.loads(stdout.getvalue())
                        self.assertEqual(payload["schema_version"], 1)
                        self.assertEqual(payload["error_code"], error_code)
                    else:
                        self.assertEqual(stdout.getvalue(), "")
                        self.assertTrue(stderr.getvalue().startswith(f"{error_code}:"))


if __name__ == "__main__":
    unittest.main()
