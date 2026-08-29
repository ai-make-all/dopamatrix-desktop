import json
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from src.api import routes_dsl
from src.api.dsl_parser import MainVisualSelectionMismatch
from tests.test_var001_balanced_axis_coverage import (
    _SyntheticParser,
    _balanced,
    _candidate,
    _payload,
    _plan_for_selections,
    _pools,
)


def _payload_for(result):
    diagnostics = result.coverage_diagnostics
    if diagnostics is None:
        raise AssertionError("balanced result must carry coverage diagnostics")
    return routes_dsl._coverage_diagnostics_v1_payload(diagnostics)


def _successful_child(plan, file_sid, kwargs):
    return routes_dsl._ChildResult(
        child_index=kwargs["child_index"],
        execution_id=kwargs["execution_id"],
        file_sid=file_sid,
        outcome="succeeded",
        assets=[{"asset_type": "video", "file_path": f"output/{file_sid}.mp4"}],
        elapsed=0.01,
        error_code=None,
        error_message=None,
        prompt_details={"meta": None, "timeline": [], "plan": plan},
    )


def _failed_child(plan, file_sid, kwargs):
    return routes_dsl._ChildResult(
        child_index=kwargs["child_index"],
        execution_id=kwargs["execution_id"],
        file_sid=file_sid,
        outcome="failed",
        assets=[],
        elapsed=0.01,
        error_code="TEST_RENDER_FAILED",
        error_message="controlled failure",
        prompt_details={"meta": None, "timeline": [], "plan": plan},
    )


def _run_balanced_coordinator(
    payload,
    planning_result,
    *,
    worker_side_effect=None,
    persist_side_effect=None,
):
    def default_worker(plan, _task_id, *args, file_sid=None, **kwargs):
        resolved_sid = file_sid or args[-1]
        return _successful_child(plan, resolved_sid, kwargs)

    with (
        patch.object(
            routes_dsl,
            "_plan_exact_main_visual_balanced_variants_from_db",
            return_value=planning_result,
        ),
        patch.object(
            routes_dsl,
            "render_worker",
            side_effect=worker_side_effect or default_worker,
        ) as worker,
        patch.object(
            routes_dsl,
            "_persist_task_history",
            side_effect=persist_side_effect,
        ) as persist,
        patch.object(routes_dsl.ws_manager, "broadcast_sync"),
    ):
        terminal = routes_dsl.render_batch_worker(
            payload,
            "coverage-task",
            batch_size=planning_result.coverage_diagnostics.requested_count,
            variant_planning_policy="exact_main_visual_balanced",
        )
    return terminal, worker, persist


