# FP-001B
# Targeted Runtime Observability Code Review Bundle

## 1. Baseline

```text
branch:
feature/var-001-variation-policy

HEAD:
35d63cd905c96fd2fa5d62162023ee07de3110fe

status:
 M src/api/routes_dsl.py
?? doc/investigations/fingerprint/FP-001B-Runtime-Fingerprint-Observability-Implementation-Report.md
?? tests/test_fp001_fingerprint_observability.py

diff stat:
 src/api/routes_dsl.py | 162 ++++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 162 insertions(+)
```

`git diff --check` passed. Only the existing LF→CRLF warning was emitted.

The final status remained identical to this review baseline.

## 2. Production Diff

Complete production diff contains these hunks:

| Hunk | Classification |
|---|---|
| `_VARIANT_FINGERPRINT_*` and component-limit constants | A. FP runtime constants |
| `_main_visual_planning_log_components` | B. Component extraction |
| `_variant_fingerprint_event_payload` | C. Event payload builder |
| `_fingerprint_observability_warning` and `_emit_authoritative_variant_fingerprint` | D. Safe diagnostic/emitter |
| Optional `render_worker(... visual_fingerprint=None)` parameter | E. Worker signature |
| Emitter call after authoritative plan acceptance | F. Worker-entry integration |
| `_execute_child` keyword forwarding | G. `_ChildWork` forwarding |
| Unrelated production change | **H. NONE** |

Signature hunk:

```diff
 dsl_payload: Optional[StoryDSLPayload] = None,
 plan_is_authoritative: bool = False,
+visual_fingerprint: Optional[_MainVisualFingerprint] = None,
 enable_tts: bool = True,
```

Worker-entry hunk:

```diff
 working_plan = plan
+_emit_authoritative_variant_fingerprint(
+    working_plan,
+    planner_fingerprint=visual_fingerprint,
+    task_id=task_id,
+    execution_id=execution_id,
+    child_index=child_index,
+    file_sid=resolved_file_sid,
+)
```

Handoff hunk:

```diff
 plan_is_authoritative=work.authoritative_plan is not None,
+visual_fingerprint=work.visual_fingerprint,
```

## 3. New Helpers

来源：[routes_dsl.py:305](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:305>)

### Component extraction

```py
def _main_visual_planning_log_components(
    plan: CompilationPlan,
    fingerprint: _MainVisualFingerprint,
    *,
    max_components: int = _MAX_LOGGED_FINGERPRINT_COMPONENTS,
) -> tuple[list[dict[str, Any]], bool]:
    """Build bounded diagnostics from the authoritative plan and fingerprint."""
    if len(plan.beats) != len(fingerprint):
        raise ValueError("FINGERPRINT_OBSERVABILITY_BEAT_COUNT_MISMATCH")

    components: list[dict[str, Any]] = []
    for beat, component in zip(plan.beats[:max_components], fingerprint[:max_components]):
        main_layers = [layer for layer in beat.layers if layer.layer_index == 0]
        if len(main_layers) != 1:
            raise ValueError("FINGERPRINT_OBSERVABILITY_MAIN_LAYER_INVALID")
        beat_index, beat_identity, _layer_index, normalized_file_hash = component
        components.append(
            {
                "beat_index": beat_index,
                "beat_identity": beat_identity,
                "asset_id": main_layers[0].asset_id,
                "normalized_file_hash": normalized_file_hash,
            }
        )
    return components, len(fingerprint) > max_components
```

### Event construction

