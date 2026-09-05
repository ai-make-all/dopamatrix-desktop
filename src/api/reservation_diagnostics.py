"""Tenant-local best-effort observability for public Reservation ENFORCE.

Diagnostic persistence is deliberately separate from Reservation and creative
truth transactions.  Nothing in this module grants or verifies authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Literal

from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from .models import ReservationRunDiagnostic


logger = logging.getLogger(__name__)

ReservationDiagnosticsWindow = Literal["1h", "24h", "7d", "30d"]
RESERVATION_DIAGNOSTICS_UNAVAILABLE = "RESERVATION_DIAGNOSTICS_UNAVAILABLE"

_WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
_SAFE_ERROR_CODES = {
    None,
    "RESERVATION_CONFLICT_EXHAUSTED",
    "RESERVATION_AUTHORITY_LOST",
    "RESERVATION_TERMINAL_PERSIST_FAILED",
    "RESERVATION_LEASE_CONFIGURATION_REQUIRED",
}
_EVENT_FIELDS = {
    "task_id",
    "planning_policy",
    "requested_count",
    "planned_count",
    "succeeded_count",
    "failed_count",
    "reservation_conflict_count",
    "had_reservation_conflict",
    "zero_plan_conflict",
    "partial_plan",
    "authority_lost",
    "terminal_persist_failed",
    "worker_lease_config_failed",
    "cleanup_warning",
    "terminal_status",
    "error_code",
    "stage",
}


@dataclass(frozen=True)
class ReservationPlanningObservation:
    planning_policy: str
    requested_count: int
    planned_count: int
    reservation_conflict_count: int
    termination_reason: str

    def __post_init__(self) -> None:
        if self.planning_policy not in {
            "exact_main_visual",
            "exact_main_visual_balanced",
        }:
            raise ValueError("RESERVATION_DIAGNOSTIC_PLANNING_POLICY_INVALID")
        counts = (
            self.requested_count,
            self.planned_count,
            self.reservation_conflict_count,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in counts):
            raise ValueError("RESERVATION_DIAGNOSTIC_COUNT_INVALID")
        if self.requested_count < 1 or self.planned_count < 0:
            raise ValueError("RESERVATION_DIAGNOSTIC_COUNT_INVALID")
        if self.planned_count > self.requested_count or self.reservation_conflict_count < 0:
            raise ValueError("RESERVATION_DIAGNOSTIC_COUNT_INVALID")

    @property
    def zero_plan_conflict(self) -> bool:
        return (
            self.planned_count == 0
            and self.termination_reason == "RESERVATION_CONFLICT_EXHAUSTED"
        )

    @property
    def partial_plan(self) -> bool:
        return 0 < self.planned_count < self.requested_count


@dataclass(frozen=True)
class ReservationTerminalObservation:
    planning_policy: str
    requested_count: int
    succeeded_count: int
    failed_count: int
    terminal_status: str
    error_code: str | None
    authority_lost: bool = False
    terminal_persist_failed: bool = False
    worker_lease_config_failed: bool = False
    cleanup_warning: bool = False

    def __post_init__(self) -> None:
        if self.planning_policy not in {
            "exact_main_visual",
            "exact_main_visual_balanced",
        }:
            raise ValueError("RESERVATION_DIAGNOSTIC_PLANNING_POLICY_INVALID")
        counts = (self.requested_count, self.succeeded_count, self.failed_count)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in counts):
            raise ValueError("RESERVATION_DIAGNOSTIC_COUNT_INVALID")
        if self.requested_count < 1 or self.succeeded_count < 0 or self.failed_count < 0:
            raise ValueError("RESERVATION_DIAGNOSTIC_COUNT_INVALID")
        if self.terminal_status not in {"completed", "failed"}:
            raise ValueError("RESERVATION_DIAGNOSTIC_TERMINAL_STATUS_INVALID")
        if self.error_code not in _SAFE_ERROR_CODES:
            raise ValueError("RESERVATION_DIAGNOSTIC_ERROR_CODE_INVALID")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def emit_reservation_diagnostic_event(event: str, **fields: Any) -> None:
    """Emit one bounded JSON event; logging failure is never authoritative."""
    try:
        payload = {"event": event}
        payload.update(
            {
                key: value
                for key, value in fields.items()
                if key in _EVENT_FIELDS and value is not None
            }
        )
        logger.info(
            "[PublicReservationDiagnostic] %s",
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
    except Exception:
        pass


def _write_upsert(
    bind: Engine,
    *,
    task_id: str,
    planning_policy: str,
    requested_count: int,
    insert_values: dict[str, Any],
    update_values: dict[str, Any],
) -> None:
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=bind,
    )
    with SessionLocal() as session:
        statement = sqlite_insert(ReservationRunDiagnostic).values(
            task_id=task_id,
            planning_policy=planning_policy,
            requested_count=requested_count,
            **insert_values,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[ReservationRunDiagnostic.task_id],
            set_={
                "planning_policy": planning_policy,
                "requested_count": requested_count,
                **update_values,
            },
        )
        try:
            session.execute(statement)
            session.commit()
        except Exception:
            session.rollback()
            raise


def _best_effort_write(stage: str, operation: Any) -> bool:
    try:
        operation()
        return True
    except Exception:
        emit_reservation_diagnostic_event(
            "PUBLIC_ENFORCE_DIAGNOSTIC_WRITE_FAILED",
            stage=stage,
        )
        return False


def best_effort_start_reservation_diagnostic(
    bind: Engine,
    *,
    task_id: str,
    planning_policy: str,
    requested_count: int,
) -> bool:
    now = _utcnow()
    succeeded = _best_effort_write(
        "start",
        lambda: _write_upsert(
            bind,
            task_id=task_id,
            planning_policy=planning_policy,
            requested_count=requested_count,
            insert_values={"started_at": now},
            update_values={},
        ),
    )
    emit_reservation_diagnostic_event(
        "PUBLIC_ENFORCE_WORKER_STARTED",
        task_id=task_id,
        planning_policy=planning_policy,
        requested_count=requested_count,
    )
    return succeeded


def best_effort_record_reservation_planning(
    bind: Engine,
    *,
    task_id: str,
    observation: ReservationPlanningObservation,
) -> bool:
    conflict_count = observation.reservation_conflict_count
    values = {
        "planning_observed": True,
        "planned_count": observation.planned_count,
        "reservation_conflict_count": conflict_count,
        "had_reservation_conflict": conflict_count > 0,
        "zero_plan_conflict": observation.zero_plan_conflict,
        "partial_plan": observation.partial_plan,
    }
    succeeded = _best_effort_write(
        "planning",
        lambda: _write_upsert(
            bind,
            task_id=task_id,
            planning_policy=observation.planning_policy,
            requested_count=observation.requested_count,
            insert_values={"started_at": _utcnow(), **values},
            update_values=values,
        ),
    )
    event = (
        "PUBLIC_ENFORCE_ZERO_PLAN_CONFLICT"
        if observation.zero_plan_conflict
        else "PUBLIC_ENFORCE_PLANNING_OBSERVED"
    )
    emit_reservation_diagnostic_event(
        event,
        task_id=task_id,
        planning_policy=observation.planning_policy,
        requested_count=observation.requested_count,
        planned_count=observation.planned_count,
        reservation_conflict_count=conflict_count,
        had_reservation_conflict=conflict_count > 0,
        zero_plan_conflict=observation.zero_plan_conflict,
        partial_plan=observation.partial_plan,
    )
    return succeeded


def best_effort_record_reservation_terminal(
    bind: Engine,
    *,
    task_id: str,
    observation: ReservationTerminalObservation,
) -> bool:
    values = {
        "succeeded_count": observation.succeeded_count,
        "failed_count": observation.failed_count,
        "authority_lost": observation.authority_lost,
        "terminal_persist_failed": observation.terminal_persist_failed,
        "worker_lease_config_failed": observation.worker_lease_config_failed,
        "cleanup_warning": observation.cleanup_warning,
        "terminal_status": observation.terminal_status,
        "error_code": observation.error_code,
        "finished_at": _utcnow(),
    }
    succeeded = _best_effort_write(
        "terminal",
        lambda: _write_upsert(
            bind,
            task_id=task_id,
            planning_policy=observation.planning_policy,
            requested_count=observation.requested_count,
            insert_values={"started_at": _utcnow(), **values},
            update_values=values,
        ),
    )
    if observation.worker_lease_config_failed:
        event = "PUBLIC_ENFORCE_WORKER_CONFIG_FAILED"
    elif observation.authority_lost:
        event = "PUBLIC_ENFORCE_AUTHORITY_LOST"
    elif observation.terminal_persist_failed:
        event = "PUBLIC_ENFORCE_TERMINAL_PERSIST_FAILED"
    elif observation.cleanup_warning:
        event = "PUBLIC_ENFORCE_CLEANUP_WARNING"
    else:
        event = "PUBLIC_ENFORCE_TERMINAL"
    emit_reservation_diagnostic_event(
        event,
        task_id=task_id,
        planning_policy=observation.planning_policy,
        requested_count=observation.requested_count,
        succeeded_count=observation.succeeded_count,
        failed_count=observation.failed_count,
        authority_lost=observation.authority_lost,
        terminal_persist_failed=observation.terminal_persist_failed,
        worker_lease_config_failed=observation.worker_lease_config_failed,
        cleanup_warning=observation.cleanup_warning,
        terminal_status=observation.terminal_status,
        error_code=observation.error_code,
    )
    return succeeded


def reservation_diagnostics_summary(
    session: Session,
    *,
    window: ReservationDiagnosticsWindow = "24h",
    now: datetime | None = None,
) -> dict[str, Any]:
    if window not in _WINDOWS:
        raise ValueError("RESERVATION_DIAGNOSTICS_WINDOW_INVALID")
    end = now or _utcnow()
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = end - _WINDOWS[window]
    rows = session.scalars(
        select(ReservationRunDiagnostic).where(
            ReservationRunDiagnostic.started_at >= start,
            ReservationRunDiagnostic.started_at <= end,
        )
    ).all()

    enforce_count = len(rows)
    planning_count = sum(row.planning_observed for row in rows)
    completed_count = sum(row.terminal_status == "completed" for row in rows)
    failed_count = sum(row.terminal_status == "failed" for row in rows)
    active_count = sum(row.terminal_status is None for row in rows)
    conflict_task_count = sum(row.had_reservation_conflict for row in rows)
    conflict_count = sum(row.reservation_conflict_count for row in rows)
    zero_plan_count = sum(row.zero_plan_conflict for row in rows)
    partial_count = sum(row.partial_plan for row in rows)
    authority_loss_count = sum(row.authority_lost for row in rows)
    terminal_failure_count = sum(row.terminal_persist_failed for row in rows)
    worker_config_count = sum(row.worker_lease_config_failed for row in rows)
    cleanup_count = sum(row.cleanup_warning for row in rows)

    def rate(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    return {
        "window": window,
        "from": start,
        "to": end,
        "enforceTaskCount": enforce_count,
        "planningObservedTaskCount": planning_count,
        "activeTaskCount": active_count,
        "completedTaskCount": completed_count,
        "failedTaskCount": failed_count,
        "conflictTaskCount": conflict_task_count,
        "conflictTaskRate": rate(conflict_task_count, planning_count),
        "reservationConflictCount": conflict_count,
        "zeroPlanConflictCount": zero_plan_count,
        "zeroPlanConflictRate": rate(zero_plan_count, planning_count),
        "partialPlanCount": partial_count,
        "partialPlanRate": rate(partial_count, planning_count),
        "authorityLossCount": authority_loss_count,
        "authorityLossRate": rate(authority_loss_count, enforce_count),
        "terminalPersistFailureCount": terminal_failure_count,
        "terminalPersistFailureRate": rate(terminal_failure_count, enforce_count),
        "workerLeaseConfigFailureCount": worker_config_count,
        "cleanupWarningCount": cleanup_count,
    }
