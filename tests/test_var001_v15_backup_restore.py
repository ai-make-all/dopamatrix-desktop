from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from src.api import backup_restore
from src.api.backup_restore import (
    BackupDestinationExistsError,
    BackupIntegrityError,
    BackupPathSafetyError,
    IncompleteBackupError,
    RestoreDestinationExistsError,
    create_backup_bundle,
    restore_backup_to_staging,
    verify_backup_bundle,
)
from src.api.database import initialize_application_schema
from src.api.fingerprint_ledger import (
    LEDGER_SCHEMA_VERSION,
    FingerprintIdentity,
    FingerprintOccurrence,
    FingerprintReservation,
    ensure_fingerprint_ledger_schema,
)
from src.api.models import (
    ReservationRolloutBreaker,
    ReservationRunDiagnostic,
    TaskHistory,
    VideoTask,
)
from src.version import APPLICATION_VERSION


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class V15BackupRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        (self.root / "data").mkdir(parents=True)
        (self.root / "output").mkdir()
        self.tenant = "tenant-a"
        self.database_path = self.root / "data" / "dopamatrix_tenant-a.db"
        self.engine = create_engine(
            f"sqlite:///{self.database_path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        initialize_application_schema(self.engine)
        ensure_fingerprint_ledger_schema(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed_current_truth()

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary.cleanup()

    def _seed_current_truth(self) -> None:
        self.dsl_asset = self.root / "output" / "final_en_12345678.mp4"
        self.matrix_asset = self.root / "output" / "final_ar_87654321.mp4"
        self.orphan_asset = self.root / "output" / "orphan-authority-lost.mp4"
        self.dsl_asset.write_bytes(b"dsl-video-" + b"A" * 70000 + b"tail-one")
        self.matrix_asset.write_bytes(b"matrix-video-content")
        self.orphan_asset.write_bytes(b"must-not-be-backed-up")

        self.task_id = "11111111-1111-4111-8111-111111111111"
        self.matrix_task_id = "22222222-2222-4222-8222-222222222222"
        self.execution_id = "33333333-3333-4333-8333-333333333333"
        self.owner_attempt_id = "44444444-4444-4444-8444-444444444444"
        self.fingerprint_digest = "a" * 64
        now = datetime.now(timezone.utc)

        with self.Session() as session:
            session.add_all(
                [
                    VideoTask(
                        task_id=self.task_id,
                        prompt="dsl sentinel",
                        batch_size=1,
                        status="completed",
                        reservation_conflict_mode="ENFORCE",
                        planning_policy="exact_main_visual",
                        reservation_mode_source="EXPLICIT_ENFORCE",
                        created_at=now,
                        finished_at=now,
                    ),
                    VideoTask(
                        task_id=self.matrix_task_id,
                        prompt="matrix sentinel",
                        batch_size=1,
                        status="completed",
                        reservation_conflict_mode="OFF",
                        planning_policy="legacy",
                        reservation_mode_source="DEFAULT_OFF",
                        created_at=now,
                        finished_at=now,
                    ),
                ]
            )
            session.add_all(
                [
                    TaskHistory(
                        task_id=self.task_id,
                        prompt="dsl sentinel",
                        batch_size=1,
                        duration=1.0,
                        output_assets=[
                            {
                                "file_path": "output/final_en_12345678.mp4",
                                "file_hash": "prefix-md5-not-backup-integrity",
                            }
                        ],
                        prompt_details=json.dumps(
                            {
                                "children": [
                                    {
                                        "child_index": 0,
                                        "execution_id": self.execution_id,
                                        "outcome": "succeeded",
                                        "output_assets": [
                                            {
                                                "file_path": "output/final_en_12345678.mp4"
                                            }
                                        ],
                                    }
                                ]
                            }
                        ),
                        created_at=now,
                    ),
                    TaskHistory(
                        task_id=self.matrix_task_id,
                        prompt="matrix sentinel",
                        batch_size=1,
                        duration=1.0,
                        output_assets=[
                            {
                                "path": str(self.matrix_asset.resolve()),
                                "hash": "legacy-prefix-md5",
                            }
                        ],
                        created_at=now,
                    ),
                ]
            )
            identity = FingerprintIdentity(
                fingerprint_type="main_visual_planning",
                fingerprint_version=1,
                fingerprint_digest=self.fingerprint_digest,
                digest_algorithm="sha256",
                source_hash_algorithm="sha256",
                canonical_payload='{"fp":"sentinel"}',
                created_at=now,
            )
            session.add(identity)
            session.flush()
            session.add(
                FingerprintOccurrence(
                    fingerprint_identity_id=identity.id,
                    task_id=self.task_id,
                    execution_id=self.execution_id,
                    child_index=0,
                    lifecycle_event="RENDERED",
                    occurred_at=now,
                    provenance="coordinator_authoritative_fp001",
                )
            )
            session.add(
                FingerprintReservation(
                    fingerprint_identity_id=identity.id,
                    owner_task_id=self.owner_attempt_id,
                    owner_slot_index=0,
                    created_at=now.replace(tzinfo=None),
                    updated_at=now.replace(tzinfo=None),
                    expires_at=(now + timedelta(minutes=10)).replace(tzinfo=None),
                    confirmed_at=now.replace(tzinfo=None),
                    execution_id=self.execution_id,
                )
            )
            session.add(
                ReservationRunDiagnostic(
                    task_id=self.task_id,
                    planning_policy="exact_main_visual",
                    requested_count=1,
                    planning_observed=True,
                    planned_count=1,
                    succeeded_count=1,
                    failed_count=0,
                    terminal_status="completed",
                    started_at=now,
                    finished_at=now,
                )
            )
            session.add(
                ReservationRolloutBreaker(
                    planning_policy="exact_main_visual",
                    rollout_generation="generation-7",
                    reason_code="AUTHORITY_LOSS_RATE_EXCEEDED",
                    tripped_at=now,
                )
            )
            session.commit()

    def _backup(self, name: str = "bundle") -> Path:
        destination = Path(self.temporary.name) / name
        create_backup_bundle(
            tenant_id=self.tenant,
            destination=destination,
            project_root=self.root,
        )
        return destination

    def _assert_alias_restore_rejection_does_not_mutate_bundle(
        self,
        *,
        bundle: Path,
        alias_parent: Path,
        child_name: str,
    ) -> None:
        before_entries = {
            path.relative_to(bundle).as_posix() for path in bundle.rglob("*")
        }
        before_files = {
            path.relative_to(bundle).as_posix(): _sha256(path)
            for path in bundle.rglob("*")
            if path.is_file()
        }
        requested = alias_parent / child_name

        with self.assertRaises(BackupPathSafetyError):
            restore_backup_to_staging(bundle=bundle, staging_root=requested)

        self.assertFalse((bundle / child_name).exists())
        self.assertEqual(list(bundle.glob(f".{child_name}.restore-*")), [])
        self.assertEqual(
            {path.relative_to(bundle).as_posix() for path in bundle.rglob("*")},
            before_entries,
        )
        self.assertEqual(
            {
                path.relative_to(bundle).as_posix(): _sha256(path)
                for path in bundle.rglob("*")
                if path.is_file()
            },
            before_files,
        )

    def test_consistent_snapshot_enumerates_only_authoritative_assets(self) -> None:
        bundle = self._backup()
        manifest = verify_backup_bundle(bundle)
        self.assertEqual(manifest["backup_format_version"], 1)
        self.assertEqual(manifest["application_version"], APPLICATION_VERSION)
        self.assertEqual(manifest["canonical_tenant_id"], self.tenant)
        self.assertEqual(manifest["asset_count"], 2)
        self.assertEqual(
            {entry["catalog_shape"] for entry in manifest["assets"]},
            {"DSL", "LEGACY_MATRIX"},
        )
        self.assertEqual(
            {entry["reference_kind"] for entry in manifest["assets"]},
            {"project_relative", "legacy_absolute_within_asset_root"},
        )
        self.assertFalse((bundle / "assets" / self.orphan_asset.name).exists())
        self.assertEqual(manifest["counts"]["task_history"], 2)
        self.assertEqual(manifest["counts"]["fingerprint_occurrences"], 1)
        serialized = json.dumps(manifest)
        self.assertNotIn(str(self.database_path.resolve()), serialized)
        self.assertNotIn(self.owner_attempt_id, serialized)
        self.assertNotIn("assignment_secret", serialized.lower())

    def test_full_file_sha256_is_not_catalog_prefix_hash(self) -> None:
        bundle = self._backup()
        manifest = verify_backup_bundle(bundle)
        dsl_entry = next(
            entry for entry in manifest["assets"] if entry["catalog_shape"] == "DSL"
        )
        self.assertEqual(dsl_entry["sha256"], _sha256(self.dsl_asset))
        self.assertEqual(len(dsl_entry["sha256"]), 64)
        prefix_md5 = hashlib.md5(self.dsl_asset.read_bytes()[:65536]).hexdigest()
        self.assertNotEqual(dsl_entry["sha256"], prefix_md5)

    def test_missing_authoritative_asset_makes_backup_incomplete(self) -> None:
        self.dsl_asset.unlink()
        destination = Path(self.temporary.name) / "incomplete"
        with self.assertRaises(IncompleteBackupError):
            create_backup_bundle(
                tenant_id=self.tenant,
                destination=destination,
                project_root=self.root,
            )
        self.assertFalse(destination.exists())
        self.assertEqual(list(destination.parent.glob(".incomplete.staging-*")), [])

    def test_backup_rejects_catalog_path_escape(self) -> None:
        outside = self.root.parent / "outside.mp4"
        outside.write_bytes(b"outside")
        unsafe_references = (
            "../outside.mp4",
            str(outside.resolve()),
            "C:drive-relative-escape.mp4",
        )
        for index, reference in enumerate(unsafe_references):
            with self.subTest(reference=reference):
                with self.Session() as session:
                    history = session.scalar(
                        select(TaskHistory).where(TaskHistory.task_id == self.task_id)
                    )
                    history.output_assets = [{"file_path": reference, "file_hash": "x"}]
                    session.commit()
                with self.assertRaises(BackupPathSafetyError):
                    create_backup_bundle(
                        tenant_id=self.tenant,
                        destination=Path(self.temporary.name) / f"escape-{index}",
                        project_root=self.root,
                    )

    def test_database_corruption_is_rejected_before_restore(self) -> None:
        bundle = self._backup()
        database = bundle / "tenant.db"
        with database.open("r+b") as handle:
            handle.seek(100)
            original = handle.read(1)
            handle.seek(100)
            handle.write(bytes([original[0] ^ 0xFF]))
        with self.assertRaises(BackupIntegrityError):
            verify_backup_bundle(bundle)
        restore_root = Path(self.temporary.name) / "db-corrupt-restore"
        with self.assertRaises(BackupIntegrityError):
            restore_backup_to_staging(bundle=bundle, staging_root=restore_root)
        self.assertFalse(restore_root.exists())

    def test_asset_corruption_and_missing_bundle_asset_are_rejected(self) -> None:
        for mutation in ("corrupt", "missing"):
            with self.subTest(mutation=mutation):
                bundle = self._backup(f"asset-{mutation}")
                manifest = json.loads((bundle / "manifest.json").read_text("utf-8"))
                asset_path = bundle / Path(manifest["assets"][0]["backup_path"])
                if mutation == "corrupt":
                    asset_path.write_bytes(asset_path.read_bytes() + b"corruption")
                else:
                    asset_path.unlink()
                with self.assertRaises(BackupIntegrityError):
                    verify_backup_bundle(bundle)

    def test_manifest_cannot_omit_an_authoritative_catalog_reference(self) -> None:
        bundle = self._backup()
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text("utf-8"))
        manifest["assets"].pop()
        manifest["asset_count"] = len(manifest["assets"])
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(BackupIntegrityError):
            verify_backup_bundle(bundle)

    def test_compatible_bundle_from_an_older_application_version_still_verifies(self) -> None:
        bundle = self._backup()
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text("utf-8"))
        manifest["application_version"] = "1.4.9"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        verified = verify_backup_bundle(bundle)
        self.assertEqual(verified["application_version"], "1.4.9")

    def test_manifest_path_traversal_and_drive_escape_are_rejected(self) -> None:
        mutations = ("../escape.mp4", "C:/escape.mp4", "/absolute/escape.mp4")
        for index, malicious in enumerate(mutations):
            with self.subTest(path=malicious):
                bundle = self._backup(f"path-{index}")
                manifest_path = bundle / "manifest.json"
                manifest = json.loads(manifest_path.read_text("utf-8"))
                manifest["assets"][0]["backup_path"] = malicious
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(BackupPathSafetyError):
                    verify_backup_bundle(bundle)

    def test_restore_to_isolated_root_preserves_identity_and_truth(self) -> None:
        bundle = self._backup()
        restored_root = Path(self.temporary.name) / "restored"
        result = restore_backup_to_staging(bundle=bundle, staging_root=restored_root)
        self.assertEqual(result.asset_count, 2)
        restored_db = restored_root / "data" / "dopamatrix_tenant-a.db"
        self.assertTrue(restored_db.is_file())
        self.assertEqual(
            _sha256(restored_root / "output" / self.dsl_asset.name),
            _sha256(self.dsl_asset),
        )

        restored_engine = create_engine(f"sqlite:///{restored_db.as_posix()}")
        try:
            RestoredSession = sessionmaker(bind=restored_engine)
            with RestoredSession() as session:
                task = session.scalar(
                    select(VideoTask).where(VideoTask.task_id == self.task_id)
                )
                history = session.scalar(
                    select(TaskHistory).where(TaskHistory.task_id == self.task_id)
                )
                identity = session.scalar(
                    select(FingerprintIdentity).where(
                        FingerprintIdentity.fingerprint_digest == self.fingerprint_digest
                    )
                )
                occurrence = session.scalar(
                    select(FingerprintOccurrence).where(
                        FingerprintOccurrence.execution_id == self.execution_id
                    )
                )
                reservation = session.get(FingerprintReservation, identity.id)
                diagnostic = session.scalar(
                    select(ReservationRunDiagnostic).where(
                        ReservationRunDiagnostic.task_id == self.task_id
                    )
                )
                breaker = session.scalar(select(ReservationRolloutBreaker))
                self.assertEqual(task.status, "completed")
                self.assertEqual(history.task_id, self.task_id)
                self.assertEqual(identity.fingerprint_digest, self.fingerprint_digest)
                self.assertEqual(occurrence.task_id, self.task_id)
                self.assertEqual(occurrence.execution_id, self.execution_id)
                self.assertEqual(reservation.owner_task_id, self.owner_attempt_id)
                self.assertEqual(reservation.execution_id, self.execution_id)
                self.assertEqual(diagnostic.terminal_status, "completed")
                self.assertEqual(breaker.rollout_generation, "generation-7")
        finally:
            restored_engine.dispose()

    def test_restore_never_overwrites_an_existing_destination(self) -> None:
        bundle = self._backup()
        existing = Path(self.temporary.name) / "existing-staging"
        existing.mkdir()
        marker = existing / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(RestoreDestinationExistsError):
            restore_backup_to_staging(bundle=bundle, staging_root=existing)
        self.assertEqual(marker.read_text("utf-8"), "keep")
        with self.assertRaises(BackupDestinationExistsError):
            create_backup_bundle(
                tenant_id=self.tenant,
                destination=bundle,
                project_root=self.root,
            )

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_restore_rejects_missing_child_under_windows_junction_into_bundle(self) -> None:
        bundle = self._backup()
        alias_parent = Path(self.temporary.name) / "bundle-junction"
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(alias_parent), str(bundle)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.skipTest(
                "Windows junction creation unavailable "
                f"(mklink exit code {result.returncode})"
            )
        try:
            self.assertTrue(alias_parent.is_dir())
            self.assertEqual(alias_parent.resolve(), bundle.resolve())
            self._assert_alias_restore_rejection_does_not_mutate_bundle(
                bundle=bundle,
                alias_parent=alias_parent,
                child_name="junction-stage",
            )
        finally:
            if alias_parent.exists():
                alias_parent.rmdir()

    @unittest.skipIf(os.name == "nt", "POSIX symlink regression")
    def test_restore_rejects_missing_child_under_posix_symlink_into_bundle(self) -> None:
        bundle = self._backup()
        alias_parent = Path(self.temporary.name) / "bundle-symlink"
        try:
            alias_parent.symlink_to(bundle, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"POSIX directory symlink creation unavailable: {exc}")
        try:
            self.assertEqual(alias_parent.resolve(), bundle.resolve())
            self._assert_alias_restore_rejection_does_not_mutate_bundle(
                bundle=bundle,
                alias_parent=alias_parent,
                child_name="symlink-stage",
            )
        finally:
            alias_parent.unlink(missing_ok=True)

    def test_restore_accepts_safe_destination_after_physical_normalization(self) -> None:
        bundle = self._backup()
        safe_parent = Path(self.temporary.name) / "safe-restore-parent"
        safe_parent.mkdir()
        requested = safe_parent / "missing-component" / ".." / "normalized-stage"
        canonical = safe_parent / "normalized-stage"

        result = restore_backup_to_staging(bundle=bundle, staging_root=requested)

        self.assertEqual(result.staging_root, canonical.resolve())
        self.assertTrue((canonical / "data" / "dopamatrix_tenant-a.db").is_file())
        self.assertFalse((safe_parent / "missing-component").exists())

    def test_backup_is_business_idempotent_and_read_only(self) -> None:
        with self.Session() as session:
            before = {
                "tasks": session.query(VideoTask).count(),
                "history": session.query(TaskHistory).count(),
                "occurrences": session.query(FingerprintOccurrence).count(),
                "reservations": session.query(FingerprintReservation).count(),
            }
        before_assets = {_sha256(self.dsl_asset), _sha256(self.matrix_asset)}
        first = verify_backup_bundle(self._backup("first"))
        second = verify_backup_bundle(self._backup("second"))
        first_business_assets = {
            (entry["logical_reference"], entry["byte_size"], entry["sha256"])
            for entry in first["assets"]
        }
        second_business_assets = {
            (entry["logical_reference"], entry["byte_size"], entry["sha256"])
            for entry in second["assets"]
        }
        self.assertEqual(first["counts"], second["counts"])
        self.assertEqual(first_business_assets, second_business_assets)
        with self.Session() as session:
            after = {
                "tasks": session.query(VideoTask).count(),
                "history": session.query(TaskHistory).count(),
                "occurrences": session.query(FingerprintOccurrence).count(),
                "reservations": session.query(FingerprintReservation).count(),
            }
        self.assertEqual(after, before)
        self.assertEqual({_sha256(self.dsl_asset), _sha256(self.matrix_asset)}, before_assets)

    def test_source_asset_change_during_copy_never_succeeds_silently(self) -> None:
        original_copy = backup_restore._copy_file_bytes

        def copy_then_change(source: Path, destination: Path):
            result = original_copy(source, destination)
            source.write_bytes(source.read_bytes() + b"changed-during-copy")
            return result

        destination = Path(self.temporary.name) / "changing"
        with patch.object(backup_restore, "_copy_file_bytes", side_effect=copy_then_change):
            with self.assertRaises(IncompleteBackupError):
                create_backup_bundle(
                    tenant_id=self.tenant,
                    destination=destination,
                    project_root=self.root,
                )
        self.assertFalse(destination.exists())

    def test_live_writer_and_online_backup_produce_clean_snapshot(self) -> None:
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE live_write_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE snapshot_padding (payload BLOB NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO snapshot_padding(payload) VALUES (zeroblob(8388608))"
            )

        started = threading.Event()
        stop = threading.Event()
        errors: list[BaseException] = []

        def writer() -> None:
            connection = sqlite3.connect(self.database_path, timeout=10)
            try:
                index = 0
                while not stop.is_set():
                    connection.execute(
                        "INSERT INTO live_write_probe(value) VALUES (?)", (f"v-{index}",)
                    )
                    connection.commit()
                    index += 1
                    started.set()
                    time.sleep(0.001)
            except BaseException as exc:  # test-thread evidence only
                errors.append(exc)
            finally:
                connection.close()

        thread = threading.Thread(target=writer, name="backup-live-writer")
        thread.start()
        self.assertTrue(started.wait(5))
        try:
            bundle = self._backup("live")
        finally:
            stop.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        manifest = verify_backup_bundle(bundle)
        snapshot = sqlite3.connect(bundle / manifest["database"]["path"])
        try:
            self.assertEqual(snapshot.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertGreater(snapshot.execute("SELECT COUNT(*) FROM live_write_probe").fetchone()[0], 0)
        finally:
            snapshot.close()

    def test_fresh_install_initializes_all_v15_dependencies(self) -> None:
        path = Path(self.temporary.name) / "fresh" / "tenant.db"
        path.parent.mkdir()
        engine = create_engine(f"sqlite:///{path.as_posix()}")
        try:
            initialize_application_schema(engine)
            ensure_fingerprint_ledger_schema(engine)
            tables = set(inspect(engine).get_table_names())
            self.assertTrue(
                {
                    "video_tasks",
                    "task_history",
                    "fingerprint_identities",
                    "fingerprint_occurrences",
                    "fingerprint_reservations",
                    "fingerprint_ledger_schema_version",
                    "reservation_run_diagnostics",
                    "reservation_rollout_breakers",
                }.issubset(tables)
            )
            with engine.connect() as connection:
                version = connection.execute(
                    text(
                        "SELECT schema_version FROM fingerprint_ledger_schema_version "
                        "WHERE component = 'fingerprint_ledger'"
                    )
                ).scalar_one()
            self.assertEqual(version, LEDGER_SCHEMA_VERSION)
        finally:
            engine.dispose()

    def test_upgrade_existing_tenant_is_additive_and_preserves_sentinels(self) -> None:
        path = Path(self.temporary.name) / "upgrade.db"
        now = datetime.now(timezone.utc).isoformat()
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                "CREATE TABLE video_tasks ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "task_id VARCHAR(64) NOT NULL, prompt TEXT NOT NULL, "
                "batch_size INTEGER NOT NULL DEFAULT 1, "
                "status VARCHAR(20) NOT NULL DEFAULT 'queued', "
                "reservation_conflict_mode TEXT NOT NULL DEFAULT 'OFF', "
                "planning_policy TEXT NOT NULL DEFAULT 'legacy', "
                "created_at DATETIME NOT NULL, finished_at DATETIME);"
                "CREATE UNIQUE INDEX ix_video_tasks_task_id ON video_tasks(task_id);"
                "CREATE TABLE task_history ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, task_id VARCHAR(64) NOT NULL UNIQUE, "
                "prompt VARCHAR NOT NULL, batch_size INTEGER NOT NULL DEFAULT 1, "
                "duration REAL NOT NULL DEFAULT 0, output_assets JSON NOT NULL, "
                "prompt_details TEXT, created_at DATETIME NOT NULL);"
            )
            connection.execute(
                "INSERT INTO video_tasks(task_id,prompt,batch_size,status,"
                "reservation_conflict_mode,planning_policy,created_at,finished_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    "upgrade-task",
                    "preserve prompt",
                    1,
                    "completed",
                    "ENFORCE",
                    "exact_main_visual",
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO task_history(task_id,prompt,batch_size,duration,"
                "output_assets,prompt_details,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    "upgrade-task",
                    "preserve prompt",
                    1,
                    3.5,
                    json.dumps([{"file_path": "output/preserved.mp4", "file_hash": "h"}]),
                    json.dumps({"children": [{"execution_id": "upgrade-exec"}]}),
                    now,
                ),
            )
            connection.commit()
        finally:
            connection.close()

        engine = create_engine(f"sqlite:///{path.as_posix()}")
        try:
            ensure_fingerprint_ledger_schema(engine)
            Session = sessionmaker(bind=engine)
            with Session() as session:
                identity = FingerprintIdentity(
                    fingerprint_type="main_visual_planning",
                    fingerprint_version=1,
                    fingerprint_digest="b" * 64,
                    digest_algorithm="sha256",
                    source_hash_algorithm="sha256",
                    canonical_payload='{"upgrade":true}',
                )
                session.add(identity)
                session.flush()
                session.add(
                    FingerprintOccurrence(
                        fingerprint_identity_id=identity.id,
                        task_id="upgrade-task",
                        execution_id="upgrade-exec",
                        child_index=0,
                        lifecycle_event="RENDERED",
                        provenance="upgrade-sentinel",
                    )
                )
                session.commit()

            initialize_application_schema(engine)
            ensure_fingerprint_ledger_schema(engine)
            with Session() as session:
                task = session.scalar(
                    select(VideoTask).where(VideoTask.task_id == "upgrade-task")
                )
                history = session.scalar(
                    select(TaskHistory).where(TaskHistory.task_id == "upgrade-task")
                )
                occurrence = session.scalar(
                    select(FingerprintOccurrence).where(
                        FingerprintOccurrence.execution_id == "upgrade-exec"
                    )
                )
                self.assertEqual(task.prompt, "preserve prompt")
                self.assertEqual(task.status, "completed")
                self.assertEqual(task.reservation_mode_source, "EXPLICIT_ENFORCE")
                self.assertEqual(history.output_assets[0]["file_path"], "output/preserved.mp4")
                self.assertEqual(occurrence.lifecycle_event, "RENDERED")
            tables = set(inspect(engine).get_table_names())
            self.assertIn("reservation_run_diagnostics", tables)
            self.assertIn("reservation_rollout_breakers", tables)
        finally:
            engine.dispose()

    def test_restored_v15_data_exposes_v16_lineage_inputs(self) -> None:
        restored_root = Path(self.temporary.name) / "lineage"
        restore_backup_to_staging(bundle=self._backup(), staging_root=restored_root)
        database = restored_root / "data" / "dopamatrix_tenant-a.db"
        connection = sqlite3.connect(database)
        try:
            history_row = connection.execute(
                "SELECT output_assets, prompt_details FROM task_history WHERE task_id = ?",
                (self.task_id,),
            ).fetchone()
            occurrence = connection.execute(
                "SELECT task_id, execution_id, fingerprint_identity_id "
                "FROM fingerprint_occurrences WHERE execution_id = ?",
                (self.execution_id,),
            ).fetchone()
            identity = connection.execute(
                "SELECT fingerprint_digest FROM fingerprint_identities WHERE id = ?",
                (occurrence[2],),
            ).fetchone()
        finally:
            connection.close()
        assets = json.loads(history_row[0])
        details = json.loads(history_row[1])
        self.assertEqual(assets[0]["file_path"], "output/final_en_12345678.mp4")
        self.assertEqual(details["children"][0]["execution_id"], self.execution_id)
        self.assertEqual(occurrence[:2], (self.task_id, self.execution_id))
        self.assertEqual(identity[0], self.fingerprint_digest)
        self.assertEqual(
            len(_sha256(restored_root / assets[0]["file_path"])),
            64,
        )

    def test_cli_backup_verify_and_restore_are_scriptable(self) -> None:
        bundle = Path(self.temporary.name) / "cli-bundle"
        restored = Path(self.temporary.name) / "cli-restored"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            backup_code = backup_restore.main(
                [
                    "backup",
                    "--tenant",
                    self.tenant,
                    "--destination",
                    str(bundle),
                    "--project-root",
                    str(self.root),
                ]
            )
            verify_code = backup_restore.main(["verify", "--bundle", str(bundle)])
            restore_code = backup_restore.main(
                [
                    "restore-to-staging",
                    "--bundle",
                    str(bundle),
                    "--staging-root",
                    str(restored),
                ]
            )
        self.assertEqual((backup_code, verify_code, restore_code), (0, 0, 0))
        self.assertEqual(stderr.getvalue(), "")
        statuses = [json.loads(line)["status"] for line in stdout.getvalue().splitlines()]
        self.assertEqual(statuses, ["VALID", "VALID", "VALID_STAGING_RESTORE"])

    def test_release_version_is_single_backend_authority_and_packaging_is_aligned(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        package = json.loads((repository / "web_ui" / "package.json").read_text("utf-8"))
        lock = json.loads((repository / "web_ui" / "package-lock.json").read_text("utf-8"))
        tauri = json.loads(
            (repository / "web_ui" / "src-tauri" / "tauri.conf.json").read_text("utf-8")
        )
        self.assertEqual(APPLICATION_VERSION, "1.5.0-rc2")
        self.assertEqual(package["version"], APPLICATION_VERSION)
        self.assertEqual(lock["version"], APPLICATION_VERSION)
        self.assertEqual(lock["packages"][""]["version"], APPLICATION_VERSION)
        self.assertEqual(tauri["version"], APPLICATION_VERSION)

    def test_backup_tool_is_not_imported_by_render_authority_paths(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        for relative in (
            "src/api/routes_dsl.py",
            "src/api/public_task_admission.py",
            "src/api/planner_reservation.py",
            "src/api/reservation_lease.py",
        ):
            source = (repository / relative).read_text(encoding="utf-8")
            self.assertNotIn("backup_restore", source)


if __name__ == "__main__":
    unittest.main()
