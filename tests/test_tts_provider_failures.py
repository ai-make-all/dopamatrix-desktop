from __future__ import annotations

import asyncio
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from src.core.context import WorkflowContext
from src.nodes.tts_node import TTSNode
from src.services.tts_provider import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_ATTEMPTS,
    PER_ATTEMPT_TIMEOUT_SECONDS,
    READ_TIMEOUT_SECONDS,
    RETRY_AFTER_CAP_SECONDS,
    TOTAL_TTS_BUDGET_SECONDS,
    ElevenLabsProvider,
    TTSErrorCode,
    TTSProviderError,
    TTSProviderRequest,
    TTSProviderResult,
)


def _alignment(text: str) -> dict[str, list]:
    return {
        "characters": list(text),
        "character_start_times_seconds": [index / 10 for index in range(len(text))],
        "character_end_times_seconds": [(index + 1) / 10 for index in range(len(text))],
    }


def _success_payload(text: str) -> dict:
    return {
        "audio_base64": base64.b64encode(b"ID3" + b"a" * 1021).decode(),
        "alignment": _alignment(text),
    }


def _context(text: str = "Hello") -> WorkflowContext:
    context = WorkflowContext(task_id="test-task", test_language="en")
    context.config["execution_id"] = "11111111-1111-4111-8111-111111111111"
    context.set_asset("tts_script", {"en": text})
    return context


class _FakeProvider:
    provider_id = "elevenlabs"

    def __init__(self, outcomes, *, clock_advance=None):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.timeouts: list[float] = []
        self.clock_advance = clock_advance

    def resolve_voice_id(self, language: str) -> str:
        return f"fake_{language}"

    def synthesize(self, request, *, attempt_timeout_seconds):
        self.calls += 1
        self.timeouts.append(attempt_timeout_seconds)
        if self.clock_advance is not None:
            self.clock_advance(attempt_timeout_seconds)
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        request.output_audio_path.write_bytes(b"ID3" + b"a" * 1021)
        request.output_timing_path.write_text(
            "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nHello\n",
            encoding="utf-8",
        )
        return TTSProviderResult(
            audio_path=request.output_audio_path,
            audio_format="mp3",
            timing_path=request.output_timing_path,
            provider_id="elevenlabs",
            safe_metadata={},
        )


