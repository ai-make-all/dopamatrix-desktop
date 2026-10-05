from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing, nullcontext
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.api import database, tenant_router
from src.api.operator_tenant_provision import (
    provision_tenant,
    validate_approved_tenant_identity,
)
from src.api.runtime_paths import RuntimeMode, RuntimePaths
from src.api.tenant_policy import (
    APPROVED_V15_PHILIPPINE_SEED_TENANTS,
    TENANT_IDENTITY_MALFORMED,
    TENANT_NOT_APPROVED,
    TENANT_NOT_PROVISIONED,
    TenantNotApproved,
    TenantNotProvisioned,
    TenantPolicyError,
    parse_approved_tenant_identity,
    require_provisioned_tenant,
)


APPROVED = frozenset({"ph-elv-0001", "ph-bty-0001", "ph-hwh-0001"})
OLD_WEAK_REQUIRED_TABLES = frozenset(
    {
        "video_tasks",
        "reservation_run_diagnostics",
        "reservation_rollout_breakers",
        "video_assets",
        "local_assets_inventory",
        "task_history",
        "variant_approvals",
        "variant_status_audits",
        "fingerprint_ledger_schema_version",
        "fingerprint_identities",
        "fingerprint_occurrences",
        "fingerprint_reservations",
    }
)


def _paths(root: Path, mode: RuntimeMode = RuntimeMode.PACKAGED) -> RuntimePaths:
    return RuntimePaths(
        mode,
        root,
        root / "dopamatrix.db",
        root / "data",
        root / "output",
    )


def _dispose_tenant_engines() -> None:
    with database._engine_lock:
        engines = tuple(database._tenant_engines.values())
        database._tenant_engines.clear()
    for engine in engines:
        engine.dispose()


def _test_app(paths: RuntimePaths) -> FastAPI:
    app = FastAPI()
    app.add_middleware(tenant_router.TenantHeaderAuthorityMiddleware, paths=paths)

    @app.exception_handler(TenantPolicyError)
    async def tenant_policy_error_handler(_, exc: TenantPolicyError):
        return JSONResponse(status_code=exc.http_status, content={"detail": exc.code})

    @app.get("/probe")
    def probe():
        return {"ok": True}

    app.include_router(tenant_router.router, prefix="/api/v1")
    return app


def _operator_provision(paths: RuntimePaths, tenant: str = "ph-elv-0001"):
    with (
        patch.object(database, "get_initialized_runtime_paths", return_value=paths),
        patch.object(database, "get_runtime_paths", return_value=paths),
    ):
        outcome = provision_tenant(
            tenant,
            "RC2-3-R1-R2-TEST",
            paths_initializer=lambda: paths,
            barrier_factory=lambda unused: nullcontext(),
            delivery_root_reader=lambda unused: None,
        )
    _dispose_tenant_engines()
    return outcome


def _old_weak_predicate_accepts(database_path: Path) -> bool:
    with closing(sqlite3.connect(database_path)) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }
        ledger = connection.execute(
            "SELECT schema_version FROM fingerprint_ledger_schema_version "
            "WHERE component='fingerprint_ledger';"
        ).fetchone()
    return OLD_WEAK_REQUIRED_TABLES.issubset(tables) and ledger == (2,)


def _database_snapshot(database_path: Path) -> dict[str, object]:
    payload = database_path.read_bytes()
    stat_result = database_path.stat()
    sidecars = tuple(
        Path(str(database_path) + suffix).exists()
        for suffix in ("-wal", "-shm", "-journal")
    )
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
        "sidecars": sidecars,
    }


