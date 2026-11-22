"""P2 first-slice storage only: no activation, connection acquisition or DDL.

All returned facts are provisional until the caller confirms its outer commit.
Synthetic evidence is not media health, authorization, Phase-1 or resource release.
"""
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3

from sqlalchemy import (
    MetaData, Table, Column, Integer, Text, LargeBinary, CheckConstraint,
    ForeignKeyConstraint, UniqueConstraint, Boolean, Index, and_, exists, select, update, event,
)
from sqlalchemy.engine import Connection
from sqlalchemy.schema import CreateTable, CreateIndex

MAX_INT = 2**63 - 1
METADATA = MetaData()
STATES = ("NOT_QUALIFIED", "INVALIDATED")


class ContractError(ValueError):
    """Safe contract rejection; never includes private input or SQL diagnostics."""


class Conflict(ContractError):
    pass


class AbortOperation(ContractError):
    """Caller must abandon the associated business atomic operation."""


class RollbackUnknown(AbortOperation):
    """The supplied connection must not be committed or reused."""


def _integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_INT:
        raise ContractError("INTEGER_INVALID")
    return value


def _text(value):
    if type(value) is not str or not value or value != value.strip() or any(
        ord(c) < 32 or ord(c) == 127 for c in value
    ):
        raise ContractError("TEXT_INVALID")
    return value


def _identity(value):
    if type(value) is not str or re.fullmatch("[0-9a-f]{32}", value) is None:
        raise ContractError("IDENTITY_INVALID")
    return value


def _digest(value):
    if type(value) is not bytes or len(value) != 32:
        raise ContractError("DIGEST_INVALID")
    return value


def _time(value):
    try:
        parsed = datetime.fromisoformat(_text(value))
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError()
    except (ValueError, TypeError):
        raise ContractError("TIME_INVALID") from None
    return value


def _json(value):
    # Finite flat evidence, no arbitrary nested payload or invented numeric budget.
    if type(value) is not dict or not value or any(
        type(k) is not str or type(v) is not str for k, v in value.items()
    ):
        raise ContractError("EVIDENCE_INVALID")
    for k, v in value.items():
        _text(k)
        _text(v)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _table(name, fields, primary=(), unique=(), foreign=(), checks=()):
    columns, rules = [], []
    for key, kind, nullable in fields:
        typ = {"i": Integer, "t": Text(collation="BINARY"), "b": LargeBinary}[kind]
        columns.append(Column(key, typ, nullable=nullable, primary_key=key in primary))
        test = {"i": f"typeof({key})='integer' AND {key} BETWEEN 0 AND {MAX_INT}",
                "t": f"typeof({key})='text' AND length({key})>0",
                "b": f"typeof({key})='blob' AND length({key})=32"}[kind]
        if key in ("asset_id", "live_asset_id", "generation", "current_generation", "schema_revision"):
            test += f" AND {key}>0"
        if key in ("version_id", "binding_id", "operation_id", "proof_id",
                   "current_version_id", "current_binding_id", "current_operation_id", "current_proof_id"):
            test += f" AND length({key})=32 AND {key} NOT GLOB '*[^0-9a-f]*'"
        rules.append(CheckConstraint(f"({key} IS NULL) OR ({test})" if nullable else test))
    rules += [UniqueConstraint(*u) for u in unique]
    rules += [ForeignKeyConstraint(local, [f"{target}.{c}" for c in remote], ondelete="RESTRICT")
              for local, target, remote in foreign]
    rules += [CheckConstraint(c) for c in checks]
    return Table(name, METADATA, *columns, *rules)


T, A, V, B, G, O, P = ("tenant_id", "asset_id", "version_id", "binding_id",
                       "generation", "operation_id", "proof_id")
AVBGO = (T, A, V, B, G, O)
CURRENT = ("current_version_id", "current_binding_id", "current_generation",
           "current_operation_id", "current_proof_id")
# Reference-only: actual name/columns checked against models.py; never owned DDL.
LEGACY = Table("local_assets_inventory", METADATA,
               Column("id", Integer, primary_key=True), Column("is_deleted", Boolean, nullable=False))
