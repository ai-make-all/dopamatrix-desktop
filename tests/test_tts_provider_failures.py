from __future__ import annotations

import asyncio
import base64
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from src.core.context import WorkflowContext
from src.nodes.tts_node import TTSNode
from src.services.tts_provider import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_ATTEMPTS,
    MAX_SAFE_ERROR_BODY_BYTES,
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


def _context(
    text: str = "Hello",
    *,
    execution_id: str = "11111111-1111-4111-8111-111111111111",
) -> WorkflowContext:
    context = WorkflowContext(task_id="test-task", test_language="en")
    context.config["execution_id"] = execution_id
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
            jitter_source=lambda: 0.0,
        ), recorded_sleeps

    def _mapped_error(
        self,
        status: int,
        *,
        payload: object | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> TTSProviderError:
        def handler(_request):
            if content is not None:
                return httpx.Response(status, content=content, headers=headers)
            return httpx.Response(status, json=payload, headers=headers)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = ElevenLabsProvider(
                "synthetic-never-log",
                voice_map={"en": "fake_en"},
                transport=httpx.MockTransport(handler),
            )
            request = TTSProviderRequest(
                text="Hello",
                language="en",
                voice_id="fake_en",
                rate="+0%",
                output_audio_path=root / "a.part",
                output_timing_path=root / "t.part",
                correlation_id="synthetic-correlation",
            )
            with self.assertRaises(TTSProviderError) as raised:
                provider.synthesize(request, attempt_timeout_seconds=5)
        return raised.exception

    def test_frozen_timeout_and_attempt_constants(self) -> None:
        self.assertEqual(CONNECT_TIMEOUT_SECONDS, 10)
        self.assertEqual(READ_TIMEOUT_SECONDS, 60)
        self.assertEqual(PER_ATTEMPT_TIMEOUT_SECONDS, 90)
        self.assertEqual(TOTAL_TTS_BUDGET_SECONDS, 180)
        self.assertEqual(MAX_ATTEMPTS, 3)
        self.assertEqual(RETRY_AFTER_CAP_SECONDS, 30)

    def test_http_auth_payment_authorization_and_concurrency_are_distinct(self) -> None:
        cases = (
            (
                401,
                TTSErrorCode.AUTH_ERROR,
                {"type": "authentication_error", "code": "invalid_api_key"},
            ),
            (
                402,
                TTSErrorCode.PAYMENT_REQUIRED,
                {"type": "payment_required", "code": "insufficient_credits"},
            ),
            (
                403,
                TTSErrorCode.AUTHORIZATION_ERROR,
                {"type": "authorization_error", "code": "forbidden"},
            ),
            (
                429,
                TTSErrorCode.CONCURRENCY_LIMITED,
                {"type": "rate_limit_error", "code": "concurrent_limit_exceeded"},
            ),
            (
                429,
                TTSErrorCode.RATE_LIMITED,
                {"type": "rate_limit_error", "code": "rate_limit_exceeded"},
            ),
        )
        for status, expected_code, detail in cases:
            error = self._mapped_error(status, payload={"detail": detail})
            with self.subTest(status=status, expected_code=expected_code):
                self.assertEqual(error.code, expected_code)
                self.assertEqual(error.safe_status, status)
                self.assertEqual(error.provider_error_type, detail["type"])
                self.assertEqual(error.provider_error_code, detail["code"])
                self.assertEqual(error.retryable, status == 429)

    def test_safe_provider_diagnostics_are_bounded_allowlisted_and_secret_free(self) -> None:
        sentinel = "SYNTHETIC_SECRET_MUST_NOT_APPEAR"
        error = self._mapped_error(
            401,
            payload={
                "detail": {
                    "type": "authentication_error",
                    "code": "invalid_api_key",
                    "status": "invalid_api_key",
                    "request_id": "req_safe-123",
                    "message": sentinel,
                    "api_key": sentinel,
                    "unknown": sentinel,
                }
            },
        )
        self.assertEqual(error.safe_status, 401)
        self.assertEqual(error.provider_error_type, "authentication_error")
        self.assertEqual(error.provider_error_code, "invalid_api_key")
        self.assertEqual(error.provider_legacy_status, "invalid_api_key")
        self.assertEqual(error.provider_request_id, "req_safe-123")
        self.assertNotIn(sentinel, repr(error))
        self.assertNotIn(sentinel, str(error))

        unsafe = self._mapped_error(
            401,
            payload={
                "detail": {
                    "type": "not_allowlisted",
                    "code": "not_allowlisted",
                    "status": "not_allowlisted",
                    "request_id": "bad request id with spaces",
                    "message": sentinel,
                }
            },
        )
        self.assertIsNone(unsafe.provider_error_type)
        self.assertIsNone(unsafe.provider_error_code)
        self.assertIsNone(unsafe.provider_legacy_status)
        self.assertIsNone(unsafe.provider_request_id)

        oversized = self._mapped_error(
            401,
            content=b"x" * (MAX_SAFE_ERROR_BODY_BYTES + 1),
        )
        self.assertEqual(oversized.safe_status, 401)
        self.assertIsNone(oversized.provider_error_type)
        self.assertIsNone(oversized.provider_error_code)
        self.assertIsNone(oversized.provider_request_id)

    def test_tts_log_contains_only_safe_provider_diagnostics(self) -> None:
        sentinel = "SYNTHETIC_SECRET_MUST_NOT_APPEAR"

        def handler(_request):
            return httpx.Response(
                401,
                json={
                    "detail": {
                        "type": "authentication_error",
                        "code": "invalid_api_key",
                        "status": "invalid_api_key",
                        "request_id": "req_safe-456",
                        "message": sentinel,
                    }
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            node, _ = self._node_with_transport(directory, handler)
            node.log = Mock()
            with self.assertRaises(RuntimeError):
                node.execute(_context(sentinel))
            output = "\n".join(str(call.args[0]) for call in node.log.call_args_list)
        self.assertIn("http_status=401", output)
        self.assertIn("provider_type=authentication_error", output)
        self.assertIn("provider_code=invalid_api_key", output)
        self.assertIn("provider_legacy_status=invalid_api_key", output)
        self.assertIn("provider_request_id=req_safe-456", output)
        self.assertNotIn(sentinel, output)

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

    def test_429_backoff_has_bounded_jitter_without_changing_attempt_limit(self) -> None:
        calls = 0

        def handler(_request):
            nonlocal calls
            calls += 1
            return httpx.Response(
                429,
                json={
                    "detail": {
                        "type": "rate_limit_error",
                        "code": "concurrent_limit_exceeded",
                    }
                },
            )

        sleeps: list[float] = []
        with tempfile.TemporaryDirectory() as directory:
            provider = ElevenLabsProvider(
                "synthetic-never-log",
                voice_map={"en": "fake_en"},
                transport=httpx.MockTransport(handler),
            )
            node = TTSNode(
                output_dir=directory,
                provider=provider,
                sleeper=sleeps.append,
                attempt_token_factory=lambda: "fixed",
                jitter_source=lambda: 1.0,
            )
            with self.assertRaises(RuntimeError) as raised:
                node.execute(_context())
        self.assertEqual(calls, 3)
        self.assertEqual(sleeps, [1.25, 2.5])
        self.assertIn(TTSErrorCode.CONCURRENCY_LIMITED.value, str(raised.exception))

    def test_batch_one_preserves_single_call_and_execution_identity(self) -> None:
        provider = _FakeProvider(["success"])
        execution_id = "99999999-9999-4999-8999-999999999999"
        with tempfile.TemporaryDirectory() as directory:
            node = TTSNode(
                output_dir=directory,
                provider=provider,
                attempt_token_factory=lambda: "fixed",
            )
            context = node.execute(_context(execution_id=execution_id))
        output = str(context.variants["en"]["voice_audio"])
        self.assertEqual(provider.calls, 1)
        self.assertIn(execution_id, output)

    def test_batch_two_and_four_share_one_provider_admission_slot(self) -> None:
        class Tracker:
            def __init__(self) -> None:
                self.lock = threading.Lock()
                self.active = 0
                self.maximum = 0
                self.calls = 0

        class TrackingProvider(_FakeProvider):
            def __init__(self, tracker: Tracker) -> None:
                super().__init__(["success"])
                self.tracker = tracker

            def synthesize(self, request, *, attempt_timeout_seconds):
                with self.tracker.lock:
                    self.tracker.active += 1
                    self.tracker.calls += 1
                    self.tracker.maximum = max(
                        self.tracker.maximum,
                        self.tracker.active,
                    )
                try:
                    time.sleep(0.02)
                    return super().synthesize(
                        request,
                        attempt_timeout_seconds=attempt_timeout_seconds,
                    )
                finally:
                    with self.tracker.lock:
                        self.tracker.active -= 1

        for batch_size in (2, 4):
            tracker = Tracker()
            with self.subTest(batch_size=batch_size), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)

                def execute_child(child_index: int) -> str:
                    execution_id = f"00000000-0000-4000-8000-{child_index:012d}"
                    node = TTSNode(
                        output_dir=str(root / str(child_index)),
                        provider=TrackingProvider(tracker),
                        attempt_token_factory=lambda: "fixed",
                    )
                    context = node.execute(
                        _context(execution_id=execution_id),
                    )
                    return str(context.variants["en"]["voice_audio"])

                with ThreadPoolExecutor(max_workers=batch_size) as pool:
                    outputs = list(pool.map(execute_child, range(batch_size)))
            self.assertEqual(tracker.calls, batch_size)
            self.assertEqual(tracker.maximum, 1)
            self.assertEqual(len(set(outputs)), batch_size)
            for child_index, output in enumerate(outputs):
                self.assertIn(f"{child_index:012d}", output)

    def test_provider_admission_timeout_fails_without_call_or_leak(self) -> None:
        class RefusingGate:
            def __init__(self) -> None:
                self.timeouts: list[float] = []
                self.releases = 0

            def acquire(self, *, timeout: float) -> bool:
                self.timeouts.append(timeout)
                return False

            def release(self) -> None:
                self.releases += 1

        provider = _FakeProvider(["success"])
        gate = RefusingGate()
        with tempfile.TemporaryDirectory() as directory:
            node = TTSNode(
                output_dir=directory,
                provider=provider,
                provider_gate=gate,
                clock=lambda: 0.0,
                attempt_token_factory=lambda: "fixed",
            )
            with self.assertRaises(RuntimeError) as raised:
                node.execute(_context())
        self.assertEqual(provider.calls, 0)
        self.assertEqual(gate.timeouts, [TOTAL_TTS_BUDGET_SECONDS])
        self.assertEqual(gate.releases, 0)
        self.assertIn(TTSErrorCode.TIMEOUT.value, str(raised.exception))

    def test_provider_failure_releases_admission_slot_for_next_child(self) -> None:
        gate = threading.BoundedSemaphore(1)
        failed_provider = _FakeProvider(
            [TTSProviderError(TTSErrorCode.AUTH_ERROR, retryable=False)],
        )
        successful_provider = _FakeProvider(["success"])
        with tempfile.TemporaryDirectory() as directory:
            failed_node = TTSNode(
                output_dir=str(Path(directory) / "failed"),
                provider=failed_provider,
                provider_gate=gate,
                attempt_token_factory=lambda: "fixed",
            )
            with self.assertRaises(RuntimeError):
                failed_node.execute(_context())

            successful_node = TTSNode(
                output_dir=str(Path(directory) / "successful"),
                provider=successful_provider,
                provider_gate=gate,
                attempt_token_factory=lambda: "fixed",
            )
            successful_node.execute(
                _context(execution_id="88888888-8888-4888-8888-888888888888"),
            )
        self.assertEqual(failed_provider.calls, 1)
        self.assertEqual(successful_provider.calls, 1)

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
