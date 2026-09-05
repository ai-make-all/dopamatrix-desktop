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
from .reservation_rollout_readiness import (
    RESERVATION_ROLLOUT_READINESS_CONFIGURATION_INVALID,
    RESERVATION_ROLLOUT_READINESS_UNAVAILABLE,
    ReservationRolloutReadinessConfigurationError,
    load_reservation_rollout_readiness_configuration,
    reservation_rollout_readiness,
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


class ReservationRolloutReadinessGateResponse(BaseModel):
    code: str
    category: Literal["EVIDENCE", "QUALITY", "SAFETY"]
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    observed: int | float | bool | None
    threshold: int | float | bool


class ReservationRolloutReadinessResponse(BaseModel):
    planningPolicy: Literal[
        "exact_main_visual",
        "exact_main_visual_balanced",
    ]
    state: Literal[
        "NOT_CONFIGURED",
        "INSUFFICIENT_EVIDENCE",
        "BLOCKED",
        "READY_FOR_CONTROLLED_CANARY",
    ]
    recommendation: Literal[
        "KEEP_EXPLICIT_ONLY",
        "ELIGIBLE_FOR_CONTROLLED_DEFAULT_ON_CANARY",
    ]
    evaluationWindow: Literal["24h", "7d", "30d"] | None
    from_time: datetime | None = Field(alias="from")
    to_time: datetime | None = Field(alias="to")
    leaseConfigurationReady: bool | None
    authoritativeEnforceTaskCount: int | None
    diagnosticRunCount: int | None
    diagnosticRunCoverageRate: float | None
    planningObservedTaskCount: int | None
    planningObservationCoverageRate: float | None
    authoritativeTerminalTaskCount: int | None
    terminalDiagnosticTaskCount: int | None
    terminalObservationCoverageRate: float | None
    conflictTaskCount: int | None
    conflictTaskRate: float | None
    reservationConflictCount: int | None
    zeroPlanConflictCount: int | None
    zeroPlanConflictRate: float | None
    partialPlanCount: int | None
    partialPlanRate: float | None
    authorityLossCount: int | None
    authorityLossRate: float | None
    terminalPersistFailureCount: int | None
    terminalPersistFailureRate: float | None
    workerLeaseConfigFailureCount: int | None
    workerLeaseConfigFailureRate: float | None
    cleanupWarningCount: int | None
    cleanupWarningRate: float | None
    activeTaskCount: int | None
    gates: list[ReservationRolloutReadinessGateResponse]


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


@router.get("/readiness", response_model=ReservationRolloutReadinessResponse)
def get_reservation_rollout_readiness(
    planning_policy: Literal[
        "exact_main_visual",
        "exact_main_visual_balanced",
    ] = Query(...),
    db: Session = Depends(get_db),
) -> ReservationRolloutReadinessResponse:
    """Return advisory tenant/policy evidence without changing runtime mode."""
    try:
        configuration = load_reservation_rollout_readiness_configuration()
        return ReservationRolloutReadinessResponse.model_validate(
            reservation_rollout_readiness(
                db,
                planning_policy=planning_policy,
                configuration=configuration,
            )
        )
    except ReservationRolloutReadinessConfigurationError as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(
            "[RESERVATION_ROLLOUT_READINESS_CONFIG_FAILED] category=%s",
            type(exc).__name__[:64],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=RESERVATION_ROLLOUT_READINESS_CONFIGURATION_INVALID,
        ) from exc
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(
            "[RESERVATION_ROLLOUT_READINESS_QUERY_FAILED] category=%s",
            type(exc).__name__[:64],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=RESERVATION_ROLLOUT_READINESS_UNAVAILABLE,
        ) from exc
