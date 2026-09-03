import math
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from src.api.fingerprint_ledger import (
    LEDGER_SCHEMA_VERSION,
    FingerprintIdentityRecord,
    FingerprintLedgerRepository,
    FingerprintReservation,
    FingerprintReservationBatchRenewalError,
    ReservationAuthorityStatus,
    ReservationConfirmationStatus,
    ReservationRenewRequest,
    ReservationRenewStatus,
    ensure_fingerprint_ledger_schema,
)
from src.api.reservation_lease import (
    RESERVATION_HEARTBEAT_INTERVAL_ENV,
    RESERVATION_LEASE_TTL_ENV,
    ReservationLeaseConfiguration,
    ReservationLeaseConfigurationError,
    ReservationHeartbeatState,
    ReservationLeaseState,
    ReservationLeaseTracker,
    ReservationLeaseTrackerError,
    load_reservation_lease_configuration,
)


def _wait_until(predicate, *, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _identity(index=0):
    return FingerprintIdentityRecord(
        fingerprint_type="main_visual_planning",
        fingerprint_version=1,
        fingerprint_digest=f"{index + 1:064x}",
        digest_algorithm="sha256",
        source_hash_algorithm="md5",
        canonical_payload=f'{{"identity":{index}}}',
    )


def _engine(url="sqlite://"):
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    ensure_fingerprint_ledger_schema(engine)
    return engine


def _acquire(db, identity, *, owner="task-a", slot=0, now, expires_at):
    return FingerprintLedgerRepository(db).acquire_reservation(
        identity,
        owner_task_id=owner,
        owner_slot_index=slot,
        now=now,
        expires_at=expires_at,
    )


class ReservationLeaseConfigurationTests(unittest.TestCase):
    def test_absent_environment_is_valid_unconfigured_configuration(self):
        configuration = load_reservation_lease_configuration({})
        self.assertFalse(configuration.configured)
        with self.assertRaisesRegex(
            ReservationLeaseConfigurationError,
            "RESERVATION_LEASE_CONFIGURATION_UNAVAILABLE",
        ):
            configuration.require_configured()

    def test_environment_values_are_explicit_and_validated(self):
        configuration = load_reservation_lease_configuration({
            RESERVATION_LEASE_TTL_ENV: "90",
            RESERVATION_HEARTBEAT_INTERVAL_ENV: "30",
        })
        self.assertTrue(configuration.configured)
        self.assertEqual(configuration.reservation_lease_ttl_seconds, 90.0)
        self.assertEqual(configuration.reservation_heartbeat_interval_seconds, 30.0)

    def test_incomplete_and_non_numeric_environment_are_rejected(self):
        cases = (
            ({RESERVATION_LEASE_TTL_ENV: "90"}, "CONFIGURATION_INCOMPLETE"),
            ({RESERVATION_HEARTBEAT_INTERVAL_ENV: "30"}, "CONFIGURATION_INCOMPLETE"),
            ({RESERVATION_LEASE_TTL_ENV: "x", RESERVATION_HEARTBEAT_INTERVAL_ENV: "1"},
             "CONFIGURATION_VALUE_INVALID"),
        )
        for environment, error in cases:
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(ReservationLeaseConfigurationError, error):
                    load_reservation_lease_configuration(environment)

    def test_numeric_contract_rejects_invalid_values(self):
        invalid = (
            (0, 0.1),
            (-1, 0.1),
            (math.nan, 0.1),
            (math.inf, 0.1),
            (3, 0),
            (3, -1),
            (3, math.nan),
            (3, math.inf),
            (True, 0.1),
            (3, False),
            (3, 1.01),
        )
        for ttl, interval in invalid:
            with self.subTest(ttl=ttl, interval=interval):
                with self.assertRaises(ReservationLeaseConfigurationError):
                    ReservationLeaseConfiguration(ttl, interval)


class FingerprintReservationRenewalTests(unittest.TestCase):
    def setUp(self):
        self.engine = _engine()
        self.Session = sessionmaker(bind=self.engine)
        self.now = datetime(2026, 9, 3, 8, 0, 0)

    def tearDown(self):
        self.engine.dispose()

    def test_unconfirmed_renewal_preserves_binding_metadata(self):
        original_expiry = self.now + timedelta(seconds=30)
        with self.Session() as db:
            acquired = _acquire(
                db, _identity(), now=self.now, expires_at=original_expiry
            )
            db.commit()
            original = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
            created_at = original.created_at

        renewed_at = self.now + timedelta(seconds=10)
        new_expiry = self.now + timedelta(seconds=60)
        with self.Session() as db:
            result = FingerprintLedgerRepository(db).renew_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
                now=renewed_at,
                expires_at=new_expiry,
            )
            db.commit()
            row = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
            self.assertEqual(result.status, ReservationRenewStatus.RENEWED)
            self.assertEqual(row.created_at, created_at)
            self.assertEqual(row.updated_at, renewed_at)
            self.assertEqual(row.expires_at, new_expiry)
            self.assertIsNone(row.execution_id)
            self.assertIsNone(row.confirmed_at)

    def test_confirmed_renewal_preserves_first_binding(self):
        with self.Session() as db:
            acquired = _acquire(
                db,
                _identity(),
                now=self.now,
                expires_at=self.now + timedelta(seconds=30),
            )
            repository = FingerprintLedgerRepository(db)
            status = repository.confirm_reservation_detailed(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
                execution_id="exec-1",
                now=self.now + timedelta(seconds=1),
            )
            self.assertEqual(status, ReservationConfirmationStatus.CONFIRMED)
            db.commit()
            original = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
            created_at = original.created_at
            confirmed_at = original.confirmed_at

        with self.Session() as db:
            result = FingerprintLedgerRepository(db).renew_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
                expected_execution_id="exec-1",
                now=self.now + timedelta(seconds=10),
                expires_at=self.now + timedelta(seconds=60),
            )
            db.commit()
            row = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
            self.assertEqual(result.status, ReservationRenewStatus.RENEWED)
            self.assertEqual(row.created_at, created_at)
            self.assertEqual(row.confirmed_at, confirmed_at)
            self.assertEqual(row.execution_id, "exec-1")

    def test_expired_reservation_cannot_be_renewed_or_rewritten(self):
        expiry = self.now + timedelta(seconds=10)
        with self.Session() as db:
            acquired = _acquire(db, _identity(), now=self.now, expires_at=expiry)
            repository = FingerprintLedgerRepository(db)
            repository.confirm_reservation_detailed(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
                execution_id="exec-1",
                now=self.now + timedelta(seconds=1),
            )
            db.commit()
            before = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
            values = (before.created_at, before.updated_at, before.expires_at,
                      before.confirmed_at, before.execution_id)

        for observed_at in (expiry, expiry + timedelta(seconds=1)):
            with self.Session() as db:
                result = FingerprintLedgerRepository(db).renew_reservation(
                    acquired.fingerprint_identity_id,
                    owner_task_id="task-a",
                    owner_slot_index=0,
                    expected_execution_id="exec-1",
                    now=observed_at,
                    expires_at=observed_at + timedelta(seconds=30),
                )
                db.commit()
                self.assertEqual(
                    result.status,
                    ReservationRenewStatus.OWNER_OR_EXPIRY_CONFLICT,
                )
        with self.Session() as db:
            row = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
            self.assertEqual(
                (row.created_at, row.updated_at, row.expires_at,
                 row.confirmed_at, row.execution_id),
                values,
            )

    def test_wrong_owner_slot_and_execution_are_classified_without_mutation(self):
        with self.Session() as db:
            acquired = _acquire(
                db, _identity(), now=self.now,
                expires_at=self.now + timedelta(seconds=60),
            )
            repository = FingerprintLedgerRepository(db)
            repository.confirm_reservation_detailed(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a", owner_slot_index=0,
                execution_id="exec-1", now=self.now + timedelta(seconds=1),
            )
            db.commit()

        cases = (
            ("task-b", 0, "exec-1", ReservationRenewStatus.OWNER_OR_EXPIRY_CONFLICT),
            ("task-a", 1, "exec-1", ReservationRenewStatus.OWNER_OR_EXPIRY_CONFLICT),
            ("task-a", 0, "exec-2", ReservationRenewStatus.EXECUTION_BINDING_CONFLICT),
        )
        for owner, slot, execution, expected in cases:
            with self.subTest(owner=owner, slot=slot, execution=execution):
                with self.Session() as db:
                    result = FingerprintLedgerRepository(db).renew_reservation(
                        acquired.fingerprint_identity_id,
                        owner_task_id=owner,
                        owner_slot_index=slot,
                        expected_execution_id=execution,
                        now=self.now + timedelta(seconds=2),
                        expires_at=self.now + timedelta(seconds=120),
                    )
                    db.rollback()
                    self.assertEqual(result.status, expected)
        with self.Session() as db:
            row = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
            self.assertEqual(row.execution_id, "exec-1")
            self.assertEqual(row.expires_at, self.now + timedelta(seconds=60))

    def test_authority_verification_uses_owner_expiry_and_execution(self):
        with self.Session() as db:
            acquired = _acquire(
                db, _identity(), now=self.now,
                expires_at=self.now + timedelta(seconds=30),
            )
            repository = FingerprintLedgerRepository(db)
            self.assertEqual(
                repository.verify_reservation_authority(
                    acquired.fingerprint_identity_id,
                    owner_task_id="task-a", owner_slot_index=0,
                    now=self.now + timedelta(seconds=1),
                ).status,
                ReservationAuthorityStatus.CURRENT,
            )
            repository.confirm_reservation_detailed(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a", owner_slot_index=0,
                execution_id="exec-1", now=self.now + timedelta(seconds=2),
            )
            self.assertEqual(
                repository.verify_reservation_authority(
                    acquired.fingerprint_identity_id,
                    owner_task_id="task-a", owner_slot_index=0,
                    expected_execution_id="exec-1",
                    now=self.now + timedelta(seconds=3),
                ).status,
                ReservationAuthorityStatus.CURRENT,
            )
            self.assertEqual(
                repository.verify_reservation_authority(
                    acquired.fingerprint_identity_id,
                    owner_task_id="task-a", owner_slot_index=0,
                    now=self.now + timedelta(seconds=3),
                ).status,
                ReservationAuthorityStatus.EXECUTION_BINDING_CONFLICT,
            )

    def test_batch_renewal_updates_all_bindings(self):
        requests = []
        with self.Session() as db:
            for index in range(3):
                acquired = _acquire(
                    db, _identity(index), owner="task-a", slot=index,
                    now=self.now, expires_at=self.now + timedelta(seconds=30),
                )
                requests.append(ReservationRenewRequest(
                    acquired.fingerprint_identity_id, "task-a", index
                ))
            db.commit()
        new_expiry = self.now + timedelta(seconds=90)
        with self.Session() as db:
            results = FingerprintLedgerRepository(db).renew_reservations(
                requests, now=self.now + timedelta(seconds=5), expires_at=new_expiry
            )
            db.commit()
            self.assertEqual(len(results), 3)
            rows = db.scalars(select(FingerprintReservation)).all()
            self.assertEqual({row.expires_at for row in rows}, {new_expiry})

    def test_batch_renewal_savepoint_rolls_back_every_binding(self):
        requests = []
        original_expiry = self.now + timedelta(seconds=30)
        with self.Session() as db:
            for index in range(3):
                acquired = _acquire(
                    db, _identity(index), owner="task-a", slot=index,
                    now=self.now, expires_at=original_expiry,
                )
                requests.append(ReservationRenewRequest(
                    acquired.fingerprint_identity_id,
                    "task-a",
                    99 if index == 1 else index,
                ))
            db.commit()

        with self.Session() as db:
            with self.assertRaises(FingerprintReservationBatchRenewalError):
                FingerprintLedgerRepository(db).renew_reservations(
                    requests,
                    now=self.now + timedelta(seconds=5),
                    expires_at=self.now + timedelta(seconds=90),
                )
            db.commit()
        with self.Session() as db:
            rows = db.scalars(select(FingerprintReservation)).all()
            self.assertEqual({row.expires_at for row in rows}, {original_expiry})

    def test_old_owner_cannot_renew_after_file_backed_takeover(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = _engine(f"sqlite:///{Path(directory) / 'tenant.db'}")
            Session = sessionmaker(bind=engine)
            expiry = self.now + timedelta(seconds=5)
            with Session() as db:
                first = _acquire(db, _identity(), now=self.now, expires_at=expiry)
                db.commit()
            barrier = threading.Barrier(2)
            results = {}
            failures = []
            result_lock = threading.Lock()

            def renew_old_owner():
                try:
                    with Session() as db:
                        barrier.wait()
                        result = FingerprintLedgerRepository(db).renew_reservation(
                            first.fingerprint_identity_id,
                            owner_task_id="task-a", owner_slot_index=0,
                            now=expiry,
                            expires_at=expiry + timedelta(seconds=60),
                        )
                        db.commit()
                    with result_lock:
                        results["renew"] = result
                except Exception as exc:
                    with result_lock:
                        failures.append(exc)

            def acquire_new_owner():
                try:
                    with Session() as db:
                        barrier.wait()
                        result = _acquire(
                            db, _identity(), owner="task-b", slot=1,
                            now=expiry, expires_at=expiry + timedelta(seconds=30),
                        )
                        db.commit()
                    with result_lock:
                        results["takeover"] = result
                except Exception as exc:
                    with result_lock:
                        failures.append(exc)

            threads = [
                threading.Thread(target=renew_old_owner),
                threading.Thread(target=acquire_new_owner),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
            self.assertFalse(failures)
            self.assertEqual(
                results["takeover"].fingerprint_identity_id,
                first.fingerprint_identity_id,
            )
            self.assertEqual(
                results["renew"].status,
                ReservationRenewStatus.OWNER_OR_EXPIRY_CONFLICT,
            )
            with Session() as db:
                row = db.get(FingerprintReservation, first.fingerprint_identity_id)
                self.assertEqual((row.owner_task_id, row.owner_slot_index), ("task-b", 1))
            engine.dispose()


class ReservationLeaseTrackerTests(unittest.TestCase):
    def setUp(self):
        self.engine = _engine()
        self.Session = sessionmaker(bind=self.engine)
        self.base = datetime(2026, 9, 3, 8, 0, 0)
        self.config = ReservationLeaseConfiguration(30, 5)

    def tearDown(self):
        self.engine.dispose()

    def _registered_tracker(self, *, expiry=None, session_factory=None):
        expires_at = expiry or self.base + timedelta(seconds=20)
        with self.Session() as db:
            acquired = _acquire(
                db, _identity(), now=self.base, expires_at=expires_at
            )
            db.commit()
        tracker = ReservationLeaseTracker(
            owner_task_id="task-a",
            session_factory=session_factory or self.Session,
            configuration=self.config,
            now=lambda: self.base + timedelta(seconds=1),
        )
        tracker.register_binding(
            fingerprint_identity_id=acquired.fingerprint_identity_id,
            owner_slot_index=0,
            expires_at=expires_at,
        )
        return tracker, acquired.fingerprint_identity_id

    def test_start_requires_binding_and_stop_does_not_release(self):
        tracker = ReservationLeaseTracker(
            owner_task_id="task-a",
            session_factory=self.Session,
            configuration=self.config,
        )
        self.assertFalse(tracker.start())
        tracker, identity_id = self._registered_tracker()
        self.assertTrue(tracker.stop())
        self.assertEqual(tracker.state, ReservationLeaseState.ACTIVE)
        self.assertEqual(
            tracker.heartbeat_state,
            ReservationHeartbeatState.STOPPED,
        )
        self.assertFalse(tracker.start())
        with self.Session() as db:
            self.assertIsNotNone(db.get(FingerprintReservation, identity_id))

    def test_execution_binding_update_controls_future_renewal(self):
        tracker, identity_id = self._registered_tracker()
        with self.Session() as db:
            status = FingerprintLedgerRepository(db).confirm_reservation_detailed(
                identity_id,
                owner_task_id="task-a", owner_slot_index=0,
                execution_id="exec-1", now=self.base + timedelta(seconds=1),
            )
            db.commit()
        self.assertEqual(status, ReservationConfirmationStatus.CONFIRMED)
        self.assertTrue(tracker.run_renewal_cycle(now=self.base + timedelta(seconds=2)))
        self.assertEqual(tracker.state, ReservationLeaseState.ACTIVE)
        tracker.update_execution_binding(identity_id, "exec-1")
        tracker.update_execution_binding(identity_id, "exec-1")
        self.assertTrue(tracker.run_renewal_cycle(now=self.base + timedelta(seconds=3)))
        with self.assertRaisesRegex(
            ReservationLeaseTrackerError,
            "RESERVATION_LEASE_EXECUTION_REBIND_FORBIDDEN",
        ):
            tracker.update_execution_binding(identity_id, "exec-2")
        with self.Session() as db:
            row = db.get(FingerprintReservation, identity_id)
            self.assertEqual(row.execution_id, "exec-1")
            self.assertIsNotNone(row.confirmed_at)

    def test_multi_binding_conflict_rolls_back_cycle_and_loses_whole_task(self):
        original_expiry = self.base + timedelta(seconds=20)
        acquired_ids = []
        with self.Session() as db:
            for index in range(3):
                acquired = _acquire(
                    db, _identity(index), owner="task-a", slot=index,
                    now=self.base, expires_at=original_expiry,
                )
                acquired_ids.append(acquired.fingerprint_identity_id)
            db.commit()
        tracker = ReservationLeaseTracker(
            owner_task_id="task-a",
            session_factory=self.Session,
            configuration=self.config,
        )
        for index, identity_id in enumerate(acquired_ids):
            tracker.register_binding(
                fingerprint_identity_id=identity_id,
                owner_slot_index=99 if index == 1 else index,
                expires_at=original_expiry,
            )
        self.assertFalse(tracker.run_renewal_cycle(now=self.base + timedelta(seconds=2)))
        self.assertEqual(tracker.state, ReservationLeaseState.LEASE_LOST)
        with self.Session() as db:
            rows = db.scalars(select(FingerprintReservation)).all()
            self.assertEqual({row.expires_at for row in rows}, {original_expiry})

    def test_infrastructure_failure_retries_before_known_expiry(self):
        calls = 0

        def session_factory():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OperationalError(
                    "renew", {}, sqlite3.OperationalError("temporarily unavailable")
                )
            return self.Session()

        tracker, identity_id = self._registered_tracker(
            expiry=self.base + timedelta(seconds=20),
            session_factory=session_factory,
        )
        self.assertFalse(tracker.run_renewal_cycle(now=self.base + timedelta(seconds=5)))
        self.assertEqual(tracker.state, ReservationLeaseState.ACTIVE)
        self.assertTrue(tracker.run_renewal_cycle(now=self.base + timedelta(seconds=6)))
        self.assertEqual(tracker.state, ReservationLeaseState.ACTIVE)
        self.assertEqual(tracker.infrastructure_failure_count, 1)
        with self.Session() as db:
            self.assertEqual(
                db.get(FingerprintReservation, identity_id).expires_at,
                self.base + timedelta(seconds=36),
            )

    def test_infrastructure_failure_through_expiry_is_irreversible(self):
        def unavailable():
            raise OperationalError(
                "renew", {}, sqlite3.OperationalError("unavailable")
            )

        tracker, _ = self._registered_tracker(
            expiry=self.base + timedelta(seconds=10),
            session_factory=unavailable,
        )
        self.assertFalse(tracker.run_renewal_cycle(now=self.base + timedelta(seconds=5)))
        self.assertEqual(tracker.state, ReservationLeaseState.ACTIVE)
        self.assertFalse(tracker.run_renewal_cycle(now=self.base + timedelta(seconds=10)))
        self.assertEqual(tracker.state, ReservationLeaseState.LEASE_LOST)
        self.assertFalse(tracker.run_renewal_cycle(now=self.base + timedelta(seconds=11)))
        self.assertEqual(tracker.state, ReservationLeaseState.LEASE_LOST)

    def test_infrastructure_failure_uses_fresh_time_after_blocking(self):
        entered = threading.Event()
        release = threading.Event()
        fresh_now = [self.base + timedelta(seconds=1)]

        def blocked_unavailable():
            entered.set()
            release.wait(timeout=5)
            raise OperationalError(
                "renew", {}, sqlite3.OperationalError("temporarily unavailable")
            )

        tracker, _ = self._registered_tracker(
            expiry=self.base + timedelta(seconds=10),
            session_factory=blocked_unavailable,
        )
        tracker._now = lambda: fresh_now[0]
        outcome = []
        thread = threading.Thread(
            target=lambda: outcome.append(
                tracker.run_renewal_cycle(now=self.base + timedelta(seconds=1))
            )
        )
        thread.start()
        self.assertTrue(entered.wait(timeout=2))
        fresh_now[0] = self.base + timedelta(seconds=11)
        release.set()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, [False])
        self.assertEqual(tracker.state, ReservationLeaseState.LEASE_LOST)
        self.assertEqual(tracker.terminal_failure_category, "OperationalError")

    def test_conflict_marks_whole_tracker_lease_lost(self):
        expiry = self.base + timedelta(seconds=5)
        tracker, identity_id = self._registered_tracker(expiry=expiry)
        with self.Session() as db:
            _acquire(
                db, _identity(), owner="task-b", slot=1,
                now=expiry, expires_at=expiry + timedelta(seconds=30),
            )
            db.commit()
        self.assertFalse(tracker.run_renewal_cycle(now=expiry + timedelta(seconds=1)))
        self.assertEqual(tracker.state, ReservationLeaseState.LEASE_LOST)
        with self.Session() as db:
            self.assertEqual(
                db.get(FingerprintReservation, identity_id).owner_task_id,
                "task-b",
            )

    def test_heartbeat_runs_multiple_cycles_and_stop_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = _engine(f"sqlite:///{Path(directory) / 'tenant.db'}")
            Session = sessionmaker(bind=engine)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            with Session() as db:
                acquired = _acquire(
                    db, _identity(), now=now,
                    expires_at=now + timedelta(seconds=0.3),
                )
                db.commit()
            calls = 0
            lock = threading.Lock()
            def counted_session():
                nonlocal calls
                with lock:
                    calls += 1
                return Session()

            tracker = ReservationLeaseTracker(
                owner_task_id="task-a",
                session_factory=counted_session,
                configuration=ReservationLeaseConfiguration(0.6, 0.05),
            )
            tracker.register_binding(
                fingerprint_identity_id=acquired.fingerprint_identity_id,
                owner_slot_index=0,
                expires_at=now + timedelta(seconds=0.3),
            )
            self.assertTrue(tracker.start())
            self.assertTrue(_wait_until(lambda: calls >= 3))
            self.assertTrue(tracker.stop(join_timeout_seconds=1))
            calls_after_stop = calls
            time.sleep(0.05)
            self.assertGreaterEqual(calls_after_stop, 3)
            self.assertEqual(calls, calls_after_stop)
            self.assertEqual(tracker.state, ReservationLeaseState.ACTIVE)
            self.assertEqual(
                tracker.heartbeat_state,
                ReservationHeartbeatState.STOPPED,
            )
            with Session() as db:
                row = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
                self.assertGreater(row.expires_at, now + timedelta(seconds=0.3))
                self.assertEqual(row.owner_task_id, "task-a")
                self.assertIsNone(row.execution_id)
            engine.dispose()

    def test_stop_remains_bounded_while_one_renewal_session_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = _engine(f"sqlite:///{Path(directory) / 'tenant.db'}")
            Session = sessionmaker(bind=engine)
            entered = threading.Event()
            release = threading.Event()
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            original_expiry = now + timedelta(seconds=20)

            with Session() as db:
                acquired = _acquire(
                    db,
                    _identity(),
                    now=now,
                    expires_at=original_expiry,
                )
                db.commit()

            def blocked_session_factory():
                entered.set()
                release.wait(timeout=5)
                return Session()

            tracker = ReservationLeaseTracker(
                owner_task_id="task-a",
                session_factory=blocked_session_factory,
                configuration=ReservationLeaseConfiguration(30, 0.05),
            )
            tracker.register_binding(
                fingerprint_identity_id=acquired.fingerprint_identity_id,
                owner_slot_index=0,
                expires_at=original_expiry,
            )
            try:
                self.assertTrue(tracker.start())
                self.assertTrue(entered.wait(timeout=2))
                started = time.monotonic()
                self.assertFalse(tracker.stop(join_timeout_seconds=0.02))
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertEqual(
                    tracker.heartbeat_state,
                    ReservationHeartbeatState.STOPPING,
                )
                self.assertEqual(tracker.state, ReservationLeaseState.ACTIVE)
                self.assertFalse(tracker.start())
                with self.assertRaisesRegex(
                    ReservationLeaseTrackerError,
                    "RESERVATION_LEASE_TRACKER_NOT_ACTIVE",
                ):
                    tracker.register_binding(
                        fingerprint_identity_id=999,
                        owner_slot_index=1,
                        expires_at=original_expiry,
                    )
                with self.assertRaisesRegex(
                    ReservationLeaseTrackerError,
                    "RESERVATION_LEASE_TRACKER_NOT_ACTIVE",
                ):
                    tracker.update_execution_binding(
                        acquired.fingerprint_identity_id,
                        "exec-1",
                    )
            finally:
                release.set()
            self.assertTrue(_wait_until(
                lambda: tracker.heartbeat_state is ReservationHeartbeatState.STOPPED
            ))
            with Session() as db:
                committed_expiry = db.get(
                    FingerprintReservation,
                    acquired.fingerprint_identity_id,
                ).expires_at
            self.assertGreater(committed_expiry, original_expiry)
            time.sleep(0.1)
            with Session() as db:
                self.assertEqual(
                    db.get(
                        FingerprintReservation,
                        acquired.fingerprint_identity_id,
                    ).expires_at,
                    committed_expiry,
                )
            self.assertTrue(tracker.stop(join_timeout_seconds=0))
            self.assertFalse(tracker.start())
            engine.dispose()

    def test_wait_callback_failure_marks_lease_lost_and_quiesces(self):
        tracker, _ = self._registered_tracker()

        def broken_wait(_interval):
            raise RuntimeError("unexpected wait failure with private detail")

        tracker._heartbeat_wait = broken_wait
        self.assertTrue(tracker.start())
        self.assertTrue(_wait_until(
            lambda: tracker.heartbeat_state is ReservationHeartbeatState.STOPPED
        ))
        self.assertEqual(tracker.state, ReservationLeaseState.LEASE_LOST)
        self.assertTrue(tracker.lease_lost)
        self.assertEqual(tracker.terminal_failure_category, "RuntimeError")

    def test_post_commit_local_apply_failure_marks_lease_lost(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = _engine(f"sqlite:///{Path(directory) / 'tenant.db'}")
            Session = sessionmaker(bind=engine)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            original_expiry = now + timedelta(seconds=20)
            with Session() as db:
                acquired = _acquire(
                    db,
                    _identity(),
                    now=now,
                    expires_at=original_expiry,
                )
                db.commit()
            tracker = ReservationLeaseTracker(
                owner_task_id="task-a",
                session_factory=Session,
                configuration=self.config,
                heartbeat_wait=lambda _interval: False,
            )
            tracker.register_binding(
                fingerprint_identity_id=acquired.fingerprint_identity_id,
                owner_slot_index=0,
                expires_at=original_expiry,
            )
            with patch(
                "src.api.reservation_lease.replace",
                side_effect=RuntimeError("local apply failure with private detail"),
            ):
                self.assertTrue(tracker.start())
                self.assertTrue(_wait_until(
                    lambda: (
                        tracker.heartbeat_state
                        is ReservationHeartbeatState.STOPPED
                    )
                ))
            self.assertEqual(tracker.state, ReservationLeaseState.LEASE_LOST)
            self.assertEqual(tracker.terminal_failure_category, "RuntimeError")
            with Session() as db:
                self.assertGreater(
                    db.get(
                        FingerprintReservation,
                        acquired.fingerprint_identity_id,
                    ).expires_at,
                    original_expiry,
                )
            engine.dispose()

    def test_stop_after_lease_loss_preserves_authority_truth(self):
        expiry = self.base + timedelta(seconds=5)
        tracker, _ = self._registered_tracker(expiry=expiry)
        with self.Session() as db:
            _acquire(
                db,
                _identity(),
                owner="task-b",
                slot=1,
                now=expiry,
                expires_at=expiry + timedelta(seconds=30),
            )
            db.commit()
        self.assertFalse(tracker.run_renewal_cycle(now=expiry))
        self.assertEqual(tracker.state, ReservationLeaseState.LEASE_LOST)
        self.assertTrue(tracker.stop())
        self.assertEqual(tracker.state, ReservationLeaseState.LEASE_LOST)
        self.assertTrue(tracker.lease_lost)
        self.assertEqual(
            tracker.heartbeat_state,
            ReservationHeartbeatState.STOPPED,
        )
        self.assertFalse(tracker.start())

    def test_schema_version_remains_v2(self):
        self.assertEqual(LEDGER_SCHEMA_VERSION, 2)


if __name__ == "__main__":
    unittest.main()
