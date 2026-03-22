"""
AssemblyNode — Phase 4: 时间线拼装节点

职责：
  将前序节点输出的资产（配音 MP3、字幕 ASS）和视频素材，
  根据 script_data 中的场景时长，动态拼装成一条完整的 Timeline，
  供 FFmpegCompositorNode 编译渲染。

数据流：
  读取 → context.assets["script_data"]       (场景脚本 + 总时长计算)
  读取 → context.assets["scene_clips"]       (AssetSelectNode 下载的真实素材路径列表，可选)
  读取 → context.assets["overlay_clips"]     (Y 轴叠加素材：{logo, sticker}，可选)
  读取 → context.variants[lang]["voice_audio"] (各语言配音 MP3，由 TTSNode 写入)
  写入 → context.assets["timeline"]           (组装完毕的 Timeline 对象)

设计说明：
  - 视频轨道优先路径：使用 context.assets["scene_clips"] 中按场景顺序下载的真实素材。
    每个 clip 依次在 X 轴拼接；若素材总时长不足总时长，最后一个 clip 循环补齐。
  - 视频轨道降级路径（Fallback）：若 scene_clips 为空，退回到原 bg_video_path 逻辑
    （循环背景视频铺满总时长），保持向后兼容。
  - Y 轴叠加轨道：若 overlay_clips 包含 Logo/Sticker 路径，分别创建 Layer 1 / Layer 2 的 Track。
    Layer 1 (logo)    ：全程常騻，右上角定位。
    Layer 2 (sticker) ：视频结束前 5 秒弹出，居中显示。
  - 背景视频素材通过构造器注入（bg_video_path），支持测试替换。
  - 每种语言的配音单独放入独立的 AudioTrack，最终由 amix 滤镜混合输出。
  - 本节点 **不** 处理字幕轨道；字幕烧录由 FFmpegCompositorNode._burn_subtitles 完成。
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

# 隐藏 Windows 下 FFprobe 子进程的黑色控制台窗口
_WIN_NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.timeline import Clip, Timeline, Track
from src.utils.env_utils import get_ffmpeg_path


class AssemblyNode(BaseNode):
    """
    时间线拼装节点。

    期望 Context 中存在：
        context.assets["script_data"]: dict
            ScriptGenNode 生成的分镜脚本。
            用于计算所有 scene.duration 之和 → 视频总时长。

        context.assets["scene_clips"]: list[str]  (可选)
            AssetSelectNode 下载的真实素材路径列表，按 scene 顺序排列。
            若存在且非空，优先使用；否则降级到 bg_video_path。

        context.variants[lang]["voice_audio"]: str
            TTSNode 生成的各语言配音 MP3 路径。

    构造参数：
        bg_video_path:  降级用背景视频文件路径（默认 None；不应在生产环境中依赖此路径，
                        素材不足时应由 AssetSelectNode 提前抛出业务异常）
        output_dir:     输出目录（用于创建临时资产，默认 "output"）

    执行后写入 Context：
        context.assets["timeline"]: Timeline
            包含 1 条视频轨道和若干音频轨道（每语言一条）。
    """

    def __init__(
        self,
        name: str = "AssemblyNode",
        bg_video_path: Optional[str] = None,
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
        ffprobe_bin = get_ffmpeg_path("ffprobe.exe")
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
                creationflags=_WIN_NO_WINDOW,
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

    def _build_video_track_from_clips(
        self,
        scene_clips: list,
        scenes: list,
        total_duration: float,
    ) -> Track:
        """
        【优先路径】使用 AssetSelectNode 下载的真实素材构建视频 Track。

        策略：
          - 遍历 scene_clips，每个 clip 探测实际时长。
          - 按 scene.duration 作为「期望时长」依次在 X 轴拼接各 clip。
            若某个 clip 实际时长 < scene.duration，则该 clip 循环使用直到填满。
          - 若所有 clips 总时长仍不足 total_duration，最后一个 clip 继续循环补齐。
        """
        track = Track(name="bg_video", z_index=0)
        cursor = 0.0
        clip_count = 0

        # 对齐 clips 与 scenes（clips 数量可能少于 scenes，因为部分 scene 可能下载失败）
        for i, clip_path in enumerate(scene_clips):
            if cursor >= total_duration:
                break

            # 该 clip 的「期望填充时长」= scene.duration（若可用），否则平均分配剩余
            if i < len(scenes):
                desired_fill = float(scenes[i].get("duration", 0))
            else:
                desired_fill = total_duration - cursor

            if desired_fill <= 0:
                desired_fill = total_duration - cursor

            # 探测 clip 实际时长
            if not os.path.exists(clip_path):
                self.log(f"Warning: clip '{clip_path}' not found, skipping.")
                continue

            clip_actual_dur = self._estimate_video_duration(clip_path)
            if clip_actual_dur <= 0:
                clip_actual_dur = 5.0

            # 在 desired_fill 范围内循环使用该 clip（X 轴拼接）
            remaining_fill = min(desired_fill, total_duration - cursor)
            while remaining_fill > 0:
                use_dur = min(clip_actual_dur, remaining_fill)
                track.add_clip(Clip(file_path=clip_path, start_time=cursor, duration=use_dur))
                cursor += use_dur
                remaining_fill -= use_dur
                clip_count += 1

        # 若所有 clips 用完后仍不足总时长，最后一个 clip 继续循环补齐
        if cursor < total_duration and scene_clips:
            last_clip = scene_clips[-1]
            if os.path.exists(last_clip):
                last_dur = self._estimate_video_duration(last_clip)
                if last_dur <= 0:
                    last_dur = 5.0
                self.log(
                    f"Extending with last clip to cover remaining "
                    f"{total_duration - cursor:.1f}s..."
                )
                while cursor < total_duration:
                    remaining = total_duration - cursor
                    use_dur = min(last_dur, remaining)
                    track.add_clip(Clip(file_path=last_clip, start_time=cursor, duration=use_dur))
                    cursor += use_dur
                    clip_count += 1

        self.log(
            f"Video track built from scene_clips: {clip_count} clip segment(s), "
            f"total={cursor:.1f}s / {total_duration:.1f}s"
        )
        return track

    def _build_video_track_from_bg(self, total_duration: float) -> Track:
        """
        【降级路径 Fallback】使用 bg_video_path 背景视频构建视频 Track。

        策略：
          - 探测背景视频实际时长。
          - 若背景视频时长 ≥ 总时长，直接放一个 Clip 即可。
          - 若不足，重复添加相同 Clip 直到铺满总时长。
        """
        track = Track(name="bg_video", z_index=0)
        bg_path = self._bg_video_path

        if not bg_path:
            raise ValueError(
                "可用视频素材不足，请在素材库中添加新素材。"
                "（scene_clips 为空且 bg_video_path 未配置，无法构建视频轨道）"
            )

        if not os.path.exists(bg_path):
            raise ValueError(
                f"可用视频素材不足，请在素材库中添加新素材。"
                f"（bg_video_path 指向的文件不存在: '{bg_path}'）"
            )

        bg_duration = self._estimate_video_duration(bg_path)
        if bg_duration <= 0:
            bg_duration = 10.0

        if total_duration <= bg_duration:
            track.add_clip(
                Clip(file_path=bg_path, start_time=0.0, duration=total_duration)
            )
            self.log(
                f"BG track (fallback): 1 clip "
                f"(bg_duration={bg_duration:.1f}s >= total={total_duration:.1f}s)"
            )
        else:
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
                f"BG track (fallback): {clip_count} clips looped "
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
          2. 构建视频 Track（scene_clips 优先；否则降级到 bg_video）
          3. 将纯视频 Timeline 写回 Context

        注意：Timeline 不含音频轨道。配音和字幕由 FFmpegCompositorNode
        在多语言变体渲染阶段逐语言合入，避免双语混音问题。
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

        # 视频轨道：优先使用真实下载素材，降级到 bg_video_path
        scene_clips: list = context.get_asset("scene_clips") or []
        scenes = script_data.get("scenes", [])

        if scene_clips:
            self.log(
                f"Using {len(scene_clips)} downloaded scene clip(s) for video track."
            )
            bg_track = self._build_video_track_from_clips(
                scene_clips, scenes, total_duration
            )
        else:
            self.log(
                f"[WARNING] scene_clips 为空，尝试降级到 bg_video_path='{self._bg_video_path}'"
            )
            bg_track = self._build_video_track_from_bg(total_duration)

        timeline.add_track(bg_track)

        # ── Step 3: Y 轴叠加轨道：Logo (Layer 1) + Sticker (Layer 2) ────────
        overlay_clips: dict = context.get_asset("overlay_clips") or {}
        logo_path: Optional[str] = overlay_clips.get("logo")
        sticker_path: Optional[str] = overlay_clips.get("sticker")

        if logo_path and os.path.exists(logo_path):
            logo_track = Track(name="logo_overlay", z_index=1, track_type="overlay")
            logo_track.add_clip(Clip(
                file_path=logo_path,
                start_time=0.0,
                duration=total_duration,
                overlay_x="W-w-30",
                overlay_y="30",
            ))
            timeline.add_track(logo_track)
            self.log(
                f"Layer 1 (logo_overlay): '{logo_path}' — "
                f"full duration={total_duration:.1f}s, position=top-right (W-w-30:30)"
            )
        else:
            self.log(
                f"Layer 1 (logo_overlay): skipped "
                f"({'not found' if logo_path else 'no logo path in overlay_clips'})"
            )

        if sticker_path and os.path.exists(sticker_path):
            sticker_start = max(0.0, total_duration - 5.0)
            sticker_dur = total_duration - sticker_start  # = min(5.0, total_duration)
            sticker_track = Track(name="sticker_overlay", z_index=2, track_type="overlay")
            sticker_track.add_clip(Clip(
                file_path=sticker_path,
                start_time=sticker_start,
                duration=sticker_dur,
                overlay_x="(W-w)/2",
                overlay_y="(H-h)/2",
            ))
            timeline.add_track(sticker_track)
            self.log(
                f"Layer 2 (sticker_overlay): '{sticker_path}' — "
                f"start={sticker_start:.1f}s, duration={sticker_dur:.1f}s, position=center"
            )
        else:
            self.log(
                f"Layer 2 (sticker_overlay): skipped "
                f"({'not found' if sticker_path else 'no sticker path in overlay_clips'})"
            )

        # ── Step 4: 写回 Context（纯视频 Timeline，无音频轨道）────────────────
        context.set_asset("timeline", timeline)
        overlay_count = len(timeline.tracks) - 1
        self.log(
            f"Timeline assembled: {len(timeline.tracks)} track(s) total "
            f"(Layer 0={bg_track.name}, +{overlay_count} overlay). "
            "Audio will be added per-language by FFmpegCompositorNode."
        )

        return context
