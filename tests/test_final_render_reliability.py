from __future__ import annotations

import io
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.api import routes_dsl
from src.core.context import WorkflowContext
from src.nodes.compositor import (
    FFmpegCompositorNode,
    _MediaProcessFailure,
    _MediaProcessResult,
)


def _context() -> WorkflowContext:
    context = WorkflowContext(task_id="reliability-task", target_duration=15)
    context.config.update(
        {
            "execution_id": "11111111-1111-4111-8111-111111111111",
            "child_index": 1,
            "file_sid": "11111111",
        }
    )
    return context


class _HangingProcess:
    def __init__(self) -> None:
        self.stdout = io.StringIO("")
        self.stderr = io.StringIO("safe diagnostic")
        self.returncode = None
        self.pid = 1234
        self.terminated = False
        self.killed = False
        self.reaped = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.reaped = True
        return self.returncode


class _StubbornProcess(_HangingProcess):
    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None):
        if not self.killed:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        self.reaped = True
        return self.returncode


class _UnreapableProcess(_HangingProcess):
    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("ffmpeg", timeout)


class _ProgressHangingProcess(_HangingProcess):
    def __init__(self) -> None:
        super().__init__()
        self.stdout = io.StringIO("out_time_us=1000\n")


class FinalRenderProcessTests(unittest.TestCase):
    def test_media_process_timeout_terminates_and_reaps(self) -> None:
        node = FFmpegCompositorNode()
        process = _HangingProcess()
        started = time.monotonic()

        with (
            patch("src.nodes.compositor.subprocess.Popen", return_value=process),
            patch("src.nodes.compositor._MEDIA_POLL_INTERVAL_SECONDS", 0.001),
            self.assertRaisesRegex(
                _MediaProcessFailure,
                "FINAL_FFMPEG_TIMEOUT",
            ) as captured,
        ):
            node._run_bounded_media_process(
                ["ffmpeg", "-version"],
                context=_context(),
                process_kind="FINAL_FFMPEG",
                timeout_seconds=0.01,
            )

        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(captured.exception.code, "FINAL_FFMPEG_TIMEOUT")
        self.assertTrue(process.terminated)
        self.assertTrue(process.reaped)
        self.assertFalse(process.killed)

    def test_media_process_creation_failure_is_typed(self) -> None:
        node = FFmpegCompositorNode()
        with (
            patch(
                "src.nodes.compositor.subprocess.Popen",
                side_effect=OSError("creation denied"),
            ),
            self.assertRaisesRegex(
                _MediaProcessFailure,
                "FFPROBE_CREATE_FAILED",
            ) as captured,
        ):
            node._run_bounded_media_process(
                ["ffprobe", "input.mp4"],
                context=_context(),
                process_kind="FFPROBE",
                timeout_seconds=1.0,
            )
        self.assertEqual(captured.exception.stage, "PROCESS_CREATE")

    def test_media_process_timeout_escalates_to_kill_and_reaps(self) -> None:
        node = FFmpegCompositorNode()
        process = _StubbornProcess()
        with (
            patch("src.nodes.compositor.subprocess.Popen", return_value=process),
            patch("src.nodes.compositor._MEDIA_POLL_INTERVAL_SECONDS", 0.001),
            patch("src.nodes.compositor._MEDIA_TERMINATE_GRACE_SECONDS", 0.001),
            self.assertRaisesRegex(_MediaProcessFailure, "MASTER_FFMPEG_TIMEOUT"),
        ):
            node._run_bounded_media_process(
                ["ffmpeg"],
                context=_context(),
                process_kind="MASTER_FFMPEG",
                timeout_seconds=0.005,
            )
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertTrue(process.reaped)

    def test_unreapable_process_closes_pipes_and_fails_explicitly(self) -> None:
        node = FFmpegCompositorNode()
        process = _UnreapableProcess()
        with (
            patch("src.nodes.compositor.subprocess.Popen", return_value=process),
            patch("src.nodes.compositor._MEDIA_POLL_INTERVAL_SECONDS", 0.001),
            patch("src.nodes.compositor._MEDIA_TERMINATE_GRACE_SECONDS", 0.001),
            self.assertRaisesRegex(
                _MediaProcessFailure,
                "MEDIA_PROCESS_REAP_TIMEOUT",
            ) as captured,
        ):
            node._run_bounded_media_process(
                ["ffmpeg"],
                context=_context(),
                process_kind="FINAL_FFMPEG",
                timeout_seconds=0.005,
            )
        self.assertEqual(captured.exception.stage, "PROCESS_CLEANUP")
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_media_process_cancellation_is_typed_and_reaped(self) -> None:
        node = FFmpegCompositorNode()
        process = _HangingProcess()
        context = _context()
        cancel_event = threading.Event()
        cancel_event.set()
        context.config["render_cancel_event"] = cancel_event
        with (
            patch("src.nodes.compositor.subprocess.Popen", return_value=process),
            self.assertRaisesRegex(_MediaProcessFailure, "FINAL_FFMPEG_CANCELLED"),
        ):
            node._run_bounded_media_process(
                ["ffmpeg"],
                context=context,
                process_kind="FINAL_FFMPEG",
                timeout_seconds=1.0,
            )
        self.assertTrue(process.terminated)
        self.assertTrue(process.reaped)

    def test_progress_callback_failure_terminates_and_reaps(self) -> None:
        node = FFmpegCompositorNode()
        process = _ProgressHangingProcess()

        def fail_callback(_line: str) -> None:
            raise RuntimeError("synthetic callback failure")

        with (
            patch("src.nodes.compositor.subprocess.Popen", return_value=process),
            patch("src.nodes.compositor._MEDIA_POLL_INTERVAL_SECONDS", 0.001),
            self.assertRaisesRegex(
                _MediaProcessFailure,
                "FINAL_FFMPEG_PROGRESS_CALLBACK_FAILED",
            ),
        ):
            node._run_bounded_media_process(
                ["ffmpeg"],
                context=_context(),
                process_kind="FINAL_FFMPEG",
                timeout_seconds=1.0,
                on_stdout_line=fail_callback,
            )

        self.assertTrue(process.terminated)
        self.assertTrue(process.reaped)

    def test_safe_stderr_is_bounded_and_redacts_credentials(self) -> None:
        raw = (
            "authorization: Bearer-secret xi-api-key=secret-value "
            "access_token=another " + "x" * 1000
        )
        excerpt = FFmpegCompositorNode._safe_stderr_excerpt(raw, limit=2000)
        self.assertNotIn("Bearer-secret", excerpt)
        self.assertNotIn("secret-value", excerpt)
        self.assertNotIn("another", excerpt)
        self.assertLessEqual(
            len(FFmpegCompositorNode._safe_stderr_excerpt(raw, limit=160)),
            160,
        )


