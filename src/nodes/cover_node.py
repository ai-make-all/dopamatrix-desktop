"""
src/nodes/cover_node.py
———————————————————
CoverNode — 极速物理抽帧节点（Phase 9.8.1 / 9.8.2）

职责：
  在 FFmpegCompositorNode 渲染完成后，取第一个语言变体的最终视频，
  通过 FFmpeg -vframes 1 截取封面帧，输出为 JPEG 图片。

上游依赖：
  context.variants  — 至少含一个语言变体，每条含 "final_video" 路径
  context.assets["highlight_timestamp"] — 可选；若无则兜底为 "00:00:01"

输出契约：
  context.assets["cover_path"]  — 生成的封面图绝对/相对路径
"""

import os
import subprocess
import sys

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.logger import logger
from src.utils.env_utils import get_ffmpeg_path

_WIN_NO_WINDOW: int = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class CoverNode(BaseNode):
    """
    封面抽帧节点。
    从渲染完成的最终变体视频中提取单帧静止封面，写入 JPEG 文件。

    极速策略（无需解码全部帧）：
      ffmpeg -y -ss <timestamp> -i <video> -vframes 1 -q:v 2 <cover.jpg>
      -ss 置于 -i 之前触发关键帧快跳（seek fast），几乎瞬间完成。
    """

    DEFAULT_TIMESTAMP = "00:00:01"

    def __init__(self, name: str = "CoverNode"):
        super().__init__(name)

    # ------------------------------------------------------------------
    # 核心执行入口
    # ------------------------------------------------------------------

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        # ── 渗透级启动日志 ─────────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("[CoverNode] 🚀 封面抽帧节点已激活 (Phase 9.8.2)")
        logger.info(
            f"[CoverNode] task_id={context.session_id} "
            f"execution_id={context.config.get('execution_id')} "
            f"child_index={context.config.get('child_index')} "
            f"file_sid={self._resolve_file_sid(context)} "
            f"tenant_id={context.tenant_id}"
        )

        # 1. 寻找第一个可用的最终变体视频
        video_path = self._resolve_video_path(context)

        logger.info("[CoverNode] 🚀 开始执行极速截帧... 目标视频: %s", video_path or "(未找到)")

        if not video_path:
            logger.error(
                "[CoverNode] ❌ 未找到任何可用的变体视频！"
                " context.variants=%s  video_master=%s",
                list(context.variants.keys()),
                context.get_asset("video_master") or "N/A",
            )
            logger.info("=" * 60)
            return context

        # 2. 确定截帧时间戳（优先 context 中的 highlight_timestamp）
        timestamp: str = (
            context.get_asset("highlight_timestamp")
            or self.DEFAULT_TIMESTAMP
        )
        logger.info("[CoverNode] 截帧时间戳: %s", timestamp)

        # 3. 构造封面输出路径
        cover_path = self._cover_output_path(context, video_path)
        logger.info(f"[CoverNode] 封面输出路径: {cover_path}")

        # 4. 执行抽帧
        success = self._extract_frame(video_path, timestamp, cover_path)

        if not success:
            logger.error(
                "[CoverNode] ❌ 封面抽帧失败 | 视频=%s | 时间戳=%s | 目标路径=%s",
                video_path, timestamp, cover_path,
            )
            logger.info("=" * 60)
            return context

        # 5. 磁盘二次确认
        if os.path.exists(cover_path):
            size_kb = os.path.getsize(cover_path) / 1024
            logger.info(
                "[CoverNode] ✅ 截帧成功！封面已生成: %s  (%.1f KB)",
                cover_path, size_kb,
            )
        else:
            logger.error(
                "[CoverNode] ❌ FFmpeg 返回成功但封面文件不存在于磁盘: %s",
                cover_path,
            )
            logger.info("=" * 60)
            return context

        # 6. 写回 Context
        context.set_asset("cover_path", cover_path)
        logger.info("[CoverNode] cover_path 已写入 Context。")
        logger.info("=" * 60)
        return context

    # ------------------------------------------------------------------
    # 私有辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_file_sid(context: WorkflowContext) -> str:
        file_sid = context.config.get("file_sid")
        if file_sid:
            return str(file_sid)

        if "child_index" in context.config or "execution_id" in context.config:
            raise RuntimeError("[CoverNode] child context is missing file_sid")

        # LEGACY FALLBACK: an explicitly configured alias remains authoritative,
        # including the historical empty-string value.
        if "session_id" in context.config:
            return str(context.config["session_id"])
        return str(context.session_id)

    @classmethod
    def _cover_output_path(cls, context: WorkflowContext, video_path: str) -> str:
        output_dir = os.path.dirname(video_path) or "output"
        return os.path.join(
            output_dir,
            f"cover_{cls._resolve_file_sid(context)}.jpg",
        )

    @staticmethod
    def _resolve_video_path(context: WorkflowContext) -> str:
        """
        从 context.variants 中取第一个存在的 final_video 路径。
        降级策略：若 variants 为空，退回到 video_master。
        """
        for lang, lang_assets in context.variants.items():
            fp = lang_assets.get("final_video", "")
            if fp and os.path.isfile(fp):
                logger.debug("[CoverNode] 使用变体视频 lang=%s path=%s", lang, fp)
                return fp

        # 最终兜底：母带（可能不含配音/字幕，但至少有画面）
        master = context.get_asset("video_master") or ""
        if master and os.path.isfile(master):
            logger.debug("[CoverNode] 降级使用母带视频: %s", master)
            return master

        return ""

    def _extract_frame(self, video_path: str, timestamp: str, cover_path: str) -> bool:
        """
        调用 FFmpeg 从视频中抽取单帧并保存为 JPEG。

        命令结构：
          ffmpeg -y -ss <timestamp> -i <video_path> -vframes 1 -q:v 2 <cover_path>

        -ss 置于 -i 之前使用容器级快跳（stream seek），速度远快于解码级跳帧。
        -q:v 2 对应 JPEG 质量约 94%，兼顾文件大小与视觉效果。

        Returns:
            True 表示成功生成封面文件；False 表示抽帧失败。
        """
        ffmpeg_bin = get_ffmpeg_path("ffmpeg.exe")
        cmd = [
            ffmpeg_bin,
            "-y",
            "-ss", timestamp,
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            cover_path,
        ]
        logger.info("[CoverNode] [CMD] %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=_WIN_NO_WINDOW,
            )
            if result.returncode != 0:
                logger.error(
                    "[CoverNode] FFmpeg 抽帧异常 exit=%d\nSTDERR: %s",
                    result.returncode,
                    result.stderr[-600:],
                )
                return False
            if not os.path.isfile(cover_path):
                logger.error(
                    "[CoverNode] FFmpeg exit=0 但文件未生成: %s", cover_path
                )
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.error(
                "[CoverNode] FFmpeg 抽帧超时（>30s）| 视频: %s", video_path
            )
            return False
        except FileNotFoundError:
            logger.error(
                "[CoverNode] FFmpeg 二进制未找到: %s  "
                "请确认 ffmpeg.exe 已安装并可通过 PATH 访问。",
                ffmpeg_bin,
            )
            return False
