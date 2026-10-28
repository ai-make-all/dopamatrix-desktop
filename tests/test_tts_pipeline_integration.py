from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.core.context import WorkflowContext
from src.nodes.compositor import FFmpegCompositorNode
from src.nodes.subtitle import SubtitleNode
from src.nodes.tts_node import TTSNode
from src.services.tts_provider import TTSProviderResult


class _DeterministicProvider:
    provider_id = "elevenlabs"

    def resolve_voice_id(self, language: str) -> str:
        return f"fake_{language}"

    def synthesize(self, request, *, attempt_timeout_seconds):
        request.output_audio_path.write_bytes(b"ID3" + b"a" * 1021)
        request.output_timing_path.write_text(
            "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nHello\n",
            encoding="utf-8",
        )
        return TTSProviderResult(
            audio_path=request.output_audio_path,
            audio_format="mp3",
            timing_path=request.output_timing_path,
            provider_id=self.provider_id,
            safe_metadata={"fixture": True},
        )


@contextmanager
def _working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class TTSPipelineIntegrationTests(unittest.TestCase):
    def test_fake_provider_reaches_subtitle_and_ffmpeg_command_boundary(self) -> None:
        context = WorkflowContext(task_id="pipeline", test_language="en")
        context.config.update(
            {
                "execution_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "file_sid": "aaaaaaaa",
                "child_index": 0,
                "internal_output_root": "output",
            }
        )
        context.set_asset("tts_script", {"en": "Hello"})
        context.set_asset("timeline", SimpleNamespace(tracks=[], audio_tracks=[]))
        commands: list[list[str]] = []

        class FakePopen:
            def __init__(self, command, **_kwargs):
                commands.append(command)
                self.stdout = []
                self.stderr = []
                self.returncode = 0

            def wait(self):
                return 0

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with _working_directory(root):
                TTSNode(
                    output_dir="output",
                    provider=_DeterministicProvider(),
                    attempt_token_factory=lambda: "fixed",
                ).execute(context)
                SubtitleNode().execute(context)
                compositor = FFmpegCompositorNode()
                compositor._build_filtergraph = lambda _timeline, language: (
                    [],
                    "[0:v]null[outv]",
                    "",
                )
                compositor._ws_broadcast = lambda *_args, **_kwargs: None
                with (
                    patch("src.nodes.compositor.get_ffmpeg_path", return_value="ffmpeg"),
                    patch("src.nodes.compositor.subprocess.Popen", FakePopen),
                    patch.object(compositor, "_probe_duration", return_value=1.0),
                    patch.object(
                        compositor,
                        "_validate_final_output",
                        return_value=None,
                    ),
                ):
                    compositor.execute(context)

                voice = context.variants["en"]["voice_audio"]
                vtt = context.variants["en"]["vtt_path"]
                subtitle = context.variants["en"]["subtitle_ass"]
                self.assertEqual(Path(voice).name, "voice_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa_en.mp3")
                self.assertEqual(Path(vtt).name, "voice_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa_en.vtt")
                self.assertEqual(Path(subtitle).name, "sub_aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa_en.ass")
                self.assertEqual(len(commands), 2)
                variant_command = commands[1]
                self.assertIn(voice, variant_command)
                self.assertIn("-filter_complex", variant_command)
                self.assertIn("subtitles=", " ".join(variant_command))


if __name__ == "__main__":
    unittest.main()
