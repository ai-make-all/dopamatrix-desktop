"""
src/api/dsl_parser.py
——————————————————————————————————————————————————————————————————————
DSLParserNode — Story DSL 意图解析引擎  (Phase 4.1)

职责：
  接收前端提交的 StoryDSLPayload，对每个 Beat 节点执行双轨寻址算法，
  组装出可供 FFmpeg 渲染流水线直接消费的 CompilationPlan（渲染蓝图）。

双轨寻址策略：
  ┌─────────────┬──────────────────────────────────────────────────────┐
  │ locked 模式 │ 按 asset_hashes 精确锁定 X 轴主视频；                 │
  │             │ 若同时携带 semantic_tags，并发查 Y 轴叠加素材。        │
  ├─────────────┼──────────────────────────────────────────────────────┤
  │ smart  模式 │ 按 semantic_tags 匹配素材并打分；                      │
  │             │ 优先选 usage_count 低 & is_exhausted=False 的素材     │
  │             │ 作为 X 轴，其余命中项作为 Y 轴叠加层。                 │
  └─────────────┴──────────────────────────────────────────────────────┘

注意：当前为 Dry-run 阶段，不写回 usage_count，不触发 FFmpeg 渲染。
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple, cast

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .models import LocalAsset
from .schemas import (
    BeatCompilationResult,
    CompilationPlan,
    CompilationPlanSummary,
    DSLBeatNode,
    ResolvedLayer,
    StoryDSLPayload,
)

logger = logging.getLogger(__name__)

# 资产注册表：定义素材在渲染引擎中的物理坐标系归属
ASSET_REGISTRY = {
    "video": {"axis_type": "X_BASE"},
    "scene_master_video": {"axis_type": "X_STRUCTURE"},  # B端视频级底模
    "audio_bgm": {"axis_type": "Y_LAYER"},
    "audio_sfx": {"axis_type": "Y_LAYER"},
    "sfx": {"axis_type": "Y_LAYER"},       # 前端上传时使用的短名（兼容 audio_sfx）
    "sticker": {"axis_type": "Y_LAYER"},
    "logo": {"axis_type": "Y_LAYER"},
    "image": {"axis_type": "Y_LAYER"},     # 通用静态图片，渲染为 Y 轴 overlay
    "vfx": {"axis_type": "Y_LAYER"},       # 视觉特效资产（前端 asset_type=vfx）
    # text_template 为虚拟资产（无物理文件），归属 Y 轴叠加层；
    # 渲染阶段由 compositor 从 manifest.content_matrix 提取文本并注入 drawtext 滤镜
    "text_template": {"axis_type": "Y_LAYER"},
}


def normalize_file_hash(value: object) -> str:
    """Return the stable exact-content key used by INV-001 planning."""
    return str(value or "").strip().lower()


def is_main_visual_asset_type(asset_type: str) -> bool:
    """Whether an asset type is eligible for the layer-0 main visual."""
    return ASSET_REGISTRY.get(str(asset_type), {}).get("axis_type") in (
        "X_BASE",
        "X_STRUCTURE",
    )


@dataclass(frozen=True)
class MainVisualCandidate:
    """Session-independent reference to one resolver-valid main-X asset."""

    asset_id: int
    file_hash: str


class MainVisualSelectionMismatch(ValueError):
    """An explicit planner selection is no longer resolver-valid."""


def _y_layer_asset_types() -> List[str]:
    """ASSET_REGISTRY 中 axis_type 为 Y_LAYER 的素材类型，供 Y 轴查询防呆。"""
    return [k for k, v in ASSET_REGISTRY.items() if v.get("axis_type") == "Y_LAYER"]


def _axis_type_for_asset(asset: LocalAsset) -> str | None:
    """从 ASSET_REGISTRY 解析 ORM 素材的 axis_type（避免 Column 类型误报）。"""
    raw = getattr(asset, "asset_type", None)
    if raw is None:
        return None
    return ASSET_REGISTRY.get(str(raw), {}).get("axis_type")


class DSLParserNode:
    """
    Story DSL 意图解析器。

    使用方式：
        parser = DSLParserNode(db)
        plan   = parser.parse_and_resolve(payload)
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ================================================================ #
    # 公开入口                                                           #
    # ================================================================ #

    def parse_and_resolve(self, payload: StoryDSLPayload) -> CompilationPlan:
        """
        遍历 payload.timeline，对每个 Beat 执行寻址，返回 CompilationPlan。
        """
        self._prepare_payload(payload)
        return self._compile_plan(payload)

    def discover_main_visual_candidates(
        self,
        payload: StoryDSLPayload,
    ) -> List[List[MainVisualCandidate]]:
        """Return every resolver-valid main-X candidate for each ordered Beat.

        Candidate eligibility and ordering come from the same private helpers
        consumed by legacy resolution.  Exact planning only deduplicates equal
        normalized hashes; it does not introduce a second resolver policy.
        """
        self._prepare_payload(payload)
        pools: List[List[MainVisualCandidate]] = []

        for node in payload.timeline:
            candidates = self._discover_main_visual_assets(node)
            seen_hashes: set[str] = set()
            pool: List[MainVisualCandidate] = []
            for asset, _matched in candidates:
                normalized_hash = normalize_file_hash(getattr(asset, "file_hash", ""))
                if not normalized_hash or normalized_hash in seen_hashes:
                    continue
                seen_hashes.add(normalized_hash)
                pool.append(
                    MainVisualCandidate(
                        asset_id=cast(int, asset.id),
                        file_hash=normalized_hash,
                    )
                )
            pools.append(pool)

        return pools

    def materialize_with_main_selections(
        self,
        payload: StoryDSLPayload,
        selections: Sequence[MainVisualCandidate],
    ) -> CompilationPlan:
        """Resolve a plan while locking each Beat to an explicit main-X asset."""
        if len(selections) != len(payload.timeline):
            raise MainVisualSelectionMismatch(
                "PLANNER_SELECTION_MISMATCH: selection count does not match Beat count"
            )
        self._prepare_payload(payload)
        return self._compile_plan(payload, selections=selections)

    def _prepare_payload(self, payload: StoryDSLPayload) -> None:
        # Shared state for legacy resolution and exact candidate discovery.
        self._user_hard_tags = list(getattr(payload, "user_hard_tags", None) or [])

    def _compile_plan(
        self,
        payload: StoryDSLPayload,
        *,
        selections: Optional[Sequence[MainVisualCandidate]] = None,
    ) -> CompilationPlan:

        beat_results: List[BeatCompilationResult] = []
        unresolved: List[str] = []

        for beat_index, beat_node in enumerate(payload.timeline):
            explicit_main = selections[beat_index] if selections is not None else None
            result = self._resolve_beat(beat_node, explicit_main=explicit_main)
            beat_results.append(result)
            if not result.resolved:
                unresolved.append(beat_node.beat)

        resolved_count = sum(1 for r in beat_results if r.resolved)

        return CompilationPlan(
            engine_type=payload.engine_type,
            beats=beat_results,
            unresolved_beats=unresolved,
            summary=CompilationPlanSummary(
                total_beats=len(beat_results),
                resolved_beats=resolved_count,
                unresolved_beats=len(unresolved),
            ),
        )

    # ================================================================ #
    # Beat 级别分发                                                      #
    # ================================================================ #

    def _resolve_beat(
        self,
        node: DSLBeatNode,
        *,
        explicit_main: Optional[MainVisualCandidate] = None,
    ) -> BeatCompilationResult:
        """根据 address_mode 分发到对应寻址策略。"""
        logger.info(
            "[DSLParser] 解析入参 Beat=%s mode=%s hashes=%d tags=%s",
            node.beat,
            node.address_mode,
            len(node.asset_hashes),
            node.semantic_tags,
        )

        if node.address_mode == "locked":
            return self._resolve_locked(node, explicit_main=explicit_main)
        elif node.address_mode == "smart":
            return self._resolve_smart(node, explicit_main=explicit_main)
        else:
            if explicit_main is not None:
                raise MainVisualSelectionMismatch(
                    "PLANNER_SELECTION_MISMATCH: unsupported address_mode "
                    f"{node.address_mode!r} for Beat {node.beat!r}"
                )
            return BeatCompilationResult(
                beat=node.beat,
                role=node.role,
                address_mode=node.address_mode,
                layers=[],
                resolved=False,
                warnings=[
                    f"未知的 address_mode='{node.address_mode}'，"
                    "合法值为 'locked' | 'smart'。"
                ],
                script_text=node.script_text,
            )

    # ================================================================ #
    # 模式 A：locked — 精确锁定寻址                                      #
    # ================================================================ #

    def _load_locked_hash_assets(
        self,
        node: DSLBeatNode,
    ) -> tuple[
        List[LocalAsset],
        List[Tuple[LocalAsset, List[str]]],
        List[Tuple[LocalAsset, List[str]]],
        List[str],
    ]:
        """Load and classify locked hashes once for legacy and exact planning."""
        if not node.asset_hashes:
            return [], [], [], []

        assets: List[LocalAsset] = (
            self._db.query(LocalAsset)
            .filter(
                LocalAsset.file_hash.in_(node.asset_hashes),
                LocalAsset.is_deleted.is_(False),
            )
            .all()
        )
        hash_order = {h: i for i, h in enumerate(node.asset_hashes)}
        assets.sort(
            key=lambda asset: hash_order.get(
                str(getattr(asset, "file_hash", "") or ""), 999
            )
        )

        x_track: List[Tuple[LocalAsset, List[str]]] = []
        y_from_hash: List[Tuple[LocalAsset, List[str]]] = []
        warnings: List[str] = []
        for asset in assets:
            axis_type = _axis_type_for_asset(asset)
            matched = _intersect_tags(asset, node.semantic_tags)
            if axis_type in ("X_BASE", "X_STRUCTURE"):
                x_track.append((asset, matched))
            elif axis_type == "Y_LAYER":
                y_from_hash.append((asset, matched))
            else:
                warnings.append(
                    "locked 模式：hash 命中素材 "
                    f"id={asset.id} type={asset.asset_type!r} "
                    "未在 ASSET_REGISTRY 中定义 axis_type，已跳过。"
                )
        return assets, x_track, y_from_hash, warnings

    def _locked_main_candidate_assets(
        self,
        node: DSLBeatNode,
        *,
        hash_assets: Optional[List[LocalAsset]] = None,
        x_track: Optional[List[Tuple[LocalAsset, List[str]]]] = None,
    ) -> List[Tuple[LocalAsset, List[str]]]:
        if hash_assets is None or x_track is None:
            hash_assets, x_track, _y_from_hash, _warnings = (
                self._load_locked_hash_assets(node)
            )
        if x_track:
            return list(x_track)

        # Preserve legacy parity: semantic fallback only runs when at least one
        # locked hash resolved (for example a physical BGM) but none was main-X.
        if not hash_assets or not node.semantic_tags:
            return []
        x_video_types = [
            asset_type
            for asset_type, registry in ASSET_REGISTRY.items()
            if registry.get("axis_type") in ("X_BASE", "X_STRUCTURE")
        ]
        fallback = self._query_by_tags(
            tags=node.semantic_tags,
            asset_types=x_video_types,
            limit=5,
        )
        return _score_candidates(
            fallback,
            user_hard_tags=self._user_hard_tags,
            request_tags=node.semantic_tags,
        )

    def _match_explicit_main(
        self,
        candidates: List[Tuple[LocalAsset, List[str]]],
        selection: MainVisualCandidate,
        node: DSLBeatNode,
    ) -> Tuple[LocalAsset, List[str]]:
        matches = [
            pair
            for pair in candidates
            if cast(int, pair[0].id) == selection.asset_id
            and normalize_file_hash(getattr(pair[0], "file_hash", ""))
            == selection.file_hash
        ]
        if len(matches) != 1:
            raise MainVisualSelectionMismatch(
                "PLANNER_SELECTION_MISMATCH: Beat "
                f"{node.beat!r} candidate asset_id={selection.asset_id} "
                f"hash={selection.file_hash!r} is not uniquely resolver-valid"
            )
        return matches[0]

    def _discover_main_visual_assets(
        self,
        node: DSLBeatNode,
    ) -> List[Tuple[LocalAsset, List[str]]]:
        if node.address_mode == "locked":
            hash_assets, x_track, _y_from_hash, _warnings = (
                self._load_locked_hash_assets(node)
            )
            return self._locked_main_candidate_assets(
                node,
                hash_assets=hash_assets,
                x_track=x_track,
            )
        if node.address_mode == "smart" and node.semantic_tags:
            _ranked, main_candidates, _is_fallback = self._smart_candidate_assets(
                node,
                enumerate_fallback=True,
            )
            return main_candidates
        return []

    def _resolve_locked(
        self,
        node: DSLBeatNode,
        *,
        explicit_main: Optional[MainVisualCandidate] = None,
    ) -> BeatCompilationResult:
        """Resolve locked layers, optionally forcing one discovered main-X asset."""
        warnings: List[str] = []
        layers: List[ResolvedLayer] = []
        next_layer_idx = 0
        seen_y_identities: set[Tuple[str, str]] = set()

        if node.asset_hashes:
            hash_assets, x_track, y_from_hash, partition_warnings = (
                self._load_locked_hash_assets(node)
            )
            warnings.extend(partition_warnings)
            if not hash_assets:
                if explicit_main is not None:
                    raise MainVisualSelectionMismatch(
                        "PLANNER_SELECTION_MISMATCH: Beat "
                        f"{node.beat!r} locked selection is no longer resolver-valid"
                    )
                warnings.append(
                    f"locked 模式：asset_hashes={node.asset_hashes} 在素材库中无匹配记录。"
                )
            else:
                main_candidates = self._locked_main_candidate_assets(
                    node,
                    hash_assets=hash_assets,
                    x_track=x_track,
                )
                chosen: Optional[Tuple[LocalAsset, List[str]]] = None
                if explicit_main is not None:
                    chosen = self._match_explicit_main(main_candidates, explicit_main, node)
                elif x_track:
                    chosen = random.choice(x_track) if len(x_track) > 1 else x_track[0]
                elif main_candidates:
                    chosen = main_candidates[0]

                if chosen is not None:
                    asset, matched = chosen
                    layers.append(
                        _make_layer(layer_index=0, asset=asset, matched_tags=matched)
                    )
                    next_layer_idx = 1
                    logger.info(
                        "[DSLParser] locked X轴%s命中 layer=0 asset_id=%d "
                        "axis_type=%s hash=%s…",
                        "显式" if explicit_main is not None else "锁定",
                        asset.id,
                        _axis_type_for_asset(asset),
                        normalize_file_hash(getattr(asset, "file_hash", ""))[:8],
                    )
                elif not x_track and node.semantic_tags:
                    warnings.append(
                        f"locked 模式：asset_hashes 中无视频素材，"
                        f"且 semantic_tags={node.semantic_tags} "
                        "也未在素材库命中可用视频，主视频轨将为空。"
                    )

                if next_layer_idx == 0:
                    next_layer_idx = 1
                next_layer_idx = _append_unique_y_layers(
                    layers,
                    y_from_hash,
                    next_layer_idx=next_layer_idx,
                    seen_identities=seen_y_identities,
                )
        else:
            if explicit_main is not None:
                raise MainVisualSelectionMismatch(
                    f"PLANNER_SELECTION_MISMATCH: Beat {node.beat!r} has no locked hashes"
                )
            warnings.append("locked 模式：asset_hashes 为空，跳过 X 轴锁定。")

        # Y resolution remains independent of the selected main visual.
        if node.semantic_tags:
            y_assets = self._query_by_tags(
                tags=node.semantic_tags,
                asset_types=_y_layer_asset_types(),
                limit=5,
            )
            if next_layer_idx == 0:
                next_layer_idx = 1
            next_layer_idx = _append_unique_y_layers(
                layers,
                y_assets,
                next_layer_idx=next_layer_idx,
                seen_identities=seen_y_identities,
            )

        _apply_layout_hints(layers, node)
        resolved = any(layer.layer_index == 0 for layer in layers) or bool(layers)
        return BeatCompilationResult(
            beat=node.beat,
            role=node.role,
            address_mode="locked",
            layers=layers,
            resolved=resolved,
            warnings=warnings,
            script_text=node.script_text,
        )

    # ================================================================ #
    # 模式 B：smart — 智能抽卡寻址                                       #
    # ================================================================ #

    def _smart_fallback_query(self):
        """Build the shared safe-shot eligibility query."""
        return (
            self._db.query(LocalAsset)
            .filter(
                LocalAsset.asset_type.in_(["video", "scene_master_video"]),
                or_(
                    LocalAsset.tags.like("%通用空镜%"),
                    LocalAsset.tags.like("%B-Roll%"),
                ),
                LocalAsset.is_deleted.is_(False),
                LocalAsset.is_exhausted.is_(False),
            )
            .order_by(func.random())
        )

    def _query_smart_fallback_assets(
        self,
        *,
        enumerate_all: bool,
    ) -> List[LocalAsset]:
        """Fetch one legacy fallback or enumerate the exact-planner space."""
        query = self._smart_fallback_query()
        if enumerate_all:
            return query.all()
        first = query.first()
        return [first] if first is not None else []

    def _smart_candidate_assets(
        self,
        node: DSLBeatNode,
        *,
        enumerate_fallback: bool,
    ) -> tuple[
        List[Tuple[LocalAsset, List[str]]],
        List[Tuple[LocalAsset, List[str]]],
        bool,
    ]:
        """Return ranked assets, eligible main-X assets, and fallback state."""
        tagged = self._query_by_tags(
            tags=node.semantic_tags,
            asset_types=None,
            limit=20,
        )
        if tagged:
            ranked = _score_candidates(
                tagged,
                user_hard_tags=self._user_hard_tags,
                request_tags=node.semantic_tags,
            )
            main_candidates = [
                pair
                for pair in ranked
                if _axis_type_for_asset(pair[0]) in ("X_BASE", "X_STRUCTURE")
            ]
            return ranked, main_candidates, False

        fallback = [
            (asset, [])
            for asset in self._query_smart_fallback_assets(
                enumerate_all=enumerate_fallback
            )
        ]
        return fallback, fallback, True

    def _resolve_smart(
        self,
        node: DSLBeatNode,
        *,
        explicit_main: Optional[MainVisualCandidate] = None,
    ) -> BeatCompilationResult:
        """Resolve Smart layers, optionally forcing one discovered main-X asset."""
        warnings: List[str] = []
        layers: List[ResolvedLayer] = []

        if not node.semantic_tags:
            if explicit_main is not None:
                raise MainVisualSelectionMismatch(
                    f"PLANNER_SELECTION_MISMATCH: Beat {node.beat!r} has no smart tags"
                )
            warnings.append("smart 模式：semantic_tags 为空，无法执行智能匹配。")
            return BeatCompilationResult(
                beat=node.beat,
                role=node.role,
                address_mode="smart",
                layers=[],
                resolved=False,
                warnings=warnings,
                script_text=node.script_text,
            )

        ranked, main_candidates, is_fallback = self._smart_candidate_assets(
            node,
            enumerate_fallback=explicit_main is not None,
        )
        chosen: Optional[Tuple[LocalAsset, List[str]]] = None
        if explicit_main is not None:
            chosen = self._match_explicit_main(main_candidates, explicit_main, node)
        elif main_candidates:
            chosen = main_candidates[0]

        if is_fallback:
            warnings.append(
                f"smart 模式：semantic_tags={node.semantic_tags} 未命中任何素材，"
                "尝试安全空镜兜底..."
            )
            if chosen is not None:
                fallback_asset, matched = chosen
                warnings.append(
                    f"已兜底安全空镜（asset_id={fallback_asset.id}），"
                    "建议补充素材库或校正 semantic_tags。"
                )
                layer = _make_layer(
                    layer_index=0,
                    asset=fallback_asset,
                    matched_tags=matched,
                )
                layers = [layer]
                _apply_layout_hints(layers, node)
                return BeatCompilationResult(
                    beat=node.beat,
                    role=node.role,
                    address_mode="smart",
                    layers=layers,
                    resolved=True,
                    warnings=warnings,
                    script_text=node.script_text,
                )

            warnings.append(
                "严重异常：素材库标签未命中，且不存在可用安全空镜（通用空镜/B-Roll）。"
                "请向素材库添加兜底素材后重试。"
            )
            return BeatCompilationResult(
                beat=node.beat,
                role=node.role,
                address_mode="smart",
                layers=[],
                resolved=False,
                warnings=warnings,
                script_text=node.script_text,
            )

        x_assigned = False
        y_index = 1
        seen_y_identities: set[Tuple[str, str]] = set()
        chosen_id = cast(int, chosen[0].id) if chosen is not None else None
        for asset, matched in ranked:
            axis_type = _axis_type_for_asset(asset)
            if (
                not x_assigned
                and axis_type in ("X_BASE", "X_STRUCTURE")
                and cast(int, asset.id) == chosen_id
            ):
                layers.insert(
                    0,
                    _make_layer(layer_index=0, asset=asset, matched_tags=matched),
                )
                x_assigned = True
            elif axis_type == "Y_LAYER":
                y_index = _append_unique_y_layers(
                    layers,
                    [(asset, matched)],
                    next_layer_idx=y_index,
                    seen_identities=seen_y_identities,
                )

        if not x_assigned:
            if explicit_main is not None:
                raise MainVisualSelectionMismatch(
                    f"PLANNER_SELECTION_MISMATCH: Beat {node.beat!r} main was not materialized"
                )
            warnings.append(
                "smart 模式：semantic_tags 命中了素材，但无可用的 X 轴素材（"
                "ASSET_REGISTRY 中 axis_type 为 X_BASE 或 X_STRUCTURE）。"
                "已将命中素材全部按序挂载为连续层。"
            )
            layers = []
            next_layer_idx = 0
            seen_y_identities.clear()
            for asset, matched in ranked:
                if _axis_type_for_asset(asset) == "Y_LAYER":
                    next_layer_idx = _append_unique_y_layers(
                        layers,
                        [(asset, matched)],
                        next_layer_idx=next_layer_idx,
                        seen_identities=seen_y_identities,
                    )
                else:
                    layers.append(
                        _make_layer(
                            layer_index=next_layer_idx,
                            asset=asset,
                            matched_tags=matched,
                        )
                    )
                    next_layer_idx += 1

        _apply_layout_hints(layers, node)
        return BeatCompilationResult(
            beat=node.beat,
            role=node.role,
            address_mode="smart",
            layers=layers,
            resolved=bool(layers),
            warnings=warnings,
            script_text=node.script_text,
        )

    # ================================================================ #
    # 内部查询工具                                                        #
    # ================================================================ #

    def _query_by_tags(
        self,
        tags: List[str],
        asset_types: List[str] | None,
        limit: int = 20,
    ) -> List[Tuple[LocalAsset, List[str]]]:
        """
        查询 LocalAsset 表，Python 侧过滤 tags 列（SQLite JSON 字段）。

        返回 (asset, matched_tags) 元组列表，只返回至少命中一个标签的素材。
        asset_types=None 时不限制素材类型。
        """
        query = self._db.query(LocalAsset).filter(
            LocalAsset.is_exhausted.is_(False),
            LocalAsset.is_deleted.is_(False),
        )
        if asset_types:
            query = query.filter(LocalAsset.asset_type.in_(asset_types))

        # 按 usage_count 升序预排序，减少 Python 侧打分工作量
        candidates: List[LocalAsset] = (
            query.order_by(LocalAsset.usage_count.asc()).limit(200).all()
        )

        results: List[Tuple[LocalAsset, List[str]]] = []
        target_set = {t.lstrip("#").lower() for t in tags}

        for asset in candidates:
            asset_tags = asset.tags or []
            normalized = {t.lstrip("#").lower() for t in asset_tags}
            matched = list(target_set & normalized)
            if matched:
                results.append((asset, matched))
            if len(results) >= limit:
                break

        return results


