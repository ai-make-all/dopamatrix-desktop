"""H4-6 SAFE_OFF and named Philippine Seed operator transitions."""

from __future__ import annotations

import math
import re
import secrets
import sqlite3
import stat
import unicodedata
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .delivery_output import (
    DeliveryPathError,
    DeliverySettingsReadError,
    derive_tenant_delivery_root,
    read_current_delivery_root,
)
from .operator_backup import OperatorBackupOutcome, verify_operator_backup
from .operator_tenant_provision import (
    OPERATOR_APPROVAL_REF_INVALID,
    OPERATOR_TENANT_INVALID,
    ApprovedTenantIdentity,
    validate_approval_ref,
    validate_approved_tenant_identity,
)
from .policy_profiles import (
    ASSIGNMENT_SECRET_ENVIRONMENT_KEY,
    OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE,
    OPERATIONAL_SNAPSHOT_INVALID,
    OPERATIONAL_SNAPSHOT_SETTING_KEY,
    AppliedOperationalSnapshot,
    OperationalProfileError,
    OperationalSnapshotError,
    PhilippineSeedStage,
    _write_snapshot_on_connection,
    build_applied_operational_snapshot,
    materialize_philippine_seed_profile,
    parse_applied_operational_snapshot,
)
from .reservation_lease import (
    RESERVATION_HEARTBEAT_INTERVAL_ENV,
    RESERVATION_LEASE_TTL_ENV,
)
from .reservation_rollout_control import (
    load_reservation_rollout_control_configuration,
    reservation_rollout_status,
)
from .reservation_rollout_readiness import (
    load_reservation_rollout_readiness_configuration,
    reservation_rollout_readiness,
)
from .runtime_mutation import (
    MutationPrestateMismatch,
    MutationTransactionError,
    RuntimeMutationBarrierBusy,
    RuntimeMutationBarrierError,
    acquire_runtime_mutation_barrier,
    checked_immediate_transaction,
)
from .runtime_paths import (
    LegacyRuntimeMigrationRequired,
    RuntimePaths,
    RuntimePathsError,
    get_initialized_runtime_paths,
    initialize_runtime_paths,
)
from .secret_store import (
    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
    SecretStore,
    SecretStoreError,
    _create_app_settings_table,
    _create_secure_settings_table,
    create_platform_secret_protector,
)


OPERATOR_SEED_GENERATION_INVALID = "OPERATOR_SEED_GENERATION_INVALID"
OPERATOR_REASON_CODE_INVALID = "OPERATOR_REASON_CODE_INVALID"
OPERATOR_SEED_LEASE_PROFILE_INVALID = "OPERATOR_SEED_LEASE_PROFILE_INVALID"
OPERATOR_SEED_BPS_INVALID = "OPERATOR_SEED_BPS_INVALID"
OPERATOR_SEED_BPS_CHANGE_TOO_LARGE = "OPERATOR_SEED_BPS_CHANGE_TOO_LARGE"
OPERATOR_SEED_TENANT_NOT_FOUND = "OPERATOR_SEED_TENANT_NOT_FOUND"
OPERATOR_SEED_SNAPSHOT_STATE_INVALID = "OPERATOR_SEED_SNAPSHOT_STATE_INVALID"
OPERATOR_SEED_SNAPSHOT_INTEGRITY_FAILED = (
    "OPERATOR_SEED_SNAPSHOT_INTEGRITY_FAILED"
)
OPERATOR_SEED_BACKUP_TENANT_MISMATCH = "OPERATOR_SEED_BACKUP_TENANT_MISMATCH"
OPERATOR_SEED_DELIVERY_NOT_CONFIGURED = "OPERATOR_SEED_DELIVERY_NOT_CONFIGURED"
OPERATOR_SEED_READINESS_NOT_READY = "OPERATOR_SEED_READINESS_NOT_READY"
OPERATOR_SEED_BREAKER_LATCHED = "OPERATOR_SEED_BREAKER_LATCHED"
OPERATOR_SEED_COHORT_NOT_READY = "OPERATOR_SEED_COHORT_NOT_READY"
OPERATOR_RUNTIME_MUTATION_BUSY = "OPERATOR_RUNTIME_MUTATION_BUSY"
OPERATOR_SEED_SUBSYSTEM_FAILED = "OPERATOR_SEED_SUBSYSTEM_FAILED"
OPERATOR_SEED_INTERNAL_FAILED = "OPERATOR_SEED_INTERNAL_FAILED"
P3A_24H_ELIGIBILITY_NOT_PROVABLE = "P3A_24H_ELIGIBILITY_NOT_PROVABLE"

