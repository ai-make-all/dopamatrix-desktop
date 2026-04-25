"""
run_matrix_factory.py — ClipFlow 高并发矩阵裂变入口

架构：
  使用 Python concurrent.futures.ThreadPoolExecutor 实现多线程并发，
  同时生成 N 个独立的矩阵视频（每个带有唯一 session_id）。

  ⚠️ 重要设计说明：
  改用 ThreadPoolExecutor（而非 ProcessPoolExecutor）的原因：
  1. Pipeline 中的重负载（LLM API 调用、TTS、FFmpeg subprocess）均为 I/O 密集型，
     subprocess.run() 调用会释放 GIL，线程并发效率与多进程相当。
  2. 在 PyInstaller --windowed 打包模式下，ProcessPoolExecutor 会重新启动
     backend.exe 作为 worker，freeze_support() 无法可靠拦截，导致 worker
     尝试绑定已占用的 8000 端口后立即崩溃，任务始终以 0 资产失败。
  3. 线程方案：worker 直接运行在父进程中，环境变量和模块缓存完全共享，
     无需解决跨进程序列化和 freeze_support 问题。

完整 Pipeline（每个线程独立运行）：
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
"""

import argparse
import json
import os
import sys
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, Future, as_completed

from src.core.logger import logger


# ===========================================================================
# Manifest 构建工具（引擎层伴生导出）
# ===========================================================================

def _fmt_time(seconds: float) -> str:
    """将秒数格式化为 MM:SS 字符串，如 65.3 → '01:05'。"""
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def _build_video_manifest(context, session_id: str, test_language: str) -> dict:
    """
    从 WorkflowContext 组装视频基因配方（Video Manifest）。

    数据来源：
      - X 轴分镜  → context.assets["script_data"].scenes
                    每个 scene 按位置映射到 hook / body / cta
      - X 轴台词  → scene.narrations[test_language]
      - X 轴时间码 → 累积 scene.duration 计算绝对起止秒
      - Y 轴 BGM  → context.assets["timeline"].audio_tracks (audio_type=="bgm")

    输出格式严格对齐前端 VideoDetailView.vue 的 videoManifest 结构：
    {
        "video_id": "vid_<session_id>",
        "bgm": "<bgm_filename>",
        "blocks": [
            {
                "id": "b1",
                "type": "hook",
                "time": "00:00 - 00:03",
                "emotion": "frustration",
                "script": "...",
                "thumb": ""
            },
            ...
        ]
    }

    注：thumb 字段留空，由后续截帧缩略图任务（Phase 3）异步填充。
    """
    # 位置 → 类型 & 情绪的映射策略
    _POSITION_TO_TYPE   = {0: "hook", -1: "cta"}   # 首 → hook，尾 → cta，其余 → body
    _TYPE_TO_EMOTION    = {"hook": "frustration", "body": "solution", "cta": "urgency"}

    script_data: dict = context.get_asset("script_data") or {}
    timeline          = context.get_asset("timeline")
    scenes: list      = script_data.get("scenes", [])
    total_scenes      = len(scenes)

    # ── X 轴：遍历 scene 构建 blocks ─────────────────────────────────────────
    blocks = []
    cursor = 0.0
    for idx, scene in enumerate(scenes):
        duration = float(scene.get("duration", 0))
        t_start  = cursor
        t_end    = cursor + duration

        if idx == 0:
            block_type = "hook"
        elif idx == total_scenes - 1 and total_scenes > 1:
            block_type = "cta"
        else:
            block_type = "body"

        script_text = (scene.get("narrations") or {}).get(test_language, "")

        blocks.append({
            "id"      : f"b{idx + 1}",
            "type"    : block_type,
            "time"    : f"{_fmt_time(t_start)} - {_fmt_time(t_end)}",
            "emotion" : _TYPE_TO_EMOTION[block_type],
            "script"  : script_text,
            "thumb"   : "",  # Phase 3 截帧任务异步填充
        })
        cursor = t_end

    # ── Y 轴：从 Timeline 音频轨道读取 BGM 文件名 ────────────────────────────
    bgm_name = ""
    if timeline:
        for audio_track in timeline.audio_tracks:
            if audio_track.audio_type == "bgm" and audio_track.clips:
                bgm_name = os.path.basename(audio_track.clips[0].file_path)
                break

    return {
        "video_id" : f"vid_{session_id}",
        "bgm"      : bgm_name,
        "blocks"   : blocks,
    }


