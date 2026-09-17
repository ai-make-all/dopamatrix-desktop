# VAR-001 V1.5 Seed Release Hardening
# Tenant / Project Delivery Output Isolation Implementation Report

## 1. Executive Result

The accepted Two-Root architecture is implemented as a narrow delivery layer.
Authoritative render assets, TaskHistory locators, Fingerprint Ledger truth, and
backup/restore remain under the project `output/` root. A machine-global
Delivery Root now receives tenant-confined operator copies and ZIP exports.

The automated Python contract and regression suites pass. Manual runtime
acceptance, including a real removable/unavailable drive, remains required.

`VAR001_V15_TENANT_DELIVERY_OUTPUT_IMPLEMENTATION_READY_FOR_RUNTIME_ACCEPTANCE`

## 2. Source Inputs

The implementation was based on the current source after reading these accepted
handoff artifacts in full:

- `doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_TARGETED_AUDIT.md`
- `doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_POSTCOMMIT_SOURCE_EXCERPTS.md`

Current source took precedence wherever a detail had changed.

## 3. Final Architecture Boundary

- Internal authority: `<project-root>/output/`
- External delivery: `<delivery-root>/tenants/<canonical-tenant>/projects/_default/`
- Render copies: `renders/<YYYY-MM-DD>/<task_id>/`
- ZIP exports: `exports/`

Delivery paths never replace TaskHistory paths. The new module is intentionally
small and is not a generic storage framework.

`TENANT_PROJECT_DELIVERY_PATH_CONTRACT_PROVEN`

## 4. Settings Persistence

`delivery_root` is persisted in the existing machine-global
`dopamatrix.db/app_settings` table. Dedicated endpoints are:

- `GET /api/v1/settings/delivery-root`
- `POST /api/v1/settings/delivery-root`

The POST stores a normalized absolute path. Blank deletes the setting and is a
valid unset state. The endpoint does not consult a tenant and exposes no secret.
Focused tests prove round-trip persistence, blank/unset behavior, cross-tenant
visibility of the same global value, and rejection before persistence of a
relative path.

`GLOBAL_DELIVERY_ROOT_DB_PERSISTENCE_PROVEN`

## 5. Delivery Path Resolver

`src/api/delivery_output.py` provides root normalization and focused tenant,
render, and export path derivation. It requires an absolute root, accepts only
the already-canonical tenant identity, rejects empty/dot/traversal/separator
segments and Windows reserved device names, resolves paths physically, and
verifies every derived target remains under Delivery Root. A real Windows
junction test proves an existing alias cannot redirect the tenant subtree out
of the configured root.

## 6. Post-Authoritative Publication Hook

The only DSL publication hook is
`routes_dsl._publish_authoritative_delivery_safely`, invoked inside
`_render_batch_worker_impl` after Reservation authority-loss and terminal-
persistence-failure wipe branches, after successful ENFORCE fenced terminal or
OFF TaskHistory commit has set `history_persisted`, and before terminal payload
construction/WebSocket broadcast.

The gate is exactly `history_persisted and assets`. Both the focused helper and
the call-site wrapper catch ordinary failures, so delivery cannot replace final
status, payload, TaskHistory, Ledger, Reservation, or later VideoTask lifecycle
truth.

`POST_AUTHORITATIVE_DELIVERY_PUBLICATION_PROVEN`

## 7. Render Delivery Semantics

Only authoritative final video paths (`final_*.mp4`) and cover paths
(`cover_*.jpg/.jpeg/.png/.webp`) are considered. Source filenames are
preserved. Repeated final/cover paths are deduplicated. Master video, voice,
VTT, ASS, and arbitrary/intermediate fields are ignored. Missing sources and
copy errors generate bounded logging only.

The legacy compositor `context.config["output_dir"]` behavior was not wired to
Delivery Root and was not changed.

`NONAUTHORITATIVE_OUTPUT_NOT_DELIVERED_PROVEN`

`FINAL_AND_COVER_DELIVERY_PROVEN`

## 8. ZIP Export Isolation

When Delivery Root is configured, ZIPs are written to the current canonical
tenant's `_default/exports` directory. When unset, physical storage retains the
legacy `<project-root>/output/exports` fallback.

New filenames retain the `dopamatrix_delivery_` prefix and `.zip` suffix while
including a non-secret tenant token, UTC microsecond timestamp, and random UUID
suffix. Same-second calls are independently unique. Temporary `.partial` and
failure marker files remain colocated with the tenant-qualified ZIP.

`TENANT_ZIP_PHYSICAL_ISOLATION_PROVEN`

`ZIP_FILENAME_COLLISION_RESISTANCE_PROVEN`

## 9. ZIP Download Tenant Confinement

Status and download both derive authority from the current request's canonical
`X-Local-User` tenant and validate that the filename token belongs to that
tenant. The download route is:

`GET /api/v1/matrix/export/download?filename=<token>`

It returns `FileResponse` only for the current tenant's resolved export
directory. Cross-tenant status and download return 404. The old unauthenticated
global `/exports` StaticFiles mount was removed; otherwise new fallback ZIPs in
the shared legacy directory could bypass tenant checks.

`TENANT_ZIP_DOWNLOAD_CONFINEMENT_PROVEN`

## 10. Frontend UX

Settings now presents **交付根目录 / Delivery Root**, explicitly explains that
authoritative assets remain in internal `output/`, and shows the current tenant
preview through `projects/_default/{renders,exports}`. Selection and clearing
use the backend settings API. App startup and Settings hydration read the
backend value. Logout no longer clears the machine-global path.

Web ZIP fallback download now uses axios with `responseType: 'blob'`, so the
existing `X-Local-User` default header is sent. It creates a temporary object
URL, downloads with the server filename, and revokes the URL. Tauri local-path
reveal behavior remains.

