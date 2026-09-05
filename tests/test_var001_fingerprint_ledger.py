import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from src.api import routes_dsl
from src.api import database
from src.api.fingerprint_ledger import (
    LEDGER_SCHEMA_COMPONENT,
    LEDGER_SCHEMA_VERSION,
    FingerprintIdentity,
    FingerprintLedgerCanonicalMismatch,
    FingerprintLedgerRepository,
    FingerprintLedgerSchemaError,
    FingerprintLedgerSchemaVersion,
    FingerprintOccurrence,
    FingerprintOccurrenceRecord,
    ensure_fingerprint_ledger_schema,
)
from src.api.models import Base, TaskHistory
from src.api.schemas import RenderDSLRequest
from tests.test_var001_balanced_axis_coverage import (
    _SyntheticParser,
    _balanced,
    _payload,
    _plan_for_selections,
    _pools,
)


def _engine(url="sqlite://"):
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool if url == "sqlite://" else None,
    )
    ensure_fingerprint_ledger_schema(engine)
    return engine


def _record(**overrides):
    values = {
        "fingerprint_type": "main_visual_planning",
        "fingerprint_version": 1,
        "fingerprint_digest": "a" * 64,
        "digest_algorithm": "sha256",
        "source_hash_algorithm": "md5",
        "canonical_payload": '{"fingerprint_type":"main_visual_planning"}',
        "task_id": "task-a",
        "execution_id": "execution-a",
        "child_index": 0,
        "lifecycle_event": "PLANNED",
        "provenance": "coordinator_authoritative_fp001",
    }
    values.update(overrides)
    return FingerprintOccurrenceRecord(**values)


def _request(headers):
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/v1/tasks/submit-dsl",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
    })


