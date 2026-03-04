"""
AssetSelectNode — Phase 4 升级版：本地矩阵素材选择节点

职责：
  优先模式（LocalMatrixProvider）：
    读取 Context 中的 script_data，计算视频总时长，
    调用 LocalMatrixProvider.get_clips_for_duration() 从本地素材库随机抽取素材，
    将路径列表写入 context.assets["scene_clips"] 供 AssemblyNode 使用。

  降级模式（PexelsProvider）：
    若构建时显式传入 PexelsProvider 实例，则退回到逐场景关键词检索的原有逻辑，
    保持与 Phase 3 的向后兼容。

数据流：
  读取 → context.assets["script_data"]      (ScriptGenNode 生成的分镜脚本)
  写入 → context.assets["scene_clips"]      (List[str] 本地 .mp4 路径列表)

设计说明：
  - 采用依赖注入：构造器接受 provider 参数，默认 None（使用 LocalMatrixProvider）。
  - 本地模式下一次性按总时长抽取素材，不再逐场景处理，更适合矩阵批量生产场景。
  - Pexels 降级逻辑保持不变，方便测试与回归。
"""

from typing import Optional, Union

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.services.asset_provider import BaseAssetProvider, LocalMatrixProvider, PexelsProvider


class AssetSelectNode(BaseNode):
    """
    素材选择节点（Phase 4 升级版）。

    期望 Context 中存在：
        context.assets["script_data"]: dict
            ScriptGenNode 生成的分镜脚本。
            本地模式：仅用于计算 total_duration（所有 scene.duration 之和）。
            Pexels 模式：每个 scene 需含 visual_prompt 和 duration。

    执行后写入 Context：
        context.assets["scene_clips"]: list[str]
            本地 .mp4 文件路径列表（本地模式可含重复路径）。

    构造参数：
        provider:    素材提供商实例。
                     - None（默认）   → 使用 LocalMatrixProvider
                     - BaseAssetProvider 实例 → 使用 PexelsProvider（降级模式）
        pool_dir:    LocalMatrixProvider 的本地素材目录（默认 "assets/matrix_pool/x_main"）
        output_dir:  PexelsProvider 下载目录（降级模式使用，默认 "output/clips"）
    """

    def __init__(
        self,
        name: str = "AssetSelectNode",
        provider: Optional[BaseAssetProvider] = None,
        pool_dir: str = "assets/matrix_pool/x_main",
        output_dir: str = "output/clips",
    ):
        super().__init__(name)
        self._provider = provider       # None → 本地模式；BaseAssetProvider → Pexels 降级
        self._pool_dir = pool_dir
        self._output_dir = output_dir

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _calc_total_duration(self, script_data: dict) -> float:
        """计算所有 scene.duration 之和（秒）。"""
        scenes = script_data.get("scenes", [])
        return sum(float(s.get("duration", 0)) for s in scenes)

    # ------------------------------------------------------------------
    # 执行入口
    # ------------------------------------------------------------------

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        """
        执行素材选择：
          - 本地矩阵模式：按总时长从 LocalMatrixProvider 随机抽卡
          - Pexels 降级模式：逐场景关键词检索下载（原有逻辑）
        """
        script_data: dict = context.get_asset("script_data") or {}
        scenes = script_data.get("scenes", [])

        if not scenes:
            self.log("Warning: script_data has no scenes. Skipping asset selection.")
            context.set_asset("scene_clips", [])
            return context

        # ── 本地矩阵模式（默认）─────────────────────────────────────────
        if self._provider is None:
            return self._run_local_mode(context, script_data, scenes)

        # ── Pexels 降级模式（显式传入 provider 时触发）──────────────────
        return self._run_pexels_mode(context, scenes)

    # ------------------------------------------------------------------
    # 本地矩阵模式
    # ------------------------------------------------------------------

    def _run_local_mode(
        self, context: WorkflowContext, script_data: dict, scenes: list
    ) -> WorkflowContext:
        """
        【本地矩阵模式】：按脚本总时长，从本地素材池随机抽取一组视频。

        与 Pexels 模式的区别：
          - 不依赖网络
          - 一次性按总时长抽取，而非逐场景处理
          - 返回的路径列表可包含重复文件（有放回抽样）
        """
        total_duration = self._calc_total_duration(script_data)
        if total_duration <= 0:
            self.log("Warning: total_duration is 0. Skipping local asset selection.")
            context.set_asset("scene_clips", [])
            return context

        self.log(
            f"[Local Mode] {len(scenes)} scene(s), total duration: {total_duration:.1f}s. "
            f"Selecting clips from '{self._pool_dir}'..."
        )

        try:
            local_provider = LocalMatrixProvider(pool_dir=self._pool_dir)
            scene_clips = local_provider.get_clips_for_duration(target_duration=total_duration)
        except RuntimeError as exc:
            self.log(
                f"[Local Mode] ✗ LocalMatrixProvider failed: {exc}. "
                "scene_clips will be empty; AssemblyNode will fall back to bg_video_path."
            )
            context.set_asset("scene_clips", [])
            context.set_asset("overlay_clips", {"logo": None, "sticker": None})
            return context

        context.set_asset("scene_clips", scene_clips)
        self.log(
            f"[Local Mode] ✓ {len(scene_clips)} clip(s) selected "
            f"(total ~{total_duration:.1f}s). Written to context.assets['scene_clips']."
        )

        # ── Y 轴素材抽取：Logo + Sticker ─────────────────────────────────
        logo_path = local_provider.get_overlay_logo()
        sticker_path = local_provider.get_overlay_sticker()
        context.set_asset("overlay_clips", {"logo": logo_path, "sticker": sticker_path})
        self.log(
            f"[Local Mode] Y-overlay: logo={logo_path or 'None'}, "
            f"sticker={sticker_path or 'None'}. Written to context.assets['overlay_clips']."
        )

        return context


    # ------------------------------------------------------------------
    # Pexels 降级模式（向后兼容）
    # ------------------------------------------------------------------

    def _run_pexels_mode(self, context: WorkflowContext, scenes: list) -> WorkflowContext:
        """
        【Pexels 降级模式】：逐场景使用 visual_prompt 从 Pexels API 检索下载素材。
        与 Phase 3 实现保持原有逻辑不变。
        """
        self.log(
            f"[Pexels Mode] Starting asset selection for {len(scenes)} scene(s)..."
        )

        # 懒加载：若未传入 provider，使用 PexelsProvider（降级触发时 provider 一定非 None）
        provider = self._provider
        if provider is None:
            provider = PexelsProvider(output_dir=self._output_dir)

        scene_clips: list[str] = []
        failed_count = 0

        for idx, scene in enumerate(scenes, start=1):
            visual_prompt: str = scene.get("visual_prompt", "").strip()
            duration: int = max(1, int(float(scene.get("duration", 5))))

            if not visual_prompt:
                self.log(f"[Scene {idx}] No visual_prompt found, skipping.")
                failed_count += 1
                continue

            self.log(
                f"[Scene {idx}/{len(scenes)}] Searching: '{visual_prompt}' "
                f"(target duration: {duration}s)"
            )

            try:
                clip_path = provider.get_video_clip(
                    keyword=visual_prompt,
                    duration=duration,
                )
                scene_clips.append(clip_path)
                self.log(f"[Scene {idx}] ✓ Downloaded: {clip_path}")

            except RuntimeError as exc:
                self.log(f"[Scene {idx}] ✗ Failed ({exc}). Skipping this scene.")
                failed_count += 1

        context.set_asset("scene_clips", scene_clips)
        success_count = len(scene_clips)
        self.log(
            f"[Pexels Mode] Complete: {success_count} clip(s) downloaded, "
            f"{failed_count} scene(s) skipped. "
            f"scene_clips written to context.assets['scene_clips']."
        )

        if success_count == 0:
            self.log(
                "Warning: No clips downloaded. "
                "AssemblyNode will fall back to bg_video_path."
            )

        return context
