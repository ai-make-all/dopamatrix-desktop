"""
src/api/routes_matrix.py
———————————————————
DopaMatrix — 审批状态机 & 交付包导出 API（Phase 9.13）

端点列表：
  PUT  /matrix/variants/{task_id}/{asset_hash}/status
       → 更新单个变体的审批状态（PENDING / APPROVED / REJECTED）
         首次 Upsert 时，自动从 TaskHistory.prompt_details["meta"] 回填社交字段。
  GET  /matrix/approvals
       → 查询审批状态表（按 task_id 或全量），返回 {asset_hash: status} 字典
  GET  /matrix/export
       → 将指定 task_id（或全部）中 APPROVED 的视频打包为 ZIP 流式返回；
         ZIP 内含 videos/ 目录（视频文件）+ 矩阵投放文案对照表.csv
         CSV 每行含：视频文件名、社交标题、替换了 {TRACKING_LINK} 后的描述文案、标签、短链接

设计原则：
  - Upsert 语义：首次设置时自动从 TaskHistory 中查找 file_path，
    避免前端需要传递完整元数据。
  - 全内存 ZIP：使用 io.BytesIO + zipfile，零磁盘 IO，适合小批量导出。
  - CF KV 短链：通过 CloudflareKVAdapter 生成归因短链，替换 {TRACKING_LINK} 占位符。
  - 自愈兼容：模型新增表通过 evolve_schema + create_all 自动建表，
    无需手动迁移脚本。
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import get_db
from .models import TaskHistory, VariantApproval
from src.services.tracking_adapter import CloudflareKVAdapter

# 模块级单例，复用 httpx 连接池（Mock 模式下无网络开销）
_tracking_adapter = CloudflareKVAdapter()

router = APIRouter(prefix="/matrix", tags=["Matrix Approval"])


# ── Pydantic 请求体 ────────────────────────────────────────────────────
class VariantStatusPayload(BaseModel):
    status: Literal["PENDING", "APPROVED", "REJECTED"]


# ── 工具 ──────────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def sanitize_filename(name: str) -> str:
    """剔除 Windows/Mac 文件系统非法字符及空格。"""
    safe_name = re.sub(r'[\\/:*?"<>|\s]', '', name)
    return safe_name or "Unknown"


def _build_safe_filename(
    account_id: str,
    core_tag: str,
    hook_tag: str,
    hash_suffix: str,
) -> str:
    """双轨混合重命名：{account_id}_{core_tag}_{hook_tag}_{hash_suffix}.mp4"""
    raw_filename = f"{account_id}_{core_tag}_{hook_tag}_{hash_suffix}.mp4"
    return sanitize_filename(raw_filename)


def _find_asset_in_history(
    db: Session, task_id: str, asset_hash: str
) -> dict | None:
    """
    从 TaskHistory.output_assets JSON 中按 asset_hash 查找 asset 记录。
    返回原始 dict（含 path / cover_path 等字段），未找到则返回 None。
    """
    record: Optional[TaskHistory] = (
        db.query(TaskHistory).filter(TaskHistory.task_id == task_id).first()
    )
    if record is None:
        return None
    for asset in record.output_assets or []:
        if asset.get("hash") == asset_hash:
            return asset
    return None


def _extract_social_meta(
    db: Session, task_id: str
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    从 TaskHistory.prompt_details["meta"] 中提取 Phase 9.12/9.13 社交媒体字段。

    Returns:
        (social_title, social_caption, social_hashtags, emotional_tag) — 任意字段不存在时为 None。
    """
    record: Optional[TaskHistory] = (
        db.query(TaskHistory).filter(TaskHistory.task_id == task_id).first()
    )
    if record is None or not record.prompt_details:
        return None, None, None, None
    try:
        details: dict = (
            json.loads(record.prompt_details)
            if isinstance(record.prompt_details, str)
            else record.prompt_details
        )
        meta: dict = details.get("meta", {}) or {}
        return (
            meta.get("social_title"),
            meta.get("social_caption"),
            meta.get("social_hashtags"),
            meta.get("emotional_tag"),
        )
    except (json.JSONDecodeError, AttributeError):
        return None, None, None, None


