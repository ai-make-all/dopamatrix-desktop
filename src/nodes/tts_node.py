"""
TTSNode — 多语言文字转语音节点

设计原则：
  使用 edge_tts Python 原生异步 API 驱动 TTS，通过 asyncio.run() 在同步
  WorkflowEngine 中执行，彻底消除对 edge-tts CLI 可执行文件的依赖，
  从根本上解决生产环境 PATH 缺失导致的 [WinError 2] 崩溃。

数据流：
  读取  → context.assets["script_data"]   (ScriptGenNode 输出的分镜 JSON)
  写入  → context.variants[lang]["voice_audio"]  (各语言 MP3 路径)
          context.variants[lang]["vtt_path"]     (各语言 WebVTT 字幕路径)

语音配置：
  en → en-US-AriaNeural   （美式英语，自然女声，适合品牌/广告内容）
  ar → ar-SA-HamedNeural  （沙特阿拉伯语，男声，覆盖中东市场）
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Dict

import edge_tts

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.logger import logger


# ---------------------------------------------------------------------------
# 语音配置表：lang_code → edge-tts voice name
# 需要新增语种时，只需在这里加一行，节点代码无需改动
# ---------------------------------------------------------------------------
VOICE_MAP: Dict[str, str] = {
    "en": "en-US-AriaNeural",
    "ar": "ar-SA-HamedNeural",
}


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
        （每种 script_data 中出现的语言均会生成对应 MP3 + VTT）

    参数：
        output_dir: MP3/VTT 文件输出目录，默认 "output"
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

    async def _run_tts_async(
        self, voice: str, text: str, output_path: Path, vtt_path: Path
    ) -> None:
        """
        使用 edge_tts Python 原生 API 流式生成音频并同步收集字幕事件。

        通过 communicate.stream() 逐块写入 MP3 文件，同时将 WordBoundary
        事件喂给 SubMaker。流结束后，将 SRT 内容转换为 WebVTT 格式写入文件。
        整个过程无需 subprocess，不依赖任何外部可执行文件。
        """
        communicate = edge_tts.Communicate(text, voice, rate=self._rate)
        submaker = edge_tts.SubMaker()

        with open(str(output_path), "wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    submaker.feed(chunk)

        # SRT → WebVTT：添加 WEBVTT 头，并将时间戳分隔符从逗号改为句点
        srt_content = submaker.get_srt()
        vtt_content = "WEBVTT\n\n" + srt_content.replace(",", ".")
        with open(str(vtt_path), "w", encoding="utf-8") as vtt_file:
            vtt_file.write(vtt_content)

    def _run_tts(self, voice: str, text: str, output_path: Path, vtt_path: Path) -> None:
        """
        同步包装器：在当前线程中启动独立事件循环执行异步 TTS 任务。

        asyncio.run() 每次都创建一个全新的事件循环并在结束后关闭，
        可在 WorkflowEngine 的 ThreadPoolExecutor 环境中安全调用，
        不会与主线程或其他工作线程的事件循环产生冲突。
        """
        self.log(
            f"Running: edge_tts.Communicate(voice={voice!r}, rate={self._rate!r})"
            f" → {output_path.name} + {vtt_path.name}"
        )
        try:
            asyncio.run(
                self._run_tts_async(
                    voice=voice,
                    text=text,
                    output_path=output_path,
                    vtt_path=vtt_path,
                )
            )
        except Exception as e:
            raise RuntimeError(
                f"[TTSNode] edge_tts API failed for voice '{voice}': {e}"
            ) from e

    # ------------------------------------------------------------------
    # 节点执行入口
    # ------------------------------------------------------------------

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        """
        执行 TTS — 测试语言优先（Test-First）模式：

        仅为 context.test_language 生成 1 个 MP3 + VTT。
        砍掉多语言循环，消除无意义算力浪费；
        正式上线时只需切换 test_language，无需改代码。
        """
        script_data: dict = context.get_asset("script_data") or {}

        if not script_data:
            self.log("Warning: context.assets['script_data'] is empty, skipping.")
            return context

        self._output_dir.mkdir(parents=True, exist_ok=True)

        # ── 确定目标语言 ────────────────────────────────────────────
        target_lang = getattr(context, "test_language", "en") or "en"
        self.log(f"[Test-First] 目标语言 = '{target_lang}'（单语种模式，跳过其他语种）")

        # 聚合所有语言旁白，但只取目标语言
        narrations = self._collect_narrations(script_data)

        if target_lang not in narrations:
            # 尝试 fallback：取 narrations 中第一个有 voice 映射的语言
            fallback = next(
                (lang for lang in narrations if lang in self._voice_map), None
            )
            if fallback:
                self.log(
                    f"[Test-First] '{target_lang}' 在 script_data 中无旁白，"
                    f"回退到 '{fallback}'。"
                )
                target_lang = fallback
            else:
                self.log(
                    f"Warning: '{target_lang}' 无旁白且无可用 fallback，跳过 TTS。"
                )
                return context

        text = narrations[target_lang]
        voice = self._voice_map.get(target_lang)
        if not voice:
            self.log(
                f"Warning: voice_map 中无 '{target_lang}' 的音色配置，跳过。"
            )
            return context

        session_id = getattr(context, "session_id", context.config.get("session_id", "default"))
        output_path = self._output_dir / f"voice_{session_id}_{target_lang}.mp3"
        vtt_path    = self._output_dir / f"voice_{session_id}_{target_lang}.vtt"

        self.log(
            f"[{target_lang}] voice={voice} | "
            f"text_length={len(text)} chars → {output_path}"
        )

        max_retries = 3
        success = False
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                self._run_tts(voice=voice, text=text, output_path=output_path, vtt_path=vtt_path)

                if not output_path.exists():
                    raise RuntimeError(f"Output file missing after TTS: {output_path}")

                file_size = output_path.stat().st_size
                if file_size < 1024:
                    raise RuntimeError(
                        f"Output file too small ({file_size} bytes), likely corrupted: {output_path}"
                    )

                success = True
                break

            except Exception as e:
                last_error = e
                self.log(
                    f"[Warning] [{target_lang}] TTS attempt {attempt}/{max_retries} failed: {e}"
                )
                if attempt < max_retries:
                    time.sleep(1)

        if not success:
            raise RuntimeError(
                f"[TTSNode] TTS audio generation failed after {max_retries} attempts. "
                f"Last error: {last_error}"
            )

        file_size_kb = output_path.stat().st_size / 1024
        self.log(f"[OK] [{target_lang}] MP3 → {output_path} ({file_size_kb:.1f} KB)")
        context.set_variant_asset(target_lang, "voice_audio", str(output_path))

        if vtt_path.exists() and vtt_path.stat().st_size > 0:
            context.set_variant_asset(target_lang, "vtt_path", str(vtt_path))
            self.log(f"[OK] [{target_lang}] VTT → {vtt_path}")
        else:
            self.log(
                f"[Warning] [{target_lang}] VTT not generated. SubtitleNode will use fallback."
            )

        self.log(f"TTS complete. Registered voice_audio for: [{target_lang}]")
        return context
