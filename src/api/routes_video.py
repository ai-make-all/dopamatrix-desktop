"""
src/api/routes_video.py
————————————————————————
视频资产详情接口 — Video Detail API

端点：
  GET /video/manifest/{file_hash}
    根据视频文件的 MD5 哈希查询对应的基因配方（manifest_data）。
    供前端 VideoDetailView.vue 的 videoManifest 数据驱动使用。

数据流：
  前端 HistoryView 的视频卡片点击 → 携带 file_hash 跳转至 /video/:id
    ↓
  VideoDetailView mounted → GET /api/v1/video/manifest/{file_hash}
    ↓
  本端点查询 video_assets 表，解析 manifest_data JSON 返回
    ↓
  前端用真实数据替换 Mock videoManifest

错误处理：
  - 404: file_hash 不存在或 manifest_data 为空（任务尚未生成 manifest）
  - 422: FastAPI 自动校验路径参数类型
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from .database import get_db
from .models import VideoAsset

router = APIRouter(prefix="/video", tags=["Video Detail"])


# ================================================================== #
# GET /video/manifest/{file_hash}                                      #
# ================================================================== #
@router.get(
    "/manifest/{file_hash}",
    summary="查询视频基因配方",
    description=(
        "根据视频文件的 MD5 哈希（file_hash）查询其视频基因配方（manifest_data）。\n\n"
        "manifest 包含：\n"
        "- `video_id`: 视频唯一标识\n"
        "- `bgm`: 背景音乐文件名\n"
        "- `blocks`: Hook / Body / CTA 区块列表，含时间码、情绪标签、台词\n\n"
        "若资产不存在或 manifest 尚未生成，返回 404。"
    ),
    response_description="视频基因配方 JSON 对象",
)
def get_video_manifest(
    file_hash: str = Path(
        ...,
        description="视频文件的 MD5 十六进制哈希值（32 位小写）",
        min_length=8,
        max_length=64,
        examples=["a3f1c0b2d4e5f678a3f1c0b2d4e5f678"],
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    查询 video_assets 表中对应 file_hash 的 manifest_data 字段。

    设计要点：
    - 同一 file_hash 可能存在多语言变体行，取任意一行即可（manifest 对所有语言相同）。
    - manifest_data 为 JSON 字符串，此处反序列化后直接返回，
      避免前端再次 JSON.parse()。
    - 若 manifest_data 为空或 NULL（历史任务未带 manifest 生成），
      返回 404 并附带明确提示，引导前端展示"基因配方待生成"占位态。
    """
    asset: VideoAsset | None = (
        db.query(VideoAsset)
        .filter(VideoAsset.file_hash == file_hash.lower())
        .first()
    )

    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到 file_hash='{file_hash}' 对应的视频资产，请确认哈希值是否正确。",
        )

    if not asset.manifest_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"视频资产 file_hash='{file_hash}' 存在，"
                "但其基因配方（manifest_data）尚未生成。"
                "该资产可能由旧版引擎生成，或渲染流程未完整执行。"
            ),
        )

    try:
        manifest: dict = json.loads(asset.manifest_data)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"manifest_data 存储格式异常，JSON 解析失败: {exc}",
        )

    return manifest


# ================================================================== #
# GET /video/asset-info/{file_hash}  — 附带资产元信息的扩展版本         #
# ================================================================== #
@router.get(
    "/asset-info/{file_hash}",
    summary="查询视频资产元信息（含 manifest）",
    description=(
        "返回资产基础元信息（file_path、language、created_at）以及 manifest 内容的完整聚合视图，"
        "供前端 VideoDetailView 顶部导航栏展示资产创建时间等上下文。"
    ),
)
def get_video_asset_info(
    file_hash: str = Path(..., min_length=8, max_length=64),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    聚合视图：asset 元信息 + manifest（若存在）。

    与 /manifest/{file_hash} 的区别：
    - 此端点即使 manifest 为空也会返回 200，附 manifest: null
    - 适合前端做 "有 manifest → 渲染基因舱，无 manifest → 渲染降级卡片" 的分支判断
    """
    asset: VideoAsset | None = (
        db.query(VideoAsset)
        .filter(VideoAsset.file_hash == file_hash.lower())
        .first()
    )

    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到 file_hash='{file_hash}' 对应的视频资产。",
        )

    manifest = None
    if asset.manifest_data:
        try:
            manifest = json.loads(asset.manifest_data)
        except json.JSONDecodeError:
            manifest = None

    return {
        "file_hash"   : asset.file_hash,
        "file_path"   : asset.file_path,
        "language"    : asset.language,
        "created_at"  : asset.created_at.isoformat() if asset.created_at else None,
        "has_manifest": manifest is not None,
        "manifest"    : manifest,
    }
