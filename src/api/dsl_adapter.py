"""
src/api/dsl_adapter.py
——————————————————————————————————————————————————————————————————————
DSL 适配器：CompilationPlan → Timeline  (Phase 5.1)

将 DSLParserNode 输出的 CompilationPlan 渲染蓝图转换为
FFmpegCompositorNode 所需的 Timeline / Track / Clip 三层对象结构。

映射规则
─────────────────────────────────────────────────────────────────────
  layer_index == 0             → main_v_track  (track_type="video")
                                 concat 管线按 Track 内 clip 顺序拼接

  layer_index >  0
    asset_type in audio types  → AudioTrack（bgm / sfx）
    其余（sticker, logo…）     → 独立 overlay Track（track_type="overlay"）
                                 每个 Track 存放 1 个 Clip，
                                 start_time 对齐主轨渲染窗口

时间分配策略
─────────────────────────────────────────────────────────────────────
  beat_duration = target_duration / max(resolved_beats, 1)
  beat_start    = beat_index × beat_duration
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.timeline import AudioTrack, Clip, Timeline, Track

if TYPE_CHECKING:
    from src.api.schemas import CompilationPlan

logger = logging.getLogger(__name__)

_AUDIO_ASSET_TYPES: frozenset[str] = frozenset({"audio_bgm", "audio_sfx"})
_BGM_TYPE = "audio_bgm"
_TEXT_ASSET_TYPE = "text_template"


def compile_plan_to_timeline(
    plan: "CompilationPlan",
    target_duration: int = 15,
) -> Timeline:
    """
    将 CompilationPlan 渲染蓝图适配为 Timeline 对象。

    主轨（layer_index == 0）的所有 Clip 聚合到同一个 main_v_track，
    由 FFmpegCompositorNode._build_filtergraph 的 concat 管线按顺序拼接。

    叠加层（layer_index > 0）每个 Clip 独占一个 Track，通过
    overlay 管线的 enable='between(t,start,end)' 控制显示时间窗口。

    Args:
        plan:            DSLParserNode 输出的编译蓝图。
        target_duration: 目标视频总时长（秒），默认 15s。

    Returns:
        已组装的 Timeline，可直接通过 context.set_asset("timeline", timeline)
        注入 WorkflowContext，供 FFmpegCompositorNode.execute() 消费。
    """
    timeline = Timeline()

    # z_index=0 保证 main_v_track 始终排在所有 overlay 轨道之下
    main_v_track = Track(name="main_video", z_index=0, track_type="video")
    overlay_z = 1   # 每个 overlay Track 独占递增的 z_index

    n_beats = len(plan.beats)
    beat_duration: float = target_duration / max(n_beats, 1)

    logger.info(
        "[DSLAdapter] 开始适配 plan → Timeline: beats=%d target_duration=%ds beat_duration=%.2fs",
        n_beats, target_duration, beat_duration,
    )

    for beat_idx, beat_result in enumerate(plan.beats):
        if not beat_result.resolved or not beat_result.layers:
            logger.debug(
                "[DSLAdapter] beat[%d]=%s 未解析，跳过",
                beat_idx, beat_result.beat,
            )
            continue

        beat_start: float = beat_idx * beat_duration

        # 保证 layer 按 layer_index 升序处理（主轴优先）
        for layer in sorted(beat_result.layers, key=lambda lyr: lyr.layer_index):
            # text_template 是虚拟资产（virtual://...），直接走 text_overlay 分支，
            # 无需 file_path 物理存在性校验。其他类型仍做空值防呆。
            if layer.asset_type == _TEXT_ASSET_TYPE:
                # 三级优先级：DSL layout > manifest default_position > 系统默认 center
                text_position = (
                    layer.layout
                    or (layer.manifest or {}).get("default_position")
                    or "center"
                )
                text_track = Track(
                    name=f"text_b{beat_idx}_l{layer.layer_index}",
                    z_index=overlay_z,
                    track_type="text_overlay",
                )
                text_track.add_clip(
                    Clip(
                        file_path=layer.file_path,
                        start_time=beat_start,
                        duration=beat_duration,
                        manifest=layer.manifest,
                        beat_index=beat_idx,
                        layout=text_position,
                    )
                )
                timeline.add_track(text_track)
                overlay_z += 1
                logger.debug(
                    "[DSLAdapter] beat[%d] → text_overlay Track(z=%d) asset_id=%d "
                    "layout=%r manifest_keys=%s",
                    beat_idx, overlay_z - 1, layer.asset_id, text_position,
                    list((layer.manifest or {}).keys()),
                )
                continue

            if not layer.file_path:
                logger.warning(
                    "[DSLAdapter] beat[%d] layer[%d] file_path 为空，跳过",
                    beat_idx, layer.layer_index,
                )
                continue

            if layer.layer_index == 0:
                # ── X 轴主视频 ────────────────────────────────────────────
                # start_time 固定 0.0：concat 管线按 clip 在 Track 内的插入顺序
                # 自动拼接，无需手动指定全局偏移。beat_index 供渲染引擎后期
                # 绑定（Late-Binding）真实物理时长时定位该 Beat 在全局时间线的位置。
                main_v_track.add_clip(
                    Clip(
                        file_path=layer.file_path,
                        start_time=0.0,
                        duration=beat_duration,
                        beat_index=beat_idx,
                    )
                )
                logger.debug(
                    "[DSLAdapter] beat[%d] → main_v_track: %s",
                    beat_idx, layer.file_path,
                )

            elif layer.asset_type in _AUDIO_ASSET_TYPES:
                # ── 音频叠加层 → AudioTrack ───────────────────────────────
                audio_type = "bgm" if layer.asset_type == _BGM_TYPE else "sfx"
                audio_track = AudioTrack(
                    name=layer.asset_name or f"audio_b{beat_idx}_l{layer.layer_index}",
                    audio_type=audio_type,
                )
                audio_track.add_clip(
                    Clip(
                        file_path=layer.file_path,
                        start_time=beat_start,
                        duration=beat_duration,
                        beat_index=beat_idx,
                    )
                )
                timeline.add_audio_track(audio_track)
                logger.debug(
                    "[DSLAdapter] beat[%d] → AudioTrack(%s) [%s]: %s",
                    beat_idx, audio_type, audio_track.name, layer.file_path,
                )

            else:
                # ── Y 轴视觉叠加层（sticker / logo）→ 独立 overlay Track ─
                # 每个 overlay Track 存放 1 个 Clip，与 _build_filtergraph
                # 的 "overlay 轨道通常只有 1 个 Clip" 约定严格对齐。
                # 三级优先级：DSL layout > manifest default_position > 系统默认 center
                overlay_position = (
                    layer.layout
                    or (layer.manifest or {}).get("default_position")
                    or "center"
                )
                overlay_track = Track(
                    name=f"overlay_b{beat_idx}_l{layer.layer_index}",
                    z_index=overlay_z,
                    track_type="overlay",
                )
                overlay_track.add_clip(
                    Clip(
                        file_path=layer.file_path,
                        start_time=beat_start,
                        duration=beat_duration,
                        beat_index=beat_idx,
                        layout=overlay_position,
                    )
                )
                timeline.add_track(overlay_track)
                overlay_z += 1
                logger.debug(
                    "[DSLAdapter] beat[%d] → overlay Track(z=%d) layout=%r: %s",
                    beat_idx, overlay_z - 1, overlay_position, layer.file_path,
                )

    # 主轨最后添加，让 timeline.add_track 的 z_index 排序不受影响
    if main_v_track.clips:
        timeline.add_track(main_v_track)
        logger.info(
            "[DSLAdapter] main_v_track: %d clips, %d overlay tracks, %d audio tracks",
            len(main_v_track.clips),
            sum(1 for t in timeline.tracks if t.track_type == "overlay"),
            len(timeline.audio_tracks),
        )
    else:
        logger.warning("[DSLAdapter] 主视频轨为空——所有 beat 均未解析或缺失 layer_index==0 素材。")

    return timeline
