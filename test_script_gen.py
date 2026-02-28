"""
test_script_gen.py — ScriptGenNode 独立测试脚本

运行方式（在项目根目录执行）：
    python test_script_gen.py

功能：
    1. 加载 .env 文件（OPENAI_API_KEY / OPENAI_BASE_URL）
    2. 构造一个真实业务场景的提示词（15 秒汽车配件短视频）
    3. 运行 ScriptGenNode
    4. 美观打印生成结果到终端
"""

import json
import sys
import os

# --- 加载 .env 文件（必须在 import openai 之前执行）---
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("[Env] .env loaded successfully.")
except ImportError:
    print("[Env] Warning: python-dotenv not installed. Reading system env vars directly.")

# --- 路径修复：确保在项目根目录运行时可以正确 import src ---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.core.context import WorkflowContext
from src.nodes.script_gen import ScriptGenNode


def main():
    print("=" * 60)
    print("  ScriptGenNode — 端到端测试")
    print("=" * 60)

    # 1. 构造 WorkflowContext，写入用户提示词
    ctx = WorkflowContext()
    ctx.set_asset(
        "script",
        "帮我写一个 15 秒的汽车配件短视频脚本，"
        "主打东南亚市场，强调减震器的耐用性。",
    )

    # 2. 初始化节点（自动从环境变量读取 API Key 和 Base URL）
    node = ScriptGenNode()

    # 3. 执行节点
    print("\n[Running] Executing ScriptGenNode...\n")
    try:
        ctx = node.execute(ctx)
    except RuntimeError as e:
        print(f"\n[ERROR] LLM call failed:\n{e}")
        sys.exit(1)
    except ValueError as e:
        print(f"\n[ERROR] Response validation failed:\n{e}")
        sys.exit(1)

    # 4. 读取结果并美观打印
    script_data = ctx.get_asset("script_data")

    if not script_data:
        print("\n[WARN] script_data is empty in context.")
        return

    print("\n" + "=" * 60)
    print("  生成的分镜脚本（script_data）")
    print("=" * 60)
    print(json.dumps(script_data, indent=4, ensure_ascii=False))

    # 5. 输出摘要统计
    scenes = script_data.get("scenes", [])
    total_duration = sum(s.get("duration", 0) for s in scenes)
    print("\n" + "-" * 60)
    print(f"  ✅ 共 {len(scenes)} 个分镜，预估总时长 {total_duration} 秒")
    print("-" * 60)


if __name__ == "__main__":
    main()