_BALANCED_BPS_KEY = "RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS"
_EXACT_BPS_KEY = "RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS"
_KILL_SWITCH_KEY = "RESERVATION_ROLLOUT_KILL_SWITCH"
_ROLLBACK_WINDOW_KEY = "RESERVATION_ROLLOUT_ROLLBACK_WINDOW"
_PLANNING_POLICY = "exact_main_visual_balanced"
_GENERATION_PATTERN = re.compile(
    r"^phseed-(?P<tenantcode>[a-z0-9]+)-bal-"
    r"(?P<date>[0-9]{8})-r(?P<revision>[1-9][0-9]*)$",
    re.ASCII,
)
_LEASE_PROFILES = MappingProxyType(
    {
        "180-45": (180, 45),
        "300-60": (300, 60),
    }
)
_BACKUP_COMMANDS = frozenset(
    {"prearm-p3w", "activate", "set-balanced-bps", "transition-p3a"}
)
_EVIDENCE_COMMANDS = frozenset({"prearm-p3w", "activate", "transition-p3a"})
_DELIVERY_COMMANDS = frozenset({"prearm-p3w", "activate"})
_ACTUAL_STATUSES = MappingProxyType(
    {
        "apply-safe-off": "APPLIED",
        "prearm-p3w": "PREARMED",
        "activate": "ACTIVATED",
        "kill": "CONTAINED",
        "set-balanced-bps": "BALANCED_BPS_SET",
        "transition-p3a": "TRANSITIONED",
    }
)
_NOOP_STATUSES = MappingProxyType(
    {
        "apply-safe-off": "ALREADY_APPLIED",
        "prearm-p3w": "ALREADY_PREARMED",
        "activate": "ALREADY_ACTIVE",
        "kill": "ALREADY_CONTAINED",
        "set-balanced-bps": "ALREADY_SET",
        "transition-p3a": "ALREADY_TRANSITIONED",
    }
)


@dataclass(frozen=True)
class OperatorSeedOutcome:
    status: str
    message: str
    data: Mapping[str, Any]
    exit_code: int = 0
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


@dataclass(frozen=True)
class SeedSourceEvidence:
    readiness_state: str
    breaker_tripped: bool
    breaker_reason: str | None
    metrics: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))


@dataclass(frozen=True)
class _SeedPrestate:
    serialized_snapshot: str | None
    snapshot: AppliedOperationalSnapshot | None
    assignment_secret: str | None


@dataclass(frozen=True)
class _SeedPlan:
    target_stage: PhilippineSeedStage
    target_values: Mapping[str, str]
    no_write: bool


class _SeedFailure(Exception):
    def __init__(self, error_code: str, exit_code: int, message: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.exit_code = exit_code
        self.message = message


def _failure(error_code: str, exit_code: int, message: str) -> _SeedFailure:
    return _SeedFailure(error_code, exit_code, message)


def validate_operator_seed_generation(
    generation: str,
    identity: ApprovedTenantIdentity,
) -> str:
    if not isinstance(generation, str):
        raise _failure(
            OPERATOR_SEED_GENERATION_INVALID,
            3,
            "Seed generation is invalid",
        )
    match = _GENERATION_PATTERN.fullmatch(generation)
    if (
        match is None
        or match.group("tenantcode") != identity.short_code
    ):
        raise _failure(
            OPERATOR_SEED_GENERATION_INVALID,
            3,
            "Seed generation is invalid",
        )
    try:
        datetime.strptime(match.group("date"), "%Y%m%d")
    except ValueError:
        raise _failure(
            OPERATOR_SEED_GENERATION_INVALID,
            3,
            "Seed generation is invalid",
        ) from None
    return generation


def validate_reason_code(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or not value.strip()
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise _failure(
            OPERATOR_REASON_CODE_INVALID,
            3,
            "reason code is invalid",
        )
    return value


def _validate_identity(tenant_id: str) -> ApprovedTenantIdentity:
    try:
        return validate_approved_tenant_identity(tenant_id)
    except Exception as exc:
        if getattr(exc, "error_code", None) == OPERATOR_TENANT_INVALID:
            raise _failure(
                OPERATOR_TENANT_INVALID,
                3,
                "tenant identity is not approved",
            ) from None
        raise


def _validate_approval(value: str | None) -> str:
    try:
        return validate_approval_ref(value)  # type: ignore[arg-type]
    except Exception as exc:
        if getattr(exc, "error_code", None) == OPERATOR_APPROVAL_REF_INVALID:
            raise _failure(
                OPERATOR_APPROVAL_REF_INVALID,
                3,
                "approval reference is invalid",
            ) from None
        raise


def _parse_lease_profile(value: str | None) -> tuple[int, int]:
    selected = "180-45" if value is None else value
    try:
        return _LEASE_PROFILES[selected]
    except (KeyError, TypeError):
        raise _failure(
            OPERATOR_SEED_LEASE_PROFILE_INVALID,
            3,
            "lease profile is invalid",
        ) from None


def _initialize_operator_runtime_paths() -> RuntimePaths:
    return get_initialized_runtime_paths() or initialize_runtime_paths()


def _default_store(paths: RuntimePaths) -> SecretStore:
    return SecretStore(
        paths.settings_db_path,
        create_platform_secret_protector(),
    )


def _default_connection(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database, timeout=5.0)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;",
            (table_name,),
        ).fetchone()
        is not None
    )


