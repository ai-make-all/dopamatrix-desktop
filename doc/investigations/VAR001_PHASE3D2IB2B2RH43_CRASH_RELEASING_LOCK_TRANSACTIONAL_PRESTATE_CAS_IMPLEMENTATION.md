# VAR-001 Phase 3D-2I-B-2B-2R-H4-3

# Crash-Releasing Lock + Transactional Pre-State/CAS Implementation

## 1. Phase Identity and Executive Result

H4-3 implements only the two foundations frozen by the H4-R0-R2 decision closure:

1. one OS-held, crash-releasing runtime mutation barrier; and
2. one caller-owned SQLite `BEGIN IMMEDIATE` checked-transaction foundation.

Implementation result: **PASS — ready for independent ChatGPT review**. This is not a ChatGPT FINAL PASS and does not authorize H4-4.

## 2. Governing Documents

The implementation followed:

- `AGENTS.md`;
- `.codex-local/handoffs.md`;
- `doc/investigations/VAR001_PHASE3D2IB2B2RH4R0R2_OPERATOR_CLI_CONTRACT_DECISION_CLOSURE.md`, especially Sections 13 and 14;
- `doc/investigations/VAR001_PHASE3D2IB2B2RH4R0_PACKAGED_OPERATOR_CLI_SOURCE_CONTRACT_AUDIT.md`;
- the H4-1A dispatcher, H4-1B same-binary packaging, and H4-2 strict-status implementation reports;
- the existing H1 RuntimePaths, H2 caller-owned secure-setting transaction, and H3 canonical snapshot source boundaries.

No closed architecture was redesigned.

## 3. Repository Baseline

| Item | Value |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| HEAD | `0f389c3d0c8b87ad48f33711c5c98b6b970ac08a` |
| Local origin ref | `0f389c3d0c8b87ad48f33711c5c98b6b970ac08a` |
| Immutable RC1 | `5f534b180dd2ae9fa9212e6632a44746669d7e6f` |
| Starting worktree | clean |
| Starting index | empty |

Only local refs were read; no fetch or pull occurred.

## 4. Pre-Change Source Audit

At the baseline:

- `main.py` performed H4-1A operator dispatch before `prepare_bootstrap()`. This was already the correct non-mutating operator/help/status boundary.
- Normal startup then called `prepare_bootstrap()`, which initializes RuntimePaths and creates the accepted runtime root/data directory before importing the application graph.
- After bootstrap, normal startup applied packaged CWD compatibility, loaded dotenv compatibility, installed the development runtime provider where applicable, and imported FastAPI, database, routers, rendering services, logger, and ngrok-related code.
- The lifespan performed global schema initialization, H2 migration/provider initialization, websocket cleanup, and ngrok startup/shutdown. There was no cross-process server/operator mutation lock.
- `src/api/runtime_paths.py` already provided an absolute immutable process path authority. H4-3 uses `RuntimePaths.runtime_root` and does not introduce CWD authority.
- H3 persisted the canonical operational snapshot in `app_settings`, provided pure canonical construction/parsing, and used caller-owned SQLite connections in its write transaction. No generic connection-bound pre-state/CAS helper existed.
- No snapshot revision/version/etag/CAS column existed and none was added.

The earliest accepted place for the server barrier was immediately after successful normal `prepare_bootstrap()` and before CWD compatibility, dotenv, provider, FastAPI, database, router, logger, or ngrok imports.

## 5. Selected Lock Design

`src/api/runtime_mutation.py` owns the complete H4-3 foundation. It contains no tenant, Seed, backup, secret-rotation, or operator command policy.

The lock authority is the currently held OS lock on byte 0. File existence, PID content, mtime, and deletion are never used as authority. The owning object retains its binary file handle for the full lock lifetime. Release unlocks and closes the handle but never deletes the file.

The open path is bounded and race-aware:

- require an existing runtime root directory;
- attempt exclusive create without truncation;
- fall back to read/write open when the file already exists;
- retry only the narrow create/open disappearance race;
- require a regular file;
- initialize exactly one byte only when the file is empty;
- never append on subsequent acquisitions.

## 6. Exact Lock Filename and Path

Constant:

```text
dopamatrix-runtime-mutation.lock
```