STORE = _table("igq_store", [("slot", "i", False), (T, "t", False),
    ("schema_revision", "i", False), ("preparation_state", "t", False),
    ("preparation_attempt", "t", False), ("structure_digest", "b", True),
    ("completion_evidence_ref", "t", True), ("completed_at", "t", True)],
    ("slot",), [(T,)], checks=("slot=1", "preparation_state IN ('INCOMPLETE','COMPLETE','FAILED','UNKNOWN')",
    "preparation_state!='COMPLETE' OR (structure_digest IS NOT NULL AND completion_evidence_ref IS NOT NULL AND completed_at IS NOT NULL)"))
HEAD = _table("igq_asset_head", [(T, "t", False), (A, "i", False),
    ("live_asset_id", "i", True), ("asset_state", "t", False),
    ("head_revision", "i", False), ("last_generation", "i", False)] +
    [(c, "i" if c == "current_generation" else "t", True) for c in CURRENT] +
    [("qualification_status", "t", False)], (T, A), [("live_asset_id",)],
    [((T,), "igq_store", (T,)), (("live_asset_id",), LEGACY.name, ("id",)),
     ((T,A,*CURRENT[:2]), "igq_source_binding", (T,A,V,B)),
     ((T,A,*CURRENT[:4]), "igq_operation", AVBGO),
     ((T,A,*CURRENT), "igq_proof", (*AVBGO,P))], checks=(
    "qualification_status IN ('NOT_QUALIFIED','INVALIDATED')",
    "asset_state IN ('LIVE','TRASHED','PURGED')",
    "((current_version_id IS NULL AND current_binding_id IS NULL) OR (current_version_id IS NOT NULL AND current_binding_id IS NOT NULL))",
    "((current_generation IS NULL AND current_operation_id IS NULL) OR (current_generation IS NOT NULL AND current_operation_id IS NOT NULL AND current_version_id IS NOT NULL AND current_binding_id IS NOT NULL))",
    "current_proof_id IS NULL OR (current_version_id IS NOT NULL AND current_binding_id IS NOT NULL AND current_generation IS NOT NULL AND current_operation_id IS NOT NULL)",
    "current_generation IS NULL OR current_generation<=last_generation",
    "((asset_state IN ('LIVE','TRASHED') AND live_asset_id IS NOT NULL AND live_asset_id=asset_id) OR (asset_state='PURGED' AND live_asset_id IS NULL AND current_version_id IS NULL AND current_binding_id IS NULL AND current_generation IS NULL AND current_operation_id IS NULL AND current_proof_id IS NULL))",
    "asset_state!='TRASHED' OR (current_generation IS NULL AND current_operation_id IS NULL AND current_proof_id IS NULL)",
    "qualification_status!='INVALIDATED' OR (current_generation IS NULL AND current_operation_id IS NULL AND current_proof_id IS NULL)"))
CONTENT = _table("igq_content_version", [(T,"t",False),(A,"i",False),(V,"t",False),
    ("sha256","b",False),("actual_size","i",False),("observation_ref","t",False),
    ("created_at","t",False)], (T,A,V), foreign=[((T,A),HEAD.name,(T,A))])
BINDING = _table("igq_source_binding", [(T,"t",False),(A,"i",False),(B,"t",False),
    (V,"t",False),("source_descriptor","t",False),("source_observation_ref","t",False),
    ("authorization_evidence_ref","t",False),("created_at","t",False)], (T,A,B),
    [(T,A,V,B)], [((T,A,V),CONTENT.name,(T,A,V))])
OPERATION = _table("igq_operation", [(T,"t",False),(O,"t",False),(A,"i",False),
    (G,"i",False),(V,"t",False),(B,"t",False),("start_head_revision","i",False),
    ("request_key_digest","b",False),("request_digest","b",False),
    ("completion_state","t",False),("retired","i",False),("result_digest","b",True),
    ("failure_summary","t",True),("retired_reason","t",True),("created_at","t",False),
    ("completed_at","t",True),("retired_at","t",True)], (T,O),
    [(T,A,G),AVBGO,(T,"request_key_digest")],
    [((T,A),HEAD.name,(T,A)),((T,A,V,B),BINDING.name,(T,A,V,B))], checks=(
    "completion_state IN ('OPEN','RESULT_ACCEPTED','FAILURE_ACCEPTED')", "retired IN (0,1)",
    "((completion_state='OPEN' AND result_digest IS NULL AND completed_at IS NULL AND failure_summary IS NULL) OR (completion_state='RESULT_ACCEPTED' AND result_digest IS NOT NULL AND completed_at IS NOT NULL AND failure_summary IS NULL) OR (completion_state='FAILURE_ACCEPTED' AND result_digest IS NOT NULL AND completed_at IS NOT NULL AND failure_summary IS NOT NULL))",
    "((retired=0 AND retired_reason IS NULL AND retired_at IS NULL) OR (retired=1 AND retired_reason IS NOT NULL AND retired_at IS NOT NULL))"))
