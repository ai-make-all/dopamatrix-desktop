"""H4-5 RuntimePaths-bound backup create/verify regressions."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from src.api import backup_restore, delivery_output, operator_backup
from src.api.backup_restore import (
    BackupDestinationExistsError,
    BackupIntegrityError,
    create_backup_bundle,
    verify_backup_bundle,
)
from src.api.delivery_output import DeliverySettingsReadError, read_current_delivery_root
from src.api.operator_backup import (
    OPERATOR_BACKUP_BUNDLE_NOT_FOUND,
    OPERATOR_BACKUP_DESTINATION_PROTECTED,
    OPERATOR_BACKUP_INTERNAL_FAILED,
    OPERATOR_BACKUP_PATH_INVALID,
    OPERATOR_BACKUP_SOURCE_NOT_FOUND,
    OPERATOR_BACKUP_SUBSYSTEM_FAILED,
    create_operator_backup,
    verify_operator_backup,
)
from src.api.operator_cli import OPERATOR_COMMAND_NOT_IMPLEMENTED, run_operator_cli
from src.api.runtime_paths import (
    LegacyRuntimeMigrationRequired,
    RuntimeMode,
    RuntimePaths,
    RuntimePathsInitializationConflict,
    RuntimeRootUnavailable,
    temporary_test_runtime_paths,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
APPROVED_TENANTS = ("ph-elv-0001", "ph-bty-0001", "ph-hwh-0001")
SYNTHETIC_SECRET_MARKER = b"synthetic-h4-5-secret-marker-never-real"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _paths(root: Path, *, create: bool = True) -> RuntimePaths:
    if create:
        (root / "data").mkdir(parents=True)
        (root / "output").mkdir()
    return RuntimePaths(
        RuntimeMode.TEST,
        root,
        root / "dopamatrix.db",
        root / "data",
        root / "output",
    )


def _create_tenant_fixture(
    paths: RuntimePaths,
    tenant: str,
    *,
    asset_name: str | None = None,
) -> tuple[Path, Path]:
    paths.tenant_data_dir.mkdir(parents=True, exist_ok=True)
    paths.internal_output_root.mkdir(parents=True, exist_ok=True)
    asset = paths.internal_output_root / (asset_name or f"final_{tenant}.mp4")
    asset.write_bytes((f"authoritative:{tenant}:".encode("ascii")) + b"A" * 4096)
    database = paths.tenant_database_path(tenant)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE task_history "
            "(id INTEGER PRIMARY KEY, output_assets TEXT NOT NULL);"
        )
        connection.execute(
            "CREATE TABLE video_tasks (id INTEGER PRIMARY KEY, marker TEXT);"
        )
        connection.execute(
            "INSERT INTO task_history(id, output_assets) VALUES (?, ?);",
            (1, json.dumps([{"file_path": f"output/{asset.name}"}])),
        )
        connection.execute(
            "INSERT INTO video_tasks(id, marker) VALUES (1, ?);",
            (f"runtime-{tenant}",),
        )
        connection.commit()
    finally:
        connection.close()
    return database, asset


def _tree_state(root: Path) -> tuple[tuple[object, ...], ...]:
    entries: list[tuple[object, ...]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            metadata = path.stat()
            entries.append(
                ("file", relative, metadata.st_size, metadata.st_mtime_ns, _sha256(path))
            )
        else:
            entries.append(("dir", relative))
    return tuple(entries)


def _invoke(*arguments: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run_operator_cli(arguments, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def _subprocess_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)
    return environment


def _sqlite_connect_that_mutates_on_close(mutation):
    original_connect = sqlite3.connect
    mutated = False

    class _MutatingConnection(sqlite3.Connection):
        def close(self) -> None:
            nonlocal mutated
            try:
                if not mutated:
                    mutated = True
                    mutation(original_connect)
            finally:
                super().close()

    def connect(*args, **kwargs):
        return original_connect(*args, factory=_MutatingConnection, **kwargs)

    return connect


class OperatorBackupCreateTests(unittest.TestCase):
    def test_create_succeeds_for_exactly_all_three_approved_tenants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            for tenant in APPROVED_TENANTS:
                _create_tenant_fixture(paths, tenant)
                destination = base / f"bundle-{tenant}"
                outcome = create_operator_backup(
                    tenant,
                    str(destination),
                    paths_resolver=lambda: paths,
                    delivery_root_reader=lambda unused: "",
                )
                with self.subTest(tenant=tenant):
                    self.assertEqual((outcome.exit_code, outcome.status), (0, "VALID"))
                    self.assertEqual(outcome.data["tenant"], tenant)
                    self.assertEqual(outcome.data["asset_count"], 1)
                    manifest = verify_backup_bundle(destination)
                    self.assertEqual(manifest["canonical_tenant_id"], tenant)
                    self.assertEqual(manifest["counts"]["task_history"], 1)

    def test_invalid_tenant_and_invalid_path_fail_before_runtime_or_destination_mutation(self) -> None:
        invalid_tenants = (
            "PH-ELV-0001",
            "ph-elv-0002",
            "default",
            " test ",
            "ph_elv_0001",
            "ph-elv-0001/../x",
        )
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "must-not-exist"
            destination = base / "parent-must-not-exist" / "bundle"
            for tenant in invalid_tenants:
                with self.subTest(tenant=tenant):
                    outcome = create_operator_backup(
                        tenant,
                        str(destination),
                        paths_resolver=lambda: (_ for _ in ()).throw(
                            AssertionError("RuntimePaths resolved for invalid tenant")
                        ),
                    )
                    self.assertEqual(outcome.exit_code, 3)
                    self.assertFalse(runtime.exists())
                    self.assertFalse(destination.parent.exists())

            paths = _paths(runtime, create=False)
            invalid_paths = ("", "   ", "relative/path", "./backup", "../backup", "\x00bad")
            if os.name == "nt":
                invalid_paths += ("C:relative", "C:\\bad?name\\bundle")
            for value in invalid_paths:
                with self.subTest(path=value):
                    outcome = create_operator_backup(
                        "ph-elv-0001",
                        value,
                        paths_resolver=lambda: (_ for _ in ()).throw(
                            AssertionError("RuntimePaths resolved for invalid path")
                        ),
                    )
                    self.assertEqual(outcome.exit_code, 3)
                    self.assertEqual(outcome.error_code, OPERATOR_BACKUP_PATH_INVALID)
            self.assertFalse(runtime.exists())

    def test_missing_source_is_not_found_and_creates_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            runtime = base / "missing-runtime"
            paths = _paths(runtime, create=False)
            destination = base / "missing-parent" / "bundle"
            outcome = create_operator_backup(
                "ph-elv-0001",
                str(destination),
                paths_resolver=lambda: paths,
                delivery_root_reader=lambda unused: "",
            )
            self.assertEqual(outcome.exit_code, 5)
            self.assertEqual(outcome.error_code, OPERATOR_BACKUP_SOURCE_NOT_FOUND)
            self.assertFalse(runtime.exists())
            self.assertFalse(destination.parent.exists())

    def test_runtimepaths_is_source_authority_and_cwd_decoy_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            runtime_database, _ = _create_tenant_fixture(paths, "ph-elv-0001")
            decoy = base / "decoy"
            decoy_paths = _paths(decoy)
            decoy_database, _ = _create_tenant_fixture(decoy_paths, "ph-elv-0001")
            with closing(sqlite3.connect(decoy_database)) as connection:
                connection.execute("UPDATE video_tasks SET marker='cwd-decoy';")
                connection.commit()

            previous = Path.cwd()
            os.chdir(decoy)
            try:
                destination = base / "authoritative-bundle"
                outcome = create_operator_backup(
                    "ph-elv-0001",
                    str(destination),
                    paths_resolver=lambda: paths,
                    delivery_root_reader=lambda unused: "",
                )
            finally:
                os.chdir(previous)
            self.assertEqual(outcome.exit_code, 0)
            with closing(sqlite3.connect(destination / "tenant.db")) as snapshot:
                marker = snapshot.execute("SELECT marker FROM video_tasks;").fetchone()[0]
            self.assertEqual(marker, "runtime-ph-elv-0001")
            self.assertNotEqual(_sha256(runtime_database), _sha256(decoy_database))

    def test_existing_destination_is_preserved_without_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            _create_tenant_fixture(paths, "ph-elv-0001")
            destination = base / "existing"
            destination.mkdir()
            marker = destination / "sentinel.bin"
            marker.write_bytes(b"preserve")
            outcome = create_operator_backup(
                "ph-elv-0001",
                str(destination),
                paths_resolver=lambda: paths,
                delivery_root_reader=lambda unused: "",
            )
            self.assertEqual(outcome.exit_code, 4)
            self.assertEqual(marker.read_bytes(), b"preserve")
            self.assertEqual(list(base.glob(".existing.staging-*")), [])

    def test_runtime_output_and_ancestor_destinations_are_protected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            _create_tenant_fixture(paths, "ph-elv-0001")
            destinations = (
                paths.runtime_root,
                paths.runtime_root / "backup",
                paths.internal_output_root / "backup",
                paths.runtime_root.parent,
            )
            for destination in destinations:
                with self.subTest(destination=destination):
                    outcome = create_operator_backup(
                        "ph-elv-0001",
                        str(destination),
                        paths_resolver=lambda: paths,
                        delivery_root_reader=lambda unused: "",
                    )
                    self.assertIn(outcome.exit_code, (3, 4))
                    if not destination.exists():
                        self.assertFalse(destination.exists())

    def test_delivery_current_value_is_read_from_active_wal_without_schema_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            delivery = base / "delivery"
            connection = sqlite3.connect(paths.settings_db_path)
            try:
                self.assertEqual(connection.execute("PRAGMA journal_mode=WAL;").fetchone()[0], "wal")
                connection.execute("PRAGMA wal_autocheckpoint=0;")
                connection.execute(
                    "CREATE TABLE app_settings (key_name TEXT PRIMARY KEY, key_value TEXT);"
                )
                connection.execute(
                    "INSERT INTO app_settings VALUES ('delivery_root', ?);",
                    (str(delivery),),
                )
                connection.commit()
                self.assertTrue(Path(str(paths.settings_db_path) + "-wal").exists())
                self.assertTrue(Path(str(paths.settings_db_path) + "-shm").exists())
                self.assertEqual(read_current_delivery_root(paths), str(delivery.resolve()))
                self.assertTrue(Path(str(paths.settings_db_path) + "-wal").exists())
                self.assertTrue(Path(str(paths.settings_db_path) + "-shm").exists())
            finally:
                connection.close()

    def test_delivery_sidecar_free_read_is_stable_and_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            delivery = base / "delivery"
            with closing(sqlite3.connect(paths.settings_db_path)) as connection:
                connection.execute(
                    "CREATE TABLE app_settings "
                    "(key_name TEXT PRIMARY KEY, key_value TEXT);"
                )
                connection.execute(
                    "INSERT INTO app_settings VALUES ('delivery_root', ?);",
                    (str(delivery),),
                )
                connection.commit()
            before = paths.settings_db_path.stat()

            self.assertEqual(
                read_current_delivery_root(paths),
                str(delivery.resolve()),
            )

            after = paths.settings_db_path.stat()
            self.assertEqual(
                (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_dev,
                    after.st_ino,
                ),
                (
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_dev,
                    before.st_ino,
                ),
            )
            self.assertFalse(
                any(
                    os.path.lexists(Path(str(paths.settings_db_path) + suffix))
                    for suffix in ("-wal", "-shm", "-journal")
                )
            )

    def test_delivery_sidecar_free_main_change_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            with closing(sqlite3.connect(paths.settings_db_path)) as connection:
                connection.execute(
                    "CREATE TABLE app_settings "
                    "(key_name TEXT PRIMARY KEY, key_value TEXT);"
                )
                connection.execute(
                    "INSERT INTO app_settings VALUES ('delivery_root', ?);",
                    (str(base / "old-delivery"),),
                )
                connection.commit()

            def mutate(connect) -> None:
                with closing(connect(paths.settings_db_path)) as writer:
                    writer.execute(
                        "UPDATE app_settings SET key_value = ? "
                        "WHERE key_name = 'delivery_root';",
                        (str(base / "new-delivery"),),
                    )
                    writer.execute("CREATE TABLE concurrent_padding(payload BLOB);")
                    writer.execute(
                        "INSERT INTO concurrent_padding VALUES (zeroblob(8192));"
                    )
                    writer.commit()

            with patch.object(
                delivery_output.sqlite3,
                "connect",
                side_effect=_sqlite_connect_that_mutates_on_close(mutate),
            ), self.assertRaises(DeliverySettingsReadError) as raised:
                read_current_delivery_root(paths)
            self.assertEqual(
                str(raised.exception),
                "DELIVERY_SETTINGS_CHANGED_DURING_READ",
            )

    def test_delivery_absent_table_concurrent_creation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            with closing(sqlite3.connect(paths.settings_db_path)) as connection:
                connection.execute("CREATE TABLE unrelated(value TEXT);")
                connection.commit()

            def mutate(connect) -> None:
                with closing(connect(paths.settings_db_path)) as writer:
                    writer.execute(
                        "CREATE TABLE app_settings "
                        "(key_name TEXT PRIMARY KEY, key_value TEXT);"
                    )
                    writer.execute(
                        "INSERT INTO app_settings VALUES ('delivery_root', ?);",
                        (str(base / "concurrent-delivery"),),
                    )
                    writer.commit()

            with patch.object(
                delivery_output.sqlite3,
                "connect",
                side_effect=_sqlite_connect_that_mutates_on_close(mutate),
            ), self.assertRaises(DeliverySettingsReadError) as raised:
                read_current_delivery_root(paths)
            self.assertEqual(
                str(raised.exception),
                "DELIVERY_SETTINGS_CHANGED_DURING_READ",
            )

    def test_runtime_root_unavailable_maps_to_subsystem_not_internal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "bundle"
            outcome = create_operator_backup(
                "ph-elv-0001",
                str(destination),
                paths_resolver=lambda: (_ for _ in ()).throw(
                    RuntimeRootUnavailable()
                ),
            )
            self.assertEqual(
                (outcome.exit_code, outcome.error_code),
                (8, OPERATOR_BACKUP_SUBSYSTEM_FAILED),
            )
            self.assertNotEqual(outcome.error_code, OPERATOR_BACKUP_INTERNAL_FAILED)
            self.assertFalse(destination.exists())

    def test_legacy_runtime_migration_maps_to_state_not_internal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "bundle"
            outcome = create_operator_backup(
                "ph-elv-0001",
                str(destination),
                paths_resolver=lambda: (_ for _ in ()).throw(
                    LegacyRuntimeMigrationRequired()
                ),
            )
            self.assertEqual(
                (outcome.exit_code, outcome.error_code),
                (4, "LEGACY_RUNTIME_MIGRATION_REQUIRED"),
            )
            self.assertNotEqual(outcome.error_code, OPERATOR_BACKUP_INTERNAL_FAILED)
            self.assertFalse(destination.exists())

    def test_runtime_paths_conflict_maps_to_subsystem_not_internal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "bundle"
            outcome = create_operator_backup(
                "ph-elv-0001",
                str(destination),
                paths_resolver=lambda: (_ for _ in ()).throw(
                    RuntimePathsInitializationConflict()
                ),
            )
            self.assertEqual(
                (outcome.exit_code, outcome.error_code),
                (8, OPERATOR_BACKUP_SUBSYSTEM_FAILED),
            )
            self.assertNotEqual(outcome.error_code, OPERATOR_BACKUP_INTERNAL_FAILED)
            self.assertFalse(destination.exists())

    def test_delivery_overlap_is_rejected_and_unconfigured_delivery_is_nonblocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            _create_tenant_fixture(paths, "ph-elv-0001")
            delivery = base / "delivery"
            delivery.mkdir()
            for destination in (delivery, delivery / "backup", base):
                with self.subTest(destination=destination):
                    outcome = create_operator_backup(
                        "ph-elv-0001",
                        str(destination),
                        paths_resolver=lambda: paths,
                        delivery_root_reader=lambda unused: str(delivery),
                    )
                    self.assertIn(outcome.exit_code, (3, 4))
            allowed = base / "safe" / "bundle"
            outcome = create_operator_backup(
                "ph-elv-0001",
                str(allowed),
                paths_resolver=lambda: paths,
                delivery_root_reader=lambda unused: "",
            )
            self.assertEqual(outcome.exit_code, 0)
            self.assertFalse((delivery / "backup").exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction proof")
    def test_windows_junctions_into_runtime_output_and_delivery_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            _create_tenant_fixture(paths, "ph-elv-0001")
            delivery = base / "delivery"
            delivery.mkdir()
            targets = (
                ("runtime-alias", paths.runtime_root, ""),
                ("output-alias", paths.internal_output_root, ""),
                ("delivery-alias", delivery, str(delivery)),
            )
            for name, target, configured_delivery in targets:
                alias = base / name
                result = subprocess.run(
                    ["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(target)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    self.skipTest(f"junction creation unavailable: {result.returncode}")
                try:
                    requested = alias / "new-backup"
                    outcome = create_operator_backup(
                        "ph-elv-0001",
                        str(requested),
                        paths_resolver=lambda: paths,
                        delivery_root_reader=lambda unused, value=configured_delivery: value,
                    )
                    with self.subTest(target=target):
                        self.assertEqual(outcome.exit_code, 3)
                        self.assertEqual(
                            outcome.error_code, OPERATOR_BACKUP_DESTINATION_PROTECTED
                        )
                        self.assertFalse((target / "new-backup").exists())
                finally:
                    if alias.exists():
                        alias.rmdir()

    @unittest.skipIf(os.name == "nt", "POSIX symlink proof")
    def test_posix_symlink_into_runtime_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            _create_tenant_fixture(paths, "ph-elv-0001")
            alias = base / "runtime-alias"
            alias.symlink_to(paths.runtime_root, target_is_directory=True)
            outcome = create_operator_backup(
                "ph-elv-0001",
                str(alias / "new-backup"),
                paths_resolver=lambda: paths,
                delivery_root_reader=lambda unused: "",
            )
            self.assertEqual(outcome.exit_code, 3)
            self.assertFalse((paths.runtime_root / "new-backup").exists())

    def test_create_does_not_acquire_server_mutation_barrier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            _create_tenant_fixture(paths, "ph-elv-0001")
            source = f"""
