"""H4-4 three-ID-only tenant provisioning service.

The public request is validated before mutable runtime paths are initialized.
All authoritative collision checks and the one-shot initializer run while the
H4-3 runtime mutation barrier is held.  Backup destinations remain H4-5-owned;
this module never resolves or creates a backup root.
"""

from __future__ import annotations

import re
import sqlite3
import stat
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .runtime_mutation import (
    RuntimeMutationBarrierBusy,
    RuntimeMutationBarrierError,
    acquire_runtime_mutation_barrier,
)
from .runtime_paths import (
    RuntimePaths,
    get_initialized_runtime_paths,
    initialize_runtime_paths,
)


OPERATOR_TENANT_INVALID = "OPERATOR_TENANT_INVALID"
OPERATOR_APPROVAL_REF_INVALID = "OPERATOR_APPROVAL_REF_INVALID"
OPERATOR_TENANT_COLLISION = "OPERATOR_TENANT_COLLISION"
OPERATOR_DELIVERY_NAMESPACE_COLLISION = "OPERATOR_DELIVERY_NAMESPACE_COLLISION"
OPERATOR_RUNTIME_MUTATION_BUSY = "OPERATOR_RUNTIME_MUTATION_BUSY"
OPERATOR_TENANT_PROVISION_SUBSYSTEM_FAILED = (
    "OPERATOR_TENANT_PROVISION_SUBSYSTEM_FAILED"
)
OPERATOR_TENANT_PROVISION_INTEGRITY_FAILED = (
    "OPERATOR_TENANT_PROVISION_INTEGRITY_FAILED"
)
OPERATOR_TENANT_PARTIAL_PROVISIONING_REVIEW_REQUIRED = (
    "OPERATOR_TENANT_PARTIAL_PROVISIONING_REVIEW_REQUIRED"
)
OPERATOR_TENANT_PROVISION_INTERNAL_FAILED = (
    "OPERATOR_TENANT_PROVISION_INTERNAL_FAILED"
)

BACKUP_NAMESPACE_NOT_CONFIGURED = "NOT_CONFIGURED"
DELIVERY_NAMESPACE_NOT_CONFIGURED = "NOT_CONFIGURED"

_TENANT_PATTERN = re.compile(
    r"^(?P<country>[a-z]{2})-(?P<vertical>[a-z0-9]{3,5})-(?P<sequence>[0-9]{4})$",
    re.ASCII,
)
_APPROVED_TENANTS = MappingProxyType(
    {
        "ph-elv-0001": "elv0001",
        "ph-bty-0001": "bty0001",
        "ph-hwh-0001": "hwh0001",
    }
)
_APPROVED_VERTICALS = frozenset({"elv", "bty", "hwh"})
_RESERVED_IDENTITIES = frozenset({"default", "test", "dev", "demo", "v15_acceptance"})
_TARGET_SUFFIXES = ("", "-wal", "-shm")

_APPLICATION_TABLES = frozenset(
    {
        "video_tasks",
        "reservation_run_diagnostics",
        "reservation_rollout_breakers",
        "video_assets",
        "local_assets_inventory",
        "task_history",
        "variant_approvals",
        "variant_status_audits",
    }
)
_LEDGER_TABLES = frozenset(
    {
        "fingerprint_ledger_schema_version",
        "fingerprint_identities",
        "fingerprint_occurrences",
        "fingerprint_reservations",
    }
)
_ZERO_BUSINESS_TABLES = tuple(sorted(_APPLICATION_TABLES | (_LEDGER_TABLES - {"fingerprint_ledger_schema_version"})))
_ROLLOUT_COLUMNS = frozenset(
    {
        "reservation_conflict_mode",
        "planning_policy",
        "reservation_mode_source",
        "rollout_generation",
        "rollout_bucket",
        "rollout_canary_basis_points",
    }
)
_ROLLOUT_INDEX_COLUMNS = frozenset(
    {
        ("reservation_conflict_mode", "planning_policy", "created_at"),
        (
            "reservation_mode_source",
            "planning_policy",
            "rollout_generation",
            "created_at",
        ),
    }
)


