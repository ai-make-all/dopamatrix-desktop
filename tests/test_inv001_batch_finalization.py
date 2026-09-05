import json
import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import routes_dsl
from src.api.models import Base, TaskHistory
from src.api.schemas import (
    BeatCompilationResult,
    CompilationPlan,
    CompilationPlanSummary,
    DSLBeatNode,
    ResolvedLayer,
    StoryDSLPayload,
)
from src.core.context import WorkflowContext
from src.nodes.compositor import FFmpegCompositorNode


@contextmanager
def _temporary_working_directory():
    previous = os.getcwd()
    with tempfile.TemporaryDirectory() as directory:
        os.chdir(directory)
        try:
            yield Path(directory)
        finally:
            os.chdir(previous)


def _renderable_plan(*, layer_index: int = 0) -> CompilationPlan:
    return CompilationPlan(
        engine_type="content",
        beats=[
            BeatCompilationResult(
                beat="Hook",
                role="hook",
                address_mode="locked",
                layers=[
                    ResolvedLayer(
                        layer_index=layer_index,
                        asset_id=0,
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


def _result_from_call(
    file_sid: str,
    kwargs: dict,
    *,
    succeeded: bool,
) -> routes_dsl._ChildResult:
    child_index = kwargs["child_index"]
    return routes_dsl._ChildResult(
        child_index=child_index,
        execution_id=kwargs["execution_id"],
        file_sid=file_sid,
        outcome="succeeded" if succeeded else "failed",
        assets=(
            [{"file_path": f"final_{child_index}.mp4", "file_hash": f"hash-{child_index}"}]
            if succeeded
            else []
        ),
        elapsed=0.1,
        error_code=None if succeeded else "TEST_CHILD_FAILED",
        error_message=None if succeeded else "test child failure",
        prompt_details={
            "meta": {"source_child": child_index},
            "timeline": [{"beat": f"Beat-{child_index}"}],
        },
    )


class BatchFinalizationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def _history_rows(self) -> list[TaskHistory]:
        with self.Session() as db:
            return db.query(TaskHistory).order_by(TaskHistory.id).all()

    def _run_fake_batch(
        self,
        *,
        task_id: str,
        batch_size: int,
        failed_indices: set[int] | None = None,
        as_completed_side_effect=None,
    ):
        failed_indices = failed_indices or set()
        calls: list[dict] = []
        calls_lock = threading.Lock()

        def fake_render_worker(
            plan,
            received_task_id,
            aspect_ratio,
            target_duration,
            tenant_id,
            prompt,
            received_batch_size,
            test_language,
            file_sid,
            **kwargs,
        ):
            with calls_lock:
                calls.append(
                    {
                        "task_id": received_task_id,
                        "batch_size": received_batch_size,
                        "child_index": kwargs["child_index"],
                        "execution_id": kwargs["execution_id"],
                        "file_sid": file_sid,
                    }
                )
            return _result_from_call(
                file_sid,
                kwargs,
                succeeded=kwargs["child_index"] not in failed_indices,
            )

        ws_broadcast = Mock()
        patches = [
            patch.object(routes_dsl, "render_worker", side_effect=fake_render_worker),
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(routes_dsl.ws_manager, "broadcast_sync", ws_broadcast),
        ]
        if as_completed_side_effect is not None:
            patches.append(
                patch.object(
                    routes_dsl,
                    "as_completed",
                    side_effect=as_completed_side_effect,
                )
            )

        entered = []
        try:
            for item in patches:
                entered.append(item.start())
            terminal = routes_dsl.render_batch_worker(
                None,
                task_id,
                prompt="test prompt",
                batch_size=batch_size,
            )
        finally:
            for item in reversed(patches):
                item.stop()

        return terminal, calls, ws_broadcast

    def test_batch_size_one_finalizes_once(self):
        terminal, calls, ws = self._run_fake_batch(
            task_id="phase2-single",
            batch_size=1,
        )

        rows = self._history_rows()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["task_id"], "phase2-single")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].task_id, "phase2-single")
        self.assertEqual(rows[0].batch_size, 1)
        self.assertEqual(rows[0].output_assets, [
            {"file_path": "final_0.mp4", "file_hash": "hash-0"}
        ])
        self.assertEqual(terminal["status"], "completed")
        self.assertFalse(terminal["partial"])
        self.assertEqual(ws.call_count, 1)

    def test_batch_size_four_writes_one_stably_ordered_history_and_terminal(self):
        terminal, calls, ws = self._run_fake_batch(
            task_id="phase2-four",
            batch_size=4,
        )

        rows = self._history_rows()
        self.assertEqual(len(calls), 4)
        self.assertEqual({call["task_id"] for call in calls}, {"phase2-four"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].task_id, "phase2-four")
        self.assertEqual(rows[0].batch_size, 4)
        self.assertEqual(
            [asset["file_path"] for asset in rows[0].output_assets],
            ["final_0.mp4", "final_1.mp4", "final_2.mp4", "final_3.mp4"],
        )
        details = json.loads(rows[0].prompt_details)
        self.assertEqual(details["meta"], {"source_child": 0})
        self.assertEqual(details["timeline"], [{"beat": "Beat-0"}])
        self.assertEqual(terminal["succeededCount"], 4)
        self.assertEqual(terminal["failedCount"], 0)
        self.assertEqual(ws.call_count, 1)
        self.assertEqual(ws.call_args.args[0]["payload"]["status"], "completed")

    def test_partial_child_failure_persists_only_successful_outputs(self):
        terminal, _calls, ws = self._run_fake_batch(
            task_id="phase2-partial",
            batch_size=4,
            failed_indices={0},
        )

        rows = self._history_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            [asset["file_path"] for asset in rows[0].output_assets],
            ["final_1.mp4", "final_2.mp4", "final_3.mp4"],
        )
        details = json.loads(rows[0].prompt_details)
        self.assertEqual(details["meta"], {"source_child": 1})
        self.assertEqual(details["timeline"], [{"beat": "Beat-1"}])
        self.assertEqual(terminal["status"], "completed")
        self.assertTrue(terminal["partial"])
        self.assertEqual(terminal["succeededCount"], 3)
        self.assertEqual(terminal["failedCount"], 1)
        self.assertEqual(ws.call_count, 1)

    def test_all_children_failed_writes_no_history_and_one_failed_terminal(self):
        terminal, _calls, ws = self._run_fake_batch(
            task_id="phase2-all-failed",
            batch_size=4,
            failed_indices={0, 1, 2, 3},
        )

        self.assertEqual(self._history_rows(), [])
        self.assertEqual(terminal["status"], "failed")
        self.assertFalse(terminal["partial"])
        self.assertEqual(terminal["succeededCount"], 0)
        self.assertEqual(terminal["failedCount"], 4)
        self.assertEqual(ws.call_count, 1)

    def test_history_persistence_failure_preserves_completed_render_outcome(self):
        def fake_render_worker(
            _plan,
            _task_id,
            _aspect_ratio,
            _target_duration,
            _tenant_id,
            _prompt,
            _batch_size,
            _test_language,
            file_sid,
            **kwargs,
        ):
            return _result_from_call(file_sid, kwargs, succeeded=True)

        with (
            patch.object(routes_dsl, "render_worker", side_effect=fake_render_worker),
            patch.object(
                routes_dsl,
                "_persist_task_history",
                side_effect=RuntimeError("commit failed"),
            ),
            patch.object(routes_dsl.ws_manager, "broadcast_sync") as ws,
        ):
            terminal = routes_dsl.render_batch_worker(
                None,
                "phase2-history-failure",
                batch_size=1,
            )

        self.assertEqual(terminal["status"], "completed")
        self.assertFalse(terminal["historyPersisted"])
        self.assertIn("HISTORY_PERSIST_FAILED", terminal["warningCodes"])
        self.assertEqual(terminal["succeededCount"], 1)
        self.assertEqual(ws.call_count, 1)

    def test_reverse_future_collection_is_sorted_before_history_and_terminal(self):
        def reverse_completion(futures):
            completed = list(futures)
            return iter(
                sorted(
                    completed,
                    key=lambda future: future.result().child_index,
                    reverse=True,
                )
            )

        terminal, _calls, _ws = self._run_fake_batch(
            task_id="phase2-reverse",
            batch_size=4,
            as_completed_side_effect=reverse_completion,
        )

        row = self._history_rows()[0]
        details = json.loads(row.prompt_details)
        self.assertEqual(
            [child["child_index"] for child in details["children"]],
            [0, 1, 2, 3],
        )
        self.assertEqual(
            [asset["file_path"] for asset in terminal["assets"]],
            ["final_0.mp4", "final_1.mp4", "final_2.mp4", "final_3.mp4"],
        )


class WorkerFinalizationBoundaryTests(unittest.TestCase):
    def test_successful_render_worker_neither_persists_history_nor_emits_terminal(self):
        task_id = "worker-child"
        child = routes_dsl._create_child_executions(task_id, 1)[0]
        plan = _renderable_plan()

        with _temporary_working_directory():
            final_path = Path("output") / f"final_en_{child.file_sid}.mp4"

            def fake_compositor(_node, context):
                final_path.parent.mkdir(exist_ok=True)
                final_path.write_bytes(b"video")
                context.variants = {"en": {"final_video": str(final_path)}}
                return True

            with (
                patch.object(
                    routes_dsl,
                    "compile_plan_to_timeline",
                    return_value=SimpleNamespace(tracks=[object()]),
                ),
                patch.object(routes_dsl, "_run_compositor", side_effect=fake_compositor),
                patch.object(routes_dsl, "_run_cover_node", return_value=False),
                patch.object(routes_dsl, "TaskHistory") as task_history,
                patch.object(routes_dsl.ws_manager, "broadcast_sync") as ws,
            ):
                result = routes_dsl.render_worker(
                    plan,
                    task_id,
                    file_sid=child.file_sid,
                    execution_id=child.execution_id,
                    child_index=child.child_index,
                )

        self.assertTrue(result.succeeded)
        task_history.assert_not_called()
        ws.assert_not_called()

    def test_empty_timeline_child_does_not_emit_task_failed(self):
        task_id = "empty-timeline-child"
        child = routes_dsl._create_child_executions(task_id, 1)[0]

        with (
            patch.object(
                routes_dsl,
                "compile_plan_to_timeline",
                return_value=SimpleNamespace(tracks=[]),
            ),
            patch.object(routes_dsl.ws_manager, "broadcast_sync") as ws,
        ):
            result = routes_dsl.render_worker(
                _renderable_plan(),
                task_id,
                file_sid=child.file_sid,
                execution_id=child.execution_id,
                child_index=child.child_index,
            )

        self.assertEqual(result.error_code, "TIMELINE_EMPTY")
        ws.assert_not_called()

    def test_main_visual_preflight_child_does_not_emit_task_failed(self):
        task_id = "main-visual-missing-child"
        child = routes_dsl._create_child_executions(task_id, 1)[0]

        with (
            _temporary_working_directory(),
            patch.object(
                routes_dsl,
                "compile_plan_to_timeline",
                return_value=SimpleNamespace(tracks=[object()]),
            ),
            patch.object(routes_dsl, "_run_compositor") as compositor,
            patch.object(routes_dsl.ws_manager, "broadcast_sync") as ws,
        ):
            result = routes_dsl.render_worker(
                _renderable_plan(layer_index=1),
                task_id,
                file_sid=child.file_sid,
                execution_id=child.execution_id,
                child_index=child.child_index,
            )

        self.assertEqual(result.error_code, "MAIN_VISUAL_MISSING")
        compositor.assert_not_called()
        ws.assert_not_called()

    def test_compositor_child_failure_suppresses_failed_but_keeps_running(self):
        context = WorkflowContext(task_id="shared-task")
        context.config["ws_terminal_managed_by_coordinator"] = True
        context.set_asset("timeline", SimpleNamespace(tracks=[], audio_tracks=[]))
        context.variants = {"en": {}}
        node = FFmpegCompositorNode()
        node._build_filtergraph = lambda _timeline, language: (
            [],
            "[0:v]null[outv]",
            "",
        )
        broadcasts = Mock()
        node._ws_broadcast = broadcasts

        with (
            patch("src.nodes.compositor.get_ffmpeg_path", return_value="ffmpeg"),
            patch("src.nodes.compositor.subprocess.Popen", side_effect=FileNotFoundError),
        ):
            node.execute(context)

        statuses = [call.args[2]["status"] for call in broadcasts.call_args_list]
        self.assertEqual(statuses, ["running"])

    def test_compositor_legacy_failure_still_emits_failed(self):
        context = WorkflowContext(task_id="legacy-task")
        context.set_asset("timeline", SimpleNamespace(tracks=[], audio_tracks=[]))
        context.variants = {"en": {}}
        node = FFmpegCompositorNode()
        node._build_filtergraph = lambda _timeline, language: (
            [],
            "[0:v]null[outv]",
            "",
        )
        broadcasts = Mock()
        node._ws_broadcast = broadcasts

        with (
            patch("src.nodes.compositor.get_ffmpeg_path", return_value="ffmpeg"),
            patch("src.nodes.compositor.subprocess.Popen", side_effect=FileNotFoundError),
        ):
            node.execute(context)

        statuses = [call.args[2]["status"] for call in broadcasts.call_args_list]
        self.assertEqual(statuses, ["running", "failed"])

    def test_compositor_child_master_process_failure_suppresses_failed(self):
        context = WorkflowContext(task_id="shared-task")
        context.config["ws_terminal_managed_by_coordinator"] = True
        context.set_asset("timeline", SimpleNamespace(tracks=[], audio_tracks=[]))
        context.variants = {"en": {}}
        node = FFmpegCompositorNode()
        node._build_filtergraph = lambda _timeline, language: (
            [],
            "[0:v]null[outv]",
            "",
        )
        broadcasts = Mock()
        node._ws_broadcast = broadcasts

        class FailedPopen:
            stdout = []
            stderr = []
            returncode = 1

            def __init__(self, *_args, **_kwargs):
                pass

            def wait(self):
                return self.returncode

        with (
            patch("src.nodes.compositor.get_ffmpeg_path", return_value="ffmpeg"),
            patch("src.nodes.compositor.subprocess.Popen", FailedPopen),
            self.assertRaises(RuntimeError),
        ):
            node.execute(context)

        statuses = [call.args[2]["status"] for call in broadcasts.call_args_list]
        self.assertEqual(statuses, ["running"])

    def test_compositor_child_variant_failure_suppresses_failed(self):
        context = WorkflowContext(task_id="shared-task")
        context.config["ws_terminal_managed_by_coordinator"] = True
        context.set_asset("timeline", SimpleNamespace(tracks=[], audio_tracks=[]))
        context.variants = {"en": {}}
        node = FFmpegCompositorNode()
        node._build_filtergraph = lambda _timeline, language: (
            [],
            "[0:v]null[outv]",
            "",
        )
        node._render_variant = Mock(side_effect=RuntimeError("variant failed"))
        broadcasts = Mock()
        node._ws_broadcast = broadcasts

        class SuccessfulPopen:
            stdout = []
            stderr = []
            returncode = 0

            def __init__(self, *_args, **_kwargs):
                pass

            def wait(self):
                return self.returncode

        with (
            patch("src.nodes.compositor.get_ffmpeg_path", return_value="ffmpeg"),
            patch("src.nodes.compositor.subprocess.Popen", SuccessfulPopen),
            self.assertRaisesRegex(RuntimeError, "variant failed"),
        ):
            node.execute(context)

        statuses = [call.args[2]["status"] for call in broadcasts.call_args_list]
        self.assertEqual(statuses, ["running"])


class ModeCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def _successful_compositor(self, _node, context):
        output = Path("output") / f"final_en_{context.config['file_sid']}.mp4"
        output.parent.mkdir(exist_ok=True)
        output.write_bytes(b"video")
        context.variants = {"en": {"final_video": str(output)}}
        return True

    def test_blind_child_keeps_director_path_with_one_coordinator_finalization(self):
        plan = _renderable_plan()
        director = Mock()
        director.draft_blueprint.return_value = {
            "timeline": [
                {
                    "beat": "Hook",
                    "role": "hook",
                    "address_mode": "locked",
                    "asset_hashes": ["asset-hash"],
                    "script_text": "Blind script",
                }
            ],
            "meta": None,
        }

        with (
            _temporary_working_directory(),
            patch.object(routes_dsl, "DirectorNode", return_value=director),
            patch.object(routes_dsl, "_fetch_available_tags", return_value=[]),
            patch.object(routes_dsl, "_parse_plan_from_db", return_value=plan),
            patch.object(
                routes_dsl,
                "compile_plan_to_timeline",
                return_value=SimpleNamespace(tracks=[object()]),
            ),
            patch.object(routes_dsl, "_run_compositor", side_effect=self._successful_compositor),
            patch.object(routes_dsl, "_run_cover_node", return_value=False),
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(routes_dsl.ws_manager, "broadcast_sync") as ws,
        ):
            terminal = routes_dsl.render_batch_worker(
                None,
                "phase2-blind",
                prompt="blind prompt",
                batch_size=1,
                blind_dsl=True,
                enable_tts=False,
                enable_subtitles=False,
            )

        director.draft_blueprint.assert_called_once()
        with self.Session() as db:
            self.assertEqual(db.query(TaskHistory).count(), 1)
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(ws.call_count, 1)

    def test_manual_child_keeps_raw_dsl_resolution_and_finalizes_once(self):
        plan = _renderable_plan()
        beat = DSLBeatNode(
            beat="Hook",
            role="hook",
            address_mode="locked",
            asset_hashes=["asset-hash"],
        )
        dsl_payload = StoryDSLPayload(engine_type="content", timeline=[beat])

        with (
            _temporary_working_directory(),
            patch.object(routes_dsl, "_parse_plan_from_db", return_value=plan) as parse_plan,
            patch.object(
                routes_dsl,
                "compile_plan_to_timeline",
                return_value=SimpleNamespace(tracks=[object()]),
            ),
            patch.object(routes_dsl, "_run_compositor", side_effect=self._successful_compositor),
            patch.object(routes_dsl, "_run_cover_node", return_value=False),
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(routes_dsl, "DirectorNode") as director,
            patch.object(routes_dsl.ws_manager, "broadcast_sync") as ws,
        ):
            terminal = routes_dsl.render_batch_worker(
                dsl_payload,
                "phase2-manual",
                batch_size=1,
                blind_dsl=False,
                resolved_plan=plan,
            )

        parse_plan.assert_called_once_with("default", dsl_payload)
        director.assert_not_called()
        with self.Session() as db:
            self.assertEqual(db.query(TaskHistory).count(), 1)
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(ws.call_count, 1)


if __name__ == "__main__":
    unittest.main()
