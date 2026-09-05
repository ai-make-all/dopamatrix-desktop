import os
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.core.context import WorkflowContext
from src.nodes.compositor import FFmpegCompositorNode
from src.nodes.cover_node import CoverNode
from src.nodes.subtitle import SubtitleNode
from src.nodes.tts_node import TTSNode


@contextmanager
def _temporary_working_directory():
    previous = os.getcwd()
    with tempfile.TemporaryDirectory() as directory:
        os.chdir(directory)
        try:
            yield Path(directory)
        finally:
            os.chdir(previous)


def _child_context(task_id: str, execution_id: str, child_index: int) -> WorkflowContext:
    context = WorkflowContext(task_id=task_id, test_language="en")
    context.config.update(
        {
            "execution_id": execution_id,
            "file_sid": uuid.UUID(execution_id).hex[:8],
            "child_index": child_index,
        }
    )
    return context


def _fake_tts_run(voice, text, output_path, vtt_path):
    output_path.write_bytes(b"a" * 2048)
    vtt_path.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n",
        encoding="utf-8",
    )


class WritableNamespaceTests(unittest.TestCase):
    def test_two_children_get_distinct_full_uuid_tts_paths(self):
        task_id = "shared-task"
        execution_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for child_index, execution_id in enumerate(execution_ids):
                context = _child_context(task_id, execution_id, child_index)
                context.set_asset("tts_script", {"en": "Hello child"})
                node = TTSNode(output_dir=directory)
                node._run_tts = _fake_tts_run

                node.execute(context)
                paths.append(
                    (
                        context.variants["en"]["voice_audio"],
                        context.variants["en"]["vtt_path"],
                    )
                )

            self.assertNotEqual(paths[0][0], paths[1][0])
            self.assertNotEqual(paths[0][1], paths[1][1])
            for execution_id, (mp3_path, vtt_path) in zip(execution_ids, paths):
                self.assertEqual(Path(mp3_path).name, f"voice_{execution_id}_en.mp3")
                self.assertEqual(Path(vtt_path).name, f"voice_{execution_id}_en.vtt")
                self.assertTrue(Path(mp3_path).is_file())
                self.assertTrue(Path(vtt_path).is_file())

    def test_tts_legacy_direct_call_falls_back_to_context_task(self):
        context = WorkflowContext(
            task_id="legacy-child",
            test_language="en",
            batch_size=4,
        )
        context.set_asset("tts_script", {"en": "Legacy text"})

        with tempfile.TemporaryDirectory() as directory:
            node = TTSNode(output_dir=directory)
            node._run_tts = _fake_tts_run
            node.execute(context)

            self.assertEqual(
                Path(context.variants["en"]["voice_audio"]).name,
                "voice_legacy-child_en.mp3",
            )
            self.assertEqual(
                Path(context.variants["en"]["vtt_path"]).name,
                "voice_legacy-child_en.vtt",
            )

    def test_new_child_tts_context_cannot_fall_back_to_shared_task_id(self):
        context = WorkflowContext(task_id="shared-task", test_language="en")
        context.config["child_index"] = 0
        context.set_asset("tts_script", {"en": "Child text"})

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "missing execution_id"):
                TTSNode(output_dir=directory).execute(context)

    def test_tts_empty_script_skip_is_unchanged(self):
        context = WorkflowContext(task_id="shared-task", test_language="en")
        context.config["child_index"] = 0

        with tempfile.TemporaryDirectory() as directory:
            TTSNode(output_dir=directory).execute(context)
            self.assertEqual(list(Path(directory).iterdir()), [])

        self.assertEqual(context.variants, {})

    def test_two_children_get_distinct_full_uuid_subtitle_paths(self):
        task_id = "shared-task"
        execution_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        with _temporary_working_directory():
            paths = []
            for child_index, execution_id in enumerate(execution_ids):
                context = _child_context(task_id, execution_id, child_index)
                context.config["translations"] = {"en": "Hello subtitle"}
                context.config["subtitle_end"] = 2.0

                SubtitleNode().execute(context)
                paths.append(context.variants["en"]["subtitle_ass"])

            self.assertNotEqual(paths[0], paths[1])
            for execution_id, ass_path in zip(execution_ids, paths):
                self.assertEqual(Path(ass_path).name, f"sub_{execution_id}_en.ass")
                self.assertTrue(Path(ass_path).is_file())

    def test_subtitle_legacy_direct_call_falls_back_to_context_task(self):
        context = WorkflowContext(
            task_id="legacy-child",
            test_language="en",
            batch_size=4,
        )
        context.config["translations"] = {"en": "Legacy subtitle"}

        with _temporary_working_directory():
            SubtitleNode().execute(context)
            ass_path = context.variants["en"]["subtitle_ass"]

            self.assertEqual(Path(ass_path).name, "sub_legacy-child_en.ass")
            self.assertTrue(Path(ass_path).is_file())

    def test_vtt_subtitle_path_uses_full_execution_id(self):
        execution_id = str(uuid.uuid4())
        context = _child_context("shared-task", execution_id, 0)

        with _temporary_working_directory() as directory:
            vtt_path = directory / "voice.vtt"
            vtt_path.write_text(
                "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nHello\n",
                encoding="utf-8",
            )
            context.set_variant_asset("en", "vtt_path", str(vtt_path))

            SubtitleNode().execute(context)
            ass_path = context.variants["en"]["subtitle_ass"]

            self.assertEqual(Path(ass_path).name, f"sub_{execution_id}_en.ass")
            self.assertTrue(Path(ass_path).is_file())

    def test_new_child_subtitle_context_cannot_fall_back_to_shared_task_id(self):
        context = WorkflowContext(task_id="shared-task", test_language="en")
        context.config.update(
            {
                "child_index": 0,
                "translations": {"en": "Child subtitle"},
            }
        )

        with _temporary_working_directory():
            with self.assertRaisesRegex(RuntimeError, "missing execution_id"):
                SubtitleNode().execute(context)

    def test_subtitle_empty_text_skip_is_unchanged(self):
        context = WorkflowContext(task_id="shared-task", test_language="en")
        context.config["child_index"] = 0

        with _temporary_working_directory() as directory:
            SubtitleNode().execute(context)
            self.assertEqual(list((directory / "output").iterdir()), [])

        self.assertEqual(context.variants, {})


