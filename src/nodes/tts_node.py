"""Provider-neutral TTS node with authoritative artifact publication.

External workflow contract remains:
``tts_script -> voice_audio + vtt_path``.  Provider-specific HTTP and
alignment parsing live below this node in ``src.services.tts_provider``.
"""

from __future__ import annotations

import math
import os
import random
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Protocol

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.services.tts_provider import (
    MAX_ATTEMPTS,
    PER_ATTEMPT_TIMEOUT_SECONDS,
    RETRY_AFTER_CAP_SECONDS,
    RETRY_DELAYS_SECONDS,
    TOTAL_TTS_BUDGET_SECONDS,
    TTSErrorCode,
    TTSProvider,
    TTSProviderError,
    TTSProviderRequest,
    TTSProviderResult,
    create_tts_provider,
)


TTS_PROVIDER_MAX_IN_FLIGHT = 1
RATE_LIMIT_JITTER_RATIO = 0.25
_ELEVENLABS_PROVIDER_GATE = threading.BoundedSemaphore(TTS_PROVIDER_MAX_IN_FLIGHT)
_SAFE_LOG_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class _ProviderAdmissionGate(Protocol):
    def acquire(self, *, timeout: float) -> bool: ...

    def release(self) -> None: ...


_VTT_TIMING = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3}) --> "
    r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})$"
)


def _resolve_execution_namespace(context: WorkflowContext) -> str:
    """Return the authoritative child namespace, with legacy direct fallback."""
    execution_id = context.config.get("execution_id")
    if execution_id:
        return str(execution_id)
    if "child_index" in context.config or "file_sid" in context.config:
        raise RuntimeError("[TTSNode] child context is missing execution_id")
    return str(getattr(context, "task_id", None) or "default")


def _timestamp_milliseconds(match: re.Match[str], offset: int) -> int:
    hours, minutes, seconds, milliseconds = (
        int(match.group(offset + index)) for index in range(4)
    )
    if minutes >= 60 or seconds >= 60:
        raise ValueError("invalid timestamp")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