from src.api.runtime_mutation import acquire_runtime_mutation_barrier
from src.api.runtime_paths import RuntimeMode, resolve_runtime_paths
paths = resolve_runtime_paths(mode=RuntimeMode.TEST, runtime_root={str(paths.runtime_root)!r})
barrier = acquire_runtime_mutation_barrier(paths)
print('LOCKED', flush=True)
input()
barrier.release()
"""
            process = subprocess.Popen(
                [sys.executable, "-c", source],
                cwd=REPOSITORY_ROOT,
                env=_subprocess_environment(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert process.stdout is not None
                self.assertEqual(process.stdout.readline().strip(), "LOCKED")
                destination = base / "server-live-bundle"
                outcome = create_operator_backup(
                    "ph-elv-0001",
                    str(destination),
                    paths_resolver=lambda: paths,
                    delivery_root_reader=lambda unused: "",
                )
                self.assertEqual(outcome.exit_code, 0)
                self.assertEqual(
                    verify_backup_bundle(destination)["canonical_tenant_id"],
                    "ph-elv-0001",
                )
            finally:
                if process.poll() is None:
                    assert process.stdin is not None
                    process.stdin.write("release\n")
                    process.stdin.flush()
                process.communicate(timeout=10)

    def test_online_writer_produces_one_valid_snapshot_without_copying_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            database, _ = _create_tenant_fixture(paths, "ph-elv-0001")
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("PRAGMA journal_mode=WAL;")
                connection.execute("CREATE TABLE live_probe(id INTEGER PRIMARY KEY, value TEXT);")
                connection.execute("CREATE TABLE padding(payload BLOB);")
                connection.execute("INSERT INTO padding VALUES (zeroblob(4194304));")
                connection.commit()

            started = threading.Event()
            stop = threading.Event()
            errors: list[BaseException] = []

            def writer() -> None:
                connection = sqlite3.connect(database, timeout=10)
                try:
                    index = 0
                    while not stop.is_set():
                        connection.execute("INSERT INTO live_probe(value) VALUES (?);", (str(index),))
                        connection.commit()
                        index += 1
                        started.set()
                        time.sleep(0.001)
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    connection.close()

            thread = threading.Thread(target=writer, name="h4-5-online-writer")
            thread.start()
            self.assertTrue(started.wait(5))
            try:
                destination = base / "online-bundle"
                outcome = create_operator_backup(
                    "ph-elv-0001",
                    str(destination),
                    paths_resolver=lambda: paths,
                    delivery_root_reader=lambda unused: "",
                )
            finally:
                stop.set()
                thread.join(10)
            self.assertEqual(errors, [])
            self.assertEqual(outcome.exit_code, 0)
            verify_backup_bundle(destination)
            with closing(sqlite3.connect(destination / "tenant.db")) as snapshot:
                self.assertEqual(snapshot.execute("PRAGMA integrity_check;").fetchone()[0], "ok")
                self.assertGreater(snapshot.execute("SELECT COUNT(*) FROM live_probe;").fetchone()[0], 0)
            names = {path.name for path in destination.rglob("*")}
            self.assertFalse(any(name.endswith(("-wal", "-shm")) for name in names))

    def test_catalog_only_and_global_secret_delivery_other_tenant_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            _, asset = _create_tenant_fixture(paths, "ph-elv-0001")
            other_database, _ = _create_tenant_fixture(paths, "ph-bty-0001")
            other_database.write_bytes(other_database.read_bytes() + b"other-tenant-marker")
            (paths.internal_output_root / "orphan.bin").write_bytes(b"orphan-marker")
            paths.settings_db_path.write_bytes(SYNTHETIC_SECRET_MARKER)
            delivery = base / "delivery"
            delivery.mkdir()
            (delivery / asset.name).write_bytes(b"delivery-copy-marker")

            destination = base / "catalog-bundle"
            outcome = create_operator_backup(
                "ph-elv-0001",
                str(destination),
                paths_resolver=lambda: paths,
                delivery_root_reader=lambda unused: str(delivery),
            )
            self.assertEqual(outcome.exit_code, 0)
            files = tuple(path for path in destination.rglob("*") if path.is_file())
            self.assertEqual(
                {path.relative_to(destination).as_posix() for path in files},
                {"tenant.db", "manifest.json", f"assets/{asset.name}"},
            )
            combined = b"".join(path.read_bytes() for path in files)
            self.assertNotIn(SYNTHETIC_SECRET_MARKER, combined)
            self.assertNotIn(b"other-tenant-marker", combined)
            self.assertNotIn(b"delivery-copy-marker", combined)
            self.assertNotIn(b"orphan-marker", combined)


class BackupCoreAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.paths = _paths(self.base / "runtime")
        self.database, self.asset = _create_tenant_fixture(self.paths, "ph-elv-0001")
        self.database_hash = _sha256(self.database)
        self.asset_hash = _sha256(self.asset)
        self.sibling = self.base / "unrelated.keep"
        self.sibling.write_bytes(b"keep")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_failure_matrix_cleans_only_staging_and_never_publishes(self) -> None:
        targets = (
            "_sqlite_online_backup",
            "_enumerate_authoritative_assets",
            "_copy_asset_consistently",
            "_write_manifest",
            "verify_backup_bundle",
            "_publish_staging_directory",
        )
        for index, target in enumerate(targets):
            destination = self.base / f"failure-{index}"
            with self.subTest(target=target), patch.object(
                backup_restore, target, side_effect=RuntimeError("synthetic failure")
            ):
                with self.assertRaises(RuntimeError):
                    create_backup_bundle(
                        tenant_id="ph-elv-0001",
                        destination=destination,
                        project_root=self.paths.runtime_root,
                    )
            self.assertFalse(destination.exists())
            self.assertEqual(list(self.base.glob(f".{destination.name}.staging-*")), [])
            self.assertEqual(_sha256(self.database), self.database_hash)
            self.assertEqual(_sha256(self.asset), self.asset_hash)
            self.assertEqual(self.sibling.read_bytes(), b"keep")

    def test_final_publish_competitor_is_preserved_and_staging_is_cleaned(self) -> None:
        destination = self.base / "publish-race"
        original = backup_restore._publish_staging_directory

        def competing_publish(staging: Path, final: Path) -> None:
            final.mkdir()
            (final / "sentinel.bin").write_bytes(b"competitor")
            original(staging, final)

        with patch.object(
            backup_restore, "_publish_staging_directory", side_effect=competing_publish
        ):
            with self.assertRaises(BackupDestinationExistsError):
                create_backup_bundle(
                    tenant_id="ph-elv-0001",
                    destination=destination,
                    project_root=self.paths.runtime_root,
                )
        self.assertEqual((destination / "sentinel.bin").read_bytes(), b"competitor")
        self.assertEqual(list(self.base.glob(".publish-race.staging-*")), [])

    def test_asset_change_race_exhausts_bounded_retry_without_publish(self) -> None:
        original = backup_restore._copy_file_bytes

        def copy_then_change(source: Path, destination: Path):
            result = original(source, destination)
            source.write_bytes(source.read_bytes() + b"changed")
            return result

        destination = self.base / "asset-race"
        with patch.object(backup_restore, "_copy_file_bytes", side_effect=copy_then_change):
            outcome = create_operator_backup(
                "ph-elv-0001",
                str(destination),
                paths_resolver=lambda: self.paths,
                delivery_root_reader=lambda unused: "",
            )
        self.assertEqual(outcome.exit_code, 6)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.base.glob(".asset-race.staging-*")), [])


class OperatorBackupVerifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.paths = _paths(self.base / "runtime")
        _create_tenant_fixture(self.paths, "ph-elv-0001")
        self.bundle = self.base / "valid-bundle"
        create_backup_bundle(
            tenant_id="ph-elv-0001",
            destination=self.bundle,
            project_root=self.paths.runtime_root,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _manifest(self, bundle: Path) -> dict[str, object]:
        return json.loads((bundle / "manifest.json").read_text("utf-8"))

    def _write_manifest(self, bundle: Path, manifest: dict[str, object]) -> None:
        (bundle / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8"
        )

    def test_verify_is_standalone_without_runtimepaths_or_source_tree(self) -> None:
        isolated = self.base / "isolated" / "bundle"
        isolated.parent.mkdir()
        shutil.copytree(self.bundle, isolated)
        shutil.rmtree(self.paths.runtime_root)
        with patch(
            "src.api.runtime_paths.initialize_runtime_paths",
            side_effect=AssertionError("verify initialized RuntimePaths"),
        ):
            outcome = verify_operator_backup(str(isolated))
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(outcome.data["tenant"], "ph-elv-0001")

    def test_verify_subprocess_import_does_not_enter_runtime_or_database_graph(self) -> None:
        source = f"""
