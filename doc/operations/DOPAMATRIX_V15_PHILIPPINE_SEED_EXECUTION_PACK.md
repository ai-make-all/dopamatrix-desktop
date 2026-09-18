# DopaMatrix V1.5
# Philippine Seed Execution Pack

Policy authority:
`doc/investigations/VAR001_PHASE3D2IB1C_FINAL_PHILIPPINE_SEED_POLICY_FREEZE.md`

Stable procedure:
`doc/operations/DOPAMATRIX_V15_PHILIPPINE_SEED_CANARY_RUNBOOK.md`

This is a per-tenant operator worksheet and evidence manifest. It does not
activate Canary by itself. Do not paste secrets, raw customer creative
content, HMAC input, owner-attempt IDs, SQL, or tenant database paths here.

## 1. Execution Header

| Field | Operator entry |
|---|---|
| Application commit | `<APPLICATION_COMMIT>` |
| Application tag | `<APPLICATION_TAG>` |
| Execution date | `<EXECUTION_DATE>` |
| Staffed block | `<STAFFED_BLOCK>` |
| Selected canonical tenant | `<CANONICAL_TENANT>` |
| Tenant business type | `[ ] elevator  [ ] beauty  [ ] villa / water-heating` |
| Tech Lead | `<TECH_LEAD>` |
| Execution operator | `<OPERATOR>` |
| Generation | `<GENERATION>` |
| Delivery Root | `<DELIVERY_ROOT>` |
| Backup identifier/path | `<BACKUP_ID>` |
| Backup verification result | `[ ] VALID  [ ] FAILED` |
| Assignment secret loaded from secure channel | `[ ] YES  [ ] NO` |

Never paste the assignment secret into this pack. Generation must match:

```text
phseed-<tenantcode>-bal-YYYYMMDD-rN
```

## 2. First-Tenant Selection Sheet

Do not select automatically. Choose using verified backup, Delivery isolation,
asset readiness, and stable operator ownership.

| Business tenant | Canonical tenant ID | Backup verified? | Delivery verified? | Asset readiness | Stable operator owner | Open blocker | Selected? |
|---|---|---|---|---|---|---|---|
| elevator | `<CANONICAL_TENANT>` | `[ ]` | `[ ]` | `<ASSESSMENT>` | `<OPERATOR>` | `<NONE_OR_BLOCKER>` | `[ ]` |
| beauty | `<CANONICAL_TENANT>` | `[ ]` | `[ ]` | `<ASSESSMENT>` | `<OPERATOR>` | `<NONE_OR_BLOCKER>` | `[ ]` |
| villa / water-heating | `<CANONICAL_TENANT>` | `[ ]` | `[ ]` | `<ASSESSMENT>` | `<OPERATOR>` | `<NONE_OR_BLOCKER>` | `[ ]` |

Selection reason: `<RECORDED_REASON>`

Tech Lead approval: `[ ] YES  [ ] NO`

## 3. P0 — BACKUP_AND_OFF Checklist

All boxes must pass before P1.

- [ ] Application commit and tag recorded.
- [ ] Canonical tenant confirmed from the authoritative tenant identity.
- [ ] Tenant backup completed.
- [ ] Backup independently verified as `VALID`.
- [ ] Delivery Root configured and GET-confirmed.
- [ ] Derived tenant path verified:
  `<DELIVERY_ROOT>/tenants/<CANONICAL_TENANT>/projects/_default/`.
