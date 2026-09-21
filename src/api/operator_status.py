"""Strictly non-mutating H4-2 operator status projections."""

from __future__ import annotations

import re
import sqlite3
import stat
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping

from src.version import APPLICATION_VERSION

from .database import canonical_tenant_id
from .policy_profiles import (
    OPERATIONAL_SNAPSHOT_SETTING_KEY,
    OperationalProfileError,
    parse_applied_operational_snapshot,
)
from .runtime_paths import RuntimePaths, resolve_runtime_paths
from .secret_store import (
    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
    SecretStore,
    SecretStoreError,
    SecretValueCorrupt,
    create_platform_secret_protector,
)


OPERATOR_TENANT_INVALID = "OPERATOR_TENANT_INVALID"
OPERATOR_TENANT_NOT_FOUND = "OPERATOR_TENANT_NOT_FOUND"
OPERATOR_SNAPSHOT_INTEGRITY_FAILED = "OPERATOR_SNAPSHOT_INTEGRITY_FAILED"
OPERATOR_STATUS_INTEGRITY_FAILED = "OPERATOR_STATUS_INTEGRITY_FAILED"
OPERATOR_STATUS_SUBSYSTEM_FAILED = "OPERATOR_STATUS_SUBSYSTEM_FAILED"
OPERATOR_ASSIGNMENT_SECRET_VERIFICATION_FAILED = (
    "OPERATOR_ASSIGNMENT_SECRET_VERIFICATION_FAILED"
)
OPERATOR_STATUS_INTERNAL_FAILED = "OPERATOR_STATUS_INTERNAL_FAILED"

_PRODUCTION_TENANT_PATTERN = re.compile(
    r"^(?P<country>[a-z]{2})-(?P<vertical>[a-z0-9]{3,5})-(?P<sequence>[0-9]{4})$"
)
_RESERVED_VERTICALS = frozenset({"test", "dev", "demo", "v15"})
_SQLITE_INTEGRITY_CODES = frozenset(
    code
    for code in (
        getattr(sqlite3, "SQLITE_CORRUPT", None),
        getattr(sqlite3, "SQLITE_NOTADB", None),
    )
    if code is not None
)


@dataclass(frozen=True)
class OperatorStatusOutcome:
    status: str
    message: str
    data: Mapping[str, Any]
    exit_code: int = 0
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


