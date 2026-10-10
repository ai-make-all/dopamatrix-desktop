"""Frozen Philippine Seed tenant identity and provisioning authority."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from types import MappingProxyType

from .runtime_paths import RuntimePaths
from .sqlite_observation import (
    ReadonlySQLiteObservationError,
    open_readonly_sqlite,
)


TENANT_IDENTITY_MALFORMED = "TENANT_IDENTITY_MALFORMED"
TENANT_NOT_APPROVED = "TENANT_NOT_APPROVED"
TENANT_NOT_PROVISIONED = "TENANT_NOT_PROVISIONED"

_TENANT_PATTERN = re.compile(
    r"^(?P<country>[a-z]{2})-(?P<vertical>[a-z0-9]{3,5})-(?P<sequence>[0-9]{4})$",
    re.ASCII,
)

APPROVED_V15_PHILIPPINE_SEED_TENANT_CODES = MappingProxyType(
    {
        "ph-elv-0001": "elv0001",
        "ph-bty-0001": "bty0001",
        "ph-hwh-0001": "hwh0001",
    }
)
APPROVED_V15_PHILIPPINE_SEED_TENANTS = frozenset(
    APPROVED_V15_PHILIPPINE_SEED_TENANT_CODES
)

_FINGERPRINT_LEDGER_TABLES = frozenset(
    {
        "fingerprint_ledger_schema_version",
        "fingerprint_identities",
        "fingerprint_occurrences",
        "fingerprint_reservations",
    }
)
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


class TenantPolicyError(RuntimeError):
    """Stable tenant-policy failure safe for an HTTP error response."""

    def __init__(self, code: str, http_status: int) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


class TenantIdentityMalformed(TenantPolicyError):
    def __init__(self) -> None:
        super().__init__(TENANT_IDENTITY_MALFORMED, 400)


class TenantNotApproved(TenantPolicyError):
    def __init__(self) -> None:
        super().__init__(TENANT_NOT_APPROVED, 403)


class TenantNotProvisioned(TenantPolicyError):
    def __init__(self) -> None:
        super().__init__(TENANT_NOT_PROVISIONED, 403)


class TenantSchemaReadinessError(ValueError):
    """An existing tenant DB is not structurally safe for normal runtime."""


def parse_approved_tenant_identity(raw: object) -> ApprovedTenantIdentity:
    """Return one exact frozen Seed identity without sanitizer acceptance."""
    if (
        not isinstance(raw, str)
        or not raw
        or not raw.isascii()
        or raw != raw.lower()
        or _TENANT_PATTERN.fullmatch(raw) is None
    ):
        raise TenantIdentityMalformed()
    try:
        short_code = APPROVED_V15_PHILIPPINE_SEED_TENANT_CODES[raw]
    except KeyError:
        raise TenantNotApproved() from None
    return ApprovedTenantIdentity(raw, short_code)


def tenant_business_table_names() -> tuple[str, ...]:
    """Return tables whose emptiness is a provisioning-time invariant only."""
    from .models import Base as ApplicationModelBase

    application_tables = {
        table.name for table in ApplicationModelBase.metadata.sorted_tables
    }
    return tuple(
        sorted(
            application_tables
            | (_FINGERPRINT_LEDGER_TABLES - {"fingerprint_ledger_schema_version"})
        )
    )


def verify_tenant_schema_readiness(connection: sqlite3.Connection) -> None:
    """Read-only structural gate shared by runtime and operator verification."""
    from .models import Base as ApplicationModelBase

    connection.execute("PRAGMA query_only=ON;")
    connection.execute("PRAGMA foreign_keys=ON;")
    if connection.execute("PRAGMA foreign_keys;").fetchone()[0] != 1:
        raise TenantSchemaReadinessError("TENANT_FOREIGN_KEYS_DISABLED")
    integrity = connection.execute("PRAGMA integrity_check;").fetchall()
    if [str(row[0]).lower() for row in integrity] != ["ok"]:
        raise TenantSchemaReadinessError("TENANT_INTEGRITY_FAILED")
    if connection.execute("PRAGMA foreign_key_check;").fetchone() is not None:
        raise TenantSchemaReadinessError("TENANT_FOREIGN_KEY_CHECK_FAILED")

    application_tables = {
        table.name for table in ApplicationModelBase.metadata.sorted_tables
    }
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()
    }
    if not (application_tables | _FINGERPRINT_LEDGER_TABLES).issubset(tables):
        raise TenantSchemaReadinessError("TENANT_SCHEMA_INCOMPLETE")

    for table in ApplicationModelBase.metadata.sorted_tables:
        expected_columns = {column.name for column in table.columns}
        actual_columns = {
            str(row[1])
            for row in connection.execute(
                f'PRAGMA table_info("{table.name}");'
            ).fetchall()
        }
        if not expected_columns.issubset(actual_columns):
            raise TenantSchemaReadinessError("TENANT_SCHEMA_INCOMPLETE")

    video_columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info('video_tasks');").fetchall()
    }
    if not _ROLLOUT_COLUMNS.issubset(video_columns):
        raise TenantSchemaReadinessError("TENANT_ROLLOUT_SCHEMA_INCOMPLETE")
    rollout_indexes = {
        tuple(
            str(column[1])
            for column in connection.execute(
                "SELECT seqno, name FROM pragma_index_info(?) ORDER BY seqno;",
                (str(row[1]),),
            ).fetchall()
        )
        for row in connection.execute("PRAGMA index_list('video_tasks');").fetchall()
    }
    if not _ROLLOUT_INDEX_COLUMNS.issubset(rollout_indexes):
        raise TenantSchemaReadinessError("TENANT_ROLLOUT_SCHEMA_INCOMPLETE")

    ledger = connection.execute(
        "SELECT schema_version FROM fingerprint_ledger_schema_version "
        "WHERE component=?;",
        ("fingerprint_ledger",),
    ).fetchone()
    if ledger is None or int(ledger[0]) != 2:
        raise TenantSchemaReadinessError("TENANT_LEDGER_V2_INVALID")


def require_provisioned_tenant(
    raw: object,
    paths: RuntimePaths,
) -> ApprovedTenantIdentity:
    """Authorize an approved tenant only when operator-created storage exists."""
    identity = parse_approved_tenant_identity(raw)
    database = paths.tenant_database_path(identity.canonical_id)
    if not database.is_file():
        raise TenantNotProvisioned()
    try:
        with open_readonly_sqlite(database, timeout=1.0) as connection:
            verify_tenant_schema_readiness(connection)
    except TenantPolicyError:
        raise
    except (
        OSError,
        ReadonlySQLiteObservationError,
        sqlite3.Error,
        TypeError,
        ValueError,
    ):
        raise TenantNotProvisioned() from None
    return identity