```py
def _variant_fingerprint_event_payload(
    plan: CompilationPlan,
    *,
    planner_fingerprint: Optional[_MainVisualFingerprint],
    task_id: str,
    execution_id: str,
    child_index: int,
    file_sid: str,
) -> dict[str, Any]:
    """Build the authoritative child-entry fingerprint observability event."""
    worker_fingerprint = _exact_main_visual_fingerprint(plan)
    contract = _main_visual_planning_fingerprint_contract(worker_fingerprint)
    components, components_truncated = _main_visual_planning_log_components(
        plan,
        worker_fingerprint,
    )
    planner_fingerprint_match = (
        None
        if planner_fingerprint is None
        else planner_fingerprint == worker_fingerprint
    )
    return {
        "event": _VARIANT_FINGERPRINT_EVENT,
        "phase": _VARIANT_FINGERPRINT_PHASE,
        "task_id": task_id,
        "execution_id": execution_id,
        "child_index": child_index,
        "file_sid": file_sid,
        "fingerprint_type": contract.fingerprint_type,
        "fingerprint_version": contract.fingerprint_version,
        "source_hash_algorithm": contract.source_hash_algorithm,
        "fingerprint_digest": contract.fingerprint_digest,
        "beat_count": len(worker_fingerprint),
        "planner_fingerprint_match": planner_fingerprint_match,
        "components": components,
        "components_truncated": components_truncated,
    }
```

### Safe diagnostic

```py
def _fingerprint_observability_warning(
    diagnostic: str,
    *,
    task_id: str,
    execution_id: str,
    child_index: int,
    file_sid: str,
    detail: str,
) -> None:
    """Emit a bounded diagnostic without allowing logging to affect rendering."""
    try:
        logger.warning(
            "[VariantFingerprint] diagnostic=%s task_id=%s execution_id=%s "
            "child_index=%d file_sid=%s detail=%s",
            diagnostic,
            task_id,
            execution_id,
            child_index,
            file_sid,
            str(detail)[:300],
        )
    except Exception:
        pass
```

### Safe INFO emitter and observability coordinator

```py
def _emit_authoritative_variant_fingerprint(
    plan: CompilationPlan,
    *,
    planner_fingerprint: Optional[_MainVisualFingerprint],
    task_id: str,
    execution_id: str,
    child_index: int,
    file_sid: str,
) -> None:
    """Emit one non-blocking authoritative VariantFingerprint INFO event."""
    try:
        event = _variant_fingerprint_event_payload(
            plan,
            planner_fingerprint=planner_fingerprint,
            task_id=task_id,
            execution_id=execution_id,
            child_index=child_index,
            file_sid=file_sid,
        )
        if event["planner_fingerprint_match"] is None:
            _fingerprint_observability_warning(
                "FINGERPRINT_OBSERVABILITY_MISSING",
                task_id=task_id,
                execution_id=execution_id,
                child_index=child_index,
                file_sid=file_sid,
                detail="planner-provided fingerprint is missing",
            )
        elif not event["planner_fingerprint_match"]:
            _fingerprint_observability_warning(
                "FINGERPRINT_OBSERVABILITY_MISMATCH",
                task_id=task_id,
                execution_id=execution_id,
                child_index=child_index,
                file_sid=file_sid,
                detail="planner fingerprint differs from authoritative worker plan",
            )
        logger.info(
            "[VariantFingerprint] %s",
            json.dumps(
                event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    except Exception as exc:
        _fingerprint_observability_warning(
            "FINGERPRINT_OBSERVABILITY_FAILED",
            task_id=task_id,
            execution_id=execution_id,
            child_index=child_index,
            file_sid=file_sid,
            detail=f"{type(exc).__name__}: {exc}",
        )
```

## 4. Log Payload Bounding

Exact component preparation:

```py
beat_index, beat_identity, _layer_index, normalized_file_hash = component

{
    "beat_index": beat_index,
    "beat_identity": beat_identity,
    "asset_id": main_layers[0].asset_id,
    "normalized_file_hash": normalized_file_hash,
}
```

Per-field result:

| Field | Source | Length/type bound |
|---|---|---|
| `beat_index` | Existing fingerprint tuple | Integer |
| `beat_identity` | Existing fingerprint tuple | **No length bound** |
| `asset_id` | Authoritative layer-0 layer | Integer |
| `normalized_file_hash` | Existing fingerprint tuple | **No length bound for abnormal plans** |

Answers:

A. Is `beat_identity` length-bounded?  
**NO.**

B. Exact maximum?  
**NONE.**

C. Is `normalized_file_hash` bounded for abnormal/non-DAM values?  
**NO.**

`normalize_file_hash` only performs:

```py
return str(value or "").strip().lower()
```

