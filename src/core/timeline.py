from typing import List, Optional


class Clip:
    """X轴：代表一个独立的素材 (视频、图片、音频)"""
    def __init__(self, file_path: str, start_time: float, duration: Optional[float] = None):
        self.file_path = file_path
        self.start_time = start_time  # 在时间线上的起始时间 (秒)
        self.duration = duration      # 持续时间 (秒)


class Track:
    """Y轴：代表一个视频图层轨道 (如底图轨、主视频轨、贴纸轨)"""
    def __init__(self, name: str, z_index: int):
        self.name = name
        self.z_index = z_index        # Y轴层级，数值越大越在顶层覆盖
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
