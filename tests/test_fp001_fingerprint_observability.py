import json
import logging
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.api import routes_dsl
from src.api.schemas import (
    BeatCompilationResult,
    CompilationPlan,
    CompilationPlanSummary,
    DSLBeatNode,
    ResolvedLayer,
    StoryDSLPayload,
)


def _plan(
    beat_count: int,
    *,
    hashes: list[str] | None = None,
    beat_names: list[str] | None = None,
    asset_ids: list[int] | None = None,
) -> CompilationPlan:
    hashes = hashes or [f"hash-{index}" for index in range(beat_count)]
    beat_names = beat_names or [f"Beat-{index}" for index in range(beat_count)]
    asset_ids = asset_ids or list(range(1, beat_count + 1))
    beats = [
        BeatCompilationResult(
            beat=beat_names[index],
            role="body",
            address_mode="locked",
            layers=[
                ResolvedLayer(
                    layer_index=0,
                    asset_id=asset_ids[index],
                    file_path=f"main-{index}.mp4",
                    asset_type="video",
                    file_hash=hashes[index],
                )
            ],
            resolved=True,
        )
        for index in range(beat_count)
    ]
    return CompilationPlan(
        engine_type="content",
        beats=beats,
        unresolved_beats=[],
        summary=CompilationPlanSummary(
            total_beats=beat_count,
            resolved_beats=beat_count,
            unresolved_beats=0,
        ),
    )


def _fingerprint(plan: CompilationPlan):
    return routes_dsl._exact_main_visual_fingerprint(plan)


def _event(plan: CompilationPlan, planner_fingerprint=None):
    return routes_dsl._variant_fingerprint_event_payload(
        plan,
        planner_fingerprint=planner_fingerprint,
        task_id="task-observe",
        execution_id="11111111-1111-4111-8111-111111111111",
        child_index=2,
        file_sid="11111111",
    )


def _variant_events(info_mock) -> list[dict]:
    prefix = "[VariantFingerprint] "
    events = []
    for call in info_mock.call_args_list:
        if not call.args or not isinstance(call.args[0], str):
            continue
        message = call.args[0]
        if not message.startswith(prefix):
            continue
        payload = message[len(prefix):]
        if payload.startswith("{"):
            events.append(json.loads(payload))
    return events


def _diagnostics(warning_mock) -> list[str]:
    prefix = "[VariantFingerprint] diagnostic="
    diagnostics = []
    for call in warning_mock.call_args_list:
        if not call.args or not isinstance(call.args[0], str):
            continue
        message = call.args[0]
        if message.startswith(prefix):
            diagnostics.append(message[len(prefix):].split(" ", 1)[0])
    return diagnostics


@contextmanager
def _temporary_working_directory():
    previous = os.getcwd()
    with tempfile.TemporaryDirectory() as directory:
        os.chdir(directory)
        try:
            yield Path(directory)
        finally:
            os.chdir(previous)


def _run_worker(
    plan: CompilationPlan,
    *,
    visual_fingerprint=None,
    plan_is_authoritative: bool,
    fingerprint_info_side_effect=None,
    fingerprint_warning_side_effect=None,
):
    task_id = "observability-worker"
    child = routes_dsl._create_child_executions(task_id, 1)[0]
    with _temporary_working_directory():
        final_path = Path("output") / f"final_en_{child.file_sid}.mp4"

        def fake_compositor(_node, context):
            final_path.parent.mkdir(exist_ok=True)
            final_path.write_bytes(b"video")
            context.variants = {"en": {"final_video": str(final_path)}}
            return True

        with (
            patch.object(
                routes_dsl,
                "compile_plan_to_timeline",
                return_value=SimpleNamespace(tracks=[object()]),
            ),
            patch.object(routes_dsl, "_run_compositor", side_effect=fake_compositor),
            patch.object(routes_dsl, "_run_cover_node", return_value=False),
            patch.object(routes_dsl.logger, "info"),
            patch.object(routes_dsl.logger, "warning"),
            patch.object(
                routes_dsl.fingerprint_logger,
                "info",
                side_effect=fingerprint_info_side_effect,
            ) as info,
            patch.object(
                routes_dsl.fingerprint_logger,
                "warning",
                side_effect=fingerprint_warning_side_effect,
            ) as warning,
        ):
            result = routes_dsl.render_worker(
                plan,
                task_id,
                file_sid=child.file_sid,
                execution_id=child.execution_id,
                child_index=child.child_index,
                plan_is_authoritative=plan_is_authoritative,
                visual_fingerprint=visual_fingerprint,
                enable_tts=False,
                enable_subtitles=False,
            )
    return result, info, warning


