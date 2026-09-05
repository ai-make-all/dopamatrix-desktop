import inspect
import os
import tempfile
import threading
import unittest
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks

from src.api import routes_dsl
from src.api.schemas import (
    BeatCompilationResult,
    CompilationPlan,
    CompilationPlanSummary,
    DSLBeatNode,
    RenderDSLRequest,
    ResolvedLayer,
    StoryDSLPayload,
)


@contextmanager
def _temporary_working_directory():
    previous = os.getcwd()
    with tempfile.TemporaryDirectory() as directory:
        os.chdir(directory)
        try:
            yield directory
        finally:
            os.chdir(previous)


def _renderable_plan() -> CompilationPlan:
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


def _request(*, timeline: list[DSLBeatNode]) -> RenderDSLRequest:
    return RenderDSLRequest(
        engine_type="content",
        timeline=timeline,
        prompt="A short test script",
        batch_size=1,
    )


def _scheduled_coordinator_arguments(background_tasks: BackgroundTasks) -> dict:
    assert len(background_tasks.tasks) == 1
    scheduled = background_tasks.tasks[0]
    assert scheduled.func is routes_dsl.render_batch_worker
    bound = inspect.signature(routes_dsl.render_batch_worker).bind_partial(
        *scheduled.args,
        **scheduled.kwargs,
    )
    return bound.arguments


