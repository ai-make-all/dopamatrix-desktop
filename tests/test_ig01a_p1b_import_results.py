"""P1B-T01..T14: extracted route definitions, synthetic objects, no application/DB.

OpenAPI is generated for an isolated APIRouter, not the real Main application.
Run P1-A regression in its own process: its T16 requires no FastAPI imports.
"""
import ast
import builtins
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import RootModel, ValidationError

from src.api import schemas as s


ROOT = Path(__file__).resolve().parents[1]
INFO = "result_format=p1b-info-v1"


class HashColumn:
    def __eq__(self, value):
        return value


class FakeAsset:
    file_hash = HashColumn()

    def __init__(self, **values):
        self.__dict__.update(values)
        self.is_deleted = values.get("is_deleted", False)
        self.identity = None

    @property
    def id(self):
        raise AssertionError("EXPIRED_ATTRIBUTE_ACCESS_FORBIDDEN")


class FakeQuery:
    def where(self, digest):
        self.digest = digest
        return self


class FakeSession:
    def __init__(self, rows=None, commit_error=None, query_error=None):
        self.rows = dict(rows or {})
        self.pending = []
        self.events = []
        self.committed = False
        self.commit_error = commit_error
        self.query_error = query_error

    def execute(self, query):
        self.events.append(("execute", query.digest))
        if self.query_error:
            raise self.query_error
        # Pending adds intentionally do not become query-visible (autoflush=False).
        return SimpleNamespace(scalar_one_or_none=lambda: self.rows.get(query.digest))

    def add(self, asset):
        self.events.append(("add", asset))
        self.pending.append(asset)

    def commit(self):
        self.events.append(("commit",))
        if self.commit_error:
            raise self.commit_error
        for index, asset in enumerate(self.pending):
            asset.identity = (101 + index,)  # Synthetic fixture IDs, not production IDs.
        self.committed = True

    def flush(self):
        raise AssertionError("EXPLICIT_FLUSH_FORBIDDEN")

    def refresh(self, *args):
        raise AssertionError("REFRESH_FORBIDDEN")

    def rollback(self):
        raise AssertionError("ROLLBACK_OR_RECOVERY_FORBIDDEN")


def existing(identity=7, deleted=False):
    asset = FakeAsset(file_path="old-private-path", is_deleted=deleted)
    asset.identity = (identity,)
    return asset


def request(query=""):
    return Request({"type": "http", "method": "POST", "path": "/assets/import",
                    "headers": [], "query_string": query.encode("ascii")})


def load_isolated_routes():
    """Compile only allowlisted definitions; never import routes/database/models."""
    path = ROOT / "src/api/routes_assets.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"_P1BImportResponseDocumentation", "_p1b_informational_requested",
             "_p1b_asset_id", "_p1b_import_response", "import_asset"}
    nodes = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    assert {node.name for node in nodes} == names
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom))
                   for definition in nodes for node in ast.walk(definition))

    def forbidden_db_dependency():
        raise AssertionError("REAL_DEPENDENCY_EXECUTION_FORBIDDEN")

    ns = dict(__name__="p1b_isolated_routes", APIRouter=APIRouter, Depends=Depends,
              HTTPException=HTTPException, Request=Request, JSONResponse=JSONResponse,
              RootModel=RootModel, Session=object, LocalAsset=FakeAsset,
              LocalAssetCreate=s.LocalAssetCreate, LocalAssetImportResponse=s.LocalAssetImportResponse,
              asset_schemas=s, get_db=forbidden_db_dependency,
              router=APIRouter(prefix="/assets"), select=lambda model: FakeQuery(),
              os=SimpleNamespace(path=SimpleNamespace(exists=Mock(return_value=True))),
              compute_md5=Mock(side_effect=lambda path: "md5:" + path))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), ns)
    return ns, tree


