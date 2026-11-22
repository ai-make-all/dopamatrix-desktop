"""Authorized P2-only temporary SQLite tests. No Main/ASGI/native imports."""
import ast
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/api/import_qualification.py"
OS_TEMP = Path(os.environ.get("TEMP") or os.environ["TMP"]).resolve(strict=True)
AT = "2026-11-22T00:00:00+00:00"
EVIDENCE = {"level": "ISOLATED_SYNTHETIC_STORAGE", "competition": [], "topology": {}}


class Guard:
    def __init__(self):
        self.roots, self.created, self.cleaned = [], [], []
        self.connects, self.closed, self.trace, self.events = [], [], [], []
        self.violations, self.probes, self.dependency_denials = [], [], []
        self.phase = "DEPENDENCY_IMPORT"
        self.creating = False
        self.probing = False
        self.core_attempts = dict(engine=0, connection=0, commit=0, sqlite_connect=0)

    def core_frame(self):
        f = sys._getframe(1)
        while f:
            if f.f_code.co_filename == str(TARGET):
                return True
            f = f.f_back
        return False

    def owned(self, value):
        if not isinstance(value, (str, bytes, os.PathLike)) or isinstance(value, bytes):
            return False
        path = Path(value).resolve()
        return any(path == r or path.is_relative_to(r) for r in self.roots)

    def deny(self, event):
        destination = self.probes if self.probing else (
            self.dependency_denials if self.phase == "DEPENDENCY_IMPORT" else self.violations)
        destination.append(event)
        if not self.probing:
            frame, chain = sys._getframe(1), []
            while frame and len(chain) < 8:
                chain.append(Path(frame.f_code.co_filename).name + ":" + frame.f_code.co_name)
                frame = frame.f_back
            print("GUARD_REJECTED=" + json.dumps({"event": event, "source": chain}))
        raise PermissionError("IGQ_GUARD_" + event)

    def audit(self, event, args):
        if event.startswith("socket.") or event in ("subprocess.Popen", "os.system", "os.startfile", "os.startfile/2", "pty.spawn") or event.startswith(("os.exec", "os.spawn", "os.posix_spawn")):
            self.deny(event)
        if event == "sqlite3.connect":
            path = args[0]
            core = self.core_frame()
            if core:
                self.core_attempts["sqlite_connect"] += 1
            if core or not isinstance(path, str) or path.startswith("file:") or "?" in path or not self.owned(path):
                self.deny(event)
            self.connects.append(str(Path(path).resolve()))
        if event in ("sqlite3.enable_load_extension", "sqlite3.load_extension"):
            self.deny(event)
        if event == "os.mkdir":
            p = Path(args[0]).resolve()
            if self.creating and p.parent == OS_TEMP and p.name.startswith("igq-i1r0-") and not p.exists():
                self.roots.append(p)
            elif not self.owned(p):
                self.deny(event)
        if event == "open":
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if writing and not self.owned(path):
                self.deny("file_write")
        if event in ("os.remove", "os.rmdir", "shutil.rmtree") and not self.owned(args[0]):
            self.deny(event)
        if event in ("os.rename", "os.replace") and not all(self.owned(p) for p in args[:2]):
            self.deny(event)

    def sql(self, statement, core):
        verb = statement.lstrip().split(None, 1)[0].upper()
        if core and (verb in ("BEGIN", "COMMIT", "END") or
                     (verb == "ROLLBACK" and not statement.lstrip().upper().startswith("ROLLBACK TO SAVEPOINT"))):
            self.deny("core_outer_transaction")
        if verb in ("ATTACH", "DETACH", "VACUUM") or "LOAD_EXTENSION" in statement.upper():
            self.deny("sql_external")
        if verb in ("CREATE", "ALTER", "DROP"):
            if core:
                self.deny("core_ddl")
            targets = re.findall(r"(?:TABLE|INDEX|TRIGGER)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?[\"`]?([\w]+)", statement, re.I)
            permitted = OWNED_NAMES | {"local_assets_inventory", "igq_operation_retired", "igq_responsibility_state", "igq_fixture_extra"}
            if not targets or any(n not in permitted for n in targets):
                self.deny("ddl_target")
        if core and verb in ("INSERT", "UPDATE", "DELETE"):
            match = re.search(r"(?:INTO|UPDATE|FROM)\s+[\"`]?([\w]+)", statement, re.I)
            if not match or match[1] not in OWNED_NAMES:
                self.deny("core_parent_write")


GUARD = Guard()
sys.addaudithook(GUARD.audit)  # Before SQLAlchemy and actual target execution.

import sqlalchemy as sa
from sqlalchemy.pool import NullPool

# These operations were still denied, never exempted. Keep dependency probes
# separate from target execution and tests, without dropping their evidence.
GUARD.phase = "TARGET_AND_TESTS"

_fixture_create_engine = sa.create_engine


def guarded_create_engine(*args, **kwargs):
    if GUARD.core_frame():
        GUARD.core_attempts["engine"] += 1
        GUARD.deny("core_engine")
    return _fixture_create_engine(*args, **kwargs)


sa.create_engine = guarded_create_engine


@sa.event.listens_for(sa.engine.Engine, "engine_connect")
def guarded_connection(connection):
    if GUARD.core_frame():
        GUARD.core_attempts["connection"] += 1
        GUARD.deny("core_connection")

OWNED_NAMES = {"igq_store", "igq_asset_head", "igq_content_version", "igq_source_binding",
               "igq_operation", "igq_proof", "igq_resource_responsibility"}


def load_target(name):
    assert name not in sys.modules
    before = (len(GUARD.connects), len(GUARD.trace), len(GUARD.violations))
    spec = importlib.util.spec_from_file_location(name, TARGET)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # Real top-level execution, not cached import/AST.
    assert before == (len(GUARD.connects), len(GUARD.trace), len(GUARD.violations))
    return module


q = load_target("igq_i1_runtime_target")


def ident(n):
    return f"{n:032x}"


def digest(n):
    return hashlib.sha256(str(n).encode()).digest()


def source(n=1, version=None):
    return q.Source(ident(version or n), ident(100+n), digest(version or n), 3,
                    "synthetic-observation", "synthetic-source", "synthetic-binding", "synthetic-not-authority", AT)


def result(n=1):
    return q.Result(ident(1000+n), 0, "synthetic-profile", "synthetic-policy",
                    "synthetic-checker", "synthetic-tool", {"test": "synthetic-only"}, "synthetic-resource-not-release", AT)


