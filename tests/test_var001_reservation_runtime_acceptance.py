import concurrent.futures
import sqlite3
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from src.api import routes_dsl
from src.api.fingerprint_ledger import (
    FingerprintLedgerRepository,
    FingerprintOccurrence,
    FingerprintReservation,
    ReservationAcquireStatus,
    ensure_fingerprint_ledger_schema,
)
from src.api.models import Base, LocalAsset, TaskHistory
from src.api.planner_reservation import (
    PlannerReservationAuthorityLost,
    PlannerReservationController,
    PlannerReservationExecutionBinding,
)
from src.api.reservation_lease import (
    ReservationHeartbeatState,
    ReservationLeaseConfiguration,
    ReservationLeaseState,
    ReservationLeaseTracker,
)
from src.api.schemas import RenderDSLRequest
from tests.test_var001_balanced_axis_coverage import (
    _SyntheticParser,
    _payload,
    _plan_for_selections,
    _pools,
)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _wait_until(predicate, *, timeout=8.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class ReservationRuntimeAcceptanceTests(unittest.TestCase):
    """File-backed, real-thread acceptance for the internal Reservation hook."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self._engines = []
        self._controllers = []
        self.engine, self.Session = self._runtime("tenant.db")

    def tearDown(self):
        for controller in reversed(self._controllers):
            try:
                controller.abort()
            except Exception:
                pass
        for engine in reversed(self._engines):
            engine.dispose()
        self.temporary.cleanup()

    def _runtime(self, name, *, timeout=10.0):
        db_path = Path(self.temporary.name) / name
        engine = create_engine(
            f"sqlite:///{db_path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": timeout},
        )
        ensure_fingerprint_ledger_schema(engine)
        Base.metadata.create_all(engine)
        self._engines.append(engine)
        return engine, sessionmaker(bind=engine, expire_on_commit=False)

    def _controller(
        self,
        task_id,
        *,
        Session=None,
        ttl=0.9,
        interval=0.15,
        now=None,
        tracker=None,
        cleanup_timeout=2.0,
    ):
        controller = PlannerReservationController(
            owner_task_id=task_id,
            session_factory=Session or self.Session,
            configuration=ReservationLeaseConfiguration(ttl, interval),
            now=now or _utcnow,
            tracker=tracker,
            cleanup_join_timeout_seconds=cleanup_timeout,
        )
        self._controllers.append(controller)
        return controller

    @staticmethod
    def _fingerprint(payload, selections):
        return routes_dsl._exact_main_visual_fingerprint(
            _plan_for_selections(payload, selections)
        )

    @staticmethod
    def _identity(fingerprint):
        return routes_dsl._main_visual_fingerprint_identity_record(fingerprint)

    def _reserved_result(
        self,
        task_id,
        *,
        count=1,
        pool_size=None,
        controller=None,
    ):
        pools = _pools(pool_size or max(2, count))
        payload = _payload(pools)
        result = routes_dsl._plan_exact_main_visual_variants(
            _SyntheticParser(pools), payload, count
        )
        controller = controller or self._controller(task_id)
        for slot, fingerprint in enumerate(result.fingerprints):
            outcome = controller.acquire_candidate(
                self._identity(fingerprint),
                prospective_slot=slot,
            )
            self.assertEqual(outcome.decision.value, "OWNED")
        return payload, replace(
            result,
            reservation_bindings=controller.bindings,
        ), controller

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

    @staticmethod
    def _failed(plan, _task_id, *args, file_sid=None, **kwargs):
        resolved_sid = file_sid or args[-1]
        return routes_dsl._ChildResult(
            child_index=kwargs["child_index"],
            execution_id=kwargs["execution_id"],
            file_sid=resolved_sid,
            outcome="failed",
            assets=[],
            elapsed=0.01,
            error_code="CONTROLLED_FAILURE",
            error_message="controlled",
            prompt_details={"meta": None, "timeline": []},
            fatigue_asset_ids=(),
        )

    def _run_worker(self, task_id, payload, result, controller, worker=None):
        broadcasts = []

        def planner(*_args, **kwargs):
            self.assertIs(kwargs.get("reservation_controller"), controller)
            return result

        with (
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_variants_from_db",
                side_effect=planner,
            ),
            patch.object(
                routes_dsl,
                "render_worker",
                side_effect=worker or self._success,
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
                tenant_id="tenant-runtime",
                batch_size=len(result.plans),
                variant_planning_policy="exact_main_visual",
                reservation_controller=controller,
            )
        self.assertEqual(len(broadcasts), 1)
        self.assertEqual(broadcasts[0]["payload"], terminal)
        return terminal

    def _execution_context(self, task_id, result, controller):
        children = routes_dsl._create_child_executions(task_id, len(result.plans))
        works = tuple(
            routes_dsl._ChildWork(child, plan, fingerprint)
            for child, plan, fingerprint in zip(
                children, result.plans, result.fingerprints
            )
        )
        bindings = tuple(
            PlannerReservationExecutionBinding(
                fingerprint_identity_id=reservation.fingerprint_identity_id,
                owner_task_id=task_id,
                owner_slot_index=slot,
                execution_id=work.execution.execution_id,
            )
            for slot, (reservation, work) in enumerate(
                zip(controller.bindings, works)
            )
        )
        planned = tuple(
            routes_dsl._fingerprint_ledger_occurrence_record(
                work, task_id, "PLANNED"
            )
            for work in works
        )
        return works, bindings, planned

    @staticmethod
    def _lock_database(engine):
        connection = engine.raw_connection()
        connection.execute("BEGIN IMMEDIATE")
        return connection

    def _reservation_expiry(self, Session, identity_id):
        with Session() as db:
            return db.get(FingerprintReservation, identity_id).expires_at

    def test_public_runtime_activation_remains_absent(self):
        self.assertNotIn("reservation_conflict_mode", RenderDSLRequest.model_fields)
        self.assertIsNone(
            routes_dsl.render_batch_worker.__kwdefaults__["reservation_controller"]
        )
        source = Path(routes_dsl.__file__).read_text(encoding="utf-8")
        public_region = source[source.index("def submit_dsl"):]
        self.assertNotIn("PlannerReservationController(", public_region)

    def test_runtime_long_planner_heartbeat_blocks_takeover(self):
        pools = _pools(2)
        payload = _payload(pools)
        first_fingerprint = self._fingerprint(payload, (pools[0][0],))
        second_entered = threading.Event()
        release_planner = threading.Event()
        attempts = 0

        def materialize(payload_arg, selections, _key):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                second_entered.set()
                self.assertTrue(release_planner.wait(timeout=8))
            return _plan_for_selections(payload_arg, selections)

        controller = self._controller("long-planner", ttl=0.6, interval=0.1)
        results = []
        failures = []

        def run():
            try:
                results.append(
                    routes_dsl._plan_exact_main_visual_variants(
                        _SyntheticParser(pools, materialize_hook=materialize),
                        payload,
                        2,
                        reservation_controller=controller,
                    )
                )
            except Exception as exc:
                failures.append(exc)

        thread = threading.Thread(target=run, name="runtime-long-planner")
        thread.start()
        try:
            self.assertTrue(second_entered.wait(timeout=5))
            initial_expiry = controller.bindings[0].committed_expires_at
            self.assertTrue(_wait_until(lambda: _utcnow() > initial_expiry))
            identity_id = controller.bindings[0].fingerprint_identity_id
            self.assertTrue(
                _wait_until(
                    lambda: self._reservation_expiry(self.Session, identity_id)
                    > _utcnow()
                )
            )
            now = _utcnow()
            with self.Session() as db:
                takeover = FingerprintLedgerRepository(db).acquire_reservation(
                    self._identity(first_fingerprint),
                    owner_task_id="planner-competitor",
                    owner_slot_index=0,
                    now=now,
                    expires_at=now + timedelta(seconds=2),
                )
                db.commit()
            self.assertEqual(takeover.status, ReservationAcquireStatus.CONFLICT)
        finally:
            release_planner.set()
            thread.join(timeout=8)
        self.assertFalse(thread.is_alive())
        self.assertFalse(failures)
        self.assertEqual(len(results[0].plans), 2)
        self.assertGreaterEqual(controller.tracker.infrastructure_failure_count, 0)

    def test_runtime_long_child_renews_confirmed_lease_beyond_initial_expiry(self):
        task_id = "long-child"
        controller = self._controller(task_id, ttl=0.6, interval=0.1)
        payload, result, controller = self._reserved_result(
            task_id, controller=controller
        )
        initial_expiry = controller.bindings[0].committed_expires_at
        child_entered = threading.Event()
        release_child = threading.Event()
        terminal = []
        failures = []

        def long_child(*args, **kwargs):
            child_entered.set()
            self.assertTrue(release_child.wait(timeout=8))
            return self._success(*args, **kwargs)

        def run():
            try:
                terminal.append(
                    self._run_worker(
                        task_id, payload, result, controller, long_child
                    )
                )
            except Exception as exc:
                failures.append(exc)

        thread = threading.Thread(target=run, name="runtime-long-child-worker")
        thread.start()
        try:
            self.assertTrue(child_entered.wait(timeout=5))
            identity_id = controller.bindings[0].fingerprint_identity_id
            self.assertTrue(_wait_until(lambda: _utcnow() > initial_expiry))
            self.assertTrue(
                _wait_until(
                    lambda: self._reservation_expiry(self.Session, identity_id)
                    > _utcnow()
                )
            )
            with self.Session() as db:
                row = db.get(FingerprintReservation, identity_id)
                self.assertIsNotNone(row.execution_id)
                self.assertIsNotNone(row.confirmed_at)
                renewed_expiry = row.expires_at
                now = _utcnow()
                conflict = FingerprintLedgerRepository(db).acquire_reservation(
                    self._identity(result.fingerprints[0]),
                    owner_task_id="child-competitor",
                    owner_slot_index=0,
                    now=now,
                    expires_at=now + timedelta(seconds=2),
                )
                db.commit()
            self.assertGreater(renewed_expiry, initial_expiry)
            self.assertEqual(conflict.status, ReservationAcquireStatus.CONFLICT)
        finally:
            release_child.set()
            thread.join(timeout=8)
        self.assertFalse(thread.is_alive())
        self.assertFalse(failures)
        self.assertEqual(terminal[0]["status"], "completed")
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events.count("PLANNED"), 1)
            self.assertEqual(events.count("RENDERED"), 1)

    def test_runtime_transient_sqlite_outage_recovers_before_expiry(self):
        engine, Session = self._runtime("transient.db", timeout=0.03)
        task_id = "transient-outage"
        controller = self._controller(
            task_id, Session=Session, ttl=1.2, interval=0.2
        )
        payload, result, controller = self._reserved_result(
            task_id, controller=controller
        )
        identity_id = controller.bindings[0].fingerprint_identity_id
        initial_expiry = controller.bindings[0].committed_expires_at
        lock = self._lock_database(engine)
        try:
            self.assertTrue(
                _wait_until(
                    lambda: controller.tracker.infrastructure_failure_count >= 1,
                    timeout=3,
                )
            )
            self.assertEqual(controller.tracker.state, ReservationLeaseState.ACTIVE)
        finally:
            lock.rollback()
            lock.close()
        self.assertTrue(
            _wait_until(
                lambda: self._reservation_expiry(Session, identity_id)
                > initial_expiry,
                timeout=4,
            )
        )
        self.assertEqual(controller.tracker.state, ReservationLeaseState.ACTIVE)
        works, bindings, planned = self._execution_context(
            task_id, result, controller
        )
        controller.confirm_and_record_planned(bindings, planned)
        rendered = tuple(replace(row, lifecycle_event="RENDERED") for row in planned)
        controller.run_fenced_terminal_transaction(
            bindings,
            lambda db: FingerprintLedgerRepository(db).record_occurrences(rendered),
        )
        self.assertEqual(works[0].execution.execution_id, bindings[0].execution_id)

    def test_runtime_sqlite_outage_through_expiry_fails_closed(self):
        engine, Session = self._runtime("expired-outage.db", timeout=0.03)
        task_id = "expiry-outage"
        controller = self._controller(
            task_id, Session=Session, ttl=0.6, interval=0.1
        )
        _payload_value, result, controller = self._reserved_result(
            task_id, controller=controller
        )
        identity_id = controller.bindings[0].fingerprint_identity_id
        lock = self._lock_database(engine)
        try:
            self.assertTrue(
                _wait_until(
                    lambda: controller.tracker.state
                    is ReservationLeaseState.LEASE_LOST,
                    timeout=4,
                )
            )
        finally:
            lock.rollback()
            lock.close()
        self.assertTrue(controller.tracker.lease_lost)
        now = _utcnow()
        with Session() as db:
            takeover = FingerprintLedgerRepository(db).acquire_reservation(
                self._identity(result.fingerprints[0]),
                owner_task_id="new-owner",
                owner_slot_index=0,
                now=now,
                expires_at=now + timedelta(seconds=2),
            )
            db.commit()
            row = db.get(FingerprintReservation, identity_id)
            self.assertEqual(row.owner_task_id, "new-owner")
        self.assertEqual(takeover.status, ReservationAcquireStatus.ACQUIRED)
        self.assertFalse(controller.tracker.start())

    def test_runtime_crash_expiry_takeover_fences_stale_resume(self):
        task_id = "crash-owner"
        controller = self._controller(task_id, ttl=0.45, interval=0.1)
        _payload_value, result, controller = self._reserved_result(
            task_id, controller=controller
        )
        _works, bindings, planned = self._execution_context(
            task_id, result, controller
        )
        controller.confirm_and_record_planned(bindings, planned)
        self.assertTrue(controller.tracker.stop(join_timeout_seconds=2))
        identity_id = bindings[0].fingerprint_identity_id
        committed_expiry = self._reservation_expiry(self.Session, identity_id)
        self.assertTrue(_wait_until(lambda: _utcnow() >= committed_expiry))
        now = _utcnow()
        with self.Session() as db:
            takeover = FingerprintLedgerRepository(db).acquire_reservation(
                self._identity(result.fingerprints[0]),
                owner_task_id="replacement-owner",
                owner_slot_index=0,
                now=now,
                expires_at=now + timedelta(seconds=2),
            )
            db.commit()
        self.assertEqual(takeover.status, ReservationAcquireStatus.ACQUIRED)
        self.assertFalse(controller.tracker.run_renewal_cycle(now=_utcnow()))
        with self.assertRaises(PlannerReservationAuthorityLost):
            controller.run_fenced_terminal_transaction(bindings, lambda _db: None)
        with self.Session() as db:
            row = db.get(FingerprintReservation, identity_id)
            self.assertEqual(row.owner_task_id, "replacement-owner")
            self.assertEqual(
                db.scalars(select(FingerprintOccurrence.lifecycle_event)).all(),
                ["PLANNED"],
            )

    def test_physical_stale_output_is_not_authoritative_after_takeover(self):
        with self.Session() as db:
            db.add(
                LocalAsset(
                    id=1,
                    file_hash="a" * 64,
                    file_path="source.mp4",
                    asset_type="video",
                    usage_count=0,
                )
            )
            db.commit()
        task_id = "physical-stale"
        controller = self._controller(task_id, ttl=0.45, interval=0.1)
        payload, result, controller = self._reserved_result(
            task_id, controller=controller
        )
        output_path = Path(self.temporary.name) / "stale-output.mp4"

        def stale_child(*args, **kwargs):
            output_path.write_bytes(b"computed-but-not-authoritative")
            self.assertTrue(controller.tracker.stop(join_timeout_seconds=2))
            identity_id = controller.bindings[0].fingerprint_identity_id
            expiry = self._reservation_expiry(self.Session, identity_id)
            self.assertTrue(_wait_until(lambda: _utcnow() >= expiry))
            now = _utcnow()
            with self.Session() as db:
                takeover = FingerprintLedgerRepository(db).acquire_reservation(
                    self._identity(result.fingerprints[0]),
                    owner_task_id="physical-new-owner",
                    owner_slot_index=0,
                    now=now,
                    expires_at=now + timedelta(seconds=2),
                )
                db.commit()
            self.assertEqual(takeover.status, ReservationAcquireStatus.ACQUIRED)
            return replace(
                self._success(*args, **kwargs),
                assets=[{"file_path": str(output_path)}],
                fatigue_asset_ids=(1,),
            )

        terminal = self._run_worker(
            task_id, payload, result, controller, stale_child
        )
        self.assertTrue(output_path.exists())
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["errorCode"], "RESERVATION_AUTHORITY_LOST")
        self.assertNotIn("assets", terminal)
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events, ["PLANNED"])
            self.assertEqual(db.query(TaskHistory).count(), 0)
            asset = db.get(LocalAsset, 1)
            self.assertEqual(asset.usage_count, 0)
            self.assertIsNone(asset.last_used_at)

    def test_runtime_one_binding_takeover_fences_whole_task(self):
        task_id = "whole-task-runtime"
        controller = self._controller(task_id, ttl=0.5, interval=0.1)
        payload, result, controller = self._reserved_result(
            task_id, count=3, pool_size=3, controller=controller
        )
        all_entered = threading.Event()
        release_children = threading.Event()
        count = 0
        count_lock = threading.Lock()
        terminal = []

        def computed_child(*args, **kwargs):
            nonlocal count
            with count_lock:
                count += 1
                if count == 3:
                    all_entered.set()
            self.assertTrue(release_children.wait(timeout=8))
            return self._success(*args, **kwargs)

        thread = threading.Thread(
            target=lambda: terminal.append(
                self._run_worker(
                    task_id, payload, result, controller, computed_child
                )
            ),
            name="runtime-whole-task-worker",
        )
        thread.start()
        try:
            self.assertTrue(all_entered.wait(timeout=5))
            self.assertTrue(controller.tracker.stop(join_timeout_seconds=2))
            lost = controller.bindings[1]
            expiry = self._reservation_expiry(
                self.Session, lost.fingerprint_identity_id
            )
            self.assertTrue(_wait_until(lambda: _utcnow() >= expiry))
            now = _utcnow()
            with self.Session() as db:
                takeover = FingerprintLedgerRepository(db).acquire_reservation(
                    self._identity(result.fingerprints[1]),
                    owner_task_id="whole-task-takeover",
                    owner_slot_index=1,
                    now=now,
                    expires_at=now + timedelta(seconds=2),
                )
                db.commit()
            self.assertEqual(takeover.status, ReservationAcquireStatus.ACQUIRED)
        finally:
            release_children.set()
            thread.join(timeout=8)
        self.assertFalse(thread.is_alive())
        self.assertEqual(terminal[0]["errorCode"], "RESERVATION_AUTHORITY_LOST")
        self.assertNotIn("assets", terminal[0])
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events.count("PLANNED"), 3)
            self.assertEqual(events.count("RENDERED"), 0)
            self.assertEqual(events.count("FAILED"), 0)
            self.assertEqual(db.query(TaskHistory).count(), 0)

    def test_runtime_mixed_result_uses_one_fence_and_success_only_fatigue(self):
        with self.Session() as db:
            db.add(
                LocalAsset(
                    id=2,
                    file_hash="b" * 64,
                    file_path="mixed-source.mp4",
                    asset_type="video",
                    usage_count=0,
                )
            )
            db.commit()
        task_id = "mixed-runtime"
        payload, result, controller = self._reserved_result(task_id, count=2)

        def mixed(*args, **kwargs):
            if kwargs["child_index"] == 0:
                return replace(
                    self._success(*args, **kwargs), fatigue_asset_ids=(2,)
                )
            return replace(self._failed(*args, **kwargs), fatigue_asset_ids=(2,))

        terminal = self._run_worker(task_id, payload, result, controller, mixed)
        self.assertEqual(terminal["status"], "completed")
        self.assertTrue(terminal["partial"])
        self.assertEqual((terminal["succeededCount"], terminal["failedCount"]), (1, 1))
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events.count("PLANNED"), 2)
            self.assertEqual(events.count("RENDERED"), 1)
            self.assertEqual(events.count("FAILED"), 1)
            self.assertEqual(db.query(TaskHistory).count(), 1)
            self.assertEqual(db.get(LocalAsset, 2).usage_count, 1)

    def test_runtime_all_failed_uses_task_level_fence(self):
        task_id = "all-failed-runtime"
        payload, result, controller = self._reserved_result(task_id, count=2)
        terminal = self._run_worker(
            task_id, payload, result, controller, self._failed
        )
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["failedCount"], 2)
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events.count("PLANNED"), 2)
            self.assertEqual(events.count("FAILED"), 2)
            self.assertEqual(db.query(TaskHistory).count(), 0)

    def _concurrent_plan(self, *, pool_size, requested_count):
        engine, Session = self._runtime(
            f"concurrent-{pool_size}-{requested_count}.db", timeout=10
        )
        pools = _pools(pool_size)
        payload = _payload(pools)
        barrier = threading.Barrier(2)
        results = {}
        controllers = {}
        failures = []
        lock = threading.Lock()

        def run(owner):
            controller = self._controller(
                owner, Session=Session, ttl=4, interval=0.5
            )
            try:
                barrier.wait(timeout=5)
                result = routes_dsl._plan_exact_main_visual_variants(
                    _SyntheticParser(pools),
                    payload,
                    requested_count,
                    reservation_controller=controller,
                )
                with lock:
                    results[owner] = result
                    controllers[owner] = controller
            except Exception as exc:
                controller.abort()
                with lock:
                    failures.append(exc)

        threads = [
            threading.Thread(target=run, args=(owner,), name=f"planner-{owner}")
            for owner in ("concurrent-a", "concurrent-b")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=12)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertFalse(failures)
        return Session, payload, results, controllers

    def test_runtime_end_to_end_concurrent_planners_diversify_and_commit(self):
        Session, payload, results, controllers = self._concurrent_plan(
            pool_size=2, requested_count=1
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(
            len({result.fingerprints[0] for result in results.values()}), 2
        )
        for owner in sorted(results):
            terminal = self._run_worker(
                owner, payload, results[owner], controllers[owner]
            )
            self.assertEqual(terminal["status"], "completed")
        with Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events.count("PLANNED"), 2)
            self.assertEqual(events.count("RENDERED"), 2)
            self.assertEqual(db.query(TaskHistory).count(), 2)
            self.assertEqual(db.query(FingerprintReservation).count(), 0)

    def test_runtime_single_candidate_allows_one_authoritative_terminal(self):
        Session, payload, results, controllers = self._concurrent_plan(
            pool_size=1, requested_count=1
        )
        winners = [owner for owner, result in results.items() if result.plans]
        blocked = [owner for owner, result in results.items() if not result.plans]
        self.assertEqual((len(winners), len(blocked)), (1, 1))
        blocked_result = results[blocked[0]]
        self.assertEqual(
            blocked_result.termination_reason,
            routes_dsl._PLANNING_RESERVATION_CONFLICT_EXHAUSTED,
        )
        terminal = self._run_worker(
            winners[0], payload, results[winners[0]], controllers[winners[0]]
        )
        self.assertEqual(terminal["status"], "completed")
        controllers[blocked[0]].abort()
        with Session() as db:
            self.assertEqual(
                db.scalars(select(FingerprintOccurrence.lifecycle_event)).all(),
                ["PLANNED", "RENDERED"],
            )

    def _block_next_heartbeat_renewal(self):
        entered = threading.Event()
        release = threading.Event()
        original = FingerprintLedgerRepository.renew_reservations
        gate_lock = threading.Lock()
        blocked = False

        def wrapped(repository, *args, **kwargs):
            nonlocal blocked
            result = original(repository, *args, **kwargs)
            if threading.current_thread().name == "reservation-lease-heartbeat":
                with gate_lock:
                    should_block = not blocked
                    if should_block:
                        blocked = True
                if should_block:
                    entered.set()
                    if not release.wait(timeout=8):
                        raise RuntimeError("heartbeat race gate timed out")
            return result

        return entered, release, wrapped

    def test_runtime_confirmation_and_terminal_serialize_with_heartbeat(self):
        task_id = "heartbeat-races"
        controller = self._controller(task_id, ttl=1.2, interval=0.1)
        _payload_value, result, controller = self._reserved_result(
            task_id, controller=controller
        )
        _works, bindings, planned = self._execution_context(
            task_id, result, controller
        )

        entered, release, wrapped = self._block_next_heartbeat_renewal()
        confirm_failures = []
        with patch.object(
            FingerprintLedgerRepository, "renew_reservations", new=wrapped
        ):
            self.assertTrue(entered.wait(timeout=4))
            confirm = threading.Thread(
                target=lambda: self._capture_failure(
                    confirm_failures,
                    lambda: controller.confirm_and_record_planned(
                        bindings, planned
                    ),
                ),
                name="runtime-confirm",
            )
            confirm.start()
            time.sleep(0.05)
            release.set()
            confirm.join(timeout=8)
        self.assertFalse(confirm.is_alive())
        self.assertFalse(confirm_failures)
        self.assertEqual(controller.tracker.state, ReservationLeaseState.ACTIVE)
        self.assertEqual(controller.tracker.bindings()[0].execution_id, bindings[0].execution_id)

        entered, release, wrapped = self._block_next_heartbeat_renewal()
        terminal_failures = []
        rendered = tuple(replace(row, lifecycle_event="RENDERED") for row in planned)
        with patch.object(
            FingerprintLedgerRepository, "renew_reservations", new=wrapped
        ):
            self.assertTrue(entered.wait(timeout=4))
            terminal_thread = threading.Thread(
                target=lambda: self._capture_failure(
                    terminal_failures,
                    lambda: controller.run_fenced_terminal_transaction(
                        bindings,
                        lambda db: FingerprintLedgerRepository(db).record_occurrences(
                            rendered
                        ),
                    ),
                ),
                name="runtime-terminal",
            )
            terminal_thread.start()
            time.sleep(0.05)
            release.set()
            terminal_thread.join(timeout=8)
        self.assertFalse(terminal_thread.is_alive())
        self.assertFalse(terminal_failures)
        self.assertEqual(controller.tracker.state, ReservationLeaseState.ACTIVE)
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events.count("PLANNED"), 1)
            self.assertEqual(events.count("RENDERED"), 1)

    @staticmethod
    def _capture_failure(target, operation):
        try:
            operation()
        except Exception as exc:
            target.append(exc)

    def test_terminal_writer_failure_rolls_back_fence_and_side_effects(self):
        with self.Session() as db:
            db.add(
                LocalAsset(
                    id=3,
                    file_hash="c" * 64,
                    file_path="rollback-source.mp4",
                    asset_type="video",
                    usage_count=0,
                )
            )
            db.commit()
        task_id = "terminal-db-failure"
        _payload_value, result, controller = self._reserved_result(task_id)
        _works, bindings, planned = self._execution_context(
            task_id, result, controller
        )
        controller.confirm_and_record_planned(bindings, planned)
        self.assertTrue(controller.tracker.stop(join_timeout_seconds=2))
        before_expiry = self._reservation_expiry(
            self.Session, bindings[0].fingerprint_identity_id
        )
        rendered = replace(planned[0], lifecycle_event="RENDERED")
        attempted_expiries = []
        original_lease_window = controller._lease_window

        def captured_lease_window():
            window = original_lease_window()
            attempted_expiries.append(window[1])
            return window

        def failing_writer(db):
            FingerprintLedgerRepository(db).record_occurrence(rendered)
            routes_dsl._apply_fatigue_updates(
                db, routes_dsl.Counter({3: 1}), used_at=_utcnow()
            )
            db.add(
                LocalAsset(
                    id=3,
                    file_hash="d" * 64,
                    file_path="duplicate-id.mp4",
                    asset_type="video",
                )
            )
            db.flush()

        with (
            patch.object(
                controller, "_lease_window", side_effect=captured_lease_window
            ),
            self.assertRaises(IntegrityError),
        ):
            controller.run_fenced_terminal_transaction(bindings, failing_writer)
        with self.Session() as db:
            final_expiry = db.get(
                FingerprintReservation,
                bindings[0].fingerprint_identity_id,
            ).expires_at
            self.assertEqual(final_expiry, before_expiry)
            self.assertEqual(len(attempted_expiries), 1)
            self.assertGreater(attempted_expiries[0], before_expiry)
            self.assertEqual(
                db.scalars(select(FingerprintOccurrence.lifecycle_event)).all(),
                ["PLANNED"],
            )
            self.assertEqual(db.get(LocalAsset, 3).usage_count, 0)
            self.assertEqual(db.query(TaskHistory).count(), 0)
        self.rollback_expiries = (
            before_expiry,
            attempted_expiries[0],
            final_expiry,
        )

    def test_confirmation_planned_failure_rolls_back_confirmation_and_renewal(self):
        with self.Session() as db:
            db.add(
                LocalAsset(
                    id=5,
                    file_hash="f" * 64,
                    file_path="confirmation-rollback-source.mp4",
                    asset_type="video",
                    usage_count=0,
                )
            )
            db.commit()
        task_id = "confirmation-planned-rollback"
        _payload_value, result, controller = self._reserved_result(task_id)
        _works, bindings, planned = self._execution_context(
            task_id, result, controller
        )
        self.assertTrue(controller.tracker.stop(join_timeout_seconds=2))
        identity_id = bindings[0].fingerprint_identity_id
        before_expiry = self._reservation_expiry(self.Session, identity_id)
        original_record_occurrences = (
            FingerprintLedgerRepository.record_occurrences
        )

        def fail_after_planned(repository, records):
            count = original_record_occurrences(repository, records)
            repository._session.add(
                LocalAsset(
                    id=5,
                    file_hash="0" * 64,
                    file_path="confirmation-duplicate-id.mp4",
                    asset_type="video",
                )
            )
            repository._session.flush()
            return count

        with (
            patch.object(
                FingerprintLedgerRepository,
                "record_occurrences",
                new=fail_after_planned,
            ),
            self.assertRaises(IntegrityError),
        ):
            controller.confirm_and_record_planned(bindings, planned)

        with self.Session() as db:
            reservation = db.get(FingerprintReservation, identity_id)
            self.assertEqual(reservation.expires_at, before_expiry)
            self.assertIsNone(reservation.execution_id)
            self.assertIsNone(reservation.confirmed_at)
            self.assertEqual(db.query(FingerprintOccurrence).count(), 0)
            self.assertEqual(db.get(LocalAsset, 5).usage_count, 0)

    def test_post_terminal_release_operational_error_cannot_rewrite_truth(self):
        with self.Session() as db:
            db.add(
                LocalAsset(
                    id=4,
                    file_hash="e" * 64,
                    file_path="release-source.mp4",
                    asset_type="video",
                    usage_count=0,
                )
            )
            db.commit()
        task_id = "release-operational-error"
        payload, result, controller = self._reserved_result(task_id)
        original_factory = controller._session_factory

        def success_with_fatigue(*args, **kwargs):
            return replace(self._success(*args, **kwargs), fatigue_asset_ids=(4,))

        def failing_factory():
            session = original_factory()

            def fail_commit():
                raise OperationalError(
                    "release",
                    {},
                    sqlite3.OperationalError("release unavailable"),
                )

            session.commit = fail_commit
            return session

        def cleanup_failure():
            controller._session_factory = failing_factory
            try:
                return PlannerReservationController.abort(controller)
            finally:
                controller._session_factory = original_factory

        with (
            patch.object(controller, "abort", side_effect=cleanup_failure),
            patch("src.api.planner_reservation.logger.warning") as warning,
        ):
            terminal = self._run_worker(
                task_id, payload, result, controller, success_with_fatigue
            )
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(terminal["succeededCount"], 1)
        warning.assert_called_once()
        self.assertNotIn("release unavailable", str(warning.call_args))
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events.count("RENDERED"), 1)
            self.assertEqual(db.query(TaskHistory).count(), 1)
            self.assertEqual(db.get(LocalAsset, 4).usage_count, 1)
            self.assertEqual(db.query(FingerprintReservation).count(), 1)
        self.assertTrue(controller.abort())

    def test_post_terminal_stop_timeout_preserves_truth_and_avoids_release_race(self):
        task_id = "post-terminal-stop-timeout"
        block_enabled = threading.Event()
        renewal_entered = threading.Event()
        release_renewal = threading.Event()

        def heartbeat_session_factory():
            if (
                threading.current_thread().name == "reservation-lease-heartbeat"
                and block_enabled.is_set()
            ):
                renewal_entered.set()
                if not release_renewal.wait(timeout=8):
                    raise RuntimeError("blocked heartbeat timed out")
            return self.Session()

        configuration = ReservationLeaseConfiguration(1.2, 0.1)
        tracker = ReservationLeaseTracker(
            owner_task_id=task_id,
            session_factory=heartbeat_session_factory,
            configuration=configuration,
        )
        controller = self._controller(
            task_id,
            ttl=1.2,
            interval=0.1,
            tracker=tracker,
            cleanup_timeout=0.03,
        )
        payload, result, controller = self._reserved_result(
            task_id, controller=controller
        )

        def child(*args, **kwargs):
            block_enabled.set()
            self.assertTrue(renewal_entered.wait(timeout=5))
            return self._success(*args, **kwargs)

        terminal = self._run_worker(task_id, payload, result, controller, child)
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(
            controller.tracker.heartbeat_state,
            ReservationHeartbeatState.STOPPING,
        )
        with self.Session() as db:
            self.assertEqual(db.query(FingerprintReservation).count(), 1)
            self.assertEqual(db.query(TaskHistory).count(), 1)
            self.assertEqual(
                db.scalars(select(FingerprintOccurrence.lifecycle_event)).all().count(
                    "RENDERED"
                ),
                1,
            )
        release_renewal.set()
        self.assertTrue(
            _wait_until(
                lambda: controller.tracker.heartbeat_state
                is ReservationHeartbeatState.STOPPED
            )
        )
        stable_expiry = self._reservation_expiry(
            self.Session, controller.bindings[0].fingerprint_identity_id
        )
        time.sleep(0.15)
        self.assertEqual(
            self._reservation_expiry(
                self.Session, controller.bindings[0].fingerprint_identity_id
            ),
            stable_expiry,
        )
        self.assertTrue(controller.abort())

    def test_forward_clock_jump_causes_irreversible_lease_loss(self):
        base = _utcnow()
        current = [base]
        task_id = "forward-clock"
        controller = self._controller(
            task_id,
            ttl=0.6,
            interval=0.1,
            now=lambda: current[0],
        )
        _payload_value, result, controller = self._reserved_result(
            task_id, controller=controller
        )
        current[0] = base + timedelta(seconds=2)
        self.assertTrue(
            _wait_until(
                lambda: controller.tracker.state
                is ReservationLeaseState.LEASE_LOST,
                timeout=3,
            )
        )
        self.assertFalse(controller.tracker.start())
        identity_id = controller.bindings[0].fingerprint_identity_id
        with self.Session() as db:
            row = db.get(FingerprintReservation, identity_id)
            self.assertEqual(row.owner_task_id, task_id)
            takeover = FingerprintLedgerRepository(db).acquire_reservation(
                self._identity(result.fingerprints[0]),
                owner_task_id="forward-new-owner",
                owner_slot_index=0,
                now=current[0],
                expires_at=current[0] + timedelta(seconds=2),
            )
            db.commit()
        self.assertEqual(takeover.status, ReservationAcquireStatus.ACQUIRED)

    def test_visible_loss_during_submission_stops_later_children(self):
        task_id = "submission-loss"
        payload, result, controller = self._reserved_result(
            task_id, count=3, pool_size=3
        )
        executed = []

        def child(*args, **kwargs):
            executed.append(kwargs["child_index"])
            return self._success(*args, **kwargs)

        class LosingExecutor:
            def __init__(_self, *args, **kwargs):
                _self.pool = concurrent.futures.ThreadPoolExecutor(*args, **kwargs)
                _self.submissions = 0

            def __enter__(_self):
                return _self

            def submit(_self, fn, *args, **kwargs):
                future = _self.pool.submit(fn, *args, **kwargs)
                _self.submissions += 1
                if _self.submissions == 1:
                    controller.tracker.fail_closed("SUBMISSION_TEST_LOSS")
                return future

            def __exit__(_self, exc_type, exc, tb):
                _self.pool.shutdown(wait=True)

        with patch.object(routes_dsl, "ThreadPoolExecutor", LosingExecutor):
            terminal = self._run_worker(task_id, payload, result, controller, child)
        self.assertEqual(executed, [0])
        self.assertEqual(terminal["errorCode"], "RESERVATION_AUTHORITY_LOST")
        self.assertNotIn("assets", terminal)
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events.count("PLANNED"), 3)
            self.assertEqual(events.count("RENDERED"), 0)

    def test_confirmed_execution_id_mismatch_is_fenced_without_rebind(self):
        task_id = "execution-fence"
        _payload_value, result, controller = self._reserved_result(task_id)
        _works, bindings, planned = self._execution_context(
            task_id, result, controller
        )
        controller.confirm_and_record_planned(bindings, planned)
        stale = (replace(bindings[0], execution_id="EXEC-B"),)
        with self.assertRaises(PlannerReservationAuthorityLost):
            controller.run_fenced_terminal_transaction(stale, lambda _db: None)
        with self.Session() as db:
            row = db.get(FingerprintReservation, bindings[0].fingerprint_identity_id)
            self.assertEqual(row.execution_id, bindings[0].execution_id)
            self.assertEqual(
                db.scalars(select(FingerprintOccurrence.lifecycle_event)).all(),
                ["PLANNED"],
            )

    def test_owner_slot_reuse_debt_remains_internal_and_explicit(self):
        pools = _pools(2)
        payload = _payload(pools)
        fingerprints = [
            self._fingerprint(payload, (candidate,)) for candidate in pools[0]
        ]
        first = self._controller("reused-task", ttl=5, interval=1)
        second = self._controller("reused-task", ttl=5, interval=1)
        self.assertEqual(
            first.acquire_candidate(
                self._identity(fingerprints[0]), prospective_slot=0
            ).decision.value,
            "OWNED",
        )
        self.assertEqual(
            second.acquire_candidate(
                self._identity(fingerprints[1]), prospective_slot=0
            ).decision.value,
            "OWNED",
        )
        with self.Session() as db:
            rows = db.scalars(select(FingerprintReservation)).all()
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {(row.owner_task_id, row.owner_slot_index) for row in rows},
                {("reused-task", 0)},
            )


if __name__ == "__main__":
    unittest.main()
