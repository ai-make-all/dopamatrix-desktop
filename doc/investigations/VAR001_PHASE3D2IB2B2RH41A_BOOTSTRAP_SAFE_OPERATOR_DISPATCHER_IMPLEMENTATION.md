# VAR-001 Phase 3D-2I-B-2B-2R-H4-1A
# Bootstrap-Safe Operator Dispatcher Implementation

## 1. Phase / Task Identity

This report records the bounded H4-1A source implementation of the
bootstrap-safe operator dispatcher, frozen parser grammar, output contract,
and exit-code foundation.

This is not ChatGPT FINAL PASS. ChatGPT remains the independent gate, and
H4-1B is not authorized by this implementation result.

## 2. Governing Artifacts

- `.codex-local/handoffs.md`;
- `doc/investigations/VAR001_PHASE3D2IB2B2RH4R0_PACKAGED_OPERATOR_CLI_SOURCE_CONTRACT_AUDIT.md`;
- `doc/investigations/VAR001_PHASE3D2IB2B2RH4R0R2_OPERATOR_CLI_CONTRACT_DECISION_CLOSURE.md`;
- locally ignored R1 final-source review bundle.

H4-R0/R1/R2 decisions were consumed as authority and were not reopened.

## 3. Starting Git Anchors

| Fact | Starting value |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| HEAD | `c11134057b1750f46baf019b124e1b480c368ef4` |
| RC1 tag target | `5f534b180dd2ae9fa9212e6632a44746669d7e6f` |
| Tracked worktree | clean |
| Git index | empty |

Ignored `.codex-local` evidence was preserved.

## 4. Files Changed

Production:

- `main.py` — exact operator dispatch before normal RuntimePaths/application
  bootstrap;
- `src/api/bootstrap.py` — pure `is_operator_invocation()` decision;
- `src/api/operator_cli.py` — standard-library-only grammar, result, output,
  symbolic-error, and exit-code foundation.

Tests:

- `tests/test_var001_operator_cli.py` — H4-1A dispatcher/parser/output/
  zero-mutation coverage;
- `tests/test_var001_runtime_paths_bootstrap.py` — replace the H1 placeholder
  expectation with the real H4-1A help result while retaining the import proof.

Evidence:

- this implementation report;
- ignored `.codex-local/review/VAR001_PHASE3D2IB2B2RH41A_FINAL_SOURCE_REVIEW_BUNDLE.md`.

No other source, test, packaging, Tauri, runbook, or prior report was changed.

## 5. Implementation Summary

`main.py:21-34` now performs a pure argv check. `backend.exe operator ...`
lazily imports `src.api.operator_cli`, emits one deterministic result, and
exits. Only the no-operator path imports the remaining bootstrap helpers and
calls `prepare_bootstrap()`.

`src/api/operator_cli.py` imports only the standard library, registers exactly
the R2 command tree without operational handlers, centralizes exit categories
0 and 2-9, and validates the global `--json` position, namespaces, command
paths, option shapes, choices, duplicates, unknown options, and syntactic
integer input.

A syntactically valid command returns `OPERATOR_COMMAND_NOT_IMPLEMENTED` with
exit 4 because later H4 command semantics are intentionally absent.

## 6. Bootstrap Ordering Before / After

Before H4-1A:

```text
main.py -> prepare_bootstrap() -> initialize_runtime_paths()
        -> operator detection -> placeholder or application graph
```

After H4-1A:

```text
main.py -> is_operator_invocation()          # pure argv inspection
        -> operator: operator_cli -> parse/render -> SystemExit
        -> normal: prepare_bootstrap() -> initialize_runtime_paths()
                   -> existing application graph
```

The operator branch is before `initialize_runtime_paths()`, dotenv, FastAPI,
database, routers, Ngrok, logger, render imports, and Uvicorn. Normal startup
retains H1 RuntimePaths initialization, compatibility CWD, dotenv compatibility,
provider installation, and FastAPI construction.

## 7. Parser Grammar Implemented in H4-1A

```text
backend.exe operator [--json] <namespace> <command> [arguments]
```

Registered paths are `config status`; `tenant provision`; all frozen `seed`
paths; `secret assignment status/rotate`; and `backup create/verify`.
Options match R2. Prohibited aliases and generic commands are not registered.
`--json` is accepted only immediately after `operator`; a later occurrence is
rejected as `OPERATOR_INVALID_ARGUMENT`.

Top-level, namespace, nested `secret assignment`, and every registered command
support deterministic `--help`.

## 8. Global `--json` Behavior

Global JSON mode applies to success and failure. A misplaced `--json` remains
invalid grammar but selects JSON rendering for the bounded placement error.
This preserves one-object output for an explicit JSON request without accepting
the wrong position.

## 9. Human Output Contract

- success/help: stdout only;
- failure: stderr only;
- stable symbolic code prefixes each failure;
- no traceback, raw exception, runtime log, or secret-derived material.

## 10. JSON Output Contract

JSON rendering emits exactly one compact UTF-8 object plus one newline on
stdout and nothing on stderr. Its exact keys are:

```text
schema_version
command
status
error_code
data
```

`schema_version` is integer `1`; successful `error_code` is `null`. No banner,
log, traceback, or diagnostic surrounds the object.

## 11. Symbolic Error / Exit-Code Helper Design

`OperatorExitCode` centralizes the frozen mapping:

| Name | Exit |
|---|---:|
| SUCCESS | 0 |
| USAGE | 2 |
| VALIDATION | 3 |
| STATE | 4 |
| NOT_FOUND | 5 |
| INTEGRITY | 6 |
| PARTIAL_MUTATION | 7 |
| SUBSYSTEM | 8 |
| INTERNAL | 9 |

