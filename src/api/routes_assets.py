"""
src/api/routes_assets.py
———————————————————
提供与 DAM 本地素材库交互的 REST 接口。
"""

import os
import uuid
import json
import hashlib
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import RootModel
from sqlalchemy.orm import Session
from sqlalchemy import select, inspect as inspect_asset

from .database import get_db
from .models import LocalAsset
from . import schemas as asset_schemas
from .schemas import LocalAssetCreate, LocalAssetResponse, LocalAssetImportResponse, AssetRoleUpdate, AssetTagsUpdate, AssetAppendTags, TextAssetCreate

router = APIRouter(prefix="/assets", tags=["DAM Assets"])

@router.get("/stream", summary="流式传输本地绝对方位素材文件")
def stream_local_asset(path: str = Query(..., description="本地文件的绝对路径")):
    """
    通过 HTTP 提供本地磁盘文件的流式读取，解决前端不在 tauri context 下无法跨盘符读取图片的跨域/404问题。
    """
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="文件不存在或已被移除")
    return FileResponse(path)

def compute_md5(file_path: str) -> str:
    """计算文件的 MD5 值（适合大文件）"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

class _P1BImportResponseDocumentation(RootModel[
    LocalAssetImportResponse | asset_schemas.P1BInformationalImportResponse
]):
    """Documentation only: the default runtime response model stays legacy."""


def _p1b_informational_requested(request: Request) -> bool:
    values = request.query_params.getlist("result_format")
    if not values:
        return False
    if len(values) != 1 or values[0] != "p1b-info-v1":
        raise HTTPException(status_code=400, detail={
            "reason_code": "CONTRACT_INVALID",
            "operator_next_action": "REVIEW_CONTRACT",
        })
    return True


def _p1b_asset_id(asset) -> int:
    # InstanceState.identity reads mapper metadata, not expired ORM attributes.
    identity = inspect_asset(asset).identity
    if type(identity) is not tuple or len(identity) != 1:
        raise ValueError("P1B_ASSET_ID_UNAVAILABLE")
    asset_id = identity[0]
    if type(asset_id) is not int or asset_id <= 0:
        raise ValueError("P1B_ASSET_ID_UNAVAILABLE")
    return asset_id


def _p1b_import_response(observations, legacy):
    """Called only after the existing commit returns; never grants qualification."""
    try:
        results = []
        for index, outcome, asset, reason, action in observations:
            references = {}
            facts = {}
            if asset is not None:
                references["asset_id"] = {
                    "value": _p1b_asset_id(asset), "state": "PRESENT",
                    "provenance": "BACKEND_OBSERVED",
                }
            if outcome in ("CREATED", "REVIVED"):
                facts["persistence_confirmed"] = {
                    "value": True, "state": "PRESENT", "provenance": "BACKEND_OBSERVED",
                }
            results.append(asset_schemas.P1APerInputResult(
                input_index=index, file_display_name=f"input-{index}",
                import_outcome=outcome, reason_code=reason, operator_next_action=action,
                references=references, facts=facts,
            ))
        # Validate the complete internal batch BEFORE excluded facts disappear.
        batch = asset_schemas.P1AResultBatch(results=tuple(results))
        public_results = asset_schemas.serialize_p1a_results(batch)
        public = asset_schemas.P1BInformationalImportResponse.model_validate({
            "result_format": "p1b-info-v1",
            "success_count": legacy.success_count, "skipped_count": legacy.skipped_count,
            "message": legacy.message, "results": public_results,
        })
        return JSONResponse(content=public.model_dump(mode="json"))
    except Exception:
        # This can fail AFTER persistence. Never claim rollback or suggest retry.
        # The existing application error fence supplies the safe non-2xx response.
        raise ValueError("P1B_RESPONSE_UNAVAILABLE") from None


@router.post(
    "/import", response_model=LocalAssetImportResponse, summary="导入本地素材",
    responses={
        200: {
            "model": _P1BImportResponseDocumentation,
            "description": "Legacy by default; informational only with one result_format=p1b-info-v1.",
        },
        400: {
            "description": "Empty, invalid, or repeated result_format: CONTRACT_INVALID before Import business work.",
            "content": {"application/json": {"schema": {
                "type": "object", "required": ["detail"], "additionalProperties": False,
                "properties": {"detail": {
                    "type": "object", "required": ["reason_code", "operator_next_action"],
                    "additionalProperties": False,
                    "properties": {
                        "reason_code": {"type": "string", "const": "CONTRACT_INVALID"},
                        "operator_next_action": {"type": "string", "const": "REVIEW_CONTRACT"},
                    },
                }},
            }}},
        },
    },
    openapi_extra={"parameters": [{
        "name": "result_format", "in": "query", "required": False,
        "schema": {"type": "string", "enum": ["p1b-info-v1"]},
        "description": "Omit for Legacy. Exactly one valid value opts in; any repetition or invalid value is HTTP 400. Informational only, never Seed/authorization authority. Existing dependencies may initialize first.",
    }]},
)
def import_asset(asset_in: LocalAssetCreate, request: Request, db: Session = Depends(get_db)):
    """
    接收本地素材的绝对路径列表，计算 MD5 后存入本地库中。
    防重复检测：如果 MD5 已存在则跳过。
    返回成功导入和跳过的数量。
    """
    informational = _p1b_informational_requested(request)
    observations = [] if informational else None
    success_count = 0
    skipped_count = 0

    for input_index, file_path in enumerate(asset_in.file_paths):
        if not os.path.exists(file_path):
            skipped_count += 1
            if observations is not None:
                observations.append((input_index, "NOT_COMPLETED", None,
                                     "FILE_MISSING_OR_UNREADABLE", "SUPPLY_HEALTHY_SOURCE"))
            continue
        
        try:
            file_hash = compute_md5(file_path)
        except Exception:
            skipped_count += 1
            if observations is not None:
                observations.append((input_index, "NOT_COMPLETED", None,
                                     "NOT_EVALUATED", "WAIT_FOR_AUTHORIZED_RESOLUTION"))
            continue

        # 防重复检测：活跃素材跳过；已逻辑删除的同 hash 则复活并更新元数据
        existing = db.execute(select(LocalAsset).where(LocalAsset.file_hash == file_hash)).scalar_one_or_none()
        if existing:
            if existing.is_deleted:
                existing.is_deleted = False
                existing.file_path = file_path
                existing.asset_type = asset_in.asset_type
                existing.video_role = asset_in.video_role
                existing.tags = asset_in.tags
                existing.entity_id = asset_in.entity_id
                existing.asset_name = asset_in.asset_name
                success_count += 1
                if observations is not None:
                    observations.append((input_index, "REVIVED", existing,
                                         "REQUALIFICATION_REQUIRED", "REQUALIFY_AND_RESELECT"))
            else:
                skipped_count += 1
                if observations is not None:
                    observations.append((input_index, "DUPLICATE_EXISTING", existing,
                                         "DUPLICATE_EXISTING", "REVIEW_EXISTING"))
            continue

        new_asset = LocalAsset(
            file_hash=file_hash,
            file_path=file_path,
            asset_type=asset_in.asset_type,
            video_role=asset_in.video_role,
            tags=asset_in.tags,
            entity_id=asset_in.entity_id,
            asset_name=asset_in.asset_name,
        )
        db.add(new_asset)
        success_count += 1
        if observations is not None:
            observations.append((input_index, "CREATED", new_asset,
                                 "NOT_EVALUATED", "WAIT_FOR_AUTHORIZED_RESOLUTION"))

    db.commit()
    
    legacy = LocalAssetImportResponse(
        success_count=success_count,
        skipped_count=skipped_count,
        message=f"成功导入 {success_count} 个素材，跳过 {skipped_count} 个已存在或无效的文件"
    )
    if observations is not None:
        return _p1b_import_response(observations, legacy)
    return legacy


@router.post("/text", response_model=LocalAssetResponse, summary="虚拟创建文本模板资产")
def create_text_asset(payload: TextAssetCreate, db: Session = Depends(get_db)):
    """
    无需物理文件，直接在 DAM 中创建 text_template 类型的虚拟资产。
    多语种内容矩阵存入 manifest.content_matrix 字段，以 JSON MD5 作为防重指纹。
    """
    content_json = json.dumps(payload.content_matrix, ensure_ascii=False, sort_keys=True)
    file_hash    = hashlib.md5(content_json.encode("utf-8")).hexdigest()

    existing = db.execute(
        select(LocalAsset).where(LocalAsset.file_hash == file_hash)
    ).scalar_one_or_none()
    if existing and not existing.is_deleted:
        raise HTTPException(status_code=409, detail="相同内容的文本资产已存在，请勿重复创建")
    if existing and existing.is_deleted:
        existing.is_deleted   = False
        existing.asset_name   = payload.asset_name
        existing.manifest     = {"content_matrix": payload.content_matrix}
        db.commit()
        db.refresh(existing)
        return existing

    new_asset = LocalAsset(
        file_hash  = file_hash,
        file_path  = f"virtual://text_{uuid.uuid4().hex[:8]}",
        asset_type = "text_template",
        video_role = "general",
        asset_name = payload.asset_name,
        manifest   = {"content_matrix": payload.content_matrix},
    )
    db.add(new_asset)
    db.commit()
    db.refresh(new_asset)
    return new_asset


@router.get("", response_model=List[LocalAssetResponse], summary="查询素材库")
def get_assets(
    asset_type: Optional[str] = Query(None, description="过滤: 'video', 'logo', 'sticker'"),
    video_role: Optional[str] = Query(None, description="过滤: 'hook', 'body', 'general'"),
    is_deleted: Optional[bool] = Query(
        None,
        description="true=仅回收站；省略或 false=仅未删除（正常 DAM 列表）",
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    按条件分页检索素材列表。
    """
    query = select(LocalAsset)

    if is_deleted is True:
        query = query.where(LocalAsset.is_deleted.is_(True))
    else:
        query = query.where(LocalAsset.is_deleted.is_(False))

    if asset_type:
        query = query.where(LocalAsset.asset_type == asset_type)
    if video_role:
        query = query.where(LocalAsset.video_role == video_role)

    query = query.order_by(LocalAsset.created_at.desc())
    assets = db.execute(query.offset(skip).limit(limit)).scalars().all()
    return list(assets)