PROOF = _table("igq_proof", [(T,"t",False),(P,"t",False),(A,"i",False),(V,"t",False),
    (B,"t",False),(G,"i",False),(O,"t",False),("selected_stream","i",False),
    ("profile_id","t",False),("policy_id","t",False),("checker_id","t",False),
    ("tool_id","t",False),("technical_complete","i",False),("evidence_summary","t",False),
    ("resource_evidence_ref","t",False),("result_digest","b",False),("recorded_at","t",False)],
    (T,P), [(T,O),(*AVBGO,P)], [(AVBGO,OPERATION.name,AVBGO)],
    checks=("technical_complete=1",))
RESPONSIBILITY = _table("igq_resource_responsibility", [(T,"t",False),(O,"t",False),
    ("resource_kind","t",False),("correlation_ref","t",False),
    ("responsibility_state","t",False),("existing_owner_ref","t",True),
    ("observation_summary","t",False),("resolution_evidence_ref","t",True)],
    (T,O,"resource_kind","correlation_ref"), foreign=[((T,O),OPERATION.name,(T,O))],
    checks=("resource_kind IN ('PROCESS','READER','PIPE','HANDLE')",
            "responsibility_state='UNKNOWN' AND resolution_evidence_ref IS NULL"))
OWNED_TABLES = (STORE, HEAD, CONTENT, BINDING, OPERATION, PROOF, RESPONSIBILITY)
Index("igq_operation_retired", OPERATION.c.tenant_id, OPERATION.c.asset_id, OPERATION.c.retired)
Index("igq_responsibility_state", RESPONSIBILITY.c.tenant_id, RESPONSIBILITY.c.responsibility_state)


def _normalized_sql(sql):
    return " ".join(sql.strip().rstrip(";").split())


def structure_digest(dialect):
    """Pure rendering; does not execute DDL or discover/open a database."""
    return hashlib.sha256("\n".join(_normalized_sql(str(CreateTable(t).compile(dialect=dialect)))
                                    for t in OWNED_TABLES).encode()).digest()


def _prevent_poisoned_commit(connection):
    if connection.info.get("igq_abort_required"):
        raise RollbackUnknown("ABANDON_CONNECTION")


@dataclass
class _OuterTicket:
    connection: Connection
    raw: sqlite3.Connection
    root: object
    active: bool = True


class _OuterObserver:
    """Narrow trusted-caller evidence, not a production transaction coordinator.

    The caller routes ALL transaction control through this SQLAlchemy Connection.
    Arbitrary privileged raw-DBAPI commit/begin bypass is outside this contract.
    Only an observed successful exact BEGIN establishes a ticket. No SQL is issued.
    """

    def __init__(self, connection):
        self.connection, self.ticket, self.pending = connection, None, None
        self.local_control = False
        event.listen(connection, "before_cursor_execute", self.before)
        event.listen(connection, "after_cursor_execute", self.after)
        event.listen(connection, "commit", self.invalidate)
        event.listen(connection, "rollback", self.invalidate)

    def invalidate(self, *args):
        if self.ticket is not None:
            self.ticket.active = False
        self.ticket, self.pending = None, None

    def before(self, connection, cursor, statement, parameters, context, many):
        sql = re.sub(r"/\*.*?\*/|--[^\r\n]*", " ", statement, flags=re.S).strip().upper()
        if connection.info.get("igq_abort_required") and sql != "ROLLBACK":
            raise RollbackUnknown("ABANDON_CONNECTION")
        # Unsupported caller nesting or SQL transaction control invalidates evidence.
        if re.match(r"^(BEGIN|COMMIT|END|ROLLBACK|SAVEPOINT|RELEASE)\b", sql):
            if self.local_control and sql.startswith(("SAVEPOINT ", "RELEASE SAVEPOINT ", "ROLLBACK TO SAVEPOINT ")):
                return
            self.invalidate()
            raw = connection.connection.driver_connection
            if sql == "BEGIN" and not raw.in_transaction and not connection.in_nested_transaction():
                self.pending = (raw, connection.get_transaction())

    def after(self, connection, cursor, statement, parameters, context, many):
        sql = re.sub(r"/\*.*?\*/|--[^\r\n]*", " ", statement, flags=re.S).strip().upper()
        if self.ticket is not None and not self.ticket.raw.in_transaction:
            self.invalidate()
        if sql == "BEGIN" and self.pending is not None:
            raw, root = self.pending
            self.pending = None
            if (root is not None and root.is_active and connection.get_transaction() is root
                    and connection.connection.driver_connection is raw and raw.in_transaction):
                self.ticket = _OuterTicket(connection, raw, root)