def _read_prestate(
    connection: sqlite3.Connection,
    store: SecretStore,
) -> _SeedPrestate:
    serialized: str | None = None
    if _table_exists(connection, "app_settings"):
        row = connection.execute(
            "SELECT key_value FROM app_settings WHERE key_name = ?;",
            (OPERATIONAL_SNAPSHOT_SETTING_KEY,),
        ).fetchone()
        if row is not None:
            if not isinstance(row[0], str):
                raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_INVALID)
            serialized = row[0]

    assignment_secret: str | None = None
    if _table_exists(connection, "secure_settings"):
        secret_row = store._read_row(
            connection,
            RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
        )
        if secret_row is not None:
            assignment_secret = store._decrypt_row(secret_row)
            if not assignment_secret:
                raise OperationalSnapshotError(
                    OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE
                )

    snapshot: AppliedOperationalSnapshot | None = None
    if serialized is not None:
        if assignment_secret is None:
            raise OperationalSnapshotError(
                OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE
            )
        snapshot = parse_applied_operational_snapshot(
            serialized,
            assignment_secret=assignment_secret,
        )
    return _SeedPrestate(serialized, snapshot, assignment_secret)


def _profile_arguments(
    snapshot: AppliedOperationalSnapshot,
) -> tuple[int, tuple[int, int], str, bool]:
    values = snapshot.effective_values
    return (
        int(values[_BALANCED_BPS_KEY]),
        (
            int(values[RESERVATION_LEASE_TTL_ENV]),
            int(values[RESERVATION_HEARTBEAT_INTERVAL_ENV]),
        ),
        values[_ROLLBACK_WINDOW_KEY],
        values[_KILL_SWITCH_KEY] == "true",
    )


def _target_values(
    *,
    tenant: str,
    generation: str,
    stage: PhilippineSeedStage,
    balanced_basis_points: int,
    lease_profile: tuple[int, int],
    rollback_window: str,
    kill_switch: bool,
) -> Mapping[str, str]:
    return materialize_philippine_seed_profile(
        tenant_id=tenant,
        generation=generation,
        stage=stage,
        balanced_basis_points=balanced_basis_points,
        lease_profile=lease_profile,
        rollback_window=rollback_window,
        kill_switch=kill_switch,
    )


def _same_target(
    snapshot: AppliedOperationalSnapshot,
    *,
    stage: PhilippineSeedStage,
    values: Mapping[str, str],
) -> bool:
    return snapshot.stage is stage and dict(snapshot.effective_values) == dict(values)


def _require_snapshot_identity(
    prestate: _SeedPrestate,
    *,
    tenant: str,
    generation: str,
) -> AppliedOperationalSnapshot:
    snapshot = prestate.snapshot
    if snapshot is None:
        raise _failure(
            OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
            4,
            "applied Seed snapshot is missing",
        )
    if (
        snapshot.tenant_allowlist != (tenant,)
        or snapshot.generation != generation
    ):
        raise _failure(
            OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
            4,
            "applied Seed snapshot does not match the command",
        )
    return snapshot


