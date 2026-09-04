import sqlite3
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from src.api import routes_dsl
from src.api.dsl_parser import MainVisualCandidate
from src.api.fingerprint_ledger import (
    FingerprintLedgerRepository,
    FingerprintOccurrenceRecord,
    FingerprintReservation,
    ReservationAcquireStatus,
    ensure_fingerprint_ledger_schema,
)
from src.api.historical_novelty_policy import PreviewIntent
from src.api.planner_reservation import (
    PlannerReservationController,
    PlannerReservationDecision,
)
from src.api.reservation_lease import (
    ReservationHeartbeatState,
    ReservationLeaseConfiguration,
    ReservationLeaseState,
)
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


def _fingerprint(payload, selections):
    return routes_dsl._exact_main_visual_fingerprint(
        _plan_for_selections(payload, selections)
    )


def _identity(fingerprint):
    return routes_dsl._main_visual_fingerprint_identity_record(fingerprint)


def _observer(session_factory, mode="OBSERVE"):
    return routes_dsl._HistoricalNoveltyObserver(
        lambda record: routes_dsl._lookup_historical_exact_in_new_session(
            session_factory,
            record,
        ),
        mode,
    )


class _FakeTracker:
    def __init__(self, *, register_error=None, stop_result=True, on_register=None):
        self.owner_attempt_id = str(uuid.uuid4())
        self.state = ReservationLeaseState.ACTIVE
        self.heartbeat_state = ReservationHeartbeatState.NOT_STARTED
        self.register_error = register_error
        self.stop_result = stop_result
        self.on_register = on_register
        self.registered = []
        self.start_calls = 0
        self.stop_calls = 0

    def register_binding(self, **kwargs):
        if self.register_error is not None:
            raise self.register_error
        if self.on_register is not None:
            self.on_register(**kwargs)
        self.registered.append(kwargs)

    def start(self):
        self.start_calls += 1
        self.heartbeat_state = ReservationHeartbeatState.RUNNING
        return True

    def stop(self, *, join_timeout_seconds):
        self.stop_calls += 1
        if self.stop_result:
            self.heartbeat_state = ReservationHeartbeatState.STOPPED
        return self.stop_result


class PlannerReservationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = _engine()
        self.Session = sessionmaker(bind=self.engine)
        self.now = datetime(2026, 9, 3, 8, 0, 0)
        self.configuration = ReservationLeaseConfiguration(30, 5)

    def tearDown(self):
        self.engine.dispose()

    def _controller(self, owner="task-a", **kwargs):
        return PlannerReservationController(
            logical_task_id=owner,
            session_factory=kwargs.pop("session_factory", self.Session),
            configuration=kwargs.pop("configuration", self.configuration),
            now=kwargs.pop("now", lambda: self.now + timedelta(seconds=1)),
            **kwargs,
        )

    def _reserve_other(self, fingerprint, *, owner="task-other", slot=0):
        with self.Session() as db:
            result = FingerprintLedgerRepository(db).acquire_reservation(
                _identity(fingerprint),
                owner_task_id=owner,
                owner_slot_index=slot,
                now=self.now,
                expires_at=self.now + timedelta(seconds=60),
            )
            db.commit()
        self.assertEqual(result.status, ReservationAcquireStatus.ACQUIRED)

    def test_public_contract_and_default_planners_have_no_activation(self):
        self.assertNotIn("reservation_conflict_mode", RenderDSLRequest.model_fields)
        pools = _pools(2)
        payload = _payload(pools)
        exact_before = routes_dsl._plan_exact_main_visual_variants(
            _SyntheticParser(pools), payload, 2
        )
        balanced_before = routes_dsl._plan_exact_main_visual_balanced_variants(
            _SyntheticParser(pools), payload, 2
        )
        with patch.object(
            FingerprintLedgerRepository,
            "acquire_reservation",
            side_effect=AssertionError("default planner must not reserve"),
        ):
            exact_after = routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools), payload, 2
            )
            balanced_after = routes_dsl._plan_exact_main_visual_balanced_variants(
                _SyntheticParser(pools), payload, 2
            )
        self.assertEqual(exact_after, exact_before)
        self.assertEqual(balanced_after, balanced_before)

    def test_exact_conflict_skips_to_next_candidate_after_historical_observe(self):
        pools = _pools(2)
        payload = _payload(pools)
        first = _fingerprint(payload, (pools[0][0],))
        second = _fingerprint(payload, (pools[0][1],))
        self._reserve_other(first)
        controller = self._controller()
        observer = _observer(self.Session)
        try:
            result = routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools),
                payload,
                1,
                historical_observer=observer,
                reservation_controller=controller,
            )
            self.assertEqual(result.fingerprints, (second,))
            diagnostics = result.historical_novelty_diagnostics
            self.assertEqual(diagnostics.reservation_conflict_count, 1)
            self.assertEqual(diagnostics.historical_rejection_count, 0)
            self.assertEqual(diagnostics.accepted_after_historical_check_count, 1)
            self.assertEqual(diagnostics.candidate_checks, 2)
            routes_dsl._historical_novelty_diagnostics_v1_payload(diagnostics)
            routes_dsl._validated_historical_novelty_diagnostics_payload(
                diagnostics,
                result,
                "OBSERVE",
            )
        finally:
            controller.abort()

    def test_balanced_conflict_does_not_update_coverage(self):
        pools = _pools(2)
        payload = _payload(pools)
        first = _fingerprint(payload, (pools[0][0],))
        second = _fingerprint(payload, (pools[0][1],))
        self._reserve_other(first)
        controller = self._controller()
        observer = _observer(self.Session)
        try:
            result = routes_dsl._plan_exact_main_visual_balanced_variants(
                _SyntheticParser(pools),
                payload,
                1,
                historical_observer=observer,
                reservation_controller=controller,
            )
            self.assertEqual(result.fingerprints, (second,))
            histogram = result.coverage_diagnostics.beats[0].selected_histogram
            self.assertEqual([(row.normalized_file_hash, row.count) for row in histogram], [("b0-1", 1)])
            self.assertEqual(
                result.historical_novelty_diagnostics.reservation_conflict_count,
                1,
            )
        finally:
            controller.abort()

    def test_historical_rendered_remains_advisory_and_selectable(self):
        pools = _pools(1)
        payload = _payload(pools)
        fingerprint = _fingerprint(payload, (pools[0][0],))
        identity = _identity(fingerprint)
        with self.Session() as db:
            FingerprintLedgerRepository(db).record_occurrence(
                FingerprintOccurrenceRecord(
                    **identity.__dict__,
                    task_id="old-task",
                    execution_id="old-exec",
                    child_index=0,
                    lifecycle_event="RENDERED",
                    provenance="test",
                )
            )
            db.commit()
        controller = self._controller()
        observer = _observer(self.Session, "ADVISORY")
        try:
            result = routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools), payload, 1,
                historical_observer=observer,
                reservation_controller=controller,
            )
            self.assertEqual(result.fingerprints, (fingerprint,))
            diagnostics = result.historical_novelty_diagnostics
            self.assertEqual(diagnostics.rendered_matches, 1)
            self.assertEqual(diagnostics.advisory_count, 1)
            self.assertEqual(diagnostics.historical_rejection_count, 0)
        finally:
            controller.abort()

    def test_lookup_unknown_is_accepted_only_when_reservation_is_owned(self):
        pools = _pools(1)
        payload = _payload(pools)
        fingerprint = _fingerprint(payload, (pools[0][0],))

        def unavailable(_record):
            raise OperationalError(
                "lookup", {}, sqlite3.OperationalError("unavailable")
            )

        controller = self._controller()
        observer = routes_dsl._HistoricalNoveltyObserver(unavailable, "OBSERVE")
        try:
            result = routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools), payload, 1,
                historical_observer=observer,
                reservation_controller=controller,
            )
            diagnostics = result.historical_novelty_diagnostics
            self.assertEqual(len(result.plans), 1)
            self.assertEqual(diagnostics.lookup_failures, 1)
            self.assertEqual(diagnostics.accepted_with_lookup_unknown_count, 1)
            self.assertEqual(diagnostics.reservation_conflict_count, 0)
        finally:
            controller.abort()

        self._reserve_other(fingerprint)
        controller = self._controller(owner="task-b")
        observer = routes_dsl._HistoricalNoveltyObserver(unavailable, "OBSERVE")
        try:
            result = routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools), payload, 1,
                historical_observer=observer,
                reservation_controller=controller,
            )
            diagnostics = result.historical_novelty_diagnostics
            self.assertEqual(result.plans, ())
            self.assertEqual(diagnostics.lookup_failures, 1)
            self.assertEqual(diagnostics.accepted_with_lookup_unknown_count, 0)
            self.assertEqual(diagnostics.reservation_conflict_count, 1)
            self.assertEqual(
                result.termination_reason,
                routes_dsl._PLANNING_RESERVATION_CONFLICT_EXHAUSTED,
            )
        finally:
            controller.abort()

    def test_preview_conflict_is_not_seeded_or_retried_and_slot_zero_is_reused(self):
        pools = _pools(2)
        payload = _payload(pools)
        preview = _plan_for_selections(payload, (pools[0][0],))
        preview_fingerprint = routes_dsl._exact_main_visual_fingerprint(preview)
        self._reserve_other(preview_fingerprint)
        controller = self._controller()
        observer = _observer(self.Session)
        try:
            result = routes_dsl._plan_exact_main_visual_balanced_variants(
                _SyntheticParser(pools), payload, 1,
                preview_plan=preview,
                historical_observer=observer,
                preview_intent=PreviewIntent.AUTOMATIC_PREVIEW,
                reservation_controller=controller,
            )
            self.assertNotEqual(result.fingerprints[0], preview_fingerprint)
            self.assertFalse(result.coverage_diagnostics.preview_seeded)
            self.assertTrue(result.historical_novelty_diagnostics.preview_checked)
            self.assertEqual(result.historical_novelty_diagnostics.candidate_checks, 2)
            self.assertEqual(result.reservation_bindings[0].owner_slot_index, 0)
            self.assertEqual(controller.conflict_count, 1)
        finally:
            controller.abort()

    def test_same_batch_duplicate_is_rejected_before_reservation(self):
        pools = [[
            MainVisualCandidate(asset_id=1, file_hash="same-hash"),
            MainVisualCandidate(asset_id=2, file_hash="same-hash"),
        ]]
        payload = _payload(pools)
        controller = self._controller()
        calls = 0
        original = controller.acquire_candidate

        def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        try:
            with patch.object(controller, "acquire_candidate", side_effect=counted):
                result = routes_dsl._plan_exact_main_visual_variants(
                    _SyntheticParser(pools), payload, 2,
                    reservation_controller=controller,
                )
            self.assertEqual(len(result.plans), 1)
            self.assertEqual(calls, 1)
        finally:
            controller.abort()

    def test_search_budget_truncation_precedes_reservation_exhaustion_reason(self):
        pools = _pools(2)
        payload = _payload(pools)
        self._reserve_other(_fingerprint(payload, (pools[0][0],)))
        controller = self._controller()
        try:
            result = routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools),
                payload,
                1,
                search_budget=1,
                historical_observer=_observer(self.Session),
                reservation_controller=controller,
            )
            self.assertEqual(result.plans, ())
            self.assertEqual(
                result.termination_reason,
                routes_dsl._PLANNING_SEARCH_LIMIT_REACHED,
            )
        finally:
            controller.abort()

    def test_termination_requires_distinct_blocked_capacity_to_fill_the_gap(self):
        cases = (
            (0, 1, 1, routes_dsl._PLANNING_RESERVATION_CONFLICT_EXHAUSTED),
            (2, 3, 1, routes_dsl._PLANNING_RESERVATION_CONFLICT_EXHAUSTED),
            (1, 4, 1, routes_dsl._PLANNING_TRUE_SPACE_EXHAUSTED),
        )
        for accepted, requested, blocked, expected in cases:
            with self.subTest(
                accepted=accepted,
                requested=requested,
                blocked=blocked,
            ):
                reason, _warnings = routes_dsl._planning_termination(
                    accepted_count=accepted,
                    requested_count=requested,
                    examined_count=4,
                    candidate_space_size=4,
                    unresolved_unique_reservation_blocked_count=blocked,
                )
                self.assertEqual(reason, expected)

        reason, _warnings = routes_dsl._planning_termination(
            accepted_count=0,
            requested_count=1,
            examined_count=1,
            candidate_space_size=2,
            unresolved_unique_reservation_blocked_count=1,
        )
        self.assertEqual(reason, routes_dsl._PLANNING_SEARCH_LIMIT_REACHED)

    def test_duplicate_conflict_attempts_count_once_as_exact_blocked_capacity(self):
        pools = [[
            MainVisualCandidate(asset_id=1, file_hash="same-hash"),
            MainVisualCandidate(asset_id=2, file_hash="same-hash"),
        ]]
        payload = _payload(pools)
        fingerprint = _fingerprint(payload, (pools[0][0],))
        self._reserve_other(fingerprint)
        controller = self._controller()
        observer = _observer(self.Session)
        try:
            result = routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools),
                payload,
                2,
                historical_observer=observer,
                reservation_controller=controller,
            )
            self.assertEqual(result.plans, ())
            self.assertEqual(controller.conflict_count, 2)
            self.assertEqual(
                result.historical_novelty_diagnostics.reservation_conflict_count,
                2,
            )
            self.assertEqual(
                result.termination_reason,
                routes_dsl._PLANNING_TRUE_SPACE_EXHAUSTED,
            )
        finally:
            controller.abort()

    def test_exact_conflicted_fingerprint_later_accepted_is_no_longer_blocked(self):
        pools = [[
            MainVisualCandidate(asset_id=1, file_hash="same-hash"),
            MainVisualCandidate(asset_id=2, file_hash="same-hash"),
        ]]
        payload = _payload(pools)
        fingerprint = _fingerprint(payload, (pools[0][0],))
        self._reserve_other(fingerprint)
        controller = self._controller()
        observer = _observer(self.Session)
        original_acquire = controller.acquire_candidate
        released = False

        def acquire_then_release_other(*args, **kwargs):
            nonlocal released
            outcome = original_acquire(*args, **kwargs)
            if outcome.decision is PlannerReservationDecision.CONFLICT and not released:
                with self.Session() as db:
                    identity = FingerprintLedgerRepository(db)._find_identity(
                        _identity(fingerprint)
                    )
                    self.assertIsNotNone(identity)
                    self.assertTrue(
                        FingerprintLedgerRepository(db).release_reservation(
                            identity.id,
                            owner_task_id="task-other",
                            owner_slot_index=0,
                        )
                    )
                    db.commit()
                released = True
            return outcome

        try:
            with patch.object(
                controller,
                "acquire_candidate",
                side_effect=acquire_then_release_other,
            ):
                result = routes_dsl._plan_exact_main_visual_variants(
                    _SyntheticParser(pools),
                    payload,
                    2,
                    historical_observer=observer,
                    reservation_controller=controller,
                )
            self.assertEqual(result.fingerprints, (fingerprint,))
            self.assertEqual(controller.conflict_count, 1)
            self.assertEqual(
                result.historical_novelty_diagnostics.reservation_conflict_count,
                1,
            )
            self.assertEqual(
                result.termination_reason,
                routes_dsl._PLANNING_TRUE_SPACE_EXHAUSTED,
            )
        finally:
            controller.abort()

    def test_exact_mixed_shortfall_not_explained_by_one_blocked_fingerprint(self):
        pools = _pools(4)
        payload = _payload(pools)
        self._reserve_other(_fingerprint(payload, (pools[0][1],)))

        def reject_tail(payload_arg, selections, _key):
            if selections[0].file_hash in {"b0-2", "b0-3"}:
                raise ValueError("intrinsic invalid plan")
            return _plan_for_selections(payload_arg, selections)

        controller = self._controller()
        try:
            result = routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools, materialize_hook=reject_tail),
                payload,
                4,
                historical_observer=_observer(self.Session),
                reservation_controller=controller,
            )
            self.assertEqual(len(result.plans), 1)
            self.assertEqual(controller.conflict_count, 1)
            self.assertEqual(
                result.termination_reason,
                routes_dsl._PLANNING_TRUE_SPACE_EXHAUSTED,
            )
        finally:
            controller.abort()

    def test_balanced_mixed_shortfall_is_explained_by_one_blocked_fingerprint(self):
        pools = _pools(4)
        payload = _payload(pools)
        self._reserve_other(_fingerprint(payload, (pools[0][2],)))

        def reject_last(payload_arg, selections, _key):
            if selections[0].file_hash == "b0-3":
                raise ValueError("intrinsic invalid plan")
            return _plan_for_selections(payload_arg, selections)

        controller = self._controller()
        try:
            result = routes_dsl._plan_exact_main_visual_balanced_variants(
                _SyntheticParser(pools, materialize_hook=reject_last),
                payload,
                3,
                historical_observer=_observer(self.Session),
                reservation_controller=controller,
            )
            self.assertEqual(len(result.plans), 2)
            self.assertEqual(controller.conflict_count, 1)
            self.assertEqual(
                result.termination_reason,
                routes_dsl._PLANNING_RESERVATION_CONFLICT_EXHAUSTED,
            )
        finally:
            controller.abort()

    def test_balanced_preview_conflict_contributes_one_distinct_capacity(self):
        pools = _pools(2)
        payload = _payload(pools)
        preview = _plan_for_selections(payload, (pools[0][0],))
        self._reserve_other(routes_dsl._exact_main_visual_fingerprint(preview))
        controller = self._controller()
        try:
            result = routes_dsl._plan_exact_main_visual_balanced_variants(
                _SyntheticParser(pools),
                payload,
                2,
                preview_plan=preview,
                historical_observer=_observer(self.Session),
                preview_intent=PreviewIntent.AUTOMATIC_PREVIEW,
                reservation_controller=controller,
            )
            self.assertEqual(len(result.plans), 1)
            self.assertFalse(result.coverage_diagnostics.preview_seeded)
            self.assertEqual(
                result.termination_reason,
                routes_dsl._PLANNING_RESERVATION_CONFLICT_EXHAUSTED,
            )
        finally:
            controller.abort()

    def test_commit_is_visible_before_tracker_registration_and_alignment_is_exact(self):
        pools = _pools(2)
        payload = _payload(pools)
        observed = []

        def on_register(**kwargs):
            with self.Session() as db:
                observed.append(
                    db.get(FingerprintReservation, kwargs["fingerprint_identity_id"])
                    is not None
                )

        tracker = _FakeTracker(on_register=on_register)
        controller = self._controller(tracker=tracker)
        try:
            result = routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools), payload, 2,
                reservation_controller=controller,
            )
            self.assertEqual(observed, [True, True])
            self.assertEqual(len(result.reservation_bindings), 2)
            self.assertEqual(
                [binding.owner_slot_index for binding in result.reservation_bindings],
                [0, 1],
            )
            for binding, fingerprint in zip(
                result.reservation_bindings, result.fingerprints
            ):
                contract = routes_dsl._main_visual_planning_fingerprint_contract(
                    fingerprint
                )
                self.assertEqual(binding.fingerprint_digest, contract.fingerprint_digest)
                self.assertEqual(binding.logical_task_id, "task-a")
                self.assertEqual(
                    binding.owner_attempt_id,
                    controller.reservation_owner_attempt_id,
                )
        finally:
            controller.abort()

    def test_reservation_db_failure_is_hard_and_not_a_conflict(self):
        pools = _pools(1)
        payload = _payload(pools)
        controller = self._controller(tracker=_FakeTracker())
        failure = OperationalError(
            "acquire", {}, sqlite3.OperationalError("unavailable")
        )
        with patch.object(
            FingerprintLedgerRepository,
            "acquire_reservation",
            side_effect=failure,
        ):
            with self.assertRaises(OperationalError):
                routes_dsl._plan_exact_main_visual_variants(
                    _SyntheticParser(pools), payload, 1,
                    reservation_controller=controller,
                )
        self.assertEqual(controller.conflict_count, 0)
        self.assertEqual(controller.bindings, ())

    def test_register_failure_releases_committed_reservation(self):
        pools = _pools(1)
        payload = _payload(pools)
        fingerprint = _fingerprint(payload, (pools[0][0],))
        tracker = _FakeTracker(register_error=RuntimeError("register failed"))
        controller = self._controller(tracker=tracker)
        with self.assertRaisesRegex(RuntimeError, "register failed"):
            routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools), payload, 1,
                reservation_controller=controller,
            )
        with self.Session() as db:
            identity = FingerprintLedgerRepository(db)._find_identity(
                _identity(fingerprint)
            )
            self.assertIsNotNone(identity)
            self.assertIsNone(db.get(FingerprintReservation, identity.id))

    def test_planner_failure_releases_owned_reservations_and_preserves_error(self):
        pools = _pools(2)
        payload = _payload(pools)
        attempts = 0

        def fail_second(payload_arg, selections, _key):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise RuntimeError("original planner failure")
            return _plan_for_selections(payload_arg, selections)

        controller = self._controller(tracker=_FakeTracker())
        with self.assertRaisesRegex(RuntimeError, "original planner failure"):
            routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools, materialize_hook=fail_second),
                payload,
                2,
                reservation_controller=controller,
            )
        self.assertEqual(controller.bindings, ())
        with self.Session() as db:
            self.assertEqual(db.query(FingerprintReservation).count(), 0)

    def test_lease_loss_during_planning_is_a_hard_failure(self):
        pools = _pools(2)
        payload = _payload(pools)
        attempts = 0
        controller = self._controller()

        def lose_after_first(payload_arg, selections, _key):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                with controller.tracker._lock:
                    controller.tracker._mark_lease_lost_locked("TEST_LEASE_LOST")
            return _plan_for_selections(payload_arg, selections)

        with self.assertRaisesRegex(Exception, "PLANNER_RESERVATION_AUTHORITY_LOST"):
            routes_dsl._plan_exact_main_visual_variants(
                _SyntheticParser(pools, materialize_hook=lose_after_first),
                payload,
                2,
                reservation_controller=controller,
            )
        self.assertEqual(controller.tracker.state, ReservationLeaseState.LEASE_LOST)


