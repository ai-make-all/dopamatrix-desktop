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
  POST /matrix/export
       → 将请求体 hashes 指定的 APPROVED 视频打包为 ZIP 流式返回；
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
import time
import zipfile
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from .database import get_db, get_tenant_engine
from .models import TaskHistory, VariantApproval
from .approval_service import batch_update_variant_status, ensure_pending_variant_records
from .approval_types import VariantStatus
from src.services.tracking_adapter import CloudflareKVAdapter

# 模块级单例，复用 httpx 连接池（Mock 模式下无网络开销）
_tracking_adapter = CloudflareKVAdapter()

router = APIRouter(prefix="/matrix", tags=["Matrix Approval"])

EXPORT_DIR = os.path.join(os.getcwd(), "output", "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)


# ── Pydantic 请求体 ────────────────────────────────────────────────────
class VariantStatusPayload(BaseModel):
    status: Literal["PENDING", "APPROVED", "REJECTED"]


class ExportRequest(BaseModel):
    hashes: List[str]


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
    返回原始 dict（含 file_path / cover_path 等字段），未找到则返回 None。
    """
    record: Optional[TaskHistory] = (
        db.query(TaskHistory).filter(TaskHistory.task_id == task_id).first()
    )
    if record is None:
        return None
    for asset in record.output_assets or []:
        if (asset.get("hash") or asset.get("file_hash")) == asset_hash:
            return asset
    return None


def _extract_social_meta(
    db: Session, task_id: str
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    从 TaskHistory.prompt_details["meta"] 中提取 Phase 9.12/9.13 社交媒体字段。

    Returns:
        (social_title, social_caption, social_hashtags, human_drive, emotional_tag) — 任意字段不存在时为 None。
    """
    record: Optional[TaskHistory] = (
        db.query(TaskHistory).filter(TaskHistory.task_id == task_id).first()
    )
    if record is None or not record.prompt_details:
        return None, None, None, None, None
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
            meta.get("human_drive"),
            meta.get("emotional_tag"),
        )
    except (json.JSONDecodeError, AttributeError):
        return None, None, None, None, None


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
    request:    Request,
    db:         Session = Depends(get_db),
) -> dict:
    operator = request.headers.get("X-Local-User", "default") or "default"
    result = batch_update_variant_status(
        db=db,
        hashes=[asset_hash],
        target_status=VariantStatus(payload.status),
        operator=operator,
    )
    return {
        **result,
        "task_id": task_id,
        "asset_hash": asset_hash,
        "status": payload.status,
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
    ensure_pending_variant_records(db)
    q = db.query(VariantApproval)
    if task_id:
        q = q.filter(VariantApproval.task_id == task_id)
    rows = q.all()
    return {
        row.asset_hash: (
            row.status.value if isinstance(row.status, VariantStatus) else row.status
        )
        for row in rows
    }


def _normalize_export_hashes(hashes: list[str]) -> list[str]:
    return list(dict.fromkeys(asset_hash.strip() for asset_hash in hashes if asset_hash.strip()))


def _safe_export_filename(filename: str) -> str:
    safe_name = os.path.basename(filename or "")
    if not safe_name.startswith("dopamatrix_delivery_") or not safe_name.endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid export filename")
    return safe_name


def _fallback_short_link(asset_hash: str) -> str:
    base_url = getattr(_tracking_adapter, "base_url", "https://dopa.mx/t/")
    return f"{base_url}mock-{(asset_hash or 'export')[:8]}"


def _generate_resilient_short_link(long_url: str, asset_hash: str) -> str:
    try:
        return _tracking_adapter.generate_short_link(long_url, asset_hash or "")
    except Exception as exc:
        print(f"⚠️ [Delivery Hub] CF 短链写入失败，已降级为本地 mock 链接: {exc}")
        return _fallback_short_link(asset_hash)


def _build_delivery_zip(
    db: Session,
    requested_hashes: list[str],
    zip_path: str,
    account_id: str,
    core_tag: str,
    landing_base: str,
) -> int:
    if not requested_hashes:
        raise ValueError("No hashes provided")

    # SQLite has no row-level SELECT FOR UPDATE. An immediate transaction
    # serializes the read/generate/write sequence so concurrent exports cannot
    # mint two links for the same asset.
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))

    approvals_by_hash = {
        approval.asset_hash: approval
        for approval in (
            db.query(VariantApproval)
            .filter(
                VariantApproval.status == VariantStatus.APPROVED,
                VariantApproval.asset_hash.in_(requested_hashes),
            )
            .all()
        )
    }
    approvals = [
        approvals_by_hash[asset_hash]
        for asset_hash in requested_hashes
        if asset_hash in approvals_by_hash
    ]

    # 过滤掉物理文件已丢失的记录
    valid = [ap for ap in approvals if ap.file_path and os.path.isfile(ap.file_path)]

    if not valid:
        raise ValueError("当前没有状态为 APPROVED 且物理文件存在的变体，无法导出。")

    csv_buf = io.StringIO()
    csv_writer = csv.writer(csv_buf)
    csv_writer.writerow(["视频文件名", "社交平台标题", "情绪化描述", "黄金标签", "追踪短链接"])

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
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

            # ── 幂等短链生成与 {TRACKING_LINK} 替换 ───────────────────────────
            short_link = ap.tracking_link
            if not short_link:
                long_url = f"{landing_base.rstrip('/')}?vid={ap.asset_hash}"
                short_link = _generate_resilient_short_link(long_url, ap.asset_hash or "")
                ap.tracking_link = short_link
                ap.exported_at = _now()

            title      = ap.social_title    or "DopaMatrix 精品视频"
            raw_cap    = ap.social_caption  or "精心打磨的内容，点击了解更多 👇 {TRACKING_LINK}"
            hashtags   = ap.social_hashtags or "#DopaMatrix #短视频"

            final_caption = raw_cap.replace("{TRACKING_LINK}", short_link)

            # 第一列必须与物理文件名绝对一致
            csv_writer.writerow([safe_filename, title, final_caption, hashtags, short_link])

        # CSV 写入 ZIP 根目录；utf-8-sig BOM 保证 Excel 打开不乱码
        zf.writestr("矩阵投放文案对照表.csv", csv_buf.getvalue().encode("utf-8-sig"))

    db.commit()
    return len(valid)


