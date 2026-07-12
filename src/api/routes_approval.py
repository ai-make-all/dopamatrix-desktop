from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from .approval_service import batch_update_variant_status, ensure_pending_variant_records
from .approval_types import VariantStatus
from .database import get_db
from .models import VariantApproval
from .schemas import BatchUpdateStatusRequest, BatchUpdateStatusResponse


router = APIRouter(prefix="/approval", tags=["Approval"])


@router.get("/list", summary="查询质检舱审核列表")
def get_approval_list(
    status_filter: str = Query("ALL", alias="status"),
    db: Session = Depends(get_db),
) -> list[dict]:
    ensure_pending_variant_records(db)

    requested_status = status_filter.strip().upper()
    if requested_status not in {"ALL", "PENDING", "APPROVED", "REJECTED"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported approval status: {status_filter}",
        )

    query = db.query(VariantApproval).filter(
        VariantApproval.status.notin_(
            [VariantStatus.DELETED, VariantStatus.PROCESSING]
        )
    )
    if requested_status == "ALL":
        query = query.filter(
            VariantApproval.status.in_(
                [VariantStatus.PENDING, VariantStatus.APPROVED]
            )
        )
    else:
        query = query.filter(
            VariantApproval.status == VariantStatus(requested_status)
        )

    rows = query.order_by(VariantApproval.updated_at.desc()).all()
    return [
        {
            "task_id": row.task_id,
            "asset_hash": row.asset_hash,
            "status": (
                row.status.value
                if isinstance(row.status, VariantStatus)
                else str(row.status)
            ),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "tracking_link": row.tracking_link or "",
            "exported_at": row.exported_at.isoformat() if row.exported_at else None,
        }
        for row in rows
    ]


@router.post(
    "/batch-update",
    response_model=BatchUpdateStatusResponse,
    summary="统一更新单个或多个视频变体的审核状态",
)
def update_variant_status_batch(
    payload: BatchUpdateStatusRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    operator = request.headers.get("X-Local-User", "default") or "default"
    return batch_update_variant_status(
        db=db,
        hashes=payload.hashes,
        target_status=payload.target_status,
        operator=operator,
    )
