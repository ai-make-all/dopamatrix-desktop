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
        # Deprecated: No longer scanning directories
        return None

    def _scan_user_logo_dir(self, logo_dir: str) -> List[str]:
        # Deprecated: No longer scanning directories
        return []

    def _scan_user_sticker_dir(self, sticker_dir: str) -> List[str]:
        # Deprecated: No longer scanning directories
        return []

    def _set_overlay_clips(
        self, context: WorkflowContext, pool_dir: str
    ) -> None:
        """
        Y 轴双轨拆分：从数据库 `local_assets_inventory` 获取最少使用的 Logo 和 Sticker。
        如果没有，则回退到 LocalMatrixProvider 默认素材池。
        """
        logo_path = None
        sticker_path = None
        used_ids = context.assets.get("used_asset_ids", [])

        # 1. 尝试从数据库获取
        try:
            from src.api.database import SessionLocal
            from src.api.models import LocalAsset
            with SessionLocal() as db:
                logo_asset = db.query(LocalAsset).filter(
                    LocalAsset.asset_type == 'logo',
                    LocalAsset.is_exhausted == False
                ).order_by(LocalAsset.usage_count.asc()).first()
                if logo_asset:
                    logo_path = logo_asset.file_path
                    used_ids.append(logo_asset.id)
                    self.log(f"[Y-Logo] 数据库提取 ID={logo_asset.id}: {logo_path}")

                sticker_asset = db.query(LocalAsset).filter(
                    LocalAsset.asset_type == 'sticker',
                    LocalAsset.is_exhausted == False
                ).order_by(LocalAsset.usage_count.asc()).first()
                if sticker_asset:
                    sticker_path = sticker_asset.file_path
                    used_ids.append(sticker_asset.id)
                    self.log(f"[Y-Sticker] 数据库提取 ID={sticker_asset.id}: {sticker_path}")
        except Exception as exc:
            self.log(f"[Y-DB] 数据库查询 Y 轴素材失败，回退到默认池: {exc}")

        # 2. 默认池 fallback
        if logo_path is None or sticker_path is None:
            try:
                local_provider = LocalMatrixProvider(pool_dir=pool_dir)
                if logo_path is None:
                    logo_path = local_provider.get_overlay_logo()
                if sticker_path is None:
                    sticker_path = local_provider.get_overlay_sticker()
            except Exception as exc:
                self.log(f"[Y-Default] 默认池获取失败: {exc}")

        context.assets["used_asset_ids"] = used_ids
        context.set_asset("overlay_clips", {"logo": logo_path, "sticker": sticker_path})
        self.log(
            f"[Y-Overlay] logo={logo_path or 'None'}, sticker={sticker_path or 'None'} "
            f"→ context.assets['overlay_clips']"
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
        【本地矩阵模式】：按脚本总时长，从数据库 LocalAsset 表提取素材。
        基于防疲劳 LRU 算法抽取（usage_count 升序），抽取文件供拼装节点使用，
        并记录使用过的 ID 以便引擎终结时反写。
        """
        # 🎯 音频霸权时长控制 (Audio Hegemony Duration Control)
        target_lang = getattr(context, "test_language", "en") or "en"
        voice_audio = context.variants.get(target_lang, {}).get("voice_audio")
        
        total_duration = 0.0
        if voice_audio and os.path.exists(voice_audio):
            import subprocess
            try:
                # 使用 ffprobe 读取真实物理时长
                result = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", voice_audio],
                    capture_output=True, text=True, check=True
                )
                total_duration = float(result.stdout.strip())
                self.log(f"[Audio Hegemony] 从音频 {voice_audio} 获取真实时长 T={total_duration:.2f}s")
            except Exception as e:
                self.log(f"[Warning] ffprobe 获取音频时长失败：{e}。回退到脚本预估时长。")
                total_duration = self._calc_total_duration(script_data)
        else:
            self.log("[Warning] 未找到 voice_audio 或文件不存在。回退到脚本预估时长。")
            total_duration = self._calc_total_duration(script_data)

        if total_duration <= 0:
            self.log("Warning: total_duration is 0. Skipping local asset selection.")
            context.set_asset("scene_clips", [])
            return context

        target_duration = total_duration + 1.0

        AVG_CLIP_DURATION = 5.0
        original_needed = max(1, int(target_duration / AVG_CLIP_DURATION) + 1)
        needed = original_needed
        scene_clips = []
        used_ids = context.assets.get("used_asset_ids", [])

        # ── 1. 从 local_assets_inventory 数据库抽取 ──────────────────────────────
        try:
            from src.api.database import SessionLocal
            from src.api.models import LocalAsset
            with SessionLocal() as db:
                # 步骤 A: 优先抽取 1 个 Hook (如果有的话)
                hook_asset = db.query(LocalAsset).filter(
                    LocalAsset.asset_type == 'video',
                    LocalAsset.video_role == 'hook',
                    LocalAsset.is_exhausted == False
                ).order_by(LocalAsset.usage_count.asc()).first()
                
                if hook_asset:
                    scene_clips.append(hook_asset.file_path)
                    used_ids.append(hook_asset.id)
                    self.log(f"[Local Mode] 🎯 选取 Hook 片头 ID={hook_asset.id}: {hook_asset.file_path}")
                    needed -= 1
                else:
                    self.log("[Local Mode] ⚠️ 警告: 库里完全没有设置 Hook 素材，退化为原来的全盘随机抽取逻辑。")

                if needed > 0:
                    # 步骤 B & C: 去查 video_role in ('body', 'general') 且未耗尽的视频
                    # 绝对禁止跨界抽取 video_role == 'hook'
                    fill_assets = db.query(LocalAsset).filter(
                        LocalAsset.asset_type == 'video',
                        LocalAsset.video_role.in_(['body', 'general']),
                        LocalAsset.is_exhausted == False
                    ).order_by(LocalAsset.usage_count.asc()).limit(needed).all()
                    
                    # 极端兜底：如果连符合条件的都没有，只回退到 general（依旧不能用 hook）
                    if not fill_assets:
                        self.log("[Local Mode] ⚠️ 警告: 库里完全没有未耗尽的 Body 素材，只能将就复用其他 general 素材 (严格排查 hook)。")
                        fill_assets = db.query(LocalAsset).filter(
                            LocalAsset.asset_type == 'video',
                            LocalAsset.video_role == 'general',
                            LocalAsset.is_exhausted == False
                        ).order_by(LocalAsset.usage_count.asc()).limit(needed).all()

                    if fill_assets:
                        # 继续使用剩余素材，直到填满总时长
                        while len(scene_clips) < original_needed:
                            for asset in fill_assets:
                                scene_clips.append(asset.file_path)
                                used_ids.append(asset.id)
                                if len(scene_clips) >= original_needed:
                                    break
                        self.log(f"[Local Mode] 📂 数据库选取 {len(fill_assets)} 种 Body (或兜底) 素材，循环平铺至完整时长。")
        except Exception as exc:
            self.log(f"[Local-DB] 数据库读取视频素材失败或未配置: {exc}")

        # ── 2. 降级：系统默认素材池（如果 DB 没有查到有效结果）───────────────────
        if not scene_clips:
            self.log(
                f"[Local Mode] {len(scenes)} scene(s), total duration: {total_duration:.1f}s. "
                f"Selecting clips from default pool '{self._pool_dir}'..."
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

        context.assets["used_asset_ids"] = used_ids
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
