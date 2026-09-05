import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.api import routes_dsl
from src.api.models import Base, TaskHistory, VideoTask
from src.api.public_task_admission import (
    PublicTaskAdmissionStateError,
    admit_public_task,
    transition_public_task_status,
)


class _SecondSubmitFailsPool:
    def __init__(self, original_error: Exception, child_finished: Event):
        self._pool = RealThreadPoolExecutor(max_workers=1)
        self._original_error = original_error
        self._child_finished = child_finished
        self._submit_count = 0
        self.exited = False

    def __enter__(self):
        self._pool.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            return self._pool.__exit__(exc_type, exc, traceback)
        finally:
            self.exited = True

    def submit(self, function, *args, **kwargs):
        self._submit_count += 1
        if self._submit_count == 2:
            raise self._original_error

        def _run_first():
            try:
                return function(*args, **kwargs)
            finally:
                self._child_finished.set()

        return self._pool.submit(_run_first)


class PublicTaskLifecycleGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        path = Path(self.temporary.name) / "tenant.db"
        self.engine = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()
        self.temporary.cleanup()

    def _admit(self, *, batch_size=1):
        return admit_public_task(
            self.engine,
            prompt="lifecycle guard",
            batch_size=batch_size,
        )

    def _task(self, task_id):
        with self.Session() as session:
            return session.scalar(
                select(VideoTask).where(VideoTask.task_id == task_id)
            )

    def _run(self, task_id, *, batch_size=1):
        return routes_dsl.render_batch_worker(
            None,
            task_id,
            tenant_id="tenant-a",
            prompt="lifecycle guard",
            batch_size=batch_size,
            variant_planning_policy="legacy",
            public_task_admitted=True,
        )

    @staticmethod
    def _successful_child(_plan, _task_id, *_args, **kwargs):
        return routes_dsl._ChildResult(
            child_index=kwargs["child_index"],
            execution_id=kwargs["execution_id"],
            file_sid=_args[6],
            outcome="succeeded",
            assets=[{"file_path": "final.mp4", "file_hash": "hash"}],
            elapsed=0.1,
            error_code=None,
            error_message=None,
            prompt_details={"meta": None, "timeline": []},
        )

    @staticmethod
    def _failed_child(_plan, _task_id, *_args, **kwargs):
        return routes_dsl._ChildResult(
            child_index=kwargs["child_index"],
            execution_id=kwargs["execution_id"],
            file_sid=_args[6],
            outcome="failed",
            assets=[],
            elapsed=0.1,
            error_code="CONTROLLED_FAILURE",
            error_message="controlled",
            prompt_details={"meta": None, "timeline": []},
        )

    def test_uncaught_child_id_allocation_finalizes_task(self):
        admission = self._admit()
        original = RuntimeError("child identity allocation failed")
        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_dsl,
                "_create_child_executions",
                side_effect=original,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                self._run(admission.task_id)

        self.assertIs(raised.exception, original)
        task = self._task(admission.task_id)
        self.assertEqual(task.status, "failed")
        self.assertIsNotNone(task.finished_at)
        with self.Session() as session:
            self.assertIsNone(
                session.scalar(
                    select(TaskHistory).where(
                        TaskHistory.task_id == admission.task_id
                    )
                )
            )

    def test_executor_construction_failure_finalizes_task(self):
        admission = self._admit(batch_size=2)
        original = RuntimeError("executor construction failed")
        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(routes_dsl, "ThreadPoolExecutor", side_effect=original),
        ):
            with self.assertRaises(RuntimeError) as raised:
                self._run(admission.task_id, batch_size=2)

        self.assertIs(raised.exception, original)
        self.assertEqual(self._task(admission.task_id).status, "failed")

    def test_submit_failure_drains_executor_and_finalizes_task(self):
        admission = self._admit(batch_size=2)
        original = RuntimeError("submit failed")
        child_finished = Event()
        fake_pool = _SecondSubmitFailsPool(original, child_finished)
        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(routes_dsl, "ThreadPoolExecutor", return_value=fake_pool),
            patch.object(
                routes_dsl,
                "render_worker",
                side_effect=self._successful_child,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                self._run(admission.task_id, batch_size=2)

        self.assertIs(raised.exception, original)
        self.assertTrue(fake_pool.exited)
        self.assertTrue(child_finished.is_set())
        self.assertEqual(self._task(admission.task_id).status, "failed")

    def test_aggregation_failure_finalizes_task(self):
        admission = self._admit(batch_size=2)
        original = RuntimeError("aggregation failed")
        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_dsl,
                "render_worker",
                side_effect=self._successful_child,
            ),
            patch.object(routes_dsl, "as_completed", side_effect=original),
        ):
            with self.assertRaises(RuntimeError) as raised:
                self._run(admission.task_id, batch_size=2)

        self.assertIs(raised.exception, original)
        self.assertEqual(self._task(admission.task_id).status, "failed")

    def test_known_terminal_target_survives_post_creative_commit_failure(self):
        admission = self._admit()
        original = RuntimeError("post-creative failure")

        def committed_then_failed(*_args, **kwargs):
            with self.Session() as session:
                session.add(
                    TaskHistory(
                        task_id=admission.task_id,
                        prompt="committed",
                        batch_size=1,
                        duration=0.1,
                        output_assets=[{"file_path": "final.mp4"}],
                    )
                )
                session.commit()
            kwargs["_terminal_target_callback"]("completed")
            raise original

        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_dsl,
                "_render_batch_worker_impl",
                side_effect=committed_then_failed,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                self._run(admission.task_id)

        self.assertIs(raised.exception, original)
        self.assertEqual(self._task(admission.task_id).status, "completed")
        with self.Session() as session:
            self.assertIsNotNone(
                session.scalar(
                    select(TaskHistory).where(
                        TaskHistory.task_id == admission.task_id
                    )
                )
            )

    def test_emergency_status_failure_does_not_mask_original_exception(self):
        admission = self._admit()
        original = RuntimeError("worker failure")
        real_transition = routes_dsl.transition_public_task_status
        calls = 0

        def transition(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("status unavailable")
            return real_transition(*args, **kwargs)

        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_dsl,
                "_create_child_executions",
                side_effect=original,
            ),
            patch.object(
                routes_dsl,
                "transition_public_task_status",
                side_effect=transition,
            ),
            patch.object(
                routes_dsl.logger,
                "error",
                side_effect=RuntimeError("logger unavailable"),
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                self._run(admission.task_id)

        self.assertIs(raised.exception, original)
        self.assertEqual(self._task(admission.task_id).status, "processing")

    def test_atomic_terminal_transition_cannot_rewrite_completed(self):
        admission = self._admit()
        transition_public_task_status(
            self.engine,
            task_id=admission.task_id,
            target_status="processing",
        )
        transition_public_task_status(
            self.engine,
            task_id=admission.task_id,
            target_status="completed",
        )

        with self.assertRaises(PublicTaskAdmissionStateError):
            transition_public_task_status(
                self.engine,
                task_id=admission.task_id,
                target_status="failed",
            )
        self.assertEqual(self._task(admission.task_id).status, "completed")

    def test_normal_success_has_one_terminal_transition(self):
        admission = self._admit()
        real_transition = routes_dsl.transition_public_task_status
        targets = []

        def transition(*args, **kwargs):
            targets.append(kwargs["target_status"])
            return real_transition(*args, **kwargs)

        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_dsl,
                "render_worker",
                side_effect=self._successful_child,
            ),
            patch.object(
                routes_dsl,
                "transition_public_task_status",
                side_effect=transition,
            ),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = self._run(admission.task_id)

        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(targets, ["processing", "completed"])
        self.assertEqual(self._task(admission.task_id).status, "completed")

    def test_normal_failure_has_one_terminal_transition(self):
        admission = self._admit()
        real_transition = routes_dsl.transition_public_task_status
        targets = []

        def transition(*args, **kwargs):
            targets.append(kwargs["target_status"])
            return real_transition(*args, **kwargs)

        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_dsl,
                "render_worker",
                side_effect=self._failed_child,
            ),
            patch.object(
                routes_dsl,
                "transition_public_task_status",
                side_effect=transition,
            ),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = self._run(admission.task_id)

        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(targets, ["processing", "failed"])
        self.assertEqual(self._task(admission.task_id).status, "failed")


if __name__ == "__main__":
    unittest.main()
