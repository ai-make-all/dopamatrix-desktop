# VAR-001 Phase 3D-2I-B-2B-2R-H1
# Runtime Paths & Bootstrap Provider Foundation Implementation Report

## 1. Executive Result

H1 is complete. The backend now chooses an explicit packaged/source/test runtime-root authority before dotenv, FastAPI, database, router, logger, Ngrok, or render-graph imports. Global settings SQLite, tenant SQLite, internal authoritative render output, and legacy ZIP fallback are rooted through that authority. A future `operator` invocation has a proven pre-application-graph seam and currently exits with a bounded H1 placeholder instead of starting Uvicorn.

The implementation does not add DPAPI, secure settings, a Seed profile/snapshot, operator commands, tenant registry, AUTH-001, packaged backup commands, or H5 dotenv/Ngrok/Tauri changes.

Final classification:

`VAR001_PHASE3D2IB2B2RH1_RUNTIME_PATHS_BOOTSTRAP_PASS`

## 2. Repository Baseline

| Fact | Value |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| Recovery HEAD | `beda79dc54f14ca307d8b80d7a2b5a8429c375e8` |
| Recovery commit | `beda79d docs(v1.5): freeze runtime configuration architecture` |
| RC1 tag target | `5f534b180dd2ae9fa9212e6632a44746669d7e6f` |
| Initial H1 state | intentionally dirty, uncommitted interrupted implementation |

No reset, restore, checkout, clean, stash, commit, push, build, service start, database migration, or installer operation was performed.

## 3. Interrupted-Run Recovery

The interrupted work was reviewed in place. Preserved files were `main.py`, `src/api/bootstrap.py`, `src/api/database.py`, `src/api/delivery_output.py`, `src/api/routes_matrix.py`, `src/api/runtime_config.py`, `src/api/runtime_paths.py`, `src/api/settings_router.py`, and `src/services/llm_provider.py`.

The recovery audit found no unrelated `.env`, SQLite, media, Delivery, backup, or build-artifact mutation. Valid partial work was edited forward. Corrections made during recovery were:

- completed internal output-root propagation through both render entry paths;
- removed the residual copied `SETTINGS_DB_PATH` compatibility alias;
- made unreadable packaged legacy state fail through the bounded migration-required error;
- used the `RuntimeMode` enum directly in bootstrap compatibility logic;
- isolated pre-existing Delivery and Ledger tests with the explicit test runtime root;
- preserved legacy direct-node forward-slash filename strings after a full-suite regression exposed Windows separator drift.

## 4. H1 Scope

Implemented only:

- pre-import bootstrap boundary;
- immutable/effectively immutable RuntimePaths authority;
- explicit global and tenant database paths;
- internal authoritative output-root conversion;
- a minimal two-lifecycle RuntimeConfigProvider foundation;
- focused and regression tests.

No H2-H6 implementation was pulled forward.

## 5. Bootstrap Refactor

`main.py` now performs:

```text
stdlib imports
-> bootstrap-safe import
-> runtime mode/root initialization
-> operator-prefix recognition
-> bounded operator placeholder exit OR packaged resource-CWD compatibility
-> temporary dotenv compatibility
-> RuntimeConfigProvider creation
-> normal FastAPI/application graph
-> Uvicorn only in __main__ server mode
```

`backend.exe operator ...` can terminate before `fastapi`, `uvicorn`, `src.api.database`, or `src.api.routes_dsl` is imported. The placeholder is deliberately not a real operator CLI and returns code `2` with `OPERATOR_COMMANDS_NOT_IMPLEMENTED_H1`.

## 6. Runtime Mode Contract

`RuntimeMode` is an enum with `PACKAGED`, `SOURCE_DEVELOPMENT`, and `TEST`. Frozen execution selects packaged mode; non-frozen execution selects source-development mode; tests must explicitly request `TEST`. Environment variables do not select the mode.

## 7. RuntimePaths Design

`RuntimePaths` is a frozen dataclass containing absolute normalized paths:

- `runtime_root`;
- `settings_db_path`;
- `tenant_data_dir`;
- `internal_output_root`.

Initialization is process-wide and idempotent only for the identical value. A conflicting second initialization raises `RUNTIME_PATHS_INITIALIZATION_CONFLICT`. Tests have an explicit scoped override that restores the previous authority; production code has no hot-reconfiguration call path.

## 8. Packaged Runtime Root

Packaged mode calls exactly:

```python
appdirs.user_data_dir("DopaMatrix", "DopaMatrixOrg")
```

The resulting absolute root owns `dopamatrix.db`, `data/`, and `output/`. Runtime directory creation/validation fails with `RUNTIME_ROOT_UNAVAILABLE`. No packaged mutable path falls back to inherited CWD.

