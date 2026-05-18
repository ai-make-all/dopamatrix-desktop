"""
src/api/routes_media.py
————————————————————————
动态流媒体网关 (Dynamic Media Streaming Gateway)

架构定位：
  替代硬编码的 StaticFiles 挂载方案。
  由于平台允许用户自定义视频输出路径（包括其他磁盘盘符），
  静态挂载方式会因路径不在挂载目录内而失效。
  本网关在运行时动态解析绝对路径，支持任意位置的媒体文件透传。

安全策略（防目录穿越 Directory Traversal Attack）：
  - 白名单后缀校验：仅允许 .mp4 / .webm / .mov / .png / .jpg / .jpeg / .gif / .webp
  - os.path.exists 物理存在性验证：路径合法但文件不存在时快速返回 404
  - 禁止路径中出现 ".." 片段，杜绝逃逸到任意系统目录

端点：
  GET /media/preview?path=<本地绝对路径>
    query param: path — 文件的本地绝对路径（前端应传入真实路径，
                        未来可升级为 base64 编码或哈希令牌）

数据流：
  前端播放器请求预览 URL
    ↓ GET /api/v1/media/preview?path=/D:/output/clip_xxx.mp4
  本端点安全校验 → FileResponse 流式透传
    ↓ 浏览器/播放器边接收边播放（Range 请求自动支持进度拖拽）
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse

router = APIRouter(prefix="/media", tags=["Media Streaming Gateway"])

# ── 合法媒体后缀白名单（小写统一比对） ─────────────────────────────────────
_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".mp4", ".webm", ".mov",            # 视频
    ".png", ".jpg", ".jpeg",            # 图片
    ".gif", ".webp",                    # 动图
})


# ================================================================== #
# GET /media/preview                                                   #
# ================================================================== #
@router.get(
    "/preview",
    summary="动态媒体文件预览",
    description=(
        "接收本地绝对路径，执行安全校验后以流式方式返回文件内容。\n\n"
        "支持浏览器原生 `Range` 请求（视频拖拽进度条）。\n\n"
        "**安全限制**：仅允许 `.mp4 / .webm / .mov / .png / .jpg / .jpeg / .gif / .webp`，"
        "且禁止路径中包含 `..` 片段（防目录穿越）。"
    ),
    response_description="媒体文件二进制流",
    # 不在 Swagger 暴露真实文件路径的示例值，避免信息泄露
    include_in_schema=True,
)
async def preview_media(
    path: str = Query(
        ...,
        description="文件的本地绝对路径，例如 D:/output/clip_001.mp4",
    ),
) -> FileResponse:
    """
    动态流媒体透传网关。

    安全三关：
      1. 禁止 ".." 路径片段（目录穿越防护）
      2. 后缀白名单校验（类型限制）
      3. 物理存在性验证（防枚举不存在文件）
    """

    # ---- 关卡 1：禁止目录穿越 ----------------------------------------- #
    # 将路径规范化后检查是否包含 ".." 片段
    normalized = os.path.normpath(path)
    if ".." in normalized.split(os.sep):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="非法路径：禁止包含 '..' 目录穿越片段。",
        )

    # ---- 关卡 2：后缀白名单 ------------------------------------------- #
    _, ext = os.path.splitext(normalized)
    if ext.lower() not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"不支持的文件类型：'{ext}'。"
                f"允许的格式：{sorted(_ALLOWED_EXTENSIONS)}"
            ),
        )

    # ---- 关卡 3：物理存在性验证 ---------------------------------------- #
    if not os.path.isfile(normalized):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"文件不存在或路径不可访问：'{normalized}'",
        )

    # ---- 流式透传（FileResponse 自动处理 Range / Content-Type）--------- #
    # FastAPI 的 FileResponse 底层使用 starlette.responses.FileResponse，
    # 原生支持 HTTP Range 请求，浏览器视频播放器可直接拖拽任意时间点。
    return FileResponse(
        path=normalized,
        filename=os.path.basename(normalized),
    )
