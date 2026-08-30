# VAR-001 Phase 2 Final Closure Report

## 1. Baseline

- Branch: `feature/var-001-variation-policy`
- HEAD: `41f72eb2744cb8028277aaa5ac4ebbb05fc19f9e`
- Phase 2B commit: `4ed3f64`
- Phase 2C commit: `41f72eb`

Worktree contains only expected Phase 2D and RF-03B work:

```text
 M main.py
 M web_ui/src/views/QueueView.vue
?? tests/test_var001_history_route_reachability.py
?? web_ui/src/components/CoverageDiagnosticsPanel.vue
?? web_ui/src/utils/coveragePresentation.ts
?? web_ui/tests/coveragePresentation.test.mjs
```

`git diff --check`: PASS. No unrelated changes found.

## 2. Phase 2A Status

Coverage Diagnostics V1 architecture remains accepted:

- Backend-owned coverage truth
- Explicit type/version/policy
- Ordered Beat diagnostics
- Planning-level counters and termination reason
- No Historical Novelty coupling

Status: PASS.

## 3. Phase 2B Status

Production, validation, observability and persistence remain intact:

- Coverage diagnostics produced by balanced planner
- Coordinator identity/digest validation
- `BalancedCoverageSummary`
- TaskHistory `planning_summary.coverage_diagnostics`
- Planning acceptance remains independent from render success

No Phase 2B production file changed during final closure.

Status: FINAL PASS / PRESERVED.

## 4. Phase 2C Status

Transport and normalization remain intact:

- Live terminal `coverageDiagnostics`
- Historical `planning_summary.coverage_diagnostics`
- One shared `normalizeCoverageDiagnostics()`
- Historical merge preserves valid live diagnostics
- Staged/committed backend payload lifecycle

No changes to:

- `routes_dsl.py`
- `queueWorker.ts`
- `useQueueStore.ts`
- `coverageDiagnostics.ts`

Status: FINAL PASS / PRESERVED.

## 5. Phase 2D-A Status

Final frontend architecture:

- [CoverageDiagnosticsPanel.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/components/CoverageDiagnosticsPanel.vue) consumes typed `CoverageDiagnosticsV1`.
- [coveragePresentation.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/utils/coveragePresentation.ts) performs presentation-only formatting.
- [QueueView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue) conditionally renders the panel whenever diagnostics exist.
- Coverage is collapsed by default using native `<details>/<summary>`.
- Both Queue lists use dynamic-height virtualization with explicit expansion dependencies.
- Narrow layout uses two-column planning context and internal table scrolling.

No frontend coverage classification or mathematics is recomputed.

Status: UI FINAL PASS.

## 6. Phase 2D-B Runtime Status

User-confirmed real browser evidence:

- Real balanced batch rendered.
- Live Coverage appeared without refresh.
- 4 variable Beats displayed as balanced.
- 1 Beat displayed as fixed by capacity.
- Expanded values matched authoritative diagnostics.
- Dynamic card height, repeated expansion and layout behavior were correct.
- Full browser refresh restored today’s completed tasks.
- Historical hydration preserved identical Coverage content.
- At approximately 733px, no destructive page-level horizontal overflow occurred.

Runtime status:

```text
VAR001_PHASE2D_RUNTIME_VISUAL_PASS
```

## 7. RF-03B Resolution

Root cause was route registration precedence:

```text
/tasks/{task_id}
shadowed
/tasks/today
```

Final [main.py](E:/dopaworkspace/dopamatrix-desktop/main.py:171) registration:

```python
# 今日态任务列表必须先于 /tasks/{task_id} 注册，避免 "today" 被动态路由抢先匹配。
app.include_router(tasks_today_router, prefix="/api/v1")
app.include_router(task_routes.router, prefix="/api/v1")
```

Resolution evidence:

- `/tasks/today` reaches `get_tasks_today()`.
- `/tasks/<integer>` continues to reach `get_task()`.
- No route names or public endpoint paths changed.
- No history semantics expanded.

## 8. Today History Endpoint

Live request:

```http
GET /api/v1/tasks/today
X-Local-User: testduplicate
```

Result:

```text
HTTP 200
today records: 2
known target count: 1
```

Known task:

```text
6b7f2606-64c5-4ef7-a25d-f01d02fe0cae
```