`H1_PACKAGED_RUNTIME_ROOT_PROVEN = PASS`

## 9. Source Development Root

Source development resolves the repository root from `runtime_paths.py`, not the process CWD. This preserves the existing repository-local `dopamatrix.db`, `data/`, and `output/` contract while making it explicit.

`H1_SOURCE_DEV_ROOT_PRESERVED = PASS`

## 10. Test Runtime Root

Tests can install a scoped, absolute temporary runtime root. H1 focused and updated existing tests use temporary locations and do not select real LocalAppData, the developer settings DB, tenant DBs, internal output, or Delivery Root.

`H1_TEST_ROOT_ISOLATION_PROVEN = PASS`

## 11. Database Path Conversion

The global SQLAlchemy engine is constructed from `RuntimePaths.settings_db_path` using an absolute SQLite URL. Import no longer creates a CWD-relative `data/` directory. `settings_router`, Delivery settings, and the LLM key loader query the same runtime authority at use time; the copied `SETTINGS_DB_PATH` constant was removed.

`H1_SETTINGS_DB_EXPLICIT_PATH_PROVEN = PASS`

## 12. Tenant Database Path Conversion

`get_tenant_engine()` retains canonicalization, locking, cache behavior, application-schema initialization, foreign-key setup, and Fingerprint Ledger V2 initialization. Only physical path construction changed to:

```text
<RuntimePaths.tenant_data_dir>/dopamatrix_<canonical-tenant>.db
```

`H1_TENANT_DB_EXPLICIT_PATH_PROVEN = PASS`

## 13. Global Settings Consumers

The following consumers now use `get_runtime_paths().settings_db_path`:

- `src/api/settings_router.py`;
- `src/api/delivery_output.py`;
- `src/services/llm_provider.py`.

OpenAI credential storage remains the existing plaintext `app_settings` behavior in H1. Delivery Root remains a dynamic machine setting.

## 14. Internal Output Root Conversion

Both production render boundaries resolve one `RuntimePaths.internal_output_root`:

- `run_matrix_factory._run_single_matrix()` injects it into TTS, Pexels/clip output, Assembly, and `WorkflowContext`;
- `routes_dsl.render_worker()` injects it into TTS and `WorkflowContext`.

Compositor and Subtitle consume `context.config["internal_output_root"]`. Cover continues to derive its directory from the authoritative final-video path. Legacy direct node calls retain their relative defaults for compatibility; supported production worker paths always inject the explicit root.

`H1_INTERNAL_OUTPUT_EXPLICIT_PATH_PROVEN = PASS`

## 15. Import-Time Side Effect Removal

`routes_matrix` no longer defines or creates CWD-relative `output/exports` during import. The fallback export directory is created lazily only when export is requested, under `RuntimePaths.internal_output_root / "exports"`.

`H1_ROUTES_IMPORT_NO_OUTPUT_MUTATION_PROVEN = PASS`

## 16. Delivery Two-Root Preservation

Internal authoritative output and external operator Delivery remain separate:

```text
authoritative: RuntimePaths.internal_output_root
delivery: configured global Delivery Root
```

Delivery publication remains non-authoritative and dynamically reads its machine setting. H1 does not relocate or subordinate Delivery to LocalAppData.

`H1_DELIVERY_TWO_ROOT_PRESERVED = PASS`

## 17. Backup Compatibility

Backup/restore code and bundle format were not changed. Existing source CLI calls that explicitly supply a project root remain compatible. Its default `project_root="."` is a bounded deferred H4 packaged-operator integration; this report does not claim packaged backup support.

## 18. Legacy Runtime Detection

Packaged path resolution inspects only meaningful executable-adjacent mutable state:

- `dopamatrix.db`;
- `data/dopamatrix_*.db`, `*.db-wal`, or `*.db-shm`;
- a non-empty `output/`.

Empty data/output directories and bundled executables/resources do not trigger. Meaningful or unreadable legacy state raises `LEGACY_RUNTIME_MIGRATION_REQUIRED` before runtime-root creation. H1 never copies, merges, deletes, overwrites, or automatically migrates state.

`H1_LEGACY_RUNTIME_FAIL_CLOSED_PROVEN = PASS`

## 19. RuntimeConfigProvider Foundation

The provider freezes a defensive copy of the static operational mapping behind `MappingProxyType` and separately accepts a bounded dynamic machine-setting reader. The static mapping cannot hot-reload; the dynamic reader can reflect Delivery/OpenAI-style machine-setting changes. H1 defines lifecycle/interface only and does not parse or persist Seed state or secrets.