## 11. Delivery Failure Semantics

Render publication is best-effort and non-raising. A missing file, unavailable
drive, permissions error, disk-full error, invalid stored root, or unexpected
hook exception is logged as `DELIVERY_COPY_FAILED` without adding a DB table or
changing the public response schema. Logging-only was selected to avoid making
delivery convenience state authoritative or destabilizing terminal payloads.

During ZIP integration testing, the pre-existing emoji console `print` was
shown to raise `UnicodeEncodeError` under Windows GBK after a successful ZIP
write. ZIP logging and short-link fallback logging were changed to the standard
logger so logging cannot reverse export control flow.

`DELIVERY_COPY_FAILURE_NON_FATAL_PROVEN`

## 12. TaskHistory / Backup / L3 Non-Changes

No TaskHistory model, builder, locator, Ledger, planner, Reservation, rollout,
readiness, backup/restore, compositor output, or future L3 code was changed.
TaskHistory assets remain internal `output/final_*` locators. Backup continues
to enumerate only authoritative internal assets; delivery copies do not enter
backup or future L3 indexing/backfill.

`TASKHISTORY_INTERNAL_AUTHORITY_UNCHANGED_PROVEN`

`BACKUP_AUTHORITY_UNCHANGED_PROVEN`

`L3_BACKFILL_BOUNDARY_UNCHANGED_PROVEN`

`RESERVATION_PLANNER_ROLLOUT_UNCHANGED_PROVEN`

## 13. Tests Added

`tests/test_var001_tenant_delivery_output.py` adds 24 focused tests covering:

- machine-global settings persistence and blank/unset behavior;
- canonical tenant, `_default`, absolute-root, traversal, confinement, and
  Windows junction behavior;
- post-authoritative gate placement and non-raising failure isolation;
- final/cover delivery and intermediate exclusion/deduplication;
- configured/fallback ZIP paths, collision resistance, filename traversal,
  tenant-confined status/download, and axios blob download wiring;
- TaskHistory/backup/compositor boundary source checks.

`tests/test_matrix_export.py` was aligned with the already-current asynchronous
export API and converted from an unavailable pytest fixture to the repository's
executable unittest style. Its 3 tests exercise the real background ZIP builder,
approved-only packaging, CSV content, short-link idempotence, unique filenames,
and cross-tenant status/download denial.

## 14. Test Results

- Focused delivery + Matrix export: **27/27 PASS**.
- Full `test_var001_*` discovery: **405/405 PASS**, 1 platform-specific skip.
- Full `test_inv001_*` discovery: **85/85 PASS**.
- Full `test_fp001_*` discovery: **42/42 PASS**.
- Additional targeted batch/Reservation/backup run: **71/71 PASS**, 1
  platform-specific skip.
- Additional task/Reservation/diagnostics/readiness/rollout run:
  **167/167 PASS**.
- Python `py_compile`: PASS.
- `git diff --check`: PASS.

The frontend production build could not be launched because this environment
has no available `node`/`npm` executable. Existing `node_modules` are present,
but no dependency or machine configuration was modified. Frontend source
contracts are covered by focused static tests; the build remains an explicit
environment-limited check for runtime acceptance.

An attempted read-only import of `main` was blocked by the managed sandbox when
the existing logger tried to open its normal AppData log file. This was not a
source/test failure and no escalation or environment change was made.

## 15. Diff Scope Audit

Production changes are confined to:

- `main.py` (remove unauthenticated global export mount)
- `src/api/delivery_output.py` (new focused helper)
- `src/api/settings_router.py`
- `src/api/routes_dsl.py`
- `src/api/routes_matrix.py`
- `web_ui/src/App.vue`
- `web_ui/src/stores/appStore.js`
- `web_ui/src/views/SettingsView.vue`

Test changes are confined to:

- `tests/test_var001_tenant_delivery_output.py`
- `tests/test_matrix_export.py`

Accepted audit inputs were not modified. No Reservation/planner/rollout,
TaskHistory authority, backup authority, L3, schema, or project model was added
or changed.

## 16. Runtime Acceptance Still Required

This report does not claim manual runtime PASS. The later narrow acceptance must
still set and reload a real Delivery Root; render as Tenant A and B; verify
internal plus final/cover delivery paths; export/download both ZIPs; verify
cross-tenant denial; simulate an unavailable drive without changing
authoritative completion; verify TaskHistory remains internal; and smoke-test
backup and Reservation diagnostics.

The frontend production build should also be run once a Node/npm executable is
available.

## 17. Findings

No authority-layer blocker was found. The implementation remains ready for
runtime acceptance.

Resolved within scope:

- unauthenticated `/exports` could bypass tenant-aware download for fallback
  ZIPs, so the legacy global mount was removed;
- Windows GBK console output could throw after ZIP success, so background export
  logging no longer uses emoji `print`.

Environment limitations, not source defects:

- no Node/npm executable for frontend build;
- sandbox-denied AppData log write during standalone `main` import.

## 18. Git Status

Baseline:

```text
branch: feature/var-001-variation-policy
HEAD: 73982e4073455a8e542015c25cd9e20e397dd078
```

Expected pre-existing untracked inputs remain:

```text
?? doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_POSTCOMMIT_SOURCE_EXCERPTS.md
?? doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_TARGETED_AUDIT.md
```

Final `git status --short`:

```text
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

`git diff --check`: PASS (line-ending conversion notices only; no whitespace
errors).

No commit or push was performed.

VAR001_V15_TENANT_DELIVERY_OUTPUT_IMPLEMENTATION_READY_FOR_RUNTIME_ACCEPTANCE