Stable H4-1A symbolic codes cover required usage, unknown namespace, missing
command, unknown command, invalid argument, and registered-but-not-implemented
outcomes. `OperatorResult`, `operator_success()`, `operator_failure()`, and
`emit_operator_result()` enforce rendering and exit selection centrally.

## 12. No Operational H4 Command Semantics

No registered command reads or writes operational state. Valid command syntax
stops at the H4-1A not-implemented result. No fake status, tenant, Seed,
secret, or backup outcome is returned.

## 13. Zero-Filesystem-Mutation Mechanism

- recognition is a tuple/argv check;
- `operator_cli` has no RuntimePaths, DB, logger, secret, policy, backup,
  FastAPI, or router import;
- `initialize_runtime_paths()` is reached only on the normal server branch;
- help/usage/unknown/invalid paths use immutable grammar data and supplied
  streams only.

The subprocess proof maps `appdirs.user_data_dir` to isolated
`<temp>/operator-must-not-create`, marks the process packaged, and patches
`initialize_runtime_paths()` to raise if reached. Before and after each path,
the target root is absent; no SQLite file exists; FastAPI, database, DSL router,
and Uvicorn are not imported.

## 14. Focused Tests Added

`tests/test_var001_operator_cli.py` covers pure recognition, normal selection,
main-entry early help, absent-before/absent-after roots, every accepted help
form, global JSON placement, one-object JSON, stream separation, stable
usage errors, all registered grammar paths, prohibited options, and exact exit
categories.

The existing H1 bootstrap test now asserts the help path while retaining its
application-graph import checks.

## 15. Exact Commands Executed

```text
.\venv_build\Scripts\python.exe -m py_compile main.py src/api/bootstrap.py src/api/operator_cli.py tests/test_var001_operator_cli.py tests/test_var001_runtime_paths_bootstrap.py

.\venv_build\Scripts\python.exe -m pytest tests/test_var001_operator_cli.py -q

.\venv_build\Scripts\python.exe -m pytest tests/test_var001_runtime_paths_bootstrap.py -q

.\venv_build\Scripts\python.exe -m pytest tests/test_var001_dpapi_secret_store.py tests/test_var001_seed_applied_snapshot.py tests/test_var001_reservation_rollout_control.py tests/test_var001_reservation_rollout_readiness.py tests/test_var001_reservation_lease.py -q

.\venv_build\Scripts\python.exe -m pytest tests -q

git diff --check
```

No packaged build or application/service start command was executed.

## 16. Exact Test Results

| Run | Passed | Skipped | Failed | Errors | Subtests |
|---|---:|---:|---:|---:|---:|
| H4-1A focused, final | 14 | 0 | 0 | 0 | 50 |
| H1 bootstrap/runtime paths | 14 | 0 | 0 | 0 | 3 |
| H2/H3 + Reservation affected group | 130 | 0 | 0 | 0 | 126 |
| Full `tests` regression | 619 | 1 | 0 | 0 | 290 |

Full regression completed in 146.82 seconds with 120 existing dependency/
route deprecation warnings and zero H4-1A failure.

## 17. Bounded Regression Results

H1 proves normal RuntimePaths/server import contracts remain intact. H2/H3 and
Reservation prove secret bootstrap, snapshot startup, lease, readiness, and
rollout behavior remain unchanged. Full regression had zero failures/errors.

## 18. Scope Proof

The H4-1A diff contains no config/seed/secret status implementation, SQLite
access, tenant provision, Seed/profile mutation, backup implementation,
lock/CAS, Assignment Secret generation/rotation, secret-derived output,
packaging console change, Tauri change, H5/H6 work, runbook synchronization,
H4-1B work, RC1 change, commit, or push.

## 19. Known Deferred Work

- H4-1B: same-binary Windows packaged console/Tauri proof;
- H4-2: strict non-mutating status;
- H4-3: mutation lock and transactional pre-state/CAS;
- H4-4 through H4-8: tenant, backup, Seed transitions, rotation, packaged
  smoke, and documentation synchronization in their frozen order.

## 20. Final Git Diff / Status Summary

Final evidence is captured in the ignored review bundle. Intended changes are
limited to three production/bootstrap files, two test files, this report, and
the ignored bundle. The Git index remains empty.

Final tracked diff stat:

```text
 main.py                                      | 21 ++++++++++++---------
 src/api/bootstrap.py                         | 20 +++++++++-----------
 tests/test_var001_runtime_paths_bootstrap.py |  7 ++++---
 3 files changed, 25 insertions(+), 23 deletions(-)
```

Final `git status --short`:

```text
 M main.py
 M src/api/bootstrap.py
 M tests/test_var001_runtime_paths_bootstrap.py
?? doc/investigations/VAR001_PHASE3D2IB2B2RH41A_BOOTSTRAP_SAFE_OPERATOR_DISPATCHER_IMPLEMENTATION.md
?? src/api/operator_cli.py
?? tests/test_var001_operator_cli.py
```

The ignored review bundle does not appear in Git status. `git diff --check`
passed and `git diff --cached --name-status` remained empty.

## 21. Implementation Conclusion

H4-1A is ready for independent ChatGPT review. This is a Codex implementation
conclusion, not ChatGPT FINAL PASS. H4-1B must not begin unless ChatGPT issues
H4-1A FINAL PASS.

```text
NO COMMIT PERFORMED
NO PUSH PERFORMED
```