Backend Beat and `ResolvedLayer.file_hash` schema fields are plain `str` without `max_length`.

D. Can an arbitrary authoritative-plan string create an unbounded event?  
**YES.** The 32-component cap limits entry count, not individual string sizes.

**LOG_PAYLOAD_FIELD_LENGTH_RISK**

## 5. Canonical Data Preservation

The worker first creates the complete authoritative fingerprint and digest:

```py
worker_fingerprint = _exact_main_visual_fingerprint(plan)
contract = _main_visual_planning_fingerprint_contract(worker_fingerprint)
```

Only afterward are presentation components constructed:

```py
components, components_truncated = _main_visual_planning_log_components(
    plan,
    worker_fingerprint,
)
```

The component cap slices:

```py
plan.beats[:max_components]
fingerprint[:max_components]
```

It does not mutate:

- `worker_fingerprint`
- FP-001A canonical payload
- canonical bytes
- SHA-256 digest

The full digest is built before presentation truncation.

There currently is no per-field truncation. Any future field shortening must remain isolated to `components` and must not change the tuple passed to the FP-001A builder.

## 6. Exception Boundary

Relevant worker code:

```py
if plan_is_authoritative:
    if plan is None:
        logger.error(
            "[render_worker] task_id=%s authoritative plan missing", task_id,
        )
        return _result(
            "failed",
            "AUTHORITATIVE_PLAN_MISSING",
            "authoritative child requires CompilationPlan",
        )

    working_plan = plan
    _emit_authoritative_variant_fingerprint(
        working_plan,
        planner_fingerprint=visual_fingerprint,
        task_id=task_id,
        execution_id=execution_id,
        child_index=child_index,
        file_sid=resolved_file_sid,
    )

# ...

assert working_plan is not None
timeline = compile_plan_to_timeline(
    working_plan,
    target_duration=target_duration,
)
```

FP-specific exception boundary resides entirely inside:

```py
_emit_authoritative_variant_fingerprint(...)
```

Its `try/except` ends before control returns to `render_worker`.

It does not wrap:

- `compile_plan_to_timeline`
- `WorkflowContext`
- TTS
- Subtitle
- Compositor
- Cover
- remaining render logic

Those remain governed by their existing worker semantics.

**OBSERVABILITY_EXCEPTION_BOUNDARY_SAFE**

## 7. Worker Emission Point

Order is:

```text
_validate_child_execution(...)
→ authoritative plan non-null check
→ working_plan = plan
→ _emit_authoritative_variant_fingerprint(...)
→ compile_plan_to_timeline(...)
```

There is exactly one normal production call to `_emit_authoritative_variant_fingerprint`.

There is exactly one `logger.info("[VariantFingerprint] %s", ...)` inside that emitter.

## 8. Mismatch Path

Match construction:

```py
planner_fingerprint_match = (
    None
    if planner_fingerprint is None
    else planner_fingerprint == worker_fingerprint
)
```

Mismatch branch:

```py
elif not event["planner_fingerprint_match"]:
    _fingerprint_observability_warning(
        "FINGERPRINT_OBSERVABILITY_MISMATCH",
        # identities
        detail="planner fingerprint differs from authoritative worker plan",
    )
```

Digest construction happens earlier from:

```py
worker_fingerprint = _exact_main_visual_fingerprint(plan)
contract = _main_visual_planning_fingerprint_contract(worker_fingerprint)
```

Therefore:

- Mismatch state is `False`.
- Diagnostic warning is emitted.
- INFO event still emits.
- Digest represents authoritative worker plan.
- Stale planner tuple is used only for equality comparison.
- No planner-provided digest is constructed or logged.
- Control returns to `render_worker`, which continues to timeline compilation.

## 9. Missing Fingerprint Path

For `visual_fingerprint=None`:

```py
planner_fingerprint_match = None
```

Missing branch:

```py
if event["planner_fingerprint_match"] is None:
    _fingerprint_observability_warning(
        "FINGERPRINT_OBSERVABILITY_MISSING",
        # identities
        detail="planner-provided fingerprint is missing",
    )
```