class Database:
    def __init__(self, fk=True, prepare=True):
        GUARD.creating = True
        try:
            self.temp = tempfile.TemporaryDirectory(prefix="igq-i1r0-", dir=OS_TEMP)
        finally:
            GUARD.creating = False
        self.root = Path(self.temp.name).resolve(strict=True)
        assert self.root.parent == OS_TEMP and not self.root.is_relative_to(ROOT)
        assert not self.root.stat().st_file_attributes & 0x400
        self.path = self.root / "fixture.sqlite"
        assert not self.path.exists() and GUARD.owned(self.path)
        self.engine = sa.create_engine("sqlite:///" + self.path.as_posix(), poolclass=NullPool,
            connect_args={"check_same_thread": False, "timeout": 1.0})
        self.fk, self.connections = fk, []

        @sa.event.listens_for(self.engine, "connect")
        def connect(raw, record):
            cid = id(raw)
            raw.set_trace_callback(lambda sql: GUARD.trace.append((cid, sql)))
            raw.set_authorizer(lambda action, a, b, db, origin:
                sqlite3.SQLITE_DENY if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH) else sqlite3.SQLITE_OK)
            if self.fk:
                raw.execute("PRAGMA foreign_keys=ON")

        @sa.event.listens_for(self.engine, "close")
        def close(raw, record):
            GUARD.closed.append(id(raw))

        @sa.event.listens_for(self.engine, "before_cursor_execute")
        def sql(conn, cursor, statement, parameters, context, many):
            core = GUARD.core_frame()
            GUARD.sql(statement, core)
            GUARD.events.append((id(conn.connection.driver_connection), statement, core))

        @sa.event.listens_for(self.engine, "commit")
        def commit(conn):
            if GUARD.core_frame():
                GUARD.core_attempts["commit"] += 1
                GUARD.deny("core_commit")

        with self.engine.begin() as c:
            meta = sa.MetaData()
            parent = sa.Table("local_assets_inventory", meta,
                sa.Column("id", sa.Integer, primary_key=True),
                sa.Column("is_deleted", sa.Boolean, nullable=False),
                sa.Column("file_hash", sa.Text, nullable=False, unique=True))
            meta.create_all(c, tables=[parent])  # Synthetic parent, never q.LEGACY.
            if prepare:
                q.METADATA.create_all(c, tables=list(q.OWNED_TABLES))
                c.execute(q.STORE.insert().values(slot=1, tenant_id="tenant-a", schema_revision=1,
                    preparation_state="COMPLETE", preparation_attempt="synthetic-prepare",
                    structure_digest=q.structure_digest(c.dialect), completion_evidence_ref="synthetic-not-readiness", completed_at=AT))

    def connection(self, real=True):
        c = self.engine.connect()
        self.connections.append(c)
        q.observe_outer_transaction(c)
        c.begin()
        if real:
            c.exec_driver_sql("BEGIN")
        return c

    def parent(self, c, asset=1, deleted=False):
        c.exec_driver_sql("INSERT INTO local_assets_inventory(id,is_deleted,file_hash) VALUES (?,?,?)",
                         (asset, int(deleted), f"synthetic-{asset}"))

    def close(self):
        for c in self.connections:
            c.close()
        self.engine.dispose()
        assert self.root in GUARD.roots and self.root.parent == OS_TEMP
        assert not self.root.stat().st_file_attributes & 0x400
        GUARD.created.append(str(self.root))
        self.temp.cleanup()
        assert not self.root.exists()
        GUARD.cleaned.append(str(self.root))


@pytest.fixture
def db():
    fixture = Database()
    try:
        yield fixture
    finally:
        fixture.close()


def flow(db, c=None):
    c = c or db.connection()
    db.parent(c)
    s = q.Storage(c, "tenant-a")
    h = s.start(1, source(), ident(201), digest(301), digest(401))
    return c, s, h


def snapshot(c):
    return {t.name: [tuple(r) for r in c.execute(sa.select(t).order_by(*t.primary_key.columns))]
            for t in q.OWNED_TABLES}


def dml_count():
    return sum(bool(re.match(r"\s*(INSERT|UPDATE|DELETE)\b", s, re.I)) for _, s, _ in GUARD.events)


def reject_unchanged(c, call, error=q.ContractError):
    before, count = snapshot(c), dml_count()
    with pytest.raises(error):
        call()
    assert snapshot(c) == before
    return dml_count() - count


@pytest.mark.parametrize("change", [
    {"current_version_id": None}, {"current_binding_id": None},
    {"current_generation": None}, {"current_operation_id": None},
    {"current_proof_id": ident(999)}, {"live_asset_id": None},
    {"asset_state": "PURGED"}, {"current_generation": 2},
    {"head_revision": -1}, {"head_revision": 1.5},
    {"current_version_id": "G"*32}, {"qualification_status": "PASS"},
    {"qualification_status": "PENDING_ACK"},
    {"asset_state": "TRASHED"}, {"live_asset_id": 2},
    {"current_operation_id": ident(999)}, {"current_binding_id": ident(999)},
    {"current_binding_id": "B"*32}, {"current_operation_id": "O"*32},
    {"current_proof_id": "P"*32},
    {"current_version_id": None, "current_binding_id": None},
    {"current_generation": None, "current_operation_id": None, "current_proof_id": ident(1001)},
])
def test_c01_head_constraints(db, change):
    c, s, h = flow(db)
    before = snapshot(c)
    with c.begin_nested() as sp:
        with pytest.raises(sa.exc.IntegrityError):
            c.execute(q.HEAD.update().values(**change))
        sp.rollback()
    assert snapshot(c) == before


@pytest.mark.parametrize("table,changes", [
    ("content", {"tenant_id": "tenant-b"}), ("content", {"asset_id": 2}),
    ("content", {"version_id": "x"*32}), ("content", {"sha256": b"short"}),
    ("content", {"sha256": "a"*32}), ("content", {"actual_size": 1.25}),
    ("proof", {"asset_id": 2}), ("proof", {"version_id": ident(2)}),
    ("proof", {"binding_id": ident(999)}), ("proof", {"operation_id": ident(999)}),
    ("proof", {"generation": 2}), ("proof", {"proof_id": "Q"*32}),
])
def test_c01_row_constraints(db, table, changes):
    c, s, h = flow(db)
    if table == "content":
        target = q.CONTENT
        values = dict(c.execute(sa.select(target)).mappings().one())
        values["version_id"] = ident(42)
    else:
        target = q.PROOF
        values = dict(tenant_id="tenant-a", asset_id=1, version_id=h.current_version_id,
            binding_id=h.current_binding_id, generation=h.current_generation,
            operation_id=h.current_operation_id, **result().payload())
    values.update(changes)
    before = snapshot(c)
    sp = c.begin_nested()
    with pytest.raises(sa.exc.IntegrityError):
        if isinstance(values.get("sha256"), str):
            # Bypass SQLAlchemy's Binary processor to reach the actual SQLite CHECK.
            columns = list(values)
            c.exec_driver_sql("INSERT INTO " + target.name + " (" + ",".join(columns) +
                              ") VALUES (" + ",".join("?" for _ in columns) + ")",
                              tuple(values[k] for k in columns))
        else:
            c.execute(target.insert().values(**values))
    sp.rollback()
    assert snapshot(c) == before


