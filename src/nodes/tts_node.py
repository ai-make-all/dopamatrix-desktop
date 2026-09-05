"""
TTSNode — 多语言文字转语音节点（单轨线性架构，Phase 9.11.2）

设计原则：
  使用 edge_tts Python 原生异步 API 驱动 TTS，通过 asyncio.run() 在同步
  WorkflowEngine 中执行，彻底消除对 edge-tts CLI 可执行文件的依赖，
  从根本上解决生产环境 PATH 缺失导致的 [WinError 2] 崩溃。

数据流（Phase 9.11.2 单轨线性架构）：
  读取  → context.assets["tts_script"]    {lang: "聚合全文"}
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


def _resolve_execution_namespace(context: WorkflowContext) -> str:
    """Return the authoritative child namespace, with a legacy direct-call fallback."""
    execution_id = context.config.get("execution_id")
    if execution_id:
        return str(execution_id)

    # A context carrying any new child marker belongs to the execution
    # contract and must never fall back to the shared task_id namespace.
    if "child_index" in context.config or "file_sid" in context.config:
        raise RuntimeError("[TTSNode] child context is missing execution_id")

    # LEGACY DIRECT-CALL FALLBACK: a direct context without child markers uses
    # its task namespace.
    legacy_id = getattr(context, "task_id", None) or "default"
    logger.warning(
        f"[TTSNode] execution_id missing; using legacy direct-call namespace={legacy_id}"
    )
    return str(legacy_id)


class TTSNode(BaseNode):
    """
    多语言文字转语音节点（单轨线性架构，Phase 9.11.2）。

    期望 Context 中存在：
        context.assets["tts_script"]: dict
            单轨架构的聚合台词字典，格式：
            { "en": "beat1 text\nbeat2 text\n...", "ar": "..." }

    执行后写入 Context：
        context.variants["en"]["voice_audio"] → "output/voice_en.mp3"
        context.variants["ar"]["voice_audio"] → "output/voice_ar.mp3"
        （每种 tts_script 中出现的语言均会生成对应 MP3 + VTT）

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

    async def _run_tts_async(
        self, voice: str, text: str, output_path: Path, vtt_path: Path
    ) -> None:
        """
        使用 edge_tts Python 原生 API 流式生成音频并同步收集字幕事件。

        通过 communicate.stream() 逐块写入 MP3 文件，同时将 WordBoundary
        事件喂给 SubMaker。流结束后，将 SRT 内容转换为 WebVTT 格式写入文件。
        整个过程无需 subprocess，不依赖任何外部可执行文件。
        """
        # edge-tts v7.x 新增 boundary 参数，默认值为 "SentenceBoundary"。
        # 必须显式声明 "WordBoundary" 才能让服务端开启逐词时间戳事件，
        # 否则 SubMaker.feed() 永远收不到 WordBoundary chunk，VTT 文件输出为空，
        # 导致 SubtitleNode 降级为单行 Dialogue（全文字幕静态堆叠 Bug）。
        communicate = edge_tts.Communicate(text, voice, rate=self._rate, boundary="WordBoundary")
        submaker = edge_tts.SubMaker()

        with open(str(output_path), "wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    submaker.feed(chunk)

        # SRT → WebVTT：添加 WEBVTT 头，逗号毫秒分隔符 → 点号（SubtitleNode 解析器已兼容两种，但标准 VTT 用点号）
        # newline='\n'：Windows 默认文本模式会把 \n 转成 \r\n，破坏 SubtitleNode 的时间行正则匹配。
        srt_content = submaker.get_srt()
        vtt_content = "WEBVTT\n\n" + srt_content.replace(",", ".")
        with open(str(vtt_path), "w", encoding="utf-8", newline="\n") as vtt_file:
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

        读取 context.assets["tts_script"]（单轨线性架构，Phase 9.11.2），
        仅为 context.test_language 生成 1 个 MP3 + VTT。
        砍掉多语言循环，消除无意义算力浪费；
        正式上线时只需切换 test_language，无需改代码。
        """
        tts_script: dict = context.get_asset("tts_script") or {}

        if not tts_script:
            self.log("Warning: context.assets['tts_script'] is empty, skipping.")
            return context

        self._output_dir.mkdir(parents=True, exist_ok=True)

        # ── 确定目标语言 ────────────────────────────────────────────
        target_lang = getattr(context, "test_language", "en") or "en"
        self.log(f"[Test-First] 目标语言 = '{target_lang}'（单语种模式，跳过其他语种）")

        if target_lang not in tts_script:
            # 尝试 fallback：取 tts_script 中第一个有 voice 映射的语言
            fallback = next(
                (lang for lang in tts_script if lang in self._voice_map), None
            )
            if fallback:
                self.log(
                    f"[Test-First] '{target_lang}' 在 tts_script 中无文本，"
                    f"回退到 '{fallback}'。"
                )
                target_lang = fallback
            else:
                self.log(
                    f"Warning: '{target_lang}' 无文本且无可用 fallback，跳过 TTS。"
                )
                return context

        text = str(tts_script[target_lang]).strip()
        if not text:
            self.log(f"Warning: tts_script['{target_lang}'] 为空字符串，跳过 TTS。")
            return context
        voice = self._voice_map.get(target_lang)
        if not voice:
            self.log(
                f"Warning: voice_map 中无 '{target_lang}' 的音色配置，跳过。"
            )
            return context

        execution_id = _resolve_execution_namespace(context)
        output_path = self._output_dir / f"voice_{execution_id}_{target_lang}.mp3"
        vtt_path    = self._output_dir / f"voice_{execution_id}_{target_lang}.vtt"

        self.log(
            f"[{target_lang}] task_id={context.task_id} execution_id={execution_id} "
            f"child_index={context.config.get('child_index')} "
            f"file_sid={context.config.get('file_sid')} voice={voice} | "
            f"text_length={len(text)} chars → MP3={output_path} VTT={vtt_path}"
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
