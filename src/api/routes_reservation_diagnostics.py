"""Read-only tenant-scoped Reservation operational summaries."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .database import get_db
from .reservation_diagnostics import (
    RESERVATION_DIAGNOSTICS_UNAVAILABLE,
    reservation_diagnostics_summary,
)


logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/diagnostics/reservation",
    tags=["Reservation Diagnostics"],
)


class ReservationDiagnosticsSummaryResponse(BaseModel):
    window: Literal["1h", "24h", "7d", "30d"]
    from_time: datetime = Field(alias="from")
    to_time: datetime = Field(alias="to")
    enforceTaskCount: int
    planningObservedTaskCount: int
    activeTaskCount: int
    completedTaskCount: int
    failedTaskCount: int
    conflictTaskCount: int
    conflictTaskRate: float | None
    reservationConflictCount: int
    zeroPlanConflictCount: int
    zeroPlanConflictRate: float | None
    partialPlanCount: int
    partialPlanRate: float | None
    authorityLossCount: int
    authorityLossRate: float | None
    terminalPersistFailureCount: int
    terminalPersistFailureRate: float | None
    workerLeaseConfigFailureCount: int
    cleanupWarningCount: int


@router.get("/summary", response_model=ReservationDiagnosticsSummaryResponse)
def get_reservation_diagnostics_summary(
    window: Literal["1h", "24h", "7d", "30d"] = Query(default="24h"),
    db: Session = Depends(get_db),
) -> ReservationDiagnosticsSummaryResponse:
    """Summarize admitted ENFORCE runs by tenant-local start-time cohort."""
    try:
        return ReservationDiagnosticsSummaryResponse.model_validate(
            reservation_diagnostics_summary(db, window=window)
        )
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(
            "[RESERVATION_DIAGNOSTICS_QUERY_FAILED] category=%s",
            type(exc).__name__[:64],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=RESERVATION_DIAGNOSTICS_UNAVAILABLE,
        ) from exc
