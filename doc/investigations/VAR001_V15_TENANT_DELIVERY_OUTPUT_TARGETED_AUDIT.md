# VAR-001 V1.5 Seed Release Hardening
# Tenant / Project Delivery Output Targeted Audit

Role: read-only current-source audit. No production, Vue, tests, SQLite,
settings, environment, render, export, or git writes besides this file.

Statement labels:

- **SOURCE FACT** — current code contract
- **EXISTING ACCEPTANCE EVIDENCE** — prior VAR-001 artifacts
- **AUDIT INFERENCE** — operational reading of those facts
- **V1.5 RECOMMENDATION** — not an implementation

## 1. Executive Result

The Settings UI path `F:\outputdir\V15` proves **SETTING_PERSISTED**
only (browser `localStorage`). It does **not** prove
**RENDER_PIPELINE_WIRED**.

Qualified V1.5 AI Draft / `POST /api/v1/tasks/submit-dsl` still writes
authoritative artifacts under project-relative `output/`. Approved ZIP
exports still write under `os.getcwd()/output/exports`. Neither consults
the UI setting.

A narrow **Two-Root** V1.5 fix is source-feasible:

- keep TaskHistory + backup + L3 future indexing on `<project-root>/output/`
- treat the configured path as a **global Delivery Root**
- derive `tenants/<canonical-tenant>/projects/_default/{renders,exports}/`
- copy operator-facing deliverables only; delivery failure must not
  change Reservation / terminal authority

Do **not** move authoritative storage. Do **not** repeat full Gate 1–6
unless authority code is touched (it need not be).

**VAR001_V15_TENANT_DELIVERY_OUTPUT_NARROW_FIX_READY**

Proof markers actually supported:

- CURRENT_OUTPUT_SETTING_PERSISTENCE_TRACED
- CURRENT_OUTPUT_SETTING_RUNTIME_WIRING_TRACED
- AUTHORITATIVE_OUTPUT_ROOT_SOURCE_PROVEN
- CUSTOM_OUTPUT_COPY_SEMANTICS_SOURCE_PROVEN
- TASKHISTORY_INTERNAL_PATH_AUTHORITY_PROVEN
- ZIP_EXPORT_PHYSICAL_PATH_SOURCE_PROVEN
- TENANT_ID_AT_DELIVERY_BOUNDARY_PROVEN
- PROJECT_NAMESPACE_CURRENT_LIMIT_PROVEN
- TWO_ROOT_BACKUP_COMPATIBILITY_PROVEN
- TWO_ROOT_L3_COMPATIBILITY_PROVEN
- V15_DELIVERY_FAILURE_NON_AUTHORITY_BOUNDARY_DEFINED
- V15_TENANT_PROJECT_DIRECTORY_CONTRACT_FEASIBLE
- V15_NARROW_FIX_SURFACE_IDENTIFIED
- FULL_L1_L2_CANARY_REACCEPTANCE_NOT_REQUIRED

## 2. Scope

Current source wins over older reports. Prior artifacts read for
boundary, not re-litigation:

- `doc/investigations/VAR001_PHASE3D2H_V15_FORWARD_COMPATIBILITY_AUDIT.md`
- `doc/investigations/VAR001_PHASE3D2IA_TARGETED_BACKUP_RESTORE_SOURCE_REVIEW.md`
- `doc/investigations/VAR001_PHASE3D2IA_V15_RC_BACKUP_ACCEPTANCE_REPORT.md`
- `doc/investigations/VAR001_PHASE3D2IA2_MANUAL_FULLSTACK_ACCEPTANCE.md`

This audit does not implement Delivery Root, change output directories,
or run renders.

## 3. Frozen V1.5 Storage Boundaries

| Root | Role | V1.5 rule |
|---|---|---|
| `<project-root>/output/` | INTERNAL ARTIFACT STORE | Authoritative finals, master, voice, subtitle, cover, TaskHistory locators, backup/restore assets, future L3 backfill source |
| User-configured path | GLOBAL DELIVERY ROOT | Operator-facing copies only; not TaskHistory authority |
| `projects/_default/` | Future-compatible namespace | No project schema exists; do not invent one |

