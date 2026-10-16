from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from src.services import tts_provider
from src.services.tts_provider import (
    DEFAULT_TTS_PROVIDER_ID,
    ELEVENLABS_MODEL_ID,
    ELEVENLABS_OUTPUT_FORMAT,
    ELEVENLABS_VOICE_MAP,
    ElevenLabsProvider,
    TTSErrorCode,
    TTSProviderError,
    create_tts_provider,
)


class TTSProviderSelectionTests(unittest.TestCase):
    def test_packaged_provider_is_exactly_elevenlabs(self) -> None:
        self.assertEqual(DEFAULT_TTS_PROVIDER_ID, "elevenlabs")
        provider = create_tts_provider(
            api_key="synthetic",
            voice_map={"en": "fake_en", "ar": "fake_ar"},
        )
        self.assertIsInstance(provider, ElevenLabsProvider)

    def test_unknown_provider_fails_closed(self) -> None:
        with self.assertRaises(TTSProviderError) as raised:
            create_tts_provider("edge", api_key="synthetic")
        self.assertEqual(raised.exception.code, TTSErrorCode.CONFIG_ERROR)
        self.assertFalse(raised.exception.retryable)

    def test_missing_credential_fails_closed_without_network(self) -> None:
        calls = 0

        def loader():
            nonlocal calls
            calls += 1
            return None

        with self.assertRaises(TTSProviderError) as raised:
            create_tts_provider(secret_loader=loader)
        self.assertEqual(calls, 1)
        self.assertEqual(raised.exception.code, TTSErrorCode.CREDENTIAL_MISSING)

    def test_owner_frozen_default_voice_ids_are_exact(self) -> None:
        provider = ElevenLabsProvider("synthetic")
        self.assertEqual(provider.resolve_voice_id("en"), "mUpJ8rmi5BCb93cmM4F5")
        self.assertEqual(provider.resolve_voice_id("ar"), "j88WSnqw1P5zuzXcvjSz")
        self.assertEqual(
            dict(ELEVENLABS_VOICE_MAP),
            {
                "en": "mUpJ8rmi5BCb93cmM4F5",
                "ar": "j88WSnqw1P5zuzXcvjSz",
            },
        )
        with self.assertRaises(TypeError):
            ELEVENLABS_VOICE_MAP["en"] = "replacement"  # type: ignore[index]

    def test_unsupported_language_fails_closed_without_fallback(self) -> None:
        provider = ElevenLabsProvider("synthetic")
        with self.assertRaises(TTSProviderError) as raised:
            provider.resolve_voice_id("zh")
        self.assertEqual(raised.exception.code, TTSErrorCode.UNSUPPORTED_LANGUAGE)
        self.assertFalse(raised.exception.retryable)

    def test_edge_ids_are_not_elevenlabs_policy(self) -> None:
        self.assertNotIn("en-US-AriaNeural", ELEVENLABS_VOICE_MAP.values())
        self.assertNotIn("ar-SA-HamedNeural", ELEVENLABS_VOICE_MAP.values())

    def test_voice_policy_is_provider_private_and_not_persisted(self) -> None:
        frozen_ids = ("mUpJ8rmi5BCb93cmM4F5", "j88WSnqw1P5zuzXcvjSz")
        forbidden_paths = (
            Path("src/core/context.py"),
            Path("src/api/runtime_config.py"),
            Path("src/api/settings_router.py"),
            Path("web_ui/src/views/SettingsView.vue"),
        )
        for path in forbidden_paths:
            source = path.read_text(encoding="utf-8")
            for voice_id in frozen_ids:
                with self.subTest(path=str(path), voice_id=voice_id):
                    self.assertNotIn(voice_id, source)

    def test_fixed_provider_policy_is_unchanged(self) -> None:
        self.assertEqual(DEFAULT_TTS_PROVIDER_ID, "elevenlabs")
        self.assertEqual(ELEVENLABS_MODEL_ID, "eleven_multilingual_v2")
        self.assertEqual(ELEVENLABS_OUTPUT_FORMAT, "mp3_44100_128")

    def test_no_edge_fallback_sdk_or_plan_policy_is_encoded(self) -> None:
        source = inspect.getsource(tts_provider)
        self.assertNotIn("import edge_tts", source)
        self.assertNotIn("EdgeTTSProvider", source)
        self.assertNotIn("auto_fallback", source)
        self.assertNotIn("free_plan", source.lower())
        self.assertNotIn("startup_grant", source.lower())


if __name__ == "__main__":
    unittest.main()