def observe_outer_transaction(connection):
    """Install before caller BEGIN; never begin, connect, repair FK or return readiness.

    Unsupported existing/nested transactions refuse. An old Storage remains bound
    to its old ticket even when this observer later observes another real BEGIN.
    """
    if not isinstance(connection, Connection) or connection.closed or connection.invalidated:
        raise ContractError("CONNECTION_INVALID")
    raw = connection.connection.driver_connection
    if not isinstance(raw, sqlite3.Connection) or raw.in_transaction:
        raise ContractError("OUTER_PROVENANCE_REQUIRED")
    if connection.info.get("igq_abort_required"):
        raise RollbackUnknown("ABANDON_CONNECTION")
    old = connection.info.get("igq_outer_observer")
    if old is not None and old.connection is not connection:
        old.invalidate()
    if old is None or old.connection is not connection:
        connection.info["igq_outer_observer"] = _OuterObserver(connection)


def _require(connection, ticket=None):
    if not isinstance(connection, Connection) or connection.closed or connection.invalidated:
        raise ContractError("CONNECTION_INVALID")
    raw = connection.connection.driver_connection
    if (not isinstance(raw, sqlite3.Connection) or not connection.in_transaction()
            or not raw.in_transaction):
        raise ContractError("REAL_OUTER_TRANSACTION_REQUIRED")
    if connection.info.get("igq_abort_required"):
        raise RollbackUnknown("ABANDON_CONNECTION")
    observer = connection.info.get("igq_outer_observer")
    current = observer.ticket if type(observer) is _OuterObserver else None
    if (current is None or not current.active or current.connection is not connection
            or current.raw is not raw or current.root is not connection.get_transaction()
            or not current.root.is_active or connection.in_nested_transaction()
            or (ticket is not None and current is not ticket)):
        raise ContractError("OUTER_PROVENANCE_REQUIRED")
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 1:
        raise ContractError("FK_REQUIRED")
    return current


def check_schema(connection, tenant):
    """Read-only first-slice compatibility, never runtime readiness/authorization."""
    _require(connection)
    _text(tenant)
    for table in OWNED_TABLES:
        sql = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table.name,)
        ).scalar()
        expected = str(CreateTable(table).compile(dialect=connection.dialect))
        if sql is None or _normalized_sql(sql) != _normalized_sql(expected):
            raise ContractError("SCHEMA_INCOMPATIBLE")
        objects = connection.exec_driver_sql(
            "SELECT type,name FROM sqlite_master WHERE tbl_name=? AND sql IS NOT NULL AND type IN ('index','trigger')",
            (table.name,)
        ).all()
        if set(objects) != {("index", index.name) for index in table.indexes}:
            raise ContractError("SCHEMA_INCOMPATIBLE")
        for index in table.indexes:
            actual = connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (index.name,)
            ).scalar()
            expected_index = str(CreateIndex(index).compile(dialect=connection.dialect))
            if actual is None or _normalized_sql(actual) != _normalized_sql(expected_index):
                raise ContractError("SCHEMA_INCOMPATIBLE")
    parent = connection.exec_driver_sql("PRAGMA table_info(local_assets_inventory)").fetchall()
    cols = {r[1]: r for r in parent}
    if ("id" not in cols or cols["id"][2].upper() != "INTEGER" or cols["id"][5] != 1
            or "is_deleted" not in cols or cols["is_deleted"][2].upper() != "BOOLEAN"
            or cols["is_deleted"][3] != 1):
        raise ContractError("LEGACY_REFERENCE_INVALID")
    row = connection.execute(select(STORE)).mappings().one_or_none()
    if (row is None or row[T] != tenant or row["schema_revision"] != 1
            or row["preparation_state"] != "COMPLETE"
            or row["structure_digest"] != structure_digest(connection.dialect)):
        raise ContractError("STORE_NOT_COMPATIBLE")
    return {"structural_compatible": True, "runtime_enablement": False}


