import hashlib
import json
import re
import unittest

from src.api import routes_dsl
from src.api.schemas import (
    BeatCompilationResult,
    CompilationPlan,
    CompilationPlanSummary,
    ResolvedLayer,
)


def _plan(
    hashes: list[str],
    *,
    beat_names: list[str] | None = None,
    y_hash: str | None = None,
) -> CompilationPlan:
    beat_names = beat_names or [f"Beat-{index}" for index in range(len(hashes))]
    beats = []
    for index, (beat_name, file_hash) in enumerate(zip(beat_names, hashes)):
        layers = [
            ResolvedLayer(
                layer_index=0,
                asset_id=index + 1,
                file_path=f"main-{index}.mp4",
                asset_type="video",
                file_hash=file_hash,
            )
        ]
        if y_hash is not None:
            layers.append(
                ResolvedLayer(
                    layer_index=1,
                    asset_id=1000 + index,
                    file_path=f"y-{index}.mp3",
                    asset_type="audio_bgm",
                    file_hash=f"{y_hash}-{index}",
                )
            )
        beats.append(
            BeatCompilationResult(
                beat=beat_name,
                role="body",
                address_mode="locked",
                layers=layers,
                resolved=True,
            )
        )
    return CompilationPlan(
        engine_type="content",
        beats=beats,
        unresolved_beats=[],
        summary=CompilationPlanSummary(
            total_beats=len(beats),
            resolved_beats=len(beats),
            unresolved_beats=0,
        ),
    )


def _fingerprint(plan: CompilationPlan):
    return routes_dsl._exact_main_visual_fingerprint(plan)


def _contract(plan: CompilationPlan):
    return routes_dsl._main_visual_planning_fingerprint_contract(_fingerprint(plan))