def background_build_zip(
    requested_hashes: list[str],
    tenant_id: str,
    filename: str,
    account_id: str = "Tk01",
    core_tag: str = "CoreTag",
    landing_base: str = "https://your-domain.com/landing",
) -> None:
    """后台独立线程：执行耗时 ZIP 压缩、CF 容灾短链回填与落盘。"""
    safe_filename = _safe_export_filename(filename)
    zip_path = os.path.join(EXPORT_DIR, safe_filename)
    tmp_path = f"{zip_path}.partial"
    failed_path = f"{zip_path}.failed"

    engine = get_tenant_engine(tenant_id or "default")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        for path in (tmp_path, failed_path):
            if os.path.exists(path):
                os.remove(path)
        exported_count = _build_delivery_zip(
            db=db,
            requested_hashes=requested_hashes,
            zip_path=tmp_path,
            account_id=account_id,
            core_tag=core_tag,
            landing_base=landing_base,
        )
        os.replace(tmp_path, zip_path)
        print(f"✅ [Delivery Hub] 交付包后台落盘成功: {zip_path} ({exported_count} assets)")
    except Exception as exc:
        db.rollback()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        with open(failed_path, "w", encoding="utf-8") as fh:
            fh.write(str(exc))
        print(f"❌ [Delivery Hub] 交付包后台落盘失败: {safe_filename} - {exc}")
    finally:
        db.close()


# ================================================================== #
# POST /matrix/export                                                 #
# ================================================================== #
@router.post(
    "/export",
    summary="异步导出已通过变体 ZIP 交付包（Phase 9.21.1 Delivery Hub）",
    description="极速接单端点：提交 hashes 后立即返回 filename，后台异步生成 ZIP，前端通过 /export/status 轮询提货。",
)
async def request_export(
    payload: ExportRequest,
    bg_tasks: BackgroundTasks,
    request: Request,
    account_id: str = Query(default="Tk01", description="目标账号 ID 或任务组简称，用于视频命名前缀。"),
    core_tag: str = Query(default="CoreTag", description="任务全局核心标签，用于视频命名。"),
    landing_base: str = Query(
        default="https://your-domain.com/landing",
        description="落地页基础 URL，系统将拼接 ?vid={asset_hash} 形成长链接再生成短链。",
    ),
) -> dict:
    requested_hashes = _normalize_export_hashes(payload.hashes)
    if not requested_hashes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无有效变体 hashes")

    filename = f"dopamatrix_delivery_{int(time.time())}.zip"
    tenant_id = request.headers.get("X-Local-User", "default") or "default"
    bg_tasks.add_task(
        background_build_zip,
        requested_hashes,
        tenant_id,
        filename,
        account_id,
        core_tag,
        landing_base,
    )
    return {"status": "processing", "filename": filename}


@router.get("/export/status", summary="查询异步交付包状态")
async def check_export_status(filename: str) -> dict:
    safe_filename = _safe_export_filename(filename)
    zip_path = os.path.join(EXPORT_DIR, safe_filename)
    failed_path = f"{zip_path}.failed"

    if os.path.exists(zip_path):
        return {
            "status": "ready",
            "download_url": f"/exports/{safe_filename}",
            "local_path": os.path.abspath(zip_path),
        }
    if os.path.exists(failed_path):
        return {"status": "failed"}
    return {"status": "processing"}
