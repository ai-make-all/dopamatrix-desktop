import os
import subprocess
from typing import List, Tuple

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.timeline import Timeline, Track


class FFmpegCompositorNode(BaseNode):
    """
    底层渲染引擎：将 Timeline 编译为 FFmpeg Complex Filtergraph (Slot 模式)。
    支持多轨视频叠加（Y轴 overlay）+ 多音频轨混音（amix）。
    严格禁止引入 moviepy 等逐帧处理库，全部通过 subprocess + ffmpeg 实现。
    """

    def __init__(self, name: str = "FFmpeg_Slot_Compositor"):
        super().__init__(name)

    # ------------------------------------------------------------------
    # 核心编译器：Timeline → (input_args, video_filtergraph, audio_filtergraph)
    # ------------------------------------------------------------------
    def _build_filtergraph(
        self, timeline: Timeline
    ) -> Tuple[List[str], str, str]:
        """
        将 Timeline 的多轨数据编译为 FFmpeg 复杂滤镜图字符串。

        视频流处理（X轴 + Y轴）：
          X轴（时间/concat）：单轨多 Clip → setpts 归一化 → concat
          X轴（时间/offset）：单 Clip 且 start_time > 0 → setpts 时移
          Y轴（图层/overlay）：从 z_index 最低层向上逐层 overlay
            每层用 enable='between(t,{t_start},{t_end})' 限制合成时间窗口

        音频流处理：
          所有 AudioTrack 中的 Clip 统一收集为 FFmpeg 输入，
          若仅有一个音频输入则直接 anull 透传 [outa]，
          若有多个则用 amix 混合为 [outa]。

        Returns:
            input_args:       FFmpeg 的所有 -i 输入参数列表（视频+音频统一编号）
            video_filtergraph: 视频部分的 filter_complex 子串（以 [outv] 结尾）
            audio_filtergraph: 音频部分的 filter_complex 子串（以 [outa] 结尾），
                               若无音频则为空字符串
        """
        self.log("正在将 X/Y 轴时间线编译为 FFmpeg 槽位滤镜图...")

        input_args: List[str] = []    # [-i file1, -i file2, ...]
        video_parts: List[str] = []   # 视频 filtergraph 语句
        audio_parts: List[str] = []   # 音频 filtergraph 语句
        clip_index = 0                # 全局输入槽位编号（视频 + 音频共用）
        track_out_labels: List[str] = []

        # ── Step 1: 遍历视频 Track，处理 X 轴 ──────────────────────────
        for t_idx, track in enumerate(timeline.tracks):
            if not track.clips:
                continue

            per_clip_labels: List[str] = []

            for clip in track.clips:
                input_args.extend(["-i", clip.file_path])
                raw = f"[{clip_index}:v]"

                if len(track.clips) > 1:
                    # 多 Clip：归一化 PTS，稍后 concat（X轴拼接）
                    norm_label = f"[norm{clip_index}]"
                    video_parts.append(f"{raw}setpts=PTS-STARTPTS{norm_label}")
                    per_clip_labels.append(norm_label)
                else:
                    # 单 Clip：若有时间偏移则用 setpts 时移
                    if clip.start_time > 0:
                        shifted_label = f"[shifted{clip_index}]"
                        video_parts.append(
                            f"{raw}setpts=PTS+{clip.start_time}/TB{shifted_label}"
                        )
                        per_clip_labels.append(shifted_label)
                    else:
                        per_clip_labels.append(raw)

                clip_index += 1

            # X 轴拼接
            if len(track.clips) > 1:
                track_label = f"[track{t_idx}]"
                concat_inputs = "".join(per_clip_labels)
                video_parts.append(
                    f"{concat_inputs}concat=n={len(track.clips)}:v=1:a=0{track_label}"
                )
                track_out_labels.append(track_label)
            else:
                track_out_labels.append(per_clip_labels[0])

        # ── Step 2: Y 轴叠加 ────────────────────────────────────────────
        if not track_out_labels:
            return [], "", ""

        if len(track_out_labels) == 1:
            video_parts.append(f"{track_out_labels[0]}copy[outv]")
        else:
            base = track_out_labels[0]
            for i in range(1, len(track_out_labels)):
                track = timeline.tracks[i]
                t_start = min(c.start_time for c in track.clips)
                t_end = max(
                    c.start_time + (c.duration if c.duration is not None else 0.0)
                    for c in track.clips
                )
                enable = f"'between(t,{t_start},{t_end})'"
                out_label = (
                    "[outv]" if i == len(track_out_labels) - 1 else f"[comp{i}]"
                )
                video_parts.append(
                    f"{base}{track_out_labels[i]}overlay=0:0:enable={enable}{out_label}"
                )
                base = out_label

        video_filtergraph = ";".join(video_parts)

        # ── Step 3: 音频轨道处理 ────────────────────────────────────────
        # ★ 防坑：每个音频片段末尾接 apad 补静音，保证音频流 ≥ 视频流长度。
        #   这样 -shortest 会以视频流作为截断标准，而不会因音频先结束
        #   导致整个渲染提前停止（"视频定格"Bug 的音频侧镜像问题）。
        audio_padded_labels: List[str] = []

        for audio_track in timeline.audio_tracks:
            for clip in audio_track.clips:
                input_args.extend(["-i", clip.file_path])
                raw_a = f"[{clip_index}:a]"
                padded_label = f"[apad{clip_index}]"
                # apad 向音频尾部无限补静音，使其在时长上"永不先于视频结束"
                audio_parts.append(f"{raw_a}apad{padded_label}")
                audio_padded_labels.append(padded_label)
                clip_index += 1

        audio_filtergraph = ""
        if len(audio_padded_labels) == 1:
            # 单音频流：apad 已完成，再 anull 透传并命名为 [outa]
            audio_parts.append(f"{audio_padded_labels[0]}anull[outa]")
            audio_filtergraph = ";".join(audio_parts)
        elif len(audio_padded_labels) > 1:
            # 多音频流：所有流已用 apad 填充，amix 以最长流为准混合
            mixed_inputs = "".join(audio_padded_labels)
            n = len(audio_padded_labels)
            audio_parts.append(
                f"{mixed_inputs}amix=inputs={n}:duration=longest:dropout_transition=2[outa]"
            )
            audio_filtergraph = ";".join(audio_parts)
        # else: 无音频 → audio_filtergraph 保持为空字符串

        return input_args, video_filtergraph, audio_filtergraph

    # ------------------------------------------------------------------
    # 节点执行入口
    # ------------------------------------------------------------------
    def execute(self, context: WorkflowContext) -> WorkflowContext:

        # 1. 从 Context 读取 Timeline
        timeline: Timeline = context.get_asset("timeline")
        if not timeline:
            self.log("Warning: no 'timeline' found in Context, skipping render.")
            return context

        self.log(
            f"Parsing Timeline ({len(timeline.tracks)} video tracks, "
            f"{len(timeline.audio_tracks)} audio tracks)..."
        )

        # 2. 调用编译器
        input_args, video_fg, audio_fg = self._build_filtergraph(timeline)

        if not video_fg:
            self.log("Warning: empty filtergraph — nothing to render.")
            return context

        has_audio = bool(audio_fg)

        # 3. 合并视频+音频 filtergraph（用分号连接）
        full_filtergraph = (
            f"{video_fg};{audio_fg}" if has_audio else video_fg
        )

        # 4. 组装完整 FFmpeg 命令（列表形式）
        output_path = "output/master_video.mp4"
        ffmpeg_bin = os.environ.get("FFMPEG_PATH", "ffmpeg")

        # 映射：视频流始终输出，音频流按需映射
        map_args = ["-map", "[outv]"]
        codec_args = ["-c:v", "libx264", "-preset", "fast"]
        if has_audio:
            map_args += ["-map", "[outa]"]
            codec_args += ["-c:a", "aac", "-b:a", "192k"]

        cmd: List[str] = (
            [ffmpeg_bin]
            + input_args
            + ["-filter_complex", full_filtergraph]
            + map_args
            + codec_args
            # ★ 防坑核心：视频结束时立即停止渲染，杜绝"视频定格等音频"Bug
            + ["-shortest", "-y", output_path]
        )

        # 5. 打印命令，方便调试
        self.log("[CMD] Full FFmpeg command:")
        print(
            "\n"
            + " \\\n    ".join(
                f'-filter_complex "{full_filtergraph}"'
                if arg == full_filtergraph
                else arg
                for arg in cmd
            )
            + "\n"
        )

        # 6. 真实执行
        print("⏳ 正在渲染最终母带，请稍候...")
        self.log("Rendering master video, please wait...")
        try:
            subprocess.run(
                cmd,
                check=True,            # 非零退出码 → 抛出 CalledProcessError
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",      # 兼容 ffmpeg stderr 中的非 UTF-8 字符
            )
            self.log("[OK] FFmpeg completed successfully.")
        except FileNotFoundError:
            self.log(
                "[ERROR] ffmpeg binary not found. "
                "Set FFMPEG_PATH to the full path of ffmpeg.exe, "
                "or add ffmpeg to your system PATH."
            )
            return context
        except subprocess.CalledProcessError as exc:
            self.log(
                f"[ERROR] FFmpeg exited with code {exc.returncode}. stderr:\n{exc.stderr}"
            )
            return context

        # 7. 将母带路径写回 Context
        context.set_asset("video_master", output_path)
        self.log(f"Master video path '{output_path}' written to Context.")

        # 8. 遍历多语言变体：将 .ass 字幕烧录到母带，生成最终多语言视频
        self._burn_subtitles(context, output_path, ffmpeg_bin)

        return context

    # ------------------------------------------------------------------
    # 字幕烧录：遍历 Context.variants，为每个语言生成最终变体视频
    # ------------------------------------------------------------------
    def _burn_subtitles(
        self, context: WorkflowContext, master_path: str, ffmpeg_bin: str
    ) -> None:
        """
        将 Context.variants 中注册的 .ass 字幕烧录到母带视频中。

        FFmpeg Windows 路径防坑处理：
          1. 反斜杠 → 正斜杠（subtitles 滤镜不接受反斜杠）
          2. 驱动器字母后的冒号需用反斜杠转义（C:/foo → C\\:/foo）
          3. 整个滤镜参数值用单引号包裹（filter_complex 内部语法）

        输出文件：output/final_{lang}.mp4
        """
        if not context.variants:
            self.log("No language variants found in Context — skipping subtitle burn-in.")
            return

        for lang, assets in context.variants.items():
            ass_path: str = assets.get("subtitle_ass", "")
            if not ass_path:
                self.log(f"[{lang}] No 'subtitle_ass' registered — skipping.")
                continue

            if not os.path.exists(ass_path):
                self.log(f"[{lang}] .ass file not found at '{ass_path}' — skipping.")
                continue

            final_path = f"output/final_{lang}.mp4"

            # ★ 路径转义：Windows 路径 → FFmpeg subtitles 滤镜安全格式
            #   Step 1: 反斜杠 → 正斜杠
            #   Step 2: 盘符冒号转义 "C:/" → "C\\:/"（FFmpeg 滤镜解析规则）
            safe_ass_path = ass_path.replace("\\", "/")
            # 仅转义第一个冒号（驱动器字母后），避免破坏路径其余部分
            if len(safe_ass_path) >= 2 and safe_ass_path[1] == ":":
                safe_ass_path = safe_ass_path[0] + "\\:" + safe_ass_path[2:]

            subtitle_filter = f"subtitles='{safe_ass_path}'"

            burn_cmd: List[str] = [
                ffmpeg_bin,
                "-i", master_path,
                "-vf", subtitle_filter,
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "copy",
                "-y", final_path,
            ]

            self.log(f"[{lang}] Burning subtitle '{ass_path}' → '{final_path}'...")
            self.log(f"[{lang}] CMD: {' '.join(burn_cmd)}")

            try:
                subprocess.run(
                    burn_cmd,
                    check=True,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                self.log(f"[{lang}] [OK] Subtitle video rendered: {final_path}")
                context.set_variant_asset(lang, "final_video", final_path)
            except FileNotFoundError:
                self.log(f"[{lang}] [ERROR] ffmpeg binary not found for subtitle burn-in.")
            except subprocess.CalledProcessError as exc:
                self.log(
                    f"[{lang}] [ERROR] FFmpeg subtitle burn failed "
                    f"(exit {exc.returncode}):\n{exc.stderr}"
                )
