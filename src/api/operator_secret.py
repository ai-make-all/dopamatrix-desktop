"""H4-7 atomic contained Assignment Secret rotation."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .operator_backup import OperatorBackupOutcome, verify_operator_backup
from .operator_seed import (
    OPERATOR_RUNTIME_MUTATION_BUSY,
    OPERATOR_SEED_BACKUP_TENANT_MISMATCH,
    OPERATOR_SEED_GENERATION_INVALID,
    OPERATOR_SEED_INTERNAL_FAILED,
    OPERATOR_SEED_SNAPSHOT_INTEGRITY_FAILED,
    OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
    OPERATOR_SEED_SUBSYSTEM_FAILED,
    validate_operator_seed_generation,
)
from .operator_tenant_provision import (
    OPERATOR_APPROVAL_REF_INVALID,
    OPERATOR_TENANT_INVALID,
    ApprovedTenantIdentity,
    validate_approval_ref,
    validate_approved_tenant_identity,
)
from .policy_profiles import (
    OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE,
    OPERATIONAL_SNAPSHOT_INVALID,
    OPERATIONAL_SNAPSHOT_SETTING_KEY,
    AppliedOperationalSnapshot,
    OperationalProfileError,
    OperationalSnapshotError,
    _write_snapshot_on_connection,
    build_applied_operational_snapshot,
    parse_applied_operational_snapshot,
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
    SecretDecryptionFailed,
    SecretEncryptionFailed,
    SecretProtectorUnavailable,
    SecretStore,
    SecretStoreError,
    SecretValueInvalid,
    create_platform_secret_protector,
)


OPERATOR_ASSIGNMENT_SECRET_ROTATION_NO_CHANGE = (
    "OPERATOR_ASSIGNMENT_SECRET_ROTATION_NO_CHANGE"
)

_GENERATION_KEY = "RESERVATION_ROLLOUT_GENERATION"
_KILL_SWITCH_KEY = "RESERVATION_ROLLOUT_KILL_SWITCH"


@dataclass(frozen=True)
class OperatorSecretRotationOutcome:
    status: str
    message: str
    data: Mapping[str, Any]
    exit_code: int = 0
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


@dataclass(frozen=True)
class _RotationPrestate:
    serialized_snapshot: str | None
    snapshot: AppliedOperationalSnapshot | None
    assignment_secret: str | None


class _RotationFailure(Exception):
    def __init__(self, error_code: str, exit_code: int, message: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.exit_code = exit_code
        self.message = message


def _failure(error_code: str, exit_code: int, message: str) -> _RotationFailure:
    return _RotationFailure(error_code, exit_code, message)


def _initialize_operator_runtime_paths() -> RuntimePaths:
    return get_initialized_runtime_paths() or initialize_runtime_paths()


def _default_store(paths: RuntimePaths) -> SecretStore:
    return SecretStore(
        paths.settings_db_path,
        create_platform_secret_protector(),
    )


def _default_connection(database: Path) -> sqlite3.Connection:
    uri = database.resolve(strict=True).as_uri() + "?mode=rw"
    connection = sqlite3.connect(
        uri,
        uri=True,
        timeout=5.0,
    )
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
) -> _RotationPrestate:
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
    return _RotationPrestate(serialized, snapshot, assignment_secret)


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


def _validate_generation(
    generation: str,
    identity: ApprovedTenantIdentity,
) -> str:
    try:
        return validate_operator_seed_generation(generation, identity)
    except Exception as exc:
        if getattr(exc, "error_code", None) == OPERATOR_SEED_GENERATION_INVALID:
            raise _failure(
                OPERATOR_SEED_GENERATION_INVALID,
                3,
                "Seed generation is invalid",
            ) from None
        raise


def _validate_approval(value: str) -> str:
    try:
        return validate_approval_ref(value)
    except Exception as exc:
        if getattr(exc, "error_code", None) == OPERATOR_APPROVAL_REF_INVALID:
            raise _failure(
                OPERATOR_APPROVAL_REF_INVALID,
                3,
                "approval reference is invalid",
            ) from None
        raise


def _verify_backup_for_tenant(
    bundle: str,
    tenant: str,
    verifier: Callable[[str], OperatorBackupOutcome],
) -> None:
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


def _validate_prestate(
    prestate: _RotationPrestate,
    *,
    tenant: str,
    expected_generation: str,
) -> tuple[AppliedOperationalSnapshot, str]:
    snapshot = prestate.snapshot
    old_secret = prestate.assignment_secret
    if snapshot is None:
        raise _failure(
            OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
            4,
            "applied Seed snapshot is missing",
        )
    if old_secret is None:
        raise OperationalSnapshotError(
            OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE
        )
    if (
        snapshot.tenant_allowlist != (tenant,)
        or snapshot.generation != expected_generation
        or snapshot.effective_values.get(_GENERATION_KEY) != expected_generation
        or snapshot.effective_values.get(_KILL_SWITCH_KEY) != "true"
    ):
        raise _failure(
            OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
            4,
            "Assignment Secret rotation prestate does not match",
        )
    return snapshot, old_secret


def rotate_assignment_secret(
    tenant_id: str,
    expected_generation: str,
    new_generation: str,
    backup_bundle: str,
    approval_ref: str,
    *,
    paths_initializer: Callable[[], RuntimePaths] = _initialize_operator_runtime_paths,
    barrier_factory: Callable[[RuntimePaths], Any] = acquire_runtime_mutation_barrier,
    store_factory: Callable[[RuntimePaths], SecretStore] = _default_store,
    connection_factory: Callable[[Path], sqlite3.Connection] = _default_connection,
    backup_verifier: Callable[[str], OperatorBackupOutcome] = verify_operator_backup,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    secret_factory: Callable[[], str] = lambda: secrets.token_urlsafe(48),
) -> OperatorSecretRotationOutcome:
    """Rotate one contained Seed secret and generation in a single transaction."""
    try:
        identity = _validate_identity(tenant_id)
        _validate_generation(expected_generation, identity)
        _validate_generation(new_generation, identity)
        _validate_approval(approval_ref)
        if new_generation == expected_generation:
            raise _failure(
                OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
                4,
                "new generation must differ from expected generation",
            )

        _verify_backup_for_tenant(
            backup_bundle,
            identity.canonical_id,
            backup_verifier,
        )

        paths = paths_initializer()
        with barrier_factory(paths):
            if not paths.settings_db_path.is_file():
                raise _failure(
                    OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
                    4,
                    "applied Seed snapshot is missing",
                )
            store = store_factory(paths)
            with closing(connection_factory(paths.settings_db_path)) as connection:
                holder: dict[str, tuple[AppliedOperationalSnapshot, str]] = {}

                def reread(conn: sqlite3.Connection) -> _RotationPrestate:
                    return _read_prestate(conn, store)

                def validate(
                    conn: sqlite3.Connection,
                    prestate: _RotationPrestate,
                ) -> None:
                    del conn
                    holder["validated"] = _validate_prestate(
                        prestate,
                        tenant=identity.canonical_id,
                        expected_generation=expected_generation,
                    )

                with checked_immediate_transaction(
                    connection,
                    reread_prestate=reread,
                    validate_prestate=validate,
                ):
                    snapshot, old_secret = holder["validated"]
                    new_secret = secret_factory()
                    if not isinstance(new_secret, str) or not new_secret:
                        raise SecretValueInvalid()
                    if new_secret == old_secret:
                        raise _failure(
                            OPERATOR_ASSIGNMENT_SECRET_ROTATION_NO_CHANGE,
                            4,
                            "Assignment Secret rotation produced no change",
                        )

                    store._set_on_connection(
                        connection,
                        RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
                        new_secret,
                    )

                    target_values = dict(snapshot.effective_values)
                    target_values[_GENERATION_KEY] = new_generation
                    result_snapshot = build_applied_operational_snapshot(
                        effective_values=target_values,
                        stage=snapshot.stage,
                        applied_at=now(),
                        audit_metadata={
                            "operator_command": "secret.assignment.rotate",
                            "approval_ref": approval_ref,
                        },
                        assignment_secret=new_secret,
                    )
                    serialized = result_snapshot.canonical_json()
                    parse_applied_operational_snapshot(
                        serialized,
                        assignment_secret=new_secret,
                    )
                    _write_snapshot_on_connection(connection, serialized)

        return OperatorSecretRotationOutcome(
            "ROTATED",
            (
                f"ROTATED: tenant={identity.canonical_id} "
                f"old_generation={expected_generation} "
                f"new_generation={new_generation} kill_switch=true "
                "restart_required=true"
            ),
            {
                "tenant": identity.canonical_id,
                "old_generation": expected_generation,
                "new_generation": new_generation,
                "kill_switch": True,
                "assignment_secret_status": "PRESENT",
                "restart_required": True,
            },
        )
    except _RotationFailure as exc:
        return OperatorSecretRotationOutcome(
            "ERROR",
            exc.message,
            {},
            exc.exit_code,
            exc.error_code,
        )
    except RuntimeMutationBarrierBusy:
        return OperatorSecretRotationOutcome(
            "ERROR",
            "runtime mutation is busy",
            {},
            4,
            OPERATOR_RUNTIME_MUTATION_BUSY,
        )
    except LegacyRuntimeMigrationRequired as exc:
        return OperatorSecretRotationOutcome(
            "ERROR",
            "legacy runtime migration is required",
            {},
            4,
            str(exc),
        )
    except RuntimePathsError:
        return OperatorSecretRotationOutcome(
            "ERROR",
            "runtime storage is unavailable",
            {},
            8,
            OPERATOR_SEED_SUBSYSTEM_FAILED,
        )
    except MutationPrestateMismatch:
        return OperatorSecretRotationOutcome(
            "ERROR",
            "Assignment Secret rotation prestate changed",
            {},
            4,
            OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
        )
    except RuntimeMutationBarrierError:
        return OperatorSecretRotationOutcome(
            "ERROR",
            "runtime mutation barrier is unavailable",
            {},
            8,
            OPERATOR_SEED_SUBSYSTEM_FAILED,
        )
    except (
        SecretProtectorUnavailable,
        SecretEncryptionFailed,
        SecretDecryptionFailed,
    ):
        return OperatorSecretRotationOutcome(
            "ERROR",
            "Assignment Secret storage is unavailable",
            {},
            8,
            OPERATOR_SEED_SUBSYSTEM_FAILED,
        )
    except (MutationTransactionError, sqlite3.Error, OSError):
        return OperatorSecretRotationOutcome(
            "ERROR",
            "Assignment Secret rotation storage is unavailable",
            {},
            8,
            OPERATOR_SEED_SUBSYSTEM_FAILED,
        )
    except (OperationalProfileError, SecretStoreError):
        return OperatorSecretRotationOutcome(
            "ERROR",
            "Assignment Secret rotation integrity validation failed",
            {},
            6,
            OPERATOR_SEED_SNAPSHOT_INTEGRITY_FAILED,
        )
    except Exception:
        return OperatorSecretRotationOutcome(
            "ERROR",
            "Assignment Secret rotation failed",
            {},
            9,
            OPERATOR_SEED_INTERNAL_FAILED,
        )