**V1.5 RECOMMENDATION:** do not move TaskHistory paths to an arbitrary
external drive.

## 4. Settings UI and Persistence

**SOURCE FACT** chain:

1. Component: `web_ui/src/views/SettingsView.vue`
2. Label: `本地输出目录绑定`
3. Subtitle: “成品短视频的统一落地目录。若不设置，默认写入工程 `output/`”
4. Reactive state: Pinia `store.globalOutputDir`
5. Picker: `pickGlobalOutputFolder()` → Tauri `open({ directory: true })`
   → `store.setGlobalOutputDir(selected)`
6. Save API: **none**. No `axios` call for this field.
7. Backend route: **none** for output path. `/api/v1/settings/llm` is
   the only settings router and stores `openai_api_key` only
   (`src/api/settings_router.py`).
8. Persistence key: browser `localStorage` `dopamatrix_output_dir`
   (`web_ui/src/stores/appStore.js`).
9. Database/file: **not** `dopamatrix.db`, **not** tenant SQLite.
10. Scope: **browser-profile GLOBAL**, not tenant-scoped. Login tenant
    does not participate in save/read. Logout **deletes** the key
    (`handleLogout` removes `dopamatrix_output_dir`).
11. Hydration: store init `localStorage.getItem('dopamatrix_output_dir') || ''`.

UI showing `F:\outputdir\V15` proves **SETTING_PERSISTED** in that
browser profile only.

It does **not** prove **RENDER_PIPELINE_WIRED**.

## 5. Settings Scope

**SOURCE FACT:** LLM settings live in global `dopamatrix.db` /
`app_settings` (`SETTINGS_DB_PATH`, comment: 非租户数据). Output path
does not live there.

**SOURCE FACT:** tenant SQLite (`data/dopamatrix_{canonical}.db`) has
no output-directory column in this setting flow.

A **single global Delivery Root** plus derived
`tenants/<canonical-tenant>/...` is naturally compatible:

- one Seed machine, three tenants, one operator UI
- current UI is already a single shared path, not per-tenant
- `canonical_tenant_id` already produces a filename-safe slug

**V1.5 RECOMMENDATION:** store **one global Delivery Root** (prefer
`app_settings` so logout/browser-switch does not drop it). Do **not**
store a separate absolute path per tenant.

Per-tenant absolute roots would fight the existing global settings
architecture and make operator mistakes (Tenant B writing into Tenant
A’s drive root) easier.

## 6. Current Render Path Authority

Qualified V1.5 path: Workspace AI Draft →
`POST /api/v1/tasks/submit-dsl` → `render_batch_worker` →
`render_worker` → nodes. `render_worker` creates `output/` and never
sets `context.config["output_dir"]`.

| Artifact | Source | Helper | Authoritative write | Consults `config["output_dir"]` | Tenant | task/execution/file_sid |
|---|---|---|---|---|---|---|
| TTS MP3/VTT | `src/nodes/tts_node.py` | `TTSNode.execute` | `output/voice_{execution_id}_{lang}.mp3/.vtt` (constructor default `"output"`) | No | `context.tenant_id` present, unused for path | execution_id yes |
| Subtitle ASS | `src/nodes/subtitle.py` | `SubtitleNode.execute` | hardcoded `Path("output")` / `sub_{execution_id}_{lang}.ass` | No | unused for path | execution_id yes |
| Master MP4 | `src/nodes/compositor.py` | `_master_output_path` | `output/master_video_{file_sid}.mp4` | No | unused for path | file_sid yes |
| Final MP4 | same | `_final_output_path` | `output/final_{lang}_{file_sid}.mp4` | Copy only, after write | unused for path | file_sid + lang |
| Cover JPG | `src/nodes/cover_node.py` | `_cover_output_path` | same dir as video → `output/cover_{file_sid}.jpg` | No | logged, unused for path | file_sid yes |

All of the above are **AUTHORITATIVE WRITE** (internal store).

Optional compositor `shutil.copy` is a **DELIVERY COPY** of finals only
and is **not entered** on the DSL worker (see §7–§8).

`os.makedirs("output", exist_ok=True)` in `render_worker` is the
authoritative root mkdir.