class CoverageDiagnosticsPlannerTests(unittest.TestCase):
    def test_cov1_golden_five_beat_contract_and_digest_bridge(self):
        result, _parser, _payload_value = _balanced(_pools(4, 2, 1, 2, 2), 4)
        payload = _payload_for(result)

        self.assertEqual(payload["type"], "balanced_axis_coverage")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(
            payload["variant_planning_policy"], "exact_main_visual_balanced"
        )
        self.assertEqual(payload["accepted_count"], 4)
        self.assertEqual(payload["candidate_space_size"], 32)
        expected = [
            (4, 4, 0, 1, 1, 0, "VARIABLE_BALANCED"),
            (2, 2, 0, 2, 2, 0, "VARIABLE_BALANCED"),
            (1, 1, 0, 4, 4, 0, "FIXED_BY_CAPACITY"),
            (2, 2, 0, 2, 2, 0, "VARIABLE_BALANCED"),
            (2, 2, 0, 2, 2, 0, "VARIABLE_BALANCED"),
        ]
        for beat, values in zip(payload["beats"], expected):
            self.assertEqual(
                (
                    beat["pool_size"],
                    beat["unique_used"],
                    beat["unused_count"],
                    beat["ideal_floor"],
                    beat["ideal_ceil"],
                    beat["max_min_gap"],
                    beat["classification"],
                ),
                values,
            )
        expected_digests = [
            routes_dsl._main_visual_planning_fingerprint_contract(
                fingerprint
            ).fingerprint_digest
            for fingerprint in result.fingerprints
        ]
        self.assertEqual(payload["accepted_fingerprint_digests"], expected_digests)
        self.assertEqual(len(set(expected_digests)), 4)

    def test_cov2_cov3_cov4_cov5_balance_mathematics(self):
        fixed, _parser, _ = _balanced(_pools(1, 4), 4)
        fixed_beat = _payload_for(fixed)["beats"][0]
        self.assertEqual(
            (
                fixed_beat["selected_histogram"][0]["count"],
                fixed_beat["ideal_floor"],
                fixed_beat["ideal_ceil"],
                fixed_beat["max_min_gap"],
                fixed_beat["classification"],
            ),
            (4, 4, 4, 0, "FIXED_BY_CAPACITY"),
        )

        four, _parser, _ = _balanced(_pools(4), 4)
        self.assertEqual(
            _payload_for(four)["beats"][0]["classification"],
            "VARIABLE_BALANCED",
        )

        six, _parser, _ = _balanced(_pools(4, 2), 6)
        six_beat = _payload_for(six)["beats"][0]
        self.assertEqual(
            sorted(row["count"] for row in six_beat["selected_histogram"]),
            [1, 1, 2, 2],
        )
        self.assertEqual((six_beat["ideal_floor"], six_beat["ideal_ceil"]), (1, 2))
        self.assertEqual(six_beat["classification"], "VARIABLE_BALANCED")

        below, _parser, _ = _balanced(_pools(4, 2), 2)
        below_beat = _payload_for(below)["beats"][0]
        self.assertEqual(below_beat["unique_used"], 2)
        self.assertEqual(below_beat["unused_count"], 2)
        self.assertEqual((below_beat["ideal_floor"], below_beat["ideal_ceil"]), (0, 1))
        self.assertEqual(below_beat["max_min_gap"], 1)
        self.assertEqual(below_beat["classification"], "VARIABLE_BALANCED")

    def test_target_not_met_and_zero_pool_pure_builder_boundaries(self):
        pools = _pools(4)
        payload = _payload(pools)
        fingerprints = tuple(
            ((0, "Beat-0", 0, hash_value),)
            for hash_value in ("b0-0", "b0-0", "b0-1", "b0-1")
        )
        diagnostics = routes_dsl._build_coverage_diagnostics_v1(
            payload,
            pools,
            [{"b0-0": 2, "b0-1": 2, "b0-2": 0, "b0-3": 0}],
            fingerprints,
            requested_count=4,
            candidate_space_size=4,
            search_budget=4,
            examined_count=4,
            proposal_attempted_count=4,
            termination_reason="REQUEST_SATISFIED",
            preview_seeded=False,
            materialization_mismatch_count=0,
            invalid_plan_count=0,
            duplicate_fingerprint_reject_count=0,
        )
        beat = routes_dsl._coverage_diagnostics_v1_payload(diagnostics)["beats"][0]
        self.assertEqual(beat["max_min_gap"], 2)
        self.assertEqual(beat["classification"], "VARIABLE_TARGET_NOT_MET")

        empty_pools = [[]]
        empty_payload = _payload(empty_pools)
        empty = routes_dsl._build_coverage_diagnostics_v1(
            empty_payload,
            empty_pools,
            [{}],
            (),
            requested_count=1,
            candidate_space_size=0,
            search_budget=1,
            examined_count=0,
            proposal_attempted_count=0,
            termination_reason="TRUE_SPACE_EXHAUSTED",
            preview_seeded=False,
            materialization_mismatch_count=0,
            invalid_plan_count=0,
            duplicate_fingerprint_reject_count=0,
        )
        empty_beat = routes_dsl._coverage_diagnostics_v1_payload(empty)["beats"][0]
        self.assertIsNone(empty_beat["classification"])
        self.assertIsNone(empty_beat["ideal_floor"])
        self.assertIsNone(empty_beat["ideal_ceil"])
        self.assertIsNone(empty_beat["max_min_gap"])

    def test_cov6_search_diagnostics_use_actual_injected_budget(self):
        result, _parser, _ = _balanced(_pools(4, 4), 4, search_budget=3)
        payload = _payload_for(result)
        self.assertEqual(payload["search_budget"], 3)
        self.assertEqual(payload["examined_count"], 3)
        self.assertEqual(payload["candidate_space_size"], 16)
        self.assertEqual(payload["termination_reason"], "PLANNING_SEARCH_LIMIT_REACHED")
        self.assertIn("PLANNING_SEARCH_LIMIT_REACHED", result.warning_codes)

    def test_cov7_mismatch_and_invalid_counters_partition_attempts(self):
        for exception_type, counter_name in (
            (MainVisualSelectionMismatch, "materialization_mismatch_count"),
            (ValueError, "invalid_plan_count"),
        ):
            pools = _pools(3)
            first_key = routes_dsl._selection_key((pools[0][0],))

            def fail_first(payload, selections, key, exc=exception_type):
                if key == first_key:
                    raise exc("controlled rejection")
                return _plan_for_selections(payload, selections)

            result, _parser, _ = _balanced(
                pools,
                2,
                parser=_SyntheticParser(pools, fail_first),
            )
            data = _payload_for(result)
            self.assertEqual(data["proposal_attempted_count"], 3)
            self.assertEqual(data["examined_count"], 3)
            self.assertEqual(data["rejection_counts"][counter_name], 1)
            self.assertEqual(data["accepted_count"], 2)
            self.assertEqual(data["beats"][0]["selected_count"], 2)

    def test_cov8_duplicate_fingerprint_rejection_does_not_change_coverage(self):
        pools = [[
            _candidate(1, "same"),
            _candidate(2, "same"),
            _candidate(3, "other"),
        ]]
        result, _parser, _ = _balanced(pools, 3)
        data = _payload_for(result)
        self.assertEqual(data["proposal_attempted_count"], 3)
        self.assertEqual(
            data["rejection_counts"]["duplicate_fingerprint_reject_count"], 1
        )
        self.assertEqual(data["accepted_count"], 2)
        self.assertEqual(data["beats"][0]["pool_size"], 2)
        self.assertEqual(
            [row["count"] for row in data["beats"][0]["selected_histogram"]],
            [1, 1],
        )

    def test_cov9_preview_and_no_preview_provenance(self):
        pools = _pools(4, 2)
        payload = _payload(pools)
        preview = _plan_for_selections(payload, tuple(pool[0] for pool in pools))
        seeded, _parser, _ = _balanced(
            pools,
            4,
            payload=payload,
            preview_plan=preview,
        )
        seeded_data = _payload_for(seeded)
        self.assertTrue(seeded_data["preview_seeded"])
        self.assertEqual(seeded_data["preview_child_index"], 0)
        self.assertEqual(
            seeded_data["preview_fingerprint_digest"],
            seeded_data["accepted_fingerprint_digests"][0],
        )
        self.assertEqual(
            seeded_data["examined_count"],
            seeded_data["proposal_attempted_count"] + 1,
        )

        plain, _parser, _ = _balanced(pools, 4, payload=payload)
        plain_data = _payload_for(plain)
        self.assertFalse(plain_data["preview_seeded"])
        self.assertIsNone(plain_data["preview_child_index"])
        self.assertIsNone(plain_data["preview_fingerprint_digest"])
        self.assertEqual(
            plain_data["examined_count"], plain_data["proposal_attempted_count"]
        )

    def test_cov14_dynamic_beats_json_unicode_and_privacy_bounds(self):
        for beat_count in (3, 5, 7):
            pools = _pools(*([2] * beat_count))
            names = [f"节拍-{beat_count}-{index}" for index in range(beat_count)]
            payload = _payload(pools, beat_names=names)
            payload.timeline[0].role = "角色-自定义"
            result, _parser, _ = _balanced(pools, 4, payload=payload)
            data = _payload_for(result)
            self.assertEqual(len(data["beats"]), beat_count)
            self.assertEqual(
                [beat["beat_index"] for beat in data["beats"]],
                list(range(beat_count)),
            )
            self.assertEqual(
                [beat["beat_identity"] for beat in data["beats"]], names
            )
            json.dumps(data, ensure_ascii=False, allow_nan=False)

        large, _parser, _ = _balanced(_pools(20, 4), 4)
        data = _payload_for(large)
        histogram = data["beats"][0]["selected_histogram"]
        self.assertEqual(data["beats"][0]["pool_size"], 20)
        self.assertLessEqual(len(histogram), 4)
        serialized = json.dumps(data, ensure_ascii=False)
        selected_hashes = {row["normalized_file_hash"] for row in histogram}
        unused_hash = next(f"b0-{index}" for index in range(20) if f"b0-{index}" not in selected_hashes)
        self.assertNotIn(unused_hash, serialized)
        for forbidden in ("file_path", "filename", "prompt", "raw_dsl", "semantic_tags"):
            self.assertNotIn(forbidden, serialized)


