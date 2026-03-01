"""
AssetSelectNode — Phase 3: 动态素材检索节点

职责：
  遍历 script_data 中的每个场景（scene），
  根据其 visual_prompt 调用素材提供商 API 检索并下载对应视频素材，
  将所有下载好的本地路径按场景顺序存入 context.assets["scene_clips"]，
  供 AssemblyNode 拼接使用。

数据流：
  读取 → context.assets["script_data"]      (ScriptGenNode 生成的分镜脚本)
  写入 → context.assets["scene_clips"]      (List[str] 按场景顺序的本地 .mp4 路径)

设计说明：
  - 采用依赖注入：构造器接受 BaseAssetProvider 实例，便于测试时替换 Mock 对象。
  - 单个场景下载失败时记录警告并跳过（不中断整条流水线）。
  - 若所有场景均下载失败，整体写入空列表，AssemblyNode 将自动降级到 bg_video_path。
"""

from typing import Optional

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.services.asset_provider import BaseAssetProvider, PexelsProvider


class AssetSelectNode(BaseNode):
    """
    动态素材检索节点。

    期望 Context 中存在：
        context.assets["script_data"]: dict
            ScriptGenNode 生成的分镜脚本，每个 scene 需包含：
              - visual_prompt: str   (场景画面描述，用作检索关键词)
              - duration:      float (场景时长秒数，用于素材筛选)

    执行后写入 Context：
        context.assets["scene_clips"]: list[str]
            按场景顺序的本地 .mp4 文件路径列表。
            若某个场景下载失败，该场景对应槽位会被跳过（列表长度可能 < 场景数）。

    构造参数：
        provider:    素材提供商实例（默认 PexelsProvider()）
        output_dir:  clips 下载目录（默认 "output/clips"）
    """

    def __init__(
        self,
        name: str = "AssetSelectNode",
        provider: Optional[BaseAssetProvider] = None,
        output_dir: str = "output/clips",
    ):
        super().__init__(name)
        # 懒加载：若 provider 未传入，在 execute 时才实例化（避免过早读取 env）
        self._provider = provider
        self._output_dir = output_dir

    def _get_provider(self) -> BaseAssetProvider:
        """获取素材提供商实例（懒加载）。"""
        if self._provider is None:
            self._provider = PexelsProvider(output_dir=self._output_dir)
        return self._provider

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        """
        执行素材检索流程：
          1. 读取 script_data，提取所有 scenes
          2. 遍历 scenes，为每个 scene 调用 provider.get_video_clip()
          3. 将下载路径列表写回 context.assets["scene_clips"]
        """
        # ── Step 1: 读取分镜脚本 ───────────────────────────────────────────
        script_data: dict = context.get_asset("script_data") or {}
        scenes = script_data.get("scenes", [])

        if not scenes:
            self.log("Warning: script_data has no scenes. Skipping asset selection.")
            context.set_asset("scene_clips", [])
            return context

        self.log(f"Starting asset selection for {len(scenes)} scene(s)...")

        # ── Step 2: 逐场景检索素材 ────────────────────────────────────────
        provider = self._get_provider()
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

        # ── Step 3: 写回 Context ──────────────────────────────────────────
        context.set_asset("scene_clips", scene_clips)

        success_count = len(scene_clips)
        self.log(
            f"Asset selection complete: {success_count} clip(s) downloaded, "
            f"{failed_count} scene(s) skipped. "
            f"scene_clips written to context.assets['scene_clips']."
        )

        if success_count == 0:
            self.log(
                "Warning: No clips were downloaded. "
                "AssemblyNode will fall back to bg_video_path."
            )

        return context
