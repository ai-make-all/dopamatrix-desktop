"""
AssemblyNode — Phase 4: 时间线拼装节点

职责：
  将前序节点输出的资产（配音 MP3、字幕 ASS）和视频素材，
  根据 script_data 中的场景时长，动态拼装成一条完整的 Timeline，
  供 FFmpegCompositorNode 编译渲染。

数据流：
  读取 → context.assets["script_data"]       (场景脚本 + 总时长计算)
  读取 → context.variants[lang]["voice_audio"] (各语言配音 MP3，由 TTSNode 写入)
  写入 → context.assets["timeline"]           (组装完毕的 Timeline 对象)

设计说明：
  - 背景视频素材通过构造器注入（bg_video_path），支持测试替换。
  - 如果背景视频时长不足，通过多次添加相同 Clip（顺序拼接）来铺满总时长。
    （FFmpegCompositorNode 的 X 轴 concat 逻辑天然支持多 Clip 拼接）
  - 每种语言的配音单独放入独立的 AudioTrack，最终由 amix 滤镜混合输出。
    （在全链路实际使用中，每次按语言独立渲染，因此每个 Timeline 变体只含单语言音频）
  - 本节点 **不** 处理字幕轨道；字幕烧录由 FFmpegCompositorNode._burn_subtitles 完成。
"""

import os
from pathlib import Path
from typing import Optional

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.timeline import AudioTrack, Clip, Timeline, Track


