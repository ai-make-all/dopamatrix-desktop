# VAR-001 Phase 3D-2I-B-2B-1T-B
# Real Philippine Tenant Provisioning Acceptance

## 1. Executive Result

The three approved Philippine tenant identities were provisioned successfully as empty tenant SQLite databases by the current source-native `src.api.database.get_tenant_engine()` initializer. Each tenant was initialized in a separate one-shot process, reopened in a separate verification process, passed SQLite and application schema checks, contained Fingerprint Ledger schema version 2, and contained zero fabricated business activity.

Final classification:

`VAR001_PHASE3D2IB2B1TB_REAL_TENANT_PROVISIONING_PASS`

This result provisions identity and schema only. It does not establish Delivery readiness, create a backup, complete P0, produce readiness evidence, or activate Reservation/Canary traffic.

## 2. Application Baseline / Tag

- Branch: `feature/var-001-variation-policy`
- Current documentation/evidence HEAD at preflight: `05ef7327c2ff4fe79eed298fda2c74323698f351`
- Current HEAD summary: `05ef732 docs(v1.5): freeze tenant identity provisioning`
- Approved application baseline: `5f534b180dd2ae9fa9212e6632a44746669d7e6f`
- Tag: `v1.5-phseed-rc1`
- Resolved tag commit: `5f534b180dd2ae9fa9212e6632a44746669d7e6f`
- Tag verification: PASS; the tag was not moved, recreated, or modified.
- Repository status before provisioning: clean.

The later current HEAD is permitted because it contains documentation/evidence work after the frozen application baseline.

## 3. Human Approval Lock

The following approved identity decisions were used without substitution:

| Business category | Canonical Tenant ID | Tenant Short Code | Country | Vertical | Sequence |
|---|---|---|---|---|---|
| Elevator | `ph-elv-0001` | `elv0001` | `ph` | `elv` | `0001` |
| Beauty | `ph-bty-0001` | `bty0001` | `ph` | `bty` | `0001` |
| Home Water Heating | `ph-hwh-0001` | `hwh0001` | `ph` | `hwh` | `0001` |

The approved Tenant Short Code pattern is `<vertical><sequence4>`. Tech Lead is `tech-lead`; provisioning operator is `seed-operator-01`. Short codes were recorded only as operator aliases and were not used as database selectors.

## 4. Backend Quiescence

Pre-creation and post-verification checks found:

- zero running processes named Python, PythonW, Uvicorn, DopaMatrix, or DopaMatrix Desktop;
- zero listeners on the application's source-defined backend port `8000`;
- zero listeners owned by a matching backend process.

A supplemental Win32 CIM command-line enumeration was unavailable because the local account lacked that query permission. The independent process-name and TCP-listener checks were available and both showed no active normal backend. No process was stopped or killed.

Backend quiescence result: PASS.

## 5. Identity Validation

All three identities passed the complete pre-creation barrier:

- exact match for `^[a-z]{2}-[a-z0-9]{3,5}-[0-9]{4}$`;
- sequence within `0001..9999`;
- `canonical_tenant_id(raw) == raw` with no transformation;
- not in the reserved/test namespace;
- vertical present in the approved `elv`, `bty`, `hwh` registry;
- exact short-code mapping under `<vertical><sequence4>`.

Identity validation result for `ph-elv-0001`, `ph-bty-0001`, and `ph-hwh-0001`: PASS.

## 6. Database Collision Preflight

Before the first creation, all three tenant identities were checked together. For every tenant, the following were absent:

- `data/dopamatrix_<tenant>.db`
- `data/dopamatrix_<tenant>.db-wal`
- `data/dopamatrix_<tenant>.db-shm`

A case-insensitive filename comparison across the existing `data/` directory found no exact or case-normalized collision for any target or sidecar. Existing `default`, `v15_acceptance`, `v15_delivery_a`, and `v15_delivery_b` databases were observed only as protected existing namespaces and were not opened, changed, renamed, or reused.

`.gitignore` rule `/data/dopamatrix*.db` covers all three new database paths. Database collision preflight: PASS.

