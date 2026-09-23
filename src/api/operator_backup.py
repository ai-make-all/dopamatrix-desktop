"""H4-5 RuntimePaths-bound operator backup create/verify adapter."""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .delivery_output import DeliverySettingsReadError, read_current_delivery_root
from .operator_tenant_provision import (
    OPERATOR_TENANT_INVALID,
    ApprovedTenantIdentity,
    validate_approved_tenant_identity,
)
from .runtime_paths import (
    LegacyRuntimeMigrationRequired,
    RuntimePaths,
    RuntimePathsError,
    get_initialized_runtime_paths,
    resolve_runtime_paths,
)


OPERATOR_BACKUP_PATH_INVALID = "OPERATOR_BACKUP_PATH_INVALID"
OPERATOR_BACKUP_DESTINATION_PROTECTED = "OPERATOR_BACKUP_DESTINATION_PROTECTED"
OPERATOR_BACKUP_SOURCE_NOT_FOUND = "OPERATOR_BACKUP_SOURCE_NOT_FOUND"
OPERATOR_BACKUP_BUNDLE_NOT_FOUND = "OPERATOR_BACKUP_BUNDLE_NOT_FOUND"
OPERATOR_BACKUP_SUBSYSTEM_FAILED = "OPERATOR_BACKUP_SUBSYSTEM_FAILED"
OPERATOR_BACKUP_INTERNAL_FAILED = "OPERATOR_BACKUP_INTERNAL_FAILED"

_CORE_ERROR_EXITS = MappingProxyType(
    {
        "TENANT_DATABASE_NOT_FOUND": 5,
        "BACKUP_DESTINATION_ALREADY_EXISTS": 4,
        "BACKUP_PATH_SAFETY_VIOLATION": 6,
        "INCOMPLETE_BACKUP": 6,
        "BACKUP_INTEGRITY_INVALID": 6,
        "BACKUP_MANIFEST_INVALID": 6,
        "BACKUP_RESTORE_FAILED": 6,
    }
)
_WINDOWS_RESERVED_SEGMENTS = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)


@dataclass(frozen=True)
class OperatorBackupOutcome:
    status: str
    message: str
    data: Mapping[str, Any]
    exit_code: int = 0
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