class PlannerReservationConcurrencyTests(unittest.TestCase):
    def test_heartbeat_renews_first_binding_during_long_planner_search(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = _engine(f"sqlite:///{Path(directory) / 'tenant.db'}")
            Session = sessionmaker(bind=engine)
            pools = _pools(2)
            payload = _payload(pools)
            first_fingerprint = _fingerprint(payload, (pools[0][0],))
            second_materialization = threading.Event()
            release_planner = threading.Event()
            attempts = 0

            def pause_second(payload_arg, selections, _key):
                nonlocal attempts
                attempts += 1
                if attempts == 2:
                    second_materialization.set()
                    release_planner.wait(timeout=5)
                return _plan_for_selections(payload_arg, selections)

            controller = PlannerReservationController(
                logical_task_id="task-a",
                session_factory=Session,
                configuration=ReservationLeaseConfiguration(0.3, 0.05),
            )
            outcome = []
            failures = []

            def run_planner():
                try:
                    outcome.append(routes_dsl._plan_exact_main_visual_variants(
                        _SyntheticParser(pools, materialize_hook=pause_second),
                        payload,
                        2,
                        reservation_controller=controller,
                    ))
                except Exception as exc:
                    failures.append(exc)

            thread = threading.Thread(target=run_planner)
            thread.start()
            try:
                self.assertTrue(second_materialization.wait(timeout=3))
                original_expiry = controller.bindings[0].committed_expires_at
                time.sleep(0.45)
                attempt_time = datetime.now(timezone.utc).replace(tzinfo=None)
                with Session() as db:
                    takeover = FingerprintLedgerRepository(db).acquire_reservation(
                        _identity(first_fingerprint),
                        owner_task_id="task-b",
                        owner_slot_index=0,
                        now=attempt_time,
                        expires_at=attempt_time + timedelta(seconds=1),
                    )
                    db.commit()
                self.assertEqual(takeover.status, ReservationAcquireStatus.CONFLICT)
                with Session() as db:
                    identity = FingerprintLedgerRepository(db)._find_identity(
                        _identity(first_fingerprint)
                    )
                    row = db.get(FingerprintReservation, identity.id)
                    self.assertGreater(row.expires_at, original_expiry)
            finally:
                release_planner.set()
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertFalse(failures)
            self.assertEqual(len(outcome[0].plans), 2)
            controller.abort()
            engine.dispose()

    def test_planner_failure_does_not_release_when_heartbeat_stop_times_out(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = _engine(f"sqlite:///{Path(directory) / 'tenant.db'}")
            Session = sessionmaker(bind=engine)
            pools = _pools(2)
            payload = _payload(pools)
            renewal_entered = threading.Event()
            release_renewal = threading.Event()
            session_calls = 0
            call_lock = threading.Lock()

            def controlled_session_factory():
                nonlocal session_calls
                with call_lock:
                    session_calls += 1
                    call_number = session_calls
                if call_number == 2:
                    renewal_entered.set()
                    release_renewal.wait(timeout=5)
                return Session()

            attempts = 0

            def fail_after_renewal_blocks(payload_arg, selections, _key):
                nonlocal attempts
                attempts += 1
                if attempts == 2:
                    self.assertTrue(renewal_entered.wait(timeout=3))
                    raise RuntimeError("original planner failure")
                return _plan_for_selections(payload_arg, selections)

            controller = PlannerReservationController(
                logical_task_id="task-a",
                session_factory=controlled_session_factory,
                configuration=ReservationLeaseConfiguration(30, 0.01),
                cleanup_join_timeout_seconds=0.02,
            )
            try:
                with self.assertRaisesRegex(RuntimeError, "original planner failure"):
                    routes_dsl._plan_exact_main_visual_variants(
                        _SyntheticParser(
                            pools,
                            materialize_hook=fail_after_renewal_blocks,
                        ),
                        payload,
                        2,
                        reservation_controller=controller,
                    )
                self.assertEqual(
                    controller.tracker.heartbeat_state,
                    ReservationHeartbeatState.STOPPING,
                )
                self.assertEqual(len(controller.bindings), 1)
                with Session() as db:
                    self.assertEqual(db.query(FingerprintReservation).count(), 1)
            finally:
                release_renewal.set()
            deadline = time.monotonic() + 5
            while (
                controller.tracker.heartbeat_state
                is not ReservationHeartbeatState.STOPPED
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertEqual(
                controller.tracker.heartbeat_state,
                ReservationHeartbeatState.STOPPED,
            )
            self.assertTrue(controller.abort())
            with Session() as db:
                self.assertEqual(db.query(FingerprintReservation).count(), 0)
            engine.dispose()

    def _run_concurrent(self, pool_size, requested_count):
        directory = tempfile.TemporaryDirectory()
        engine = _engine(f"sqlite:///{Path(directory.name) / 'tenant.db'}")
        Session = sessionmaker(bind=engine)
        pools = _pools(pool_size)
        payload = _payload(pools)
        barrier = threading.Barrier(2)
        results = {}
        controllers = {}
        failures = []
        lock = threading.Lock()

        def run(owner):
            controller = PlannerReservationController(
                logical_task_id=owner,
                session_factory=Session,
                configuration=ReservationLeaseConfiguration(30, 5),
            )
            try:
                barrier.wait()
                result = routes_dsl._plan_exact_main_visual_variants(
                    _SyntheticParser(pools), payload, requested_count,
                    historical_observer=_observer(Session),
                    reservation_controller=controller,
                )
                with lock:
                    results[owner] = result
                    controllers[owner] = controller
            except Exception as exc:
                controller.abort()
                with lock:
                    failures.append(exc)

        threads = [threading.Thread(target=run, args=(owner,)) for owner in ("task-a", "task-b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertFalse(failures)
        return directory, engine, results, controllers

    def test_two_real_planners_diversify_across_x_and_y(self):
        directory, engine, results, controllers = self._run_concurrent(2, 1)
        try:
            self.assertEqual(len(results), 2)
            fingerprints = {result.fingerprints[0] for result in results.values()}
            self.assertEqual(len(fingerprints), 2)
            self.assertEqual(
                sorted(result.historical_novelty_diagnostics.reservation_conflict_count for result in results.values()),
                [0, 1],
            )
        finally:
            for controller in controllers.values():
                controller.abort()
            engine.dispose()
            directory.cleanup()

    def test_single_candidate_reports_transient_reservation_exhaustion(self):
        directory, engine, results, controllers = self._run_concurrent(1, 1)
        try:
            counts = sorted(len(result.plans) for result in results.values())
            self.assertEqual(counts, [0, 1])
            blocked = next(result for result in results.values() if not result.plans)
            self.assertEqual(
                blocked.termination_reason,
                routes_dsl._PLANNING_RESERVATION_CONFLICT_EXHAUSTED,
            )
            self.assertEqual(
                blocked.historical_novelty_diagnostics.reservation_conflict_count,
                1,
            )
        finally:
            for controller in controllers.values():
                controller.abort()
            engine.dispose()
            directory.cleanup()

    def test_same_fingerprint_is_independent_in_two_tenant_databases(self):
        with tempfile.TemporaryDirectory() as directory:
            engines = [
                _engine(f"sqlite:///{Path(directory) / name}")
                for name in ("tenant-a.db", "tenant-b.db")
            ]
            pools = _pools(1)
            payload = _payload(pools)
            results = []
            controllers = []
            try:
                for index, engine in enumerate(engines):
                    Session = sessionmaker(bind=engine)
                    controller = PlannerReservationController(
                        logical_task_id=f"task-{index}",
                        session_factory=Session,
                        configuration=ReservationLeaseConfiguration(30, 5),
                    )
                    controllers.append(controller)
                    results.append(routes_dsl._plan_exact_main_visual_variants(
                        _SyntheticParser(pools), payload, 1,
                        reservation_controller=controller,
                    ))
                self.assertEqual(results[0].fingerprints, results[1].fingerprints)
                self.assertEqual([controller.conflict_count for controller in controllers], [0, 0])
            finally:
                for controller in controllers:
                    controller.abort()
                for engine in engines:
                    engine.dispose()


if __name__ == "__main__":
    unittest.main()