class TTSProviderFailureTests(unittest.TestCase):
    def _node_with_transport(self, directory: str, handler, sleeps=None) -> tuple[TTSNode, list]:
        recorded_sleeps = sleeps if sleeps is not None else []
        provider = ElevenLabsProvider(
            "synthetic-never-log",
            voice_map={"en": "fake_en"},
            transport=httpx.MockTransport(handler),
        )
        return TTSNode(
            output_dir=directory,
            provider=provider,
            sleeper=recorded_sleeps.append,
            attempt_token_factory=lambda: "fixed",
        ), recorded_sleeps

    def test_frozen_timeout_and_attempt_constants(self) -> None:
        self.assertEqual(CONNECT_TIMEOUT_SECONDS, 10)
        self.assertEqual(READ_TIMEOUT_SECONDS, 60)
        self.assertEqual(PER_ATTEMPT_TIMEOUT_SECONDS, 90)
        self.assertEqual(TOTAL_TTS_BUDGET_SECONDS, 180)
        self.assertEqual(MAX_ATTEMPTS, 3)
        self.assertEqual(RETRY_AFTER_CAP_SECONDS, 30)

    def test_nonretryable_http_statuses_make_one_attempt(self) -> None:
        for status in (400, 401, 402, 403, 404, 409, 422, 501):
            calls = 0

            def handler(_request, response_status=status):
                nonlocal calls
                calls += 1
                return httpx.Response(response_status, json={"detail": "must-not-leak"})

            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                node, sleeps = self._node_with_transport(directory, handler)
                with self.assertRaises(RuntimeError):
                    node.execute(_context())
                self.assertEqual(calls, 1)
                self.assertEqual(sleeps, [])

    def test_transient_statuses_retry_exactly_three_times(self) -> None:
        for status in (429, 500, 502, 503, 504):
            calls = 0

            def handler(_request, response_status=status):
                nonlocal calls
                calls += 1
                return httpx.Response(response_status)

            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                node, sleeps = self._node_with_transport(directory, handler)
                with self.assertRaises(RuntimeError):
                    node.execute(_context())
                self.assertEqual(calls, 3)
                self.assertEqual(sleeps, [1.0, 2.0])

    def test_retry_after_is_only_honored_for_429_and_503_and_capped(self) -> None:
        for status, expected in ((429, 30.0), (503, 30.0), (500, 1.0)):
            calls = 0

            def handler(_request, response_status=status):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return httpx.Response(response_status, headers={"Retry-After": "300"})
                return httpx.Response(200, json=_success_payload("Hello"))

            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                node, sleeps = self._node_with_transport(directory, handler)
                node.execute(_context())
                self.assertEqual(calls, 2)
                self.assertEqual(sleeps, [expected])

    def test_network_error_retries_and_never_leaks_exception_detail(self) -> None:
        calls = 0

        def handler(request):
            nonlocal calls
            calls += 1
            raise httpx.ConnectError("synthetic-sensitive-detail", request=request)

        with tempfile.TemporaryDirectory() as directory:
            node, _ = self._node_with_transport(directory, handler)
            with self.assertRaises(RuntimeError) as raised:
                node.execute(_context("customer script"))
        self.assertEqual(calls, 3)
        self.assertIn(TTSErrorCode.NETWORK_ERROR.value, str(raised.exception))
        self.assertNotIn("synthetic-sensitive-detail", str(raised.exception))
        self.assertNotIn("customer script", str(raised.exception))

    def test_timeout_error_retries_three_times_when_budget_remains(self) -> None:
        provider = _FakeProvider(
            [TTSProviderError(TTSErrorCode.TIMEOUT, retryable=True)],
        )
        sleeps: list[float] = []
        with tempfile.TemporaryDirectory() as directory:
            node = TTSNode(
                output_dir=directory,
                provider=provider,
                sleeper=sleeps.append,
                attempt_token_factory=lambda: "fixed",
            )
            with self.assertRaises(RuntimeError):
                node.execute(_context())
        self.assertEqual(provider.calls, 3)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_decoded_small_or_invalid_mp3_is_nonretryable_and_cleaned(self) -> None:
        for audio in (b"tiny", b"x" * 1024):
            calls = 0

            def handler(_request, current=audio):
                nonlocal calls
                calls += 1
                payload = _success_payload("Hello")
                payload["audio_base64"] = base64.b64encode(current).decode()
                return httpx.Response(200, json=payload)

            with self.subTest(audio_size=len(audio)), tempfile.TemporaryDirectory() as directory:
                node, _ = self._node_with_transport(directory, handler)
                with self.assertRaises(RuntimeError) as raised:
                    node.execute(_context())
                self.assertEqual(calls, 1)
                self.assertIn(TTSErrorCode.ARTIFACT_INVALID.value, str(raised.exception))
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_invalid_json_base64_and_alignment_make_one_attempt(self) -> None:
        payloads = [
            None,
            {"audio_base64": "!!!", "alignment": _alignment("Hello")},
            {
                "audio_base64": base64.b64encode(b"ID3" + b"a" * 1021).decode(),
                "alignment": {**_alignment("Hello"), "characters": list("Hxllo")},
            },
        ]
        for payload in payloads:
            calls = 0

            def handler(_request, current=payload):
                nonlocal calls
                calls += 1
                if current is None:
                    return httpx.Response(200, content=b"not-json")
                return httpx.Response(200, json=current)

            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                node, _ = self._node_with_transport(directory, handler)
                with self.assertRaises(RuntimeError) as raised:
                    node.execute(_context())
                self.assertEqual(calls, 1)
                self.assertIn(TTSErrorCode.ARTIFACT_INVALID.value, str(raised.exception))
                self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_outer_attempt_deadline_is_real_and_distinct_from_http_read_timeout(self) -> None:
        async def slow_handler(_request):
            await asyncio.sleep(0.05)
            return httpx.Response(200, json=_success_payload("Hello"))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = ElevenLabsProvider(
                "synthetic",
                voice_map={"en": "fake_en"},
                transport=httpx.MockTransport(slow_handler),
            )
            request = TTSProviderRequest(
                text="Hello",
                language="en",
                voice_id="fake_en",
                rate="+0%",
                output_audio_path=root / "a.part",
                output_timing_path=root / "t.part",
                correlation_id="c",
            )
            with self.assertRaises(TTSProviderError) as raised:
                provider.synthesize(request, attempt_timeout_seconds=0.001)
        self.assertEqual(raised.exception.code, TTSErrorCode.TIMEOUT)
        self.assertTrue(raised.exception.retryable)

    def test_total_budget_prevents_an_unsafe_third_attempt(self) -> None:
        now = [0.0]
        provider = _FakeProvider(
            [TTSProviderError(TTSErrorCode.TIMEOUT, retryable=True)],
            clock_advance=lambda seconds: now.__setitem__(0, now[0] + seconds),
        )

        def sleep(seconds):
            now[0] += seconds

        with tempfile.TemporaryDirectory() as directory:
            node = TTSNode(
                output_dir=directory,
                provider=provider,
                clock=lambda: now[0],
                sleeper=sleep,
                attempt_token_factory=lambda: "fixed",
            )
            with self.assertRaises(RuntimeError) as raised:
                node.execute(_context())
        self.assertEqual(provider.calls, 2)
        self.assertEqual(provider.timeouts, [90.0, 89.0])
        self.assertIn(TTSErrorCode.TIMEOUT.value, str(raised.exception))

    def test_partial_two_artifact_publish_compensates_without_context_mutation(self) -> None:
        provider = _FakeProvider(["success"])
        context = _context()
        original_replace = __import__("os").replace
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("deterministic second publication failure")
            return original_replace(source, destination)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            node = TTSNode(
                output_dir=directory,
                provider=provider,
                attempt_token_factory=lambda: "fixed",
            )
            with patch("src.nodes.tts_node.os.replace", side_effect=fail_second):
                with self.assertRaises(RuntimeError):
                    node.execute(context)
            self.assertEqual(context.variants, {})
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
