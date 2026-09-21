# VAR-001 Phase 3D-2I-B-2B-2R-H4-1B
# Same-Binary Packaged Console / Tauri Proof

## 1. Phase Identity

This report records the bounded H4-1B implementation and Windows packaged proof for the frozen single-entry contract:

- direct operator mode: `backend.exe operator ...`;
- normal desktop mode: the Tauri application launches the same backend bytes without an `operator` argument.

Result: `VAR001_PHASE3D2IB2B2RH41B_SAME_BINARY_PACKAGED_CONSOLE_TAURI_PROOF_PASS`.

This is a Codex implementation/proof result, not ChatGPT FINAL PASS. H4-2 remains unauthorized.

## 2. Governing Artifacts

The implementation followed:

- `.codex-local/handoffs.md`;
- `doc/investigations/VAR001_PHASE3D2IB2B2RH4R0_PACKAGED_OPERATOR_CLI_SOURCE_CONTRACT_AUDIT.md`;
- `doc/investigations/VAR001_PHASE3D2IB2B2RH4R0R2_OPERATOR_CLI_CONTRACT_DECISION_CLOSURE.md`;
- `doc/investigations/VAR001_PHASE3D2IB2B2RH41A_BOOTSTRAP_SAFE_OPERATOR_DISPATCHER_IMPLEMENTATION.md`;
- the ignored H4-1A final review bundle;
- the user-authorized H4-1B continuation allowing a bounded real Tauri launch with the accepted current ngrok startup behavior.

H0-H3, H4-R0/R1/R2, and H4-1A were not reopened.

## 3. Starting Repository Baseline

Before H4-1B edits:

| Fact | Value |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| HEAD | `22686979ba8d31fda90ce06636d218836f35ed22` |
| Local origin ref | `22686979ba8d31fda90ce06636d218836f35ed22` |
| Immutable RC1 target | `5f534b180dd2ae9fa9212e6632a44746669d7e6f` |
| Tracked worktree | clean |
| Git index | empty |

No fetch, pull, commit, push, reset, restore, stash, or clean was performed.

## 4. H4-1A Closed-State Reference

At the baseline, `main.py:21-34` already recognized `operator` before RuntimePaths initialization, dotenv, FastAPI, database, routers, logger, ngrok, or render imports. The operator module was imported lazily and returned through `SystemExit`. H4-1B did not modify this accepted dispatcher or its command semantics.

## 5. Pre-Change Source Findings

- Tracked `build_backend.py` invoked PyInstaller with `--onefile --windowed --name backend main.py`. A windowed PE could not establish direct shell stdout/stderr/wait behavior.
- `backend.spec` was not a HEAD blob and was not tracked (`git cat-file` exit 128; `git ls-files --error-unmatch` exit 1). `.gitignore:45` ignores `*.spec`; it remained generated secondary evidence, not build authority.
- `web_ui/src-tauri/tauri.conf.json` declared exactly `"externalBin": ["bin/backend"]`.
- `web_ui/src-tauri/src/lib.rs:81-95` called `.sidecar("backend").spawn()` with no arguments and retained the child while draining events.
- The locked `tauri-plugin-shell 2.3.5` implementation pipes stdin/stdout/stderr and on Windows calls `creation_flags(CREATE_NO_WINDOW)` (`src/process/mod.rs:19-20,167-173`).

## 6. Toolchain Inventory

| Tool | Authoritative observation |
|---|---|
| Python | 3.12.10, `E:\dopaworkspace\dopamatrix-desktop\venv_build\Scripts\python.exe` |
| PyInstaller | 6.21.0 |
| Rust | `rustc 1.97.1 (8bab26f4f 2026-07-14)` |
| Cargo | `cargo 1.97.1 (c980f4866 2026-06-30)` |
| Project-local Tauri CLI | 2.10.1 |

Two Tauri-build toolchain observations are intentionally retained:

1. **Preliminary, non-authoritative:** Node 22.14.0 / npm 10.9.2 from the incidental `360se6`/`secoresdk` bundled Node component. That successful build was preliminary only.
2. **Authoritative H4-1B build:** Node 22.23.1 / npm 10.9.8 from the user-managed WinGet OpenJS Node installation at `C:\Users\chenp\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.22_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v22.23.1-win-x64`.

The authoritative process-local PATH check resolved `node.exe`, `npm`, and `npm.cmd` from the WinGet directory first. The system/user PATH was not changed. No dependency install or update command was run.

## 7. Selected Same-Binary Technique and Alternatives

Selected technique:

- build one PyInstaller console-subsystem `backend.exe` so direct PowerShell/cmd invocations inherit terminal streams and yield an observable process exit code;
- continue launching those byte-identical backend bytes through `tauri-plugin-shell`, whose locked Windows implementation uses `CREATE_NO_WINDOW`, preserving a windowless normal sidecar experience.

Alternatives rejected:

- keeping `--windowed`: does not prove reliable direct terminal streams/wait;
- a second operator executable: expressly prohibited;
- custom `AttachConsole`/`AllocConsole` or Rust spawn redesign: unnecessary because the locked plugin already supplies the bounded normal-sidecar creation flag;
- H5 network/ngrok changes: outside H4-1B.

## 8. Exact Source and Test Changes

1. `build_backend.py`
   - added `get_pyinstaller_command()`;
   - changed the authoritative option from `--windowed` to `--console`;
   - retained one-file, one-name, one-entrypoint behavior.
2. `tests/test_var001_packaged_console_contract.py`
   - proves the authoritative command selects one console backend and no windowed mode;
   - proves Tauri still declares one external backend binary;
   - proves the Rust sidecar builder adds no `operator` argument.

No Rust or Tauri configuration source change was necessary.

## 9. Isolated Worktree and Safety Controls

All destructive-capable packaging and runtime proof occurred outside the primary worktree at:

`E:\dopaworkspace\h4-1b-staging-20260921T000000Z`

The detached worktree used baseline commit `22686979ba8d31fda90ce06636d218836f35ed22`. Only the candidate `build_backend.py` and focused test were overlaid, with hashes checked against the primary worktree. Existing project dependencies were reused; no package lock or dependency version changed.

The destructive `build_backend.py` orchestration was not executed. The isolated proof used its exact PyInstaller command directly, avoiding process-name killing, cache deletion, output clearing, or database reset. Tauri/Cargo/frontend outputs and all temporary runtime data remained in isolated staging.

## 10. Packaged Backend Build Command

Executed in the isolated root:

```powershell
E:\dopaworkspace\dopamatrix-desktop\venv_build\Scripts\python.exe -m PyInstaller --noconfirm --onefile --console --name backend main.py
```

The build completed successfully in approximately 90.6 seconds. No old packaged executable was used.

## 11. Packaged Backend Artifact

| Field | Value |
|---|---|
| Path | `E:\dopaworkspace\h4-1b-staging-20260921T000000Z\dist\backend.exe` |
| Bytes | 44,295,559 |
| SHA-256 | `EB374F623CF86F3E563F442F98E2518B7628CA124526AE95636B754BEA9ED04D` |
| PE format | PE32+ |
| PE subsystem | 3 (`WINDOWS_CUI`) |
| UTC file timestamp | `2026-09-21T07:49:45.2217771Z` |

The isolated generated spec recorded `console=True`; it is build output, not tracked authority.

## 12. Tauri Sidecar Artifact

Before the authoritative Tauri rebuild, the already CLI-tested bytes were copied to the required target-triple name and rehashed:

- input: `web_ui/src-tauri/bin/backend-x86_64-pc-windows-msvc.exe`;
- Tauri release-side copy: `web_ui/src-tauri/target/release/backend.exe`;
- each size: 44,295,559 bytes;
- each SHA-256: `EB374F623CF86F3E563F442F98E2518B7628CA124526AE95636B754BEA9ED04D`.

## 13. Same-Binary Byte Identity