class MainVisualPlanningFingerprintContractTests(unittest.TestCase):
    def test_fp1_same_tuple_has_same_canonical_bytes_and_digest(self):
        fingerprint = _fingerprint(
            _plan(["hash-a", "hash-b"], beat_names=["Hook", "Reveal"])
        )

        first = routes_dsl._main_visual_planning_fingerprint_contract(fingerprint)
        second = routes_dsl._main_visual_planning_fingerprint_contract(fingerprint)

        self.assertEqual(first.canonical_bytes, second.canonical_bytes)
        self.assertEqual(first.fingerprint_digest, second.fingerprint_digest)

    def test_fp2_one_main_hash_change_changes_digest(self):
        left = _contract(_plan(["hash-a", "hash-b"]))
        right = _contract(_plan(["hash-a", "hash-c"]))

        self.assertNotEqual(left.fingerprint_digest, right.fingerprint_digest)

    def test_fp3_beat_order_change_changes_digest(self):
        left = _contract(_plan(["a", "b"], beat_names=["Hook", "Reveal"]))
        right = _contract(_plan(["b", "a"], beat_names=["Reveal", "Hook"]))

        self.assertNotEqual(left.fingerprint_digest, right.fingerprint_digest)

    def test_fp4_beat_identity_only_change_changes_digest(self):
        before = _contract(_plan(["same"], beat_names=["Reveal"]))
        after = _contract(_plan(["same"], beat_names=["Product Reveal"]))

        self.assertNotEqual(before.fingerprint_digest, after.fingerprint_digest)

    def test_fp5_normalized_hashes_have_same_tuple_and_digest(self):
        left_fingerprint = _fingerprint(_plan(["  AbC123  "]))
        right_fingerprint = _fingerprint(_plan(["abc123"]))

        self.assertEqual(left_fingerprint, right_fingerprint)
        self.assertEqual(
            routes_dsl._main_visual_planning_fingerprint_contract(
                left_fingerprint
            ).fingerprint_digest,
            routes_dsl._main_visual_planning_fingerprint_contract(
                right_fingerprint
            ).fingerprint_digest,
        )

    def test_fp6_y_layer_change_does_not_change_tuple_or_digest(self):
        left_fingerprint = _fingerprint(_plan(["main"], y_hash="bgm-a"))
        right_fingerprint = _fingerprint(_plan(["main"], y_hash="bgm-b"))

        self.assertEqual(left_fingerprint, right_fingerprint)
        self.assertEqual(
            routes_dsl._main_visual_planning_fingerprint_contract(
                left_fingerprint
            ).fingerprint_digest,
            routes_dsl._main_visual_planning_fingerprint_contract(
                right_fingerprint
            ).fingerprint_digest,
        )

    def test_fp7_five_dynamic_beats_preserve_ordered_components(self):
        names = ["Hook", "Context", "Build", "Reveal", "CTA"]
        hashes = [f"hash-{index}" for index in range(5)]
        fingerprint = _fingerprint(_plan(hashes, beat_names=names))
        payload = routes_dsl._main_visual_planning_canonical_payload(fingerprint)

        self.assertEqual(len(payload["beats"]), 5)
        self.assertEqual(
            payload["beats"],
            [
                {
                    "beat_index": index,
                    "beat_identity": names[index],
                    "layer_index": 0,
                    "normalized_file_hash": hashes[index],
                }
                for index in range(5)
            ],
        )

    def test_fp8_arbitrary_beat_counts_are_deterministic(self):
        for beat_count in (1, 3, 7):
            with self.subTest(beat_count=beat_count):
                plan = _plan([f"hash-{index}" for index in range(beat_count)])
                fingerprint = _fingerprint(plan)
                first = routes_dsl._main_visual_planning_canonical_bytes(fingerprint)
                second = routes_dsl._main_visual_planning_canonical_bytes(fingerprint)

                self.assertEqual(first, second)
                self.assertEqual(
                    len(json.loads(first.decode("utf-8"))["beats"]),
                    beat_count,
                )

    def test_fp9_fingerprint_type_is_explicit(self):
        contract = _contract(_plan(["hash"]))

        self.assertEqual(
            routes_dsl._MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE,
            "main_visual_planning",
        )
        self.assertEqual(contract.fingerprint_type, "main_visual_planning")

    def test_fp10_fingerprint_version_is_one(self):
        contract = _contract(_plan(["hash"]))

        self.assertEqual(routes_dsl._MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION, 1)
        self.assertEqual(contract.fingerprint_version, 1)

    def test_fp11_source_hash_algorithm_is_md5(self):
        contract = _contract(_plan(["hash"]))

        self.assertEqual(
            routes_dsl._MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM,
            "md5",
        )
        self.assertEqual(contract.source_hash_algorithm, "md5")

    def test_fp12_digest_is_lowercase_sha256_hex(self):
        contract = _contract(_plan(["hash"]))
        digest = contract.fingerprint_digest

        self.assertRegex(digest, re.compile(r"^[0-9a-f]{64}$"))
        self.assertEqual(
            digest,
            hashlib.sha256(contract.canonical_bytes).hexdigest(),
        )

    def test_fp13_canonical_json_has_sorted_keys_and_no_whitespace(self):
        fingerprint = _fingerprint(_plan(["abc"], beat_names=["Hook"]))
        canonical = routes_dsl._main_visual_planning_canonical_bytes(fingerprint)

        self.assertEqual(
            canonical,
            b'{"beats":[{"beat_identity":"Hook","beat_index":0,'
            b'"layer_index":0,"normalized_file_hash":"abc"}],'
            b'"fingerprint_type":"main_visual_planning",'
            b'"fingerprint_version":1,"source_hash_algorithm":"md5"}',
        )

    def test_fp14_delimiter_like_and_unicode_values_are_unambiguous(self):
        left = ((0, "揭示|A:B,\\\"", 0, "c|d:e"),)
        right = ((0, "揭示", 0, "A:B,\\\"|c|d:e"),)

        left_bytes = routes_dsl._main_visual_planning_canonical_bytes(left)
        right_bytes = routes_dsl._main_visual_planning_canonical_bytes(right)

        self.assertNotEqual(left_bytes, right_bytes)
        self.assertEqual(
            json.loads(left_bytes.decode("utf-8"))["beats"][0],
            {
                "beat_index": 0,
                "beat_identity": "揭示|A:B,\\\"",
                "layer_index": 0,
                "normalized_file_hash": "c|d:e",
            },
        )

    def test_existing_inv_tuple_shape_and_value_are_unchanged(self):
        plan = _plan(
            ["  AbC123  ", "DEF456"],
            beat_names=[" Reveal ", "CTA"],
        )

        fingerprint = routes_dsl._exact_main_visual_fingerprint(plan)

        self.assertEqual(
            fingerprint,
            (
                (0, "Reveal", 0, "abc123"),
                (1, "CTA", 0, "def456"),
            ),
        )
        self.assertIsInstance(fingerprint, tuple)
        self.assertTrue(all(isinstance(component, tuple) for component in fingerprint))
        self.assertEqual(
            routes_dsl._main_visual_planning_fingerprint_contract(
                fingerprint
            ).components,
            fingerprint,
        )


if __name__ == "__main__":
    unittest.main()
