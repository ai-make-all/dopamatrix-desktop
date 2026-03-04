from typing import List, Optional


class Clip:
    """X轴：代表一个独立的素材 (视频、图片、音频、PNG叠加层)"""
    def __init__(
        self,
        file_path: str,
        start_time: float,
        duration: Optional[float] = None,
        effects: Optional[List[str]] = None,
        overlay_x: Optional[str] = None,
        overlay_y: Optional[str] = None,
    ):
        self.file_path = file_path
        self.start_time = start_time  # 在时间线上的起始时间 (秒)
        self.duration = duration      # 持续时间 (秒)
        # per-clip FFmpeg 滤镜链（如 AntiDupNode 注入的防查重滤镜）
        # 格式：["eq=brightness=0.01:saturation=1.01", "atempo=1.005", ...]
        self.effects: List[str] = effects if effects is not None else []
        # Y轴 overlay 定位参数（FFmpeg 表达式，仅 track_type="overlay" 时使用）
        # 例：overlay_x="W-w-30", overlay_y="30" → 右上角距边框 30px
        self.overlay_x: Optional[str] = overlay_x
        self.overlay_y: Optional[str] = overlay_y


class Track:
    """Y轴：代表一个视频图层轨道 (如底图轨、主视频轨、贴纸轨)"""
    def __init__(self, name: str, z_index: int, track_type: str = "video"):
        self.name = name
        self.z_index = z_index        # Y轴层级，数值越大越在顶层覆盖
        # track_type: "video"   — 普通视频轨，走 concat 管线
        #             "overlay" — PNG 静态图层轨，走 overlay 管线（支持透明通道）
        self.track_type: str = track_type
        self.clips: List[Clip] = []

    def add_clip(self, clip: Clip):
        self.clips.append(clip)
        # 确保同一轨道内的 clip 按起始时间 (X轴) 排序
        self.clips.sort(key=lambda c: c.start_time)


class AudioTrack:
    """
    纯音频轨道：容纳音乐、旁白、音效等音频 Clip。
    与视频 Track 平级，独立存放于 Timeline.audio_tracks。
    多条 AudioTrack 最终会被 amix 滤镜混合为单一音频输出流 [outa]。
    """
    def __init__(self, name: str):
        self.name = name
        self.clips: List[Clip] = []

    def add_clip(self, clip: Clip):
        self.clips.append(clip)
        self.clips.sort(key=lambda c: c.start_time)


class Timeline:
    """多维时间线：容纳所有视频轨道（Y轴叠加）和音频轨道"""
    def __init__(self):
        self.tracks: List[Track] = []
        self.audio_tracks: List[AudioTrack] = []

    def add_track(self, track: Track):
        self.tracks.append(track)
        # 保持轨道按 z_index (Y轴) 由底向上排序，方便 FFmpeg 叠加渲染
        self.tracks.sort(key=lambda t: t.z_index)

    def add_audio_track(self, audio_track: AudioTrack):
        self.audio_tracks.append(audio_track)