def test_c01_required_unique_keys(db):
    c, s, h = flow(db)
    inspector = sa.inspect(c)
    expected = {q.STORE: [("tenant_id",)], q.HEAD: [("live_asset_id",)],
        q.BINDING: [(q.T,q.A,q.V,q.B)],
        q.OPERATION: [(q.T,q.A,q.G),q.AVBGO,(q.T,"request_key_digest")],
        q.PROOF: [(q.T,q.O),(*q.AVBGO,q.P)]}
    for table, keys in expected.items():
        actual = {tuple(x["column_names"]) for x in inspector.get_unique_constraints(table.name)}
        assert set(keys) <= actual
    op = dict(c.execute(sa.select(q.OPERATION)).mappings().one())
    for changes in ({"operation_id": ident(999)}, {"operation_id": ident(999), "generation": 2}):
        sp = c.begin_nested()
        with pytest.raises(sa.exc.IntegrityError):
            c.execute(q.OPERATION.insert().values(**dict(op, **changes)))
        sp.rollback()
    assert all(not col.nullable for t in q.OWNED_TABLES for col in t.primary_key)
    EVIDENCE["physical"] = {t.name: {
        "pk": inspector.get_pk_constraint(t.name)["constrained_columns"],
        "foreign_keys": len(inspector.get_foreign_keys(t.name)),
        "unique_keys": [u["column_names"] for u in inspector.get_unique_constraints(t.name)],
        "checks": len(inspector.get_check_constraints(t.name))} for t in q.OWNED_TABLES}


def test_c01_live_anchor_requires_actual_parent(db):
    c = db.connection()
    before = snapshot(c)
    sp = c.begin_nested()
    with pytest.raises(sa.exc.IntegrityError, match="FOREIGN KEY"):
        c.execute(q.HEAD.insert().values(tenant_id="tenant-a", asset_id=999,
            live_asset_id=999, asset_state="LIVE", head_revision=0, last_generation=0,
            qualification_status="NOT_QUALIFIED"))
    sp.rollback()
    assert snapshot(c) == before


@pytest.mark.parametrize("value", [True, 1.0, -1, 2**63, "1"])
def test_c01_python_integer_refusal(db, value):
    c, s, h = flow(db)
    assert reject_unchanged(c, lambda: s.start(value, source(2), ident(202), digest(302), digest(402))) == 0


@pytest.mark.parametrize("field", ["head_revision", "last_generation"])
def test_c01_overflow(db, field):
    c, s, h = flow(db)
    c.execute(q.HEAD.update().values(**{field: q.MAX_INT}))
    h = s.head(1)
    before = snapshot(c)
    with pytest.raises(q.ContractError, match="OVERFLOW"):
        s.start(1, source(2), ident(202), digest(302), digest(402), expected=h, replace_current=True)
    assert snapshot(c) == before


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "tenant-b"), ("asset_id", 2), ("live_asset_id", 2),
    ("head_revision", 1), ("last_generation", 2), ("asset_state", "TRASHED"),
    ("current_version_id", ident(42)), ("current_binding_id", ident(42)),
    ("current_generation", 2), ("current_operation_id", ident(42)),
    ("current_proof_id", ident(42)), ("qualification_status", "INVALIDATED"),
])
def test_c02_each_cas_fact(db, field, value):
    c, s, h = flow(db)
    bad = replace(h, **{field: value})
    # Direct real SQL helper isolates the complete conditional predicate itself.
    before = snapshot(c)
    with pytest.raises(q.Conflict, match="CONDITIONAL_WRITE"):
        s._reserve(bad, s._op(h.current_operation_id))
    assert snapshot(c) == before
    # Public known-stale path must also reject without business DML.
    assert reject_unchanged(c, lambda: s.complete(bad, result())) == 0


def test_c02_explicit_replacement_and_binding(db):
    c, s, h = flow(db)
    assert reject_unchanged(c, lambda: s.start(1, source(2), ident(202), digest(302), digest(402), expected=h)) == 0
    newer = s.start(1, source(2, version=1), ident(202), digest(302), digest(402), expected=h, replace_current=True)
    assert newer.last_generation == 2 and newer.current_version_id == h.current_version_id
    assert newer.current_binding_id != h.current_binding_id and s._op(h.current_operation_id)["retired"] == 1
    assert reject_unchanged(c, lambda: s.complete(h, result())) == 0
    assert reject_unchanged(c, lambda: s.start(1, source(3), ident(203), digest(301), digest(403), expected=newer, replace_current=True)) == 0