@dataclass(frozen=True)
class Head:
    tenant_id: str
    asset_id: int
    live_asset_id: int | None
    asset_state: str
    head_revision: int
    last_generation: int
    current_version_id: str | None
    current_binding_id: str | None
    current_generation: int | None
    current_operation_id: str | None
    current_proof_id: str | None
    qualification_status: str


@dataclass(frozen=True)
class Source:
    version_id: str
    binding_id: str
    sha256: bytes
    actual_size: int
    observation_ref: str
    source_descriptor: str
    source_observation_ref: str
    authorization_evidence_ref: str
    created_at: str

    def validate(self):
        _identity(self.version_id); _identity(self.binding_id)
        _digest(self.sha256); _integer(self.actual_size); _time(self.created_at)
        for name in ("observation_ref", "source_descriptor", "source_observation_ref", "authorization_evidence_ref"):
            _text(getattr(self, name))


@dataclass(frozen=True)
class Result:
    proof_id: str
    selected_stream: int
    profile_id: str
    policy_id: str
    checker_id: str
    tool_id: str
    evidence_summary: dict
    resource_evidence_ref: str
    recorded_at: str

    def payload(self):
        _identity(self.proof_id); _integer(self.selected_stream); _time(self.recorded_at)
        data = asdict(self)
        for name in ("profile_id", "policy_id", "checker_id", "tool_id", "resource_evidence_ref"):
            _text(data[name])
        data["evidence_summary"] = _json(self.evidence_summary)
        data["technical_complete"] = 1
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).digest()
        return dict(data, result_digest=digest)


