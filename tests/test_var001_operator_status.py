"""H4-2 strict non-mutating operator status regressions."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.api.operator_cli import run_operator_cli
from src.api.operator_status import (
    OPERATOR_ASSIGNMENT_SECRET_VERIFICATION_FAILED,
    OPERATOR_SNAPSHOT_INTEGRITY_FAILED,
    OPERATOR_STATUS_INTEGRITY_FAILED,
    OPERATOR_STATUS_SUBSYSTEM_FAILED,
    OPERATOR_TENANT_INVALID,
    OPERATOR_TENANT_NOT_FOUND,
    observe_operator_status,
)
from src.api.policy_profiles import (
    OPERATIONAL_SNAPSHOT_SETTING_KEY,
    PhilippineSeedStage,
    build_applied_operational_snapshot,
    canonical_snapshot_json,
    materialize_philippine_seed_profile,
)
from src.api.runtime_paths import RuntimeMode, resolve_runtime_paths
from src.api.secret_store import (
    DPAPI_CURRENT_USER_V1,
    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = REPOSITORY_ROOT / "main.py"
_SYNTHETIC_SECRET = "synthetic-assignment-value-for-test-only"


class FakeProtector:
    scheme = DPAPI_CURRENT_USER_V1

    def protect(self, plaintext: bytes) -> bytes:
        return b"test-protected:" + plaintext[::-1]

    def unprotect(self, ciphertext: bytes) -> bytes:
        prefix = b"test-protected:"
        if not ciphertext.startswith(prefix):
            raise ValueError("synthetic-ciphertext-sentinel")
        return ciphertext[len(prefix) :][::-1]


class FailingProtector(FakeProtector):
    def unprotect(self, ciphertext: bytes) -> bytes:
        raise RuntimeError("synthetic-dpapi-internal-sentinel")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(root: Path) -> tuple[str, ...]:
    if not root.exists():
        return ()
    return tuple(
        sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
    )


def _schema(path: Path) -> tuple[tuple[str, str, str], ...]:
    with closing(sqlite3.connect(path)) as connection:
        return tuple(
            connection.execute(
                "SELECT type, name, sql FROM sqlite_master ORDER BY type, name;"
            ).fetchall()
        )


def _sidecars(path: Path) -> tuple[str, ...]:
    return tuple(
        str(candidate.name)
        for candidate in (
            Path(str(path) + "-wal"),
            Path(str(path) + "-shm"),
            Path(str(path) + "-journal"),
        )
        if candidate.exists()
    )


def _sqlite_artifact_state(path: Path) -> tuple[tuple[str, bool, int, int, str], ...]:
    state = []
    for label, candidate in (
        ("main", path),
        ("wal", Path(str(path) + "-wal")),
        ("shm", Path(str(path) + "-shm")),
        ("journal", Path(str(path) + "-journal")),
    ):
        if candidate.exists():
            metadata = candidate.stat()
            state.append(
                (label, True, metadata.st_size, metadata.st_mtime_ns, _hash(candidate))
            )
        else:
            state.append((label, False, 0, 0, ""))
    return tuple(state)


def _sqlite_header_versions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:20]
    if len(header) < 20 or not header.startswith(b"SQLite format 3\x00"):
        raise AssertionError("fixture is not an SQLite database")
    return header[18], header[19]


def _open_wal_global_fixture(
    path: Path,
    protector: FakeProtector,
    *,
    serialized_snapshot: str | None = None,
) -> tuple[str, sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    mode = connection.execute("PRAGMA journal_mode=WAL;").fetchone()[0]
    connection.execute(
        "CREATE TABLE app_settings (key_name TEXT PRIMARY KEY, key_value TEXT);"
    )
    connection.execute(
        "CREATE TABLE secure_settings ("
        "key_name TEXT PRIMARY KEY, encryption_scheme TEXT NOT NULL, "
        "ciphertext BLOB NOT NULL, updated_at TEXT NOT NULL);"
    )
    connection.commit()
    if serialized_snapshot is not None:
        connection.execute(
            "INSERT INTO app_settings (key_name, key_value) VALUES (?, ?);",
            (OPERATIONAL_SNAPSHOT_SETTING_KEY, serialized_snapshot),
        )
        connection.execute(
            "INSERT INTO secure_settings "
            "(key_name, encryption_scheme, ciphertext, updated_at) "
            "VALUES (?, ?, ?, ?);",
            (
                RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
                protector.scheme,
                sqlite3.Binary(protector.protect(_SYNTHETIC_SECRET.encode("utf-8"))),
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()
    return mode, connection


def _create_global_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)):
        pass


def _create_app_settings(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE app_settings (key_name TEXT PRIMARY KEY, key_value TEXT);"
        )


def _create_secure_settings(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE secure_settings ("
            "key_name TEXT PRIMARY KEY, encryption_scheme TEXT NOT NULL, "
            "ciphertext BLOB NOT NULL, updated_at TEXT NOT NULL);"
        )


def _insert_secret(
    path: Path,
    protector: FakeProtector,
    secret: str = _SYNTHETIC_SECRET,
) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO secure_settings "
            "(key_name, encryption_scheme, ciphertext, updated_at) "
            "VALUES (?, ?, ?, ?);",
            (
                RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
                protector.scheme,
                sqlite3.Binary(protector.protect(secret.encode("utf-8"))),
                "2026-01-01T00:00:00+00:00",
            ),
        )


def _valid_snapshot(tenant: str = "ph-elv-0001") -> str:
    values = materialize_philippine_seed_profile(
        tenant_id=tenant,
        generation="phseed-elv0001-bal-20260921-r1",
        stage=PhilippineSeedStage.SAFE_OFF,
    )
    snapshot = build_applied_operational_snapshot(
        effective_values=values,
        stage=PhilippineSeedStage.SAFE_OFF,
        applied_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        audit_metadata={"operator": "synthetic-test"},
        assignment_secret=_SYNTHETIC_SECRET,
    )
    return snapshot.canonical_json()


def _insert_snapshot(path: Path, serialized: str) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "INSERT INTO app_settings (key_name, key_value) VALUES (?, ?);",
            (OPERATIONAL_SNAPSHOT_SETTING_KEY, serialized),
        )


def _create_tenant_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE fixture_marker (value TEXT NOT NULL);")


@contextmanager
def _cli_dependencies(paths, protector):
    with patch(
        "src.api.operator_status.resolve_runtime_paths",
        return_value=paths,
    ), patch(
        "src.api.operator_status.create_platform_secret_protector",
        return_value=protector,
    ):
        yield


def _run_cli(arguments: tuple[str, ...], paths, protector):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with _cli_dependencies(paths, protector):
        exit_code = run_operator_cli(arguments, stdout=stdout, stderr=stderr)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class StrictNonMutatingStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.runtime = self.base / "runtime-does-not-exist"
        self.paths = resolve_runtime_paths(
            mode=RuntimeMode.TEST,
            runtime_root=self.runtime,
        )
        self.protector = FakeProtector()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_fresh_install_config_and_secret_status_leave_root_absent(self):
        self.assertFalse(self.runtime.exists())
        before = _inventory(self.base)

        config = observe_operator_status(
            ("config", "status"), paths=self.paths, protector=self.protector
        )
        secret = observe_operator_status(
            ("secret", "assignment", "status"),
            paths=self.paths,
            protector=self.protector,
        )

        self.assertEqual((config.exit_code, config.status), (0, "NOT_INITIALIZED"))
        self.assertEqual((secret.exit_code, secret.status), (0, "ABSENT"))
        self.assertFalse(self.runtime.exists())
        self.assertEqual(_inventory(self.base), before)

    def test_existing_root_without_global_db_is_unchanged(self):
        self.runtime.mkdir()
        before = _inventory(self.runtime)

        config = observe_operator_status(
            ("config", "status"), paths=self.paths, protector=self.protector
        )
        secret = observe_operator_status(
            ("secret", "assignment", "status"),
            paths=self.paths,
            protector=self.protector,
        )

        self.assertEqual(config.status, "NOT_INITIALIZED")
        self.assertEqual(secret.status, "ABSENT")
        self.assertFalse(self.paths.settings_db_path.exists())
        self.assertEqual(_inventory(self.runtime), before)

    def test_empty_existing_global_db_is_read_only_and_safe_off_missing(self):
        _create_global_db(self.paths.settings_db_path)
        before = (
            _hash(self.paths.settings_db_path),
            self.paths.settings_db_path.stat().st_size,
            _schema(self.paths.settings_db_path),
            _sidecars(self.paths.settings_db_path),
        )

        config = observe_operator_status(
            ("config", "status"), paths=self.paths, protector=self.protector
        )
        secret = observe_operator_status(
            ("secret", "assignment", "status"),
            paths=self.paths,
            protector=self.protector,
        )

        self.assertEqual(config.status, "SAFE_OFF_MISSING")
        self.assertEqual(secret.status, "ABSENT")
        self.assertEqual(
            (
                _hash(self.paths.settings_db_path),
                self.paths.settings_db_path.stat().st_size,
                _schema(self.paths.settings_db_path),
                _sidecars(self.paths.settings_db_path),
            ),
            before,
        )

    def test_sqlite_master_precedes_optional_table_queries_and_uri_is_read_only(self):
        _create_global_db(self.paths.settings_db_path)
        statements: list[str] = []
        connect_calls: list[tuple[str, bool]] = []
        real_connect = sqlite3.connect

        def recording_connect(database, *args, **kwargs):
            connect_calls.append((str(database), bool(kwargs.get("uri"))))
            connection = real_connect(database, *args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection

        with patch("src.api.operator_status.sqlite3.connect", side_effect=recording_connect):
            outcome = observe_operator_status(
                ("config", "status"), paths=self.paths, protector=self.protector
            )

        self.assertEqual(outcome.status, "SAFE_OFF_MISSING")
        self.assertTrue(connect_calls[0][0].endswith("?mode=ro&immutable=1"))
        self.assertTrue(connect_calls[0][1])
        optional = [
            index
            for index, statement in enumerate(statements)
            if "FROM app_settings" in statement or "FROM secure_settings" in statement
        ]
        master = [
            index for index, statement in enumerate(statements) if "sqlite_master" in statement
        ]
        self.assertTrue(master)
        self.assertFalse(optional)

    def test_table_and_row_absence_are_observed_without_schema_change(self):
        for case in ("tables-absent", "rows-absent"):
            with self.subTest(case=case):
                root = self.base / case
                paths = resolve_runtime_paths(mode=RuntimeMode.TEST, runtime_root=root)
                _create_global_db(paths.settings_db_path)
                if case == "rows-absent":
                    _create_app_settings(paths.settings_db_path)
                    _create_secure_settings(paths.settings_db_path)
                before = (_hash(paths.settings_db_path), _schema(paths.settings_db_path))
                config = observe_operator_status(
                    ("config", "status"), paths=paths, protector=self.protector
                )
                secret = observe_operator_status(
                    ("secret", "assignment", "status"),
                    paths=paths,
                    protector=self.protector,
                )
                self.assertEqual(config.status, "SAFE_OFF_MISSING")
                self.assertEqual(secret.status, "ABSENT")
                self.assertEqual((_hash(paths.settings_db_path), _schema(paths.settings_db_path)), before)
                self.assertEqual(_sidecars(paths.settings_db_path), ())

    def test_valid_snapshot_is_canonically_validated_and_unchanged(self):
        _create_global_db(self.paths.settings_db_path)
        _create_app_settings(self.paths.settings_db_path)
        _create_secure_settings(self.paths.settings_db_path)
        _insert_secret(self.paths.settings_db_path, self.protector)
        _insert_snapshot(self.paths.settings_db_path, _valid_snapshot())
        before = (_hash(self.paths.settings_db_path), _schema(self.paths.settings_db_path))

        outcome = observe_operator_status(
            ("config", "status"), paths=self.paths, protector=self.protector
        )

        self.assertEqual((outcome.exit_code, outcome.status), (0, "ACTIVE"))
        self.assertEqual(outcome.data["tenant"], "ph-elv-0001")
        self.assertEqual(outcome.data["exact_basis_points"], 0)
        self.assertTrue(outcome.data["kill_switch"])
        self.assertEqual(outcome.data["assignment_secret_status"], "PRESENT")
        self.assertEqual((_hash(self.paths.settings_db_path), _schema(self.paths.settings_db_path)), before)
        self.assertEqual(_sidecars(self.paths.settings_db_path), ())

    def test_wal_mode_clean_global_database_creates_no_sidecars(self):
        mode, writer = _open_wal_global_fixture(
            self.paths.settings_db_path,
            self.protector,
        )
        writer.close()
        self.assertEqual(mode.lower(), "wal")
        self.assertEqual(_sqlite_header_versions(self.paths.settings_db_path), (2, 2))
        self.assertEqual(_sidecars(self.paths.settings_db_path), ())
        before = _sqlite_artifact_state(self.paths.settings_db_path)

        config = observe_operator_status(
            ("config", "status"), paths=self.paths, protector=self.protector
        )
        secret = observe_operator_status(
            ("secret", "assignment", "status"),
            paths=self.paths,
            protector=self.protector,
        )

        self.assertEqual((config.exit_code, config.status), (0, "SAFE_OFF_MISSING"))
        self.assertEqual((secret.exit_code, secret.status), (0, "ABSENT"))
        self.assertEqual(_sqlite_artifact_state(self.paths.settings_db_path), before)

    def test_wal_mode_clean_canonical_snapshot_and_tenant_are_current_and_unchanged(self):
        mode, writer = _open_wal_global_fixture(
            self.paths.settings_db_path,
            self.protector,
            serialized_snapshot=_valid_snapshot(),
        )
        writer.close()
        tenant = "ph-elv-0001"
        tenant_path = self.paths.tenant_database_path(tenant)
        tenant_path.parent.mkdir(parents=True, exist_ok=True)
        tenant_writer = sqlite3.connect(tenant_path)
        tenant_mode = tenant_writer.execute("PRAGMA journal_mode=WAL;").fetchone()[0]
        tenant_writer.execute("CREATE TABLE fixture_marker (value TEXT NOT NULL);")
        tenant_writer.execute("INSERT INTO fixture_marker VALUES ('committed');")
        tenant_writer.commit()
        tenant_writer.close()

        self.assertEqual((mode.lower(), tenant_mode.lower()), ("wal", "wal"))
        self.assertEqual(_sqlite_header_versions(self.paths.settings_db_path), (2, 2))
        self.assertEqual(_sqlite_header_versions(tenant_path), (2, 2))
        self.assertEqual(_sidecars(self.paths.settings_db_path), ())
        self.assertEqual(_sidecars(tenant_path), ())
        global_before = _sqlite_artifact_state(self.paths.settings_db_path)
        tenant_before = _sqlite_artifact_state(tenant_path)

        config = observe_operator_status(
            ("config", "status"), paths=self.paths, protector=self.protector
        )
        seed = observe_operator_status(
            ("seed", "status"),
            tenant_id=tenant,
            paths=self.paths,
            protector=self.protector,
        )

        self.assertEqual((config.exit_code, config.status), (0, "ACTIVE"))
        self.assertEqual((seed.exit_code, seed.status), (0, "ACTIVE"))
        self.assertEqual(config.data["tenant"], tenant)
        self.assertEqual(seed.data["generation"], config.data["generation"])
        self.assertEqual(_sqlite_artifact_state(self.paths.settings_db_path), global_before)
        self.assertEqual(_sqlite_artifact_state(tenant_path), tenant_before)

    def test_existing_active_wal_state_fails_closed_without_stale_projection_or_mutation(self):
        mode, writer = _open_wal_global_fixture(
            self.paths.settings_db_path,
            self.protector,
        )
        try:
            writer.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            writer.execute(
                "INSERT INTO app_settings (key_name, key_value) VALUES (?, ?);",
                (OPERATIONAL_SNAPSHOT_SETTING_KEY, _valid_snapshot()),
            )
            writer.commit()
            self.assertEqual(mode.lower(), "wal")
            self.assertEqual(
                set(_sidecars(self.paths.settings_db_path)),
                {"dopamatrix.db-wal", "dopamatrix.db-shm"},
            )

            immutable_uri = (
                self.paths.settings_db_path.resolve(strict=True).as_uri()
                + "?mode=ro&immutable=1"
            )
            with closing(sqlite3.connect(immutable_uri, uri=True)) as stale_reader:
                stale_row = stale_reader.execute(
                    "SELECT key_value FROM app_settings WHERE key_name = ?;",
                    (OPERATIONAL_SNAPSHOT_SETTING_KEY,),
                ).fetchone()
            self.assertIsNone(stale_row)
            before = _sqlite_artifact_state(self.paths.settings_db_path)

            outcome = observe_operator_status(
                ("config", "status"), paths=self.paths, protector=self.protector
            )

            self.assertEqual(outcome.exit_code, 8)
            self.assertEqual(outcome.error_code, OPERATOR_STATUS_SUBSYSTEM_FAILED)
            self.assertEqual(_sqlite_artifact_state(self.paths.settings_db_path), before)
        finally:
            writer.close()

    def test_incomplete_wal_sidecar_state_fails_integrity_without_repair(self):
        source = self.base / "wal-source" / "source.db"
        mode, writer = _open_wal_global_fixture(
            source,
            self.protector,
        )
        try:
            writer.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            writer.execute(
                "INSERT INTO app_settings (key_name, key_value) VALUES (?, ?);",
                (OPERATIONAL_SNAPSHOT_SETTING_KEY, _valid_snapshot()),
            )
            writer.commit()
            self.assertEqual(mode.lower(), "wal")
            destination = self.paths.settings_db_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            shutil.copy2(Path(str(source) + "-wal"), Path(str(destination) + "-wal"))
            self.assertFalse(Path(str(destination) + "-shm").exists())
            before = _sqlite_artifact_state(destination)

            outcome = observe_operator_status(
                ("config", "status"), paths=self.paths, protector=self.protector
            )

            self.assertEqual(outcome.exit_code, 6)
            self.assertEqual(outcome.error_code, OPERATOR_STATUS_INTEGRITY_FAILED)
            self.assertEqual(_sqlite_artifact_state(destination), before)
        finally:
            writer.close()

    def test_malformed_and_policy_invalid_snapshots_fail_integrity_without_repair(self):
        valid_payload = json.loads(_valid_snapshot())
        invalid_values = dict(valid_payload["effective_values"])
        invalid_values["RESERVATION_LEASE_TTL_SECONDS"] = "180.0"
        valid_payload["effective_values"] = invalid_values
        cases = ("{malformed", canonical_snapshot_json(valid_payload))

        for index, serialized in enumerate(cases):
            with self.subTest(index=index):
                root = self.base / f"invalid-{index}"
                paths = resolve_runtime_paths(mode=RuntimeMode.TEST, runtime_root=root)
                _create_global_db(paths.settings_db_path)
                _create_app_settings(paths.settings_db_path)
                _create_secure_settings(paths.settings_db_path)
                _insert_secret(paths.settings_db_path, self.protector)
                _insert_snapshot(paths.settings_db_path, serialized)
                before = _hash(paths.settings_db_path)
                outcome = observe_operator_status(
                    ("config", "status"), paths=paths, protector=self.protector
                )
                self.assertEqual(outcome.exit_code, 6)
                self.assertEqual(outcome.error_code, OPERATOR_SNAPSHOT_INTEGRITY_FAILED)
                self.assertEqual(_hash(paths.settings_db_path), before)
                self.assertEqual(_sidecars(paths.settings_db_path), ())

    def test_corrupt_sqlite_is_bounded_and_not_replaced(self):
        self.paths.settings_db_path.parent.mkdir(parents=True)
        self.paths.settings_db_path.write_bytes(b"synthetic-not-a-sqlite-database")
        before = self.paths.settings_db_path.read_bytes()

        outcome = observe_operator_status(
            ("config", "status"), paths=self.paths, protector=self.protector
        )

        self.assertEqual(outcome.exit_code, 6)
        self.assertEqual(outcome.error_code, OPERATOR_STATUS_INTEGRITY_FAILED)
        self.assertEqual(self.paths.settings_db_path.read_bytes(), before)
        self.assertEqual(_sidecars(self.paths.settings_db_path), ())

    def test_secret_absent_for_missing_db_table_and_row(self):
        paths_by_case = {}
        paths_by_case["db"] = self.paths
        for case in ("table", "row"):
            paths = resolve_runtime_paths(
                mode=RuntimeMode.TEST,
                runtime_root=self.base / f"secret-{case}",
            )
            _create_global_db(paths.settings_db_path)
            if case == "row":
                _create_secure_settings(paths.settings_db_path)
            paths_by_case[case] = paths

        for case, paths in paths_by_case.items():
            with self.subTest(case=case):
                before = _inventory(self.base)
                outcome = observe_operator_status(
                    ("secret", "assignment", "status"),
                    paths=paths,
                    protector=self.protector,
                )
                self.assertEqual((outcome.exit_code, outcome.status), (0, "ABSENT"))
                self.assertEqual(outcome.data, {"assignment_secret_status": "ABSENT"})
                self.assertEqual(_inventory(self.base), before)

    def test_secret_present_and_dpapi_failure_are_redacted_and_read_only(self):
        _create_global_db(self.paths.settings_db_path)
        _create_secure_settings(self.paths.settings_db_path)
        _insert_secret(self.paths.settings_db_path, self.protector)
        before = _hash(self.paths.settings_db_path)

        present = observe_operator_status(
            ("secret", "assignment", "status"),
            paths=self.paths,
            protector=self.protector,
        )
        failed = observe_operator_status(
            ("secret", "assignment", "status"),
            paths=self.paths,
            protector=FailingProtector(),
        )

        self.assertEqual((present.exit_code, present.status), (0, "PRESENT"))
        self.assertEqual(present.data, {"assignment_secret_status": "PRESENT"})
        self.assertEqual(failed.exit_code, 8)
        self.assertEqual(
            failed.error_code,
            OPERATOR_ASSIGNMENT_SECRET_VERIFICATION_FAILED,
        )
        rendered = repr((present, failed))
        for sentinel in (
            _SYNTHETIC_SECRET,
            "synthetic-dpapi-internal-sentinel",
            "test-protected:",
        ):
            self.assertNotIn(sentinel, rendered)
        self.assertEqual(_hash(self.paths.settings_db_path), before)
        self.assertEqual(_sidecars(self.paths.settings_db_path), ())

    def test_tenant_validation_and_missing_tenant_do_not_create_data(self):
        for tenant in ("PH-ELV-0001", "ph_elv_0001", "ph-elv-0000", "../ph-elv-0001"):
            with self.subTest(tenant=tenant):
                outcome = observe_operator_status(
                    ("seed", "status"),
                    tenant_id=tenant,
                    paths=self.paths,
                    protector=self.protector,
                )
                self.assertEqual(outcome.exit_code, 3)
                self.assertEqual(outcome.error_code, OPERATOR_TENANT_INVALID)
        missing = observe_operator_status(
            ("seed", "status"),
            tenant_id="ph-elv-0001",
            paths=self.paths,
            protector=self.protector,
        )
        self.assertEqual(missing.exit_code, 5)
        self.assertEqual(missing.error_code, OPERATOR_TENANT_NOT_FOUND)
        self.assertFalse(self.runtime.exists())

    def test_existing_tenant_missing_valid_and_invalid_snapshot_are_read_only(self):
        tenant = "ph-elv-0001"
        _create_tenant_db(self.paths.tenant_database_path(tenant))
        tenant_before = (
            _hash(self.paths.tenant_database_path(tenant)),
            _schema(self.paths.tenant_database_path(tenant)),
        )
        missing = observe_operator_status(
            ("seed", "status"),
            tenant_id=tenant,
            paths=self.paths,
            protector=self.protector,
        )
        self.assertEqual((missing.exit_code, missing.status), (0, "SAFE_OFF_MISSING"))

        _create_global_db(self.paths.settings_db_path)
        _create_app_settings(self.paths.settings_db_path)
        _create_secure_settings(self.paths.settings_db_path)
        _insert_secret(self.paths.settings_db_path, self.protector)
        _insert_snapshot(self.paths.settings_db_path, _valid_snapshot(tenant))
        global_before = _hash(self.paths.settings_db_path)
        active = observe_operator_status(
            ("seed", "status"),
            tenant_id=tenant,
            paths=self.paths,
            protector=self.protector,
        )
        self.assertEqual((active.exit_code, active.status), (0, "ACTIVE"))
        self.assertEqual(active.data["tenant"], tenant)

        with closing(sqlite3.connect(self.paths.settings_db_path)) as connection, connection:
            connection.execute(
                "UPDATE app_settings SET key_value = ? WHERE key_name = ?;",
                ("{invalid", OPERATIONAL_SNAPSHOT_SETTING_KEY),
            )
        invalid_before = _hash(self.paths.settings_db_path)
        invalid = observe_operator_status(
            ("seed", "status"),
            tenant_id=tenant,
            paths=self.paths,
            protector=self.protector,
        )
        self.assertEqual(invalid.exit_code, 6)
        self.assertEqual(invalid.error_code, OPERATOR_SNAPSHOT_INTEGRITY_FAILED)
        self.assertEqual(_hash(self.paths.settings_db_path), invalid_before)
        self.assertNotEqual(global_before, invalid_before)
        self.assertEqual(
            (
                _hash(self.paths.tenant_database_path(tenant)),
                _schema(self.paths.tenant_database_path(tenant)),
            ),
            tenant_before,
        )
        self.assertEqual(_sidecars(self.paths.tenant_database_path(tenant)), ())
        self.assertEqual(_sidecars(self.paths.settings_db_path), ())

    def test_human_and_json_output_contracts_for_all_status_commands(self):
        _create_tenant_db(self.paths.tenant_database_path("ph-elv-0001"))
        successes = (
            ("config", "status"),
            ("seed", "status", "--tenant", "ph-elv-0001"),
            ("secret", "assignment", "status"),
        )
        for arguments in successes:
            with self.subTest(arguments=arguments, mode="human"):
                code, stdout, stderr = _run_cli(arguments, self.paths, self.protector)
                self.assertEqual(code, 0)
                self.assertTrue(stdout.startswith("STATUS: "))
                self.assertEqual(stderr, "")
            with self.subTest(arguments=arguments, mode="json"):
                code, stdout, stderr = _run_cli(
                    ("--json", *arguments), self.paths, self.protector
                )
                self.assertEqual(code, 0)
                self.assertEqual(stderr, "")
                self.assertEqual(len(stdout.splitlines()), 1)
                payload = json.loads(stdout)
                self.assertEqual(payload["schema_version"], 1)
                self.assertIsNone(payload["error_code"])
                self.assertEqual(payload["command"], " ".join(arguments[:2]) if arguments[0] != "secret" else "secret assignment status")

        code, stdout, stderr = _run_cli(
            ("seed", "status", "--tenant", "invalid"),
            self.paths,
            self.protector,
        )
        self.assertEqual(code, 3)
        self.assertEqual(stdout, "")
        self.assertTrue(stderr.startswith(f"{OPERATOR_TENANT_INVALID}:"))

        code, stdout, stderr = _run_cli(
            ("--json", "seed", "status", "--tenant", "invalid"),
            self.paths,
            self.protector,
        )
        self.assertEqual(code, 3)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["error_code"], OPERATOR_TENANT_INVALID)
        self.assertEqual(payload["status"], "ERROR")

    def test_redaction_excludes_secret_ciphertext_hash_and_raw_error_sentinels(self):
        _create_global_db(self.paths.settings_db_path)
        _create_secure_settings(self.paths.settings_db_path)
        _insert_secret(self.paths.settings_db_path, self.protector)
        digest_sentinel = hashlib.sha256(_SYNTHETIC_SECRET.encode()).hexdigest()

        for arguments in (
            ("secret", "assignment", "status"),
            ("--json", "secret", "assignment", "status"),
        ):
            code, stdout, stderr = _run_cli(
                arguments,
                self.paths,
                FailingProtector(),
            )
            self.assertEqual(code, 8)
            combined = stdout + stderr
            for sentinel in (
                _SYNTHETIC_SECRET,
                "test-protected:",
                digest_sentinel,
                "synthetic-dpapi-internal-sentinel",
                "synthetic-ciphertext-sentinel",
            ):
                self.assertNotIn(sentinel, combined)
            self.assertNotIn("Traceback", combined)

    def test_status_subprocess_does_not_initialize_paths_or_import_server_graph(self):
        probe_root = self.base / "subprocess-runtime-must-not-exist"
        script = f"""