Authority path:

```text
RuntimePaths.runtime_root / "dopamatrix-runtime-mutation.lock"
```

The filename is not configurable, tenant-derived, command-derived, or exposed through CLI grammar.

Source-development RuntimePaths can resolve to the repository root, so `.gitignore` now contains the exact root-only rule:

```text
/dopamatrix-runtime-mutation.lock
```

No broad `*.lock` ignore was added.

## 7. Windows `msvcrt` Mechanics

On Windows, the module conditionally imports `msvcrt` and executes:

- `seek(0)`;
- `msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)` for acquisition;
- `seek(0)`;
- `msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)` for release.

Contention is non-blocking and maps only expected `EACCES`/`EAGAIN` equivalents to `RuntimeMutationBarrierBusy`. Open/stat/unexpected lock failures map to `RuntimeMutationBarrierError`; raw OS text is not exposed.

The Windows focused test uses a real independent Python process. It proved live contention, forced process termination without graceful unlock, preservation of the same lock file, and successful acquisition afterward. The test does not delete or replace the lock file to recover.

## 8. POSIX `flock` Adapter

On non-Windows platforms, the module conditionally imports `fcntl` and uses:

- `fcntl.flock(fd, LOCK_EX | LOCK_NB)`;
- `fcntl.flock(fd, LOCK_UN)`.

Windows does not import `fcntl`; POSIX does not import `msvcrt`. The Windows run includes source/dispatch assertions but does not claim real POSIX runtime execution.

## 9. Lock Exception and Error Model

Stable internal exceptions are:

- `RuntimeMutationBarrierBusy` → future operator/state category 4;
- `RuntimeMutationBarrierError` → subsystem category 8 at normal-server bootstrap;
- `MutationTransactionStateError`;
- `MutationTransactionError`;
- `MutationPrestateMismatch` → future command precondition/state category.

Second-server contention writes one stable bounded stderr line and exits 4 without a traceback. Unexpected barrier subsystem failure exits 8 with a separate stable line.

## 10. Server Lifecycle Wiring

The normal server now:

1. preserves the H4-1A early operator dispatch;
2. performs accepted normal RuntimePaths initialization;
3. imports only the bounded lock foundation;
4. acquires the server mutation barrier;
5. only then applies CWD/dotenv/provider compatibility and imports the application graph;
6. holds the same process-global barrier throughout application startup and server lifetime;
7. releases in the lifespan `finally`, direct-run `finally`, and an idempotent `atexit` safety hook.

The lifespan wrapper reacquires idempotently for the same path, then delegates to the unchanged application lifespan. A synthetic application-startup exception proved the wrapper releases and another acquisition succeeds.

For source-development reload, the launcher process releases immediately before `uvicorn.run("main:app", reload=True)`. The imported serving child executes normal module bootstrap and acquires the barrier itself. This avoids the reload supervisor holding the lock while blocking its serving child.

## 11. Second-Server Exit-4 Behavior

With an independent process holding the runtime barrier, executing `main.py` through an isolated normal-server bootstrap probe produced:

```text
RUNTIME_MUTATION_BARRIER_BUSY: another backend or mutation is active
```

and `SystemExit(4)`. The probe proved that FastAPI, database, routes, Uvicorn, and pyngrok were not imported. Therefore no Uvicorn runner, ngrok seam, database/schema initialization, provider mutation, or port startup was reached after contention.

## 12. Status and Backup Lock Exclusions

`src/api/operator_status.py`, `src/api/operator_cli.py`, and `src/api/backup_restore.py` do not import or acquire the H4-3 barrier.

While a barrier was actively held, direct H4-2 observations remained:

- `config status` → `NOT_INITIALIZED`, exit 0;
- `secret assignment status` → `ABSENT`, exit 0;
- missing-tenant `seed status` → the existing not-found category, not lock busy.

The CLOSED H4-2 WAL/SHM strategy is unchanged. `backup verify` remains a placeholder and architecturally lock-free. `backup create` also remains a placeholder and is not forced through this exclusive barrier; H4-5 retains its frozen online-backup concurrency design.

## 13. `BEGIN IMMEDIATE` Transaction API

The new API is:

