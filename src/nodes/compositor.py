import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import List, Tuple

# 隐藏 Windows 下 FFmpeg 子进程的黑色控制台窗口
_WIN_NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

from src.api.ws_manager import manager as ws_manager
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

    @staticmethod
    def _resolve_file_sid(context: WorkflowContext) -> str:
        """Resolve the short output token without reusing the batch task identity."""
        file_sid = context.config.get("file_sid")
        if file_sid:
            return str(file_sid)

        if "child_index" in context.config or "execution_id" in context.config:
            raise RuntimeError(
                "[FFmpegCompositorNode] child context is missing file_sid"
            )

        # Legacy direct calls without child markers use their task namespace.
        return str(context.task_id)

    @classmethod
    def _master_output_path(cls, context: WorkflowContext) -> str:
        file_sid = cls._resolve_file_sid(context)
        sid_suffix = f"_{file_sid}" if file_sid else ""
        return f"output/master_video{sid_suffix}.mp4"

    @classmethod
    def _final_output_path(cls, context: WorkflowContext, language: str) -> str:
        file_sid = cls._resolve_file_sid(context)
        sid_suffix = f"_{file_sid}" if file_sid else ""
        return f"output/final_{language}{sid_suffix}.mp4"

    # ------------------------------------------------------------------
    # 事件总线辅助工具
    # ------------------------------------------------------------------

    @staticmethod
    def _quick_hash(path: str) -> str:
        """
        读取文件前 64 KB 计算 MD5，供 WS payload 中的 file_hash 字段展示使用。

        设计原则：
          - 只读前 64 KB（对 100MB+ 视频文件不做全量 IO）
          - 文件不存在时回退到路径字符串哈希，保证返回值始终有效
          - 完整内容哈希（perceptual_hash / file_hash 入库）由 services.py 负责
        """
        h = hashlib.md5()
        try:
            with open(path, "rb") as f:
                h.update(f.read(65536))
        except OSError:
            h.update(path.encode())
        return h.hexdigest()

    def _ws_broadcast(self, task_id: str, user_id: str, extra: dict) -> None:
        """
        防御性 WS 广播包装器。

        职责：
          1. 按标准信封协议拼装消息（type + payload.taskId + extra 字段）
          2. 捕获 broadcast_sync 的所有异常——保证事件总线故障绝不中断渲染主流程
          3. 定向推送（user_id）确保多租户隔离，防止跨用户数据串流

        Args:
            task_id: 前端 queueWorker 中对应的任务 ID（= context.task_id）
            user_id: 广播目标用户（= context.tenant_id），传入则为定向推送
            extra:   追加到 payload 的业务字段（status / progress / assets 等）
        """
        try:
            ws_manager.broadcast_sync(
                {"type": "WS_UPDATE", "payload": {"taskId": task_id, **extra}},
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning("[FFmpegCompositorNode] WS 广播异常（不阻断渲染流程）: %r", exc)

    @staticmethod
    def _coordinator_owns_terminal(context: WorkflowContext) -> bool:
        """True for routes_dsl children whose task terminal is finalized upstream."""
        return context.config.get("ws_terminal_managed_by_coordinator") is True

    # ------------------------------------------------------------------
    # 核心编译器：Timeline → (input_args, video_filtergraph, audio_filtergraph)
    # ------------------------------------------------------------------

    @staticmethod
    def _probe_duration(file_path: str) -> float:
        """
        使用 ffprobe 探测媒体文件的真实时长（秒）。
        任何异常均静默返回 0.0，由上层按名义时长兜底。
        """
        ffprobe_bin = get_ffmpeg_path("ffprobe.exe")
        try:
            result = subprocess.run(
                [
                    ffprobe_bin,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path,
                ],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=_WIN_NO_WINDOW,
            )
            val = result.stdout.strip()
            return float(val) if val else 0.0
        except Exception:
            return 0.0

    def _compute_beat_timeline(
        self, main_video_clips: "List[Clip]"
    ) -> "Tuple[List[float], float]":
        """
        【全局时间线计算 — Phase 9.7.1 Late-Binding 核心】

        在寻址引擎已为各 Beat 确定真实物理素材、ffprobe 采集到 duration 之后，
        但在拼接 FFmpeg filter_complex 字符串之前执行：

        1. 以 X 轴主视频轨道的 Clip 列表为输入（顺序即 Beat 顺序）。
        2. 对每个 Clip 运行 ffprobe 获取真实时长；失败时退回 Clip.duration 名义值。
        3. 累加得出每个 Beat 的绝对起始时间 beat_actual_starts[i]。

        Args:
            main_video_clips: 主视频轨道（layer_index==0 / track_type="video"）
                              中的所有 Clip，按 Beat 顺序排列。

        Returns:
            (beat_actual_starts, total_actual_duration)
            beat_actual_starts[i] = Beat i 在最终视频中的绝对起始时间（秒）
        """
        beat_actual_starts: List[float] = []
        current_time = 0.0

        for clip in main_video_clips:
            beat_actual_starts.append(current_time)
            actual_dur = 0.0
            if os.path.isfile(clip.file_path):
                actual_dur = self._probe_duration(clip.file_path)
            if actual_dur <= 0:
                # ffprobe 失败时退回名义时长，再退回保守值 5s
                actual_dur = (clip.duration or 0.0) if (clip.duration or 0.0) > 0 else 5.0
                self.log(
                    f"[GlobalTimeline] ffprobe 失败 '{clip.file_path}'，"
                    f"使用名义时长 {actual_dur:.3f}s 作为兜底。"
                )
            current_time += actual_dur

        self.log(
            f"[GlobalTimeline] {len(main_video_clips)} 个主视频 Clip → "
            f"beat_actual_starts={[round(s, 3) for s in beat_actual_starts]} "
            f"total={current_time:.3f}s"
        )
        return beat_actual_starts, current_time

    @staticmethod
    def _resolve_clip_timing(
        clip: "Clip",
        beat_actual_starts: "List[float]",
        total_actual_dur: float,
    ) -> "Tuple[float, float]":
        """
        计算叠加层 Clip（overlay / text_overlay）的绝对显示窗口 (t_start, t_end)。

        • DSL 路径：Clip.beat_index 已由 dsl_adapter 标注，
          直接查 beat_actual_starts 映射到真实物理时间域。
        • Assembler 路径：beat_index=None，退回 Clip 自身的 start_time / duration
          （assembler 已经设置了正确的绝对时间，无需重新计算）。
        """
        if clip.beat_index is not None and beat_actual_starts:
            idx = clip.beat_index
            if 0 <= idx < len(beat_actual_starts):
                t_start = beat_actual_starts[idx]
                t_end = (
                    beat_actual_starts[idx + 1]
                    if idx + 1 < len(beat_actual_starts)
                    else total_actual_dur
                )
                return t_start, t_end
        # Assembler / 未知路径：使用 Clip 自身时间戳
        t_start = clip.start_time
        t_end = t_start + (clip.duration if clip.duration is not None else 0.0)
        return t_start, t_end

    @staticmethod
    def get_ffmpeg_coordinates(
        position_key: str, is_text: bool = False
    ) -> tuple[str, str]:
        """
        九宫格空间排版坐标解析引擎（Phase 9.7.2）。

        将抽象的布局意图键转换为 FFmpeg 滤镜表达式 (x, y)。

        变量体系差异（FFmpeg 内部约定）：
          drawtext（is_text=True）：
            tw / th  — 渲染后文字的像素宽高
            w  / h   — 主画布（视频帧）宽高
          overlay（is_text=False）：
            w  / h   — 叠加物（贴纸/图片）宽高
            W  / H   — 主画布（视频帧）宽高

        Args:
            position_key: 九宫格位置键，支持的取值：
                'center'        — 正中心
                'bottom_center' — 底部居中（TikTok/Shorts 安全区）
                'top_center'    — 顶部居中
                'top_left'      — 左上角（固定边距）
                'top_right'     — 右上角（固定边距）
                'bottom_left'   — 左下角（TikTok/Shorts 安全区）
                其他未知值      — 回退到 'center'
            is_text: True 表示 drawtext 变量体系；False 表示 overlay 变量体系。

        Returns:
            (x_expr, y_expr) — 可直接拼入 FFmpeg 滤镜的表达式字符串元组。
        """
        if is_text:
            ow, oh = "tw", "th"   # drawtext: text_w / text_h
            mw, mh = "w",  "h"   # drawtext: main canvas w / h
        else:
            ow, oh = "w",  "h"   # overlay: overlay item w / h
            mw, mh = "W",  "H"   # overlay: main canvas W / H

        _MAP: dict[str, tuple[str, str]] = {
            "center": (
                f"({mw}-{ow})/2",
                f"({mh}-{oh})/2",
            ),
            "bottom_center": (
                f"({mw}-{ow})/2",
                f"{mh}-{oh}-({mh}*0.15)",
            ),
            "top_center": (
                f"({mw}-{ow})/2",
                f"{mh}*0.1",
            ),
            "top_left": (
                "50",
                "100",
            ),
            "top_right": (
                f"{mw}-{ow}-50",
                "100",
            ),
            "bottom_left": (
                "50",
                f"{mh}-{oh}-({mh}*0.15)",
            ),
        }
        return _MAP.get(position_key, _MAP["center"])

    @staticmethod
    def _escape_drawtext(text: str) -> str:
        """
        对 FFmpeg drawtext 滤镜的 text 参数执行特殊字符转义。

        FFmpeg drawtext 的 text 值中，以下字符需要反斜杠转义：
          \\  '  :  [  ]  ,  ;
        此外还需转义百分号（%），避免被解释为 FFmpeg 格式化占位符。
        """
        for ch in ("\\", "'", ":", "[", "]", ",", ";", "%"):
            text = text.replace(ch, "\\" + ch)
        return text

    def _build_filtergraph(
        self, timeline: Timeline, language: str = "en"
    ) -> Tuple[List[str], str, str]:
        """
        将 Timeline 的多轨数据编译为 FFmpeg 复杂滤镜图字符串。

        视频流处理（X轴 + Y轴）：
          X轴（时间/concat）：track_type="video" 的轨道 → setpts 归一化 → concat
          Y轴（图层/overlay）：track_type="overlay" 的轨道 → PNG format=rgba 转换
            → 级联 overlay 滤镜（由低 z_index 向高 z_index 逐层叠加）
            → enable='between(t,{t_start},{t_end})' 精确控制每层时间窗口
            → overlay_x / overlay_y 控制每层定位（来自 Clip 元数据）
          文本叠加：track_type="text_overlay" 的轨道 → 从 manifest.content_matrix
            按 language 提取文本 → 注入 drawtext 滤镜（无物理输入文件）

        PNG 透明通道保留：
          overlay 轨道的 PNG 素材必须先经过 format=rgba 转换（保留 alpha），
          底层视频需为 yuv420p；FFmpeg overlay 滤镜会正确混合两者。

        音频流处理：
          所有 AudioTrack 中的 Clip 统一收集为 FFmpeg 输入，
          若仅有一个音频输入则直接 anull 透传 [outa]，
          若有多个则用 amix 混合为 [outa]。

        Args:
            timeline: 已组装的 Timeline 对象。
            language: 目标渲染语种（如 'zh'、'en'、'ar'），
                      text_overlay 轨道从 content_matrix 中按此键提取文本。

        Returns:
            input_args:        FFmpeg 的所有 -i 输入参数列表（视频+音频统一编号）
            video_filtergraph: 视频部分的 filter_complex 子串（以 [outv] 结尾）
            audio_filtergraph: 音频部分的 filter_complex 子串（以 [outa] 结尾），
                               若无音频则为空字符串
        """
        self.log("正在将 X/Y 轴时间线编译为 FFmpeg 槽位滤镜图...")

        # ── Step 0: 全局真实时间轴计算（Late-Binding，Phase 9.7.1）──────────
        # 在 ffprobe 确定主视频 Clip 真实时长之后、拼接 filter_complex 之前执行。
        # 结果供后续 overlay / text_overlay 注入 enable='between(t,start,end)'。
        _main_video_clips: List[Clip] = []
        for _track in timeline.tracks:
            if getattr(_track, "track_type", "video") == "video" and _track.clips:
                _main_video_clips = list(_track.clips)
                break  # 主视频轨唯一，找到即止

        beat_actual_starts: List[float]
        total_actual_dur: float
        beat_actual_starts, total_actual_dur = self._compute_beat_timeline(_main_video_clips)

        input_args: List[str] = []    # [-i file1, -i file2, ...]
        video_parts: List[str] = []   # 视频 filtergraph 语句
        audio_parts: List[str] = []   # 音频 filtergraph 语句
        clip_index = 0                # 全局输入槽位编号（视频 + 音频共用）

        # 基础视频轨（track_type="video"）的拼接输出标签
        base_video_out_labels: List[str] = []
        # Y 轴叠加轨（track_type="overlay"）的槽位 + clip 元数据 + 是否静态图片
        overlay_slots: List[Tuple[str, Clip, bool]] = []  # (rgba_label, clip, is_image)
        # 文本叠加轨（track_type="text_overlay"）：(display_text, clip_obj)
        text_overlay_slots: List[Tuple[str, Clip]] = []

        # ── Step 1: 遍历 Track，区分 video / overlay / text_overlay ────
        for t_idx, track in enumerate(timeline.tracks):
            if not track.clips:
                continue

            track_type = getattr(track, "track_type", "video")

            # ── text_overlay 轨道（text_template 虚拟资产）──────────────
            # 无物理文件，不添加 -i 输入；直接从 manifest.content_matrix
            # 按目标语种提取文本，延迟到 overlay 级联阶段注入 drawtext 滤镜。
            if track_type == "text_overlay":
                clip = track.clips[0]
                content_matrix: dict = {}
                if clip.manifest:
                    content_matrix = clip.manifest.get("content_matrix", {})
                # 优先目标语种 → 降级 zh → 降级第一个可用语种 → 素材路径兜底
                display_text = (
                    content_matrix.get(language)
                    or content_matrix.get("zh")
                    or (next(iter(content_matrix.values()), None) if content_matrix else None)
                    or clip.file_path  # 最终兜底：显示虚拟路径（便于调试）
                )
                text_overlay_slots.append((str(display_text), clip))
                self.log(
                    f"[TextOverlay] track={track.name} lang={language} "
                    f"text={str(display_text)[:40]!r}"
                )
                continue

            # ── overlay 轨道（PNG 图层）：只注册输入槽位，不走 concat ──────
            if track_type == "overlay":
                # overlay 轨道通常只有 1 个 Clip（logo 或 sticker）
                clip = track.clips[0]
                # 静态图片检测（png/jpg/webp/bmp）：
                #   -loop 1 让图片流无限循环，避免单帧闪退；
                #   overlay 滤镜侧追加 shortest=1 安全截断，防止输出视频被无限拉长。
                _ext = clip.file_path.rsplit(".", 1)[-1].lower() if "." in clip.file_path else ""
                _is_static_image = _ext in {"png", "jpg", "jpeg", "webp", "bmp"}
                if _is_static_image:
                    input_args.extend(["-loop", "1", "-i", clip.file_path])
                    self.log(
                        f"[Overlay] 静态图片输入: {clip.file_path!r} → 追加 -loop 1"
                    )
                else:
                    input_args.extend(["-i", clip.file_path])
                raw_label = f"[{clip_index}:v]"
                rgba_label = f"[rgba{clip_index}]"
                # format=rgba：保留 PNG 透明通道，避免 alpha 被黑色填充
                video_parts.append(f"{raw_label}format=rgba{rgba_label}")
                overlay_slots.append((rgba_label, clip, _is_static_image))
                clip_index += 1
                continue

            # ── video 轨道：原有 X 轴 concat 管线 ─────────────────────────
            per_clip_labels: List[str] = []

            for clip in track.clips:
                # 静态图片嗅探与时空膨胀：单帧图片需要 -loop 1 撑开为视频流，
                # 否则 concat 滤镜只见一帧即丢弃，导致主轴片段缺失。
                _ext = clip.file_path.rsplit(".", 1)[-1].lower() if "." in clip.file_path else ""
                _is_static_image = _ext in {"png", "jpg", "jpeg", "webp", "bmp"}

                if _is_static_image:
                    actual_dur = (clip.duration or 0.0) if (clip.duration or 0.0) > 0 else 5.0
                    input_args.extend([
                        "-loop", "1",
                        "-framerate", str(self.TARGET_FPS),
                        "-t", str(actual_dur),
                        "-i", clip.file_path,
                    ])
                    self.log(f"[VideoTrack] X轴主图膨胀: {clip.file_path!r} → {actual_dur}s")
                else:
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
        total_text_count = len(text_overlay_slots)
        # 若后续还有 text_overlay 要串联，PNG overlay 的最后一级不能直接输出 [outv]，
        # 而应输出一个中间过渡标签，由 drawtext 链终结为 [outv]。
        _has_text_after_overlay = total_text_count > 0

        for ov_idx, (rgba_label, clip, is_image) in enumerate(overlay_slots):
            is_last_ov = (ov_idx == total_overlay_count - 1)
            # 若 PNG overlay 是最后一层且后续无文本叠加，直接终结为 [outv]
            if is_last_ov and not _has_text_after_overlay:
                out_label = "[outv]"
            else:
                out_label = f"[comp_ov{ov_idx}]"

            # 定位坐标：三级优先级 — layout 九宫格 > overlay_x/y 传统字段 > 左上角 0:0
            _clip_layout = getattr(clip, "layout", None)
            if _clip_layout:
                ov_x, ov_y = self.get_ffmpeg_coordinates(_clip_layout, is_text=False)
            else:
                ov_x = getattr(clip, "overlay_x", None) or "0"
                ov_y = getattr(clip, "overlay_y", None) or "0"

            # 时间窗口：使用全局真实时间轴（Late-Binding），精确控制显示区间。
            # DSL 路径：beat_index 已标注 → 使用 ffprobe 采集的累积真实时间。
            # Assembler 路径：beat_index=None → 退回 Clip 自身 start_time/duration。
            t_start, t_end = self._resolve_clip_timing(
                clip, beat_actual_starts, total_actual_dur
            )
            enable = f"'between(t,{t_start:.6f},{t_end:.6f})'"

            # 静态图片安全兜底：shortest=1 确保 -loop 1 图片流不会拉长输出视频。
            # 当主视频流结束时，overlay 滤镜随之终止，完全防止无限延伸。
            overlay_extra = ":shortest=1" if is_image else ""

            video_parts.append(
                f"{base}{rgba_label}overlay={ov_x}:{ov_y}:enable={enable}{overlay_extra}{out_label}"
            )
            base = out_label
            self.log(
                f"[Overlay] slot {ov_idx}: {rgba_label} @ ({ov_x},{ov_y}) "
                f"layout={_clip_layout or 'legacy'} "
                f"enable=between(t,{t_start:.3f},{t_end:.3f}) "
                f"{'[image/shortest=1]' if is_image else '[video]'} → {out_label}"
            )

        # 无任何叠加层：基础视频直接 copy → [outv]
        # 仅有文本叠加（无 PNG overlay）：先 copy 到过渡标签，再由 drawtext 链终结
        if total_overlay_count == 0 and total_text_count == 0:
            video_parts.append(f"{base}copy[outv]")
        elif total_overlay_count == 0 and total_text_count > 0:
            pre_text_label = "[pre_text]"
            video_parts.append(f"{base}copy{pre_text_label}")
            base = pre_text_label

        # ── Step 2b: 级联 text_overlay（drawtext 滤镜链）──────────────
        # text_template 无物理输入文件，直接在视频流上叠加 drawtext 滤镜。
        # 每个文本槽位依次串联，最终输出 [outv]。
        # 建议字体参数：fontsize 根据画幅动态计算，居中显示 + 半透明底框。
        for txt_idx, (display_text, clip) in enumerate(text_overlay_slots):
            is_last_txt = (txt_idx == total_text_count - 1)
            out_label = "[outv]" if is_last_txt else f"[comp_txt{txt_idx}]"

            escaped = self._escape_drawtext(display_text)
            # 时间窗口：使用全局真实时间轴（Late-Binding），与 Beat 的物理素材时长完美同寿。
            t_start, t_end = self._resolve_clip_timing(
                clip, beat_actual_starts, total_actual_dur
            )

            # fontsize 按画幅高度 1/18 自适应（竖屏 1280 → ~71px；横屏 720 → ~40px）
            font_size = max(int(self.target_h / 18), 28)

            # 九宫格坐标解析：读取 clip.layout（三级优先级已由 DSLAdapter 注入）
            _txt_layout = getattr(clip, "layout", None) or "center"
            txt_x, txt_y = self.get_ffmpeg_coordinates(_txt_layout, is_text=True)

            drawtext_filter = (
                f"drawtext="
                f"text='{escaped}':"
                f"fontsize={font_size}:"
                f"fontcolor=white:"
                f"x={txt_x}:"
                f"y={txt_y}:"
                f"box=1:boxcolor=black@0.5:boxborderw=10:"
                f"enable='between(t\\,{t_start:.6f}\\,{t_end:.6f})'"
            )
            video_parts.append(f"{base}{drawtext_filter}{out_label}")
            base = out_label
            self.log(
                f"[TextOverlay] drawtext slot {txt_idx}: "
                f"text={display_text[:30]!r} layout={_txt_layout} "
                f"x={txt_x} y={txt_y} "
                f"enable=between({t_start:.3f},{t_end:.3f}) → {out_label}"
            )

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

        # 2. 调用编译器（传入目标语种，供 text_overlay 轨道提取 content_matrix 文本）
        render_lang: str = getattr(context, "test_language", None) or "en"
        input_args, video_fg, audio_fg = self._build_filtergraph(timeline, language=render_lang)

        if not video_fg:
            self.log("Warning: empty filtergraph — nothing to render.")
            return context

        # 3. 合并视频 filtergraph（无音频：Timeline 只含视频轨道）
        full_filtergraph = video_fg

        # 4. 组装完整 FFmpeg 命令（无音频流：生成静音母带）
        task_id:   str = context.task_id   # WS 任务 ID，与前端 queueWorker 对齐
        user_id:   str = context.tenant_id    # 定向推送目标，防止多租户数据串流
        file_sid = self._resolve_file_sid(context)
        output_path = self._master_output_path(context)
        logger.info(
            f"[FFmpegCompositorNode] master output task_id={task_id} "
            f"execution_id={context.config.get('execution_id')} "
            f"child_index={context.config.get('child_index')} "
            f"file_sid={file_sid} path={output_path}"
        )
        ffmpeg_bin = get_ffmpeg_path("ffmpeg.exe")

        map_args = ["-map", "[outv]", "-an"]   # -an: 无音频轨道
        codec_args = ["-c:v", "libx264", "-preset", "superfast", "-threads", "0"]

        cmd: List[str] = (
            # -progress pipe:1 将进度键值对写入 stdout，与 stderr 错误日志完全分离
            [ffmpeg_bin, "-progress", "pipe:1"]
            + input_args
            + ["-filter_complex", full_filtergraph]
            + map_args
            + codec_args
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

        # ── 生命周期 WS 推送：启动前发 running ──────────────────────────────────
        self._ws_broadcast(task_id, user_id, {"status": "running", "progress": 0})
        logger.info("⏳ 正在渲染最终母带，请稍候...")
        self.log("Rendering master video, please wait...")

        # 6. 用 Popen 替换 subprocess.run，实现实时进度流读取
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,   # 承接 -progress pipe:1 的进度输出
                stderr=subprocess.PIPE,   # 承接 FFmpeg 的错误/警告日志
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_WIN_NO_WINDOW,
            )

            # ── stderr 独立线程消费，防止缓冲区满导致子进程死锁 ──────────────
            _stderr_lines: List[str] = []

            def _drain_stderr(pipe) -> None:
                for line in pipe:
                    _stderr_lines.append(line)

            _stderr_thread = threading.Thread(
                target=_drain_stderr, args=(proc.stderr,), daemon=True
            )
            _stderr_thread.start()

            # ── 逐行解析 -progress 输出，计算并推送实时进度 ──────────────────
            # out_time_us: FFmpeg ≥ 4.x 输出的已渲染微秒数（精度优于 out_time_ms）
            # 总时长以 context.target_duration 为基准（秒 → 微秒），最小值 1 防零除
            total_us: int = max(context.target_duration * 1_000_000, 1)
            _last_ws_time: float = 0.0   # 上次广播的 monotonic 时间戳
            _last_pct: int = -1          # 上次广播的进度百分比

            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line.startswith("out_time_us="):
                    continue
                try:
                    elapsed_us = int(line.split("=", 1)[1])
                except ValueError:
                    continue

                pct = min(int(elapsed_us * 100 / total_us), 99)  # 99 封顶；completed 由 coordinator 推送
                now = time.monotonic()
                # 限速规则：两次广播间隔 ≥ 1s，或进度跳变 ≥ 5%（防止高频刷屏）
                if now - _last_ws_time >= 1.0 or pct - _last_pct >= 5:
                    self._ws_broadcast(task_id, user_id, {"status": "running", "progress": pct})
                    _last_ws_time = now
                    _last_pct = pct

            proc.wait()
            _stderr_thread.join(timeout=10)
            stderr_output = "".join(_stderr_lines)

            if proc.returncode != 0:
                raise subprocess.CalledProcessError(
                    proc.returncode, cmd, stderr=stderr_output
                )

            self.log("[OK] FFmpeg master render completed successfully.")

        except FileNotFoundError:
            if not self._coordinator_owns_terminal(context):
                self._ws_broadcast(task_id, user_id, {"status": "failed"})
            self.log(
                f"[ERROR] ffmpeg binary not found at '{ffmpeg_bin}'. "
                "In production, ensure ffmpeg.exe is in the same directory as backend.exe. "
                "In development, ensure ffmpeg is available on your system PATH."
            )
            return context
        except subprocess.CalledProcessError as exc:
            if not self._coordinator_owns_terminal(context):
                self._ws_broadcast(task_id, user_id, {"status": "failed"})
            self.log(
                f"[ERROR] FFmpeg exited with code {exc.returncode}. stderr:\n{exc.stderr}"
            )
            raise RuntimeError(f"FFmpeg render failed: {exc.stderr}")

        # 7. 将母带路径写回 Context
        context.set_asset("video_master", output_path)
        self.log(f"Master video path '{output_path}' written to Context.")

        # 8. 逐语言生成最终变体视频（配音 + 字幕 + 画面合并）
        # Legacy direct calls retain failed WS; coordinator children only re-raise.
        try:
            self._render_variant(context, output_path, ffmpeg_bin)
        except Exception:
            if not self._coordinator_owns_terminal(context):
                self._ws_broadcast(task_id, user_id, {"status": "failed"})
            raise

        # WS completed 推送职责已移交给 render_batch_worker（routes_dsl.py），
        # 确保在 CoverNode 抽帧完成后才推送，cover_path 才能包含在 payload 中。
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

        # WS 推送上下文（与 execute() 保持一致，使用同一 task_id / user_id）
        task_id: str = context.task_id
        user_id: str = context.tenant_id

        # 拉取 timeline，用于读取 BGM/SFX audio_tracks
        timeline: Timeline = context.get_asset("timeline")
        audio_tracks = timeline.audio_tracks if timeline else []

        # 从 context.config 读取管线开关（render_worker 已注入，默认保守兜底为 True）
        _enable_tts       = context.config.get("enable_tts", True)
        _enable_subtitles = context.config.get("enable_subtitles", True)

        for lang, assets in context.variants.items():
            ass_path: str = assets.get("subtitle_ass", "")
            voice_path: str = assets.get("voice_audio", "")
            file_sid = self._resolve_file_sid(context)
            final_path = self._final_output_path(context, lang)
            logger.info(
                f"[FFmpegCompositorNode] final output task_id={task_id} "
                f"execution_id={context.config.get('execution_id')} "
                f"child_index={context.config.get('child_index')} "
                f"file_sid={file_sid} lang={lang} path={final_path}"
            )

            has_sub   = bool(ass_path   and os.path.exists(ass_path))
            has_voice = bool(voice_path and os.path.exists(voice_path))

            # ── 管线开关硬截断：即使文件存在也强制旁路 ────────────────────
            if not _enable_tts and has_voice:
                self.log(
                    f"[{lang}] enable_tts=False：强制旁路配音轨，"
                    "从 FFmpeg 命令中裁剪 voice 输入与 amix 混音"
                )
                has_voice = False
            if not _enable_subtitles and has_sub:
                self.log(
                    f"[{lang}] enable_subtitles=False：强制旁路字幕轨，"
                    "跳过 subtitles=... 滤镜，防止 FFmpeg 找不到 .ass 文件崩溃"
                )
                has_sub = False

            if not has_sub:
                self.log(f"[{lang}] No subtitle file — video track will be raw copy.")
            if not has_voice:
                self.log(f"[{lang}] No voice_audio — TTS track skipped.")

            # ── Step 1: 收集所有 FFmpeg 输入，严格按槽位编号递增 ──────────────
            # 槽位 0 = master_video（固定）；-progress pipe:1 分离进度与 stderr
            inputs: List[str] = [ffmpeg_bin, "-progress", "pipe:1", "-i", master_path]
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

            # ── 生命周期推送：变体渲染开始 ────────────────────────────────────
            self._ws_broadcast(task_id, user_id, {"status": "running", "progress": 0, "lang": lang})

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=_WIN_NO_WINDOW,
                )

                # stderr 消费线程，防止缓冲区满阻塞子进程
                _stderr_lines: List[str] = []

                def _drain(pipe) -> None:
                    for line in pipe:
                        _stderr_lines.append(line)

                _t = threading.Thread(target=_drain, args=(proc.stderr,), daemon=True)
                _t.start()

                # 实时进度推送（变体渲染通常比母带快，限速 1s/次即可）
                total_us: int = max(context.target_duration * 1_000_000, 1)
                _last_ws_time: float = 0.0

                for raw_line in proc.stdout:
                    line = raw_line.strip()
                    if not line.startswith("out_time_us="):
                        continue
                    try:
                        elapsed_us = int(line.split("=", 1)[1])
                    except ValueError:
                        continue
                    now = time.monotonic()
                    if now - _last_ws_time >= 1.0:
                        pct = min(int(elapsed_us * 100 / total_us), 99)
                        self._ws_broadcast(
                            task_id, user_id,
                            {"status": "running", "progress": pct, "lang": lang},
                        )
                        _last_ws_time = now

                proc.wait()
                _t.join(timeout=10)
                stderr_output = "".join(_stderr_lines)

                if proc.returncode != 0:
                    raise subprocess.CalledProcessError(
                        proc.returncode, cmd, stderr=stderr_output
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
                raise
            except subprocess.CalledProcessError as exc:
                error_msg = exc.stderr[-800:] if exc.stderr else "Unknown error"
                self.log(
                    f"[{lang}] [ERROR] Variant render failed "
                    f"(exit {exc.returncode}):\n{error_msg}"
                )
                raise RuntimeError(f"FFmpeg render failed: {error_msg}")
