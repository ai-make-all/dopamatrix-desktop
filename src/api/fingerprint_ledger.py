"""Tenant-local FP-001 fingerprint ledger foundation (shadow mode only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, inspect, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


LEDGER_SCHEMA_VERSION = 1
LEDGER_SCHEMA_COMPONENT = "fingerprint_ledger"
LEDGER_DIGEST_ALGORITHM = "sha256"
LEDGER_LIFECYCLE_EVENTS = frozenset({"PLANNED", "RENDERED", "FAILED"})


class FingerprintLedgerError(RuntimeError):
    """Base error for ledger invariants and schema verification."""


class FingerprintLedgerSchemaError(FingerprintLedgerError):
    """Raised when an opened tenant database has an invalid ledger schema."""


class FingerprintLedgerCanonicalMismatch(FingerprintLedgerError):
    """Raised when one digest resolves to different canonical FP payloads."""


class FingerprintLedgerBase(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FingerprintLedgerSchemaVersion(FingerprintLedgerBase):
    __tablename__ = "fingerprint_ledger_schema_version"

    component: Mapped[str] = mapped_column(String(64), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class FingerprintIdentity(FingerprintLedgerBase):
    __tablename__ = "fingerprint_identities"
    __table_args__ = (
        Index(
            "uq_fingerprint_identity_contract",
            "fingerprint_type", "fingerprint_version", "fingerprint_digest",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint_type: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_version: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    digest_algorithm: Mapped[str] = mapped_column(String(16), nullable=False)
    source_hash_algorithm: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class FingerprintOccurrence(FingerprintLedgerBase):
    __tablename__ = "fingerprint_occurrences"
    __table_args__ = (
        Index(
            "uq_fingerprint_occurrence_event",
            "fingerprint_identity_id", "task_id", "execution_id",
            "child_index", "lifecycle_event", unique=True,
        ),
        Index(
            "ix_fingerprint_occurrence_identity_lifecycle",
            "fingerprint_identity_id", "lifecycle_event", "occurred_at",
        ),
        Index(
            "ix_fingerprint_occurrence_task_execution", "task_id", "execution_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint_identity_id: Mapped[int] = mapped_column(
        ForeignKey("fingerprint_identities.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False)
    child_index: Mapped[int] = mapped_column(Integer, nullable=False)
    lifecycle_event: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    provenance: Mapped[str] = mapped_column(String(128), nullable=False)


@dataclass(frozen=True)
class FingerprintOccurrenceRecord:
    fingerprint_type: str
    fingerprint_version: int
    fingerprint_digest: str
    digest_algorithm: str
    source_hash_algorithm: str
    canonical_payload: str
    task_id: str
    execution_id: str
    child_index: int
    lifecycle_event: str
    provenance: str


_REQUIRED_COLUMNS = {
    FingerprintLedgerSchemaVersion.__tablename__: {
        "component", "schema_version", "updated_at",
    },
    FingerprintIdentity.__tablename__: {
        "id", "fingerprint_type", "fingerprint_version", "fingerprint_digest",
        "digest_algorithm", "source_hash_algorithm", "canonical_payload", "created_at",
    },
    FingerprintOccurrence.__tablename__: {
        "id", "fingerprint_identity_id", "task_id", "execution_id", "child_index",
        "lifecycle_event", "occurred_at", "provenance",
    },
}


_REQUIRED_PRIMARY_KEYS = {
    FingerprintLedgerSchemaVersion.__tablename__: ["component"],
    FingerprintIdentity.__tablename__: ["id"],
    FingerprintOccurrence.__tablename__: ["id"],
}


_REQUIRED_COLUMN_TYPES = {
    FingerprintLedgerSchemaVersion.__tablename__: {
        "component": "string",
        "schema_version": "integer",
        "updated_at": "datetime",
    },
    FingerprintIdentity.__tablename__: {
        "id": "integer",
        "fingerprint_type": "string",
        "fingerprint_version": "integer",
        "fingerprint_digest": "string",
        "digest_algorithm": "string",
        "source_hash_algorithm": "string",
        "canonical_payload": "string",
        "created_at": "datetime",
    },
    FingerprintOccurrence.__tablename__: {
        "id": "integer",
        "fingerprint_identity_id": "integer",
        "task_id": "string",
        "execution_id": "string",
        "child_index": "integer",
        "lifecycle_event": "string",
        "occurred_at": "datetime",
        "provenance": "string",
    },
}


def _column_type_matches(column_type, expected_family: str) -> bool:
    """Match only the SQLite-reflected type families material to Ledger V1."""
    if expected_family == "integer":
        return isinstance(column_type, Integer)
    if expected_family == "string":
        return isinstance(column_type, String)
    if expected_family == "datetime":
        return isinstance(column_type, DateTime)
    return False


def _verify_ledger_table_contract(inspector, table_name: str) -> None:
    columns = {
        column["name"]: column
        for column in inspector.get_columns(table_name)
    }
    required = _REQUIRED_COLUMNS[table_name]
    if set(columns) != required:
        raise FingerprintLedgerSchemaError(
            "FINGERPRINT_LEDGER_SCHEMA_INVALID: "
            f"table={table_name} columns={sorted(columns)} expected={sorted(required)}"
        )

    primary_key = inspector.get_pk_constraint(table_name)
    expected_primary_key = _REQUIRED_PRIMARY_KEYS[table_name]
    if primary_key.get("constrained_columns") != expected_primary_key:
        raise FingerprintLedgerSchemaError(
            "FINGERPRINT_LEDGER_SCHEMA_INVALID: "
            f"table={table_name} primary_key={primary_key.get('constrained_columns')} "
            f"expected={expected_primary_key}"
        )

    for column_name, expected_family in _REQUIRED_COLUMN_TYPES[table_name].items():
        column = columns[column_name]
        if column.get("nullable") is not False:
            raise FingerprintLedgerSchemaError(
                "FINGERPRINT_LEDGER_SCHEMA_INVALID: "
                f"table={table_name} column={column_name} nullable"
            )
        if not _column_type_matches(column["type"], expected_family):
            raise FingerprintLedgerSchemaError(
                "FINGERPRINT_LEDGER_SCHEMA_INVALID: "
                f"table={table_name} column={column_name} "
                f"type={column['type']} expected_family={expected_family}"
            )


def ensure_fingerprint_ledger_schema(engine) -> None:
    """Create missing V1 ledger tables, then strictly verify their contract."""
    FingerprintLedgerBase.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    missing_tables = set(_REQUIRED_COLUMNS) - set(inspector.get_table_names())
    if missing_tables:
        raise FingerprintLedgerSchemaError(
            f"FINGERPRINT_LEDGER_SCHEMA_INVALID: missing tables {sorted(missing_tables)}"
        )
    for table_name in _REQUIRED_COLUMNS:
        _verify_ledger_table_contract(inspector, table_name)

    identity_indexes = {
        item["name"]: item
        for item in inspector.get_indexes(FingerprintIdentity.__tablename__)
    }
    occurrence_indexes = {
        item["name"]: item
        for item in inspector.get_indexes(FingerprintOccurrence.__tablename__)
    }
    for index_map, name, unique, columns in (
        (identity_indexes, "uq_fingerprint_identity_contract", True,
         ["fingerprint_type", "fingerprint_version", "fingerprint_digest"]),
        (occurrence_indexes, "uq_fingerprint_occurrence_event", True,
         ["fingerprint_identity_id", "task_id", "execution_id", "child_index",
          "lifecycle_event"]),
        (occurrence_indexes, "ix_fingerprint_occurrence_identity_lifecycle", False,
         ["fingerprint_identity_id", "lifecycle_event", "occurred_at"]),
        (occurrence_indexes, "ix_fingerprint_occurrence_task_execution", False,
         ["task_id", "execution_id"]),
    ):
        index = index_map.get(name)
        if (
            index is None
            or bool(index.get("unique")) is not unique
            or index.get("column_names") != columns
        ):
            raise FingerprintLedgerSchemaError(
                f"FINGERPRINT_LEDGER_SCHEMA_INVALID: index={name}"
            )

    foreign_keys = inspector.get_foreign_keys(FingerprintOccurrence.__tablename__)
    if len(foreign_keys) != 1:
        raise FingerprintLedgerSchemaError(
            "FINGERPRINT_LEDGER_SCHEMA_INVALID: occurrence identity foreign key"
        )
    identity_foreign_key = foreign_keys[0]
    if (
        identity_foreign_key.get("constrained_columns") != ["fingerprint_identity_id"]
        or identity_foreign_key.get("referred_table")
        != FingerprintIdentity.__tablename__
        or identity_foreign_key.get("referred_columns") != ["id"]
        or str(identity_foreign_key.get("options", {}).get("ondelete", "")).upper()
        != "CASCADE"
    ):
        raise FingerprintLedgerSchemaError(
            "FINGERPRINT_LEDGER_SCHEMA_INVALID: occurrence identity foreign key"
        )

    with engine.begin() as connection:
        connection.execute(
            sqlite_insert(FingerprintLedgerSchemaVersion)
            .values(
                component=LEDGER_SCHEMA_COMPONENT,
                schema_version=LEDGER_SCHEMA_VERSION,
                updated_at=_utcnow(),
            )
            .on_conflict_do_nothing(
                index_elements=[FingerprintLedgerSchemaVersion.component]
            )
        )
        row = connection.execute(
            select(FingerprintLedgerSchemaVersion).where(
                FingerprintLedgerSchemaVersion.component == LEDGER_SCHEMA_COMPONENT
            )
        ).first()
        if row is None or row.schema_version != LEDGER_SCHEMA_VERSION:
            raise FingerprintLedgerSchemaError(
                "FINGERPRINT_LEDGER_SCHEMA_VERSION_UNSUPPORTED: "
                f"{None if row is None else row.schema_version}"
            )


class FingerprintLedgerRepository:
    """Idempotent ledger writes within a caller-supplied tenant Session."""

    def __init__(self, session: Session):
        self._session = session

    def ensure_identity(self, record: FingerprintOccurrenceRecord) -> FingerprintIdentity:
        self._session.execute(
            sqlite_insert(FingerprintIdentity)
            .values(
                fingerprint_type=record.fingerprint_type,
                fingerprint_version=record.fingerprint_version,
                fingerprint_digest=record.fingerprint_digest,
                digest_algorithm=record.digest_algorithm,
                source_hash_algorithm=record.source_hash_algorithm,
                canonical_payload=record.canonical_payload,
                created_at=_utcnow(),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    FingerprintIdentity.fingerprint_type,
                    FingerprintIdentity.fingerprint_version,
                    FingerprintIdentity.fingerprint_digest,
                ]
            )
        )
        identity = self._session.scalar(
            select(FingerprintIdentity).where(
                FingerprintIdentity.fingerprint_type == record.fingerprint_type,
                FingerprintIdentity.fingerprint_version == record.fingerprint_version,
                FingerprintIdentity.fingerprint_digest == record.fingerprint_digest,
            )
        )
        if identity is None:
            raise FingerprintLedgerError("FINGERPRINT_LEDGER_IDENTITY_WRITE_FAILED")
        if identity.canonical_payload != record.canonical_payload:
            raise FingerprintLedgerCanonicalMismatch("FINGERPRINT_LEDGER_CANONICAL_MISMATCH")
        if (
            identity.digest_algorithm != record.digest_algorithm
            or identity.source_hash_algorithm != record.source_hash_algorithm
        ):
            raise FingerprintLedgerError("FINGERPRINT_LEDGER_IDENTITY_METADATA_MISMATCH")
        return identity

    def record_occurrence(self, record: FingerprintOccurrenceRecord) -> bool:
        if record.lifecycle_event not in LEDGER_LIFECYCLE_EVENTS:
            raise FingerprintLedgerError("FINGERPRINT_LEDGER_LIFECYCLE_INVALID")
        identity = self.ensure_identity(record)
        result = self._session.execute(
            sqlite_insert(FingerprintOccurrence)
            .values(
                fingerprint_identity_id=identity.id,
                task_id=record.task_id,
                execution_id=record.execution_id,
                child_index=record.child_index,
                lifecycle_event=record.lifecycle_event,
                occurred_at=_utcnow(),
                provenance=record.provenance,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    FingerprintOccurrence.fingerprint_identity_id,
                    FingerprintOccurrence.task_id,
                    FingerprintOccurrence.execution_id,
                    FingerprintOccurrence.child_index,
                    FingerprintOccurrence.lifecycle_event,
                ]
            )
        )
        return bool(result.rowcount)

    def record_occurrences(self, records: Iterable[FingerprintOccurrenceRecord]) -> int:
        return sum(self.record_occurrence(record) for record in records)
