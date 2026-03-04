"""
TTSNode — 多语言文字转语音节点

设计原则：
  使用 edge-tts CLI（subprocess.run）驱动 TTS，而非直接调用 async Python API。
  这样可以在同步的 WorkflowEngine 中无缝运行，无需引入 asyncio 事件循环管理。

数据流：
  读取  → context.assets["script_data"]   (ScriptGenNode 输出的分镜 JSON)
  写入  → context.variants[lang]["voice_audio"]  (各语言 MP3 路径)

语音配置：
  en → en-US-AriaNeural   （美式英语，自然女声，适合品牌/广告内容）
  ar → ar-SA-HamedNeural  （沙特阿拉伯语，男声，覆盖中东市场）

CLI 命令格式：
  edge-tts --voice <voice> --text "<text>" --write-media <output.mp3>
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext


# ---------------------------------------------------------------------------
# 语音配置表：lang_code → edge-tts voice name
# 需要新增语种时，只需在这里加一行，节点代码无需改动
# ---------------------------------------------------------------------------
VOICE_MAP: Dict[str, str] = {
    "en": "en-US-AriaNeural",
    "ar": "ar-SA-HamedNeural",
}

# edge-tts 在不同环境下的可执行程序名（Windows 和 Unix 均可用）
_EDGE_TTS_CMD = "edge-tts"


class TTSNode(BaseNode):
    """
    多语言文字转语音节点。

    期望 Context 中存在：
        context.assets["script_data"]: dict
            ScriptGenNode 生成的分镜 JSON，格式：
            {
              "scenes": [
                {
                  "duration": 5,
                  "visual_prompt": "...",
                  "narrations": {"en": "...", "ar": "..."}
                },
                ...
              ]
            }

    执行后写入 Context：
        context.variants["en"]["voice_audio"] → "output/voice_en.mp3"
        context.variants["ar"]["voice_audio"] → "output/voice_ar.mp3"
        （每种 script_data 中出现的语言均会生成对应 MP3）

    参数：
        output_dir: MP3 文件输出目录，默认 "output"
        voice_map:  语言代码 → edge-tts 音色名称的映射表，默认使用 VOICE_MAP
        rate:       语速调整，格式为 "+0%"（默认不调整）
    """

    def __init__(
        self,
        name: str = "TTSNode",
        output_dir: str = "output",
        voice_map: Dict[str, str] | None = None,
        rate: str = "+0%",
    ):
        super().__init__(name)
        self._output_dir = Path(output_dir)
        self._voice_map: Dict[str, str] = voice_map or VOICE_MAP
        self._rate = rate

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _collect_narrations(self, script_data: dict) -> Dict[str, str]:
        """
        从 script_data 中，按语言代码聚合所有 scene 的旁白文本。

        每个 scene 的旁白用换行符拼接，形成完整的、连贯的 TTS 输入文本。
        返回格式：{"en": "scene1 en...\nscene2 en...", "ar": "scene1 ar...\n..."}
        """
        narrations: Dict[str, list] = {}
        for scene in script_data.get("scenes", []):
            for lang, text in scene.get("narrations", {}).items():
                if text and text.strip():
                    narrations.setdefault(lang, []).append(text.strip())

        return {lang: "\n".join(lines) for lang, lines in narrations.items()}

    def _run_tts(self, voice: str, text: str, output_path: Path, vtt_path: Path) -> None:
        """
        调用 edge-tts CLI，将 text 转换为 MP3 文件，并同步生成 .vtt 时间轴文件。

        命令格式：
          edge-tts --voice {voice} --rate {rate} --text "{text}"
                   --write-media  {output_path}
                   --write-subtitles {vtt_path}

        如果命令失败，抛出 RuntimeError（包含 stderr 信息方便诊断）。
        """
        cmd = [
            _EDGE_TTS_CMD,
            "--voice", voice,
            "--rate", self._rate,
            "--text", text,
            "--write-media", str(output_path),
            "--write-subtitles", str(vtt_path),   # 生成精准分句时间轴
        ]

        self.log(f"Running: {' '.join(cmd[:4])} ... --write-media {output_path.name} --write-subtitles {vtt_path.name}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"[TTSNode] edge-tts failed for voice '{voice}'.\n"
                f"Return code: {result.returncode}\n"
                f"stderr: {result.stderr.strip()}\n"
                f"stdout: {result.stdout.strip()}"
            )

    # ------------------------------------------------------------------
    # 节点执行入口
    # ------------------------------------------------------------------

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        """
        执行 TTS 流程：
          1. 从 Context 取出 script_data
          2. 按语言聚合所有 scene 的旁白文本
          3. 对每种语言调用 edge-tts CLI 生成 MP3
          4. 将输出路径注册到 Context.variants
        """
        script_data: dict = context.get_asset("script_data") or {}

        if not script_data:
            self.log("Warning: context.assets['script_data'] is empty, skipping.")
            return context

        # 确保输出目录存在
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # 聚合各语言旁白
        narrations = self._collect_narrations(script_data)

        if not narrations:
            self.log("Warning: No narrations found in script_data['scenes'], skipping.")
            return context

        self.log(
            f"Detected languages: {list(narrations.keys())}. "
            f"Starting TTS generation..."
        )

        for lang, text in narrations.items():
            # 获取对应语音模型，找不到时使用 fallback 并警告
            voice = self._voice_map.get(lang)
            if not voice:
                self.log(
                    f"Warning: No voice configured for lang='{lang}' in voice_map. "
                    f"Skipping."
                )
                continue

            output_path = self._output_dir / f"voice_{lang}.mp3"
            vtt_path    = self._output_dir / f"voice_{lang}.vtt"

            self.log(
                f"[{lang}] voice={voice} | "
                f"text_length={len(text)} chars → {output_path}"
            )

            # 调用 edge-tts CLI（同时写入 MP3 + VTT）
            self._run_tts(voice=voice, text=text, output_path=output_path, vtt_path=vtt_path)

            # 验证 MP3 文件真的生成了
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError(
                    f"[TTSNode] Output file missing or empty after TTS: {output_path}"
                )

            file_size_kb = output_path.stat().st_size / 1024
            self.log(
                f"[OK] [{lang}] MP3 generated → {output_path} "
                f"({file_size_kb:.1f} KB)"
            )

            # 注册资产路径到 Context.variants
            context.set_variant_asset(lang, "voice_audio", str(output_path))

            # 注册 .vtt 路径（如果文件存在）：供 SubtitleNode 第一时间读取
            if vtt_path.exists() and vtt_path.stat().st_size > 0:
                context.set_variant_asset(lang, "vtt_path", str(vtt_path))
                self.log(f"[OK] [{lang}] VTT timeline → {vtt_path}")
            else:
                self.log(
                    f"[Warning] [{lang}] VTT file not generated (edge-tts may not support "
                    "--write-subtitles in this version). SubtitleNode will use fallback mode."
                )

        self.log(
            f"TTS complete. Registered voice_audio for: "
            f"{[lang for lang in narrations if self._voice_map.get(lang)]}"
        )

        return context