```python
checked_immediate_transaction(
    connection,
    *,
    reread_prestate=<same-connection callback>,
    validate_prestate=<callback receiving same connection and reread state>,
)
```

It rejects a caller connection already in a transaction, executes `BEGIN IMMEDIATE`, rereads authoritative state only afterward, validates before yielding write authority, yields the same connection plus actual reread pre-state, commits once on success, and rolls back on validation or mutation failure.

It contains no business policy and does not open or close a SQLite connection.

## 14. Caller-Owned Connection Proof

Focused tests record Python object identity in the reread callback, validator, yielded transaction, and fixture write. All identities equal the caller-owned `sqlite3.Connection`. The caller connection remains usable after successful commit and after rollback.

Passing a connection already inside a caller transaction raises `MUTATION_TRANSACTION_ALREADY_ACTIVE`; the caller transaction remains active and is neither silently committed nor rolled back by H4-3.

## 15. Pre-State Reread and Validator Sequence

SQLite trace output in the focused test establishes the order:

```text
BEGIN IMMEDIATE;
SELECT ... authoritative pre-state ...;
UPDATE ... synthetic fixture write ...;
COMMIT
```

The validator runs after the SELECT returns and before the context yields, so future services cannot supply a pre-read value and skip the in-transaction reread.

## 16. Stale-State CAS Proof

Synthetic CAS scenario:

1. expected state `A` is captured;
2. another connection commits state `B`;
3. the checked transaction starts with `BEGIN IMMEDIATE`;
4. its callback rereads `B`;
5. validation expecting `A` raises `MutationPrestateMismatch`;
6. the business-write block is never reached;
7. rollback completes;
8. state `B` remains.

The H3-compatible proof repeats the same pattern with two valid canonical applied operational snapshots. It parses the authoritative snapshot from the same transaction using the existing H3 parser, rejects the stale expected canonical state, performs no business write, and preserves the newer canonical snapshot.

## 17. Rollback and Commit Proof

Focused tests prove:

- valid pre-state commits exactly once and persists the fixture write;
- validator rejection yields no write authority and rolls back;
- an exception after a fixture write rolls the write back;
- while the checked transaction is active, a second connection's bounded-timeout `BEGIN IMMEDIATE` fails busy;
- after the first transaction ends, the second writer succeeds;
- the caller connection remains open and usable in every path.

## 18. No Revision Column Proof

The fixture schema before and after a checked transaction is byte-for-byte equivalent at the `PRAGMA table_info` projection. No `revision`, `version`, `etag`, or `cas` column is added. No production schema or migration file changed.

## 19. Crash-Release Windows Process Proof

The authoritative Windows test sequence was:

1. create the stable one-byte file;
2. child process acquires the real `msvcrt` byte-range lock and reports `LOCKED`;
3. parent receives `RuntimeMutationBarrierBusy`;
4. parent forcibly terminates the child without graceful release;
5. the same file remains present with the same byte content;
6. parent acquires and releases it successfully.

This proves process/handle lifetime, not file metadata, controls authority.

## 20. Clean Release and Stale-File Proof

Normal child release allows a subsequent independent process to acquire without file deletion. A pre-existing unheld one-byte file also permits acquisition. Eight repeated acquire/release cycles leave exactly the same one-byte file and do not append or truncate.

## 21. Application Graph and Network Non-Start

The contention probe executes the actual early normal-server path with isolated RuntimePaths and an externally held lock. Module inventory after exit shows no FastAPI, database, routes, Uvicorn, or pyngrok import. No real server, service, network request, or port listener was started during H4-3 tests.

## 22. Complete Changed-File Inventory

| Path | Change | Purpose |
|---|---|---|
| `.gitignore` | modified | exact source-root runtime lock ignore |
| `main.py` | modified | pre-graph server barrier and lifecycle release |
| `src/api/runtime_mutation.py` | new | bounded lock and checked transaction foundation |
| `tests/test_var001_runtime_mutation_foundation.py` | new | H4-3 focused evidence |
| `tests/test_var001_runtime_paths_bootstrap.py` | modified | isolate normal-import runtime root from repository |
| this report | new | tracked implementation evidence |
| `.codex-local/review/VAR001_PHASE3D2IB2B2RH43_FINAL_SOURCE_REVIEW_BUNDLE.md` | ignored new | raw independent-review evidence |