def test_c02_real_competing_connections(db):
    c, s, h = flow(db)
    s.record_unknown(h.current_operation_id, "PIPE", "competition-history", {"state": "unknown"})
    initial = snapshot(c)
    old_operation = dict(s._op(h.current_operation_id))
    c.commit()
    event_start = len(GUARD.events)  # Exclude recycled DBAPI ids from prior connections.
    barrier = threading.Barrier(2, timeout=5)
    outcomes, identities, expected = [], [], []
    def worker(n):
        conn = db.connection()
        try:
            store = q.Storage(conn, "tenant-a")
            observed = store.head(1)
            identities.append(id(conn.connection.driver_connection)); expected.append(asdict(observed))
            assert observed == h
            barrier.wait()
            try:
                out = store.start(1, source(n), ident(200+n), digest(300+n), digest(400+n),
                                  expected=observed, replace_current=True)
                conn.commit(); outcomes.append((n, "COMMITTED", out.current_operation_id))
            except (q.Conflict, q.AbortOperation) as exc:
                conn.rollback(); outcomes.append((n, type(exc).__name__, None))
        finally:
            conn.close()
    threads = [threading.Thread(target=worker, args=(n,)) for n in (2,3)]
    for t in threads: t.start()
    for t in threads: t.join(8)
    assert all(not t.is_alive() for t in threads) and len(outcomes) == 2
    assert len(set(identities)) == 2 and expected[0] == expected[1]
    assert sum(o[1] == "COMMITTED" for o in outcomes) <= 1
    attempts = [x for x in GUARD.events[event_start:] if x[0] in identities and re.match(r"UPDATE igq_asset_head SET head_revision=", x[1])]
    assert len(attempts) == 2  # No refreshed retry; both reached actual conditional DML.
    read = db.connection()
    final = q.Storage(read, "tenant-a").head(1)
    final_state = snapshot(read)
    winners = [o for o in outcomes if o[1] == "COMMITTED"]
    if winners:
        winner = winners[0][0]
        loser = 3 if winner == 2 else 2
        assert final.current_operation_id == ident(200+winner)
        assert final.current_version_id == source(winner).version_id
        assert final.current_binding_id == source(winner).binding_id
        assert final.current_generation == final.last_generation == h.last_generation + 1
        assert final.head_revision == h.head_revision + 1 and final.current_proof_id is None
        assert final == replace(h, head_revision=h.head_revision+1, last_generation=h.last_generation+1,
            current_version_id=source(winner).version_id, current_binding_id=source(winner).binding_id,
            current_generation=h.last_generation+1, current_operation_id=ident(200+winner))
        ops = list(read.execute(sa.select(q.OPERATION)).mappings())
        assert len(ops) == 2 and next(o for o in ops if o[q.O] == h.current_operation_id)["retired"] == 1
        historical = dict(next(o for o in ops if o[q.O] == h.current_operation_id))
        assert historical == dict(old_operation, retired=1, retired_reason="EXPLICIT_REPLACEMENT", retired_at=AT)
        winning = next(o for o in ops if o[q.O] == final.current_operation_id)
        assert dict(winning) == dict(tenant_id="tenant-a", asset_id=1, operation_id=ident(200+winner),
            generation=h.last_generation+1, version_id=source(winner).version_id,
            binding_id=source(winner).binding_id, start_head_revision=h.head_revision,
            request_key_digest=digest(300+winner), request_digest=digest(400+winner),
            completion_state="OPEN", retired=0, result_digest=None, failure_summary=None,
            retired_reason=None, created_at=AT, completed_at=None, retired_at=None)
        assert not any(o[q.O] == ident(200+loser) or o["request_key_digest"] == digest(300+loser) for o in ops)
        assert read.execute(sa.select(sa.func.count()).select_from(q.CONTENT)).scalar() == 2
        assert read.execute(sa.select(sa.func.count()).select_from(q.BINDING)).scalar() == 2
        assert not read.execute(sa.select(q.CONTENT).where(q.CONTENT.c.version_id == source(loser).version_id)).first()
        assert not read.execute(sa.select(q.BINDING).where(q.BINDING.c.binding_id == source(loser).binding_id)).first()
        assert final_state[q.PROOF.name] == initial[q.PROOF.name]
        assert final_state[q.STORE.name] == initial[q.STORE.name]
        assert final_state[q.RESPONSIBILITY.name] == initial[q.RESPONSIBILITY.name]
        assert set(initial[q.CONTENT.name]) <= set(final_state[q.CONTENT.name])
        assert set(initial[q.BINDING.name]) <= set(final_state[q.BINDING.name])
    else:
        assert final_state == initial
    EVIDENCE["competition"].append({"connection_ids": identities, "same_expected": True,
        "outcomes": outcomes, "conditional_attempts": len(attempts), "final_generation": final.last_generation,
        "full_durable_readback": True, "loser_residue": False})


def test_c03_duplicate_conflict_and_missing_evidence(db):
    c, s, h = flow(db)
    done = s.complete(h, result())
    before, count = snapshot(c), dml_count()
    assert s.complete(done, result()) == done
    assert snapshot(c) == before and dml_count() == count
    assert reject_unchanged(c, lambda: s.complete(done, replace(result(), policy_id="conflict"))) == 0
    assert reject_unchanged(c, lambda: s.complete(done, replace(result(), evidence_summary={}))) == 0
    assert reject_unchanged(c, lambda: s.complete(done, {"result_digest": result().payload()["result_digest"]})) == 0
    assert reject_unchanged(c, lambda: s.fail(done, {"failure": "late"}, AT)) == 0
    newer = s.start(1, source(2), ident(202), digest(302), digest(402), expected=done, replace_current=True)
    assert reject_unchanged(c, lambda: s.complete(done, result())) == 0
    assert newer.current_proof_id is None


def test_c03_failure_lifecycle(db):
    c, s, h = flow(db)
    failed = s.fail(h, {"failure": "synthetic"}, AT)
    assert s._op(failed.current_operation_id)["completion_state"] == "FAILURE_ACCEPTED"
    assert reject_unchanged(c, lambda: s.complete(failed, result())) == 0


def test_c03_retired_operation_with_unchanged_head(db):
    c, s, h = flow(db)
    c.execute(q.OPERATION.update().values(retired=1, retired_reason="synthetic-retirement", retired_at=AT))
    # Head remains identical, so refusal reaches the operation retirement predicate.
    assert s.head(1) == h
    assert reject_unchanged(c, lambda: s.complete(h, result())) == 0


def test_c04_outer_commit_and_rollback(db):
    trace_start = len(GUARD.trace)  # Scope to this test, not recycled raw object ids.
    c, s, h = flow(db)
    cid = id(c.connection.driver_connection)
    assert c.connection.driver_connection.in_transaction
    other = db.connection()
    assert other.execute(sa.select(sa.func.count()).select_from(q.HEAD)).scalar() == 0
    other.rollback(); other.close()
    c.rollback()
    other = db.connection()
    assert other.execute(sa.select(sa.func.count()).select_from(q.HEAD)).scalar() == 0
    other.rollback(); other.close()
    c.exec_driver_sql("BEGIN")
    c, s, h = flow(db, c)
    s.complete(h, result())
    c.commit()
    other = db.connection()
    assert other.execute(sa.select(sa.func.count()).select_from(q.PROOF)).scalar() == 1
    trace = [sql.split()[0].upper() for key, sql in GUARD.trace[trace_start:] if key == cid]
    assert "BEGIN" in trace and "SAVEPOINT" in trace and "RELEASE" in trace and "ROLLBACK" in trace and "COMMIT" in trace
    EVIDENCE["topology"]["real_transaction_trace"] = trace