class CoverageDiagnosticsCoordinatorTests(unittest.TestCase):
    def test_coordinator_validates_then_emits_once_before_children_and_persists_same_payload(self):
        result, _parser, payload = _balanced(_pools(4, 2, 1, 2, 2), 4)
        order = []
        persisted = []
        emitted = []
        original_validate = routes_dsl._validated_coverage_diagnostics_payload

        def validate(*args):
            order.append("validate")
            return original_validate(*args)

        def emit(_task_id, coverage_payload):
            order.append("summary")
            emitted.append(coverage_payload)

        def worker(plan, _task_id, *args, file_sid=None, **kwargs):
            order.append("child")
            resolved_sid = file_sid or args[-1]
            return _successful_child(plan, resolved_sid, kwargs)

        def persist(**kwargs):
            persisted.append(kwargs["coverage_diagnostics"])

        with (
            patch.object(
                routes_dsl,
                "_validated_coverage_diagnostics_payload",
                side_effect=validate,
            ),
            patch.object(
                routes_dsl,
                "_emit_balanced_coverage_summary",
                side_effect=emit,
            ) as summary,
        ):
            terminal, worker_mock, _persist = _run_balanced_coordinator(
                payload,
                result,
                worker_side_effect=worker,
                persist_side_effect=persist,
            )

        self.assertEqual(order[:3], ["validate", "summary", "child"])
        summary.assert_called_once()
        self.assertEqual(worker_mock.call_count, 4)
        self.assertEqual(len(emitted), 1)
        self.assertIs(emitted[0], persisted[0])
        self.assertEqual(emitted[0], _payload_for(result))
        self.assertNotIn("coverageDiagnostics", terminal)

    def test_coordinator_digest_mismatch_is_hard_and_emits_nothing(self):
        result, _parser, payload = _balanced(_pools(2), 2)
        bad_diagnostics = replace(
            result.coverage_diagnostics,
            accepted_fingerprint_digests=("0" * 64,) * 2,
        )
        bad_result = replace(result, coverage_diagnostics=bad_diagnostics)
        with patch.object(
            routes_dsl, "_emit_balanced_coverage_summary"
        ) as summary:
            terminal, worker, _persist = _run_balanced_coordinator(payload, bad_result)

        summary.assert_not_called()
        worker.assert_not_called()
        self.assertEqual(terminal["plannedCount"], 0)
        self.assertIn("VARIANT_PLANNING_FAILED", terminal["warningCodes"])

    def test_coordinator_contract_identity_mismatch_is_hard(self):
        result, _parser, payload = _balanced(_pools(2), 2)
        invalid_fields = (
            {"diagnostics_type": "invalid_type"},
            {"version": 999},
            {"variant_planning_policy": "exact_main_visual"},
        )

        for replacement in invalid_fields:
            with self.subTest(replacement=replacement):
                bad_diagnostics = replace(
                    result.coverage_diagnostics,
                    **replacement,
                )
                bad_result = replace(
                    result,
                    coverage_diagnostics=bad_diagnostics,
                )
                with patch.object(
                    routes_dsl,
                    "_emit_balanced_coverage_summary",
                ) as summary:
                    terminal, worker, _persist = _run_balanced_coordinator(
                        payload,
                        bad_result,
                    )

                summary.assert_not_called()
                worker.assert_not_called()
                self.assertEqual(terminal["plannedCount"], 0)
                self.assertIn(
                    "VARIANT_PLANNING_FAILED",
                    terminal["warningCodes"],
                )

    def test_summary_loguru_payload_and_logger_failure_are_nonblocking(self):
        result, _parser, payload = _balanced(_pools(2), 2)
        captured = []
        with patch.object(
            routes_dsl.fingerprint_logger,
            "info",
            side_effect=lambda message: captured.append(message),
        ):
            terminal, worker, _persist = _run_balanced_coordinator(payload, result)

        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(worker.call_count, 2)
        self.assertEqual(len(captured), 1)
        self.assertTrue(captured[0].startswith("[BalancedCoverageSummary] "))
        event = json.loads(captured[0].split(" ", 1)[1])
        self.assertEqual(event["event"], "BalancedCoverageSummary")
        self.assertEqual(event["coverage_diagnostics"], _payload_for(result))

        with patch.object(
            routes_dsl.fingerprint_logger,
            "info",
            side_effect=RuntimeError("sink failed"),
        ):
            terminal, worker, _persist = _run_balanced_coordinator(payload, result)
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(worker.call_count, 2)

    def test_planning_accepted_count_survives_one_render_failure(self):
        result, _parser, payload = _balanced(_pools(4, 2), 4)
        persisted = []

        def worker(plan, _task_id, *args, file_sid=None, **kwargs):
            resolved_sid = file_sid or args[-1]
            if kwargs["child_index"] == 3:
                return _failed_child(plan, resolved_sid, kwargs)
            return _successful_child(plan, resolved_sid, kwargs)

        terminal, _worker, _persist = _run_balanced_coordinator(
            payload,
            result,
            worker_side_effect=worker,
            persist_side_effect=lambda **kwargs: persisted.append(
                kwargs["coverage_diagnostics"]
            ),
        )
        self.assertEqual(terminal["succeededCount"], 3)
        self.assertEqual(persisted[0]["accepted_count"], 4)

    def test_cov11_taskhistory_persists_nested_payload_without_schema_change(self):
        result, _parser, _payload_value = _balanced(_pools(2), 2)
        coverage_payload = _payload_for(result)
        child = _successful_child(
            result.plans[0],
            "file-a",
            {"child_index": 0, "execution_id": "exec-a"},
        )
        added = []

        class SessionContext:
            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _traceback):
                return False

            def add(self, row):
                added.append(row)

            def commit(self):
                return None

        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value="engine"),
            patch.object(
                routes_dsl,
                "sessionmaker",
                return_value=lambda: SessionContext(),
            ),
        ):
            routes_dsl._persist_task_history(
                task_id="coverage-history",
                tenant_id="tenant-a",
                prompt="prompt",
                batch_size=2,
                elapsed=1.0,
                child_results=[child],
                output_assets=child.assets,
                warning_codes=[],
                coverage_diagnostics=coverage_payload,
            )
            routes_dsl._persist_task_history(
                task_id="exact-history",
                tenant_id="tenant-a",
                prompt="prompt",
                batch_size=1,
                elapsed=1.0,
                child_results=[child],
                output_assets=child.assets,
                warning_codes=[],
            )

        details = json.loads(added[0].prompt_details)
        self.assertEqual(
            details["planning_summary"]["coverage_diagnostics"],
            coverage_payload,
        )
        self.assertFalse(hasattr(added[0], "coverage_diagnostics"))
        exact_details = json.loads(added[1].prompt_details)
        self.assertNotIn(
            "coverage_diagnostics",
            exact_details["planning_summary"],
        )

    def test_exact_and_legacy_do_not_emit_or_persist_coverage(self):
        pools = _pools(2)
        payload = _payload(pools)
        exact_result = routes_dsl._plan_exact_main_visual_variants(
            _SyntheticParser(pools), payload, 2
        )
        self.assertIsNone(exact_result.coverage_diagnostics)

        persisted = []

        def worker(plan, _task_id, *args, file_sid=None, **kwargs):
            resolved_sid = file_sid or args[-1]
            return _successful_child(plan, resolved_sid, kwargs)

        with (
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_variants_from_db",
                return_value=exact_result,
            ),
            patch.object(routes_dsl, "render_worker", side_effect=worker),
            patch.object(
                routes_dsl,
                "_persist_task_history",
                side_effect=lambda **kwargs: persisted.append(kwargs),
            ),
            patch.object(routes_dsl, "_emit_balanced_coverage_summary") as summary,
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            routes_dsl.render_batch_worker(
                payload,
                "exact-task",
                batch_size=2,
                variant_planning_policy="exact_main_visual",
            )
        summary.assert_not_called()
        self.assertIsNone(persisted[0]["coverage_diagnostics"])

        persisted.clear()
        resolved = _plan_for_selections(payload, (pools[0][0],))
        with (
            patch.object(routes_dsl, "render_worker", side_effect=worker),
            patch.object(
                routes_dsl,
                "_persist_task_history",
                side_effect=lambda **kwargs: persisted.append(kwargs),
            ),
            patch.object(routes_dsl, "_emit_balanced_coverage_summary") as summary,
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            routes_dsl.render_batch_worker(
                payload,
                "legacy-task",
                batch_size=1,
                resolved_plan=resolved,
                variant_planning_policy="legacy",
            )
        summary.assert_not_called()
        self.assertIsNone(persisted[0]["coverage_diagnostics"])


if __name__ == "__main__":
    unittest.main()
