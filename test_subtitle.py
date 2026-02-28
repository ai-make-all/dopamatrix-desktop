"""
test_subtitle.py — Phase 3 端到端字幕测试

正确的管线执行顺序：
  Step A: SubtitleNode      → 生成 .ass 文件，注册到 Context.variants
  Step B: FFmpegCompositorNode → 渲染 master_video.mp4，然后自动调用
           _burn_subtitles 读取 Context.variants 中已注册的 .ass
           路径，完成多语言字幕烧录，输出 final_{lang}.mp4

注意：SubtitleNode 必须在 CompositorNode 之前运行，否则
      _burn_subtitles 触发时 .ass 文件尚未生成。
"""

import os
from pathlib import Path

from src.core.context import WorkflowContext
from src.core.timeline import Timeline, Track, Clip, AudioTrack
from src.nodes.compositor import FFmpegCompositorNode
from src.nodes.subtitle import SubtitleNode

# 确保输出目录存在
Path("output").mkdir(exist_ok=True)

ASSETS = "tests/assets"


def test_subtitle_pipeline():
    print("=" * 60)
    print("Phase 3: Multi-Language Subtitle Pipeline Test")
    print("=" * 60)

    # ── 1. 构建 Timeline（复用现有测试素材，仅用 bg1.mp4 保持简短）───
    bg_track = Track(name="Background", z_index=0)
    bg_track.add_clip(Clip(f"{ASSETS}/bg1.mp4", start_time=0.0, duration=5.0))

    bgm_track = AudioTrack(name="BGM")
    bgm_track.add_clip(Clip(f"{ASSETS}/bgm.mp3", start_time=0.0))

    timeline = Timeline()
    timeline.add_track(bg_track)
    timeline.add_audio_track(bgm_track)

    # ── 2. 构建 Context，注入多语言翻译配置 ─────────────────────────
    context = WorkflowContext(session_id="SUBTITLE-TEST-001")
    context.set_asset("timeline", timeline)

    context.config["translations"] = {
        "en": "Hello, Middle East Market!",
        "ar": "مرحبًا بالسوق الشرق أوسطي",   # 阿拉伯语：测试 RTL 连写整形
    }
    context.config["subtitle_start"] = 0.5   # 字幕起始秒
    context.config["subtitle_end"]   = 4.5   # 字幕结束秒
    #context.config["font_name"]      = "Arial"
    context.config["font_name"]      = "Tahoma"
    context.config["font_size"]      = 52

    # ── Step A: SubtitleNode — 生成 .ass 文件并注册到 Context ────────
    # 必须先于 CompositorNode 运行，_burn_subtitles 才能找到 .ass 路径
    print("\n[Step A] SubtitleNode: Generating .ass subtitle files...")
    subtitle_node = SubtitleNode()
    context = subtitle_node.execute(context)

    # ── Step B: FFmpegCompositorNode — 渲染母带 + 字幕烧录 ──────────
    # execute() 内部会自动调用 _burn_subtitles(context, ...)
    print("\n[Step B] FFmpegCompositorNode: Rendering master + burning subtitles...")
    compositor = FFmpegCompositorNode()
    context = compositor.execute(context)

    # ── 3. 验证所有输出文件 ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Verification Results")
    print("=" * 60)

    all_pass = True

    # 检查 master_video.mp4
    master = context.get_asset("video_master")
    all_pass &= _check_file(master, "Master video (master_video.mp4)", min_bytes=1024)

    # 检查各语言 .ass 文件
    for lang in ["en", "ar"]:
        ass_path = context.variants.get(lang, {}).get("subtitle_ass")
        ok = _check_file(ass_path, f"ASS subtitle (sub_{lang}.ass)", min_bytes=100)
        all_pass &= ok

        # 打印阿语 Dialogue 行，直观验证 RTL 整形结果
        if lang == "ar" and ass_path and os.path.exists(ass_path):
            with open(ass_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("Dialogue:"):
                        print(f"  [INFO] Arabic Dialogue (RTL-shaped): {line.rstrip()}")
                        break

    # 检查多语言最终视频
    for lang in ["en", "ar"]:
        final_path = context.variants.get(lang, {}).get("final_video")
        all_pass &= _check_file(
            final_path, f"Final variant video (final_{lang}.mp4)", min_bytes=1024
        )

    print("\n" + "=" * 60)
    if all_pass:
        print("✅  ALL CHECKS PASSED — Phase 3 subtitle pipeline verified!")
    else:
        print("❌  SOME CHECKS FAILED — review errors above.")
    print("=" * 60)


def _check_file(path: "str | None", label: str, min_bytes: int = 0) -> bool:
    """检查文件是否存在且大小满足最低要求，打印结果并返回 bool。"""
    if not path:
        print(f"  [FAIL] {label}: path is None/empty in Context")
        return False
    if not os.path.exists(path):
        print(f"  [FAIL] {label}: file not found → {path}")
        return False
    size = os.path.getsize(path)
    if size < min_bytes:
        print(f"  [FAIL] {label}: file too small ({size} bytes < {min_bytes}) → {path}")
        return False
    display_size = f"{size // 1024} KB" if size >= 1024 else f"{size} bytes"
    print(f"  [PASS] {label}: {path} ({display_size})")
    return True


if __name__ == "__main__":
    test_subtitle_pipeline()
