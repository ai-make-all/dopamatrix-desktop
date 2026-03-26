"""
AntiDupNode — 防封/去重节点 (Phase 4)

职责：
  位于 AssemblyNode 之后、FFmpegCompositorNode 之前。
  遍历 Timeline 中所有视频 ClipItem，随机注入微量 FFmpeg 防查重滤镜，
  使每个批次视频在底层像素层面产生微小差异，规避平台内容哈希指纹检测。

扰动策略（人眼不可察，机器无法哈希匹配）：
  视觉扰动：eq 滤镜
    - brightness: 随机范围 [-0.02, +0.02]（默认值 0，正值增亮）
    - saturation: 随机范围 [0.98, 1.02] （默认值 1.0）
  时间扰动：atempo 滤镜
    - 播放速度: 随机范围 [0.99, 1.01]（默认值 1.0，几乎不影响节奏感知）

数据流：
  读取 → context.assets["timeline"]   (AssemblyNode 构建的 Timeline 对象)
  修改 → Timeline 内所有视频 Clip 的 .effects 列表（原地追加，不替换）
  写回 → context.assets["timeline"]   (修改后的 Timeline)

注意：
  - 本节点只操作 timeline.tracks 中的视频 Clip，不处理 AudioTrack。
  - 每次执行时随机种子不固定，保证每次批量运行结果唯一。
  - 若 Context 中无 timeline，静默跳过（不报错）。
"""

import random

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.logger import logger
from src.core.timeline import Timeline


class AntiDupNode(BaseNode):
    """
    防封/去重节点。

    对 Timeline 中每个视频 Clip 独立随机注入微量 FFmpeg 滤镜，
    从底层像素和时序层面产生扰动，破坏平台重复内容检测机制。

    扰动参数范围（超参数，可通过构造器调整）：
        brightness_range: eq 滤镜亮度调整范围，默认 (-0.02, 0.02)
        saturation_range: eq 滤镜饱和度调整范围，默认 (0.98, 1.02)
        tempo_range:      atempo 滤镜速度调整范围，默认 (0.99, 1.01)
    """

    def __init__(
        self,
        name: str = "AntiDupNode",
        brightness_range: tuple[float, float] = (-0.02, 0.02),
        saturation_range: tuple[float, float] = (0.98, 1.02),
        tempo_range: tuple[float, float] = (0.99, 1.01),
    ):
        super().__init__(name)
        self._brightness_range = brightness_range
        self._saturation_range = saturation_range
        self._tempo_range = tempo_range

    # ------------------------------------------------------------------
    # 扰动值生成器
    # ------------------------------------------------------------------

    def _gen_eq_filter(self) -> str:
        """
        生成随机 eq 滤镜字符串（视觉扰动）。

        返回格式：'eq=brightness=0.013:saturation=1.008'
        FFmpeg eq 滤镜文档：https://ffmpeg.org/ffmpeg-filters.html#eq
        """
        brightness = random.uniform(*self._brightness_range)
        saturation = random.uniform(*self._saturation_range)
        return f"eq=brightness={brightness:.4f}:saturation={saturation:.4f}"

    def _gen_atempo_filter(self) -> str:
        """
        生成随机视频时间扰动滤镜字符串（合并版，减少 setpts 调用次数）。

        【优化说明】——任务3 滤镜合并：
          原先 compositor 归一化管道已含 setpts=PTS-STARTPTS（归零），
          本节点再单独追加 setpts=factor*PTS 会造成两步 setpts 叠加。
          现改为单步合并表达式：setpts=(PTS-STARTPTS)*factor
            - 同时完成 PTS 归零 + 速度微扰，减少一个滤镜节点
            - STARTPTS 为当前片段首帧 PTS，保证片段内时序连续

        返回格式：'setpts=(PTS-STARTPTS)*0.99128'（示例值）

        说明：factor = 1/tempo
          tempo=1.01（加速1%） → factor ≈ 0.99010  → setpts=(PTS-STARTPTS)*0.99010
          tempo=0.99（减速1%） → factor ≈ 1.01010  → setpts=(PTS-STARTPTS)*1.01010
        """
        # setpts 乘数 = 1/tempo（tempo > 1 加速 → setpts < 1）
        tempo = random.uniform(*self._tempo_range)
        pts_factor = 1.0 / tempo
        return f"setpts=(PTS-STARTPTS)*{pts_factor:.5f}"

    # ------------------------------------------------------------------
    # 节点执行入口
    # ------------------------------------------------------------------

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        """
        遍历 Timeline 所有视频 Track 的所有 Clip，
        为每个 Clip 独立生成并追加防查重滤镜。

        步骤：
          1. 读取 context.assets["timeline"]
          2. 遍历所有 Track → 所有 Clip
          3. 对每个 Clip 追加 eq 滤镜（视觉扰动）和 setpts 滤镜（时间扰动）
          4. Timeline 原地修改，无需额外写回（Python 对象引用）
        """
        timeline: Timeline = context.get_asset("timeline")

        if not timeline:
            self.log("Warning: no 'timeline' in Context, skipping anti-dup injection.")
            return context

        total_tracks = len(timeline.tracks)
        if total_tracks == 0:
            self.log("Warning: Timeline has no video tracks, skipping.")
            return context

        self.log(
            f"Injecting anti-dup filters into {total_tracks} video track(s)..."
        )

        total_clips = 0
        for t_idx, track in enumerate(timeline.tracks):
            for clip in track.clips:
                eq_filter = self._gen_eq_filter()
                pts_filter = self._gen_atempo_filter()

                # 追加（不替换）滤镜，保留已有 effects
                clip.effects.append(eq_filter)
                clip.effects.append(pts_filter)
                total_clips += 1

                self.log(
                    f"  [Track {t_idx}] {clip.file_path!r}: "
                    f"effects={clip.effects}"
                )

        self.log(
            f"Anti-dup injection complete: {total_clips} clip(s) processed across "
            f"{total_tracks} track(s). Filters: eq (brightness/saturation) + setpts (tempo)."
        )

        return context
