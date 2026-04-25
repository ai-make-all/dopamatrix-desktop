"""
src/api/schemas.py
———————————————————
Pydantic v2 请求 / 响应模型。
- 严格与 SQLAlchemy ORM 字段对齐
- Response 强制包含 hash 指纹 + 成本预估字段（GrowthOS 去重契约）
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, ConfigDict


# ================================================================== #
# VideoTask Schemas                                                    #
# ================================================================== #

class VideoTaskCreate(BaseModel):
    """
    POST /tasks/submit  请求体。
    调用方（Agent / GrowthOS / CLI / Tauri Desktop）提交一个新的矩阵生成任务。
    弹药完全由内部按 LRU（最少使用）算法自动补给。
    """
    session_id: Optional[str] = Field(
        default=None,
        description="可选：指定 session_id；留空则由引擎自动生成 UUID。"
    )
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

    id:           int
    session_id:   str
    prompt:       str
    batch_size:   int
    status:       str           # pending | processing | completed | failed
    created_at:   datetime
    finished_at:  Optional[datetime] = None

    # ---- 成本预估字段（Response 强制契约）------------------------- #
    llm_tokens_used:      Optional[int]   = Field(None, description="LLM Token 总用量。")
    tts_duration_seconds: Optional[float] = Field(None, description="TTS 合成总时长（秒）。")
    estimated_cost_usd:   Optional[float] = Field(None, description="综合成本预估（USD）。")

    # ---- 关联的视频资产 ------------------------------------------- #
    assets: List[VideoAssetResponse] = []


class VideoTaskStatusResponse(BaseModel):
    """
    轻量级状态查询响应体（仅状态 + 概要），避免大批量资产列表下的性能开销。
    """
    model_config = ConfigDict(from_attributes=True)

    id:         int
    session_id: str
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
    task_id:         int
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
    不包含完整资产列表（那是 GET /tasks/{id} 的事）。
    """
    task_id:    int
    session_id: str
    status:     str = "queued"
    message:    str = "任务已提交至后台矩阵工厂，请通过 GET /tasks/{task_id} 轮询进度。"

# ================================================================== #
# LocalAsset Schemas                                                 #
# ================================================================== #

class LocalAssetCreate(BaseModel):
    file_paths:  List[str] = Field(..., description="本地素材文件绝对路径列表")
    asset_type:  str = Field(..., description="枚举: 'video', 'logo', 'sticker'")
    video_role:  str = Field(default="general", description="枚举: 'hook', 'body', 'general'")
    tags:        Optional[List[str]] = Field(default=[], description="自定义标签内容，例如 ['高转化', 'Hook']")
    entity_id:   Optional[str] = Field(default=None, description="素材归属实体/产品线标识，例如 '@DogFood_BrandA'")
    asset_name:  Optional[str] = Field(default=None, description="人类可读名称或备注，用于看板绝对寻址拖拽识别")

class AssetRoleUpdate(BaseModel):
    video_role: str = Field(..., description="枚举: 'hook', 'body', 'general'")

class LocalAssetImportResponse(BaseModel):
    success_count: int
    skipped_count: int
    message: str


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
    created_at:      datetime
    last_used_at:    Optional[datetime] = None
    business_scopes: Optional[List[str]] = None
    entity_id:       Optional[str] = None
    asset_name:      Optional[str] = None
