import logging
import unittest
from collections import Counter
from itertools import product
from pathlib import Path
from unittest.mock import patch

from src.api import routes_dsl
from src.api.dsl_parser import MainVisualCandidate, MainVisualSelectionMismatch
from src.api.schemas import (
    BeatCompilationResult,
    CompilationPlan,
    CompilationPlanSummary,
    DSLBeatNode,
    ResolvedLayer,
    StoryDSLPayload,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _candidate(asset_id: int, file_hash: str) -> MainVisualCandidate:
    return MainVisualCandidate(asset_id=asset_id, file_hash=file_hash)


def _pools(*sizes: int) -> list[list[MainVisualCandidate]]:
    next_asset_id = 1
    pools: list[list[MainVisualCandidate]] = []
    for beat_index, size in enumerate(sizes):
        pool = []
        for candidate_index in range(size):
            pool.append(
                _candidate(
                    next_asset_id,
                    f"b{beat_index}-{candidate_index}",
                )
            )
            next_asset_id += 1
        pools.append(pool)
    return pools


def _payload(
    pools: list[list[MainVisualCandidate]],
    *,
    beat_names: list[str] | None = None,
) -> StoryDSLPayload:
    names = beat_names or [f"Beat-{index}" for index in range(len(pools))]
    return StoryDSLPayload(
        engine_type="content",
        timeline=[
            DSLBeatNode(
                beat=names[index],
                role=f"role-{index}",
                address_mode="locked",
                asset_hashes=[candidate.file_hash for candidate in pool],
                script_text=f"script-{index}",
            )
            for index, pool in enumerate(pools)
        ],
    )


def _plan_for_selections(
    payload: StoryDSLPayload,
    selections: tuple[MainVisualCandidate, ...] | list[MainVisualCandidate],
) -> CompilationPlan:
    beats = []
    for node, selection in zip(payload.timeline, selections):
        beats.append(
            BeatCompilationResult(
                beat=node.beat,
                role=node.role,
                address_mode=node.address_mode,
                layers=[
                    ResolvedLayer(
                        layer_index=0,
                        asset_id=selection.asset_id,
                        file_path=f"C:/{selection.file_hash}.mp4",
                        asset_type="video",
                        file_hash=selection.file_hash,
                    )
                ],
                resolved=True,
                script_text=node.script_text,
            )
        )
    return CompilationPlan(
        engine_type=payload.engine_type,
        beats=beats,
        unresolved_beats=[],
        summary=CompilationPlanSummary(
            total_beats=len(beats),
            resolved_beats=len(beats),
            unresolved_beats=0,
        ),
    )


class _SyntheticParser:
    def __init__(self, pools, materialize_hook=None):
        self.pools = pools
        self.materialize_hook = materialize_hook
        self.materialized_keys = []

    def discover_main_visual_candidates(self, _payload):
        return self.pools

    def materialize_with_main_selections(self, payload, selections):
        selection_tuple = tuple(selections)
        key = routes_dsl._selection_key(selection_tuple)
        self.materialized_keys.append(key)
        if self.materialize_hook is not None:
            return self.materialize_hook(payload, selection_tuple, key)
        return _plan_for_selections(payload, selection_tuple)


def _balanced(pools, requested_count, **kwargs):
    payload = kwargs.pop("payload", _payload(pools))
    parser = kwargs.pop("parser", _SyntheticParser(pools))
    result = routes_dsl._plan_exact_main_visual_balanced_variants(
        parser,
        payload,
        requested_count,
        **kwargs,
    )
    return result, parser, payload


def _axis_histogram(result, beat_index: int) -> Counter:
    return Counter(fingerprint[beat_index][3] for fingerprint in result.fingerprints)


def _fingerprint_sequences(result):
    return [tuple(component[3] for component in row) for row in result.fingerprints]


class BalancedCoverageAcceptanceTests(unittest.TestCase):
    def test_var1_four_candidates_batch_four_uses_each_once(self):
        result, _parser, _payload_value = _balanced(_pools(4), 4)

        self.assertEqual(sorted(_axis_histogram(result, 0).values()), [1, 1, 1, 1])
        self.assertEqual(len(set(result.fingerprints)), 4)

    def test_var2_four_by_two_batch_six_has_two_two_one_one(self):
        result, _parser, _payload_value = _balanced(_pools(4, 2), 6)

        self.assertEqual(sorted(_axis_histogram(result, 0).values()), [1, 1, 2, 2])
        self.assertEqual(len(result.fingerprints), 6)
        self.assertEqual(len(set(result.fingerprints)), 6)

    def test_var3_two_by_two_selects_complete_combination_set(self):
        pools = _pools(2, 2)
        result, _parser, _payload_value = _balanced(pools, 4)

        self.assertEqual(
            set(_fingerprint_sequences(result)),
            {
                ("b0-0", "b1-0"),
                ("b0-0", "b1-1"),
                ("b0-1", "b1-0"),
                ("b0-1", "b1-1"),
            },
        )

    def test_var4_fixed_axis_repeats_without_blocking_variable_coverage(self):
        result, _parser, _payload_value = _balanced(_pools(1, 4), 4)

        self.assertEqual(_axis_histogram(result, 0), Counter({"b0-0": 4}))
        self.assertEqual(sorted(_axis_histogram(result, 1).values()), [1, 1, 1, 1])

    def test_var5_golden_dynamic_five_beat_distribution(self):
        result, _parser, _payload_value = _balanced(_pools(4, 2, 1, 2, 2), 4)

        self.assertEqual(len(result.fingerprints), 4)
        self.assertEqual(len(set(result.fingerprints)), 4)
        self.assertEqual(sorted(_axis_histogram(result, 0).values()), [1, 1, 1, 1])
        self.assertEqual(sorted(_axis_histogram(result, 1).values()), [2, 2])
        self.assertEqual(_axis_histogram(result, 2), Counter({"b2-0": 4}))
        self.assertEqual(sorted(_axis_histogram(result, 3).values()), [2, 2])
        self.assertEqual(sorted(_axis_histogram(result, 4).values()), [2, 2])

    def test_var6_all_accepted_plans_use_existing_unique_fingerprint(self):
        result, _parser, _payload_value = _balanced(_pools(4, 2, 1, 2, 2), 4)

        recomputed = tuple(
            routes_dsl._exact_main_visual_fingerprint(plan) for plan in result.plans
        )
        self.assertEqual(recomputed, result.fingerprints)
        self.assertEqual(len(set(recomputed)), len(recomputed))

    def test_var7_preview_is_index_zero_and_counts_toward_coverage(self):
        pools = _pools(4, 2, 1, 2, 2)
        payload = _payload(pools)
        preview_selections = tuple(pool[0] for pool in pools)
        preview = _plan_for_selections(payload, preview_selections)
        result, _parser, _payload_value = _balanced(
            pools,
            4,
            payload=payload,
            preview_plan=preview,
        )

        self.assertIs(result.plans[0], preview)
        self.assertEqual(result.fingerprints[0], routes_dsl._exact_main_visual_fingerprint(preview))
        self.assertEqual(len(result.fingerprints), 4)
        self.assertEqual(len(set(result.fingerprints)), 4)
        self.assertEqual(sorted(_axis_histogram(result, 0).values()), [1, 1, 1, 1])
        for beat_index in (1, 3, 4):
            self.assertEqual(sorted(_axis_histogram(result, beat_index).values()), [2, 2])

    def test_var8_examined_attempts_never_exceed_injected_budget(self):
        result, parser, _payload_value = _balanced(
            _pools(4, 4),
            4,
            search_budget=3,
        )

        self.assertEqual(result.examined_combinations, 3)
        self.assertEqual(len(parser.materialized_keys), 3)
        self.assertLessEqual(result.examined_combinations, 3)

    def test_var9_complete_small_space_reports_true_capacity(self):
        result, parser, _payload_value = _balanced(_pools(2), 4)

        self.assertEqual(len(result.plans), 2)
        self.assertEqual(len(parser.materialized_keys), 2)
        self.assertEqual(result.termination_reason, "TRUE_SPACE_EXHAUSTED")
        self.assertEqual(result.warning_codes, ("INSUFFICIENT_UNIQUE_CAPACITY",))

    def test_var10_bounded_partial_space_reports_search_limit(self):
        def always_invalid(_payload_value, _selections, _key):
            raise MainVisualSelectionMismatch("forced mismatch")

        pools = _pools(4, 2)
        parser = _SyntheticParser(pools, always_invalid)
        result, _parser, _payload_value = _balanced(
            pools,
            3,
            parser=parser,
            search_budget=2,
        )

        self.assertEqual(result.examined_combinations, 2)
        self.assertEqual(result.termination_reason, "PLANNING_SEARCH_LIMIT_REACHED")
        self.assertIn("PLANNING_SEARCH_LIMIT_REACHED", result.warning_codes)
        self.assertNotIn("INSUFFICIENT_UNIQUE_CAPACITY", result.warning_codes)

    def _assert_dynamic_planning(self, beat_count: int):
        pools = _pools(*([2] * beat_count))
        names = [f"Dynamic-{beat_count}-{index}" for index in range(beat_count)]
        payload = _payload(pools, beat_names=names)
        result, _parser, _payload_value = _balanced(
            pools,
            4,
            payload=payload,
        )

        self.assertEqual(len(result.plans), 4)
        self.assertEqual(len(set(result.fingerprints)), 4)
        for plan, fingerprint in zip(result.plans, result.fingerprints):
            self.assertEqual([beat.beat for beat in plan.beats], names)
            self.assertEqual([component[0] for component in fingerprint], list(range(beat_count)))
            self.assertEqual([component[1] for component in fingerprint], names)

    def test_var11_dynamic_three_beats(self):
        self._assert_dynamic_planning(3)

    def test_var12_dynamic_five_beats(self):
        self._assert_dynamic_planning(5)

    def test_var13_dynamic_seven_beats(self):
        self._assert_dynamic_planning(7)

    def test_var14_unequal_four_by_three_by_two_balances_all_axes(self):
        result, _parser, _payload_value = _balanced(_pools(4, 3, 2), 12)

        self.assertEqual(sorted(_axis_histogram(result, 0).values()), [3, 3, 3, 3])
        self.assertEqual(sorted(_axis_histogram(result, 1).values()), [4, 4, 4])
        self.assertEqual(sorted(_axis_histogram(result, 2).values()), [6, 6])
        self.assertEqual(len(set(result.fingerprints)), 12)

    def test_var15_repeated_runs_have_identical_accepted_order(self):
        pools = _pools(4, 3, 2)
        orders = []
        fingerprints = []
        for _ in range(3):
            result, _parser, _payload_value = _balanced(pools, 10)
            orders.append(_fingerprint_sequences(result))
            fingerprints.append(result.fingerprints)

        self.assertEqual(orders[0], orders[1])
        self.assertEqual(orders[1], orders[2])
        self.assertEqual(fingerprints[0], fingerprints[1])
        self.assertEqual(fingerprints[1], fingerprints[2])


class BalancedCoverageFailureTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_invalid_best_proposal_consumes_budget_but_not_coverage(self):
        pools = _pools(3)
        first_key = routes_dsl._selection_key((pools[0][0],))

        def fail_first(payload, selections, key):
            if key == first_key:
                raise MainVisualSelectionMismatch("forced first mismatch")
            return _plan_for_selections(payload, selections)

        parser = _SyntheticParser(pools, fail_first)
        with patch.object(
            routes_dsl,
            "_update_main_visual_coverage",
            wraps=routes_dsl._update_main_visual_coverage,
        ) as update_coverage:
            result, _parser, _payload_value = _balanced(
                pools,
                2,
                parser=parser,
            )

        self.assertEqual(result.examined_combinations, 3)
        self.assertEqual(len(result.plans), 2)
        self.assertEqual(update_coverage.call_count, 2)
        self.assertEqual(_axis_histogram(result, 0), Counter({"b0-1": 1, "b0-2": 1}))
        self.assertIn("PLANNER_SELECTION_MISMATCH", result.warning_codes)

    def test_duplicate_authoritative_fingerprint_is_rejected_without_coverage_update(self):
        pools = [[
            _candidate(1, "same"),
            _candidate(2, "same"),
            _candidate(3, "other"),
        ]]
        with patch.object(
            routes_dsl,
            "_update_main_visual_coverage",
            wraps=routes_dsl._update_main_visual_coverage,
        ) as update_coverage:
            result, parser, _payload_value = _balanced(pools, 3)

        self.assertEqual(len(parser.materialized_keys), 3)
        self.assertEqual(len(result.plans), 2)
        self.assertEqual(len(set(result.fingerprints)), 2)
        self.assertEqual(update_coverage.call_count, 2)
        self.assertEqual(_axis_histogram(result, 0), Counter({"same": 1, "other": 1}))


class BalancedCandidateWindowTests(unittest.TestCase):
    def test_large_space_refills_preview_collision_to_remaining_budget(self):
        pools = _pools(4, 64)
        candidate_space_size = 4 * 64
        remaining_budget = 10
        preview_key = routes_dsl._selection_key(
            routes_dsl._selection_from_cartesian_ordinal(pools, 0)
        )

        original_schedule = routes_dsl._stratified_cartesian_ordinals(
            candidate_space_size,
            remaining_budget,
        )
        original_available = [
            ordinal
            for ordinal in original_schedule
            if routes_dsl._selection_key(
                routes_dsl._selection_from_cartesian_ordinal(pools, ordinal)
            )
            != preview_key
        ]
        window = routes_dsl._balanced_candidate_window(
            pools,
            candidate_space_size,
            remaining_budget,
            excluded_keys={preview_key},
        )

        self.assertEqual(len(original_available), remaining_budget - 1)
        self.assertEqual(len(window), remaining_budget)
        self.assertNotIn(preview_key, {entry.selection_key for entry in window})
        self.assertEqual(
            len({entry.selection_key for entry in window}),
            remaining_budget,
        )

    def test_large_space_stratification_exposes_all_leading_candidates(self):
        leading = [_candidate(index + 1, f"h{index + 1}") for index in range(4)]
        suffix = [_candidate(1000 + index, f"s{index}") for index in range(2048)]
        pools = [leading, suffix]
        candidate_space_size = 4 * 2048

        raw_prefix_leading = {
            routes_dsl._selection_from_cartesian_ordinal(pools, ordinal)[0].file_hash
            for ordinal in range(8)
        }
        window = routes_dsl._balanced_candidate_window(
            pools,
            candidate_space_size,
            8,
            excluded_keys=set(),
        )
        stratified_leading = {entry.selections[0].file_hash for entry in window}

        self.assertEqual(raw_prefix_leading, {"h1"})
        self.assertEqual(stratified_leading, {"h1", "h2", "h3", "h4"})
        self.assertEqual(window[0].cartesian_ordinal, 0)
        self.assertEqual(window[-1].cartesian_ordinal, candidate_space_size - 1)

    def test_mixed_radix_decoding_matches_itertools_product(self):
        pools = _pools(2, 3, 2)
        expected = list(product(*pools))

        actual = [
            routes_dsl._selection_from_cartesian_ordinal(pools, ordinal)
            for ordinal in range(len(expected))
        ]

        self.assertEqual(actual, expected)

    def test_large_window_materializes_only_actual_successful_attempts(self):
        pools = _pools(4, 256)
        result, parser, _payload_value = _balanced(
            pools,
            4,
            search_budget=128,
        )

        self.assertEqual(len(result.plans), 4)
        self.assertEqual(len(parser.materialized_keys), 4)
        self.assertEqual(result.examined_combinations, 4)


class BalancedCoverageScoreTests(unittest.TestCase):
    def test_unused_candidate_outranks_overused_candidate(self):
        candidates = [_candidate(1, "a"), _candidate(2, "b")]
        coverage = [{"a": 1, "b": 0}]
        repeated = routes_dsl._BalancedCandidateWindowEntry(
            selections=(candidates[0],),
            selection_key=routes_dsl._selection_key((candidates[0],)),
            cartesian_ordinal=0,
        )
        unused = routes_dsl._BalancedCandidateWindowEntry(
            selections=(candidates[1],),
            selection_key=routes_dsl._selection_key((candidates[1],)),
            cartesian_ordinal=1,
        )

        self.assertLess(
            routes_dsl._projected_main_visual_coverage_score(unused, coverage),
            routes_dsl._projected_main_visual_coverage_score(repeated, coverage),
        )

    def test_fixed_axis_does_not_change_coverage_score_components(self):
        fixed = _candidate(1, "fixed")
        variable = [_candidate(2, "a"), _candidate(3, "b")]
        entry = routes_dsl._BalancedCandidateWindowEntry(
            selections=(fixed, variable[1]),
            selection_key=routes_dsl._selection_key((fixed, variable[1])),
            cartesian_ordinal=3,
        )

        low_fixed_count = routes_dsl._projected_main_visual_coverage_score(
            entry,
            [{"fixed": 1}, {"a": 1, "b": 0}],
        )
        high_fixed_count = routes_dsl._projected_main_visual_coverage_score(
            entry,
            [{"fixed": 100}, {"a": 1, "b": 0}],
        )
        self.assertEqual(low_fixed_count[:3], high_fixed_count[:3])

    def test_equal_coverage_falls_through_to_ordinal_then_selection_key(self):
        candidates = [_candidate(1, "a"), _candidate(2, "b")]
        coverage = [{"a": 0, "b": 0}]
        earlier = routes_dsl._BalancedCandidateWindowEntry(
            selections=(candidates[1],),
            selection_key=routes_dsl._selection_key((candidates[1],)),
            cartesian_ordinal=0,
        )
        later = routes_dsl._BalancedCandidateWindowEntry(
            selections=(candidates[0],),
            selection_key=routes_dsl._selection_key((candidates[0],)),
            cartesian_ordinal=1,
        )
        self.assertLess(
            routes_dsl._projected_main_visual_coverage_score(earlier, coverage),
            routes_dsl._projected_main_visual_coverage_score(later, coverage),
        )

        key_first = routes_dsl._BalancedCandidateWindowEntry(
            selections=(candidates[0],),
            selection_key=routes_dsl._selection_key((candidates[0],)),
            cartesian_ordinal=5,
        )
        key_second = routes_dsl._BalancedCandidateWindowEntry(
            selections=(candidates[1],),
            selection_key=routes_dsl._selection_key((candidates[1],)),
            cartesian_ordinal=5,
        )
        self.assertLess(
            routes_dsl._projected_main_visual_coverage_score(key_first, coverage),
            routes_dsl._projected_main_visual_coverage_score(key_second, coverage),
        )


class ExactPlannerControlTests(unittest.TestCase):
    def test_existing_exact_planner_keeps_historical_lexicographic_order(self):
        pools = _pools(2, 2, 2)
        payload = _payload(pools)
        parser = _SyntheticParser(pools)

        result = routes_dsl._plan_exact_main_visual_variants(
            parser,
            payload,
            4,
        )

        self.assertEqual(
            _fingerprint_sequences(result),
            [
                ("b0-0", "b1-0", "b2-0"),
                ("b0-0", "b1-0", "b2-1"),
                ("b0-0", "b1-1", "b2-0"),
                ("b0-0", "b1-1", "b2-1"),
            ],
        )

    def test_phase1a_does_not_activate_balanced_policy(self):
        schemas_source = (REPO_ROOT / "src/api/schemas.py").read_text(encoding="utf-8")
        routes_source = (REPO_ROOT / "src/api/routes_dsl.py").read_text(encoding="utf-8")
        workspace_source = (
            REPO_ROOT / "web_ui/src/views/WorkspaceView.vue"
        ).read_text(encoding="utf-8")

        self.assertNotIn('"exact_main_visual_balanced"', schemas_source)
        self.assertNotIn(
            'variant_planning_policy == "exact_main_visual_balanced"',
            routes_source,
        )
        self.assertNotIn("exact_main_visual_balanced", workspace_source)


if __name__ == "__main__":
    unittest.main()
