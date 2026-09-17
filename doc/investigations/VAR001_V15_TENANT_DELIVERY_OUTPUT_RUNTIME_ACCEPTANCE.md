# VAR-001 V1.5 Seed Release Hardening
# Tenant / Project Delivery Output Runtime Acceptance

Role: runtime acceptance evidence consolidator. Documentation only.
No production, Vue, tests, SQLite, settings, services, renders, ZIPs,
or git writes besides this file.

This is **not** Philippine Seed production acceptance, V1.5 GA
authorization, a full L1/L2 Gate 1–6 rerun, or an L3 implementation.

Prior artifacts (architecture not reopened):

- `doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_TARGETED_AUDIT.md`
- `doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_POSTCOMMIT_SOURCE_EXCERPTS.md`
- `doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_IMPLEMENTATION_REPORT.md`

## 1. Executive Result

Manual Windows runtime acceptance for the Two-Root Delivery Root
implementation is **complete**. Gates D1–D6 all **PASS**.

A machine-global Delivery Root at `F:\outputdir\V15` derived tenant
subtrees. Tenant A and Tenant B real Balanced renders kept
TaskHistory on internal `output/final_*` while publishing only
final + cover copies under
`<delivery-root>/tenants/<canonical-tenant>/projects/_default/renders/<date>/<task_id>/`.
ZIP exports were tenant-confined on disk and on download. An
unavailable `Z:\` root did not fail the authoritative task. Unset
root fell back to `<project-root>/output/exports` without breaking
cross-tenant 404. Reservation diagnostics remained HTTP 200 with
the normal schema. A local frontend production build passed.

**VAR001_V15_TENANT_DELIVERY_OUTPUT_RUNTIME_ACCEPTANCE_FINAL_PASS**

## 2. Scope

Consolidates operator-observed D1–D6 Windows runtime evidence against
the accepted Two-Root contract and the implementation report.

Does **not** claim:

- Philippine Seed production acceptance
- V1.5 GA authorization
- full L1/L2 Manual Gate 1–6 rerun
- L3 historical-memory implementation
- captured `DELIVERY_COPY_FAILED` log lines (none supplied)

## 3. Runtime Environment

- OS: Windows (local Seed-hardening machine)
- Branch: `feature/var-001-variation-policy`
- HEAD at documentation time: `73982e4073455a8e542015c25cd9e20e397dd078`
- Delivery Root (restored after fault tests): `F:\outputdir\V15`
- Tenants: `v15_delivery_a`, `v15_delivery_b`
- Tenant DB (D6 durable read): `data/dopamatrix_v15_delivery_a.db`
- Qualified path: AI Draft → Tactical Board → `exact_main_visual_balanced` → Render
- Node: v22.23.1
- npm: 10.9.8

## 4. D1 Global Delivery Root

**PASS**

- UI semantics: **交付根目录 / Delivery Root**
- `POST /api/v1/settings/delivery-root` → HTTP 200
- Configured value: `F:\outputdir\V15`
- `GET` returned the same value
- Backend restart preserved the value
- Tenant switch preview (same global root, derived tenant path):

```text
v15_delivery_a → F:\outputdir\V15\tenants\v15_delivery_a\projects\_default\
v15_delivery_b → F:\outputdir\V15\tenants\v15_delivery_b\projects\_default\
```

Conclusion: Delivery Root is machine-global. Tenant path is derived
dynamically.

**D1_GLOBAL_DELIVERY_ROOT_RUNTIME_PASS**

## 5. D2 Tenant A Real Render

**PASS**

Tenant: `v15_delivery_a`

Qualified path: AI Draft → Tactical Board → `exact_main_visual_balanced`
→ render

Observed public task IDs:

- `935a6e76-1644-4465-963e-a6e95cc6b69d`
- `5d095b7d-9efc-4a74-9fcd-94e7b53dda92` (additional same-day task)

Internal authority (`<project-root>\output\`) contained:

- final
- cover
- master
- voice
- vtt
- ass

Delivery path:

```text
F:\outputdir\V15\
tenants\v15_delivery_a\
projects\_default\
renders\2026-09-16\
<task_id>\
```

Delivery contained **only** final videos and cover images. No master,
voice, or subtitle intermediates were published externally.

Same-day multiple tasks remained separated by `task_id` directories.

**D2_TENANT_A_REAL_RENDER_RUNTIME_PASS**

## 6. D3 Tenant B Physical Isolation

**PASS**

Tenant: `v15_delivery_b`

Observed task: `44131027-97bc-4605-a6bc-b8e9ccbb1f4c`

Delivery path:

```text
F:\outputdir\V15\
tenants\v15_delivery_b\
projects\_default\
renders\2026-09-16\
44131027-97bc-4605-a6bc-b8e9ccbb1f4c\
```

Observed: 2 final videos, 2 covers.

Tenant A’s directory did not contain Tenant B’s task ID.

Conclusion: one global root + canonical tenant namespace = physical
cross-tenant render isolation.

**D3_TENANT_B_PHYSICAL_ISOLATION_RUNTIME_PASS**

## 7. D4 ZIP Tenant Isolation

**PASS**

Tenant A ZIP:

`dopamatrix_delivery_v15_delivery_a_70027063d660_20260916T142517499869Z_bc7b459f.zip`

Tenant A physical path:

```text
F:\outputdir\V15\tenants\v15_delivery_a\projects\_default\exports\
```

Tenant B ZIP:

`dopamatrix_delivery_v15_delivery_b_8acaa51847cb_20260916T143242861999Z_2383c266.zip`

Tenant B physical path:

```text
F:\outputdir\V15\tenants\v15_delivery_b\projects\_default\exports\
```

Cross-tenant negative proof (`X-Local-User = v15_delivery_b`):

- status lookup for Tenant A ZIP → **404 Export not found**
- download Tenant A ZIP → **404 Export not found**

Positive proof: Tenant B downloads Tenant B ZIP → **HTTP 200**
`application/zip`

**D4_ZIP_TENANT_ISOLATION_RUNTIME_PASS**

## 8. D5 External Root Failure

**PASS**

Precondition: PowerShell `Test-Path "Z:\"` returned `False`.

Global Delivery Root was temporarily set to
`Z:\DopaMatrixUnavailableTest`. Backend accepted it as configured.

A real qualified Balanced render then **completed**.

Observed:

- UI task completed
- internal `output/` assets were created
- external root was unavailable
- authoritative task did **not** become failed

After test, Delivery Root was restored to `F:\outputdir\V15`.

This artifact does **not** claim runtime log proof of
`DELIVERY_COPY_FAILED` (no captured log was supplied). Behavioral
runtime evidence proves external Delivery failure remained
non-authoritative. Automated implementation tests already cover the
non-raising delivery-failure contract.

**D5_EXTERNAL_ROOT_FAILURE_NON_FATAL_RUNTIME_PASS**

**DELIVERY_ROOT_RESTORED_AFTER_FAULT_TEST**

## 9. D6 Authority / Fallback / Diagnostics

**PASS**

Durable SQLite read-only evidence from
`data/dopamatrix_v15_delivery_a.db`, task
`935a6e76-1644-4465-963e-a6e95cc6b69d`:

TaskHistory persisted internal locators:

```text
output/final_en_efbd11f1.mp4
output/final_en_6f14c940.mp4
```

Cover paths remained internal `output/` paths.

Variant approvals also referenced `output/final_...`, not
`F:\` Delivery Root.

VideoTask remained:

- `status = completed`
- `planning_policy = exact_main_visual_balanced`
- `reservation_conflict_mode = OFF`
- `reservation_mode_source = DEFAULT_OFF`

Fallback test: Delivery Root cleared. Backend returned
`delivery_root = ""`, `is_configured = false`.

New ZIP export physically appeared under
`<project-root>\output\exports\`.

- Tenant A downloading own fallback ZIP: HTTP 200, `application/zip`
- Tenant B downloading Tenant A fallback ZIP: HTTP 404 Export not found

After fallback test, Delivery Root restored to `F:\outputdir\V15`.

Reservation diagnostics:

`GET /api/v1/diagnostics/reservation/summary?window=24h` → HTTP 200
with the normal Reservation diagnostics schema. No Delivery-specific
fields contaminated that payload.

**D6_AUTHORITY_FALLBACK_DIAGNOSTICS_RUNTIME_PASS**

**ZIP_FALLBACK_TENANT_CONFINEMENT_RUNTIME_PROVEN**

**RESERVATION_DIAGNOSTICS_RUNTIME_UNCHANGED**

## 10. SQLite Durable Truth

TaskHistory remains authoritative on internal:

```text
output/final_*
output/cover_*
```

External `F:\outputdir\V15\...` is **delivery copy only**.

`fingerprint_occurrences` retained authoritative `PLANNED` and
`RENDERED` records tied to task/execution identities.

This supports:

- TaskHistory authority unchanged
- Fingerprint lineage unchanged
- Future L3 backfill boundary unchanged (internal catalog only)

No full temporary terminal dump is reproduced here.

**TASKHISTORY_INTERNAL_AUTHORITY_RUNTIME_PROVEN**

## 11. Frontend Production Build

Local Windows frontend production build completed successfully after
implementation, closing the Node/npm environment limitation recorded
in the Implementation Report.

- Node: v22.23.1
- npm: 10.9.8
- `npm run build`: **PASS**
- Vite warning(s) did not fail the build

**FRONTEND_PRODUCTION_BUILD_RUNTIME_PASS**

## 12. Final Gate Table

| Gate | Purpose | Result | Primary Evidence |
|---|---|---|---|
| D1 | Global Delivery Root | **PASS** | POST/GET `F:\outputdir\V15`; restart persistence; tenant preview derivation |
| D2 | Tenant A real render | **PASS** | Tasks `935a6e76-…`, `5d095b7d-…`; internal `output/` full set; delivery finals+covers only under `renders/2026-09-16/<task_id>/` |
| D3 | Tenant B isolation | **PASS** | Task `44131027-…` under `tenants\v15_delivery_b\…`; A dir has no B task id |
| D4 | ZIP isolation | **PASS** | Distinct tenant ZIP names/paths; B cannot status/download A (404); B self-download 200 zip |
| D5 | External-root failure | **PASS** | `Z:\` missing; task completed; internal assets present; root restored |
| D6 | Authority / fallback / diagnostics | **PASS** | TaskHistory `output/final_*`; fallback `output/exports` + 404 cross-tenant; diagnostics 200 |

All result: **PASS**

## 13. Final Two-Root Authority Boundary

**INTERNAL AUTHORITY:** `<project-root>/output/`

Owns:

- TaskHistory locators
- final authoritative assets
- master / intermediate assets
- backup source
- future L3 backfill source

**EXTERNAL DELIVERY:** `<delivery-root>/tenants/<tenant>/projects/_default/`

Owns:

- operator-facing final copies
- cover copies
- tenant-confined ZIP exports

Delivery never becomes authority.

## 14. Regression Boundary

Manual Runtime D1–D6 plus the implementation-report automated
regression evidence did **not** require rerunning the old L1/L2
Manual Gate 1–6.

Reason: implementation did not change FP-001, planner, same-batch
uniqueness, Reservation authority, lease, Readiness, rollout,
breaker, kill switch, TaskHistory authority, backup authority, or
the L3 boundary.

This artifact does **not** imply those features were manually
re-tested during D1–D6.

**FULL_L1_L2_CANARY_REACCEPTANCE_NOT_REQUIRED**

## 15. Runtime Evidence Policy

This acceptance artifact is the durable Git evidence.

Runtime screenshots were temporary human-review evidence only. They
are **not** required in Git and are not referenced by local filename
here.

## 16. Remaining Non-Blockers

- Content-Disposition header was null in a manual ZIP fetch, while
  HTTP 200 `application/zip` and frontend blob download remain
  correct.
- Node/Codex PATH discoverability is a developer-environment
  maintenance issue, not a V1.5 runtime blocker. The local
  `npm run build` PASS already closed the implementation-report
  frontend-build gap.

Do not expand scope.

## 17. Git Status

Before this write:

```text
git branch --show-current
feature/var-001-variation-policy