# ================================================================== #
# 模块级纯函数工具                                                      #
# ================================================================== #


def _make_layer(
    layer_index: int,
    asset: LocalAsset,
    matched_tags: List[str],
) -> ResolvedLayer:
    """将 ORM 实体转换为 ResolvedLayer Schema。

    text_template 类型资产携带 manifest（含 content_matrix），
    供下游适配器和 FFmpeg 渲染器提取多语种文本。
    """
    return ResolvedLayer(
        layer_index=layer_index,
        asset_id=cast(int, asset.id),
        file_path=str(asset.file_path),
        asset_type=str(asset.asset_type),
        file_hash=str(asset.file_hash),
        asset_name=str(asset.asset_name) if asset.asset_name is not None else None,
        matched_tags=matched_tags,
        manifest=dict(asset.manifest) if getattr(asset, "manifest", None) else None,
    )


def _y_asset_identity(asset: LocalAsset) -> Tuple[str, str]:
    """Return the stable per-Beat identity for one Y-layer media asset."""
    normalized_hash = normalize_file_hash(getattr(asset, "file_hash", ""))
    if normalized_hash:
        return "file_hash", normalized_hash
    return "asset_id", str(getattr(asset, "id", ""))


def _append_unique_y_layers(
    layers: List[ResolvedLayer],
    candidates: Sequence[Tuple[LocalAsset, List[str]]],
    *,
    next_layer_idx: int,
    seen_identities: set[Tuple[str, str]],
) -> int:
    """Append first-seen Y assets in stable order and keep indexes contiguous."""
    for asset, matched in candidates:
        identity = _y_asset_identity(asset)
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        layers.append(
            _make_layer(
                layer_index=next_layer_idx,
                asset=asset,
                matched_tags=matched,
            )
        )
        next_layer_idx += 1
    return next_layer_idx


