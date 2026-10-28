import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, List, Optional, Tuple

# 隐藏 Windows 下 FFmpeg 子进程的黑色控制台窗口
_WIN_NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

from src.api.ws_manager import manager as ws_manager
from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.logger import logger
from src.core.timeline import Clip, Timeline, Track
from src.utils.env_utils import get_ffmpeg_path


_MEDIA_STDOUT_LIMIT = 64 * 1024
_MEDIA_STDERR_LIMIT = 8 * 1024
_MEDIA_POLL_INTERVAL_SECONDS = 0.05
_MEDIA_TERMINATE_GRACE_SECONDS = 3.0
_FFPROBE_TIMEOUT_SECONDS = 15.0
_RENDER_TIMEOUT_MIN_SECONDS = 120.0
_RENDER_TIMEOUT_OVERHEAD_SECONDS = 60.0
_RENDER_TIMEOUT_PER_MEDIA_SECOND = 12.0
_RENDER_TIMEOUT_MAX_SECONDS = 900.0


class _BoundedTextBuffer:
    """Thread-safe trailing text buffer with a strict character ceiling."""

    def __init__(self, limit: int) -> None:
        self._limit = max(int(limit), 0)
        self._parts: Deque[str] = deque()
        self._length = 0
        self._lock = threading.Lock()

    def append(self, value: str) -> None:
        if self._limit == 0 or not value:
            return
        with self._lock:
            self._parts.append(value)
            self._length += len(value)
            while self._length > self._limit and self._parts:
                overflow = self._length - self._limit
                head = self._parts[0]
                if len(head) <= overflow:
                    self._parts.popleft()
                    self._length -= len(head)
                else:
                    self._parts[0] = head[overflow:]
                    self._length -= overflow

    def getvalue(self) -> str:
        with self._lock:
            return "".join(self._parts)


@dataclass(frozen=True)
class _MediaProcessResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float


class _MediaProcessFailure(RuntimeError):
    """Safe, typed failure propagated from one bounded media subprocess."""

    def __init__(
        self,
        code: str,
        *,
        stage: str,
        returncode: Optional[int] = None,
        stderr: str = "",
    ) -> None:
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.returncode = returncode
        self.stderr = stderr[-_MEDIA_STDERR_LIMIT:]