## 7. Custom Output Copy Wiring

**SOURCE FACT** (`src/nodes/compositor.py` after successful variant
FFmpeg):

```text
custom_output_dir = context.config.get("output_dir")
if custom_output_dir:
    os.makedirs(custom_output_dir, exist_ok=True)
    target = join(custom_output_dir, basename(final_path))
    shutil.copy(final_path, target)
```

Revalidation vs 2H: still accurate.

| Question | Current source |
|---|---|
| Artifact types copied | **final video only** (`final_{lang}_{file_sid}.mp4`) |
| When | after that language variant FFmpeg returncode 0, still inside the same `try` as FFmpeg |
| Source path | internal `final_path` (`output/final_...`) |
| Destination | `{custom_output_dir}/{basename}` — **flat**, no tenant/project |
| Filename | basename unchanged (execution-unique) |
| Overwrite | `shutil.copy` overwrites if the name exists |
| mkdir | `os.makedirs(..., exist_ok=True)` |
| Copy failure | `OSError`/`shutil.Error` are **not** caught as copy-specific errors; they propagate from `_render_variant` |
| Fails the render? | **Yes, if this branch runs.** `_run_compositor` treats any `execute()` exception as child render failure (`False`) |
| TaskHistory path | still internal `final_video`; copy does **not** replace it |
| WS/UI path | `render_worker` collects `context.variants[].final_video` (internal) |
| Cover copied? | **No** |
| Multilingual finals? | Yes, per language in the variant loop **if** `output_dir` is set |
| Master/voice/subtitle copied? | **No** |

Why the UI root is not visible today — complete value flow, no guess:

1. Settings writes `localStorage` only.
2. `WorkspaceView.vue` submit payload has **no** `output_dir`.
3. `RenderDSLRequest` has **no** `output_dir` field.
4. `render_worker` never assigns `context.config["output_dir"]`.
5. Compositor copy is skipped.

**FIRST BROKEN / MISSING LINK:** UI `dopamatrix_output_dir` never
enters any backend request or worker config on the qualified V1.5 path.

Legacy `/api/v1/tasks/submit` (`routes.py` + `services.py` +
`run_matrix_factory.py`) **can** set `context.config["output_dir"]`.
Ordinary V1.5 UI does not call that endpoint.

## 8. Settings-to-Worker Value Flow

```text
Settings UI
  → Pinia globalOutputDir
  → localStorage dopamatrix_output_dir
  → ✖ (no API, no app_settings key)
  → Workspace POST /api/v1/tasks/submit-dsl
       payload: engine/timeline/aspect/batch/policy/...  (no output_dir)
  → RenderDSLRequest  (no output_dir field)
  → public admission / render_batch_worker
  → render_worker WorkflowContext.config
       keys set: execution_id, file_sid, child_index,
                 enable_tts, enable_subtitles,
                 ws_terminal_managed_by_coordinator
       NOT set: output_dir, delivery_root, export_dir
  → compositor copy skipped
  → AUTHORITATIVE WRITE under output/
```

Searched: `output_dir`, `output_path`, `export_dir`, `delivery_dir`,
`delivery_root`, `dopamatrix_output_dir`.

On the V1.5 DSL path the first missing link is **UI → backend**. There
is no later worker consumption of the UI key because it never arrives.

## 9. Tenant Identity Availability

**SOURCE FACT:** `submit_dsl` resolves
`tenant_id = _authoritative_request_tenant(payload, request)` from
`X-Local-User` via `request_tenant_id` → `canonical_tenant_id`
(alnum / `_` / `-`, then `os.path.normcase`; empty → `default`).

That canonical string is passed to `render_batch_worker(..., tenant_id)`
and `render_worker(..., tenant_id)` and stored as
`WorkflowContext.tenant_id`.

A future copy helper **can** derive:

```text
<delivery-root>/tenants/<canonical-tenant>/
```

without changing task identity, planner, Reservation, rollout, or
TaskHistory authority.

**VAR3D2I-OUTPUT-RF-06 is NOT supported.** Tenant id is available at
the delivery-copy point (`context.tenant_id`).

## 10. Project Namespace Availability

