import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from src.api import routes_dsl
from src.api.schemas import (
    BeatCompilationResult,
    CompilationPlan,
    CompilationPlanSummary,
    DSLBeatNode,
    RenderDSLRequest,
    ResolvedLayer,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _beat() -> DSLBeatNode:
    return DSLBeatNode(
        beat="Hook",
        role="hook",
        address_mode="locked",
        asset_hashes=["asset-hash"],
    )


def _request(**overrides) -> RenderDSLRequest:
    values = {
        "engine_type": "content",
        "timeline": [_beat()],
        "batch_size": 1,
    }
    values.update(overrides)
    return RenderDSLRequest(**values)


def _plan() -> CompilationPlan:
    return CompilationPlan(
        engine_type="content",
        beats=[
            BeatCompilationResult(
                beat="Hook",
                role="hook",
                address_mode="locked",
                layers=[
                    ResolvedLayer(
                        layer_index=0,
                        asset_id=1,
                        file_path="input.mp4",
                        asset_type="video",
                        file_hash="asset-hash",
                    )
                ],
                resolved=True,
            )
        ],
        unresolved_beats=[],
        summary=CompilationPlanSummary(
            total_beats=1,
            resolved_beats=1,
            unresolved_beats=0,
        ),
    )


class PlanningPolicySchemaTests(unittest.TestCase):
    def test_all_supported_policies_are_schema_valid(self):
        for policy in (
            "legacy",
            "exact_main_visual",
            "exact_main_visual_balanced",
        ):
            with self.subTest(policy=policy):
                self.assertEqual(
                    _request(variant_planning_policy=policy).variant_planning_policy,
                    policy,
                )

    def test_omitted_policy_defaults_to_legacy(self):
        request = _request()

        self.assertEqual(request.variant_planning_policy, "legacy")
        self.assertFalse(routes_dsl._requests_exact_main_visual(request))

    def test_exact_policy_is_backend_visible_without_mode_heuristics(self):
        request = _request(
            mode="rewrite",
            variant_planning_policy="exact_main_visual",
        )

        self.assertEqual(request.variant_planning_policy, "exact_main_visual")
        self.assertTrue(routes_dsl._requests_exact_main_visual(request))
        self.assertFalse(routes_dsl._requests_exact_main_visual_balanced(request))

    def test_balanced_policy_is_distinct_and_backend_visible(self):
        request = _request(variant_planning_policy="exact_main_visual_balanced")

        self.assertFalse(routes_dsl._requests_exact_main_visual(request))
        self.assertTrue(routes_dsl._requests_exact_main_visual_balanced(request))
        self.assertTrue(routes_dsl._requests_authoritative_main_visual(request))

    def test_invalid_policy_fails_schema_validation(self):
        with self.assertRaises(ValidationError):
            _request(variant_planning_policy="random_diversity")


class PlanningPolicyRouteTests(unittest.TestCase):
    def test_ai_draft_exact_policy_schedules_planner_coordinator(self):
        parser = Mock()
        parser.parse_and_resolve.return_value = _plan()
        background = Mock()

        with (
            patch.object(routes_dsl, "DSLParserNode", return_value=parser),
            patch.object(
                routes_dsl,
                "_admit_dsl_public_task",
                return_value="admitted-test-task",
            ),
        ):
            response = routes_dsl.submit_dsl(
                _request(variant_planning_policy="exact_main_visual"),
                background,
                db=Mock(),
            )

        self.assertEqual(response.render_status, "rendering")
        background.add_task.assert_called_once()
        scheduled = background.add_task.call_args
        self.assertIs(scheduled.args[0], routes_dsl.render_batch_worker)
        self.assertEqual(
            scheduled.kwargs["variant_planning_policy"],
            "exact_main_visual",
        )
        self.assertIs(scheduled.kwargs["resolved_plan"], parser.parse_and_resolve.return_value)

    def test_blind_exact_policy_is_explicitly_unsupported(self):
        blind_request = _request(
            timeline=[],
            prompt="blind prompt",
            variant_planning_policy="exact_main_visual",
        )

        with self.assertRaises(HTTPException) as raised:
            routes_dsl.submit_dsl(
                blind_request,
                BackgroundTasks(),
                db=Mock(),
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn(
            "EXACT_MAIN_VISUAL_UNSUPPORTED_FOR_BLIND",
            str(raised.exception.detail),
        )

    def test_balanced_policy_schedules_same_request_time_preview_contract(self):
        parser = Mock()
        parser.parse_and_resolve.return_value = _plan()
        background = Mock()

        with (
            patch.object(routes_dsl, "DSLParserNode", return_value=parser),
            patch.object(
                routes_dsl,
                "_admit_dsl_public_task",
                return_value="admitted-test-task",
            ),
        ):
            response = routes_dsl.submit_dsl(
                _request(variant_planning_policy="exact_main_visual_balanced"),
                background,
                db=Mock(),
            )

        self.assertEqual(response.render_status, "rendering")
        scheduled = background.add_task.call_args
        self.assertEqual(
            scheduled.kwargs["variant_planning_policy"],
            "exact_main_visual_balanced",
        )
        self.assertIs(
            scheduled.kwargs["resolved_plan"],
            parser.parse_and_resolve.return_value,
        )

    def test_manual_default_policy_preserves_dispatch(self):
        parser = Mock()
        parser.parse_and_resolve.return_value = _plan()
        background = Mock()

        with (
            patch.object(routes_dsl, "DSLParserNode", return_value=parser),
            patch.object(
                routes_dsl,
                "_admit_dsl_public_task",
                return_value="admitted-test-task",
            ),
        ):
            response = routes_dsl.submit_manual(
                _request(),
                background,
                db=Mock(),
            )

        self.assertEqual(response.render_status, "rendering")
        parser.parse_and_resolve.assert_called_once()
        background.add_task.assert_called_once()

    def test_render_dsl_default_policy_preserves_dispatch(self):
        parser = Mock()
        parser.parse_and_resolve.return_value = _plan()
        background = Mock()

        with (
            patch.object(routes_dsl, "DSLParserNode", return_value=parser),
            patch.object(
                routes_dsl,
                "_admit_dsl_public_task",
                return_value="admitted-test-task",
            ),
        ):
            response = routes_dsl.render_dsl(
                _request(),
                background,
                db=Mock(),
            )

        self.assertEqual(response.status, "processing")
        parser.parse_and_resolve.assert_called_once()
        background.add_task.assert_called_once()

    def test_manual_and_direct_render_do_not_silently_accept_exact_policy(self):
        request = _request(variant_planning_policy="exact_main_visual")

        for endpoint, error_code in (
            (routes_dsl.submit_manual, "EXACT_MAIN_VISUAL_UNSUPPORTED_FOR_SUBMIT_MANUAL"),
            (routes_dsl.render_dsl, "EXACT_MAIN_VISUAL_UNSUPPORTED_FOR_RENDER_DSL"),
        ):
            with self.subTest(endpoint=endpoint.__name__):
                with self.assertRaises(HTTPException) as raised:
                    endpoint(request, BackgroundTasks(), db=Mock())
                self.assertEqual(raised.exception.status_code, 422)
                self.assertIn(error_code, str(raised.exception.detail))


class PlanningPolicyFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = (
            REPO_ROOT / "web_ui/src/views/WorkspaceView.vue"
        ).read_text(encoding="utf-8")
        cls.drawer = (
            REPO_ROOT / "web_ui/src/views/DslOrchestratorDrawer.vue"
        ).read_text(encoding="utf-8")
        draft_start = cls.workspace.index("async function draftBlueprint()")
        draft_end = cls.workspace.index("function buildTimelineFromTracks()")
        cls.draft_blueprint = cls.workspace[draft_start:draft_end]
        confirm_start = cls.workspace.index("function onOrchestratorConfirm(")
        confirm_end = cls.workspace.index("const stagedBlockCount")
        cls.orchestrator_confirm = cls.workspace[confirm_start:confirm_end]
        fission_start = cls.workspace.index("async function blindFission(")
        fission_end = cls.workspace.index("</script>", fission_start)
        cls.blind_fission = cls.workspace[fission_start:fission_end]

    def test_ai_draft_direct_render_carries_balanced_policy(self):
        self.assertIn(
            "const EXACT_MAIN_VISUAL_PLANNING_POLICY = 'exact_main_visual'",
            self.workspace,
        )
        self.assertIn(
            "const BALANCED_MAIN_VISUAL_PLANNING_POLICY = "
            "'exact_main_visual_balanced'",
            self.workspace,
        )
        self.assertIn(
            "orchestratorVariantPlanningPolicy.value = "
            "BALANCED_MAIN_VISUAL_PLANNING_POLICY",
            self.draft_blueprint,
        )
        self.assertNotIn("exact_main_visual_balanced", self.drawer)
        self.assertIn(
            "orchestratorDirectRender.value = true",
            self.draft_blueprint,
        )
        self.assertNotIn(
            "orchestratorVariantPlanningPolicy.value = "
            "EXACT_MAIN_VISUAL_PLANNING_POLICY",
            self.draft_blueprint,
        )
        self.assertIn(
            ':variant-planning-policy="orchestratorVariantPlanningPolicy"',
            self.workspace,
        )
        self.assertIn(':direct-render="orchestratorDirectRender"', self.workspace)
        self.assertIn("if (props.directRender)", self.drawer)
        self.assertIn(
            "variantPlanningPolicy: props.variantPlanningPolicy",
            self.drawer,
        )
        self.assertIn("blindFission({", self.orchestrator_confirm)
        self.assertIn("variantPlanningPolicy,", self.orchestrator_confirm)
        self.assertIn(
            "variant_planning_policy: variantPlanningPolicy",
            self.blind_fission,
        )
        self.assertIn(
            "const variantPlanningPolicy = options.variantPlanningPolicy",
            self.blind_fission,
        )

    def test_generic_submission_explicitly_defaults_to_legacy(self):
        self.assertIn(
            "variantPlanningPolicy = options.variantPlanningPolicy",
            self.workspace,
        )
        self.assertIn(
            "?? LEGACY_VARIANT_PLANNING_POLICY",
            self.workspace,
        )
        self.assertIn('@click="blindFission()"', self.workspace)
        self.assertIn(
            "orchestratorVariantPlanningPolicy.value = "
            "LEGACY_VARIANT_PLANNING_POLICY",
            self.workspace,
        )
        self.assertIn("orchestratorDirectRender.value = false", self.workspace)


if __name__ == "__main__":
    unittest.main()