def _apply_layout_hints(layers: List[ResolvedLayer], node: DSLBeatNode) -> None:
    """Apply DSL asset-hash layout hints to resolved layers in-place."""
    hints = getattr(node, "layout_hints", None) or {}
    if not hints:
        return

    for layer in layers:
        hint = hints.get(layer.file_hash)
        if hint:
            layer.layout = hint


def _intersect_tags(asset: LocalAsset, request_tags: List[str]) -> List[str]:
    """计算素材已有标签与请求标签的交集（统一忽略 # 前缀 & 大小写）。"""
    asset_set = {t.lstrip("#").lower() for t in (asset.tags or [])}
    request_set = {t.lstrip("#").lower() for t in request_tags}
    return list(asset_set & request_set)


def _score_candidates(
    candidates: List[Tuple[LocalAsset, List[str]]],
    *,
    user_hard_tags: Optional[List[str]] = None,
    request_tags: Optional[List[str]] = None,
) -> List[Tuple[LocalAsset, List[str]]]:
    """
    Smart 2.0 高维抽卡打分引擎（硬约束一票否决 + 4维权重洗牌）：

    Recall Phase — 硬约束一票否决：
      计算当前 Beat 的硬约束交集
        hard_veto_tags = set(request_tags) ∩ set(user_hard_tags)
      素材的 tags 必须完整包含 hard_veto_tags，否则直接从候选池剔除。
      若无硬约束（交集为空），所有候选照常进入 Ranking Phase。

    Ranking Phase — 4维排序 key（升序，越小越优先）：
      (-soft_match_count,          # 软标签命中越多越优先（负号反转）
       1 if is_exhausted else 0,   # 惩罚已耗尽素材
       int(usage_count),           # 使用越少越优先（防疲劳）
       random.random())            # 随机熵：打破并发克隆，保证矩阵多样性
    """
    # ── Recall Phase ─────────────────────────────────────────────────────── #
    hard_veto_tags: set[str] = set()
    if user_hard_tags and request_tags:
        normalized_hard = {t.lstrip("#").lower() for t in user_hard_tags}
        normalized_req  = {t.lstrip("#").lower() for t in request_tags}
        hard_veto_tags  = normalized_hard & normalized_req

    if hard_veto_tags:
        survivors: List[Tuple[LocalAsset, List[str]]] = []
        for asset, matched in candidates:
            asset_tag_set = {t.lstrip("#").lower() for t in (asset.tags or [])}
            if hard_veto_tags.issubset(asset_tag_set):
                survivors.append((asset, matched))
        candidates = survivors

    # ── Ranking Phase ─────────────────────────────────────────────────────── #
    def _score(pair: Tuple[LocalAsset, List[str]]) -> Tuple[int, int, int, float]:
        asset, matched = pair
        soft_match_count = len(matched)
        return (
            -soft_match_count,
            1 if bool(asset.is_exhausted) else 0,
            cast(int, asset.usage_count) if asset.usage_count is not None else 0,
            random.random(),
        )

    return sorted(candidates, key=_score)