- [ ] Two-Root boundary confirmed: internal `output/` remains authority.
- [ ] Lease configured as TTL `180`, heartbeat `45`.
- [ ] Complete Readiness environment key set configured.
- [ ] Complete Rollout environment key set configured.
- [ ] Exact Canary bps is `0`.
- [ ] Balanced Canary bps is `0`.
- [ ] Kill switch is `true`.
- [ ] Only the selected tenant is in the active allowlist.
- [ ] Generation matches `phseed-<tenantcode>-bal-YYYYMMDD-rN`.
- [ ] Assignment secret loaded securely and never printed.
- [ ] Controlled backend restart completed after environment changes.
- [ ] Readiness endpoint returns a bounded non-error response.
- [ ] Rollout-status endpoint returns a bounded non-error response.
- [ ] Summary endpoint returns a bounded non-error response.
- [ ] Ordinary omitted traffic remains `DEFAULT_OFF`.
- [ ] No unresolved task, DB, lease, cleanup, or authority incident.
- [ ] Selected staffed block leaves at least two staffed hours after activation.

Backup timestamp: `<UTC_TIMESTAMP>`

Backup operator / independent verifier: `<OPERATOR>` / `<VERIFIER>`

P0 result: `[ ] PASS  [ ] STOP`

## 4. Source-Valid Environment Manifest

Every environment change in this table requires a controlled backend restart.
The loaders inspect the running process environment, but `.env` is loaded only
at process startup and there is no supported hot-reload/mutation API.

`Dynamic CC` means the value may change only within the 1C Change-Control
envelope. Rollout and Readiness key sets are all-or-none.

### Lease

| Exact key | P0/P1/P2 | P3-W | P3-A | Restart? | Secret? | Dynamic CC? |
|---|---|---|---|---|---|---|
| `RESERVATION_LEASE_TTL_SECONDS` | `180` | `180` | `180` | YES | NO | YES: profile may become 300 |
| `RESERVATION_HEARTBEAT_INTERVAL_SECONDS` | `45` | `45` | `45` | YES | NO | YES: paired profile may become 60 |

Lease profiles are indivisible: `180/45` or `300/60` only.

### Readiness

| Exact key | P0/P1/P2 | P3-W | P3-A | Restart? | Secret? | Dynamic CC? |
|---|---|---|---|---|---|---|
| `RESERVATION_ROLLOUT_READINESS_WINDOW` | `7d` | `7d` | `7d` | YES | NO | NO |
| `RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS` | `10` | `10` | `10` | YES | NO | NO |
| `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS` | `10` | `10` | `10` | YES | NO | NO |
| `RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS` | `0` | `0` | `0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE` | `1.0` | `1.0` | `1.0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE` | `1.0` | `1.0` | `1.0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE` | `1.0` | `1.0` | `1.0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | `0.30` | `0.30` | `0.30` | YES | NO | NO |
| `RESERVATION_ROLLOUT_MAXIMUM_PARTIAL_PLAN_RATE` | `0.20` | `0.20` | `0.20` | YES | NO | NO |
| `RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE` | `0` | `0` | `0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | `0` | `0` | `0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE` | `0` | `0` | `0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_MAXIMUM_CLEANUP_WARNING_RATE` | `0.10` | `0.10` | `0.10` | YES | NO | NO |

### Rollout control