The event was already constructed from the authoritative plan before this branch. After the warning:

```py
logger.info("[VariantFingerprint] %s", ...)
```

still executes.

No return or exception interrupts the worker.

## 10. Failure Path

If either of these raises:

```py
_exact_main_visual_fingerprint(plan)
_main_visual_planning_fingerprint_contract(worker_fingerprint)
```

the emitter catches it:

```py
except Exception as exc:
    _fingerprint_observability_warning(
        "FINGERPRINT_OBSERVABILITY_FAILED",
        # identities
        detail=f"{type(exc).__name__}: {exc}",
    )
```

The diagnostic detail is bounded:

```py
str(detail)[:300]
```

The diagnostic helper catches logger failure and returns:

```py
try:
    logger.warning(...)
except Exception:
    pass
```

There is:

- No re-raise.
- No new `_ChildResult`.
- No error code.
- No product warning code.
- No early worker return.

After the emitter returns, existing timeline/render processing continues.

## 11. Logger Compatibility

Logger definition:

```py
import logging

logger = logging.getLogger(__name__)
```

Representative existing usage in the same module:

```py
logger.warning(
    "[routes_dsl] _fetch_available_tags 查询失败，返回空标签库",
    exc_info=True,
)

logger.info(
    "[render_worker] task_id=%s 标签菜单注入：%d 个可用标签供 LLM 约束",
    task_id,
    len(_available_tags),
)
```

New usage:

```py
logger.info(
    "[VariantFingerprint] %s",
    json_string,
)
```

This is standard Python logging `%`-argument formatting and matches existing module conventions.

**LOGGER_FORMAT_COMPATIBLE**

## 12. Logger Failure Safety

Diagnostic logger:

```py
try:
    logger.warning(...)
except Exception:
    pass
```

INFO logger is inside the outer emitter `try`. If it raises, the outer exception handler invokes the protected diagnostic helper.

If both INFO and warning logging are broken:

1. INFO raises.
2. Emitter calls diagnostic helper once.
3. Warning raises.
4. Diagnostic helper swallows it.
5. No recursive logging call occurs.

There is no recursion or retry loop.

## 13. Component Alignment

Alignment logic:

```py
if len(plan.beats) != len(fingerprint):
    raise ValueError("FINGERPRINT_OBSERVABILITY_BEAT_COUNT_MISMATCH")
```

Then:

```py
for beat, component in zip(
    plan.beats[:max_components],
    fingerprint[:max_components],
):
```

Layer validation:

```py
main_layers = [
    layer for layer in beat.layers
    if layer.layer_index == 0
]
if len(main_layers) != 1:
    raise ValueError("FINGERPRINT_OBSERVABILITY_MAIN_LAYER_INVALID")
```

Additional protection comes from `_exact_main_visual_fingerprint(plan)`, which generated `worker_fingerprint` from the same ordered plan and already validates:

- Beat count
- Beat ordering
- exactly one layer 0
- valid main-X type
- non-empty normalized hash
- non-empty Beat identity

If the extractor’s independent count/layer checks fail, the emitter catches the exception and rendering continues under its existing behavior.

## 14. Digest Source

Only source:

```text
authoritative plan
→ _exact_main_visual_fingerprint(plan)
→ _main_visual_planning_fingerprint_contract(worker_fingerprint)
→ contract.fingerprint_digest
→ INFO payload
```

Not used:

- planner tuple alone
- preview
- `_selection_key`
- candidate state
- FFmpeg path
- asset path
- database lookup

## 15. FO1 Evidence

来源：[test_fp001_fingerprint_observability.py:147](</E:/dopaworkspace/dopamatrix-desktop/tests/test_fp001_fingerprint_observability.py:147>)

FO1 constructs one exact `planning_result` with a specific `fingerprint`, allows the real coordinator to construct `_ChildWork`, mocks only `render_worker`, then asserts:

```py
self.assertEqual(
    worker.call_args.kwargs["visual_fingerprint"],
    fingerprint,
)
```

The value is the exact tuple stored in `planning_result.fingerprints`; it is not independently recomputed for the assertion.

## 16. FO8 Evidence