class Storage:
    """Sanctioned synthetic storage operations; no outer transaction ownership."""

    def __init__(self, connection, tenant):
        check_schema(connection, tenant)
        self.connection, self.tenant = connection, tenant
        self._ticket = _require(connection)
        self._attempt = None
        if not event.contains(connection, "commit", _prevent_poisoned_commit):
            event.listen(connection, "commit", _prevent_poisoned_commit)

    def _guard(self):
        _require(self.connection, self._ticket)
        check_schema(self.connection, self.tenant)

    def head(self, asset):
        _require(self.connection, self._ticket); _integer(asset, 1)
        row = self.connection.execute(select(HEAD).where(HEAD.c.tenant_id == self.tenant,
                                                        HEAD.c.asset_id == asset)).mappings().one_or_none()
        return Head(**row) if row else None

    def _parent(self, asset, state):
        return exists(select(LEGACY.c.id).where(LEGACY.c.id == asset,
                                               LEGACY.c.is_deleted == int(state == "TRASHED")))

    def _expected(self, expected):
        if type(expected) is not Head or expected.tenant_id != self.tenant:
            raise Conflict("EXPECTED_HEAD_INVALID")
        _integer(expected.asset_id, 1)
        for name in ("head_revision", "last_generation"):
            _integer(getattr(expected, name))
        for name in ("live_asset_id", "current_generation"):
            if getattr(expected, name) is not None:
                _integer(getattr(expected, name), 1)
        for name in ("current_version_id", "current_binding_id", "current_operation_id", "current_proof_id"):
            if getattr(expected, name) is not None:
                _identity(getattr(expected, name))
        if expected.qualification_status not in STATES:
            raise ContractError("QUALIFICATION_STATE_INVALID")
        if self.head(expected.asset_id) != expected or expected.asset_state == "PURGED":
            raise Conflict("STALE_OR_RETIRED_HEAD")

    def _op(self, operation):
        return self.connection.execute(select(OPERATION).where(OPERATION.c.tenant_id == self.tenant,
            OPERATION.c.operation_id == operation)).mappings().one_or_none()

    @contextmanager
    def _atomic(self):
        _require(self.connection, self._ticket)
        observer = self.connection.info["igq_outer_observer"]
        nested = None
        self._attempt = {"written": False}
        try:
            observer.local_control = True
            try:
                nested = self.connection.begin_nested()
            finally:
                observer.local_control = False
            yield
            observer.local_control = True
            try:
                nested.commit()  # RELEASE only, never outer COMMIT.
            finally:
                observer.local_control = False
            _require(self.connection, self._ticket)
        except BaseException as error:
            try:
                if nested is None or not nested.is_active:
                    raise RuntimeError("SAVEPOINT_OUTCOME_UNKNOWN")
                observer.local_control = True
                try:
                    nested.rollback()
                finally:
                    observer.local_control = False
                _require(self.connection, self._ticket)
            except BaseException:
                self.connection.info["igq_abort_required"] = True
                raise RollbackUnknown("LOCAL_ROLLBACK_UNKNOWN") from None
            if isinstance(error, ContractError) and not self._attempt["written"]:
                raise
            reason = str(error) if isinstance(error, ContractError) else "DEPENDENT_WRITE_FAILED"
            raise AbortOperation("ASSOCIATED_ATOMIC_ABORT_REQUIRED:" + reason) from None
        finally:
            observer.local_control = False
            self._attempt = None

    def _one(self, statement):
        if self.connection.execute(statement).rowcount != 1:
            raise Conflict("CONDITIONAL_WRITE_REJECTED")
        if self._attempt is not None:
            self._attempt["written"] = True

    def _reserve(self, expected, op=None, parent_state=None):
        if expected.head_revision == MAX_INT:
            raise ContractError("REVISION_OVERFLOW")
        terms = [HEAD.c[k].is_(None) if v is None else HEAD.c[k] == v
                 for k, v in asdict(expected).items()]
        terms.append(self._parent(expected.asset_id, parent_state or expected.asset_state))
        if op is not None:
            terms.append(exists(select(OPERATION.c.operation_id).where(*[
                OPERATION.c[k].is_(None) if op[k] is None else OPERATION.c[k] == op[k]
                for k in (T,A,V,B,G,O,"completion_state","retired","result_digest")
            ])))
        self._one(update(HEAD).where(and_(*terms)).values(head_revision=expected.head_revision + 1))

    def _finish_head(self, asset, **values):
        self._one(update(HEAD).where(HEAD.c.tenant_id == self.tenant, HEAD.c.asset_id == asset).values(**values))

    def _retire_op(self, op, reason, at):
        if op is not None:
            self._one(update(OPERATION).where(OPERATION.c.tenant_id == self.tenant,
                OPERATION.c.operation_id == op[O], OPERATION.c.retired == 0).values(
                retired=1, retired_reason=reason, retired_at=at))

    def start(self, asset, source, operation, key_digest, request_digest, *, expected=None, replace_current=False):
        self._guard(); _integer(asset, 1); _identity(operation)
        _digest(key_digest); _digest(request_digest)
        if type(source) is not Source or type(replace_current) is not bool:
            raise ContractError("START_INPUT_INVALID")
        source.validate()
        current = self.head(asset)
        if current != expected or (expected is not None and expected.asset_id != asset):
            raise Conflict("EXPECTED_HEAD_MISMATCH")
        old = None
        if current:
            self._expected(expected)
            old = self._op(current.current_operation_id) if current.current_operation_id else None
            if not replace_current:
                raise Conflict("EXPLICIT_REPLACEMENT_REQUIRED")
            if current.last_generation == MAX_INT:
                raise ContractError("GENERATION_OVERFLOW")
        if not self.connection.execute(select(self._parent(asset, "LIVE"))).scalar():
            raise Conflict("LIVE_PARENT_REQUIRED")
        if self.connection.execute(select(OPERATION.c.operation_id).where(
                OPERATION.c.tenant_id == self.tenant, OPERATION.c.request_key_digest == key_digest)).first():
            raise Conflict("REQUEST_KEY_ALREADY_USED")
        generation = (current.last_generation if current else 0) + 1
        with self._atomic():
            if current:
                self._reserve(expected, old, "LIVE")
                self._retire_op(old, "EXPLICIT_REPLACEMENT", source.created_at)
            else:
                self.connection.execute(HEAD.insert().values(tenant_id=self.tenant, asset_id=asset,
                    live_asset_id=asset, asset_state="LIVE", head_revision=0, last_generation=0,
                    qualification_status="NOT_QUALIFIED"))
                self._attempt["written"] = True
            c = dict(tenant_id=self.tenant, asset_id=asset, version_id=source.version_id,
                     sha256=source.sha256, actual_size=source.actual_size,
                     observation_ref=source.observation_ref, created_at=source.created_at)
            present = self.connection.execute(select(CONTENT).where(CONTENT.c.tenant_id == self.tenant,
                CONTENT.c.asset_id == asset, CONTENT.c.version_id == source.version_id)).mappings().one_or_none()
            if present:
                if any(present[k] != c[k] for k in ("sha256", "actual_size")):
                    raise Conflict("CONTENT_IDENTITY_CONFLICT")
            else:
                self.connection.execute(CONTENT.insert().values(**c))
            binding = dict(tenant_id=self.tenant, asset_id=asset,
                binding_id=source.binding_id, version_id=source.version_id,
                source_descriptor=source.source_descriptor, source_observation_ref=source.source_observation_ref,
                authorization_evidence_ref=source.authorization_evidence_ref, created_at=source.created_at)
            previous_binding = self.connection.execute(select(BINDING).where(
                BINDING.c.tenant_id == self.tenant, BINDING.c.asset_id == asset,
                BINDING.c.binding_id == source.binding_id)).mappings().one_or_none()
            if previous_binding is not None:
                if (current is None or not replace_current or
                        current.current_version_id != source.version_id or
                        current.current_binding_id != source.binding_id):
                    raise Conflict("HISTORICAL_BINDING_REUSE_REJECTED")
                if dict(present) != c:
                    raise Conflict("CONTENT_IDENTITY_CONFLICT")
                if dict(previous_binding) != binding:
                    raise Conflict("BINDING_IDENTITY_CONFLICT")
                # Explicit same-source requalification: preserve C/B, one new G/O.
            else:
                self.connection.execute(BINDING.insert().values(**binding))
            self.connection.execute(OPERATION.insert().values(tenant_id=self.tenant, asset_id=asset,
                operation_id=operation, generation=generation, version_id=source.version_id,
                binding_id=source.binding_id, start_head_revision=current.head_revision if current else 0,
                request_key_digest=key_digest, request_digest=request_digest, completion_state="OPEN",
                retired=0, created_at=source.created_at))
            self._finish_head(asset, asset_state="LIVE", current_version_id=source.version_id,
                current_binding_id=source.binding_id, current_generation=generation,
                current_operation_id=operation, current_proof_id=None, last_generation=generation,
                qualification_status="NOT_QUALIFIED")
        return self.head(asset)

    def complete(self, expected, result):
        self._guard(); self._expected(expected)
        if type(result) is not Result:
            raise ContractError("COMPLETE_EVIDENCE_REQUIRED")
        payload = result.payload()
        op = self._op(expected.current_operation_id)
        if op is None or op["retired"] or expected.asset_state != "LIVE":
            raise Conflict("COMPLETION_NOT_ALLOWED")
        identity = dict(zip(AVBGO, (self.tenant, expected.asset_id, expected.current_version_id,
            expected.current_binding_id, expected.current_generation, expected.current_operation_id)))
        if any(op[k] != v for k, v in identity.items()):
            raise Conflict("OPERATION_BINDING_MISMATCH")
        if op["completion_state"] == "RESULT_ACCEPTED":
            if not self.connection.execute(select(self._parent(expected.asset_id, "LIVE"))).scalar():
                raise Conflict("DUPLICATE_PARENT_UNAVAILABLE")
            old = self.connection.execute(select(PROOF).where(PROOF.c.tenant_id == self.tenant,
                PROOF.c.operation_id == op[O])).mappings().one_or_none()
            if (old is None or expected.current_proof_id != result.proof_id
                    or any(old[k] != v for k, v in payload.items())
                    or op["result_digest"] != payload["result_digest"]):
                raise Conflict("CONFLICTING_COMPLETION")
            return expected  # No savepoint, reservation, revision or DML.
        if op["completion_state"] != "OPEN" or expected.current_proof_id is not None:
            raise Conflict("LIFECYCLE_REJECTED")
        with self._atomic():
            self._reserve(expected, op)
            self._one(update(OPERATION).where(OPERATION.c.tenant_id == self.tenant,
                OPERATION.c.operation_id == op[O], OPERATION.c.completion_state == "OPEN",
                OPERATION.c.retired == 0).values(completion_state="RESULT_ACCEPTED",
                result_digest=payload["result_digest"], completed_at=result.recorded_at))
            self.connection.execute(PROOF.insert().values(**identity, **payload))
            self._finish_head(expected.asset_id, current_proof_id=result.proof_id)
        return self.head(expected.asset_id)

    def fail(self, expected, summary, at):
        self._guard(); self._expected(expected); _time(at)
        summary = _json(summary)
        op = self._op(expected.current_operation_id)
        if op is None or op["retired"] or op["completion_state"] != "OPEN":
            raise Conflict("FAILURE_NOT_ALLOWED")
        with self._atomic():
            self._reserve(expected, op)
            self._one(update(OPERATION).where(OPERATION.c.tenant_id == self.tenant,
                OPERATION.c.operation_id == op[O], OPERATION.c.completion_state == "OPEN",
                OPERATION.c.retired == 0).values(completion_state="FAILURE_ACCEPTED",
                failure_summary=summary, result_digest=hashlib.sha256(summary.encode()).digest(), completed_at=at))
        return self.head(expected.asset_id)

    def retire(self, expected, state, reason, at, *, invalidation_evidence=None):
        self._guard(); self._expected(expected); _text(reason); _time(at)
        if state not in ("LIVE", "TRASHED", "PURGED"):
            raise ContractError("STATE_INVALID")
        if state == "PURGED" and expected.asset_state != "TRASHED":
            raise Conflict("TRASH_REQUIRED")
        if invalidation_evidence is not None:
            _text(invalidation_evidence)
            if expected.current_version_id is None and expected.qualification_status != "INVALIDATED":
                raise ContractError("INVALIDATION_FACT_NOT_ESTABLISHED")
        status = "INVALIDATED" if invalidation_evidence is not None else expected.qualification_status
        op = self._op(expected.current_operation_id) if expected.current_operation_id else None
        with self._atomic():
            self._reserve(expected, op, "TRASHED" if state == "PURGED" else state)
            self._retire_op(op, _json({"reason": reason, "evidence": invalidation_evidence or "NOT_ESTABLISHED"}), at)
            changes = dict(asset_state=state, current_generation=None, current_operation_id=None,
                           current_proof_id=None, qualification_status=status)
            if state == "PURGED":
                changes.update(live_asset_id=None, current_version_id=None, current_binding_id=None)
            self._finish_head(expected.asset_id, **changes)
        return self.head(expected.asset_id)

    def record_unknown(self, operation, kind, correlation, observation, *, owner=None):
        self._guard(); _identity(operation); _text(correlation)
        if kind not in ("PROCESS", "READER", "PIPE", "HANDLE"):
            raise ContractError("RESOURCE_KIND_INVALID")
        if owner is not None:
            _text(owner)
        values = dict(tenant_id=self.tenant, operation_id=operation, resource_kind=kind,
            correlation_ref=correlation, responsibility_state="UNKNOWN", existing_owner_ref=owner,
            observation_summary=_json(observation), resolution_evidence_ref=None)
        if self._op(operation) is None:
            raise Conflict("RESPONSIBILITY_PARENT_MISSING")
        old = self.connection.execute(select(RESPONSIBILITY).where(*[
            RESPONSIBILITY.c[k] == values[k] for k in (T,O,"resource_kind","correlation_ref")
        ])).mappings().one_or_none()
        if old:
            if dict(old) != values:
                raise Conflict("RESPONSIBILITY_CONFLICT")
            return "DUPLICATE_NO_WRITE"
        with self._atomic():
            self.connection.execute(RESPONSIBILITY.insert().values(**values))
        return "PROVISIONAL_UNKNOWN_RECORD"