**SOURCE FACT:** repository search finds **no** `project_id` /
`project_slug` on public tasks, `VideoTask`, or `TaskHistory`.

Classify V1.5 delivery as:

```text
projects/_default/
```

A future real project segment can replace `_default` additively under
the same `tenants/<tenant>/projects/<segment>/` contract. Do not add
schema in V1.5.

**PROJECT_NAMESPACE_CURRENT_LIMIT_PROVEN**

## 11. Current ZIP Export Flow

**SOURCE FACT** (`src/api/routes_matrix.py`):

1. Trigger: `POST /api/v1/matrix/export` body `{ hashes: [...] }`
2. Tenant DB: `X-Local-User` → `background_build_zip(tenant_id)` →
   `get_tenant_engine(tenant_id)`
3. Selection: `VariantApproval` rows with `APPROVED` and hash in list;
   skip if `file_path` missing on disk
4. Physical files: `ap.file_path` (TaskHistory-backed internal paths)
5. ZIP construction: temp `{EXPORT_DIR}/{filename}.partial` then
   `os.replace` to `{filename}`
6. Export directory: `EXPORT_DIR = os.path.join(os.getcwd(), "output", "exports")`
   (module import also `os.makedirs`)
7. Filename: `dopamatrix_delivery_{int(time.time())}.zip`
8. Tenant id: **yes** for DB; **no** for directory/filename
9. Project identity: **no**
10. Custom output setting: **not consulted**
11. Cross-tenant disk collision: **yes** — shared `output/exports`,
    second-resolution names
12. Discovery/download: `GET /matrix/export/status?filename=` looks in
    `EXPORT_DIR`; `download_url` = `/exports/{safe_filename}`;
    `main.py` mounts `StaticFiles(directory=output/exports)` at `/exports`

ZIP inner names: `{account}_{core}_{hook}_{hash6}.mp4` under `videos/`
plus CSV. Covers are not zipped.

Locations that would need to change for
`<delivery-root>/tenants/<tenant>/projects/_default/exports/`
(not modified here): `EXPORT_DIR` constant; `background_build_zip`
path join; `check_export_status` lookup; `main.py` `/exports` mount
**or** a tenant-aware download route; possibly filename uniqueness.

## 12. Export API Contract

| Surface | Current | Physical-path change impact |
|---|---|---|
| POST response | `{ status, filename }` | Keep filename token if status lookup is tenant-aware |
| `download_url` | `/exports/{filename}` | Global StaticFiles has **no tenant**. Moving files off `output/exports` **without** a tenant-aware GET will break download |
| Filename validation | must match `dopamatrix_delivery_*.zip` (`os.path.basename` only) | Keep; add uniqueness suffix without changing prefix contract |
| GET status | exists(zip) / exists(.failed) / processing | Must search the same physical root written by the builder |
| UI history | polls filename; stores `downloadUrl` + `local_path` | `local_path` is `os.path.abspath(zip_path)` — will change if dest changes; download URL can stay |
| Restart | in-flight zip is a file on disk; no DB job table | Same |
| Confinement | StaticFiles of entire export dir; guessable timestamps | Tenant-aware route is safer |

**V1.5 RECOMMENDATION:** keep the **filename token** and `/exports/...`
URL shape if possible; implement download as a tenant-header confined
route rather than a global directory listing. That is a small serving
change, not a payload schema rewrite.

Physical storage path ≠ public filename contract.

## 13. TaskHistory Authority

**SOURCE FACT:** DSL `render_worker` appends
`{"file_path": _fp, "file_hash": ..., "cover_path": _cover_path}`
where `_fp = variants[lang]["final_video"]` = compositor internal path
`output/final_{lang}_{file_sid}.mp4`.

Coordinator persists that list on `TaskHistory.output_assets`.

Compositor copy, when present, does **not** assign `final_video` to the
copy destination (2H revalidated).

**HARD V1.5 SAFETY BOUNDARY:** a Delivery Root fix can and must leave
TaskHistory unchanged.

**TASKHISTORY_INTERNAL_PATH_AUTHORITY_PROVEN**

**VAR3D2I-OUTPUT-RF-03 is NOT supported** (copy does not replace
history).

## 14. Backup / Restore Compatibility

