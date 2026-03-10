"""
run_matrix_factory.py — ClipFlow 高并发矩阵裂变入口

架构：
  使用 Python concurrent.futures.ProcessPoolExecutor 实现多进程并发，
  同时生成 N 个独立的矩阵视频（每个带有唯一 session_id）。

完整 Pipeline（每个子进程独立运行）：
  ScriptGenNode
    → TTSNode
    → AssetSelectNode (LocalMatrixProvider)
    → TranslationBridgeNode
    → SubtitleNode
    → AssemblyNode
    → AntiDupNode         ← Phase 4 新增：防查重滤镜注入
    → FFmpegCompositorNode

输出文件命名规则：
  母带：  output/master_video_{session_id}.mp4
  变体：  output/final_{lang}_{session_id}.mp4
  （session_id 由 context.config["session_id"] 传递，compositor 自动读取）

用法：
  # 默认 batch_size=3（同时生产 3 个矩阵视频）
  python run_matrix_factory.py

  # 指定批量大小
  python run_matrix_factory.py --batch-size 5

多进程注意事项：
  - 每个 worker 函数顶部必须调用 load_dotenv()，因为子进程不继承父进程的环境变量。
  - 所有临时文件路径均含 session_id 以避免跨进程文件覆盖。
  - Windows 下使用 ProcessPoolExecutor 必须在 if __name__ == "__main__": 中调用，
    否则子进程会无限 fork（spawn 模式）。
"""

import argparse
import time
import os
import sys
import traceback
import uuid
from concurrent.futures import ProcessPoolExecutor, Future, as_completed

# ── Windows GBK 终端兼容修复 ──────────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ===========================================================================
# Worker 函数（运行在独立子进程中）
# ===========================================================================

