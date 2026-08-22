import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import routes_dsl
from src.api.dsl_parser import (
    DSLParserNode,
    MainVisualCandidate,
    MainVisualSelectionMismatch,
)
from src.api.models import Base, LocalAsset
from src.api.schemas import (
    BeatCompilationResult,
    BlueprintMeta,
    CompilationPlan,
    CompilationPlanSummary,
    DSLBeatNode,
    RenderDSLRequest,
    ResolvedLayer,
    StoryDSLPayload,
)


@contextmanager
def _temporary_working_directory():
    previous = os.getcwd()
    with tempfile.TemporaryDirectory() as directory:
        os.chdir(directory)
        try:
            yield Path(directory)
        finally:
            os.chdir(previous)


def _layer(
    file_hash: str,
    *,
    asset_id: int,
    layer_index: int = 0,
    asset_type: str = "video",
) -> ResolvedLayer:
    return ResolvedLayer(
        layer_index=layer_index,
        asset_id=asset_id,
        file_path=f"{file_hash.strip() or 'missing'}.mp4",
        asset_type=asset_type,
        file_hash=file_hash,
    )


def _plan_from_hashes(
    hashes: list[str],
    *,
    beat_names: list[str] | None = None,
    asset_ids: list[int] | None = None,
    y_hash: str | None = None,
) -> CompilationPlan:
    beat_names = beat_names or [f"Beat-{index}" for index in range(len(hashes))]
    asset_ids = asset_ids or list(range(1, len(hashes) + 1))
    beats = []
    for index, (beat_name, file_hash, asset_id) in enumerate(
        zip(beat_names, hashes, asset_ids)
    ):
        layers = [_layer(file_hash, asset_id=asset_id)]
        if y_hash is not None:
            layers.append(
                _layer(
                    f"{y_hash}-{index}",
                    asset_id=1000 + index,
                    layer_index=1,
                    asset_type="audio_bgm",
                )
            )
        beats.append(
            BeatCompilationResult(
                beat=beat_name,
                role=beat_name.lower(),
                address_mode="locked",
                layers=layers,
                resolved=True,
                script_text=f"script-{index}",
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


def _payload(pool_hashes: list[list[str]]) -> StoryDSLPayload:
    names = ["Hook", "Context", "Build", "CTA"]
    return StoryDSLPayload(
        engine_type="content",
        timeline=[
            DSLBeatNode(
                beat=names[index],
                role=names[index].lower(),
                address_mode="locked",
                asset_hashes=hashes,
                script_text=f"script-{index}",
            )
            for index, hashes in enumerate(pool_hashes)
        ],
    )


class _RecordingParser:
    def __init__(self, pools: list[list[MainVisualCandidate]]):
        self.pools = pools
        self.materialized_keys: list[tuple[tuple[int, str], ...]] = []

    def discover_main_visual_candidates(self, _payload):
        return self.pools

    def materialize_with_main_selections(self, payload, selections):
        self.materialized_keys.append(routes_dsl._selection_key(selections))
        return _plan_from_hashes(
            [selection.file_hash for selection in selections],
            beat_names=[node.beat for node in payload.timeline],
            asset_ids=[selection.asset_id for selection in selections],
        )


class ExactFingerprintTests(unittest.TestCase):
    def test_f1_same_ordered_main_hashes_have_same_fingerprint(self):
        left = _plan_from_hashes(["hook-a", "context-a"], beat_names=["Hook", "Context"])
        right = _plan_from_hashes(["hook-a", "context-a"], beat_names=["Hook", "Context"])
        self.assertEqual(
            routes_dsl._exact_main_visual_fingerprint(left),
            routes_dsl._exact_main_visual_fingerprint(right),
        )

    def test_f2_one_main_hash_difference_changes_fingerprint(self):
        left = _plan_from_hashes(["hook-a", "context-a"], beat_names=["Hook", "Context"])
        right = _plan_from_hashes(["hook-b", "context-a"], beat_names=["Hook", "Context"])
        self.assertNotEqual(
            routes_dsl._exact_main_visual_fingerprint(left),
            routes_dsl._exact_main_visual_fingerprint(right),
        )

    def test_f3_beat_order_changes_fingerprint(self):
        left = _plan_from_hashes(["a", "b"], beat_names=["Hook", "Context"])
        right = _plan_from_hashes(["b", "a"], beat_names=["Context", "Hook"])
        self.assertNotEqual(
            routes_dsl._exact_main_visual_fingerprint(left),
            routes_dsl._exact_main_visual_fingerprint(right),
        )

    def test_f4_y_layer_difference_does_not_change_level_one_fingerprint(self):
        left = _plan_from_hashes(["a"], beat_names=["Hook"], y_hash="bgm-a")
        right = _plan_from_hashes(["a"], beat_names=["Hook"], y_hash="bgm-b")
        self.assertEqual(
            routes_dsl._exact_main_visual_fingerprint(left),
            routes_dsl._exact_main_visual_fingerprint(right),
        )

    def test_f5_hash_case_and_whitespace_are_normalized(self):
        left = _plan_from_hashes(["  AbC123  "], beat_names=["Hook"])
        right = _plan_from_hashes(["abc123"], beat_names=["Hook"])
        self.assertEqual(
            routes_dsl._exact_main_visual_fingerprint(left),
            routes_dsl._exact_main_visual_fingerprint(right),
        )

    def test_f6_missing_conflicting_or_nonvisual_main_fails_validation(self):
        missing = _plan_from_hashes(["a"], beat_names=["Hook"])
        missing.beats[0].layers[0].layer_index = 1
        conflicting = _plan_from_hashes(["a"], beat_names=["Hook"])
        conflicting.beats[0].layers.append(_layer("b", asset_id=2))
        audio = _plan_from_hashes(["a"], beat_names=["Hook"])
        audio.beats[0].layers[0].asset_type = "audio_bgm"

        for plan in (missing, conflicting, audio):
            with self.subTest(plan=plan):
                with self.assertRaises(ValueError):
                    routes_dsl._exact_main_visual_fingerprint(plan)


class ResolverPlanningTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()

    def _add_asset(
        self,
        file_hash: str,
        *,
        asset_type: str = "video",
        tags: list[str] | None = None,
        usage_count: int = 0,
        exhausted: bool = False,
        deleted: bool = False,
    ) -> LocalAsset:
        asset = LocalAsset(
            file_hash=file_hash,
            file_path=f"C:/{file_hash}.mp4",
            asset_type=asset_type,
            video_role="general",
            usage_count=usage_count,
            tags=tags or [],
            is_exhausted=exhausted,
            is_deleted=deleted,
        )
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def test_p1_p2_p4_and_structural_repro_plan_four_unique_combinations(self):
        for file_hash in ("hook-12", "hook-13", "context-18", "context-28", "build-24"):
            self._add_asset(file_hash)
        payload = _payload(
            [["hook-12", "hook-13"], ["context-18", "context-28"], ["build-24"]]
        )
        parser = DSLParserNode(self.db)
        preview = parser.parse_and_resolve(payload)

        with patch("src.api.dsl_parser.random.choice") as legacy_random_choice:
            result = routes_dsl._plan_exact_main_visual_variants(
                parser,
                payload,
                4,
                preview_plan=preview,
            )

        self.assertEqual(len(result.plans), 4)
        self.assertEqual(len(set(result.fingerprints)), 4)
        self.assertEqual(result.warning_codes, ())
        legacy_random_choice.assert_not_called()
        self.assertEqual(
            {fingerprint[2][3] for fingerprint in result.fingerprints},
            {"build-24"},
        )

    def test_p3_candidate_hash_dedup_preserves_first_resolver_candidate(self):
        parser = DSLParserNode(Mock())
        first = SimpleNamespace(id=1, file_hash=" Same-Hash ")
        duplicate = SimpleNamespace(id=2, file_hash="same-hash")
        payload = _payload([["unused"]])

        with patch.object(
            parser,
            "_discover_main_visual_assets",
            return_value=[(first, []), (duplicate, [])],
        ):
            pools = parser.discover_main_visual_candidates(payload)

        self.assertEqual(
            pools,
            [[MainVisualCandidate(asset_id=1, file_hash="same-hash")]],
        )

    def test_locked_discovery_preserves_current_deleted_exhausted_and_axis_rules(self):
        exhausted_x = self._add_asset("exhausted-x", exhausted=True)
        self._add_asset("deleted-x", deleted=True)
        self._add_asset("physical-y", asset_type="audio_bgm")
        payload = _payload([["exhausted-x", "deleted-x", "physical-y"]])

        pools = DSLParserNode(self.db).discover_main_visual_candidates(payload)

        self.assertEqual(
            pools,
            [[MainVisualCandidate(exhausted_x.id, "exhausted-x")]],
        )

    def test_formal_hook_physical_bgm_semantic_x_discovery_and_planning(self):
        hook_tag = "hook:test-shock-absorber"
        bgm = self._add_asset(
            "hook-bgm",
            asset_type="audio_bgm",
            tags=[hook_tag],
        )
        first_video = self._add_asset("hook-video-a", tags=[hook_tag])
        second_video = self._add_asset("hook-video-b", tags=[hook_tag])
        payload = StoryDSLPayload(
            engine_type="content",
            timeline=[
                DSLBeatNode(
                    beat="Hook",
                    role="hook",
                    address_mode="locked",
                    asset_hashes=["hook-bgm"],
                    semantic_tags=[hook_tag],
                )
            ],
        )
        parser = DSLParserNode(self.db)

        pools = parser.discover_main_visual_candidates(payload)
        self.assertEqual(
            {candidate.asset_id for candidate in pools[0]},
            {first_video.id, second_video.id},
        )
        self.assertNotIn(bgm.id, {candidate.asset_id for candidate in pools[0]})

        result = routes_dsl._plan_exact_main_visual_variants(
            parser,
            payload,
            2,
        )

        self.assertEqual(len(result.plans), 2)
        self.assertEqual(len(set(result.fingerprints)), 2)
        self.assertEqual(
            {fingerprint[0][3] for fingerprint in result.fingerprints},
            {"hook-video-a", "hook-video-b"},
        )
        for plan in result.plans:
            main_layers = [
                layer
                for layer in plan.beats[0].layers
                if layer.layer_index == 0
            ]
            self.assertEqual(len(main_layers), 1)
            self.assertEqual(main_layers[0].asset_type, "video")
            self.assertIn(main_layers[0].asset_id, {first_video.id, second_video.id})
            self.assertTrue(
                any(
                    layer.layer_index > 0 and layer.asset_id == bgm.id
                    for layer in plan.beats[0].layers
                )
            )

    def test_legacy_context_multiple_physical_x_uses_random_choice(self):
        first = self._add_asset("context-video-a")
        second = self._add_asset("context-video-b")
        payload = StoryDSLPayload(
            engine_type="content",
            timeline=[
                DSLBeatNode(
                    beat="Context",
                    role="context",
                    address_mode="locked",
                    asset_hashes=["context-video-a", "context-video-b"],
                )
            ],
        )

        with patch(
            "src.api.dsl_parser.random.choice",
            side_effect=lambda candidates: candidates[1],
        ) as choose:
            plan = DSLParserNode(self.db).parse_and_resolve(payload)

        choose.assert_called_once()
        main_layers = [
            layer
            for layer in plan.beats[0].layers
            if layer.layer_index == 0
        ]
        self.assertEqual(
            [(layer.asset_id, layer.file_hash) for layer in main_layers],
            [(second.id, "context-video-b")],
        )
        self.assertNotEqual(main_layers[0].asset_id, first.id)

    def test_explicit_locked_selection_fails_fast_if_asset_disappears(self):
        asset = self._add_asset("locked-main")
        payload = _payload([["locked-main"]])
        parser = DSLParserNode(self.db)
        selected = parser.discover_main_visual_candidates(payload)[0][0]
        asset.is_deleted = True
        self.db.commit()

        with self.assertRaisesRegex(
            MainVisualSelectionMismatch,
            "PLANNER_SELECTION_MISMATCH",
        ):
            parser.materialize_with_main_selections(payload, [selected])

    def test_smart_fallback_fetch_scope_separates_legacy_and_exact_planning(self):
        parser = DSLParserNode(Mock())
        node = DSLBeatNode(
            beat="Hook",
            role="hook",
            address_mode="smart",
            semantic_tags=["not-found"],
        )

        with (
            patch.object(parser, "_query_by_tags", return_value=[]),
            patch.object(
                parser,
                "_query_smart_fallback_assets",
                return_value=[],
            ) as fallback_query,
        ):
            parser._resolve_smart(node)
            fallback_query.assert_called_once_with(enumerate_all=False)

            fallback_query.reset_mock()
            parser.discover_main_visual_candidates(
                StoryDSLPayload(engine_type="content", timeline=[node])
            )
            fallback_query.assert_called_once_with(enumerate_all=True)

        query = Mock()
        fallback_asset = SimpleNamespace(id=42)
        query.first.return_value = fallback_asset
        with patch.object(parser, "_smart_fallback_query", return_value=query):
            self.assertEqual(
                parser._query_smart_fallback_assets(enumerate_all=False),
                [fallback_asset],
            )
        query.first.assert_called_once_with()
        query.all.assert_not_called()

    def test_p5_p6_p7_each_tuple_materialized_once_and_terminates_finitely(self):
        pools = [
            [MainVisualCandidate(1, "h1"), MainVisualCandidate(2, "h2")],
            [MainVisualCandidate(3, "c1"), MainVisualCandidate(4, "c2")],
        ]
        parser = _RecordingParser(pools)
        result = routes_dsl._plan_exact_main_visual_variants(
            parser,
            _payload([["h1", "h2"], ["c1", "c2"]]),
            9,
        )

        self.assertEqual(len(parser.materialized_keys), 4)
        self.assertEqual(len(set(parser.materialized_keys)), 4)
        self.assertEqual(result.examined_combinations, 4)
        self.assertEqual(result.termination_reason, "TRUE_SPACE_EXHAUSTED")

    def test_a4_explicit_smart_selection_becomes_layer_zero_and_keeps_y(self):
        first = self._add_asset("smart-a", tags=["scene"], usage_count=0)
        second = self._add_asset("smart-b", tags=["scene"], usage_count=1)
        bgm = self._add_asset(
            "bgm-y",
            asset_type="audio_bgm",
            tags=["scene"],
        )
        payload = StoryDSLPayload(
            engine_type="content",
            timeline=[
                DSLBeatNode(
                    beat="Hook",
                    role="hook",
                    address_mode="smart",
                    semantic_tags=["scene"],
                )
            ],
        )
        parser = DSLParserNode(self.db)
        pools = parser.discover_main_visual_candidates(payload)
        selected = next(candidate for candidate in pools[0] if candidate.asset_id == second.id)

        plan = parser.materialize_with_main_selections(payload, [selected])
        main = [layer for layer in plan.beats[0].layers if layer.layer_index == 0]
        y_layers = [layer for layer in plan.beats[0].layers if layer.layer_index > 0]

        self.assertEqual([(layer.asset_id, layer.file_hash) for layer in main], [(second.id, "smart-b")])
        self.assertIn(bgm.id, {layer.asset_id for layer in y_layers})
        self.assertNotEqual(first.id, main[0].asset_id)


class CapacityPlanningTests(unittest.TestCase):
    def test_c1_true_capacity_two_does_not_duplicate_fill_request_four(self):
        parser = _RecordingParser(
            [
                [MainVisualCandidate(1, "h1"), MainVisualCandidate(2, "h2")],
                [MainVisualCandidate(3, "fixed")],
            ]
        )
        result = routes_dsl._plan_exact_main_visual_variants(
            parser,
            _payload([["h1", "h2"], ["fixed"]]),
            4,
        )

        self.assertEqual(len(result.plans), 2)
        self.assertEqual(result.termination_reason, "TRUE_SPACE_EXHAUSTED")
        self.assertEqual(result.warning_codes, ("INSUFFICIENT_UNIQUE_CAPACITY",))

    def test_c2_search_limit_is_not_reported_as_capacity_exhaustion(self):
        parser = _RecordingParser(
            [
                [MainVisualCandidate(1, "h1"), MainVisualCandidate(2, "h2")],
                [MainVisualCandidate(3, "c1"), MainVisualCandidate(4, "c2")],
            ]
        )
        result = routes_dsl._plan_exact_main_visual_variants(
            parser,
            _payload([["h1", "h2"], ["c1", "c2"]]),
            4,
            search_budget=1,
        )

        self.assertEqual(len(result.plans), 1)
        self.assertEqual(result.termination_reason, "PLANNING_SEARCH_LIMIT_REACHED")
        self.assertEqual(result.warning_codes, ("PLANNING_SEARCH_LIMIT_REACHED",))
        self.assertNotIn("INSUFFICIENT_UNIQUE_CAPACITY", result.warning_codes)

    def test_c3_zero_candidate_space_accepts_no_plan(self):
        parser = _RecordingParser([[]])
        result = routes_dsl._plan_exact_main_visual_variants(
            parser,
            _payload([["missing"]]),
            4,
        )

        self.assertEqual(result.plans, ())
        self.assertEqual(result.candidate_space_size, 0)
        self.assertEqual(result.warning_codes, ("INSUFFICIENT_UNIQUE_CAPACITY",))

    def test_c4_preview_is_seeded_only_when_current_and_valid(self):
        candidate = MainVisualCandidate(1, "current")
        payload = _payload([["current"]])
        valid_parser = _RecordingParser([[candidate]])
        valid_preview = _plan_from_hashes(
            ["current"], beat_names=["Hook"], asset_ids=[1]
        )

        valid = routes_dsl._plan_exact_main_visual_variants(
            valid_parser,
            payload,
            1,
            preview_plan=valid_preview,
        )
        self.assertIs(valid.plans[0], valid_preview)
        self.assertEqual(valid_parser.materialized_keys, [])

        stale_parser = _RecordingParser([[candidate]])
        stale_preview = _plan_from_hashes(
            ["stale"], beat_names=["Hook"], asset_ids=[99]
        )
        stale = routes_dsl._plan_exact_main_visual_variants(
            stale_parser,
            payload,
            1,
            preview_plan=stale_preview,
        )
        self.assertEqual(stale.fingerprints[0][0][3], "current")
        self.assertEqual(len(stale_parser.materialized_keys), 1)


def _successful_child_result(file_sid: str, kwargs: dict, plan: CompilationPlan):
    return routes_dsl._ChildResult(
        child_index=kwargs["child_index"],
        execution_id=kwargs["execution_id"],
        file_sid=file_sid,
        outcome="succeeded",
        assets=[
            {
                "file_path": f"final_{kwargs['child_index']}.mp4",
                "file_hash": routes_dsl._exact_main_visual_fingerprint(plan)[0][3],
            }
        ],
        elapsed=0.01,
        error_code=None,
        error_message=None,
        prompt_details={"meta": None, "timeline": []},
    )


class CoordinatorPlanningTests(unittest.TestCase):
    def _planning_result(self, plans, warning_codes=(), reason="REQUEST_SATISFIED"):
        fingerprints = tuple(
            routes_dsl._exact_main_visual_fingerprint(plan) for plan in plans
        )
        return routes_dsl._VariantPlanningResult(
            plans=tuple(plans),
            fingerprints=fingerprints,
            examined_combinations=len(plans),
            candidate_space_size=max(len(plans), 1),
            termination_reason=reason,
            warning_codes=tuple(warning_codes),
        )

    def test_a5_exact_coordinator_binds_unique_plans_after_planning(self):
        plans = [
            _plan_from_hashes(["h1"], beat_names=["Hook"]),
            _plan_from_hashes(["h2"], beat_names=["Hook"]),
        ]
        captured = []

        def fake_worker(plan, _task_id, *_args, file_sid=None, **kwargs):
            resolved_sid = file_sid or _args[-1]
            captured.append((plan, resolved_sid, kwargs))
            return _successful_child_result(resolved_sid, kwargs, plan)

        with (
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_variants_from_db",
                return_value=self._planning_result(plans),
            ) as planner,
            patch.object(routes_dsl, "render_worker", side_effect=fake_worker),
            patch.object(routes_dsl, "_persist_task_history"),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = routes_dsl.render_batch_worker(
                _payload([["h1", "h2"]]),
                "exact-batch",
                batch_size=2,
                resolved_plan=plans[0],
                variant_planning_policy="exact_main_visual",
            )

        planner.assert_called_once()
        self.assertEqual(len(captured), 2)
        self.assertEqual(
            len({routes_dsl._exact_main_visual_fingerprint(call[0]) for call in captured}),
            2,
        )
        self.assertTrue(all(call[2]["plan_is_authoritative"] for call in captured))
        self.assertEqual(terminal["plannedCount"], 2)

    def test_capacity_reduction_creates_only_accepted_children_and_is_partial(self):
        plans = [
            _plan_from_hashes(["h1"], beat_names=["Hook"]),
            _plan_from_hashes(["h2"], beat_names=["Hook"]),
        ]
        worker = Mock(
            side_effect=lambda plan, _task, *_args, file_sid=None, **kwargs: (
                _successful_child_result(file_sid or _args[-1], kwargs, plan)
            )
        )
        result = self._planning_result(
            plans,
            warning_codes=("INSUFFICIENT_UNIQUE_CAPACITY",),
            reason="TRUE_SPACE_EXHAUSTED",
        )

        with (
            patch.object(routes_dsl, "_plan_exact_main_visual_variants_from_db", return_value=result),
            patch.object(routes_dsl, "render_worker", worker),
            patch.object(routes_dsl, "_persist_task_history"),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = routes_dsl.render_batch_worker(
                _payload([["h1", "h2"]]),
                "reduced-batch",
                batch_size=4,
                variant_planning_policy="exact_main_visual",
            )

        self.assertEqual(worker.call_count, 2)
        self.assertEqual(terminal["requestedCount"], 4)
        self.assertEqual(terminal["plannedCount"], 2)
        self.assertEqual(terminal["succeededCount"], 2)
        self.assertTrue(terminal["partial"])
        self.assertIn("INSUFFICIENT_UNIQUE_CAPACITY", terminal["warningCodes"])

    def test_c3_zero_plans_creates_no_identity_or_render_and_finalizes_failed(self):
        result = self._planning_result(
            [],
            warning_codes=("INSUFFICIENT_UNIQUE_CAPACITY",),
            reason="TRUE_SPACE_EXHAUSTED",
        )
        with (
            patch.object(routes_dsl, "_plan_exact_main_visual_variants_from_db", return_value=result),
            patch.object(routes_dsl, "_create_child_executions") as create_children,
            patch.object(routes_dsl, "render_worker") as worker,
            patch.object(routes_dsl, "_persist_task_history") as persist,
            patch.object(routes_dsl.ws_manager, "broadcast_sync") as ws,
        ):
            terminal = routes_dsl.render_batch_worker(
                _payload([["missing"]]),
                "zero-plan-batch",
                batch_size=4,
                variant_planning_policy="exact_main_visual",
            )

        create_children.assert_not_called()
        worker.assert_not_called()
        persist.assert_not_called()
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["plannedCount"], 0)
        self.assertFalse(terminal["partial"])
        self.assertEqual(ws.call_count, 1)

    def test_search_limit_warning_survives_coordinator_terminal_payload(self):
        plan = _plan_from_hashes(["h1"], beat_names=["Hook"])
        result = self._planning_result(
            [plan],
            warning_codes=("PLANNING_SEARCH_LIMIT_REACHED",),
            reason="PLANNING_SEARCH_LIMIT_REACHED",
        )
        worker = Mock(
            side_effect=lambda selected, _task, *_args, file_sid=None, **kwargs: (
                _successful_child_result(file_sid or _args[-1], kwargs, selected)
            )
        )
        with (
            patch.object(routes_dsl, "_plan_exact_main_visual_variants_from_db", return_value=result),
            patch.object(routes_dsl, "render_worker", worker),
            patch.object(routes_dsl, "_persist_task_history"),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = routes_dsl.render_batch_worker(
                _payload([["h1", "h2"]]),
                "search-limited-batch",
                batch_size=4,
                variant_planning_policy="exact_main_visual",
            )

        self.assertEqual(terminal["plannedCount"], 1)
        self.assertTrue(terminal["partial"])
        self.assertEqual(
            terminal["warningCodes"],
            ["PLANNING_SEARCH_LIMIT_REACHED"],
        )

    def test_m4_legacy_coordinator_never_invokes_exact_planner(self):
        plan = _plan_from_hashes(["legacy"], beat_names=["Hook"])
        worker = Mock(
            side_effect=lambda _plan, _task, *_args, file_sid=None, **kwargs: (
                _successful_child_result(file_sid or _args[-1], kwargs, plan)
            )
        )
        with (
            patch.object(routes_dsl, "_plan_exact_main_visual_variants_from_db") as planner,
            patch.object(routes_dsl, "render_worker", worker),
            patch.object(routes_dsl, "_persist_task_history"),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = routes_dsl.render_batch_worker(
                _payload([["legacy"]]),
                "legacy-batch",
                batch_size=1,
                resolved_plan=plan,
            )

        planner.assert_not_called()
        self.assertFalse(worker.call_args.kwargs["plan_is_authoritative"])
        self.assertEqual(terminal["status"], "completed")


class ModePolicyNegativeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)

    @staticmethod
    def _successful_compositor(_node, context):
        file_sid = context.config["file_sid"]
        final_path = Path("output") / f"final_en_{file_sid}.mp4"
        final_path.parent.mkdir(exist_ok=True)
        final_path.write_bytes(b"video")
        context.variants = {"en": {"final_video": str(final_path)}}
        return True

    def test_manual_legacy_does_not_invoke_exact_planner(self):
        plan = _plan_from_hashes(["manual-main"], beat_names=["Hook"])
        dsl_payload = _payload([["manual-main"]])

        with (
            _temporary_working_directory(),
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_variants_from_db",
            ) as planner,
            patch.object(
                routes_dsl,
                "_parse_plan_from_db",
                return_value=plan,
            ) as parse_plan,
            patch.object(
                routes_dsl,
                "compile_plan_to_timeline",
                return_value=SimpleNamespace(tracks=[object()]),
            ),
            patch.object(
                routes_dsl,
                "_run_compositor",
                side_effect=self._successful_compositor,
            ),
            patch.object(routes_dsl, "_run_cover_node", return_value=False),
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(routes_dsl, "_persist_task_history"),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = routes_dsl.render_batch_worker(
                dsl_payload,
                "manual-legacy-no-planner",
                batch_size=1,
                resolved_plan=plan,
            )

        planner.assert_not_called()
        parse_plan.assert_called_once_with("default", dsl_payload)
        self.assertEqual(terminal["status"], "completed")

    def test_blind_legacy_does_not_invoke_exact_planner_and_uses_director(self):
        plan = _plan_from_hashes(["blind-main"], beat_names=["Hook"])
        director = Mock()
        director.draft_blueprint.return_value = {
            "timeline": [
                {
                    "beat": "Hook",
                    "role": "hook",
                    "address_mode": "locked",
                    "asset_hashes": ["blind-main"],
                    "script_text": "Blind script",
                }
            ],
            "meta": None,
        }

        with (
            _temporary_working_directory(),
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_variants_from_db",
            ) as planner,
            patch.object(routes_dsl, "DirectorNode", return_value=director),
            patch.object(routes_dsl, "_fetch_available_tags", return_value=[]),
            patch.object(
                routes_dsl,
                "_parse_plan_from_db",
                return_value=plan,
            ) as parse_plan,
            patch.object(
                routes_dsl,
                "compile_plan_to_timeline",
                return_value=SimpleNamespace(tracks=[object()]),
            ),
            patch.object(
                routes_dsl,
                "_run_compositor",
                side_effect=self._successful_compositor,
            ),
            patch.object(routes_dsl, "_run_cover_node", return_value=False),
            patch.object(routes_dsl, "get_tenant_engine", return_value=self.engine),
            patch.object(routes_dsl, "_persist_task_history"),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = routes_dsl.render_batch_worker(
                None,
                "blind-legacy-no-planner",
                prompt="blind prompt",
                batch_size=1,
                blind_dsl=True,
                enable_tts=False,
                enable_subtitles=False,
            )

        planner.assert_not_called()
        director.draft_blueprint.assert_called_once()
        parse_plan.assert_called_once()
        self.assertEqual(terminal["status"], "completed")


class AuthoritativeWorkerTests(unittest.TestCase):
    def test_a1_a2_a3_authoritative_plan_bypasses_resolver_and_raw_dsl_supplies_metadata(self):
        plan = _plan_from_hashes(["approved"], beat_names=["Hook"], asset_ids=[0])
        meta = BlueprintMeta(
            social_title="title",
            social_caption="caption {TRACKING_LINK}",
            social_hashtags="#tag",
            human_drive="curiosity",
            emotional_tag="energy",
        )
        dsl_payload = StoryDSLPayload(
            engine_type="content",
            timeline=[
                DSLBeatNode(
                    beat="Hook",
                    role="hook",
                    address_mode="locked",
                    asset_hashes=["raw-choice"],
                    script_text="raw DSL narration",
                )
            ],
            meta=meta,
        )
        child = routes_dsl._create_child_executions("authoritative-task", 1)[0]
        captured_tts = {}

        with _temporary_working_directory():
            final_path = Path("output") / f"final_en_{child.file_sid}.mp4"

            def fake_tts(context):
                captured_tts.update(context.assets.get("tts_script") or {})

            def fake_compositor(_node, context):
                final_path.parent.mkdir(exist_ok=True)
                final_path.write_bytes(b"video")
                context.variants = {"en": {"final_video": str(final_path)}}
                return True

            with (
                patch.object(routes_dsl, "_parse_plan_from_db") as resolver,
                patch.object(
                    routes_dsl,
                    "compile_plan_to_timeline",
                    return_value=SimpleNamespace(tracks=[object()]),
                ) as compile_timeline,
                patch.object(routes_dsl.TTSNode, "execute", side_effect=fake_tts),
                patch.object(routes_dsl, "_run_compositor", side_effect=fake_compositor),
                patch.object(routes_dsl, "_run_cover_node", return_value=False),
            ):
                result = routes_dsl.render_worker(
                    plan,
                    "authoritative-task",
                    prompt="metadata prompt",
                    file_sid=child.file_sid,
                    execution_id=child.execution_id,
                    child_index=child.child_index,
                    dsl_payload=dsl_payload,
                    plan_is_authoritative=True,
                    enable_subtitles=False,
                )

        resolver.assert_not_called()
        compile_timeline.assert_called_once_with(plan, target_duration=15)
        self.assertEqual(captured_tts, {"en": "raw DSL narration"})
        self.assertEqual(result.prompt_details["meta"]["social_title"], "title")
        self.assertTrue(result.succeeded)


class PolicyTransitionTests(unittest.TestCase):
    def test_p0_transition_exact_submit_no_longer_501_and_invokes_planner_lifecycle(self):
        preview = _plan_from_hashes(["asset-hash"], beat_names=["Hook"])
        request = RenderDSLRequest(
            engine_type="content",
            timeline=[
                DSLBeatNode(
                    beat="Hook",
                    role="hook",
                    address_mode="locked",
                    asset_hashes=["asset-hash"],
                )
            ],
            batch_size=1,
            variant_planning_policy="exact_main_visual",
        )
        background = Mock()
        parser = Mock()
        parser.parse_and_resolve.return_value = preview

        with patch.object(routes_dsl, "DSLParserNode", return_value=parser):
            response = routes_dsl.submit_dsl(request, background, db=Mock())

        scheduled = background.add_task.call_args
        planning_result = routes_dsl._VariantPlanningResult(
            plans=(preview,),
            fingerprints=(routes_dsl._exact_main_visual_fingerprint(preview),),
            examined_combinations=1,
            candidate_space_size=1,
            termination_reason="REQUEST_SATISFIED",
            warning_codes=(),
        )

        def fake_worker(plan, _task, *_args, file_sid=None, **kwargs):
            return _successful_child_result(file_sid or _args[-1], kwargs, plan)

        with (
            patch.object(
                routes_dsl,
                "_plan_exact_main_visual_variants_from_db",
                return_value=planning_result,
            ) as planner,
            patch.object(routes_dsl, "render_worker", side_effect=fake_worker),
            patch.object(routes_dsl, "_persist_task_history"),
            patch.object(routes_dsl.ws_manager, "broadcast_sync"),
        ):
            terminal = scheduled.args[0](*scheduled.args[1:], **scheduled.kwargs)

        self.assertEqual(response.render_status, "rendering")
        planner.assert_called_once()
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(terminal["plannedCount"], 1)


if __name__ == "__main__":
    unittest.main()
