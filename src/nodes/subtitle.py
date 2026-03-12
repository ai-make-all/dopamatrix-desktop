"""
SubtitleNode — Phase 4 精准重构版：VTT 驱动的分句字幕生成器

Bug 修复：
  1. 时间轴塌陷：废弃单个 15s Dialogue 事件，改为从 .vtt 文件解析每句话的
     精准 start/end，为每句话生成独立的 ASS Dialogue 行。
  2. 竖屏溢出：加入「竖屏强制换行算法」，英文每 ~22 字符、阿拉伯语每 ~18
     字符在最近空格处插入 ASS 换行符 \\N。

执行路径：
  路径 A（精准模式）: context.variants[lang]["vtt_path"] 存在
    → 解析 VTT cues → 每条 cue 生成 1 个 Dialogue 行（含换行处理）
  路径 B（降级模式）: vtt_path 不存在
    → 原有单 Dialogue 逻辑（从 context.config["translations"] 读取文本）
    → 保持向后兼容，不报错

ASS 样式改进：
  - PlayResX/Y 保持 1920×1080（横屏母带渲染分辨率）
  - WrapStyle: 1（行末自动换行兜底）
  - BorderStyle: 3（实心背景色块，比外描边更清晰易读）
  - BackColour: &H99000000（半透明黑底）
  - Outline: 0（BorderStyle=3 时无需描边）

数据流：
  路径 A 读取 → context.variants[lang]["vtt_path"]
  路径 B 读取 → context.config["translations"]
  写入         → context.variants[lang]["subtitle_ass"]
"""

import os
import re
from pathlib import Path
from typing import Dict, List

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext


class SubtitleNode(BaseNode):
    """
    多语言字幕生成节点（精准重构版）。

    核心能力：
      - 解析 edge-tts 生成的 .vtt 文件，提取每句话的精准时间戳
      - 为每句话生成独立的 ASS Dialogue 行（时间轴精准对齐语音）
      - 竖屏强制换行算法（英文 22 chars/行，阿文 18 chars/行）
      - 保留 libass 原生 RTL 渲染（不对阿拉伯语做任何字符重排）
    """

    # ------------------------------------------------------------------
    # ASS 文件头模板（优化版：BorderStyle=3 背景块 + WrapStyle=1）
    # ------------------------------------------------------------------
    _ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H99000000,0,0,0,0,100,100,0,0,3,0,0,2,40,40,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def __init__(self, name: str = "SubtitleNode"):
        super().__init__(name)

    # ------------------------------------------------------------------
    # VTT 解析器（健壮重写版）
    # ------------------------------------------------------------------

    @staticmethod
    def _vtt_time_to_seconds(ts: str) -> float:
        """
        将时间字符串转为浮点秒数。

        兼容两种格式：
          - WebVTT 标准格式 : HH:MM:SS.mmm  → "00:01:23.450"
          - SRT/edge-tts 格式  : HH:MM:SS,mmm  → "00:01:23,450"  ← 实际输出
          - 省略小时格式  : MM:SS.mmm     → "01:23.450"
        """
        # 统一将逗号小数分隔符转为点号（SRT 兑容）
        ts = ts.strip().replace(",", ".")
        parts = ts.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        else:
            return float(ts)

    @staticmethod
    def _strip_vtt_tags(text: str) -> str:
        """去除 VTT cue 内的 HTML/时间标签（如 <c>、<00:01.500>）。"""
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()

    def _parse_vtt(self, vtt_path: str) -> List[Dict]:
        """
        解析 VTT/SRT 混合格式文件，提取所有 cue。

        已证实兼容的格式：
          edge-tts VTT : "00:00:00,100 --> 00:00:05,650" (逗号毫秒)
          标准 WebVTT  : "00:00:00.100 --> 00:00:05.650" (点号毫秒)

        返回格式： [{"start": 0.1, "end": 5.65, "text": "..."}]
        """
        cues: List[Dict] = []

        try:
            with open(vtt_path, encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            self.log(f"[VTT] Cannot read '{vtt_path}': {exc}")
            return cues

        # 按空行分割成块（兼容 Windows \r\n 和 Unix \n）
        blocks = re.split(r"(?:\r?\n){2,}", content.strip())

        # 时间行正则：化全局提前编译，并兼容逗号/点号两种毫秒分隔符
        _TIME_RE = re.compile(
            r"(\d{1,2}:\d{2}:\d{2}[.,]\d+)"    # start: HH:MM:SS,mmm 或 HH:MM:SS.mmm
            r"\s+-->\s+"
            r"(\d{1,2}:\d{2}:\d{2}[.,]\d+)"    # end:   同上
        )

        for block in blocks:
            lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
            if not lines:
                continue

            # 跳过文件头、元数据块
            first = lines[0]
            if first.startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
                continue

            # 在块内找含 "-->" 的行
            time_line = None
            text_start_idx = 0
            for i, line in enumerate(lines):
                if "-->" in line:
                    time_line = line
                    text_start_idx = i + 1
                    break

            if not time_line:
                continue

            m = _TIME_RE.search(time_line)
            if not m:
                self.log(f"[VTT] Cannot parse time line: {time_line!r}")
                continue

            start = self._vtt_time_to_seconds(m.group(1))
            end   = self._vtt_time_to_seconds(m.group(2))

            # 合并文本行，去掉内联标签
            text_lines = lines[text_start_idx:]
            raw_text = " ".join(
                self._strip_vtt_tags(l) for l in text_lines if l
            )
            if not raw_text:
                continue

            cues.append({"start": start, "end": end, "text": raw_text})

        self.log(f"[VTT] Parsed {len(cues)} cue(s) from '{vtt_path}'")
        return cues

    # ------------------------------------------------------------------
    # TikTok 级短句聚合算法 (Chunking)
    # ------------------------------------------------------------------

    def _chunk_cues(
        self,
        cues: List[Dict],
        max_chars: int = 25,
    ) -> List[Dict]:
        """
        将逐词 cue 列表聚合为自然短句。

        聊天每个 cue 短到仅一小段时（edge-tts 逐词模式），直接生成 ASS 会导致
        画面闪烁且打破阿拉伯语连写。本方法采用贪心算法把逐词 cue 合并成
        自然语羧由短句，做到 "TikTok 呼吸感" 字幕效果。

        截断条件（任一满足即切割）：
          1. 当前 chunk 累积字符数 >= max_chars
          2. 当前词末尾含标点符号 (. , ! ? \u3002！？)

        Args:
            cues:      _parse_vtt() 返回的原始 cue 列表
            max_chars: 每块最大字符数阈値，默认 25

        Returns:
            聚合后的 cue 列表，格式与输入相同
        """
        if not cues:
            return cues

        # 如果 cue 平均字数已超过阈値（说明已是分句格式），直接返回不做聚合
        avg_len = sum(len(c["text"]) for c in cues) / len(cues)
        if avg_len >= max_chars * 0.8:
            self.log(
                f"[Chunk] Average cue length {avg_len:.1f} chars >= threshold, "
                "skipping chunking (already sentence-level)."
            )
            return cues

        self.log(f"[Chunk] Word-level cues detected (avg {avg_len:.1f} chars). Aggregating...")

        _PUNCT = set(".!?,。！？،۔")

        chunks: List[Dict] = []
        buf_words: List[str] = []
        buf_start: float = cues[0]["start"]
        buf_end: float = cues[0]["end"]
        buf_len: int = 0

        for cue in cues:
            word = cue["text"]
            # 累积当前词
            buf_words.append(word)
            buf_end = cue["end"]
            buf_len += len(word) + 1  # +1 代表单词间空格

            # 判断是否截断
            ends_with_punct = bool(word) and word[-1] in _PUNCT
            if buf_len >= max_chars or ends_with_punct:
                chunks.append({
                    "start": buf_start,
                    "end":   buf_end,
                    "text":  " ".join(buf_words),
                })
                # 重置缓冲区
                buf_words = []
                buf_start = cue["end"]
                buf_end   = cue["end"]
                buf_len   = 0

        # 收尾未截断的剩余词
        if buf_words:
            chunks.append({
                "start": buf_start,
                "end":   buf_end,
                "text":  " ".join(buf_words),
            })

        self.log(f"[Chunk] {len(cues)} word-cues → {len(chunks)} sentence-chunks")
        return chunks

    # ------------------------------------------------------------------
    # 竖屏强制换行算法
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap_text(text: str, lang: str, max_chars: int = 22) -> str:
        """
        在最近空格处插入 ASS 换行符 \\N，防止字幕超出竖屏宽度。

        策略：
          - 按空格分割单词，贪心地累积到当前行长度 < max_chars
          - 超出时在此处插入 \\N（ASS 硬换行）
          - 阿拉伯语使用较小 max_chars（默认 18），但不做字符重排
            （RTL 渲染由 libass 原生处理，Python 侧只管分行）

        Args:
            text:      待处理文本
            lang:      语言代码（"ar" 使用更小的行宽）
            max_chars: 每行最大字符数（英文默认 22）

        Returns:
            含 \\N 换行符的 ASS 字幕文本
        """
        # 阿拉伯语字符更宽，使用更小阈值
        if lang == "ar":
            max_chars = min(max_chars, 18)

        words = text.split()
        if not words:
            return text

        lines: List[str] = []
        current: List[str] = []
        current_len = 0

        for word in words:
            word_len = len(word)
            # +1 for space
            if current and current_len + 1 + word_len > max_chars:
                lines.append(" ".join(current))
                current = [word]
                current_len = word_len
            else:
                if current:
                    current_len += 1 + word_len
                else:
                    current_len = word_len
                current.append(word)

        if current:
            lines.append(" ".join(current))

        return r"\N".join(lines)

    # ------------------------------------------------------------------
    # ASS 时间戳格式化
    # ------------------------------------------------------------------

    @staticmethod
    def _seconds_to_ass_time(seconds: float) -> str:
        """将浮点秒数转换为 ASS 时间格式 H:MM:SS.cs（百分之一秒）"""
        seconds = max(0.0, seconds)
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int(round((seconds - int(seconds)) * 100))
        if cs >= 100:
            cs = 99
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    # ------------------------------------------------------------------
    # ASS 内容构建
    # ------------------------------------------------------------------

    def _build_ass_from_cues(
        self,
        cues: List[Dict],
        lang: str,
        font_name: str,
        font_size: int,
        max_chars: int,
    ) -> str:
        """
        【精准模式】根据 VTT cues 列表构建完整 ASS 内容。
        每个 cue 对应一条独立的 Dialogue 行。
        """
        header = self._ASS_HEADER.format(font_name=font_name, font_size=font_size)
        dialogues: List[str] = []

        for cue in cues:
            start_ts = self._seconds_to_ass_time(cue["start"])
            end_ts = self._seconds_to_ass_time(cue["end"])
            text = self._wrap_text(cue["text"], lang=lang, max_chars=max_chars)
            dialogues.append(
                f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{text}"
            )

        return header + "\n".join(dialogues) + "\n"

    def _build_ass_fallback(
        self,
        text: str,
        t_start: float,
        t_end: float,
        lang: str,
        font_name: str,
        font_size: int,
        max_chars: int,
    ) -> str:
        """
        【降级模式】无 VTT 时，退回单 Dialogue 行（含换行处理）。
        与旧版逻辑兼容，但加入了竖屏换行算法。
        """
        header = self._ASS_HEADER.format(font_name=font_name, font_size=font_size)
        start_ts = self._seconds_to_ass_time(t_start)
        end_ts = self._seconds_to_ass_time(t_end)
        wrapped = self._wrap_text(text, lang=lang, max_chars=max_chars)
        dialogue = f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{wrapped}\n"
        return header + dialogue

    # ------------------------------------------------------------------
    # 节点执行入口
    # ------------------------------------------------------------------

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        """
        执行字幕生成 — 测试语言优先（Test-First）模式：
        仅为 context.test_language 生成 1 个 .ass 文件。
        """
        font_name: str = str(context.config.get("font_name", "Tahoma"))
        font_size: int = int(context.config.get("font_size", 42))
        max_chars: int = int(context.config.get("subtitle_max_chars", 22))

        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        target_lang = getattr(context, "test_language", "en") or "en"
        self.log(f"[Test-First] 字幕仅生成语言 '{target_lang}'")

        session_id = getattr(context, "session_id", context.config.get("session_id", "default"))
        ass_path = str(output_dir / f"sub_{session_id}_{target_lang}.ass")
        vtt_path: str = (context.variants.get(target_lang) or {}).get("vtt_path", "")

        # ── 精准模式：VTT → 聚合短句 → 多行 Dialogue ─────────────────
        if vtt_path and os.path.exists(vtt_path):
            self.log(f"[{target_lang}] 精准模式: 解析 VTT '{vtt_path}'")
            cues = self._parse_vtt(vtt_path)
            if cues:
                chunks = self._chunk_cues(cues, max_chars=25)
                ass_content = self._build_ass_from_cues(
                    cues=chunks, lang=target_lang,
                    font_name=font_name, font_size=font_size, max_chars=max_chars,
                )
                with open(ass_path, "w", encoding="utf-8") as f:
                    f.write(ass_content)
                size = os.path.getsize(ass_path)
                self.log(
                    f"[OK] [{target_lang}] ASS ({len(chunks)} chunks) "
                    f"→ {ass_path} ({size} bytes)"
                )
                context.set_variant_asset(target_lang, "subtitle_ass", ass_path)
                return context
            else:
                self.log(f"[{target_lang}] VTT 无 cue，切换降级模式。")

        # ── 降级模式：单行 Dialogue ────────────────────────────────────
        translations: Dict[str, str] = context.config.get("translations", {})
        text: str = translations.get(target_lang, "")
        if not text:
            text = (context.variants.get(target_lang) or {}).get("subtitle_text", "")

        if not text:
            self.log(f"[{target_lang}] 无可用文本，跳过字幕生成。")
            return context

        t_start = float(context.config.get("subtitle_start", 0.0))
        t_end   = float(context.config.get("subtitle_end",   5.0))
        self.log(f"[{target_lang}] 降级模式: 单 Dialogue ({t_start:.1f}s → {t_end:.1f}s)")
        ass_content = self._build_ass_fallback(
            text=text, t_start=t_start, t_end=t_end, lang=target_lang,
            font_name=font_name, font_size=font_size, max_chars=max_chars,
        )
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
        size = os.path.getsize(ass_path)
        self.log(f"[OK] [{target_lang}] ASS (降级) → {ass_path} ({size} bytes)")
        context.set_variant_asset(target_lang, "subtitle_ass", ass_path)
        self.log(f"字幕生成完成: [{target_lang}]")
        return context