def _run_single_matrix(session_id: str, user_prompt: str,
                       local_asset_dir: str | None = None,
                       local_logo_dir: str | None = None,
                       local_sticker_dir: str | None = None,
                       aspect_ratio: str = "9:16",
                       test_language: str = "en") -> dict:
    """
    单个矩阵视频生产 Worker，在独立子进程中执行完整 Pipeline。

    Args:
        session_id:        当前任务的唯一标识符（8位短 UUID）
        user_prompt:       视频生成提示词
        local_asset_dir:   （可选）X 轴：Tauri Desktop 选取的本地视频素材目录绝对路径
        local_overlay_dir: （可选）Y 轴：透明背景 .png 贴图目录绝对路径

    Returns:
        结果字典，包含 session_id、success、assets、error 等字段

    重要：
        - 子进程不继承父进程的 os.environ（通过 load_dotenv 加载）
        - 所有输出路径均含 session_id，由 compositor.py 自动拼接
    """
    # ── 子进程必须重新加载 .env（父进程的 load_dotenv 不传递给子进程）────────
    from dotenv import load_dotenv
    load_dotenv()

    # ── 重新配置子进程 stdout/stderr 编码 ────────────────────────────────────
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    print(f"\n{'='*60}")
    print(f"[Worker {session_id}] 子进程启动，开始生产矩阵视频...")
    print(f"{'='*60}")

    try:
        # ── 导入所有节点（在子进程内导入，避免跨进程序列化问题）────────────
        from src.core.context import WorkflowContext
        from src.core.engine import WorkflowEngine
        from src.core.base_node import BaseNode
        from src.nodes.script_gen import ScriptGenNode
        from src.nodes.tts_node import TTSNode
        from src.nodes.asset_select import AssetSelectNode
        from src.nodes.subtitle import SubtitleNode
        from src.nodes.assembler import AssemblyNode
        from src.nodes.anti_dup_node import AntiDupNode
        from src.nodes.compositor import FFmpegCompositorNode

        # ── 内联 TranslationBridgeNode ────────────────────────────────────────
        class TranslationBridgeNode(BaseNode):
            """从 script_data 中聚合各语言旁白 → context.config["translations"]"""
            def __init__(self):
                super().__init__(name="TranslationBridgeNode")

            def execute(self, context: WorkflowContext) -> WorkflowContext:
                script_data: dict = context.get_asset("script_data") or {}
                scenes = script_data.get("scenes", [])
                if not scenes:
                    self.log("Warning: no scenes, skipping translation bridge.")
                    return context

                translations: dict[str, list] = {}
                total_duration: float = 0.0

                for scene in scenes:
                    total_duration += float(scene.get("duration", 0))
                    for lang, text in scene.get("narrations", {}).items():
                        if text and text.strip():
                            translations.setdefault(lang, []).append(text.strip())

                combined: dict[str, str] = {
                    lang: "\n".join(lines) for lang, lines in translations.items()
                }

                context.config["translations"] = combined
                context.config["subtitle_start"] = 0.0
                context.config["subtitle_end"] = total_duration if total_duration > 0 else 5.0
                self.log(
                    f"Translations bridged for {list(combined.keys())}. "
                    f"subtitle_end={context.config['subtitle_end']:.1f}s"
                )
                return context

        # ── 组装完整 Pipeline ─────────────────────────────────────────────────
        engine = WorkflowEngine()
        engine.nodes = [
            ScriptGenNode(),                                           # 1. LLM 生成分镜脚本
            TTSNode(output_dir="output"),                             # 2. 文字转语音
            AssetSelectNode(pool_dir="assets/matrix_pool/x_main"),   # 3. 本地抽卡
            TranslationBridgeNode(),                                   # 4. 字幕文本桥接
            SubtitleNode(),                                            # 5. 生成 .ass 字幕
            AssemblyNode(bg_video_path="tests/assets/bg1.mp4"),       # 6. 拼装 Timeline
            AntiDupNode(),                                             # 7. 防查重注入 ← NEW
            FFmpegCompositorNode(),                                    # 8. FFmpeg 渲染
        ]

        context = WorkflowContext(
            session_id=session_id,
            local_asset_dir=local_asset_dir,
            local_logo_dir=local_logo_dir,
            local_sticker_dir=local_sticker_dir,
            aspect_ratio=aspect_ratio,
            test_language=test_language,
        )
        context.config["session_id"] = session_id
        context.set_asset("script", user_prompt)
        if local_asset_dir:
            print(f"[Worker {session_id}] 📂 X轴素材: {local_asset_dir}")
        if local_logo_dir:
            print(f"[Worker {session_id}] 🎨 Logo: {local_logo_dir}")
        if local_sticker_dir:
            print(f"[Worker {session_id}] ✨ Sticker: {local_sticker_dir}")
        print(f"[Worker {session_id}] 📐 画幅: {aspect_ratio} | 🌐 语言: {test_language}")


        # ── 确保输出目录存在 ──────────────────────────────────────────────────
        os.makedirs("output", exist_ok=True)
        os.makedirs("output/clips", exist_ok=True)

        print(f"[Worker {session_id}] Pipeline 节点序列 ({len(engine.nodes)} 个节点):")
        for i, node in enumerate(engine.nodes, 1):
            print(f"  {i}. {node.name}")

        # ── 运行 Pipeline ─────────────────────────────────────────────────────
        final_context = engine.run(context)

        # ── 收集结果 ──────────────────────────────────────────────────────────
        result: dict = {
            "session_id": session_id,
            "success": True,
            "error": None,
            "assets": {
                "video_master": final_context.get_asset("video_master") or "",
                "variants": {
                    lang: assets.get("final_video", "")
                    for lang, assets in final_context.variants.items()
                },
            },
        }

        print(f"\n[Worker {session_id}] ✅ 完成！母带: {result['assets']['video_master']}")
        return result

    except Exception as exc:
        tb = traceback.format_exc()
        print(f"\n[Worker {session_id}] ❌ 执行失败:\n{tb}")
        return {
            "session_id": session_id,
            "success": False,
            "error": str(exc),
            "traceback": tb,
            "assets": {},
        }


# ===========================================================================
# 矩阵工厂主函数
# ===========================================================================

