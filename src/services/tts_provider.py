"""TTS-only provider boundary for the packaged ElevenLabs RC2 path.

The adapter owns provider-specific HTTP, credential use, response parsing, and
attempt-private artifacts.  It never publishes authoritative execution files
or mutates WorkflowContext.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import math
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Literal, Mapping, Protocol

import httpx

from src.api.secret_store import ELEVENLABS_API_KEY, get_default_secret_store


DEFAULT_TTS_PROVIDER_ID = "elevenlabs"
ELEVENLABS_API_BASE = "https://api.elevenlabs.io"
ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"
ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"
CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 60.0
PER_ATTEMPT_TIMEOUT_SECONDS = 90.0
TOTAL_TTS_BUDGET_SECONDS = 180.0
MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (1.0, 2.0)
RETRY_AFTER_CAP_SECONDS = 30.0

# Owner-frozen RC2 provider policy.  These provider-specific IDs are neither
# persisted nor exposed as WorkflowContext/application settings.
ELEVENLABS_VOICE_MAP: Mapping[str, str] = MappingProxyType(
    {
        "en": "mUpJ8rmi5BCb93cmM4F5",  # DopaRC2_EN_Expressive_F
        "ar": "j88WSnqw1P5zuzXcvjSz",  # DopaRC2_AR_Saudi_M
    }
)

_SIGNED_PERCENT = re.compile(r"^[+-]\d+%$")
_VOICE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class TTSErrorCode(str, Enum):
    AUTH_ERROR = "TTS_AUTH_ERROR"
    CREDENTIAL_MISSING = "TTS_CREDENTIAL_MISSING"
    CONFIG_ERROR = "TTS_CONFIG_ERROR"
    INVALID_INPUT = "TTS_INVALID_INPUT"
    UNSUPPORTED_LANGUAGE = "TTS_UNSUPPORTED_LANGUAGE"
    UNSUPPORTED_VOICE = "TTS_UNSUPPORTED_VOICE"
    RATE_LIMITED = "TTS_RATE_LIMITED"
    TIMEOUT = "TTS_TIMEOUT"
    NETWORK_ERROR = "TTS_NETWORK_ERROR"
    PROVIDER_5XX = "TTS_PROVIDER_5XX"
    PROVIDER_REJECTED = "TTS_PROVIDER_REJECTED"
    ARTIFACT_INVALID = "TTS_ARTIFACT_INVALID"
    INTERNAL_ERROR = "TTS_INTERNAL_ERROR"


class TTSProviderError(RuntimeError):
    """Secret-safe provider-neutral failure."""

    def __init__(
        self,
        code: TTSErrorCode,
        *,
        retryable: bool,
        retry_after_seconds: float | None = None,
        safe_status: int | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.safe_status = safe_status


@dataclass(frozen=True)
class TTSProviderRequest:
    text: str
    language: str
    voice_id: str
    rate: str
    output_audio_path: Path
    output_timing_path: Path
    correlation_id: str


@dataclass(frozen=True)
class TTSProviderResult:
    audio_path: Path
    audio_format: Literal["mp3"]
    timing_path: Path | None
    provider_id: str
    safe_metadata: Mapping[str, str | int | float | bool]


class TTSProvider(Protocol):
    provider_id: str

    def resolve_voice_id(self, language: str) -> str: ...

    def synthesize(
        self,
        request: TTSProviderRequest,
        *,
        attempt_timeout_seconds: float,
    ) -> TTSProviderResult: ...


def parse_rate_to_speed(rate: str) -> float:
    """Map the existing signed integer-percent contract to provider speed."""
    if not isinstance(rate, str) or not _SIGNED_PERCENT.fullmatch(rate):
        raise TTSProviderError(TTSErrorCode.INVALID_INPUT, retryable=False)
    percent = int(rate[:-1])
    speed = 1.0 + percent / 100.0
    if not 0.7 <= speed <= 1.2:
        raise TTSProviderError(TTSErrorCode.INVALID_INPUT, retryable=False)
    return speed


def _format_vtt_timestamp(seconds: float) -> str:
    milliseconds = int(seconds * 1000.0 + 0.5)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def alignment_to_vtt(text: str, alignment: object) -> tuple[str, int]:
    """Normalize ElevenLabs original character alignment to deterministic VTT."""
    if not isinstance(alignment, dict):
        raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
    characters = alignment.get("characters")
    starts = alignment.get("character_start_times_seconds")
    ends = alignment.get("character_end_times_seconds")
    if not all(isinstance(item, list) for item in (characters, starts, ends)):
        raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
    if not characters or not (len(characters) == len(starts) == len(ends)):
        raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
    if any(
        not isinstance(character, str) or len(character) != 1
        for character in characters
    ):
        raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
    if "".join(characters) != text:
        raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)

    validated: list[tuple[str, float, float]] = []
    previous_start = -1.0
    previous_end = -1.0
    for character, start_value, end_value in zip(characters, starts, ends):
        if (
            isinstance(start_value, bool)
            or isinstance(end_value, bool)
            or not isinstance(start_value, (int, float))
            or not isinstance(end_value, (int, float))
        ):
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
        start = float(start_value)
        end = float(end_value)
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end < 0
            or start >= end
            or start < previous_start
            or end < previous_end
        ):
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
        validated.append((character, start, end))
        previous_start = start
        previous_end = end

    cues: list[tuple[str, float, float]] = []
    token_characters: list[str] = []
    token_start = 0.0
    token_end = 0.0
    for character, start, end in validated:
        if character.isspace():
            if token_characters:
                cues.append(("".join(token_characters), token_start, token_end))
                token_characters = []
            continue
        if not token_characters:
            token_start = start
        token_characters.append(character)
        token_end = end
    if token_characters:
        cues.append(("".join(token_characters), token_start, token_end))
    if not cues:
        raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)

    lines = ["WEBVTT", ""]
    previous_cue_start = -1.0
    for index, (cue_text, start, end) in enumerate(cues, start=1):
        if start < previous_cue_start or int(end * 1000 + 0.5) <= int(start * 1000 + 0.5):
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
        lines.extend(
            [
                str(index),
                f"{_format_vtt_timestamp(start)} --> {_format_vtt_timestamp(end)}",
                cue_text,
                "",
            ]
        )
        previous_cue_start = start
    return "\n".join(lines), len(cues)


def _bounded_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return min(value, RETRY_AFTER_CAP_SECONDS)


class ElevenLabsProvider:
    provider_id = DEFAULT_TTS_PROVIDER_ID

    def __init__(
        self,
        api_key: str,
        *,
        voice_map: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise TTSProviderError(TTSErrorCode.CREDENTIAL_MISSING, retryable=False)
        self.__api_key = api_key.strip()
        self._voice_map = dict(voice_map or ELEVENLABS_VOICE_MAP)
        self._transport = transport

    def resolve_voice_id(self, language: str) -> str:
        if language not in self._voice_map:
            raise TTSProviderError(TTSErrorCode.UNSUPPORTED_LANGUAGE, retryable=False)
        voice_id = self._voice_map[language]
        if not voice_id or not _VOICE_ID.fullmatch(voice_id):
            raise TTSProviderError(TTSErrorCode.UNSUPPORTED_VOICE, retryable=False)
        return voice_id

    def _map_http_error(self, response: httpx.Response) -> TTSProviderError:
        status = response.status_code
        if status == 401:
            return TTSProviderError(TTSErrorCode.AUTH_ERROR, retryable=False, safe_status=status)
        if status == 404:
            return TTSProviderError(
                TTSErrorCode.UNSUPPORTED_VOICE,
                retryable=False,
                safe_status=status,
            )
        if status in {400, 422}:
            return TTSProviderError(
                TTSErrorCode.INVALID_INPUT,
                retryable=False,
                safe_status=status,
            )
        if status == 429:
            return TTSProviderError(
                TTSErrorCode.RATE_LIMITED,
                retryable=True,
                retry_after_seconds=_bounded_retry_after(response),
                safe_status=status,
            )
        if status in {500, 502, 503, 504}:
            retry_after = _bounded_retry_after(response) if status == 503 else None
            return TTSProviderError(
                TTSErrorCode.PROVIDER_5XX,
                retryable=True,
                retry_after_seconds=retry_after,
                safe_status=status,
            )
        if 400 <= status < 600:
            return TTSProviderError(
                TTSErrorCode.PROVIDER_REJECTED,
                retryable=False,
                safe_status=status,
            )
        return TTSProviderError(TTSErrorCode.INTERNAL_ERROR, retryable=False)

    async def _request_and_write(self, request: TTSProviderRequest) -> TTSProviderResult:
        if not request.text or not request.text.strip():
            raise TTSProviderError(TTSErrorCode.INVALID_INPUT, retryable=False)
        if not _VOICE_ID.fullmatch(request.voice_id):
            raise TTSProviderError(TTSErrorCode.UNSUPPORTED_VOICE, retryable=False)
        speed = parse_rate_to_speed(request.rate)
        timeout = httpx.Timeout(
            connect=CONNECT_TIMEOUT_SECONDS,
            read=READ_TIMEOUT_SECONDS,
            write=None,
            pool=None,
        )
        url = (
            f"{ELEVENLABS_API_BASE}/v1/text-to-speech/"
            f"{request.voice_id}/with-timestamps"
        )
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                trust_env=False,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    url,
                    params={"output_format": ELEVENLABS_OUTPUT_FORMAT},
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "xi-api-key": self.__api_key,
                    },
                    json={
                        "text": request.text,
                        "model_id": ELEVENLABS_MODEL_ID,
                        "voice_settings": {"speed": speed},
                    },
                )
        except httpx.TimeoutException:
            raise TTSProviderError(TTSErrorCode.TIMEOUT, retryable=True) from None
        except httpx.RequestError:
            raise TTSProviderError(TTSErrorCode.NETWORK_ERROR, retryable=True) from None

        if response.status_code != 200:
            raise self._map_http_error(response)
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False) from None
        if not isinstance(payload, dict):
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
        encoded_audio = payload.get("audio_base64")
        if not isinstance(encoded_audio, str) or not encoded_audio:
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False)
        try:
            audio = base64.b64decode(encoded_audio, validate=True)
        except (binascii.Error, ValueError):
            raise TTSProviderError(TTSErrorCode.ARTIFACT_INVALID, retryable=False) from None
        vtt, cue_count = alignment_to_vtt(request.text, payload.get("alignment"))

        request.output_audio_path.parent.mkdir(parents=True, exist_ok=True)
        request.output_audio_path.write_bytes(audio)
        request.output_timing_path.write_text(vtt, encoding="utf-8", newline="\n")
        return TTSProviderResult(
            audio_path=request.output_audio_path,
            audio_format="mp3",
            timing_path=request.output_timing_path,
            provider_id=self.provider_id,
            safe_metadata=MappingProxyType(
                {
                    "audio_bytes": len(audio),
                    "cue_count": cue_count,
                    "timing_granularity": "character-grouped",
                    "model_id": ELEVENLABS_MODEL_ID,
                }
            ),
        )

    def synthesize(
        self,
        request: TTSProviderRequest,
        *,
        attempt_timeout_seconds: float,
    ) -> TTSProviderResult:
        if not math.isfinite(attempt_timeout_seconds) or attempt_timeout_seconds <= 0:
            raise TTSProviderError(TTSErrorCode.TIMEOUT, retryable=True)

        async def _bounded() -> TTSProviderResult:
            try:
                return await asyncio.wait_for(
                    self._request_and_write(request),
                    timeout=attempt_timeout_seconds,
                )
            except asyncio.TimeoutError:
                raise TTSProviderError(TTSErrorCode.TIMEOUT, retryable=True) from None

        try:
            return asyncio.run(_bounded())
        except TTSProviderError:
            raise
        except Exception:
            raise TTSProviderError(TTSErrorCode.INTERNAL_ERROR, retryable=False) from None


def create_tts_provider(
    provider_id: str = DEFAULT_TTS_PROVIDER_ID,
    *,
    api_key: str | None = None,
    voice_map: Mapping[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    secret_loader: Callable[[], str | None] | None = None,
) -> TTSProvider:
    """Create the single packaged provider and fail closed for all other IDs."""
    if provider_id != DEFAULT_TTS_PROVIDER_ID:
        raise TTSProviderError(TTSErrorCode.CONFIG_ERROR, retryable=False)
    if api_key is None:
        loader = secret_loader or (
            lambda: get_default_secret_store().get_secret(ELEVENLABS_API_KEY)
        )
        try:
            api_key = loader()
        except Exception:
            raise TTSProviderError(TTSErrorCode.CREDENTIAL_MISSING, retryable=False) from None
    if not api_key:
        raise TTSProviderError(TTSErrorCode.CREDENTIAL_MISSING, retryable=False)
    return ElevenLabsProvider(api_key, voice_map=voice_map, transport=transport)