| Exact key | P0/P1/P2 | P3-W | P3-A | Restart? | Secret? | Dynamic CC? |
|---|---|---|---|---|---|---|
| `RESERVATION_ROLLOUT_CONTROL_ENABLED` | `true` | `true` | `true` | YES | NO | NO |
| `RESERVATION_ROLLOUT_GENERATION` | `<GENERATION>` | same | same | YES | NO | YES: governed epoch only |
| `RESERVATION_ROLLOUT_TENANT_ALLOWLIST` | `<CANONICAL_TENANT>` | same single tenant | same single tenant | YES | NO | YES: one-at-a-time stagger |
| `RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS` | `0` | `0` | `0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS` | `0` | `3000` | `3000` unless reviewed | YES | NO | YES: 1000--4000, <=1000/review |
| `RESERVATION_ROLLOUT_ASSIGNMENT_SECRET` | `<LOAD_FROM_SECURE_OPERATOR_CHANNEL>` | unchanged | unchanged | YES | **YES** | Custodian only; never record value |
| `RESERVATION_ROLLOUT_KILL_SWITCH` | `true` | `false` last | `false` unless containment | YES | NO | YES |
| `RESERVATION_ROLLOUT_ROLLBACK_WINDOW` | `7d` | `7d` | `7d` initially | YES | NO | YES: `24h` only after eligibility |
| `RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS` | `5` | `5` | `5` | YES | NO | NO |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_DIAGNOSTIC_COVERAGE_RATE` | `1.0` | `1.0` | `1.0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_PLANNING_COVERAGE_RATE` | `1.0` | `1.0` | `1.0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_TERMINAL_COVERAGE_RATE` | `1.0` | `1.0` | `1.0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | `1.0` | `1.0` | `0.30` after review | YES | NO | YES: defined P3 transition |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE` | `1.0` | `1.0` | `0.20` after review | YES | NO | YES: defined P3 transition |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE` | `0` | `0` | `0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | `0` | `0` | `0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE` | `0` | `0` | `0` | YES | NO | NO |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE` | `1.0` | `1.0` | `0.20` after review | YES | NO | YES: defined P3 transition |

Do not confuse the two worker keys:

- Readiness: `RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE`
- Rollback: `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE`

## 5. Environment Apply / Restart Procedure

For each P0, P3-W activation, P3-A tightening, or later Change-Control edit:

1. Record old/new values without recording the secret.
2. Confirm the complete Rollout and Readiness key sets remain present.
3. Keep or set kill switch `true` before risk-increasing changes.
4. Drain active work for a controlled restart when required by the runbook.
5. Update the deployment environment / `.env` through the approved operator
   channel.
6. Restart the backend. There is no supported production hot reload.
7. Query Readiness, rollout status, and summary.
8. Confirm generation, allowlist, BPS, breaker, and lease readiness.
9. If activation is intended, disable kill switch last, restart again, and
   re-query before ordinary omitted traffic.
10. Record the post-change result in the Change-Control Log.

Do not mutate `os.environ` through a debug console and do not depend on
development `uvicorn --reload` as an operator mechanism.

## 6. P1 — EXPLICIT_ENFORCE_BOOTSTRAP

Owner: **Central Tech Operator only**.

- Policy: `exact_main_visual_balanced`.
- Work: normal, diverse, production-like tasks.
- Do not manufacture same-FP contention.
- Goal: `authoritativeEnforceTaskCount >= 10` and
  `planningObservedTaskCount >= 10`.
- Conflict minimum: `0`.
- Pace: **serial through planning, concurrent after planning**.
- Ordinary creative operators do not receive an ENFORCE toggle.

### P1 task evidence (10+ rows)

Use `Y/N` for event columns. Add rows without deleting the first ten.

| # | task_id | Submitted UTC | Planning observed UTC | Terminal UTC | Status | Policy | Reservation source | Requested | Planned | Succeeded | Failed | Zero-plan? | Partial? | Authority loss? | Persist failure? | Worker config failure? | Cleanup warning? |
|---:|---|---|---|---|---|---|---|---:|---:|---:|---:|---|---|---|---|---|---|
| 1 | `<TASK_ID>` | | | | | `exact_main_visual_balanced` | `EXPLICIT_ENFORCE` | | | | | | | | | | |
| 2 | `<TASK_ID>` | | | | | `exact_main_visual_balanced` | `EXPLICIT_ENFORCE` | | | | | | | | | | |
| 3 | `<TASK_ID>` | | | | | `exact_main_visual_balanced` | `EXPLICIT_ENFORCE` | | | | | | | | | | |
| 4 | `<TASK_ID>` | | | | | `exact_main_visual_balanced` | `EXPLICIT_ENFORCE` | | | | | | | | | | |
| 5 | `<TASK_ID>` | | | | | `exact_main_visual_balanced` | `EXPLICIT_ENFORCE` | | | | | | | | | | |
| 6 | `<TASK_ID>` | | | | | `exact_main_visual_balanced` | `EXPLICIT_ENFORCE` | | | | | | | | | | |
| 7 | `<TASK_ID>` | | | | | `exact_main_visual_balanced` | `EXPLICIT_ENFORCE` | | | | | | | | | | |
| 8 | `<TASK_ID>` | | | | | `exact_main_visual_balanced` | `EXPLICIT_ENFORCE` | | | | | | | | | | |
| 9 | `<TASK_ID>` | | | | | `exact_main_visual_balanced` | `EXPLICIT_ENFORCE` | | | | | | | | | | |
| 10 | `<TASK_ID>` | | | | | `exact_main_visual_balanced` | `EXPLICIT_ENFORCE` | | | | | | | | | | |
| 11+ | `<TASK_ID>` | | | | | `exact_main_visual_balanced` | `EXPLICIT_ENFORCE` | | | | | | | | | | |