def test_c04_reservation_failure_and_parent_rollback(db, monkeypatch):
    c, s, h = flow(db)
    c.commit(); c.exec_driver_sql("BEGIN")
    s = q.Storage(c, "tenant-a"); h = s.head(1)
    before = snapshot(c)
    real_finish = s._finish_head
    def fail_finish(*args, **kwargs):
        raise RuntimeError("synthetic-after-reservation-and-dependent-writes")
    monkeypatch.setattr(s, "_finish_head", fail_finish)
    with pytest.raises(q.AbortOperation):
        s.complete(h, result())
    assert snapshot(c) == before  # Reservation, terminal O and inserted P all rolled back.
    monkeypatch.setattr(s, "_finish_head", real_finish)
    c.exec_driver_sql("UPDATE local_assets_inventory SET is_deleted=1 WHERE id=1")
    monkeypatch.setattr(s, "_finish_head", fail_finish)
    with pytest.raises(q.AbortOperation):
        s.retire(h, "TRASHED", "TRASH", AT, invalidation_evidence="synthetic-observed")
    c.rollback()  # Required caller abandonment, not core rollback of unrelated work.
    read = db.connection()
    assert read.exec_driver_sql("SELECT is_deleted FROM local_assets_inventory WHERE id=1").scalar() == 0
    assert snapshot(read) == before
    EVIDENCE["topology"]["reservation_failure_rolled_back"] = True


def test_c04_invalid_outer_and_fk():
    for fk, real in ((True,False),(False,True)):
        f = Database(fk=fk)
        try:
            c = f.connection(real=real)
            count = len(GUARD.trace)
            with pytest.raises(q.ContractError, match="REAL_OUTER|FK_REQUIRED"):
                q.Storage(c, "tenant-a")
            assert not any(re.match(r"\s*(SAVEPOINT|INSERT|UPDATE|DELETE)", sql, re.I) for _, sql in GUARD.trace[count:])
        finally:
            f.close()
    f = Database()
    try:
        with f.engine.connect() as c:
            with pytest.raises(q.ContractError, match="REAL_OUTER"):
                q.Storage(c, "tenant-a")
        with pytest.raises(q.ContractError):
            q.Storage(object(), "tenant-a")
        with pytest.raises(q.ContractError):
            q.Storage(c, "tenant-a")
    finally:
        f.close()


def test_c04_unknown_rollback_poison(db, monkeypatch):
    c, s, h = flow(db)
    actual_nested = c.begin_nested
    class Uncertain:
        is_active = True
        def commit(self): raise RuntimeError("synthetic-release-error")
        def rollback(self): raise RuntimeError("synthetic-rollback-unknown")
    monkeypatch.setattr(c, "begin_nested", lambda: Uncertain())
    with pytest.raises(q.RollbackUnknown):
        s.complete(h, result())
    with pytest.raises(q.RollbackUnknown):
        c.commit()
    monkeypatch.setattr(c, "begin_nested", actual_nested)
    c.rollback()
    EVIDENCE["topology"]["unknown_rollback"] = "SYNTHETIC:commit-blocked;caller-abandoned"


def test_c04_unknown_commit_classification(db):
    c, s, h = flow(db)
    s.complete(h, result())
    c.commit()
    # Synthetic lost acknowledgement AFTER actual commit, not real disk/crash proof.
    observed_by_caller = "COMMIT_OUTCOME_UNKNOWN_SYNTHETIC"
    read = db.connection()
    assert read.execute(sa.select(sa.func.count()).select_from(q.PROOF)).scalar() == 1
    EVIDENCE["topology"]["unknown_commit"] = observed_by_caller + ":independent-readback-row-present"


def test_c05_purge_reuse_and_c06_retention(db):
    c, s, h = flow(db)
    h = s.complete(h, result())
    s.record_unknown(h.current_operation_id, "PIPE", "synthetic-pipe", {"observed": "unknown"})
    proof_before = list(c.execute(sa.select(q.PROOF)))
    c.exec_driver_sql("UPDATE local_assets_inventory SET is_deleted=1 WHERE id=1")
    h = s.retire(h, "TRASHED", "TRASH", AT, invalidation_evidence="synthetic-invalidation")
    assert h.qualification_status == "INVALIDATED"
    h = s.retire(h, "PURGED", "PURGE", AT)
    c.exec_driver_sql("DELETE FROM local_assets_inventory WHERE id=1")
    c.commit(); c.exec_driver_sql("BEGIN")
    s = q.Storage(c, "tenant-a")
    db.parent(c, 1)  # Explicitly reproduce reuse in a synthetic parent only.
    assert reject_unchanged(c, lambda: s.start(1, source(2), ident(202), digest(302), digest(402), expected=s.head(1))) == 0
    db.parent(c, 2)
    assert s.start(2, source(2), ident(202), digest(302), digest(402)).asset_id == 2
    assert list(c.execute(sa.select(q.PROOF))) == proof_before
    assert c.execute(sa.select(sa.func.count()).select_from(q.RESPONSIBILITY)).scalar() == 1
    old_op = ident(201)
    assert s._op(old_op)["retired"] == 1
    assert s.record_unknown(old_op, "HANDLE", "late-handle", {"observed": "unknown"}) == "PROVISIONAL_UNKNOWN_RECORD"
    assert reject_unchanged(c, lambda: s.record_unknown(ident(999), "PIPE", "missing", {"observed": "unknown"})) == 0
    EVIDENCE["purge"] = "synthetic-reuse-rejected;legal-new-id-accepted;P/O/R-retained"


def test_c05_parent_delete_requires_reference_disposition(db):
    c, s, h = flow(db)
    before = snapshot(c)
    with pytest.raises(sa.exc.IntegrityError):
        c.exec_driver_sql("DELETE FROM local_assets_inventory WHERE id=1")
    assert snapshot(c) == before and s.head(1) == h


def test_c06_responsibility_after_conflict_and_failure(db, monkeypatch):
    c, s, h = flow(db)
    newer = s.start(1, source(2), ident(202), digest(302), digest(402), expected=h, replace_current=True)
    with pytest.raises(q.Conflict): s.complete(h, result())
    s.record_unknown(h.current_operation_id, "READER", "reader", {"state": "unknown"})
    assert s.head(1) == newer
    before = snapshot(c)
    actual_one = s.connection.execute
    def fail_insert(statement, *args, **kwargs):
        if getattr(statement, "is_insert", False) and statement.table is q.RESPONSIBILITY:
            raise RuntimeError("synthetic-responsibility-write-failure")
        return actual_one(statement, *args, **kwargs)
    monkeypatch.setattr(s.connection, "execute", fail_insert)
    with pytest.raises(q.AbortOperation):
        s.record_unknown(h.current_operation_id, "HANDLE", "handle", {"state": "unknown"})
    monkeypatch.setattr(s.connection, "execute", actual_one)
    assert snapshot(c) == before


