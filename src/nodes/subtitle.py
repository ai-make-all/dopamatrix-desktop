"""
SubtitleNode — Phase 3: 多语言字幕生成节点（精简重构版）

核心原则：大道至简
  FFmpeg 完整版已内置 HarfBuzz（文本塑形）+ FriBidi（双向文本处理），
  libass 渲染器会原生处理阿拉伯语连写与 RTL 顺序。
  在 Python 侧对文本进行二次转换（arabic_reshaper / bidi）
  会与 libass 产生"Double Magic Conflict"，反而导致字母断开。

  因此：原始文本直接透传至 .ass 模板，不做任何修改。
  字体使用 Tahoma，它原生支持阿拉伯语字形，防止方块乱码。
"""

import os
from pathlib import Path
from typing import Dict

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext


class SubtitleNode(BaseNode):
    """
    多语言字幕生成节点。

    期望 Context 中存在：
        context.config["translations"]: Dict[str, str]
            例如 {"en": "Hello, World!", "ar": "مرحبا بالعالم"}

        context.config["subtitle_start"] (可选, float): 字幕起始时间，默认 0.0
        context.config["subtitle_end"]   (可选, float): 字幕结束时间，默认 5.0
        context.config["font_name"]      (可选, str):   字体名称，默认 "Tahoma"
        context.config["font_size"]      (可选, int):   字体大小，默认 40
    """

    # ASS 文件头模板（标准 SSA/ASS v4.00+ 格式）
    # Tahoma 原生支持阿拉伯语字形，是防方块乱码的首选字体
    _ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,10,10,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def __init__(self, name: str = "SubtitleNode"):
        super().__init__(name)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _seconds_to_ass_time(seconds: float) -> str:
        """将浮点秒数转换为 ASS 时间格式 H:MM:SS.cs（百分之一秒）"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int(round((seconds - int(seconds)) * 100))
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def _build_ass_content(
        self,
        text: str,
        t_start: float,
        t_end: float,
        font_name: str,
        font_size: int,
    ) -> str:
        """
        组装完整的 ASS 文件内容（头部 + 单条字幕事件）。
        文本原样透传，由 FFmpeg/libass 负责渲染塑形与 BiDi 顺序处理。
        """
        header = self._ASS_HEADER.format(font_name=font_name, font_size=font_size)
        start_ts = self._seconds_to_ass_time(t_start)
        end_ts = self._seconds_to_ass_time(t_end)
        dialogue = f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{text}\n"
        return header + dialogue

    # ------------------------------------------------------------------
    # 节点执行入口
    # ------------------------------------------------------------------
    def execute(self, context: WorkflowContext) -> WorkflowContext:
        translations: Dict[str, str] = context.config.get("translations", {})

        if not translations:
            self.log("Warning: no 'translations' found in context.config, skipping.")
            return context

        # 读取可选配置，提供合理默认值（字体默认 Tahoma，支持阿拉伯语）
        t_start: float = float(context.config.get("subtitle_start", 0.0))
        t_end: float   = float(context.config.get("subtitle_end", 5.0))
        font_name: str = str(context.config.get("font_name", "Tahoma"))
        font_size: int = int(context.config.get("font_size", 40))

        # 确保输出目录存在
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        self.log(
            f"Generating subtitles for {len(translations)} language(s): "
            f"{list(translations.keys())}"
        )

        for lang, text in translations.items():
            ass_path = str(output_dir / f"sub_{lang}.ass")

            # 生成 ASS 文件内容（文本原样透传，不做任何预处理）
            ass_content = self._build_ass_content(
                text=text,
                t_start=t_start,
                t_end=t_end,
                font_name=font_name,
                font_size=font_size,
            )

            # 写入文件（UTF-8 编码）
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(ass_content)

            size = os.path.getsize(ass_path)
            self.log(f"[OK] [{lang}] ASS subtitle written → {ass_path} ({size} bytes)")

            # 注册路径回 Context.variants
            context.set_variant_asset(lang, "subtitle_ass", ass_path)

        self.log(
            f"All subtitle files registered in Context.variants: "
            f"{list(context.variants.keys())}"
        )
        return context
