# VAR-001 Phase 3D-2I-B-2B-2R-H4-2
# Strict Non-Mutating Status Implementation

## 1. Phase Identity

H4-2 implements exactly three previously registered operator commands:

- `backend.exe operator [--json] config status`
- `backend.exe operator [--json] seed status --tenant ID`
- `backend.exe operator [--json] secret assignment status`

Codex result: `VAR001_PHASE3D2IB2B2RH42_STRICT_NON_MUTATING_STATUS_PASS`.

This is not ChatGPT FINAL PASS. H4-3 remains unauthorized.

## 2. Governing Documents

- repository-root `AGENTS.md`;
- `.codex-local/handoffs.md`;
- H4-R0 source/contract audit;
- H4-R0-R2 operator contract decision closure;
- H4-1A dispatcher/output implementation report;
- H4-1B same-binary packaged proof;
- existing H1 RuntimePaths, H2 SecretStore, H3 applied-snapshot source.

Closed phases were not reopened and Frozen Architecture was not redesigned.

## 3. Starting Baseline

| Fact | Value |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| HEAD | `7af64061f0b0d231daea7f34397bcba0cd733723` |
| Local origin ref | `7af64061f0b0d231daea7f34397bcba0cd733723` |
| Reviewed production anchor | `7e557057068aebcd8e2bad9a54e425e9e7799fb8` |
| RC1 | `5f534b180dd2ae9fa9212e6632a44746669d7e6f` |
| Worktree/index | clean / empty |

No fetch, pull, dependency mutation, build, commit, or push occurred.

## 4. Closed H4-1A / H4-1B References

H4-1A remains the parser, output envelope, and early-dispatch authority. H4-1B remains the same-binary packaged console/Tauri authority. H4-2 does not modify `main.py`, bootstrap behavior, `build_backend.py`, Rust, Tauri, or packaging configuration.

## 5. Pre-Change Source Audit

### RuntimePaths

`resolve_runtime_paths()` computes absolute source/packaged/test paths and performs no mkdir, migration, provider installation, or file creation. `initialize_runtime_paths()` prepares directories and was therefore prohibited. A new `get_initialized_runtime_paths()` observer returns the already-installed authority or `None` without initialization.

### Snapshot storage and validation

The H3 canonical snapshot is stored in global `app_settings` under `operational_runtime_snapshot_v1` as canonical JSON. `parse_applied_operational_snapshot()` validates schema/profile versions, exact fields, duplicate keys, timestamp, metadata, tenant/generation, all 32 effective values, exact Lease strings, stage compatibility, secret reference, and canonical serialization.

The existing `load_applied_runtime_config_provider()` is mutating-inappropriate for H4-2 because it uses `SecretStore` read helpers and constructs a provider. H4-2 instead reads the existing row read-only and invokes only the canonical parser.

### SecretStore

`SecretStore.get_status()` delegates to `get_secret()`, which opens SQLite read/write and calls `CREATE TABLE IF NOT EXISTS secure_settings`. H4-2 does not call either method. It checks `sqlite_master`, reads the fixed Assignment Secret row, and invokes only the accepted `_decrypt_row()` DPAPI verification boundary.

### Tenant path

`RuntimePaths.tenant_database_path()` is pure. `get_tenant_engine()` creates/initializes a tenant DB, application schema, and Ledger V2 and is never called. Input validation applies the frozen production regex, lowercase/raw-equals-canonical check, sequence `0001..9999`, and reserved vertical rule before deriving the path.

### Readiness/rollout helper purity

Reservation readiness/status calculation uses ORM tenant models and operational queries; rollout control also contains breaker mutation paths. These optional projections were not imported or forced into H4-2. Status is limited to canonical persisted snapshot state.

### Import-time database boundary

The H3 validation import chain reaches `database.py`. Its module-level path binding previously called initializing `get_runtime_paths()`. It now uses an already-installed authority when present and otherwise pure `resolve_runtime_paths()`. The request type imports `starlette.requests.Request`, preserving FastAPI dependency injection without importing FastAPI on status-only execution. Engine construction remains connection-free; status never uses that engine.

## 6. Selected Minimal Design

`operator_cli` retains grammar/validation/output authority and lazily imports `operator_status` only after a valid invocation matches one of the three H4-2 paths. The new service:

