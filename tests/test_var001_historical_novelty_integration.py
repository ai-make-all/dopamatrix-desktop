import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from src.api import routes_dsl
from src.api.fingerprint_ledger import (
    LEDGER_DIGEST_ALGORITHM,
    FingerprintIdentity,
    FingerprintIdentityRecord,
    FingerprintLedgerCanonicalMismatch,
    FingerprintLedgerRepository,
    FingerprintOccurrenceRecord,
    ensure_fingerprint_ledger_schema,
)
from src.api.historical_novelty_policy import PreviewIntent
from src.api.models import Base, TaskHistory
from src.api.schemas import RenderDSLRequest
from tests.test_var001_balanced_axis_coverage import (
    _SyntheticParser,
    _payload,
    _plan_for_selections,
    _pools,
)


def _engine(url="sqlite://"):
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    ensure_fingerprint_ledger_schema(engine)
    return engine


def _identity_record(fingerprint):
    contract = routes_dsl._main_visual_planning_fingerprint_contract(fingerprint)
    return FingerprintIdentityRecord(
        fingerprint_type=contract.fingerprint_type,
        fingerprint_version=contract.fingerprint_version,
        fingerprint_digest=contract.fingerprint_digest,
        digest_algorithm=LEDGER_DIGEST_ALGORITHM,
        source_hash_algorithm=contract.source_hash_algorithm,
        canonical_payload=contract.canonical_bytes.decode("utf-8"),
    )


def _occurrence(fingerprint, lifecycle_event, index=0):
    identity = _identity_record(fingerprint)
    return FingerprintOccurrenceRecord(
        **identity.__dict__,
        task_id="historical-task",
        execution_id=f"historical-{lifecycle_event.lower()}-{index}",
        child_index=index,
        lifecycle_event=lifecycle_event,
        provenance="test_historical_observation",
    )


def _observer(session_factory, mode):
    return routes_dsl._HistoricalNoveltyObserver(
        lambda identity_record: routes_dsl._lookup_historical_exact_in_new_session(
            session_factory,
            identity_record,
        ),
        mode,
    )


def _successful_child(plan, _task_id, *args, file_sid=None, **kwargs):
    resolved_sid = file_sid or args[-1]
    return routes_dsl._ChildResult(
        child_index=kwargs["child_index"],
        execution_id=kwargs["execution_id"],
        file_sid=resolved_sid,
        outcome="succeeded",
        assets=[{"asset_type": "video", "file_path": f"output/{resolved_sid}.mp4"}],
        elapsed=0.01,
        error_code=None,
        error_message=None,
        prompt_details={"meta": None, "timeline": [], "plan": plan},
    )


