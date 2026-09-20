"""Philippine Seed v1 policy and complete applied operational snapshots.

This module changes configuration source, not Reservation parser semantics.
Every effective mapping is validated through the existing Lease, Readiness,
and Rollout loaders before it can be persisted or activated.
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any

from .database import canonical_tenant_id
from .reservation_lease import (
    RESERVATION_HEARTBEAT_INTERVAL_ENV,
    RESERVATION_LEASE_ENVIRONMENT_KEYS,
    RESERVATION_LEASE_TTL_ENV,
    load_reservation_lease_configuration,
)
from .reservation_rollout_control import (
    RESERVATION_ROLLOUT_CONTROL_ENVIRONMENT_KEYS,
    load_reservation_rollout_control_configuration,
)
from .reservation_rollout_readiness import (
    RESERVATION_ROLLOUT_READINESS_ENVIRONMENT_KEYS,
    load_reservation_rollout_readiness_configuration,
)
from .runtime_config import (
    RuntimeConfigProvider,
    StaticOperationalStatus,
)
from .runtime_paths import RuntimePaths
from .secret_store import (
    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
    SecretStatus,
    SecretStore,
    SecretStoreError,
    _create_app_settings_table,
    _create_secure_settings_table,
)


PHILIPPINE_SEED_PROFILE_NAME = "philippine-seed-v1"
PHILIPPINE_SEED_PROFILE_VERSION = "1.0"
OPERATIONAL_SNAPSHOT_SCHEMA_VERSION = 1
OPERATIONAL_SNAPSHOT_SETTING_KEY = "operational_runtime_snapshot_v1"
ASSIGNMENT_SECRET_ENVIRONMENT_KEY = "RESERVATION_ROLLOUT_ASSIGNMENT_SECRET"

OPERATIONAL_SNAPSHOT_MISSING = "OPERATIONAL_SNAPSHOT_MISSING"
OPERATIONAL_SNAPSHOT_INVALID = "OPERATIONAL_SNAPSHOT_INVALID"
OPERATIONAL_SNAPSHOT_SCHEMA_UNSUPPORTED = (
    "OPERATIONAL_SNAPSHOT_SCHEMA_UNSUPPORTED"
)
OPERATIONAL_PROFILE_UNSUPPORTED = "OPERATIONAL_PROFILE_UNSUPPORTED"
OPERATIONAL_PROFILE_VERSION_UNSUPPORTED = (
    "OPERATIONAL_PROFILE_VERSION_UNSUPPORTED"
)
OPERATIONAL_SNAPSHOT_KEYSET_INVALID = "OPERATIONAL_SNAPSHOT_KEYSET_INVALID"
OPERATIONAL_SNAPSHOT_STAGE_MISMATCH = "OPERATIONAL_SNAPSHOT_STAGE_MISMATCH"
OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE = (
    "OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE"
)
OPERATIONAL_PROFILE_POLICY_VIOLATION = "OPERATIONAL_PROFILE_POLICY_VIOLATION"
OPERATIONAL_PROFILE_APPLICATION_FAILED = "OPERATIONAL_PROFILE_APPLICATION_FAILED"

_GENERATION_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")
_SAFE_METADATA_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")
_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "profile_name",
        "profile_version",
        "applied_at_utc",
        "audit_metadata",
        "tenant_allowlist",
        "generation",
        "stage",
        "effective_values",
        "assignment_secret",
    }
)


class PhilippineSeedStage(str, Enum):
    SAFE_OFF = "SAFE_OFF"
    P3_W = "P3_W"
    P3_A = "P3_A"


class OperationalProfileError(RuntimeError):
    """Stable, secret-independent profile/snapshot failure."""


class OperationalSnapshotError(OperationalProfileError):
    pass


class OperationalProfilePolicyError(OperationalProfileError):
    def __init__(self) -> None:
        super().__init__(OPERATIONAL_PROFILE_POLICY_VIOLATION)


class OperationalProfileApplicationError(OperationalProfileError):
    pass


def _source_inventory() -> tuple[frozenset[str], frozenset[str]]:
    lease = frozenset(RESERVATION_LEASE_ENVIRONMENT_KEYS)
    readiness = frozenset(RESERVATION_ROLLOUT_READINESS_ENVIRONMENT_KEYS)
    control = frozenset(RESERVATION_ROLLOUT_CONTROL_ENVIRONMENT_KEYS)
    secret = frozenset({ASSIGNMENT_SECRET_ENVIRONMENT_KEY})
    non_secret = lease | readiness | (control - secret)
    if (
        len(lease) != 2
        or len(readiness) != 13
        or len(control) != 18
        or ASSIGNMENT_SECRET_ENVIRONMENT_KEY not in control
        or len(non_secret) != 32
        or len(lease | readiness | control) != 33
    ):
        raise OperationalProfileError("OPERATIONAL_PROFILE_SOURCE_INVENTORY_INVALID")
    return non_secret, secret


SEED_NON_SECRET_ENVIRONMENT_KEYS, SEED_SECRET_ENVIRONMENT_KEYS = (
    _source_inventory()
)
SEED_RUNTIME_ENVIRONMENT_KEYS = (
    SEED_NON_SECRET_ENVIRONMENT_KEYS | SEED_SECRET_ENVIRONMENT_KEYS
)


_READINESS_VALUES = MappingProxyType(
    {
        "RESERVATION_ROLLOUT_READINESS_WINDOW": "7d",
        "RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS": "10",
        "RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS": "10",
        "RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS": "0",
        "RESERVATION_ROLLOUT_MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE": "1.0",
        "RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE": "1.0",
        "RESERVATION_ROLLOUT_MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE": "1.0",
        "RESERVATION_ROLLOUT_MAXIMUM_ZERO_PLAN_CONFLICT_RATE": "0.30",
        "RESERVATION_ROLLOUT_MAXIMUM_PARTIAL_PLAN_RATE": "0.20",
        "RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE": "0",
        "RESERVATION_ROLLOUT_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE": "0",
        "RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE": "0",
        "RESERVATION_ROLLOUT_MAXIMUM_CLEANUP_WARNING_RATE": "0.10",
    }
)
_ROLLBACK_COMMON = MappingProxyType(
    {
        "RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS": "5",
        "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_DIAGNOSTIC_COVERAGE_RATE": "1.0",
        "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_PLANNING_COVERAGE_RATE": "1.0",
        "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_TERMINAL_COVERAGE_RATE": "1.0",
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE": "0",
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE": "0",
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE": "0",
    }
)
_ROLLBACK_WARMUP = MappingProxyType(
    {
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE": "1.0",
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE": "1.0",
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE": "1.0",
    }
)
_ROLLBACK_ACTIVE = MappingProxyType(
    {
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE": "0.30",
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE": "0.20",
        "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE": "0.20",
    }
)
_APPROVED_LEASES = frozenset({(180, 45), (300, 60)})
_APPROVED_LEASE_VALUE_PAIRS = frozenset(
    (str(ttl), str(heartbeat)) for ttl, heartbeat in _APPROVED_LEASES
)


def _canonical_tenant_exact(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not tenant_id:
        raise OperationalProfilePolicyError()
    canonical = canonical_tenant_id(tenant_id)
    if canonical != tenant_id or canonical == "default":
        raise OperationalProfilePolicyError()
    return canonical


def _validate_generation(generation: str) -> str:
    if (
        not isinstance(generation, str)
        or _GENERATION_PATTERN.fullmatch(generation) is None
    ):
        raise OperationalProfilePolicyError()
    return generation


def materialize_philippine_seed_profile(
    *,
    tenant_id: str,
    generation: str,
    stage: PhilippineSeedStage | str,
    balanced_basis_points: int | None = None,
    lease_profile: tuple[int, int] = (180, 45),
    rollback_window: str = "7d",
    kill_switch: bool | None = None,
) -> Mapping[str, str]:
    """Derive all 32 non-secret values from bounded reviewed concepts."""
    tenant = _canonical_tenant_exact(tenant_id)
    generation = _validate_generation(generation)
    try:
        selected_stage = PhilippineSeedStage(stage)
    except (TypeError, ValueError):
        raise OperationalProfilePolicyError() from None
    if lease_profile not in _APPROVED_LEASES:
        raise OperationalProfilePolicyError()
    ttl, heartbeat = lease_profile

    if selected_stage is PhilippineSeedStage.SAFE_OFF:
        if balanced_basis_points not in (None, 0):
            raise OperationalProfilePolicyError()
        balanced = 0
        killed = True if kill_switch is None else kill_switch
        if killed is not True or rollback_window != "7d":
            raise OperationalProfilePolicyError()
        rollback_thresholds = _ROLLBACK_WARMUP
    else:
        balanced = 3000 if balanced_basis_points is None else balanced_basis_points
        if (
            isinstance(balanced, bool)
            or not isinstance(balanced, int)
            or not 1000 <= balanced <= 4000
        ):
            raise OperationalProfilePolicyError()
        killed = False if kill_switch is None else kill_switch
        if not isinstance(killed, bool):
            raise OperationalProfilePolicyError()
        if selected_stage is PhilippineSeedStage.P3_W:
            if rollback_window != "7d":
                raise OperationalProfilePolicyError()
            rollback_thresholds = _ROLLBACK_WARMUP
        else:
            if rollback_window not in {"7d", "24h"}:
                raise OperationalProfilePolicyError()
            rollback_thresholds = _ROLLBACK_ACTIVE

    values = {
        RESERVATION_LEASE_TTL_ENV: str(ttl),
        RESERVATION_HEARTBEAT_INTERVAL_ENV: str(heartbeat),
        **_READINESS_VALUES,
        "RESERVATION_ROLLOUT_CONTROL_ENABLED": "true",
        "RESERVATION_ROLLOUT_GENERATION": generation,
        "RESERVATION_ROLLOUT_TENANT_ALLOWLIST": tenant,
        "RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS": "0",
        "RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS": str(balanced),
        "RESERVATION_ROLLOUT_KILL_SWITCH": "true" if killed else "false",
        "RESERVATION_ROLLOUT_ROLLBACK_WINDOW": rollback_window,
        **_ROLLBACK_COMMON,
        **rollback_thresholds,
    }
    validate_philippine_seed_effective_values(
        values,
        stage=selected_stage,
        assignment_secret="profile-validation-only",
    )
    return MappingProxyType(values)


def validate_philippine_seed_effective_values(
    values: Mapping[str, str],
    *,
    stage: PhilippineSeedStage | str,
    assignment_secret: str,
) -> None:
    """Apply exact-key, existing-loader, and Philippine policy validation."""
    if set(values) != set(SEED_NON_SECRET_ENVIRONMENT_KEYS) or any(
        not isinstance(value, str) for value in values.values()
    ):
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_KEYSET_INVALID)
    try:
        selected_stage = PhilippineSeedStage(stage)
        lease = load_reservation_lease_configuration(values).require_configured()
        readiness = load_reservation_rollout_readiness_configuration(values)
        control_values = dict(values)
        control_values[ASSIGNMENT_SECRET_ENVIRONMENT_KEY] = assignment_secret
        control = load_reservation_rollout_control_configuration(control_values)
    except OperationalProfileError:
        raise
    except Exception:
        raise OperationalProfilePolicyError() from None
    if readiness is None or control is None:
        raise OperationalProfilePolicyError()

    if (
        (
            values[RESERVATION_LEASE_TTL_ENV],
            values[RESERVATION_HEARTBEAT_INTERVAL_ENV],
        )
        not in _APPROVED_LEASE_VALUE_PAIRS
        or any(values[key] != expected for key, expected in _READINESS_VALUES.items())
        or control.enabled is not True
        or len(control.tenant_allowlist) != 1
        or control.exact_main_visual_canary_basis_points != 0
        or control.minimum_canary_task_count != 5
        or control.minimum_diagnostic_run_coverage_rate != 1.0
        or control.minimum_planning_observation_coverage_rate != 1.0
        or control.minimum_terminal_observation_coverage_rate != 1.0
        or control.maximum_authority_loss_rate != 0.0
        or control.maximum_terminal_persist_failure_rate != 0.0
        or control.maximum_worker_lease_config_failure_rate != 0.0
    ):
        raise OperationalProfilePolicyError()

    balanced = control.exact_main_visual_balanced_canary_basis_points
    warmup = all(values[key] == expected for key, expected in _ROLLBACK_WARMUP.items())
    active = all(values[key] == expected for key, expected in _ROLLBACK_ACTIVE.items())
    if selected_stage is PhilippineSeedStage.SAFE_OFF:
        compatible = (
            balanced == 0
            and control.kill_switch is True
            and control.rollback_evaluation_window == "7d"
            and warmup
        )
    elif selected_stage is PhilippineSeedStage.P3_W:
        compatible = (
            1000 <= balanced <= 4000
            and control.rollback_evaluation_window == "7d"
            and warmup
        )
    else:
        compatible = (
            1000 <= balanced <= 4000
            and control.rollback_evaluation_window in {"7d", "24h"}
            and active
        )
    if not compatible:
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_STAGE_MISMATCH)


def _validate_audit_metadata(metadata: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(metadata, Mapping) or len(metadata) > 8:
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_INVALID)
    normalized: dict[str, str] = {}
    for key, value in metadata.items():
        if (
            not isinstance(key, str)
            or _SAFE_METADATA_KEY.fullmatch(key) is None
            or not isinstance(value, str)
            or len(value) > 256
            or any(ord(character) < 32 for character in value)
        ):
            raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_INVALID)
        normalized[key] = value
    return normalized


def _normalized_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class AppliedOperationalSnapshot:
    applied_at_utc: str
    audit_metadata: Mapping[str, str]
    tenant_allowlist: tuple[str, ...]
    generation: str
    stage: PhilippineSeedStage
    effective_values: Mapping[str, str] = field(repr=False)
    schema_version: int = OPERATIONAL_SNAPSHOT_SCHEMA_VERSION
    profile_name: str = PHILIPPINE_SEED_PROFILE_NAME
    profile_version: str = PHILIPPINE_SEED_PROFILE_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_name": self.profile_name,
            "profile_version": self.profile_version,
            "applied_at_utc": self.applied_at_utc,
            "audit_metadata": dict(self.audit_metadata),
            "tenant_allowlist": list(self.tenant_allowlist),
            "generation": self.generation,
            "stage": self.stage.value,
            "effective_values": dict(self.effective_values),
            "assignment_secret": {
                "key_name": RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
                "status": SecretStatus.PRESENT.value,
            },
        }

    def canonical_json(self) -> str:
        return canonical_snapshot_json(self.to_payload())


def canonical_snapshot_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _reject_duplicate_json_pairs(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_KEYSET_INVALID)
        result[key] = value
    return result


def build_applied_operational_snapshot(
    *,
    effective_values: Mapping[str, str],
    stage: PhilippineSeedStage | str,
    applied_at: datetime,
    audit_metadata: Mapping[str, str] | None = None,
    assignment_secret: str,
) -> AppliedOperationalSnapshot:
    try:
        selected_stage = PhilippineSeedStage(stage)
    except (TypeError, ValueError):
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_STAGE_MISMATCH) from None
    validate_philippine_seed_effective_values(
        effective_values,
        stage=selected_stage,
        assignment_secret=assignment_secret,
    )
    control_values = dict(effective_values)
    control_values[ASSIGNMENT_SECRET_ENVIRONMENT_KEY] = assignment_secret
    control = load_reservation_rollout_control_configuration(control_values)
    if control is None:  # pragma: no cover - guarded by validation above
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_INVALID)
    return AppliedOperationalSnapshot(
        applied_at_utc=_normalized_utc_timestamp(applied_at),
        audit_metadata=MappingProxyType(
            _validate_audit_metadata(audit_metadata or {})
        ),
        tenant_allowlist=tuple(sorted(control.tenant_allowlist)),
        generation=control.rollout_generation,
        stage=selected_stage,
        effective_values=MappingProxyType(dict(effective_values)),
    )


def parse_applied_operational_snapshot(
    serialized: str,
    *,
    assignment_secret: str,
) -> AppliedOperationalSnapshot:
    try:
        payload = json.loads(
            serialized,
            object_pairs_hook=_reject_duplicate_json_pairs,
        )
    except (TypeError, json.JSONDecodeError):
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_INVALID) from None
    if not isinstance(payload, dict) or set(payload) != set(_SNAPSHOT_FIELDS):
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_KEYSET_INVALID)
    if payload.get("schema_version") != OPERATIONAL_SNAPSHOT_SCHEMA_VERSION:
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_SCHEMA_UNSUPPORTED)
    if payload.get("profile_name") != PHILIPPINE_SEED_PROFILE_NAME:
        raise OperationalSnapshotError(OPERATIONAL_PROFILE_UNSUPPORTED)
    if payload.get("profile_version") != PHILIPPINE_SEED_PROFILE_VERSION:
        raise OperationalSnapshotError(OPERATIONAL_PROFILE_VERSION_UNSUPPORTED)
    if not isinstance(payload.get("applied_at_utc"), str):
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_INVALID)
    try:
        timestamp = datetime.fromisoformat(payload["applied_at_utc"])
    except ValueError:
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_INVALID) from None
    if timestamp.tzinfo is None:
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_INVALID)
    metadata = _validate_audit_metadata(payload.get("audit_metadata"))
    tenants = payload.get("tenant_allowlist")
    values = payload.get("effective_values")
    secret_reference = payload.get("assignment_secret")
    if (
        not isinstance(tenants, list)
        or len(tenants) != 1
        or any(not isinstance(tenant, str) for tenant in tenants)
        or not isinstance(values, dict)
        or not isinstance(payload.get("generation"), str)
        or secret_reference
        != {
            "key_name": RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
            "status": SecretStatus.PRESENT.value,
        }
    ):
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_INVALID)
    if not assignment_secret:
        raise OperationalSnapshotError(OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE)
    try:
        stage = PhilippineSeedStage(payload.get("stage"))
    except (TypeError, ValueError):
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_STAGE_MISMATCH) from None
    validate_philippine_seed_effective_values(
        values,
        stage=stage,
        assignment_secret=assignment_secret,
    )
    control_values = dict(values)
    control_values[ASSIGNMENT_SECRET_ENVIRONMENT_KEY] = assignment_secret
    control = load_reservation_rollout_control_configuration(control_values)
    if (
        control is None
        or list(sorted(control.tenant_allowlist)) != tenants
        or control.rollout_generation != payload["generation"]
    ):
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_INVALID)
    snapshot = AppliedOperationalSnapshot(
        applied_at_utc=_normalized_utc_timestamp(timestamp),
        audit_metadata=MappingProxyType(metadata),
        tenant_allowlist=tuple(tenants),
        generation=payload["generation"],
        stage=stage,
        effective_values=MappingProxyType(dict(values)),
    )
    if snapshot.canonical_json() != serialized:
        raise OperationalSnapshotError(OPERATIONAL_SNAPSHOT_INVALID)
    return snapshot


@dataclass(frozen=True)
class ProfileApplicationResult:
    profile_name: str
    profile_version: str
    stage: PhilippineSeedStage
    tenant_allowlist: tuple[str, ...]
    generation: str
    applied_at_utc: str
    assignment_secret_status: SecretStatus
    assignment_secret_created: bool


def _write_snapshot_on_connection(
    conn: sqlite3.Connection,
    serialized: str,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO app_settings (key_name, key_value) VALUES (?, ?);",
        (OPERATIONAL_SNAPSHOT_SETTING_KEY, serialized),
    )


def apply_philippine_seed_profile(
    store: SecretStore,
    *,
    tenant_id: str,
    generation: str,
    stage: PhilippineSeedStage | str,
    balanced_basis_points: int | None = None,
    lease_profile: tuple[int, int] = (180, 45),
    rollback_window: str = "7d",
    kill_switch: bool | None = None,
    audit_metadata: Mapping[str, str] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    secret_factory: Callable[[], str] = lambda: secrets.token_urlsafe(48),
) -> ProfileApplicationResult:
    """Atomically apply one complete profile and create a secret if absent."""
    values = materialize_philippine_seed_profile(
        tenant_id=tenant_id,
        generation=generation,
        stage=stage,
        balanced_basis_points=balanced_basis_points,
        lease_profile=lease_profile,
        rollback_window=rollback_window,
        kill_switch=kill_switch,
    )
    try:
        with closing(store._connect()) as conn, conn:
            _create_app_settings_table(conn)
            _create_secure_settings_table(conn)
            row = store._read_row(conn, RESERVATION_ROLLOUT_ASSIGNMENT_SECRET)
            created = row is None
            if created:
                assignment_secret = secret_factory()
                if not isinstance(assignment_secret, str) or not assignment_secret:
                    raise OperationalProfileApplicationError(
                        OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE
                    )
                store._set_on_connection(
                    conn,
                    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
                    assignment_secret,
                )
            else:
                assignment_secret = store._decrypt_row(row)
                if not assignment_secret:
                    raise OperationalProfileApplicationError(
                        OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE
                    )

            snapshot = build_applied_operational_snapshot(
                effective_values=values,
                stage=stage,
                applied_at=now(),
                audit_metadata=audit_metadata,
                assignment_secret=assignment_secret,
            )
            serialized = snapshot.canonical_json()
            parse_applied_operational_snapshot(
                serialized,
                assignment_secret=assignment_secret,
            )
            _write_snapshot_on_connection(conn, serialized)
        return ProfileApplicationResult(
            profile_name=PHILIPPINE_SEED_PROFILE_NAME,
            profile_version=PHILIPPINE_SEED_PROFILE_VERSION,
            stage=snapshot.stage,
            tenant_allowlist=snapshot.tenant_allowlist,
            generation=snapshot.generation,
            applied_at_utc=snapshot.applied_at_utc,
            assignment_secret_status=SecretStatus.PRESENT,
            assignment_secret_created=created,
        )
    except OperationalProfileError:
        raise
    except SecretStoreError:
        raise OperationalProfileApplicationError(
            OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE
        ) from None
    except (sqlite3.Error, OSError):
        raise OperationalProfileApplicationError(
            OPERATIONAL_PROFILE_APPLICATION_FAILED
        ) from None


def _safe_off_provider(
    paths: RuntimePaths,
    *,
    status: StaticOperationalStatus,
    error_code: str,
) -> RuntimeConfigProvider:
    return RuntimeConfigProvider.create(
        paths=paths,
        static_operational_mapping={},
        static_operational_status=status,
        static_operational_error_code=error_code,
    )


def load_applied_runtime_config_provider(
    paths: RuntimePaths,
    store: SecretStore,
) -> RuntimeConfigProvider:
    """Load one packaged/test process snapshot; never consult environment."""
    try:
        with closing(store._connect()) as conn:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings';"
            ).fetchone()
            if table is None:
                return _safe_off_provider(
                    paths,
                    status=StaticOperationalStatus.SAFE_OFF_MISSING,
                    error_code=OPERATIONAL_SNAPSHOT_MISSING,
                )
            row = conn.execute(
                "SELECT key_value FROM app_settings WHERE key_name = ?;",
                (OPERATIONAL_SNAPSHOT_SETTING_KEY,),
            ).fetchone()
        if row is None:
            return _safe_off_provider(
                paths,
                status=StaticOperationalStatus.SAFE_OFF_MISSING,
                error_code=OPERATIONAL_SNAPSHOT_MISSING,
            )
        try:
            assignment_secret = store.get_secret(
                RESERVATION_ROLLOUT_ASSIGNMENT_SECRET
            )
        except SecretStoreError:
            raise OperationalSnapshotError(
                OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE
            ) from None
        if not assignment_secret:
            raise OperationalSnapshotError(
                OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE
            )
        snapshot = parse_applied_operational_snapshot(
            row[0],
            assignment_secret=assignment_secret,
        )
        runtime_mapping = dict(snapshot.effective_values)
        runtime_mapping[ASSIGNMENT_SECRET_ENVIRONMENT_KEY] = assignment_secret
        return RuntimeConfigProvider.create(
            paths=paths,
            static_operational_mapping=runtime_mapping,
            static_operational_status=StaticOperationalStatus.ACTIVE,
        )
    except OperationalProfileError as exc:
        return _safe_off_provider(
            paths,
            status=StaticOperationalStatus.SAFE_OFF_INVALID,
            error_code=str(exc),
        )
    except (SecretStoreError, sqlite3.Error, OSError, TypeError):
        return _safe_off_provider(
            paths,
            status=StaticOperationalStatus.SAFE_OFF_INVALID,
            error_code=OPERATIONAL_SNAPSHOT_INVALID,
        )