### P1 aggregate evidence

| Metric | Recorded value | Required |
|---|---:|---:|
| Authoritative ENFORCE count | `<COUNT>` | `>=10` |
| Planning-observed count | `<COUNT>` | `>=10` |
| Conflict-task count | `<COUNT>` | `>=0` |
| Diagnostic coverage | `<RATE>` | `>=1.0` |
| Planning coverage | `<RATE>` | `>=1.0` |
| Terminal coverage | `<RATE>` | `>=1.0` |
| Zero-plan count / rate | `<COUNT>` / `<RATE>` | `<=0.30` |
| Partial-plan count / rate | `<COUNT>` / `<RATE>` | `<=0.20` |
| Authority-loss count / rate | `<COUNT>` / `<RATE>` | `0` |
| Terminal-persist-failure count / rate | `<COUNT>` / `<RATE>` | `0` |
| Worker-config-failure count / rate | `<COUNT>` / `<RATE>` | `0` |
| Cleanup-warning count / rate | `<COUNT>` / `<RATE>` | `<=0.10` |

P1 result: `[ ] PASS TO P2  [ ] HOLD  [ ] KILL`

## 7. P2 — READY Checklist

- [ ] Readiness state is exactly `READY_FOR_CONTROLLED_CANARY`.
- [ ] Recommendation is `ELIGIBLE_FOR_CONTROLLED_DEFAULT_ON_CANARY`.
- [ ] Every individual Readiness gate below is `PASS`.
- [ ] Breaker is not latched.
- [ ] Kill switch remains `true`.
- [ ] Generation equals `<GENERATION>`.
- [ ] Allowlist contains only `<CANONICAL_TENANT>`.
- [ ] Exact bps is `0`.
- [ ] Balanced bps remains `0`, or has been prepared at `3000` while kill
  switch remains `true`.
- [ ] Rollout state reflects containment (`KILL_SWITCHED` while killed).
- [ ] Backup and Delivery verification remain current.
- [ ] Tech Lead approved P3-W activation.
- [ ] Activation is at the beginning of `<STAFFED_BLOCK>` with >=2 staffed
  hours remaining.

| Readiness gate code | Observed | Threshold | Status |
|---|---:|---:|---|
| `MINIMUM_AUTHORITATIVE_ENFORCE_TASKS` | | 10 | |
| `MINIMUM_PLANNING_OBSERVED_TASKS` | | 10 | |
| `MINIMUM_CONFLICT_TASKS` | | 0 | |
| `MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE` | | 1.0 | |
| `MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE` | | 1.0 | |
| `MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE` | | 1.0 | |
| `MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | | .30 | |
| `MAXIMUM_PARTIAL_PLAN_RATE` | | .20 | |
| `MAXIMUM_AUTHORITY_LOSS_RATE` | | 0 | |
| `MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | | 0 | |
| `MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE` | | 0 | |
| `MAXIMUM_CLEANUP_WARNING_RATE` | | .10 | |
| `CURRENT_LEASE_CONFIGURATION_READY` | | `true` | |