class HistoricalNoveltyRuntimeSchemaTests(unittest.TestCase):
    def test_runtime_mode_defaults_off_and_does_not_expose_enforce(self):
        request = RenderDSLRequest(engine_type="content", timeline=[])
        self.assertEqual(request.historical_novelty_mode, "OFF")
        with self.assertRaises(ValidationError):
            RenderDSLRequest(
                engine_type="content",
                timeline=[],
                historical_novelty_mode="ENFORCE",
            )

    def test_non_authoritative_policy_cannot_claim_runtime_observation(self):
        request = RenderDSLRequest(
            engine_type="content",
            timeline=[],
            variant_planning_policy="legacy",
            historical_novelty_mode="ADVISORY",
        )
        with self.assertRaisesRegex(
            Exception,
            "HISTORICAL_NOVELTY_REQUIRES_AUTHORITATIVE_PLANNING",
        ):
            routes_dsl._guard_pre_planner_policy(request, flow="submit_dsl")

    def test_submit_dsl_forwards_advisory_mode_to_authoritative_worker(self):
        pools = _pools(1)
        payload = _payload(pools)
        preview = _plan_for_selections(payload, (pools[0][0],))
        request = RenderDSLRequest(
            engine_type=payload.engine_type,
            timeline=list(payload.timeline),
            variant_planning_policy="exact_main_visual_balanced",
            historical_novelty_mode="ADVISORY",
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
            routes_dsl.submit_dsl(request, background, db=Mock())
        self.assertEqual(
            background.add_task.call_args.kwargs["historical_novelty_mode"],
            "ADVISORY",
        )
        self.assertIs(
            background.add_task.call_args.kwargs["preview_intent"],
            PreviewIntent.AUTOMATIC_PREVIEW,
        )


class HistoricalNoveltyPlannerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = _engine()
        self.Session = sessionmaker(bind=self.engine)
        self.pools = _pools(1)
        self.payload = _payload(self.pools)
        self.baseline = routes_dsl._plan_exact_main_visual_balanced_variants(
            _SyntheticParser(self.pools),
            self.payload,
            1,
        )
        self.fingerprint = self.baseline.fingerprints[0]

    def tearDown(self):
        self.engine.dispose()

    def _preload(self, lifecycle_events):
        with self.Session() as db:
            repository = FingerprintLedgerRepository(db)
            for index, lifecycle_event in enumerate(lifecycle_events):
                repository.record_occurrence(
                    _occurrence(self.fingerprint, lifecycle_event, index)
                )
            db.commit()

    def _run(self, mode):
        observer = _observer(self.Session, mode)
        result = routes_dsl._plan_exact_main_visual_balanced_variants(
            _SyntheticParser(self.pools),
            self.payload,
            1,
            historical_observer=observer,
        )
        diagnostics = result.historical_novelty_diagnostics
        self.assertIsNotNone(diagnostics)
        return result, routes_dsl._historical_novelty_diagnostics_v1_payload(
            diagnostics
        )

    def test_default_off_performs_no_lookup_and_preserves_all_outputs(self):
        with (
            patch.object(
                routes_dsl,
                "get_tenant_engine",
                return_value=self.engine,
            ),
            patch.object(
                routes_dsl,
                "DSLParserNode",
                return_value=_SyntheticParser(self.pools),
            ),
            patch.object(
                FingerprintLedgerRepository,
                "lookup_historical_exact",
            ) as lookup,
            patch.object(
                FingerprintLedgerRepository,
                "acquire_reservation",
                side_effect=AssertionError("reservation must not be called"),
            ),
        ):
            result = routes_dsl._plan_exact_main_visual_balanced_variants_from_db(
                "tenant-a",
                self.payload,
                1,
            )
        lookup.assert_not_called()
        self.assertEqual(result.plans, self.baseline.plans)
        self.assertEqual(result.fingerprints, self.baseline.fingerprints)
        self.assertEqual(
            result.coverage_diagnostics,
            self.baseline.coverage_diagnostics,
        )
        self.assertIsNone(result.historical_novelty_diagnostics)

    def test_observe_rendered_collects_facts_without_advisory_or_rejection(self):
        self._preload(("RENDERED",))
        result, diagnostics = self._run("OBSERVE")
        self.assertEqual(result.fingerprints, self.baseline.fingerprints)
        self.assertEqual(diagnostics["rendered_matches"], 1)
        self.assertEqual(diagnostics["advisory_count"], 0)
        self.assertEqual(diagnostics["historical_rejection_count"], 0)

    def test_advisory_rendered_is_advisory_and_never_rejected(self):
        self._preload(("RENDERED",))
        result, diagnostics = self._run("ADVISORY")
        self.assertEqual(result.fingerprints, self.baseline.fingerprints)
        self.assertEqual(diagnostics["rendered_matches"], 1)
        self.assertEqual(diagnostics["advisory_count"], 1)
        self.assertEqual(diagnostics["actual_override_count"], 0)
        self.assertEqual(diagnostics["historical_rejection_count"], 0)

    def test_lifecycle_evidence_classes_are_partitioned_without_double_counting(self):
        cases = (
            (("PLANNED",), "planned_only_matches"),
            (("FAILED",), "failed_only_matches"),
            (("PLANNED", "FAILED"), "planned_and_failed_matches"),
        )
        for lifecycle_events, expected_counter in cases:
            with self.subTest(lifecycle_events=lifecycle_events):
                engine = _engine()
                Session = sessionmaker(bind=engine)
                with Session() as db:
                    repository = FingerprintLedgerRepository(db)
                    for index, event in enumerate(lifecycle_events):
                        repository.record_occurrence(
                            _occurrence(self.fingerprint, event, index)
                        )
                    db.commit()
                    observer = _observer(Session, "ADVISORY")
                    result = routes_dsl._plan_exact_main_visual_balanced_variants(
                        _SyntheticParser(self.pools),
                        self.payload,
                        1,
                        historical_observer=observer,
                    )
                diagnostics = routes_dsl._historical_novelty_diagnostics_v1_payload(
                    result.historical_novelty_diagnostics
                )
                self.assertEqual(diagnostics[expected_counter], 1)
                self.assertEqual(diagnostics["advisory_count"], 0)
                self.assertEqual(diagnostics["historical_rejection_count"], 0)
                self.assertEqual(diagnostics["lookup_successes"], 1)
                engine.dispose()

    def test_identity_only_and_no_history_are_distinct(self):
        with self.Session() as db:
            FingerprintLedgerRepository(db).ensure_identity(
                _identity_record(self.fingerprint)
            )
            db.commit()
        _result, identity_only = self._run("ADVISORY")
        self.assertEqual(identity_only["identity_matches"], 1)
        self.assertEqual(identity_only["historical_occurrence_matches"], 0)
        self.assertEqual(identity_only["identity_only_matches"], 1)
        self.assertEqual(identity_only["no_history_matches"], 0)

        empty_engine = _engine()
        EmptySession = sessionmaker(bind=empty_engine)
        observer = _observer(EmptySession, "ADVISORY")
        result = routes_dsl._plan_exact_main_visual_balanced_variants(
            _SyntheticParser(self.pools),
            self.payload,
            1,
            historical_observer=observer,
        )
        no_history = routes_dsl._historical_novelty_diagnostics_v1_payload(
            result.historical_novelty_diagnostics
        )
        self.assertEqual(no_history["identity_matches"], 0)
        self.assertEqual(no_history["no_history_matches"], 1)
        empty_engine.dispose()

    def test_lookup_infrastructure_failure_fails_open_with_bounded_warning(self):
        for mode in ("OBSERVE", "ADVISORY"):
            with self.subTest(mode=mode):
                observer = _observer(self.Session, mode)
                with (
                    patch.object(
                        observer,
                        "_lookup_historical_exact",
                        side_effect=OperationalError(
                            "SELECT historical facts",
                            {"secret": "must-not-be-logged"},
                            sqlite3.OperationalError("database unavailable"),
                        ),
                    ),
                    patch.object(
                        FingerprintLedgerRepository,
                        "acquire_reservation",
                        side_effect=AssertionError("reservation must not be called"),
                    ),
                    patch.object(routes_dsl.fingerprint_logger, "warning") as warning,
                ):
                    result = routes_dsl._plan_exact_main_visual_balanced_variants(
                        _SyntheticParser(self.pools),
                        self.payload,
                        1,
                        historical_observer=observer,
                    )
                diagnostics = routes_dsl._historical_novelty_diagnostics_v1_payload(
                    result.historical_novelty_diagnostics
                )
                self.assertEqual(result.fingerprints, self.baseline.fingerprints)
                self.assertEqual(diagnostics["lookup_failures"], 1)
                self.assertEqual(
                    diagnostics["accepted_with_lookup_unknown_count"],
                    1,
                )
                warning.assert_called_once()
                warning_message = warning.call_args.args[0]
                self.assertIn("category=database_read_unavailable", warning_message)
                self.assertNotIn("SELECT historical facts", warning_message)
                self.assertNotIn("must-not-be-logged", warning_message)

    def test_programming_errors_fail_closed_without_unknown_acceptance(self):
        for mode in ("OBSERVE", "ADVISORY"):
            for error in (
                AttributeError("bug"),
                TypeError("bug"),
                RuntimeError("unexpected bug"),
            ):
                with self.subTest(mode=mode, error=type(error).__name__):
                    lookup = Mock(side_effect=error)
                    observer = routes_dsl._HistoricalNoveltyObserver(lookup, mode)
                    with self.assertRaises(type(error)):
                        routes_dsl._plan_exact_main_visual_balanced_variants(
                            _SyntheticParser(self.pools),
                            self.payload,
                            1,
                            historical_observer=observer,
                        )
                    diagnostics = observer.diagnostics()
                    self.assertEqual(diagnostics.candidate_checks, 1)
                    self.assertEqual(diagnostics.lookup_failures, 0)
                    self.assertEqual(
                        diagnostics.accepted_with_lookup_unknown_count,
                        0,
                    )
                    self.assertEqual(
                        diagnostics.accepted_after_historical_check_count,
                        0,
                    )

    def test_dbapi_failure_isolated_and_next_candidate_lookup_recovers(self):
        pools = _pools(2)
        payload = _payload(pools)
        baseline = routes_dsl._plan_exact_main_visual_balanced_variants(
            _SyntheticParser(pools),
            payload,
            2,
        )
        with tempfile.TemporaryDirectory() as directory:
            engine = _engine(
                f"sqlite:///{Path(directory) / 'tenant-history-isolation.db'}"
            )
            original_lookup = FingerprintLedgerRepository.lookup_historical_exact
            planning_sessions = []
            planning_queries = []
            historical_sessions = []

            def parser_factory(planning_db):
                planning_sessions.append(planning_db)

                def materialize(candidate_payload, selections, _key):
                    planning_queries.append(planning_db.scalar(select(1)))
                    return _plan_for_selections(candidate_payload, selections)

                return _SyntheticParser(pools, materialize_hook=materialize)

            def lookup_with_first_real_dbapi_failure(repository, identity_record):
                historical_sessions.append(repository._session)
                if len(historical_sessions) == 1:
                    repository._session.execute(
                        text("SELECT * FROM var001_missing_history_source")
                    ).all()
                return original_lookup(repository, identity_record)

            with (
                patch.object(routes_dsl, "get_tenant_engine", return_value=engine),
                patch.object(routes_dsl, "DSLParserNode", side_effect=parser_factory),
                patch.object(
                    FingerprintLedgerRepository,
                    "lookup_historical_exact",
                    autospec=True,
                    side_effect=lookup_with_first_real_dbapi_failure,
                ),
                patch.object(routes_dsl.fingerprint_logger, "warning") as warning,
            ):
                result = (
                    routes_dsl._plan_exact_main_visual_balanced_variants_from_db(
                        "tenant-a",
                        payload,
                        2,
                        historical_novelty_mode="ADVISORY",
                    )
                )

            diagnostics = routes_dsl._historical_novelty_diagnostics_v1_payload(
                result.historical_novelty_diagnostics
            )
            self.assertEqual(result.plans, baseline.plans)
            self.assertEqual(result.fingerprints, baseline.fingerprints)
            self.assertEqual(result.coverage_diagnostics, baseline.coverage_diagnostics)
            self.assertEqual(planning_queries, [1, 1])
            self.assertEqual(len(planning_sessions), 1)
            self.assertEqual(len(historical_sessions), 2)
            self.assertIsNot(historical_sessions[0], historical_sessions[1])
            self.assertTrue(
                all(session is not planning_sessions[0] for session in historical_sessions)
            )
            self.assertEqual(diagnostics["candidate_checks"], 2)
            self.assertEqual(diagnostics["lookup_failures"], 1)
            self.assertEqual(diagnostics["lookup_successes"], 1)
            self.assertEqual(
                diagnostics["accepted_with_lookup_unknown_count"],
                1,
            )
            self.assertEqual(
                diagnostics["accepted_after_historical_check_count"],
                1,
            )
            warning.assert_called_once()
            engine.dispose()

    def test_canonical_mismatch_fails_closed(self):
        identity = _identity_record(self.fingerprint)
        with self.Session() as db:
            db.add(FingerprintIdentity(
                fingerprint_type=identity.fingerprint_type,
                fingerprint_version=identity.fingerprint_version,
                fingerprint_digest=identity.fingerprint_digest,
                digest_algorithm=identity.digest_algorithm,
                source_hash_algorithm=identity.source_hash_algorithm,
                canonical_payload='{"corrupt":true}',
                created_at=datetime(2026, 1, 1),
            ))
            db.commit()
            observer = _observer(self.Session, "ADVISORY")
            with self.assertRaises(FingerprintLedgerCanonicalMismatch):
                routes_dsl._plan_exact_main_visual_balanced_variants(
                    _SyntheticParser(self.pools),
                    self.payload,
                    1,
                    historical_observer=observer,
                )

    def test_no_reservation_access_in_observe_or_advisory(self):
        for mode in ("OBSERVE", "ADVISORY"):
            with self.subTest(mode=mode):
                with (
                    self.Session() as db,
                    patch.object(
                        FingerprintLedgerRepository,
                        "acquire_reservation",
                        side_effect=AssertionError("reservation must not be called"),
                    ),
                ):
                    observer = _observer(self.Session, mode)
                    result = routes_dsl._plan_exact_main_visual_balanced_variants(
                        _SyntheticParser(self.pools),
                        self.payload,
                        1,
                        historical_observer=observer,
                    )
                self.assertEqual(result.fingerprints, self.baseline.fingerprints)

    def test_diagnostics_serializer_enforces_phase3d2b_counter_invariants(self):
        result, _payload_value = self._run("ADVISORY")
        diagnostics = result.historical_novelty_diagnostics
        for malformed in (
            replace(diagnostics, candidate_checks=2),
            replace(diagnostics, historical_rejection_count=1),
            replace(diagnostics, reservation_conflict_count=1),
            replace(diagnostics, actual_override_count=1),
        ):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    routes_dsl._historical_novelty_diagnostics_v1_payload(
                        malformed
                    )

    def test_exact_planner_observes_without_selection_effect(self):
        exact_before = routes_dsl._plan_exact_main_visual_variants(
            _SyntheticParser(self.pools), self.payload, 1
        )
        self._preload(("RENDERED",))
        observer = _observer(self.Session, "ADVISORY")
        exact_after = routes_dsl._plan_exact_main_visual_variants(
            _SyntheticParser(self.pools),
            self.payload,
            1,
            historical_observer=observer,
        )
        self.assertEqual(exact_after.plans, exact_before.plans)
        self.assertEqual(exact_after.fingerprints, exact_before.fingerprints)
        self.assertEqual(
            exact_after.historical_novelty_diagnostics.rendered_matches,
            1,
        )


class HistoricalNoveltyPreviewAndTenantTests(unittest.TestCase):
    def test_preview_uses_same_observation_path_without_selection_effect(self):
        pools = _pools(2, 2)
        payload = _payload(pools)
        preview = _plan_for_selections(payload, (pools[0][0], pools[1][0]))
        before = routes_dsl._plan_exact_main_visual_balanced_variants(
            _SyntheticParser(pools), payload, 2, preview_plan=preview
        )
        engine = _engine()
        Session = sessionmaker(bind=engine)
        with Session() as db:
            FingerprintLedgerRepository(db).record_occurrence(
                _occurrence(before.fingerprints[0], "RENDERED")
            )
            db.commit()
            observer = _observer(Session, "ADVISORY")
            after = routes_dsl._plan_exact_main_visual_balanced_variants(
                _SyntheticParser(pools),
                payload,
                2,
                preview_plan=preview,
                historical_observer=observer,
                preview_intent=PreviewIntent.AUTOMATIC_PREVIEW,
            )
        diagnostics = routes_dsl._historical_novelty_diagnostics_v1_payload(
            after.historical_novelty_diagnostics
        )
        self.assertIs(after.plans[0], preview)
        self.assertEqual(after.plans, before.plans)
        self.assertEqual(after.fingerprints, before.fingerprints)
        self.assertEqual(after.coverage_diagnostics, before.coverage_diagnostics)
        self.assertEqual(diagnostics["rendered_matches"], 1)
        self.assertEqual(diagnostics["advisory_count"], 1)
        self.assertTrue(diagnostics["preview_checked"])
        self.assertEqual(diagnostics["preview_intent"], "AUTOMATIC_PREVIEW")
        engine.dispose()

    def test_tenant_sessions_keep_historical_facts_physically_isolated(self):
        pools = _pools(1)
        payload = _payload(pools)
        baseline = routes_dsl._plan_exact_main_visual_balanced_variants(
            _SyntheticParser(pools), payload, 1
        )
        with tempfile.TemporaryDirectory() as directory:
            engines = {
                tenant: _engine(f"sqlite:///{Path(directory) / f'{tenant}.db'}")
                for tenant in ("tenant-a", "tenant-b")
            }
            with sessionmaker(bind=engines["tenant-a"])() as db:
                FingerprintLedgerRepository(db).record_occurrence(
                    _occurrence(baseline.fingerprints[0], "RENDERED")
                )
                db.commit()

            observed = {}
            for tenant, engine in engines.items():
                with sessionmaker(bind=engine)() as db:
                    observer = _observer(sessionmaker(bind=engine), "ADVISORY")
                    result = routes_dsl._plan_exact_main_visual_balanced_variants(
                        _SyntheticParser(pools),
                        payload,
                        1,
                        historical_observer=observer,
                    )
                observed[tenant] = routes_dsl._historical_novelty_diagnostics_v1_payload(
                    result.historical_novelty_diagnostics
                )
                self.assertEqual(result.fingerprints, baseline.fingerprints)
            self.assertEqual(observed["tenant-a"]["rendered_matches"], 1)
            self.assertEqual(observed["tenant-b"]["no_history_matches"], 1)
            for engine in engines.values():
                engine.dispose()


class HistoricalNoveltyCoordinatorTests(unittest.TestCase):
    def test_summary_and_persistence_reuse_same_serialized_payload(self):
        pools = _pools(1)
        payload = _payload(pools)
        engine = _engine()
        with sessionmaker(bind=engine)() as db:
            observer = _observer(sessionmaker(bind=engine), "ADVISORY")
            planning_result = routes_dsl._plan_exact_main_visual_balanced_variants(
                _SyntheticParser(pools),
                payload,
                1,
                historical_observer=observer,
            )

        with (
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_balanced_variants_from_db",
                return_value=planning_result,
            ),
            patch.object(routes_dsl, "render_worker", side_effect=_successful_child),
            patch.object(routes_dsl, "_persist_task_history", return_value=True) as persist,
            patch.object(routes_dsl, "_emit_historical_novelty_summary") as summary,
            patch.object(
                routes_dsl,
                "_record_fingerprint_ledger_records_safely",
                return_value=True,
            ),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = routes_dsl.render_batch_worker(
                payload,
                "historical-diagnostics-task",
                batch_size=1,
                variant_planning_policy="exact_main_visual_balanced",
                historical_novelty_mode="ADVISORY",
            )

        summary.assert_called_once()
        summary_payload = summary.call_args.args[1]
        persisted_payload = persist.call_args.kwargs[
            "historical_novelty_diagnostics"
        ]
        self.assertIs(summary_payload, persisted_payload)
        self.assertEqual(summary_payload["type"], "historical_novelty")
        self.assertNotIn("historicalNoveltyDiagnostics", terminal)
        engine.dispose()

    def test_structured_summary_wraps_the_canonical_payload_once(self):
        diagnostics_payload = {
            "type": "historical_novelty",
            "version": 1,
            "historical_policy_mode": "OBSERVE",
        }
        with patch.object(routes_dsl.fingerprint_logger, "info") as info:
            routes_dsl._emit_historical_novelty_summary(
                "summary-task",
                diagnostics_payload,
            )
        info.assert_called_once()
        message = info.call_args.args[0]
        self.assertTrue(message.startswith("[HistoricalNoveltySummary] "))
        envelope = json.loads(message.split(" ", 1)[1])
        self.assertEqual(envelope["event"], "HistoricalNoveltySummary")
        self.assertEqual(
            envelope["historical_novelty_diagnostics"],
            diagnostics_payload,
        )

    def test_task_history_planning_summary_persists_same_payload(self):
        engine = _engine()
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        diagnostics_payload = {
            "type": "historical_novelty",
            "version": 1,
            "historical_policy_mode": "ADVISORY",
        }
        child = routes_dsl._ChildResult(
            child_index=0,
            execution_id="execution-1",
            file_sid="file-1",
            outcome="succeeded",
            assets=[{"asset_type": "video", "file_path": "output/final.mp4"}],
            elapsed=0.1,
            error_code=None,
            error_message=None,
            prompt_details={"meta": None, "timeline": []},
        )
        with patch.object(routes_dsl, "get_tenant_engine", return_value=engine):
            routes_dsl._persist_task_history(
                task_id="history-task",
                tenant_id="tenant-a",
                prompt="prompt",
                batch_size=1,
                elapsed=0.1,
                child_results=[child],
                output_assets=child.assets,
                warning_codes=[],
                historical_novelty_diagnostics=diagnostics_payload,
            )
        with Session() as db:
            record = db.scalar(
                select(TaskHistory).where(TaskHistory.task_id == "history-task")
            )
            planning_summary = json.loads(record.prompt_details)["planning_summary"]
        self.assertEqual(
            planning_summary["historical_novelty_diagnostics"],
            diagnostics_payload,
        )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
