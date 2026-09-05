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
    Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, JSON,
    CheckConstraint, Enum as SAEnum, Index, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .approval_types import VariantStatus
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
    - task_id    : DopaMatrix 为一次提交生成的公开 UUID
    - status     : queued → processing → completed | failed
    """
    __tablename__ = "video_tasks"
    __table_args__ = (
        CheckConstraint(
            "reservation_conflict_mode IN ('OFF', 'ENFORCE')",
            name="ck_video_tasks_reservation_conflict_mode",
        ),
        CheckConstraint(
            "planning_policy IN ("
            "'legacy', 'exact_main_visual', 'exact_main_visual_balanced'"
            ")",
            name="ck_video_tasks_planning_policy",
        ),
        Index(
            "ix_video_tasks_rollout_readiness",
            "reservation_conflict_mode",
            "planning_policy",
            "created_at",
        ),
    )

    id              = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_id         = Column(String(64), unique=True, nullable=False, index=True)
    prompt          = Column(Text, nullable=False)               # 剧本要求
    batch_size      = Column(Integer, nullable=False, default=1) # 矩阵数量
    status          = Column(String(20), nullable=False, default="queued")
                                                                 # queued/processing/completed/failed
    reservation_conflict_mode = Column(
        String(16),
        nullable=False,
        default="OFF",
        server_default="OFF",
    )
    planning_policy = Column(
        String(64),
        nullable=False,
        default="legacy",
        server_default="legacy",
    )
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
        return f"<VideoTask id={self.id} task_id={self.task_id} status={self.status}>"


# ================================================================== #
# ReservationRunDiagnostic — tenant-local operational observation     #
# ================================================================== #
class ReservationRunDiagnostic(Base):
    """Best-effort operational facts for one admitted public ENFORCE task.

    This row is not Reservation authority and is never consulted by planning,
    confirmation, fencing, terminal persistence, or task lifecycle decisions.
    """

    __tablename__ = "reservation_run_diagnostics"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_id = Column(String(64), unique=True, nullable=False, index=True)
    planning_policy = Column(String(64), nullable=False)
    requested_count = Column(Integer, nullable=False)
    planning_observed = Column(Boolean, nullable=False, default=False)
    planned_count = Column(Integer, nullable=True)
    succeeded_count = Column(Integer, nullable=True)
    failed_count = Column(Integer, nullable=True)
    reservation_conflict_count = Column(Integer, nullable=False, default=0)
    had_reservation_conflict = Column(Boolean, nullable=False, default=False)
    zero_plan_conflict = Column(Boolean, nullable=False, default=False)
    partial_plan = Column(Boolean, nullable=False, default=False)
    authority_lost = Column(Boolean, nullable=False, default=False)
    terminal_persist_failed = Column(Boolean, nullable=False, default=False)
    worker_lease_config_failed = Column(Boolean, nullable=False, default=False)
    cleanup_warning = Column(Boolean, nullable=False, default=False)
    terminal_status = Column(String(20), nullable=True, index=True)
    error_code = Column(String(64), nullable=True)
    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        index=True,
    )
    finished_at = Column(DateTime(timezone=True), nullable=True)


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
    manifest_data    = Column(Text,        nullable=True)         # 视频基因配方 JSON（对齐前端 VideoDetailView）
    created_at       = Column(DateTime(timezone=True), nullable=False, default=_now)

    # ---- 关联 ----------------------------------------------------- #
    task = relationship("VideoTask", back_populates="assets")

    def __repr__(self) -> str:
        return (
            f"<VideoAsset id={self.id} lang={self.language} "
            f"file_hash={self.file_hash[:8]}…>"
        )


# ================================================================== #
# LocalAsset — DAM 本地素材库                                        #
# ================================================================== #
class LocalAsset(Base):
    """
    DAM 本地素材库模型。用于管理用户导入的 X轴视频骨料、Logo水印、贴纸等。
    - file_hash: MD5（防重复导入契约）
    """
    __tablename__ = "local_assets_inventory"

    id           = Column(Integer, primary_key=True, index=True, autoincrement=True)
    file_hash    = Column(String(64), unique=True, nullable=False, index=True)
    file_path    = Column(String(512), nullable=False)        # 本地绝对路径
    asset_type   = Column(String(20), nullable=False)         # 'video', 'logo', 'sticker',
                                                              # 'audio_bgm', 'audio_sfx', 'audio_tts'
    video_role   = Column(String(20), nullable=False, default="general") # 'hook', 'body', 'general'
    usage_count  = Column(Integer, nullable=False, default=0)
    tags         = Column(JSON, nullable=True)                # 自定义标签列表
    emotion_tag  = Column(String(50), index=True, nullable=True)         # BGM 情绪抽卡标签（如 asmr, cyberpunk）
    is_exhausted     = Column(Boolean, nullable=False, default=False)
    is_deleted       = Column(Boolean, nullable=False, default=False, index=True)  # DAM 逻辑删除 → 回收站
    created_at       = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_used_at     = Column(DateTime(timezone=True), nullable=True)
    business_scopes  = Column(JSON, nullable=True,
                              default=lambda: ["content", "ua"])  # 跨界业务线可见性白名单
    entity_id        = Column(String(128), index=True, nullable=True)  # 素材归属实体/产品线（如 @DogFood_BrandA）
    asset_name       = Column(String(255), nullable=True)              # 人类可读名称，用于看板绝对寻址
    manifest         = Column(JSON, nullable=True)                     # 多态载荷（text_template 存 content_matrix 等）

    def __repr__(self) -> str:
        return f"<LocalAsset id={self.id} type={self.asset_type} hash={self.file_hash[:8]}…>"


# ================================================================== #
# TaskHistory — 历史记录表                                              #
# ================================================================== #
class TaskHistory(Base):
    """
    任务历史记录。
    用于在任务成功跑完后，固化保存最终产出的内容和溯源信息。
    """
    __tablename__ = "task_history"

    id             = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_id        = Column(String(64), unique=True, index=True, nullable=False)
    prompt         = Column(String, nullable=False)        # 剧本要求
    batch_size     = Column(Integer, nullable=False, default=1)
    duration       = Column(Float, nullable=False, default=0.0) # 总耗时（秒）
    output_assets  = Column(JSON, nullable=False)          # 生成的资产列表 [{"path": "...", "hash": "..."}]
    prompt_details = Column(Text, nullable=True)           # {"meta": ..., "timeline": ...} JSON，供归因与台词回显
    created_at     = Column(DateTime(timezone=True), nullable=False, default=_now)

    def __repr__(self) -> str:
        return f"<TaskHistory id={self.id} task_id={self.task_id} prompt={self.prompt[:10]}…>"


# ================================================================== #
# VariantApproval — 变体审批状态机                                      #
# ================================================================== #
class VariantApproval(Base):
    """
    记录每个视频变体的质检审批状态。

    主键语义：(task_id, asset_hash) 联合唯一
      task_id   : 对应 TaskHistory.task_id（DopaMatrix server UUID）
      asset_hash: 视频文件 MD5（TaskHistory.output_assets[].hash）

    status 生命周期：PROCESSING → PENDING → APPROVED | REJECTED → DELETED
      支持人工恢复：REJECTED → PENDING | APPROVED
    """
    __tablename__ = "variant_approvals"
    __table_args__ = (
        UniqueConstraint("task_id", "asset_hash", name="uq_variant_approval"),
    )

    id          = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_id     = Column(String(64),  nullable=False, index=True)  # TaskHistory.task_id
    asset_hash  = Column(String(64),  nullable=False, index=True)  # 视频 MD5
    file_path   = Column(String(512), nullable=False)              # 视频物理路径
    cover_path  = Column(String(512), nullable=True,  default="")  # 封面帧路径
    status      = Column(
        SAEnum(
            VariantStatus,
            name="variant_status",
            native_enum=False,
            validate_strings=True,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=VariantStatus.PENDING,
        index=True,
    )
    # ── Phase 9.12 社交媒体归因字段（从 TaskHistory.prompt_details["meta"] 回填）── #
    social_title    = Column(String(512), nullable=True)           # 极具网感短标题
    social_caption  = Column(Text,        nullable=True)           # 含 {TRACKING_LINK} 的情绪化文案
    social_hashtags = Column(String(512), nullable=True)           # 空格分隔的话题标签
    human_drive     = Column(String(64),  nullable=True)           # 核心利用的人性本能/七宗罪
    emotional_tag   = Column(String(64),  nullable=True)           # 情绪微标（Phase 9.13 扁平化命名）
    tracking_link   = Column(String(512), nullable=True)           # 已持久化的专属 CF 追踪短链
    exported_at     = Column(DateTime(timezone=True), nullable=True)  # 首次成功生成交付包的时间

    operator    = Column(String(128), nullable=False, default="system")
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at  = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    def __repr__(self) -> str:
        return (
            f"<VariantApproval id={self.id} task={self.task_id[:8]} "
            f"hash={self.asset_hash[:8]} status={self.status}>"
        )


class VariantStatusAudit(Base):
    """Append-only audit trail for every variant status transition."""

    __tablename__ = "variant_status_audits"

    id          = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_id     = Column(String(64), nullable=False, index=True)
    asset_hash  = Column(String(64), nullable=False, index=True)
    from_status = Column(String(20), nullable=True)
    to_status   = Column(String(20), nullable=False)
    operator    = Column(String(128), nullable=False, default="system")
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now, index=True)

