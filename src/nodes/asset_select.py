"""
AssetSelectNode — Phase 5 升级版：双轨寻址素材选择节点

职责：
  支持两条素材寻址轨道（Double-Track Addressing）：

  [路径一] 绝对指纹直通车（Locked Bypass）：
    当 timeline 场景块中 address_mode == "locked" 时，读取 asset_hashes 列表，
    按文件指纹（file_hash）直接定位数据库物理路径，强制绕过疲劳度权重计算。
    用户锁定 N 个素材时，内部循环随机排列以填满所需 clip 数量。

  [路径二] 智能抽卡（Smart Select）：
    address_mode == "smart" 或缺省时，沿用 LRU 防疲劳算法，
    并强制注入 entity_id 实体隔离过滤（来自 context.config["project_entity"]），
    从底层杜绝跨实体"串戏"事故（如猫粮/狗粮混剪）。

  降级模式（PexelsProvider）：
    若构建时显式传入 PexelsProvider 实例，则退回到逐场景关键词检索的原有逻辑，
    保持与 Phase 3 的向后兼容。

数据流：
  读取 → context.assets["script_data"]      (ScriptGenNode 生成的分镜脚本)
         └─ scenes[*].address_mode          ("locked" | "smart", 缺省 "smart")
         └─ scenes[*].asset_hashes          (locked 模式下的 file_hash 列表)
         context.config["project_entity"]   (实体隔离 ID，如 "@DogFood_BrandA")
  写入 → context.assets["scene_clips"]      (List[str] 本地 .mp4 路径列表)

设计说明：
  - 双轨 DSL 解析在 _run_local_mode 入口完成；业务逻辑分别委托给
    _select_locked_clips 和 _select_smart_clips。
  - Locked 模式：hash 未命中时，自动 Fallback 到 Smart 模式并打印警告，不中断流程。
  - 所有 DB 查询均走多租户 get_tenant_engine(context.tenant_id)。
  - Pexels 降级逻辑保持不变，方便测试与回归。
"""

import os
import random
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Union