Verified for that record:

```text
output_assets: 4
planning_summary: present
coverage_diagnostics: present
```

The endpoint remains UTC-today-only. It was not converted into an all-history API.

## 9. Coverage Runtime Evidence

For the known real task:

- TaskHistory persisted successfully.
- Four output assets are returned.
- `planning_summary` is returned.
- `coverage_diagnostics` is returned.
- Browser live and historical Coverage views agree.
- Refresh hydration now restores the completed task into 战果阅兵场.

Internal values remain hidden from the normal UX:

- normalized source hashes
- accepted fingerprint digests
- preview fingerprint digest
- raw asset IDs
- raw contract type/version/policy

## 10. Frontend Tests

Executed:

```text
coverageDiagnostics.test.mjs
coveragePresentation.test.mjs
```

Result:

```text
19 tests
19 PASS
0 FAIL
```

Coverage includes normalization, detached copies, Phase 2C merge semantics, summaries, distributions, classifications, termination presentation, rejection context, preview provenance and component source boundaries.

## 11. Frontend Build

Command:

```text
npm run build
```

Result:

```text
PASS
Vite 7.3.1
141 modules transformed
built in 8.50s
```

Non-blocking existing warnings:

- Browserslist data is six months old.
- `Login.vue` is both statically and dynamically imported.

No dependency changes were made.

## 12. Route Tests

Focused file:

[tests/test_var001_history_route_reachability.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_var001_history_route_reachability.py)

Result:

```text
3 tests
3 PASS
```

Proven contracts:

- Production static route registration precedes dynamic route.
- `/tasks/today` returns controlled tenant history and not `int_parsing`.
- Tenant isolation remains enforced through `X-Local-User`.
- Integer task lookup remains functional.

## 13. VAR Regression

```text
Ran 55 tests
OK
```

The count includes the three new route reachability tests.

## 14. INV Regression

```text
Ran 85 tests
OK
```

No INV planning, uniqueness, capacity or execution behavior changed.

## 15. FP Regression

```text
Ran 42 tests
OK
```

No planning fingerprint, canonical digest or observability behavior changed.

Additional checks:

```text
py_compile: PASS
git diff --check: PASS
```

## 16. Scope Audit

| Class | Result |
|---|---|
| A. `/tasks/today` reachability | Present, minimal router-order change |
| B. Coverage UX component | Present |
| C. Coverage presentation helper | Present |
| D. Dynamic-height virtualization | Present and runtime accepted |
| E. Planner | None |
| F. Coverage mathematics | None |
| G. Fingerprint semantics | None |
| H. TaskHistory schema | None |
| I. Coverage transport | None |
| J. Coverage normalizer | None |
| K. DB migration | None |
| L. Approval / Matrix QC | None |
| M. Historical Novelty | None |
| N. Unrelated production change | None |

Additional boundaries:

- `getModeLabel` and generation-mode badge behavior are unchanged.
- No raw Coverage internals are rendered.
- No Phase 3 implementation was started.

Product scope is explicitly:

- Matrix Factory / 战果阅兵场: today-scoped operator workbench.
- 矩阵质检舱: cross-day asset review and approval.
- Fingerprint Historical Novelty: future machine-memory layer, independent of Matrix Factory UI scope.

## 17. Deferred Debts

### UI-RF-01

```text
GENERATION_MODE_BADGE_STALE_OR_INCORRECT
```

The historical generation-mode badge remains unchanged and was not used as planning-policy evidence.

### QUEUE-TODAY-01

```text
TODAY_BOUNDARY_USES_UTC_NOT_WORKSPACE_LOCAL_DAY
```

Current endpoint uses a UTC calendar day. Future work must define tenant/workspace timezone ownership before changing operator-local “today” semantics.

## 18. Final Git Status

```text
 M main.py
 M web_ui/src/views/QueueView.vue
?? tests/test_var001_history_route_reachability.py
?? web_ui/src/components/CoverageDiagnosticsPanel.vue
?? web_ui/src/utils/coveragePresentation.ts
?? web_ui/tests/coveragePresentation.test.mjs
```

No commit, push or tag was performed.

VAR001_PHASE2_COVERAGE_EXPLAINABILITY_FINAL_PASS