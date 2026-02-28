"""
test_tts.py — TTSNode 独立测试脚本

运行方式（在项目根目录执行）：
    python test_tts.py

功能：
    1. 手动构造一段「减震器短视频」Mock JSON 数据（与 ScriptGenNode 真实输出格式一致）
    2. 将 Mock 数据注入 WorkflowContext
    3. 运行 TTSNode
    4. 验证 output/ 目录下是否生成了合法的 .mp3 文件，并打印文件大小
"""

import json
import os
import sys
from pathlib import Path

# --- 路径修复：确保在项目根目录运行时可以正确 import src ---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.core.context import WorkflowContext
from src.nodes.tts_node import TTSNode


# ---------------------------------------------------------------------------
# Mock 脚本数据（模拟 ScriptGenNode 的真实输出）
# ---------------------------------------------------------------------------

MOCK_SCRIPT_DATA = {
    "scenes": [
        {
            "duration": 4,
            "visual_prompt": (
                "Low-angle slow-motion shot of a car wheel driving over rough gravel road, "
                "dust particles flying, golden hour lighting."
            ),
            "narrations": {
                "en": "Every road has its challenges. Your shock absorber shouldn't be one of them.",
                "ar": "كل طريق له تحدياته. ومستهلك الصدمات لديك لا ينبغي أن يكون أحدها.",
            },
        },
        {
            "duration": 4,
            "visual_prompt": (
                "Close-up of a premium shock absorber being stress-tested in a factory, "
                "engineers observing, hi-tech lab environment."
            ),
            "narrations": {
                "en": "Engineered for Southeast Asia's toughest roads. Built to outlast the journey.",
                "ar": "مُصمَّم لأقسى طرق جنوب شرق آسيا. مبني ليتحمل أطول الرحلات.",
            },
        },
        {
            "duration": 4,
            "visual_prompt": (
                "Family car smoothly gliding on a bumpy village road, children smiling inside, "
                "lush green tropical scenery."
            ),
            "narrations": {
                "en": "Smooth ride, every time. Because the people inside matter most.",
                "ar": "رحلة سلسة في كل مرة. لأن من بداخل السيارة هم الأهم.",
            },
        },
        {
            "duration": 3,
            "visual_prompt": (
                "Product shot of the shock absorber on a clean white background, "
                "brand logo appearing, call-to-action text overlay."
            ),
            "narrations": {
                "en": "ProShock — Durability you can feel. Order now with free shipping.",
                "ar": "برو شوك — متانة تشعر بها. اطلب الآن مع شحن مجاني.",
            },
        },
    ]
}


def main():
    print("=" * 60)
    print("  TTSNode — 端到端测试")
    print("=" * 60)

    # 1. 构造 WorkflowContext，注入 Mock 数据
    ctx = WorkflowContext()
    ctx.set_asset("script_data", MOCK_SCRIPT_DATA)

    print("\n[Mock Data] script_data injected into Context:")
    print(f"  Scenes: {len(MOCK_SCRIPT_DATA['scenes'])}")
    for i, s in enumerate(MOCK_SCRIPT_DATA["scenes"], 1):
        print(f"  Scene {i} ({s['duration']}s): {list(s['narrations'].keys())}")

    # 2. 初始化 TTSNode
    node = TTSNode(output_dir="output")

    # 3. 执行节点
    print("\n[Running] Executing TTSNode...\n")
    try:
        ctx = node.execute(ctx)
    except RuntimeError as e:
        print(f"\n[ERROR] TTS failed:\n{e}")
        sys.exit(1)

    # 4. 验证生成的文件
    print("\n" + "=" * 60)
    print("  验证结果")
    print("=" * 60)

    all_ok = True
    for lang in ["en", "ar"]:
        variant = ctx.variants.get(lang, {})
        audio_path = variant.get("voice_audio")

        if not audio_path:
            print(f"  ❌ [{lang}] voice_audio NOT registered in Context.variants")
            all_ok = False
            continue

        path = Path(audio_path)
        if path.exists() and path.stat().st_size > 0:
            size_kb = path.stat().st_size / 1024
            print(f"  ✅ [{lang}] {audio_path} ({size_kb:.1f} KB)")
        else:
            print(f"  ❌ [{lang}] File missing or empty: {audio_path}")
            all_ok = False

    print("\n" + "-" * 60)
    print("  Context.variants 完整内容：")
    print(json.dumps(ctx.variants, indent=4, ensure_ascii=False))
    print("-" * 60)

    if all_ok:
        print("\n  🎉 所有 MP3 文件生成成功！TTSNode 验证通过。")
    else:
        print("\n  ⚠️  部分文件生成失败，请检查上方错误信息。")
        sys.exit(1)


if __name__ == "__main__":
    main()