@dataclass(frozen=True)
class ApprovedTenantIdentity:
    canonical_id: str
    short_code: str


@dataclass(frozen=True)
class TenantProvisionOutcome:
    status: str
    message: str
    data: Mapping[str, Any]
    exit_code: int = 0
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


class _ProvisionFailure(Exception):
    def __init__(self, *, error_code: str, exit_code: int, message: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.exit_code = exit_code
        self.message = message


def _failure(error_code: str, exit_code: int, message: str) -> _ProvisionFailure:
    return _ProvisionFailure(
        error_code=error_code,
        exit_code=exit_code,
        message=message,
    )


def validate_approved_tenant_identity(raw: str) -> ApprovedTenantIdentity:
    """Validate the frozen V1.5 identity without sanitizer acceptance."""
    if not isinstance(raw, str) or not raw or not raw.isascii() or raw != raw.lower():
        raise _failure(OPERATOR_TENANT_INVALID, 3, "tenant identity is not approved")
    match = _TENANT_PATTERN.fullmatch(raw)
    if match is None:
        raise _failure(OPERATOR_TENANT_INVALID, 3, "tenant identity is not approved")
    sequence = int(match.group("sequence"))
    if (
        not 1 <= sequence <= 9999
        or raw in _RESERVED_IDENTITIES
        or match.group("vertical") not in _APPROVED_VERTICALS
        or raw not in _APPROVED_TENANTS
    ):
        raise _failure(OPERATOR_TENANT_INVALID, 3, "tenant identity is not approved")
    return ApprovedTenantIdentity(raw, _APPROVED_TENANTS[raw])


def validate_approval_ref(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or not value.strip()
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise _failure(
            OPERATOR_APPROVAL_REF_INVALID,
            3,
            "approval reference is invalid",
        )
    return value


def _target_artifacts(paths: RuntimePaths, tenant: str) -> tuple[Path, ...]:
    database = paths.tenant_database_path(tenant)
    return tuple(Path(str(database) + suffix) for suffix in _TARGET_SUFFIXES)


def _existing_target_artifacts(paths: RuntimePaths, tenant: str) -> tuple[Path, ...]:
    expected = {path.name.casefold() for path in _target_artifacts(paths, tenant)}
    try:
        entries = tuple(paths.tenant_data_dir.iterdir())
    except OSError:
        raise _failure(
            OPERATOR_TENANT_PROVISION_SUBSYSTEM_FAILED,
            8,
            "tenant data directory is unavailable",
        ) from None
    return tuple(path for path in entries if path.name.casefold() in expected)


def _read_delivery_root(paths: RuntimePaths) -> str | None:
    """Read the existing app_settings authority without creating DB/table state."""
    database = paths.settings_db_path
    if not database.exists():
        return None
    sidecars = tuple(Path(str(database) + suffix) for suffix in ("-wal", "-shm", "-journal"))
    if any(path.exists() for path in sidecars):
        raise _failure(
            OPERATOR_TENANT_PROVISION_SUBSYSTEM_FAILED,
            8,
            "Delivery configuration cannot be read safely",
        )
    try:
        uri = database.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings';"
            ).fetchone()
            if table is None:
                return None
            row = connection.execute(
                "SELECT key_value FROM app_settings WHERE key_name='delivery_root';"
            ).fetchone()
    except (OSError, sqlite3.Error):
        raise _failure(
            OPERATOR_TENANT_PROVISION_SUBSYSTEM_FAILED,
            8,
            "Delivery configuration cannot be read safely",
        ) from None
    if row is None or not str(row[0]).strip():
        return None
    from .delivery_output import normalize_delivery_root

    try:
        return normalize_delivery_root(str(row[0]))
    except Exception:
        raise _failure(
            OPERATOR_TENANT_PROVISION_SUBSYSTEM_FAILED,
            8,
            "Delivery configuration is invalid",
        ) from None


def _check_delivery_namespace(delivery_root: str | None, tenant: str) -> str:
    if delivery_root is None:
        return DELIVERY_NAMESPACE_NOT_CONFIGURED
    from .delivery_output import derive_tenant_delivery_root

    try:
        project_root = derive_tenant_delivery_root(delivery_root, tenant)
        tenant_root = project_root.parents[1]
        tenant_parent = tenant_root.parent
        if not tenant_parent.exists():
            return "AVAILABLE"
        if not tenant_parent.is_dir():
            raise OSError("Delivery tenant namespace parent is not a directory")
        collision = next(
            (entry for entry in tenant_parent.iterdir() if entry.name.casefold() == tenant.casefold()),
            None,
        )
    except _ProvisionFailure:
        raise
    except Exception:
        raise _failure(
            OPERATOR_TENANT_PROVISION_SUBSYSTEM_FAILED,
            8,
            "Delivery namespace cannot be inspected",
        ) from None
    if collision is not None:
        raise _failure(
            OPERATOR_DELIVERY_NAMESPACE_COLLISION,
            4,
            "Delivery tenant namespace already exists",
        )
    return "AVAILABLE"


def _default_initializer(tenant: str) -> None:
    from .database import get_tenant_engine

    engine = get_tenant_engine(tenant)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1").scalar_one()
    finally:
        engine.dispose()


def _initialize_operator_runtime_paths() -> RuntimePaths:
    return get_initialized_runtime_paths() or initialize_runtime_paths()


def _table_names(connection: sqlite3.Connection) -> frozenset[str]:
    return frozenset(
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()
    )


def _default_verifier(database: Path) -> None:
    """Independently verify one initialized tenant DB without repair."""
    if not database.is_file():
        raise ValueError("TENANT_DATABASE_MISSING")
    before = database.stat()
    sidecars = tuple(Path(str(database) + suffix) for suffix in ("-wal", "-shm", "-journal"))
    if any(path.exists() for path in sidecars):
        raise ValueError("TENANT_DATABASE_SIDECAR_PRESENT")
    uri = database.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON;")
        connection.execute("PRAGMA foreign_keys=ON;")
        if connection.execute("PRAGMA foreign_keys;").fetchone()[0] != 1:
            raise ValueError("TENANT_FOREIGN_KEYS_DISABLED")
        integrity = connection.execute("PRAGMA integrity_check;").fetchall()
        if [str(row[0]).lower() for row in integrity] != ["ok"]:
            raise ValueError("TENANT_INTEGRITY_FAILED")
        if connection.execute("PRAGMA foreign_key_check;").fetchone() is not None:
            raise ValueError("TENANT_FOREIGN_KEY_CHECK_FAILED")

        tables = _table_names(connection)
        if not (_APPLICATION_TABLES | _LEDGER_TABLES).issubset(tables):
            raise ValueError("TENANT_SCHEMA_INCOMPLETE")
        from .models import Base as ApplicationModelBase

        expected_application_columns = {
            table.name: frozenset(column.name for column in table.columns)
            for table in ApplicationModelBase.metadata.sorted_tables
        }
        for table_name, expected_columns in expected_application_columns.items():
            actual_columns = frozenset(
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table_name}");')
            )
            if not expected_columns.issubset(actual_columns):
                raise ValueError("TENANT_SCHEMA_INCOMPLETE")
        video_columns = frozenset(
            str(row[1]) for row in connection.execute("PRAGMA table_info('video_tasks');")
        )
        if not _ROLLOUT_COLUMNS.issubset(video_columns):
            raise ValueError("TENANT_ROLLOUT_SCHEMA_INCOMPLETE")
        rollout_indexes = frozenset(
            tuple(str(column[2]) for column in connection.execute(f"PRAGMA index_info('{row[1]}');"))
            for row in connection.execute("PRAGMA index_list('video_tasks');")
        )
        if not _ROLLOUT_INDEX_COLUMNS.issubset(rollout_indexes):
            raise ValueError("TENANT_ROLLOUT_SCHEMA_INCOMPLETE")
        ledger = connection.execute(
            "SELECT schema_version FROM fingerprint_ledger_schema_version WHERE component=?;",
            ("fingerprint_ledger",),
        ).fetchone()
        if ledger is None or int(ledger[0]) != 2:
            raise ValueError("TENANT_LEDGER_V2_INVALID")
        for table in _ZERO_BUSINESS_TABLES:
            if int(connection.execute(f'SELECT COUNT(*) FROM "{table}";').fetchone()[0]) != 0:
                raise ValueError("TENANT_BUSINESS_DATA_NOT_EMPTY")
    after = database.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("TENANT_DATABASE_CHANGED_DURING_VERIFICATION")
    if any(path.exists() for path in sidecars):
        raise ValueError("TENANT_DATABASE_SIDECAR_CREATED")