class FFmpegCompositorNode(BaseNode):
    """
    底层渲染引擎：将 Timeline 编译为 FFmpeg Complex Filtergraph (Slot 模式)。
    支持多轨视频叠加（Y轴 overlay）+ 多音频轨混音（amix）。
    严格禁止引入 moviepy 等逐帧处理库，全部通过 subprocess + ffmpeg 实现。
    """

    def __init__(self, name: str = "FFmpeg_Slot_Compositor"):
        super().__init__(name)
        self.target_duration: float = 15.0
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

    @staticmethod
    def _internal_output_root(context: WorkflowContext) -> Path:
        """Use the injected runtime authority, preserving direct-node tests."""
        return Path(context.config.get("internal_output_root", "output"))

    @classmethod
    def _master_output_path(cls, context: WorkflowContext) -> str:
        file_sid = cls._resolve_file_sid(context)
        sid_suffix = f"_{file_sid}" if file_sid else ""
        if "internal_output_root" not in context.config:
            return f"output/master_video{sid_suffix}.mp4"
        return str(cls._internal_output_root(context) / f"master_video{sid_suffix}.mp4")

    @classmethod
    def _final_output_path(cls, context: WorkflowContext, language: str) -> str:
        file_sid = cls._resolve_file_sid(context)
        sid_suffix = f"_{file_sid}" if file_sid else ""
        if "internal_output_root" not in context.config:
            return f"output/final_{language}{sid_suffix}.mp4"
        return str(
            cls._internal_output_root(context) / f"final_{language}{sid_suffix}.mp4"
        )

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

    @staticmethod
    def _render_timeout_seconds(media_duration: float) -> float:
        """Return a bounded encoding budget derived from the real media duration."""
        duration = max(float(media_duration or 0.0), 1.0)
        calculated = (
            _RENDER_TIMEOUT_OVERHEAD_SECONDS
            + duration * _RENDER_TIMEOUT_PER_MEDIA_SECOND
        )
        return min(
            max(calculated, _RENDER_TIMEOUT_MIN_SECONDS),
            _RENDER_TIMEOUT_MAX_SECONDS,
        )

    @staticmethod
    def _identity_fields(context: WorkflowContext) -> str:
        return (
            f"task_id={context.task_id} "
            f"execution_id={context.config.get('execution_id')} "
            f"child_index={context.config.get('child_index')} "
            f"file_sid={context.config.get('file_sid')}"
        )

    @staticmethod
    def _safe_stderr_excerpt(stderr: str, limit: int = 800) -> str:
        """Keep diagnostics finite and single-line without exposing process state."""
        safe = "".join(
            char if char.isprintable() and char not in "\r\n" else " "
            for char in (stderr or "")
        )
        safe = " ".join(safe.split())
        safe = re.sub(
            r"(?i)\b(authorization|xi-api-key|api[_-]?key|access[_-]?token|token)"
            r"\s*[:=]\s*[^\s,;]+",
            r"\1=[REDACTED]",
            safe,
        )
        safe = re.sub(
            r"(?i)\bbearer\s+[^\s,;]+",
            "Bearer [REDACTED]",
            safe,
        )
        return safe[-max(int(limit), 0):]

    def _log_media_stage(
        self,
        context: WorkflowContext,
        stage: str,
        *,
        elapsed_seconds: Optional[float] = None,
        failure_code: Optional[str] = None,
        returncode: Optional[int] = None,
        role: Optional[str] = None,
        extra: str = "",
    ) -> None:
        fields = [
            "[FINAL_RENDER]",
            f"stage={stage}",
            self._identity_fields(context),
        ]
        if role:
            fields.append(f"role={role}")
        if elapsed_seconds is not None:
            fields.append(f"elapsed_ms={int(max(elapsed_seconds, 0.0) * 1000)}")
        if failure_code:
            fields.append(f"failure_code={failure_code}")
        if returncode is not None:
            fields.append(f"returncode={returncode}")
        if extra:
            fields.append(extra)
        logger.info(" ".join(fields))

    @staticmethod
    def _stop_and_reap_process(proc: subprocess.Popen, grace_seconds: float) -> None:
        """Terminate, escalate to kill, and reap one already-created process."""
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired as exc:
            raise _MediaProcessFailure(
                "MEDIA_PROCESS_REAP_TIMEOUT",
                stage="PROCESS_CLEANUP",
            ) from exc

    def _run_bounded_media_process(
        self,
        command: List[str],
        *,
        context: WorkflowContext,
        process_kind: str,
        timeout_seconds: float,
        started_stage: Optional[str] = None,
        exited_stage: Optional[str] = None,
        on_stdout_line: Optional[Callable[[str], None]] = None,
    ) -> _MediaProcessResult:
        """
        Run one created media process without blocking on a pipe iterator.

        Windows process creation itself is synchronous and cannot be made an
        absolute deadline without risking a late-created orphan. The caller logs
        before entry; STARTED is logged only after Popen returns successfully.
        """
        started_at = time.monotonic()
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_WIN_NO_WINDOW,
            )
        except Exception as exc:
            raise _MediaProcessFailure(
                f"{process_kind}_CREATE_FAILED",
                stage="PROCESS_CREATE",
            ) from exc

        if started_stage:
            self._log_media_stage(
                context,
                started_stage,
                elapsed_seconds=time.monotonic() - started_at,
                extra=f"pid={getattr(proc, 'pid', 'NOT_AVAILABLE')}",
            )

        stdout_tail = _BoundedTextBuffer(_MEDIA_STDOUT_LIMIT)
        stderr_tail = _BoundedTextBuffer(_MEDIA_STDERR_LIMIT)
        stdout_events: "queue.Queue[str]" = queue.Queue()

        def _drain_stdout(pipe) -> None:
            if pipe is None:
                return
            for line in pipe:
                stdout_tail.append(line)
                if on_stdout_line is not None:
                    stdout_events.put(line)

        def _drain_stderr(pipe) -> None:
            if pipe is None:
                return
            for line in pipe:
                stderr_tail.append(line)

        stdout_thread = threading.Thread(
            target=_drain_stdout, args=(proc.stdout,), daemon=True
        )
        stderr_thread = threading.Thread(
            target=_drain_stderr, args=(proc.stderr,), daemon=True
        )
        stdout_thread.start()
        stderr_thread.start()

        deadline = started_at + max(float(timeout_seconds), 0.001)
        cancel_event = context.config.get("render_cancel_event")
        failure_code: Optional[str] = None

        def _deliver_stdout_events() -> Optional[str]:
            while True:
                try:
                    stdout_line = stdout_events.get_nowait()
                except queue.Empty:
                    return None
                if on_stdout_line is None:
                    continue
                try:
                    on_stdout_line(stdout_line)
                except Exception:
                    return f"{process_kind}_PROGRESS_CALLBACK_FAILED"

        while True:
            callback_failure = _deliver_stdout_events()
            if callback_failure is not None:
                failure_code = callback_failure
                break

            poll = getattr(proc, "poll", None)
            if callable(poll):
                returncode = poll()
            else:  # Compatibility for deterministic legacy test doubles only.
                returncode = getattr(proc, "returncode", None)
            if returncode is not None:
                break
            if (
                cancel_event is not None
                and callable(getattr(cancel_event, "is_set", None))
                and cancel_event.is_set()
            ):
                failure_code = f"{process_kind}_CANCELLED"
                break
            if time.monotonic() >= deadline:
                failure_code = f"{process_kind}_TIMEOUT"
                break
            time.sleep(_MEDIA_POLL_INTERVAL_SECONDS)

        cleanup_failure: Optional[_MediaProcessFailure] = None
        if failure_code is not None:
            try:
                self._stop_and_reap_process(proc, _MEDIA_TERMINATE_GRACE_SECONDS)
            except _MediaProcessFailure as exc:
                # Continue through pipe closure even when the operating system
                # does not confirm that the killed process was reaped.  The
                # explicit cleanup failure remains the authoritative result.
                cleanup_failure = exc
                failure_code = exc.code

        # Reap an exited process and let both pipe readers observe EOF.
        if failure_code is None:
            proc.wait()
        stdout_thread.join(timeout=_MEDIA_TERMINATE_GRACE_SECONDS)
        stderr_thread.join(timeout=_MEDIA_TERMINATE_GRACE_SECONDS)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            for pipe in (proc.stdout, proc.stderr):
                try:
                    if pipe is not None:
                        pipe.close()
                except Exception:
                    pass
            stdout_thread.join(timeout=_MEDIA_TERMINATE_GRACE_SECONDS)
            stderr_thread.join(timeout=_MEDIA_TERMINATE_GRACE_SECONDS)
            failure_code = failure_code or f"{process_kind}_PIPE_DRAIN_TIMEOUT"
        for pipe in (proc.stdout, proc.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:
                pass

        callback_failure = _deliver_stdout_events()
        if callback_failure is not None and failure_code is None:
            failure_code = callback_failure

        elapsed = time.monotonic() - started_at
        raw_returncode = getattr(proc, "returncode", None)
        returncode = int(raw_returncode) if raw_returncode is not None else -1
        if exited_stage:
            self._log_media_stage(
                context,
                exited_stage,
                elapsed_seconds=elapsed,
                failure_code=failure_code,
                returncode=returncode,
            )
        if failure_code is not None:
            raise _MediaProcessFailure(
                failure_code,
                stage=(
                    cleanup_failure.stage
                    if cleanup_failure is not None
                    else exited_stage or process_kind
                ),
                returncode=returncode,
                stderr=stderr_tail.getvalue(),
            )
        return _MediaProcessResult(
            returncode=returncode,
            stdout=stdout_tail.getvalue(),
            stderr=stderr_tail.getvalue(),
            elapsed_seconds=elapsed,
        )

    # ------------------------------------------------------------------
    # 核心编译器：Timeline → (input_args, video_filtergraph, audio_filtergraph)
    # ------------------------------------------------------------------

    def _probe_duration(
        self,
        file_path: str,
        *,
        context: WorkflowContext,
        role: str,
    ) -> float:
        """
        Probe one required Final-stage media duration or raise a typed failure.

        Unlike the timeline planner's explicit nominal-duration fallback, this
        preflight is fail-closed and always emits bounded structured evidence.
        """
        probe_stage = f"PROBE_{role.upper()}"
        started_at = time.monotonic()
        self._log_media_stage(context, f"{probe_stage}_START", role=role)
        try:
            try:
                ffprobe_bin = get_ffmpeg_path("ffprobe.exe")
            except Exception as exc:
                raise _MediaProcessFailure(
                    "FFPROBE_PATH_RESOLUTION_FAILED",
                    stage=probe_stage,
                ) from exc
            result = self._run_bounded_media_process(
                [
                    ffprobe_bin,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path,
                ],
                context=context,
                process_kind="FFPROBE",
                timeout_seconds=_FFPROBE_TIMEOUT_SECONDS,
            )
            if result.returncode != 0:
                raise _MediaProcessFailure(
                    "FFPROBE_NONZERO_EXIT",
                    stage=probe_stage,
                    returncode=result.returncode,
                    stderr=result.stderr,
                )
            val = result.stdout.strip()
            try:
                duration = float(val)
            except (TypeError, ValueError) as exc:
                raise _MediaProcessFailure(
                    "FFPROBE_RESULT_INVALID",
                    stage=probe_stage,
                    returncode=result.returncode,
                ) from exc
            if duration <= 0:
                raise _MediaProcessFailure(
                    "FFPROBE_RESULT_INVALID",
                    stage=probe_stage,
                    returncode=result.returncode,
                )
            self._log_media_stage(
                context,
                f"{probe_stage}_END",
                role=role,
                elapsed_seconds=time.monotonic() - started_at,
            )
            return duration
        except _MediaProcessFailure as exc:
            self._log_media_stage(
                context,
                f"{probe_stage}_FAILED",
                role=role,
                elapsed_seconds=time.monotonic() - started_at,
                failure_code=exc.code,
                returncode=exc.returncode,
                extra=(
                    f"stderr={self._safe_stderr_excerpt(exc.stderr)}"
                    if exc.stderr
                    else ""
                ),
            )
            raise

    @staticmethod
    def _probe_duration_for_timeline(file_path: str) -> float:
        """Best-effort planning probe; callers intentionally use nominal fallback."""
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
                timeout=_FFPROBE_TIMEOUT_SECONDS,
                creationflags=_WIN_NO_WINDOW,
            )
            if result.returncode != 0:
                return 0.0
            value = float(result.stdout.strip())
            return value if value > 0 else 0.0
        except (OSError, subprocess.SubprocessError, TypeError, ValueError):
            return 0.0

    def _validate_final_output(
        self,
        final_path: str,
        *,
        context: WorkflowContext,
        require_audio: bool,
    ) -> None:
        """Enforce the Final success contract without changing media content."""
        if not os.path.isfile(final_path):
            raise _MediaProcessFailure(
                "FINAL_OUTPUT_MISSING",
                stage="FINAL_POSTCONDITION",
            )
        try:
            output_size = os.path.getsize(final_path)
        except OSError as exc:
            raise _MediaProcessFailure(
                "FINAL_OUTPUT_STAT_FAILED",
                stage="FINAL_POSTCONDITION",
            ) from exc
        if output_size <= 0:
            raise _MediaProcessFailure(
                "FINAL_OUTPUT_EMPTY",
                stage="FINAL_POSTCONDITION",
            )

        ffprobe_bin = get_ffmpeg_path("ffprobe.exe")
        result = self._run_bounded_media_process(
            [
                ffprobe_bin,
                "-v", "error",
                "-show_entries", "stream=codec_type",
                "-of", "json",
                final_path,
            ],
            context=context,
            process_kind="FINAL_POSTCONDITION_PROBE",
            timeout_seconds=_FFPROBE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise _MediaProcessFailure(
                "FINAL_OUTPUT_PROBE_NONZERO_EXIT",
                stage="FINAL_POSTCONDITION",
                returncode=result.returncode,
                stderr=result.stderr,
            )
        try:
            payload = json.loads(result.stdout)
            stream_types = {
                stream.get("codec_type")
                for stream in payload.get("streams", [])
                if isinstance(stream, dict)
            }
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise _MediaProcessFailure(
                "FINAL_OUTPUT_PROBE_INVALID",
                stage="FINAL_POSTCONDITION",
            ) from exc
        if "video" not in stream_types:
            raise _MediaProcessFailure(
                "FINAL_OUTPUT_VIDEO_STREAM_MISSING",
                stage="FINAL_POSTCONDITION",
            )
        if require_audio and "audio" not in stream_types:
            raise _MediaProcessFailure(
                "FINAL_OUTPUT_AUDIO_STREAM_MISSING",
                stage="FINAL_POSTCONDITION",
            )

        self._log_media_stage(
            context,
            "FINAL_POSTCONDITION",
            extra=(
                f"result=PASS bytes={output_size} "
                f"audio_required={str(require_audio).lower()}"
            ),
        )

    @staticmethod
    def _main_video_clip_count(timeline: Optional[Timeline]) -> int:
        """Return the clip count on the first non-empty (main) video track."""
        if timeline is None:
            return 0
        for track in timeline.tracks:
            if getattr(track, "track_type", "video") == "video" and track.clips:
                return len(track.clips)
        return 0

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
                actual_dur = self._probe_duration_for_timeline(clip.file_path)
            if actual_dur <= 0:
                # ffprobe 失败时退回名义时长，再退回保守值 5s
                actual_dur = (clip.duration or 0.0) if (clip.duration or 0.0) > 0 else 5.0
                self.log(
                    f"[GlobalTimeline] ffprobe 失败 '{clip.file_path}'，"
                    f"使用名义时长 {actual_dur:.3f}s 作为兜底。"
                )
            planned_dur = self._planned_clip_duration(
                clip,
                clip_count=len(main_video_clips),
                probed_duration=actual_dur,
            )
            self.log(
                f"[GlobalTimeline] clip={clip.file_path!r} "
                f"physical={actual_dur:.3f}s contract={planned_dur:.3f}s"
            )
            current_time += planned_dur

        self.log(
            f"[GlobalTimeline] {len(main_video_clips)} 个主视频 Clip → "
            f"beat_actual_starts={[round(s, 3) for s in beat_actual_starts]} "
            f"total={current_time:.3f}s"
        )
        return beat_actual_starts, current_time

    def _planned_clip_duration(
        self,
        clip: "Clip",
        *,
        clip_count: int,
        probed_duration: float | None = None,
    ) -> float:
        """Return the bounded output duration for one main-video clip."""
        if clip_count == 1 and self.target_duration > 0:
            return self.target_duration

        if probed_duration is not None and float(probed_duration) > 0:
            return float(probed_duration)

        nominal = float(clip.duration or 0.0)
        if nominal > 0:
            return nominal

        actual = (
            float(probed_duration)
            if probed_duration is not None
            else self._probe_duration_for_timeline(clip.file_path)
        )
        if actual > 0:
            return actual
        return 5.0

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
        _main_video_track: Optional[Track] = None
        _main_video_clips: List[Clip] = []
        for _track in timeline.tracks:
            if getattr(_track, "track_type", "video") == "video" and _track.clips:
                _main_video_track = _track
                _main_video_clips = list(_track.clips)
                break  # 主视频轨唯一，找到即止

        beat_actual_starts: List[float]
        total_actual_dur: float
        beat_actual_starts, total_actual_dur = self._compute_beat_timeline(_main_video_clips)
        self._compiled_media_duration = total_actual_dur

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
            is_single_main_video_track = (
                track is _main_video_track and len(_main_video_clips) == 1
            )

            for clip in track.clips:
                # 静态图片嗅探与时空膨胀：单帧图片需要 -loop 1 撑开为视频流，
                # 否则 concat 滤镜只见一帧即丢弃，导致主轴片段缺失。
                _ext = clip.file_path.rsplit(".", 1)[-1].lower() if "." in clip.file_path else ""
                _is_static_image = _ext in {"png", "jpg", "jpeg", "webp", "bmp"}

                if _is_static_image:
                    actual_dur = self._planned_clip_duration(
                        clip,
                        clip_count=len(track.clips),
                    )
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

                # Every main-video clip follows the same normalization and
                # target geometry contract. Duration conformance is deliberately
                # limited to the single-clip recovery path so the established
                # multi-clip concat timing remains unchanged.
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
                if is_single_main_video_track:
                    output_dur = self._planned_clip_duration(
                        clip,
                        clip_count=1,
                    )
                    norm_chain += (
                        f",tpad=stop_mode=clone:stop_duration={output_dur:.6f},"
                        f"trim=duration={output_dur:.6f},"
                        f"setpts=PTS-STARTPTS"
                    )
                norm_chain += norm_label
                video_parts.append(norm_chain)
                per_clip_labels.append(norm_label)

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
        self.target_duration = float(getattr(context, "target_duration", 15) or 15)
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

        # 6. Drain both pipes independently and enforce a media-duration budget.
        total_us: int = max(int(context.target_duration * 1_000_000), 1)
        _last_ws_time: float = 0.0
        _last_pct: int = -1

        def _master_progress(raw_line: str) -> None:
            nonlocal _last_ws_time, _last_pct
            line = raw_line.strip()
            if not line.startswith("out_time_us="):
                return
            try:
                elapsed_us = int(line.split("=", 1)[1])
            except ValueError:
                return
            pct = min(int(elapsed_us * 100 / total_us), 99)
            now = time.monotonic()
            if now - _last_ws_time >= 1.0 or pct - _last_pct >= 5:
                self._ws_broadcast(
                    task_id,
                    user_id,
                    {"status": "running", "progress": pct},
                )
                _last_ws_time = now
                _last_pct = pct

        master_media_duration = max(
            float(context.target_duration or 0.0),
            float(getattr(self, "_compiled_media_duration", 0.0) or 0.0),
        )
        master_timeout = self._render_timeout_seconds(master_media_duration)
        try:
            master_result = self._run_bounded_media_process(
                cmd,
                context=context,
                process_kind="MASTER_FFMPEG",
                timeout_seconds=master_timeout,
                started_stage="MASTER_PROCESS_STARTED",
                exited_stage="MASTER_PROCESS_EXITED",
                on_stdout_line=_master_progress,
            )
            if master_result.returncode != 0:
                raise _MediaProcessFailure(
                    "MASTER_FFMPEG_NONZERO_EXIT",
                    stage="MASTER_PROCESS_EXITED",
                    returncode=master_result.returncode,
                    stderr=master_result.stderr,
                )
            self.log("[OK] FFmpeg master render completed successfully.")
        except _MediaProcessFailure as exc:
            if not self._coordinator_owns_terminal(context):
                self._ws_broadcast(task_id, user_id, {"status": "failed"})
            error_excerpt = self._safe_stderr_excerpt(exc.stderr)
            self.log(
                "[ERROR] Master render failed "
                f"code={exc.code} returncode={exc.returncode} "
                f"stderr={error_excerpt or 'NOT_AVAILABLE'}"
            )
            raise

        # 7. 将母带路径写回 Context
        context.set_asset("video_master", output_path)
        self.log(f"Master video path '{output_path}' written to Context.")

        # 8. 逐语言生成最终变体视频（配音 + 字幕 + 画面合并）
        # Legacy direct calls retain failed WS; coordinator children only re-raise.
        try:
            self._render_variant(context, output_path, ffmpeg_bin)
        except Exception as exc:
            failure_code = getattr(exc, "code", exc.__class__.__name__.upper())
            self._log_media_stage(
                context,
                "FINAL_FAILED",
                failure_code=str(failure_code),
                returncode=getattr(exc, "returncode", None),
                extra=(
                    f"stderr={self._safe_stderr_excerpt(getattr(exc, 'stderr', ''))}"
                    if getattr(exc, "stderr", "")
                    else ""
                ),
            )
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
        target_duration = float(getattr(context, "target_duration", 15) or 15)
        if target_duration <= 0:
            raise RuntimeError("TARGET_DURATION_INVALID")
        single_main_clip = self._main_video_clip_count(timeline) == 1

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
            self._log_media_stage(
                context,
                "FINAL_PREFLIGHT_START",
                role=lang,
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
            trusted_media_duration = max(
                target_duration,
                float(getattr(self, "_compiled_media_duration", 0.0) or 0.0),
            )
            master_duration: Optional[float] = None
            if has_voice and not single_main_clip:
                master_duration = self._probe_duration(
                    master_path,
                    context=context,
                    role="MASTER",
                )
                if master_duration <= 0:
                    raise _MediaProcessFailure(
                        "MASTER_VIDEO_DURATION_UNVERIFIED",
                        stage="FINAL_PREFLIGHT",
                    )
            voice_target_duration = (
                target_duration
                if single_main_clip
                else master_duration or trusted_media_duration
            )
            if has_voice:
                voice_duration = self._probe_duration(
                    voice_path,
                    context=context,
                    role="VOICE",
                )
                if voice_duration <= 0:
                    raise _MediaProcessFailure(
                        "TTS_AUDIO_DURATION_UNVERIFIED",
                        stage="FINAL_PREFLIGHT",
                    )
                if voice_duration > voice_target_duration + 0.05:
                    raise _MediaProcessFailure(
                        "TTS_AUDIO_EXCEEDS_TARGET_DURATION",
                        stage="FINAL_PREFLIGHT",
                    )
                inputs += ["-i", voice_path]
                voice_label = f"[{next_idx}:a]"
                next_idx += 1

            # 第二顺位：timeline.audio_tracks 中的 BGM / SFX / general
            # audio_filter_parts : BGM 降噪滤镜语句列表（需写入 filter_complex）
            # audio_mix_labels   : 最终送入 amix 的标签列表（顺序即混音顺序）
            audio_filter_parts: List[str] = []
            audio_mix_labels:   List[str] = []

            if voice_label:
                padded_voice = "[voice_target]"
                audio_filter_parts.append(
                    f"{voice_label}apad,"
                    f"atrim=duration={voice_target_duration:.6f}"
                    f"{padded_voice}"
                )
                audio_mix_labels.append(padded_voice)

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
                        if single_main_clip:
                            audio_filter_parts.append(
                                f"{raw_label}volume=0.2,apad,"
                                f"atrim=duration={target_duration:.6f}{bgm_out}"
                            )
                        else:
                            audio_filter_parts.append(
                                f"{raw_label}volume=0.2{bgm_out}"
                            )
                        audio_mix_labels.append(bgm_out)
                        self.log(
                            f"[{lang}] BGM '{audio_track.name}' [{slot}:a] → volume=0.2 {bgm_out}"
                        )
                    else:
                        # Preserve the established multi-clip SFX/general path.
                        # Only the single-main-clip recovery path conforms tails.
                        if single_main_clip:
                            audio_out = f"[audio{slot}]"
                            audio_filter_parts.append(
                                f"{raw_label}apad,"
                                f"atrim=duration={target_duration:.6f}{audio_out}"
                            )
                            audio_mix_labels.append(audio_out)
                        else:
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
                audio_fg    = ""
                audio_map   = ["-map", audio_mix_labels[0].strip("[]")]
                audio_codec = ["-c:a", "aac", "-b:a", "192k"]
                shortest    = ["-shortest"]
            elif n == 1:
                audio_fg    = ";".join(audio_filter_parts)
                audio_map   = ["-map", audio_mix_labels[0]]
                audio_codec = ["-c:a", "aac", "-b:a", "192k"]
                shortest    = ["-shortest"]
            else:
                # 多路混音，或单路但有 BGM volume 中间滤镜（amix=inputs=1 合法）
                mix_in  = "".join(audio_mix_labels)
                amix_fg = (
                    f"{mix_in}"
                    f"amix=inputs={n}:duration=longest:dropout_transition=2"
                )
                if single_main_clip:
                    amix_fg += f",atrim=duration={target_duration:.6f}"
                amix_fg += "[outa]"
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

            final_timeout = self._render_timeout_seconds(
                master_duration or trusted_media_duration
            )
            self._log_media_stage(
                context,
                "FINAL_COMMAND_BUILT",
                role=lang,
                extra=f"timeout_seconds={final_timeout:.3f}",
            )

            self.log(f"[{lang}] Rendering variant → {final_path}")
            self.log(f"[{lang}] CMD: {' '.join(cmd)}")

            # ── 生命周期推送：变体渲染开始 ────────────────────────────────────
            self._ws_broadcast(task_id, user_id, {"status": "running", "progress": 0, "lang": lang})

            total_us: int = max(int(voice_target_duration * 1_000_000), 1)
            _last_ws_time: float = 0.0

            def _final_progress(raw_line: str) -> None:
                nonlocal _last_ws_time
                line = raw_line.strip()
                if not line.startswith("out_time_us="):
                    return
                try:
                    elapsed_us = int(line.split("=", 1)[1])
                except ValueError:
                    return
                now = time.monotonic()
                if now - _last_ws_time >= 1.0:
                    pct = min(int(elapsed_us * 100 / total_us), 99)
                    self._ws_broadcast(
                        task_id,
                        user_id,
                        {"status": "running", "progress": pct, "lang": lang},
                    )
                    _last_ws_time = now

            try:
                final_result = self._run_bounded_media_process(
                    cmd,
                    context=context,
                    process_kind="FINAL_FFMPEG",
                    timeout_seconds=final_timeout,
                    started_stage="FINAL_PROCESS_STARTED",
                    exited_stage="FINAL_PROCESS_EXITED",
                    on_stdout_line=_final_progress,
                )
                if final_result.returncode != 0:
                    raise _MediaProcessFailure(
                        "FINAL_FFMPEG_NONZERO_EXIT",
                        stage="FINAL_PROCESS_EXITED",
                        returncode=final_result.returncode,
                        stderr=final_result.stderr,
                    )

                self._validate_final_output(
                    final_path,
                    context=context,
                    require_audio=bool(audio_mix_labels),
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
            except _MediaProcessFailure as exc:
                error_msg = self._safe_stderr_excerpt(exc.stderr)
                self.log(
                    f"[{lang}] [ERROR] Variant render failed "
                    f"code={exc.code} returncode={exc.returncode} "
                    f"stderr={error_msg or 'NOT_AVAILABLE'}"
                )
                raise
