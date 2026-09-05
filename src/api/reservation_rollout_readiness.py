"""Tenant/policy rollout evidence for a future controlled Reservation canary.

This module is read-only.  A readiness result is neither Reservation authority
nor a runtime activation input.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import os
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ReservationRunDiagnostic, VideoTask
from .reservation_lease import (
    ReservationLeaseConfigurationError,
    load_reservation_lease_configuration,
)


ReservationRolloutPlanningPolicy = Literal[
    "exact_main_visual",
    "exact_main_visual_balanced",
]
ReservationRolloutReadinessState = Literal[
    "NOT_CONFIGURED",
    "INSUFFICIENT_EVIDENCE",
    "BLOCKED",
    "READY_FOR_CONTROLLED_CANARY",
]

RESERVATION_ROLLOUT_READINESS_CONFIGURATION_INVALID = (
    "RESERVATION_ROLLOUT_READINESS_CONFIGURATION_INVALID"
)
RESERVATION_ROLLOUT_READINESS_UNAVAILABLE = (
    "RESERVATION_ROLLOUT_READINESS_UNAVAILABLE"
)

_ALLOWED_POLICIES = {
    "exact_main_visual",
    "exact_main_visual_balanced",
}
_WINDOWS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
_TERMINAL_STATUSES = {"completed", "failed"}
_ENVIRONMENT_KEYS = {
    "evaluation_window": "RESERVATION_ROLLOUT_READINESS_WINDOW",
    "minimum_authoritative_enforce_tasks": (
        "RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS"
    ),
    "minimum_planning_observed_tasks": (
        "RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS"
    ),
    "minimum_conflict_tasks": (
        "RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS"
    ),
    "minimum_diagnostic_run_coverage_rate": (
        "RESERVATION_ROLLOUT_MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE"
    ),
    "minimum_planning_observation_coverage_rate": (
        "RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE"
    ),
    "minimum_terminal_observation_coverage_rate": (
        "RESERVATION_ROLLOUT_MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE"
    ),
    "maximum_zero_plan_conflict_rate": (
        "RESERVATION_ROLLOUT_MAXIMUM_ZERO_PLAN_CONFLICT_RATE"
    ),
    "maximum_partial_plan_rate": (
        "RESERVATION_ROLLOUT_MAXIMUM_PARTIAL_PLAN_RATE"
    ),
    "maximum_authority_loss_rate": (
        "RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE"
    ),
    "maximum_terminal_persist_failure_rate": (
        "RESERVATION_ROLLOUT_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE"
    ),
    "maximum_worker_lease_config_failure_rate": (
        "RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE"
    ),
    "maximum_cleanup_warning_rate": (
        "RESERVATION_ROLLOUT_MAXIMUM_CLEANUP_WARNING_RATE"
    ),
}


class ReservationRolloutReadinessConfigurationError(ValueError):
    """Stable backend-only rollout configuration failure."""

    def __init__(self) -> None:
        super().__init__(RESERVATION_ROLLOUT_READINESS_CONFIGURATION_INVALID)


@dataclass(frozen=True)
class ReservationRolloutReadinessConfiguration:
    evaluation_window: Literal["24h", "7d", "30d"]
    minimum_authoritative_enforce_tasks: int
    minimum_planning_observed_tasks: int
    minimum_conflict_tasks: int
    minimum_diagnostic_run_coverage_rate: float
    minimum_planning_observation_coverage_rate: float
    minimum_terminal_observation_coverage_rate: float
    maximum_zero_plan_conflict_rate: float
    maximum_partial_plan_rate: float
    maximum_authority_loss_rate: float
    maximum_terminal_persist_failure_rate: float
    maximum_worker_lease_config_failure_rate: float
    maximum_cleanup_warning_rate: float

    def __post_init__(self) -> None:
        if self.evaluation_window not in _WINDOWS:
            raise ReservationRolloutReadinessConfigurationError()

        count_fields = (
            "minimum_authoritative_enforce_tasks",
            "minimum_planning_observed_tasks",
            "minimum_conflict_tasks",
        )
        for name in count_fields:
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ReservationRolloutReadinessConfigurationError()

        rate_fields = (
            "minimum_diagnostic_run_coverage_rate",
            "minimum_planning_observation_coverage_rate",
            "minimum_terminal_observation_coverage_rate",
            "maximum_zero_plan_conflict_rate",
            "maximum_partial_plan_rate",
            "maximum_authority_loss_rate",
            "maximum_terminal_persist_failure_rate",
            "maximum_worker_lease_config_failure_rate",
            "maximum_cleanup_warning_rate",
        )
        for name in rate_fields:
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ReservationRolloutReadinessConfigurationError()
            object.__setattr__(self, name, float(value))


def _parse_nonnegative_integer(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ReservationRolloutReadinessConfigurationError() from None
    if parsed < 0:
        raise ReservationRolloutReadinessConfigurationError()
    return parsed


def _parse_rate(value: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ReservationRolloutReadinessConfigurationError() from None
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise ReservationRolloutReadinessConfigurationError()
    return parsed


def load_reservation_rollout_readiness_configuration(
    environ: Mapping[str, str] | None = None,
) -> ReservationRolloutReadinessConfiguration | None:
    """Load one all-or-nothing backend policy without numeric defaults."""
    source = os.environ if environ is None else environ
    present = {
        field
        for field, environment_key in _ENVIRONMENT_KEYS.items()
        if environment_key in source
    }
    if not present:
        return None
    if present != set(_ENVIRONMENT_KEYS):
        raise ReservationRolloutReadinessConfigurationError()

    def raw(field: str) -> str:
        value = source[_ENVIRONMENT_KEYS[field]]
        if not isinstance(value, str):
            raise ReservationRolloutReadinessConfigurationError()
        return value

    return ReservationRolloutReadinessConfiguration(
        evaluation_window=raw("evaluation_window"),  # type: ignore[arg-type]
        minimum_authoritative_enforce_tasks=_parse_nonnegative_integer(
            raw("minimum_authoritative_enforce_tasks")
        ),
        minimum_planning_observed_tasks=_parse_nonnegative_integer(
            raw("minimum_planning_observed_tasks")
        ),
        minimum_conflict_tasks=_parse_nonnegative_integer(
            raw("minimum_conflict_tasks")
        ),
        minimum_diagnostic_run_coverage_rate=_parse_rate(
            raw("minimum_diagnostic_run_coverage_rate")
        ),
        minimum_planning_observation_coverage_rate=_parse_rate(
            raw("minimum_planning_observation_coverage_rate")
        ),
        minimum_terminal_observation_coverage_rate=_parse_rate(
            raw("minimum_terminal_observation_coverage_rate")
        ),
        maximum_zero_plan_conflict_rate=_parse_rate(
            raw("maximum_zero_plan_conflict_rate")
        ),
        maximum_partial_plan_rate=_parse_rate(
            raw("maximum_partial_plan_rate")
        ),
        maximum_authority_loss_rate=_parse_rate(
            raw("maximum_authority_loss_rate")
        ),
        maximum_terminal_persist_failure_rate=_parse_rate(
            raw("maximum_terminal_persist_failure_rate")
        ),
        maximum_worker_lease_config_failure_rate=_parse_rate(
            raw("maximum_worker_lease_config_failure_rate")
        ),
        maximum_cleanup_warning_rate=_parse_rate(
            raw("maximum_cleanup_warning_rate")
        ),
    )


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _gate(
    code: str,
    category: Literal["EVIDENCE", "QUALITY", "SAFETY"],
    status: Literal["PASS", "FAIL", "UNKNOWN"],
    observed: int | float | bool | None,
    threshold: int | float | bool,
) -> dict[str, Any]:
    return {
        "code": code,
        "category": category,
        "status": status,
        "observed": observed,
        "threshold": threshold,
    }


def _minimum_gate(
    code: str,
    observed: int | float | None,
    threshold: int | float,
) -> dict[str, Any]:
    status = (
        "UNKNOWN"
        if observed is None
        else "PASS" if observed >= threshold else "FAIL"
    )
    return _gate(code, "EVIDENCE", status, observed, threshold)


def _maximum_gate(
    code: str,
    category: Literal["QUALITY", "SAFETY"],
    observed: float | None,
    threshold: float,
) -> dict[str, Any]:
    status = (
        "UNKNOWN"
        if observed is None
        else "PASS" if observed <= threshold else "FAIL"
    )
    return _gate(code, category, status, observed, threshold)


def _not_configured_result(
    planning_policy: ReservationRolloutPlanningPolicy,
) -> dict[str, Any]:
    return {
        "planningPolicy": planning_policy,
        "state": "NOT_CONFIGURED",
        "recommendation": "KEEP_EXPLICIT_ONLY",
        "evaluationWindow": None,
        "from": None,
        "to": None,
        "leaseConfigurationReady": None,
        "authoritativeEnforceTaskCount": None,
        "diagnosticRunCount": None,
        "diagnosticRunCoverageRate": None,
        "planningObservedTaskCount": None,
        "planningObservationCoverageRate": None,
        "authoritativeTerminalTaskCount": None,
        "terminalDiagnosticTaskCount": None,
        "terminalObservationCoverageRate": None,
        "conflictTaskCount": None,
        "conflictTaskRate": None,
        "reservationConflictCount": None,
        "zeroPlanConflictCount": None,
        "zeroPlanConflictRate": None,
        "partialPlanCount": None,
        "partialPlanRate": None,
        "authorityLossCount": None,
        "authorityLossRate": None,
        "terminalPersistFailureCount": None,
        "terminalPersistFailureRate": None,
        "workerLeaseConfigFailureCount": None,
        "workerLeaseConfigFailureRate": None,
        "cleanupWarningCount": None,
        "cleanupWarningRate": None,
        "activeTaskCount": None,
        "gates": [],
    }


def _current_lease_configuration_ready() -> bool:
    try:
        load_reservation_lease_configuration().require_configured()
        return True
    except ReservationLeaseConfigurationError:
        return False


def reservation_rollout_readiness(
    session: Session,
    *,
    planning_policy: ReservationRolloutPlanningPolicy,
    configuration: ReservationRolloutReadinessConfiguration | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate live tenant-local evidence without persisting a decision."""
    if planning_policy not in _ALLOWED_POLICIES:
        raise ValueError("RESERVATION_ROLLOUT_PLANNING_POLICY_INVALID")
    if configuration is None:
        return _not_configured_result(planning_policy)

    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = end - _WINDOWS[configuration.evaluation_window]

    rows = session.execute(
        select(
            VideoTask.status.label("task_status"),
            ReservationRunDiagnostic.id.label("diagnostic_id"),
            ReservationRunDiagnostic.planning_observed.label(
                "planning_observed"
            ),
            ReservationRunDiagnostic.reservation_conflict_count.label(
                "reservation_conflict_count"
            ),
            ReservationRunDiagnostic.had_reservation_conflict.label(
                "had_reservation_conflict"
            ),
            ReservationRunDiagnostic.zero_plan_conflict.label(
                "zero_plan_conflict"
            ),
            ReservationRunDiagnostic.partial_plan.label("partial_plan"),
            ReservationRunDiagnostic.authority_lost.label("authority_lost"),
            ReservationRunDiagnostic.terminal_persist_failed.label(
                "terminal_persist_failed"
            ),
            ReservationRunDiagnostic.worker_lease_config_failed.label(
                "worker_lease_config_failed"
            ),
            ReservationRunDiagnostic.cleanup_warning.label(
                "cleanup_warning"
            ),
            ReservationRunDiagnostic.terminal_status.label(
                "diagnostic_terminal_status"
            ),
        )
        .select_from(VideoTask)
        .outerjoin(
            ReservationRunDiagnostic,
            ReservationRunDiagnostic.task_id == VideoTask.task_id,
        )
        .where(
            VideoTask.reservation_conflict_mode == "ENFORCE",
            VideoTask.planning_policy == planning_policy,
            VideoTask.created_at >= start,
            VideoTask.created_at <= end,
        )
    ).all()

    authoritative_count = len(rows)
    diagnostic_count = sum(row.diagnostic_id is not None for row in rows)
    planning_count = sum(bool(row.planning_observed) for row in rows)
    authoritative_terminal_count = sum(
        row.task_status in _TERMINAL_STATUSES for row in rows
    )
    terminal_diagnostic_count = sum(
        row.task_status in _TERMINAL_STATUSES
        and row.diagnostic_terminal_status in _TERMINAL_STATUSES
        for row in rows
    )
    active_count = authoritative_count - authoritative_terminal_count
    conflict_task_count = sum(
        bool(row.had_reservation_conflict) for row in rows
    )
    reservation_conflict_count = sum(
        int(row.reservation_conflict_count or 0) for row in rows
    )
    zero_plan_count = sum(bool(row.zero_plan_conflict) for row in rows)
    partial_plan_count = sum(bool(row.partial_plan) for row in rows)
    authority_loss_count = sum(bool(row.authority_lost) for row in rows)
    terminal_failure_count = sum(
        bool(row.terminal_persist_failed) for row in rows
    )
    worker_config_count = sum(
        bool(row.worker_lease_config_failed) for row in rows
    )
    cleanup_count = sum(bool(row.cleanup_warning) for row in rows)

    diagnostic_coverage = _rate(diagnostic_count, authoritative_count)
    planning_coverage = _rate(planning_count, authoritative_count)
    terminal_coverage = _rate(
        terminal_diagnostic_count,
        authoritative_terminal_count,
    )
    conflict_rate = _rate(conflict_task_count, planning_count)
    zero_plan_rate = _rate(zero_plan_count, planning_count)
    partial_plan_rate = _rate(partial_plan_count, planning_count)
    authority_loss_rate = _rate(authority_loss_count, authoritative_count)
    terminal_failure_rate = _rate(
        terminal_failure_count,
        authoritative_count,
    )
    worker_config_rate = _rate(worker_config_count, authoritative_count)
    cleanup_rate = _rate(cleanup_count, authoritative_count)
    lease_ready = _current_lease_configuration_ready()

    gates = [
        _minimum_gate(
            "MINIMUM_AUTHORITATIVE_ENFORCE_TASKS",
            authoritative_count,
            configuration.minimum_authoritative_enforce_tasks,
        ),
        _minimum_gate(
            "MINIMUM_PLANNING_OBSERVED_TASKS",
            planning_count,
            configuration.minimum_planning_observed_tasks,
        ),
        _minimum_gate(
            "MINIMUM_CONFLICT_TASKS",
            conflict_task_count,
            configuration.minimum_conflict_tasks,
        ),
        _minimum_gate(
            "MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE",
            diagnostic_coverage,
            configuration.minimum_diagnostic_run_coverage_rate,
        ),
        _minimum_gate(
            "MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE",
            planning_coverage,
            configuration.minimum_planning_observation_coverage_rate,
        ),
        _minimum_gate(
            "MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE",
            terminal_coverage,
            configuration.minimum_terminal_observation_coverage_rate,
        ),
        _maximum_gate(
            "MAXIMUM_ZERO_PLAN_CONFLICT_RATE",
            "QUALITY",
            zero_plan_rate,
            configuration.maximum_zero_plan_conflict_rate,
        ),
        _maximum_gate(
            "MAXIMUM_PARTIAL_PLAN_RATE",
            "QUALITY",
            partial_plan_rate,
            configuration.maximum_partial_plan_rate,
        ),
        _maximum_gate(
            "MAXIMUM_AUTHORITY_LOSS_RATE",
            "SAFETY",
            authority_loss_rate,
            configuration.maximum_authority_loss_rate,
        ),
        _maximum_gate(
            "MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE",
            "SAFETY",
            terminal_failure_rate,
            configuration.maximum_terminal_persist_failure_rate,
        ),
        _maximum_gate(
            "MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE",
            "SAFETY",
            worker_config_rate,
            configuration.maximum_worker_lease_config_failure_rate,
        ),
        _maximum_gate(
            "MAXIMUM_CLEANUP_WARNING_RATE",
            "SAFETY",
            cleanup_rate,
            configuration.maximum_cleanup_warning_rate,
        ),
        _gate(
            "CURRENT_LEASE_CONFIGURATION_READY",
            "SAFETY",
            "PASS" if lease_ready else "FAIL",
            lease_ready,
            True,
        ),
    ]

    blocking_failure = any(
        gate["category"] in {"QUALITY", "SAFETY"}
        and gate["status"] == "FAIL"
        for gate in gates
    )
    incomplete_evidence = any(
        gate["status"] != "PASS" for gate in gates
    )
    state: ReservationRolloutReadinessState
    if blocking_failure:
        state = "BLOCKED"
    elif incomplete_evidence:
        state = "INSUFFICIENT_EVIDENCE"
    else:
        state = "READY_FOR_CONTROLLED_CANARY"

    recommendation = (
        "ELIGIBLE_FOR_CONTROLLED_DEFAULT_ON_CANARY"
        if state == "READY_FOR_CONTROLLED_CANARY"
        else "KEEP_EXPLICIT_ONLY"
    )
    return {
        "planningPolicy": planning_policy,
        "state": state,
        "recommendation": recommendation,
        "evaluationWindow": configuration.evaluation_window,
        "from": start,
        "to": end,
        "leaseConfigurationReady": lease_ready,
        "authoritativeEnforceTaskCount": authoritative_count,
        "diagnosticRunCount": diagnostic_count,
        "diagnosticRunCoverageRate": diagnostic_coverage,
        "planningObservedTaskCount": planning_count,
        "planningObservationCoverageRate": planning_coverage,
        "authoritativeTerminalTaskCount": authoritative_terminal_count,
        "terminalDiagnosticTaskCount": terminal_diagnostic_count,
        "terminalObservationCoverageRate": terminal_coverage,
        "conflictTaskCount": conflict_task_count,
        "conflictTaskRate": conflict_rate,
        "reservationConflictCount": reservation_conflict_count,
        "zeroPlanConflictCount": zero_plan_count,
        "zeroPlanConflictRate": zero_plan_rate,
        "partialPlanCount": partial_plan_count,
        "partialPlanRate": partial_plan_rate,
        "authorityLossCount": authority_loss_count,
        "authorityLossRate": authority_loss_rate,
        "terminalPersistFailureCount": terminal_failure_count,
        "terminalPersistFailureRate": terminal_failure_rate,
        "workerLeaseConfigFailureCount": worker_config_count,
        "workerLeaseConfigFailureRate": worker_config_rate,
        "cleanupWarningCount": cleanup_count,
        "cleanupWarningRate": cleanup_rate,
        "activeTaskCount": active_count,
        "gates": gates,
    }