def test_c07_nonqualified_missing_and_parent_semantics(db):
    c = db.connection(); db.parent(c)
    s = q.Storage(c, "tenant-a")
    assert s.head(1) is None
    h = s.start(1, source(), ident(201), digest(301), digest(401))
    assert h.qualification_status == "NOT_QUALIFIED"
    # Changing only the synthetic parent does not silently grant a valid qualified mutation.
    c.exec_driver_sql("UPDATE local_assets_inventory SET is_deleted=1 WHERE id=1")
    assert reject_unchanged(c, lambda: s.complete(h, result())) == 1  # Zero-row CAS attempt.
    trashed = s.retire(h, "TRASHED", "TRASH", AT)  # No claimed invalidation evidence.
    assert trashed.qualification_status == "NOT_QUALIFIED"
    c.exec_driver_sql("UPDATE local_assets_inventory SET is_deleted=0 WHERE id=1")
    restored = s.start(1, source(2), ident(202), digest(302), digest(402), expected=trashed, replace_current=True)
    assert restored.current_generation == 2 and restored.current_proof_id is None
    for status in ("PASS", "PENDING_ACK"):
        assert reject_unchanged(c, lambda: s.complete(replace(restored, qualification_status=status), result(2))) == 0


def test_c08_actual_import_and_static_dependencies():
    before = set(sys.modules)
    module = load_target("igq_i1_second_actual_execution")
    assert module is not q and module.METADATA is not q.METADATA
    tree = ast.parse(TARGET.read_text(encoding="utf-8"))
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    imports += [alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names]
    assert not any(n and (n.startswith("src") or n == "main") for n in imports)
    assert not any(n.startswith("src.api") or n == "main" for n in set(sys.modules)-before)
    assert not any(hasattr(module, n) for n in ("create_engine", "Session", "get_db", "prepare_schema", "activate", "ack", "recover"))
    EVIDENCE["actual_import_executions"] = 2


def test_c08_guard_policy_negative_probes():
    GUARD.probing = True
    try:
        for name, args in (("socket.bind", (object(), ("127.0.0.1",0))),
            ("socket.connect", (object(), ("127.0.0.1",9))),
            ("socket.sendto", (object(), ("127.0.0.1",9))),
            ("subprocess.Popen", ("blocked", ["blocked"], None, None)),
            ("sqlite3.connect", (str(OS_TEMP / "not-owned.sqlite"),)),
            ("open", (str(ROOT / "not-created.txt"), "w", os.O_WRONLY))):
            with pytest.raises(PermissionError): GUARD.audit(name, args)
        for statement, core in (("ATTACH DATABASE 'not-opened' AS other", False),
                                ("CREATE TABLE unapproved(x)", False),
                                ("CREATE TABLE igq_bad(x)", True),
                                ("BEGIN", True), ("COMMIT", True), ("ROLLBACK", True)):
            with pytest.raises(PermissionError): GUARD.sql(statement, core)
    finally:
        GUARD.probing = False
    EVIDENCE["negative_probe_count"] = len(GUARD.probes)