git rev-parse HEAD
73982e4073455a8e542015c25cd9e20e397dd078

git status --short
 M main.py
 M src/api/routes_dsl.py
 M src/api/routes_matrix.py
 M src/api/settings_router.py
 M tests/test_matrix_export.py
 M web_ui/src/App.vue
 M web_ui/src/stores/appStore.js
 M web_ui/src/views/SettingsView.vue
?? doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_IMPLEMENTATION_REPORT.md
?? doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_POSTCOMMIT_SOURCE_EXCERPTS.md
?? doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_TARGETED_AUDIT.md
?? src/api/delivery_output.py
?? tests/test_var001_tenant_delivery_output.py
```

After this artifact only, the new file is:

```text
?? doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_RUNTIME_ACCEPTANCE.md
```

Audit, source-excerpt, and implementation-report files were not
modified. No commit. No push.

## 18. Final Classification

Proof markers:

- D1_GLOBAL_DELIVERY_ROOT_RUNTIME_PASS
- D2_TENANT_A_REAL_RENDER_RUNTIME_PASS
- D3_TENANT_B_PHYSICAL_ISOLATION_RUNTIME_PASS
- D4_ZIP_TENANT_ISOLATION_RUNTIME_PASS
- D5_EXTERNAL_ROOT_FAILURE_NON_FATAL_RUNTIME_PASS
- D6_AUTHORITY_FALLBACK_DIAGNOSTICS_RUNTIME_PASS
- FRONTEND_PRODUCTION_BUILD_RUNTIME_PASS
- TASKHISTORY_INTERNAL_AUTHORITY_RUNTIME_PROVEN
- ZIP_FALLBACK_TENANT_CONFINEMENT_RUNTIME_PROVEN
- DELIVERY_ROOT_RESTORED_AFTER_FAULT_TEST
- RESERVATION_DIAGNOSTICS_RUNTIME_UNCHANGED
- FULL_L1_L2_CANARY_REACCEPTANCE_NOT_REQUIRED

VAR001_V15_TENANT_DELIVERY_OUTPUT_RUNTIME_ACCEPTANCE_FINAL_PASS
