"""P1A-T01..T16: synthetic facts only; no route, DB, media or service fixtures."""
import ast
import builtins
import io
import json
import os
import pathlib
import socket
import subprocess
import sys
import unittest
import uuid
import urllib.request
from contextlib import ExitStack
from unittest.mock import patch

from pydantic import StrictBool, ValidationError
from src.api import schemas as s


def ref(value, provenance="BACKEND_OBSERVED"):
    return {"value": value, "state": "PRESENT", "provenance": provenance}


def references():
    return dict(zip(s.P1AIdentityReferences.model_fields, (
        ref(7), ref("content-1"), ref("binding-1"),
        ref("proof-1"), ref("generation-1"), ref("operation-1"),
    )))


def result(index=0, **changes):
    values = dict(
        input_index=index, file_display_name="same.mp4",
        import_outcome="DUPLICATE_EXISTING", reason_code="NOT_EVALUATED",
        operator_next_action="REVIEW_EXISTING",
    )
    values.update(changes)
    return s.P1APerInputResult(**values)


def decide(event, **changes):
    return s.decide_p1a_invalidation(s.P1AInvalidationFacts(event=event, **changes))


class P1AContractTests(unittest.TestCase):
    def test_p1a_t01_six_independent_identities(self):
        identities = s.P1AIdentityReferences(**references())
        self.assertEqual(len(type(identities).model_fields), 6)
        for key in type(identities).model_fields:
            changed = references()
            changed[key] = ref(8 if key == "asset_id" else "independent-2")
            other = s.P1AIdentityReferences(**changed)
            self.assertNotEqual(getattr(identities, key), getattr(other, key))
            for untouched in set(type(identities).model_fields) - {key}:
                self.assertEqual(getattr(identities, untouched), getattr(other, untouched))
        with self.assertRaises(ValidationError):
            s.P1AIdentityReferences(asset_id=ref("7"))
        self.assertEqual(s.P1AIdentityReferences().asset_id.state, "NOT_ESTABLISHED")

    def test_p1a_t02_same_path_changed_bytes(self):
        facts = s.P1AInvalidationFacts(event="SAME_PATH_BYTES_CHANGED", references=references())
        before = facts.model_dump()
        answer = s.decide_p1a_invalidation(facts)
        self.assertEqual(answer.content_version_action, "NEW_REQUIRED")
        self.assertEqual(answer.source_binding_action, "NEW_REQUIRED")
        self.assertTrue(answer.qualification_invalidation_required)
        self.assertTrue(answer.requalification_required)
        self.assertEqual(facts.model_dump(), before)

    def test_p1a_t03_different_path_same_bytes(self):
        answer = decide("DIFFERENT_PATH_SAME_BYTES", references=references(), same_bytes=ref(True))
        self.assertEqual(answer.content_version_action, "KEEP")
        self.assertEqual(answer.source_binding_action, "NEW_REQUIRED")
        self.assertEqual(answer.operation_action, "NEW_REQUIRED")
        for evidence in ({}, ref(True, "CLIENT_ASSERTED"), {"state": "UNKNOWN"}):
            answer = decide("DIFFERENT_PATH_SAME_BYTES", references=references(), same_bytes=evidence)
            self.assertEqual(answer.content_version_action, "UNDETERMINED")
        answer = decide("DIFFERENT_PATH_BYTES_CHANGED")
        self.assertEqual(answer.content_version_action, "NEW_REQUIRED")
        self.assertEqual(answer.source_binding_action, "NEW_REQUIRED")

    def test_p1a_t04_md5_is_not_identity_or_authorization(self):
        for field in ("md5", "file_path", "size", "mtime", "tenant_id"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                s.P1AIdentityReferences(**{field: "client-assertion"})
        answer = decide("SAME_MD5_REVIVAL")
        self.assertEqual(answer.content_version_action, "UNDETERMINED")
        self.assertFalse(answer.normal_use_permitted)
        with self.assertRaises(ValidationError):
            s.P1AQualificationActivation(status="PASS")

    def test_p1a_t05_three_independent_dimensions(self):
        created = result(
            import_outcome="CREATED", references=references(),
            facts={"persistence_confirmed": ref(True)},
        )
        self.assertEqual(created.technical_validation.status, "NOT_EVALUATED")
        self.assertEqual(created.qualification_activation.status, "NOT_QUALIFIED")
        with self.assertRaises(ValidationError):
            result(import_outcome="CREATED", references=references())
        with self.assertRaises(ValidationError):
            result(import_outcome="REJECTED", facts={"persistence_confirmed": ref(True)})
        for outcome in ("NOT_COMPLETED", "PERSISTENCE_UNKNOWN", "REJECTED"):
            self.assertEqual(result(import_outcome=outcome).qualification_activation.status, "NOT_QUALIFIED")
        with self.assertRaises(ValidationError):
            result(import_outcome="REPLACED")

    def test_p1a_t06_technical_pass_is_not_activation(self):
        passed = result(
            technical_validation={"status": "PASS"},
            facts={"technical_completed": ref(True), "existing_binding_current": ref(True)},
        )
        self.assertEqual(passed.technical_validation.status, "PASS")
        self.assertEqual(passed.qualification_activation.status, "NOT_QUALIFIED")
        with self.assertRaises(ValidationError):
            result(technical_validation={"status": "PASS"})
        self.assertEqual({x.value for x in s.P1ATechnicalStatus}, {
            "NOT_EVALUATED", "PENDING", "PASS", "REJECTED", "UNVERIFIED", "UNSUPPORTED_PROFILE",
        })
        with self.assertRaises(ValidationError):
            s.P1ATechnicalValidation(status="AI_ANALYSIS_FAILED")

    def test_p1a_t07_no_caller_pass_or_ack_bypass(self):
        for claims in ({}, {"authorized": True}, {"ack_confirmed": True}, {"tenant_id": "a"}):
            with self.assertRaises(ValidationError):
                s.P1AQualificationActivation.model_validate(
                    {"status": "PASS", **claims}, context={"authorized": True, "ack_confirmed": True},
                )
        with self.assertRaises(ValidationError):
            result(references=references(), qualification_activation={"status": "PASS"})
        forged = result().model_copy(update={
            "qualification_activation": s.P1AQualificationActivation.model_construct(status="PASS"),
        })
        batch = s.P1AResultBatch.model_construct(results=(forged,))
        with self.assertRaisesRegex(ValueError, "^P1A_CONTRACT_INVALID$"):
            s.serialize_p1a_results(batch)

    def test_p1a_t08_pending_ack_is_not_technical_pending(self):
        with self.assertRaises(ValidationError):
            s.P1ATechnicalValidation(status="PENDING_ACK")
        with self.assertRaises(ValidationError):
            result(qualification_activation={"status": "PENDING_ACK"})
        pending = result(
            import_outcome="CREATED", references=references(), technical_validation={"status": "PASS"},
            qualification_activation={"status": "PENDING_ACK"},
            facts={"persistence_confirmed": ref(True),
                   "technical_completed": ref(True), "phase1_persisted": ref(True),
                   "existing_binding_current": ref(True)},
        )
        self.assertEqual(pending.technical_validation.status, "PASS")
        self.assertEqual(pending.qualification_activation.status, "PENDING_ACK")
        self.assertNotEqual(pending.qualification_activation.status, "PASS")
        duplicate = pending.model_dump()
        duplicate["facts"] = pending.facts.model_dump()
        duplicate["import_outcome"] = "DUPLICATE_EXISTING"
        with self.assertRaises(ValidationError):
            s.P1APerInputResult.model_validate(duplicate)
        forged = pending.model_copy(update={"import_outcome": s.P1AImportOutcome.DUPLICATE_EXISTING})
        with self.assertRaises(ValueError):
            s.serialize_p1a_results(s.P1AResultBatch.model_construct(results=(forged,)))

    def test_p1a_t09_missing_fact_distinctions(self):
        for state in ("NOT_ESTABLISHED", "UNKNOWN", "NOT_APPLICABLE"):
            fact = s.P1AEvidenceReference[str](state=state)
            self.assertIsNone(fact.value)
            self.assertEqual(fact.model_dump(mode="json")["state"], state)
            with self.assertRaises(ValidationError):
                s.P1AEvidenceReference[str](state=state, value="fabricated")
        with self.assertRaises(ValidationError):
            s.P1AEvidenceReference[str](state="PRESENT", provenance="BACKEND_OBSERVED")
        false_fact = s.P1AEvidenceReference[StrictBool](**ref(False))
        self.assertIs(false_fact.value, False)
        with self.assertRaises(ValidationError):
            s.P1AEvidenceReference[StrictBool](**ref(1))
        for value in ({"credential": "SYNTHETIC_ONLY"}, ["not-an-id"], 1.5):
            with self.assertRaises(ValidationError):
                s.P1AEvidenceReference(**ref(value))

    def test_p1a_t10_provenance_does_not_grant_trust(self):
        for provenance in ("CLIENT_ASSERTED", "BACKEND_OBSERVED"):
            fact = s.P1AEvidenceReference[str](**ref("claimed-id", provenance))
            self.assertEqual(fact.provenance, provenance)
        for state in s.P1AEvidenceState:
            with self.assertRaises(ValidationError):
                s.P1AEvidenceReference[str].model_validate(
                    {"state": state, "value": "issuer-id" if state == "PRESENT" else None,
                     "provenance": "TRUSTED_AUTHORITY_VERIFIED"},
                    context={"trusted_authority_qualified": True},
                )
        bad_refs = s.P1AIdentityReferences(**references()).model_copy(update={
            "qualification_proof": s.P1AEvidenceReference[str].model_construct(
                value="synthetic-proof", state="PRESENT", provenance="TRUSTED_AUTHORITY_VERIFIED",
            ),
        })
        forged = result().model_copy(update={"references": bad_refs})
        with self.assertRaises(ValueError):
            s.serialize_p1a_results(s.P1AResultBatch.model_construct(results=(forged,)))

    def test_p1a_t11_duplicate_restore_revival(self):
        facts = s.P1AInvalidationFacts(event="ACTIVE_DUPLICATE", references=references())
        before = facts.model_dump()
        duplicate = s.decide_p1a_invalidation(facts)
        # Preserve the old record, not evidence of its PASS. The incoming
        # request must not get use/ACK/proof/path binding from those references.
        self.assertFalse(duplicate.qualification_invalidation_required)
        self.assertTrue(duplicate.requalification_required)
        self.assertFalse(duplicate.normal_use_permitted)
        self.assertFalse(duplicate.automatic_rebind_permitted)
        self.assertEqual(duplicate.generation_action, "KEEP")
        self.assertEqual(duplicate.operation_action, "KEEP")
        self.assertEqual(facts.model_dump(), before)
        self.assertNotIn("references", duplicate.model_dump())
        self.assertNotIn("operation_id", duplicate.model_dump())
        unknown = decide("ACTIVE_DUPLICATE")
        self.assertEqual(unknown.operation_action, "UNDETERMINED")
        self.assertTrue(unknown.requalification_required)
        existing = result(references=references(), technical_validation={"status": "PASS"},
                          facts={"technical_completed": ref(True), "existing_binding_current": ref(True)})
        self.assertEqual(existing.qualification_activation.status, "NOT_QUALIFIED")
        for outcome, event in (("RESTORED", "TRASH_RESTORE"), ("REVIVED", "SAME_MD5_REVIVAL")):
            item = result(import_outcome=outcome, references=references(), facts={"persistence_confirmed": ref(True)})
            self.assertEqual(item.import_outcome, outcome)
            self.assertEqual(item.technical_validation.status, "NOT_EVALUATED")
            self.assertTrue(decide(event).requalification_required)
            with self.assertRaises(ValidationError):
                result(import_outcome=outcome, references=references(),
                       facts={"persistence_confirmed": ref(True), "technical_completed": ref(True)},
                       technical_validation={"status": "PASS"})

    def test_p1a_t12_events_purge_and_late_results(self):
        self.assertEqual(len(s.P1AEvent), 14)
        for event in s.P1AEvent:
            answer = decide(event)
            self.assertFalse(answer.normal_use_permitted)
            self.assertFalse(answer.automatic_rebind_permitted)
            self.assertTrue(answer.preserve_history)
            self.assertTrue(answer.preserve_proof_operation_tombstones)
            self.assertTrue(answer.preserve_resource_responsibility)
            self.assertNotEqual(answer.content_version_action, "KEEP")
        purge = decide("PURGE")
        self.assertEqual(purge.operation_action, "RETIRE")
        self.assertTrue(purge.reject_stale_result)
        current, candidate = references(), references()

        def check_late(left, right, binding, rejected):
            facts = s.P1AInvalidationFacts(
                event="LATE_RESULT_ACK_OR_RECOVER", references=references(),
                current_references=left, candidate_references=right, binding_current=binding,
            )
            before = facts.model_dump()
            answer = s.decide_p1a_invalidation(facts)
            self.assertEqual(answer.reject_stale_result, rejected)
            if rejected:
                self.assertEqual(answer.reason_code, "STALE_RESULT_REJECTED")
            self.assertTrue(answer.requalification_required)
            self.assertTrue(answer.qualification_invalidation_required)
            self.assertFalse(answer.normal_use_permitted)
            self.assertFalse(answer.automatic_rebind_permitted)
            self.assertEqual(facts.model_dump(), before)

        check_late(current, candidate, ref(True), False)
        for key in s.P1AIdentityReferences.model_fields:
            with self.subTest(identity=key):
                changed = references()
                changed[key] = ref(8 if key == "asset_id" else "mismatch-2")
                check_late(current, changed, ref(True), True)
                for side in ("current", "candidate"):
                    for evidence in ({}, {"state": "UNKNOWN"},
                                     {"state": "NOT_APPLICABLE"},
                                     ref(candidate[key]["value"], "CLIENT_ASSERTED")):
                        insufficient = references()
                        insufficient[key] = evidence
                        check_late(insufficient if side == "current" else current,
                                   insufficient if side == "candidate" else candidate, ref(True), True)
        for binding in ({}, {"state": "UNKNOWN"}, ref(True, "CLIENT_ASSERTED"), ref(False)):
            check_late(current, candidate, binding, True)
        # The legacy single set must not fill either missing independent set.
        check_late({}, candidate, ref(True), True)
        check_late(current, {}, ref(True), True)
        # Revalidate unchecked objects; invalid values/types/provenance reject,
        # rather than counting their mere presence or mutating the input.
        valid = s.P1AInvalidationFacts(
            event="LATE_RESULT_ACK_OR_RECOVER", current_references=current,
            candidate_references=candidate, binding_current=ref(True),
        )
        for field, bad in (("asset_id", ref(0)), ("operation", ref("bad/path")),
                           ("asset_id", ref("7")),
                           ("operation", ref("operation-1", "TRUSTED_AUTHORITY_VERIFIED"))):
            for side in ("current_references", "candidate_references"):
                malformed = getattr(valid, side).model_copy(update={field: bad})
                forged = valid.model_copy(update={side: malformed})
                before = repr(forged)
                answer = s.decide_p1a_invalidation(forged)
                self.assertTrue(answer.reject_stale_result)
                self.assertEqual(answer.reason_code, "STALE_RESULT_REJECTED")
                self.assertEqual(repr(forged), before)
        for compatibility in ({}, {"state": "UNKNOWN"}, ref(True, "CLIENT_ASSERTED"), ref(True)):
            facts = s.P1AInvalidationFacts(event="VALIDATION_POLICY_CHANGED", references=references(),
                                          compatibility_allows_reuse=compatibility)
            before = facts.model_dump()
            answer = s.decide_p1a_invalidation(facts)
            self.assertTrue(answer.requalification_required)
            self.assertTrue(answer.qualification_invalidation_required)
            self.assertFalse(answer.normal_use_permitted)
            self.assertEqual(facts.model_dump(), before)
        self.assertTrue(decide("TRASH").qualification_invalidation_required)

    def test_p1a_t13_order_repeated_inputs_and_missing_references(self):
        batch = s.P1AResultBatch(results=(result(), result(1)))
        encoded = s.serialize_p1a_results(batch)
        self.assertEqual([x["input_index"] for x in encoded], [0, 1])
        self.assertEqual([x["file_display_name"] for x in encoded], ["same.mp4", "same.mp4"])
        self.assertNotIn("facts", encoded[0])
        for missing in encoded[0]["references"].values():
            self.assertEqual(missing, {"value": None, "state": "NOT_ESTABLISHED", "provenance": None})
        for items in ((result(1), result()), (result(), result())):
            with self.assertRaises(ValidationError):
                s.P1AResultBatch(results=items)

    def test_p1a_t14_privacy_and_unchecked_serialization(self):
        sentinel = "SYNTHETIC_PRIVATE_ONLY"
        for name in ("C:\\private\\" + sentinel, "/private/" + sentinel,
                     "\\\\server\\" + sentinel, "https://host/" + sentinel, "bad\nname"):
            with self.assertRaises(ValidationError) as raised:
                result(file_display_name=name)
            self.assertNotIn(sentinel, str(raised.exception))
            self.assertNotIn(sentinel, json.dumps(s.safe_p1a_validation_errors(raised.exception)))
        for key in ("credential", "token", sentinel):
            with self.assertRaises(ValidationError) as raised:
                result(**{key: sentinel})
            self.assertNotIn(sentinel, str(raised.exception))
        for change in ({"file_display_name": "/private/" + sentinel},
                       {"reason_code": sentinel}, {"operator_next_action": sentinel}):
            forged = result().model_copy(update=change)
            with self.assertRaisesRegex(ValueError, "^P1A_CONTRACT_INVALID$"):
                s.serialize_p1a_results(s.P1AResultBatch.model_construct(results=(forged,)))
        with self.assertRaises(ValidationError):
            s.P1AEvidenceReference[str](**ref("C:\\private\\" + sentinel))

    def test_p1a_t15_legacy_compatibility(self):
        response = s.LocalAssetImportResponse(success_count=2, skipped_count=3, message="legacy summary")
        self.assertEqual(response.model_dump(), {"success_count": 2, "skipped_count": 3, "message": "legacy summary"})
        self.assertEqual(set(s.LocalAssetImportResponse.model_fields), {"success_count", "skipped_count", "message"})
        self.assertEqual(set(s.LocalAssetCreate.model_fields), {"file_paths", "asset_type", "video_role", "tags", "entity_id", "asset_name"})
        self.assertEqual(s.LocalAssetCreate(file_paths=["synthetic.mp4"], asset_type="video").video_role, "general")
        self.assertEqual({k for k, f in s.LocalAssetCreate.model_fields.items() if f.is_required()}, {"file_paths", "asset_type"})
        self.assertNotIn("qualification_activation", s.LocalAssetResponse.model_fields)
        self.assertEqual(s.VideoTaskCreate(prompt="synthetic").batch_size, 1)
        self.assertEqual(s.RenderDSLRequest(engine_type="content", timeline=[]).reservation_conflict_mode, "OFF")

    def test_p1a_t16_no_business_side_effects(self):
        # Phase A: source-only I/O, before runtime guards. Inspect the entire
        # appended P1-A block, including defaults, validators and serializers.
        source = pathlib.Path(s.__file__).read_text(encoding="utf-8")
        marker = "# P1-A: independent, in-memory contracts; deliberately not wired to live routes."
        self.assertEqual(source.count(marker), 1)
        block = ast.parse(source.split(marker, 1)[1])
        allowed_globals = {
            "BaseModel", "ConfigDict", "Field", "StrictBool", "StrictInt", "StrictStr",
            "ValidationError", "model_validator", "Enum", "Generic", "Optional",
            "Literal", "TypeVar", "str", "int", "bool", "type", "isinstance",
            "any", "all", "getattr", "ord", "tuple", "range", "len",
            "ValueError", "classmethod",
        }
        allowed_calls = {
            "ConfigDict", "Field", "model_validator", "TypeVar", "ValueError",
            "type", "isinstance", "any", "all", "getattr", "ord", "tuple", "range", "len",
            "handler", "ch.isascii", "ch.isalnum", "checked.model_dump",
            "P1AResultBatch.model_validate", "P1AInvalidationFacts.model_validate",
            "P1AInvalidationFacts", "P1AInvalidationDecision", "_p1a_observed", "_p1a_true",
        }

        def static_violations(tree):
            nodes = list(ast.walk(tree))
            bound = {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            bound.update(n.arg for n in nodes if isinstance(n, ast.arg))
            bound.update(n.name for n in nodes if isinstance(n, (ast.ClassDef, ast.FunctionDef)))
            failures = []
            for node in nodes:
                if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
                    failures.append(type(node).__name__)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    if node.id not in bound | allowed_globals:
                        failures.append("global:" + node.id)
                if isinstance(node, ast.Call) and ast.unparse(node.func) not in allowed_calls:
                    failures.append("call:" + ast.unparse(node.func))
            return failures

        self.assertEqual(static_violations(block), [])
        # Negative controls exercise the checker without executing these strings.
        for snippet in (
            "import sqlite3", "from sqlalchemy import create_engine",
            "from src.api import routes_assets", "from src.services import validator",
            "import main", "open('synthetic')", "io.open('synthetic')",
            "os.open('synthetic', 0)", "pathlib.Path('synthetic').open()",
            "socket.create_connection(('synthetic', 1))", "urllib.request.urlopen('synthetic')",
            "subprocess.Popen(['synthetic'])", "os.system('synthetic')",
            "uuid.uuid4()", "secrets.token_urlsafe()", "exec('synthetic')",
        ):
            self.assertTrue(static_violations(ast.parse(snippet)), snippet)
        imported = set()
        for node in ast.parse(source).body:
            if isinstance(node, ast.Import):
                imported.update(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {
            "__future__", "datetime", "enum", "typing", "pydantic", "approval_types", "task_identity",
        })

        # Phase B: no source reading or fixture I/O under runtime guards. These
        # cover named APIs, not all possible security or native-runtime behavior.
        def business_import(name):
            return (name.split(".")[0] in {"sqlite3", "_sqlite3", "sqlalchemy", "fastapi", "main"}
                    or name == "src.api.database" or name.startswith("src.api.database.")
                    or name.startswith(("src.api.routes", "src.api.services", "src.services",
                                        "src.nodes", "src.core")))

        self.assertEqual([name for name in sys.modules if business_import(name)], [])
        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            fromlist = kwargs.get("fromlist", args[2] if len(args) > 2 else ())
            if business_import(name) or any(business_import(name + "." + item) for item in (fromlist or ())):
                raise AssertionError("BUSINESS_IMPORT_FORBIDDEN")
            return real_import(name, *args, **kwargs)

        targets = [
            (builtins, "open"), (io, "open"), (os, "open"), (pathlib.Path, "open"),
            (socket, "socket"), (socket, "create_connection"),
            (urllib.request, "urlopen"), (urllib.request.OpenerDirector, "open"),
        ]
        targets.extend((subprocess, name) for name in ("Popen", "run", "call", "check_call", "check_output"))
        targets.extend((os, name) for name in (
            "system", "popen", "startfile", "fork", "forkpty", "posix_spawn", "posix_spawnp",
            "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
            "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
        ) if hasattr(os, name))
        targets.extend((uuid, name) for name in ("uuid1", "uuid3", "uuid4", "uuid5", "uuid6", "uuid7", "uuid8", "getnode")
                       if hasattr(uuid, name))
        # No SQLite/SQLAlchemy import just to patch them: module absence plus
        # import interception and the static dependency boundary enforce that gap.
        with ExitStack() as guards:
            interceptors = [guards.enter_context(patch.object(
                owner, name, side_effect=AssertionError("SIDE_EFFECT_FORBIDDEN"),
            )) for owner, name in targets]
            guards.enter_context(patch.object(builtins, "__import__", side_effect=guarded_import))
            for event in s.P1AEvent:
                facts = s.P1AInvalidationFacts(event=event, references=references(),
                                              current_references=references(), candidate_references=references(),
                                              binding_current=ref(True), compatibility_allows_reuse=ref(True))
                before = facts.model_dump()
                answer = s.decide_p1a_invalidation(facts)
                self.assertFalse(answer.normal_use_permitted)
                self.assertEqual(answer, s.decide_p1a_invalidation(facts))
                self.assertEqual(facts.model_dump(), before)
            pending = result(import_outcome="CREATED", references=references(),
                             technical_validation={"status": "PASS"}, qualification_activation={"status": "PENDING_ACK"},
                             facts={"persistence_confirmed": ref(True), "technical_completed": ref(True),
                                    "phase1_persisted": ref(True)})
            batch = s.P1AResultBatch(results=(pending, result(1)))
            before = batch.model_dump()
            encoded = s.serialize_p1a_results(batch)
            self.assertEqual(len(encoded), 2)
            self.assertEqual(encoded[0]["qualification_activation"]["status"], "PENDING_ACK")
            self.assertEqual(batch.model_dump(), before)
            with self.assertRaises(ValidationError) as raised:
                result(file_display_name="/synthetic/private")
            self.assertEqual(s.safe_p1a_validation_errors(raised.exception)[0]["reason_code"], "CONTRACT_INVALID")
            for interceptor in interceptors:
                interceptor.assert_not_called()
            for name in ("sqlite3", "sqlalchemy", "src.api.database", "src.api.routes_assets",
                         "src.services.validator", "main"):
                with self.assertRaisesRegex(AssertionError, "BUSINESS_IMPORT_FORBIDDEN"):
                    guarded_import(name)
        self.assertEqual([name for name in sys.modules if business_import(name)], [])


if __name__ == "__main__":
    unittest.main()
