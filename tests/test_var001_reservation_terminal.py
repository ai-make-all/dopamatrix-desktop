import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from src.api import routes_dsl
from src.api.fingerprint_ledger import (
    FingerprintOccurrence,
    FingerprintReservation,
    ensure_fingerprint_ledger_schema,
)
from src.api.models import Base, LocalAsset, TaskHistory
from src.api.planner_reservation import (
    PlannerReservationAuthorityLost,
    PlannerReservationController,
    PlannerReservationExecutionBinding,
)
from src.api.reservation_lease import ReservationLeaseConfiguration
from src.api.schemas import RenderDSLRequest
from tests.test_var001_balanced_axis_coverage import (
    _SyntheticParser,
    _payload,
    _pools,
)


class ReservationTerminalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        db_path = Path(self.temporary.name) / "tenant.db"
        self.engine = create_engine(
            f"sqlite:///{db_path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        ensure_fingerprint_ledger_schema(self.engine)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.configuration = ReservationLeaseConfiguration(300, 100)

    def tearDown(self):
        self.engine.dispose()
        self.temporary.cleanup()

    def _controller(self, task_id):
        return PlannerReservationController(
            logical_task_id=task_id,
            session_factory=self.Session,
            configuration=self.configuration,
        )

    def _reserved_result(self, task_id, count=1):
        pools = _pools(max(2, count))
        payload = _payload(pools)
        result = routes_dsl._plan_exact_main_visual_variants(
            _SyntheticParser(pools), payload, count
        )
        controller = self._controller(task_id)
        for slot, fingerprint in enumerate(result.fingerprints):
            outcome = controller.acquire_candidate(
                routes_dsl._main_visual_fingerprint_identity_record(fingerprint),
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
            fatigue_asset_ids=routes_dsl._plan_fatigue_asset_ids(plan),
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
        )

    def _run_worker(self, task_id, payload, result, controller, worker=None):
        same_controller_seen = []

        def planner(*args, **kwargs):
            same_controller_seen.append(
                kwargs.get("reservation_controller") is controller
            )
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
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = routes_dsl.render_batch_worker(
                payload,
                task_id,
                tenant_id="tenant-a",
                batch_size=len(result.plans),
                variant_planning_policy="exact_main_visual",
                reservation_controller=controller,
            )
        self.assertEqual(same_controller_seen, [True])
        return terminal

    def test_public_contract_reservation_activation_defaults_off(self):
        self.assertEqual(
            RenderDSLRequest.model_fields["reservation_conflict_mode"].default,
            "OFF",
        )
        self.assertIsNone(
            routes_dsl.render_batch_worker.__kwdefaults__["reservation_controller"]
        )

    def test_same_controller_confirms_planned_fences_terminal_and_releases(self):
        task_id = "terminal-success"
        payload, result, controller = self._reserved_result(task_id, 2)
        terminal = self._run_worker(task_id, payload, result, controller)
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(terminal["succeededCount"], 2)
        tracker_bindings = controller.tracker.bindings()
        self.assertEqual(len(tracker_bindings), 2)
        self.assertTrue(all(binding.execution_id for binding in tracker_bindings))
        with self.Session() as db:
            occurrences = db.scalars(
                select(FingerprintOccurrence).order_by(
                    FingerprintOccurrence.child_index,
                    FingerprintOccurrence.lifecycle_event,
                )
            ).all()
            self.assertEqual(
                {row.lifecycle_event for row in occurrences},
                {"PLANNED", "RENDERED"},
            )
            self.assertEqual(len(occurrences), 4)
            self.assertEqual(len(db.scalars(select(TaskHistory)).all()), 1)
            self.assertEqual(len(db.scalars(select(FingerprintReservation)).all()), 0)

    def test_partial_confirmation_failure_rolls_back_all_and_starts_no_child(self):
        task_id = "confirm-rollback"
        payload, result, controller = self._reserved_result(task_id, 2)
        second = controller.bindings[1]
        with self.Session() as db:
            db.execute(
                update(FingerprintReservation)
                .where(
                    FingerprintReservation.fingerprint_identity_id
                    == second.fingerprint_identity_id
                )
                .values(owner_task_id="takeover")
            )
            db.commit()
        with (
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_variants_from_db",
                return_value=result,
            ),
            patch.object(routes_dsl, "render_worker") as worker,
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
            patch.object(controller, "abort", return_value=False),
        ):
            terminal = routes_dsl.render_batch_worker(
                payload,
                task_id,
                batch_size=2,
                variant_planning_policy="exact_main_visual",
                reservation_controller=controller,
            )
        worker.assert_not_called()
        self.assertEqual(terminal["errorCode"], "RESERVATION_AUTHORITY_LOST")
        with self.Session() as db:
            rows = db.scalars(select(FingerprintReservation)).all()
            retained = next(row for row in rows if row.owner_task_id == "takeover")
            first = next(
                row
                for row in rows
                if row.owner_task_id
                == controller.reservation_owner_attempt_id
            )
            self.assertIsNone(first.execution_id)
            self.assertIsNone(first.confirmed_at)
            self.assertIsNone(retained.execution_id)
            self.assertEqual(len(db.scalars(select(FingerprintOccurrence)).all()), 0)
        controller.abort()

    def test_confirm_commit_precedes_atomic_tracker_update(self):
        task_id = "commit-before-tracker"
        payload, result, controller = self._reserved_result(task_id, 1)
        fingerprint = result.fingerprints[0]
        child = routes_dsl._create_child_executions(task_id, 1)[0]
        work = routes_dsl._ChildWork(child, result.plans[0], fingerprint)
        binding = PlannerReservationExecutionBinding(
            fingerprint_identity_id=controller.bindings[0].fingerprint_identity_id,
            logical_task_id=task_id,
            owner_attempt_id=controller.reservation_owner_attempt_id,
            owner_slot_index=0,
            execution_id=child.execution_id,
        )
        record = routes_dsl._fingerprint_ledger_occurrence_record(
            work, task_id, "PLANNED"
        )
        original = controller.tracker.update_committed_execution_bindings

        def assert_committed_then_apply(updates):
            with self.Session() as db:
                reservation = db.get(
                    FingerprintReservation,
                    binding.fingerprint_identity_id,
                )
                self.assertEqual(reservation.execution_id, child.execution_id)
                self.assertEqual(
                    len(db.scalars(select(FingerprintOccurrence)).all()), 1
                )
            original(updates)

        with patch.object(
            controller.tracker,
            "update_committed_execution_bindings",
            side_effect=assert_committed_then_apply,
        ):
            controller.confirm_and_record_planned((binding,), (record,))
        controller.abort()

    def test_already_confirmed_retry_is_idempotent_and_rebind_fails(self):
        task_id = "confirm-retry"
        payload, result, controller = self._reserved_result(task_id, 1)
        fingerprint = result.fingerprints[0]
        child = routes_dsl._create_child_executions(task_id, 1)[0]
        work = routes_dsl._ChildWork(child, result.plans[0], fingerprint)
        binding = PlannerReservationExecutionBinding(
            fingerprint_identity_id=controller.bindings[0].fingerprint_identity_id,
            logical_task_id=task_id,
            owner_attempt_id=controller.reservation_owner_attempt_id,
            owner_slot_index=0,
            execution_id=child.execution_id,
        )
        record = routes_dsl._fingerprint_ledger_occurrence_record(
            work, task_id, "PLANNED"
        )
        controller.confirm_and_record_planned((binding,), (record,))
        controller.confirm_and_record_planned((binding,), (record,))
        replacement = replace(binding, execution_id="different-execution")
        replacement_record = replace(
            record,
            execution_id="different-execution",
        )
        with self.assertRaises(PlannerReservationAuthorityLost):
            controller.confirm_and_record_planned(
                (replacement,), (replacement_record,)
            )
        with self.Session() as db:
            reservation = db.get(
                FingerprintReservation, binding.fingerprint_identity_id
            )
            self.assertEqual(reservation.execution_id, child.execution_id)
            self.assertEqual(
                len(db.scalars(select(FingerprintOccurrence)).all()), 1
            )
        controller.abort()

    def test_tracker_update_failure_after_commit_starts_no_child_and_keeps_planned(self):
        task_id = "tracker-update-failure"
        payload, result, controller = self._reserved_result(task_id, 1)
        with (
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_variants_from_db",
                return_value=result,
            ),
            patch.object(
                controller.tracker,
                "update_committed_execution_bindings",
                side_effect=RuntimeError("local apply failed"),
            ),
            patch.object(routes_dsl, "render_worker") as worker,
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = routes_dsl.render_batch_worker(
                payload,
                task_id,
                batch_size=1,
                variant_planning_policy="exact_main_visual",
                reservation_controller=controller,
            )
        worker.assert_not_called()
        self.assertTrue(controller.tracker.lease_lost)
        self.assertEqual(terminal["errorCode"], "RESERVATION_AUTHORITY_LOST")
        with self.Session() as db:
            self.assertEqual(
                db.scalars(select(FingerprintOccurrence.lifecycle_event)).all(),
                ["PLANNED"],
            )
            self.assertEqual(len(db.scalars(select(TaskHistory)).all()), 0)

    def test_all_failed_path_is_fenced_and_preserves_no_history_semantics(self):
        task_id = "terminal-all-failed"
        payload, result, controller = self._reserved_result(task_id, 2)
        terminal = self._run_worker(
            task_id, payload, result, controller, worker=self._failed
        )
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["failedCount"], 2)
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events.count("PLANNED"), 2)
            self.assertEqual(events.count("FAILED"), 2)
            self.assertEqual(len(db.scalars(select(TaskHistory)).all()), 0)

    def test_takeover_after_child_computation_fences_assets_history_and_terminal(self):
        task_id = "stale-child"
        payload, result, controller = self._reserved_result(task_id, 1)
        identity_id = controller.bindings[0].fingerprint_identity_id

        def stale_success(*args, **kwargs):
            outcome = self._success(*args, **kwargs)
            with self.Session() as db:
                db.execute(
                    update(FingerprintReservation)
                    .where(
                        FingerprintReservation.fingerprint_identity_id
                        == identity_id
                    )
                    .values(owner_task_id="new-owner")
                )
                db.commit()
            return outcome

        terminal = self._run_worker(
            task_id, payload, result, controller, worker=stale_success
        )
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["errorCode"], "RESERVATION_AUTHORITY_LOST")
        self.assertNotIn("assets", terminal)
        self.assertTrue(controller.tracker.lease_lost)
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events, ["PLANNED"])
            self.assertEqual(len(db.scalars(select(TaskHistory)).all()), 0)

    def test_terminal_writer_failure_rolls_back_ledger_history_and_fatigue(self):
        with self.Session() as db:
            db.add(
                LocalAsset(
                    id=1,
                    file_hash="e" * 64,
                    file_path="asset-e.mp4",
                    asset_type="video",
                    usage_count=0,
                )
            )
            db.commit()
        task_id = "terminal-rollback"
        payload, result, controller = self._reserved_result(task_id, 1)

        def success_with_intent(*args, **kwargs):
            return replace(self._success(*args, **kwargs), fatigue_asset_ids=(1,))

        with patch.object(
            routes_dsl,
            "_build_task_history_record",
            side_effect=RuntimeError("history build failed"),
        ):
            terminal = self._run_worker(
                task_id, payload, result, controller, success_with_intent
            )
        self.assertEqual(
            terminal["errorCode"], "RESERVATION_TERMINAL_PERSIST_FAILED"
        )
        self.assertNotIn("assets", terminal)
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events, ["PLANNED"])
            self.assertEqual(len(db.scalars(select(TaskHistory)).all()), 0)
            self.assertEqual(db.get(LocalAsset, 1).usage_count, 0)

    def test_one_binding_loss_fences_whole_task_terminal_truth(self):
        task_id = "whole-task-loss"
        payload, result, controller = self._reserved_result(task_id, 2)
        lost_identity = controller.bindings[1].fingerprint_identity_id

        def lose_one_binding(plan, *args, **kwargs):
            outcome = self._success(plan, *args, **kwargs)
            if kwargs["child_index"] == 1:
                with self.Session() as db:
                    db.execute(
                        update(FingerprintReservation)
                        .where(
                            FingerprintReservation.fingerprint_identity_id
                            == lost_identity
                        )
                        .values(owner_task_id="replacement-task")
                    )
                    db.commit()
            return outcome

        terminal = self._run_worker(
            task_id, payload, result, controller, lose_one_binding
        )
        self.assertEqual(terminal["errorCode"], "RESERVATION_AUTHORITY_LOST")
        self.assertNotIn("assets", terminal)
        self.assertTrue(controller.tracker.lease_lost)
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events.count("PLANNED"), 2)
            self.assertEqual(events.count("RENDERED"), 0)
            self.assertEqual(events.count("FAILED"), 0)
            self.assertEqual(len(db.scalars(select(TaskHistory)).all()), 0)

    def test_cleanup_failure_after_terminal_commit_does_not_rewrite_truth(self):
        task_id = "cleanup-after-commit"
        payload, result, controller = self._reserved_result(task_id, 1)
        with patch.object(controller, "abort", return_value=False) as cleanup:
            terminal = self._run_worker(task_id, payload, result, controller)
        cleanup.assert_called_once_with()
        self.assertEqual(terminal["status"], "completed")
        with self.Session() as db:
            events = db.scalars(select(FingerprintOccurrence.lifecycle_event)).all()
            self.assertEqual(events.count("RENDERED"), 1)
            self.assertEqual(len(db.scalars(select(TaskHistory)).all()), 1)
            self.assertEqual(len(db.scalars(select(FingerprintReservation)).all()), 1)
        controller.abort()

    def test_authoritative_fatigue_commits_once_and_stale_fatigue_is_zero(self):
        with self.Session() as db:
            db.add(
                LocalAsset(
                    id=1,
                    file_hash="f" * 64,
                    file_path="asset.mp4",
                    asset_type="video",
                    usage_count=0,
                )
            )
            db.commit()

        task_id = "fatigue-success"
        payload, result, controller = self._reserved_result(task_id, 1)
        plan = result.plans[0]

        def success_with_intent(*args, **kwargs):
            outcome = self._success(*args, **kwargs)
            return replace(outcome, fatigue_asset_ids=(1,))

        self._run_worker(task_id, payload, result, controller, success_with_intent)
        with self.Session() as db:
            self.assertEqual(db.get(LocalAsset, 1).usage_count, 1)

        stale_task = "fatigue-stale"
        payload, result, controller = self._reserved_result(stale_task, 1)
        identity_id = controller.bindings[0].fingerprint_identity_id

        def stale_with_intent(*args, **kwargs):
            outcome = success_with_intent(*args, **kwargs)
            with self.Session() as db:
                db.execute(
                    update(FingerprintReservation)
                    .where(
                        FingerprintReservation.fingerprint_identity_id
                        == identity_id
                    )
                    .values(owner_task_id="new-owner")
                )
                db.commit()
            return outcome

        self._run_worker(stale_task, payload, result, controller, stale_with_intent)
        with self.Session() as db:
            self.assertEqual(db.get(LocalAsset, 1).usage_count, 1)


if __name__ == "__main__":
    unittest.main()