```text
CLI_TESTED_BACKEND_SHA256
== TAURI_INPUT_BACKEND_SHA256
== TAURI_SIDECAR_BACKEND_SHA256
== EB374F623CF86F3E563F442F98E2518B7628CA124526AE95636B754BEA9ED04D
```

Result: PASS. The contract is established by bytes, not by common source or filename.

## 14. PowerShell Packaged Operator Cases

The real PyInstaller executable was invoked directly. Each case returned control only after process exit; `$LASTEXITCODE` was captured, no backend remained, and stdout/stderr were captured separately.

| Case | Command suffix | Exit | stdout | stderr |
|---|---|---:|---|---|
| PS-1 | `operator --help` | 0 | deterministic `Usage: backend.exe operator ...` help | empty |
| PS-2 | `operator` | 2 | empty | `OPERATOR_USAGE_REQUIRED: a namespace and command are required; use operator --help` |
| PS-3 | `operator --json --help` | 0 | exactly one valid JSON object, `schema_version=1`, `status=HELP` | empty |
| PS-4 | `operator --json unknown command` | 2 | exactly one JSON object with `OPERATOR_UNKNOWN_NAMESPACE` | empty |
| PS-5 | `operator config status` | 4 | empty | `OPERATOR_COMMAND_NOT_IMPLEMENTED: config status is registered but not implemented in H4-1A` |
| PS-6 | invalid argument case | 2 | empty | bounded stable usage error |

Two earlier PowerShell harness revisions mishandled empty stderr under strict PowerShell behavior. They were evidence-harness defects only; the executable was unchanged. The corrected v3 harness produced the results above.

## 15. cmd.exe Packaged Operator Cases

A temporary `.cmd` harness inside isolated evidence staging invoked the real executable and captured `%ERRORLEVEL%`.

| Case | Command suffix | Exit | stdout/stderr contract |
|---|---|---:|---|
| CMD-1 | `operator --help` | 0 | help on stdout, stderr empty |
| CMD-2 | `operator` | 2 | stdout empty, stable usage error on stderr |
| CMD-3 | `operator --json --help` | 0 | one JSON stdout object, stderr empty |
| CMD-4 | `operator --json unknown command` | 2 | one JSON stdout object, stderr empty |
| CMD-5 | `operator config status` | 4 | stdout empty, not-implemented error on stderr |
| CMD-6 | invalid argument case | 2 | stdout empty, bounded usage error on stderr |

All cases left no packaged backend process.

## 16. Packaged Zero-Runtime-Mutation Proof

For help, bare usage, JSON help, unknown command, registered placeholder, and invalid arguments:

- the isolated DopaMatrix runtime root was absent before execution and remained absent;
- DB/WAL/SHM count remained zero;
- no runtime log or internal-output directory appeared;
- PyInstaller extraction under isolated TEMP was treated separately from application runtime state.

Result: PASS.

## 17. Packaged No-Server-Graph Proof

For every packaged operator case:

- the process exited deterministically;
- no backend remained;
- no Uvicorn/FastAPI startup text appeared;
- no normal port-8000 listener appeared;
- no Tauri process participated;
- no runtime database appeared.

Result: the accepted H4-1A pre-import seam survives real packaging.

## 18. Authoritative Tauri Build and Launch

The preliminary successful Tauri build used incidental Node 22.14.0/npm 10.9.2 and is retained only as non-authoritative history.

The authoritative build prepended only the WinGet Node directory to that isolated process PATH, verified Node 22.23.1/npm 10.9.8, verified project-local `tauri-cli 2.10.1`, forced Cargo offline, and repeated the previously successful release/no-bundle procedure:

```powershell
npm run tauri -- build --no-bundle --ci
```

No `npm install`, update, audit fix, or `cargo update` ran. The build succeeded in approximately 157.1 seconds.

Authoritative Tauri executable:

