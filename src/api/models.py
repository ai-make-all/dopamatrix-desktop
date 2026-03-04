"""
src/api/models.py
———————————————————
SQLAlchemy ORM 数据表定义。

表结构：
  VideoTask  — 记录每一次矩阵生成任务（生命周期管理）
  VideoAsset — 记录生成的视频资产与防重指纹
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import relationship

from .database import Base


def _now() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(timezone.utc)


# ================================================================== #
# VideoTask — 任务生命周期记录                                          #
# ================================================================== #
class VideoTask(Base):
    """
    一次矩阵生成任务。
    - session_id : 对应 WorkflowContext 中的 session_id
    - status     : pending → processing → completed | failed
    """
    __tablename__ = "video_tasks"

    id              = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id      = Column(String(64), unique=True, nullable=False, index=True)
    prompt          = Column(Text, nullable=False)               # 剧本要求
    batch_size      = Column(Integer, nullable=False, default=1) # 矩阵数量
    status          = Column(String(20), nullable=False, default="pending")
                                                                 # pending/processing/completed/failed
    created_at      = Column(DateTime(timezone=True), nullable=False, default=_now)
    finished_at     = Column(DateTime(timezone=True), nullable=True)

    # 成本预估字段（USD）
    llm_tokens_used       = Column(Integer, nullable=True)       # LLM Token 用量
    tts_duration_seconds  = Column(Float,   nullable=True)       # TTS 时长（秒）
    estimated_cost_usd    = Column(Float,   nullable=True)       # 综合成本估算（USD）

    # ---- 关联 ----------------------------------------------------- #
    assets = relationship(
        "VideoAsset",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<VideoTask id={self.id} session={self.session_id} status={self.status}>"


# ================================================================== #
# VideoAsset — 视频资产 & 防重指纹                                       #
# ================================================================== #
class VideoAsset(Base):
    """
    生成后的视频资产及其指纹，供 GrowthOS 等上层系统去重防重。
    - file_hash       : MD5（或 SHA-256）文件哈希
    - perceptual_hash : 感知哈希（pHash），防视觉相似度重复；初期可为空
    """
    __tablename__ = "video_assets"

    id               = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_id          = Column(Integer, ForeignKey("video_tasks.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    file_path        = Column(String(512), nullable=False)        # 相对项目根的路径
    language         = Column(String(16),  nullable=False)        # "zh" / "ar" / "en" …
    file_hash        = Column(String(64),  nullable=False, index=True)   # MD5 hex
    perceptual_hash  = Column(String(128), nullable=False, default="")   # pHash；可预留空
    created_at       = Column(DateTime(timezone=True), nullable=False, default=_now)

    # ---- 关联 ----------------------------------------------------- #
    task = relationship("VideoTask", back_populates="assets")

    def __repr__(self) -> str:
        return (
            f"<VideoAsset id={self.id} lang={self.language} "
            f"file_hash={self.file_hash[:8]}…>"
        )