P2 approval UTC / Tech Lead: `<UTC_TIMESTAMP>` / `<TECH_LEAD>`

## 8. P3-W — Activation Sequence

Complete in order; stop on any failed check.

1. [ ] Confirm verified backup remains valid.
2. [ ] Confirm Delivery Root and tenant subtree remain valid.
3. [ ] Confirm `<CANONICAL_TENANT>` and `<GENERATION>`.
4. [ ] Confirm Readiness is READY.
5. [ ] Confirm breaker is not latched.
6. [ ] Confirm Exact bps is 0.
7. [ ] Set Balanced bps to 3000.
8. [ ] Keep kill switch `true`.
9. [ ] Controlled backend restart.
10. [ ] Re-query Readiness and rollout status.
11. [ ] Verify rollout state is `KILL_SWITCHED` and omitted traffic remains OFF.
12. [ ] Set kill switch `false` **last**.
13. [ ] Controlled backend restart.
14. [ ] Re-query rollout status and record state.
15. [ ] Ordinary operator submits omitted-mode AI Draft -> Tactical Board -> Render.
16. [ ] Verify selected task has `ROLLOUT_CANARY`, current generation, bucket,
    and 3000 bps metadata. A non-selected bucket may correctly remain OFF.
17. [ ] Record terminal diagnostics.

Do not use Explicit ENFORCE as a substitute for ordinary omitted P3 traffic.
Rollback evaluates from the first Canary. The five-task minimum only controls
`WARMING_UP` versus `CANARY_ACTIVE` status.

## 9. P3-W — First Five Fully Observed Canary Tasks

Warmup: coverage minima 1.0, quality/cleanup maxima 1.0, safety maxima 0.
Any authority-loss, terminal-persist, or worker-config event means `KILL`.

| Canary # | task_id | Admission UTC | Generation | Bucket | BPS | Planning observed? | Terminal observed? | Zero-plan | Partial | Authority loss | Persist failure | Worker config failure | Cleanup warning | Final review |
|---:|---|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `<TASK_ID>` | | `<GENERATION>` | | 3000 | | | | | | | | | |
| 2 | `<TASK_ID>` | | `<GENERATION>` | | 3000 | | | | | | | | | |
| 3 | `<TASK_ID>` | | `<GENERATION>` | | 3000 | | | | | | | | | |
| 4 | `<TASK_ID>` | | `<GENERATION>` | | 3000 | | | | | | | | | |
| 5 | `<TASK_ID>` | | `<GENERATION>` | | 3000 | | | | | | | | | |

## 10. P3-A — Pre-Change Cohort Evaluation

`THRESHOLD_TIGHTENING_REQUIRES_PRE_CHANGE_COHORT_EVALUATION`

Do not tighten automatically at task five.

| Metric | Integer numerator | Denominator | Current rate | P3-A threshold | Would pass? |
|---|---:|---:|---:|---:|---|
| Diagnostic coverage | | | | 1.0 minimum | |
| Planning coverage | | | | 1.0 minimum | |
| Terminal coverage | | | | 1.0 minimum | |
| Zero-plan | | | | .30 maximum | |
| Partial-plan | | | | .20 maximum | |
| Cleanup warning | | | | .20 maximum | |
| Authority loss | | | | 0 maximum | |
| Terminal persist failure | | | | 0 maximum | |
| Worker config failure | | | | 0 maximum | |

If any post-warmup threshold would fail, select one and do not rotate:

`[ ] HOLD  [ ] DE_RAMP  [ ] HOLD_ASSET  [ ] INVESTIGATE  [ ] KILL`

If all pass:

- [ ] Keep the same generation.
- [ ] Set rollback zero-plan `.30`, partial `.20`, cleanup `.20`.
- [ ] Keep safety maxima `0` and coverage minima `1.0`.
- [ ] Keep kill switch true while editing.
- [ ] Restart backend, re-query, then disable kill switch last and restart.
- [ ] Record post-change state.

