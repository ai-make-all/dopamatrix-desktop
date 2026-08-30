# VAR-001 Phase 2C Small Fix-Up Report

## 1. Findings

Addressed:

- `VAR2C-RF-01` — `COVERAGE_DIAGNOSTICS_CAN_BE_ERASED_BY_ABSENT_UPDATE`
- `VAR2C-RF-02` — `COVERAGE_DIAGNOSTICS_SURVIVES_POST_VALIDATION_COORDINATOR_FAILURE`

## 2. RF-01 Historical Merge Fix

Added a pure merge helper in [coverageDiagnostics.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/utils/coverageDiagnostics.ts):

```ts
export function mergeCoverageDiagnostics(
  current: CoverageDiagnosticsV1 | undefined,
  incoming: CoverageDiagnosticsV1 | undefined,
): CoverageDiagnosticsV1 | undefined {
  return incoming ?? current
}
```

Historical convergence in [QueueView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue) now explicitly applies:

```ts
coverageDiagnostics: mergeCoverageDiagnostics(
  t.coverageDiagnostics,
  historical.coverageDiagnostics,
)
```

Result:

- Valid history replaces live diagnostics.
- Missing/malformed history preserves valid live diagnostics.
- Both absent remains `undefined`.
- The subsequent `INIT_TASKS` snapshot retains the merged value.

Direct worker and Pinia fallback update semantics were not changed.

## 3. RF-01 Tests

Added five executable cases:

- Live valid + history absent → live retained
- Live valid + history malformed → live retained
- Live A + valid history B → history B selected
- Standalone old history → `undefined`
- Merged `INIT_TASKS` snapshot → retained diagnostics remain present

The replacement fixture uses a structurally and semantically valid V1 payload with a distinct `search_budget`.

## 4. RF-02 Staged / Committed Payload Fix

In [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py), the outer value remains the committed payload:

```python
coverage_diagnostics_payload: Optional[dict[str, Any]] = None
```

The authoritative setup uses a staged value:

```python
staged_coverage_diagnostics_payload: Optional[dict[str, Any]] = None
```

Validation and `BalancedCoverageSummary` use the staged payload. Commit occurs only through the successful `try/except/else` path:

```python
else:
    coverage_diagnostics_payload = staged_coverage_diagnostics_payload
```

Therefore, any exception during child identity allocation, `_ChildWork` construction, or remaining coordinator setup leaves the committed payload as `None`.

## 5. RF-02 Tests

Added a controlled post-validation failure test:

```text
valid balanced result
→ coordinator validation succeeds
→ BalancedCoverageSummary emitted
→ _create_child_executions raises
→ VARIANT_PLANNING_FAILED
```

Assertions prove:

- validated payload was produced
- summary event remained exactly once at the existing Phase 2B timing
- worker was not called
- TaskHistory persistence was not called
- `plannedCount == 0`
- `coverageDiagnostics` absent from terminal

## 6. Positive Balanced Control

Normal balanced coordinator still proves:

- diagnostics validate
- one `BalancedCoverageSummary` is emitted
- children are allocated and executed
- terminal receives the same payload object
- TaskHistory receives the same payload object

## 7. Partial Render Control

Retained and passed:

```text
planning accepted = 4
render succeeded = 3
terminal.succeededCount = 3
terminal.coverageDiagnostics.accepted_count = 4
```

Ordinary child render failure occurs after successful coordinator setup, so committed planning diagnostics remain present.

## 8. Exact / Legacy Control

Verified unchanged:

- Exact terminal: `coverageDiagnostics` absent
- Legacy terminal: `coverageDiagnostics` absent
- Neither emits `BalancedCoverageSummary`
- Neither persists coverage diagnostics

## 9. Frontend Tests

Node executable tests:

```text
11 tests
11 PASS
0 FAIL
```

Includes the original six normalization tests plus five RF-01 merge tests.

## 10. Backend Focused Tests

```text
tests.test_var001_coverage_diagnostics
16 tests
16 PASS
```

Controlled exceptions shown in output were expected negative-path fixtures.

## 11. VAR Regression

```text
52 tests
52 PASS
```

## 12. INV Regression

```text
85 tests
85 PASS
```

## 13. FP Regression

```text
42 tests
42 PASS
```

## 14. Frontend Build

```text
npm run build
PASS
Vite 7.3.1
137 modules transformed
```

Only existing non-blocking warnings appeared:

- stale Browserslist data
- `Login.vue` mixed static/dynamic import warning

## 15. Diff / Scope Audit

Fix-up production changes were limited to:

- [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py): staged/committed lifecycle
- [QueueView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue): historical convergence
- [coverageDiagnostics.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/utils/coverageDiagnostics.ts): pure merge helper

Tests changed only in the approved files.

Confirmed unchanged:

- balanced planner and selection
- coverage builder and mathematics
- coordinator identity/digest validator semantics
- fingerprint contracts
- TaskHistory persistence implementation
- worker live merge semantics
- Pinia fallback semantics
- DB/schema/history API
- QueueView template and Coverage UX
- UI-RF-01
- Historical Novelty

Checks:

- `py_compile`: PASS
- `git diff --check`: PASS
- untracked-file whitespace check: PASS

## 16. Final Git Status

```text
 M src/api/routes_dsl.py
 M tests/test_var001_coverage_diagnostics.py
 M web_ui/src/stores/useQueueStore.ts
 M web_ui/src/views/QueueView.vue
 M web_ui/src/workers/queueWorker.ts
?? web_ui/src/utils/coverageDiagnostics.ts
?? web_ui/tests/coverageDiagnostics.test.mjs
```

The worker/store modifications are the existing uncommitted Phase 2C transport changes; this fix-up did not alter them.

No commit, push, service startup, or real-media execution performed.

VAR001_PHASE2C_FIXUP_PASS