# 隐藏 Windows 下 FFprobe 子进程的黑色控制台窗口
_WIN_NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.logger import logger
from src.utils.env_utils import get_ffmpeg_path
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
            from src.api.database import get_tenant_engine
            from src.api.models import LocalAsset
            from sqlalchemy.orm import sessionmaker as _sessionmaker
            _engine = get_tenant_engine(context.tenant_id)
            with _sessionmaker(autocommit=False, autoflush=False, bind=_engine)() as db:
                logo_asset = db.query(LocalAsset).filter(
                    LocalAsset.asset_type == 'logo',
                    LocalAsset.is_exhausted == False,  # noqa: E712
                    LocalAsset.is_deleted.is_(False),
                ).order_by(LocalAsset.usage_count.asc()).first()
                if logo_asset:
                    logo_path = logo_asset.file_path
                    used_ids.append(logo_asset.id)
                    self.log(f"[Y-Logo] 数据库提取 ID={logo_asset.id}: {logo_path}")

                sticker_asset = db.query(LocalAsset).filter(
                    LocalAsset.asset_type == 'sticker',
                    LocalAsset.is_exhausted == False,  # noqa: E712
                    LocalAsset.is_deleted.is_(False),
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
    # 本地矩阵模式（Phase 5：双轨寻址入口）
    # ------------------------------------------------------------------

    def _run_local_mode(
        self, context: WorkflowContext, script_data: dict, scenes: list
    ) -> WorkflowContext:
        """
        【本地矩阵模式 — 双轨寻址调度器】

        1. 音频霸权时长控制：用 ffprobe 读取真实音频时长，估算所需 clip 数量。
        2. DSL 解析：扫描所有 scene 块，收集 address_mode == "locked" 的 asset_hashes。
        3. 分发：
           - 有锁定 hash → _select_locked_clips（指纹直通，绕过疲劳度）
             └ hash 全部不命中时 → 自动 Fallback 到 _select_smart_clips
           - 无锁定 hash → _select_smart_clips（LRU + 实体隔离）
        4. 如果数据库两条路都没结果 → 系统默认素材池兜底。
        """
        # ── 音频霸权时长控制（Audio Hegemony Duration Control）──────────────
        target_lang = getattr(context, "test_language", "en") or "en"
        voice_audio = context.variants.get(target_lang, {}).get("voice_audio")

        total_duration = 0.0
        if voice_audio and os.path.exists(voice_audio):
            try:
                result = subprocess.run(
                    [
                        get_ffmpeg_path("ffprobe.exe"), "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        voice_audio,
                    ],
                    capture_output=True, text=True, check=True,
                    creationflags=_WIN_NO_WINDOW,
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
        needed = max(1, int(target_duration / AVG_CLIP_DURATION) + 1)

        # ── DSL 解析：扫描所有场景，收集锁定素材指纹 ───────────────────────
        raw_locked: List[str] = []
        for scene in scenes:
            if scene.get("address_mode") == "locked":
                raw_locked.extend(scene.get("asset_hashes") or [])

        # 去重，保留原始顺序
        seen: set = set()
        unique_locked: List[str] = []
        for h in raw_locked:
            if h and h not in seen:
                seen.add(h)
                unique_locked.append(h)

        used_ids: list = list(context.assets.get("used_asset_ids", []))
        scene_clips: List[str] = []

        # ── 路径一：绝对指纹直通车（Locked Bypass）─────────────────────────
        if unique_locked:
            self.log(
                f"[Double-Track] 检测到 {len(unique_locked)} 个锁定 hash，"
                f"进入绝对指纹直通车模式。"
            )
            scene_clips, used_ids = self._select_locked_clips(
                context, unique_locked, needed, used_ids
            )
            if not scene_clips:
                self.log(
                    "[Double-Track] ⚠️ 锁定 hash 全部未命中，"
                    "自动 Fallback 到智能抽卡（保证流程不中断）。"
                )
                scene_clips, used_ids = self._select_smart_clips(
                    context, needed, used_ids
                )
        else:
            # ── 路径二：智能抽卡 + 实体隔离（Smart Select）─────────────────
            self.log("[Double-Track] 无锁定 hash，进入智能抽卡（Smart）模式。")
            scene_clips, used_ids = self._select_smart_clips(
                context, needed, used_ids
            )

        # ── 兜底：系统默认素材池（数据库双路均无结果）───────────────────────
        if not scene_clips:
            self.log(
                f"[Local Mode] 数据库无可用素材，回退默认池 '{self._pool_dir}' "
                f"(scenes={len(scenes)}, duration={total_duration:.1f}s)..."
            )
            try:
                local_provider = LocalMatrixProvider(pool_dir=self._pool_dir)
                scene_clips = local_provider.get_clips_for_duration(
                    target_duration=total_duration
                )
            except RuntimeError as exc:
                self.log(f"[Local Mode] ✗ 默认素材池读取失败: {exc}")
                raise ValueError(
                    f"可用视频素材不足，请在素材库中添加新素材。"
                    f"（数据库无可用记录，默认素材池 '{self._pool_dir}' 也无法提供素材：{exc}）"
                ) from exc

        context.assets["used_asset_ids"] = used_ids
        context.set_asset("scene_clips", scene_clips)
        self.log(
            f"[Local Mode] ✓ {len(scene_clips)} clip(s) selected "
            f"(total ~{total_duration:.1f}s). Written to context.assets['scene_clips']."
        )
        self._set_overlay_clips(context, pool_dir=self._pool_dir)
        return context

    # ------------------------------------------------------------------
    # 路径一：绝对指纹直通车
    # ------------------------------------------------------------------

    def _select_locked_clips(
        self,
        context: WorkflowContext,
        hashes: List[str],
        needed: int,
        used_ids: list,
    ) -> tuple[List[str], list]:
        """
        按 file_hash 列表从数据库直接定位物理路径，强制跳过疲劳度权重。

        - 完整命中：将命中的素材循环随机排列，填满 needed 数量。
        - 部分命中：警告缺失 hash，使用命中部分继续循环。
        - 全部未命中：返回空列表（调用方负责 Fallback）。
        - 所有查询走多租户 get_tenant_engine(context.tenant_id)。
        """
        resolved_paths: List[str] = []
        resolved_ids: list = []
        missing: List[str] = []

        try:
            from src.api.database import get_tenant_engine
            from src.api.models import LocalAsset
            from sqlalchemy.orm import sessionmaker as _sessionmaker

            _engine = get_tenant_engine(context.tenant_id)
            with _sessionmaker(autocommit=False, autoflush=False, bind=_engine)() as db:
                for h in hashes:
                    asset = db.query(LocalAsset).filter(
                        LocalAsset.file_hash == h,
                        LocalAsset.is_deleted.is_(False),
                    ).first()
                    if asset:
                        resolved_paths.append(str(asset.file_path))
                        resolved_ids.append(asset.id)
                        self.log(
                            f"[Locked Bypass] ✓ hash={h[:12]}… → "
                            f"ID={asset.id} {asset.file_path}"
                        )
                    else:
                        missing.append(h)
        except Exception as exc:
            self.log(f"[Locked Bypass] 数据库查询异常: {exc}")
            return [], used_ids

        if missing:
            self.log(
                f"[Locked Bypass] ⚠️ {len(missing)}/{len(hashes)} 个 hash 未在数据库中找到，"
                f"已跳过: {[h[:12] + '…' for h in missing]}"
            )

        if not resolved_paths:
            return [], used_ids

        # 循环随机排列组合，填满 needed 数量（不超出用户指定素材池）
        pool = list(resolved_paths)
        clips: List[str] = []
        while len(clips) < needed:
            random.shuffle(pool)
            clips.extend(pool)
        clips = clips[:needed]

        # 每个命中 hash 只记录一次 used_id（不随循环倍增）
        new_used_ids = list(used_ids) + resolved_ids
        self.log(
            f"[Locked Bypass] ✓ {len(resolved_paths)} 个锁定素材，"
            f"循环填满 {len(clips)} clips（usage_count 权重已绕过）"
        )
        return clips, new_used_ids

    # ------------------------------------------------------------------
    # 路径二：智能抽卡 + 实体隔离
    # ------------------------------------------------------------------

    def _select_smart_clips(
        self,
        context: WorkflowContext,
        needed: int,
        used_ids: list,
    ) -> tuple[List[str], list]:
        """
        LRU 防疲劳智能抽卡，强制注入 entity_id 实体隔离过滤条件。

        entity_id 来源：context.config.get("project_entity")
        - 有值：WHERE entity_id = '<project_entity>'（杜绝跨品牌串戏）
        - 无值：不加过滤（兼容未设置实体的历史任务）

        抽卡策略与原有逻辑相同：
          A. 优先抽 1 个 video_role == 'hook'
          B. 剩余配额从 body / general 中 LRU 抽取并循环平铺
          C. body 无结果时降级到纯 general（严格排除 hook）
        """
        entity_id: Optional[str] = context.config.get("project_entity")
        entity_tag = f" [entity={entity_id}]" if entity_id else ""

        scene_clips: List[str] = []
        new_used_ids = list(used_ids)
        original_needed = needed

        try:
            from src.api.database import get_tenant_engine
            from src.api.models import LocalAsset
            from sqlalchemy.orm import sessionmaker as _sessionmaker

            _engine = get_tenant_engine(context.tenant_id)
            with _sessionmaker(autocommit=False, autoflush=False, bind=_engine)() as db:

                def _apply_entity(q):
                    """注入实体隔离过滤（仅 entity_id 非空时生效）。"""
                    if entity_id:
                        return q.filter(LocalAsset.entity_id == entity_id)
                    return q

                # 步骤 A：优先抽取 1 个 Hook
                hook_q = _apply_entity(
                    db.query(LocalAsset).filter(
                        LocalAsset.asset_type == "video",
                        LocalAsset.video_role == "hook",
                        LocalAsset.is_exhausted == False,   # noqa: E712
                        LocalAsset.is_deleted.is_(False),
                    )
                )
                hook_asset = hook_q.order_by(LocalAsset.usage_count.asc()).first()

                if hook_asset:
                    scene_clips.append(str(hook_asset.file_path))
                    new_used_ids.append(hook_asset.id)
                    needed -= 1
                    self.log(
                        f"[Smart] 🎯 Hook ID={hook_asset.id}{entity_tag}: "
                        f"{hook_asset.file_path}"
                    )
                else:
                    self.log(
                        f"[Smart] ⚠️ 无 Hook 素材{entity_tag}，退化为全盘随机抽取。"
                    )

                # 步骤 B：body / general 填充（严格禁止抽 hook）
                if needed > 0:
                    fill_q = _apply_entity(
                        db.query(LocalAsset).filter(
                            LocalAsset.asset_type == "video",
                            LocalAsset.video_role.in_(["body", "general"]),
                            LocalAsset.is_exhausted == False,   # noqa: E712
                            LocalAsset.is_deleted.is_(False),
                        )
                    )
                    fill_assets = (
                        fill_q.order_by(LocalAsset.usage_count.asc())
                        .limit(needed)
                        .all()
                    )

                    # 步骤 C：极端兜底——纯 general（依旧严禁 hook）
                    if not fill_assets:
                        self.log(
                            f"[Smart] ⚠️ 无未耗尽 Body 素材{entity_tag}，"
                            f"降级为纯 general 兜底（严格排除 hook）。"
                        )
                        fallback_q = _apply_entity(
                            db.query(LocalAsset).filter(
                                LocalAsset.asset_type == "video",
                                LocalAsset.video_role == "general",
                                LocalAsset.is_exhausted == False,   # noqa: E712
                                LocalAsset.is_deleted.is_(False),
                            )
                        )
                        fill_assets = (
                            fallback_q.order_by(LocalAsset.usage_count.asc())
                            .limit(needed)
                            .all()
                        )

                    if fill_assets:
                        while len(scene_clips) < original_needed:
                            for asset in fill_assets:
                                scene_clips.append(str(asset.file_path))
                                new_used_ids.append(asset.id)
                                if len(scene_clips) >= original_needed:
                                    break
                        self.log(
                            f"[Smart] 📂 {len(fill_assets)} 种 Body/General 素材{entity_tag}，"
                            f"循环平铺至完整时长。"
                        )

        except Exception as exc:
            self.log(f"[Smart-DB] 数据库读取视频素材失败或未配置: {exc}")

        return scene_clips, new_used_ids


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