- path: `E:\dopaworkspace\h4-1b-staging-20260921T000000Z\web_ui\src-tauri\target\release\app.exe`;
- bytes: 13,137,408;
- SHA-256: `B057BDA90755DA3598E96A94C54A0F9CBCCAF7DCC969E7620E5BCECA0D3DB665`;
- UTC timestamp: `2026-09-21T08:46:32.3150600Z`.

The real launch was equivalent to:

```powershell
Start-Process -FilePath 'E:\dopaworkspace\h4-1b-staging-20260921T000000Z\web_ui\src-tauri\target\release\app.exe' -PassThru
```

with LOCALAPPDATA, APPDATA, TEMP, and TMP redirected to fresh isolated staging directories. The first authorized launch probe attempted to hash the child before its path became observable and aborted; its `finally` cleanup closed the app and child. This was a probe-timing defect only. The corrected authoritative v2 probe produced the following sections.

## 19. Backend Child PID and Command Line

Authoritative launch evidence:

- Tauri GUI PID: `8452`;
- direct Tauri backend child PID: `7920`;
- PyInstaller worker PID: `13340`;
- direct child executable: `...\target\release\backend.exe`;
- direct child command line: `"\\?\E:\dopaworkspace\h4-1b-staging-20260921T000000Z\web_ui\src-tauri\target\release\backend.exe"`;
- worker command line: the same executable path, also without arguments.

The child file hash was the required `EB374F...04D` value.

## 20. No Operator Arguments

Both observed backend command lines contained no `operator` token and no H4 command. `AnyBackendHasOperatorToken` was `false`; exactly one backend process was the direct Tauri child. The process followed the normal sidecar/server path.

## 21. Normal Server Startup and Health

- backend processes remained alive during observation (`BackendAliveCount=2`, reflecting PyInstaller parent/worker behavior);
- PID 13340 listened on `127.0.0.1:8000`;
- health endpoint returned HTTP 200;
- bounded body: `{"status":"DopaMatrix Engine is running","version":"1.5.0-rc1","db":"connected"}`;
- no operator behavior was entered.

Current startup did not create a new ngrok process in this run. Establishing a public ngrok tunnel was explicitly permitted for this bounded proof but was not an acceptance requirement, and no tunnel URL or credential was recorded.

## 22. Machine-Auditable No-Visible-Console Proof

Win32 top-level-window enumeration after launch found only windows owned by Tauri PID 8452:

- visible `Tauri Window`, title `DopaMatrix Studio`;
- `Tao Thread Event Target`.

No top-level window was owned by backend PID 7920 or worker PID 13340. `BackendVisibleWindows=[]` and `NewConsoleWindows=[]`. This runtime result agrees with the locked plugin source applying Windows `CREATE_NO_WINDOW` while preserving piped streams.

Result: no visible backend console window.

## 23. Tauri / Backend Shutdown and Orphan Proof

The probe requested normal GUI closure with `CloseMainWindow()`.

| Check | Result |
|---|---|
| Close request accepted | true |
| Tauri app exited | true |
| Forced app termination | false |
| Backend exited after app close | true |
| Remaining backend count | 0 |
| Remaining app count | 0 |
| New ngrok processes | 0 |
| Remaining new ngrok processes | 0 |
| Port 8000 after shutdown | no listener |

No unrelated process was killed.

## 24. Focused Source Tests

Focused command:

```powershell
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_packaged_console_contract.py tests/test_var001_operator_cli.py tests/test_var001_runtime_paths_bootstrap.py tests/test_var001_v15_backup_restore.py::V15BackupRestoreTests::test_release_version_is_single_backend_authority_and_packaging_is_aligned -q
```

Result: 31 passed, 53 subtests passed, 0 failures/errors.

The H4-1B file itself collected 2 passing tests. No test was skipped or weakened.

## 25. Regression Results

- isolated `cargo check --locked` with Cargo offline: PASS;
- authoritative frontend/Tauri `build --no-bundle --ci`: PASS;
- full backend command `.\venv_build\Scripts\python.exe -m pytest tests -q`: **621 passed, 1 skipped, 290 subtests passed, 0 failures/errors, 120 warnings**, 152.59 seconds.

