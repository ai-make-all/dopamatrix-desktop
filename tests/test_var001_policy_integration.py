import unittest
from collections import Counter
from unittest.mock import Mock, patch

from src.api import routes_dsl
from tests.test_var001_balanced_axis_coverage import (
    _SyntheticParser,
    _balanced,
    _payload,
    _plan_for_selections,
    _pools,
)


def _planning_result(
    plans,
    *,
    warning_codes=(),
    reason="REQUEST_SATISFIED",
    candidate_space_size=None,
):
    fingerprints = tuple(
        routes_dsl._exact_main_visual_fingerprint(plan) for plan in plans
    )
    return routes_dsl._VariantPlanningResult(
        plans=tuple(plans),
        fingerprints=fingerprints,
        examined_combinations=len(plans),
        candidate_space_size=(
            candidate_space_size
            if candidate_space_size is not None
            else max(len(plans), 1)
        ),
        termination_reason=reason,
        warning_codes=tuple(warning_codes),
    )


def _successful_child_result(file_sid, kwargs, plan):
    return routes_dsl._ChildResult(
        child_index=kwargs["child_index"],
        execution_id=kwargs["execution_id"],
        file_sid=file_sid,
        outcome="succeeded",
        assets=[
            {
                "asset_type": "video",
                "file_path": f"output/final_{file_sid}.mp4",
            }
        ],
        elapsed=0.01,
        error_code=None,
        error_message=None,
        prompt_details={"timeline": [], "plan": plan},
    )


def _run_coordinator(
    payload,
    *,
    policy,
    batch_size,
    exact_result=None,
    balanced_result=None,
    balanced_side_effect=None,
    resolved_plan=None,
):
    captured = []

    def fake_worker(plan, _task_id, *args, file_sid=None, **kwargs):
        resolved_sid = file_sid or args[-1]
        captured.append((plan, resolved_sid, kwargs))
        return _successful_child_result(resolved_sid, kwargs, plan)

    with (
        patch.object(
            routes_dsl,
            "_plan_exact_main_visual_variants_from_db",
            return_value=exact_result,
        ) as exact_planner,
        patch.object(
            routes_dsl,
            "_plan_exact_main_visual_balanced_variants_from_db",
            return_value=balanced_result,
            side_effect=balanced_side_effect,
        ) as balanced_planner,
        patch.object(routes_dsl, "render_worker", side_effect=fake_worker) as worker,
        patch.object(routes_dsl, "_persist_task_history"),
        patch.object(routes_dsl.ws_manager, "broadcast_sync"),
    ):
        terminal = routes_dsl.render_batch_worker(
            payload,
            "var-phase1b-task",
            batch_size=batch_size,
            resolved_plan=resolved_plan,
            variant_planning_policy=policy,
        )

    captured.sort(key=lambda item: item[2]["child_index"])
    return terminal, captured, exact_planner, balanced_planner, worker