class RuntimeFingerprintObservabilityTests(unittest.TestCase):
    def test_fo1_child_work_fingerprint_is_forwarded_to_render_worker(self):
        plan = _plan(1)
        fingerprint = _fingerprint(plan)
        planning_result = routes_dsl._VariantPlanningResult(
            plans=(plan,),
            fingerprints=(fingerprint,),
            examined_combinations=1,
            candidate_space_size=1,
            termination_reason="REQUEST_SATISFIED",
            warning_codes=(),
        )
        payload = StoryDSLPayload(
            engine_type="content",
            timeline=[
                DSLBeatNode(
                    beat="Beat-0",
                    role="body",
                    address_mode="locked",
                    asset_hashes=["hash-0"],
                )
            ],
        )

        def fake_worker(_plan, _task_id, *_args, file_sid=None, **kwargs):
            resolved_file_sid = file_sid or _args[-1]
            return routes_dsl._ChildResult(
                child_index=kwargs["child_index"],
                execution_id=kwargs["execution_id"],
                file_sid=resolved_file_sid,
                outcome="succeeded",
                assets=[{"file_path": "output.mp4"}],
                elapsed=0.0,
                error_code=None,
                error_message=None,
                prompt_details={"meta": None, "timeline": []},
            )

        with (
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_variants_from_db",
                return_value=planning_result,
            ),
            patch.object(routes_dsl, "render_worker", side_effect=fake_worker) as worker,
            patch.object(routes_dsl, "_persist_task_history"),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            routes_dsl.render_batch_worker(
                payload,
                "forwarding-task",
                batch_size=1,
                resolved_plan=plan,
                variant_planning_policy="exact_main_visual",
            )

        self.assertEqual(worker.call_args.kwargs["visual_fingerprint"], fingerprint)

    def test_fo2_event_binds_child_execution_identity(self):
        event = _event(_plan(1))

        self.assertEqual(event["event"], "VariantFingerprint")
        self.assertEqual(event["phase"], "authoritative_worker_start")
        self.assertEqual(event["task_id"], "task-observe")
        self.assertEqual(
            event["execution_id"],
            "11111111-1111-4111-8111-111111111111",
        )
        self.assertEqual(event["child_index"], 2)
        self.assertEqual(event["file_sid"], "11111111")

    def test_fo3_event_exposes_committed_contract_metadata(self):
        event = _event(_plan(1))

        self.assertEqual(event["fingerprint_type"], "main_visual_planning")
        self.assertEqual(event["fingerprint_version"], 1)
        self.assertEqual(event["source_hash_algorithm"], "md5")

    def test_fo4_event_digest_uses_authoritative_fp001a_contract(self):
        plan = _plan(2)
        authoritative_fingerprint = _fingerprint(plan)
        expected = routes_dsl._main_visual_planning_fingerprint_contract(
            authoritative_fingerprint
        )

        self.assertEqual(
            _event(plan)["fingerprint_digest"],
            expected.fingerprint_digest,
        )

    def test_fo5_five_beats_emit_all_ordered_components(self):
        names = ["Hook", "Context", "Build", "Reveal", "CTA"]
        plan = _plan(5, beat_names=names)
        event = _event(plan)

        self.assertEqual(event["beat_count"], 5)
        self.assertFalse(event["components_truncated"])
        self.assertFalse(event["component_fields_truncated"])
        self.assertEqual(
            event["components"],
            [
                {
                    "beat_index": index,
                    "beat_identity": names[index],
                    "asset_id": index + 1,
                    "normalized_file_hash": f"hash-{index}",
                }
                for index in range(5)
            ],
        )

    def test_fo6_asset_id_is_observational_not_digest_identity(self):
        left = _event(_plan(1, asset_ids=[11]))
        right = _event(_plan(1, asset_ids=[99]))

        self.assertEqual(left["fingerprint_digest"], right["fingerprint_digest"])
        self.assertEqual(left["components"][0]["asset_id"], 11)
        self.assertEqual(right["components"][0]["asset_id"], 99)

    def test_fo7_matching_planner_tuple_is_reported_true(self):
        plan = _plan(2)

        self.assertIs(_event(plan, _fingerprint(plan))["planner_fingerprint_match"], True)

    def test_fo8_mismatch_warns_and_renders_authoritative_digest(self):
        plan = _plan(1, hashes=["authoritative"], asset_ids=[0])
        stale = _fingerprint(_plan(1, hashes=["stale"]))
        expected_digest = routes_dsl._main_visual_planning_fingerprint_contract(
            _fingerprint(plan)
        ).fingerprint_digest

        result, info, warning = _run_worker(
            plan,
            visual_fingerprint=stale,
            plan_is_authoritative=True,
        )
        events = _variant_events(info)

        self.assertTrue(result.succeeded)
        self.assertEqual(len(events), 1)
        self.assertIs(events[0]["planner_fingerprint_match"], False)
        self.assertEqual(events[0]["fingerprint_digest"], expected_digest)
        self.assertIn("FINGERPRINT_OBSERVABILITY_MISMATCH", _diagnostics(warning))

    def test_fo9_missing_planner_fingerprint_is_unknown_and_non_blocking(self):
        plan = _plan(1, asset_ids=[0])

        result, info, warning = _run_worker(
            plan,
            visual_fingerprint=None,
            plan_is_authoritative=True,
        )
        events = _variant_events(info)

        self.assertTrue(result.succeeded)
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["planner_fingerprint_match"])
        self.assertIn("FINGERPRINT_OBSERVABILITY_MISSING", _diagnostics(warning))

    def test_fo10_non_authoritative_missing_fingerprint_remains_compatible(self):
        result, info, warning = _run_worker(
            _plan(1, asset_ids=[0]),
            plan_is_authoritative=False,
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(_variant_events(info), [])
        self.assertEqual(_diagnostics(warning), [])

    def test_fo11_component_logging_is_bounded_without_truncating_digest(self):
        plan = _plan(routes_dsl._MAX_LOGGED_FINGERPRINT_COMPONENTS + 1)
        authoritative_fingerprint = _fingerprint(plan)
        event = _event(plan, authoritative_fingerprint)
        expected_digest = routes_dsl._main_visual_planning_fingerprint_contract(
            authoritative_fingerprint
        ).fingerprint_digest

        self.assertEqual(
            len(event["components"]),
            routes_dsl._MAX_LOGGED_FINGERPRINT_COMPONENTS,
        )
        self.assertTrue(event["components_truncated"])
        self.assertEqual(event["beat_count"], 33)
        self.assertEqual(event["fingerprint_digest"], expected_digest)
        self.assertEqual(len(event["fingerprint_digest"]), 64)

    def test_fo12_three_and_five_beats_are_not_truncated(self):
        for beat_count in (3, 5):
            with self.subTest(beat_count=beat_count):
                event = _event(_plan(beat_count))
                self.assertEqual(len(event["components"]), beat_count)
                self.assertFalse(event["components_truncated"])

    def test_fo13_observability_failures_do_not_escape_or_fail_render(self):
        plan = _plan(1, asset_ids=[0])
        fingerprint = _fingerprint(plan)
        with patch.object(
            routes_dsl,
            "_main_visual_planning_fingerprint_contract",
            side_effect=RuntimeError("contract failed"),
        ):
            result, info, warning = _run_worker(
                plan,
                visual_fingerprint=fingerprint,
                plan_is_authoritative=True,
            )

        self.assertTrue(result.succeeded)
        self.assertEqual(_variant_events(info), [])
        self.assertIn("FINGERPRINT_OBSERVABILITY_FAILED", _diagnostics(warning))

        with (
            patch.object(
                routes_dsl.fingerprint_logger,
                "info",
                side_effect=RuntimeError("log failed"),
            ),
            patch.object(
                routes_dsl.fingerprint_logger,
                "warning",
            ) as log_warning,
        ):
            routes_dsl._emit_authoritative_variant_fingerprint(
                plan,
                planner_fingerprint=fingerprint,
                task_id="log-failure",
                execution_id="22222222-2222-4222-8222-222222222222",
                child_index=0,
                file_sid="22222222",
            )
        self.assertIn("FINGERPRINT_OBSERVABILITY_FAILED", _diagnostics(log_warning))

    def test_fo14_normal_authoritative_worker_emits_exactly_one_event(self):
        plan = _plan(1, asset_ids=[0])
        fingerprint = _fingerprint(plan)

        result, info, warning = _run_worker(
            plan,
            visual_fingerprint=fingerprint,
            plan_is_authoritative=True,
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(len(_variant_events(info)), 1)
        self.assertEqual(_diagnostics(warning), [])

    def test_fo15_long_beat_identity_is_bounded_without_changing_digest(self):
        long_identity = "揭示" * 100
        plan = _plan(1, beat_names=[long_identity])
        authoritative_fingerprint = _fingerprint(plan)
        expected_digest = routes_dsl._main_visual_planning_fingerprint_contract(
            authoritative_fingerprint
        ).fingerprint_digest

        event = _event(plan, authoritative_fingerprint)

        self.assertEqual(authoritative_fingerprint[0][1], long_identity)
        self.assertEqual(
            event["components"][0]["beat_identity"],
            long_identity[:routes_dsl._MAX_LOGGED_BEAT_IDENTITY_CHARS],
        )
        self.assertLessEqual(
            len(event["components"][0]["beat_identity"]),
            routes_dsl._MAX_LOGGED_BEAT_IDENTITY_CHARS,
        )
        self.assertTrue(event["component_fields_truncated"])
        self.assertEqual(event["fingerprint_digest"], expected_digest)

    def test_fo16_long_abnormal_hash_is_bounded_without_changing_digest(self):
        long_hash = "A" * 200
        plan = _plan(1, hashes=[long_hash])
        authoritative_fingerprint = _fingerprint(plan)
        full_normalized_hash = "a" * 200
        expected_digest = routes_dsl._main_visual_planning_fingerprint_contract(
            authoritative_fingerprint
        ).fingerprint_digest

        event = _event(plan, authoritative_fingerprint)

        self.assertEqual(authoritative_fingerprint[0][3], full_normalized_hash)
        self.assertEqual(
            event["components"][0]["normalized_file_hash"],
            full_normalized_hash[:routes_dsl._MAX_LOGGED_SOURCE_HASH_CHARS],
        )
        self.assertLessEqual(
            len(event["components"][0]["normalized_file_hash"]),
            routes_dsl._MAX_LOGGED_SOURCE_HASH_CHARS,
        )
        self.assertTrue(event["component_fields_truncated"])
        self.assertEqual(event["fingerprint_digest"], expected_digest)

    def test_fo17_normal_identity_and_md5_remain_fully_visible(self):
        md5_hash = "a" * 32
        plan = _plan(1, hashes=[md5_hash], beat_names=["hook"])

        event = _event(plan, _fingerprint(plan))

        self.assertEqual(event["components"][0]["beat_identity"], "hook")
        self.assertEqual(event["components"][0]["normalized_file_hash"], md5_hash)
        self.assertFalse(event["components_truncated"])
        self.assertFalse(event["component_fields_truncated"])

    def test_fo18_component_count_truncation_does_not_imply_field_truncation(self):
        plan = _plan(routes_dsl._MAX_LOGGED_FINGERPRINT_COMPONENTS + 1)

        event = _event(plan, _fingerprint(plan))

        self.assertTrue(event["components_truncated"])
        self.assertFalse(event["component_fields_truncated"])

    def test_fo19_component_and_field_truncation_are_reported_independently(self):
        beat_count = routes_dsl._MAX_LOGGED_FINGERPRINT_COMPONENTS + 1
        beat_names = ["X" * 200] + [f"Beat-{index}" for index in range(1, beat_count)]
        plan = _plan(beat_count, beat_names=beat_names)

        event = _event(plan, _fingerprint(plan))

        self.assertTrue(event["components_truncated"])
        self.assertTrue(event["component_fields_truncated"])

    def test_fl1_normal_event_uses_project_loguru_and_contains_valid_json(self):
        plan = _plan(1)
        fingerprint = _fingerprint(plan)

        with (
            patch.object(routes_dsl.fingerprint_logger, "info") as fp_info,
            patch.object(routes_dsl.fingerprint_logger, "warning") as fp_warning,
        ):
            routes_dsl._emit_authoritative_variant_fingerprint(
                plan,
                planner_fingerprint=fingerprint,
                task_id="fl1-task",
                execution_id="31111111-1111-4111-8111-111111111111",
                child_index=0,
                file_sid="31111111",
            )

        events = _variant_events(fp_info)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "VariantFingerprint")
        self.assertEqual(events[0]["fingerprint_type"], "main_visual_planning")
        self.assertEqual(events[0]["fingerprint_version"], 1)
        fp_warning.assert_not_called()

    def test_fl2_normal_event_does_not_use_stdlib_routes_logger(self):
        plan = _plan(1)
        fingerprint = _fingerprint(plan)

        with (
            patch.object(routes_dsl.fingerprint_logger, "info") as fp_info,
            patch.object(routes_dsl.logger, "info") as stdlib_info,
        ):
            routes_dsl._emit_authoritative_variant_fingerprint(
                plan,
                planner_fingerprint=fingerprint,
                task_id="fl2-task",
                execution_id="32222222-2222-4222-8222-222222222222",
                child_index=0,
                file_sid="32222222",
            )

        self.assertEqual(len(_variant_events(fp_info)), 1)
        stdlib_info.assert_not_called()

    def test_fl3_mismatch_diagnostic_uses_project_loguru_non_blocking(self):
        plan = _plan(1, hashes=["authoritative"], asset_ids=[0])
        stale = _fingerprint(_plan(1, hashes=["stale"]))

        result, info, warning = _run_worker(
            plan,
            visual_fingerprint=stale,
            plan_is_authoritative=True,
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(len(_variant_events(info)), 1)
        self.assertIn("FINGERPRINT_OBSERVABILITY_MISMATCH", _diagnostics(warning))

    def test_fl4_missing_diagnostic_uses_project_loguru_non_blocking(self):
        result, info, warning = _run_worker(
            _plan(1, asset_ids=[0]),
            visual_fingerprint=None,
            plan_is_authoritative=True,
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(len(_variant_events(info)), 1)
        self.assertIn("FINGERPRINT_OBSERVABILITY_MISSING", _diagnostics(warning))

    def test_fl5_contract_failure_uses_project_loguru_non_blocking(self):
        plan = _plan(1, asset_ids=[0])
        with patch.object(
            routes_dsl,
            "_main_visual_planning_fingerprint_contract",
            side_effect=RuntimeError("contract failed"),
        ):
            result, info, warning = _run_worker(
                plan,
                visual_fingerprint=_fingerprint(plan),
                plan_is_authoritative=True,
            )

        self.assertTrue(result.succeeded)
        self.assertEqual(_variant_events(info), [])
        self.assertIn("FINGERPRINT_OBSERVABILITY_FAILED", _diagnostics(warning))

    def test_fl6_project_loguru_info_failure_does_not_fail_rendering(self):
        plan = _plan(1, asset_ids=[0])
        result, info, warning = _run_worker(
            plan,
            visual_fingerprint=_fingerprint(plan),
            plan_is_authoritative=True,
            fingerprint_info_side_effect=RuntimeError("loguru info failed"),
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(info.call_count, 1)
        self.assertIn("FINGERPRINT_OBSERVABILITY_FAILED", _diagnostics(warning))

    def test_fl7_info_and_diagnostic_logger_failures_do_not_escape_or_recurse(self):
        plan = _plan(1, asset_ids=[0])
        result, info, warning = _run_worker(
            plan,
            visual_fingerprint=_fingerprint(plan),
            plan_is_authoritative=True,
            fingerprint_info_side_effect=RuntimeError("loguru info failed"),
            fingerprint_warning_side_effect=RuntimeError("loguru warning failed"),
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(info.call_count, 1)
        self.assertEqual(warning.call_count, 1)

    def test_fl8_existing_routes_logger_remains_stdlib_logger(self):
        self.assertIs(routes_dsl.logger, logging.getLogger(routes_dsl.__name__))
        self.assertIsNot(routes_dsl.logger, routes_dsl.fingerprint_logger)


if __name__ == "__main__":
    unittest.main()
