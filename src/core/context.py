from typing import Any, Dict, Optional
import uuid

class WorkflowContext:
    """
    工作流上下文：贯穿整个视频生成生命周期的数据总线。
    类似 Coze/ComfyUI 中的 payload 传递。
    """
    # 修复处：将 str = None 改为 Optional[str] = None
    def __init__(self, session_id: Optional[str] = None,
                 local_asset_dir: Optional[str] = None,
                 local_overlay_dir: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())
        # X 轴：本地视频素材目录（Tauri Dialog 传入）；None 表示使用系统默认素材池
        self.local_asset_dir: Optional[str] = local_asset_dir
        # Y 轴：本地贴图/Logo 目录（透明背景 .png）；None 表示使用系统默认叠层素材
        self.local_overlay_dir: Optional[str] = local_overlay_dir
        
        # 存放全局配置 (如：目标语言、分辨率、API Keys)
        self.config: Dict[str, Any] = {}
        
        # 存放流转中的核心资产路径或数据
        self.assets: Dict[str, Any] = {
            "script": "",             # 原始文案
            "audio_master": "",       # 主音频 (如无BGM的纯干声)
            "video_master": "",       # 主视频 (无字幕的纯净画面母带)
        }
        
        # 存放多语言变体资产 (专为中东等多地区分发设计)
        # 例如: {"ar": {"subtitle_ass": "path/to/ar.ass", "final_video": "path/to/ar.mp4"}}
        self.variants: Dict[str, Dict[str, str]] = {}

    def set_asset(self, key: str, value: Any):
        """写入公共资产"""
        self.assets[key] = value

    def get_asset(self, key: str) -> Any:
        """读取公共资产"""
        return self.assets.get(key)
        
    def set_variant_asset(self, lang_code: str, key: str, value: str):
        """写入特定语言的变体资产 (如阿语字幕文件)"""
        if lang_code not in self.variants:
            self.variants[lang_code] = {}
        self.variants[lang_code][key] = value