## 11. Reusable Three-Day Review

| Field | Entry |
|---|---|
| Tenant | `<CANONICAL_TENANT>` |
| Generation | `<GENERATION>` |
| Review window | `<FROM_UTC> .. <TO_UTC>` |
| Public Matrix Tasks/day | `<COUNT>` |
| Rendered Outputs/day | `<COUNT>` |
| Successful Outputs/public Task | `<RATE>` |
| Canary task count | `<COUNT>` |
| Fully observed Canary count | `<COUNT>` |
| Candidate-pool status | `<ASSESSMENT>` |
| Zero-plan count / rate | `<COUNT>` / `<RATE>` |
| Partial-plan count / rate | `<COUNT>` / `<RATE>` |
| Cleanup count / rate | `<COUNT>` / `<RATE>` |
| Authority-loss count / rate | `<COUNT>` / `<RATE>` |
| Terminal-persist-failure count / rate | `<COUNT>` / `<RATE>` |
| Worker-config-failure count / rate | `<COUNT>` / `<RATE>` |
| Diagnostic / planning / terminal coverage | `<RATE>` / `<RATE>` / `<RATE>` |
| Readiness state | `<STATE>` |
| Breaker state / reason | `<STATE>` / `<REASON>` |
| Kill-switch state | `<true_or_false>` |
| Current BPS | `<BPS>` |
| Decision | `[ ] KEEP [ ] RAMP [ ] DE_RAMP [ ] HOLD_ASSET [ ] KILL [ ] REBASELINE` |

If BPS changes:

| Old | New | Reason | Operator | Approval | Post-change staffed observation |
|---:|---:|---|---|---|---|
| `<BPS>` | `<BPS>` | `<REASON>` | `<OPERATOR>` | `<TECH_LEAD_OR_NA>` | `<RESULT>` |

Rules: remain within 1000--4000; move by at most 1000 per review; no
automatic ramp; KEEP is preferred when 5--10 fully observed tasks/7d are
healthy.

## 12. Change-Control Log

Never place secret values in this table.

| Timestamp | Tenant | Generation | Parameter | Old Value | New Value | Reason | Pre-change Evidence | Operator | Approver | Restart Required? | Post-change Check | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `<UTC>` | `<CANONICAL_TENANT>` | `<GENERATION>` | `<BPS_or_lease_or_window_or_threshold_or_kill_or_allowlist_or_delivery_root_or_generation>` | `<OLD>` | `<NEW>` | `<REASON>` | `<EVIDENCE>` | `<OPERATOR>` | `<APPROVER>` | `<YES_OR_NO>` | `<CHECK>` | `<RESULT>` |

Environment-backed changes require restart. Delivery Root uses its app-setting
API and does not itself require backend restart.

## 13. KILL / Safety Card

Immediate `KILL` conditions:

- authority-loss count > 0;
- terminal-persist-failure count > 0;
- worker-config-failure count > 0;
- critical evidence state cannot be verified.

Actions:

1. Set kill switch `true` through approved environment control.
2. Stop routine Explicit ENFORCE.
3. Restart backend so the environment change is loaded.
4. Preserve all evidence; record tenant and generation.
5. Query summary, Readiness, and rollout status.
6. Do not rotate generation.
7. Investigate and remediate root cause.

New generation is allowed only after remediation, evidence review, Tech Lead
approval, and a backup checkpoint. A cleanup warning alone requires
investigation but is not automatically authority loss.

## 14. HOLD_ASSET Card

Use when authority safety is clean but zero-plan/partial weakness is explained
by small or low-diversity candidate pools:

- choose `HOLD_ASSET`;
- do not increase BPS;
- replenish assets;
- keep or reduce BPS;
- do not weaken authority thresholds;
- review at the next checkpoint.

## 15. Unattended-Hours Card