class FingerprintLedgerSchemaTests(unittest.TestCase):
    @staticmethod
    def _create_manual_ledger_schema(
        engine,
        *,
        identity_id="INTEGER NOT NULL PRIMARY KEY",
        fingerprint_digest="VARCHAR(64) NOT NULL",
        child_index="INTEGER NOT NULL",
        referred_column="id",
        on_delete="ON DELETE CASCADE",
    ):
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE fingerprint_ledger_schema_version ("
                "component VARCHAR(64) NOT NULL PRIMARY KEY, "
                "schema_version INTEGER NOT NULL, updated_at DATETIME NOT NULL)"
            ))
            connection.execute(text(
                "CREATE TABLE fingerprint_identities ("
                f"id {identity_id}, fingerprint_type VARCHAR(64) NOT NULL, "
                "fingerprint_version INTEGER NOT NULL, "
                f"fingerprint_digest {fingerprint_digest}, "
                "digest_algorithm VARCHAR(16) NOT NULL, "
                "source_hash_algorithm VARCHAR(16) NOT NULL, "
                "canonical_payload TEXT NOT NULL, created_at DATETIME NOT NULL)"
            ))
            connection.execute(text(
                "CREATE UNIQUE INDEX uq_fingerprint_identity_contract "
                "ON fingerprint_identities "
                "(fingerprint_type, fingerprint_version, fingerprint_digest)"
            ))
            connection.execute(text(
                "CREATE TABLE fingerprint_occurrences ("
                "id INTEGER NOT NULL PRIMARY KEY, "
                "fingerprint_identity_id INTEGER NOT NULL, "
                "task_id VARCHAR(64) NOT NULL, execution_id VARCHAR(64) NOT NULL, "
                f"child_index {child_index}, lifecycle_event VARCHAR(16) NOT NULL, "
                "occurred_at DATETIME NOT NULL, provenance VARCHAR(128) NOT NULL, "
                "FOREIGN KEY(fingerprint_identity_id) REFERENCES "
                f"fingerprint_identities({referred_column}) {on_delete})"
            ))
            connection.execute(text(
                "CREATE UNIQUE INDEX uq_fingerprint_occurrence_event "
                "ON fingerprint_occurrences "
                "(fingerprint_identity_id, task_id, execution_id, child_index, "
                "lifecycle_event)"
            ))
            connection.execute(text(
                "CREATE INDEX ix_fingerprint_occurrence_identity_lifecycle "
                "ON fingerprint_occurrences "
                "(fingerprint_identity_id, lifecycle_event, occurred_at)"
            ))
            connection.execute(text(
                "CREATE INDEX ix_fingerprint_occurrence_task_execution "
                "ON fingerprint_occurrences (task_id, execution_id)"
            ))

    def test_tenant_engine_open_applies_ledger_schema_without_global_manifest(self):
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                Path("data").mkdir()
                with patch.object(database, "_tenant_engines", {}):
                    engine = database.get_tenant_engine("tenant-open")
                    self.assertIn("fingerprint_identities", inspect(engine).get_table_names())
                    with engine.connect() as connection:
                        self.assertEqual(
                            connection.execute(text("PRAGMA foreign_keys")).scalar_one(),
                            1,
                        )
                    engine.dispose()
            finally:
                os.chdir(previous)

    def test_ledger_tables_are_not_registered_on_global_database_base(self):
        self.assertNotIn("fingerprint_identities", Base.metadata.tables)
        self.assertNotIn("fingerprint_occurrences", Base.metadata.tables)

    def test_new_existing_and_second_open_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tenant.db"
            engine = create_engine(f"sqlite:///{path}")
            ensure_fingerprint_ledger_schema(engine)
            ensure_fingerprint_ledger_schema(engine)
            engine.dispose()
            reopened = create_engine(f"sqlite:///{path}")
            ensure_fingerprint_ledger_schema(reopened)
            with sessionmaker(bind=reopened)() as db:
                version = db.get(FingerprintLedgerSchemaVersion, LEDGER_SCHEMA_COMPONENT)
                self.assertEqual(version.schema_version, LEDGER_SCHEMA_VERSION)
            reopened.dispose()

    def test_required_indexes_and_foreign_key_are_present(self):
        inspector = inspect(_engine())
        identity_indexes = {
            item["name"]: item
            for item in inspector.get_indexes("fingerprint_identities")
        }
        occurrence_indexes = {
            item["name"]: item
            for item in inspector.get_indexes("fingerprint_occurrences")
        }
        self.assertTrue(identity_indexes["uq_fingerprint_identity_contract"]["unique"])
        self.assertTrue(occurrence_indexes["uq_fingerprint_occurrence_event"]["unique"])
        self.assertIn("ix_fingerprint_occurrence_identity_lifecycle", occurrence_indexes)
        self.assertIn("ix_fingerprint_occurrence_task_execution", occurrence_indexes)
        self.assertEqual(
            inspector.get_foreign_keys("fingerprint_occurrences")[0]["referred_table"],
            "fingerprint_identities",
        )

    def test_malformed_existing_table_fails_verification(self):
        engine = create_engine("sqlite://")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE fingerprint_identities (id INTEGER PRIMARY KEY)"))
        with self.assertRaises(FingerprintLedgerSchemaError):
            ensure_fingerprint_ledger_schema(engine)

    def test_unsupported_version_fails_on_reopen(self):
        engine = _engine()
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE fingerprint_ledger_schema_version SET schema_version=999 "
                "WHERE component='fingerprint_ledger'"
            ))
        with self.assertRaises(FingerprintLedgerSchemaError):
            ensure_fingerprint_ledger_schema(engine)

    def test_wrong_foreign_key_referred_column_fails_verification(self):
        engine = create_engine("sqlite://")
        self._create_manual_ledger_schema(engine, referred_column="fingerprint_digest")
        with self.assertRaises(FingerprintLedgerSchemaError):
            ensure_fingerprint_ledger_schema(engine)

    def test_wrong_foreign_key_on_delete_fails_verification(self):
        engine = create_engine("sqlite://")
        self._create_manual_ledger_schema(engine, on_delete="ON DELETE NO ACTION")
        with self.assertRaises(FingerprintLedgerSchemaError):
            ensure_fingerprint_ledger_schema(engine)

    def test_wrong_primary_key_fails_verification(self):
        engine = create_engine("sqlite://")
        self._create_manual_ledger_schema(engine, identity_id="INTEGER NOT NULL")
        with self.assertRaises(FingerprintLedgerSchemaError):
            ensure_fingerprint_ledger_schema(engine)

    def test_nullable_required_column_fails_verification(self):
        engine = create_engine("sqlite://")
        self._create_manual_ledger_schema(engine, fingerprint_digest="VARCHAR(64)")
        with self.assertRaises(FingerprintLedgerSchemaError):
            ensure_fingerprint_ledger_schema(engine)

    def test_wrong_type_affinity_fails_verification(self):
        engine = create_engine("sqlite://")
        self._create_manual_ledger_schema(engine, child_index="TEXT NOT NULL")
        with self.assertRaises(FingerprintLedgerSchemaError):
            ensure_fingerprint_ledger_schema(engine)

    def test_schema_verification_failure_does_not_poison_tenant_engine_cache(self):
        failed_engine = create_engine("sqlite://")
        retry_engine = create_engine("sqlite://")
        engine_cache = {}
        try:
            with (
                patch.object(database, "_tenant_engines", engine_cache),
                patch.object(
                    database,
                    "create_engine",
                    side_effect=[failed_engine, retry_engine],
                ),
            ):
                with patch(
                    "src.api.fingerprint_ledger.ensure_fingerprint_ledger_schema",
                    side_effect=FingerprintLedgerSchemaError("controlled invalid schema"),
                ):
                    with self.assertRaises(FingerprintLedgerSchemaError):
                        database.get_tenant_engine("retry-tenant")
                    self.assertNotIn("retry-tenant", engine_cache)

                engine = database.get_tenant_engine("retry-tenant")
                self.assertIs(engine_cache["retry-tenant"], engine)
        finally:
            failed_engine.dispose()
            retry_engine.dispose()


class FingerprintLedgerRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = _engine()
        self.Session = sessionmaker(bind=self.engine)

    def _counts(self):
        with self.Session() as db:
            return (
                len(db.scalars(select(FingerprintIdentity)).all()),
                len(db.scalars(select(FingerprintOccurrence)).all()),
            )

    def test_identity_and_occurrence_idempotency(self):
        with self.Session() as db:
            repository = FingerprintLedgerRepository(db)
            self.assertEqual(repository.record_occurrences([_record(), _record()]), 1)
            db.commit()
        self.assertEqual(self._counts(), (1, 1))

    def test_identity_dimensions_and_canonical_invariant(self):
        records = [
            _record(),
            _record(fingerprint_digest="b" * 64, execution_id="e-b"),
            _record(fingerprint_version=2, execution_id="e-v2"),
            _record(fingerprint_type="other", execution_id="e-other"),
        ]
        with self.Session() as db:
            FingerprintLedgerRepository(db).record_occurrences(records)
            db.commit()
        self.assertEqual(self._counts(), (4, 4))
        with self.Session() as db:
            with self.assertRaisesRegex(
                FingerprintLedgerCanonicalMismatch,
                "FINGERPRINT_LEDGER_CANONICAL_MISMATCH",
            ):
                FingerprintLedgerRepository(db).record_occurrence(
                    _record(canonical_payload='{"different":true}', execution_id="e-mismatch")
                )

    def test_lifecycle_and_child_occurrences_do_not_inflate_on_replay(self):
        records = [
            _record(lifecycle_event="PLANNED"),
            _record(lifecycle_event="RENDERED"),
            _record(lifecycle_event="RENDERED"),
            _record(task_id="task-b", execution_id="execution-b", child_index=1),
            _record(task_id="task-c", execution_id="execution-c", lifecycle_event="FAILED"),
        ]
        with self.Session() as db:
            FingerprintLedgerRepository(db).record_occurrences(records)
            db.commit()
        self.assertEqual(self._counts(), (1, 4))

    def test_same_fingerprint_is_physically_isolated_per_tenant_database(self):
        with tempfile.TemporaryDirectory() as directory:
            engines = [
                _engine(f"sqlite:///{Path(directory) / name}")
                for name in ("tenant-a.db", "tenant-b.db")
            ]
            for index, engine in enumerate(engines):
                with sessionmaker(bind=engine)() as db:
                    FingerprintLedgerRepository(db).record_occurrence(
                        _record(task_id=f"task-{index}", execution_id=f"execution-{index}")
                    )
                    db.commit()
            for engine in engines:
                with sessionmaker(bind=engine)() as db:
                    self.assertEqual(len(db.scalars(select(FingerprintIdentity)).all()), 1)
                    self.assertEqual(len(db.scalars(select(FingerprintOccurrence)).all()), 1)
                engine.dispose()

    def test_shadow_engine_failure_is_non_blocking(self):
        with patch.object(routes_dsl, "get_tenant_engine", side_effect=RuntimeError("down")):
            self.assertFalse(routes_dsl._record_fingerprint_ledger_records_safely(
                "tenant-a", [_record()], phase="planned"
            ))