def _build_plan(
    command: str,
    prestate: _SeedPrestate,
    *,
    tenant: str,
    generation: str,
    lease_profile: tuple[int, int],
    balanced_basis_points: int | None,
) -> _SeedPlan:
    if command == "apply-safe-off":
        target = _target_values(
            tenant=tenant,
            generation=generation,
            stage=PhilippineSeedStage.SAFE_OFF,
            balanced_basis_points=0,
            lease_profile=lease_profile,
            rollback_window="7d",
            kill_switch=True,
        )
        if prestate.snapshot is None:
            return _SeedPlan(PhilippineSeedStage.SAFE_OFF, target, False)
        snapshot = _require_snapshot_identity(
            prestate,
            tenant=tenant,
            generation=generation,
        )
        if _same_target(
            snapshot,
            stage=PhilippineSeedStage.SAFE_OFF,
            values=target,
        ):
            return _SeedPlan(PhilippineSeedStage.SAFE_OFF, target, True)
        raise _failure(
            OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
            4,
            "SAFE_OFF may only initialize an absent snapshot",
        )

    snapshot = _require_snapshot_identity(
        prestate,
        tenant=tenant,
        generation=generation,
    )
    current_bps, current_lease, current_window, current_kill = _profile_arguments(
        snapshot
    )

    if command == "prearm-p3w":
        target = _target_values(
            tenant=tenant,
            generation=generation,
            stage=PhilippineSeedStage.P3_W,
            balanced_basis_points=3000,
            lease_profile=current_lease,
            rollback_window="7d",
            kill_switch=True,
        )
        if _same_target(snapshot, stage=PhilippineSeedStage.P3_W, values=target):
            return _SeedPlan(PhilippineSeedStage.P3_W, target, True)
        if snapshot.stage is not PhilippineSeedStage.SAFE_OFF:
            raise _failure(
                OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
                4,
                "P3-W pre-arm requires SAFE_OFF",
            )
        return _SeedPlan(PhilippineSeedStage.P3_W, target, False)

    if command == "activate":
        if snapshot.stage not in {PhilippineSeedStage.P3_W, PhilippineSeedStage.P3_A}:
            raise _failure(
                OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
                4,
                "activation requires a contained P3 snapshot",
            )
        if (
            snapshot.stage is PhilippineSeedStage.P3_A
            and current_window == "24h"
        ):
            raise _failure(
                P3A_24H_ELIGIBILITY_NOT_PROVABLE,
                4,
                "P3-A 24-hour eligibility is not machine-provable",
            )
        target = _target_values(
            tenant=tenant,
            generation=generation,
            stage=snapshot.stage,
            balanced_basis_points=current_bps,
            lease_profile=current_lease,
            rollback_window=current_window,
            kill_switch=False,
        )
        return _SeedPlan(
            snapshot.stage,
            target,
            _same_target(snapshot, stage=snapshot.stage, values=target),
        )

    if command == "kill":
        if snapshot.stage not in {PhilippineSeedStage.P3_W, PhilippineSeedStage.P3_A}:
            raise _failure(
                OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
                4,
                "containment requires a P3 snapshot",
            )
        target = _target_values(
            tenant=tenant,
            generation=generation,
            stage=snapshot.stage,
            balanced_basis_points=current_bps,
            lease_profile=current_lease,
            rollback_window=current_window,
            kill_switch=True,
        )
        return _SeedPlan(
            snapshot.stage,
            target,
            _same_target(snapshot, stage=snapshot.stage, values=target),
        )

    if command == "set-balanced-bps":
        if snapshot.stage not in {PhilippineSeedStage.P3_W, PhilippineSeedStage.P3_A}:
            raise _failure(
                OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
                4,
                "Balanced BPS change requires a P3 snapshot",
            )
        if not current_kill:
            raise _failure(
                OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
                4,
                "Balanced BPS change requires kill containment",
            )
        if balanced_basis_points is None:  # defensive direct-call guard
            raise _failure(
                OPERATOR_SEED_BPS_INVALID,
                3,
                "Balanced BPS is invalid",
            )
        if abs(balanced_basis_points - current_bps) > 1000:
            raise _failure(
                OPERATOR_SEED_BPS_CHANGE_TOO_LARGE,
                4,
                "Balanced BPS change exceeds the reviewed bound",
            )
        target = _target_values(
            tenant=tenant,
            generation=generation,
            stage=snapshot.stage,
            balanced_basis_points=balanced_basis_points,
            lease_profile=current_lease,
            rollback_window=current_window,
            kill_switch=True,
        )
        return _SeedPlan(
            snapshot.stage,
            target,
            _same_target(snapshot, stage=snapshot.stage, values=target),
        )

    if command == "transition-p3a":
        target = _target_values(
            tenant=tenant,
            generation=generation,
            stage=PhilippineSeedStage.P3_A,
            balanced_basis_points=current_bps,
            lease_profile=current_lease,
            rollback_window="7d",
            kill_switch=True,
        )
        if _same_target(snapshot, stage=PhilippineSeedStage.P3_A, values=target):
            return _SeedPlan(PhilippineSeedStage.P3_A, target, True)
        if snapshot.stage is not PhilippineSeedStage.P3_W or not current_kill:
            raise _failure(
                OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
                4,
                "P3-A transition requires contained P3-W",
            )
        return _SeedPlan(PhilippineSeedStage.P3_A, target, False)

    raise _failure(
        OPERATOR_SEED_INTERNAL_FAILED,
        9,
        "Seed command is unsupported",
    )