class P1BImportResultTests(unittest.TestCase):
    def setUp(self):
        self.ns, self.tree = load_isolated_routes()

    def invoke(self, paths, query=INFO, session=None):
        session = session or FakeSession()

        def inspect_identity(asset):
            self.assertTrue(session.committed)
            session.events.append(("inspect", asset))
            return SimpleNamespace(identity=asset.identity)

        self.ns["inspect_asset"] = Mock(side_effect=inspect_identity)
        answer = self.ns["import_asset"](
            s.LocalAssetCreate(file_paths=paths, asset_type="video"), request(query), session,
        )
        return answer, session

    def payload(self, paths, **kwargs):
        answer, session = self.invoke(paths, **kwargs)
        self.assertIsInstance(answer, JSONResponse)
        return json.loads(answer.body), session

    def test_t01_legacy_exact_three_fields(self):
        self.ns["os"].path.exists.side_effect = lambda path: path != "missing"
        self.ns["compute_md5"].side_effect = lambda path: (
            (_ for _ in ()).throw(OSError("synthetic-private-context"))
            if path == "hash-error" else "md5:" + path
        )
        session = FakeSession({"md5:duplicate": existing(), "md5:revive": existing(8, True)})
        answer, session = self.invoke(["fresh", "duplicate", "revive", "missing", "hash-error"],
                                      query="", session=session)
        self.assertEqual(answer.model_dump(), {
            "success_count": 2, "skipped_count": 3,
            "message": "成功导入 2 个素材，跳过 3 个已存在或无效的文件",
        })
        self.assertEqual(type(answer), s.LocalAssetImportResponse)
        self.ns["inspect_asset"].assert_not_called()
        self.assertEqual([event[0] for event in session.events].count("commit"), 1)

    def test_t02_valid_opt_in_independent_response(self):
        data, _ = self.payload(["fresh"])
        self.assertEqual(set(data), {"result_format", "success_count", "skipped_count", "message", "results"})
        self.assertEqual(data["result_format"], "p1b-info-v1")
        self.assertEqual(data["results"][0]["import_outcome"], "CREATED")
        self.assertEqual(s.P1BInformationalImportResponse.model_validate(data).model_dump(mode="json"), data)
        # Another, unrelated query key does not opt the caller into P1-B.
        answer, _ = self.invoke([], query="other=p1b-info-v1")
        self.assertIsInstance(answer, s.LocalAssetImportResponse)
        empty, session = self.payload([])
        self.assertEqual(empty["results"], [])
        self.assertEqual((empty["success_count"], empty["skipped_count"]), (0, 0))
        self.assertEqual(session.events, [("commit",)])

    def test_t03_invalid_and_empty_selector(self):
        for query in ("result_format=", "result_format", "result_format=unknown",
                      "result_format=%FF", "result_format=p1b-info-v1%", "result_format=" + "x" * 10000):
            with self.subTest(query_kind=query[:40]), self.assertRaises(HTTPException) as raised:
                self.invoke(["private-path"], query=query)
            self.assertEqual(raised.exception.status_code, 400)
            self.assertEqual(raised.exception.detail, {
                "reason_code": "CONTRACT_INVALID", "operator_next_action": "REVIEW_CONTRACT",
            })

    def test_t04_repeated_selectors_including_identical(self):
        for query in (INFO + "&" + INFO, INFO + "&result_format=unknown",
                      "result_format=&result_format=", INFO + "&" + INFO + "&" + INFO):
            with self.subTest(query=query), self.assertRaises(HTTPException) as raised:
                self.invoke(["fresh"], query=query)
            self.assertEqual(raised.exception.status_code, 400)

    def test_t05_selector_rejected_before_business_work(self):
        for query in ("result_format=unknown", INFO + "&" + INFO):
            session = FakeSession()
            with self.assertRaises(HTTPException):
                self.invoke(["fresh"], query=query, session=session)
            self.ns["os"].path.exists.assert_not_called()
            self.ns["compute_md5"].assert_not_called()
            self.ns["inspect_asset"].assert_not_called()
            self.assertEqual(session.events, [])

    def test_t06_order_indices_and_repeated_inputs(self):
        duplicate = existing()
        self.ns["compute_md5"].return_value = "unused"
        self.ns["compute_md5"].side_effect = lambda path: "same-md5"
        data, session = self.payload(["C:/private/same.mp4", "C:/private/same.mp4", "D:/other/same.mp4"],
                                     session=FakeSession({"same-md5": duplicate}))
        self.assertEqual([r["input_index"] for r in data["results"]], [0, 1, 2])
        self.assertEqual([r["file_display_name"] for r in data["results"]], ["input-0", "input-1", "input-2"])
        self.assertEqual([r["import_outcome"] for r in data["results"]], ["DUPLICATE_EXISTING"] * 3)
        self.assertEqual(len([e for e in session.events if e[0] == "execute"]), 3)
        self.assertEqual(duplicate.file_path, "old-private-path")

    def test_t07_post_commit_identity_tuple_without_id_attribute(self):
        revived = existing(8, True)
        data, session = self.payload(["fresh", "duplicate", "revive"], session=FakeSession({
            "md5:duplicate": existing(7), "md5:revive": revived,
        }))
        self.assertEqual([r["import_outcome"] for r in data["results"]], ["CREATED", "DUPLICATE_EXISTING", "REVIVED"])
        self.assertEqual([r["references"]["asset_id"]["value"] for r in data["results"]], [101, 7, 8])
        names = [e[0] for e in session.events]
        self.assertGreater(names.index("inspect"), names.index("commit"))
        self.assertFalse(revived.is_deleted)
        self.assertEqual(revived.file_path, "revive")
        for bad in (None, (), (None,), (True,), ("7",), (0,), (-1,), (7, 8), [7]):
            with self.subTest(identity=bad):
                asset = existing()
                asset.identity = bad
                with self.assertRaisesRegex(ValueError, "^P1B_RESPONSE_UNAVAILABLE$"):
                    self.payload(["duplicate"], session=FakeSession({"md5:duplicate": asset}))
        session = FakeSession()

        def committed_without_identity():
            session.events.append(("commit",))
            session.committed = True

        session.commit = Mock(side_effect=committed_without_identity)
        with self.assertRaisesRegex(ValueError, "^P1B_RESPONSE_UNAVAILABLE$"):
            self.payload(["fresh"], session=session)
        session.commit.assert_called_once()
        self.assertIsNone(session.pending[0].identity)

    def test_t08_commit_query_and_post_commit_failures(self):
        for query in ("", INFO):
            for kind in ("commit_error", "query_error"):
                error = RuntimeError("synthetic-private-database-detail")
                session = FakeSession(**{kind: error})
                with self.subTest(query=query, kind=kind), self.assertRaises(RuntimeError) as raised:
                    self.invoke(["fresh"], query=query, session=session)
                self.assertIs(raised.exception, error)  # Existing request-level exception path, no invented result.
                self.ns["inspect_asset"].assert_not_called()
                self.assertLessEqual([e[0] for e in session.events].count("commit"), 1)
        for target in ("dto", "json"):
            session = FakeSession()
            patcher = (patch.object(s.P1BInformationalImportResponse, "model_validate",
                                    side_effect=ValueError("synthetic-private-projection"))
                       if target == "dto" else patch.dict(self.ns, JSONResponse=Mock(
                           side_effect=TypeError("synthetic-private-serialization"))))
            with patcher, self.assertRaisesRegex(ValueError, "^P1B_RESPONSE_UNAVAILABLE$") as raised:
                self.invoke(["fresh"], session=session)
            self.assertTrue(session.committed)
            self.assertTrue(raised.exception.__suppress_context__)
            self.assertEqual([e[0] for e in session.events].count("commit"), 1)

    def test_t09_public_projection_privacy_and_missing_inputs(self):
        self.ns["os"].path.exists.side_effect = lambda path: path != "missing"
        self.ns["compute_md5"].side_effect = OSError("C:/synthetic/private?credential=synthetic")
        data, _ = self.payload(["missing", "C:/synthetic/private.mp4"])
        self.assertEqual([r["import_outcome"] for r in data["results"]], ["NOT_COMPLETED"] * 2)
        self.assertEqual(data["results"][0]["reason_code"], "FILE_MISSING_OR_UNREADABLE")
        self.assertEqual(data["results"][1]["reason_code"], "NOT_EVALUATED")
        encoded = json.dumps(data)
        for forbidden in ("C:/", "private", "credential", "facts", "persistence_confirmed", "exception"):
            self.assertNotIn(forbidden, encoded)
        for result in data["results"]:
            for reference in result["references"].values():
                self.assertEqual(reference, {"value": None, "state": "NOT_ESTABLISHED", "provenance": None})

    def test_t10_no_qualification_or_fabricated_proof(self):
        data, _ = self.payload(["fresh", "duplicate", "revive"], session=FakeSession({
            "md5:duplicate": existing(), "md5:revive": existing(8, True),
        }))
        for result in data["results"]:
            self.assertEqual(result["technical_validation"], {"status": "NOT_EVALUATED"})
            self.assertEqual(result["qualification_activation"], {"status": "NOT_QUALIFIED"})
            for key, value in result["references"].items():
                if key != "asset_id":
                    self.assertEqual(value, {"value": None, "state": "NOT_ESTABLISHED", "provenance": None})
        for field, status in (("technical_validation", "PASS"), ("qualification_activation", "PASS"),
                              ("qualification_activation", "PENDING_ACK")):
            bad = json.loads(json.dumps(data))
            bad["results"][0][field]["status"] = status
            with self.assertRaises(ValidationError):
                s.P1BInformationalImportResponse.model_validate(bad, context={"authorized": True, "ack_confirmed": True})

    def test_t11_single_commit_no_extra_sql_or_external_side_effects(self):
        handler = next(n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name == "import_asset")
        calls = [n.func.attr for n in ast.walk(handler) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        self.assertEqual(calls.count("commit"), 1)
        self.assertEqual(calls.count("execute"), 1)
        self.assertFalse(set(calls) & {"flush", "refresh", "rollback"})
        self.assertNotIn("sqlalchemy", sys.modules)
        self.assertNotIn("src.api.database", sys.modules)
        targets = [(builtins, "open"), (io, "open"), (os, "open"), (Path, "open"),
                   (socket, "socket"), (socket, "create_connection"),
                   (subprocess, "Popen"), (subprocess, "run"), (os, "system")]
        with ExitStack() as guards:
            interceptors = [guards.enter_context(patch.object(owner, name,
                            side_effect=AssertionError("BUSINESS_SIDE_EFFECT_FORBIDDEN"))) for owner, name in targets]
            data, session = self.payload(["fresh", "duplicate"], session=FakeSession({"md5:duplicate": existing()}))
            self.assertEqual(data["success_count"], 1)
            self.assertEqual([e[0] for e in session.events].count("execute"), 2)
            self.assertEqual([e[0] for e in session.events].count("commit"), 1)
            for interceptor in interceptors:
                interceptor.assert_not_called()

    def test_t12_internal_validation_public_dto_and_isolated_openapi(self):
        original = s.serialize_p1a_results

        def serialize(batch):
            self.assertTrue(batch.results[0].facts.persistence_confirmed.value)
            answer = original(batch)
            self.assertNotIn("facts", answer[0])
            return answer

        with patch.object(s, "serialize_p1a_results", side_effect=serialize) as observed:
            data, _ = self.payload(["fresh"])
            observed.assert_called_once()
        bad = s.P1BInformationalImportResponse.model_validate(data).model_copy(update={"success_count": 99})
        with self.assertRaises(ValidationError):
            s.P1BInformationalImportResponse.model_validate(bad)
        bad_data = json.loads(json.dumps(data))
        bad_data["results"][0]["facts"] = {"authorized": True}
        with self.assertRaises(ValidationError):
            s.P1BInformationalImportResponse.model_validate(bad_data)
        bad_data = json.loads(json.dumps(data))
        bad_data["results"][0]["file_display_name"] = "C:/private/file.mp4"
        with self.assertRaises(ValidationError) as raised:
            s.P1BInformationalImportResponse.model_validate(bad_data)
        self.assertNotIn("C:/private", str(raised.exception))
        for key in ("content_version", "source_binding_revision", "qualification_proof", "generation", "operation"):
            with self.subTest(unestablished_reference=key):
                bad_data = json.loads(json.dumps(data))
                bad_data["results"][0]["references"][key] = {
                    "value": "synthetic-unsupported", "state": "PRESENT", "provenance": "BACKEND_OBSERVED",
                }
                with self.assertRaises(ValidationError):
                    s.P1BInformationalImportResponse.model_validate(bad_data)
        bad_data = json.loads(json.dumps(data))
        bad_data["results"][0]["references"]["asset_id"]["provenance"] = "CLIENT_ASSERTED"
        with self.assertRaises(ValidationError):
            s.P1BInformationalImportResponse.model_validate(bad_data)
        bad_data = json.loads(json.dumps(data))
        bad_data["results"][0].update(input_index=1, file_display_name="input-1")
        unchecked = s.P1BInformationalImportResponse.model_construct(**bad_data)
        with self.assertRaises(ValidationError):
            s.P1BInformationalImportResponse.model_validate(unchecked)

        route = self.ns["router"].routes[0]
        self.assertIs(route.response_model, s.LocalAssetImportResponse)
        document = get_openapi(title="isolated P1-B declarations", version="test", routes=[route])
        operation = document["paths"]["/assets/import"]["post"]
        schemas = document["components"]["schemas"]
        response = operation["responses"]["200"]["content"]["application/json"]["schema"]
        union = schemas[response["$ref"].rsplit("/", 1)[1]]
        names = {part["$ref"].rsplit("/", 1)[1] for part in union["anyOf"]}
        self.assertEqual(names, {"LocalAssetImportResponse", "P1BInformationalImportResponse"})
        self.assertEqual(set(schemas["LocalAssetImportResponse"]["properties"]), {"success_count", "skipped_count", "message"})
        self.assertEqual(set(schemas["P1BInformationalImportResponse"]["required"]), set(data))
        self.assertNotIn('"facts"', json.dumps(schemas))
        selector = next(p for p in operation["parameters"] if p["name"] == "result_format")
        self.assertFalse(selector["required"])
        self.assertIn("repetition", selector["description"])
        error = operation["responses"]["400"]["content"]["application/json"]["schema"]
        self.assertEqual(error["properties"]["detail"]["properties"]["reason_code"]["const"], "CONTRACT_INVALID")

    def test_t13_existing_p1a_contract_and_test_preserved(self):
        self.assertEqual(set(s.LocalAssetImportResponse.model_fields), {"success_count", "skipped_count", "message"})
        self.assertEqual({name for name, field in s.LocalAssetCreate.model_fields.items() if field.is_required()},
                         {"file_paths", "asset_type"})
        self.assertEqual(hashlib.sha256((ROOT / "tests/test_ig01a_p1a_contracts.py").read_bytes()).hexdigest().upper(),
                         "AB26512EEE935FF02F004CDA2F9554C3E449A712A5ADCEBEDB175BDF178DC045")
        self.assertFalse(s.decide_p1a_invalidation(s.P1AInvalidationFacts(event="ACTIVE_DUPLICATE")).normal_use_permitted)

    def test_t14_no_new_intra_batch_dedup_or_retry(self):
        self.ns["compute_md5"].side_effect = lambda path: "same-unseen-md5"
        error = RuntimeError("synthetic-unconfirmed-transaction")
        session = FakeSession(commit_error=error)
        with self.assertRaises(RuntimeError) as raised:
            self.invoke(["same", "same"], session=session)
        self.assertIs(raised.exception, error)
        self.assertEqual(len(session.pending), 2)
        self.assertEqual([e[0] for e in session.events].count("execute"), 2)
        self.assertEqual([e[0] for e in session.events].count("commit"), 1)
        self.ns["inspect_asset"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
