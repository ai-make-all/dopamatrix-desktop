"""V1-R0: actual router ASGI + actual LocalAsset persistence, never Main startup.

All runtime writes belong to one exclusively created OS temporary directory.
The minimal application's error handler is test-only, NOT Main's error fence.
"""
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
import asyncio.proactor_events as proactor_events
import asyncio.windows_events as windows_events
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from src.api import runtime_paths


REPO = Path(__file__).resolve().parents[1]
ENDPOINT = "/api/v1/assets/import"
INFO = "?result_format=p1b-info-v1"
PREFIX = "dopamatrix-p1b-v1-"


def linked(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


@dataclass
class Measurement:
    active: bool = False
    dependency_calls: int = 0
    hash_calls: int = 0
    application_commits: int = 0
    before_commit: int = 0
    after_commit: int = 0
    engine_commits: int = 0
    engine_rollbacks: int = 0
    flush_inside_commit: int = 0
    flush_outside_commit: int = 0
    refreshes: int = 0
    inside_commit: bool = False
    commit_returned: bool = False
    commit_exception: str | None = None
    request_exception: str | None = None
    sql: Counter = field(default_factory=Counter)
    post_commit_sql: Counter = field(default_factory=Counter)
    identities: list = field(default_factory=list)
    expired_primary_keys: list = field(default_factory=list)

    def public(self):
        return {
            "dependency_calls": self.dependency_calls, "hash_calls": self.hash_calls,
            "application_commits": self.application_commits,
            "before_commit_events": self.before_commit, "after_commit_events": self.after_commit,
            "engine_commits": self.engine_commits, "engine_rollbacks": self.engine_rollbacks,
            "automatic_commit_flushes": self.flush_inside_commit,
            "outside_commit_flushes": self.flush_outside_commit, "refreshes": self.refreshes,
            "commit_returned": self.commit_returned, "commit_exception": self.commit_exception,
            "request_exception": self.request_exception,
            "sql": dict(self.sql), "post_commit_sql": dict(self.post_commit_sql),
            "post_commit_identities": self.identities,
            "expired_primary_keys": self.expired_primary_keys,
        }


class ObservedSession(Session):
    """Measurement wrapper; all persistence/flush behavior delegates to SQLAlchemy."""
    def commit(self):
        m = self.info.get("v1_measurement")
        if m is None:
            return super().commit()
        m.application_commits += 1
        m.inside_commit = True
        # Keep actual mapped objects alive without accessing expired attributes.
        retained = tuple(self.new) + tuple(self.identity_map.values())
        try:
            answer = super().commit()
        except Exception as error:
            m.commit_exception = type(error).__name__
            raise
        else:
            m.commit_returned = True
            states = [inspect(asset) for asset in retained]
            m.identities = [list(state.identity) for state in states if state.identity is not None]
            m.expired_primary_keys = ["id" in state.expired_attributes for state in states]
            return answer
        finally:
            m.inside_commit = False

    def flush(self, *args, **kwargs):
        m = self.info.get("v1_measurement")
        if m is not None:
            if m.inside_commit:
                m.flush_inside_commit += 1
            else:
                m.flush_outside_commit += 1
        return super().flush(*args, **kwargs)

    def refresh(self, *args, **kwargs):
        m = self.info.get("v1_measurement")
        if m is not None:
            m.refreshes += 1
        return super().refresh(*args, **kwargs)


@event.listens_for(ObservedSession, "before_commit")
def observe_before_commit(session):
    m = session.info.get("v1_measurement")
    if m is not None:
        m.before_commit += 1


@event.listens_for(ObservedSession, "after_commit")
def observe_after_commit(session):
    m = session.info.get("v1_measurement")
    if m is not None:
        m.after_commit += 1


class RuntimeSuite:
    def __init__(self):
        self.root = None
        self.os_temp = None
        self.owner = None
        self.paths_context = None
        self.paths_entered = False
        self.active = False
        self.closed = False
        self.cases = []
        self.connected = set()
        self.violations = []
        self.sqlite_violations = []
        self.internal_pairs = []
        self.negative_boundary_checks = []
        self.synthetic_audit_denials = []
        self.records = []
        self.cleaned = False

    def owned_path(self, path):
        path = Path(path).resolve()
        if self.root is None or not path.is_relative_to(self.root):
            self.violations.append("OUTSIDE_OWNED_TEMP")
            raise AssertionError("ENVIRONMENT_BLOCKER_OUTSIDE_OWNED_TEMP")
        return path

    def permit_internal_socketpair(self, name, args, origin):
        """Only the inspected stdlib fallback called by Proactor __init__.

        Inspect adjacent, code-identity-verified frames, never a thread-wide
        allowance or a guessed numeric stack depth. Objects remain private;
        the report exposes only counts and the verified provenance label.
        """
        if name not in {"socket.bind", "socket.connect"} or origin is None:
            return False
        if (origin.f_code is not socket._fallback_socketpair.__code__
                or origin.f_globals is not vars(socket)):
            return False
        pipe = origin.f_back
        if (pipe is None
                or pipe.f_code is not proactor_events.BaseProactorEventLoop._make_self_pipe.__code__
                or pipe.f_globals is not vars(proactor_events)):
            return False
        initializing = pipe.f_back
        loop = pipe.f_locals.get("self")
        if (initializing is None
                or initializing.f_code is not proactor_events.BaseProactorEventLoop.__init__.__code__
                or initializing.f_globals is not vars(proactor_events)
                or initializing.f_locals.get("self") is not loop
                or type(loop) is not windows_events.ProactorEventLoop):
            return False
        local = origin.f_locals
        if (local.get("family") != socket.AF_INET or local.get("type") != socket.SOCK_STREAM
                or local.get("proto") != 0 or local.get("host") != "127.0.0.1"):
            return False
        sock, address = args
        if (type(sock) is not socket.socket or sock.family != socket.AF_INET
                or sock.type != socket.SOCK_STREAM or sock.proto != 0):
            return False
        listener = local.get("lsock")
        if name == "socket.bind":
            if (sock is not listener or address != ("127.0.0.1", 0)
                    or any(p["listener"] is sock for p in self.internal_pairs)):
                return False
            self.internal_pairs.append({"frame_id": id(origin), "listener": sock,
                                        "loop": loop, "client": None,
                                        "events": ["socket.bind"]})
            return True
        pair = next((p for p in self.internal_pairs
                     if p["frame_id"] == id(origin) and p["listener"] is listener
                     and p["loop"] is loop), None)
        if (pair is None or pair["events"] != ["socket.bind"]
                or sock is not local.get("csock") or sock is listener):
            return False
        endpoint = listener.getsockname()
        if (endpoint[0] != "127.0.0.1" or not 0 < endpoint[1] <= 65535
                or address != endpoint
                or (local.get("addr"), local.get("port")) != endpoint):
            return False
        pair["client"] = sock
        pair["events"].append("socket.connect")
        return True

    def verify_internal_pairs(self, *, closed=False):
        assert self.internal_pairs, "SOCKETPAIR_EXCEPTION_NOT_OBSERVED"
        for pair in self.internal_pairs:
            loop, client = pair["loop"], pair["client"]
            assert pair["events"] == ["socket.bind", "socket.connect"]
            assert pair["listener"].fileno() == -1  # No surviving listener.
            if closed or loop.is_closed():
                assert loop.is_closed() and client.fileno() == -1
                assert loop._ssock is None and loop._csock is None
            else:
                assert loop._csock is client and client.fileno() >= 0
                assert loop._ssock.getpeername() == client.getsockname()
                assert client.getpeername() == loop._ssock.getsockname()

    def verify_negative_boundary(self):
        # Policy-only probes: no socket creation, bind, connect, DNS or process.
        probes = [
            ("unrelated_loopback_bind", "socket.bind", ("127.0.0.1", 0)),
            ("unrelated_localhost_connect", "socket.connect", ("localhost", 12345)),
            ("unrelated_loopback_connect", "socket.connect", ("127.0.0.1", 12345)),
            ("unrelated_ipv6_bind", "socket.bind", ("::1", 0)),
            ("non_loopback_connect", "socket.connect", ("192.0.2.1", 12345)),
            ("private_network_bind", "socket.bind", ("192.168.1.1", 0)),
            ("unverified_context", "socket.connect", ("127.0.0.1", 12345)),
        ]
        for label, event_name, endpoint in probes:
            origin = None if label == "unverified_context" else sys._getframe()
            assert not self.permit_internal_socketpair(event_name, (object(), endpoint), origin)
            self.negative_boundary_checks.append(label)
        assert not self.internal_pairs  # Negative probes cannot create provenance.

    def audit(self, name, args):
        if not self.active:
            return
        if name == "sqlite3.connect":
            value = os.fsdecode(args[0])
            if value == ":memory:" or value.startswith("file:"):
                self.sqlite_violations.append("UNAPPROVED_SQLITE_TARGET")
                self.violations.append("UNAPPROVED_SQLITE_TARGET")
                raise AssertionError("ENVIRONMENT_BLOCKER_SQLITE_TARGET")
            try:
                path = self.owned_path(value)  # Before SQLite opens a connection.
            except AssertionError:
                self.sqlite_violations.append("OUTSIDE_OWNED_TEMP")
                raise
            self.connected.add(str(path))
        elif name in {"socket.connect", "socket.bind", "socket.sendto",
                      "subprocess.Popen", "os.system", "os.posix_spawn"}:
            if self.permit_internal_socketpair(name, args, sys._getframe().f_back):
                return
            self.violations.append(name)
            raise AssertionError("ENVIRONMENT_BLOCKER_EXTERNAL_OPERATION")

    def start(self):
        assert sys.dont_write_bytecode, "ENVIRONMENT_BLOCKER_BYTECODE_ENABLED"
        assert sys.platform == "win32" and sys.version_info[:3] == (3, 12, 10)
        assert socket.socketpair is socket._fallback_socketpair
        stdlib = Path(sys.base_prefix) / "Lib"
        assert Path(socket._fallback_socketpair.__code__.co_filename).resolve() == (stdlib / "socket.py").resolve()
        assert Path(proactor_events.BaseProactorEventLoop._make_self_pipe.__code__.co_filename).resolve() == (stdlib / "asyncio/proactor_events.py").resolve()
        self.verify_negative_boundary()
        assert "main" not in sys.modules and "src.api.database" not in sys.modules
        self.os_temp = Path(tempfile.gettempdir()).resolve()
        assert not self.os_temp.is_relative_to(REPO)
        assert not any("dopamatrix" in part.lower() for part in self.os_temp.parts)
        self.root = Path(tempfile.mkdtemp(prefix=PREFIX, dir=self.os_temp)).resolve()
        assert self.root.parent == self.os_temp and self.root.name.startswith(PREFIX)
        assert not linked(self.root) and not self.root.is_relative_to(REPO)
        info = self.root.stat()
        self.owner = (info.st_dev, info.st_ino)
        sys.addaudithook(self.audit)
        self.active = True
        self.paths_context = runtime_paths.temporary_test_runtime_paths(self.root)
        self.paths_context.__enter__()
        self.paths_entered = True
        self.routes = importlib.import_module("src.api.routes_assets")
        self.database = importlib.import_module("src.api.database")
        self.models = importlib.import_module("src.api.models")
        self.schemas = importlib.import_module("src.api.schemas")
        self.owned_path(self.database.engine.url.database)
        assert self.database._runtime_paths.mode is runtime_paths.RuntimeMode.TEST
        assert not self.database._tenant_engines
        assert not (self.root / "dopamatrix.db").exists()
        assert "main" not in sys.modules

    def close(self):
        if self.closed:
            return
        try:
            for case in self.cases:
                case.close()
            if self.internal_pairs:
                self.verify_internal_pairs(closed=True)
            if hasattr(self, "database"):
                self.database.engine.dispose()
                assert not self.database._tenant_engines
                assert not (self.root / "dopamatrix.db").exists()
            if self.paths_entered:
                self.paths_context.__exit__(None, None, None)
                self.paths_entered = False
            if self.root is not None:
                info = self.root.lstat()
                assert (info.st_dev, info.st_ino) == self.owner
                assert self.root.parent == self.os_temp and self.root.name.startswith(PREFIX)
                assert not linked(self.root) and not self.root.is_relative_to(REPO)
                for directory, dirs, files in os.walk(self.root, followlinks=False):
                    for name in dirs + files:
                        child = Path(directory) / name
                        assert not linked(child), "UNSAFE_TEMP_CLEANUP_LINK"
                        self.owned_path(child)
                # Exact exclusively-created root, ownership and every child verified above.
                shutil.rmtree(self.root)
                self.cleaned = not self.root.exists()
                assert self.cleaned
        finally:
            self.active = False
            self.closed = True

    def report(self):
        return {"asgi_level": "REAL_ROUTER_ASGI", "main_app_http": "NOT_VERIFIED",
                "production_error_fence": "NOT_VERIFIED", "cases": self.records,
                "sqlite_connection_targets_verified": bool(self.connected) and not self.sqlite_violations,
                "sqlite_guard_violations": self.sqlite_violations,
                "permitted_internal_transport": {
                    "provenance": "stdlib _fallback_socketpair -> BaseProactorEventLoop._make_self_pipe -> BaseProactorEventLoop.__init__",
                    "pairs": len(self.internal_pairs),
                    "events": dict(Counter(e for p in self.internal_pairs for e in p["events"])),
                    "all_temporary_listeners_closed": all(p["listener"].fileno() == -1 for p in self.internal_pairs),
                    "all_internal_clients_closed": all(p["client"] is not None and p["client"].fileno() == -1 for p in self.internal_pairs)},
                "negative_boundary_checks": self.negative_boundary_checks,
                "synthetic_audit_denials": self.synthetic_audit_denials,
                "forbidden_operation_counts": dict(Counter(self.violations)),
                "unique_temp_databases_connected": len(self.connected),
                "guard_violations": self.violations, "temporary_resources_disposed": self.cleaned,
                "location": "new exclusively-owned OS_TEMP/dopamatrix-p1b-v1-<random>"}


class RuntimeCase:
    def __init__(self, suite):
        self.suite = suite
        self.root = suite.owned_path(suite.root / ("case-" + str(len(suite.cases))))
        self.root.mkdir()
        self.closed = False
        self.engine = None
        self.client = None
        self.client_entered = False
        suite.cases.append(self)
        self.measurement = Measurement()
        self.query_fault = False
        self.not_null_fault = False
        self.fixture_commits = 0
        db_path = suite.owned_path(self.root / "runtime.sqlite")
        assert not db_path.exists()
        self.engine = create_engine(URL.create("sqlite+pysqlite", database=str(db_path)),
                                    connect_args={"check_same_thread": False}, hide_parameters=True)
        suite.owned_path(self.engine.url.database)
        asset_table = suite.models.LocalAsset.__table__
        asset_table.create(self.engine)  # This table and its indexes only; no production migrations.
        assert inspect(self.engine).get_table_names() == [asset_table.name]
        self.factory = sessionmaker(bind=self.engine, class_=ObservedSession,
                                    autoflush=False, expire_on_commit=True)
        event.listen(self.engine, "before_cursor_execute", self.observe_sql)
        event.listen(self.engine, "commit", self.observe_engine_commit)
        event.listen(self.engine, "rollback", self.observe_engine_rollback)
        self.app = FastAPI()
        self.app.include_router(suite.routes.router, prefix="/api/v1")
        self.app.dependency_overrides[suite.database.get_db] = self.session_dependency

        @self.app.exception_handler(Exception)
        async def test_only_error_handler(request, error):
            self.measurement.request_exception = type(error).__name__
            return JSONResponse(status_code=500, content={"detail": "V1_REQUEST_FAILED"})

        assert not self.app.router.on_startup and not self.app.router.on_shutdown
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.client.__enter__()
        self.client_entered = True
        suite.verify_internal_pairs()

    def observe_sql(self, connection, cursor, statement, parameters, context, executemany):
        category = statement.lstrip().split(None, 1)[0].upper()
        assert category not in {"ATTACH", "DETACH"}, "ENVIRONMENT_BLOCKER_DATABASE_ATTACH"
        m = self.measurement
        if m.active:
            m.sql[category] += 1  # Counts attempted statements; parameters are never recorded.
            if m.commit_returned:
                m.post_commit_sql[category] += 1
            if self.query_fault and category == "SELECT":
                raise RuntimeError("SYNTHETIC_PRIVATE_QUERY_CONTEXT")

    def observe_engine_commit(self, connection):
        if self.measurement.active:
            self.measurement.engine_commits += 1

    def observe_engine_rollback(self, connection):
        if self.measurement.active:
            self.measurement.engine_rollbacks += 1

    def session_dependency(self):
        m = self.measurement
        m.dependency_calls += 1
        m.active = True
        session = self.factory(info={"v1_measurement": m})
        assert session.autoflush is False and session.expire_on_commit is True
        if self.not_null_fault:
            def inject_invalid_test_row(current, context, instances):
                for asset in current.new:
                    if isinstance(asset, self.suite.models.LocalAsset):
                        asset.file_hash = None  # Controlled temporary-data NOT NULL fault.
            event.listen(session, "before_flush", inject_invalid_test_row)
        try:
            yield session
        finally:
            session.close()
            m.active = False

    def source(self, name, content=b"synthetic-non-media-input"):
        path = self.suite.owned_path(self.root / name)
        assert not path.exists()
        path.write_bytes(content)
        return path

    def seed(self, path, deleted=False):
        self.suite.owned_path(path)
        with Session(self.engine, autoflush=False, expire_on_commit=True) as session:
            asset = self.suite.models.LocalAsset(file_hash=hashlib.md5(path.read_bytes()).hexdigest(),
                                                file_path=str(path), asset_type="video", is_deleted=deleted)
            session.add(asset)
            session.commit()
            self.fixture_commits += 1
            return inspect(asset).identity[0]

    def rows(self):
        assert not self.measurement.active
        # Verification SELECTs run only after the request measurement has ended.
        with Session(self.engine) as session:
            return [{"id": asset.id, "path": asset.file_path, "deleted": asset.is_deleted}
                    for asset in session.execute(select(self.suite.models.LocalAsset)).scalars()]

    def post(self, paths, selector=INFO):
        for path in paths:
            self.suite.owned_path(path)
        self.measurement = Measurement()
        original_hash = self.suite.routes.compute_md5
        with patch.object(self.suite.routes, "compute_md5", wraps=original_hash) as hash_calls:
            response = self.client.post(ENDPOINT + selector,
                                        json={"file_paths": [str(path) for path in paths], "asset_type": "video"})
            self.measurement.hash_calls = hash_calls.call_count
        assert not self.measurement.active
        assert not self.suite.database._tenant_engines
        assert not self.suite.violations
        assert "main" not in sys.modules
        return response

    def record(self, label, response, classification="CONTRACT_VERIFIED", **extra):
        self.suite.records.append({"case": label, "http": response.status_code,
                                   "classification": classification, "fixture_commits_excluded": self.fixture_commits,
                                   **self.measurement.public(), **extra})

    def close(self):
        if self.closed:
            return
        try:
            try:
                if self.client_entered:
                    self.client.__exit__(None, None, None)
                elif self.client is not None:
                    self.client.close()
            finally:
                if self.engine is not None:
                    self.engine.dispose()
        finally:
            self.closed = True


@pytest.fixture(scope="module")
def runtime_suite(request):
    suite = RuntimeSuite()
    try:
        suite.start()
        yield suite
    finally:
        try:
            suite.close()
        finally:
            capture = request.config.pluginmanager.getplugin("capturemanager")
            with capture.global_and_fixture_disabled():
                print("V1_RUNTIME_EVIDENCE=" + json.dumps(suite.report(), sort_keys=True))


@contextmanager
def isolated_case(suite):
    case = RuntimeCase(suite)
    try:
        yield case
    finally:
        case.close()


def assert_private(case, response):
    text = response.text
    assert str(case.root) not in text
    for forbidden in ("Traceback", "SYNTHETIC_PRIVATE", "sqlite:///", '"facts"', "persistence_confirmed"):
        assert forbidden not in text


def assert_info(case, response):
    assert response.status_code == 200
    data = response.json()
    case.suite.schemas.P1BInformationalImportResponse.model_validate(data)
    assert_private(case, response)
    for index, result in enumerate(data["results"]):
        assert result["input_index"] == index and result["file_display_name"] == f"input-{index}"
        assert result["technical_validation"] == {"status": "NOT_EVALUATED"}
        assert result["qualification_activation"] == {"status": "NOT_QUALIFIED"}
        for key, reference in result["references"].items():
            if key != "asset_id":
                assert reference == {"value": None, "state": "NOT_ESTABLISHED", "provenance": None}
    return data


def assert_success_boundary(case):
    m = case.measurement
    assert m.application_commits == m.before_commit == m.after_commit == m.engine_commits == 1
    assert m.commit_returned and m.commit_exception is None
    assert m.flush_outside_commit == m.refreshes == 0
    assert not m.post_commit_sql


def assert_safe_failure(case, response):
    assert response.status_code == 500
    assert response.json() == {"detail": "V1_REQUEST_FAILED"}
    assert_private(case, response)
    assert "rollback" not in response.text.lower()
    assert "results" not in response.json()


def test_h01_default_legacy(runtime_suite):
    with isolated_case(runtime_suite) as case:
        source = case.source("legacy.bin")
        missing = case.root / "absent.bin"
        response = case.post([source, missing], selector="")
        assert response.status_code == 200
        assert response.json() == {"success_count": 1, "skipped_count": 1,
                                   "message": "成功导入 1 个素材，跳过 1 个已存在或无效的文件"}
        assert_private(case, response)
        assert len(case.rows()) == 1
        assert_success_boundary(case)
        case.record("H01", response, persisted_rows=1)


def test_h02_ordered_informational(runtime_suite):
    with isolated_case(runtime_suite) as case:
        duplicate = case.source("existing.bin", b"existing-synthetic")
        existing_id = case.seed(duplicate)
        fresh = case.source("fresh.bin", b"fresh-synthetic")
        response = case.post([duplicate, fresh, duplicate, case.root / "absent.bin"])
        data = assert_info(case, response)
        assert (data["success_count"], data["skipped_count"]) == (1, 3)
        assert [r["import_outcome"] for r in data["results"]] == [
            "DUPLICATE_EXISTING", "CREATED", "DUPLICATE_EXISTING", "NOT_COMPLETED"]
        rows = case.rows()
        new_id = next(row["id"] for row in rows if row["path"] == str(fresh))
        ids = [r["references"]["asset_id"]["value"] for r in data["results"]]
        assert ids == [existing_id, new_id, existing_id, None]
        assert_success_boundary(case)
        assert case.measurement.sql == {"SELECT": 3, "INSERT": 1}
        case.record("H02", response, public_ids=ids, persisted_rows=len(rows))


def test_h03_invalid_selectors(runtime_suite):
    with isolated_case(runtime_suite) as case:
        source = case.source("selector.bin")
        selectors = ("?result_format=", "?result_format", "?result_format=unknown",
                     "?result_format=%FF", "?result_format=p1b-info-v1%", "?result_format=" + "x" * 4096)
        for selector in selectors:
            response = case.post([source], selector)
            assert response.status_code == 400
            assert response.json() == {"detail": {"reason_code": "CONTRACT_INVALID",
                                                   "operator_next_action": "REVIEW_CONTRACT"}}
            assert case.measurement.hash_calls == case.measurement.application_commits == 0
            assert not case.measurement.sql
            assert_private(case, response)
        assert case.rows() == []
        case.record("H03", response, variants_verified=len(selectors), persisted_rows=0)


def test_h04_repeated_selectors(runtime_suite):
    with isolated_case(runtime_suite) as case:
        source = case.source("repeated.bin")
        selectors = (INFO + "&result_format=p1b-info-v1", INFO + "&result_format=unknown",
                     "?result_format=&result_format=", INFO + "&result_format=p1b-info-v1&result_format=p1b-info-v1")
        for selector in selectors:
            response = case.post([source], selector)
            assert response.status_code == 400
            assert response.json()["detail"]["reason_code"] == "CONTRACT_INVALID"
            assert case.measurement.hash_calls == case.measurement.application_commits == 0
            assert not case.measurement.sql
            assert_private(case, response)
        assert case.rows() == []
        case.record("H04", response, variants_verified=len(selectors), persisted_rows=0)


def test_h05_actual_router_openapi(runtime_suite):
    with isolated_case(runtime_suite) as case:
        response = case.client.get("/openapi.json")
        assert response.status_code == 200
        document = response.json()
        operation = document["paths"][ENDPOINT]["post"]
        schemas = document["components"]["schemas"]
        schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        union = schemas[schema["$ref"].rsplit("/", 1)[1]]
        assert {item["$ref"].rsplit("/", 1)[1] for item in union["anyOf"]} == {
            "LocalAssetImportResponse", "P1BInformationalImportResponse"}
        assert set(schemas["LocalAssetImportResponse"]["properties"]) == {"success_count", "skipped_count", "message"}
        assert set(schemas["P1BInformationalImportResponse"]["required"]) == {
            "result_format", "success_count", "skipped_count", "message", "results"}
        selector = next(p for p in operation["parameters"] if p["name"] == "result_format")
        assert selector["required"] is False
        assert selector["schema"]["enum"] == ["p1b-info-v1"]
        error = operation["responses"]["400"]["content"]["application/json"]["schema"]
        assert error["properties"]["detail"]["properties"]["reason_code"]["const"] == "CONTRACT_INVALID"
        assert '"facts"' not in json.dumps(schemas)
        case.record("H05", response, main_openapi="NOT_VERIFIED")


def test_o01_new_asset_real_identity(runtime_suite):
    with isolated_case(runtime_suite) as case:
        source = case.source("new.bin")
        response = case.post([source])
        data = assert_info(case, response)
        rows = case.rows()
        assert len(rows) == 1 and rows[0]["id"] > 0
        assert data["results"][0]["import_outcome"] == "CREATED"
        assert data["results"][0]["references"]["asset_id"]["value"] == rows[0]["id"]
        assert case.measurement.identities == [[rows[0]["id"]]]
        assert case.measurement.expired_primary_keys == [True]
        assert case.measurement.sql == {"SELECT": 1, "INSERT": 1}
        assert case.measurement.flush_inside_commit == 1
        assert_success_boundary(case)
        case.record("O01/O04", response, persisted_rows=1, public_asset_id=rows[0]["id"])


def test_o02_active_duplicate(runtime_suite):
    with isolated_case(runtime_suite) as case:
        original = case.source("original.bin")
        asset_id = case.seed(original)
        supplied = case.source("different-binding.bin")
        response = case.post([supplied])
        data = assert_info(case, response)
        assert data["results"][0]["import_outcome"] == "DUPLICATE_EXISTING"
        assert data["results"][0]["references"]["asset_id"]["value"] == asset_id
        assert case.rows() == [{"id": asset_id, "path": str(original), "deleted": False}]
        assert case.measurement.sql == {"SELECT": 1}
        assert case.measurement.flush_inside_commit == 0
        assert_success_boundary(case)
        case.record("O02/O04", response, persisted_rows=1, public_asset_id=asset_id, automatic_rebind=False)


def test_o03_revival(runtime_suite):
    with isolated_case(runtime_suite) as case:
        original = case.source("deleted.bin")
        asset_id = case.seed(original, deleted=True)
        supplied = case.source("revival-binding.bin")
        response = case.post([supplied])
        data = assert_info(case, response)
        assert data["results"][0]["import_outcome"] == "REVIVED"
        assert data["results"][0]["references"]["asset_id"]["value"] == asset_id
        assert case.rows() == [{"id": asset_id, "path": str(supplied), "deleted": False}]
        assert case.measurement.sql == {"SELECT": 1, "UPDATE": 1}
        assert case.measurement.flush_inside_commit == 1
        assert_success_boundary(case)
        case.record("O03/O04", response, persisted_rows=1, public_asset_id=asset_id)


def test_o05_real_constraint_commit_failure(runtime_suite):
    with isolated_case(runtime_suite) as case:
        case.not_null_fault = True
        response = case.post([case.source("constraint-failure.bin")])
        assert_safe_failure(case, response)
        assert case.rows() == []
        m = case.measurement
        assert m.application_commits == m.before_commit == m.flush_inside_commit == 1
        assert m.after_commit == 0 and not m.commit_returned
        assert m.commit_exception == "IntegrityError" and m.engine_rollbacks == 1
        assert m.sql == {"SELECT": 1, "INSERT": 1} and not m.post_commit_sql
        case.record("O05/H06", response, classification="CONTROLLED_TEST_DATA_FAULT", persisted_rows=0)


def test_o06_same_new_md5_observation(runtime_suite):
    with isolated_case(runtime_suite) as case:
        first = case.source("same-new-a.bin", b"same-previously-unseen-synthetic-bytes")
        second = case.source("same-new-b.bin", b"same-previously-unseen-synthetic-bytes")
        response = case.post([first, second])
        assert_safe_failure(case, response)
        assert case.rows() == []
        m = case.measurement
        assert m.hash_calls == m.application_commits + 1 == 2
        assert m.sql["SELECT"] == 2 and 1 <= m.sql["INSERT"] <= 2
        assert m.commit_exception == "IntegrityError" and m.engine_rollbacks == 1
        assert m.after_commit == 0 and not m.commit_returned and not m.post_commit_sql
        case.record("O06", response, classification="EXISTING_BEHAVIOR_OBSERVATION",
                    unique_constraint_failed=True, persisted_rows=0)


def test_h06_request_level_query_failure(runtime_suite):
    with isolated_case(runtime_suite) as case:
        case.query_fault = True
        response = case.post([case.source("query-failure.bin")])
        assert_safe_failure(case, response)
        assert case.rows() == []
        assert case.measurement.application_commits == 0
        assert case.measurement.request_exception == "RuntimeError"
        case.record("H06-query", response, classification="CONTROLLED_SQL_EVENT_FAULT", persisted_rows=0)


@pytest.mark.parametrize("failure_point", ["dto", "json"])
def test_h06_post_commit_response_failure(runtime_suite, failure_point):
    with isolated_case(runtime_suite) as case:
        source = case.source("post-commit-failure.bin")
        injected = RuntimeError("SYNTHETIC_PRIVATE_SERIALIZATION_CONTEXT")
        target = (patch.object(runtime_suite.schemas.P1BInformationalImportResponse, "model_validate", side_effect=injected)
                  if failure_point == "dto" else patch.object(runtime_suite.routes, "JSONResponse", side_effect=injected))
        with target:
            response = case.post([source])
        assert_safe_failure(case, response)
        assert len(case.rows()) == 1  # Persistence survives the response failure.
        assert_success_boundary(case)
        assert case.measurement.request_exception == "ValueError"
        case.record("H06-post-commit-" + failure_point, response,
                    classification="CONTROLLED_RESPONSE_FAULT", persisted_rows=1)


@pytest.mark.parametrize("scenario,event_name,address", [
    ("sendto_loopback", "socket.sendto", ("127.0.0.1", 12345)),
    ("sendto_localhost", "socket.sendto", ("localhost", 12345)),
    ("sendto_ipv6", "socket.sendto", ("::1", 12345, 0, 0)),
    ("sendto_private", "socket.sendto", ("192.168.1.1", 12345)),
    ("sendto_non_loopback", "socket.sendto", ("192.0.2.1", 12345)),
    ("bind_wrong_source", "socket.bind", ("127.0.0.1", 0)),
    ("connect_wrong_source", "socket.connect", ("127.0.0.1", 49152)),
    ("bind_wrong_object", "socket.bind", ("127.0.0.1", 0)),
    ("connect_wrong_object", "socket.connect", ("127.0.0.1", 49152)),
    ("connect_wrong_endpoint", "socket.connect", ("127.0.0.1", 49153)),
    ("connect_before_bind", "socket.connect", ("127.0.0.1", 49152)),
    ("connect_repeated", "socket.connect", ("127.0.0.1", 49152)),
    ("bind_wrong_caller", "socket.bind", ("127.0.0.1", 0)),
], ids=lambda value: value if isinstance(value, str) and not value.startswith("socket.") else None)
def test_sr1_full_audit_denial(runtime_suite, scenario, event_name, address):
    """Synthetic audit calls only: never invoke bind/connect/sendto or DNS.

    Borrow CLOSED sockets from the original runtime cases for genuine socket
    type/identity metadata. Synthetic frames exercise deeper refusal branches;
    they are not evidence that a real caller can supply forged audit frames.
    Only this test module's sys binding is substituted, not the system module
    or either guard method. No synthetic frame is supplied to the live hook.
    """
    assert runtime_suite.internal_pairs  # Original 13 regressions run first.
    accepted = runtime_suite.internal_pairs[0]
    sock, loop = accepted["client"], accepted["loop"]
    assert sock.fileno() == -1 and loop.is_closed()
    guard = RuntimeSuite()  # Not installed as a process audit hook; no resources.
    guard.active = True
    listener = SimpleNamespace(getsockname=lambda: ("127.0.0.1", 49152))
    initializing = SimpleNamespace(
        f_code=proactor_events.BaseProactorEventLoop.__init__.__code__,
        f_globals=vars(proactor_events), f_locals={"self": loop})
    pipe = SimpleNamespace(
        f_code=proactor_events.BaseProactorEventLoop._make_self_pipe.__code__,
        f_globals=vars(proactor_events), f_locals={"self": loop}, f_back=initializing)
    origin = SimpleNamespace(
        f_code=socket._fallback_socketpair.__code__, f_globals=vars(socket), f_back=pipe,
        f_locals={"family": socket.AF_INET, "type": socket.SOCK_STREAM, "proto": 0,
                  "host": "127.0.0.1", "lsock": listener, "csock": sock,
                  "addr": "127.0.0.1", "port": 49152})
    if scenario.endswith("wrong_source"):
        origin = sys._getframe()  # Genuine wrong caller, not fallback provenance.
    elif scenario == "bind_wrong_caller":
        origin.f_locals["lsock"] = sock  # Otherwise a matching bind.
        pipe.f_code = test_sr1_full_audit_denial.__code__
    elif scenario == "connect_wrong_object":
        origin.f_locals["csock"] = object()
    if event_name == "socket.connect" and not scenario.endswith("wrong_source"):
        guard.internal_pairs.append({"frame_id": id(origin), "listener": listener,
                                     "loop": loop, "client": None,
                                     "events": ["socket.bind"]})
        if scenario == "connect_before_bind":
            guard.internal_pairs.clear()
        elif scenario == "connect_repeated":
            guard.internal_pairs[0]["events"].append("socket.connect")
    before = [(id(p), tuple(p["events"]), p["client"]) for p in guard.internal_pairs]
    module = sys.modules[__name__]
    frame_source = SimpleNamespace(_getframe=lambda: SimpleNamespace(f_back=origin))
    # CPython 3.12 audit_events.html: all three events use (self, address),
    # including sendto -- the audit arguments do NOT include payload bytes.
    with patch.object(module, "sys", frame_source):
        with pytest.raises(AssertionError, match="^ENVIRONMENT_BLOCKER_EXTERNAL_OPERATION$"):
            guard.audit(event_name, (sock, address))
    assert guard.violations == [event_name]
    assert [(id(p), tuple(p["events"]), p["client"]) for p in guard.internal_pairs] == before
    assert not guard.connected and not guard.sqlite_violations
    runtime_suite.synthetic_audit_denials.append({
        "scenario": scenario, "event": event_name, "argument_count": 2,
        "exception": "ENVIRONMENT_BLOCKER_EXTERNAL_OPERATION",
        "scope": "SYNTHETIC_AUDIT_CALL_NO_NETWORK"})
