# VAR-001 Phase 3D-2I-B-2B-1
# First Philippine Tenant P0 Preflight & Operator Input Lock

## 1. Executive Result

This read-only preflight found no source or runtime contradiction that prevents the P0 `BACKUP_AND_OFF` preparation sequence. The repository is on the expected branch and commit with a clean baseline, but the apply phase is not ready because the release tag, tenant selection, Delivery Root runtime fact, backup destination, named operators, assignment-secret presence, generation inputs, and staffed apply block remain unresolved.

No runtime state was changed. No service was started or stopped, no task was submitted, no database was opened or modified, no backup or restore was run, and no environment or rollout setting was changed.

Current classification:

`VAR001_PHASE3D2IB2B1_P0_PREFLIGHT_WAITING_OPERATOR_INPUT`

## 2. Repository Baseline

| Fact | Result |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| HEAD | `5f534b180dd2ae9fa9212e6632a44746669d7e6f` |
| Latest commit | `5f534b1 docs(v1.5): assemble Philippine seed execution pack` |
| Initial worktree | Clean |

The required policy, execution, assembly, canary, and backup/restore documents were read in full before this artifact was created. The Phase 3D-2I-B-1C Policy Freeze remains policy authority, and the Philippine Seed Execution Pack remains execution authority.

## 3. Application Commit / Tag

`APPLICATION_COMMIT = 5f534b180dd2ae9fa9212e6632a44746669d7e6f`

Application commit status: `READY`

No existing V1.5 / Philippine Seed candidate tag points to the current HEAD.

`APPLICATION_TAG_REQUIRED_BEFORE_P0_APPLY`

The operator may consider `v1.5-phseed-rc1` as a naming suggestion, but this preflight did not create, select, or move any tag.

## 4. Tenant Selection Inputs

Read-only filename inventory under the local tenant data location exposed these canonical-looking identifiers only:

- `default`
- `v15_acceptance`
- `v15_delivery_a`
- `v15_delivery_b`

The filenames do not safely prove a business mapping to the first Philippine elevator, beauty, or villa / water-heating tenant. No tenant database was opened and no customer content, prompt, asset, or SQL row was inspected. Business mapping and first-tenant selection therefore remain human decisions.

| Business tenant | Canonical tenant ID | Asset readiness | Stable operator owner | Known blocker | Backup destination available? | Delivery prerequisite known? | Selected? |
|---|---|---|---|---|---|---|---|
| elevator | `<OPERATOR_INPUT_REQUIRED>` | `<OPERATOR_INPUT_REQUIRED>` | `<OPERATOR_INPUT_REQUIRED>` | Business-to-canonical mapping is unproven | `<OPERATOR_INPUT_REQUIRED>` | `<OPERATOR_INPUT_REQUIRED>` | No decision recorded |
| beauty | `<OPERATOR_INPUT_REQUIRED>` | `<OPERATOR_INPUT_REQUIRED>` | `<OPERATOR_INPUT_REQUIRED>` | Business-to-canonical mapping is unproven | `<OPERATOR_INPUT_REQUIRED>` | `<OPERATOR_INPUT_REQUIRED>` | No decision recorded |
| villa / water-heating | `<OPERATOR_INPUT_REQUIRED>` | `<OPERATOR_INPUT_REQUIRED>` | `<OPERATOR_INPUT_REQUIRED>` | Business-to-canonical mapping is unproven | `<OPERATOR_INPUT_REQUIRED>` | `<OPERATOR_INPUT_REQUIRED>` | No decision recorded |

The Tech Lead must explicitly select exactly one business tenant and confirm its authoritative canonical tenant ID before 2B-2.

## 5. Delivery Root Preflight

The backend was not running at the local settings endpoint during the read-only check. It was not started.

`DELIVERY_ROOT_RUNTIME_CHECK_PENDING`

Configured status: unknown

Current root path: not read

Mutation performed: none

Once an operator confirms the machine-global Delivery Root, the expected tenant project path is:

`<DELIVERY_ROOT>/tenants/<CANONICAL_TENANT>/projects/_default/`

Delivery files are operator-facing copies and must not be treated as authoritative assets.

## 6. Backup Preflight

The current source-valid commands documented for the later operator-controlled operation are:

```powershell
.\venv_build\Scripts\python.exe -m src.api.backup_restore backup `
  --tenant <canonical-tenant> `
  --destination <new-backup-directory>

.\venv_build\Scripts\python.exe -m src.api.backup_restore verify `
  --bundle <backup-directory>

.\venv_build\Scripts\python.exe -m src.api.backup_restore restore-to-staging `
  --bundle <backup-directory> `
  --staging-root <new-isolated-root>
```

No command was executed. No backup directory was created.

`<BACKUP_DESTINATION_ROOT>` remains operator input and must satisfy all of the following:

- It is outside the authoritative project `output/` tree.
- It is outside the configured Delivery Root subtree used for operator copies.
- It is stable storage with sufficient free space.
- It permits creation of a new backup directory; the final bundle directory must not already exist.

The project root and internal `output/` directory exist. No backup parent was supplied, so its existence and free space could not be checked. Delivery Root existence is also pending because the backend was not running and the setting was not otherwise read.

## 7. Environment Presence Matrix

The check inspected only presence of the required keys in the current process environment and root `.env`. It did not dump `.env`. For non-secret keys, a missing key is reported as `ABSENT / UNREADABLE` because there is no current value to compare with P0. For the assignment secret, only presence is reported.

| Required Seed key | Presence | P0 comparison |
|---|---|---|
| `RESERVATION_LEASE_TTL_SECONDS` | ABSENT | UNREADABLE |
| `RESERVATION_HEARTBEAT_INTERVAL_SECONDS` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_READINESS_WINDOW` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MAXIMUM_PARTIAL_PLAN_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MAXIMUM_CLEANUP_WARNING_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_CONTROL_ENABLED` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_GENERATION` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_TENANT_ALLOWLIST` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_KILL_SWITCH` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_ROLLBACK_WINDOW` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_DIAGNOSTIC_COVERAGE_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_PLANNING_COVERAGE_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_TERMINAL_COVERAGE_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE` | ABSENT | UNREADABLE |
| `RESERVATION_ROLLOUT_ASSIGNMENT_SECRET` | ABSENT | Not inspected |

Summary: 32 required non-secret keys are absent, and the assignment-secret key is absent.

`ASSIGNMENT_SECRET_STATUS = ABSENT`

No secret value, length, hash, prefix, suffix, or derived information was read or recorded.

## 8. P0 Target Matrix

These are frozen targets for the later operator-controlled apply phase. Nothing in this matrix was applied during preflight.

| Area | P0 target |
|---|---|
| Lease TTL | `180` seconds |
| Heartbeat interval | `45` seconds |
| Rollout control | `enabled=true` |
| Exact Canary | `0` basis points |
| Balanced Canary | `0` basis points |
| Kill switch | `true` |
| Tenant allowlist | Exactly one selected canonical tenant |
| Generation | `phseed-<tenantcode>-bal-YYYYMMDD-rN` |
| Readiness window | `7d` |
| Readiness evidence minima | authoritative ENFORCE `10`; planning observed `10`; conflict tasks `0` |
| Readiness coverage minima | diagnostic `1.0`; planning `1.0`; terminal `1.0` |
| Readiness quality maxima | zero-plan `0.30`; partial-plan `0.20` |
| Readiness safety maxima | authority loss `0`; terminal persistence failure `0`; worker lease-config failure `0` |
| Readiness cleanup maximum | `0.10` |
| Rollback window for P0/P1/P2 | `7d` |
| Rollback minimum Canary tasks | `5` |
| Rollback coverage minima | diagnostic `1.0`; planning `1.0`; terminal `1.0` |
| Rollback quality maxima | zero-plan `1.0`; partial-plan `1.0` |
| Rollback safety maxima | authority loss `0`; terminal persistence failure `0`; worker config failure `0` |
| Rollback cleanup maximum | `1.0` |