class ChildIdentityTests(unittest.TestCase):
    def test_batch_size_one_identity_is_full_and_derived(self):
        task_id = "submitted-task"
        child = routes_dsl._create_child_executions(task_id, 1)[0]

        parsed = uuid.UUID(child.execution_id)
        self.assertNotEqual(child.execution_id, task_id)
        self.assertEqual(child.child_index, 0)
        self.assertEqual(child.file_sid, parsed.hex[:8])

    def test_batch_size_four_identities_are_unique(self):
        children = routes_dsl._create_child_executions("submitted-task", 4)

        self.assertEqual([child.child_index for child in children], [0, 1, 2, 3])
        self.assertEqual(len({child.execution_id for child in children}), 4)
        self.assertEqual(len({child.file_sid for child in children}), 4)
        for child in children:
            self.assertEqual(child.file_sid, uuid.UUID(child.execution_id).hex[:8])

    def test_file_sid_collision_retries_with_a_new_execution_id(self):
        first = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
        colliding = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000002")
        replacement = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000003")

        with patch.object(
            routes_dsl.uuid,
            "uuid4",
            side_effect=[first, colliding, replacement],
        ):
            children = routes_dsl._create_child_executions("submitted-task", 2)

        self.assertEqual(
            [child.execution_id for child in children],
            [str(first), str(replacement)],
        )
        self.assertEqual(
            [child.file_sid for child in children],
            ["aaaaaaaa", "bbbbbbbb"],
        )

    def test_single_submit_paths_use_coordinator_and_create_new_child_identity(self):
        task_id = "shared-ui-task"
        beat = DSLBeatNode(
            beat="Hook",
            role="hook",
            address_mode="locked",
            asset_hashes=["asset-hash"],
            script_text="A short test script",
        )
        normal_request = _request(timeline=[beat])
        blind_request = _request(timeline=[])
        plan = _renderable_plan()
        execution_ids: list[str] = []

        with (
            patch.object(routes_dsl, "DSLParserNode") as parser_cls,
            patch.object(
                routes_dsl,
                "_admit_dsl_public_task",
                return_value=task_id,
            ),
            patch.object(routes_dsl, "transition_public_task_status"),
        ):
            parser_cls.return_value.parse_and_resolve.return_value = plan
            cases = (
                ("ai-draft", routes_dsl.submit_dsl, normal_request),
                ("ai-draft-rerun", routes_dsl.submit_dsl, normal_request),
                ("blind", routes_dsl.submit_dsl, blind_request),
                ("manual", routes_dsl.submit_manual, normal_request),
                ("render-dsl", routes_dsl.render_dsl, normal_request),
            )
            for label, endpoint, payload in cases:
                with self.subTest(path=label):
                    background = BackgroundTasks()
                    endpoint(payload, background, db=Mock())
                    arguments = _scheduled_coordinator_arguments(background)
                    captured: list[dict] = []

                    def fake_render_worker(
                        _plan,
                        received_task_id,
                        _aspect_ratio,
                        _target_duration,
                        _tenant_id,
                        _prompt,
                        _batch_size,
                        _test_language,
                        file_sid,
                        **kwargs,
                    ):
                        captured.append(
                            {
                                "task_id": received_task_id,
                                "execution_id": kwargs["execution_id"],
                                "file_sid": file_sid,
                                "child_index": kwargs["child_index"],
                            }
                        )
                        return routes_dsl._ChildResult(
                            child_index=kwargs["child_index"],
                            execution_id=kwargs["execution_id"],
                            file_sid=file_sid,
                            outcome="succeeded",
                            assets=[{"file_path": f"final_{file_sid}.mp4"}],
                            elapsed=0.1,
                            error_code=None,
                            error_message=None,
                            prompt_details={"meta": None, "timeline": []},
                        )

                    with (
                        patch.object(routes_dsl, "render_worker", side_effect=fake_render_worker),
                        patch.object(routes_dsl, "_persist_task_history"),
                        patch.object(routes_dsl.ws_manager, "broadcast_sync"),
                    ):
                        background.tasks[0].kwargs["public_task_admitted"] = False
                        background.tasks[0].func(
                            *background.tasks[0].args,
                            **background.tasks[0].kwargs,
                        )

                    self.assertEqual(len(captured), 1)
                    child = captured[0]
                    execution_id = child["execution_id"]
                    file_sid = child["file_sid"]

                    self.assertEqual(arguments["task_id"], task_id)
                    self.assertEqual(arguments["batch_size"], 1)
                    self.assertEqual(child["task_id"], task_id)
                    self.assertEqual(child["child_index"], 0)
                    self.assertNotEqual(execution_id, task_id)
                    self.assertEqual(file_sid, uuid.UUID(execution_id).hex[:8])
                    execution_ids.append(execution_id)

        self.assertEqual(len(set(execution_ids)), len(execution_ids))

    def test_render_batch_worker_submits_unique_children_with_shared_task_id(self):
        task_id = "shared-batch-task"
        calls: list[dict] = []
        calls_lock = threading.Lock()

        def fake_render_worker(
            plan,
            received_task_id,
            aspect_ratio,
            target_duration,
            tenant_id,
            prompt,
            batch_size,
            test_language,
            file_sid,
            **kwargs,
        ):
            with calls_lock:
                calls.append(
                    {
                        "task_id": received_task_id,
                        "execution_id": kwargs["execution_id"],
                        "child_index": kwargs["child_index"],
                        "file_sid": file_sid,
                        "enable_tts": kwargs["enable_tts"],
                        "enable_subtitles": kwargs["enable_subtitles"],
                    }
                )
            return routes_dsl._ChildResult(
                child_index=kwargs["child_index"],
                execution_id=kwargs["execution_id"],
                file_sid=file_sid,
                outcome="failed",
                assets=[],
                elapsed=0.1,
                error_code="TEST_NO_OUTPUT",
                error_message="test",
                prompt_details={"meta": None, "timeline": []},
            )

        with (
            patch.object(routes_dsl, "render_worker", side_effect=fake_render_worker),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            routes_dsl.render_batch_worker(
                None,
                task_id,
                batch_size=4,
                enable_tts=False,
                enable_subtitles=False,
            )

        self.assertEqual(len(calls), 4)
        self.assertEqual({call["task_id"] for call in calls}, {task_id})
        self.assertEqual({call["child_index"] for call in calls}, {0, 1, 2, 3})
        self.assertEqual(len({call["execution_id"] for call in calls}), 4)
        self.assertEqual(len({call["file_sid"] for call in calls}), 4)
        self.assertTrue(all(not call["enable_tts"] for call in calls))
        self.assertTrue(all(not call["enable_subtitles"] for call in calls))
        for call in calls:
            self.assertEqual(
                call["file_sid"],
                uuid.UUID(call["execution_id"]).hex[:8],
            )


class WorkerContextTests(unittest.TestCase):
    def test_render_worker_propagates_explicit_child_identity(self):
        task_id = "shared-task"
        child = routes_dsl._create_child_executions(task_id, 1)[0]
        captured_contexts = []

        def capture_compositor(_node, context):
            captured_contexts.append(context)
            return False

        with (
            _temporary_working_directory(),
            patch.object(
                routes_dsl,
                "compile_plan_to_timeline",
                return_value=SimpleNamespace(tracks=[object()]),
            ),
            patch.object(routes_dsl, "_run_compositor", side_effect=capture_compositor),
        ):
            routes_dsl.render_worker(
                _renderable_plan(),
                task_id,
                file_sid=child.file_sid,
                execution_id=child.execution_id,
                child_index=child.child_index,
            )

        self.assertEqual(len(captured_contexts), 1)
        context = captured_contexts[0]
        self.assertEqual(context.task_id, task_id)
        self.assertEqual(context.config["execution_id"], child.execution_id)
        self.assertEqual(context.config["file_sid"], child.file_sid)
        self.assertEqual(context.config["child_index"], 0)
        self.assertTrue(context.config["ws_terminal_managed_by_coordinator"])
        self.assertNotIn("session_id", context.config)

    def test_disabled_tts_and_subtitle_nodes_are_not_invoked(self):
        task_id = "shared-task"
        child = routes_dsl._create_child_executions(task_id, 1)[0]
        beat = DSLBeatNode(
            beat="Hook",
            role="hook",
            address_mode="locked",
            asset_hashes=["asset-hash"],
            script_text="A short test script",
            duration=5.0,
        )
        dsl_payload = StoryDSLPayload(engine_type="content", timeline=[beat])
        captured_contexts = []

        def capture_compositor(_node, context):
            captured_contexts.append(context)
            return False

        with (
            _temporary_working_directory(),
            patch.object(routes_dsl, "_parse_plan_from_db", return_value=_renderable_plan()),
            patch.object(
                routes_dsl,
                "compile_plan_to_timeline",
                return_value=SimpleNamespace(tracks=[object()]),
            ),
            patch.object(routes_dsl, "_run_compositor", side_effect=capture_compositor),
            patch.object(routes_dsl, "TTSNode") as tts_node,
            patch.object(routes_dsl, "SubtitleNode") as subtitle_node,
        ):
            routes_dsl.render_worker(
                None,
                task_id,
                prompt="A short test script",
                file_sid=child.file_sid,
                execution_id=child.execution_id,
                child_index=child.child_index,
                dsl_payload=dsl_payload,
                enable_tts=False,
                enable_subtitles=False,
            )

        tts_node.assert_not_called()
        subtitle_node.assert_not_called()
        self.assertEqual(len(captured_contexts), 1)
        self.assertFalse(captured_contexts[0].config["enable_tts"])
        self.assertFalse(captured_contexts[0].config["enable_subtitles"])

    def test_tts_and_subtitle_disable_flags_are_independent(self):
        beat = DSLBeatNode(
            beat="Hook",
            role="hook",
            address_mode="locked",
            asset_hashes=["asset-hash"],
            script_text="A short test script",
            duration=5.0,
        )
        dsl_payload = StoryDSLPayload(engine_type="content", timeline=[beat])

        for enable_tts, enable_subtitles in ((False, True), (True, False)):
            with self.subTest(
                enable_tts=enable_tts,
                enable_subtitles=enable_subtitles,
            ):
                task_id = "shared-task"
                child = routes_dsl._create_child_executions(task_id, 1)[0]
                with (
                    _temporary_working_directory(),
                    patch.object(
                        routes_dsl,
                        "_parse_plan_from_db",
                        return_value=_renderable_plan(),
                    ),
                    patch.object(
                        routes_dsl,
                        "compile_plan_to_timeline",
                        return_value=SimpleNamespace(tracks=[object()]),
                    ),
                    patch.object(routes_dsl, "_run_compositor", return_value=False),
                    patch.object(routes_dsl, "TTSNode") as tts_node,
                    patch.object(routes_dsl, "SubtitleNode") as subtitle_node,
                ):
                    routes_dsl.render_worker(
                        None,
                        task_id,
                        prompt="A short test script",
                        file_sid=child.file_sid,
                        execution_id=child.execution_id,
                        child_index=child.child_index,
                        dsl_payload=dsl_payload,
                        enable_tts=enable_tts,
                        enable_subtitles=enable_subtitles,
                    )

                self.assertEqual(tts_node.called, enable_tts)
                self.assertEqual(subtitle_node.called, enable_subtitles)


if __name__ == "__main__":
    unittest.main()