class BalancedPolicyRoutingTests(unittest.TestCase):
    def test_balanced_db_wrapper_delegates_to_phase1a_core(self):
        pools = _pools(1)
        payload = _payload(pools)
        preview = _plan_for_selections(payload, (pools[0][0],))
        expected = _planning_result([preview])
        parser = Mock()
        db = Mock()

        class SessionContext:
            def __enter__(self):
                return db

            def __exit__(self, _exc_type, _exc, _traceback):
                return False

        session_factory = Mock(return_value=SessionContext())
        with (
            patch.object(routes_dsl, "get_tenant_engine", return_value="engine"),
            patch.object(routes_dsl, "sessionmaker", return_value=session_factory),
            patch.object(routes_dsl, "DSLParserNode", return_value=parser),
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_balanced_variants",
                return_value=expected,
            ) as core,
        ):
            result = routes_dsl._plan_exact_main_visual_balanced_variants_from_db(
                "tenant-a",
                payload,
                1,
                preview_plan=preview,
            )

        self.assertIs(result, expected)
        core.assert_called_once_with(
            parser,
            payload,
            1,
            preview_plan=preview,
        )

    def test_var1b04_exact_routes_old_planner_and_keeps_control_order(self):
        pools = _pools(2, 2, 2)
        payload = _payload(pools)
        exact_result = routes_dsl._plan_exact_main_visual_variants(
            _SyntheticParser(pools),
            payload,
            4,
        )

        terminal, captured, exact, balanced, _worker = _run_coordinator(
            payload,
            policy="exact_main_visual",
            batch_size=4,
            exact_result=exact_result,
        )

        exact.assert_called_once()
        balanced.assert_not_called()
        self.assertEqual(terminal["plannedCount"], 4)
        self.assertEqual(
            [
                tuple(component[3] for component in call[2]["visual_fingerprint"])
                for call in captured
            ],
            [
                ("b0-0", "b1-0", "b2-0"),
                ("b0-0", "b1-0", "b2-1"),
                ("b0-0", "b1-1", "b2-0"),
                ("b0-0", "b1-1", "b2-1"),
            ],
        )

    def test_var1b05_08_13_balanced_routes_and_pairs_golden_results(self):
        pools = _pools(4, 2, 1, 2, 2)
        balanced_result, _parser, payload = _balanced(pools, 4)

        terminal, captured, exact, balanced, _worker = _run_coordinator(
            payload,
            policy="exact_main_visual_balanced",
            batch_size=4,
            balanced_result=balanced_result,
        )

        exact.assert_not_called()
        balanced.assert_called_once()
        self.assertEqual(terminal["plannedCount"], 4)
        self.assertEqual(len(captured), 4)
        for child_index, (plan, _file_sid, kwargs) in enumerate(captured):
            self.assertIs(plan, balanced_result.plans[child_index])
            self.assertEqual(
                kwargs["visual_fingerprint"],
                balanced_result.fingerprints[child_index],
            )
            self.assertTrue(kwargs["plan_is_authoritative"])

        histograms = [
            Counter(fingerprint[index][3] for fingerprint in balanced_result.fingerprints)
            for index in range(5)
        ]
        self.assertEqual(sorted(histograms[0].values()), [1, 1, 1, 1])
        self.assertEqual(sorted(histograms[1].values()), [2, 2])
        self.assertEqual(histograms[2], Counter({"b2-0": 4}))
        self.assertEqual(sorted(histograms[3].values()), [2, 2])
        self.assertEqual(sorted(histograms[4].values()), [2, 2])
        self.assertEqual(len(set(balanced_result.fingerprints)), 4)

    def test_var1b06_legacy_routes_neither_planner(self):
        pools = _pools(1)
        payload = _payload(pools)
        legacy_plan = _plan_for_selections(payload, (pools[0][0],))

        terminal, captured, exact, balanced, worker = _run_coordinator(
            payload,
            policy="legacy",
            batch_size=1,
            resolved_plan=legacy_plan,
        )

        exact.assert_not_called()
        balanced.assert_not_called()
        worker.assert_called_once()
        self.assertFalse(captured[0][2]["plan_is_authoritative"])
        self.assertIsNone(captured[0][2]["visual_fingerprint"])
        self.assertEqual(terminal["status"], "completed")

    def test_var1b07_balanced_preview_reaches_wrapper_and_remains_child_zero(self):
        pools = _pools(4, 2, 1, 2, 2)
        payload = _payload(pools)
        preview = _plan_for_selections(payload, tuple(pool[0] for pool in pools))
        observed_preview = []

        def plan_balanced(_tenant, worker_payload, requested, *, preview_plan=None):
            observed_preview.append(preview_plan)
            return routes_dsl._plan_exact_main_visual_balanced_variants(
                _SyntheticParser(pools),
                worker_payload,
                requested,
                preview_plan=preview_plan,
            )

        terminal, captured, exact, balanced, _worker = _run_coordinator(
            payload,
            policy="exact_main_visual_balanced",
            batch_size=4,
            balanced_side_effect=plan_balanced,
            resolved_plan=preview,
        )

        exact.assert_not_called()
        balanced.assert_called_once()
        self.assertEqual(observed_preview, [preview])
        self.assertIs(captured[0][0], preview)
        self.assertEqual(terminal["plannedCount"], 4)

    def test_var1b09_balanced_uses_existing_fingerprint_invariant(self):
        pools = _pools(1)
        payload = _payload(pools)
        plan = _plan_for_selections(payload, (pools[0][0],))
        wrong_fingerprint = ((0, "Beat-0", 0, "wrong"),)
        invalid_result = routes_dsl._VariantPlanningResult(
            plans=(plan,),
            fingerprints=(wrong_fingerprint,),
            examined_combinations=1,
            candidate_space_size=1,
            termination_reason="REQUEST_SATISFIED",
            warning_codes=(),
        )

        terminal, _captured, exact, balanced, worker = _run_coordinator(
            payload,
            policy="exact_main_visual_balanced",
            batch_size=1,
            balanced_result=invalid_result,
        )

        exact.assert_not_called()
        balanced.assert_called_once()
        worker.assert_not_called()
        self.assertEqual(terminal["plannedCount"], 0)
        self.assertIn("VARIANT_PLANNING_FAILED", terminal["warningCodes"])

    def test_var1b10_capacity_warning_propagates_without_duplicate_fill(self):
        pools = _pools(2)
        result, _parser, payload = _balanced(pools, 4)

        terminal, captured, exact, balanced, _worker = _run_coordinator(
            payload,
            policy="exact_main_visual_balanced",
            batch_size=4,
            balanced_result=result,
        )

        exact.assert_not_called()
        balanced.assert_called_once()
        self.assertEqual(len(captured), 2)
        self.assertEqual(terminal["plannedCount"], 2)
        self.assertTrue(terminal["partial"])
        self.assertIn("INSUFFICIENT_UNIQUE_CAPACITY", terminal["warningCodes"])

    def test_var1b11_search_limit_warning_propagates(self):
        pools = _pools(2, 2)
        result, _parser, payload = _balanced(pools, 4, search_budget=1)

        terminal, captured, exact, balanced, _worker = _run_coordinator(
            payload,
            policy="exact_main_visual_balanced",
            batch_size=4,
            balanced_result=result,
        )

        exact.assert_not_called()
        balanced.assert_called_once()
        self.assertEqual(len(captured), 1)
        self.assertEqual(
            terminal["warningCodes"],
            ["PLANNING_SEARCH_LIMIT_REACHED"],
        )
        self.assertNotIn("INSUFFICIENT_UNIQUE_CAPACITY", terminal["warningCodes"])

    def test_var1b14_balanced_policy_supports_dynamic_three_beats(self):
        pools = _pools(2, 2, 2)
        balanced_result, _parser, payload = _balanced(pools, 4)

        terminal, captured, exact, balanced, _worker = _run_coordinator(
            payload,
            policy="exact_main_visual_balanced",
            batch_size=4,
            balanced_result=balanced_result,
        )

        exact.assert_not_called()
        balanced.assert_called_once()
        self.assertEqual(terminal["plannedCount"], 4)
        self.assertEqual(len(captured), 4)
        self.assertTrue(
            all(len(call[2]["visual_fingerprint"]) == 3 for call in captured)
        )

    def test_var1b16_balanced_failure_does_not_fallback(self):
        pools = _pools(1)
        payload = _payload(pools)

        terminal, _captured, exact, balanced, worker = _run_coordinator(
            payload,
            policy="exact_main_visual_balanced",
            batch_size=1,
            balanced_side_effect=RuntimeError("balanced planner failed"),
        )

        exact.assert_not_called()
        balanced.assert_called_once()
        worker.assert_not_called()
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["plannedCount"], 0)
        self.assertIn("VARIANT_PLANNING_FAILED", terminal["warningCodes"])


if __name__ == "__main__":
    unittest.main()