## 9. Operator Inputs Still Required

The following values must be supplied or approved through the appropriate operator channels before 2B-2:

- `<APPLICATION_TAG>`: an approved release candidate tag pointing to the recorded application commit.
- `<SELECTED_CANONICAL_TENANT>`: exactly one authoritative tenant ID, after business mapping is verified.
- `<TENANT_CODE>`: approved code for the selected tenant; it must not be chosen automatically.
- `<EXECUTION_DATE>`: actual approved execution date.
- `<GENERATION>`: formed only after tenant, tenant code, date, and revision are approved: `phseed-<tenantcode>-bal-YYYYMMDD-rN`.
- `<DELIVERY_ROOT>`: runtime-confirmed configured root and availability.
- `<BACKUP_DESTINATION_ROOT>`: approved stable destination outside both authoritative output and Delivery trees.
- `<TECH_LEAD>`: named approving Tech Lead.
- `<EXECUTION_OPERATOR>`: named operator responsible for the apply block.
- Assignment secret: supplied only through the secure operator channel and confirmed present without disclosure.
- `<PLANNED_P0_APPLY_BLOCK>`: an operator-chosen staffed block. Frozen staffed windows are `09:00–12:00`, `14:00–17:00`, and `19:00–21:00`; later risk-increasing activation must begin with at least two staffed hours remaining.
- Business asset readiness, stable owner, and Delivery prerequisite confirmation for each candidate tenant.

## 10. 2B-2 Apply Readiness

| Required input | Status | Evidence / remaining action |
|---|---|---|
| `APPLICATION_COMMIT` | READY | HEAD recorded as `5f534b180dd2ae9fa9212e6632a44746669d7e6f` |
| `APPLICATION_TAG` | OPERATOR_INPUT_REQUIRED | No suitable tag points to HEAD; create only through the approved operator/release process |
| `SELECTED_CANONICAL_TENANT` | OPERATOR_INPUT_REQUIRED | No business-to-canonical mapping or selection was proven |
| `TENANT_CODE` | OPERATOR_INPUT_REQUIRED | Must be approved after tenant selection |
| `EXECUTION_DATE` | OPERATOR_INPUT_REQUIRED | Must be the approved real execution date |
| `GENERATION` | OPERATOR_INPUT_REQUIRED | Depends on selected tenant, tenant code, date, and revision |
| `DELIVERY_ROOT` | OPERATOR_INPUT_REQUIRED | Backend was not running; runtime check is pending |
| `BACKUP_DESTINATION_ROOT` | OPERATOR_INPUT_REQUIRED | No candidate path was supplied |
| `TECH_LEAD` | OPERATOR_INPUT_REQUIRED | No named approver supplied |
| `EXECUTION_OPERATOR` | OPERATOR_INPUT_REQUIRED | No named operator supplied |
| `ASSIGNMENT_SECRET_PRESENT` | OPERATOR_INPUT_REQUIRED | Required key is absent; secret must arrive only through the secure operator channel |
| `PLANNED_P0_APPLY_BLOCK` | OPERATOR_INPUT_REQUIRED | No staffed block was selected |

Only `APPLICATION_COMMIT` is currently ready. Phase 2B-2 must not apply P0 until every other row is resolved and recorded.

## 11. Git Status

The repository baseline was clean before this allowed report was created. The expected final worktree delta is only:

```text
?? doc/investigations/VAR001_PHASE3D2IB2B1_FIRST_TENANT_P0_PREFLIGHT.md
```

No commit or push was performed.

## 12. Final Classification

Read-only repository and source facts are coherent, but required human/operator inputs and runtime confirmations remain unresolved. No P0 mutation is authorized by this artifact.

`VAR001_PHASE3D2IB2B1_P0_PREFLIGHT_WAITING_OPERATOR_INPUT`