class TTSNode(BaseNode):
    """Generate one authoritative MP3/VTT pair for the target language."""

    def __init__(
        self,
        name: str = "TTSNode",
        output_dir: str = "output",
        *,
        provider: TTSProvider | None = None,
        provider_factory: Callable[[], TTSProvider] = create_tts_provider,
        rate: str = "+0%",
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        attempt_token_factory: Callable[[], str] | None = None,
        provider_gate: _ProviderAdmissionGate | None = None,
        jitter_source: Callable[[], float] = random.random,
    ) -> None:
        super().__init__(name)
        self._output_dir = Path(output_dir)
        self._provider = provider
        self._provider_factory = provider_factory
        self._rate = rate
        self._clock = clock
        self._sleeper = sleeper
        self._attempt_token_factory = attempt_token_factory or (
            lambda: uuid.uuid4().hex
        )
        self._provider_gate = (
            provider_gate if provider_gate is not None else _ELEVENLABS_PROVIDER_GATE
        )
        self._jitter_source = jitter_source

    def _active_provider(self) -> TTSProvider:
        if self._provider is None:
            self._provider = self._provider_factory()
        return self._provider

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Cleanup is best effort here; the terminal error remains sanitized.
            pass

    @staticmethod
    def _validate_audio(path: Path) -> None:
        if not path.is_file():
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
        size = path.stat().st_size
        if size < 1024:
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
        with path.open("rb") as handle:
            signature = handle.read(3)
        is_id3 = signature == b"ID3"
        is_mpeg_frame = (
            len(signature) >= 2
            and signature[0] == 0xFF
            and signature[1] & 0xE0 == 0xE0
        )
        if not is_id3 and not is_mpeg_frame:
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)

    @staticmethod
    def _validate_vtt(path: Path) -> None:
        if not path.is_file() or path.stat().st_size == 0:
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False) from None
        if not lines or lines[0] != "WEBVTT":
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
        cue_count = 0
        previous_start = -1
        for line in lines[1:]:
            match = _VTT_TIMING.fullmatch(line)
            if match is None:
                continue
            try:
                start = _timestamp_milliseconds(match, 1)
                end = _timestamp_milliseconds(match, 5)
            except ValueError:
                raise TTSProviderError(
                    TTSErrorCode.ARTIFACT_INVALID,
                    retryable=False,
                ) from None
            if start < previous_start or end <= start:
                raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
            previous_start = start
            cue_count += 1
        if cue_count == 0:
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)

    @staticmethod
    def _validate_result(
        result: TTSProviderResult,
        expected_audio: Path,
        expected_timing: Path,
    ) -> None:
        if (
            result.provider_id != "elevenlabs"
            or result.audio_format != "mp3"
            or result.audio_path != expected_audio
            or result.timing_path != expected_timing
        ):
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
        TTSNode._validate_audio(expected_audio)
        TTSNode._validate_vtt(expected_timing)

    @staticmethod
    def _publish_pair(
        temporary_audio: Path,
        temporary_timing: Path,
        final_audio: Path,
        final_timing: Path,
    ) -> None:
        existed_before = {
            final_audio: final_audio.exists(),
            final_timing: final_timing.exists(),
        }
        if any(existed_before.values()):
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
        published: list[Path] = []
        try:
            os.replace(temporary_audio, final_audio)
            published.append(final_audio)
            os.replace(temporary_timing, final_timing)
            published.append(final_timing)
        except OSError:
            for path in reversed(published):
                if not existed_before[path]:
                    TTSNode._safe_unlink(path)
            raise TTSProviderError(TTSErrorCode.INTERNAL_ERROR, retryable=False) from None

    def _attempt_paths(
        self,
        execution_id: str,
        language: str,
        attempt: int,
    ) -> tuple[Path, Path]:
        token = self._attempt_token_factory()
        prefix = f".voice_{execution_id}_{language}.attempt-{attempt}-{token}"
        return (
            self._output_dir / f"{prefix}.mp3.part",
            self._output_dir / f"{prefix}.vtt.part",
        )

    def _retry_delay(self, attempt: int, error: TTSProviderError) -> float:
        base_delay = (
            error.retry_after_seconds
            if error.retry_after_seconds is not None
            else RETRY_DELAYS_SECONDS[attempt - 1]
        )
        base_delay = max(0.0, min(float(base_delay), RETRY_AFTER_CAP_SECONDS))
        if error.code not in {
            TTSErrorCode.RATE_LIMITED,
            TTSErrorCode.CONCURRENCY_LIMITED,
        }:
            return base_delay
        try:
            jitter_fraction = float(self._jitter_source())
        except (TypeError, ValueError, OverflowError):
            jitter_fraction = 0.0
        if not math.isfinite(jitter_fraction):
            jitter_fraction = 0.0
        jitter_fraction = min(max(jitter_fraction, 0.0), 1.0)
        jitter = min(
            base_delay * RATE_LIMIT_JITTER_RATIO * jitter_fraction,
            RETRY_AFTER_CAP_SECONDS - base_delay,
        )
        return base_delay + jitter

    @staticmethod
    def _safe_error_diagnostics(error: TTSProviderError) -> str:
        diagnostics: list[str] = []
        if (
            isinstance(error.safe_status, int)
            and not isinstance(error.safe_status, bool)
            and 100 <= error.safe_status <= 599
        ):
            diagnostics.append(f"http_status={error.safe_status}")
        for label, value in (
            ("provider_type", error.provider_error_type),
            ("provider_code", error.provider_error_code),
            ("provider_legacy_status", error.provider_legacy_status),
            ("provider_request_id", error.provider_request_id),
        ):
            if isinstance(value, str) and _SAFE_LOG_TOKEN.fullmatch(value):
                diagnostics.append(f"{label}={value}")
        return "" if not diagnostics else " " + " ".join(diagnostics)

    def _synthesize_with_admission(
        self,
        provider: TTSProvider,
        request: TTSProviderRequest,
        *,
        started_at: float,
    ) -> TTSProviderResult:
        remaining = TOTAL_TTS_BUDGET_SECONDS - (self._clock() - started_at)
        if not math.isfinite(remaining) or remaining <= 0:
            raise TTSProviderError(TTSErrorCode.TIMEOUT, retryable=False)

        acquired = False
        try:
            acquired = self._provider_gate.acquire(timeout=remaining)
            if not acquired:
                raise TTSProviderError(TTSErrorCode.TIMEOUT, retryable=False)
            remaining = TOTAL_TTS_BUDGET_SECONDS - (self._clock() - started_at)
            if not math.isfinite(remaining) or remaining <= 0:
                raise TTSProviderError(TTSErrorCode.TIMEOUT, retryable=False)
            return provider.synthesize(
                request,
                attempt_timeout_seconds=min(PER_ATTEMPT_TIMEOUT_SECONDS, remaining),
            )
        finally:
            if acquired:
                self._provider_gate.release()

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        tts_script: dict = context.get_asset("tts_script") or {}
        if not tts_script:
            self.log("Warning: context.assets['tts_script'] is empty, skipping.")
            return context

        target_language = getattr(context, "test_language", "en") or "en"
        if target_language not in {"en", "ar"}:
            raise RuntimeError(
                "[TTSNode] TTS audio generation failed after 0 attempt(s); "
                "code=TTS_UNSUPPORTED_LANGUAGE; provider=elevenlabs"
            )
        if target_language not in tts_script:
            target_language = next(
                (language for language in tts_script if language in {"en", "ar"}),
                target_language,
            )
        if target_language not in tts_script:
            raise RuntimeError(
                "[TTSNode] TTS audio generation failed after 0 attempt(s); "
                "code=TTS_UNSUPPORTED_LANGUAGE; provider=elevenlabs"
            )
        text = str(tts_script[target_language]).strip()
        if not text:
            self.log(f"Warning: tts_script['{target_language}'] is empty, skipping.")
            return context

        execution_id = _resolve_execution_namespace(context)
        final_audio = self._output_dir / f"voice_{execution_id}_{target_language}.mp3"
        final_timing = self._output_dir / f"voice_{execution_id}_{target_language}.vtt"
        self._output_dir.mkdir(parents=True, exist_ok=True)

        provider: TTSProvider | None = None
        attempts_started = 0
        last_error = TTSProviderError(TTSErrorCode.INTERNAL_ERROR, retryable=False)
        started_at = self._clock()

        try:
            provider = self._active_provider()
            voice_id = provider.resolve_voice_id(target_language)
        except TTSProviderError as error:
            last_error = error
            provider_id = getattr(provider, "provider_id", "elevenlabs")
            raise RuntimeError(
                "[TTSNode] TTS audio generation failed after 0 attempt(s); "
                f"code={error.code.value}; provider={provider_id}"
            ) from None
        except Exception:
            raise RuntimeError(
                "[TTSNode] TTS audio generation failed after 0 attempt(s); "
                "code=TTS_INTERNAL_ERROR; provider=elevenlabs"
            ) from None

        provider_id = provider.provider_id
        self.log(
            f"[TTSNode] provider={provider_id} language={target_language} "
            f"execution_id={execution_id} text_length={len(text)}"
        )

        for attempt in range(1, MAX_ATTEMPTS + 1):
            elapsed = self._clock() - started_at
            remaining = TOTAL_TTS_BUDGET_SECONDS - elapsed
            if not math.isfinite(remaining) or remaining <= 0:
                last_error = TTSProviderError(TTSErrorCode.TIMEOUT, retryable=False)
                break
            temporary_audio, temporary_timing = self._attempt_paths(
                execution_id,
                target_language,
                attempt,
            )
            request = TTSProviderRequest(
                text=text,
                language=target_language,
                voice_id=voice_id,
                rate=self._rate,
                output_audio_path=temporary_audio,
                output_timing_path=temporary_timing,
                correlation_id=execution_id,
            )
            attempts_started += 1
            try:
                result = self._synthesize_with_admission(
                    provider,
                    request,
                    started_at=started_at,
                )
                self._validate_result(result, temporary_audio, temporary_timing)
                published_audio_bytes = temporary_audio.stat().st_size
                self._publish_pair(
                    temporary_audio,
                    temporary_timing,
                    final_audio,
                    final_timing,
                )
            except TTSProviderError as error:
                last_error = error
                self._safe_unlink(temporary_audio)
                self._safe_unlink(temporary_timing)
                self.log(
                    f"[TTSNode] provider={provider_id} language={target_language} "
                    f"attempt={attempt} code={error.code.value}"
                    f"{self._safe_error_diagnostics(error)}"
                )
                if not error.retryable or attempt >= MAX_ATTEMPTS:
                    break
                delay = self._retry_delay(attempt, error)
                remaining_after_attempt = (
                    TOTAL_TTS_BUDGET_SECONDS - (self._clock() - started_at)
                )
                if delay >= remaining_after_attempt:
                    last_error = TTSProviderError(TTSErrorCode.TIMEOUT, retryable=False)
                    break
                self._sleeper(delay)
                continue
            except Exception:
                last_error = TTSProviderError(TTSErrorCode.INTERNAL_ERROR, retryable=False)
                self._safe_unlink(temporary_audio)
                self._safe_unlink(temporary_timing)
                break

            context.variants.setdefault(target_language, {}).update(
                {
                    "voice_audio": str(final_audio),
                    "vtt_path": str(final_timing),
                }
            )
            self.log(
                f"[TTSNode] provider={provider_id} language={target_language} "
                f"attempt={attempt} audio_bytes={published_audio_bytes} published=YES"
            )
            return context

        raise RuntimeError(
            "[TTSNode] TTS audio generation failed after "
            f"{attempts_started} attempt(s); code={last_error.code.value}; "
            f"provider={provider_id}"
        ) from None
