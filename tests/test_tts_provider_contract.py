from __future__ import annotations

import base64
import json
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

import httpx

from src.services import tts_provider as module
from src.services.tts_provider import (
    ELEVENLABS_MODEL_ID,
    ELEVENLABS_OUTPUT_FORMAT,
    ElevenLabsProvider,
    TTSProviderRequest,
    TTSProviderResult,
)


def _alignment(text: str) -> dict[str, list]:
    return {
        "characters": list(text),
        "character_start_times_seconds": [index / 10 for index in range(len(text))],
        "character_end_times_seconds": [(index + 1) / 10 for index in range(len(text))],
    }


class TTSProviderContractTests(unittest.TestCase):
    def test_request_and_result_contracts_exclude_runtime_and_secret_authority(self) -> None:
        self.assertEqual(
            [item.name for item in fields(TTSProviderRequest)],
            [
                "text",
                "language",
                "voice_id",
                "rate",
                "output_audio_path",
                "output_timing_path",
                "correlation_id",
            ],
        )
        self.assertEqual(
            [item.name for item in fields(TTSProviderResult)],
            ["audio_path", "audio_format", "timing_path", "provider_id", "safe_metadata"],
        )
        forbidden = {
            "context", "tenant", "runtime_paths", "secret_store", "api_key",
            "raw_response", "story", "matrix", "ffmpeg",
        }
        self.assertTrue(forbidden.isdisjoint({item.name for item in fields(TTSProviderRequest)}))
        self.assertTrue(forbidden.isdisjoint({item.name for item in fields(TTSProviderResult)}))

    def test_fixed_rest_contract_and_key_remains_adapter_private(self) -> None:
        captured: dict[str, object] = {}
        fake_key = "synthetic-elevenlabs-key-never-log"
        text = "Hello world"

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["json"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "audio_base64": base64.b64encode(b"ID3" + b"a" * 1021).decode(),
                    "alignment": _alignment(text),
                },
            )

        original_client = httpx.AsyncClient
        client_kwargs: dict[str, object] = {}

        def recording_client(*args, **kwargs):
            client_kwargs.update(kwargs)
            return original_client(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = ElevenLabsProvider(
                fake_key,
                voice_map={"en": "fake_en_voice"},
                transport=httpx.MockTransport(handler),
            )
            request = TTSProviderRequest(
                text=text,
                language="en",
                voice_id=provider.resolve_voice_id("en"),
                rate="+0%",
                output_audio_path=root / "attempt.mp3.part",
                output_timing_path=root / "attempt.vtt.part",
                correlation_id="correlation-only",
            )
            with patch.object(module.httpx, "AsyncClient", side_effect=recording_client):
                result = provider.synthesize(request, attempt_timeout_seconds=5)

        self.assertEqual(result.provider_id, "elevenlabs")
        self.assertEqual(result.audio_format, "mp3")
        self.assertIn("/v1/text-to-speech/fake_en_voice/with-timestamps", captured["url"])
        self.assertIn(f"output_format={ELEVENLABS_OUTPUT_FORMAT}", captured["url"])
        self.assertEqual(captured["json"]["model_id"], ELEVENLABS_MODEL_ID)
        self.assertEqual(captured["json"]["voice_settings"]["speed"], 1.0)
        self.assertNotIn("plan", captured["json"])
        self.assertNotIn("tier", captured["json"])
        self.assertEqual(captured["headers"]["xi-api-key"], fake_key)
        self.assertIs(client_kwargs["trust_env"], False)
        self.assertNotIn(fake_key, repr(result))
        self.assertNotIn(fake_key, repr(provider))
        self.assertNotIn(text, repr(result))


if __name__ == "__main__":
    unittest.main()
