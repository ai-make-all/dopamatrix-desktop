import inspect
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect as sa_inspect, select
from sqlalchemy.orm import sessionmaker

from src.api import routes, routes_dsl, services
from src.api.database import (
    TaskIdentitySchemaError,
    initialize_application_schema,
    verify_video_task_identity_schema,
    get_db,
)
from src.api.models import Base, TaskHistory, VideoTask
from src.api.public_task_admission import (
    PublicTaskAdmissionError,
    admit_public_task,
)
from src.api.schemas import (
    BeatCompilationResult,
    CompilationPlan,
    CompilationPlanSummary,
    DSLBeatNode,
    RenderDSLRequest,
    ResolvedLayer,
    VideoTaskCreate,
)
from src.api.task_identity import (
    CLIENT_TASK_ID_NOT_ALLOWED,
    PUBLIC_TASK_ID_GENERATION_COLLISION,
    VIDEO_TASK_TASK_ID_SCHEMA_RESET_REQUIRED,
)
from src.core.context import WorkflowContext


def _beat():
    return DSLBeatNode(
        beat="Hook",
        role="hook",
        address_mode="locked",
        asset_hashes=["asset-hash"],
    )


def _request():
    return RenderDSLRequest(
        engine_type="content",
        timeline=[_beat()],
        prompt="clean server task identity",
        batch_size=1,
    )


def _plan():
    return CompilationPlan(
        engine_type="content",
        beats=[
            BeatCompilationResult(
                beat="Hook",
                role="hook",
                address_mode="locked",
                layers=[
                    ResolvedLayer(
                        layer_index=0,
                        asset_id=1,
                        file_path="input.mp4",
                        asset_type="video",
                        file_hash="asset-hash",
                    )
                ],
                resolved=True,
            )
        ],
        unresolved_beats=[],
        summary=CompilationPlanSummary(
            total_beats=1,
            resolved_beats=1,
            unresolved_beats=0,
        ),
    )


class _Background:
    def __init__(self, before_dispatch=None, failure=None):
        self.tasks = []
        self.before_dispatch = before_dispatch
        self.failure = failure

    def add_task(self, func, *args, **kwargs):
        if self.before_dispatch is not None:
            self.before_dispatch()
        if self.failure is not None:
            raise self.failure
        self.tasks.append(SimpleNamespace(func=func, args=args, kwargs=kwargs))


