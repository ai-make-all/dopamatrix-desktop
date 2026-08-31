"""Tenant-local FP-001 fingerprint ledger foundation (shadow mode only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    and_,
    case,
    delete,
    func,
    inspect,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


LEDGER_SCHEMA_VERSION = 2
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


def _normalize_reservation_datetime(value: datetime) -> datetime:
    """Return Reservation time as UTC-naive; naive input is already interpreted as UTC."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _reservation_utcnow() -> datetime:
    """Return the current instant in the Reservation UTC-naive persistence form."""
    return _normalize_reservation_datetime(_utcnow())


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


class FingerprintReservation(FingerprintLedgerBase):
    __tablename__ = "fingerprint_reservations"
    __table_args__ = (
        Index("ix_fingerprint_reservation_expires_at", "expires_at"),
        Index(
            "ix_fingerprint_reservation_owner",
            "owner_task_id",
            "owner_slot_index",
        ),
    )

    fingerprint_identity_id: Mapped[int] = mapped_column(
        ForeignKey("fingerprint_identities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    owner_task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=_reservation_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=_reservation_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


@dataclass(frozen=True)
class FingerprintIdentityRecord:
    fingerprint_type: str
    fingerprint_version: int
    fingerprint_digest: str
    digest_algorithm: str
    source_hash_algorithm: str
    canonical_payload: str


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


class ReservationAcquireStatus(str, Enum):
    ACQUIRED = "ACQUIRED"
    REACQUIRED = "REACQUIRED"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class ReservationAcquireResult:
    status: ReservationAcquireStatus
    fingerprint_identity_id: int
    expires_at: datetime | None


@dataclass(frozen=True)
class HistoricalExactLookupResult:
    identity_exists: bool
    historical_match: bool
    fingerprint_identity_id: int | None
    historical_occurrence_count: int
    planned_count: int
    rendered_count: int
    failed_count: int
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    last_rendered_at: datetime | None


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
    FingerprintReservation.__tablename__: {
        "fingerprint_identity_id", "owner_task_id", "owner_slot_index",
        "created_at", "updated_at", "expires_at", "confirmed_at", "execution_id",
    },
}


_REQUIRED_PRIMARY_KEYS = {
    FingerprintLedgerSchemaVersion.__tablename__: ["component"],
    FingerprintIdentity.__tablename__: ["id"],
    FingerprintOccurrence.__tablename__: ["id"],
    FingerprintReservation.__tablename__: ["fingerprint_identity_id"],
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
    FingerprintReservation.__tablename__: {
        "fingerprint_identity_id": "integer",
        "owner_task_id": "string",
        "owner_slot_index": "integer",
        "created_at": "datetime",
        "updated_at": "datetime",
        "expires_at": "datetime",
        "confirmed_at": "datetime",
        "execution_id": "string",
    },
}


_NULLABLE_COLUMNS = {
    FingerprintReservation.__tablename__: {"confirmed_at", "execution_id"},
}


_V1_TABLES = (
    FingerprintLedgerSchemaVersion.__tablename__,
    FingerprintIdentity.__tablename__,
    FingerprintOccurrence.__tablename__,
)


_V2_TABLES = (*_V1_TABLES, FingerprintReservation.__tablename__)


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
        expected_nullable = column_name in _NULLABLE_COLUMNS.get(table_name, set())
        if column.get("nullable") is not expected_nullable:
            raise FingerprintLedgerSchemaError(
                "FINGERPRINT_LEDGER_SCHEMA_INVALID: "
                f"table={table_name} column={column_name} "
                f"nullable={column.get('nullable')} expected={expected_nullable}"
            )
        if not _column_type_matches(column["type"], expected_family):
            raise FingerprintLedgerSchemaError(
                "FINGERPRINT_LEDGER_SCHEMA_INVALID: "
                f"table={table_name} column={column_name} "
                f"type={column['type']} expected_family={expected_family}"
            )


def _verify_required_tables(inspector, table_names: tuple[str, ...]) -> None:
    missing_tables = set(table_names) - set(inspector.get_table_names())
    if missing_tables:
        raise FingerprintLedgerSchemaError(
            f"FINGERPRINT_LEDGER_SCHEMA_INVALID: missing tables {sorted(missing_tables)}"
        )
    for table_name in table_names:
        _verify_ledger_table_contract(inspector, table_name)


def _verify_index(
    index_map: dict,
    name: str,
    *,
    unique: bool,
    columns: list[str],
) -> None:
    index = index_map.get(name)
    if (
        index is None
        or bool(index.get("unique")) is not unique
        or index.get("column_names") != columns
    ):
        raise FingerprintLedgerSchemaError(
            f"FINGERPRINT_LEDGER_SCHEMA_INVALID: index={name}"
        )


def _verify_identity_foreign_key(
    inspector,
    table_name: str,
    constrained_column: str,
) -> None:
    foreign_keys = inspector.get_foreign_keys(table_name)
    if len(foreign_keys) != 1:
        raise FingerprintLedgerSchemaError(
            f"FINGERPRINT_LEDGER_SCHEMA_INVALID: table={table_name} identity foreign key"
        )
    identity_foreign_key = foreign_keys[0]
    if (
        identity_foreign_key.get("constrained_columns") != [constrained_column]
        or identity_foreign_key.get("referred_table")
        != FingerprintIdentity.__tablename__
        or identity_foreign_key.get("referred_columns") != ["id"]
        or str(identity_foreign_key.get("options", {}).get("ondelete", "")).upper()
        != "CASCADE"
    ):
        raise FingerprintLedgerSchemaError(
            f"FINGERPRINT_LEDGER_SCHEMA_INVALID: table={table_name} identity foreign key"
        )


def _verify_v1_contract(inspector) -> None:
    _verify_required_tables(inspector, _V1_TABLES)
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
        _verify_index(index_map, name, unique=unique, columns=columns)

    _verify_identity_foreign_key(
        inspector,
        FingerprintOccurrence.__tablename__,
        "fingerprint_identity_id",
    )


def _verify_v2_contract(inspector) -> None:
    _verify_v1_contract(inspector)
    _verify_required_tables(inspector, (FingerprintReservation.__tablename__,))
    reservation_indexes = {
        item["name"]: item
        for item in inspector.get_indexes(FingerprintReservation.__tablename__)
    }
    _verify_index(
        reservation_indexes,
        "ix_fingerprint_reservation_expires_at",
        unique=False,
        columns=["expires_at"],
    )
    _verify_index(
        reservation_indexes,
        "ix_fingerprint_reservation_owner",
        unique=False,
        columns=["owner_task_id", "owner_slot_index"],
    )
    _verify_identity_foreign_key(
        inspector,
        FingerprintReservation.__tablename__,
        "fingerprint_identity_id",
    )


def _read_ledger_schema_version(engine) -> int:
    with engine.connect() as connection:
        row = connection.execute(
            select(FingerprintLedgerSchemaVersion.schema_version).where(
                FingerprintLedgerSchemaVersion.component == LEDGER_SCHEMA_COMPONENT
            )
        ).first()
    if row is None:
        raise FingerprintLedgerSchemaError(
            "FINGERPRINT_LEDGER_SCHEMA_VERSION_MISSING"
        )
    return int(row.schema_version)


def _insert_new_ledger_schema_version(engine) -> None:
    with engine.begin() as connection:
        result = connection.execute(
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
        if result.rowcount != 1:
            raise FingerprintLedgerSchemaError(
                "FINGERPRINT_LEDGER_SCHEMA_VERSION_INITIALIZATION_FAILED"
            )


def _migrate_v1_to_v2(engine) -> None:
    with engine.begin() as connection:
        FingerprintReservation.__table__.create(bind=connection, checkfirst=True)

    _verify_v2_contract(inspect(engine))

    with engine.begin() as connection:
        result = connection.execute(
            update(FingerprintLedgerSchemaVersion)
            .where(
                FingerprintLedgerSchemaVersion.component == LEDGER_SCHEMA_COMPONENT,
                FingerprintLedgerSchemaVersion.schema_version == 1,
            )
            .values(schema_version=LEDGER_SCHEMA_VERSION, updated_at=_utcnow())
        )
        if result.rowcount != 1:
            raise FingerprintLedgerSchemaError(
                "FINGERPRINT_LEDGER_SCHEMA_V1_TO_V2_MIGRATION_FAILED"
            )


def ensure_fingerprint_ledger_schema(engine) -> None:
    """Create or non-destructively migrate and verify the tenant Ledger V2 schema."""
    existing_tables = set(inspect(engine).get_table_names())
    ledger_tables_present = existing_tables.intersection(_V2_TABLES)

    if not ledger_tables_present:
        FingerprintLedgerBase.metadata.create_all(bind=engine)
        _verify_v2_contract(inspect(engine))
        _insert_new_ledger_schema_version(engine)
        if _read_ledger_schema_version(engine) != LEDGER_SCHEMA_VERSION:
            raise FingerprintLedgerSchemaError(
                "FINGERPRINT_LEDGER_SCHEMA_VERSION_UNSUPPORTED"
            )
        return

    _verify_v1_contract(inspect(engine))
    current_version = _read_ledger_schema_version(engine)
    if current_version == 1:
        _migrate_v1_to_v2(engine)
    elif current_version != LEDGER_SCHEMA_VERSION:
        raise FingerprintLedgerSchemaError(
            f"FINGERPRINT_LEDGER_SCHEMA_VERSION_UNSUPPORTED: {current_version}"
        )

    _verify_v2_contract(inspect(engine))
    if _read_ledger_schema_version(engine) != LEDGER_SCHEMA_VERSION:
        raise FingerprintLedgerSchemaError(
            "FINGERPRINT_LEDGER_SCHEMA_VERSION_UNSUPPORTED"
        )


class FingerprintLedgerRepository:
    """Idempotent ledger writes within a caller-supplied tenant Session."""

    def __init__(self, session: Session):
        self._session = session

    @staticmethod
    def _validate_identity_metadata(
        identity: FingerprintIdentity,
        record: FingerprintIdentityRecord | FingerprintOccurrenceRecord,
    ) -> None:
        if identity.canonical_payload != record.canonical_payload:
            raise FingerprintLedgerCanonicalMismatch(
                "FINGERPRINT_LEDGER_CANONICAL_MISMATCH"
            )
        if (
            identity.digest_algorithm != record.digest_algorithm
            or identity.source_hash_algorithm != record.source_hash_algorithm
        ):
            raise FingerprintLedgerError(
                "FINGERPRINT_LEDGER_IDENTITY_METADATA_MISMATCH"
            )

    def _find_identity(
        self,
        record: FingerprintIdentityRecord | FingerprintOccurrenceRecord,
    ) -> FingerprintIdentity | None:
        return self._session.scalar(
            select(FingerprintIdentity).where(
                FingerprintIdentity.fingerprint_type == record.fingerprint_type,
                FingerprintIdentity.fingerprint_version == record.fingerprint_version,
                FingerprintIdentity.fingerprint_digest == record.fingerprint_digest,
            )
        )

    def ensure_identity(
        self,
        record: FingerprintIdentityRecord | FingerprintOccurrenceRecord,
    ) -> FingerprintIdentity:
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
        identity = self._find_identity(record)
        if identity is None:
            raise FingerprintLedgerError("FINGERPRINT_LEDGER_IDENTITY_WRITE_FAILED")
        self._validate_identity_metadata(identity, record)
        return identity

    def lookup_historical_exact(
        self,
        record: FingerprintIdentityRecord | FingerprintOccurrenceRecord,
    ) -> HistoricalExactLookupResult:
        """Return indexed historical facts without creating an identity or policy action."""
        identity = self._find_identity(record)
        if identity is None:
            return HistoricalExactLookupResult(
                identity_exists=False,
                historical_match=False,
                fingerprint_identity_id=None,
                historical_occurrence_count=0,
                planned_count=0,
                rendered_count=0,
                failed_count=0,
                first_seen_at=None,
                last_seen_at=None,
                last_rendered_at=None,
            )
        self._validate_identity_metadata(identity, record)

        aggregate = self._session.execute(
            select(
                func.count(FingerprintOccurrence.id).label("occurrence_count"),
                func.sum(case(
                    (FingerprintOccurrence.lifecycle_event == "PLANNED", 1),
                    else_=0,
                )).label("planned_count"),
                func.sum(case(
                    (FingerprintOccurrence.lifecycle_event == "RENDERED", 1),
                    else_=0,
                )).label("rendered_count"),
                func.sum(case(
                    (FingerprintOccurrence.lifecycle_event == "FAILED", 1),
                    else_=0,
                )).label("failed_count"),
                func.min(FingerprintOccurrence.occurred_at).label("first_seen_at"),
                func.max(FingerprintOccurrence.occurred_at).label("last_seen_at"),
                func.max(case(
                    (
                        FingerprintOccurrence.lifecycle_event == "RENDERED",
                        FingerprintOccurrence.occurred_at,
                    ),
                    else_=None,
                )).label("last_rendered_at"),
            ).where(FingerprintOccurrence.fingerprint_identity_id == identity.id)
        ).one()
        occurrence_count = int(aggregate.occurrence_count or 0)
        return HistoricalExactLookupResult(
            identity_exists=True,
            historical_match=occurrence_count > 0,
            fingerprint_identity_id=identity.id,
            historical_occurrence_count=occurrence_count,
            planned_count=int(aggregate.planned_count or 0),
            rendered_count=int(aggregate.rendered_count or 0),
            failed_count=int(aggregate.failed_count or 0),
            first_seen_at=aggregate.first_seen_at,
            last_seen_at=aggregate.last_seen_at,
            last_rendered_at=aggregate.last_rendered_at,
        )

    def acquire_reservation(
        self,
        record: FingerprintIdentityRecord | FingerprintOccurrenceRecord,
        *,
        owner_task_id: str,
        owner_slot_index: int,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> ReservationAcquireResult:
        """Atomically claim or refresh one fingerprint lease in the caller transaction."""
        current_time = _normalize_reservation_datetime(now or _utcnow())
        normalized_expires_at = _normalize_reservation_datetime(expires_at)
        if normalized_expires_at <= current_time:
            raise FingerprintLedgerError("FINGERPRINT_RESERVATION_EXPIRY_INVALID")
        identity = self.ensure_identity(record)

        same_owner = and_(
            FingerprintReservation.owner_task_id == owner_task_id,
            FingerprintReservation.owner_slot_index == owner_slot_index,
        )
        same_current_owner = and_(
            same_owner,
            FingerprintReservation.expires_at > current_time,
        )
        claimable = or_(
            same_owner,
            FingerprintReservation.expires_at <= current_time,
        )
        statement = (
            sqlite_insert(FingerprintReservation)
            .values(
                fingerprint_identity_id=identity.id,
                owner_task_id=owner_task_id,
                owner_slot_index=owner_slot_index,
                created_at=current_time,
                updated_at=current_time,
                expires_at=normalized_expires_at,
                confirmed_at=None,
                execution_id=None,
            )
            .on_conflict_do_update(
                index_elements=[FingerprintReservation.fingerprint_identity_id],
                set_={
                    "owner_task_id": owner_task_id,
                    "owner_slot_index": owner_slot_index,
                    "created_at": case(
                        (same_current_owner, FingerprintReservation.created_at),
                        else_=current_time,
                    ),
                    "updated_at": current_time,
                    "expires_at": normalized_expires_at,
                    "confirmed_at": case(
                        (same_current_owner, FingerprintReservation.confirmed_at),
                        else_=None,
                    ),
                    "execution_id": case(
                        (same_current_owner, FingerprintReservation.execution_id),
                        else_=None,
                    ),
                },
                where=claimable,
            )
            .returning(
                FingerprintReservation.fingerprint_identity_id,
                FingerprintReservation.created_at,
                FingerprintReservation.expires_at,
            )
        )
        acquired = self._session.execute(statement).first()
        if acquired is None:
            existing_expiry = self._session.scalar(
                select(FingerprintReservation.expires_at).where(
                    FingerprintReservation.fingerprint_identity_id == identity.id
                )
            )
            return ReservationAcquireResult(
                status=ReservationAcquireStatus.CONFLICT,
                fingerprint_identity_id=identity.id,
                expires_at=existing_expiry,
            )

        normalized_created_at = _normalize_reservation_datetime(acquired.created_at)
        status = (
            ReservationAcquireStatus.ACQUIRED
            if normalized_created_at == current_time
            else ReservationAcquireStatus.REACQUIRED
        )
        return ReservationAcquireResult(
            status=status,
            fingerprint_identity_id=acquired.fingerprint_identity_id,
            expires_at=acquired.expires_at,
        )

    def confirm_reservation(
        self,
        fingerprint_identity_id: int,
        *,
        owner_task_id: str,
        owner_slot_index: int,
        execution_id: str,
        now: datetime | None = None,
    ) -> bool:
        current_time = _normalize_reservation_datetime(now or _utcnow())
        result = self._session.execute(
            update(FingerprintReservation)
            .where(
                FingerprintReservation.fingerprint_identity_id
                == fingerprint_identity_id,
                FingerprintReservation.owner_task_id == owner_task_id,
                FingerprintReservation.owner_slot_index == owner_slot_index,
                FingerprintReservation.expires_at > current_time,
            )
            .values(
                confirmed_at=current_time,
                execution_id=execution_id,
                updated_at=current_time,
            )
        )
        return bool(result.rowcount)

    def release_reservation(
        self,
        fingerprint_identity_id: int,
        *,
        owner_task_id: str,
        owner_slot_index: int,
    ) -> bool:
        result = self._session.execute(
            delete(FingerprintReservation).where(
                FingerprintReservation.fingerprint_identity_id
                == fingerprint_identity_id,
                FingerprintReservation.owner_task_id == owner_task_id,
                FingerprintReservation.owner_slot_index == owner_slot_index,
            )
        )
        return bool(result.rowcount)

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