1. resolves paths without initializing them;
2. checks file existence before connection;
3. opens only existing SQLite files through `file:...?mode=ro`, `uri=True`;
4. applies connection-local `PRAGMA query_only=ON`;
5. queries `sqlite_master` before optional table access;
6. performs canonical H3 validation and bounded DPAPI verification;
7. returns a bounded status outcome consumed by the unchanged H4-1A renderer.

All later command paths still return `OPERATOR_COMMAND_NOT_IMPLEMENTED`, exit 4.

## 7. Changed-File Inventory

- `src/api/operator_status.py` — new narrow read-only service;
- `src/api/operator_cli.py` — lazy dispatch for exactly three status paths;
- `src/api/runtime_paths.py` — non-initializing installed-authority observer;
- `src/api/database.py` — pure import-time path selection and Starlette request type;
- `tests/test_var001_operator_status.py` — focused H4-2 matrix;
- `tests/test_var001_operator_cli.py` — updates the superseded all-placeholder assertion while retaining all later placeholders;
- this report;
- ignored final review bundle.

## 8. Exact Grammar Preserved

No option was added or removed. Global `--json` remains immediately after `operator`. `config status` and Assignment Secret status accept no command options. Seed status requires exactly `--tenant ID`. Existing help and usage behavior is unchanged.

## 9. Config Status Projection

| State | Exit | Status |
|---|---:|---|
| Global DB absent | 0 | `NOT_INITIALIZED` |
| Existing DB, missing `app_settings`/row | 0 | `SAFE_OFF_MISSING` |
| Canonical verified snapshot | 0 | `ACTIVE` |
| Invalid snapshot | 6 | `ERROR` / `OPERATOR_SNAPSHOT_INTEGRITY_FAILED` |
| Corrupt DB | 6 | `ERROR` / `OPERATOR_STATUS_INTEGRITY_FAILED` |
| Storage/platform failure | 8 | `ERROR` / `OPERATOR_STATUS_SUBSYSTEM_FAILED` |

Bounded success fields include application version, runtime mode/root state, DB presence, H3 profile/stage/tenant/generation, BPS, kill, Lease profile, rollback window, and Assignment Secret status enum. No absolute DB path or machine inventory is emitted.

## 10. Seed Status Projection

Tenant validation failure maps to exit 3. A missing tenant DB maps to exit 5 without creating `data/` or a DB. Existing tenant DBs are opened read-only and receive `PRAGMA quick_check(1)`. Missing global snapshot maps to `SAFE_OFF_MISSING`. A valid matching canonical snapshot maps to `ACTIVE`. Invalid snapshot/database state maps to exit 6/8. Readiness/breaker summaries are intentionally omitted because their existing ORM path is not the narrow pure source required here.

## 11. Assignment Secret Status Projection

No DB, no `secure_settings` table, or no fixed row returns exit 0 / `ABSENT`. An existing decryptable, nonempty fixed row returns exit 0 / `PRESENT`. DPAPI/scheme/ciphertext verification failure returns exit 8 / `OPERATOR_ASSIGNMENT_SECRET_VERIFICATION_FAILED`. Output never contains plaintext, ciphertext, length, hash, prefix, suffix, entropy, or secret-derived material.

## 12. Exit / Status / Error Mapping

| Symbolic code | Exit | Meaning |
|---|---:|---|
| success (`error_code=null`) | 0 | valid observation, including missing/absent |
| `OPERATOR_TENANT_INVALID` | 3 | noncanonical production tenant identity |
| `OPERATOR_TENANT_NOT_FOUND` | 5 | requested canonical tenant DB absent |
| `OPERATOR_SNAPSHOT_INTEGRITY_FAILED` | 6 | applied snapshot is malformed/noncanonical/policy-invalid |
| `OPERATOR_STATUS_INTEGRITY_FAILED` | 6 | SQLite/tenant integrity failure |
| `OPERATOR_STATUS_SUBSYSTEM_FAILED` | 8 | filesystem/SQLite/platform inspection failure |
| `OPERATOR_ASSIGNMENT_SECRET_VERIFICATION_FAILED` | 8 | existing secret row cannot be safely verified |
| `OPERATOR_STATUS_INTERNAL_FAILED` | 9 | bounded unexpected failure |

Raw exceptions and tracebacks are never rendered.

## 13. SQLite Read-Only Implementation

