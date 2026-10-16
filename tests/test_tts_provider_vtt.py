from __future__ import annotations

import math
import unittest

from src.services.tts_provider import (
    TTSErrorCode,
    TTSProviderError,
    alignment_to_vtt,
    parse_rate_to_speed,
)


def _alignment(text: str, step: float = 0.1) -> dict[str, list]:
    return {
        "characters": list(text),
        "character_start_times_seconds": [index * step for index in range(len(text))],
        "character_end_times_seconds": [(index + 1) * step for index in range(len(text))],
    }


class TTSProviderVttTests(unittest.TestCase):
    def test_english_character_alignment_has_exact_golden_vtt(self) -> None:
        actual, count = alignment_to_vtt("Hello world!", _alignment("Hello world!"))
        self.assertEqual(count, 2)
        self.assertEqual(
            actual,
            "WEBVTT\n\n"
            "1\n00:00:00.000 --> 00:00:00.500\nHello\n\n"
            "2\n00:00:00.600 --> 00:00:01.200\nworld!\n",
        )

    def test_arabic_character_alignment_has_exact_golden_vtt(self) -> None:
        actual, count = alignment_to_vtt("مرحبا بك", _alignment("مرحبا بك", 0.2))
        self.assertEqual(count, 2)
        self.assertEqual(
            actual,
            "WEBVTT\n\n"
            "1\n00:00:00.000 --> 00:00:01.000\nمرحبا\n\n"
            "2\n00:00:01.200 --> 00:00:01.600\nبك\n",
        )

    def test_rate_contract_is_exact_and_never_clamps(self) -> None:
        self.assertEqual(parse_rate_to_speed("-30%"), 0.7)
        self.assertEqual(parse_rate_to_speed("+0%"), 1.0)
        self.assertEqual(parse_rate_to_speed("+20%"), 1.2)
        for invalid in ("-31%", "+21%", "0%", "fast", "+1.5%"):
            with self.subTest(invalid=invalid), self.assertRaises(TTSProviderError) as raised:
                parse_rate_to_speed(invalid)
            self.assertEqual(raised.exception.code, TTSErrorCode.INVALID_INPUT)
            self.assertFalse(raised.exception.retryable)

    def test_deterministic_alignment_violations_are_non_retryable(self) -> None:
        text = "ab"
        bad_alignments = [
            {},
            _alignment(""),
            {**_alignment(text), "character_end_times_seconds": [0.1]},
            {**_alignment(text), "characters": ["a", "x"]},
            {
                "characters": ["ab"],
                "character_start_times_seconds": [0.0],
                "character_end_times_seconds": [0.2],
            },
            {**_alignment(text), "character_start_times_seconds": [-1.0, 0.1]},
            {**_alignment(text), "character_end_times_seconds": [0.0, 0.2]},
            {**_alignment(text), "character_start_times_seconds": [0.1, 0.0]},
            {**_alignment(text), "character_end_times_seconds": [0.2, 0.15]},
            {**_alignment(text), "character_start_times_seconds": [math.nan, 0.1]},
        ]
        for alignment in bad_alignments:
            with self.subTest(alignment=alignment), self.assertRaises(TTSProviderError) as raised:
                alignment_to_vtt(text, alignment)
            self.assertEqual(raised.exception.code, TTSErrorCode.ARTIFACT_INVALID)
            self.assertFalse(raised.exception.retryable)


if __name__ == "__main__":
    unittest.main()