@pytest.mark.parametrize("damage", ["missing", "altered", "index", "version", "tenant", "partial", "digest", "extra_index", "trigger"])
def test_c09_readonly_schema_refusal(db, damage):
    c = db.connection()
    if damage == "missing": c.exec_driver_sql("DROP TABLE igq_resource_responsibility")
    elif damage == "altered": c.exec_driver_sql("ALTER TABLE igq_content_version ADD COLUMN unexpected TEXT")
    elif damage == "index": c.exec_driver_sql("DROP INDEX igq_operation_retired")
    elif damage == "version": c.execute(q.STORE.update().values(schema_revision=2))
    elif damage == "tenant": c.execute(q.STORE.update().values(tenant_id="tenant-b"))
    elif damage == "partial": c.execute(q.STORE.update().values(preparation_state="INCOMPLETE"))
    elif damage == "digest": c.execute(q.STORE.update().values(structure_digest=b"x"*32))
    elif damage == "extra_index": c.exec_driver_sql("CREATE INDEX igq_fixture_extra ON igq_content_version(actual_size)")
    elif damage == "trigger": c.exec_driver_sql("CREATE TRIGGER igq_fixture_extra AFTER UPDATE ON igq_asset_head BEGIN SELECT 1; END")
    before = list(c.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name"))
    count = dml_count()
    with pytest.raises(q.ContractError): q.Storage(c, "tenant-a")
    assert list(c.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name")) == before
    assert count == dml_count()


def test_c09_owned_scope_and_no_schema_creation():
    assert {t.name for t in q.OWNED_TABLES} == OWNED_NAMES and q.LEGACY not in q.OWNED_TABLES
    f = Database(prepare=False)
    try:
        c = f.connection()
        with pytest.raises(q.ContractError, match="SCHEMA_INCOMPATIBLE"):
            q.Storage(c, "tenant-a")
        assert set(sa.inspect(c).get_table_names()) == {"local_assets_inventory"}
    finally:
        f.close()


def full_snapshot(c):
    return snapshot(c), list(c.exec_driver_sql("SELECT id,is_deleted,file_hash FROM local_assets_inventory ORDER BY id"))


def observed_refusal(c, call, error, reason, dml=0):
    before, start, count = full_snapshot(c), len(GUARD.events), dml_count()
    with pytest.raises(error, match=reason) as caught:
        call()
    assert full_snapshot(c) == before and dml_count() - count == dml
    entry = {"reason": str(caught.value), "exception": type(caught.value).__name__, "dml": dml}
    EVIDENCE.setdefault("sr_predicates", []).append(entry)
    return GUARD.events[start:]


@pytest.mark.parametrize("topology", ["sqlalchemy", "direct_sql", "commented_sql"])
def test_sr01_outermost_savepoint_refusal(db, topology):
    c = db.connection(real=False)
    assert not c.connection.driver_connection.in_transaction
    if topology == "sqlalchemy":
        c.begin_nested()
    else:
        c.exec_driver_sql(("/* caller */ " if topology == "commented_sql" else "") + "SAVEPOINT caller_outermost")
    assert c.in_transaction() and c.connection.driver_connection.in_transaction
    assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    assert set(sa.inspect(c).get_table_names()) == OWNED_NAMES | {"local_assets_inventory"}
    events = observed_refusal(c, lambda: q.Storage(c, "tenant-a"), q.ContractError, "OUTER_PROVENANCE_REQUIRED")
    assert not any(core and re.match(r"\s*(SAVEPOINT|INSERT|UPDATE|DELETE)", sql, re.I) for _,sql,core in events)
    c.rollback()
    read = db.connection()
    assert read.execute(sa.select(sa.func.count()).select_from(q.HEAD)).scalar() == 0
    EVIDENCE.setdefault("sr01_topologies", []).append({"topology": topology,
        "raw_transaction_true": True, "fk_on": True, "schema_present": True,
        "reason": "OUTER_PROVENANCE_REQUIRED", "core_savepoint_or_dml": 0})


@pytest.mark.parametrize("boundary", ["commit", "rollback", "sql_commit", "sql_rollback"])
def test_sr01_ticket_lifetime(db, boundary):
    c, s, h = flow(db)
    ticket = s._ticket
    if boundary.startswith("sql_"):
        c.exec_driver_sql(boundary[4:].upper())
    else:
        getattr(c, boundary)()
    assert not ticket.active
    with pytest.raises(q.ContractError, match="REAL_OUTER"):
        s.head(1)
    c.exec_driver_sql("BEGIN")
    assert q.Storage(c, "tenant-a")._ticket is not ticket
    observed_refusal(c, lambda: s.head(1), q.ContractError, "OUTER_PROVENANCE_REQUIRED")
    other = db.connection()
    with pytest.raises(q.ContractError, match="OUTER_PROVENANCE_REQUIRED"):
        q._require(other, ticket)


def test_sr01_unobserved_begin_and_changed_boundary(db):
    c = db.engine.connect(); db.connections.append(c)
    c.exec_driver_sql("BEGIN")
    assert c.connection.driver_connection.in_transaction
    observed_refusal(c, lambda: q.Storage(c, "tenant-a"), q.ContractError, "OUTER_PROVENANCE_REQUIRED")
    c.rollback(); q.observe_outer_transaction(c); c.exec_driver_sql("BEGIN")
    s = q.Storage(c, "tenant-a")
    c.exec_driver_sql("SAVEPOINT unsupported_caller_nested")
    observed_refusal(c, lambda: s.head(1), q.ContractError, "OUTER_PROVENANCE_REQUIRED")
    c.rollback(); c.exec_driver_sql("BEGIN")
    assert q.Storage(c, "tenant-a")
    c.exec_driver_sql("/* boundary */ ROLLBACK")
    assert not c.info["igq_outer_observer"].ticket


@pytest.mark.parametrize("boundary", ["close", "invalidate"])
def test_sr01_unusable_connection(db, boundary):
    c, s, h = flow(db)
    getattr(c, boundary)()
    with pytest.raises(q.ContractError, match="CONNECTION_INVALID"):
        s.head(1)


@pytest.mark.parametrize("changed,reason", [
    ("parent", "DUPLICATE_PARENT_UNAVAILABLE"),
    ("retired", "COMPLETION_NOT_ALLOWED"),
    ("proof", "CONFLICTING_COMPLETION"),
])
def test_sr02_duplicate_actual_facts(db, changed, reason):
    c, s, h = flow(db)
    done = s.complete(h, result())
    if changed == "parent":
        c.exec_driver_sql("UPDATE local_assets_inventory SET is_deleted=1 WHERE id=1")
    elif changed == "retired":
        c.execute(q.OPERATION.update().values(retired=1, retired_reason="synthetic", retired_at=AT))
    else:
        c.execute(q.PROOF.update().values(policy_id="synthetic-conflicting-evidence"))
    assert s.head(1) == done  # Other Head predicates cannot mask the target.
    events = observed_refusal(c, lambda: s.complete(done, result()), q.Conflict, reason)
    assert not any(re.match(r"\s*SAVEPOINT", sql, re.I) for _,sql,_ in events)


def test_sr02_legal_duplicate_no_savepoint(db):
    c, s, h = flow(db)
    done = s.complete(h, result())
    before, event_start = full_snapshot(c), len(GUARD.events)
    assert s.complete(done, result()) == done and full_snapshot(c) == before
    assert not any(re.match(r"\s*(SAVEPOINT|INSERT|UPDATE|DELETE)", sql, re.I)
                   for _,sql,_ in GUARD.events[event_start:])


def test_sr03_prewrite_and_zero_row(db):
    c, s, h = flow(db)
    observed_refusal(c, lambda: s.start(1, source(2), ident(202), digest(302), digest(402), expected=h),
                     q.Conflict, "EXPLICIT_REPLACEMENT_REQUIRED")
    observed_refusal(c, lambda: s._reserve(replace(h, head_revision=99), s._op(h.current_operation_id)),
                     q.Conflict, "CONDITIONAL_WRITE_REJECTED", dml=1)


def test_sr03_real_contract_failure_after_reservation(db):
    c, s, h = flow(db)
    c.commit(); c.exec_driver_sql("BEGIN"); s = q.Storage(c, "tenant-a"); h = s.head(1)
    durable_before = full_snapshot(c)
    c.exec_driver_sql("UPDATE local_assets_inventory SET file_hash='synthetic-parent-change' WHERE id=1")
    wrong = replace(source(2, version=1), sha256=digest(999))
    trace_start = len(GUARD.trace)
    events = observed_refusal(c, lambda: s.start(1, wrong, ident(202), digest(302), digest(402),
                              expected=h, replace_current=True), q.AbortOperation,
                              "ASSOCIATED_ATOMIC_ABORT_REQUIRED:CONTENT_IDENTITY_CONFLICT", dml=2)
    assert sum(core and sql.startswith("UPDATE") for _,sql,core in events) == 2
    assert any(sql.upper().startswith("ROLLBACK TO SAVEPOINT") for _,sql in GUARD.trace[trace_start:])
    # Local rollback is not permission to commit the associated parent mutation.
    assert full_snapshot(c) != durable_before
    c.rollback()
    read = db.connection()
    assert full_snapshot(read) == durable_before
    EVIDENCE["sr03_actual_contract_failure"] = "reservation+retirement;content-conflict;savepoint-rollback;caller-rollback;independent-readback"


@pytest.mark.parametrize("failure", ["establish", "release_known", "release_unknown", "rollback_unknown"])
def test_sr03_savepoint_boundaries(db, monkeypatch, failure):
    c, s, h = flow(db)
    c.commit(); c.exec_driver_sql("BEGIN"); s = q.Storage(c, "tenant-a"); h = s.head(1)
    initial = full_snapshot(c)
    real_begin = c.begin_nested
    class Boundary:
        def __init__(self): self.real = real_begin()
        @property
        def is_active(self): return self.real.is_active
        def commit(self):
            if failure == "release_unknown": self.real.commit()
            raise RuntimeError("SYNTHETIC_RELEASE")
        def rollback(self):
            if failure == "rollback_unknown": raise RuntimeError("SYNTHETIC_ROLLBACK")
            self.real.rollback()
    def begin():
        if failure == "establish": raise RuntimeError("SYNTHETIC_ESTABLISHMENT_UNKNOWN")
        return Boundary()
    monkeypatch.setattr(c, "begin_nested", begin)
    error = q.AbortOperation if failure == "release_known" else q.RollbackUnknown
    with pytest.raises(error): s.complete(h, result())
    if failure == "release_known":
        assert full_snapshot(c) == initial
    else:
        assert c.info["igq_abort_required"]
        with pytest.raises(q.RollbackUnknown): s.head(1)
        with pytest.raises(q.RollbackUnknown): c.exec_driver_sql("COMMIT")
        with pytest.raises(q.RollbackUnknown): c.exec_driver_sql("SELECT 1")
        with pytest.raises(q.RollbackUnknown): c.commit()
    c.rollback()
    c.close()  # Abandon poisoned connections; no reset/re-enable path.
    read = db.connection()
    assert full_snapshot(read) == initial
    EVIDENCE.setdefault("sr03_synthetic_boundaries", []).append(failure)


def test_sr04_same_source_requalification_preserves_identities(db):
    c, s, h = flow(db)
    h = s.complete(h, result())
    s.record_unknown(h.current_operation_id, "PIPE", "same-source", {"state": "unknown"})
    initial = snapshot(c)
    observed_refusal(c, lambda: s.start(1, source(), ident(202), digest(302), digest(402), expected=h),
                     q.Conflict, "EXPLICIT_REPLACEMENT_REQUIRED")
    newer = s.start(1, source(), ident(202), digest(302), digest(402), expected=h, replace_current=True)
    after = snapshot(c)
    for t in (q.CONTENT, q.BINDING, q.PROOF, q.RESPONSIBILITY):
        assert after[t.name] == initial[t.name]
    assert newer.current_version_id == h.current_version_id and newer.current_binding_id == h.current_binding_id
    assert newer.current_generation == h.current_generation + 1 and newer.head_revision == h.head_revision + 1
    assert len(after[q.OPERATION.name]) == 2 and newer.current_proof_id is None
    old = s._op(h.current_operation_id)
    assert old["retired"] == 1 and old["completion_state"] == "RESULT_ACCEPTED"
    assert old["request_key_digest"] == digest(301) and old["result_digest"] == result().payload()["result_digest"]
    observed_refusal(c, lambda: s.complete(h, result()), q.Conflict, "STALE_OR_RETIRED_HEAD")
    observed_refusal(c, lambda: s.fail(h, {"failure": "late"}, AT), q.Conflict, "STALE_OR_RETIRED_HEAD")
    observed_refusal(c, lambda: s.start(1, source(), ident(203), digest(301), digest(403),
                     expected=newer, replace_current=True), q.Conflict, "REQUEST_KEY_ALREADY_USED")


@pytest.mark.parametrize("change,reason", [
    ({"sha256": digest(999)}, "CONTENT_IDENTITY_CONFLICT"),
    ({"observation_ref": "synthetic-other-content-evidence"}, "CONTENT_IDENTITY_CONFLICT"),
    ({"source_descriptor": "synthetic-other-source"}, "BINDING_IDENTITY_CONFLICT"),
    ({"source_observation_ref": "synthetic-other-observation"}, "BINDING_IDENTITY_CONFLICT"),
    ({"authorization_evidence_ref": "synthetic-other-evidence"}, "BINDING_IDENTITY_CONFLICT"),
])
def test_sr04_same_binding_conflict(db, change, reason):
    c, s, h = flow(db)
    observed_refusal(c, lambda: s.start(1, replace(source(), **change), ident(202), digest(302), digest(402),
                     expected=h, replace_current=True), q.AbortOperation, reason, dml=2)


def test_sr04_rebinding_new_content_and_historical_refusal(db):
    c, s, h = flow(db)
    rebound = s.start(1, source(2, version=1), ident(202), digest(302), digest(402), expected=h, replace_current=True)
    assert rebound.current_version_id == h.current_version_id and rebound.current_binding_id != h.current_binding_id
    assert c.execute(sa.select(sa.func.count()).select_from(q.CONTENT)).scalar() == 1
    assert c.execute(sa.select(sa.func.count()).select_from(q.BINDING)).scalar() == 2
    observed_refusal(c, lambda: s.start(1, source(), ident(203), digest(303), digest(403),
                     expected=rebound, replace_current=True), q.AbortOperation, "HISTORICAL_BINDING_REUSE_REJECTED", dml=2)
    changed = s.start(1, source(3), ident(203), digest(303), digest(403), expected=rebound, replace_current=True)
    assert changed.current_version_id != rebound.current_version_id and changed.current_binding_id != rebound.current_binding_id
    assert changed.current_generation == 3
    assert c.execute(sa.select(sa.func.count()).select_from(q.CONTENT)).scalar() == 2
    assert c.execute(sa.select(sa.func.count()).select_from(q.BINDING)).scalar() == 3


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "tenant-b"), ("asset_id", 2), ("version_id", ident(42)),
    ("binding_id", ident(42)), ("generation", 2), ("operation_id", ident(42)),
    ("completion_state", "RESULT_ACCEPTED"), ("retired", 1), ("result_digest", digest(999)),
])
def test_sre01_each_operation_cas_predicate(db, field, value):
    c, s, h = flow(db)
    op = dict(s._op(h.current_operation_id)); op[field] = value
    # Expected-facts variation, not an illegal persisted row. Other conjuncts stay true.
    observed_refusal(c, lambda: s._reserve(h, op), q.Conflict, "CONDITIONAL_WRITE_REJECTED", dml=1)


def test_z_isolation_evidence():
    assert not GUARD.violations
    assert len(GUARD.created) == len(GUARD.cleaned)
    assert len(GUARD.connects) == len(GUARD.closed)
    assert not any(Path(p).exists() for p in GUARD.cleaned)
    assert not any(GUARD.core_attempts.values())
    EVIDENCE.update({"sqlite_connections": len(GUARD.connects), "connections_closed": len(GUARD.closed),
        "temporary_databases": len(GUARD.created), "temporary_roots_cleaned": GUARD.cleaned,
        "all_connections_owned": all(GUARD.owned(p) for p in GUARD.connects),
        "dependency_import_denied_operations": GUARD.dependency_denials,
        "unexpected_guard_events": GUARD.violations, "synthetic_denials": GUARD.probes,
        "core_dml_statements": sum(core and bool(re.match(r"\s*(INSERT|UPDATE|DELETE)", sql,re.I)) for _,sql,core in GUARD.events),
        "core_attempts_monitored": GUARD.core_attempts,
        "coverage": "Python audit + SQLAlchemy/SQLite events; not OS sandbox"})
    print("IGQ_I1_EVIDENCE=" + json.dumps(EVIDENCE, sort_keys=True))