class _OperatorBackupFailure(Exception):
    def __init__(self, error_code: str, exit_code: int, message: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.exit_code = exit_code
        self.message = message


def _failure(error_code: str, exit_code: int, message: str) -> _OperatorBackupFailure:
    return _OperatorBackupFailure(error_code, exit_code, message)


def _validate_tenant(raw: str) -> ApprovedTenantIdentity:
    try:
        return validate_approved_tenant_identity(raw)
    except Exception as exc:
        if getattr(exc, "error_code", None) == OPERATOR_TENANT_INVALID:
            raise _failure(
                OPERATOR_TENANT_INVALID,
                3,
                "tenant identity is not approved",
            ) from None
        raise


def _validate_windows_path_text(raw: str) -> None:
    if os.name != "nt":
        return
    windows_path = PureWindowsPath(raw)
    if windows_path.drive and not windows_path.is_absolute():
        raise _failure(OPERATOR_BACKUP_PATH_INVALID, 3, "backup path is invalid")
    for segment in windows_path.parts:
        if segment == windows_path.anchor:
            continue
        if (
            not segment
            or segment.endswith((" ", "."))
            or any(character in segment for character in '<>:"|?*')
            or segment.split(".", 1)[0].upper() in _WINDOWS_RESERVED_SEGMENTS
        ):
            raise _failure(OPERATOR_BACKUP_PATH_INVALID, 3, "backup path is invalid")


def _absolute_lexical_path(raw: str) -> Path:
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise _failure(OPERATOR_BACKUP_PATH_INVALID, 3, "backup path is invalid")
    _validate_windows_path_text(raw)
    try:
        lexical = Path(raw)
        if not lexical.is_absolute():
            raise _failure(OPERATOR_BACKUP_PATH_INVALID, 3, "backup path must be absolute")
        return lexical
    except _OperatorBackupFailure:
        raise
    except (OSError, RuntimeError, ValueError):
        raise _failure(OPERATOR_BACKUP_PATH_INVALID, 3, "backup path is invalid") from None


def _absolute_physical_path(raw: str) -> Path:
    try:
        return _absolute_lexical_path(raw).resolve(strict=False)
    except _OperatorBackupFailure:
        raise
    except (OSError, RuntimeError, ValueError):
        raise _failure(OPERATOR_BACKUP_PATH_INVALID, 3, "backup path is invalid") from None


def _lexists(path: Path) -> bool:
    try:
        return os.path.lexists(path)
    except OSError:
        raise _failure(
            OPERATOR_BACKUP_SUBSYSTEM_FAILED,
            8,
            "backup storage is unavailable",
        ) from None


def _require_usable_existing_prefix(destination: Path) -> None:
    current = destination.parent
    while not _lexists(current):
        parent = current.parent
        if parent == current:
            raise _failure(
                OPERATOR_BACKUP_SUBSYSTEM_FAILED,
                8,
                "backup destination parent is unavailable",
            )
        current = parent
    try:
        metadata = current.stat()
    except OSError:
        raise _failure(
            OPERATOR_BACKUP_SUBSYSTEM_FAILED,
            8,
            "backup destination parent is unavailable",
        ) from None
    if not stat.S_ISDIR(metadata.st_mode):
        raise _failure(
            OPERATOR_BACKUP_SUBSYSTEM_FAILED,
            8,
            "backup destination parent is unavailable",
        )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _paths_overlap(first: Path, second: Path) -> bool:
    return _is_within(first, second) or _is_within(second, first)


def _resolve_operator_paths() -> RuntimePaths:
    return get_initialized_runtime_paths() or resolve_runtime_paths()


def _regular_source_database(paths: RuntimePaths, tenant: str) -> Path:
    database = paths.tenant_database_path(tenant)
    try:
        metadata = database.stat()
    except FileNotFoundError:
        raise _failure(
            OPERATOR_BACKUP_SOURCE_NOT_FOUND,
            5,
            "tenant database was not found",
        ) from None
    except OSError:
        raise _failure(
            OPERATOR_BACKUP_SUBSYSTEM_FAILED,
            8,
            "tenant database is unavailable",
        ) from None
    if not stat.S_ISREG(metadata.st_mode):
        raise _failure(
            OPERATOR_BACKUP_SOURCE_NOT_FOUND,
            5,
            "tenant database was not found",
        )
    return database


def _preflight_destination(
    raw: str,
    *,
    paths: RuntimePaths,
    delivery_root: str,
) -> Path:
    lexical_destination = _absolute_lexical_path(raw)
    if _lexists(lexical_destination):
        raise _failure(
            "BACKUP_DESTINATION_ALREADY_EXISTS",
            4,
            "backup destination already exists",
        )
    try:
        destination = lexical_destination.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        raise _failure(OPERATOR_BACKUP_PATH_INVALID, 3, "backup path is invalid") from None
    if _lexists(destination):
        raise _failure(
            "BACKUP_DESTINATION_ALREADY_EXISTS",
            4,
            "backup destination already exists",
        )
    _require_usable_existing_prefix(destination)

    runtime_root = paths.runtime_root.resolve(strict=False)
    if _paths_overlap(destination, runtime_root):
        raise _failure(
            OPERATOR_BACKUP_DESTINATION_PROTECTED,
            3,
            "backup destination overlaps protected runtime storage",
        )
    if delivery_root:
        delivery = Path(delivery_root).resolve(strict=False)
        if _paths_overlap(destination, delivery):
            raise _failure(
                OPERATOR_BACKUP_DESTINATION_PROTECTED,
                3,
                "backup destination overlaps protected Delivery storage",
            )
    return destination


def _create_backup_core(*, tenant: str, destination: Path, runtime_root: Path):
    from .backup_restore import create_backup_bundle

    return create_backup_bundle(
        tenant_id=tenant,
        destination=destination,
        project_root=runtime_root,
    )


def _verify_backup_core(bundle: Path) -> dict[str, Any]:
    from .backup_restore import verify_backup_bundle

    return verify_backup_bundle(bundle)


def _core_failure(exc: BaseException) -> OperatorBackupOutcome | None:
    error_code = getattr(exc, "code", None)
    exit_code = _CORE_ERROR_EXITS.get(error_code)
    if exit_code is None:
        return None
    messages = {
        4: "backup destination already exists",
        5: "tenant database was not found",
        6: "backup integrity verification failed",
    }
    return OperatorBackupOutcome(
        "ERROR",
        messages[exit_code],
        {},
        exit_code,
        str(error_code),
    )


def create_operator_backup(
    tenant_id: str,
    destination: str,
    *,
    paths_resolver: Callable[[], RuntimePaths] = _resolve_operator_paths,
    delivery_root_reader: Callable[[RuntimePaths], str] = read_current_delivery_root,
    backup_creator: Callable[..., Any] = _create_backup_core,
) -> OperatorBackupOutcome:
    """Create one tenant backup with explicit RuntimePaths source authority."""
    try:
        identity = _validate_tenant(tenant_id)
        _absolute_lexical_path(destination)
        paths = paths_resolver()
        _regular_source_database(paths, identity.canonical_id)
        try:
            delivery_root = delivery_root_reader(paths)
        except DeliverySettingsReadError:
            raise _failure(
                OPERATOR_BACKUP_SUBSYSTEM_FAILED,
                8,
                "Delivery configuration cannot be read safely",
            ) from None
        final_destination = _preflight_destination(
            destination,
            paths=paths,
            delivery_root=delivery_root,
        )
        result = backup_creator(
            tenant=identity.canonical_id,
            destination=final_destination,
            runtime_root=paths.runtime_root,
        )
    except _OperatorBackupFailure as exc:
        return OperatorBackupOutcome(
            "ERROR", exc.message, {}, exc.exit_code, exc.error_code
        )
    except LegacyRuntimeMigrationRequired as exc:
        return OperatorBackupOutcome(
            "ERROR",
            "legacy runtime migration is required",
            {},
            4,
            str(exc),
        )
    except RuntimePathsError:
        return OperatorBackupOutcome(
            "ERROR",
            "backup runtime storage is unavailable",
            {},
            8,
            OPERATOR_BACKUP_SUBSYSTEM_FAILED,
        )
    except (OSError, sqlite3.Error):
        return OperatorBackupOutcome(
            "ERROR",
            "backup subsystem failed",
            {},
            8,
            OPERATOR_BACKUP_SUBSYSTEM_FAILED,
        )
    except Exception as exc:
        mapped = _core_failure(exc)
        if mapped is not None:
            return mapped
        return OperatorBackupOutcome(
            "ERROR",
            "backup operation failed",
            {},
            9,
            OPERATOR_BACKUP_INTERNAL_FAILED,
        )

    return OperatorBackupOutcome(
        "VALID",
        (
            f"BACKUP CREATED: tenant={identity.canonical_id} "
            f"bundle={result.bundle_path} asset_count={int(result.asset_count)}"
        ),
        {
            "tenant": identity.canonical_id,
            "bundle": str(result.bundle_path),
            "asset_count": int(result.asset_count),
            "counts": dict(result.counts),
        },
    )


def verify_operator_backup(
    bundle: str,
    *,
    backup_verifier: Callable[[Path], Mapping[str, Any]] = _verify_backup_core,
) -> OperatorBackupOutcome:
    """Verify one absolute bundle without resolving or initializing RuntimePaths."""
    try:
        bundle_root = _absolute_physical_path(bundle)
        if not _lexists(bundle_root):
            raise _failure(
                OPERATOR_BACKUP_BUNDLE_NOT_FOUND,
                5,
                "backup bundle was not found",
            )
        manifest = backup_verifier(bundle_root)
    except _OperatorBackupFailure as exc:
        return OperatorBackupOutcome(
            "ERROR", exc.message, {}, exc.exit_code, exc.error_code
        )
    except (OSError, sqlite3.Error):
        return OperatorBackupOutcome(
            "ERROR",
            "backup verification subsystem failed",
            {},
            8,
            OPERATOR_BACKUP_SUBSYSTEM_FAILED,
        )
    except Exception as exc:
        mapped = _core_failure(exc)
        if mapped is not None:
            return mapped
        return OperatorBackupOutcome(
            "ERROR",
            "backup verification failed",
            {},
            9,
            OPERATOR_BACKUP_INTERNAL_FAILED,
        )

    tenant = str(manifest["canonical_tenant_id"])
    return OperatorBackupOutcome(
        "VALID",
        (
            f"BACKUP VERIFIED: tenant={tenant} "
            f"bundle={bundle_root} asset_count={int(manifest['asset_count'])}"
        ),
        {
            "tenant": tenant,
            "bundle": str(bundle_root),
            "asset_count": int(manifest["asset_count"]),
            "counts": dict(manifest["counts"]),
        },
    )