# ================================================================== #
# PUT /matrix/variants/{task_id}/{asset_hash}/status                  #
# ================================================================== #
@router.put(
    "/variants/{task_id}/{asset_hash}/status",
    summary="更新变体审批状态",
    description=(
        "更新单个视频变体的质检审批状态。\n\n"
        "**Upsert 语义**：若该 (task_id, asset_hash) 对尚无记录，则自动从 "
        "`task_history` 中查找对应 `file_path` 并新建记录；若已有记录则更新状态。\n\n"
        "status 取值：`PENDING` | `APPROVED` | `REJECTED`"
    ),
)
def update_variant_status(
    task_id:    str,
    asset_hash: str,
    payload:    VariantStatusPayload,
    db:         Session = Depends(get_db),
) -> dict:
    # 1. 查找是否已存在审批记录
    approval: Optional[VariantApproval] = (
        db.query(VariantApproval)
        .filter(
            VariantApproval.task_id    == task_id,
            VariantApproval.asset_hash == asset_hash,
        )
        .first()
    )

    if approval is None:
        # 2. 首次审批：从 TaskHistory 中回查 file_path
        asset_meta = _find_asset_in_history(db, task_id, asset_hash)
        if asset_meta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"未找到 task_id={task_id!r} / asset_hash={asset_hash!r} 对应的历史记录。"
                    " 请确认任务已完成并写入 task_history 表。"
                ),
            )
        # 从 TaskHistory.prompt_details 提取全局社交媒体 meta（Phase 9.12/9.13）
        social_title, social_caption, social_hashtags, emotional_tag = _extract_social_meta(db, task_id)

        approval = VariantApproval(
            task_id         = task_id,
            asset_hash      = asset_hash,
            file_path       = asset_meta.get("path", ""),
            cover_path      = asset_meta.get("cover_path", ""),
            status          = payload.status,
            social_title    = social_title,
            social_caption  = social_caption,
            social_hashtags = social_hashtags,
            emotional_tag   = emotional_tag,
            created_at      = _now(),
            updated_at      = _now(),
        )
        db.add(approval)
    else:
        # 3. 更新已有记录
        approval.status     = payload.status
        approval.updated_at = _now()

    db.commit()
    db.refresh(approval)

    return {
        "id":         approval.id,
        "task_id":    approval.task_id,
        "asset_hash": approval.asset_hash,
        "file_path":  approval.file_path,
        "status":     approval.status,
        "updated_at": approval.updated_at.isoformat() if approval.updated_at else None,
    }


# ================================================================== #
# GET /matrix/approvals                                               #
# ================================================================== #
@router.get(
    "/approvals",
    summary="查询审批状态",
    description=(
        "返回指定 task_id（不传则返回所有）的变体审批状态。\n\n"
        "响应格式：`{asset_hash: status}` 扁平字典，便于前端 O(1) 查找。"
    ),
)
def get_approvals(
    task_id: Optional[str] = Query(None, description="可选：按 task_id 过滤"),
    db: Session = Depends(get_db),
) -> dict:
    q = db.query(VariantApproval)
    if task_id:
        q = q.filter(VariantApproval.task_id == task_id)
    rows = q.all()
    return {row.asset_hash: row.status for row in rows}


