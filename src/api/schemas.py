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
    """
    session_id: Optional[str] = Field(
        default=None,
        description="可选：指定 session_id；留空则由引擎自动生成 UUID。"
    )
    prompt:     str = Field(..., min_length=1, description="剧本要求或主题文案。")
    batch_size: int = Field(default=1, ge=1, le=256, description="矩阵变体数量。")
    local_asset_dir: Optional[str] = Field(
        default=None,
        description=(
            "可选：Tauri Desktop 通过 dialog 选取的本地素材目录绝对路径。"
            "若提供，AssetSelectNode 将优先从该目录扫描 .mp4 / .mov 文件作为视频素材，"
            "而非使用系统默认素材池。"
        ),
    )
    local_logo_dir: Optional[str] = Field(
        default=None,
        description=(
            "可选：Y 轴 Logo 水印目录（透明背景 .png，常驻右上角）。"
            "AssetSelectNode 将把其中的 .png 标注 type='logo'。"
        ),
    )
    local_sticker_dir: Optional[str] = Field(
        default=None,
        description=(
            "可选：Y 轴促销贴纸目录（透明背景 .png，居中弹出）。"
            "AssetSelectNode 将把其中的 .png 标注 type='sticker'。"
        ),
    )
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