import io
import sys
from unittest.mock import patch
import src.api.runtime_paths as runtime_paths
with patch.object(runtime_paths, 'initialize_runtime_paths', side_effect=AssertionError('initialized')):
    with patch.object(runtime_paths, 'resolve_runtime_paths', side_effect=AssertionError('resolved')):
        from src.api.operator_cli import run_operator_cli
        stdout, stderr = io.StringIO(), io.StringIO()
        code = run_operator_cli(
            ('backup', 'verify', '--bundle', {str(self.bundle)!r}),
            stdout=stdout,
            stderr=stderr,
        )
print(code)
print('DATABASE_IMPORTED=' + str('src.api.database' in sys.modules))
print('STDERR_EMPTY=' + str(stderr.getvalue() == ''))
"""
        result = subprocess.run(
            [sys.executable, "-c", source],
            cwd=REPOSITORY_ROOT,
            env=_subprocess_environment(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\n0\n", "\n" + result.stdout)
        self.assertIn("DATABASE_IMPORTED=False", result.stdout)
        self.assertIn("STDERR_EMPTY=True", result.stdout)

    def test_verify_success_and_failure_are_read_only_and_create_no_sidecars(self) -> None:
        before = _tree_state(self.bundle)
        first = verify_operator_backup(str(self.bundle))
        second = verify_operator_backup(str(self.bundle))
        self.assertEqual((first.exit_code, second.exit_code), (0, 0))
        self.assertEqual(_tree_state(self.bundle), before)
        self.assertFalse(any(self.bundle.glob("tenant.db-*")))

        invalid = self.base / "invalid-read-only"
        shutil.copytree(self.bundle, invalid)
        manifest = self._manifest(invalid)
        manifest["backup_format_version"] = 999
        self._write_manifest(invalid, manifest)
        invalid_before = _tree_state(invalid)
        outcome = verify_operator_backup(str(invalid))
        self.assertEqual(outcome.exit_code, 6)
        self.assertEqual(_tree_state(invalid), invalid_before)
        self.assertFalse(any(invalid.glob("tenant.db-*")))

    def test_verify_rejects_relative_and_missing_bundle_before_runtime(self) -> None:
        relative = verify_operator_backup("relative/bundle")
        self.assertEqual(relative.exit_code, 3)
        self.assertEqual(relative.error_code, OPERATOR_BACKUP_PATH_INVALID)
        missing = verify_operator_backup(str(self.base / "missing"))
        self.assertEqual(missing.exit_code, 5)
        self.assertEqual(missing.error_code, OPERATOR_BACKUP_BUNDLE_NOT_FOUND)

    def test_full_verify_failure_matrix_is_deterministic_and_read_only(self) -> None:
        cases = (
            "missing_manifest",
            "invalid_json",
            "wrong_format",
            "invalid_application_version",
            "invalid_tenant",
            "wrong_db_path",
            "missing_database",
            "database_size",
            "database_sha",
            "sqlite_integrity",
            "asset_count",
            "count_mismatch",
            "missing_asset",
            "asset_size",
            "asset_sha",
            "traversal",
            "absolute_member",
            "duplicate_member",
            "locator_mismatch",
            "catalog_shape_mismatch",
            "manifest_snapshot_mismatch",
        )
        for index, case in enumerate(cases):
            bundle = self.base / f"invalid-{index}"
            shutil.copytree(self.bundle, bundle)
            manifest_path = bundle / "manifest.json"
            manifest = self._manifest(bundle)
            asset_path = bundle / str(manifest["assets"][0]["backup_path"])
            database_path = bundle / "tenant.db"

            if case == "missing_manifest":
                manifest_path.unlink()
            elif case == "invalid_json":
                manifest_path.write_text("{", encoding="utf-8")
            elif case == "wrong_format":
                manifest["backup_format_version"] = 2
            elif case == "invalid_application_version":
                manifest["application_version"] = "bad version"
            elif case == "invalid_tenant":
                manifest["canonical_tenant_id"] = "bad/tenant"
            elif case == "wrong_db_path":
                manifest["database"]["path"] = "other.db"
            elif case == "missing_database":
                database_path.unlink()
            elif case == "database_size":
                manifest["database"]["byte_size"] += 1
            elif case == "database_sha":
                manifest["database"]["sha256"] = "0" * 64
            elif case == "sqlite_integrity":
                database_path.write_bytes(b"not-a-sqlite-database")
                manifest["database"]["byte_size"] = database_path.stat().st_size
                manifest["database"]["sha256"] = _sha256(database_path)
            elif case == "asset_count":
                manifest["asset_count"] += 1
            elif case == "count_mismatch":
                manifest["counts"]["task_history"] += 1
            elif case == "missing_asset":
                asset_path.unlink()
            elif case == "asset_size":
                manifest["assets"][0]["byte_size"] += 1
            elif case == "asset_sha":
                manifest["assets"][0]["sha256"] = "0" * 64
            elif case == "traversal":
                manifest["assets"][0]["backup_path"] = "assets/../escape"
            elif case == "absolute_member":
                manifest["assets"][0]["backup_path"] = str(asset_path.resolve())
            elif case == "duplicate_member":
                manifest["assets"].append(dict(manifest["assets"][0]))
                manifest["asset_count"] = 2
            elif case == "locator_mismatch":
                manifest["assets"][0]["catalog_locators"] = ["task_history:1:9"]
            elif case == "catalog_shape_mismatch":
                manifest["assets"][0]["catalog_shape"] = "LEGACY_MATRIX"
            elif case == "manifest_snapshot_mismatch":
                manifest["assets"][0]["catalog_locators"] = ["task_history:9:0"]

            if case not in {"missing_manifest", "invalid_json"}:
                self._write_manifest(bundle, manifest)
            before = _tree_state(bundle)
            outcome = verify_operator_backup(str(bundle))
            with self.subTest(case=case):
                self.assertEqual(outcome.exit_code, 6)
                self.assertEqual(_tree_state(bundle), before)
                self.assertFalse(any(bundle.glob("tenant.db-*")))

    def test_unknown_extra_file_remains_non_authoritative_and_tolerated(self) -> None:
        extra = self.bundle / "unreferenced.extra"
        extra.write_bytes(b"not authority")
        before = _tree_state(self.bundle)
        outcome = verify_operator_backup(str(self.bundle))
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(_tree_state(self.bundle), before)


class OperatorBackupOutputTests(unittest.TestCase):
    def test_human_json_and_placeholder_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            _create_tenant_fixture(paths, "ph-elv-0001")
            with temporary_test_runtime_paths(paths.runtime_root):
                destination = base / "cli-bundle"
                code, stdout, stderr = _invoke(
                    "backup", "create", "--tenant", "ph-elv-0001",
                    "--destination", str(destination),
                )
                self.assertEqual(code, 0)
                self.assertEqual(stderr, "")
                self.assertEqual(len(stdout.splitlines()), 1)

                code, stdout, stderr = _invoke(
                    "--json", "backup", "verify", "--bundle", str(destination)
                )
                self.assertEqual(code, 0)
                self.assertEqual(stderr, "")
                self.assertEqual(len(stdout.splitlines()), 1)
                payload = json.loads(stdout)
                self.assertEqual(payload["schema_version"], 1)
                self.assertEqual(payload["command"], "backup verify")
                self.assertEqual(payload["status"], "VALID")
                self.assertIsNone(payload["error_code"])
                self.assertEqual(payload["data"]["tenant"], "ph-elv-0001")

        placeholders = (
            (
                "seed", "apply-safe-off", "--tenant", "ph-elv-0001",
                "--generation", "phseed-elv0001-bal-20260921-r1",
                "--approval-ref", "A-1",
            ),
            (
                "seed", "prearm-p3w", "--tenant", "ph-elv-0001",
                "--generation", "phseed-elv0001-bal-20260921-r1",
                "--backup-bundle", "X:/backup", "--approval-ref", "A-1",
            ),
            (
                "secret", "assignment", "rotate", "--tenant", "ph-elv-0001",
                "--expected-generation", "phseed-elv0001-bal-20260921-r1",
                "--new-generation", "phseed-elv0001-bal-20260921-r2",
                "--backup-bundle", "X:/backup", "--approval-ref", "A-1",
            ),
        )
        for command in placeholders:
            with self.subTest(command=command):
                code, stdout, stderr = _invoke(*command)
                self.assertEqual(code, 4)
                self.assertEqual(stdout, "")
                self.assertIn(OPERATOR_COMMAND_NOT_IMPLEMENTED, stderr)

    def test_json_failures_cover_validation_state_not_found_integrity_and_subsystem(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = _paths(base / "runtime")
            _create_tenant_fixture(paths, "ph-elv-0001")
            existing = base / "existing"
            existing.mkdir()
            invalid_bundle = base / "invalid-bundle"
            invalid_bundle.mkdir()

            with temporary_test_runtime_paths(paths.runtime_root):
                cases = (
                    (
                        ("--json", "backup", "create", "--tenant", "PH-ELV-0001", "--destination", str(base / "x")),
                        3,
                    ),
                    (
                        ("--json", "backup", "create", "--tenant", "ph-elv-0001", "--destination", str(existing)),
                        4,
                    ),
                    (
                        ("--json", "backup", "create", "--tenant", "ph-bty-0001", "--destination", str(base / "missing-source")),
                        5,
                    ),
                    (
                        ("--json", "backup", "verify", "--bundle", str(invalid_bundle)),
                        6,
                    ),
                )
                for arguments, expected in cases:
                    with self.subTest(expected=expected):
                        code, stdout, stderr = _invoke(*arguments)
                        self.assertEqual(code, expected)
                        self.assertEqual(stderr, "")
                        self.assertEqual(len(stdout.splitlines()), 1)
                        payload = json.loads(stdout)
                        self.assertEqual(payload["schema_version"], 1)
                        self.assertIsNotNone(payload["error_code"])

                paths.settings_db_path.write_bytes(b"not-sqlite")
                code, stdout, stderr = _invoke(
                    "--json", "backup", "create", "--tenant", "ph-elv-0001",
                    "--destination", str(base / "subsystem"),
                )
                self.assertEqual(code, 8)
                self.assertEqual(stderr, "")
                self.assertEqual(len(stdout.splitlines()), 1)
                self.assertIsNotNone(json.loads(stdout)["error_code"])


if __name__ == "__main__":
    unittest.main()