**SOURCE FACT:** backup enumerates **only** TaskHistory
`file_path` / legacy `path`, resolves them under
`project_root/output`, and rejects locators outside that asset root
(`BackupPathSafetyError`). It does not scan `output/` and does not
read `cover_path`. Restore writes `staging/output/...`.

If V1.5 adds **only** external copies under `F:\outputdir\V15\...` and
TaskHistory stays on `<project-root>/output/...`:

**existing backup/restore does not require modification.**

Should Delivery Root be in authoritative backup?

**V1.5 RECOMMENDATION: NO.** It is a reproducible operator-facing copy.
Including it would either duplicate bytes or, if history ever pointed
there, **break** backup containment.

**VAR3D2I-OUTPUT-RF-08 is NOT supported** for Option B.
It **would** be true for Option A.

**TWO_ROOT_BACKUP_COMPATIBILITY_PROVEN**

## 15. Future L3 Compatibility

Keeping TaskHistory + authoritative `output/` unchanged preserves:

- exact file-hash backfill from catalog locators
- perceptual-hash backfill from those files
- task / execution / FP lineage already in history JSON + ledger

External delivery copies **must be ignored** by L3 indexing. Indexing
both roots would double-count the same creative.

Do not implement L3 here.

**TWO_ROOT_L3_COMPATIBILITY_PROVEN**

## 16. Path Safety

Proposed:

```text
<delivery-root>/
  tenants/<canonical-tenant>/
    projects/_default/
      renders/ | exports/
```

Tenant slug source: **only** `canonical_tenant_id` (already strips to
`[A-Za-z0-9_-]`, Windows `normcase`).

| Rule | Class |
|---|---|
| Use canonical tenant only; never raw `X-Local-User` | MUST_HAVE_V15 |
| Reject empty / `.` / `..` after canonicalize | MUST_HAVE_V15 |
| Join then verify result stays under `delivery-root.resolve()` | MUST_HAVE_V15 |
| Delivery root must be absolute | MUST_HAVE_V15 |
| mkdir parents for tenant tree | MUST_HAVE_V15 |
| Missing/offline/permission: warn, do not fail render | MUST_HAVE_V15 |
| Windows reserved device names (`CON`, `NUL`, …) as tenant slug | MUST_HAVE_V15 |
| Trailing dot/space on segments | DEFER_TO_2_0 (canonical slug rarely hits this) |
| MAX_PATH / very long UNC | DEFER_TO_2_0 |
| Symlink/junction escape of delivery root | DEFER_TO_2_0 unless a one-line resolve check is cheap |
| Unicode NFC | DEFER_TO_2_0 |
| Mapped/network drive as delivery root | permitted if operator chose it; treat disconnect as copy-fail |

