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

import logging
import os
import random
from pathlib import Path
from typing import List, Optional, Union

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.services.asset_provider import BaseAssetProvider, LocalMatrixProvider, PexelsProvider

logger = logging.getLogger(__name__)


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

    # -- 1.0 MVP validation constants ----------------------------------
    # X-axis: video clip validation
    _ALLOWED_SUFFIXES    = {".mp4", ".mov"}       # format whitelist (lowercase)
    _MAX_FILE_SIZE_BYTES = 200 * 1024 * 1024      # hard cap: 200 MB
    # Y-axis: overlay PNG validation
    _ALLOWED_OVERLAY_SUFFIX  = ".png"             # only transparent PNGs
    _MAX_OVERLAY_SIZE_BYTES  = 5 * 1024 * 1024    # hard cap: 5 MB

    def _scan_user_asset_dir(
        self, asset_dir: str, total_duration: float
    ) -> Optional[List[str]]:
        """
        扫描用户通过 Tauri Dialog 选取的本地目录，收集符合条件的视频文件。

        1.0 MVP 校验防线：
          - 格式白名单：仅接受 .mp4 / .mov（忽略大小写）。
          - 体积红线：单文件超过 200 MB 则警告并跳过。
          - 零有效文件：扫描完毕后仍无合规文件，抛出 ValueError。

        采样策略：
          - 文件数量充足时，先随机打乱，再依序填满 total_duration；
          - 文件较少时，有放回重复抽取（循环补足）；
          - 目录不存在时，返回 None（触发 fallback 逻辑）。

        Args:
            asset_dir:      用户选取目录的绝对路径字符串。
            total_duration: 视频总时长（秒），用于估算所需素材数量。

        Returns:
            List[str] — 选取的本地视频绝对路径列表（可含重复）。

        Raises:
            ValueError — 扫描后发现 0 个合规视频文件。
        """
        p = Path(asset_dir)
        if not p.exists() or not p.is_dir():
            self.log(f"[Scan] ✗ Directory does not exist or is not a folder: {asset_dir}")
            return None

        # ── Step 1：收集全部普通文件（不预设后缀，由校验层决定取舍）──────────
        all_files: List[Path] = [f for f in p.iterdir() if f.is_file()]

        # ── Step 2：逐文件执行格式 + 体积校验 ───────────────────────────────
        valid_files: List[Path] = []
        for f in all_files:
            suffix = f.suffix.lower()

            # 格式校验
            if suffix not in self._ALLOWED_SUFFIXES:
                logger.warning(
                    "[Scan] ⚠️ 格式不符，已跳过：%s（仅支持 %s）",
                    f.name,
                    ", ".join(sorted(self._ALLOWED_SUFFIXES)),
                )
                continue

            # 体积校验
            try:
                size_bytes = os.path.getsize(f)
            except OSError as exc:
                logger.warning("[Scan] ⚠️ 无法读取文件大小，已跳过：%s — %s", f.name, exc)
                continue

            if size_bytes > self._MAX_FILE_SIZE_BYTES:
                size_mb = size_bytes / (1024 * 1024)
                logger.warning(
                    "[Scan] ⚠️ 文件超过 200MB 体积红线，已跳过：%s（%.1f MB）",
                    f.name, size_mb,
                )
                continue

            valid_files.append(f)

        # ── Step 3：零有效文件 → 直接抛出异常，终止流程 ──────────────────────
        if not valid_files:
            raise ValueError(
                "本地素材库中没有找到符合要求的有效视频"
                "（仅支持 mp4/mov，且单文件需小于 200MB）。"
            )

        self.log(
            f"[Scan] ✓ 校验通过 {len(valid_files)} 个视频文件（来自：'{asset_dir}'）。"
        )

        # ── Step 4：按总时长估算所需数量，随机有放回抽样 ──────────────────────
        AVG_CLIP_DURATION = 5.0
        needed = max(1, int(total_duration / AVG_CLIP_DURATION) + 1)

        shuffled = valid_files.copy()
        random.shuffle(shuffled)

        result: List[str] = []
        while len(result) < needed:
            result.extend(str(f) for f in shuffled)
        return result[:needed]

    def _scan_user_overlay_dir(self, overlay_dir: str) -> List[str]:
        """
        Scan user-supplied Y-axis local directory for valid PNG overlay assets.

        1.0 MVP guard-rails (Y-axis):
          - Format whitelist : only .png accepted (case-insensitive).
          - Size cap         : files > 5 MB are warned and skipped.
          - Zero valid files : raise ValueError so the pipeline stops cleanly.
          - Dir not found    : raise ValueError (user passed a bad path).

        Args:
            overlay_dir: Absolute path string of the user-chosen folder.

        Returns:
            List[str] of absolute paths to valid PNG files.

        Raises:
            ValueError when the directory is missing or zero qualifying PNGs exist.
        """
        p = Path(overlay_dir)
        if not p.exists() or not p.is_dir():
            raise ValueError(
                f"Y\u8f74\u7d20\u6750\u5e93\u9519\u8bef\uff1a\u76ee\u5f55\u4e0d\u5b58\u5728\u6216\u65e0\u6cd5\u8bbf\u95ee: {overlay_dir}\uff0c"
                "\u8bf7\u786e\u4fdd\u8def\u5f84\u6b63\u786e\u4e14\u6709\u8bfb\u53d6\u6743\u9650\u3002"
            )

        all_files: List[Path] = [f for f in p.iterdir() if f.is_file()]
        valid_pngs: List[Path] = []

        for f in all_files:
            suffix = f.suffix.lower()

            # Format check
            if suffix != self._ALLOWED_OVERLAY_SUFFIX:
                logger.warning(
                    "[Y-Scan] Skipping non-PNG file: %s (only .png transparent overlays allowed).",
                    f.name,
                )
                continue

            # Size check
            try:
                size_bytes = os.path.getsize(f)
            except OSError as exc:
                logger.warning("[Y-Scan] Cannot read file size, skipping: %s — %s", f.name, exc)
                continue

            if size_bytes > self._MAX_OVERLAY_SIZE_BYTES:
                size_mb = size_bytes / (1024 * 1024)
                logger.warning(
                    "[Y-Scan] PNG exceeds 5 MB cap, skipping: %s (%.1f MB).",
                    f.name, size_mb,
                )
                continue

            valid_pngs.append(f)

        if not valid_pngs:
            raise ValueError(
                "Y\u8f74\u7d20\u6750\u5e93\u9519\u8bef\uff1a\u672a\u627e\u5230\u6709\u6548\u7684\u900f\u660e PNG \u56fe\u7247\uff0c"
                "\u8bf7\u786e\u4fdd\u6587\u4ef6\u683c\u5f0f\u6b63\u786e\u4e14\u5c0f\u4e8e 5MB\u3002"
            )

        self.log(
            f"[Y-Scan] Validated {len(valid_pngs)} PNG file(s) from '{overlay_dir}'."
        )
        return [str(f) for f in valid_pngs]

    def _set_overlay_clips(
        self, context: WorkflowContext, pool_dir: str
    ) -> None:
        """
        Write Y-axis overlay assets (Logo + Sticker) into context.

        Priority:
          1. context.local_overlay_dir  -> user-supplied local PNG folder (strict validation)
          2. default pool LocalMatrixProvider -> mock fallback (graceful degradation)
        """
        # -- Priority 1: user-supplied local Y-axis directory ----------------
        if context.local_overlay_dir:
            self.log(
                f"[Y-Overlay] User local overlay dir detected: '{context.local_overlay_dir}'. "
                "Scanning PNG files..."
            )
            # ValueError propagates up through execute() and surfaces as a task error
            png_paths = self._scan_user_overlay_dir(context.local_overlay_dir)
            # First file -> logo; second file (if any) -> sticker; else reuse logo
            logo_path    = png_paths[0]
            sticker_path = png_paths[1] if len(png_paths) >= 2 else png_paths[0]
            context.set_asset("overlay_clips", {"logo": logo_path, "sticker": sticker_path})
            self.log(
                f"[Y-Overlay] User-dir mode: logo={logo_path}, "
                f"sticker={sticker_path}. Written to context.assets['overlay_clips']."
            )
            return

        # -- Priority 2: system default pool (graceful fallback) -------------
        try:
            local_provider = LocalMatrixProvider(pool_dir=pool_dir)
            logo_path = local_provider.get_overlay_logo()
            sticker_path = local_provider.get_overlay_sticker()
        except Exception as exc:
            self.log(f"[Y-Overlay] Failed to get overlay assets: {exc}. Setting to None.")
            logo_path, sticker_path = None, None

        context.set_asset("overlay_clips", {"logo": logo_path, "sticker": sticker_path})
        self.log(
            f"[Y-Overlay] Default-pool mode: logo={logo_path or 'None'}, "
            f"sticker={sticker_path or 'None'}. Written to context.assets['overlay_clips']."
        )



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

        优先级：
          1. context.local_asset_dir  → 用户通过 Tauri Dialog 选取的本地目录
          2. self._pool_dir           → 默认系统素材池（fallback）

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

        # ── 优先：用户桌面端传入的本地素材目录 ──────────────────────────────
        if context.local_asset_dir:
            self.log(
                f"[Local Mode] 📂 Tauri Asset Dir detected: '{context.local_asset_dir}'. "
                "Scanning for .mp4 / .mov files..."
            )
            scene_clips = self._scan_user_asset_dir(
                asset_dir=context.local_asset_dir,
                total_duration=total_duration,
            )
            if scene_clips is not None:
                context.set_asset("scene_clips", scene_clips)
                self.log(
                    f"[Local Mode] ✓ {len(scene_clips)} clip(s) from user dir selected "
                    f"(total ~{total_duration:.1f}s). Written to context.assets['scene_clips']."
                )
                # Y-overlay 仍从默认池获取；用户目录通常只含主视频素材
                self._set_overlay_clips(context, pool_dir=self._pool_dir)
                return context
            # 若用户目录扫描失败，发出警告并 fallback 到系统素材池
            self.log(
                f"[Local Mode] ⚠️ User asset dir invalid or empty. "
                "Falling back to default pool."
            )

        # ── 降级：系统默认素材池（LocalMatrixProvider） ──────────────────────
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

        self._set_overlay_clips(context, pool_dir=self._pool_dir)
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
