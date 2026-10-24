from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.context import WorkflowContext
from src.core.timeline import AudioTrack, Clip, Timeline, Track
from src.nodes.compositor import FFmpegCompositorNode
from src.utils.env_utils import get_ffmpeg_path


def _video_timeline(*clips: Clip) -> Timeline:
    timeline = Timeline()
    track = Track("main", 0, "video")
    for clip in clips:
        track.add_clip(clip)
    timeline.add_track(track)
    return timeline


def _add_audio_track(
    timeline: Timeline,
    audio_type: str,
    source_path: Path,
    duration: float = 2.5,
) -> None:
    track = AudioTrack(f"{audio_type}-track", audio_type)
    track.add_clip(Clip(str(source_path), 0.0, duration))
    timeline.add_audio_track(track)


class _SuccessfulPopen:
    commands: list[list[str]] = []

    def __init__(self, command, **_kwargs):
        self.commands.append(command)
        self.stdout = []
        self.stderr = []
        self.returncode = 0

    def wait(self):
        return 0


class ENDeliveryRecoveryUnitTests(unittest.TestCase):
    def test_single_clip_is_normalized_and_frozen_to_target(self) -> None:
        node = FFmpegCompositorNode()
        node.target_w, node.target_h = (720, 1280)
        node.target_duration = 15.0
        timeline = _video_timeline(Clip("two-seconds.mp4", 0.0, 15.0))

        inputs, video_fg, _audio_fg = node._build_filtergraph(timeline)

        self.assertEqual(inputs, ["-i", "two-seconds.mp4"])
        self.assertIn("scale=720:1280:force_original_aspect_ratio=decrease", video_fg)
        self.assertIn("pad=720:1280:(ow-iw)/2:(oh-ih)/2", video_fg)
        self.assertIn("setsar=1", video_fg)
        self.assertIn("tpad=stop_mode=clone:stop_duration=15.000000", video_fg)
        self.assertIn("trim=duration=15.000000", video_fg)

    def test_long_single_clip_is_bounded_by_target_trim(self) -> None:
        node = FFmpegCompositorNode()
        node.target_duration = 15.0
        clip = Clip("long.mp4", 0.0, 30.0)
        timeline = _video_timeline(clip)

        _inputs, video_fg, _audio_fg = node._build_filtergraph(timeline)

        self.assertEqual(node._planned_clip_duration(clip, clip_count=1), 15.0)
        self.assertIn("trim=duration=15.000000", video_fg)

    def test_existing_multi_clip_concat_keeps_normalization(self) -> None:
        node = FFmpegCompositorNode()
        node.target_duration = 15.0
        timeline = _video_timeline(
            Clip("first.mp4", 0.0, 7.5),
            Clip("second.mp4", 7.5, 7.5),
        )

        _inputs, video_fg, _audio_fg = node._build_filtergraph(timeline)

        self.assertEqual(video_fg.count("scale=720:1280"), 2)
        self.assertIn("concat=n=2:v=1:a=0", video_fg)
        self.assertNotIn("tpad=", video_fg)
        self.assertNotIn("trim=duration=", video_fg)

    def test_only_single_main_video_track_gets_duration_extension(self) -> None:
        node = FFmpegCompositorNode()
        node.target_duration = 15.0
        timeline = _video_timeline(Clip("main.mp4", 0.0, 2.0))
        secondary = Track("secondary", 1, "video")
        secondary.add_clip(Clip("secondary.mp4", 0.0, 2.0))
        timeline.add_track(secondary)

        _inputs, video_fg, _audio_fg = node._build_filtergraph(timeline)

        self.assertEqual(
            video_fg.count("tpad=stop_mode=clone:stop_duration=15.000000"),
            1,
        )

    def test_multi_clip_bgm_and_sfx_keep_legacy_unbounded_mix(self) -> None:
        _SuccessfulPopen.commands = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            master = root / "master.mp4"
            bgm = root / "bgm.mp3"
            sfx = root / "sfx.mp3"
            for path in (master, bgm, sfx):
                path.write_bytes(b"fixture")
            timeline = _video_timeline(
                Clip("first.mp4", 0.0, 2.0),
                Clip("second.mp4", 2.0, 2.0),
            )
            _add_audio_track(timeline, "bgm", bgm)
            _add_audio_track(timeline, "sfx", sfx)
            context = WorkflowContext(task_id="multi-audio", target_duration=1)
            context.set_asset("timeline", timeline)
            context.variants = {"en": {}}
            node = FFmpegCompositorNode()
            node._ws_broadcast = lambda *_args, **_kwargs: None

            with patch("src.nodes.compositor.subprocess.Popen", _SuccessfulPopen):
                node._render_variant(context, str(master), "ffmpeg")

        command = _SuccessfulPopen.commands[0]
        filter_complex = command[command.index("-filter_complex") + 1]
        self.assertIn("volume=0.2", filter_complex)
        self.assertIn(
            "amix=inputs=2:duration=longest:dropout_transition=2",
            filter_complex,
        )
        self.assertNotIn("apad", filter_complex)
        self.assertNotIn("atrim=duration=1.000000", filter_complex)

    def test_short_voice_is_padded_and_subtitles_are_retained(self) -> None:
        _SuccessfulPopen.commands = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            master = root / "master.mp4"
            voice = root / "voice.mp3"
            subtitle = root / "sub.ass"
            master.write_bytes(b"master")
            voice.write_bytes(b"voice")
            subtitle.write_text("[Events]\n", encoding="utf-8")

            context = WorkflowContext(task_id="short-voice", target_duration=15)
            context.set_asset(
                "timeline", _video_timeline(Clip("source.mp4", 0.0, 2.0))
            )
            context.variants = {
                "en": {"voice_audio": str(voice), "subtitle_ass": str(subtitle)}
            }
            node = FFmpegCompositorNode()
            node._ws_broadcast = lambda *_args, **_kwargs: None

            with (
                patch.object(node, "_probe_duration", return_value=4.0),
                patch("src.nodes.compositor.subprocess.Popen", _SuccessfulPopen),
            ):
                node._render_variant(context, str(master), "ffmpeg")

        command = _SuccessfulPopen.commands[0]
        joined = " ".join(command)
        self.assertIn("apad,atrim=duration=15.000000[voice_target]", joined)
        self.assertIn("subtitles=", joined)
        self.assertIn("-shortest", command)

    def test_multi_clip_short_voice_uses_actual_master_duration(self) -> None:
        _SuccessfulPopen.commands = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            master = root / "master.mp4"
            voice = root / "voice.mp3"
            master.write_bytes(b"master")
            voice.write_bytes(b"voice")
            context = WorkflowContext(task_id="multi-short-voice", target_duration=1)
            context.set_asset(
                "timeline",
                _video_timeline(
                    Clip("first.mp4", 0.0, 7.0),
                    Clip("second.mp4", 7.0, 8.0),
                ),
            )
            context.variants = {"en": {"voice_audio": str(voice)}}
            node = FFmpegCompositorNode()
            node._ws_broadcast = lambda *_args, **_kwargs: None

            def duration_for(path: str) -> float:
                return 15.0 if path == str(master) else 2.0

            with (
                patch.object(node, "_probe_duration", side_effect=duration_for),
                patch("src.nodes.compositor.subprocess.Popen", _SuccessfulPopen),
            ):
                node._render_variant(context, str(master), "ffmpeg")

        command = _SuccessfulPopen.commands[0]
        joined = " ".join(command)
        self.assertIn("apad,atrim=duration=15.000000[voice_target]", joined)
        self.assertNotIn("atrim=duration=1.000000", joined)
        self.assertIn("-shortest", command)

    def test_multi_clip_only_tts_gets_duration_protection(self) -> None:
        _SuccessfulPopen.commands = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            master = root / "master.mp4"
            voice = root / "voice.mp3"
            bgm = root / "bgm.mp3"
            sfx = root / "sfx.mp3"
            for path in (master, voice, bgm, sfx):
                path.write_bytes(b"fixture")
            timeline = _video_timeline(
                Clip("first.mp4", 0.0, 7.0),
                Clip("second.mp4", 7.0, 8.0),
            )
            _add_audio_track(timeline, "bgm", bgm)
            _add_audio_track(timeline, "sfx", sfx)
            context = WorkflowContext(task_id="multi-scoped-audio", target_duration=15)
            context.set_asset("timeline", timeline)
            context.variants = {"en": {"voice_audio": str(voice)}}
            node = FFmpegCompositorNode()
            node._ws_broadcast = lambda *_args, **_kwargs: None

            with (
                patch.object(node, "_probe_duration", side_effect=[15.0, 2.0]),
                patch("src.nodes.compositor.subprocess.Popen", _SuccessfulPopen),
            ):
                node._render_variant(context, str(master), "ffmpeg")

        command = _SuccessfulPopen.commands[0]
        filter_complex = command[command.index("-filter_complex") + 1]
        self.assertIn("[1:a]apad,atrim=duration=15.000000[voice_target]", filter_complex)
        self.assertIn("[2:a]volume=0.2[bgm2]", filter_complex)
        self.assertIn("[3:a]", filter_complex)
        self.assertIn(
            "amix=inputs=3:duration=longest:dropout_transition=2[outa]",
            filter_complex,
        )
        self.assertEqual(filter_complex.count("apad"), 1)
        self.assertEqual(filter_complex.count("atrim=duration=15.000000"), 1)

    def test_multi_clip_voice_longer_than_master_fails_before_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            master = root / "master.mp4"
            voice = root / "voice.mp3"
            master.write_bytes(b"master")
            voice.write_bytes(b"voice")
            context = WorkflowContext(task_id="multi-long-voice", target_duration=15)
            context.set_asset(
                "timeline",
                _video_timeline(
                    Clip("first.mp4", 0.0, 7.0),
                    Clip("second.mp4", 7.0, 8.0),
                ),
            )
            context.variants = {"en": {"voice_audio": str(voice)}}
            node = FFmpegCompositorNode()

            with (
                patch.object(node, "_probe_duration", side_effect=[15.0, 15.2]),
                patch("src.nodes.compositor.subprocess.Popen") as popen,
                self.assertRaisesRegex(
                    RuntimeError, "TTS_AUDIO_EXCEEDS_TARGET_DURATION"
                ),
            ):
                node._render_variant(context, str(master), "ffmpeg")
            popen.assert_not_called()

    def test_multi_clip_unparseable_durations_fail_before_ffmpeg(self) -> None:
        for durations, error in (
            ([0.0], "MASTER_VIDEO_DURATION_UNVERIFIED"),
            ([15.0, 0.0], "TTS_AUDIO_DURATION_UNVERIFIED"),
        ):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                master = root / "master.mp4"
                voice = root / "voice.mp3"
                master.write_bytes(b"master")
                voice.write_bytes(b"voice")
                context = WorkflowContext(task_id="multi-bad-duration", target_duration=15)
                context.set_asset(
                    "timeline",
                    _video_timeline(
                        Clip("first.mp4", 0.0, 7.0),
                        Clip("second.mp4", 7.0, 8.0),
                    ),
                )
                context.variants = {"en": {"voice_audio": str(voice)}}
                node = FFmpegCompositorNode()

                with (
                    patch.object(node, "_probe_duration", side_effect=durations),
                    patch("src.nodes.compositor.subprocess.Popen") as popen,
                    self.assertRaisesRegex(RuntimeError, error),
                ):
                    node._render_variant(context, str(master), "ffmpeg")
                popen.assert_not_called()

    def test_voice_longer_than_target_fails_before_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            master = root / "master.mp4"
            voice = root / "voice.mp3"
            master.write_bytes(b"master")
            voice.write_bytes(b"voice")
            context = WorkflowContext(task_id="long-voice", target_duration=15)
            context.set_asset(
                "timeline", _video_timeline(Clip("source.mp4", 0.0, 2.0))
            )
            context.variants = {"en": {"voice_audio": str(voice)}}
            node = FFmpegCompositorNode()

            with (
                patch.object(node, "_probe_duration", return_value=15.2),
                patch("src.nodes.compositor.subprocess.Popen") as popen,
                self.assertRaisesRegex(
                    RuntimeError, "TTS_AUDIO_EXCEEDS_TARGET_DURATION"
                ),
            ):
                node._render_variant(context, str(master), "ffmpeg")
            popen.assert_not_called()

    def test_unparseable_voice_duration_fails_before_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            master = root / "master.mp4"
            voice = root / "voice.mp3"
            master.write_bytes(b"master")
            voice.write_bytes(b"voice")
            context = WorkflowContext(task_id="bad-voice", target_duration=15)
            context.set_asset(
                "timeline", _video_timeline(Clip("source.mp4", 0.0, 2.0))
            )
            context.variants = {"en": {"voice_audio": str(voice)}}
            node = FFmpegCompositorNode()

            with (
                patch.object(node, "_probe_duration", return_value=0.0),
                patch("src.nodes.compositor.subprocess.Popen") as popen,
                self.assertRaisesRegex(
                    RuntimeError, "TTS_AUDIO_DURATION_UNVERIFIED"
                ),
            ):
                node._render_variant(context, str(master), "ffmpeg")
            popen.assert_not_called()

    def test_tts_disabled_does_not_probe_or_map_existing_voice(self) -> None:
        _SuccessfulPopen.commands = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            master = root / "master.mp4"
            voice = root / "voice.mp3"
            master.write_bytes(b"master")
            voice.write_bytes(b"voice")
            context = WorkflowContext(task_id="tts-off", target_duration=15)
            context.config["enable_tts"] = False
            context.set_asset(
                "timeline", _video_timeline(Clip("source.mp4", 0.0, 2.0))
            )
            context.variants = {"en": {"voice_audio": str(voice)}}
            node = FFmpegCompositorNode()
            node._ws_broadcast = lambda *_args, **_kwargs: None

            with (
                patch.object(node, "_probe_duration") as probe,
                patch("src.nodes.compositor.subprocess.Popen", _SuccessfulPopen),
            ):
                node._render_variant(context, str(master), "ffmpeg")

            probe.assert_not_called()
            self.assertNotIn(str(voice), _SuccessfulPopen.commands[0])


