# VAR-001 H5-1 Packaged NO-.env Network Bootstrap Implementation

## 1. Executive Result

H5-1 implements the authorized source/config boundary only:

- packaged/frozen execution never imports, searches, loads, or deletes `.env`;
- source development retains `load_dotenv(override=False)`;
- Tauri no longer declares `.env` as a resource;
- packaged lifespan does not import or connect Ngrok and needs no Ngrok token;
- packaged matrix asset URLs ignore process `PUBLIC_BASE_URL` and use
  `http://127.0.0.1:8000`;
- operator early dispatch, local bind, H4 mutation barrier, RuntimePaths,
  profiles, DPAPI, operator grammar, and H4 behavior remain unchanged.

Implementation-owner classification:

```text
VAR001_PHASE3D2IB2B2RH51_PACKAGED_NO_ENV_NETWORK_BOOTSTRAP_PASS
```

Independent ChatGPT review remains the phase gate.

## 2. Repository Baseline

```text
branch=feature/var-001-variation-policy
HEAD=0612318a6a738ab8e51d4fdee225697f99872748
origin/feature/var-001-variation-policy=0612318a6a738ab8e51d4fdee225697f99872748
RC1=5f534b180dd2ae9fa9212e6632a44746669d7e6f
starting worktree=CLEAN
starting index=EMPTY
```

The governing authority gate supplied for this slice was:

```text
VAR001_PHASE3D2IB2B2RH5R0_NO_ENV_NETWORK_CONFIG_AUTHORITY_RECONNAISSANCE_PASS
```

No separately named H5-R0 artifact was present in the repository; the task's
frozen H5-1 boundary was treated as the reviewed authority decision.

## 3. Exact Source and Configuration Changes

### `src/utils/env_utils.py`

`load_env()` now checks the existing PyInstaller `sys.frozen` predicate before
importing `dotenv`. Frozen execution returns immediately. It performs no path
probe and makes no `.env`-derived environment mutation.

### `main.py`

- operator dispatch remains before RuntimePaths, dotenv adapter, FastAPI,
  database, routes, logger, and render imports;
- the old packaged lifespan `.env` deletion block was removed;
- the top-level `pyngrok` import was removed;
- Ngrok import/connect/disconnect is confined to the existing
  `RuntimeMode.SOURCE_DEVELOPMENT` branch;
- the development-only tunnel continues to set `PUBLIC_BASE_URL` solely as a
  source-development compatibility adapter.

### `src/api/services.py`

`_resolve_matrix_base_url()` provides the narrow authority split:

```text
PACKAGED/FROZEN -> http://127.0.0.1:8000
SOURCE_DEVELOPMENT -> PUBLIC_BASE_URL when explicitly supplied, otherwise local
```

`run_matrix_job()` now uses that helper. No DB/profile/config key was added.

### `web_ui/src-tauri/tauri.conf.json`

Removed `.env` from `bundle.resources`; retained:

```text
externalBin = ["bin/backend"]
resources = ["bin/ffmpeg.exe", "bin/ffprobe.exe"]
```

## 4. Packaged Dotenv Contract

The packaged/frozen branch:

- returns before `from dotenv import load_dotenv`;
- does not inspect executable-adjacent, CWD, or ancestor `.env` paths;
- does not modify `os.environ` from `.env`;
- does not delete an adjacent `.env`;
- does not use packaged compatibility CWD as dotenv authority.

The focused test places synthetic `.env` files adjacent to a fake executable
and in an ancestor, rejects any dotenv import or path search, and proves both
files and `os.environ` remain untouched.

## 5. Source-Development Dotenv Contract

Source development still calls:

```python
load_dotenv(override=False)
```

This is an explicit dev adapter and cannot overwrite already supplied process
environment values.

## 6. Ngrok Production Default-Off

Packaged lifespan does not import `pyngrok`, call `connect`, require a token,
write a tunnel URL, or run disconnect/kill. Source development retains the
existing optional tunnel behavior behind `RuntimeMode.SOURCE_DEVELOPMENT`.

