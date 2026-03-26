import os
import shutil
import subprocess
import sys
from typing import List, Tuple

# 隐藏 Windows 下 FFmpeg 子进程的黑色控制台窗口
_WIN_NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.logger import logger
from src.core.timeline import Clip, Timeline, Track
from src.utils.env_utils import get_ffmpeg_path


class FFmpegCompositorNode(BaseNode):
    """
    底层渲染引擎：将 Timeline 编译为 FFmpeg Complex Filtergraph (Slot 模式)。
    支持多轨视频叠加（Y轴 overlay）+ 多音频轨混音（amix）。
    严格禁止引入 moviepy 等逐帧处理库，全部通过 subprocess + ffmpeg 实现。
    """

    def __init__(self, name: str = "FFmpeg_Slot_Compositor"):
        super().__init__(name)
        # 运行时动态分辨率（由 execute() 从 context.aspect_ratio 解析和赋值）
        self.target_w: int = 720    # 默认 9:16 宽（720P 级别，MVP 提速）
        self.target_h: int = 1280   # 默认 9:16 高
    TARGET_FPS: int = 30

    @staticmethod
    def _resolve_dimensions(aspect_ratio: str) -> tuple[int, int]:
        """
        将画幅比例字符串转换为输出分辨率 (width, height)。

        支持规格（MVP 720P 级别，渲染提速 ~60%）：
          '9:16' →  720 × 1280  （竖屏，TikTok / Reels）
          '16:9' → 1280 ×  720  （横屏，YouTube / 横版广告）
          '1:1'  →  720 ×  720  （方形，Instagram Feed）

        Args:
            aspect_ratio: 画幅比例字符串（不区分大小写、容许首尾空格）

        Returns:
            (width, height) 整数元组
        """
        _MAP = {
            "9:16": (720, 1280),
            "16:9": (1280, 720),
            "1:1":  (720, 720),
        }
        key = aspect_ratio.strip()
        if key not in _MAP:
            import warnings
            warnings.warn(
                f"[FFmpegCompositorNode] 未知画幅比例 '{aspect_ratio}'，"
                f"回退为默认竖屏 9:16 (720×1280)。"
            )
            return (720, 1280)
        return _MAP[key]

    # ------------------------------------------------------------------
    # 核心编译器：Timeline → (input_args, video_filtergraph, audio_filtergraph)
    # ------------------------------------------------------------------
    def _build_filtergraph(
        self, timeline: Timeline
    ) -> Tuple[List[str], str, str]:
        """
        将 Timeline 的多轨数据编译为 FFmpeg 复杂滤镜图字符串。

        视频流处理（X轴 + Y轴）：
          X轴（时间/concat）：track_type="video" 的轨道 → setpts 归一化 → concat
          Y轴（图层/overlay）：track_type="overlay" 的轨道 → PNG format=rgba 转换
            → 级联 overlay 滤镜（由低 z_index 向高 z_index 逐层叠加）
            → enable='between(t,{t_start},{t_end})' 精确控制每层时间窗口
            → overlay_x / overlay_y 控制每层定位（来自 Clip 元数据）

        PNG 透明通道保留：
          overlay 轨道的 PNG 素材必须先经过 format=rgba 转换（保留 alpha），
          底层视频需为 yuv420p；FFmpeg overlay 滤镜会正确混合两者。

        音频流处理：
          所有 AudioTrack 中的 Clip 统一收集为 FFmpeg 输入，
          若仅有一个音频输入则直接 anull 透传 [outa]，
          若有多个则用 amix 混合为 [outa]。

        Returns:
            input_args:        FFmpeg 的所有 -i 输入参数列表（视频+音频统一编号）
            video_filtergraph: 视频部分的 filter_complex 子串（以 [outv] 结尾）
            audio_filtergraph: 音频部分的 filter_complex 子串（以 [outa] 结尾），
                               若无音频则为空字符串
        """
        self.log("正在将 X/Y 轴时间线编译为 FFmpeg 槽位滤镜图...")

        input_args: List[str] = []    # [-i file1, -i file2, ...]
        video_parts: List[str] = []   # 视频 filtergraph 语句
        audio_parts: List[str] = []   # 音频 filtergraph 语句
        clip_index = 0                # 全局输入槽位编号（视频 + 音频共用）

        # 基础视频轨（track_type="video"）的拼接输出标签
        base_video_out_labels: List[str] = []
        # Y 轴叠加轨（track_type="overlay"）的槽位 + clip 元数据
        overlay_slots: List[Tuple[str, Clip]] = []   # [(rgba_label, clip_obj), ...]

        # ── Step 1: 遍历 Track，区分 video / overlay ───────────────────
        for t_idx, track in enumerate(timeline.tracks):
            if not track.clips:
                continue

            # ── overlay 轨道（PNG 图层）：只注册输入槽位，不走 concat ──────
            if getattr(track, "track_type", "video") == "overlay":
                # overlay 轨道通常只有 1 个 Clip（logo 或 sticker）
                clip = track.clips[0]
                input_args.extend(["-i", clip.file_path])
                raw_label = f"[{clip_index}:v]"
                rgba_label = f"[rgba{clip_index}]"
                # format=rgba：保留 PNG 透明通道，避免 alpha 被黑色填充
                video_parts.append(f"{raw_label}format=rgba{rgba_label}")
                overlay_slots.append((rgba_label, clip))
                clip_index += 1
                continue

            # ── video 轨道：原有 X 轴 concat 管线 ─────────────────────────
            per_clip_labels: List[str] = []

            for clip in track.clips:
                input_args.extend(["-i", clip.file_path])
                raw = f"[{clip_index}:v]"

                if len(track.clips) > 1:
                    # 多 Clip：完整归一化管道（解决花屏）：
                    # setpts  — PTS 归零
                    # scale   — 等比缩小到目标尺寸（保持宽高比）
                    # pad     — 补黑边对齐到精确目标尺寸
                    # setsar  — 强制 SAR=1（消除非方形像素 DAR 异常）
                    # fps     — 统一帧率（消除帧率不一致导致的花屏）
                    # format  — 强制 yuv420p（FFmpeg concat 要求像素格式一致）
                    # effects — per-clip 防查重滤镜链（来自 AntiDupNode）
                    tw, th = self.target_w, self.target_h
                    norm_label = f"[norm{clip_index}]"
                    norm_chain = (
                        f"{raw}setpts=PTS-STARTPTS,"
                        f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                        f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,"
                        f"setsar=1,"
                        f"fps={self.TARGET_FPS},"
                        f"format=yuv420p"
                    )
                    if clip.effects:
                        effects_chain = ",".join(clip.effects)
                        norm_chain += f",{effects_chain}"
                    norm_chain += norm_label
                    video_parts.append(norm_chain)
                    per_clip_labels.append(norm_label)
                else:
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
                base_video_out_labels.append(track_label)
            else:
                base_video_out_labels.append(per_clip_labels[0])

        # ── Step 2: 级联 Y 轴 overlay（基础视频 + 叠加层）──────────────
        if not base_video_out_labels:
            return [], "", ""

        # 基础视频（Layer 0）输出
        if len(base_video_out_labels) == 1:
            base = base_video_out_labels[0]
        else:
            # 多个 video track（极少情况），先做基础叠加
            base = base_video_out_labels[0]
            for i, next_label in enumerate(base_video_out_labels[1:], start=1):
                out_label = f"[base_comp{i}]"
                video_parts.append(f"{base}{next_label}overlay=0:0{out_label}")
                base = out_label

        # Y 轴级联 PNG overlay（按 overlay_slots 顺序，z_index 由低到高）
        total_overlay_count = len(overlay_slots)
        for ov_idx, (rgba_label, clip) in enumerate(overlay_slots):
            is_last = (ov_idx == total_overlay_count - 1)
            out_label = "[outv]" if is_last else f"[comp_ov{ov_idx}]"

            # 定位坐标：从 Clip.overlay_x / overlay_y 读取（默认左上角 0:0）
            ov_x = getattr(clip, "overlay_x", None) or "0"
            ov_y = getattr(clip, "overlay_y", None) or "0"

            # 时间窗口：enable='between(t,start,end)' 精确控制显示区间
            t_start = clip.start_time
            t_end = t_start + (clip.duration if clip.duration is not None else 0.0)
            enable = f"'between(t,{t_start},{t_end})'"

            video_parts.append(
                f"{base}{rgba_label}overlay={ov_x}:{ov_y}:enable={enable}{out_label}"
            )
            base = out_label
            self.log(
                f"[Overlay] slot {ov_idx}: {rgba_label} @ ({ov_x},{ov_y}) "
                f"enable=between(t,{t_start},{t_end}) -> {out_label}"
            )

        # 无 overlay 轨道时：基础视频直接命名为 [outv]
        if total_overlay_count == 0:
            video_parts.append(f"{base}copy[outv]")

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

        # 1b. 解析画幅比例，动态设置目标分辨率
        aspect_ratio: str = getattr(context, "aspect_ratio", "9:16") or "9:16"
        self.target_w, self.target_h = self._resolve_dimensions(aspect_ratio)
        self.log(
            f"📐 画幅比例={aspect_ratio} → 目标分辨率={self.target_w}×{self.target_h}"
        )

        self.log(
            f"Parsing Timeline ({len(timeline.tracks)} video tracks, "
            f"{len(timeline.audio_tracks)} audio tracks)..."
        )

        # 2. 调用编译器
        input_args, video_fg, audio_fg = self._build_filtergraph(timeline)

        if not video_fg:
            self.log("Warning: empty filtergraph — nothing to render.")
            return context

        # 3. 合并视频 filtergraph（无音频：Timeline 只含视频轨道）
        full_filtergraph = video_fg

        # 4. 组装完整 FFmpeg 命令（无音频流：生成静音母带）
        # 读取 session_id 实现多进程输出路径隔离（无 session_id 时使用默认名）
        session_id: str = context.config.get("session_id", "")
        sid_suffix = f"_{session_id}" if session_id else ""
        output_path = f"output/master_video{sid_suffix}.mp4"
        ffmpeg_bin = get_ffmpeg_path("ffmpeg.exe")

        map_args = ["-map", "[outv]", "-an"]   # -an: 无音频轨道
        # superfast: 比 fast 快约 2x，码率略升但对 MVP 演示可接受
        # threads 0: 让 FFmpeg 自动使用所有 CPU 物理核心
        codec_args = ["-c:v", "libx264", "-preset", "superfast", "-threads", "0"]

        cmd: List[str] = (
            [ffmpeg_bin]
            + input_args
            + ["-filter_complex", full_filtergraph]
            + map_args
            + codec_args
            # master_video 是纯视频，无 -shortest 约束
            + ["-y", output_path]
        )

        # 5. 打印命令，方便调试
        self.log("[CMD] Full FFmpeg command:")
        logger.info(
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
        logger.info("⏳ 正在渲染最终母带，请稍候...")
        self.log("Rendering master video, please wait...")
        try:
            subprocess.run(
                cmd,
                check=True,            # 非零退出码 → 抛出 CalledProcessError
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",      # 兼容 ffmpeg stderr 中的非 UTF-8 字符
                creationflags=_WIN_NO_WINDOW,
            )
            self.log("[OK] FFmpeg completed successfully.")
        except FileNotFoundError:
            self.log(
                f"[ERROR] ffmpeg binary not found at '{ffmpeg_bin}'. "
                "In production, ensure ffmpeg.exe is in the same directory as backend.exe. "
                "In development, ensure ffmpeg is available on your system PATH."
            )
            return context
        except subprocess.CalledProcessError as exc:
            self.log(
                f"[ERROR] FFmpeg exited with code {exc.returncode}. stderr:\n{exc.stderr}"
            )
            raise RuntimeError(f"FFmpeg render failed: {exc.stderr}")

        # 7. 将母带路径写回 Context
        context.set_asset("video_master", output_path)
        self.log(f"Master video path '{output_path}' written to Context.")

        # 8. 逐语言生成最终变体视频（配音 + 字幕 + 画面合并）
        self._render_variant(context, output_path, ffmpeg_bin)

        return context

    # ------------------------------------------------------------------
    # 字幕烧录 + BGM/SFX 混音：遍历 Context.variants，为每个语言生成最终变体视频
    # ------------------------------------------------------------------
    def _render_variant(
        self, context: WorkflowContext, master_path: str, ffmpeg_bin: str
    ) -> None:
        """
        逐语言生成最终变体视频：master_video（静音）+ TTS 配音 + BGM/SFX + 字幕。

        输入槽位约定（动态分配，序号严格按加入顺序递增）：
          [0]       — master_video.mp4（纯净静音画面，永远第一位）
          [1]       — voice_{lang}.mp3（TTS 配音，若存在）
          [2..N]    — timeline.audio_tracks 中的 BGM / SFX 文件（按轨道 → clip 顺序）

        音频混音策略：
          - BGM (audio_type=="bgm")  → volume=0.2 闪避降噪，保护人声清晰度
          - TTS / SFX / general      → 原始音量直通
          - 所有有效音频标签用 amix=inputs=N:duration=longest:dropout_transition=2[outa] 合并
          - 无任何音频输入时 → -an

        视频策略：
          - 有字幕 → [0:v]subtitles=...[outv]，-map [outv]
          - 无字幕 → -map 0:v（无 filter_complex 视频部分）

        输出文件：output/final_{lang}.mp4
        """
        if not context.variants:
            self.log("No language variants found in Context — skipping variant rendering.")
            return

        # 拉取 timeline，用于读取 BGM/SFX audio_tracks
        timeline: Timeline = context.get_asset("timeline")
        audio_tracks = timeline.audio_tracks if timeline else []

        for lang, assets in context.variants.items():
            ass_path: str = assets.get("subtitle_ass", "")
            voice_path: str = assets.get("voice_audio", "")
            session_id: str = context.config.get("session_id", "")
            sid_suffix = f"_{session_id}" if session_id else ""
            final_path = f"output/final_{lang}{sid_suffix}.mp4"

            has_sub   = bool(ass_path   and os.path.exists(ass_path))
            has_voice = bool(voice_path and os.path.exists(voice_path))

            if not has_sub:
                self.log(f"[{lang}] No subtitle file — video track will be raw copy.")
            if not has_voice:
                self.log(f"[{lang}] No voice_audio — TTS track skipped.")

            # ── Step 1: 收集所有 FFmpeg 输入，严格按槽位编号递增 ──────────────
            # 槽位 0 = master_video（固定）
            inputs: List[str] = [ffmpeg_bin, "-i", master_path]
            next_idx: int = 1   # 下一个可用输入槽位编号

            # 第一顺位：TTS 配音
            voice_label: str = ""           # e.g. "[1:a]"，不存在则为空
            if has_voice:
                inputs += ["-i", voice_path]
                voice_label = f"[{next_idx}:a]"
                next_idx += 1

            # 第二顺位：timeline.audio_tracks 中的 BGM / SFX / general
            # audio_filter_parts : BGM 降噪滤镜语句列表（需写入 filter_complex）
            # audio_mix_labels   : 最终送入 amix 的标签列表（顺序即混音顺序）
            audio_filter_parts: List[str] = []
            audio_mix_labels:   List[str] = []

            if voice_label:
                audio_mix_labels.append(voice_label)

            for audio_track in audio_tracks:
                for clip in audio_track.clips:
                    if not clip.file_path or not os.path.exists(clip.file_path):
                        self.log(
                            f"[{lang}] [WARN] Audio clip missing, skipping: {clip.file_path}"
                        )
                        continue

                    inputs += ["-i", clip.file_path]
                    raw_label = f"[{next_idx}:a]"
                    slot = next_idx
                    next_idx += 1

                    if audio_track.audio_type == "bgm":
                        # BGM 闪避：降至 20% 音量，保护 TTS 人声
                        bgm_out = f"[bgm{slot}]"
                        audio_filter_parts.append(f"{raw_label}volume=0.2{bgm_out}")
                        audio_mix_labels.append(bgm_out)
                        self.log(
                            f"[{lang}] BGM '{audio_track.name}' [{slot}:a] → volume=0.2 {bgm_out}"
                        )
                    else:
                        # SFX / TTS / general：原音量直通
                        audio_mix_labels.append(raw_label)
                        self.log(
                            f"[{lang}] Audio '{audio_track.name}' "
                            f"(type={audio_track.audio_type}) [{slot}:a] → {raw_label}"
                        )

            # ── Step 2: 视频滤镜 — 字幕烧录 ──────────────────────────────────
            if has_sub:
                # Windows 路径转义：反斜杠 → 正斜杠，盘符冒号 "X:" → "X\:"
                safe_ass = ass_path.replace("\\", "/")
                if len(safe_ass) >= 2 and safe_ass[1] == ":":
                    safe_ass = safe_ass[0] + "\\:" + safe_ass[2:]
                video_fg  = f"[0:v]subtitles='{safe_ass}'[outv]"
                video_map = ["-map", "[outv]"]
            else:
                video_fg  = ""
                video_map = ["-map", "0:v"]

            # ── Step 3: 音频滤镜 — 动态 amix ─────────────────────────────────
            n = len(audio_mix_labels)
            if n == 0:
                # 无任何音频来源
                audio_fg    = ""
                audio_map   = ["-an"]
                audio_codec = []
                shortest    = []
            elif n == 1 and not audio_filter_parts:
                # 单一 TTS/SFX 且无中间滤镜：直接映射，不走 filter_complex 音频部分
                # audio_mix_labels[0] 形如 "[1:a]"，去括号得 "1:a"
                audio_fg    = ""
                audio_map   = ["-map", audio_mix_labels[0].strip("[]")]
                audio_codec = ["-c:a", "aac", "-b:a", "192k"]
                shortest    = ["-shortest"]
            else:
                # 多路混音，或单路但有 BGM volume 中间滤镜（amix=inputs=1 合法）
                mix_in  = "".join(audio_mix_labels)
                amix_fg = (
                    f"{mix_in}"
                    f"amix=inputs={n}:duration=longest:dropout_transition=2[outa]"
                )
                audio_fg    = ";".join(audio_filter_parts + [amix_fg])
                audio_map   = ["-map", "[outa]"]
                audio_codec = ["-c:a", "aac", "-b:a", "192k"]
                shortest    = ["-shortest"]

            # ── Step 4: 合并 filter_complex（视频 + 音频两部分以 ; 连接）────────
            filter_parts = [p for p in [video_fg, audio_fg] if p]
            filter_args  = ["-filter_complex", ";".join(filter_parts)] if filter_parts else []

            # ── Step 5: 组装并执行最终命令 ────────────────────────────────────
            cmd: List[str] = (
                inputs
                + filter_args
                + video_map
                + audio_map
                + ["-c:v", "libx264", "-preset", "superfast", "-threads", "0"]
                + audio_codec
                + shortest
                + ["-y", final_path]
            )

            self.log(f"[{lang}] Rendering variant → {final_path}")
            self.log(f"[{lang}] CMD: {' '.join(cmd)}")

            try:
                subprocess.run(
                    cmd,
                    check=True,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=_WIN_NO_WINDOW,
                )
                self.log(f"[{lang}] [OK] Variant rendered: {final_path}")
                context.set_variant_asset(lang, "final_video", final_path)

                custom_output_dir = context.config.get("output_dir")
                if custom_output_dir:
                    os.makedirs(custom_output_dir, exist_ok=True)
                    target_file_path = os.path.join(
                        custom_output_dir, os.path.basename(final_path)
                    )
                    shutil.copy(final_path, target_file_path)
                    self.log(
                        f"[{lang}] [OK] Copied to custom output dir: {target_file_path}"
                    )
            except FileNotFoundError:
                self.log(f"[{lang}] [ERROR] ffmpeg binary not found.")
            except subprocess.CalledProcessError as exc:
                error_msg = exc.stderr[-800:] if exc.stderr else "Unknown error"
                self.log(
                    f"[{lang}] [ERROR] Variant render failed "
                    f"(exit {exc.returncode}):\n{error_msg}"
                )
                raise RuntimeError(f"FFmpeg render failed: {error_msg}")