`_readonly_sqlite()` requires an existing strict absolute path and builds `Path.as_uri() + "?mode=ro"`. It calls `sqlite3.connect(..., uri=True)` and `PRAGMA query_only=ON`, closes deterministically, and never uses an in-memory copy. Missing files are handled before connect. Tenant and global status paths do not execute DDL or DML.

## 14. sqlite_master Before Optional Tables

`_table_exists()` queries only:

```sql
SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;
```

Only after that succeeds does the service query `app_settings` or `secure_settings`. Trace-based focused coverage proved no optional-table query was issued when tables were absent.

## 15. Zero-Runtime-Mutation Architecture

The status module contains no mkdir, write/create-mode open, schema bootstrap, DDL, DML, provider install, tenant engine, profile apply, secret migration/generation, logging setup, lock, CAS, or transaction mutation. Existing DB proof recorded unchanged SHA-256, size, `sqlite_master`, and zero sidecars. Fresh root proof recorded before/after inventory count 0 and the runtime root remained nonexistent.

## 16. Secret Redaction Architecture

The service only turns successful verification into enum `PRESENT`. All `SecretStoreError` cases become one stable public error. Tests injected synthetic plaintext, ciphertext marker, digest, and DPAPI/DB internals and asserted none appeared in human output, JSON, stderr, result repr, or traceback.

## 17. Application-Graph / Import Boundary

The H4-1A early branch remains unchanged. Status imports are lazy. A subprocess patched `initialize_runtime_paths()` to fail if reached and ran real `main.py operator config status`; result was exit 0 while:

- runtime root remained absent;
- RuntimePaths remained uninitialized;
- FastAPI, Uvicorn, ngrok, and router modules were absent from `sys.modules`.

## 18. Focused Test Matrix and Result

Command:

```powershell
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_operator_status.py -q
```

Final result: **16 passed, 27 subtests passed, 0 failures/errors**.

Coverage includes fresh root, existing root/no DB, empty DB, table/row absence, read-only URI and query order, canonical snapshot, malformed/policy-invalid snapshot, corrupt SQLite, secret absence/presence/DPAPI failure, tenant validation/not-found, existing tenant, seed missing/valid/invalid, human/JSON streams, redaction, application-graph boundary, and all later placeholders.

An initial run reported nine Windows teardown failures because test fixture connections used SQLite transaction context managers without closing the file handles. Fixture connections were corrected to use `closing()`; no product behavior or assertion was weakened.

## 19. Zero-Mutation Before / After Evidence

Fresh isolated root:

```text
config status: exit 0, NOT_INITIALIZED
secret assignment status: exit 0, ABSENT
seed status existing syntax/missing DB: exit 5, OPERATOR_TENANT_NOT_FOUND
runtime root exists after: false
before files: 0
after files: 0
```

Canonical snapshot fixture:

```text
before SHA-256 = b8a3dbf17358763756059173c868647362f927b1b53cc887343e75951ffe113a
after  SHA-256 = b8a3dbf17358763756059173c868647362f927b1b53cc887343e75951ffe113a
before/after bytes = 20480
before/after sqlite_master = identical
WAL/SHM/journal after = none
```

## 20. Relevant Regressions

H4-1A/H1/H4-1B command:

```powershell
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_operator_cli.py tests/test_var001_runtime_paths_bootstrap.py tests/test_var001_packaged_console_contract.py -q
```

Result: **30 passed, 50 subtests passed**.

H2/H3/Reservation/tenant command:

```powershell
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_dpapi_secret_store.py tests/test_var001_seed_applied_snapshot.py tests/test_var001_reservation_rollout_control.py tests/test_var001_reservation_rollout_readiness.py tests/test_var001_reservation_lease.py tests/test_var001_tenant_delivery_output.py -q
```

Result: **154 passed, 139 subtests passed, 19 warnings**.

The first targeted run exposed a real request-annotation regression from a type-check-only FastAPI import. The final implementation uses `starlette.requests.Request`, preserving route injection without importing FastAPI on the status path. The same regression group then passed.

## 21. Full Regression

```powershell
.\venv_build\Scripts\python.exe -m pytest tests -q
```

Result: **637 passed, 1 skipped, 314 subtests passed, 0 failures/errors, 120 warnings**, 151.01 seconds.

`py_compile` passed for all changed/new Python modules. `git diff --check` passed.

## 22. Forbidden-Scope Audit