class CleanServerTaskIdentityTests(unittest.TestCase):
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
        Base.metadata.create_all(engine)
        self.engines.append(engine)
        return engine, sessionmaker(bind=engine, expire_on_commit=False)

    def _submit_dsl(self, endpoint, *, background=None):
        background = background or _Background()
        parser = Mock()
        parser.parse_and_resolve.return_value = _plan()
        with self.Session() as db, patch.object(
            routes_dsl, "DSLParserNode", return_value=parser
        ):
            response = endpoint(_request(), background, db=db)
        return response, background

    def test_client_identity_fields_are_explicitly_rejected(self):
        for schema, base in (
            (VideoTaskCreate, {"prompt": "legacy"}),
            (
                RenderDSLRequest,
                {
                    "engine_type": "content",
                    "timeline": [_beat().model_dump()],
                    "prompt": "dsl",
                },
            ),
        ):
            for field in ("session_id", "task_id"):
                with self.subTest(schema=schema.__name__, field=field):
                    with self.assertRaises(ValidationError) as raised:
                        schema.model_validate({**base, field: "client-chosen"})
                    self.assertIn(CLIENT_TASK_ID_NOT_ALLOWED, str(raised.exception))
        with self.Session() as session:
            self.assertEqual(session.query(VideoTask).count(), 0)

    def test_all_submission_endpoints_reject_legacy_identity_before_dispatch(self):
        app = FastAPI()
        app.include_router(routes_dsl.router, prefix="/api/v1")
        app.include_router(routes.router, prefix="/api/v1")

        def override_get_db(_request: Request):
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        dsl_payload = {
            "engine_type": "content",
            "timeline": [_beat().model_dump()],
            "prompt": "rejected",
        }
        with TestClient(app) as client:
            for path, base in (
                ("/api/v1/tasks/submit-dsl", dsl_payload),
                ("/api/v1/tasks/submit-manual", dsl_payload),
                ("/api/v1/tasks/render-dsl", dsl_payload),
                ("/api/v1/tasks/submit", {"prompt": "rejected"}),
            ):
                for field in ("session_id", "task_id"):
                    response = client.post(path, json={**base, field: "client-chosen"})
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertIn(CLIENT_TASK_ID_NOT_ALLOWED, response.text)
        with self.Session() as session:
            self.assertEqual(session.query(VideoTask).count(), 0)

    def test_all_public_submission_routes_return_server_uuid(self):
        for endpoint in (
            routes_dsl.submit_dsl,
            routes_dsl.submit_manual,
            routes_dsl.render_dsl,
        ):
            response, background = self._submit_dsl(endpoint)
            task_id = response.task_id
            self.assertEqual(str(uuid.UUID(task_id)), task_id)
            self.assertFalse(hasattr(response, "session_id"))
            self.assertEqual(background.tasks[0].args[1], task_id)
            with self.Session() as session:
                row = session.scalar(
                    select(VideoTask).where(VideoTask.task_id == task_id)
                )
                self.assertEqual(row.status, "queued")

        request = Mock(headers={"X-Local-User": "default"})
        background = _Background()
        with self.Session() as db:
            response = routes.submit_task(
                VideoTaskCreate(prompt="legacy route"), background, request, db
            )
        self.assertEqual(str(uuid.UUID(response.task_id)), response.task_id)
        self.assertFalse(hasattr(response, "session_id"))
        self.assertEqual(background.tasks[0].kwargs["task_id"], response.task_id)

    def test_two_identical_requests_create_distinct_tasks(self):
        first, _ = self._submit_dsl(routes_dsl.submit_dsl)
        second, _ = self._submit_dsl(routes_dsl.submit_dsl)
        self.assertNotEqual(first.task_id, second.task_id)
        with self.Session() as session:
            self.assertEqual(session.query(VideoTask).count(), 2)

    def test_many_generated_task_ids_are_uuid_and_unique(self):
        ids = {
            admit_public_task(self.engine, prompt="p", batch_size=1).task_id
            for _ in range(100)
        }
        self.assertEqual(len(ids), 100)
        self.assertTrue(all(str(uuid.UUID(value)) == value for value in ids))

    def test_uuid_collision_retries_and_exhaustion_fails_closed(self):
        collision = str(uuid.UUID("00000000-0000-4000-8000-000000000001"))
        replacement = str(uuid.UUID("00000000-0000-4000-8000-000000000002"))
        admit_public_task(
            self.engine,
            prompt="first",
            batch_size=1,
            task_id_factory=lambda: collision,
        )
        generated = iter((collision, replacement))
        admitted = admit_public_task(
            self.engine,
            prompt="second",
            batch_size=1,
            task_id_factory=lambda: next(generated),
        )
        self.assertEqual(admitted.task_id, replacement)

        with self.assertRaises(PublicTaskAdmissionError) as raised:
            admit_public_task(
                self.engine,
                prompt="never dispatched",
                batch_size=1,
                task_id_factory=lambda: collision,
            )
        self.assertEqual(str(raised.exception), PUBLIC_TASK_ID_GENERATION_COLLISION)
        with self.Session() as session:
            self.assertEqual(session.query(VideoTask).count(), 2)

    def test_claim_commit_precedes_dispatch_visibility(self):
        observed = []

        def before_dispatch():
            with self.Session() as independent:
                row = independent.scalar(select(VideoTask))
                observed.append((row.task_id, row.status))

        response, background = self._submit_dsl(
            routes_dsl.submit_dsl,
            background=_Background(before_dispatch=before_dispatch),
        )
        self.assertEqual(observed, [(response.task_id, "queued")])
        self.assertEqual(len(background.tasks), 1)

    def test_dispatch_failure_keeps_task_and_marks_failed(self):
        background = _Background(failure=RuntimeError("dispatch failed"))
        with self.assertRaisesRegex(RuntimeError, "dispatch failed"):
            self._submit_dsl(routes_dsl.submit_dsl, background=background)
        with self.Session() as session:
            rows = session.scalars(select(VideoTask)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "failed")
        next_response, _ = self._submit_dsl(routes_dsl.submit_dsl)
        self.assertNotEqual(next_response.task_id, rows[0].task_id)

    def test_status_lookup_uses_public_uuid_not_surrogate(self):
        response, _ = self._submit_dsl(routes_dsl.submit_dsl)
        with self.Session() as session:
            row = session.scalar(select(VideoTask))
            self.assertNotEqual(str(row.id), row.task_id)
            result = routes.get_task(response.task_id, db=session)
            self.assertEqual(result.task_id, response.task_id)
            self.assertFalse(hasattr(result, "id"))
            self.assertFalse(hasattr(result, "session_id"))

    def test_worker_lifecycle_taskhistory_and_ws_share_server_id(self):
        response, background = self._submit_dsl(routes_dsl.submit_dsl)
        scheduled = background.tasks[0]
        events = []

        def successful_child(_plan_value, child_task_id, *_args, **kwargs):
            self.assertEqual(child_task_id, response.task_id)
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

        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(routes_dsl, "render_worker", side_effect=successful_child),
            patch.object(
                routes_dsl.ws_manager,
                "broadcast_sync",
                side_effect=lambda event, **_kwargs: events.append(event),
            ),
        ):
            terminal = scheduled.func(*scheduled.args, **scheduled.kwargs)

        self.assertEqual(terminal["taskId"], response.task_id)
        with self.Session() as session:
            task = session.scalar(
                select(VideoTask).where(VideoTask.task_id == response.task_id)
            )
            history = session.scalar(
                select(TaskHistory).where(TaskHistory.task_id == response.task_id)
            )
            self.assertEqual(task.status, "completed")
            self.assertIsNotNone(history)
        self.assertTrue(
            any(event.get("payload", {}).get("taskId") == response.task_id for event in events)
        )

    def test_all_failed_worker_marks_same_server_task_failed(self):
        response, background = self._submit_dsl(routes_dsl.submit_dsl)
        scheduled = background.tasks[0]

        def failed_child(_plan_value, child_task_id, *_args, **kwargs):
            self.assertEqual(child_task_id, response.task_id)
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

        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(routes_dsl, "render_worker", side_effect=failed_child),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = scheduled.func(*scheduled.args, **scheduled.kwargs)

        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["taskId"], response.task_id)
        with self.Session() as session:
            task = session.scalar(
                select(VideoTask).where(VideoTask.task_id == response.task_id)
            )
            self.assertEqual(task.status, "failed")
            self.assertIsNone(
                session.scalar(
                    select(TaskHistory).where(TaskHistory.task_id == response.task_id)
                )
            )

    def test_terminal_status_failure_cannot_rewrite_creative_truth(self):
        response, background = self._submit_dsl(routes_dsl.submit_dsl)
        scheduled = background.tasks[0]
        real_transition = routes_dsl.transition_public_task_status
        transition_count = 0

        def transition(*args, **kwargs):
            nonlocal transition_count
            transition_count += 1
            if transition_count == 2:
                raise RuntimeError("task status unavailable")
            return real_transition(*args, **kwargs)

        def successful_child(_plan_value, _task_id, *_args, **kwargs):
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

        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(routes_dsl, "render_worker", side_effect=successful_child),
            patch.object(
                routes_dsl,
                "transition_public_task_status",
                side_effect=transition,
            ),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = scheduled.func(*scheduled.args, **scheduled.kwargs)

        self.assertEqual(terminal["status"], "completed")
        with self.Session() as session:
            task = session.scalar(
                select(VideoTask).where(VideoTask.task_id == response.task_id)
            )
            history = session.scalar(
                select(TaskHistory).where(TaskHistory.task_id == response.task_id)
            )
            self.assertEqual(task.status, "processing")
            self.assertIsNotNone(history)

    def test_legacy_worker_uses_public_uuid_for_lifecycle_history_and_ws(self):
        admission = admit_public_task(self.engine, prompt="legacy", batch_size=1)
        events = []
        fake_results = [
            {
                "execution_id": str(uuid.uuid4()),
                "success": True,
                "assets": {"variants": {"en": "final.mp4"}},
                "cover_path": "",
                "video_manifest": {},
                "used_asset_ids": [],
            }
        ]
        with (
            patch("src.api.database.get_tenant_engine", return_value=self.engine),
            patch("run_matrix_factory.run_matrix_factory", return_value=fake_results),
            patch.object(
                services.ws_manager,
                "broadcast_sync",
                side_effect=lambda event, **_kwargs: events.append(event),
            ),
            patch.object(services, "notify_task_result", new_callable=AsyncMock),
        ):
            services.run_matrix_job(
                video_task_id=admission.video_task_id,
                task_id=admission.task_id,
                prompt="legacy",
                batch_size=1,
            )

        with self.Session() as session:
            task = session.get(VideoTask, admission.video_task_id)
            history = session.scalar(
                select(TaskHistory).where(TaskHistory.task_id == admission.task_id)
            )
            self.assertEqual(task.task_id, admission.task_id)
            self.assertEqual(task.status, "completed")
            self.assertIsNotNone(history)
        self.assertTrue(events)
        self.assertTrue(
            all(event["payload"]["taskId"] == admission.task_id for event in events)
        )

    def test_workflow_context_uses_task_identity_only(self):
        task_id = str(uuid.uuid4())
        context = WorkflowContext(task_id=task_id)
        self.assertEqual(context.task_id, task_id)
        self.assertFalse(hasattr(context, "session_id"))

    def test_admission_does_not_scan_taskhistory(self):
        source = inspect.getsource(admit_public_task) + inspect.getsource(
            __import__(
                "src.api.public_task_admission",
                fromlist=["_claim_one"],
            )._claim_one
        )
        self.assertNotIn("TaskHistory", source)
        self.assertNotIn("task_history", source)

    def test_fresh_schema_is_clean_and_old_schema_is_hard_rejected(self):
        fresh_path = Path(self.temporary.name) / "fresh.db"
        fresh = create_engine(f"sqlite:///{fresh_path.as_posix()}")
        self.engines.append(fresh)
        initialize_application_schema(fresh)
        inspector = sa_inspect(fresh)
        columns = {column["name"]: column for column in inspector.get_columns("video_tasks")}
        self.assertIn("task_id", columns)
        self.assertNotIn("session_id", columns)
        self.assertFalse(columns["task_id"]["nullable"])
        unique_indexes = [
            index for index in inspector.get_indexes("video_tasks") if index.get("unique")
        ]
        self.assertTrue(any(index["column_names"] == ["task_id"] for index in unique_indexes))

        old_path = Path(self.temporary.name) / "old.db"
        connection = sqlite3.connect(old_path)
        try:
            connection.execute(
                "CREATE TABLE video_tasks ("
                "id INTEGER PRIMARY KEY, session_id VARCHAR(64) NOT NULL UNIQUE)"
            )
            connection.commit()
        finally:
            connection.close()
        old = create_engine(f"sqlite:///{old_path.as_posix()}")
        self.engines.append(old)
        with self.assertRaises(TaskIdentitySchemaError) as raised:
            verify_video_task_identity_schema(old)
        self.assertEqual(str(raised.exception), VIDEO_TASK_TASK_ID_SCHEMA_RESET_REQUIRED)
        old_columns = {
            column["name"] for column in sa_inspect(old).get_columns("video_tasks")
        }
        self.assertEqual(old_columns, {"id", "session_id"})
        old.dispose()

    def test_identical_injected_id_is_tenant_local_test_authority(self):
        other, OtherSession = self._database("tenant-b.db")
        injected = str(uuid.UUID("00000000-0000-4000-8000-000000000010"))
        first = admit_public_task(
            self.engine, prompt="a", batch_size=1, task_id_factory=lambda: injected
        )
        second = admit_public_task(
            other, prompt="b", batch_size=1, task_id_factory=lambda: injected
        )
        self.assertEqual(first.task_id, second.task_id)
        with self.Session() as a, OtherSession() as b:
            self.assertEqual(a.query(VideoTask).count(), 1)
            self.assertEqual(b.query(VideoTask).count(), 1)

    def test_public_routes_expose_policy_but_do_not_construct_controller(self):
        route_source = inspect.getsource(routes.submit_task)
        dsl_sources = "".join(
            inspect.getsource(endpoint)
            for endpoint in (
                routes_dsl.submit_dsl,
                routes_dsl.submit_manual,
                routes_dsl.render_dsl,
            )
        )
        self.assertNotIn("PlannerReservationController(", route_source + dsl_sources)
        self.assertEqual(
            RenderDSLRequest.model_fields["reservation_conflict_mode"].default,
            "OFF",
        )


if __name__ == "__main__":
    unittest.main()