## 20. Dotenv Temporary Compatibility

Bootstrap/operator-prefix recognition happens before dotenv import/loading. Normal server mode still invokes the existing dotenv compatibility because Seed keys have not moved to the future applied snapshot. Frozen dotenv removal and Tauri resource removal remain H5.

`H1_DOTENV_COMPATIBILITY_NOT_PREMATURELY_REMOVED = PASS`

## 21. Reservation Semantic Preservation

Lease, Readiness, and Rollout source files were not modified. Focused tests proved the current environment behavior and the existing injected `Mapping[str, str]` seams remain available through the same validators/all-or-none contracts. Authority, HMAC assignment, breaker, readiness, terminal fencing, Ledger V2, and Task Identity regressions passed.

`H1_RESERVATION_SEMANTICS_UNCHANGED = PASS`

## 22. Tests Added / Updated

Added `tests/test_var001_runtime_paths_bootstrap.py` with 14 focused tests covering bootstrap ordering, server import, modes, appdirs, absolute roots, test isolation, initialization conflicts, global/tenant DB paths, output injection, routes import behavior, Delivery separation, legacy detection/non-mutation, provider lifecycles, and Reservation loader compatibility.

Updated:

- `tests/test_var001_tenant_delivery_output.py` to use the test runtime root and the new lazy export fallback;
- `tests/test_var001_fingerprint_ledger.py` to open tenant engines through the test runtime root rather than CWD mutation.

## 23. Regression Results

| Suite / command scope | Result |
|---|---:|
| H1 focused | 14/14 PASS |
| Tenant Delivery Output | 24/24 PASS |
| Fingerprint Ledger | 26/26 PASS |
| Fingerprint Ledger Phase3C | 24/24 PASS |
| Reservation Lease | 25/25 PASS |
| Reservation Readiness | 15/15 PASS |
| Reservation Rollout Control | 36/36 PASS |
| Reservation runtime/terminal/planner/public/diagnostics combined | 109/109 PASS |
| Clean Task Identity + lifecycle guard | 27/27 PASS |
| V1.5 Backup/Restore | 23/23 PASS, 1 POSIX-only skip |
| Matrix Export | 3/3 PASS |
| Planning policy + balanced coverage | 36/36 PASS |
| INV execution paths after compatibility correction | 16/16 PASS |
| Unittest regression (all unittest-compatible backend modules) | 549/549 PASS, 1 POSIX-only skip |
| Pytest approval service closure | 3/3 PASS |
| Full pytest repository view | 551 PASS, 1 skipped, 217 subtests PASS |
| H1 focused unittest re-run after pytest installation | 14/14 PASS |

The initial full `unittest discover` ran 550 entries and exposed three H1-caused Windows separator assertions plus one environment import error. The separator regression was corrected and its module plus focused suite were rerun successfully. The `test_approval_service` import error was unrelated to H1: that module is pytest-style and pytest was not installed in the repository virtual environment at the time. All unittest-compatible backend test modules were then run together and passed 549/549, with one POSIX-only skip. This unittest result is distinct from the later pytest-driven repository result below.

### Pytest Regression Closure

Pytest `9.1.1` was installed only into `venv_build` as verification tooling; no production or test dependency declaration was changed. `tests/test_approval_service.py` uses `pytest.fixture`, the built-in `tmp_path` fixture, and `pytest.raises`; it operates on an in-memory SQLite approval schema and temporary files, and does not use RuntimePaths, tenant engines, authoritative output, or bootstrap state.

The previously blocked module was actually collected and executed with pytest: `3 passed` (`0 failed`, `0 skipped`, `0 errors`). The complete `pytest tests -q` repository view then completed with `551 passed`, `1 skipped`, `217 subtests passed`, and no failures or errors. The only skip is the existing POSIX-only case; emitted warnings are deprecation/compatibility warnings and did not fail the run. Finally, `tests.test_var001_runtime_paths_bootstrap` was rerun with its intended unittest runner and passed `14/14`.

No H1 source correction was required by this closure. The unittest and pytest results are reported separately and are not combined into a synthetic total.

## 24. Remaining Relative-Path Audit

No production match remains for `sqlite:///./`, `SETTINGS_DB_PATH`, a hard-coded `db_path = "dopamatrix.db"`, or `os.getcwd()` runtime authority.

Remaining relative output/path text is classified as follows:

- TTS, AssetSelect/Pexels, Assembly, Subtitle, and Compositor defaults: direct-node/test compatibility; production factories inject the explicit root;
- compositor `context.config["output_dir"]`: pre-existing optional external legacy copy, not authoritative TaskHistory storage or the Delivery Root path;
- Cover fallback `"output"`: reached only when an input video path has no directory; production final-video paths are injected absolute paths;
- backup `project_root="."`: explicit source-CLI compatibility deferred to H4 packaged commands;
- relative asset-pool/resource lookup: immutable/source resource behavior, not mutable DB/output authority;
- one packaged `chdir`: temporary non-authoritative resource compatibility only; mutable database/output authority is absolute.

`H1_NO_CWD_RUNTIME_AUTHORITY_PROVEN = PASS`

## 25. Scope Check

No Reservation, Readiness, Rollout, breaker, HMAC, planner, Historical, Coverage, Task Identity, Ledger schema, Delivery authority, backup format, frontend, Rust/Tauri, build script, version, tag, `.env`, DPAPI, secure storage, profile, snapshot, tenant registry, or operator-command semantics were changed.

`H1_NO_SECRET_ARCHITECTURE_IMPLEMENTED_EARLY = PASS`

`H1_NO_SEED_PROFILE_IMPLEMENTED_EARLY = PASS`

## 26. Git Diff

Production changes are confined to bootstrap/runtime-path/provider foundation, DB/settings consumers, output propagation, and lazy matrix export fallback. Test changes are confined to H1 coverage and path isolation. This report is the only documentation artifact added by H1.

Final `git diff --check`: PASS (line-ending conversion notices are informational; no whitespace error).

## 27. Git Status

Expected uncommitted H1 delta:

```text
 M main.py
 M run_matrix_factory.py
 M src/api/database.py
 M src/api/delivery_output.py
 M src/api/routes_dsl.py
 M src/api/routes_matrix.py
 M src/api/settings_router.py
 M src/nodes/compositor.py
 M src/nodes/subtitle.py
 M src/services/llm_provider.py
 M tests/test_var001_fingerprint_ledger.py
 M tests/test_var001_tenant_delivery_output.py
?? doc/investigations/VAR001_PHASE3D2IB2B2RH1_RUNTIME_PATHS_BOOTSTRAP_IMPLEMENTATION.md
?? src/api/bootstrap.py
?? src/api/runtime_config.py
?? src/api/runtime_paths.py
?? tests/test_var001_runtime_paths_bootstrap.py
```

No commit or push was performed.

## 28. Deferred H2-H6 Work

- H2: DPAPI, `secure_settings`, OpenAI and optional integration credential migration;
- H3: versioned Seed policy, atomic applied snapshot, typed validator bridge;
- H4: real packaged operator commands, tenant provisioning, packaged backup/verify;
- H5: packaged NO-`.env`, Tauri `.env` removal, Ngrok/default network cleanup, remaining configuration consumers;
- H6: isolated clean build, installer/artifact security acceptance, checksum/manifest/handoff.

The legacy runtime detector deliberately blocks rather than performs migration; an explicit verified migration command remains deferred.

## 29. Final Classification

All H1 authority paths are explicit, the pre-import bootstrap seam is proven, relevant semantics regressions pass, and no H2-H6 authority was implemented early.

Proof markers:

- `H1_BOOTSTRAP_PREIMPORT_SEAM_PROVEN = PASS`
- `H1_PACKAGED_RUNTIME_ROOT_PROVEN = PASS`
- `H1_SOURCE_DEV_ROOT_PRESERVED = PASS`
- `H1_TEST_ROOT_ISOLATION_PROVEN = PASS`
- `H1_SETTINGS_DB_EXPLICIT_PATH_PROVEN = PASS`
- `H1_TENANT_DB_EXPLICIT_PATH_PROVEN = PASS`
- `H1_INTERNAL_OUTPUT_EXPLICIT_PATH_PROVEN = PASS`
- `H1_NO_CWD_RUNTIME_AUTHORITY_PROVEN = PASS`
- `H1_ROUTES_IMPORT_NO_OUTPUT_MUTATION_PROVEN = PASS`
- `H1_DELIVERY_TWO_ROOT_PRESERVED = PASS`
- `H1_LEGACY_RUNTIME_FAIL_CLOSED_PROVEN = PASS`
- `H1_RESERVATION_SEMANTICS_UNCHANGED = PASS`
- `H1_DOTENV_COMPATIBILITY_NOT_PREMATURELY_REMOVED = PASS`
- `H1_NO_SECRET_ARCHITECTURE_IMPLEMENTED_EARLY = PASS`
- `H1_NO_SEED_PROFILE_IMPLEMENTED_EARLY = PASS`

`VAR001_PHASE3D2IB2B2RH1_RUNTIME_PATHS_BOOTSTRAP_PASS`