Warnings were retained separately from failures and did not change the pass result.

## 26. Primary Worktree Contamination Audit

No isolated build or runtime artifact was copied into the primary worktree. Primary ignored `build/`, `dist/`, `backend.spec`, `output/`, repository DB, Tauri target, sidecar, and `.env` had pre-H4-1B timestamps and were not modified by this proof. A recent-artifact scan found no forbidden primary-worktree creation.

At report creation, the only product/test changes were:

- `M build_backend.py`;
- `?? tests/test_var001_packaged_console_contract.py`;
- this new report.

The ignored review bundle does not appear in Git status.

## 27. Explicit Non-Goal Audit

- [x] no config/Seed/Assignment-Secret status implementation
- [x] no SQLite status/read service or schema work
- [x] no tenant provisioning or registry
- [x] no Seed/profile mutation
- [x] no backup create/verify implementation
- [x] no lock/CAS
- [x] no Assignment Secret rotation
- [x] no H5 `.env`, ngrok, CORS, or network cleanup
- [x] no H6 installer acceptance
- [x] no Login/UI cleanup
- [x] no second operator executable
- [x] no RC1 mutation
- [x] no dependency upgrade
- [x] no H4-2 implementation

## 28. Known Limitations

- This is a release/no-bundle Tauri proof, not MSI/NSIS installation acceptance.
- The current `.env` bundle resource and ngrok startup remain H5 debt; they were not changed.
- The isolated build staging is retained for independent evidence review. No process or listener remains active.
- Shell behavior was proved on this Windows machine and must be reviewed independently before the gate advances.

## 29. Final Git Evidence

Final commands were run from the primary worktree:

```text
branch: feature/var-001-variation-policy
HEAD: 22686979ba8d31fda90ce06636d218836f35ed22
origin/feature/var-001-variation-policy: 22686979ba8d31fda90ce06636d218836f35ed22
v1.5-phseed-rc1^{commit}: 5f534b180dd2ae9fa9212e6632a44746669d7e6f
index: empty
git diff --check: PASS
```

The exact final status/stat after both evidence documents are written is recorded in the ignored review bundle and final Codex return.

## 30. Final Classification and Safety Declarations

Proof markers:

- `H41B_ONE_BACKEND_BINARY_PRESERVED = PASS`
- `H41B_POWERSHELL_WAIT_STREAMS_EXIT_PROVEN = PASS`
- `H41B_CMD_WAIT_STREAMS_EXIT_PROVEN = PASS`
- `H41B_PACKAGED_OPERATOR_ZERO_RUNTIME_MUTATION = PASS`
- `H41B_PACKAGED_OPERATOR_NO_SERVER_GRAPH = PASS`
- `H41B_CLI_TAURI_BACKEND_BYTE_IDENTITY = PASS`
- `H41B_AUTHORITATIVE_WINGET_NODE_BUILD = PASS`
- `H41B_TAURI_NORMAL_SERVER_STARTUP = PASS`
- `H41B_TAURI_NO_OPERATOR_ARGUMENT = PASS`
- `H41B_NO_VISIBLE_BACKEND_CONSOLE = PASS`
- `H41B_TAURI_SHUTDOWN_NO_ORPHAN = PASS`
- `H41B_FULL_REGRESSION = PASS`
- `H41B_PRIMARY_WORKTREE_UNCONTAMINATED = PASS`
- `H41B_SCOPE_CONTROL = PASS`

Final Codex classification:

`VAR001_PHASE3D2IB2B2RH41B_SAME_BINARY_PACKAGED_CONSOLE_TAURI_PROOF_PASS`

```text
NO COMMIT PERFORMED
NO PUSH PERFORMED
H4_2_NOT_STARTED
INSTALLER_ACCEPTANCE_NOT_PERFORMED
```

H4-1B evidence is ready for independent ChatGPT review. Only ChatGPT may issue H4-1B FINAL PASS.
