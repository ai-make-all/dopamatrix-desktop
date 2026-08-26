"""
run_factory.py — DopaMatrix 终极印钞机入口

全自动视频生成流水线：
  ScriptGenNode → TTSNode → AssetSelectNode → TranslationBridgeNode → SubtitleNode
  → AssemblyNode → FFmpegCompositorNode

TranslationBridgeNode（内联桥接节点）：
  SubtitleNode 从 context.config["translations"] 读取各语言字幕文本，
  而该文本存在于 script_data 的 narrations 中（由 ScriptGenNode 生成）。
  此桥接节点负责从 script_data 中聚合各语言旁白，写入 context.config["translations"]，
  并自动推算 subtitle_end（即视频总时长），使字幕覆盖整个视频。

用法：
  python run_factory.py
"""

import os
import sys

# ── Windows GBK 终端兼容修复 ──────────────────────────────────────────────────
# 在 Windows 上将输出重定向到文件时，系统默认使用 GBK 编码，
# 导致 emoji / 中文等 UTF-8 字符引发 UnicodeEncodeError。
# 此处强制将 stdout/stderr 切换为 UTF-8，errors='replace' 确保即使遇到
# 无法编码的字符也只输出 '?' 而不是崩溃整个进程。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 加载 .env 环境变量（必须在任何业务模块导入之前执行）────────────────────
from src.utils.env_utils import load_env
load_env()

# ── 导入核心组件 ─────────────────────────────────────────────────────────────
from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.engine import WorkflowEngine

# ── 导入所有业务节点 ──────────────────────────────────────────────────────────
from src.nodes.script_gen import ScriptGenNode
from src.nodes.tts_node import TTSNode
from src.nodes.asset_select import AssetSelectNode
from src.nodes.subtitle import SubtitleNode
from src.nodes.assembler import AssemblyNode
from src.nodes.compositor import FFmpegCompositorNode


# ===========================================================================
# 桥接节点：将 script_data.narrations → context.config["translations"]
# ===========================================================================

class TranslationBridgeNode(BaseNode):
    """
    内联桥接节点：从 script_data 中聚合各语言旁白，填入 SubtitleNode 所需的
    context.config["translations"] 字段，并设置字幕时间范围覆盖整个视频。

    本节点专为全链路流水线设计，无需独立文件。
    """

    def __init__(self):
        super().__init__(name="TranslationBridgeNode")

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        script_data: dict = context.get_asset("script_data") or {}
        scenes = script_data.get("scenes", [])

        if not scenes:
            self.log("Warning: script_data has no scenes, skipping translation bridge.")
            return context

        # 聚合各语言旁白（换行拼接，与 TTSNode 逻辑一致）
        translations: dict[str, list] = {}
        total_duration: float = 0.0

        for scene in scenes:
            duration = float(scene.get("duration", 0))
            total_duration += duration
            for lang, text in scene.get("narrations", {}).items():
                if text and text.strip():
                    translations.setdefault(lang, []).append(text.strip())

        # 拼接成完整字幕文本
        combined: dict[str, str] = {
            lang: "\n".join(lines) for lang, lines in translations.items()
        }

        context.config["translations"] = combined
        context.config["subtitle_start"] = 0.0
        context.config["subtitle_end"] = total_duration if total_duration > 0 else 5.0

        self.log(
            f"Translations bridged for {list(combined.keys())}. "
            f"subtitle_end set to {context.config['subtitle_end']:.1f}s"
        )
        return context


# ===========================================================================
# 主流水线入口
# ===========================================================================

def build_pipeline() -> tuple[WorkflowEngine, WorkflowContext]:
    """
    组装全自动视频生成流水线。

    节点顺序与职责：
      1. ScriptGenNode         — 调用 LLM，生成结构化分镜脚本（script_data）
      2. TTSNode               — 将各语言旁白转为配音 MP3，写入 variants[lang]["voice_audio"]
      3. AssetSelectNode       — 逐场景检索下载视频素材，写入 assets["scene_clips"]
      4. TranslationBridgeNode — 将 script_data 旁白聚合，写入 config["translations"]
      5. SubtitleNode          — 生成各语言 .ass 字幕文件，写入 variants[lang]["subtitle_ass"]
      6. AssemblyNode          — 读取 scene_clips + 配音路径，组装 Timeline 写入 assets["timeline"]
      7. FFmpegCompositorNode  — 编译 Timeline → FFmpeg → 渲染主视频 + 各语言字幕烧录变体

    Returns:
        (engine, context) — 可进一步配置后调用 engine.run(context)
    """
    engine = WorkflowEngine()

    # 各节点实例化（可通过构造器注入测试替换件）
    engine.nodes = [
        ScriptGenNode(),
        TTSNode(output_dir="output"),
        AssetSelectNode(output_dir="output/clips"),
        TranslationBridgeNode(),
        SubtitleNode(),
        AssemblyNode(),
        FFmpegCompositorNode(),
    ]

    # 初始化 Context
    context = WorkflowContext()

    # ── 用户输入：真实 Prompt ────────────────────────────────────────────────
    user_prompt = (
        "帮我生成一个 15 秒的汽车减震器出海短视频，包含英文和阿拉伯语。"
        "视频节奏紧凑，突出产品耐用性和适合中东路况的卖点，"
        "需要吸引海湾地区的汽车用品批发商。"
    )
    context.set_asset("script", user_prompt)

    # ── 输出目录初始化 ────────────────────────────────────────────────────────
    os.makedirs("output", exist_ok=True)
    os.makedirs("output/clips", exist_ok=True)

    return engine, context


def main():
    print("=" * 60)
    print("🎬  DopaMatrix 全自动印钞机启动")
    print("=" * 60)

    engine, context = build_pipeline()

    print(f"\n📋 流水线节点序列：")
    for i, node in enumerate(engine.nodes, 1):
        print(f"  {i}. {node.name}")
    print()

    try:
        final_context = engine.run(context)
    except Exception as exc:
        print(f"\n❌ 流水线执行失败: {exc}")
        raise

    # ── 打印最终资产摘要 ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("✅  全链路执行完成 — 资产摘要")
    print("=" * 60)
    print(f"\n📁 主视频母带: {final_context.get_asset('video_master') or '(未渲染)'}")

    if final_context.variants:
        print("\n🌍 多语言变体输出:")
        for lang, assets in final_context.variants.items():
            final_video = assets.get("final_video", "(未渲染)")
            voice = assets.get("voice_audio", "(无)")
            subtitle = assets.get("subtitle_ass", "(无)")
            print(f"  [{lang}]")
            print(f"    配音   : {voice}")
            print(f"    字幕   : {subtitle}")
            print(f"    最终视频: {final_video}")
    else:
        print("\n⚠️  无多语言变体输出。")

    print()
    return final_context


if __name__ == "__main__":
    main()
