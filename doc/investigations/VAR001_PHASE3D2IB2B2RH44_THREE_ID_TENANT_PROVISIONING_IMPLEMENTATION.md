# VAR-001 Phase 3D-2I-B-2B-2R-H4-4 — Three-ID-Only Tenant Provisioning Implementation

## 1. Phase Identity and Executive Result

H4-4 implements exactly `backend.exe operator [--json] tenant provision --tenant ID --approval-ref REF`. The source implementation, focused tests, relevant regressions, and full backend regression pass. This is Codex implementation evidence for independent ChatGPT review, not a FINAL PASS.

## 2. Governing Documents

Authority used: root `AGENTS.md`, `.codex-local/handoffs.md`, H4-R2 operator contract decision closure, tenant identity constitution, H4-3 lock/CAS implementation evidence, Release Field Boundary, Seed Execution Pack, and the accepted backup namespace decision `VAR001_PHASE3D2IB2B2RH44_BACKUP_NAMESPACE_AUTHORITY_DECISION_PASS`. The compact decision record is `VAR001_PHASE3D2IB2B2RH44R0_BACKUP_NAMESPACE_AUTHORITY_DECISION_CLOSURE.md`.

## 3. Repository Baseline

- Branch: `feature/var-001-variation-policy`
- HEAD/origin: `35b1fc8406891623126ec4080e5be13057bb9687`
- Immutable RC1: `5f534b180dd2ae9fa9212e6632a44746669d7e6f`
- Initial worktree/index: clean/empty

## 4. Pre-Change Source Audit

- `database.canonical_tenant_id()` is a filename sanitizer and was not accepted as the production identity constitution.
- `get_tenant_engine()` resolves `RuntimePaths.tenant_database_path()`, creates one cached Engine, enables tenant FK connections, initializes the application schema, and initializes Fingerprint Ledger V2.
- `initialize_application_schema()` creates current ORM tables, rollout metadata columns/indexes, and verifies task identity/rollout contracts.
- `RuntimePaths.tenant_database_path()` maps to `data/dopamatrix_<canonical-id>.db`.
- Delivery authority is existing `app_settings.delivery_root`; `derive_tenant_delivery_root()` establishes the accepted tenant layout.
- No persisted Backup Root authority exists. Backup destination is selected at backup time.
- H4-3 exposes the shared nonblocking OS-held runtime mutation barrier.
- The accepted audit metadata bound is 1..256 characters with no control characters.

## 5. Command Grammar and Identity Constitution

The grammar remains exactly:

```text
backend.exe operator [--json] tenant provision --tenant ID --approval-ref REF
```

No `--tenant-code`, force, overwrite, repair, retry, backup-root, or secret argument exists. Pure validation requires ASCII lowercase, exact regex `^[a-z]{2}-[a-z0-9]{3,5}-[0-9]{4}$`, sequence 0001..9999, approved vertical, non-reserved identity, and membership in the exact allowlist:

| Canonical tenant | Derived short code |
|---|---|
| `ph-elv-0001` | `elv0001` |
| `ph-bty-0001` | `bty0001` |
| `ph-hwh-0001` | `hwh0001` |

Raw input is never sanitized into validity. Short code is derived, never accepted as input.

## 6. Approval Reference Contract

`--approval-ref` is external change-control metadata only. It must be non-empty, at most 256 characters, and contain no C0/DEL control character. It is not authentication or proof of approval and is not treated as a secret.

## 7. Pre-Mutation and Lock Ordering

Ordering is: parser → pure tenant/approval validation → mutable RuntimePaths initialization → H4-3 barrier acquisition → authoritative DB/Delivery/Backup preflight recheck → one initializer call → independent verifier → bounded success. Invalid input cannot initialize paths or acquire the lock. The barrier is released through the context manager on every exit.

## 8. Database and Partial-Allocation Collision Barrier

While holding the barrier, H4-4 enumerates only the tenant data directory and compares case-folded names against the exact target `.db`, `.db-wal`, and `.db-shm` names. Exact or case-normalized collision returns state/exit 4 before initialization. A complete existing tenant remains a conflict, not idempotent success. Existing bytes are not changed.

## 9. Delivery Namespace Preflight

The existing global settings DB is read without table creation. Missing DB/table/row means Delivery `NOT_CONFIGURED` and is not a blocker. A configured root is normalized through the accepted Delivery helper. H4-4 inspects only `<delivery-root>/tenants` and rejects an exact or case-normalized target tenant allocation without creating, deleting, renaming, or repairing it. An absent target is `AVAILABLE` and remains absent.

## 10. H4-4 Backup Namespace Authority Decision Closure

Original blocker: `H4_4_BACKUP_NAMESPACE_AUTHORITY_UNRESOLVED`.

Current source has no persisted Backup Root authority. Architecture freezes Backup Root/destination selection at backup time, and the Field Boundary places tenant provisioning before field Backup Root configuration. The historical development path is not product authority. H4-4 therefore reports `NOT_CONFIGURED`, does not scan or create any Backup Root, and does not fail solely for missing authority. H4-5 owns explicit backup destination/path validation. No configuration authority was added.

## 11. One-Shot Initializer

The default initializer lazily imports `get_tenant_engine(canonical-id)`, executes its current application-schema and Ledger V2 initialization, proves a connection can be opened, disposes the Engine, and is invoked exactly once. H4-4 performs no automatic retry. The packaged operator process is the one-shot lifetime boundary.

## 12. Independent Non-Repairing Verifier

The verifier independently opens the resulting DB with SQLite `mode=ro&immutable=1`, `query_only`, and no SQLAlchemy initializer. It refuses pre-existing sidecars, creates no schema, performs no migration, and checks that the main DB and sidecar state remain unchanged.