No H3/policy helper change was needed.

## 23. Focused Test Results

Command:

```powershell
.\venv_build\Scripts\python.exe -m pytest tests\test_var001_runtime_mutation_foundation.py -q
```

Result: `18 passed, 10 subtests passed`.

The focused suite covers real Windows cross-process contention/crash release, stale-file behavior, file stability, server contention and startup failure, status exclusion, placeholder preservation, SQL ordering, same-connection identity, stale CAS, commit/rollback, second-writer contention, caller connection ownership, active-transaction rejection, no revision column, and canonical H3 stale-state rejection.

## 24. H4-1A / H4-1B / H4-2 Regressions

Command:

```powershell
.\venv_build\Scripts\python.exe -m pytest tests\test_var001_runtime_mutation_foundation.py tests\test_var001_operator_cli.py tests\test_var001_operator_status.py tests\test_var001_runtime_paths_bootstrap.py tests\test_var001_packaged_console_contract.py -q
```

Result: `68 passed, 87 subtests passed`. This run includes the final `18` H4-3 tests, including the application-lifespan startup-exception release proof.

## 25. H2 / H3 / Reservation / Tenant Regressions

Command:

```powershell
.\venv_build\Scripts\python.exe -m pytest tests\test_var001_dpapi_secret_store.py tests\test_var001_seed_applied_snapshot.py tests\test_var001_reservation_rollout_control.py tests\test_var001_reservation_rollout_readiness.py tests\test_var001_reservation_lease.py tests\test_var001_tenant_delivery_output.py -q
```

Result: `154 passed, 139 subtests passed`, with 19 existing dependency/deprecation warnings and zero failures/errors.

## 26. Full Pytest Result

Command:

```powershell
.\venv_build\Scripts\python.exe -m pytest tests -q
```

Result: `659 passed, 1 skipped, 324 subtests passed`, zero failures/errors, 120 warnings, in 166.52 seconds.

## 27. Static and Diff Checks

Command:

```powershell
.\venv_build\Scripts\python.exe -m py_compile main.py src\api\runtime_mutation.py tests\test_var001_runtime_mutation_foundation.py tests\test_var001_runtime_paths_bootstrap.py
git diff --check
```

Result: PASS. The primary worktree contains no runtime lock file, SQLite DB, WAL/SHM, log, network artifact, build artifact, or test artifact.

## 28. Forbidden-Scope Audit

PASS for every required boundary:

- no tenant provisioning, tenant registry, or H4-4 implementation;
- no SAFE_OFF/P3_W/activate/kill/BPS/P3_A business mutation;
- no backup create/verify implementation or restore;
- no Assignment Secret generation, rotation, export, or reveal;
- no revision/version/etag snapshot column;
- no PID-file/existence/mtime/delete-to-unlock authority;
- no blocking lock wait;
- no status or backup-verify lock acquisition;
- no app/network startup after contention;
- no HTTP/router/UI work;
- no H5 `.env`/ngrok/CORS cleanup;
- no H6/installer/Tauri/Rust/build-backend change;
- no packaged rebuild or dependency mutation;
- no `AGENTS.md` or tracked handoff change;
- no RC1/tag mutation;
- no commit and no push.

All future mutation and backup CLI commands remain `OPERATOR_COMMAND_NOT_IMPLEMENTED` placeholders.

## 29. Final Git Evidence and Classification

Final command outputs are reproduced in the ignored review bundle. The index is empty; HEAD/origin and RC1 remain unchanged. The final tracked delta is limited to the H4-3 source, focused/isolated test changes, exact ignore rule, and this report.

Classification:

```text
VAR001_PHASE3D2IB2B2RH43_CRASH_RELEASING_LOCK_TRANSACTIONAL_PRESTATE_CAS_PASS
```

Declarations:

```text
NO COMMIT PERFORMED
NO PUSH PERFORMED
H4_4_NOT_STARTED
NO_PACKAGED_REBUILD_PERFORMED
```

H4-3 evidence is ready for independent ChatGPT review. H4-4 must not begin unless ChatGPT issues H4-3 FINAL PASS and H4-3 subsequently receives post-push closure.