# ================================================================== #
# GET /matrix/export                                                  #
# ================================================================== #
@router.get(
    "/export",
    summary="导出已通过变体 ZIP 交付包（Phase 9.13 扁平化归因版）",
    description=(
        "将所有 `status == APPROVED` 的变体视频打包为 ZIP，以流式响应返回。\n\n"
        "**ZIP 包内容结构：**\n"
        "```\n"
        "dopamatrix_delivery_<task8>.zip\n"
        "├── videos/\n"
        "│   ├── Tk01_ShockAbsorber_BossAngry_a1b2c3.mp4\n"
        "│   └── ...\n"
        "└── 矩阵投放文案对照表.csv   ← UTF-8-BOM，Excel 可直接打开\n"
        "```\n\n"
        "**CSV 列：** 视频文件名 | 社交平台标题 | 情绪化描述（含追踪链接） | 黄金标签 | 追踪短链接\n\n"
        "- 可选 `task_id` 参数：指定只导出某批次的成片；不传则导出全部已通过成片。\n"
        "- `account_id` / `core_tag`：控制扁平化视频命名前缀。\n"
        "- `{TRACKING_LINK}` 占位符由 CloudflareKVAdapter 动态替换为唯一短链。\n"
        "- 全内存 ZIP（`io.BytesIO`），零磁盘 IO；仅含 `videos/` 与根目录 CSV，无嵌套子目录。\n"
        "- 若无任何已通过成片，返回 404。"
    ),
)
def export_approved_zip(
    task_id:      Optional[str] = Query(None, description="可选：按 task_id 过滤"),
    account_id:   str           = Query(default="Tk01", description="目标账号 ID 或任务组简称，用于视频命名前缀。"),
    core_tag:     str           = Query(default="CoreTag", description="任务全局核心标签，用于视频命名。"),
    landing_base: str           = Query(
        default="https://your-domain.com/landing",
        description="落地页基础 URL，系统将拼接 ?vid={asset_hash} 形成长链接再生成短链。",
    ),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    q = db.query(VariantApproval).filter(VariantApproval.status == "APPROVED")
    if task_id:
        q = q.filter(VariantApproval.task_id == task_id)
    approvals = q.all()

    # 过滤掉物理文件已丢失的记录
    valid = [ap for ap in approvals if ap.file_path and os.path.isfile(ap.file_path)]

    if not valid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="当前没有状态为 APPROVED 且物理文件存在的变体，无法导出。",
        )

    # ── 内存缓冲区 ────────────────────────────────────────────────────
    zip_buf = io.BytesIO()
    csv_buf = io.StringIO()
    csv_writer = csv.writer(csv_buf)
    csv_writer.writerow(["视频文件名", "社交平台标题", "情绪化描述", "黄金标签", "追踪短链接"])

    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for ap in valid:
            hook_tag    = ap.emotional_tag or "Auto"
            hash_suffix = (ap.asset_hash or "")[:6]
            safe_filename = _build_safe_filename(
                sanitize_filename(account_id),
                sanitize_filename(core_tag),
                sanitize_filename(hook_tag),
                hash_suffix,
            )

            # 视频文件写入 videos/ 根目录（扁平化，无嵌套子目录）
            zf.write(ap.file_path, f"videos/{safe_filename}")

            # ── 短链生成与 {TRACKING_LINK} 替换（Phase 9.12 逻辑保留）──────────
            long_url   = f"{landing_base.rstrip('/')}?vid={ap.asset_hash}"
            short_link = _tracking_adapter.generate_short_link(long_url, ap.asset_hash or "")

            title      = ap.social_title    or "DopaMatrix 精品视频"
            raw_cap    = ap.social_caption  or "精心打磨的内容，点击了解更多 👇 {TRACKING_LINK}"
            hashtags   = ap.social_hashtags or "#DopaMatrix #短视频"

            final_caption = raw_cap.replace("{TRACKING_LINK}", short_link)

            # 第一列必须与物理文件名绝对一致
            csv_writer.writerow([safe_filename, title, final_caption, hashtags, short_link])

        # CSV 写入 ZIP 根目录；utf-8-sig BOM 保证 Excel 打开不乱码
        zf.writestr("矩阵投放文案对照表.csv", csv_buf.getvalue().encode("utf-8-sig"))

    zip_buf.seek(0)

    zip_name = f"dopamatrix_delivery_{task_id[:8]}.zip" if task_id else "dopamatrix_approved.zip"

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )
