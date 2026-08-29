# VAR-001
# Phase 1C-A
# AI Draft Policy Activation Report

## 1. Baseline

- Branch: `feature/var-001-variation-policy`
- HEAD: `8554646fd2484908c083328c5fc74e33c0e92cfe`
- Phase 1B commit present: `8554646 feat(var-001): integrate balanced planning policy`
- Initial worktree: clean

## 2. Files Changed

Production:

- [WorkspaceView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:111)

Tests:

- [test_inv001_planning_policy.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_planning_policy.py:229)
- [test_var001_balanced_axis_coverage.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_var001_balanced_axis_coverage.py:531)

No other production files changed.

## 3. Previous AI Draft Policy

Before Phase 1C-A, successful `draftBlueprint()` assigned:

```js
orchestratorVariantPlanningPolicy.value =
  EXACT_MAIN_VISUAL_PLANNING_POLICY
```

Resolved value:

```text
exact_main_visual
```

## 4. New Balanced Policy Constant

Added a distinct policy identity:

```js
const BALANCED_MAIN_VISUAL_PLANNING_POLICY =
  'exact_main_visual_balanced'
```

The control constant remains unchanged:

```js
const EXACT_MAIN_VISUAL_PLANNING_POLICY =
  'exact_main_visual'
```

No policy aliasing or reinterpretation was introduced.

## 5. AI Draft Activation Point

Only the successful AI Draft transition changed:

```js
orchestratorDirectRender.value = true
orchestratorVariantPlanningPolicy.value =
  BALANCED_MAIN_VISUAL_PLANNING_POLICY
showOrchestrator.value = true
```

Activation remains after:

- successful `/draft-blueprint`
- timeline application
- `nextTick()`

It is not applied during initialization, page mount, request failure, or unrelated manual flows.

## 6. Drawer Handoff

[DslOrchestratorDrawer.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/DslOrchestratorDrawer.vue:425) was unchanged.

Its existing generic handoff remains:

```js
variantPlanningPolicy: props.variantPlanningPolicy
```

The prop is typed as `String`; no frontend enum or typing expansion was required.

## 7. Submit-DLS Payload Propagation

Resolved static path:

```text
draftBlueprint success
  exact_main_visual_balanced
→ orchestratorVariantPlanningPolicy
  exact_main_visual_balanced
→ DslOrchestratorDrawer prop/confirm event
  exact_main_visual_balanced
→ onOrchestratorConfirm
  exact_main_visual_balanced
→ blindFission({ variantPlanningPolicy })
  exact_main_visual_balanced
→ submit-dsl.variant_planning_policy
  exact_main_visual_balanced
```

The existing nullish fallback:

```js
options.variantPlanningPolicy ?? LEGACY_VARIANT_PLANNING_POLICY
```

does not overwrite a valid balanced policy string.

## 8. Request Before / After

Before:

```json
{
  "variant_planning_policy": "exact_main_visual"
}
```

After:

```json
{
  "variant_planning_policy": "exact_main_visual_balanced"
}
```

The production diff changes no other request fields. Batch size, timeline, aspect ratio, duration, language, tenant, mode, engine type, prompt, tags, and blueprint request semantics are unchanged.

## 9. Legacy Workflow Preservation

Unchanged paths:

- Workspace initialization defaults to `legacy`.
- Manual orchestrator opening resets policy to `legacy`.
- Direct `blindFission()` calls without an explicit policy retain the legacy fallback.
- Manual drawer submission remains `/submit-manual`.
- Manual Tactical Board behavior was not modified.

## 10. Exact Control Preservation

`exact_main_visual` remains:

- an explicit frontend constant
- accepted by the backend schema
- routed to the existing exact planner
- covered by existing control-policy tests

Output:

```text
EXACT_CONTROL_AVAILABLE
```

## 11. Backend Contract Verification

Read-only verification confirmed:

- `legacy` remains supported.
- `exact_main_visual` routes to the existing exact planner.
- `exact_main_visual_balanced` routes to the balanced planner.
- `RenderDSLRequest` still defaults to `legacy`.
- No balanced-to-exact or balanced-to-legacy fallback was introduced.

## 12. UI-RF-01 Non-Change

`UI-RF-01 — GENERATION_MODE_BADGE_STALE_OR_INCORRECT` remains unchanged.

No QueueView, result-card badge, authoring-mode metadata, or display mapping was modified.

## 13. Tests Added / Updated

Existing static/source contract infrastructure was used; no new frontend test framework was introduced.

| Contract | Evidence |
|---|---|
| VAR1CA-01 | Backend schema and routing still contain balanced policy |
| VAR1CA-02 | Old exact constant and backend route remain |
| VAR1CA-03 | AI Draft success block explicitly assigns balanced constant |
| VAR1CA-04 | Drawer forwards `props.variantPlanningPolicy` unchanged |
| VAR1CA-05 | Confirm handler passes policy into `blindFission` |
| VAR1CA-06 | Submit payload uses `variant_planning_policy: variantPlanningPolicy` |
| VAR1CA-07 | AI Draft success block no longer assigns old exact constant |
| VAR1CA-08 | Legacy/default contract tests retained |
| VAR1CA-09 | Backend production diff is empty |
| VAR1CA-10 | Phase 1A planner-core diff is empty |
| VAR1CA-11 | UI badge source unchanged |
| VAR1CA-12 | No persistence or Historical Novelty code added |

Targeted policy contract:

```text
Ran 13 tests
OK
```

## 14. Frontend Build / Check

Command:

```text
npm.cmd run build
```

Result:

```text
Vite 7.3.1
136 modules transformed
Build completed successfully in 6.58s
```

Non-blocking existing warnings:

- Browserslist dataset age advisory
- `Login.vue` static/dynamic import chunk advisory

No tracked build artifacts were created.

## 15. VAR Regression

```text
Ran 36 tests
OK
```

## 16. INV Regression

```text
Ran 85 tests
OK
```

## 17. FP Regression

```text
Ran 42 tests
OK
```

## 18. Backend Diff Audit

Both commands returned empty diffs:

```text
git diff -- src/api/routes_dsl.py
git diff -- src/api/schemas.py
```

No backend source was modified.

## 19. Phase 1A Core Preservation

No worktree changes affect:

- `_selection_from_cartesian_ordinal`
- `_stratified_cartesian_ordinals`
- `_balanced_candidate_window`
- `_initial_main_visual_coverage`
- `_projected_main_visual_coverage_score`
- `_update_main_visual_coverage`
- `_plan_exact_main_visual_balanced_variants`

Output:

```text
PHASE1A_CORE_UNCHANGED
```

## 20. Scope Audit

Confirmed:

- Only AI Draft policy selection changed.
- Drawer behavior unchanged.
- Backend and planner core unchanged.
- Fingerprint and VariantFingerprint unchanged.
- No DB, TaskHistory, schema, or API field changes.
- No UI badge fix.
- No Historical Novelty.
- No backend startup or real-media execution.
- No commit or push.
- `py_compile`: PASS
- `git diff --check`: PASS; only Git LF→CRLF working-copy advisories

## 21. Review Findings

```text
NONE
```

## 22. Final Git Status

```text
 M tests/test_inv001_planning_policy.py
 M tests/test_var001_balanced_axis_coverage.py
 M web_ui/src/views/WorkspaceView.vue
```

Diff summary:

```text
3 files changed, 50 insertions(+), 9 deletions(-)
```

`VAR001_PHASE1CA_ACTIVATION_PASS`