# ===========================================================================
# Worker 函数（运行在独立线程中）
# ===========================================================================

def _run_single_matrix(session_id: str, user_prompt: str,
                       aspect_ratio: str = "9:16",
                       test_language: str = "en",
                       target_duration: int = 15,
                       output_dir: str = None,
                       batch_size: int = 1,
                       script_mode: str = "auto",
                       tenant_id: str = "default") -> dict:
    """
    单个矩阵视频生产 Worker，在独立线程中执行完整 Pipeline。

    Args:
        session_id:        当前任务的唯一标识符（8位短 UUID）
        user_prompt:       视频生成提示词

    Returns:
        结果字典，包含 session_id、success、assets、error 等字段
    """
    # ── 线程安全的 .env 加载（父线程已加载则幂等；override=False 不覆盖） ──────
    from src.utils.env_utils import load_env
    load_env()

    logger.info(f"[Worker {session_id}] 线程启动，开始生产矩阵视频...")

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
            AssemblyNode(),                                            # 6. 拼装 Timeline
            AntiDupNode(),                                             # 7. 防查重注入 ← NEW
            FFmpegCompositorNode(),                                    # 8. FFmpeg 渲染
        ]

        context = WorkflowContext(
            session_id=session_id,
            aspect_ratio=aspect_ratio,
            test_language=test_language,
            target_duration=target_duration,
            batch_size=batch_size,
            script_mode=script_mode,
            tenant_id=tenant_id,
        )
        context.config["session_id"] = session_id
        if output_dir:
            context.config["output_dir"] = output_dir
        context.set_asset("script", user_prompt)
        logger.info(
            f"[Worker {session_id}] 画幅: {aspect_ratio} | 语言: {test_language} "
            f"| 时长: {target_duration}s | 模式: {script_mode}"
        )

        # ── 确保输出目录存在 ──────────────────────────────────────────────────
        os.makedirs("output", exist_ok=True)
        os.makedirs("output/clips", exist_ok=True)

        logger.info(
            f"[Worker {session_id}] Pipeline 节点数: {len(engine.nodes)}"
        )

        # ── 运行 Pipeline ─────────────────────────────────────────────────────
        final_context = engine.run(context)

        # ── 收集结果 ──────────────────────────────────────────────────────────
        video_manifest = _build_video_manifest(final_context, session_id, test_language)
        logger.info(
            f"[Worker {session_id}] Manifest 已生成: "
            f"blocks={len(video_manifest['blocks'])} bgm='{video_manifest['bgm']}'"
        )

        result: dict = {
            "session_id"    : session_id,
            "success"       : True,
            "error"         : None,
            "used_asset_ids": final_context.assets.get("used_asset_ids", []),
            "video_manifest": video_manifest,   # ← 基因配方，供 services.py 持久化
            "assets": {
                "video_master": final_context.get_asset("video_master") or "",
                "variants": {
                    lang: assets.get("final_video", "")
                    for lang, assets in final_context.variants.items()
                },
            },
        }

        logger.info(f"[Worker {session_id}] 完成！母带: {result['assets']['video_master']}")
        return result

    except Exception as exc:
        tb = traceback.format_exc()
        # 使用 logger 写入日志文件（打包后 --windowed 模式下 print 输出到 NUL，无法排查）
        logger.error(f"[Worker {session_id}] 执行失败: {exc}\n{tb}")
        return {
            "session_id": session_id,
            "success": False,
            "error": str(exc),
            "traceback": tb,
            "used_asset_ids": [],
            "assets": {},
        }