## 7. Delivery Namespace Preflight

Approved Delivery Root: `D:\outputdir\V15`.

At preflight the Delivery Root did not exist. Consequently none of these tenant namespaces existed:

- `D:\outputdir\V15\tenants\ph-elv-0001`
- `D:\outputdir\V15\tenants\ph-bty-0001`
- `D:\outputdir\V15\tenants\ph-hwh-0001`

No Delivery directory was created. There was no Delivery namespace collision. Delivery Root creation/configuration/verification remains a later P0 prerequisite.

## 8. Backup Namespace Preflight

Approved Backup Root: `D:\dopamatrix-backups`.

At preflight the Backup Root did not exist. Therefore there was no existing allocation for any approved canonical tenant. No backup directory or Seed backup was created.

Carried-forward state: `BACKUP_ROOT_CREATION_PENDING_P0`.

## 9. Creation Operations

The creation barrier was cleared for all three identities before the first mutation. Provisioning then used one repository virtual-environment Python process per tenant, in the approved deterministic order. Each process called `get_tenant_engine(<canonical-id>)`, allowed the application and Ledger initializers to finish, disposed its Engine, and exited cleanly.

| Order | Tenant | Started (UTC) | Finished (UTC) | Exit | Resulting relative path | Size |
|---:|---|---|---|---:|---|---:|
| 1 | `ph-elv-0001` | `2026-09-18T15:25:41.829598+00:00` | `2026-09-18T15:25:42.351623+00:00` | 0 | `data/dopamatrix_ph-elv-0001.db` | 217,088 bytes |
| 2 | `ph-bty-0001` | `2026-09-18T15:26:03.046555+00:00` | `2026-09-18T15:26:03.413995+00:00` | 0 | `data/dopamatrix_ph-bty-0001.db` | 217,088 bytes |
| 3 | `ph-hwh-0001` | `2026-09-18T15:26:21.585311+00:00` | `2026-09-18T15:26:21.989341+00:00` | 0 | `data/dopamatrix_ph-hwh-0001.db` | 217,088 bytes |

After verification, only the three `.db` files remained; no target `-wal` or `-shm` sidecar residue remained.

## 10. Schema Verification

Each tenant was reopened through `get_tenant_engine()` in its own new verification process. For each tenant:

- source initialization and reopen completed;
- `PRAGMA integrity_check` returned `ok`;
- `PRAGMA foreign_keys` returned `1` on the source-configured connection;
- VideoTask identity verification passed;
- rollout metadata schema verification passed;
- all 8 current application ORM tables were present;
- all 4 current Fingerprint Ledger tables were present;
- missing expected tables: none.

The application tables verified through current model metadata were `video_tasks`, `reservation_run_diagnostics`, `reservation_rollout_breakers`, `video_assets`, `local_assets_inventory`, `task_history`, `variant_approvals`, and `variant_status_audits`.

Schema verification result:

| Tenant | Integrity | Foreign keys | Rollout metadata | Missing tables | Reopen |
|---|---|---:|---|---|---|
| `ph-elv-0001` | `ok` | 1 | PASS | none | PASS |
| `ph-bty-0001` | `ok` | 1 | PASS | none | PASS |
| `ph-hwh-0001` | `ok` | 1 | PASS | none | PASS |

## 11. Ledger V2 Verification

For each tenant, current Ledger metadata and tables were verified after reopen:

- `fingerprint_ledger_schema_version` row for component `fingerprint_ledger`: version `2`;
- `fingerprint_identities`: present;
- `fingerprint_occurrences`: present;
- `fingerprint_reservations`: present;
- no missing Ledger tables.

Ledger V2 verification result for all three tenants: PASS.

## 12. Zero Business Data Verification

Only bounded row counts were read; no row content was dumped. Every listed business-activity table had count `0` in every new tenant database:

| Table | Elevator | Beauty | Home Water Heating |
|---|---:|---:|---:|
| `video_tasks` | 0 | 0 | 0 |
| `task_history` | 0 | 0 | 0 |
| `video_assets` | 0 | 0 | 0 |
| `local_assets_inventory` | 0 | 0 | 0 |
| `variant_approvals` | 0 | 0 | 0 |
| `variant_status_audits` | 0 | 0 | 0 |
| `reservation_run_diagnostics` | 0 | 0 | 0 |
| `reservation_rollout_breakers` | 0 | 0 | 0 |
| `fingerprint_identities` | 0 | 0 | 0 |
| `fingerprint_occurrences` | 0 | 0 | 0 |
| `fingerprint_reservations` | 0 | 0 | 0 |

The Ledger schema-version metadata row is expected schema metadata and is not business activity. No VideoTask, TaskHistory, creative asset, approval, Reservation, diagnostic, breaker, or fingerprint activity was fabricated.

## 13. Tenant Identity Mapping

The authoritative mappings are:

- `ph-elv-0001` -> `data/dopamatrix_ph-elv-0001.db`; operator alias `elv0001`
- `ph-bty-0001` -> `data/dopamatrix_ph-bty-0001.db`; operator alias `bty0001`
- `ph-hwh-0001` -> `data/dopamatrix_ph-hwh-0001.db`; operator alias `hwh0001`

Only Canonical Tenant IDs were passed to the database initializer. Tenant Short Codes are not database, authorization, Reservation, TaskHistory, or billing authority.

## 14. Failure / Cleanup State

No tenant initialization failed, no tenant was retried against an active filename, and no partial provisioning state occurred.

One initial verification shell invocation had a quoting error and ended with a Python `SyntaxError` before the verification program imported application modules or opened a database. It was corrected by supplying the same read-only verification program through standard input. All three actual verification processes then exited successfully. This command-construction error was not an initialization or database failure and caused no database mutation.

No automatic deletion, overwrite, rollback fabrication, or cleanup of a partial tenant was performed. No transient target sidecars remained after the independent verification processes exited.

## 15. P0 Prerequisites Carried Forward

Provisioning does not imply P0 completion. The following remain explicitly outside this phase:

- Delivery Root `D:\outputdir\V15`: approved but absent and not verified;
- Backup Root `D:\dopamatrix-backups`: approved but absent; creation and verified Seed backup remain pending P0;
- no Seed backup exists;
- no rollout/Readiness/lease environment was changed;
- no assignment secret was read, generated, or exposed;
- no P1 Explicit ENFORCE evidence exists from this phase;
- no Canary or Reservation traffic was created.

The Login / `X-Local-User` route remains an internal V1.5 workspace-entry mechanism, not a provisioning API. Future controlled Seed use must use the exact approved Canonical Tenant IDs. Operator identity and membership architecture remains outside VAR-001.

## 16. Scope Check

Scope result: PASS.

- Created only the three approved tenant SQLite database files and this acceptance artifact.
- Did not modify production source, Vue, tests, `.env`, process environment, rollout settings, lease settings, Readiness settings, or Delivery settings.
- Did not start the backend, send HTTP requests, use Login UI, submit creative work, create fake tasks/assets/evidence, create a backup, or restore a backup.
- Did not insert business rows.
- Did not change Reservation, Task Identity, Fingerprint Ledger semantics, or schema version.
- Did not add tenant databases to Git.
- Did not commit or push.

## 17. Git Status

Before provisioning, `git status --short` was empty. The three tenant databases are ignored by the existing `/data/dopamatrix*.db` rule and therefore do not enter Git status.

Final `git diff --check`: PASS (no output).

Final visible Git delta:

```text
?? doc/investigations/VAR001_PHASE3D2IB2B1TB_REAL_TENANT_PROVISIONING_ACCEPTANCE.md
```

No tenant SQLite file appeared in Git status.

## 18. Final Classification

All three approved tenant databases were created through the current source-native initializer, independently reopened, passed application schema and SQLite integrity checks, carried Fingerprint Ledger schema version 2, and contained zero fabricated business activity.

`VAR001_PHASE3D2IB2B1TB_REAL_TENANT_PROVISIONING_PASS`