class ENDeliveryRecoveryRealFFmpegTests(unittest.TestCase):
    def test_real_ffmpeg_two_seconds_becomes_fifteen_second_vertical_output(self) -> None:
        ffmpeg = Path(get_ffmpeg_path("ffmpeg.exe"))
        ffprobe = Path(get_ffmpeg_path("ffprobe.exe"))
        if not ffmpeg.is_file() or not ffprobe.is_file():
            self.skipTest("repository FFmpeg/ffprobe binaries are unavailable")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            voice = root / "voice.mp3"
            bgm = root / "bgm.mp3"
            subtitle = root / "subtitle.ass"
            output = root / "output"
            output.mkdir()

            subprocess.run(
                [
                    str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                    "color=c=blue:s=320x240:r=30:d=2", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-y", str(source),
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=1", "-c:a", "libmp3lame",
                    "-b:a", "128k", "-y", str(voice),
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=220:duration=2.5", "-c:a", "libmp3lame",
                    "-b:a", "128k", "-y", str(bgm),
                ],
                check=True,
                capture_output=True,
            )
            subtitle.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\n\n"
                "[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,"
                "&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,40,1\n\n"
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
                "Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Offline test\n",
                encoding="utf-8",
            )

            context = WorkflowContext(
                task_id="real-offline",
                aspect_ratio="9:16",
                test_language="en",
                target_duration=15,
            )
            context.config.update(
                {
                    "internal_output_root": str(output),
                    "file_sid": "offline",
                    "execution_id": "offline-execution",
                    "child_index": 0,
                    "ws_terminal_managed_by_coordinator": True,
                }
            )
            timeline = _video_timeline(
                Clip(str(source), 0.0, 15.0, beat_index=0)
            )
            _add_audio_track(timeline, "bgm", bgm)
            context.set_asset("timeline", timeline)
            context.variants = {
                "en": {"voice_audio": str(voice), "subtitle_ass": str(subtitle)}
            }
            node = FFmpegCompositorNode()
            node._ws_broadcast = lambda *_args, **_kwargs: None
            node.execute(context)

            final_path = Path(context.variants["en"]["final_video"])
            probe = subprocess.run(
                [
                    str(ffprobe), "-v", "error", "-show_streams", "-show_format",
                    "-of", "json", str(final_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            metadata = json.loads(probe.stdout)
            streams = metadata["streams"]
            video_stream = next(s for s in streams if s["codec_type"] == "video")
            audio_stream = next(s for s in streams if s["codec_type"] == "audio")

            self.assertEqual((video_stream["width"], video_stream["height"]), (720, 1280))
            self.assertEqual(video_stream["codec_name"], "h264")
            self.assertEqual(audio_stream["codec_name"], "aac")
            self.assertAlmostEqual(float(metadata["format"]["duration"]), 15.0, delta=0.1)
            self.assertAlmostEqual(float(audio_stream["duration"]), 15.0, delta=0.1)
            print(
                "REAL_FFMPEG_PROBE="
                f"video={video_stream['codec_name']} "
                f"size={video_stream['width']}x{video_stream['height']} "
                f"format_duration={metadata['format']['duration']} "
                f"audio={audio_stream['codec_name']} "
                f"audio_duration={audio_stream['duration']}"
            )

    def test_real_ffmpeg_multi_clip_keeps_existing_timeline_and_audio_mix(self) -> None:
        ffmpeg = Path(get_ffmpeg_path("ffmpeg.exe"))
        ffprobe = Path(get_ffmpeg_path("ffprobe.exe"))
        if not ffmpeg.is_file() or not ffprobe.is_file():
            self.skipTest("repository FFmpeg/ffprobe binaries are unavailable")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.mp4"
            second = root / "second.mp4"
            bgm = root / "bgm.mp3"
            sfx = root / "sfx.mp3"
            output = root / "output"
            output.mkdir()

            for path, color in ((first, "blue"), (second, "green")):
                subprocess.run(
                    [
                        str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                        f"color=c={color}:s=320x240:r=30:d=0.75",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-y", str(path),
                    ],
                    check=True,
                    capture_output=True,
                )
            for path, frequency in ((bgm, 220), (sfx, 660)):
                subprocess.run(
                    [
                        str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                        f"sine=frequency={frequency}:duration=2.5",
                        "-c:a", "libmp3lame", "-b:a", "128k",
                        "-y", str(path),
                    ],
                    check=True,
                    capture_output=True,
                )

            timeline = _video_timeline(
                Clip(str(first), 0.0, 0.75, beat_index=0),
                Clip(str(second), 0.75, 0.75, beat_index=1),
            )
            _add_audio_track(timeline, "bgm", bgm)
            _add_audio_track(timeline, "sfx", sfx)
            context = WorkflowContext(
                task_id="real-multi-offline",
                aspect_ratio="9:16",
                test_language="en",
                target_duration=1,
            )
            context.config.update(
                {
                    "internal_output_root": str(output),
                    "file_sid": "offline-multi",
                    "execution_id": "offline-multi-execution",
                    "child_index": 0,
                    "enable_tts": False,
                    "enable_subtitles": False,
                    "ws_terminal_managed_by_coordinator": True,
                }
            )
            context.set_asset("timeline", timeline)
            context.variants = {"en": {"voice_audio": str(sfx)}}
            node = FFmpegCompositorNode()
            node._ws_broadcast = lambda *_args, **_kwargs: None
            node.execute(context)

            final_path = Path(context.variants["en"]["final_video"])
            probe = subprocess.run(
                [
                    str(ffprobe), "-v", "error", "-show_streams", "-show_format",
                    "-of", "json", str(final_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            metadata = json.loads(probe.stdout)
            streams = metadata["streams"]
            video_stream = next(s for s in streams if s["codec_type"] == "video")
            audio_stream = next(s for s in streams if s["codec_type"] == "audio")
            duration = float(metadata["format"]["duration"])

            self.assertEqual((video_stream["width"], video_stream["height"]), (720, 1280))
            self.assertEqual(video_stream["codec_name"], "h264")
            self.assertEqual(audio_stream["codec_name"], "aac")
            self.assertGreater(duration, 1.4)
            self.assertLess(duration, 1.7)
            print(
                "REAL_MULTI_FFMPEG_PROBE="
                f"video={video_stream['codec_name']} "
                f"size={video_stream['width']}x{video_stream['height']} "
                f"format_duration={metadata['format']['duration']} "
                f"audio={audio_stream['codec_name']}"
            )

    def test_real_ffmpeg_multi_clip_short_tts_reaches_video_duration(self) -> None:
        ffmpeg = Path(get_ffmpeg_path("ffmpeg.exe"))
        ffprobe = Path(get_ffmpeg_path("ffprobe.exe"))
        if not ffmpeg.is_file() or not ffprobe.is_file():
            self.skipTest("repository FFmpeg/ffprobe binaries are unavailable")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first-red.mp4"
            second = root / "second-blue.mp4"
            voice = root / "short-voice.mp3"
            subtitle = root / "safe.ass"
            output = root / "output"
            output.mkdir()

            for path, color, duration in (
                (first, "red", 7),
                (second, "blue", 8),
            ):
                subprocess.run(
                    [
                        str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                        f"color=c={color}:s=320x240:r=30:d={duration}",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-y", str(path),
                    ],
                    check=True,
                    capture_output=True,
                )
            subprocess.run(
                [
                    str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-c:a", "libmp3lame",
                    "-b:a", "128k", "-y", str(voice),
                ],
                check=True,
                capture_output=True,
            )
            subtitle.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\n\n"
                "[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,"
                "&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,40,1\n\n"
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
                "Effect, Text\n"
                "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,"
                "Safe multi clip subtitle\n",
                encoding="utf-8",
            )

            timeline = _video_timeline(
                Clip(str(first), 0.0, 7.0, beat_index=0),
                Clip(str(second), 7.0, 8.0, beat_index=1),
            )
            context = WorkflowContext(
                task_id="real-multi-short-tts",
                aspect_ratio="9:16",
                test_language="en",
                target_duration=15,
            )
            context.config.update(
                {
                    "internal_output_root": str(output),
                    "file_sid": "offline-multi-short",
                    "execution_id": "offline-multi-short-execution",
                    "child_index": 0,
                    "enable_tts": True,
                    "enable_subtitles": True,
                    "ws_terminal_managed_by_coordinator": True,
                }
            )
            context.set_asset("timeline", timeline)
            context.variants = {
                "en": {
                    "voice_audio": str(voice),
                    "subtitle_ass": str(subtitle),
                }
            }
            node = FFmpegCompositorNode()
            node._ws_broadcast = lambda *_args, **_kwargs: None
            node.execute(context)

            master_path = output / "master_video_offline-multi-short.mp4"
            final_path = Path(context.variants["en"]["final_video"])

            def probe(path: Path) -> dict:
                result = subprocess.run(
                    [
                        str(ffprobe), "-v", "error", "-show_streams",
                        "-show_format", "-of", "json", str(path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                return json.loads(result.stdout)

            def frame_rgb(path: Path, second: float) -> tuple[int, int, int]:
                result = subprocess.run(
                    [
                        str(ffmpeg), "-v", "error", "-ss", str(second),
                        "-i", str(path), "-vf", "scale=1:1", "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
                    ],
                    check=True,
                    capture_output=True,
                )
                return tuple(result.stdout[:3])

            def audio_peak(path: Path, start: float, duration: float) -> float:
                result = subprocess.run(
                    [
                        str(ffmpeg), "-v", "error", "-ss", str(start),
                        "-t", str(duration), "-i", str(path), "-map", "0:a:0",
                        "-ac", "1", "-ar", "16000", "-f", "f32le", "-",
                    ],
                    check=True,
                    capture_output=True,
                )
                sample_count = len(result.stdout) // 4
                samples = struct.unpack(f"<{sample_count}f", result.stdout)
                return max((abs(sample) for sample in samples), default=0.0)

            master_metadata = probe(master_path)
            final_metadata = probe(final_path)
            final_streams = final_metadata["streams"]
            video_stream = next(
                stream for stream in final_streams if stream["codec_type"] == "video"
            )
            audio_stream = next(
                stream for stream in final_streams if stream["codec_type"] == "audio"
            )
            first_rgb = frame_rgb(final_path, 3)
            second_rgb = frame_rgb(final_path, 10)
            voiced_peak = audio_peak(final_path, 0.25, 1.0)
            padded_peak = audio_peak(final_path, 5.0, 2.0)
            final_sha256 = hashlib.sha256(final_path.read_bytes()).hexdigest().upper()

            self.assertAlmostEqual(
                float(master_metadata["format"]["duration"]), 15.0, delta=0.1
            )
            self.assertAlmostEqual(
                float(final_metadata["format"]["duration"]), 15.0, delta=0.1
            )
            self.assertEqual((video_stream["width"], video_stream["height"]), (720, 1280))
            self.assertEqual(video_stream["codec_name"], "h264")
            self.assertEqual(audio_stream["codec_name"], "aac")
            self.assertGreater(first_rgb[0], first_rgb[2])
            self.assertGreater(second_rgb[2], second_rgb[0])
            self.assertGreater(voiced_peak, 0.01)
            self.assertLess(padded_peak, 0.001)
            print(
                "REAL_MULTI_SHORT_TTS_PROBE="
                f"master_duration={master_metadata['format']['duration']} "
                f"final_duration={final_metadata['format']['duration']} "
                f"video={video_stream['codec_name']} "
                f"size={video_stream['width']}x{video_stream['height']} "
                f"audio={audio_stream['codec_name']} "
                f"audio_duration={audio_stream.get('duration')} "
                f"first_rgb={first_rgb} second_rgb={second_rgb} "
                f"voiced_peak={voiced_peak:.6f} padded_peak={padded_peak:.6f} "
                f"final_bytes={final_path.stat().st_size} "
                f"final_sha256={final_sha256}"
            )


if __name__ == "__main__":
    unittest.main()