class _StatusFailure(Exception):
    def __init__(self, *, error_code: str, exit_code: int, message: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.exit_code = exit_code
        self.message = message


@dataclass(frozen=True)
class _SQLiteFileObservation:
    size: int
    modified_ns: int
    device: int
    inode: int


def _success(status: str, data: Mapping[str, Any]) -> OperatorStatusOutcome:
    return OperatorStatusOutcome(
        status=status,
        message=f"STATUS: {status}",
        data=data,
    )


def _failure(*, error_code: str, exit_code: int, message: str) -> _StatusFailure:
    return _StatusFailure(
        error_code=error_code,
        exit_code=exit_code,
        message=message,
    )


def _regular_file_state(path: Path) -> str:
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return "ABSENT"
    except OSError:
        raise _failure(
            error_code=OPERATOR_STATUS_SUBSYSTEM_FAILED,
            exit_code=8,
            message="status storage is unavailable",
        ) from None
    if not stat.S_ISREG(metadata.st_mode):
        raise _failure(
            error_code=OPERATOR_STATUS_SUBSYSTEM_FAILED,
            exit_code=8,
            message="status storage is unavailable",
        )
    return "PRESENT"


def _directory_state(path: Path) -> str:
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return "ABSENT"
    except OSError:
        raise _failure(
            error_code=OPERATOR_STATUS_SUBSYSTEM_FAILED,
            exit_code=8,
            message="runtime root is unavailable",
        ) from None
    if not stat.S_ISDIR(metadata.st_mode):
        raise _failure(
            error_code=OPERATOR_STATUS_SUBSYSTEM_FAILED,
            exit_code=8,
            message="runtime root is unavailable",
        )
    return "PRESENT"


def _observe_sqlite_file(path: Path, *, required: bool) -> _SQLiteFileObservation | None:
    try:
        metadata = path.stat()
    except FileNotFoundError:
        if required:
            raise _failure(
                error_code=OPERATOR_STATUS_SUBSYSTEM_FAILED,
                exit_code=8,
                message="status database is unavailable",
            ) from None
        return None
    except OSError:
        raise _failure(
            error_code=OPERATOR_STATUS_SUBSYSTEM_FAILED,
            exit_code=8,
            message="status database is unavailable",
        ) from None
    if not stat.S_ISREG(metadata.st_mode):
        raise _failure(
            error_code=OPERATOR_STATUS_SUBSYSTEM_FAILED,
            exit_code=8,
            message="status database is unavailable",
        )
    return _SQLiteFileObservation(
        size=metadata.st_size,
        modified_ns=metadata.st_mtime_ns,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


def _sqlite_sidecar_paths(path: Path) -> tuple[Path, Path, Path]:
    return (
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    )


def _require_sidecar_free_sqlite(path: Path) -> _SQLiteFileObservation:
    main = _observe_sqlite_file(path, required=True)
    assert main is not None
    wal_path, shm_path, journal_path = _sqlite_sidecar_paths(path)
    wal = _observe_sqlite_file(wal_path, required=False)
    shm = _observe_sqlite_file(shm_path, required=False)
    journal = _observe_sqlite_file(journal_path, required=False)
    if journal is not None or (wal is None) != (shm is None):
        raise _failure(
            error_code=OPERATOR_STATUS_INTEGRITY_FAILED,
            exit_code=6,
            message="status database sidecar state is incomplete",
        )
    if wal is not None and shm is not None:
        raise _failure(
            error_code=OPERATOR_STATUS_SUBSYSTEM_FAILED,
            exit_code=8,
            message="active WAL state cannot be observed without mutation",
        )
    return main


def _verify_sidecar_free_sqlite(
    path: Path,
    expected_main: _SQLiteFileObservation,
) -> None:
    current_main = _observe_sqlite_file(path, required=True)
    assert current_main is not None
    wal_path, shm_path, journal_path = _sqlite_sidecar_paths(path)
    if (
        current_main != expected_main
        or _observe_sqlite_file(wal_path, required=False) is not None
        or _observe_sqlite_file(shm_path, required=False) is not None
        or _observe_sqlite_file(journal_path, required=False) is not None
    ):
        raise _failure(
            error_code=OPERATOR_STATUS_SUBSYSTEM_FAILED,
            exit_code=8,
            message="status database changed during observation",
        )


@contextmanager
def _readonly_sqlite(path: Path) -> Iterator[sqlite3.Connection]:
    """Observe a stable, sidecar-free SQLite file without filesystem mutation."""
    before = _require_sidecar_free_sqlite(path)
    try:
        uri = path.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON;")
    except (OSError, sqlite3.Error) as exc:
        _raise_sqlite_failure(exc)
    try:
        with closing(connection):
            yield connection
    except sqlite3.Error as exc:
        _raise_sqlite_failure(exc)
    finally:
        _verify_sidecar_free_sqlite(path, before)


def _raise_sqlite_failure(exc: BaseException) -> None:
    code = getattr(exc, "sqlite_errorcode", None)
    if code in _SQLITE_INTEGRITY_CODES:
        raise _failure(
            error_code=OPERATOR_STATUS_INTEGRITY_FAILED,
            exit_code=6,
            message="status database integrity verification failed",
        ) from None
    raise _failure(
        error_code=OPERATOR_STATUS_SUBSYSTEM_FAILED,
        exit_code=8,
        message="status database is unavailable",
    ) from None


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;",
        (table_name,),
    ).fetchone()
    return row is not None


def _validate_tenant(tenant_id: str) -> str:
    if not isinstance(tenant_id, str):
        raise _failure(
            error_code=OPERATOR_TENANT_INVALID,
            exit_code=3,
            message="tenant identity is invalid",
        )
    match = _PRODUCTION_TENANT_PATTERN.fullmatch(tenant_id)
    if (
        match is None
        or match.group("vertical") in _RESERVED_VERTICALS
        or not 1 <= int(match.group("sequence")) <= 9999
        or canonical_tenant_id(tenant_id) != tenant_id
    ):
        raise _failure(
            error_code=OPERATOR_TENANT_INVALID,
            exit_code=3,
            message="tenant identity is invalid",
        )
    return tenant_id


def _read_assignment_secret(
    connection: sqlite3.Connection,
    *,
    db_path: Path,
    protector: Any,
) -> str | None:
    if not _table_exists(connection, "secure_settings"):
        return None
    row = connection.execute(
        "SELECT encryption_scheme, ciphertext FROM secure_settings "
        "WHERE key_name = ?;",
        (RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,),
    ).fetchone()
    if row is None:
        return None
    try:
        secret = SecretStore(db_path, protector)._decrypt_row(row)
        if not secret:
            raise SecretValueCorrupt()
        return secret
    except SecretStoreError:
        raise _failure(
            error_code=OPERATOR_ASSIGNMENT_SECRET_VERIFICATION_FAILED,
            exit_code=8,
            message="Assignment Secret verification failed",
        ) from None


def _snapshot_projection(
    connection: sqlite3.Connection,
    *,
    paths: RuntimePaths,
    protector: Any,
) -> dict[str, Any] | None:
    if not _table_exists(connection, "app_settings"):
        return None
    row = connection.execute(
        "SELECT key_value FROM app_settings WHERE key_name = ?;",
        (OPERATIONAL_SNAPSHOT_SETTING_KEY,),
    ).fetchone()
    if row is None:
        return None
    assignment_secret = _read_assignment_secret(
        connection,
        db_path=paths.settings_db_path,
        protector=protector,
    )
    if assignment_secret is None:
        raise _failure(
            error_code=OPERATOR_SNAPSHOT_INTEGRITY_FAILED,
            exit_code=6,
            message="applied operational snapshot verification failed",
        )
    try:
        snapshot = parse_applied_operational_snapshot(
            row["key_value"],
            assignment_secret=assignment_secret,
        )
    except OperationalProfileError:
        raise _failure(
            error_code=OPERATOR_SNAPSHOT_INTEGRITY_FAILED,
            exit_code=6,
            message="applied operational snapshot verification failed",
        ) from None
    values = snapshot.effective_values
    ttl = values["RESERVATION_LEASE_TTL_SECONDS"]
    heartbeat = values["RESERVATION_HEARTBEAT_INTERVAL_SECONDS"]
    return {
        "snapshot_status": "ACTIVE",
        "profile_name": snapshot.profile_name,
        "profile_version": snapshot.profile_version,
        "stage": snapshot.stage.value,
        "tenant": snapshot.tenant_allowlist[0],
        "generation": snapshot.generation,
        "balanced_basis_points": int(
            values["RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS"]
        ),
        "exact_basis_points": int(
            values["RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS"]
        ),
        "kill_switch": values["RESERVATION_ROLLOUT_KILL_SWITCH"] == "true",
        "lease_profile": f"{ttl}-{heartbeat}",
        "rollback_window": values["RESERVATION_ROLLOUT_ROLLBACK_WINDOW"],
        "assignment_secret_status": "PRESENT",
    }


def _config_status(paths: RuntimePaths, protector: Any) -> OperatorStatusOutcome:
    root_state = _directory_state(paths.runtime_root)
    if _regular_file_state(paths.settings_db_path) == "ABSENT":
        return _success(
            "NOT_INITIALIZED",
            {
                "application_version": APPLICATION_VERSION,
                "runtime_mode": paths.mode.value,
                "runtime_root_state": root_state,
                "global_database": "ABSENT",
                "snapshot_status": "NOT_INITIALIZED",
            },
        )
    with _readonly_sqlite(paths.settings_db_path) as connection:
        snapshot = _snapshot_projection(
            connection,
            paths=paths,
            protector=protector,
        )
    if snapshot is None:
        return _success(
            "SAFE_OFF_MISSING",
            {
                "application_version": APPLICATION_VERSION,
                "runtime_mode": paths.mode.value,
                "runtime_root_state": root_state,
                "global_database": "PRESENT",
                "snapshot_status": "SAFE_OFF_MISSING",
            },
        )
    return _success(
        "ACTIVE",
        {
            "application_version": APPLICATION_VERSION,
            "runtime_mode": paths.mode.value,
            "runtime_root_state": root_state,
            "global_database": "PRESENT",
            **snapshot,
        },
    )


def _secret_status(paths: RuntimePaths, protector: Any) -> OperatorStatusOutcome:
    if _regular_file_state(paths.settings_db_path) == "ABSENT":
        return _success("ABSENT", {"assignment_secret_status": "ABSENT"})
    with _readonly_sqlite(paths.settings_db_path) as connection:
        secret = _read_assignment_secret(
            connection,
            db_path=paths.settings_db_path,
            protector=protector,
        )
    state = "PRESENT" if secret is not None else "ABSENT"
    return _success(state, {"assignment_secret_status": state})


def _verify_tenant_database(path: Path) -> None:
    with _readonly_sqlite(path) as connection:
        result = connection.execute("PRAGMA quick_check(1);").fetchone()
        if result is None or result[0] != "ok":
            raise _failure(
                error_code=OPERATOR_STATUS_INTEGRITY_FAILED,
                exit_code=6,
                message="tenant database integrity verification failed",
            )


def _seed_status(
    paths: RuntimePaths,
    protector: Any,
    tenant_id: str,
) -> OperatorStatusOutcome:
    tenant = _validate_tenant(tenant_id)
    tenant_db = paths.tenant_database_path(tenant)
    if _regular_file_state(tenant_db) == "ABSENT":
        raise _failure(
            error_code=OPERATOR_TENANT_NOT_FOUND,
            exit_code=5,
            message="tenant database was not found",
        )
    _verify_tenant_database(tenant_db)
    if _regular_file_state(paths.settings_db_path) == "ABSENT":
        return _success(
            "SAFE_OFF_MISSING",
            {"tenant": tenant, "snapshot_status": "SAFE_OFF_MISSING"},
        )
    with _readonly_sqlite(paths.settings_db_path) as connection:
        snapshot = _snapshot_projection(
            connection,
            paths=paths,
            protector=protector,
        )
    if snapshot is None or snapshot["tenant"] != tenant:
        return _success(
            "SAFE_OFF_MISSING",
            {"tenant": tenant, "snapshot_status": "SAFE_OFF_MISSING"},
        )
    return _success("ACTIVE", snapshot)


def observe_operator_status(
    command: tuple[str, ...],
    *,
    tenant_id: str | None = None,
    paths: RuntimePaths | None = None,
    protector: Any | None = None,
) -> OperatorStatusOutcome:
    """Observe one H4-2 status command without initializing runtime state."""
    try:
        selected_paths = paths if paths is not None else resolve_runtime_paths()
        selected_protector = (
            protector if protector is not None else create_platform_secret_protector()
        )
        if command == ("config", "status"):
            return _config_status(selected_paths, selected_protector)
        if command == ("secret", "assignment", "status"):
            return _secret_status(selected_paths, selected_protector)
        if command == ("seed", "status") and tenant_id is not None:
            return _seed_status(selected_paths, selected_protector, tenant_id)
        raise _failure(
            error_code=OPERATOR_STATUS_INTERNAL_FAILED,
            exit_code=9,
            message="status command dispatch failed",
        )
    except _StatusFailure as exc:
        return OperatorStatusOutcome(
            status="ERROR",
            message=exc.message,
            data={},
            exit_code=exc.exit_code,
            error_code=exc.error_code,
        )
    except Exception:
        return OperatorStatusOutcome(
            status="ERROR",
            message="status command failed",
            data={},
            exit_code=9,
            error_code=OPERATOR_STATUS_INTERNAL_FAILED,
        )