class ShortOutputFilenameTests(unittest.TestCase):
    def test_master_final_and_cover_prefer_explicit_file_sid(self):
        context = WorkflowContext(task_id="shared-task")
        context.config.update(
            {
                "execution_id": str(uuid.uuid4()),
                "file_sid": "deadbeef",
                "child_index": 0,
            }
        )

        self.assertEqual(
            FFmpegCompositorNode._master_output_path(context),
            "output/master_video_deadbeef.mp4",
        )
        self.assertEqual(
            FFmpegCompositorNode._final_output_path(context, "en"),
            "output/final_en_deadbeef.mp4",
        )
        self.assertEqual(
            CoverNode._cover_output_path(context, os.path.join("output", "video.mp4")),
            os.path.join("output", "cover_deadbeef.jpg"),
        )

    def test_output_filename_tokens_differ_between_children(self):
        first = _child_context(
            "shared-task",
            "11111111-1111-4111-8111-111111111111",
            0,
        )
        second = _child_context(
            "shared-task",
            "22222222-2222-4222-8222-222222222222",
            1,
        )

        self.assertNotEqual(
            FFmpegCompositorNode._master_output_path(first),
            FFmpegCompositorNode._master_output_path(second),
        )
        self.assertNotEqual(
            FFmpegCompositorNode._final_output_path(first, "en"),
            FFmpegCompositorNode._final_output_path(second, "en"),
        )
        self.assertNotEqual(
            CoverNode._cover_output_path(first, os.path.join("output", "video.mp4")),
            CoverNode._cover_output_path(second, os.path.join("output", "video.mp4")),
        )

    def test_direct_output_name_falls_back_to_task_id(self):
        context = WorkflowContext(task_id="legacy-context")

        self.assertEqual(
            FFmpegCompositorNode._master_output_path(context),
            "output/master_video_legacy-context.mp4",
        )
        self.assertEqual(
            FFmpegCompositorNode._final_output_path(context, "en"),
            "output/final_en_legacy-context.mp4",
        )
        self.assertEqual(
            CoverNode._cover_output_path(context, os.path.join("output", "video.mp4")),
            os.path.join("output", "cover_legacy-context.jpg"),
        )

    def test_cover_direct_context_uses_task_id(self):
        legacy_context = WorkflowContext(task_id="legacy-context")
        child_context = _child_context(
            "shared-task",
            "55555555-5555-4555-8555-555555555555",
            0,
        )

        self.assertEqual(
            CoverNode._cover_output_path(
                legacy_context,
                os.path.join("output", "video.mp4"),
            ),
            os.path.join("output", "cover_legacy-context.jpg"),
        )
        self.assertEqual(
            CoverNode._cover_output_path(
                child_context,
                os.path.join("output", "video.mp4"),
            ),
            os.path.join("output", "cover_55555555.jpg"),
        )

    def test_new_child_output_context_cannot_use_legacy_file_fallback(self):
        context = WorkflowContext(task_id="shared-task")
        context.config.update(
            {
                "execution_id": str(uuid.uuid4()),
                "child_index": 0,
            }
        )

        with self.assertRaisesRegex(RuntimeError, "missing file_sid"):
            FFmpegCompositorNode._master_output_path(context)
        with self.assertRaisesRegex(RuntimeError, "missing file_sid"):
            CoverNode._cover_output_path(
                context,
                os.path.join("output", "video.mp4"),
            )

    def test_cover_execute_hands_off_explicit_file_sid(self):
        context = _child_context(
            "shared-task",
            "33333333-3333-4333-8333-333333333333",
            0,
        )

        with _temporary_working_directory() as directory:
            video_path = directory / "output" / "final_en_33333333.mp4"
            video_path.parent.mkdir()
            video_path.write_bytes(b"video")
            context.set_variant_asset("en", "final_video", str(video_path))

            node = CoverNode()

            def fake_extract(_video_path, _timestamp, cover_path):
                Path(cover_path).write_bytes(b"jpeg")
                return True

            node._extract_frame = fake_extract
            node.execute(context)

            expected = video_path.parent / "cover_33333333.jpg"
            self.assertEqual(Path(context.get_asset("cover_path")), expected)
            self.assertTrue(expected.is_file())

    def test_compositor_execute_hands_off_file_sid_to_master_and_final(self):
        context = _child_context(
            "shared-task",
            "44444444-4444-4444-8444-444444444444",
            0,
        )
        context.set_asset("timeline", SimpleNamespace(tracks=[], audio_tracks=[]))
        context.variants = {"en": {}}
        commands = []

        class FakePopen:
            def __init__(self, command, **_kwargs):
                commands.append(command)
                self.stdout = []
                self.stderr = []
                self.returncode = 0

            def wait(self):
                return 0

        node = FFmpegCompositorNode()
        node._build_filtergraph = lambda _timeline, language: (
            [],
            "[0:v]null[outv]",
            "",
        )
        node._ws_broadcast = lambda *_args, **_kwargs: None

        with (
            _temporary_working_directory(),
            patch("src.nodes.compositor.get_ffmpeg_path", return_value="ffmpeg"),
            patch("src.nodes.compositor.subprocess.Popen", FakePopen),
        ):
            node.execute(context)

        self.assertEqual(context.get_asset("video_master"), "output/master_video_44444444.mp4")
        self.assertEqual(
            context.variants["en"]["final_video"],
            "output/final_en_44444444.mp4",
        )
        self.assertEqual(commands[0][-1], "output/master_video_44444444.mp4")
        self.assertEqual(commands[1][-1], "output/final_en_44444444.mp4")


if __name__ == "__main__":
    unittest.main()