- no tenant provisioning or tenant schema initialization;
- no Seed/profile/SAFE_OFF write;
- no backup command implementation;
- no runtime mutation lock, CAS, or `BEGIN IMMEDIATE`;
- no Assignment Secret generation/rotation/export/reveal;
- no HTTP/router/UI exposure;
- no Rust/Tauri/build configuration change or packaged rebuild;
- no H5 environment/ngrok/CORS/network work;
- no H6 installer work;
- no second executable, dependency change, AGENTS/handoff change, or RC1 mutation;
- no H4-3 implementation.

## 23. Final Git Evidence

The exact final `git diff --stat`, `git status --short`, `git diff --check`, empty index, and ignored-bundle proof are captured in the final review bundle and Codex return. Only the H4-2 source/test/report set is present.

## 24. Final Classification and Declarations

Proof markers:

- `H42_EXACTLY_THREE_STATUS_COMMANDS_IMPLEMENTED = PASS`
- `H42_LATER_COMMAND_PLACEHOLDERS_PRESERVED = PASS`
- `H42_RUNTIME_PATH_RESOLUTION_NO_WRITE = PASS`
- `H42_SQLITE_MODE_RO = PASS`
- `H42_SQLITE_MASTER_BEFORE_OPTIONAL_TABLE = PASS`
- `H42_FRESH_INSTALL_ZERO_MUTATION = PASS`
- `H42_EXISTING_DB_CONTENT_UNCHANGED = PASS`
- `H42_TENANT_NOT_LAZY_PROVISIONED = PASS`
- `H42_CANONICAL_SNAPSHOT_VALIDATION = PASS`
- `H42_CORRUPTION_NOT_DISGUISED_AS_ABSENCE = PASS`
- `H42_ASSIGNMENT_SECRET_REDACTION = PASS`
- `H42_APPLICATION_GRAPH_NOT_STARTED = PASS`
- `H42_FULL_REGRESSION = PASS`
- `H42_SCOPE_CONTROL = PASS`

`VAR001_PHASE3D2IB2B2RH42_STRICT_NON_MUTATING_STATUS_PASS`

```text
NO COMMIT PERFORMED
NO PUSH PERFORMED
H4_3_NOT_STARTED
NO_PACKAGED_REBUILD_PERFORMED
```

H4-2 evidence is ready for independent ChatGPT review.

### Final command evidence

```text
branch = feature/var-001-variation-policy
HEAD = 7af64061f0b0d231daea7f34397bcba0cd733723
origin/feature/var-001-variation-policy = 7af64061f0b0d231daea7f34397bcba0cd733723
v1.5-phseed-rc1^{commit} = 5f534b180dd2ae9fa9212e6632a44746669d7e6f

git diff --check:
<no output>
exit = 0

git diff --stat:
 src/api/database.py               | 12 +++++++++---
 src/api/operator_cli.py           | 35 +++++++++++++++++++++++++++++++++++
 src/api/runtime_paths.py          |  6 ++++++
 tests/test_var001_operator_cli.py | 11 ++++-------
 4 files changed, 54 insertions(+), 10 deletions(-)

git status --short:
 M src/api/database.py
 M src/api/operator_cli.py
 M src/api/runtime_paths.py
 M tests/test_var001_operator_cli.py
?? doc/investigations/VAR001_PHASE3D2IB2B2RH42_STRICT_NON_MUTATING_STATUS_IMPLEMENTATION.md
?? src/api/operator_status.py
?? tests/test_var001_operator_status.py

git diff --cached --name-status:
<no output>

git check-ignore:
.git/info/exclude:7:/.codex-local/ .codex-local/review/VAR001_PHASE3D2IB2B2RH42_FINAL_SOURCE_REVIEW_BUNDLE.md
```

## H4-2-R1 WAL-Mode Zero-Mutation Fixup

### Independent-review blocking finding

Independent ChatGPT review correctly found that SQLite URI `mode=ro` plus
`PRAGMA query_only=ON` did not prove filesystem non-mutation for databases
whose persistent journal mode is WAL. The original focused fixtures used ordinary
rollback-journal databases and therefore did not cover SQLite's WAL/SHM behavior.

### Windows reproduction before the fix

The current pre-fix status path was exercised against isolated temporary SQLite
databases on this Windows development machine before product source was changed.
The fixture explicitly executed `PRAGMA journal_mode=WAL`, committed data, and
closed or retained the writer according to the case.