class FingerprintLedgerHistoryTransactionTests(unittest.TestCase):
    def setUp(self):
        self.engine = _engine()
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    @staticmethod
    def _result(task_suffix="0"):
        return routes_dsl._ChildResult(
            child_index=0,
            execution_id=f"execution-{task_suffix}",
            file_sid=f"file-{task_suffix}",
            outcome="succeeded",
            assets=[{"file_path": f"final-{task_suffix}.mp4"}],
            elapsed=0.01,
            error_code=None,
            error_message=None,
            prompt_details={"meta": None, "timeline": []},
        )

    def test_task_history_and_terminal_occurrence_share_tenant_transaction(self):
        result = self._result("shared")
        terminal = _record(
            task_id="history-shared",
            execution_id=result.execution_id,
            lifecycle_event="RENDERED",
        )
        with patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine):
            ledger_ok = routes_dsl._persist_task_history(
                task_id="history-shared",
                tenant_id="tenant-a",
                prompt="prompt",
                batch_size=1,
                elapsed=0.1,
                child_results=[result],
                output_assets=result.assets,
                warning_codes=[],
                ledger_terminal_records=[terminal],
            )
        self.assertTrue(ledger_ok)
        with self.Session() as db:
            self.assertEqual(len(db.scalars(select(TaskHistory)).all()), 1)
            self.assertEqual(len(db.scalars(select(FingerprintOccurrence)).all()), 1)

    def test_ledger_savepoint_failure_preserves_task_history(self):
        result = self._result("savepoint")
        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_dsl,
                "_record_fingerprint_ledger_records",
                side_effect=RuntimeError("controlled ledger fault"),
            ),
        ):
            ledger_ok = routes_dsl._persist_task_history(
                task_id="history-savepoint",
                tenant_id="tenant-a",
                prompt="prompt",
                batch_size=1,
                elapsed=0.1,
                child_results=[result],
                output_assets=result.assets,
                warning_codes=[],
                ledger_terminal_records=[_record(task_id="history-savepoint")],
            )
        self.assertFalse(ledger_ok)
        with self.Session() as db:
            self.assertEqual(len(db.scalars(select(TaskHistory)).all()), 1)
            self.assertEqual(len(db.scalars(select(FingerprintOccurrence)).all()), 0)


class TenantAuthorityTests(unittest.TestCase):
    def test_http_route_rejects_header_body_split_before_planning(self):
        app = FastAPI()
        app.include_router(routes_dsl.router, prefix="/api/v1")

        def fake_db():
            yield Mock()

        app.dependency_overrides[database.get_db] = fake_db
        response = TestClient(app).post(
            "/api/v1/tasks/submit-dsl",
            headers={"X-Local-User": "tenant-a"},
            json={
                "engine_type": "content",
                "timeline": [],
                "prompt": "blind",
                "tenant_id": "tenant-b",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "TENANT_AUTHORITY_MISMATCH")

    def test_omitted_body_uses_header_and_explicit_mismatch_is_rejected(self):
        header_request = _request({"X-Local-User": "tenant-a"})
        omitted = RenderDSLRequest(engine_type="content", timeline=[], tenant_id=None)
        self.assertEqual(
            routes_dsl._authoritative_request_tenant(omitted, header_request),
            "tenant-a",
        )
        mismatched = omitted.model_copy(update={"tenant_id": "tenant-b"})
        with self.assertRaises(HTTPException) as raised:
            routes_dsl._authoritative_request_tenant(mismatched, header_request)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "TENANT_AUTHORITY_MISMATCH")

    def test_submit_schedules_background_with_header_authority(self):
        pools = _pools(1)
        payload = _payload(pools)
        preview = _plan_for_selections(payload, (pools[0][0],))
        request_model = RenderDSLRequest(
            engine_type=payload.engine_type,
            timeline=list(payload.timeline),
            tenant_id="tenant-a",
            variant_planning_policy="exact_main_visual",
        )
        background = Mock()
        parser = Mock()
        parser.parse_and_resolve.return_value = preview
        with (
            patch.object(routes_dsl, "DSLParserNode", return_value=parser),
            patch.object(
                routes_dsl,
                "_admit_dsl_public_task",
                return_value="admitted-test-task",
            ),
        ):
            routes_dsl.submit_dsl(
                request_model,
                background,
                db=Mock(),
                request=_request({"X-Local-User": "tenant-a"}),
            )
        scheduled = background.add_task.call_args
        self.assertEqual(scheduled.args[5], "tenant-a")