```py
def test_fo8_mismatch_warns_and_renders_authoritative_digest(self):
    plan = _plan(1, hashes=["authoritative"], asset_ids=[0])
    stale = _fingerprint(_plan(1, hashes=["stale"]))
    expected_digest = routes_dsl._main_visual_planning_fingerprint_contract(
        _fingerprint(plan)
    ).fingerprint_digest

    result, info, warning = _run_worker(
        plan,
        visual_fingerprint=stale,
        plan_is_authoritative=True,
    )
    events = _variant_events(info)

    self.assertTrue(result.succeeded)
    self.assertEqual(len(events), 1)
    self.assertIs(events[0]["planner_fingerprint_match"], False)
    self.assertEqual(events[0]["fingerprint_digest"], expected_digest)
    self.assertIn(
        "FINGERPRINT_OBSERVABILITY_MISMATCH",
        _diagnostics(warning),
    )
```

This invokes real `render_worker`, not only the pure payload helper.

It independently proves:

- Planner tuple is stale.
- Authoritative plan uses a different hash.
- Event digest matches authoritative plan.
- Mismatch warning occurs.
- Worker reaches successful existing endpoint.

## 17. FO9 Evidence

```py
def test_fo9_missing_planner_fingerprint_is_unknown_and_non_blocking(self):
    plan = _plan(1, asset_ids=[0])

    result, info, warning = _run_worker(
        plan,
        visual_fingerprint=None,
        plan_is_authoritative=True,
    )
    events = _variant_events(info)

    self.assertTrue(result.succeeded)
    self.assertEqual(len(events), 1)
    self.assertIsNone(events[0]["planner_fingerprint_match"])
    self.assertIn(
        "FINGERPRINT_OBSERVABILITY_MISSING",
        _diagnostics(warning),
    )
```

It invokes an authoritative real worker with `None`, observes a constructed event and successful render result.

## 18. FO10 Evidence

```py
def test_fo10_non_authoritative_missing_fingerprint_remains_compatible(self):
    result, info, warning = _run_worker(
        _plan(1, asset_ids=[0]),
        plan_is_authoritative=False,
    )

    self.assertTrue(result.succeeded)
    self.assertEqual(_variant_events(info), [])
    self.assertEqual(_diagnostics(warning), [])
```

The helper passes `visual_fingerprint=None`.

The real worker:

- Succeeds.
- Emits no VariantFingerprint INFO.
- Emits no fingerprint diagnostic, including no missing warning.

## 19. FO13 Evidence

```py
def test_fo13_observability_failures_do_not_escape_or_fail_render(self):
    plan = _plan(1, asset_ids=[0])
    fingerprint = _fingerprint(plan)

    with patch.object(
        routes_dsl,
        "_main_visual_planning_fingerprint_contract",
        side_effect=RuntimeError("contract failed"),
    ):
        result, info, warning = _run_worker(
            plan,
            visual_fingerprint=fingerprint,
            plan_is_authoritative=True,
        )

    self.assertTrue(result.succeeded)
    self.assertEqual(_variant_events(info), [])
    self.assertIn(
        "FINGERPRINT_OBSERVABILITY_FAILED",
        _diagnostics(warning),
    )

    with (
        patch.object(
            routes_dsl.logger,
            "info",
            side_effect=RuntimeError("log failed"),
        ),
        patch.object(routes_dsl.logger, "warning") as log_warning,
    ):
        routes_dsl._emit_authoritative_variant_fingerprint(
            plan,
            planner_fingerprint=fingerprint,
            task_id="log-failure",
            execution_id="22222222-2222-4222-8222-222222222222",
            child_index=0,
            file_sid="22222222",
        )

    self.assertIn(
        "FINGERPRINT_OBSERVABILITY_FAILED",
        _diagnostics(log_warning),
    )
```

The forced exception occurs inside:

```py
_variant_fingerprint_event_payload()
→ _main_visual_planning_fingerprint_contract()
```

Production catch boundary is `_emit_authoritative_variant_fingerprint()`.

`_run_worker` does mock timeline compilation and external compositor/cover effects, but it does not mock:

- `render_worker`
- authoritative branch selection
- fingerprint emitter
- exception boundary
- WorkflowContext creation
- output collection
- final `_ChildResult` construction

The fake compositor creates a real temporary output file so the real worker reaches its existing successful result condition.

**FO13_NON_BLOCKING_PROOF_STRONG**

## 20. FO14 Evidence

```py
def test_fo14_normal_authoritative_worker_emits_exactly_one_event(self):
    plan = _plan(1, asset_ids=[0])
    fingerprint = _fingerprint(plan)

    result, info, warning = _run_worker(
        plan,
        visual_fingerprint=fingerprint,
        plan_is_authoritative=True,
    )

    self.assertTrue(result.succeeded)
    self.assertEqual(len(_variant_events(info)), 1)
    self.assertEqual(_diagnostics(warning), [])
```

`_variant_events()` counts only INFO calls whose format string is exactly:

```py
"[VariantFingerprint] %s"
```

Warnings are captured separately through the warning mock and are not counted as INFO events.

Result:

```text
VariantFingerprint INFO count = 1
diagnostic count = 0
```

## 21. Production Call Sites

Production matches:

| Match | Consumer |
|---|---|
| `visual_fingerprint=fingerprint` | `_ChildWork` construction |
| `visual_fingerprint=work.visual_fingerprint` | Coordinator-to-worker handoff |
| `VariantFingerprint` | Event/diagnostic logger only |
| `FINGERPRINT_OBSERVABILITY_*` | Internal exceptions and logger diagnostics |
| `_main_visual_planning_fingerprint_contract(worker_fingerprint)` | Authoritative event builder |

No consumer exists in:

- DB
- TaskHistory persistence
- frontend
- API schema
- planner decision
- preview
- capacity logic
- FFmpeg

## 22. Failure Semantics Audit

The new FP-001B code contains two `raise ValueError` statements, both within component event construction:

```text
FINGERPRINT_OBSERVABILITY_BEAT_COUNT_MISMATCH
FINGERPRINT_OBSERVABILITY_MAIN_LAYER_INVALID
```

Both are caught by the emitter’s FP-specific `except Exception`.

No new FP-001B path adds:

- `_ChildResult.error_code`
- `_result("failed", ...)`
- `warning_codes`
- `HTTPException`
- WebSocket field/event
- TaskHistory write/state
- planner rejection

Product outcome changes: **NONE**.

## 23. Test Results

Focused observability:

```text
Ran 14 tests in 0.086s
OK
```

All FP-001 tests:

```text
Ran 29 tests in 0.083s
OK
```

INV regression:

```text
Ran 82 tests in 0.812s
OK
```

Other checks:

```text
py_compile:
  src/api/routes_dsl.py                         PASS
  tests/test_fp001_fingerprint_observability.py PASS

git diff --check:
  PASS
```

## 24. Review Findings

### FP1B-RF-01 — COMPONENT_LOG_FIELDS_NOT_LENGTH_BOUNDED

`_MAX_LOGGED_FINGERPRINT_COMPONENTS = 32` limits only the number of components.

The following presentation fields are inserted without length limits:

```text
beat_identity
normalized_file_hash
```

Both backend schema fields are unconstrained strings, and hash normalization does not enforce a maximum. An abnormal authoritative plan can therefore produce an arbitrarily large VariantFingerprint JSON event.

Canonical tuple and digest behavior are unaffected; this is strictly a runtime log-payload bounding defect.

## 25. Final Classification

**FP001B_FIXUP_REQUIRED**

## 26. Final Git Status

```text
branch:
feature/var-001-variation-policy

HEAD:
35d63cd905c96fd2fa5d62162023ee07de3110fe

status:
 M src/api/routes_dsl.py
?? doc/investigations/fingerprint/FP-001B-Runtime-Fingerprint-Observability-Implementation-Report.md
?? tests/test_fp001_fingerprint_observability.py

diff stat:
 src/api/routes_dsl.py | 162 ++++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 162 insertions(+)
```

No files were modified during this review. No commit or push was performed. FP-001C, VAR-001 and Historical Ledger were not started.