def _default_evidence_reader(
    paths: RuntimePaths,
    tenant: str,
    snapshot: AppliedOperationalSnapshot,
    assignment_secret: str,
) -> SeedSourceEvidence:
    database = paths.tenant_database_path(tenant)
    try:
        uri = database.resolve(strict=True).as_uri() + "?mode=ro"
    except (OSError, RuntimeError, ValueError):
        raise _failure(
            OPERATOR_SEED_SUBSYSTEM_FAILED,
            8,
            "tenant evidence is unavailable",
        ) from None

    def creator() -> sqlite3.Connection:
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.execute("PRAGMA query_only=ON;")
        return connection

    engine = None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import NullPool

        engine = create_engine("sqlite://", creator=creator, poolclass=NullPool)
        runtime_mapping = dict(snapshot.effective_values)
        runtime_mapping[ASSIGNMENT_SECRET_ENVIRONMENT_KEY] = assignment_secret
        readiness_configuration = (
            load_reservation_rollout_readiness_configuration(runtime_mapping)
        )
        control_configuration = load_reservation_rollout_control_configuration(
            runtime_mapping
        )
        observed_at = datetime.now(timezone.utc)
        with Session(engine) as session:
            readiness = reservation_rollout_readiness(
                session,
                planning_policy=_PLANNING_POLICY,
                configuration=readiness_configuration,
                now=observed_at,
                runtime_mapping=runtime_mapping,
            )
            rollout = reservation_rollout_status(
                session,
                canonical_tenant=tenant,
                planning_policy=_PLANNING_POLICY,
                configuration=control_configuration,
                now=observed_at,
                runtime_mapping=runtime_mapping,
            )
        metric_names = (
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
        return SeedSourceEvidence(
            readiness_state=str(readiness["state"]),
            breaker_tripped=bool(rollout["breakerTripped"]),
            breaker_reason=(
                str(rollout["breakerReason"])
                if rollout["breakerReason"] is not None
                else None
            ),
            metrics={name: rollout[name] for name in metric_names},
        )
    except _SeedFailure:
        raise
    except Exception:
        raise _failure(
            OPERATOR_SEED_SUBSYSTEM_FAILED,
            8,
            "tenant evidence is unavailable",
        ) from None
    finally:
        if engine is not None:
            engine.dispose()


def _require_delivery(
    paths: RuntimePaths,
    tenant: str,
    reader: Callable[[RuntimePaths], str],
) -> None:
    try:
        delivery_root = reader(paths)
        if not delivery_root:
            raise _failure(
                OPERATOR_SEED_DELIVERY_NOT_CONFIGURED,
                4,
                "Delivery Root is not configured",
            )
        derive_tenant_delivery_root(delivery_root, tenant)
    except _SeedFailure:
        raise
    except DeliverySettingsReadError:
        raise _failure(
            OPERATOR_SEED_SUBSYSTEM_FAILED,
            8,
            "Delivery configuration cannot be read safely",
        ) from None
    except DeliveryPathError:
        raise _failure(
            OPERATOR_SEED_DELIVERY_NOT_CONFIGURED,
            4,
            "Delivery Root is invalid",
        ) from None


def _is_finite_metric_number(value: Any) -> bool:
    if type(value) is int:
        return True
    return type(value) is float and math.isfinite(value)


def _cohort_ready(metrics: Mapping[str, Any]) -> bool:
    minimum_rates = {
        "diagnosticRunCoverageRate": 1.0,
        "planningObservationCoverageRate": 1.0,
        "terminalObservationCoverageRate": 1.0,
    }
    maximums = {
        "zeroPlanConflictRate": 0.30,
        "partialPlanRate": 0.20,
        "authorityLossRate": 0.0,
        "terminalPersistFailureRate": 0.0,
        "workerLeaseConfigFailureRate": 0.0,
        "cleanupWarningRate": 0.20,
    }
    try:
        canary_task_count = metrics["canaryTaskCount"]
        if type(canary_task_count) is not int or canary_task_count < 5:
            return False
        return all(
            _is_finite_metric_number(metrics[key])
            and metrics[key] >= threshold
            for key, threshold in minimum_rates.items()
        ) and all(
            _is_finite_metric_number(metrics[key])
            and metrics[key] <= threshold
            for key, threshold in maximums.items()
        )
    except Exception:
        return False


def _require_source_evidence(
    command: str,
    *,
    paths: RuntimePaths,
    tenant: str,
    prestate: _SeedPrestate,
    delivery_reader: Callable[[RuntimePaths], str],
    evidence_reader: Callable[
        [RuntimePaths, str, AppliedOperationalSnapshot, str],
        SeedSourceEvidence,
    ],
) -> None:
    if command not in _EVIDENCE_COMMANDS:
        return
    snapshot = prestate.snapshot
    assignment_secret = prestate.assignment_secret
    if snapshot is None or assignment_secret is None:
        raise OperationalSnapshotError(
            OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE
        )
    if command in _DELIVERY_COMMANDS:
        _require_delivery(paths, tenant, delivery_reader)
    evidence = evidence_reader(paths, tenant, snapshot, assignment_secret)
    if evidence.readiness_state != "READY_FOR_CONTROLLED_CANARY":
        raise _failure(
            OPERATOR_SEED_READINESS_NOT_READY,
            4,
            "Reservation Readiness is not ready",
        )
    if evidence.breaker_tripped:
        raise _failure(
            OPERATOR_SEED_BREAKER_LATCHED,
            4,
            "Reservation rollout breaker is latched",
        )
    if command == "transition-p3a" and not _cohort_ready(evidence.metrics):
        raise _failure(
            OPERATOR_SEED_COHORT_NOT_READY,
            4,
            "P3-A cohort evidence is not ready",
        )


def _verify_backup_for_tenant(
    bundle: str | None,
    tenant: str,
    verifier: Callable[[str], OperatorBackupOutcome],
) -> None:
    if not isinstance(bundle, str):
        raise _failure(
            "OPERATOR_BACKUP_PATH_INVALID",
            3,
            "backup bundle is required",
        )
    outcome = verifier(bundle)
    if outcome.error_code is not None:
        raise _failure(
            outcome.error_code,
            outcome.exit_code,
            "backup verification failed",
        )
    if outcome.data.get("tenant") != tenant:
        raise _failure(
            OPERATOR_SEED_BACKUP_TENANT_MISMATCH,
            4,
            "backup bundle tenant does not match",
        )


def _regular_tenant_database(paths: RuntimePaths, tenant: str) -> Path:
    database = paths.tenant_database_path(tenant)
    try:
        metadata = database.stat()
    except FileNotFoundError:
        raise _failure(
            OPERATOR_SEED_TENANT_NOT_FOUND,
            5,
            "tenant database was not found",
        ) from None
    except OSError:
        raise _failure(
            OPERATOR_SEED_SUBSYSTEM_FAILED,
            8,
            "tenant database is unavailable",
        ) from None
    if not stat.S_ISREG(metadata.st_mode):
        raise _failure(
            OPERATOR_SEED_TENANT_NOT_FOUND,
            5,
            "tenant database was not found",
        )
    return database


def _audit_metadata(
    command: str,
    *,
    approval_ref: str | None,
    reason_code: str | None,
) -> Mapping[str, str]:
    metadata = {"operator_command": f"seed.{command}"}
    if approval_ref is not None:
        metadata["approval_ref"] = approval_ref
    if reason_code is not None:
        metadata["reason_code"] = reason_code
    return metadata


def _outcome_data(
    snapshot: AppliedOperationalSnapshot,
    *,
    restart_required: bool,
) -> Mapping[str, Any]:
    values = snapshot.effective_values
    return {
        "tenant": snapshot.tenant_allowlist[0],
        "generation": snapshot.generation,
        "stage": snapshot.stage.value,
        "balanced_basis_points": int(values[_BALANCED_BPS_KEY]),
        "exact_basis_points": int(values[_EXACT_BPS_KEY]),
        "kill_switch": values[_KILL_SWITCH_KEY] == "true",
        "rollback_window": values[_ROLLBACK_WINDOW_KEY],
        "assignment_secret_status": "PRESENT",
        "restart_required": restart_required,
    }


def execute_seed_transition(
    command: str,
    tenant_id: str,
    generation: str,
    *,
    approval_ref: str | None = None,
    reason_code: str | None = None,
    lease_profile: str | None = None,
    balanced_basis_points: int | None = None,
    rollback_window: str | None = None,
    backup_bundle: str | None = None,
    paths_initializer: Callable[[], RuntimePaths] = _initialize_operator_runtime_paths,
    barrier_factory: Callable[[RuntimePaths], Any] = acquire_runtime_mutation_barrier,
    store_factory: Callable[[RuntimePaths], SecretStore] = _default_store,
    connection_factory: Callable[[Path], sqlite3.Connection] = _default_connection,
    backup_verifier: Callable[[str], OperatorBackupOutcome] = verify_operator_backup,
    delivery_reader: Callable[[RuntimePaths], str] = read_current_delivery_root,
    evidence_reader: Callable[
        [RuntimePaths, str, AppliedOperationalSnapshot, str],
        SeedSourceEvidence,
    ] = _default_evidence_reader,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    secret_factory: Callable[[], str] = lambda: secrets.token_urlsafe(48),
) -> OperatorSeedOutcome:
    """Execute one bounded H4-6 transition under barrier and checked transaction."""
    try:
        identity = _validate_identity(tenant_id)
        validate_operator_seed_generation(generation, identity)
        selected_lease = _parse_lease_profile(lease_profile)
        if command == "kill":
            validate_reason_code(reason_code)  # type: ignore[arg-type]
        else:
            _validate_approval(approval_ref)
        if command == "set-balanced-bps":
            if (
                isinstance(balanced_basis_points, bool)
                or not isinstance(balanced_basis_points, int)
                or not 1000 <= balanced_basis_points <= 4000
            ):
                raise _failure(
                    OPERATOR_SEED_BPS_INVALID,
                    3,
                    "Balanced BPS is invalid",
                )
        if command == "transition-p3a" and rollback_window not in {"7d", "24h"}:
            raise _failure(
                OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
                3,
                "rollback window is invalid",
            )
        if command in _BACKUP_COMMANDS:
            _verify_backup_for_tenant(
                backup_bundle,
                identity.canonical_id,
                backup_verifier,
            )
        if command == "transition-p3a" and rollback_window == "24h":
            raise _failure(
                P3A_24H_ELIGIBILITY_NOT_PROVABLE,
                4,
                "P3-A 24-hour eligibility is not machine-provable",
            )

        paths = paths_initializer()
        with barrier_factory(paths):
            _regular_tenant_database(paths, identity.canonical_id)
            if (
                command != "apply-safe-off"
                and not paths.settings_db_path.is_file()
            ):
                raise _failure(
                    OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
                    4,
                    "applied Seed snapshot is missing",
                )
            store = store_factory(paths)
            with closing(connection_factory(paths.settings_db_path)) as connection:
                holder: dict[str, _SeedPlan] = {}

                def reread(conn: sqlite3.Connection) -> _SeedPrestate:
                    return _read_prestate(conn, store)

                def validate(
                    conn: sqlite3.Connection,
                    prestate: _SeedPrestate,
                ) -> None:
                    del conn
                    plan = _build_plan(
                        command,
                        prestate,
                        tenant=identity.canonical_id,
                        generation=generation,
                        lease_profile=selected_lease,
                        balanced_basis_points=balanced_basis_points,
                    )
                    _require_source_evidence(
                        command,
                        paths=paths,
                        tenant=identity.canonical_id,
                        prestate=prestate,
                        delivery_reader=delivery_reader,
                        evidence_reader=evidence_reader,
                    )
                    holder["plan"] = plan

                with checked_immediate_transaction(
                    connection,
                    reread_prestate=reread,
                    validate_prestate=validate,
                ) as checked:
                    plan = holder["plan"]
                    prestate = checked.prestate
                    if plan.no_write:
                        if prestate.snapshot is None:  # defensive invariant
                            raise OperationalSnapshotError(
                                OPERATIONAL_SNAPSHOT_INVALID
                            )
                        result_snapshot = prestate.snapshot
                    else:
                        _create_app_settings_table(connection)
                        _create_secure_settings_table(connection)
                        assignment_secret = prestate.assignment_secret
                        if assignment_secret is None:
                            if command != "apply-safe-off":
                                raise OperationalSnapshotError(
                                    OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE
                                )
                            assignment_secret = secret_factory()
                            if (
                                not isinstance(assignment_secret, str)
                                or not assignment_secret
                            ):
                                raise OperationalSnapshotError(
                                    OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE
                                )
                            store._set_on_connection(
                                connection,
                                RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
                                assignment_secret,
                            )
                        result_snapshot = build_applied_operational_snapshot(
                            effective_values=plan.target_values,
                            stage=plan.target_stage,
                            applied_at=now(),
                            audit_metadata=_audit_metadata(
                                command,
                                approval_ref=approval_ref,
                                reason_code=reason_code,
                            ),
                            assignment_secret=assignment_secret,
                        )
                        serialized = result_snapshot.canonical_json()
                        parse_applied_operational_snapshot(
                            serialized,
                            assignment_secret=assignment_secret,
                        )
                        _write_snapshot_on_connection(connection, serialized)

        status = (
            _NOOP_STATUSES[command]
            if plan.no_write
            else _ACTUAL_STATUSES[command]
        )
        return OperatorSeedOutcome(
            status,
            (
                f"{status}: tenant={identity.canonical_id} "
                f"generation={generation} restart_required="
                f"{str(not plan.no_write).lower()}"
            ),
            _outcome_data(
                result_snapshot,
                restart_required=not plan.no_write,
            ),
        )
    except _SeedFailure as exc:
        return OperatorSeedOutcome(
            "ERROR",
            exc.message,
            {},
            exc.exit_code,
            exc.error_code,
        )
    except RuntimeMutationBarrierBusy:
        return OperatorSeedOutcome(
            "ERROR",
            "runtime mutation is busy",
            {},
            4,
            OPERATOR_RUNTIME_MUTATION_BUSY,
        )
    except LegacyRuntimeMigrationRequired as exc:
        return OperatorSeedOutcome(
            "ERROR",
            "legacy runtime migration is required",
            {},
            4,
            str(exc),
        )
    except RuntimePathsError:
        return OperatorSeedOutcome(
            "ERROR",
            "runtime storage is unavailable",
            {},
            8,
            OPERATOR_SEED_SUBSYSTEM_FAILED,
        )
    except MutationPrestateMismatch:
        return OperatorSeedOutcome(
            "ERROR",
            "Seed prestate changed",
            {},
            4,
            OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
        )
    except RuntimeMutationBarrierError:
        return OperatorSeedOutcome(
            "ERROR",
            "runtime mutation barrier is unavailable",
            {},
            8,
            OPERATOR_SEED_SUBSYSTEM_FAILED,
        )
    except (MutationTransactionError, sqlite3.Error, OSError):
        return OperatorSeedOutcome(
            "ERROR",
            "Seed storage is unavailable",
            {},
            8,
            OPERATOR_SEED_SUBSYSTEM_FAILED,
        )
    except (OperationalProfileError, SecretStoreError):
        return OperatorSeedOutcome(
            "ERROR",
            "Seed snapshot integrity validation failed",
            {},
            6,
            OPERATOR_SEED_SNAPSHOT_INTEGRITY_FAILED,
        )
    except Exception:
        return OperatorSeedOutcome(
            "ERROR",
            "Seed transition failed",
            {},
            9,
            OPERATOR_SEED_INTERNAL_FAILED,
        )