class AssemblyNode(BaseNode):
    """
    时间线拼装节点。

    期望 Context 中存在：
        context.assets["script_data"]: dict
            ScriptGenNode 生成的分镜脚本。
            用于计算所有 scene.duration 之和 → 视频总时长。

        context.variants[lang]["voice_audio"]: str
            TTSNode 生成的各语言配音 MP3 路径。

    构造参数：
        bg_video_path:  背景视频文件路径（默认 "tests/assets/bg1.mp4"）
        output_dir:     输出目录（用于创建临时资产，默认 "output"）
        primary_lang:   组装 Timeline 音频时使用的语言（默认使用所有可用语言，
                        若需要单语言版本可通过此参数指定）

    执行后写入 Context：
        context.assets["timeline"]: Timeline
            包含 1 条视频轨道（背景 + 铺满 Clip）和若干音频轨道（每语言一条）。
    """

    def __init__(
        self,
        name: str = "AssemblyNode",
        bg_video_path: str = "tests/assets/bg1.mp4",
        output_dir: str = "output",
    ):
        super().__init__(name)
        self._bg_video_path = bg_video_path
        self._output_dir = Path(output_dir)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _calc_total_duration(self, script_data: dict) -> float:
        """
        计算所有 scene.duration 之和，得出视频总时长（秒）。
        如果 script_data 为空或 scenes 缺失，返回 0.0。
        """
        scenes = script_data.get("scenes", [])
        total = sum(float(s.get("duration", 0)) for s in scenes)
        return total

    def _estimate_video_duration(self, video_path: str) -> float:
        """
        用 ffprobe 探测视频文件的实际时长（秒）。
        如果 ffprobe 不可用或探测失败，返回保守估计值 10.0 秒。
        """
        import subprocess
        ffprobe_bin = os.environ.get("FFPROBE_PATH", "ffprobe")
        try:
            result = subprocess.run(
                [
                    ffprobe_bin,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    video_path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            duration = float(result.stdout.strip())
            self.log(f"ffprobe detected bg video duration: {duration:.2f}s")
            return duration
        except Exception as exc:
            self.log(
                f"Warning: ffprobe failed ({exc}). "
                "Assuming bg video duration = 10.0s."
            )
            return 10.0

    def _build_video_track(self, total_duration: float) -> Track:
        """
        构建背景视频 Track（z_index=0，最底层）。

        策略：
          - 探测背景视频实际时长。
          - 若背景视频时长 ≥ 总时长，直接放一个 Clip 即可。
          - 若不足，重复添加相同 Clip 直到铺满总时长。
            FFmpegCompositorNode 的多 Clip concat 逻辑会自动处理 X 轴拼接。
        """
        track = Track(name="bg_video", z_index=0)
        bg_path = self._bg_video_path

        if not os.path.exists(bg_path):
            self.log(
                f"Warning: bg_video_path '{bg_path}' not found. "
                "Using as-is; FFmpeg will error if file is missing at render time."
            )
            # 仍然放入 Clip，让渲染阶段报告具体错误
            track.add_clip(Clip(file_path=bg_path, start_time=0.0, duration=total_duration))
            return track

        bg_duration = self._estimate_video_duration(bg_path)

        if bg_duration <= 0:
            bg_duration = 10.0

        if total_duration <= bg_duration:
            # 背景视频够长，直接放一个 Clip
            track.add_clip(
                Clip(file_path=bg_path, start_time=0.0, duration=total_duration)
            )
            self.log(
                f"BG track: 1 clip (bg_duration={bg_duration:.1f}s >= total={total_duration:.1f}s)"
            )
        else:
            # 背景视频不足：重复添加 Clip 铺满
            cursor = 0.0
            clip_count = 0
            while cursor < total_duration:
                remaining = total_duration - cursor
                clip_dur = min(bg_duration, remaining)
                track.add_clip(
                    Clip(file_path=bg_path, start_time=cursor, duration=clip_dur)
                )
                cursor += clip_dur
                clip_count += 1
            self.log(
                f"BG track: {clip_count} clips looped "
                f"(bg_duration={bg_duration:.1f}s, total={total_duration:.1f}s)"
            )

        return track

    # ------------------------------------------------------------------
    # 节点执行入口
    # ------------------------------------------------------------------

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        """
        执行时间线拼装流程：
          1. 读取 script_data，计算视频总时长
          2. 构建背景视频 Track（铺满总时长）
          3. 读取各语言配音，为每种语言添加独立 AudioTrack
          4. 将组装完毕的 Timeline 写回 Context
        """

        # ── Step 1: 计算总时长 ────────────────────────────────────────────
        script_data: dict = context.get_asset("script_data") or {}

        if not script_data:
            self.log("Warning: context.assets['script_data'] is empty, skipping.")
            return context

        total_duration = self._calc_total_duration(script_data)
        if total_duration <= 0:
            self.log("Warning: total_duration is 0 (no scenes or all durations are 0), skipping.")
            return context

        self.log(
            f"script_data has {len(script_data.get('scenes', []))} scenes. "
            f"Total video duration: {total_duration:.1f}s"
        )

        # ── Step 2: 构建 Timeline ──────────────────────────────────────────
        timeline = Timeline()

        # 背景视频轨道（Z轴最底层 z_index=0）
        bg_track = self._build_video_track(total_duration)
        timeline.add_track(bg_track)

        # ── Step 3: 添加各语言配音的 AudioTrack ──────────────────────────
        voice_added = []
        for lang, assets in context.variants.items():
            voice_path = assets.get("voice_audio", "")
            if not voice_path:
                self.log(
                    f"[{lang}] No 'voice_audio' in variants — skipping audio track for this lang."
                )
                continue

            if not os.path.exists(voice_path):
                self.log(
                    f"[{lang}] voice_audio file not found at '{voice_path}' "
                    "— adding to timeline anyway; FFmpeg will report error at render time."
                )

            audio_track = AudioTrack(name=f"voice_{lang}")
            # 配音从 0 秒开始，时长由 FFmpeg 实际音频决定（duration=None 时 FFmpeg 自动截断）
            audio_track.add_clip(Clip(file_path=voice_path, start_time=0.0, duration=None))
            timeline.add_audio_track(audio_track)
            voice_added.append(lang)
            self.log(f"[{lang}] AudioTrack added: {voice_path}")

        if not voice_added:
            self.log(
                "Warning: No voice_audio found in any language variant. "
                "Timeline will have no audio tracks."
            )
        else:
            self.log(f"Audio tracks assembled for languages: {voice_added}")

        # ── Step 4: 写回 Context ──────────────────────────────────────────
        context.set_asset("timeline", timeline)
        self.log(
            f"Timeline assembled and written to Context: "
            f"{len(timeline.tracks)} video track(s), "
            f"{len(timeline.audio_tracks)} audio track(s)."
        )

        return context
