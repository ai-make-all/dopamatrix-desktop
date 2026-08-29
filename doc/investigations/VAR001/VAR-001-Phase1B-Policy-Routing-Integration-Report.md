# VAR-001
# Phase 1B
# Policy Routing & Integration Report

## 1. Baseline

- Branch: `feature/var-001-variation-policy`
- HEAD: `def9f6545197fed688b145bb24e18d0ca45625e0`
- Phase 1A commit: `def9f65 feat(var-001): add balanced planner core`
- Initial worktree: clean

## 2. Files Changed

Production:

- [schemas.py](E:/dopaworkspace/dopamatrix-desktop/src/api/schemas.py:402)
- [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:144)

Tests:

- [test_inv001_planning_policy.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_planning_policy.py:71)
- [test_var001_balanced_axis_coverage.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_var001_balanced_axis_coverage.py:531)
- [test_var001_policy_integration.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_var001_policy_integration.py:1)

## 3. Policy Contract

Backend policies are now explicitly distinct:

| Policy | Planner path |
|---|---|
| `legacy` | Historical worker-local resolution |
| `exact_main_visual` | Existing exact DB planner |
| `exact_main_visual_balanced` | New balanced DB planner |

`exact_main_visual` was not reinterpreted.

## 4. Schema Extension

`RenderDSLRequest.variant_planning_policy` now accepts:

```python
Literal[
    "legacy",
    "exact_main_visual",
    "exact_main_visual_balanced",
]
```

Default remains `legacy`. No request fields or strategy configuration were added.

## 5. Balanced Policy Predicate

Added:

```python
_requests_exact_main_visual_balanced()
_requests_authoritative_main_visual()
```

The original predicate remains exact equality:

```python
_requests_exact_main_visual(payload)
# true only for "exact_main_visual"
```

Balanced cannot accidentally satisfy the old exact predicate.

## 6. Preview Preparation

`submit_dsl()` now uses the exact-like setup predicate:

```python
if _requests_authoritative_main_visual(payload):
    _worker_kw["resolved_plan"] = plan
```

Both exact policies receive the same request-time preview seed. The original policy string is forwarded verbatim.

Legacy receives no new preview behavior.

## 7. Balanced DB Wrapper

Added:

```python
_plan_exact_main_visual_balanced_variants_from_db()
```

It mirrors the existing DB lifecycle:

```text
get tenant engine
→ sessionmaker
→ DSLParserNode(db)
→ _plan_exact_main_visual_balanced_variants(...)
```

A focused test verifies delegation, payload, requested count, parser, and preview forwarding.

## 8. Render Batch Routing

`render_batch_worker()` explicitly selects:

```python
if policy == "exact_main_visual":
    planning_function = old exact wrapper
elif policy == "exact_main_visual_balanced":
    planning_function = balanced wrapper
elif policy == "legacy":
    historical child work
else:
    fail planning without fallback
```

No substring or prefix matching is used.

## 9. Authoritative Handoff

Both exact planners share the existing downstream path:

```text
planning_result.plans/fingerprints
→ coordinator recomputation
→ _create_child_executions
→ _ChildWork(authoritative_plan, visual_fingerprint)
→ _execute_child
→ render_worker
```

The four-plan integration test verifies exact `P0→F0` through `P3→F3` pairing and authoritative worker flags.

FP-001B `VariantFingerprint` is inherited naturally; no second log was added.

## 10. Coordinator Fingerprint Invariant

The existing invariant remains shared:

```python
computed_fingerprints = tuple(
    _exact_main_visual_fingerprint(plan)
    for plan in planning_result.plans
)
```

Mismatch or duplicate recomputation raises the existing planner-result failure. The balanced mismatch test proves:

- No child executes.
- No weaker balanced invariant exists.
- Terminal result contains `VARIANT_PLANNING_FAILED`.

## 11. Warning Propagation

Balanced results reuse existing warnings:

- `INSUFFICIENT_UNIQUE_CAPACITY`
- `PLANNING_SEARCH_LIMIT_REACHED`

Tests prove:

- Capacity reduction creates only accepted children—no duplicate fill.
- Requested/planned/partial counts remain accurate.
- Search limit is not converted into capacity exhaustion.
- No balanced-specific warning family was introduced.

## 12. Legacy Preservation

The legacy integration test proves:

- Neither exact wrapper is invoked.
- Worker receives `plan_is_authoritative=False`.
- `visual_fingerprint=None`.
- Existing completion behavior continues.

Unknown internal worker policy values no longer silently fall into legacy; schema still rejects them before normal scheduling.

## 13. Exact Control Preservation

The existing exact policy:

- Calls only `_plan_exact_main_visual_variants_from_db()`.
- Does not call the balanced wrapper.
- Retains historical `2×2×2`, batch 4 order:

```text
A1 B1 C1
A1 B1 C2
A1 B2 C1
A1 B2 C2
```

**EXACT_CONTROL_UNCHANGED**

## 14. Balanced Golden Integration

Through `render_batch_worker` balanced policy routing, the controlled `4×2×1×2×2`, batch 4 fixture produces:

```text
Beat0: 1/1/1/1
Beat1: 2/2
Beat2: 4
Beat3: 2/2
Beat4: 2/2
```

Fingerprints: **4/4 unique**

All four plans and fingerprints reach their corresponding authoritative children.

## 15. Dynamic Beat Integration

A routing-level 3-Beat balanced test produces four authoritative children, each carrying a three-component fingerprint.

No five-Beat-only policy integration assumption was introduced.

## 16. Frontend Non-Activation

Read-only frontend verification:

```javascript
const EXACT_MAIN_VISUAL_PLANNING_POLICY = 'exact_main_visual'
```

No `exact_main_visual_balanced` match exists under `web_ui/`.

**AI_DRAFT_STILL_EXACT_CONTROL: YES**

## 17. Failure / No-Fallback Semantics

If the balanced planner raises unexpectedly:

- Old exact planner is not called.
- Legacy children are not created.
- Render workers do not start.
- Task returns failed with `VARIANT_PLANNING_FAILED`.

No balanced-to-exact or balanced-to-legacy fallback exists.

## 18. Tests Added

| ID | Evidence |
|---|---|
| VAR1B-01 | All three schema policies accepted |
| VAR1B-02 | Unknown policy rejected |
| VAR1B-03 | Default remains legacy |
| VAR1B-04 | Exact routes old planner and retains output order |
| VAR1B-05 | Balanced routes balanced wrapper only |
| VAR1B-06 | Legacy routes neither planner |
| VAR1B-07 | Submit preview and worker preview handoff |
| VAR1B-08 | Four authoritative plan/fingerprint pairs |
| VAR1B-09 | Shared fingerprint invariant |
| VAR1B-10 | Capacity warning propagation |
| VAR1B-11 | Search-limit warning propagation |
| VAR1B-12 | Exact control output unchanged |
| VAR1B-13 | Five-Beat golden backend integration |
| VAR1B-14 | Dynamic 3-Beat integration |
| VAR1B-15 | Frontend remains old exact control |
| VAR1B-16 | Balanced failure has no fallback |

Additional test verifies the balanced DB wrapper delegates directly to the Phase 1A core.

## 19. VAR Core Regression

Phase 1A focused suite:

```text
Ran 26 tests
OK
```

Complete VAR suite, including Phase 1B integration:

```text
Ran 36 tests
OK
```

## 20. INV Regression

```text
Ran 85 tests
OK
```

Count increased from 82 because three policy tests were intentionally added to `test_inv001_planning_policy.py`.

## 21. FP Regression

```text
Ran 42 tests
OK
```

No fingerprint or observability regression.

## 22. Phase 1A Core Preservation

No changed lines exist in:

- `_selection_from_cartesian_ordinal`
- `_stratified_cartesian_ordinals`
- `_balanced_candidate_window`
- `_initial_main_visual_coverage`
- `_projected_main_visual_coverage_score`
- `_update_main_visual_coverage`
- `_plan_exact_main_visual_balanced_variants`

Phase 1B routes the committed core without rewriting it.

## 23. Production Diff Audit

| Hunk | Classification |
|---|---|
| Schema Literal and description | A. policy enum extension |
| Balanced/exact-like predicates | B. policy helpers |
| Pre-planner guard sharing | D. exact-like preparation |
| Balanced DB wrapper | C. DB wrapper |
| Explicit planner selection | E. batch routing |
| Shared result validation/child construction | F. authoritative handoff |
| `submit_dsl` preview predicate | D. preview preparation |
| Unrelated | NONE |

## 24. Scope Audit

Confirmed unchanged:

- Frontend
- `dsl_parser.py`
- Models and database
- TaskHistory schema
- Rendering/TTS/Subtitle/Compositor/Cover/BGM
- FP fingerprint and observability semantics
- Search budget and batch maximum
- Historical Ledger

No backend or real-media runtime was started.

`py_compile` and `git diff --check` passed.

## 25. Review Findings

NONE.

## 26. Final Git Status

```text
 M src/api/routes_dsl.py
 M src/api/schemas.py
 M tests/test_inv001_planning_policy.py
 M tests/test_var001_balanced_axis_coverage.py
?? tests/test_var001_policy_integration.py
```

No commit or push was performed. Phase 1C was not started.

VAR001_PHASE1B_INTEGRATION_PASS