def run_matrix_factory(batch_size: int = 3, user_prompt: str = "",
                       local_asset_dir: str | None = None,
                       local_logo_dir: str | None = None,
                       local_sticker_dir: str | None = None,
                       aspect_ratio: str = "9:16",
                       test_language: str = "en") -> list[dict]:
    """
    启动多进程矩阵批量生产。

    Args:
        batch_size:        同时生产的矩阵视频数量
        user_prompt:       所有任务共享的提示词
        local_asset_dir:   X 轴本地视频素材目录
        local_logo_dir:    Y 轴 Logo 水印目录
        local_sticker_dir: Y 轴促销贴纸目录
        aspect_ratio:      画幅比例
        test_language:     测试语言

    Returns:
        所有任务的结果字典列表，按完成顺序排列
    """
    if not user_prompt:
        user_prompt = (
            "帮我生成一个 15 秒的汽车减震器出海短视频，包含英文和阿拉伯语。"
            "视频节奏紧凑，突出产品耐用性和适合中东路况的卖点，"
            "需要吸引海湾地区的汽车用品批发商。"
        )

    # 为每个任务生成唯一的 session_id（取 UUID4 前 8 位，简洁且碰撞概率极低）
    sessions = [uuid.uuid4().hex[:8] for _ in range(batch_size)]

    print("=" * 60)
    print(f"🏭  ClipFlow 矩阵工厂启动")
    print(f"    批量大小: {batch_size}")
    print(f"    任务 ID : {sessions}")
    print("=" * 60)

    results: list[dict] = []

    # ProcessPoolExecutor：每个 session 在独立子进程中运行完整 Pipeline
    # max_workers=batch_size 确保所有任务真正并行（受 CPU 核心数上限）
    with ProcessPoolExecutor(max_workers=batch_size) as executor:
        # 提交所有任务
        future_to_session: dict[Future, str] = {
            executor.submit(_run_single_matrix, sid, user_prompt,
                            local_asset_dir, local_logo_dir, local_sticker_dir,
                            aspect_ratio, test_language): sid
            for sid in sessions
        }

        print(f"\n⏳ 已提交 {batch_size} 个生产任务，等待完成...\n")

        # 按完成顺序收集结果（as_completed 不阻塞其他任务）
        for future in as_completed(future_to_session):
            sid = future_to_session[future]
            try:
                result = future.result()
                results.append(result)
                status = "✅" if result["success"] else "❌"
                print(f"\n{status} [Session {sid}] 完成")
                if not result["success"]:
                    print(f"   错误: {result.get('error', 'Unknown error')}")
            except Exception as exc:
                # future.result() 本身抛异常（如序列化失败）
                print(f"\n❌ [Session {sid}] Future 异常: {exc}")
                results.append({
                    "session_id": sid,
                    "success": False,
                    "error": str(exc),
                    "assets": {},
                })

    return results


def _print_summary(results: list[dict]) -> None:
    """打印所有任务的最终摘要。"""
    print("\n" + "=" * 60)
    print("📊  矩阵工厂生产摘要")
    print("=" * 60)

    success_count = sum(1 for r in results if r["success"])
    print(f"\n总计: {len(results)} 个任务，{success_count} 成功，{len(results) - success_count} 失败\n")

    for r in results:
        sid = r["session_id"]
        if r["success"]:
            master = r["assets"].get("video_master", "(未生成)")
            print(f"  ✅ [{sid}] 母带: {master}")
            for lang, path in r["assets"].get("variants", {}).items():
                print(f"         [{lang}]: {path or '(未生成)'}")
        else:
            print(f"  ❌ [{sid}] 失败: {r.get('error', 'Unknown')}")

    print()


# ===========================================================================
# 命令行入口
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="ClipFlow 高并发矩阵裂变工厂",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_matrix_factory.py              # 默认 batch_size=3
  python run_matrix_factory.py --batch-size 5
  python run_matrix_factory.py --batch-size 2 --prompt "30秒运动相机出海短视频"
        """
    )
    parser.add_argument(
        "--batch-size", "-n",
        type=int,
        default=3,
        help="同时生产的矩阵视频数量（默认: 3）"
    )
    parser.add_argument(
        "--prompt", "-p",
        type=str,
        default="",
        help="视频生成提示词（默认: 汽车减震器示例）"
    )
    args = parser.parse_args()

    # ── 加载 .env（父进程加载；子进程会在 worker 内独立重新加载）────────────
    from dotenv import load_dotenv
    load_dotenv()

    start_time = time.time()
    results = run_matrix_factory(
        batch_size=args.batch_size,
        user_prompt=args.prompt,
    )
    _print_summary(results)
    print(f"✅ 矩阵生成完毕！总耗时: {time.time() - start_time:.2f} 秒")

    # 若有任何失败，以非零退出码通知 CI/CD 系统
    all_success = all(r["success"] for r in results)
    sys.exit(0 if all_success else 1)


# ===========================================================================
# Windows 多进程安全入口
# ===========================================================================
# CRITICAL: ProcessPoolExecutor 在 Windows spawn 模式下必须在此守卫内执行，
# 否则子进程在 import 时会无限递归 fork。

if __name__ == "__main__":
    main()