1. A clean WAL-mode main database had no sidecars before status. The original
   `mode=ro` status open created an empty `-wal` and a 32 KiB `-shm`.
   Main SHA-256 remained
   `c0ed729199e25573ee446b0ad30931a25e2388b258955cd7add54e0a8e653b5d`;
   the new SHM SHA-256 was
   `fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb`.
2. With an active WAL and SHM, the original path returned the committed WAL row,
   but changed the SHM SHA-256 from
   `fc3b5cdc1475d4871b75b975dedbbd48a29f678aa83e404155195c53132b47fa`
   to
   `67641fc98f63d9b102d331b52a99f3f615fe0e86e9da58176c0d4a9c25014442`.
3. With WAL present and SHM absent, the original path recreated a 32 KiB SHM
   whose SHA-256 was
   `068f0f9c554ce78c8f2e172af15677378d710352987dd119303203f5eb6e62bf`.

Four final-contract WAL tests were added before the source fix. All four failed
against the old implementation, proving the defect rather than merely asserting
the new implementation.

### Selected WAL-safe observation strategy

The narrow status reader now classifies the main database and all three relevant
sidecars before connecting:

- main DB present and no `-wal`, `-shm`, or `-journal`: open with
  `mode=ro&immutable=1`, retain `query_only=ON`, then re-observe the main
  file identity/size/mtime and sidecar absence after close;
- WAL and SHM both present: fail closed with
  `OPERATOR_STATUS_SUBSYSTEM_FAILED` / exit 8 without opening SQLite;
- only one WAL sidecar, or a rollback journal is present: fail closed with
  `OPERATOR_STATUS_INTEGRITY_FAILED` / exit 6 without opening SQLite;
- any main-file or sidecar change racing the observation: discard the projection
  and fail with the bounded subsystem error.

Status does not execute `PRAGMA journal_mode`, `wal_checkpoint`,
`VACUUM`, repair, deletion, checkpoint, or sidecar creation. H4-3 locking/CAS
was not introduced.

### Current-state visibility and no-sidecar proof

The post-fix Windows proof used a clean WAL-mode global DB with a canonical
snapshot and secret plus a clean WAL-mode tenant DB. Both writers were fully
closed, both main headers retained WAL read/write versions `(2, 2)`, and no
sidecars existed. Results were `config ACTIVE`, `secret PRESENT`, and
`seed ACTIVE`. Before and after main hashes/sizes were identical:

- global: 20480 bytes,
  `6f8995ef911ead2e6c70761f18fda2fef36d98ca6e1908a7f1e053d2dfa69cd6`;
- tenant: 8192 bytes,
  `86ea3119430e13bf36c3ea2fac7d5b89ca426a966e8d5223493ac7534b4ead32`.

No WAL, SHM, or journal existed before or after.

For an active WAL+SHM fixture, an explicit immutable probe could not see the
committed snapshot row, proving that blindly applying immutable mode would be
stale. H4-2 instead returned exit 8 without opening the DB. Main/WAL/SHM hashes
and sizes were identical before and after. For a copied WAL-without-SHM fixture,
H4-2 returned exit 6 and did not create SHM; all artifact hashes/sizes remained
identical. Thus H4-2 either reports the complete sidecar-free committed state or
fails closed rather than returning a stale projection.

### WAL tests and superseding regression results

New direct tests cover:

- clean WAL global DB through config and secret status;
- clean WAL canonical global snapshot and WAL tenant DB through config/seed;
- active WAL+SHM current-state/stale-immutable proof with unchanged artifacts;
- incomplete WAL-without-SHM bounded integrity failure and no repair.

```text
WAL red proof before source fix:
4 failed

Focused H4-2 after fix:
20 passed, 27 subtests passed in 6.19s

H4-1A / H4-1B / H1:
30 passed, 50 subtests passed in 14.26s

H2 / H3 / Reservation / tenant:
154 passed, 139 subtests passed, 19 warnings in 56.12s

Full backend:
641 passed, 1 skipped, 314 subtests passed, 120 warnings in 150.59s
0 failures, 0 errors

py_compile: PASS
git diff --check: PASS
```

These results supersede the earlier pre-R1 H4-2 test counts in this report.
The accepted command grammar, output envelope, exit taxonomy, redaction,
snapshot validation, early dispatch, packaging contract, and journal-mode policy
remain unchanged.