class FingerprintLedgerCoordinatorTests(unittest.TestCase):
    def _run(self, policy, planning_result, failed_indices=()):
        planned_calls = []
        history_terminal = []

        def safe_write(_tenant, records, *, phase):
            planned_calls.append((phase, tuple(records)))
            return True

        def persist(**kwargs):
            history_terminal.extend(kwargs["ledger_terminal_records"])
            return True

        def worker(plan, _task_id, *args, file_sid=None, **kwargs):
            resolved_sid = file_sid or args[-1]
            succeeded = kwargs["child_index"] not in failed_indices
            return routes_dsl._ChildResult(
                child_index=kwargs["child_index"],
                execution_id=kwargs["execution_id"],
                file_sid=resolved_sid,
                outcome="succeeded" if succeeded else "failed",
                assets=[{"file_path": f"final-{resolved_sid}.mp4"}] if succeeded else [],
                elapsed=0.01,
                error_code=None if succeeded else "CONTROLLED_FAILURE",
                error_message=None if succeeded else "controlled",
                prompt_details={"meta": None, "timeline": []},
            )

        planner_name = (
            "_plan_exact_main_visual_balanced_variants_from_db"
            if policy == "exact_main_visual_balanced"
            else "_plan_exact_main_visual_variants_from_db"
        )
        with (
            patch.object(routes_dsl, planner_name, return_value=planning_result),
            patch.object(routes_dsl, "render_worker", side_effect=worker),
            patch.object(routes_dsl, "_persist_task_history", side_effect=persist),
            patch.object(
                routes_dsl,
                "_record_fingerprint_ledger_records_safely",
                side_effect=safe_write,
            ),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = routes_dsl.render_batch_worker(
                _payload(_pools(1)),
                "ledger-task",
                tenant_id="tenant-a",
                batch_size=len(planning_result.plans),
                variant_planning_policy=policy,
            )
        return terminal, planned_calls, history_terminal

    def test_exact_and_balanced_write_planned_then_terminal_lifecycle(self):
        exact_pools = _pools(4)
        exact_payload = _payload(exact_pools)
        exact_result = routes_dsl._plan_exact_main_visual_variants(
            _SyntheticParser(exact_pools), exact_payload, 4
        )
        balanced_result, _parser, _balanced_payload = _balanced(_pools(4), 4)
        for policy, result in (
            ("exact_main_visual", exact_result),
            ("exact_main_visual_balanced", balanced_result),
        ):
            with self.subTest(policy=policy):
                terminal, calls, terminal_records = self._run(policy, result, {3})
                self.assertEqual([record.lifecycle_event for record in calls[0][1]],
                                 ["PLANNED"] * 4)
                self.assertEqual([record.lifecycle_event for record in terminal_records],
                                 ["RENDERED", "RENDERED", "RENDERED", "FAILED"])
                self.assertEqual(terminal["succeededCount"], 3)

    def test_all_failed_terminalizes_without_task_history(self):
        pools = _pools(2)
        payload = _payload(pools)
        result = routes_dsl._plan_exact_main_visual_variants(
            _SyntheticParser(pools), payload, 2
        )
        calls = []
        with (
            patch.object(routes_dsl, "_plan_exact_main_visual_variants_from_db",
                         return_value=result),
            patch.object(routes_dsl, "render_worker", side_effect=RuntimeError("failed")),
            patch.object(routes_dsl, "_persist_task_history") as persist,
            patch.object(
                routes_dsl,
                "_record_fingerprint_ledger_records_safely",
                side_effect=lambda _tenant, records, *, phase:
                    calls.append((phase, tuple(records))) or True,
            ),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = routes_dsl.render_batch_worker(
                payload,
                "all-failed",
                batch_size=2,
                variant_planning_policy="exact_main_visual",
            )
        persist.assert_not_called()
        self.assertEqual([phase for phase, _records in calls], ["planned", "terminal_fallback"])
        self.assertEqual([r.lifecycle_event for r in calls[1][1]], ["FAILED", "FAILED"])
        self.assertEqual(terminal["succeededCount"], 0)

    def test_legacy_does_not_fabricate_ledger_identity(self):
        with (
            patch.object(routes_dsl, "render_worker", side_effect=RuntimeError("failed")),
            patch.object(routes_dsl, "_record_fingerprint_ledger_records_safely") as ledger,
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            routes_dsl.render_batch_worker(None, "legacy-task", variant_planning_policy="legacy")
        ledger.assert_not_called()

    def test_prepopulated_ledger_does_not_change_balanced_selection(self):
        pools = _pools(4, 2)
        payload = _payload(pools)
        before = routes_dsl._plan_exact_main_visual_balanced_variants(
            _SyntheticParser(pools), payload, 4
        )
        engine = _engine()
        with sessionmaker(bind=engine)() as db:
            repository = FingerprintLedgerRepository(db)
            for index, fingerprint in enumerate(before.fingerprints):
                contract = routes_dsl._main_visual_planning_fingerprint_contract(fingerprint)
                repository.record_occurrence(_record(
                    fingerprint_digest=contract.fingerprint_digest,
                    canonical_payload=contract.canonical_bytes.decode("utf-8"),
                    execution_id=f"existing-{index}",
                    child_index=index,
                ))
            db.commit()
        after = routes_dsl._plan_exact_main_visual_balanced_variants(
            _SyntheticParser(pools), payload, 4
        )
        self.assertEqual(before.fingerprints, after.fingerprints)


if __name__ == "__main__":
    unittest.main()