It proves:

- `PRAGMA integrity_check` returns exactly `ok`;
- FK enforcement can be enabled for the verification connection and `foreign_key_check` is empty;
- every current ORM application table and its modeled columns are present;
- required rollout columns and both required rollout indexes are present;
- all Ledger V2 tables are present;
- Ledger component `fingerprint_ledger` has version exactly `2`;
- every business activity table has zero rows.

## 13. Application, Rollout, Ledger, and Zero-Data Contract

Application tables checked: `video_tasks`, `reservation_run_diagnostics`, `reservation_rollout_breakers`, `video_assets`, `local_assets_inventory`, `task_history`, `variant_approvals`, and `variant_status_audits`.

Zero-row checks additionally cover `fingerprint_identities`, `fingerprint_occurrences`, and `fingerprint_reservations`. Ledger version metadata is allowed and required; it is not business activity. No fake task, asset, Reservation, diagnostics, breaker, approval, or fingerprint occurrence is inserted.

## 14. Success Output and Failure Contract

Success exposes only canonical tenant, derived short code, relative DB path, schema PASS, Ledger V2 PASS, zero-business-data PASS, Delivery namespace status, and Backup `NOT_CONFIGURED`. It exposes no absolute path or sensitive value.

Stable errors map to frozen exits: identity/approval validation → 3; lock busy, DB collision, Delivery collision → 4; post-artifact initializer/verifier failure → 7; barrier/storage/subsystem failure before allocation → 8; bounded unexpected failure before allocation → 9. Human output uses stdout on success/stderr on failure; JSON is one schema-version-1 object on stdout with empty stderr.

## 15. Partial Preservation and No Retry

If initializer failure occurs after `.db`, WAL, or SHM appears, or any independent verification fails, the target is preserved and exit 7 reports `OPERATOR_TENANT_PARTIAL_PROVISIONING_REVIEW_REQUIRED`. H4-4 never deletes, overwrites, repairs, or retries the partial allocation.

## 16. Focused Evidence

Command:

```text
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_operator_tenant_provision.py -q
```

Result: `22 passed, 62 subtests passed`. This includes separate-process real initialization for all three IDs, identity/approval matrices, DB/WAL/SHM/case collisions, authoritative in-lock recheck, real cross-process lock contention and post-release success, Delivery cases, Backup no-authority/no-hardcode guard, schema/Ledger/business fault injection, partial preservation/no-retry call counts, representative human/JSON failure contracts, and later placeholders.

## 17. H4-1A / H4-2 / H4-3 Regression

Command:

```text
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_operator_tenant_provision.py tests/test_var001_runtime_mutation_foundation.py tests/test_var001_operator_cli.py tests/test_var001_operator_status.py tests/test_var001_runtime_paths_bootstrap.py tests/test_var001_packaged_console_contract.py -q
```

Result: `90 passed, 146 subtests passed`. Historical placeholder lists were narrowed only by removing the now-implemented H4-4 command; H4-5/H4-6/H4-7 remain placeholders.

## 18. Tenant / Ledger / Reservation Regression

The exact selected command covered H2/H3, rollout/readiness/lease, Delivery, backup/restore, both Ledger suites, and clean Task Identity. Result: `244 passed, 1 skipped, 157 subtests passed`.

## 19. Full Regression

```text
.\venv_build\Scripts\python.exe -m pytest tests -q
```

Result: `681 passed, 1 skipped, 383 subtests passed`, zero failures/errors. `py_compile` passed for all changed/new Python modules. Warnings are existing dependency/deprecation warnings; no test was skipped or weakened for H4-4.

## 20. Changed Files

- `src/api/operator_cli.py` — lazy H4-4 dispatch/result mapping.
- `src/api/operator_tenant_provision.py` — new bounded service.
- `tests/test_var001_operator_tenant_provision.py` — new focused suite.
- `tests/test_var001_operator_cli.py` — post-H4-4 placeholder inventory.
- `tests/test_var001_operator_status.py` — post-H4-4 placeholder inventory.
- `tests/test_var001_runtime_mutation_foundation.py` — post-H4-4 placeholder inventory.
- this implementation report.
- compact Backup authority decision closure.
- ignored final review bundle (not staged).

No production database helper, RuntimePaths, backup, Seed, secret, Tauri, Rust, build, dependency, AGENTS, or handoff file changed.

## 21. Forbidden-Scope Audit

PASS: no arbitrary tenant provision/registry/fourth ID; no tenant-code/force/overwrite/repair/retry; no Login/UI/HTTP/X-Local-User authority; no tenant switching; no automatic partial deletion/retry; no fake activity/evidence; no backup create/verify or H4-5; no Seed transition/H4-6; no secret generation/rotation/H4-7; no restore; no lock/CAS redesign; no status locking; no H5/H6 work; no Tauri/Rust/build/dependency mutation; no AGENTS/handoff/RC1 mutation.

## 22. Final Git Evidence

Final commands and raw output are captured in the ignored review bundle. `git diff --check` exits 0 (Git may print only line-ending conversion warnings); index remains empty. No runtime DB, sidecar, Delivery, Backup, lock, log, build, or package artifact was added to the primary worktree.

## 23. Declarations

```text
NO COMMIT PERFORMED
NO PUSH PERFORMED
H4_5_NOT_STARTED
NO_PACKAGED_REBUILD_PERFORMED
```

## 24. Final Classification

`VAR001_PHASE3D2IB2B2RH44_THREE_ID_TENANT_PROVISIONING_IMPLEMENTATION_PASS`

Independent ChatGPT review remains required before any commit, push, or H4-5 authorization.
