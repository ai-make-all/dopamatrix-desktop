import json
import os
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch, PropertyMock

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select, update
from sqlalchemy.orm import sessionmaker

from src.api import reservation_diagnostics, routes_dsl
from src.api.database import initialize_application_schema
from src.api.dsl_parser import MainVisualCandidate
from src.api.fingerprint_ledger import (
    FingerprintLedgerRepository,
    FingerprintReservation,
    ReservationAcquireStatus,
    ensure_fingerprint_ledger_schema,
)
from src.api.models import Base, ReservationRunDiagnostic, TaskHistory, VideoTask
from src.api.planner_reservation import (
    PlannerReservationAuthorityLost,
    PlannerReservationController,
    PlannerReservationError,
)
from src.api.public_task_admission import admit_public_task
from src.api.reservation_diagnostics import (
    ReservationPlanningObservation,
    ReservationTerminalObservation,
    best_effort_record_reservation_planning,
    best_effort_record_reservation_terminal,
    best_effort_start_reservation_diagnostic,
    reservation_diagnostics_summary,
)
from src.api.reservation_lease import ReservationLeaseConfiguration
from src.api.routes_reservation_diagnostics import (
    get_reservation_diagnostics_summary,
)
from tests.test_var001_balanced_axis_coverage import _payload, _pools
from tests import test_var001_public_reservation_activation as public_activation


class _UnstringablePlannerError(PlannerReservationError):
    def __str__(self):
        raise RuntimeError("diagnostic exception formatting failed")


class ReservationDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.harness = public_activation.PublicReservationActivationTests(
            methodName="test_request_default_and_explicit_off_are_the_same_policy"
        )
        self.harness.setUp()
        self.engine = self.harness.engine
        self.Session = self.harness.Session

    def tearDown(self):
        self.harness.tearDown()

    def _row(self, task_id):
        with self.Session() as session:
            return session.scalar(
                select(ReservationRunDiagnostic).where(
                    ReservationRunDiagnostic.task_id == task_id
                )
            )

    @staticmethod
    def _failed_child(_plan, _task_id, *args, file_sid=None, **kwargs):
        return routes_dsl._ChildResult(
            child_index=kwargs["child_index"],
            execution_id=kwargs["execution_id"],
            file_sid=file_sid or args[-1],
            outcome="failed",
            assets=[],
            elapsed=0.01,
            error_code="CONTROLLED_FAILURE",
            error_message="controlled failure",
            prompt_details={"meta": None, "timeline": []},
            fatigue_asset_ids=(),
        )

    def test_off_mode_has_no_diagnostic_row_or_event(self):
        task_id = self.harness._admit()

        def implementation(*args, **kwargs):
            kwargs["_terminal_target_callback"]("completed")
            return {"taskId": args[1], "status": "completed"}

        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(routes_dsl, "_render_batch_worker_impl", side_effect=implementation),
            patch.object(reservation_diagnostics.logger, "info") as diagnostic_log,
        ):
            terminal = routes_dsl.render_batch_worker(
                None,
                task_id,
                tenant_id="tenant-a",
                reservation_conflict_mode="OFF",
                public_task_admitted=True,
            )
        self.assertEqual(terminal["status"], "completed")
        self.assertIsNone(self._row(task_id))
        diagnostic_log.assert_not_called()

    def test_exact_and_balanced_success_are_durable(self):
        for policy in ("exact_main_visual", "exact_main_visual_balanced"):
            with self.subTest(policy=policy):
                task_id = self.harness._admit()
                terminal, _controllers, _results, _broadcasts = (
                    self.harness._run_public(
                        task_id,
                        _pools(2),
                        policy=policy,
                    )
                )
                row = self._row(task_id)
                self.assertEqual(terminal["status"], "completed")
                self.assertEqual(row.task_id, task_id)
                self.assertEqual(row.planning_policy, policy)
                self.assertTrue(row.planning_observed)
                self.assertEqual(row.requested_count, 1)
                self.assertEqual(row.planned_count, 1)
                self.assertEqual(row.succeeded_count, 1)
                self.assertEqual(row.failed_count, 0)
                self.assertEqual(row.terminal_status, "completed")
                self.assertFalse(row.authority_lost)

    def test_recovered_conflict_is_observed_without_exhaustion_warning(self):
        task_a = self.harness._admit()
        task_b = self.harness._admit()
        started = threading.Event()
        release = threading.Event()

        def held_child(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(timeout=8))
            return self.harness._success(*args, **kwargs)

        holder = threading.Thread(
            target=lambda: self.harness._run_public(
                task_a,
                _pools(1),
                child=held_child,
            )
        )
        holder.start()
        self.assertTrue(started.wait(timeout=8))
        recovered = self.harness._run_public(task_b, _pools(2))
        release.set()
        holder.join(timeout=10)

        row = self._row(task_b)
        self.assertEqual(recovered[2][0].termination_reason, "REQUEST_SATISFIED")
        self.assertNotIn(
            "RESERVATION_CONFLICT_EXHAUSTED",
            recovered[0]["warningCodes"],
        )
        self.assertEqual(row.reservation_conflict_count, 1)
        self.assertTrue(row.had_reservation_conflict)
        self.assertFalse(row.zero_plan_conflict)

    def test_conflict_metric_counts_distinct_fingerprints_not_attempts(self):
        pools = [[
            MainVisualCandidate(
                asset_id=1,
                file_hash="same-hash",
            ),
            MainVisualCandidate(
                asset_id=2,
                file_hash="same-hash",
            ),
        ]]
        identity = self.harness._identity_for_pools(pools)
        with self.Session() as session:
            acquired = FingerprintLedgerRepository(session).acquire_reservation(
                identity,
                owner_task_id=str(uuid.uuid4()),
                owner_slot_index=0,
                now=datetime.now(timezone.utc).replace(tzinfo=None),
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(seconds=30),
            )
            session.commit()
        self.assertEqual(acquired.status, ReservationAcquireStatus.ACQUIRED)

        task_id = self.harness._admit(batch_size=2)
        terminal, controllers, results, _broadcasts = self.harness._run_public(
            task_id,
            pools,
            batch_size=2,
        )
        row = self._row(task_id)
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(controllers[0].conflict_count, 2)
        self.assertEqual(results[0].reservation_conflict_count, 1)
        self.assertEqual(row.reservation_conflict_count, 1)
        self.assertTrue(row.had_reservation_conflict)

    def test_zero_plan_and_partial_plan_causality(self):
        task_a = self.harness._admit()
        zero_task = self.harness._admit()
        partial_task = self.harness._admit(batch_size=2)
        failed_partial_task = self.harness._admit(batch_size=2)
        started = threading.Event()
        release = threading.Event()

        def held_child(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(timeout=8))
            return self.harness._success(*args, **kwargs)

        holder = threading.Thread(
            target=lambda: self.harness._run_public(
                task_a,
                _pools(1),
                child=held_child,
            )
        )
        holder.start()
        self.assertTrue(started.wait(timeout=8))
        zero = self.harness._run_public(zero_task, _pools(1))
        partial = self.harness._run_public(partial_task, _pools(2), batch_size=2)
        failed_partial = self.harness._run_public(
            failed_partial_task,
            _pools(2),
            batch_size=2,
            child=self._failed_child,
        )
        release.set()
        holder.join(timeout=10)

        zero_row = self._row(zero_task)
        self.assertEqual(zero[0]["errorCode"], "RESERVATION_CONFLICT_EXHAUSTED")
        self.assertEqual(zero_row.planned_count, 0)
        self.assertTrue(zero_row.zero_plan_conflict)
        self.assertFalse(zero_row.partial_plan)
        self.assertEqual(zero_row.error_code, "RESERVATION_CONFLICT_EXHAUSTED")

        partial_row = self._row(partial_task)
        self.assertEqual(partial[0]["status"], "completed")
        self.assertTrue(partial_row.partial_plan)
        self.assertFalse(partial_row.zero_plan_conflict)

        failed_row = self._row(failed_partial_task)
        self.assertEqual(failed_partial[0]["status"], "failed")
        self.assertNotEqual(
            failed_partial[0].get("errorCode"),
            "RESERVATION_CONFLICT_EXHAUSTED",
        )
        self.assertTrue(failed_row.partial_plan)
        self.assertEqual(failed_row.planned_count, 1)
        self.assertEqual(failed_row.succeeded_count, 0)
        self.assertEqual(failed_row.failed_count, 1)
        self.assertIsNone(failed_row.error_code)

    def test_authority_loss_and_terminal_failure_are_observed(self):
        pools = _pools(1)
        authority_task = self.harness._admit()
        identity = self.harness._identity_for_pools(pools)

        def stale_child(*args, **kwargs):
            with self.Session() as session:
                reservation = session.scalar(select(FingerprintReservation))
                session.execute(
                    update(FingerprintReservation)
                    .where(
                        FingerprintReservation.fingerprint_identity_id
                        == reservation.fingerprint_identity_id
                    )
                    .values(
                        expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
                        - timedelta(seconds=1)
                    )
                )
                session.commit()
                takeover = FingerprintLedgerRepository(session).acquire_reservation(
                    identity,
                    owner_task_id=str(uuid.uuid4()),
                    owner_slot_index=0,
                    now=datetime.now(timezone.utc).replace(tzinfo=None),
                    expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
                    + timedelta(seconds=30),
                )
                session.commit()
                self.assertEqual(takeover.status, ReservationAcquireStatus.ACQUIRED)
            return self.harness._success(*args, **kwargs)

        authority = self.harness._run_public(
            authority_task,
            pools,
            child=stale_child,
        )
        authority_row = self._row(authority_task)
        self.assertEqual(authority[0]["errorCode"], "RESERVATION_AUTHORITY_LOST")
        self.assertTrue(authority_row.authority_lost)
        self.assertEqual(authority_row.error_code, "RESERVATION_AUTHORITY_LOST")

        terminal_task = self.harness._admit()
        terminal_pools = _pools(1, 1)
        with patch.object(
            routes_dsl,
            "_persist_reservation_authoritative_terminal",
            side_effect=RuntimeError("controlled terminal failure"),
        ):
            terminal = self.harness._run_public(terminal_task, terminal_pools)
        terminal_row = self._row(terminal_task)
        self.assertEqual(
            terminal[0]["errorCode"],
            "RESERVATION_TERMINAL_PERSIST_FAILED",
        )
        self.assertTrue(terminal_row.terminal_persist_failed)
        self.assertEqual(
            terminal_row.error_code,
            "RESERVATION_TERMINAL_PERSIST_FAILED",
        )

    def test_worker_config_revalidation_failure_is_observed(self):
        task_id = self.harness._admit()
        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_dsl,
                "load_reservation_lease_configuration",
                return_value=ReservationLeaseConfiguration(),
            ),
            self.assertRaisesRegex(
                RuntimeError,
                "RESERVATION_LEASE_CONFIGURATION_REQUIRED",
            ),
        ):
            routes_dsl.render_batch_worker(
                _payload(_pools(1)),
                task_id,
                tenant_id="tenant-a",
                variant_planning_policy="exact_main_visual",
                reservation_conflict_mode="ENFORCE",
                public_task_admitted=True,
            )
        row = self._row(task_id)
        self.assertTrue(row.worker_lease_config_failed)
        self.assertEqual(row.terminal_status, "failed")
        self.assertEqual(
            row.error_code,
            "RESERVATION_LEASE_CONFIGURATION_REQUIRED",
        )
        with self.Session() as session:
            self.assertEqual(session.query(FingerprintReservation).count(), 0)

    def test_existing_controller_cleanup_warning_is_persisted(self):
        task_id = self.harness._admit()
        original_abort = PlannerReservationController.abort

        def abort_with_warning(controller):
            result = original_abort(controller)
            controller._warn_cleanup("CONTROLLED_TEST_WARNING")
            return result

        with patch.object(
            PlannerReservationController,
            "abort",
            new=abort_with_warning,
        ):
            terminal = self.harness._run_public(task_id, _pools(1))[0]
        row = self._row(task_id)
        self.assertEqual(terminal["status"], "completed")
        self.assertTrue(row.cleanup_warning)

    def test_diagnostic_write_failures_do_not_change_authority_or_payload(self):
        for stage in ("start", "planning", "terminal"):
            with self.subTest(stage=stage):
                task_id = self.harness._admit()
                target = {
                    "start": "best_effort_start_reservation_diagnostic",
                    "planning": "best_effort_record_reservation_planning",
                    "terminal": "best_effort_record_reservation_terminal",
                }[stage]
                with patch.object(
                    routes_dsl,
                    target,
                    side_effect=RuntimeError("diagnostic unavailable"),
                ):
                    terminal = self.harness._run_public(task_id, _pools(1))[0]
                self.assertEqual(terminal["status"], "completed")
                self.assertEqual(terminal["succeededCount"], 1)
                with self.Session() as session:
                    history = session.scalar(
                        select(TaskHistory).where(TaskHistory.task_id == task_id)
                    )
                    task = session.scalar(
                        select(VideoTask).where(VideoTask.task_id == task_id)
                    )
                self.assertIsNotNone(history)
                self.assertEqual(task.status, "completed")

    def test_diagnostic_observation_failures_do_not_change_authority_or_payload(self):
        for observation_type in (
            "ReservationPlanningObservation",
            "ReservationTerminalObservation",
        ):
            with self.subTest(observation_type=observation_type):
                task_id = self.harness._admit()
                with patch.object(
                    routes_dsl,
                    observation_type,
                    side_effect=RuntimeError("diagnostic observation unavailable"),
                ):
                    terminal = self.harness._run_public(task_id, _pools(1))[0]
                self.assertEqual(terminal["status"], "completed")
                self.assertEqual(terminal["succeededCount"], 1)
                with self.Session() as session:
                    history = session.scalar(
                        select(TaskHistory).where(TaskHistory.task_id == task_id)
                    )
                    task = session.scalar(
                        select(VideoTask).where(VideoTask.task_id == task_id)
                    )
                self.assertIsNotNone(history)
                self.assertEqual(task.status, "completed")

    def test_exception_string_failure_preserves_original_worker_exception(self):
        task_id = self.harness._admit()
        original = _UnstringablePlannerError("original worker exception")
        configuration = ReservationLeaseConfiguration(0.9, 0.15)

        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_dsl,
                "load_reservation_lease_configuration",
                return_value=configuration,
            ),
            patch.object(
                routes_dsl,
                "_render_batch_worker_impl",
                side_effect=original,
            ),
            self.assertRaises(_UnstringablePlannerError) as caught,
        ):
            routes_dsl.render_batch_worker(
                _payload(_pools(1)),
                task_id,
                tenant_id="tenant-a",
                variant_planning_policy="exact_main_visual",
                reservation_conflict_mode="ENFORCE",
                public_task_admitted=True,
            )

        self.assertIs(caught.exception, original)
        with self.Session() as session:
            task = session.scalar(
                select(VideoTask).where(VideoTask.task_id == task_id)
            )
            history = session.scalar(
                select(TaskHistory).where(TaskHistory.task_id == task_id)
            )
            reservation_count = session.query(FingerprintReservation).count()
        self.assertEqual(task.status, "failed")
        self.assertIsNone(history)
        self.assertEqual(reservation_count, 0)

    def test_cleanup_property_failure_isolated_in_terminal_and_fallback(self):
        normal_task = self.harness._admit()
        with patch.object(
            PlannerReservationController,
            "cleanup_warning",
            new_callable=PropertyMock,
            side_effect=RuntimeError("diagnostic cleanup property unavailable"),
        ):
            terminal = self.harness._run_public(normal_task, _pools(1))[0]

        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(terminal["succeededCount"], 1)
        with self.Session() as session:
            task = session.scalar(
                select(VideoTask).where(VideoTask.task_id == normal_task)
            )
            history = session.scalar(
                select(TaskHistory).where(TaskHistory.task_id == normal_task)
            )
            rows = session.scalars(
                select(ReservationRunDiagnostic).where(
                    ReservationRunDiagnostic.task_id == normal_task
                )
            ).all()
            reservation_count = session.query(FingerprintReservation).count()
        self.assertEqual(task.status, "completed")
        self.assertIsNotNone(history)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].planning_observed)
        self.assertIsNone(rows[0].terminal_status)
        self.assertEqual(reservation_count, 0)

        fallback_task = self.harness._admit()
        original = PlannerReservationError("original fallback exception")
        configuration = ReservationLeaseConfiguration(0.9, 0.15)
        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_dsl,
                "load_reservation_lease_configuration",
                return_value=configuration,
            ),
            patch.object(
                routes_dsl,
                "_render_batch_worker_impl",
                side_effect=original,
            ),
            patch.object(
                PlannerReservationController,
                "cleanup_warning",
                new_callable=PropertyMock,
                side_effect=RuntimeError("diagnostic cleanup property unavailable"),
            ),
            self.assertRaises(PlannerReservationError) as caught,
        ):
            routes_dsl.render_batch_worker(
                _payload(_pools(1)),
                fallback_task,
                tenant_id="tenant-a",
                variant_planning_policy="exact_main_visual",
                reservation_conflict_mode="ENFORCE",
                public_task_admitted=True,
            )

        self.assertIs(caught.exception, original)
        with self.Session() as session:
            task = session.scalar(
                select(VideoTask).where(VideoTask.task_id == fallback_task)
            )
            history = session.scalar(
                select(TaskHistory).where(TaskHistory.task_id == fallback_task)
            )
            reservation_count = session.query(FingerprintReservation).count()
        self.assertEqual(task.status, "failed")
        self.assertIsNone(history)
        self.assertEqual(reservation_count, 0)

    def test_cleanup_property_failure_preserves_authority_terminal_codes(self):
        scenarios = (
            (
                PlannerReservationAuthorityLost("controlled authority loss"),
                "RESERVATION_AUTHORITY_LOST",
            ),
            (
                RuntimeError("controlled terminal persistence failure"),
                "RESERVATION_TERMINAL_PERSIST_FAILED",
            ),
        )
        for failure, expected_error_code in scenarios:
            with self.subTest(expected_error_code=expected_error_code):
                task_id = self.harness._admit()
                with (
                    patch.object(
                        routes_dsl,
                        "_persist_reservation_authoritative_terminal",
                        side_effect=failure,
                    ),
                    patch.object(
                        PlannerReservationController,
                        "cleanup_warning",
                        new_callable=PropertyMock,
                        side_effect=RuntimeError(
                            "diagnostic cleanup property unavailable"
                        ),
                    ),
                ):
                    terminal = self.harness._run_public(task_id, _pools(1))[0]

                self.assertEqual(terminal["status"], "failed")
                self.assertEqual(terminal["errorCode"], expected_error_code)
                with self.Session() as session:
                    task = session.scalar(
                        select(VideoTask).where(VideoTask.task_id == task_id)
                    )
                    history = session.scalar(
                        select(TaskHistory).where(TaskHistory.task_id == task_id)
                    )
                    reservation_count = session.query(FingerprintReservation).count()
                self.assertEqual(task.status, "failed")
                self.assertIsNone(history)
                self.assertEqual(reservation_count, 0)

    def test_summary_empty_math_window_active_and_privacy(self):
        with self.Session() as session:
            empty = reservation_diagnostics_summary(session, window="24h")
        self.assertEqual(empty["enforceTaskCount"], 0)
        for name in (
            "conflictTaskRate",
            "zeroPlanConflictRate",
            "partialPlanRate",
            "authorityLossRate",
            "terminalPersistFailureRate",
        ):
            self.assertIsNone(empty[name])

        now = datetime.now(timezone.utc)
        with self.Session() as session:
            session.add_all(
                [
                    ReservationRunDiagnostic(
                        task_id=str(uuid.uuid4()), planning_policy="exact_main_visual",
                        requested_count=1, planning_observed=True, planned_count=1,
                        succeeded_count=1, failed_count=0, reservation_conflict_count=2,
                        had_reservation_conflict=True, terminal_status="completed",
                        started_at=now - timedelta(minutes=10), finished_at=now,
                    ),
                    ReservationRunDiagnostic(
                        task_id=str(uuid.uuid4()), planning_policy="exact_main_visual",
                        requested_count=1, planning_observed=True, planned_count=0,
                        succeeded_count=0, failed_count=0, reservation_conflict_count=1,
                        had_reservation_conflict=True, zero_plan_conflict=True,
                        terminal_status="failed", started_at=now - timedelta(minutes=20),
                        finished_at=now, error_code="RESERVATION_CONFLICT_EXHAUSTED",
                    ),
                    ReservationRunDiagnostic(
                        task_id=str(uuid.uuid4()), planning_policy="exact_main_visual_balanced",
                        requested_count=2, planning_observed=True, planned_count=1,
                        succeeded_count=0, failed_count=1, partial_plan=True,
                        authority_lost=True, terminal_status="failed",
                        started_at=now - timedelta(minutes=30), finished_at=now,
                        error_code="RESERVATION_AUTHORITY_LOST",
                    ),
                    ReservationRunDiagnostic(
                        task_id=str(uuid.uuid4()), planning_policy="exact_main_visual",
                        requested_count=1, planning_observed=False,
                        worker_lease_config_failed=True, terminal_persist_failed=True,
                        cleanup_warning=True, terminal_status="failed",
                        started_at=now - timedelta(minutes=40), finished_at=now,
                    ),
                    ReservationRunDiagnostic(
                        task_id=str(uuid.uuid4()), planning_policy="exact_main_visual",
                        requested_count=1, planning_observed=False,
                        terminal_status=None, started_at=now - timedelta(minutes=50),
                    ),
                    ReservationRunDiagnostic(
                        task_id=str(uuid.uuid4()), planning_policy="exact_main_visual",
                        requested_count=1, planning_observed=True, planned_count=1,
                        terminal_status="completed", started_at=now - timedelta(days=2),
                        finished_at=now,
                    ),
                ]
            )
            session.commit()

        with self.Session() as session:
            summary = reservation_diagnostics_summary(
                session,
                window="24h",
                now=now,
            )
        self.assertEqual(summary["enforceTaskCount"], 5)
        self.assertEqual(summary["planningObservedTaskCount"], 3)
        self.assertEqual(summary["activeTaskCount"], 1)
        self.assertEqual(summary["completedTaskCount"], 1)
        self.assertEqual(summary["failedTaskCount"], 3)
        self.assertEqual(summary["conflictTaskCount"], 2)
        self.assertEqual(summary["reservationConflictCount"], 3)
        self.assertEqual(summary["conflictTaskRate"], 2 / 3)
        self.assertEqual(summary["zeroPlanConflictRate"], 1 / 3)
        self.assertEqual(summary["partialPlanRate"], 1 / 3)
        self.assertEqual(summary["authorityLossRate"], 1 / 5)
        self.assertEqual(summary["terminalPersistFailureRate"], 1 / 5)
        self.assertEqual(summary["workerLeaseConfigFailureCount"], 1)
        self.assertEqual(summary["cleanupWarningCount"], 1)

        with self.Session() as session:
            response = get_reservation_diagnostics_summary(window="24h", db=session)
        serialized = response.model_dump(by_alias=True, mode="json")
        self.assertEqual(serialized["window"], "24h")
        forbidden = (
            "task_id", "owner", "execution", "fingerprint", "prompt",
            "sqlite", "sql", "expires_at", "lease_timestamp",
        )
        lowered = json.dumps(serialized).lower()
        for token in forbidden:
            self.assertNotIn(token, lowered)

    def test_tenant_isolation_and_persistence_across_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = [Path(temporary) / "a.db", Path(temporary) / "b.db"]
            engines = [
                create_engine(
                    f"sqlite:///{path.as_posix()}",
                    connect_args={"check_same_thread": False},
                )
                for path in paths
            ]
            for engine in engines:
                initialize_application_schema(engine)
            task_a = str(uuid.uuid4())
            task_b = str(uuid.uuid4())
            best_effort_start_reservation_diagnostic(
                engines[0], task_id=task_a,
                planning_policy="exact_main_visual", requested_count=1,
            )
            best_effort_start_reservation_diagnostic(
                engines[1], task_id=task_b,
                planning_policy="exact_main_visual", requested_count=1,
            )
            for engine, expected in zip(engines, (task_a, task_b)):
                SessionLocal = sessionmaker(bind=engine)
                with SessionLocal() as session:
                    rows = session.scalars(select(ReservationRunDiagnostic)).all()
                self.assertEqual([row.task_id for row in rows], [expected])

            engines[0].dispose()
            reopened = create_engine(
                f"sqlite:///{paths[0].as_posix()}",
                connect_args={"check_same_thread": False},
            )
            initialize_application_schema(reopened)
            ReopenedSession = sessionmaker(bind=reopened)
            with ReopenedSession() as session:
                summary = reservation_diagnostics_summary(session)
                self.assertEqual(summary["enforceTaskCount"], 1)
            reopened.dispose()
            engines[1].dispose()

    def test_schema_is_additive_and_ledger_version_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = create_engine(
                f"sqlite:///{(Path(temporary) / 'existing.db').as_posix()}"
            )
            VideoTask.__table__.create(engine)
            initialize_application_schema(engine)
            self.assertIn("reservation_run_diagnostics", inspect(engine).get_table_names())
            ensure_fingerprint_ledger_schema(engine)
            from src.api.fingerprint_ledger import LEDGER_SCHEMA_VERSION

            self.assertEqual(LEDGER_SCHEMA_VERSION, 2)
            engine.dispose()

    def test_structured_events_are_allowlisted_machine_readable(self):
        with patch.object(reservation_diagnostics.logger, "info") as logged:
            reservation_diagnostics.emit_reservation_diagnostic_event(
                "PUBLIC_ENFORCE_TERMINAL",
                task_id="public-task",
                planning_policy="exact_main_visual",
                requested_count=1,
                terminal_status="completed",
                owner_attempt_id="forbidden-owner",
                execution_id="forbidden-execution",
                fingerprint_digest="forbidden-fingerprint",
                prompt="forbidden-prompt",
                raw_exception="forbidden-error",
            )
        self.assertEqual(logged.call_count, 1)
        payload = json.loads(logged.call_args.args[1])
        self.assertEqual(payload["event"], "PUBLIC_ENFORCE_TERMINAL")
        self.assertEqual(payload["task_id"], "public-task")
        self.assertNotIn("owner_attempt_id", payload)
        self.assertNotIn("execution_id", payload)
        self.assertNotIn("fingerprint_digest", payload)
        self.assertNotIn("prompt", payload)
        self.assertNotIn("raw_exception", payload)

    def test_idempotent_stage_updates_keep_one_row(self):
        task_id = str(uuid.uuid4())
        for _ in range(2):
            best_effort_start_reservation_diagnostic(
                self.engine,
                task_id=task_id,
                planning_policy="exact_main_visual",
                requested_count=2,
            )
            best_effort_record_reservation_planning(
                self.engine,
                task_id=task_id,
                observation=ReservationPlanningObservation(
                    planning_policy="exact_main_visual",
                    requested_count=2,
                    planned_count=1,
                    reservation_conflict_count=1,
                    termination_reason="RESERVATION_CONFLICT_EXHAUSTED",
                ),
            )
            best_effort_record_reservation_terminal(
                self.engine,
                task_id=task_id,
                observation=ReservationTerminalObservation(
                    planning_policy="exact_main_visual",
                    requested_count=2,
                    succeeded_count=1,
                    failed_count=0,
                    terminal_status="completed",
                    error_code=None,
                ),
            )
        with self.Session() as session:
            rows = session.scalars(
                select(ReservationRunDiagnostic).where(
                    ReservationRunDiagnostic.task_id == task_id
                )
            ).all()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].partial_plan)

    def test_summary_query_failure_is_safe(self):
        db = Mock()
        with (
            patch(
                "src.api.routes_reservation_diagnostics.reservation_diagnostics_summary",
                side_effect=RuntimeError("database path and SQL must stay private"),
            ),
            self.assertRaises(HTTPException) as caught,
        ):
            get_reservation_diagnostics_summary(window="24h", db=db)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(
            caught.exception.detail,
            "RESERVATION_DIAGNOSTICS_UNAVAILABLE",
        )


if __name__ == "__main__":
    unittest.main()
