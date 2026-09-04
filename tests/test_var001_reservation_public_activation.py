import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.api import routes_dsl
from src.api.fingerprint_ledger import (
    LEDGER_SCHEMA_VERSION,
    FingerprintIdentityRecord,
    FingerprintLedgerRepository,
    FingerprintOccurrenceRecord,
    FingerprintReservation,
    ensure_fingerprint_ledger_schema,
)
from src.api.models import Base, TaskHistory
from src.api.planner_reservation import (
    PlannerReservationController,
    PlannerReservationDecision,
    PlannerReservationError,
    PlannerReservationExecutionBinding,
    new_reservation_owner_attempt_id,
)
from src.api.reservation_lease import (
    ReservationLeaseConfiguration,
    ReservationLeaseTracker,
)
from src.api.schemas import RenderDSLRequest


class ReservationOwnerAttemptAndPublicGateTests(unittest.TestCase):
    """Owner-attempt isolation proofs while the public activation gate is closed."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.engines = []
        self.controllers = []
        self.engine, self.Session = self._database("tenant-a.db")
        self.configuration = ReservationLeaseConfiguration(30, 10)
        self.now = datetime(2026, 9, 4, 8, 0, 0)

    def tearDown(self):
        for controller in reversed(self.controllers):
            try:
                controller.abort()
            except Exception:
                pass
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

    def _controller(self, logical_task_id, *, Session=None, now=None, tracker=None):
        controller = PlannerReservationController(
            logical_task_id=logical_task_id,
            session_factory=Session or self.Session,
            configuration=self.configuration,
            now=now or (lambda: self.now),
            tracker=tracker,
        )
        self.controllers.append(controller)
        return controller

    @staticmethod
    def _identity(name):
        return FingerprintIdentityRecord(
            fingerprint_type="main_visual_planning",
            fingerprint_version=1,
            fingerprint_digest=f"digest-{name}",
            digest_algorithm="sha256",
            source_hash_algorithm="sha256",
            canonical_payload=f'{{"candidate":"{name}"}}',
        )

    @staticmethod
    def _acquire(controller, name, slot=0):
        return controller.acquire_candidate(
            ReservationOwnerAttemptAndPublicGateTests._identity(name),
            prospective_slot=slot,
        )

    def test_owner_attempt_ids_are_unique_uuid_values_for_same_logical_task(self):
        ids = {
            self._controller("repeatable-logical-task").reservation_owner_attempt_id
            for _ in range(128)
        }
        self.assertEqual(len(ids), 128)
        for owner_attempt_id in ids:
            self.assertEqual(str(uuid.UUID(owner_attempt_id)), owner_attempt_id)
            self.assertNotEqual(owner_attempt_id, "repeatable-logical-task")

    def test_same_logical_task_same_fingerprint_is_not_false_reacquire(self):
        first = self._controller("logical-task")
        second = self._controller("logical-task")
        first_outcome = self._acquire(first, "x")
        second_outcome = self._acquire(second, "x")

        self.assertEqual(first_outcome.decision, PlannerReservationDecision.OWNED)
        self.assertEqual(second_outcome.decision, PlannerReservationDecision.CONFLICT)
        self.assertNotEqual(
            first.reservation_owner_attempt_id,
            second.reservation_owner_attempt_id,
        )
        with self.Session() as session:
            row = session.scalar(select(FingerprintReservation))
            self.assertEqual(
                row.owner_task_id,
                first.reservation_owner_attempt_id,
            )
            self.assertNotEqual(row.owner_task_id, first.logical_task_id)

    def test_same_logical_task_different_fingerprints_can_use_slot_zero(self):
        first = self._controller("logical-task")
        second = self._controller("logical-task")
        self.assertEqual(
            self._acquire(first, "x").decision,
            PlannerReservationDecision.OWNED,
        )
        self.assertEqual(
            self._acquire(second, "y").decision,
            PlannerReservationDecision.OWNED,
        )
        with self.Session() as session:
            rows = session.scalars(select(FingerprintReservation)).all()
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {(row.owner_task_id, row.owner_slot_index) for row in rows},
                {
                    (first.reservation_owner_attempt_id, 0),
                    (second.reservation_owner_attempt_id, 0),
                },
            )

    def test_one_attempt_cannot_reuse_slot_zero_for_second_identity(self):
        controller = self._controller("logical-task")
        self.assertEqual(
            self._acquire(controller, "x").decision,
            PlannerReservationDecision.OWNED,
        )
        with self.assertRaisesRegex(
            PlannerReservationError,
            "PLANNER_RESERVATION_SLOT_ALIGNMENT_INVALID",
        ):
            self._acquire(controller, "y", slot=0)
        with self.Session() as session:
            self.assertEqual(session.query(FingerprintReservation).count(), 1)

    def test_owner_attempt_cannot_be_reused_as_child_execution_id(self):
        controller = self._controller("logical-task")
        identity = self._identity("x")
        self._acquire(controller, "x")
        binding = controller.bindings[0]
        execution_binding = PlannerReservationExecutionBinding(
            fingerprint_identity_id=binding.fingerprint_identity_id,
            logical_task_id=controller.logical_task_id,
            owner_attempt_id=controller.reservation_owner_attempt_id,
            owner_slot_index=0,
            execution_id=controller.reservation_owner_attempt_id,
        )
        planned = FingerprintOccurrenceRecord(
            **identity.__dict__,
            task_id=controller.logical_task_id,
            execution_id=controller.reservation_owner_attempt_id,
            child_index=0,
            lifecycle_event="PLANNED",
            provenance="phase3d2d-test",
        )
        with self.assertRaisesRegex(
            PlannerReservationError,
            "PLANNER_RESERVATION_EXECUTION_BINDING_ALIGNMENT_MISMATCH",
        ):
            controller.confirm_and_record_planned((execution_binding,), (planned,))

    def test_new_attempt_conflicts_while_old_attempt_is_live(self):
        first = self._controller("logical-task")
        retry = self._controller("logical-task")
        self.assertEqual(
            self._acquire(first, "x").decision,
            PlannerReservationDecision.OWNED,
        )
        self.assertEqual(
            self._acquire(retry, "x").decision,
            PlannerReservationDecision.CONFLICT,
        )

    def test_new_attempt_can_acquire_after_old_attempt_releases(self):
        first = self._controller("logical-task")
        self.assertEqual(
            self._acquire(first, "x").decision,
            PlannerReservationDecision.OWNED,
        )
        self.assertTrue(first.abort())

        retry = self._controller("logical-task")
        self.assertEqual(
            self._acquire(retry, "x").decision,
            PlannerReservationDecision.OWNED,
        )
        self.assertNotEqual(
            first.reservation_owner_attempt_id,
            retry.reservation_owner_attempt_id,
        )

    def test_new_attempt_can_take_over_after_old_attempt_expires(self):
        first = self._controller("logical-task", now=lambda: self.now)
        self.assertEqual(
            self._acquire(first, "x").decision,
            PlannerReservationDecision.OWNED,
        )
        retry_time = self.now + timedelta(seconds=30)
        retry = self._controller("logical-task", now=lambda: retry_time)
        self.assertEqual(
            self._acquire(retry, "x").decision,
            PlannerReservationDecision.OWNED,
        )
        with self.Session() as session:
            row = session.scalar(select(FingerprintReservation))
            self.assertEqual(row.owner_task_id, retry.reservation_owner_attempt_id)

    def test_schema_v2_legacy_owner_column_stores_attempt_identity(self):
        controller = self._controller("business-task")
        self._acquire(controller, "x")
        self.assertEqual(LEDGER_SCHEMA_VERSION, 2)
        self.assertNotIn("owner_attempt_id", FingerprintReservation.__table__.columns)
        with self.Session() as session:
            row = session.scalar(select(FingerprintReservation))
            self.assertEqual(
                row.owner_task_id,
                controller.reservation_owner_attempt_id,
            )
            self.assertNotEqual(row.owner_task_id, controller.logical_task_id)

    def test_same_attempt_string_has_no_cross_tenant_authority(self):
        _engine_b, SessionB = self._database("tenant-b.db")
        shared_attempt = new_reservation_owner_attempt_id()
        tracker_a = ReservationLeaseTracker(
            owner_attempt_id=shared_attempt,
            session_factory=self.Session,
            configuration=self.configuration,
            now=lambda: self.now,
        )
        tracker_b = ReservationLeaseTracker(
            owner_attempt_id=shared_attempt,
            session_factory=SessionB,
            configuration=self.configuration,
            now=lambda: self.now,
        )
        first = self._controller(
            "tenant-a-task",
            Session=self.Session,
            tracker=tracker_a,
        )
        second = self._controller(
            "tenant-b-task",
            Session=SessionB,
            tracker=tracker_b,
        )
        self.assertEqual(
            self._acquire(first, "x").decision,
            PlannerReservationDecision.OWNED,
        )
        self.assertEqual(
            self._acquire(second, "x").decision,
            PlannerReservationDecision.OWNED,
        )
        with self.Session() as session_a, SessionB() as session_b:
            self.assertEqual(session_a.query(FingerprintReservation).count(), 1)
            self.assertEqual(session_b.query(FingerprintReservation).count(), 1)

    def test_public_schema_cannot_control_reservation_authority(self):
        forbidden = {
            "reservation_conflict_mode",
            "reservation_owner_attempt_id",
            "owner_attempt_id",
            "reservation_lease_ttl_seconds",
            "reservation_heartbeat_interval_seconds",
            "execution_id",
        }
        self.assertTrue(forbidden.isdisjoint(RenderDSLRequest.model_fields))
        self.assertIsNone(
            routes_dsl.render_batch_worker.__kwdefaults__["reservation_controller"]
        )
        public_source = Path(routes_dsl.__file__).read_text(encoding="utf-8")
        public_source = public_source[public_source.index("def submit_dsl"):]
        self.assertNotIn("PlannerReservationController(", public_source)

    def test_repeated_logical_task_is_blocked_by_task_history_unique_contract(self):
        first = TaskHistory(
            task_id="caller-repeatable-session",
            prompt="first",
            batch_size=1,
            duration=0.1,
            output_assets=[],
        )
        second = TaskHistory(
            task_id="caller-repeatable-session",
            prompt="second",
            batch_size=1,
            duration=0.1,
            output_assets=[],
        )
        with self.Session() as session:
            session.add(first)
            session.commit()
        with self.Session() as session:
            session.add(second)
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()


if __name__ == "__main__":
    unittest.main()
