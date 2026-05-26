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
from typing import List, Optional, Tuple, cast

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
    "sticker": {"axis_type": "Y_LAYER"},
    "logo": {"axis_type": "Y_LAYER"},
}


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
        # 缓存全局硬约束标签（规范化），供 _resolve_smart 内 _score_candidates 消费
        self._user_hard_tags: List[str] = list(getattr(payload, "user_hard_tags", None) or [])

        beat_results: List[BeatCompilationResult] = []
        unresolved: List[str] = []

        for beat_node in payload.timeline:
            result = self._resolve_beat(beat_node)
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

    def _resolve_beat(self, node: DSLBeatNode) -> BeatCompilationResult:
        """根据 address_mode 分发到对应寻址策略。"""
        logger.info(
            "[DSLParser] 解析入参 Beat=%s mode=%s hashes=%d tags=%s",
            node.beat,
            node.address_mode,
            len(node.asset_hashes),
            node.semantic_tags,
        )

        if node.address_mode == "locked":
            return self._resolve_locked(node)
        elif node.address_mode == "smart":
            return self._resolve_smart(node)
        else:
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
            )

    # ================================================================ #
    # 模式 A：locked — 精确锁定寻址                                      #
    # ================================================================ #

    def _resolve_locked(self, node: DSLBeatNode) -> BeatCompilationResult:
        """
        按 asset_hashes 列表精确锁定 X 轴主视频。
        若同时携带 semantic_tags，则并发查询 Y 轴叠加素材（由 ASSET_REGISTRY 动态界定）。

        多候选随机抽取：当 asset_hashes 携带多个 X 轴候选（备选池）时，
        使用 random.choice() 随机抽取一个作为本次变体的唯一主轴，
        避免并发变体因确定性排序而克隆到同一素材。
        """
        warnings: List[str] = []
        layers: List[ResolvedLayer] = []
        next_layer_idx = 0

        # ── 按 hash 命中：按 axis_type 分拨 X / Y ──────────────────── #
        if node.asset_hashes:
            x_assets = (
                self._db.query(LocalAsset)
                .filter(
                    LocalAsset.file_hash.in_(node.asset_hashes),
                    LocalAsset.is_deleted.is_(False),
                )
                .all()
            )
            if not x_assets:
                warnings.append(
                    f"locked 模式：asset_hashes={node.asset_hashes} 在素材库中无匹配记录。"
                )
            else:
                hash_order = {h: i for i, h in enumerate(node.asset_hashes)}
                x_assets.sort(
                    key=lambda a: hash_order.get(
                        str(getattr(a, "file_hash", "") or ""), 999
                    )
                )

                x_track: List[Tuple[LocalAsset, List[str]]] = []
                y_from_hash: List[Tuple[LocalAsset, List[str]]] = []

                for asset in x_assets:
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

                # 多候选备选池：随机抽取一个 X 轴主素材，打破并发克隆
                if len(x_track) > 1:
                    chosen_x = random.choice(x_track)
                    logger.info(
                        "[DSLParser] locked X轴备选池 %d 个候选，随机抽取 asset_id=%d",
                        len(x_track),
                        chosen_x[0].id,
                    )
                    x_track = [chosen_x]

                for asset, matched in x_track:
                    x_axis = _axis_type_for_asset(asset)
                    layers.append(
                        _make_layer(
                            layer_index=next_layer_idx,
                            asset=asset,
                            matched_tags=matched,
                        )
                    )
                    logger.info(
                        "[DSLParser] locked X轴锁定命中 layer=%d asset_id=%d "
                        "axis_type=%s hash=%s…",
                        next_layer_idx,
                        asset.id,
                        x_axis,
                        (str(getattr(asset, "file_hash", "") or ""))[:8],
                    )
                    next_layer_idx += 1

                # ── X 轴兜底：hash 列表里无视频素材时，用 semantic_tags 查 video ──
                # 场景：用户在战术板只把 BGM/SFX 锁定到 beat，导致 asset_hashes
                # 全部解析为 Y_LAYER；此时若携带 semantic_tags，则尝试以"智能模式"
                # 补全 X 轴视频，避免主视频轨为空。
                if next_layer_idx == 0 and node.semantic_tags:
                    x_video_types = [
                        t for t, v in ASSET_REGISTRY.items()
                        if v.get("axis_type") in ("X_BASE", "X_STRUCTURE")
                    ]
                    x_fallback = self._query_by_tags(
                        tags=node.semantic_tags,
                        asset_types=x_video_types,
                        limit=5,
                    )
                    if x_fallback:
                        scored_fb = _score_candidates(
                            x_fallback,
                            user_hard_tags=self._user_hard_tags,
                            request_tags=node.semantic_tags,
                        )
                        fb_asset, fb_matched = scored_fb[0]
                        layers.insert(
                            0,
                            _make_layer(
                                layer_index=0,
                                asset=fb_asset,
                                matched_tags=fb_matched,
                            ),
                        )
                        next_layer_idx = 1
                        logger.info(
                            "[DSLParser] locked X轴兜底命中 layer=0 asset_id=%d "
                            "axis_type=%s tags=%s（hashes 中无 X 轴视频）",
                            fb_asset.id,
                            _axis_type_for_asset(fb_asset),
                            fb_matched,
                        )
                    else:
                        warnings.append(
                            f"locked 模式：asset_hashes 中无视频素材，"
                            f"且 semantic_tags={node.semantic_tags} "
                            "也未在素材库命中可用视频，主视频轨将为空。"
                        )

                if next_layer_idx == 0:
                    next_layer_idx = 1

                for asset, matched in y_from_hash:
                    layers.append(
                        _make_layer(
                            layer_index=next_layer_idx,
                            asset=asset,
                            matched_tags=matched,
                        )
                    )
                    logger.info(
                        "[DSLParser] locked Y轴锁定命中 layer=%d asset_id=%d "
                        "type=%s tags=%s",
                        next_layer_idx,
                        asset.id,
                        asset.asset_type,
                        matched,
                    )
                    next_layer_idx += 1
        else:
            warnings.append("locked 模式：asset_hashes 为空，跳过 X 轴锁定。")

        # ── Y 轴：semantic_tags 并发查叠加素材（类型列表来自注册表）── #
        if node.semantic_tags:
            y_assets = self._query_by_tags(
                tags=node.semantic_tags,
                asset_types=_y_layer_asset_types(),
                limit=5,
            )
            if next_layer_idx == 0:
                next_layer_idx = 1
            for asset, matched in y_assets:
                layers.append(
                    _make_layer(
                        layer_index=next_layer_idx,
                        asset=asset,
                        matched_tags=matched,
                    )
                )
                logger.info(
                    "[DSLParser] locked Y轴锁定命中 layer=%d asset_id=%d tags=%s",
                    next_layer_idx,
                    asset.id,
                    matched,
                )
                next_layer_idx += 1

        resolved = any(lyr.layer_index == 0 for lyr in layers) or (len(layers) > 0)

        return BeatCompilationResult(
            beat=node.beat,
            role=node.role,
            address_mode="locked",
            layers=layers,
            resolved=resolved,
            warnings=warnings,
        )

    # ================================================================ #
    # 模式 B：smart — 智能抽卡寻址                                       #
    # ================================================================ #

    def _resolve_smart(self, node: DSLBeatNode) -> BeatCompilationResult:
        """
        按 semantic_tags 匹配素材，执行防疲劳打分逻辑：
          优先 usage_count 低 + is_exhausted=False 的素材作为 X 轴；
          其余命中项依次作为 Y 轴叠加层。
        """
        warnings: List[str] = []
        layers: List[ResolvedLayer] = []

        if not node.semantic_tags:
            warnings.append("smart 模式：semantic_tags 为空，无法执行智能匹配。")
            return BeatCompilationResult(
                beat=node.beat,
                role=node.role,
                address_mode="smart",
                layers=[],
                resolved=False,
                warnings=warnings,
            )

        # ── 查询所有类型素材，Python 侧统一打分 ──────────────────── #
        all_candidates = self._query_by_tags(
            tags=node.semantic_tags,
            asset_types=None,  # 不限类型，打分后再分拨
            limit=20,
        )

        if not all_candidates:
            warnings.append(
                f"smart 模式：semantic_tags={node.semantic_tags} 未命中任何素材，"
                "请检查素材库标签或放宽搜索条件。"
            )
            return BeatCompilationResult(
                beat=node.beat,
                role=node.role,
                address_mode="smart",
                layers=[],
                resolved=False,
                warnings=warnings,
            )

        # ── Smart 2.0：硬约束一票否决 + 4维打分排序 ──────────────── #
        scored = _score_candidates(
            all_candidates,
            user_hard_tags=self._user_hard_tags,
            request_tags=node.semantic_tags,
        )

        # ── 分拨 X 轴 / Y 轴（axis_type 来自 ASSET_REGISTRY）────────── #
        x_assigned = False
        y_index = 1

        for asset, matched in scored:
            axis_type = _axis_type_for_asset(asset)
            if not x_assigned and axis_type in ("X_BASE", "X_STRUCTURE"):
                layers.insert(
                    0,
                    _make_layer(layer_index=0, asset=asset, matched_tags=matched),
                )
                x_assigned = True
                logger.info(
                    "[DSLParser] Smart分发命中 X轴 asset_id=%d axis_type=%s "
                    "usage=%d tags=%s",
                    asset.id,
                    axis_type,
                    asset.usage_count,
                    matched,
                )
            elif axis_type == "Y_LAYER":
                layers.append(
                    _make_layer(layer_index=y_index, asset=asset, matched_tags=matched)
                )
                logger.info(
                    "[DSLParser] Smart分发命中 Y轴 layer=%d asset_id=%d "
                    "type=%s tags=%s",
                    y_index,
                    asset.id,
                    asset.asset_type,
                    matched,
                )
                y_index += 1

        if not x_assigned:
            warnings.append(
                "smart 模式：semantic_tags 命中了素材，但无可用的 X 轴素材（"
                "ASSET_REGISTRY 中 axis_type 为 X_BASE 或 X_STRUCTURE）。"
                "已将命中素材全部按序挂载为连续层。"
            )
            # 将命中的非 X 轴素材兜底挂入，layer_index 重新排序
            layers = [
                _make_layer(layer_index=i, asset=a, matched_tags=m)
                for i, (a, m) in enumerate(scored)
            ]

        return BeatCompilationResult(
            beat=node.beat,
            role=node.role,
            address_mode="smart",
            layers=layers,
            resolved=bool(layers),
            warnings=warnings,
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
    """将 ORM 实体转换为 ResolvedLayer Schema。"""
    return ResolvedLayer(
        layer_index=layer_index,
        asset_id=cast(int, asset.id),
        file_path=str(asset.file_path),
        asset_type=str(asset.asset_type),
        file_hash=str(asset.file_hash),
        asset_name=str(asset.asset_name) if asset.asset_name is not None else None,
        matched_tags=matched_tags,
    )


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
