"""Fail-safe control for omitted-request Reservation canaries.

Rollout control may choose an effective public mode, but it is not Reservation
authority.  Planner and fencing code receive only the final effective mode.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import logging
import math
import os
import re
from typing import Any, Literal

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from .database import canonical_tenant_id
from .models import (
    ReservationRolloutBreaker,
    ReservationRunDiagnostic,
    VideoTask,
)
from .public_task_admission import PublicTaskReservationModeDecision
from .reservation_lease import (
    ReservationLeaseConfigurationError,
    load_reservation_lease_configuration,
)
from .reservation_rollout_readiness import (
    load_reservation_rollout_readiness_configuration,
    reservation_rollout_readiness,
)
from .runtime_config import reservation_runtime_mapping


logger = logging.getLogger(__name__)

ReservationRolloutPolicy = Literal[
    "exact_main_visual",
    "exact_main_visual_balanced",
]
ReservationRolloutStatusState = Literal[
    "DISABLED",
    "NOT_ELIGIBLE",
    "WARMING_UP",
    "CANARY_ACTIVE",
    "KILL_SWITCHED",
    "AUTO_ROLLED_BACK",
]

RESERVATION_ROLLOUT_CONTROL_CONFIGURATION_INVALID = (
    "RESERVATION_ROLLOUT_CONTROL_CONFIGURATION_INVALID"
)
RESERVATION_ROLLOUT_STATUS_UNAVAILABLE = (
    "RESERVATION_ROLLOUT_STATUS_UNAVAILABLE"
)

_ALLOWED_POLICIES = {
    "exact_main_visual",
    "exact_main_visual_balanced",
}
_WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}
_TERMINAL_STATUSES = {"completed", "failed"}
_SAFE_GENERATION = re.compile(r"[A-Za-z0-9._-]{1,64}")
_ENVIRONMENT_KEYS = {
    "enabled": "RESERVATION_ROLLOUT_CONTROL_ENABLED",
    "rollout_generation": "RESERVATION_ROLLOUT_GENERATION",
    "tenant_allowlist": "RESERVATION_ROLLOUT_TENANT_ALLOWLIST",
    "exact_main_visual_canary_basis_points": (
        "RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS"
    ),
    "exact_main_visual_balanced_canary_basis_points": (
        "RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS"
    ),
    "assignment_secret": "RESERVATION_ROLLOUT_ASSIGNMENT_SECRET",
    "kill_switch": "RESERVATION_ROLLOUT_KILL_SWITCH",
    "rollback_evaluation_window": (
        "RESERVATION_ROLLOUT_ROLLBACK_WINDOW"
    ),
    "minimum_canary_task_count": (
        "RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS"
    ),
    "minimum_diagnostic_run_coverage_rate": (
        "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_DIAGNOSTIC_COVERAGE_RATE"
    ),
    "minimum_planning_observation_coverage_rate": (
        "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_PLANNING_COVERAGE_RATE"
    ),
    "minimum_terminal_observation_coverage_rate": (
        "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_TERMINAL_COVERAGE_RATE"
    ),
    "maximum_zero_plan_conflict_rate": (
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE"
    ),
    "maximum_partial_plan_rate": (
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE"
    ),
    "maximum_authority_loss_rate": (
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE"
    ),
    "maximum_terminal_persist_failure_rate": (
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE"
    ),
    "maximum_worker_lease_config_failure_rate": (
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE"
    ),
    "maximum_cleanup_warning_rate": (
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE"
    ),
}
RESERVATION_ROLLOUT_CONTROL_ENVIRONMENT_KEYS = frozenset(
    _ENVIRONMENT_KEYS.values()
)
_ROLLBACK_REASONS = (
    (
        "diagnosticRunCoverageRate",
        "minimum_diagnostic_run_coverage_rate",
        "DIAGNOSTIC_RUN_COVERAGE_BELOW_MINIMUM",
        "minimum",
    ),
    (
        "planningObservationCoverageRate",
        "minimum_planning_observation_coverage_rate",
        "PLANNING_OBSERVATION_COVERAGE_BELOW_MINIMUM",
        "minimum",
    ),
    (
        "terminalObservationCoverageRate",
        "minimum_terminal_observation_coverage_rate",
        "TERMINAL_OBSERVATION_COVERAGE_BELOW_MINIMUM",
        "minimum",
    ),
    (
        "zeroPlanConflictRate",
        "maximum_zero_plan_conflict_rate",
        "ZERO_PLAN_CONFLICT_RATE_EXCEEDED",
        "maximum",
    ),
    (
        "partialPlanRate",
        "maximum_partial_plan_rate",
        "PARTIAL_PLAN_RATE_EXCEEDED",
        "maximum",
    ),
    (
        "authorityLossRate",
        "maximum_authority_loss_rate",
        "AUTHORITY_LOSS_RATE_EXCEEDED",
        "maximum",
    ),
    (
        "terminalPersistFailureRate",
        "maximum_terminal_persist_failure_rate",
        "TERMINAL_PERSIST_FAILURE_RATE_EXCEEDED",
        "maximum",
    ),
    (
        "workerLeaseConfigFailureRate",
        "maximum_worker_lease_config_failure_rate",
        "WORKER_LEASE_CONFIG_FAILURE_RATE_EXCEEDED",
        "maximum",
    ),
    (
        "cleanupWarningRate",
        "maximum_cleanup_warning_rate",
        "CLEANUP_WARNING_RATE_EXCEEDED",
        "maximum",
    ),
)


def _safe_warning(event: str, exc: Exception) -> None:
    """Keep optional rollout logging inside the fail-safe boundary."""
    try:
        logger.warning(
            "[%s] category=%s",
            event,
            type(exc).__name__[:64],
        )
    except Exception:
        pass


class ReservationRolloutControlConfigurationError(ValueError):
    """Stable all-or-none operator configuration failure."""

    def __init__(self) -> None:
        super().__init__(RESERVATION_ROLLOUT_CONTROL_CONFIGURATION_INVALID)


@dataclass(frozen=True)
class ReservationRolloutControlConfiguration:
    enabled: bool
    rollout_generation: str
    tenant_allowlist: frozenset[str]
    exact_main_visual_canary_basis_points: int
    exact_main_visual_balanced_canary_basis_points: int
    assignment_secret: str = field(repr=False)
    kill_switch: bool
    rollback_evaluation_window: Literal["1h", "24h", "7d"]
    minimum_canary_task_count: int
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
        if not isinstance(self.enabled, bool) or not isinstance(
            self.kill_switch,
            bool,
        ):
            raise ReservationRolloutControlConfigurationError()
        if (
            not isinstance(self.rollout_generation, str)
            or _SAFE_GENERATION.fullmatch(self.rollout_generation) is None
        ):
            raise ReservationRolloutControlConfigurationError()
        if (
            not isinstance(self.tenant_allowlist, frozenset)
            or any(
                not isinstance(tenant, str)
                or not tenant
                or canonical_tenant_id(tenant) != tenant
                for tenant in self.tenant_allowlist
            )
        ):
            raise ReservationRolloutControlConfigurationError()
        if (
            not isinstance(self.assignment_secret, str)
            or not self.assignment_secret
        ):
            raise ReservationRolloutControlConfigurationError()
        if self.rollback_evaluation_window not in _WINDOWS:
            raise ReservationRolloutControlConfigurationError()

        basis_point_fields = (
            "exact_main_visual_canary_basis_points",
            "exact_main_visual_balanced_canary_basis_points",
        )
        for name in basis_point_fields:
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 10000
            ):
                raise ReservationRolloutControlConfigurationError()
        if (
            isinstance(self.minimum_canary_task_count, bool)
            or not isinstance(self.minimum_canary_task_count, int)
            or self.minimum_canary_task_count < 1
        ):
            raise ReservationRolloutControlConfigurationError()

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
                raise ReservationRolloutControlConfigurationError()
            object.__setattr__(self, name, float(value))

    def canary_basis_points(self, planning_policy: str) -> int:
        if planning_policy == "exact_main_visual":
            return self.exact_main_visual_canary_basis_points
        if planning_policy == "exact_main_visual_balanced":
            return self.exact_main_visual_balanced_canary_basis_points
        return 0


def _parse_bool(value: str) -> bool:
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    raise ReservationRolloutControlConfigurationError()


def _parse_integer(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ReservationRolloutControlConfigurationError() from None


def _parse_rate(value: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ReservationRolloutControlConfigurationError() from None
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise ReservationRolloutControlConfigurationError()
    return parsed


def _parse_tenant_allowlist(value: str) -> frozenset[str]:
    if not isinstance(value, str):
        raise ReservationRolloutControlConfigurationError()
    raw_tenants = [tenant.strip() for tenant in value.split(",")]
    if any(not tenant for tenant in raw_tenants):
        if raw_tenants == [""]:
            return frozenset()
        raise ReservationRolloutControlConfigurationError()
    tenants = frozenset(canonical_tenant_id(tenant) for tenant in raw_tenants)
    if any(
        canonical_tenant_id(raw) != raw
        for raw in raw_tenants
    ):
        raise ReservationRolloutControlConfigurationError()
    return tenants


def load_reservation_rollout_control_configuration(
    environ: Mapping[str, str] | None = None,
) -> ReservationRolloutControlConfiguration | None:
    """Load one backend-only rollout policy without numeric defaults."""
    source = os.environ if environ is None else environ
    present = {
        field
        for field, environment_key in _ENVIRONMENT_KEYS.items()
        if environment_key in source
    }
    if not present:
        return None
    if present != set(_ENVIRONMENT_KEYS):
        raise ReservationRolloutControlConfigurationError()

    def raw(field: str) -> str:
        value = source[_ENVIRONMENT_KEYS[field]]
        if not isinstance(value, str):
            raise ReservationRolloutControlConfigurationError()
        return value

    return ReservationRolloutControlConfiguration(
        enabled=_parse_bool(raw("enabled")),
        rollout_generation=raw("rollout_generation"),
        tenant_allowlist=_parse_tenant_allowlist(raw("tenant_allowlist")),
        exact_main_visual_canary_basis_points=_parse_integer(
            raw("exact_main_visual_canary_basis_points")
        ),
        exact_main_visual_balanced_canary_basis_points=_parse_integer(
            raw("exact_main_visual_balanced_canary_basis_points")
        ),
        assignment_secret=raw("assignment_secret"),
        kill_switch=_parse_bool(raw("kill_switch")),
        rollback_evaluation_window=raw(  # type: ignore[arg-type]
            "rollback_evaluation_window"
        ),
        minimum_canary_task_count=_parse_integer(
            raw("minimum_canary_task_count")
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


def deterministic_rollout_bucket(
    *,
    assignment_secret: str,
    canonical_tenant: str,
    planning_policy: str,
    task_id: str,
    rollout_generation: str,
) -> int:
    """Map server-owned assignment inputs to a stable 0..9999 bucket."""
    message = "\x1f".join(
        (
            "reservation-rollout-v1",
            canonical_tenant,
            planning_policy,
            task_id,
            rollout_generation,
        )
    ).encode("utf-8")
    digest = hmac.new(
        assignment_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()
    return int.from_bytes(digest, "big") % 10000


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _canary_metrics(
    session: Session,
    *,
    planning_policy: ReservationRolloutPolicy,
    configuration: ReservationRolloutControlConfiguration,
    now: datetime | None = None,
) -> dict[str, Any]:
    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = end - _WINDOWS[configuration.rollback_evaluation_window]
    rows = session.execute(
        select(
            VideoTask.status.label("task_status"),
            ReservationRunDiagnostic.id.label("diagnostic_id"),
            ReservationRunDiagnostic.planning_observed.label(
                "planning_observed"
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
            VideoTask.reservation_mode_source == "ROLLOUT_CANARY",
            VideoTask.planning_policy == planning_policy,
            VideoTask.rollout_generation
            == configuration.rollout_generation,
            VideoTask.created_at >= start,
            VideoTask.created_at <= end,
        )
    ).all()

    canary_count = len(rows)
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

    return {
        "rollbackWindow": configuration.rollback_evaluation_window,
        "from": start,
        "to": end,
        "canaryTaskCount": canary_count,
        "diagnosticRunCount": diagnostic_count,
        "diagnosticRunCoverageRate": _rate(
            diagnostic_count,
            canary_count,
        ),
        "planningObservedTaskCount": planning_count,
        "planningObservationCoverageRate": _rate(
            planning_count,
            canary_count,
        ),
        "authoritativeTerminalTaskCount": authoritative_terminal_count,
        "terminalDiagnosticTaskCount": terminal_diagnostic_count,
        "terminalObservationCoverageRate": _rate(
            terminal_diagnostic_count,
            authoritative_terminal_count,
        ),
        "zeroPlanConflictCount": zero_plan_count,
        "zeroPlanConflictRate": _rate(zero_plan_count, planning_count),
        "partialPlanCount": partial_plan_count,
        "partialPlanRate": _rate(partial_plan_count, planning_count),
        "authorityLossCount": authority_loss_count,
        "authorityLossRate": _rate(authority_loss_count, canary_count),
        "terminalPersistFailureCount": terminal_failure_count,
        "terminalPersistFailureRate": _rate(
            terminal_failure_count,
            canary_count,
        ),
        "workerLeaseConfigFailureCount": worker_config_count,
        "workerLeaseConfigFailureRate": _rate(
            worker_config_count,
            canary_count,
        ),
        "cleanupWarningCount": cleanup_count,
        "cleanupWarningRate": _rate(cleanup_count, canary_count),
    }


def _generation_canary_task_count(
    session: Session,
    *,
    planning_policy: str,
    rollout_generation: str,
) -> int:
    """Count whether a generation ever started, independent of guard window."""
    return int(
        session.scalar(
            select(func.count(VideoTask.id)).where(
                VideoTask.reservation_mode_source == "ROLLOUT_CANARY",
                VideoTask.planning_policy == planning_policy,
                VideoTask.rollout_generation == rollout_generation,
            )
        )
        or 0
    )


def _rollback_reason(
    metrics: Mapping[str, Any],
    configuration: ReservationRolloutControlConfiguration,
) -> str | None:
    if metrics["canaryTaskCount"] == 0:
        return None
    for metric, threshold_field, reason, comparison in _ROLLBACK_REASONS:
        observed = metrics[metric]
        if observed is None:
            continue
        threshold = getattr(configuration, threshold_field)
        failed = (
            observed < threshold
            if comparison == "minimum"
            else observed > threshold
        )
        if failed:
            return reason
    return None


def _find_breaker(
    session: Session,
    *,
    planning_policy: str,
    rollout_generation: str,
) -> ReservationRolloutBreaker | None:
    return session.scalar(
        select(ReservationRolloutBreaker).where(
            ReservationRolloutBreaker.planning_policy == planning_policy,
            ReservationRolloutBreaker.rollout_generation
            == rollout_generation,
        )
    )


def _trip_breaker(
    session: Session,
    *,
    planning_policy: str,
    rollout_generation: str,
    reason_code: str,
) -> bool:
    try:
        session.execute(
            sqlite_insert(ReservationRolloutBreaker)
            .values(
                planning_policy=planning_policy,
                rollout_generation=rollout_generation,
                reason_code=reason_code,
                tripped_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ReservationRolloutBreaker.planning_policy,
                    ReservationRolloutBreaker.rollout_generation,
                ]
            )
        )
        session.commit()
        return True
    except Exception as exc:
        try:
            session.rollback()
        except Exception:
            pass
        _safe_warning(
            "RESERVATION_ROLLOUT_BREAKER_WRITE_FAILED",
            exc,
        )
        return False


def _default_off_decision() -> PublicTaskReservationModeDecision:
    return PublicTaskReservationModeDecision(
        reservation_conflict_mode="OFF",
        reservation_mode_source="DEFAULT_OFF",
    )


def resolve_omitted_reservation_mode(
    bind: Engine,
    *,
    canonical_tenant: str,
    planning_policy: str,
    task_id: str,
) -> PublicTaskReservationModeDecision:
    """Resolve optional promotion; every control failure returns OFF."""
    try:
        runtime_mapping = reservation_runtime_mapping()
        configuration = load_reservation_rollout_control_configuration(
            runtime_mapping
        )
        if (
            configuration is None
            or not configuration.enabled
            or configuration.kill_switch
            or planning_policy not in _ALLOWED_POLICIES
            or canonical_tenant not in configuration.tenant_allowlist
        ):
            return _default_off_decision()
        basis_points = configuration.canary_basis_points(planning_policy)
        if basis_points == 0:
            return _default_off_decision()

        SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            bind=bind,
        )
        with SessionLocal() as session:
            breaker = _find_breaker(
                session,
                planning_policy=planning_policy,
                rollout_generation=configuration.rollout_generation,
            )
            if breaker is not None:
                return _default_off_decision()

            metrics = _canary_metrics(
                session,
                planning_policy=planning_policy,  # type: ignore[arg-type]
                configuration=configuration,
            )
            generation_canary_count = _generation_canary_task_count(
                session,
                planning_policy=planning_policy,
                rollout_generation=configuration.rollout_generation,
            )
            readiness_configuration = (
                load_reservation_rollout_readiness_configuration(runtime_mapping)
            )
            readiness = reservation_rollout_readiness(
                session,
                planning_policy=planning_policy,  # type: ignore[arg-type]
                configuration=readiness_configuration,
                runtime_mapping=runtime_mapping,
            )
            readiness_ready = (
                readiness["state"] == "READY_FOR_CONTROLLED_CANARY"
            )
            if not readiness_ready:
                if generation_canary_count > 0:
                    _trip_breaker(
                        session,
                        planning_policy=planning_policy,
                        rollout_generation=configuration.rollout_generation,
                        reason_code="READINESS_LOST",
                    )
                return _default_off_decision()

            rollback_reason = _rollback_reason(metrics, configuration)
            if rollback_reason is not None:
                _trip_breaker(
                    session,
                    planning_policy=planning_policy,
                    rollout_generation=configuration.rollout_generation,
                    reason_code=rollback_reason,
                )
                return _default_off_decision()

        bucket = deterministic_rollout_bucket(
            assignment_secret=configuration.assignment_secret,
            canonical_tenant=canonical_tenant,
            planning_policy=planning_policy,
            task_id=task_id,
            rollout_generation=configuration.rollout_generation,
        )
        if bucket >= basis_points:
            return _default_off_decision()

        try:
            load_reservation_lease_configuration(
                runtime_mapping
            ).require_configured()
        except ReservationLeaseConfigurationError:
            return _default_off_decision()
        return PublicTaskReservationModeDecision(
            reservation_conflict_mode="ENFORCE",
            reservation_mode_source="ROLLOUT_CANARY",
            rollout_generation=configuration.rollout_generation,
            rollout_bucket=bucket,
            rollout_canary_basis_points=basis_points,
        )
    except Exception as exc:
        _safe_warning(
            "RESERVATION_ROLLOUT_CONTROL_FAILED",
            exc,
        )
        return _default_off_decision()


def _disabled_status(
    planning_policy: ReservationRolloutPolicy,
) -> dict[str, Any]:
    return {
        "planningPolicy": planning_policy,
        "state": "DISABLED",
        "rolloutGeneration": None,
        "canaryBasisPoints": None,
        "readinessState": None,
        "breakerTripped": False,
        "breakerReason": None,
        "rollbackWindow": None,
        "from": None,
        "to": None,
        "canaryTaskCount": None,
        "diagnosticRunCoverageRate": None,
        "planningObservationCoverageRate": None,
        "terminalObservationCoverageRate": None,
        "zeroPlanConflictRate": None,
        "partialPlanRate": None,
        "authorityLossRate": None,
        "terminalPersistFailureRate": None,
        "workerLeaseConfigFailureRate": None,
        "cleanupWarningRate": None,
    }


def reservation_rollout_status(
    session: Session,
    *,
    canonical_tenant: str,
    planning_policy: ReservationRolloutPolicy,
    configuration: ReservationRolloutControlConfiguration | None,
    now: datetime | None = None,
    runtime_mapping: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Compute operator status without mutating breaker or rollout state."""
    if planning_policy not in _ALLOWED_POLICIES:
        raise ValueError("RESERVATION_ROLLOUT_PLANNING_POLICY_INVALID")
    if configuration is None:
        return _disabled_status(planning_policy)

    basis_points = configuration.canary_basis_points(planning_policy)
    metrics = _canary_metrics(
        session,
        planning_policy=planning_policy,
        configuration=configuration,
        now=now,
    )
    breaker = _find_breaker(
        session,
        planning_policy=planning_policy,
        rollout_generation=configuration.rollout_generation,
    )
    base = {
        "planningPolicy": planning_policy,
        "rolloutGeneration": configuration.rollout_generation,
        "canaryBasisPoints": basis_points,
        "breakerTripped": breaker is not None,
        "breakerReason": breaker.reason_code if breaker is not None else None,
        **{
            key: metrics[key]
            for key in (
                "rollbackWindow",
                "from",
                "to",
                "canaryTaskCount",
                "diagnosticRunCoverageRate",
                "planningObservationCoverageRate",
                "terminalObservationCoverageRate",
                "zeroPlanConflictRate",
                "partialPlanRate",
                "authorityLossRate",
                "terminalPersistFailureRate",
                "workerLeaseConfigFailureRate",
                "cleanupWarningRate",
            )
        },
    }

    if not configuration.enabled:
        return {**base, "state": "DISABLED", "readinessState": None}
    if configuration.kill_switch:
        return {**base, "state": "KILL_SWITCHED", "readinessState": None}
    if (
        canonical_tenant not in configuration.tenant_allowlist
        or basis_points == 0
    ):
        return {**base, "state": "NOT_ELIGIBLE", "readinessState": None}
    if breaker is not None:
        return {
            **base,
            "state": "AUTO_ROLLED_BACK",
            "readinessState": None,
        }

    active_runtime_mapping = (
        reservation_runtime_mapping()
        if runtime_mapping is None
        else runtime_mapping
    )
    readiness_configuration = load_reservation_rollout_readiness_configuration(
        active_runtime_mapping
    )
    readiness = reservation_rollout_readiness(
        session,
        planning_policy=planning_policy,
        configuration=readiness_configuration,
        now=now,
        runtime_mapping=active_runtime_mapping,
    )
    readiness_state = readiness["state"]
    if readiness_state != "READY_FOR_CONTROLLED_CANARY":
        return {
            **base,
            "state": "NOT_ELIGIBLE",
            "readinessState": readiness_state,
        }
    if _rollback_reason(metrics, configuration) is not None:
        return {
            **base,
            "state": "NOT_ELIGIBLE",
            "readinessState": readiness_state,
        }
    state = (
        "WARMING_UP"
        if metrics["canaryTaskCount"]
        < configuration.minimum_canary_task_count
        else "CANARY_ACTIVE"
    )
    return {**base, "state": state, "readinessState": readiness_state}