import json, runpy, sys
from pathlib import Path
from unittest.mock import patch
import src.api.runtime_paths as runtime_paths
paths = runtime_paths.resolve_runtime_paths(
    mode=runtime_paths.RuntimeMode.TEST,
    runtime_root={str(probe_root)!r},
)
runtime_paths.initialize_runtime_paths = lambda *a, **k: (_ for _ in ()).throw(
    AssertionError('initialize_runtime_paths reached')
)
import src.api.operator_status as operator_status
operator_status.resolve_runtime_paths = lambda: paths
sys.argv = [{str(MAIN_PATH)!r}, 'operator', 'config', 'status']
try:
    runpy.run_path({str(MAIN_PATH)!r}, run_name='__main__')
except SystemExit as exc:
    exit_code = int(exc.code)
print(json.dumps({{
    'exit_code': exit_code,
    'runtime_root_exists': Path({str(probe_root)!r}).exists(),
    'runtime_paths_initialized': runtime_paths.get_initialized_runtime_paths() is not None,
    'fastapi': 'fastapi' in sys.modules,
    'uvicorn': 'uvicorn' in sys.modules,
    'ngrok': 'pyngrok.ngrok' in sys.modules,
    'routers': sorted(name for name in sys.modules if name.startswith('src.api.routes')),
}}))
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(observed["exit_code"], 0)
        self.assertFalse(observed["runtime_root_exists"])
        self.assertFalse(observed["runtime_paths_initialized"])
        self.assertFalse(observed["fastapi"])
        self.assertFalse(observed["uvicorn"])
        self.assertFalse(observed["ngrok"])
        self.assertEqual(observed["routers"], [])

if __name__ == "__main__":
    unittest.main()
