from typing import Any, Dict, Optional

from src.api.task_identity import new_task_id

class WorkflowContext:
    """
    工作流上下文：贯穿整个视频生成生命周期的数据总线。
    类似 Coze/ComfyUI 中的 payload 传递。
    """
    # 修复处：将 str = None 改为 Optional[str] = None
    def __init__(self, task_id: Optional[str] = None,
                 aspect_ratio: str = "9:16",
                 test_language: str = "en",
                 target_duration: int = 15,
                 batch_size: int = 1,
                 script_mode: str = "auto",
                 tenant_id: str = "default"):
        self.task_id = task_id or new_task_id()
        # 多租户隔离标识，贯穿整个 Pipeline，供各节点使用专属 DB Engine
        self.tenant_id: str = tenant_id or "default"
        # 画幅比例
        self.aspect_ratio: str = aspect_ratio
        # 测试语言优先：单次任务仅生成此语种的 TTS+字幕+变体
        self.test_language: str = test_language
        # 目标视频时长（秒），固定枚举：15 | 30 | 60
        self.target_duration: int = target_duration
        # 本次任务的矩阵裂变数量（洗稿模式下用于告知 LLM 需生成多少个变体）
        self.batch_size: int = batch_size
        # 文案生成模式：'auto'(智能创作) | 'rewrite'(专属文案洗稿防重)
        self.script_mode: str = script_mode
        
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