No Ngrok setting, app-settings key, SecretStore key, operator command, or
dependency change was introduced.

## 7. PUBLIC_BASE_URL Legacy Cleanup

Packaged matrix URL construction ignores a synthetic process
`PUBLIC_BASE_URL` and deterministically resolves to:

```text
http://127.0.0.1:8000
```

Source development may still consume the explicit legacy override. Packaged
startup does not write the key. No DB/profile authority was created.

## 8. Preserved Bootstrap and Server Contracts

The existing order remains:

```text
operator recognition/dispatch
-> normal-server RuntimePaths initialization
-> server mutation barrier
-> compatibility CWD
-> packaged-no-op/dev dotenv adapter
-> normal application graph
```

Both server entry points retain `127.0.0.1:8000`. Health/version behavior and
barrier lifetime were not changed.

## 9. Tests Added

Created `tests/test_var001_h5_no_env_network_bootstrap.py` with direct coverage
for:

- frozen return before dotenv import/search;
- no `.env` environment mutation or deletion;
- development `override=False` behavior;
- packaged lifespan with forbidden dotenv/pyngrok imports;
- no packaged `PUBLIC_BASE_URL` write;
- packaged local matrix URL despite a legacy environment value;
- source-development URL override preservation;
- Tauri resource/externalBin contract;
- operator-before-bootstrap/application-graph ordering;
- unchanged local host/port source contract.

No existing H4 test was weakened or edited.

## 10. Focused Test Result

Command:

```text
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_h5_no_env_network_bootstrap.py tests/test_var001_runtime_paths_bootstrap.py tests/test_var001_runtime_mutation_foundation.py -q --basetemp <fresh-temp>
```

Result:

```text
37 passed, 1 warning, 3 subtests passed
failures=0
errors=0
exit=0
```

## 11. Relevant Regression Result

The exact authorized nine-module H4/H2/H3 regression set returned:

```text
175 passed, 2 warnings, 248 subtests passed
failures=0
errors=0
exit=0
```

## 12. Full Backend Regression

Command:

```text
.\venv_build\Scripts\python.exe -m pytest tests -q --basetemp <fresh-temp>
```

Result:

```text
768 passed, 2 skipped, 120 warnings, 580 subtests passed
failures=0
errors=0
exit=0
```

Warnings were pre-existing deprecation/SQLAlchemy warnings and did not change
test outcomes.

## 13. Static Validation

The changed Python modules and new test compile successfully. Python JSON
parsing proves:

```json
{"externalBin":["bin/backend"],"resources":["bin/ffmpeg.exe","bin/ffprobe.exe"]}
```

`git diff --check` returns exit `0`.

## 14. Changed-File Inventory

```text
M main.py
M src/api/services.py
M src/utils/env_utils.py
M web_ui/src-tauri/tauri.conf.json
A tests/test_var001_h5_no_env_network_bootstrap.py
A doc/investigations/VAR001_PHASE3D2IB2B2RH51_PACKAGED_NO_ENV_NETWORK_BOOTSTRAP_IMPLEMENTATION.md
```

The ignored final review bundle is under `.codex-local/review/`.

## 15. Scope Check

```text
NO H4 REOPEN
NO H5-2 ENV-READER CLEANUP
NO H5-3 PACKAGE BUILD
NO PYINSTALLER
NO CARGO/TAURI BUILD
NO TEMPORARY WINDOWS USER
NO H6
NO NEW CONFIG AUTHORITY
NO DEPENDENCY CHANGE
NO COMMIT
NO PUSH
```

## 16. Final Classification

```text
VAR001_PHASE3D2IB2B2RH51_PACKAGED_NO_ENV_NETWORK_BOOTSTRAP_PASS
H5_2_NOT_STARTED
H5_3_NOT_STARTED
H6_NOT_STARTED
```
