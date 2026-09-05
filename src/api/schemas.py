"""
src/api/schemas.py
———————————————————
Pydantic v2 请求 / 响应模型。
- 严格与 SQLAlchemy ORM 字段对齐
- Response 强制包含 hash 指纹 + 成本预估字段（GrowthOS 去重契约）
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict, model_validator

from .approval_types import VariantStatus
from .task_identity import CLIENT_TASK_ID_NOT_ALLOWED


CLIENT_RESERVATION_AUTHORITY_NOT_ALLOWED = (
    "CLIENT_RESERVATION_AUTHORITY_NOT_ALLOWED"
)
_CLIENT_RESERVATION_AUTHORITY_FIELDS = frozenset(
    {
        "owner_attempt_id",
        "reservation_owner_attempt_id",
        "owner_task_id",
        "execution_id",
        "reservation_lease_ttl_seconds",
        "reservation_heartbeat_interval_seconds",
    }
)


class _ServerOwnedTaskRequest(BaseModel):
    """Reject legacy/client attempts to choose DopaMatrix task authority."""

    @model_validator(mode="before")
    @classmethod
    def reject_client_task_identity(cls, value):
        if isinstance(value, dict) and ({"session_id", "task_id"} & value.keys()):
            raise ValueError(CLIENT_TASK_ID_NOT_ALLOWED)
        return value


class BatchUpdateStatusRequest(BaseModel):
    hashes: List[str] = Field(default_factory=list)
    target_status: Literal[
        VariantStatus.PENDING,
        VariantStatus.APPROVED,
        VariantStatus.REJECTED,
        VariantStatus.DELETED,
    ]


class BatchUpdateStatusResponse(BaseModel):
    message: str = "success"
    updated_count: int
    target_status: VariantStatus
    updated_hashes: List[str] = Field(default_factory=list)
    missing_hashes: List[str] = Field(default_factory=list)
    missing_files: List[str] = Field(default_factory=list)
    cleanup_errors: List[str] = Field(default_factory=list)

# ================================================================== #
# VideoTask Schemas                                                    #
# ================================================================== #

class VideoTaskCreate(_ServerOwnedTaskRequest):
    """
    POST /tasks/submit  请求体。
    调用方（Agent / GrowthOS / CLI / Tauri Desktop）提交一个新的矩阵生成任务。
    弹药完全由内部按 LRU（最少使用）算法自动补给。
    """
    prompt:      str = Field(..., min_length=1, description="剧本要求或主题文案。")
    script_mode: str = Field(
        default="auto",
        description=(
            "文案生成模式：\n"
            "  'auto'    → AI 从零开始智能创作分镜脚本（默认）\n"
            "  'rewrite' → 以用户提供的基准文案为蓝本，裂变出 N 个变体，规避平台音频查重"
        ),
    )
    batch_size: int = Field(default=1, ge=1, le=256, description="矩阵变体数量。")
    aspect_ratio: str = Field(
        default="9:16",
        description=(
            "输出画幅比例。支持三种规格：\n"
            "  '9:16' →  720×1280（竖屏，TikTok / Reels）\n"
            "  '16:9' → 1280×720 （横屏，YouTube / 横版广告）\n"
            "  '1:1'  →  720×720 （方形，Instagram Feed）"
        ),
    )
    test_language: str = Field(
        default="en",
        description=(
            "测试语言优先策略：仅生成该语种的 TTS 音频 + 字幕 + 最终变体。"
            "支持：'en'（英语）| 'ar'（阿语）| 'zh'（中文）等。"
        ),
    )
    target_duration: int = Field(
        default=15,
        description=(
            "目标视频时长（秒），固定枚举值：15 | 30 | 60。"
            "用于驯服 LLM 剧本生成节点，精准控制配音字数与视频总长。"
        ),
    )
    output_dir: Optional[str] = Field(
        default=None,
        description="可选：自定义最终成品视频输出目录绝对路径。"
    )
    webhook_url: Optional[str] = Field(
        default=None,
        description="渲染完成后，本地引擎主动推送结案报告的云端接收地址。"
    )
    client_payload: Optional[dict] = Field(
        default=None,
        description="无结构透传字典，用于外部 Agent/Bot 存放上下文（如 TG 的 chat_id），在 Webhook 中原样奉还。"
    )


class VideoTaskResponse(BaseModel):
    """
    任务查询响应体。
    包含完整的生命周期信息与成本估算 —— GrowthOS/ROI 核算的数据来源。
    """
    model_config = ConfigDict(from_attributes=True)

    task_id:      str
    prompt:       str
    batch_size:   int
    status:       str           # queued | processing | completed | failed
    created_at:   datetime
    finished_at:  Optional[datetime] = None

    # ---- 成本预估字段（Response 强制契约）------------------------- #
    llm_tokens_used:      Optional[int]   = Field(default=None, description="LLM Token 总用量。")
    tts_duration_seconds: Optional[float] = Field(default=None, description="TTS 合成总时长（秒）。")
    estimated_cost_usd:   Optional[float] = Field(default=None, description="综合成本预估（USD）。")

    # ---- 关联的视频资产 ------------------------------------------- #
    assets: List[VideoAssetResponse] = []


class VideoTaskStatusResponse(BaseModel):
    """
    轻量级状态查询响应体（仅状态 + 概要），避免大批量资产列表下的性能开销。
    """
    model_config = ConfigDict(from_attributes=True)

    task_id:    str
    status:     str
    finished_at: Optional[datetime] = None
    estimated_cost_usd: Optional[float] = None


# ================================================================== #
# VideoAsset Schemas                                                   #
# ================================================================== #

class VideoAssetResponse(BaseModel):
    """
    资产响应体。
    file_hash / perceptual_hash 为 GrowthOS 防重去重的核心字段。
    """
    model_config = ConfigDict(from_attributes=True)

    id:              int
    file_path:       str
    language:        str
    file_hash:       str   = Field(..., description="MD5 文件哈希，用于精确去重。")
    perceptual_hash: str   = Field(..., description="感知哈希 (pHash)，用于视觉相似度去重。")
    created_at:      datetime


# 解决 Pydantic 前向引用（VideoTaskResponse 中引用了 VideoAssetResponse）
VideoTaskResponse.model_rebuild()


# ================================================================== #
# Health Check Schema                                                  #
# ================================================================== #

class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"
    db: str = "connected"


# ================================================================== #
# Task Submit Ack (202 Accepted)                                       #
# ================================================================== #

class TaskSubmitAck(BaseModel):
    """
    POST /tasks/submit 的即时响应体（202 Accepted）。

    职责：让前端秒拿到 task_id 以便立即开始轮询，
    同时给出人类可读的 message 说明任务在排队中。
    不包含完整资产列表（那是 GET /tasks/{task_id} 的事）。
    """
    task_id:    str
    status:     str = "queued"
    message:    str = "任务已提交至后台矩阵工厂，请通过 GET /tasks/{task_id} 轮询进度。"

# ================================================================== #
# LocalAsset Schemas                                                 #
# ================================================================== #

class LocalAssetCreate(BaseModel):
    file_paths:  List[str] = Field(..., description="本地素材文件绝对路径列表")
    asset_type:  str = Field(..., description="枚举: 'video' | 'logo' | 'sticker' | 'image' | 'vfx' | 'audio_bgm' | 'audio_sfx' | 'sfx' | 'text_template' | 'scene_master_video'")
    video_role:  str = Field(default="general", description="枚举: 'hook', 'body', 'general'")
    tags:        Optional[List[str]] = Field(default=[], description="自定义标签内容，例如 ['高转化', 'Hook']")
    entity_id:   Optional[str] = Field(default=None, description="素材归属实体/产品线标识，例如 '@DogFood_BrandA'")
    asset_name:  Optional[str] = Field(default=None, description="人类可读名称或备注，用于看板绝对寻址拖拽识别")

class AssetRoleUpdate(BaseModel):
    video_role: str = Field(..., description="枚举: 'hook', 'body', 'general'")

class AssetTagsUpdate(BaseModel):
    tags: List[str] = Field(..., description="全量覆盖的语义标签数组")

class AssetAppendTags(BaseModel):
    tags: List[str] = Field(..., description="追加合并的语义标签数组（Set 去重，不覆盖已有标签）")

class LocalAssetImportResponse(BaseModel):
    success_count: int
    skipped_count: int
    message: str


class TextAssetCreate(BaseModel):
    asset_name:     str = Field(..., description="文本资产的人类可读名称")
    content_matrix: dict = Field(..., description="多语种内容字典，如 {'zh': '...', 'en': '...', 'ar': '...'}")


class LocalAssetResponse(BaseModel):
    """
    前端查询素材库接口的响应模型
    """
    model_config = ConfigDict(from_attributes=True)

    id:              int
    file_hash:       str
    file_path:       str
    asset_type:      str
    video_role:      str
    usage_count:     int
    tags:            Optional[List[str]] = None
    is_exhausted:    bool
    is_deleted:      bool = False
    created_at:      datetime
    last_used_at:    Optional[datetime] = None
    business_scopes: Optional[List[str]] = None
    entity_id:       Optional[str] = None
    asset_name:      Optional[str] = None
    manifest:        Optional[dict] = None


# ================================================================== #
# Story DSL Schemas  (Phase 4.1 — DSLParserNode 契约)                #
# ================================================================== #

class BlueprintMeta(BaseModel):
    """
    导演蓝图全局社交媒体投放文案（Phase 9.12 CF 边缘归因管线）。
    由 LLM 在 draft_blueprint 时一同生成，存入 TaskHistory.prompt_details["meta"]。
    导出 ZIP 时，social_caption 中的 {TRACKING_LINK} 将被替换为 CF KV 短链。
    """
    social_title:    str = Field(..., description="极具网感的短标题")
    social_caption:  str = Field(..., description="情绪化描述文案，必须包含 {TRACKING_LINK}")
    social_hashtags: str = Field(..., description="高流量话题标签")
    human_drive:     str = Field(..., description="核心利用的人性本能/七宗罪，单选")
    emotional_tag:   str = Field(..., description="提炼的情绪标签，用于文件命名")


class DSLBeatNode(BaseModel):
    """
    Story DSL 时间轴上的一个 Beat 节点（单轨线性一体化架构，Phase 9.11.2）。

    address_mode 决定寻址策略：
      'locked' → 精确锁定，直接按 asset_hashes 查库；
                 若同时携带 semantic_tags，则并发查 Y 轴叠加素材。
      'smart'  → 智能抽卡，按 semantic_tags 匹配并打分，
                 防疲劳优先选 usage_count 低且未耗尽的素材。

    script_text 与资产图层生死同寿，台词（灵魂）直接内聚于本节拍物理时空舱中；
    duration 为 LLM 生成时的时长预估，供字幕时间轴计算使用。
    """
    beat:          str            = Field(..., description="Beat 标识符，如 'hook_01'、'body_02'。")
    role:          str            = Field(..., description="角色标签，如 'hook'、'body'、'cta'。")
    address_mode:  str            = Field(..., description="寻址模式：'locked' | 'smart'。")
    asset_hashes:  List[str]      = Field(default_factory=list, description="locked 模式下指定的素材 MD5 哈希列表。")
    semantic_tags: List[str]      = Field(default_factory=list, description="语义标签列表，用于 smart 模式匹配与 Y 轴叠加查询。")
    script_text:   Optional[str]  = Field(default="", description="内聚于该节拍的高光口播台词；TTS 管线直接原位消费，无需旁路 script_data 字典。")
    visual_script: Optional[str]  = Field(default="", description="动作描写与画面分镜指令")
    emotion:       Optional[str]  = Field(default="", description="该分镜的核心情绪标签")
    layout_hints:  Dict[str, str] = Field(default_factory=dict, description="asset hash -> layout position key.")
    tts_params:    Optional[str]  = Field(default="", description="该情绪下的 TTS 语速/语调特征，如 'fast, high-pitch'。")
    duration:      Optional[float] = Field(default=None, description="该节拍预估时长（秒），LLM 生成时填写，字幕时间轴兜底计算依据。")

    # ── Phase 9.12 社交媒体归因字段（Beat 级可选，全局 meta 优先）─────────── #
    social_title:    Optional[str] = Field(default=None, description="该节拍对应的社交媒体短标题（可选，全局 meta.social_title 优先）。")
    social_caption:  Optional[str] = Field(default=None, description="该节拍对应的社交文案，含 {TRACKING_LINK} 占位符（可选）。")
    social_hashtags: Optional[str] = Field(default=None, description="该节拍对应的话题标签，空格分隔（可选）。")
    emotional_tag:   Optional[str] = Field(default=None, description="该节拍对应的情绪微标（可选，全局 meta.emotional_tag 优先）。")


class StoryDSLPayload(BaseModel):
    """
    前端提交的 Story DSL 完整载荷。
    engine_type 区分内容型 ('content') 与 UA 投放型 ('ua') 两类渲染策略。
    """
    engine_type:    str               = Field(..., description="引擎类型：'content' | 'ua'。")
    timeline:       List[DSLBeatNode] = Field(..., description="Beat 节点时间轴，顺序即渲染顺序。")
    meta:           Optional[BlueprintMeta] = Field(default=None, description="全局社交文案与情绪归因元数据")
    prompt:         Optional[str]     = Field(default=None, description="用户输入的提示词。若存在，将触发大模型与 TTS 配音管线。")
    user_hard_tags: List[str]         = Field(default_factory=list, description="前端剥离的硬约束标签列表，DSLParserNode 寻址时执行一票否决过滤。")
    language:       Optional[str]     = Field(default=None, description="目标渲染语种，如 'zh'、'en'、'ar'；供 FFmpeg 渲染阶段从 text_template content_matrix 提取对应文本。")


# ── DSL 解析结果 Schema ─────────────────────────────────────────── #

class ResolvedLayer(BaseModel):
    """单个图层（X 轴 / Y 轴）的解析结果。"""
    layer_index: int             = Field(..., description="图层层级：0 = X轴主视频，1+ = Y轴叠加层。")
    asset_id:    int             = Field(..., description="LocalAsset 主键 ID。")
    file_path:   str             = Field(..., description="素材本地绝对路径，直接用于 FFmpeg 指令；text_template 以 virtual:// 为前缀。")
    asset_type:  str             = Field(..., description="素材类型：'video' / 'logo' / 'sticker' / 'text_template' 等。")
    file_hash:   str             = Field(..., description="素材 MD5 哈希（溯源 & 防重契约）。")
    asset_name:  Optional[str]   = Field(default=None, description="人类可读名称。")
    matched_tags: List[str]      = Field(default_factory=list, description="实际命中的语义标签。")
    manifest:    Optional[dict]  = Field(default=None, description="虚拟资产多态载荷；text_template 携带 content_matrix 多语种文本字典。")
    layout:      Optional[str]   = Field(
        default=None,
        description=(
            "DSL 最高级空间排版意图（Phase 9.7.2 三级控制体系 Level-1）。"
            "取值：'center' | 'bottom_center' | 'top_center' | 'top_left' | 'top_right' | 'bottom_left'。"
            "留空则由渲染引擎按 Manifest default_position → 系统默认 'center' 顺序降级处理。"
        ),
    )


class BeatCompilationResult(BaseModel):
    """单个 Beat 节点的编译结果。"""
    beat:         str                  = Field(..., description="Beat 标识符（原样透传）。")
    role:         str                  = Field(..., description="角色标签（原样透传）。")
    address_mode: str                  = Field(..., description="实际使用的寻址模式。")
    layers:       List[ResolvedLayer]  = Field(default_factory=list, description="已解析的图层列表（按 layer_index 升序）。")
    resolved:     bool                 = Field(..., description="True = 至少找到一个主轴素材；False = 寻址失败。")
    warnings:     List[str]            = Field(default_factory=list, description="寻址过程中产生的警告信息。")
    script_text:  Optional[str]        = Field(default=None, description="原样透传的节拍台词内容（单轨线性架构，Phase 9.11.2）。")


class CompilationPlanSummary(BaseModel):
    total_beats:      int
    resolved_beats:   int
    unresolved_beats: int


class CompilationPlan(BaseModel):
    """
    DSLParserNode 输出的渲染蓝图（Dry-run）。
    前端可用此结构核对寻址结果，确认无误后再触发真实 FFmpeg 渲染流水线。
    """
    engine_type:      str                       = Field(..., description="原样透传的引擎类型。")
    beats:            List[BeatCompilationResult]
    unresolved_beats: List[str]                 = Field(default_factory=list, description="未能解析的 Beat 标识符列表。")
    summary:          CompilationPlanSummary


# ================================================================== #
# Render DSL Schemas  (Phase 5.1 — DSL → Timeline → FFmpeg 全链路)   #
# ================================================================== #

class RenderDSLRequest(_ServerOwnedTaskRequest):
    """
    POST /tasks/render-dsl 请求体。

    在 StoryDSLPayload 基础上追加渲染配置字段，
    供适配器计算节拍时长和 WorkflowContext 初始化使用。
    """
    engine_type:     str              = Field(..., description="引擎类型：'content' | 'ua'。")
    timeline:        List[DSLBeatNode] = Field(..., description="Beat 节点时间轴，顺序即渲染顺序。")
    meta:            Optional[BlueprintMeta] = Field(default=None, description="全局社交文案与情绪归因元数据")

    # ── 渲染配置 ─────────────────────────────────────────────────── #
    aspect_ratio:    str             = Field(
        default="9:16",
        description="输出画幅比例：'9:16' | '16:9' | '1:1'。",
    )
    target_duration: int             = Field(
        default=15,
        description="目标视频总时长（秒），用于计算每 Beat 均等时长切分。",
    )
    batch_size:      int             = Field(
        default=1, ge=1, le=20,
        description="批量裂变数量：同时 dispatch N 个独立渲染任务，每个任务拥有唯一 task_id。",
    )
    test_language:   str             = Field(
        default="en",
        description="输出语种：'en' | 'ar' | 'zh'，透传至 WorkflowContext.test_language。",
    )
    tenant_id:       Optional[str]   = Field(
        default=None,
        description=(
            "可选租户声明；实际安全边界由 X-Local-User 请求头权威决定。"
        ),
    )
    prompt:          Optional[str]   = Field(
        default=None,
        description="用户输入的提示词。若存在，将触发大模型与 TTS 配音管线。",
    )
    mode:            str              = Field(
        default="auto",
        description="导演节点模式：'auto' | 'rewrite'，透传 DirectorNode / draft-blueprint。",
    )
    variant_planning_policy: Literal[
        "legacy",
        "exact_main_visual",
        "exact_main_visual_balanced",
    ] = Field(
        default="legacy",
        description=(
            "批次变体规划策略。legacy 保持既有 worker-local resolution；"
            "exact_main_visual 请求精确主视觉组合唯一性规划；"
            "exact_main_visual_balanced 在相同精确唯一性约束上优化 Beat 轴覆盖。"
        ),
    )
    historical_novelty_mode: Literal["OFF", "OBSERVE", "ADVISORY"] = Field(
        default="OFF",
        description=(
            "Historical exact-match observation mode. Phase 3D-2B supports only "
            "OFF, OBSERVE, and non-enforcing ADVISORY."
        ),
    )
    reservation_conflict_mode: Literal["OFF", "ENFORCE"] = Field(
        default="OFF",
        description=(
            "Short-lived cross-task Reservation coordination policy. OFF performs "
            "no Reservation coordination. ENFORCE prevents concurrently active "
            "tasks from authoritatively using the same planning fingerprint. It "
            "is not historical, permanent, copyright, or global deduplication."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def reject_client_reservation_authority(cls, value):
        if isinstance(value, dict) and (
            _CLIENT_RESERVATION_AUTHORITY_FIELDS & value.keys()
        ):
            raise ValueError(CLIENT_RESERVATION_AUTHORITY_NOT_ALLOWED)
        return value
    user_hard_tags:  List[str]        = Field(
        default_factory=list,
        description="前端剥离的硬约束标签，透传至 DSLParserNode 寻址引擎做一票否决过滤。",
    )
    enable_tts:       bool             = Field(
        default=True,
        description="是否生成并混合 AI 语音。False = 跳过 TTSNode，仅保留 BGM 音轨。",
    )
    enable_subtitles: bool             = Field(
        default=True,
        description="是否在视频上渲染字幕。False = 跳过 SubtitleNode，不烧录 .ass 字幕轨。",
    )


class DraftBlueprintRequest(BaseModel):
    """POST /tasks/draft-blueprint — 战术板同步起草蓝图。"""

    prompt:         str       = Field(..., min_length=1, description="用户创意或主题描述。")
    mode:           str       = Field(default="auto", description="'auto' | 'rewrite'。")
    duration:       int       = Field(default=15, ge=5, le=120, description="目标总时长（秒）。")
    langs:          List[str] = Field(
        default_factory=lambda: ["en"],
        min_length=1,
        description="目标语种列表，如 ['en','ar']。",
    )
    available_tags: List[str] = Field(
        default_factory=list,
        description="素材库去重标签列表，LLM 生成 semantic_tags 时必须从中挑选，禁止自由捏造。",
    )
    user_hard_tags: List[str] = Field(
        default_factory=list,
        description="前端剥离的硬约束标签，注入 Jinja 模板后作为 LLM 绝对军令强制写入 timeline。",
    )


class EnhancePromptRequest(BaseModel):
    """POST /tasks/enhance-prompt — 魔法扩写与自动打标。"""

    prompt:         str       = Field(..., min_length=1, description="用户极简短句。")
    available_tags: List[str] = Field(
        default_factory=list,
        description="素材库去重标签列表，供 LLM 挑选 @ 标签。",
    )


class RenderDSLAck(BaseModel):
    """
    POST /tasks/render-dsl 的即时响应体（202 Accepted）。
    渲染任务已下发至后台线程，前端通过 WS 事件总线接收进度推送。
    """
    status:     str = "processing"
    task_id:    str
    message:    str = "渲染任务已下发，请通过 WebSocket 事件总线监听进度。"


# ================================================================== #
# Submit-DSL Response  (Phase 5.2 — submit-dsl 全链路升级)           #
# ================================================================== #

class DSLSubmitResponse(CompilationPlan):
    """
    POST /tasks/submit-dsl 升级后的响应体（202 Accepted）。

    继承 CompilationPlan 的全部字段（前端可同时核对寻址蓝图），
    并追加渲染任务元数据，使前端无需二次请求即可获得 task_id。

    字段说明：
      task_id       — DopaMatrix 生成的 UUID，与 WorkflowContext.task_id 保持一致，
                      同时作为 WS 事件的 taskId 和输出文件名后缀。
      render_status — 任务下发状态（固定为 "rendering"，区别于 HTTP status）。
      message       — 人类可读的操作说明。
    """
    task_id:       str       = Field(..., description="首个任务的 UUID（向后兼容单任务场景）。")
    task_ids:      List[str] = Field(default_factory=list, description="全部下发任务的 UUID 列表，长度 = batch_size。")
    render_status: str       = Field(default="rendering", description="后台渲染下发状态。")
    message:       str       = Field(
        default="渲染任务已在后台下发，请在输出目录查看或通过 WebSocket 监听进度。",
        description="人类可读的操作结果说明。",
    )