@router.post("/{asset_id}/increment-usage", response_model=LocalAssetResponse, summary="增加素材引用次数")
def increment_usage(asset_id: int, db: Session = Depends(get_db)):
    """
    内部或前端调用，标识素材被引用 1 次。根据阈值(如 10 次)判定是否设定疲劳警告 (is_exhausted = True)
    """
    asset = db.get(LocalAsset, asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应素材")

    asset.usage_count += 1
    
    # 模拟简单的防疲劳规则: 引用超过 10 次标为警示状态
    if asset.usage_count >= 10:
        asset.is_exhausted = True
        
    asset.last_used_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/{asset_id}/role", response_model=LocalAssetResponse, summary="修改素材的角色(Hook/Body)")
def update_asset_role(asset_id: int, payload: AssetRoleUpdate, db: Session = Depends(get_db)):
    """
    修改单个素材的角色，例如将普通视频标记为 'hook' 或 'body'。
    """
    asset = db.get(LocalAsset, asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应素材")

    valid_roles = {"hook", "body", "general"}
    if payload.video_role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"无效的角色，必须为 {valid_roles} 之一")

    asset.video_role = payload.video_role
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/{asset_id}/tags", response_model=LocalAssetResponse, summary="修改素材的语义标签")
def update_asset_tags(asset_id: int, payload: AssetTagsUpdate, db: Session = Depends(get_db)):
    """
    全量覆盖单个素材的语义标签数组，为 Smart 抽卡机制提供底层数据弹药。
    """
    asset = db.get(LocalAsset, asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应素材")

    asset.tags = payload.tags
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/{asset_id}/append-tags", response_model=LocalAssetResponse, summary="追加合并语义标签（Drop-to-Tag 基因注入）")
def append_asset_tags(asset_id: int, payload: AssetAppendTags, db: Session = Depends(get_db)):
    """
    将传入的标签列表与素材现有标签合并（Set 去重），不覆盖已有标签。
    用于 Drop-to-Tag 拖拽继承场景：素材被拖入带标签的轨道时，自动继承轨道基因。
    """
    asset = db.get(LocalAsset, asset_id)
    if not asset or asset.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应素材")

    existing = list(asset.tags or [])
    merged   = list(dict.fromkeys(existing + payload.tags))  # 保序去重
    asset.tags = merged
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/{asset_id}/trash", response_model=LocalAssetResponse, summary="逻辑删除（移入回收站）")
def trash_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(LocalAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="未找到对应素材")
    if asset.is_deleted:
        raise HTTPException(status_code=400, detail="素材已在回收站中")
    asset.is_deleted = True
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/{asset_id}/restore", response_model=LocalAssetResponse, summary="从回收站恢复")
def restore_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(LocalAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="未找到对应素材")
    if not asset.is_deleted:
        raise HTTPException(status_code=400, detail="素材不在回收站中")
    asset.is_deleted = False
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{asset_id}/purge", status_code=204, summary="永久删除数据库记录")
def purge_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(LocalAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="未找到对应素材")
    if not asset.is_deleted:
        raise HTTPException(status_code=400, detail="请先将素材移入回收站后再彻底销毁")
    db.delete(asset)
    db.commit()
    return None