Do not let the tenant segment contain `:` or `\` (canonicalizer already
strips them).

## 17. Delivery Failure Semantics

**Current source (legacy copy site):** copy failure after FFmpeg success
fails the child (`_run_compositor` → `False`). Internal files may
already exist while public terminal becomes failed. That must **not**
be reused for V1.5 Delivery Root.

**V1.5 RECOMMENDATION: option B**

Keep authoritative render **completed**. Record/warn delivery-copy
failure (log + optional non-blocking warning code). Do **not** fail
TaskHistory, Reservation fence, or UI completed solely because
`F:\` is missing, read-only, full, or disconnected.

| Interaction | Required |
|---|---|
| TaskHistory | internal paths only |
| Terminal status | success if internal render succeeded |
| UI completed | follows terminal + internal assets |
| Operator visibility | toast/log that delivery copy failed |
| Backup truth | unchanged |
| Reservation | **must not** depend on the convenience drive |

Reject A (fail whole render) and C (delivery queue service) for V1.5
scope.

**V15_DELIVERY_FAILURE_NON_AUTHORITY_BOUNDARY_DEFINED**

**VAR3D2I-OUTPUT-RF-09:** supported as a **latent risk of the existing
compositor copy try-block**, not as current DSL behavior. V1.5 copy
must run **after** authoritative success, best-effort.

## 18. Filename / Collision Analysis

DSL finals: `final_{lang}_{file_sid}.mp4` with `file_sid = execution_uuid.hex[:8]`
unique per child. Cover: `cover_{file_sid}.jpg`. Language disambiguates
multilingual finals.

Copying those names into a **per-tenant** `renders/` directory is
collision-safe across tenants. Flat copy into a shared `F:\outputdir\V15`
without tenant dirs would mix tenants (current hypothetical compositor
copy).

ZIP: `dopamatrix_delivery_{unix_seconds}.zip` in a **shared**
`output/exports` can collide across tenants and same-second exports.

**V1.5 RECOMMENDATION:** keep execution-unique render filenames; add a
tenant-safe export name (e.g. include canonical tenant and a finer
unique suffix) while retaining the `dopamatrix_delivery_` prefix if
validation stays.

## 19. Delivery Directory Shape

| | Option 1 `renders/<date>/<task_id>/` | Option 2 `renders/<date>/` unique names only |
|---|---|---|
| Operator find-by-task | easier | harder |
| Future project | both fit under `_default` | both fit |
| Collision | very low | low (file_sid) |
| Manual copy/delete | delete one task folder | hunt files |
| Traceability | task_id in path | task_id only in filename/history |

**V1.5 RECOMMENDATION: Option 1**
`.../projects/_default/renders/<YYYY-MM-DD>/<task_id>/`

Exports: `.../exports/` with unique zip names (no need to nest by
task_id; export is multi-hash).

## 20. Delivery Content Set

| Artifact | Class |
|---|---|
| final video | **COPY_TO_DELIVERY** |
| cover | **COPY_TO_DELIVERY** (operator-facing; ZIP today omits it — still useful beside the mp4) |
| approved delivery ZIP | **COPY_TO_DELIVERY** (write here as primary operator drop, with API serving confined) |
| master video | **KEEP_INTERNAL_ONLY** |
| voice mp3/vtt | **KEEP_INTERNAL_ONLY** |
| subtitle ass | **KEEP_INTERNAL_ONLY** |
| intermediate/temp/clips | **KEEP_INTERNAL_ONLY** |

Principle: only operator-facing deliverables leave the internal store.

Cover in ZIP: **OPTIONAL** (current ZIP is video+CSV only; do not
expand ZIP schema unless product asks).

## 21. Default Fallback

When no Delivery Root is configured:

**V1.5 RECOMMENDATION: A** — no external copy; internal `output/` only.

Do **not** treat `project-root/output` as Delivery Root (that would
blur authority vs delivery and mix tenants). Do not invent a second
default drive.

This matches current DSL behavior (already internal-only) and is the
least surprising “unset” state.

## 22. UI Semantics

Current wording “本地输出目录绑定” + “成品短视频的统一落地目录” +
“默认写入工程 output/” **incorrectly suggests** that authoritative
output **moves** to the chosen path.

**V1.5 RECOMMENDATION** (wording only; do not edit UI in this phase):

- Title: **交付根目录 / Delivery Root**
- Body: 权威成片仍保存在应用内部 `output/`；此目录仅接收面向交付的副本。
- Read-only preview:
  - Current root: `F:\outputdir\V15`
  - Current tenant delivery: `F:\outputdir\V15\tenants\<canonical>\projects\_default\`
  - Renders: `...\renders\`
  - Exports: `...\exports\`

## 23. Option A vs Option B

| | OPTION A — move authoritative output to external root | OPTION B — internal output + tenant-aware Delivery Root |
|---|---|---|
| V1.5 risk | HIGH | LOW |
| TaskHistory | all locators change; media preview, ZIP, approval `file_path` follow | unchanged |
| Backup | containment likely **breaks** unless asset_root is redefined | unchanged |
| Restore | staging `output/` contract changes | unchanged |
| L3 | indexes external/unstable drives | indexes stable internal catalog |
| Operator usability | one folder, but mixed with internals if everything moves | two places; operator folder stays clean |
| Multi-tenant isolation | only if path includes tenant; easy to get wrong | derived `tenants/<canonical>/` |
| Future project | harder if history already escaped | `_default` additive |
| Regression | HIGH — Gate 1–6 + backup + restore | MINIMAL |

**SOURCE-GROUNDED RECOMMENDATION: OPTION B.**

Option A is classified **ARCHITECTURE_BLOCKED** for V1.5 (would force
backup/TaskHistory authority change). The observed operator problem
does **not** require Option A.

## 24. Minimal Fix Surface

| File | Function / component | Current | Likely narrow fix | Authority risk | Must change? | Why |
|---|---|---|---|---|---|---|
| `web_ui/src/views/SettingsView.vue` | output card | local picker + misleading copy | persist via API; Delivery Root wording + preview | none | yes | operator contract |
| `web_ui/src/stores/appStore.js` | `globalOutputDir` | localStorage only; cleared on logout | hydrate from settings API; stop treating as render root | none | yes | persistence |
| `src/api/settings_router.py` | LLM-only | global `app_settings` | add delivery-root get/set | none | yes | one global root |
| `src/api/routes_dsl.py` | `render_worker` after `render_ok` | no delivery | best-effort copy final+cover into derived tree | **must stay after success** | yes | value-flow break is here |
| `src/nodes/compositor.py` | custom copy in FFmpeg try | latent fail-render copy | **do not** reuse for V1.5; leave legacy or isolate later | HIGH if reused | no for DSL fix | keep authority try clean |
| `src/api/routes_matrix.py` | `EXPORT_DIR`, zip builder/status | cwd `output/exports` | write under tenant delivery exports; unique name | none if `file_path` reads stay internal | yes | RF-04/05/10 |
| `main.py` | `/exports` StaticFiles | global dir | tenant-confined download **or** dual-serve | none | likely yes | API serving |
| `src/api/backup_restore.py` | catalog under `output/` | TaskHistory only | **no change** | n/a | **no** | Option B |
| planner / Reservation / rollout | — | authority | **no change** | n/a | **no** | RF-13 false |
| TaskHistory persist | `_build_task_history_record` | internal `file_path` | **no change** | n/a | **no** | safety boundary |

**V15_NARROW_FIX_SURFACE_IDENTIFIED**

Hard non-goals remain out of scope. None of them are required to fix
the observed UI-vs-disk mismatch.

## 25. Regression Impact

Expected scope: **MINIMAL**.

Isolated from: FP-001, same-batch uniqueness, planner, Reservation
acquire/confirm/release, lease heartbeat, readiness, rollout, breaker,
kill switch, public task identity, child execution identity — **if**
copy stays post-success and TaskHistory paths stay internal.

**VAR3D2I-OUTPUT-RF-13 / RF-14 are NOT supported** as required.

After implementation, prefer the §26 plan over full Gate 1–6.
Repeat Gate 1–6 **only** if authority or compositor success-path
exceptions are touched.

Suggested automated smokes: settings round-trip; path-join confinement
unit tests; copy-failure does not mark child failed; export filename
uniqueness; backup still rejects `F:\...` locators.

## 26. Required Narrow Acceptance Plan

1. Settings persist + restart/reload shows the same Delivery Root
   (and survives logout if moved to `app_settings`).
2. Tenant A render: internal `output/final_*` exists; delivery copy
   only under A’s tenant dir.
3. Tenant B render: no files under A’s tenant dir.
4. Tenant A approval ZIP lands under A `.../exports/`.
5. Tenant B ZIP does not overwrite A; status/download for B cannot
   fetch A’s zip via B’s header.
6. Unset Delivery Root: no external copy; internal output only;
   ZIP may remain internal `output/exports` **or** skip external copy
   with documented fallback — must not crash.
7. Traversal / `..` / raw header not used as path segment.
8. External drive unavailable: task **completed**, TaskHistory internal,
   warning only.
9. TaskHistory `file_path` still `output/final_...`.
10. Backup smoke enumerates internal authoritative output only.
11. One real AI Draft balanced render: completed + internal truth +
    tenant delivery copy of final (+ cover if in content set).
12. Reservation diagnostics endpoints still 200 / unchanged schema.

**Full manual Gate 1–6: NOT required** for this isolated Two-Root fix.

## 27. Findings

Supported by current source:

| ID | Result |
|---|---|
| **VAR3D2I-OUTPUT-RF-01** | **CONFIRMED.** UI persists; DSL render path not wired. |
| **VAR3D2I-OUTPUT-RF-02** | **CONFIRMED** for the compositor copy site: finals only. Cover/master/voice/sub not copied. DSL never reaches the site. |
| **VAR3D2I-OUTPUT-RF-03** | **NOT CONFIRMED.** Copy does not replace TaskHistory. |
| **VAR3D2I-OUTPUT-RF-04** | **CONFIRMED.** ZIP uses hardcoded `output/exports`. |
| **VAR3D2I-OUTPUT-RF-05** | **CONFIRMED.** Shared export directory; tenant used only for DB. |
| **VAR3D2I-OUTPUT-RF-06** | **NOT CONFIRMED.** `canonical_tenant_id` is on the worker context. |
| **VAR3D2I-OUTPUT-RF-07** | **CONFIRMED as unavailable.** No project identity; use `_default`. Not “unsafe existing id”. |
| **VAR3D2I-OUTPUT-RF-08** | **NOT CONFIRMED** for Option B. |
| **VAR3D2I-OUTPUT-RF-09** | **LATENT** on compositor copy-in-try. Not current DSL. V1.5 must not reuse that site. |
| **VAR3D2I-OUTPUT-RF-10** | **CONFIRMED.** `int(time.time())` zip names in a shared folder. |
| **VAR3D2I-OUTPUT-RF-11** | **NOT a current exploit** (setting unused). Future join must confine slug+root. |
| **VAR3D2I-OUTPUT-RF-12** | **CONFIRMED.** “统一落地目录” misrepresents storage authority. |
| **VAR3D2I-OUTPUT-RF-13** | **NOT CONFIRMED.** Two-Root need not touch authority layers. |
| **VAR3D2I-OUTPUT-RF-14** | **NOT CONFIRMED.** Full Gate 1–6 not required if authority untouched. |

## 28. Recommended V1.5 Boundary

```text
INTERNAL:  <project-root>/output/     ← TaskHistory, backup, L3, Reservation-unrelated files
DELIVERY:  <global-root>/tenants/<canonical>/projects/_default/
             renders/<date>/<task_id>/   ← final + cover copies
             exports/                    ← approval ZIPs