# ===========================================================================
# 矩阵工厂主函数
# ===========================================================================

def run_matrix_factory(batch_size: int = 3, user_prompt: str = "",
                       aspect_ratio: str = "9:16",
                       test_language: str = "en",
                       target_duration: int = 15,
                       output_dir: str = None,
                       script_mode: str = "auto",
                       tenant_id: str = "default") -> list[dict]:
    """
    启动多线程矩阵批量生产。

    使用 ThreadPoolExecutor 而非 ProcessPoolExecutor，原因见模块文档。
    Pipeline 中的重负载（LLM/TTS API 调用、FFmpeg subprocess）均会释放 GIL，
    线程并发效率与多进程相当，同时完全避免 PyInstaller 打包下的进程衍生问题。

    Args:
        batch_size:        同时生产的矩阵视频数量
        user_prompt:       所有任务共享的提示词
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

    logger.info(f"[矩阵工厂] 启动，批量大小: {batch_size}，任务 ID: {sessions}")

    results: list[dict] = []

    # ThreadPoolExecutor：每个 session 在独立线程中运行完整 Pipeline
    # max_workers=batch_size 确保所有任务真正并行（受 CPU 核心数上限）
    with ThreadPoolExecutor(max_workers=batch_size) as executor:
        future_to_session: dict[Future, str] = {
            executor.submit(_run_single_matrix, sid, user_prompt,
                            aspect_ratio, test_language, target_duration,
                            output_dir, batch_size, script_mode, tenant_id): sid
            for sid in sessions
        }

        logger.info(f"[矩阵工厂] 已提交 {batch_size} 个生产任务，等待完成...")

        # 按完成顺序收集结果（as_completed 不阻塞其他任务）
        for future in as_completed(future_to_session):
            sid = future_to_session[future]
            try:
                result = future.result()
                results.append(result)
                if result["success"]:
                    logger.info(f"[矩阵工厂] [Session {sid}] 完成 ✓")
                else:
                    logger.warning(
                        f"[矩阵工厂] [Session {sid}] 失败: {result.get('error', 'Unknown error')}"
                    )
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error(f"[矩阵工厂] [Session {sid}] Future 异常: {exc}\n{tb}")
                results.append({
                    "session_id": sid,
                    "success": False,
                    "error": str(exc),
                    "assets": {},
                })

    return results


def _print_summary(results: list[dict]) -> None:
    """将所有任务的最终摘要写入日志。"""
    logger.info("\n" + "=" * 60)
    logger.info("📊  矩阵工厂生产摘要")
    logger.info("=" * 60)

    success_count = sum(1 for r in results if r["success"])
    logger.info(f"\n总计: {len(results)} 个任务，{success_count} 成功，{len(results) - success_count} 失败\n")

    for r in results:
        sid = r["session_id"]
        if r["success"]:
            master = r["assets"].get("video_master", "(未生成)")
            logger.info(f"  ✅ [{sid}] 母带: {master}")
            for lang, path in r["assets"].get("variants", {}).items():
                logger.info(f"         [{lang}]: {path or '(未生成)'}")
        else:
            logger.warning(f"  ❌ [{sid}] 失败: {r.get('error', 'Unknown')}")

    logger.info("")


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

    from src.utils.env_utils import load_env
    load_env()

    start_time = time.time()
    results = run_matrix_factory(
        batch_size=args.batch_size,
        user_prompt=args.prompt,
    )
    _print_summary(results)
    logger.info(f"✅ 矩阵生成完毕！总耗时: {time.time() - start_time:.2f} 秒")

    all_success = all(r["success"] for r in results)
    sys.exit(0 if all_success else 1)


if __name__ == "__main__":
    main()
