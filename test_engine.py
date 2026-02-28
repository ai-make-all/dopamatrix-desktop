import os
from pathlib import Path
from src.core.context import WorkflowContext
from src.core.timeline import Timeline, Track, Clip, AudioTrack
from src.nodes.compositor import FFmpegCompositorNode

# 确保 output/ 目录存在
Path("output").mkdir(exist_ok=True)

ASSETS = "tests/assets"


def test_timeline_compilation():
    # 1. 模拟底层轨道 (Y轴: z=0) — 两个视频前后拼接 (X轴)
    bg_track = Track(name="Background", z_index=0)
    bg_track.add_clip(Clip(f"{ASSETS}/bg1.mp4", start_time=0.0, duration=5.0))
    bg_track.add_clip(Clip(f"{ASSETS}/bg2.mp4", start_time=5.0, duration=5.0))

    # 2. 模拟中层轨道 (Y轴: z=1) — 画中画素材，从第2秒开始
    fg_track = Track(name="Foreground", z_index=1)
    fg_track.add_clip(Clip(f"{ASSETS}/fg1.mp4", start_time=2.0, duration=4.0))

    # 3. 音频轨道 — BGM 从第0秒开始，-shortest 保证跟随视频长度裁断
    bgm_track = AudioTrack(name="BGM")
    bgm_track.add_clip(Clip(f"{ASSETS}/bgm11.mp3", start_time=0.0))

    # 4. 组装 Timeline
    timeline = Timeline()
    timeline.add_track(bg_track)
    timeline.add_track(fg_track)
    timeline.add_audio_track(bgm_track)

    # 5. 塞入 Context
    context = WorkflowContext(session_id="TEST-001")
    context.set_asset("timeline", timeline)

    # 6. 执行节点
    print("--- Starting FFmpeg Compositor Node Test (Video + Audio) ---")
    node = FFmpegCompositorNode()
    result_ctx = node.execute(context)

    # 7. 验证输出
    master = result_ctx.get_asset("video_master")
    if master and os.path.exists(master):
        size_kb = os.path.getsize(master) // 1024
        print(f"\n[PASS] Master video written: {master} ({size_kb} KB)")
    else:
        print(f"\n[FAIL] Expected output not found: {master}")


if __name__ == "__main__":
    test_timeline_compilation()