No risk-increasing changes during:

- 12:00--14:00
- 17:00--19:00
- 21:00--09:00

Do not increase BPS, tighten thresholds, change generation/lease, or expand
allowlist. Authorized risk-reducing kill, de-ramp, or BPS-zero action may occur
when needed.

## 16. Delivery Root Card

Delivery Root is a machine-global app setting and is **not authority**.

Before activation verify:

```text
GET /api/v1/settings/delivery-root

<DELIVERY_ROOT>/
  tenants/<CANONICAL_TENANT>/
    projects/_default/
```

Do not use Delivery files as TaskHistory source, backup authority, or future L3
index source. A same-machine root-path change is Change Control only while the
Two-Root contract remains intact.

## 17. Backup Card

From the installation/project root, using the current accepted CLI:

```powershell
.\venv_build\Scripts\python.exe -m src.api.backup_restore backup `
  --tenant <CANONICAL_TENANT> `
  --destination <NEW_BACKUP_DIRECTORY>

.\venv_build\Scripts\python.exe -m src.api.backup_restore verify `
  --bundle <BACKUP_ID>
```

Record:

| Evidence | Entry |
|---|---|
| Backup timestamp | `<UTC_TIMESTAMP>` |
| Backup location / identifier | `<BACKUP_ID>` |
| Verification outcome | `<VALID_OR_FAILED>` |
| Operator / verifier | `<OPERATOR>` / `<VERIFIER>` |
| Application commit/tag | `<APPLICATION_COMMIT>` / `<APPLICATION_TAG>` |

Do not perform destructive or live restore during normal activation. The only
accepted restore command targets a new isolated staging root and is governed
by `DOPAMATRIX_V15_BACKUP_RESTORE_RUNBOOK.md`.

## 18. Source-Verified Diagnostics Commands

Replace only placeholders. These GETs are read-only.

```powershell
curl.exe -H "X-Local-User: <CANONICAL_TENANT>" `
  "http://127.0.0.1:8000/api/v1/diagnostics/reservation/readiness?planning_policy=exact_main_visual_balanced"

curl.exe -H "X-Local-User: <CANONICAL_TENANT>" `
  "http://127.0.0.1:8000/api/v1/diagnostics/reservation/rollout-status?planning_policy=exact_main_visual_balanced"

curl.exe -H "X-Local-User: <CANONICAL_TENANT>" `
  "http://127.0.0.1:8000/api/v1/diagnostics/reservation/summary?window=7d"

curl.exe -H "X-Local-User: <CANONICAL_TENANT>" `
  "http://127.0.0.1:8000/api/v1/settings/delivery-root"
```

Delivery Root is global; the tenant header does not scope its stored value.
It is included in the template only to keep the operator request context
explicit.

## 19. Tenant Stagger Exit / Next-Tenant Gate

Before moving to the next tenant:

- [ ] Current tenant has a reviewed post-warmup cohort.
- [ ] No unresolved authority-safety event.
- [ ] No unresolved cleanup root cause.
- [ ] Evidence and change-control log preserved.
- [ ] Current tenant returned to zero omitted exposure.
- [ ] Next tenant completed its own backup, Delivery, assets, P1, and P2.
- [ ] New tenant activation generation approved by Tech Lead.

Never combine tenant statistics.

## 20. Execution Result

| Item | Entry |
|---|---|
| Highest state reached | `[ ] P0 [ ] P1 [ ] P2 [ ] P3-W [ ] P3-A` |
| Final decision | `[ ] KEEP [ ] RAMP [ ] DE_RAMP [ ] HOLD_ASSET [ ] KILL [ ] REBASELINE` |
| Open incidents | `<NONE_OR_REFERENCES>` |
| Evidence reviewer | `<REVIEWER>` |
| Review UTC | `<UTC_TIMESTAMP>` |
| Philippine production acceptance claimed? | **NO — requires a later executed acceptance artifact** |