```

- Planning policy / canary / Reservation unchanged
- Unset root → internal only
- Copy/ZIP write failure → warn, keep completed
- No automatic ramp, no new project table, no backup rewrite

### A. CURRENT SETTINGS FLOW

```text
Settings UI “本地输出目录绑定”
  → Pinia + localStorage dopamatrix_output_dir
  → (stop)
  Workspace submit-dsl never reads it
  → render always uses output/
```

### B. CURRENT AUTHORITATIVE RENDER FLOW

```text
X-Local-User → canonical tenant → admit public task
  → render_batch_worker / render_worker
  → WorkflowContext (tenant_id, execution_id, file_sid)
  → TTS/sub/master/final/cover under output/
  → collected_assets.file_path = output/final_...
  → TaskHistory.output_assets
  → WS/UI preview those internal paths
```

### C. CURRENT EXPORT FLOW

```text
Approval hashes + X-Local-User
  → tenant DB VariantApproval.file_path (internal)
  → ZIP bytes
  → output/exports/dopamatrix_delivery_<epoch>.zip
  → GET /exports/<filename>  (global StaticFiles)
```

### D. RECOMMENDED NARROW V1.5 FLOW

```text
Global Delivery Root (app_settings)
  + canonical tenant
  + projects/_default
  → renders/<date>/<task_id>/   (copy final+cover, best-effort)
  → exports/                    (ZIP physical drop, tenant-safe name)
Internal output/ + TaskHistory unchanged
Download API remains filename-based, tenant-confined
```

## 29. Git Status

Before analysis:

```text
git branch --show-current
feature/var-001-variation-policy

git rev-parse HEAD
73982e4073455a8e542015c25cd9e20e397dd078

git status --short
(empty)
```

After this artifact only:

```text
git diff --check
(empty)

git status --short
?? doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_TARGETED_AUDIT.md
```

No other files modified. No commit. No push.

VAR001_V15_TENANT_DELIVERY_OUTPUT_NARROW_FIX_READY
