import os
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from src.api import routes_dsl
from src.api.fingerprint_ledger import (
    FingerprintLedgerRepository,
    FingerprintOccurrence,
    FingerprintOccurrenceRecord,
    FingerprintReservation,
    ReservationAcquireStatus,
    ensure_fingerprint_ledger_schema,
)
from src.api.models import Base, TaskHistory, VideoTask
from src.api.planner_reservation import (
    PlannerReservationController,
    PlannerReservationError,
)
from src.api.public_task_admission import admit_public_task
from src.api.reservation_lease import ReservationLeaseConfiguration
from src.api.schemas import DSLBeatNode, RenderDSLRequest
from tests.test_var001_balanced_axis_coverage import (
    _SyntheticParser,
    _payload,
    _plan_for_selections,
    _pools,
)


_LEASE_ENV = {
    "RESERVATION_LEASE_TTL_SECONDS": "0.9",
    "RESERVATION_HEARTBEAT_INTERVAL_SECONDS": "0.15",
}


def _request(**overrides):
    values = {
        "engine_type": "content",
        "timeline": [
            DSLBeatNode(
                beat="Hook",
                role="hook",
                address_mode="locked",
                asset_hashes=["asset-hash"],
            )
        ],
        "prompt": "public Reservation activation",
        "variant_planning_policy": "exact_main_visual",
    }
    values.update(overrides)
    return RenderDSLRequest(**values)


class _Background:
    def __init__(self):
        self.tasks = []

    def add_task(self, function, *args, **kwargs):
        self.tasks.append(SimpleNamespace(func=function, args=args, kwargs=kwargs))


class PublicReservationActivationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.engines = []
        self.engine, self.Session = self._database("tenant-a.db")

    def tearDown(self):
        for engine in reversed(self.engines):
            engine.dispose()
        self.temporary.cleanup()

    def _database(self, name):
        path = Path(self.temporary.name) / name
        engine = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        ensure_fingerprint_ledger_schema(engine)
        Base.metadata.create_all(engine)
        self.engines.append(engine)
        return engine, sessionmaker(bind=engine, expire_on_commit=False)

    def _admit(self, *, batch_size=1):
        return admit_public_task(
            self.engine,
            prompt="public Reservation activation",
            batch_size=batch_size,
        ).task_id

    @staticmethod
    def _identity_for_pools(pools):
        payload = _payload(pools)
        plan = _plan_for_selections(payload, tuple(pool[0] for pool in pools))
        fingerprint = routes_dsl._exact_main_visual_fingerprint(plan)
        return routes_dsl._main_visual_fingerprint_identity_record(fingerprint)

    @staticmethod
    def _success(plan, _task_id, *args, file_sid=None, **kwargs):
        resolved_sid = file_sid or args[-1]
        return routes_dsl._ChildResult(
            child_index=kwargs["child_index"],
            execution_id=kwargs["execution_id"],
            file_sid=resolved_sid,
            outcome="succeeded",
            assets=[{"file_path": f"output/{resolved_sid}.mp4"}],
            elapsed=0.01,
            error_code=None,
            error_message=None,
            prompt_details={"meta": None, "timeline": []},
            fatigue_asset_ids=(),
        )

    def _run_public(
        self,
        task_id,
        pools,
        *,
        batch_size=1,
        policy="exact_main_visual",
        historical_mode="OFF",
        child=None,
        engine=None,
        Session=None,
        lease_env=None,
        retain_reservation=False,
        terminal_record_hook=None,
    ):
        tenant_engine = engine or self.engine
        tenant_session = Session or self.Session
        payload = _payload(pools)
        controllers = []
        planning_results = []
        broadcasts = []
        original_controller = PlannerReservationController
        original_record_records = routes_dsl._record_fingerprint_ledger_records

        def construct_controller(**kwargs):
            controller = original_controller(**kwargs)
            if retain_reservation:
                controller.abort = lambda: controller.tracker.stop(
                    join_timeout_seconds=2.0
                )
            controllers.append(controller)
            return controller

        def record_records(session, records):
            original_record_records(session, records)
            if terminal_record_hook is not None:
                terminal_record_hook(session, records)

        def plan_exact(_tenant_id, dsl_payload, requested_count, **kwargs):
            observer = routes_dsl._historical_novelty_observer(
                tenant_session,
                kwargs.get("historical_novelty_mode", "OFF"),
            )
            result = routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools),
                dsl_payload,
                requested_count,
                preview_plan=kwargs.get("preview_plan"),
                historical_observer=observer,
                preview_intent=kwargs.get(
                    "preview_intent", routes_dsl.PreviewIntent.UNSPECIFIED
                ),
                reservation_controller=kwargs["reservation_controller"],
            )
            planning_results.append(result)
            return result

        def plan_balanced(_tenant_id, dsl_payload, requested_count, **kwargs):
            observer = routes_dsl._historical_novelty_observer(
                tenant_session,
                kwargs.get("historical_novelty_mode", "OFF"),
            )
            result = routes_dsl._plan_exact_main_visual_balanced_variants(
                _SyntheticParser(pools),
                dsl_payload,
                requested_count,
                preview_plan=kwargs.get("preview_plan"),
                historical_observer=observer,
                preview_intent=kwargs.get(
                    "preview_intent", routes_dsl.PreviewIntent.UNSPECIFIED
                ),
                reservation_controller=kwargs["reservation_controller"],
            )
            planning_results.append(result)
            return result

        environment = dict(_LEASE_ENV if lease_env is None else lease_env)
        with (
            patch.dict(os.environ, environment, clear=False),
            patch.object(routes_dsl, "get_tenant_engine", return_value=tenant_engine),
            patch.object(
                routes_dsl,
                "PlannerReservationController",
                side_effect=construct_controller,
            ),
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_variants_from_db",
                side_effect=plan_exact,
            ),
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_balanced_variants_from_db",
                side_effect=plan_balanced,
            ),
            patch.object(
                routes_dsl,
                "render_worker",
                side_effect=child or self._success,
            ),
            patch.object(
                routes_dsl,
                "_record_fingerprint_ledger_records",
                side_effect=record_records,
            ),
            patch.object(
                routes_dsl.ws_manager,
                "broadcast_sync",
                side_effect=lambda payload, **_kwargs: broadcasts.append(payload),
            ),
        ):
            terminal = routes_dsl.render_batch_worker(
                payload,
                task_id,
                tenant_id="tenant-authoritative",
                batch_size=batch_size,
                variant_planning_policy=policy,
                historical_novelty_mode=historical_mode,
                reservation_conflict_mode="ENFORCE",
                public_task_admitted=True,
            )
        return terminal, controllers, planning_results, broadcasts

    def test_request_default_and_explicit_off_are_the_same_policy(self):
        self.assertEqual(_request().reservation_conflict_mode, "OFF")
        self.assertEqual(
            _request(reservation_conflict_mode="OFF").model_dump(),
            _request().model_dump(),
        )

    def test_invalid_public_modes_are_rejected(self):
        for mode in ("OBSERVE", "ADVISORY", "UNKNOWN"):
            with self.subTest(mode=mode), self.assertRaises(ValidationError):
                _request(reservation_conflict_mode=mode)

    def test_client_authority_and_timing_fields_are_explicitly_rejected(self):
        for field in (
            "owner_attempt_id",
            "reservation_owner_attempt_id",
            "owner_task_id",
            "execution_id",
            "reservation_lease_ttl_seconds",
            "reservation_heartbeat_interval_seconds",
        ):
            with self.subTest(field=field), self.assertRaisesRegex(
                ValidationError, "CLIENT_RESERVATION_AUTHORITY_NOT_ALLOWED"
            ):
                _request(**{field: "client-controlled"})

    def test_legacy_enforce_rejected_before_admission(self):
        payload = _request(
            variant_planning_policy="legacy",
            reservation_conflict_mode="ENFORCE",
        )
        with self.assertRaises(HTTPException) as caught:
            routes_dsl._preflight_public_reservation_policy(payload)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(
            caught.exception.detail,
            "RESERVATION_ENFORCE_UNSUPPORTED_FOR_LEGACY",
        )

    def test_enforce_without_configuration_rejected_before_admission(self):
        payload = _request(reservation_conflict_mode="ENFORCE")
        with (
            patch.object(
                routes_dsl,
                "load_reservation_lease_configuration",
                return_value=ReservationLeaseConfiguration(),
            ),
            self.assertRaises(HTTPException) as caught,
        ):
            routes_dsl._preflight_public_reservation_policy(payload)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(
            caught.exception.detail,
            "RESERVATION_LEASE_CONFIGURATION_REQUIRED",
        )

    def test_submit_route_passes_only_normalized_policy_after_preflight(self):
        payload = _request(reservation_conflict_mode="ENFORCE")
        background = _Background()
        db = Mock()
        db.get_bind.return_value = self.engine
        with (
            patch.object(
                routes_dsl,
                "load_reservation_lease_configuration",
                return_value=ReservationLeaseConfiguration(30, 10),
            ),
            patch.object(routes_dsl.DSLParserNode, "parse_and_resolve") as parse,
            patch.object(routes_dsl, "_admit_dsl_public_task", return_value=str(uuid.uuid4())),
        ):
            pools = _pools(1)
            parse.return_value = routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools), _payload(pools), 1
            ).plans[0]
            routes_dsl.submit_dsl(payload, background, db=db, request=None)
        self.assertEqual(len(background.tasks), 1)
        kwargs = background.tasks[0].kwargs
        self.assertEqual(kwargs["reservation_conflict_mode"], "ENFORCE")
        self.assertNotIn("reservation_controller", kwargs)
        self.assertNotIn("reservation_owner_attempt_id", kwargs)

    def test_off_without_configuration_constructs_no_reservation_authority(self):
        task_id = self._admit()
        default_task_id = self._admit()
        callback_seen = []

        def implementation(*args, **kwargs):
            kwargs["_terminal_target_callback"]("completed")
            callback_seen.append(True)
            return {"taskId": args[1], "status": "completed"}

        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_dsl,
                "load_reservation_lease_configuration",
                side_effect=AssertionError("OFF must not load lease configuration"),
            ),
            patch.object(
                routes_dsl,
                "PlannerReservationController",
                side_effect=AssertionError("OFF must not construct a controller"),
            ),
            patch.object(
                routes_dsl,
                "_render_batch_worker_impl",
                side_effect=implementation,
            ),
        ):
            terminal = routes_dsl.render_batch_worker(
                None,
                task_id,
                tenant_id="tenant-authoritative",
                reservation_conflict_mode="OFF",
                public_task_admitted=True,
            )
            default_terminal = routes_dsl.render_batch_worker(
                None,
                default_task_id,
                tenant_id="tenant-authoritative",
                public_task_admitted=True,
            )
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(default_terminal["status"], terminal["status"])
        self.assertEqual(callback_seen, [True, True])
        with self.Session() as db:
            statuses = set(db.scalars(select(VideoTask.status)).all())
            self.assertEqual(statuses, {"completed"})
            self.assertEqual(db.query(FingerprintReservation).count(), 0)

    def test_worker_revalidation_failure_terminalizes_admitted_task(self):
        task_id = self._admit()
        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_dsl,
                "load_reservation_lease_configuration",
                return_value=ReservationLeaseConfiguration(),
            ),
            patch.object(
                routes_dsl,
                "_render_batch_worker_impl",
                side_effect=AssertionError("creative work must not start"),
            ),
            self.assertRaisesRegex(
                PlannerReservationError,
                "RESERVATION_LEASE_CONFIGURATION_REQUIRED",
            ),
        ):
            routes_dsl.render_batch_worker(
                _payload(_pools(1)),
                task_id,
                tenant_id="tenant-authoritative",
                variant_planning_policy="exact_main_visual",
                reservation_conflict_mode="ENFORCE",
                public_task_admitted=True,
            )
        with self.Session() as db:
            self.assertEqual(db.scalar(select(VideoTask.status)), "failed")
            self.assertEqual(db.query(FingerprintReservation).count(), 0)

    def test_internal_controller_and_public_enforce_are_ambiguous(self):
        task_id = self._admit()
        controller = PlannerReservationController(
            logical_task_id=task_id,
            session_factory=self.Session,
            configuration=ReservationLeaseConfiguration(30, 10),
        )
        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            self.assertRaisesRegex(
                PlannerReservationError,
                "AMBIGUOUS_RESERVATION_CONTROLLER_OWNERSHIP",
            ),
        ):
            routes_dsl.render_batch_worker(
                _payload(_pools(1)),
                task_id,
                tenant_id="tenant-authoritative",
                variant_planning_policy="exact_main_visual",
                reservation_conflict_mode="ENFORCE",
                reservation_controller=controller,
                public_task_admitted=True,
            )
        controller.abort()
        with self.Session() as db:
            self.assertEqual(db.scalar(select(VideoTask.status)), "failed")

    def test_exact_enforce_runs_full_protocol_and_separates_identities(self):
        task_id = self._admit()
        terminal, controllers, results, broadcasts = self._run_public(
            task_id, _pools(2)
        )
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(len(controllers), 1)
        self.assertEqual(len(results[0].reservation_bindings), 1)
        attempt_id = results[0].reservation_bindings[0].owner_attempt_id
        with self.Session() as db:
            events = db.scalars(
                select(FingerprintOccurrence)
                .where(FingerprintOccurrence.task_id == task_id)
                .order_by(FingerprintOccurrence.id)
            ).all()
            history = db.scalar(
                select(TaskHistory).where(TaskHistory.task_id == task_id)
            )
            task = db.scalar(select(VideoTask).where(VideoTask.task_id == task_id))
            self.assertEqual(db.query(FingerprintReservation).count(), 0)
        self.assertEqual([event.lifecycle_event for event in events], ["PLANNED", "RENDERED"])
        execution_id = events[0].execution_id
        self.assertEqual(events[1].execution_id, execution_id)
        self.assertEqual(history.task_id, task_id)
        self.assertEqual(task.status, "completed")
        self.assertNotEqual(task_id, attempt_id)
        self.assertNotEqual(task_id, execution_id)
        self.assertNotEqual(attempt_id, execution_id)
        self.assertEqual(len(broadcasts), 1)
        public_text = repr(broadcasts[0]) + repr(terminal)
        self.assertIn(task_id, public_text)
        self.assertNotIn(attempt_id, public_text)

    def test_balanced_enforce_runs_full_protocol(self):
        task_id = self._admit(batch_size=2)
        terminal, controllers, results, _broadcasts = self._run_public(
            task_id,
            _pools(3),
            batch_size=2,
            policy="exact_main_visual_balanced",
        )
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(terminal["succeededCount"], 2)
        self.assertEqual(len(controllers), 1)
        self.assertEqual(len(results[0].reservation_bindings), 2)
        self.assertIsNotNone(results[0].coverage_diagnostics)
        with self.Session() as db:
            self.assertEqual(
                db.query(FingerprintOccurrence)
                .filter(FingerprintOccurrence.task_id == task_id)
                .count(),
                4,
            )

    def test_concurrent_public_tasks_diversify(self):
        task_a = self._admit()
        task_b = self._admit()
        first_child_started = threading.Event()
        release_first = threading.Event()
        child_lock = threading.Lock()
        child_calls = 0
        records = {}

        def child(*args, **kwargs):
            nonlocal child_calls
            with child_lock:
                child_calls += 1
                call = child_calls
            if call == 1:
                first_child_started.set()
                self.assertTrue(release_first.wait(timeout=8))
            return self._success(*args, **kwargs)

        def run(label, task_id):
            records[label] = self._run_public(
                task_id, _pools(2), child=child
            )

        thread_a = threading.Thread(target=run, args=("a", task_a))
        thread_a.start()
        self.assertTrue(first_child_started.wait(timeout=8))
        thread_b = threading.Thread(target=run, args=("b", task_b))
        thread_b.start()
        thread_b.join(timeout=10)
        release_first.set()
        thread_a.join(timeout=10)
        self.assertFalse(thread_a.is_alive())
        self.assertFalse(thread_b.is_alive())
        self.assertEqual(records["a"][0]["status"], "completed")
        self.assertEqual(records["b"][0]["status"], "completed")
        fingerprints = {
            records[label][2][0].fingerprints[0] for label in ("a", "b")
        }
        self.assertEqual(len(fingerprints), 2)
        attempts = {
            records[label][2][0].reservation_bindings[0].owner_attempt_id
            for label in ("a", "b")
        }
        self.assertEqual(len(attempts), 2)

    def test_single_candidate_conflict_is_safe_public_failure(self):
        task_a = self._admit()
        task_b = self._admit()
        first_child_started = threading.Event()
        release_first = threading.Event()
        first_record = {}

        def child(*args, **kwargs):
            first_child_started.set()
            self.assertTrue(release_first.wait(timeout=8))
            return self._success(*args, **kwargs)

        thread = threading.Thread(
            target=lambda: first_record.setdefault(
                "run", self._run_public(task_a, _pools(1), child=child)
            )
        )
        thread.start()
        self.assertTrue(first_child_started.wait(timeout=8))
        losing = self._run_public(task_b, _pools(1))
        release_first.set()
        thread.join(timeout=10)
        self.assertEqual(losing[0]["status"], "failed")
        self.assertEqual(losing[0]["errorCode"], "RESERVATION_CONFLICT_EXHAUSTED")
        self.assertNotIn("assets", losing[0])
        self.assertEqual(losing[2][0].plans, ())
        with self.Session() as db:
            self.assertIsNone(
                db.scalar(select(TaskHistory).where(TaskHistory.task_id == task_b))
            )
            self.assertEqual(
                db.scalar(select(VideoTask.status).where(VideoTask.task_id == task_b)),
                "failed",
            )

    def test_partial_public_plan_preserves_authoritative_subset(self):
        task_a = self._admit()
        task_b = self._admit(batch_size=2)
        first_child_started = threading.Event()
        release_first = threading.Event()

        def child(*args, **kwargs):
            first_child_started.set()
            self.assertTrue(release_first.wait(timeout=8))
            return self._success(*args, **kwargs)

        thread = threading.Thread(
            target=lambda: self._run_public(task_a, _pools(1), child=child)
        )
        thread.start()
        self.assertTrue(first_child_started.wait(timeout=8))
        partial = self._run_public(task_b, _pools(2), batch_size=2)
        release_first.set()
        thread.join(timeout=10)
        self.assertEqual(partial[0]["status"], "completed")
        self.assertTrue(partial[0]["partial"])
        self.assertEqual(partial[0]["plannedCount"], 1)
        self.assertEqual(partial[0]["succeededCount"], 1)
        self.assertEqual(len(partial[2][0].reservation_bindings), 1)

    def test_partial_public_plan_all_children_failed_preserves_render_causality(self):
        task_a = self._admit()
        task_b = self._admit(batch_size=2)
        first_child_started = threading.Event()
        release_first = threading.Event()

        def held_success(*args, **kwargs):
            first_child_started.set()
            self.assertTrue(release_first.wait(timeout=8))
            return self._success(*args, **kwargs)

        def failed_child(_plan, _task_id, *args, file_sid=None, **kwargs):
            resolved_sid = file_sid or args[-1]
            return routes_dsl._ChildResult(
                child_index=kwargs["child_index"],
                execution_id=kwargs["execution_id"],
                file_sid=resolved_sid,
                outcome="failed",
                assets=[],
                elapsed=0.01,
                error_code="RENDER_FAILED",
                error_message="expected render failure",
                prompt_details={"meta": None, "timeline": []},
                fatigue_asset_ids=(),
            )

        thread = threading.Thread(
            target=lambda: self._run_public(
                task_a,
                _pools(1),
                child=held_success,
            )
        )
        thread.start()
        self.assertTrue(first_child_started.wait(timeout=8))
        failed = self._run_public(
            task_b,
            _pools(2),
            batch_size=2,
            child=failed_child,
        )
        release_first.set()
        thread.join(timeout=10)

        terminal = failed[0]
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["plannedCount"], 1)
        self.assertEqual(terminal["succeededCount"], 0)
        self.assertEqual(terminal["failedCount"], 1)
        self.assertFalse(terminal["partial"])
        self.assertIn(
            "RESERVATION_CONFLICT_EXHAUSTED",
            terminal["warningCodes"],
        )
        self.assertIn("CHILD_EXECUTION_FAILED", terminal["warningCodes"])
        self.assertNotEqual(
            terminal.get("errorCode"),
            "RESERVATION_CONFLICT_EXHAUSTED",
        )
        self.assertNotIn("assets", terminal)
        self.assertEqual(
            failed[2][0].termination_reason,
            "RESERVATION_CONFLICT_EXHAUSTED",
        )
        with self.Session() as db:
            self.assertIsNone(
                db.scalar(
                    select(TaskHistory).where(TaskHistory.task_id == task_b)
                )
            )
            self.assertEqual(
                db.scalar(
                    select(VideoTask.status).where(VideoTask.task_id == task_b)
                ),
                "failed",
            )

    def test_advisory_history_does_not_reject_without_active_conflict(self):
        pools = _pools(1)
        payload = _payload(pools)
        fingerprint = routes_dsl._exact_main_visual_fingerprint(
            _SyntheticParser(pools).materialize_with_main_selections(
                payload, (pools[0][0],)
            )
        )
        identity = routes_dsl._main_visual_fingerprint_identity_record(fingerprint)
        record = FingerprintOccurrenceRecord(
            **identity.__dict__,
            task_id="historical-task",
            execution_id="historical-execution",
            child_index=0,
            lifecycle_event="RENDERED",
            provenance="test_public_advisory",
        )
        with self.Session() as db:
            FingerprintLedgerRepository(db).record_occurrence(record)
            db.commit()
        task_id = self._admit()
        terminal, _controllers, results, _broadcasts = self._run_public(
            task_id,
            pools,
            historical_mode="ADVISORY",
        )
        self.assertEqual(terminal["status"], "completed")
        diagnostics = results[0].historical_novelty_diagnostics
        self.assertEqual(diagnostics.rendered_matches, 1)
        self.assertEqual(diagnostics.advisory_count, 1)
        self.assertEqual(diagnostics.historical_rejection_count, 0)

    def test_historical_evidence_does_not_override_active_reservation_conflict(self):
        pools = _pools(2)
        identity_x = self._identity_for_pools([[pools[0][0]]])
        rendered = FingerprintOccurrenceRecord(
            **identity_x.__dict__,
            task_id="historical-task",
            execution_id="historical-rendered-x",
            child_index=0,
            lifecycle_event="RENDERED",
            provenance="test_public_advisory_conflict",
        )
        with self.Session() as db:
            repository = FingerprintLedgerRepository(db)
            repository.record_occurrence(rendered)
            acquired = repository.acquire_reservation(
                identity_x,
                owner_task_id=str(uuid.uuid4()),
                owner_slot_index=0,
                now=datetime.now(timezone.utc).replace(tzinfo=None),
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(seconds=30),
            )
            db.commit()
        self.assertEqual(acquired.status, ReservationAcquireStatus.ACQUIRED)
        task_id = self._admit()
        terminal, _controllers, results, _broadcasts = self._run_public(
            task_id,
            pools,
            historical_mode="ADVISORY",
        )
        self.assertEqual(terminal["status"], "completed")
        self.assertNotEqual(
            results[0].fingerprints[0],
            routes_dsl._exact_main_visual_fingerprint(
                _plan_for_selections(_payload(pools), (pools[0][0],))
            ),
        )
        diagnostics = results[0].historical_novelty_diagnostics
        self.assertEqual(diagnostics.advisory_count, 1)
        self.assertEqual(diagnostics.reservation_conflict_count, 1)
        self.assertEqual(diagnostics.historical_rejection_count, 0)

    def test_authority_loss_discards_public_asset_and_creative_truth(self):
        pools = _pools(1)
        task_id = self._admit()
        identity_record = self._identity_for_pools(pools)

        def stale_child(*args, **kwargs):
            with self.Session() as db:
                reservation = db.scalar(select(FingerprintReservation))
                db.execute(
                    update(FingerprintReservation)
                    .where(
                        FingerprintReservation.fingerprint_identity_id
                        == reservation.fingerprint_identity_id
                    )
                    .values(expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1))
                )
                db.commit()
                takeover = FingerprintLedgerRepository(db).acquire_reservation(
                    identity_record,
                    owner_task_id=str(uuid.uuid4()),
                    owner_slot_index=0,
                    now=datetime.now(timezone.utc).replace(tzinfo=None),
                    expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=30),
                )
                db.commit()
                self.assertEqual(takeover.status, ReservationAcquireStatus.ACQUIRED)
            return self._success(*args, **kwargs)

        terminal, _controllers, _results, _broadcasts = self._run_public(
            task_id, pools, child=stale_child
        )
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["errorCode"], "RESERVATION_AUTHORITY_LOST")
        self.assertNotIn("assets", terminal)
        with self.Session() as db:
            self.assertIsNone(
                db.scalar(select(TaskHistory).where(TaskHistory.task_id == task_id))
            )
            terminal_events = db.scalars(
                select(FingerprintOccurrence).where(
                    FingerprintOccurrence.task_id == task_id,
                    FingerprintOccurrence.lifecycle_event.in_(["RENDERED", "FAILED"]),
                )
            ).all()
            self.assertEqual(terminal_events, [])

    def test_public_terminal_writer_failure_rolls_back_renewal_and_truth(self):
        task_id = self._admit()
        before_expiry = []
        attempted_expiry = []

        def child(*args, **kwargs):
            with self.Session() as db:
                before_expiry.append(
                    db.scalar(select(FingerprintReservation.expires_at))
                )
            return self._success(*args, **kwargs)

        def fail_terminal_writer(session, _records):
            attempted_expiry.append(
                session.scalar(select(FingerprintReservation.expires_at))
            )
            session.add(
                TaskHistory(
                    task_id=None,
                    prompt="invalid terminal writer",
                    batch_size=1,
                    duration=0.0,
                    output_assets=[],
                )
            )
            session.flush()

        terminal, _controllers, _results, _broadcasts = self._run_public(
            task_id,
            _pools(1),
            child=child,
            lease_env={
                "RESERVATION_LEASE_TTL_SECONDS": "30",
                "RESERVATION_HEARTBEAT_INTERVAL_SECONDS": "10",
            },
            retain_reservation=True,
            terminal_record_hook=fail_terminal_writer,
        )
        with self.Session() as db:
            final_expiry = db.scalar(select(FingerprintReservation.expires_at))
            terminal_events = db.scalars(
                select(FingerprintOccurrence).where(
                    FingerprintOccurrence.task_id == task_id,
                    FingerprintOccurrence.lifecycle_event.in_(["RENDERED", "FAILED"]),
                )
            ).all()
            history = db.scalar(
                select(TaskHistory).where(TaskHistory.task_id == task_id)
            )
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(
            terminal["errorCode"], "RESERVATION_TERMINAL_PERSIST_FAILED"
        )
        self.assertEqual(len(before_expiry), 1)
        self.assertEqual(len(attempted_expiry), 1)
        self.assertGreater(attempted_expiry[0], before_expiry[0])
        self.assertEqual(final_expiry, before_expiry[0])
        self.assertEqual(terminal_events, [])
        self.assertIsNone(history)

    def test_long_public_child_heartbeat_blocks_takeover(self):
        task_id = self._admit()
        takeover_status = []
        pools = _pools(1)
        identity_record = self._identity_for_pools(pools)

        def long_child(*args, **kwargs):
            time.sleep(0.55)
            with self.Session() as db:
                reservation = db.scalar(select(FingerprintReservation))
                outcome = FingerprintLedgerRepository(db).acquire_reservation(
                    identity_record,
                    owner_task_id=str(uuid.uuid4()),
                    owner_slot_index=0,
                    now=datetime.now(timezone.utc).replace(tzinfo=None),
                    expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=30),
                )
                db.commit()
                takeover_status.append(outcome.status)
            return self._success(*args, **kwargs)

        terminal, _controllers, _results, _broadcasts = self._run_public(
            task_id,
            pools,
            child=long_child,
            lease_env={
                "RESERVATION_LEASE_TTL_SECONDS": "0.36",
                "RESERVATION_HEARTBEAT_INTERVAL_SECONDS": "0.08",
            },
        )
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(takeover_status, [ReservationAcquireStatus.CONFLICT])

    def test_tenant_databases_do_not_cross_conflict(self):
        engine_b, SessionB = self._database("tenant-b.db")
        task_a = self._admit()
        task_b = admit_public_task(
            engine_b, prompt="tenant b", batch_size=1
        ).task_id
        hold_a = threading.Event()
        release_a = threading.Event()

        def child_a(*args, **kwargs):
            hold_a.set()
            self.assertTrue(release_a.wait(timeout=8))
            return self._success(*args, **kwargs)

        holder = {}
        thread = threading.Thread(
            target=lambda: holder.setdefault(
                "a", self._run_public(task_a, _pools(1), child=child_a)
            )
        )
        thread.start()
        self.assertTrue(hold_a.wait(timeout=8))
        run_b = self._run_public(
            task_b,
            _pools(1),
            engine=engine_b,
            Session=SessionB,
        )
        release_a.set()
        thread.join(timeout=10)
        self.assertEqual(run_b[0]["status"], "completed")
        self.assertEqual(holder["a"][0]["status"], "completed")
        self.assertEqual(run_b[2][0].termination_reason, "REQUEST_SATISFIED")


if __name__ == "__main__":
    unittest.main()