class FinalRenderProbeAndPostconditionTests(unittest.TestCase):
    def test_probe_path_resolution_failure_is_classified_and_logged(self) -> None:
        node = FFmpegCompositorNode()
        with (
            patch(
                "src.nodes.compositor.get_ffmpeg_path",
                side_effect=OSError("synthetic path failure"),
            ),
            patch.object(node, "_log_media_stage") as stage_log,
            self.assertRaisesRegex(
                _MediaProcessFailure,
                "FFPROBE_PATH_RESOLUTION_FAILED",
            ),
        ):
            node._probe_duration(
                "input.mp4",
                context=_context(),
                role="MASTER",
            )

        failed_calls = [
            call
            for call in stage_log.call_args_list
            if call.args[1] == "PROBE_MASTER_FAILED"
        ]
        self.assertEqual(len(failed_calls), 1)
        self.assertEqual(
            failed_calls[0].kwargs["failure_code"],
            "FFPROBE_PATH_RESOLUTION_FAILED",
        )

    def test_required_probe_rejects_nonzero_and_invalid_results(self) -> None:
        node = FFmpegCompositorNode()
        cases = (
            (
                _MediaProcessResult(1, "", "probe failed", 0.1),
                "FFPROBE_NONZERO_EXIT",
            ),
            (
                _MediaProcessResult(0, "not-a-duration", "", 0.1),
                "FFPROBE_RESULT_INVALID",
            ),
            (
                _MediaProcessResult(0, "0", "", 0.1),
                "FFPROBE_RESULT_INVALID",
            ),
        )
        for result, code in cases:
            with self.subTest(code=code), patch.object(
                node,
                "_run_bounded_media_process",
                return_value=result,
            ), self.assertRaisesRegex(_MediaProcessFailure, code):
                node._probe_duration(
                    "input.mp4",
                    context=_context(),
                    role="MASTER",
                )

    def test_required_probe_propagates_timeout(self) -> None:
        node = FFmpegCompositorNode()
        failure = _MediaProcessFailure(
            "FFPROBE_TIMEOUT",
            stage="FFPROBE",
        )
        with (
            patch.object(
                node,
                "_run_bounded_media_process",
                side_effect=failure,
            ),
            self.assertRaisesRegex(_MediaProcessFailure, "FFPROBE_TIMEOUT"),
        ):
            node._probe_duration(
                "input.mp4",
                context=_context(),
                role="VOICE",
            )

    def test_final_postcondition_rejects_missing_empty_and_invalid_output(self) -> None:
        node = FFmpegCompositorNode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.mp4"
            with self.assertRaisesRegex(
                _MediaProcessFailure,
                "FINAL_OUTPUT_MISSING",
            ):
                node._validate_final_output(
                    str(missing),
                    context=_context(),
                    require_audio=False,
                )

            empty = root / "empty.mp4"
            empty.write_bytes(b"")
            with self.assertRaisesRegex(
                _MediaProcessFailure,
                "FINAL_OUTPUT_EMPTY",
            ):
                node._validate_final_output(
                    str(empty),
                    context=_context(),
                    require_audio=False,
                )

            invalid = root / "invalid.mp4"
            invalid.write_bytes(b"not-empty")
            with (
                patch.object(
                    node,
                    "_run_bounded_media_process",
                    return_value=_MediaProcessResult(0, "not-json", "", 0.1),
                ),
                self.assertRaisesRegex(
                    _MediaProcessFailure,
                    "FINAL_OUTPUT_PROBE_INVALID",
                ),
            ):
                node._validate_final_output(
                    str(invalid),
                    context=_context(),
                    require_audio=False,
                )

    def test_final_postcondition_requires_video_and_configured_audio(self) -> None:
        node = FFmpegCompositorNode()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "final.mp4"
            output.write_bytes(b"fixture")
            cases = (
                ('{"streams": [{"codec_type": "audio"}]}', False,
                 "FINAL_OUTPUT_VIDEO_STREAM_MISSING"),
                ('{"streams": [{"codec_type": "video"}]}', True,
                 "FINAL_OUTPUT_AUDIO_STREAM_MISSING"),
            )
            for payload, require_audio, code in cases:
                with self.subTest(code=code), patch.object(
                    node,
                    "_run_bounded_media_process",
                    return_value=_MediaProcessResult(0, payload, "", 0.1),
                ), self.assertRaisesRegex(_MediaProcessFailure, code):
                    node._validate_final_output(
                        str(output),
                        context=_context(),
                        require_audio=require_audio,
                    )

    def test_final_postcondition_accepts_video_and_audio_streams(self) -> None:
        node = FFmpegCompositorNode()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "final.mp4"
            output.write_bytes(b"fixture")
            payload = (
                '{"streams": [{"codec_type": "video"}, '
                '{"codec_type": "audio"}]}'
            )
            with patch.object(
                node,
                "_run_bounded_media_process",
                return_value=_MediaProcessResult(0, payload, "", 0.1),
            ):
                node._validate_final_output(
                    str(output),
                    context=_context(),
                    require_audio=True,
                )


class RenderFailurePropagationTests(unittest.TestCase):
    def test_compositor_failure_code_is_preserved_for_child_result(self) -> None:
        class _FailingCompositor:
            def execute(self, _context):
                raise _MediaProcessFailure(
                    "FINAL_FFMPEG_TIMEOUT",
                    stage="FINAL_PROCESS_EXITED",
                )

        context = _context()
        self.assertFalse(routes_dsl._run_compositor(_FailingCompositor(), context))
        self.assertEqual(
            context.config["render_failure_code"],
            "FINAL_FFMPEG_TIMEOUT",
        )


if __name__ == "__main__":
    unittest.main()
