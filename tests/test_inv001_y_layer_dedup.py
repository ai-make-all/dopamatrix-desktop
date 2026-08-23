import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.dsl_parser import DSLParserNode
from src.api.models import Base, LocalAsset
from src.api.schemas import DSLBeatNode, StoryDSLPayload


class YLayerDedupTests(unittest.TestCase):
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
        self.engine.dispose()

    def _add_asset(
        self,
        file_hash: str,
        *,
        asset_type: str,
        tags: list[str],
        usage_count: int = 0,
    ) -> LocalAsset:
        asset = LocalAsset(
            file_hash=file_hash,
            file_path=f"C:/assets/{file_hash}",
            asset_type=asset_type,
            video_role="general",
            usage_count=usage_count,
            tags=tags,
            is_exhausted=False,
            is_deleted=False,
        )
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    @staticmethod
    def _locked_hook(
        *,
        beat: str,
        physical_hash: str,
        semantic_tag: str,
    ) -> DSLBeatNode:
        return DSLBeatNode(
            beat=beat,
            role="hook",
            address_mode="locked",
            asset_hashes=[physical_hash],
            semantic_tags=[semantic_tag],
        )

    @staticmethod
    def _layers_for_asset(beat_result, asset_id: int):
        return [layer for layer in beat_result.layers if layer.asset_id == asset_id]

    def test_y1_y2_y4_y5_y7_locked_duplicate_removed_and_distinct_y_survives(self):
        tag = "hook:test"
        bgm_a = self._add_asset(
            "bgm-a",
            asset_type="audio_bgm",
            tags=[tag],
            usage_count=10,
        )
        bgm_b = self._add_asset("bgm-b", asset_type="audio_bgm", tags=[tag])
        video_x = self._add_asset("video-x", asset_type="video", tags=[tag])
        payload = StoryDSLPayload(
            engine_type="content",
            timeline=[
                self._locked_hook(
                    beat="Hook",
                    physical_hash=bgm_a.file_hash,
                    semantic_tag=tag,
                )
            ],
        )

        plan = DSLParserNode(self.db).parse_and_resolve(payload)
        beat = plan.beats[0]

        self.assertEqual(
            [(layer.asset_id, layer.file_hash) for layer in beat.layers if layer.layer_index == 0],
            [(video_x.id, "video-x")],
        )
        self.assertEqual(len(self._layers_for_asset(beat, bgm_a.id)), 1)
        self.assertEqual(len(self._layers_for_asset(beat, bgm_b.id)), 1)
        self.assertEqual(
            [(layer.layer_index, layer.asset_id) for layer in beat.layers],
            [(0, video_x.id), (1, bgm_a.id), (2, bgm_b.id)],
        )

    def test_y3_same_y_asset_can_be_reused_once_in_each_beat(self):
        tag = "hook:cross-beat"
        bgm_a = self._add_asset("shared-bgm", asset_type="audio_bgm", tags=[tag])
        self._add_asset("shared-video", asset_type="video", tags=[tag])
        payload = StoryDSLPayload(
            engine_type="content",
            timeline=[
                self._locked_hook(
                    beat=beat_name,
                    physical_hash=bgm_a.file_hash,
                    semantic_tag=tag,
                )
                for beat_name in ("Hook", "Context")
            ],
        )

        plan = DSLParserNode(self.db).parse_and_resolve(payload)

        self.assertEqual(len(plan.beats), 2)
        for beat in plan.beats:
            self.assertEqual(len(self._layers_for_asset(beat, bgm_a.id)), 1)
            self.assertEqual([layer.layer_index for layer in beat.layers], [0, 1])

    def test_y6_exact_explicit_materialization_uses_shared_y_dedup(self):
        tag = "hook:exact"
        bgm_a = self._add_asset("exact-bgm", asset_type="audio_bgm", tags=[tag])
        video_x = self._add_asset("exact-video", asset_type="video", tags=[tag])
        payload = StoryDSLPayload(
            engine_type="content",
            timeline=[
                self._locked_hook(
                    beat="Hook",
                    physical_hash=bgm_a.file_hash,
                    semantic_tag=tag,
                )
            ],
        )
        parser = DSLParserNode(self.db)

        selections = [pool[0] for pool in parser.discover_main_visual_candidates(payload)]
        plan = parser.materialize_with_main_selections(payload, selections)
        beat = plan.beats[0]

        self.assertEqual(
            [(layer.asset_id, layer.file_hash) for layer in beat.layers if layer.layer_index == 0],
            [(video_x.id, "exact-video")],
        )
        self.assertEqual(len(self._layers_for_asset(beat, bgm_a.id)), 1)
        self.assertEqual([layer.layer_index for layer in beat.layers], [0, 1])

    def test_y9_normalized_equal_hashes_from_different_rows_are_one_y_media(self):
        tag = "hook:normalized-hash"
        physical = self._add_asset(
            " BGM-SAME ",
            asset_type="audio_bgm",
            tags=[tag],
            usage_count=10,
        )
        semantic_duplicate = self._add_asset(
            "bgm-same",
            asset_type="audio_bgm",
            tags=[tag],
        )
        self._add_asset("normalized-video", asset_type="video", tags=[tag])
        payload = StoryDSLPayload(
            engine_type="content",
            timeline=[
                self._locked_hook(
                    beat="Hook",
                    physical_hash=physical.file_hash,
                    semantic_tag=tag,
                )
            ],
        )

        beat = DSLParserNode(self.db).parse_and_resolve(payload).beats[0]
        y_layers = [layer for layer in beat.layers if layer.layer_index > 0]

        self.assertEqual([(layer.asset_id, layer.layer_index) for layer in y_layers], [(physical.id, 1)])
        self.assertNotIn(semantic_duplicate.id, {layer.asset_id for layer in y_layers})

    def test_smart_y_candidates_share_the_same_per_beat_identity_contract(self):
        tag = "smart:normalized-hash"
        first_bgm = self._add_asset(
            " SMART-BGM ",
            asset_type="audio_bgm",
            tags=[tag],
            usage_count=0,
        )
        duplicate_bgm = self._add_asset(
            "smart-bgm",
            asset_type="audio_bgm",
            tags=[tag],
            usage_count=1,
        )
        sfx = self._add_asset(
            "smart-sfx",
            asset_type="audio_sfx",
            tags=[tag],
            usage_count=2,
        )
        video = self._add_asset(
            "smart-video",
            asset_type="video",
            tags=[tag],
        )
        payload = StoryDSLPayload(
            engine_type="content",
            timeline=[
                DSLBeatNode(
                    beat="Hook",
                    role="hook",
                    address_mode="smart",
                    semantic_tags=[tag],
                )
            ],
        )

        beat = DSLParserNode(self.db).parse_and_resolve(payload).beats[0]

        self.assertEqual(
            [(layer.asset_id, layer.layer_index) for layer in beat.layers],
            [(video.id, 0), (first_bgm.id, 1), (sfx.id, 2)],
        )
        self.assertNotIn(duplicate_bgm.id, {layer.asset_id for layer in beat.layers})


if __name__ == "__main__":
    unittest.main()