def provision_tenant(
    tenant_id: str,
    approval_ref: str,
    *,
    paths_initializer: Callable[[], RuntimePaths] = _initialize_operator_runtime_paths,
    barrier_factory: Callable[[RuntimePaths], Any] = acquire_runtime_mutation_barrier,
    delivery_root_reader: Callable[[RuntimePaths], str | None] = _read_delivery_root,
    initializer: Callable[[str], None] = _default_initializer,
    verifier: Callable[[Path], None] = _default_verifier,
) -> TenantProvisionOutcome:
    """Provision exactly one approved empty tenant or return a bounded failure."""
    try:
        identity = validate_approved_tenant_identity(tenant_id)
        validate_approval_ref(approval_ref)
    except _ProvisionFailure as exc:
        return TenantProvisionOutcome("ERROR", exc.message, {}, exc.exit_code, exc.error_code)

    try:
        paths = paths_initializer()
        with barrier_factory(paths):
            if _existing_target_artifacts(paths, identity.canonical_id):
                raise _failure(
                    OPERATOR_TENANT_COLLISION,
                    4,
                    "tenant database allocation already exists",
                )
            delivery_status = _check_delivery_namespace(
                delivery_root_reader(paths), identity.canonical_id
            )
            database = paths.tenant_database_path(identity.canonical_id)
            try:
                initializer(identity.canonical_id)
            except Exception:
                if any(path.exists() for path in _target_artifacts(paths, identity.canonical_id)):
                    raise _failure(
                        OPERATOR_TENANT_PARTIAL_PROVISIONING_REVIEW_REQUIRED,
                        7,
                        "partial tenant allocation requires human review",
                    ) from None
                raise _failure(
                    OPERATOR_TENANT_PROVISION_SUBSYSTEM_FAILED,
                    8,
                    "tenant initialization failed before allocation",
                ) from None
            try:
                verifier(database)
            except Exception:
                raise _failure(
                    OPERATOR_TENANT_PARTIAL_PROVISIONING_REVIEW_REQUIRED,
                    7,
                    "partial tenant allocation requires human review",
                ) from None
    except RuntimeMutationBarrierBusy:
        return TenantProvisionOutcome(
            "ERROR", "runtime mutation is busy", {}, 4, OPERATOR_RUNTIME_MUTATION_BUSY
        )
    except RuntimeMutationBarrierError:
        return TenantProvisionOutcome(
            "ERROR",
            "runtime mutation barrier is unavailable",
            {},
            8,
            OPERATOR_TENANT_PROVISION_SUBSYSTEM_FAILED,
        )
    except _ProvisionFailure as exc:
        return TenantProvisionOutcome("ERROR", exc.message, {}, exc.exit_code, exc.error_code)
    except Exception:
        return TenantProvisionOutcome(
            "ERROR",
            "tenant provisioning failed",
            {},
            9,
            OPERATOR_TENANT_PROVISION_INTERNAL_FAILED,
        )

    relative_path = f"data/dopamatrix_{identity.canonical_id}.db"
    return TenantProvisionOutcome(
        "PROVISIONED",
        f"TENANT PROVISIONED: {identity.canonical_id}",
        {
            "tenant": identity.canonical_id,
            "tenant_short_code": identity.short_code,
            "database_path": relative_path,
            "schema": "PASS",
            "ledger_v2": "PASS",
            "zero_business_data": "PASS",
            "delivery_namespace": delivery_status,
            "backup_namespace": BACKUP_NAMESPACE_NOT_CONFIGURED,
        },
    )