class FrozenTenantPolicyTests(unittest.TestCase):
    def tearDown(self) -> None:
        _dispose_tenant_engines()

    def test_exact_frozen_set_is_the_operator_and_runtime_authority(self):
        self.assertEqual(APPROVED_V15_PHILIPPINE_SEED_TENANTS, APPROVED)
        for tenant in sorted(APPROVED):
            with self.subTest(tenant=tenant):
                self.assertEqual(
                    parse_approved_tenant_identity(tenant),
                    validate_approved_tenant_identity(tenant),
                )

    def test_requested_negative_identities_are_rejected(self):
        for tenant in (
            "ph-elv-001",
            "ph-elv-0002",
            "testduplicate",
            "abc",
            "../../bad",
            "a-valid-format-but-unapproved-id",
        ):
            with self.subTest(tenant=tenant):
                with self.assertRaises(TenantPolicyError):
                    parse_approved_tenant_identity(tenant)

    def test_low_level_engine_rejects_before_runtime_or_tenant_path_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "must-not-exist"
            with (
                patch.object(database, "get_initialized_runtime_paths", return_value=None),
                patch.object(
                    database,
                    "get_runtime_paths",
                    side_effect=AssertionError("runtime paths reached"),
                ),
            ):
                with self.assertRaises(TenantNotApproved):
                    database.get_tenant_engine("ph-elv-0002")
            self.assertFalse(root.exists())

    def test_approved_unprovisioned_tenant_is_not_auto_created(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            paths.tenant_data_dir.mkdir()
            with patch.object(database, "get_initialized_runtime_paths", return_value=paths):
                with self.assertRaises(TenantNotProvisioned):
                    database.get_tenant_engine("ph-elv-0001")
            self.assertEqual(tuple(paths.tenant_data_dir.iterdir()), ())

    def test_placeholder_database_is_not_treated_as_operator_provisioning(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            paths.tenant_data_dir.mkdir()
            database_path = paths.tenant_database_path("ph-elv-0001")
            database_path.touch()
            before = database_path.read_bytes()
            with patch.object(database, "get_initialized_runtime_paths", return_value=paths):
                with self.assertRaises(TenantNotProvisioned):
                    database.get_tenant_engine("ph-elv-0001")
            self.assertEqual(database_path.read_bytes(), before)

    def test_old_weak_predicate_missing_application_column_is_rejected_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            paths.tenant_data_dir.mkdir()
            outcome = _operator_provision(paths)
            self.assertEqual(outcome.status, "PROVISIONED")
            database_path = paths.tenant_database_path("ph-elv-0001")
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute("ALTER TABLE video_assets DROP COLUMN manifest_data;")
                connection.commit()
            self.assertTrue(_old_weak_predicate_accepts(database_path))
            before = _database_snapshot(database_path)
            self.assertEqual(before["sidecars"], (False, False, False))

            with patch.object(
                database, "get_initialized_runtime_paths", return_value=paths
            ):
                with self.assertRaises(TenantNotProvisioned):
                    database.get_tenant_engine("ph-elv-0001")

            self.assertEqual(_database_snapshot(database_path), before)
            with closing(sqlite3.connect(database_path)) as connection:
                columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info('video_assets');"
                    ).fetchall()
                }
            self.assertNotIn("manifest_data", columns)
            self.assertNotIn("ph-elv-0001", database._tenant_engines)

    def test_old_weak_predicate_missing_rollout_index_is_rejected_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            paths.tenant_data_dir.mkdir()
            outcome = _operator_provision(paths)
            self.assertEqual(outcome.status, "PROVISIONED")
            database_path = paths.tenant_database_path("ph-elv-0001")
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute("DROP INDEX ix_video_tasks_rollout_readiness;")
                connection.commit()
            self.assertTrue(_old_weak_predicate_accepts(database_path))
            before = _database_snapshot(database_path)
            self.assertEqual(before["sidecars"], (False, False, False))

            with patch.object(
                database, "get_initialized_runtime_paths", return_value=paths
            ):
                with self.assertRaises(TenantNotProvisioned):
                    database.get_tenant_engine("ph-elv-0001")

            self.assertEqual(_database_snapshot(database_path), before)
            with closing(sqlite3.connect(database_path)) as connection:
                indexes = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA index_list('video_tasks');"
                    ).fetchall()
                }
            self.assertNotIn("ix_video_tasks_rollout_readiness", indexes)
            self.assertNotIn("ph-elv-0001", database._tenant_engines)

    def test_operator_provisioned_tenant_with_business_data_remains_runtime_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            paths.tenant_data_dir.mkdir()
            outcome = _operator_provision(paths)
            self.assertEqual(outcome.status, "PROVISIONED")
            database_path = paths.tenant_database_path("ph-elv-0001")
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    "INSERT INTO fingerprint_identities "
                    "(fingerprint_type, fingerprint_version, fingerprint_digest, "
                    "digest_algorithm, source_hash_algorithm, canonical_payload, created_at) "
                    "VALUES ('synthetic', 1, 'synthetic', 'sha256', 'sha256', '{}', "
                    "'2026-01-01 00:00:00');"
                )
                connection.commit()

            identity = require_provisioned_tenant("ph-elv-0001", paths)
            self.assertEqual(identity.canonical_id, "ph-elv-0001")
            try:
                with patch.object(
                    database, "get_initialized_runtime_paths", return_value=paths
                ):
                    engine = database.get_tenant_engine("ph-elv-0001")
                    self.assertIsNotNone(engine)
            finally:
                _dispose_tenant_engines()

    def test_operator_provisioned_approved_tenants_become_usable_and_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            paths.tenant_data_dir.mkdir()
            with (
                patch.object(database, "get_initialized_runtime_paths", return_value=paths),
                patch.object(database, "get_runtime_paths", return_value=paths),
            ):
                try:
                    for tenant in sorted(APPROVED):
                        database.provision_tenant_engine(tenant)
                    _dispose_tenant_engines()
                    for tenant in sorted(APPROVED):
                        self.assertIsNotNone(database.get_tenant_engine(tenant))
                        self.assertTrue(paths.tenant_database_path(tenant).is_file())
                    self.assertEqual(
                        len({str(path) for path in paths.tenant_data_dir.glob("*.db")}),
                        3,
                    )
                finally:
                    _dispose_tenant_engines()

    def test_direct_unauthorized_header_is_rejected_without_filesystem_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory) / "runtime")
            client = TestClient(_test_app(paths))
            response = client.get("/probe", headers={"X-Local-User": "ph-elv-0002"})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": TENANT_NOT_APPROVED})
            self.assertFalse(paths.runtime_root.exists())

    def test_malformed_header_is_400_and_arbitrary_header_never_reaches_route(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory) / "runtime")
            client = TestClient(_test_app(paths))
            for tenant in ("ph-elv-001", "testduplicate", "abc", "../../bad"):
                with self.subTest(tenant=tenant):
                    response = client.get("/probe", headers={"X-Local-User": tenant})
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json(), {"detail": TENANT_IDENTITY_MALFORMED})
            self.assertFalse(paths.runtime_root.exists())

    def test_session_endpoint_requires_provisioning_and_never_auto_provisions(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            paths.tenant_data_dir.mkdir()
            app = _test_app(paths)
            with patch.object(tenant_router, "get_runtime_paths", return_value=paths):
                client = TestClient(app)
                response = client.post(
                    "/api/v1/tenant/session/validate",
                    json={"tenant_id": "ph-hwh-0001"},
                )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": TENANT_NOT_PROVISIONED})
            self.assertEqual(tuple(paths.tenant_data_dir.iterdir()), ())

    def test_session_endpoint_accepts_only_an_existing_operator_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            paths.tenant_data_dir.mkdir()
            with (
                patch.object(database, "get_initialized_runtime_paths", return_value=paths),
                patch.object(database, "get_runtime_paths", return_value=paths),
            ):
                engine = database.provision_tenant_engine("ph-bty-0001")
                engine.dispose()
                _dispose_tenant_engines()
            app = _test_app(paths)
            with patch.object(tenant_router, "get_runtime_paths", return_value=paths):
                response = TestClient(app).post(
                    "/api/v1/tenant/session/validate",
                    json={"tenant_id": "ph-bty-0001"},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "tenant_id": "ph-bty-0001",
                    "authorized": True,
                    "provisioned": True,
                    "usable": True,
                },
            )


if __name__ == "__main__":
    unittest.main()
