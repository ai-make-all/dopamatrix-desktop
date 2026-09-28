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
| Application tag / release identifier | `<APPLICATION_TAG_OR_RELEASE>` |
| Execution date | `<EXECUTION_DATE>` |
| Staffed block | `<STAFFED_BLOCK>` |
| Selected canonical tenant | `<CANONICAL_TENANT>` |
| Tenant business type | `[ ] elevator  [ ] beauty  [ ] villa / water-heating` |
| Tech Lead | `<TECH_LEAD>` |
| Execution operator | `<OPERATOR>` |
| Current generation | `<GENERATION>` |
| Approval/change references | `<APPROVAL_OR_CHANGE_REFERENCES>` |
| Tenant provision result | `<PROVISIONED_OR_EXISTING_WITH_EVIDENCE>` |
| Config status | `<STATUS_OR_BOUNDED_ERROR>` |
| Seed status | `<STATUS_OR_BOUNDED_ERROR>` |
| Assignment Secret status | `[ ] PRESENT  [ ] ABSENT  [ ] ERROR` |
| SAFE_OFF apply result | `<APPLIED_OR_ALREADY_APPLIED>` |
| Controlled restart completed after SAFE_OFF | `[ ] YES  [ ] NO` |
| Delivery Root | `<DELIVERY_ROOT>` |
| Delivery verification | `[ ] PASS  [ ] FAIL` |
| Backup create result/path | `<RESULT>` / `<ABSOLUTE_BUNDLE>` |
| Backup verification result | `[ ] VALID  [ ] FAILED` |
| P3-W prearm result | `<RESULT_OR_NOT_RUN>` |
| Activation result | `<RESULT_OR_NOT_RUN>` |
| Kill containment result | `<RESULT_OR_NOT_RUN>` |
| Balanced BPS change result | `<RESULT_OR_NOT_RUN>` |
| P3-A / 7d transition result | `<RESULT_OR_NOT_RUN>` |
| Secret rotation incident/change record | `<OLD_GENERATION>` → `<NEW_GENERATION>` / `<REFERENCE>` |
| Post-rotation restart completed | `[ ] YES  [ ] NO  [ ] NOT_APPLICABLE` |
| Diagnostic evidence identifier | `<EVIDENCE_REFERENCE>` |

Never add an Assignment Secret value, length, hash, prefix, suffix, ciphertext,
DPAPI blob, or HMAC intermediate to this pack. Only
`PRESENT`/`ABSENT`/`ERROR` is permitted. Generation must match:

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
- [ ] Approval/change references and responsible humans recorded.
- [ ] Server quiesced before each mutation command.
- [ ] Approved tenant explicitly provisioned with
  `backend.exe operator tenant provision`, or existing-tenant evidence
  independently confirmed.
- [ ] `seed apply-safe-off` returned `APPLIED` or exact no-write
  `ALREADY_APPLIED`.
- [ ] Assignment Secret status recorded only as `PRESENT`, `ABSENT`, or
  `ERROR`; no Secret material recorded.
- [ ] Controlled backend restart completed after an applied mutation.
- [ ] `config status` and tenant `seed status` recorded separately as
  read-only evidence.
- [ ] Packaged tenant backup completed to a new absolute destination outside
  RuntimePaths, internal output, and Delivery.
- [ ] Packaged `backup verify` independently returned `VALID`.
- [ ] Delivery Root configured and GET-confirmed.
- [ ] Derived tenant path verified:
  `<DELIVERY_ROOT>/tenants/<CANONICAL_TENANT>/projects/_default/`.
- [ ] Two-Root boundary confirmed: internal `output/` remains authority.
- [ ] Packaged Seed projection confirms lease `180/45`, Exact bps `0`,
  Balanced bps `0`, kill `true`, one tenant, and reviewed generation.
- [ ] Readiness endpoint returns a bounded non-error response.
- [ ] Rollout-status endpoint returns a bounded non-error response.
- [ ] Summary endpoint returns a bounded non-error response.
- [ ] Ordinary omitted traffic remains `DEFAULT_OFF`.
- [ ] No unresolved task, DB, lease, cleanup, or authority incident.
- [ ] Selected staffed block leaves at least two staffed hours after activation.

Backup timestamp: `<UTC_TIMESTAMP>`

Backup operator / independent verifier: `<OPERATOR>` / `<VERIFIER>`

P0 result: `[ ] PASS  [ ] STOP`

## 4. Packaged Operator Evidence Manifest

Every mutation requires server quiescence because the running server holds the
H4 mutation barrier. `restart_required=true` means a controlled restart must
follow; it does not mean the CLI performed one.

| Checkpoint | Packaged command / evidence | Result | Exit | Approval/change reference | Restart completed? |
|---|---|---|---:|---|---|
| Tenant provision | `backend.exe operator tenant provision --tenant <TENANT> --approval-ref <REF>` | `<RESULT>` | `<EXIT>` | `<REF>` | N/A |
| Config status | `backend.exe operator config status` | `<STATUS_OR_ERROR>` | `<EXIT>` | N/A | N/A |
| Seed status | `backend.exe operator seed status --tenant <TENANT>` | `<STATUS_OR_ERROR>` | `<EXIT>` | N/A | N/A |
| Assignment Secret status | `backend.exe operator secret assignment status` | `<PRESENT_ABSENT_ERROR>` | `<EXIT>` | N/A | N/A |
| SAFE_OFF | `backend.exe operator seed apply-safe-off --tenant <TENANT> --generation <GENERATION> --approval-ref <REF>` | `<APPLIED_OR_ALREADY_APPLIED>` | `<EXIT>` | `<REF>` | `[ ]` |
| Backup create | `backend.exe operator backup create --tenant <TENANT> --destination <ABSOLUTE_NEW_DIRECTORY>` | `<RESULT_AND_PATH>` | `<EXIT>` | `<CHANGE_REF>` | N/A |
| Backup verify | `backend.exe operator backup verify --bundle <ABSOLUTE_BUNDLE>` | `<VALID_OR_ERROR>` | `<EXIT>` | `<VERIFIER>` | N/A |
| P3-W prearm | `backend.exe operator seed prearm-p3w --tenant <TENANT> --generation <GENERATION> --backup-bundle <BUNDLE> --approval-ref <REF>` | `<RESULT>` | `<EXIT>` | `<REF>` | `[ ]` |
| Activate | `backend.exe operator seed activate --tenant <TENANT> --generation <GENERATION> --backup-bundle <BUNDLE> --approval-ref <REF>` | `<RESULT>` | `<EXIT>` | `<REF>` | `[ ]` |
| Kill containment | `backend.exe operator seed kill --tenant <TENANT> --generation <GENERATION> --reason-code <CODE>` | `<RESULT>` | `<EXIT>` | `<INCIDENT_REF>` | `[ ]` |
| Balanced BPS | `backend.exe operator seed set-balanced-bps --tenant <TENANT> --generation <GENERATION> --bps <N> --backup-bundle <BUNDLE> --approval-ref <REF>` | `<RESULT>` | `<EXIT>` | `<REF>` | `[ ]` |
| P3-A / 7d | `backend.exe operator seed transition-p3a --tenant <TENANT> --generation <GENERATION> --rollback-window 7d --backup-bundle <BUNDLE> --approval-ref <REF>` | `<RESULT>` | `<EXIT>` | `<REF>` | `[ ]` |

The paired lease profiles remain indivisible: `180/45` or reviewed `300/60`.
P3-W is Balanced `3000`, Exact `0`, kill `true`. P3-A / 7d retains the frozen
coverage/safety thresholds and tightens zero-plan/partial/cleanup to
`.30/.20/.20`. `P3_A/24h` is not machine-authorized through H4-6 and has no
working operator recipe in this pack.

### Assignment Secret rotation incident/change record

| Field | Entry |
|---|---|
| Tenant | `<CANONICAL_TENANT>` |
| Old generation | `<OLD_GENERATION>` |
| New generation | `<NEW_GENERATION>` |
| Verified backup bundle | `<ABSOLUTE_BUNDLE>` |
| Approval/change reference | `<REFERENCE>` |
| Rotation result | `<ROTATED_OR_BOUNDED_ERROR>` |
| Kill containment confirmed | `[ ] true` |
| Assignment Secret status | `[ ] PRESENT  [ ] ABSENT  [ ] ERROR` |
| `restart_required` | `<true_or_false>` |
| Controlled post-rotation restart completed | `[ ] YES  [ ] NO` |

Rotation is contained, backup-backed, and new-generation only. It is not
routine cohort reset, Secret recovery/export/import, or permission to record
Secret material.

## 5. Packaged Mutation / Restart Procedure

For SAFE_OFF, prearm, activation, containment, BPS change, P3-A / 7d, or
Secret rotation:

1. Record tenant, generation, exact packaged command, approval/change
   reference, operator, approver, and pre-change evidence.
2. Verify the command's required backup with packaged `backup verify`.
   Backup-bearing mutation commands reverify it again synchronously.
3. Drain active work and quiesce the normal server.
4. Run the one reviewed packaged mutation command.
5. Record exact exit, bounded status/error, and `restart_required`.
6. For a successful write, perform the controlled backend restart; there is
   no supported hot reload and the CLI did not restart it.
7. Query packaged status separately, then Readiness, rollout status, and
   summary.
8. If activation is intended, use separate `seed activate` only after all
   external gates pass, then restart and re-query before omitted traffic.
9. Record the post-change result in the Change-Control Log.

Packaged production does not bundle, search or load a `.env` file. Packaged
configuration authority is limited to RuntimePaths, the global database, the
versioned operational profile/snapshot, DPAPI secure settings and reviewed
fixed defaults. Delivery Root remains an existing reviewed machine setting.
Source-development environment adapters are not packaged field authority.

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
- [ ] Packaged Seed status confirms kill remains `true`.
- [ ] Packaged Seed status confirms generation `<GENERATION>`.
- [ ] Packaged Seed status confirms only `<CANONICAL_TENANT>`.
- [ ] Exact bps is `0`; Balanced bps is `0`, or P3-W prearm has prepared
  `3000` while kill remains `true`.
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

1. [ ] Re-run packaged `backup verify`; record `VALID`.
2. [ ] Confirm Delivery Root and tenant subtree remain valid.
3. [ ] Confirm `<CANONICAL_TENANT>` and `<GENERATION>`.
4. [ ] Confirm Readiness is READY.
5. [ ] Confirm breaker is not latched.
6. [ ] Confirm Exact bps is 0.
7. [ ] Quiesce the server and run packaged `seed prearm-p3w` with the verified
   bundle and approval reference.
8. [ ] Record Balanced bps 3000, Exact 0, and kill `true` from the result.
9. [ ] Complete the controlled backend restart required by prearm.
10. [ ] Re-query Readiness and rollout status.
11. [ ] Verify rollout state is `KILL_SWITCHED` and omitted traffic remains OFF.
12. [ ] Quiesce the server and run packaged `seed activate` with the verified
    bundle **last**.
13. [ ] Complete the controlled backend restart required by activation.
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
- [ ] Reverify the backup bundle.
- [ ] Quiesce the server and run packaged
  `seed transition-p3a --rollback-window 7d`.
- [ ] Record rollback zero-plan `.30`, partial `.20`, cleanup `.20`; safety
  maxima remain `0` and coverage minima remain `1.0`.
- [ ] Complete the controlled restart while kill remains true.
- [ ] Re-query, then use separate packaged `seed activate` only after all
  gates pass again; restart after activation.
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

| Old | New | Packaged command result | Reason | Operator | Approval | Restart complete | Post-change staffed observation |
|---:|---:|---|---|---|---|---|---|
| `<BPS>` | `<BPS>` | `<RESULT>` | `<REASON>` | `<OPERATOR>` | `<TECH_LEAD_OR_NA>` | `[ ]` | `<RESULT>` |

Rules: remain within 1000--4000; move by at most 1000 per review; no
automatic ramp; KEEP is preferred when 5--10 fully observed tasks/7d are
healthy.

## 12. Change-Control Log

Never place secret values in this table.

| Timestamp | Tenant | Generation | Packaged command / governed change | Old projection | New projection | Reason | Pre-change evidence | Operator | Approver | `restart_required` | Restart completed | Post-change check | Result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `<UTC>` | `<CANONICAL_TENANT>` | `<GENERATION>` | `<COMMAND_OR_DELIVERY_CHANGE>` | `<OLD>` | `<NEW>` | `<REASON>` | `<EVIDENCE>` | `<OPERATOR>` | `<APPROVER>` | `<true_false_NA>` | `[ ]` | `<CHECK>` | `<RESULT>` |

Successful Seed/Secret mutations require controlled restart before the loaded
provider sees the new snapshot. Delivery Root uses its app-setting API and
does not itself require backend restart.

## 13. KILL / Safety Card

Immediate `KILL` conditions:

- authority-loss count > 0;
- terminal-persist-failure count > 0;
- worker-config-failure count > 0;
- critical evidence state cannot be verified.

Actions:

1. Stop routine Explicit ENFORCE and quiesce the server.
2. Run packaged `seed kill --tenant <TENANT> --generation <GENERATION>
   --reason-code <CODE>`.
3. Complete the controlled backend restart required by containment.
4. Preserve all evidence; record tenant and generation.
5. Query summary, Readiness, and rollout status.
6. Do not rotate generation.
7. Investigate and remediate root cause.

New generation is allowed only after remediation, evidence review, Tech Lead
approval, containment, and a verified backup checkpoint, using the separate
`secret assignment rotate` incident workflow. It is not a routine cohort or
breaker reset. A cleanup warning alone requires investigation but is not
automatically authority loss.

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

Do not increase BPS, tighten thresholds, change generation/lease, or change
the active tenant selection. Authorized risk-reducing kill, de-ramp, or
BPS-zero action may occur when needed.

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

Using the installed packaged backend:

```powershell
.\backend.exe operator backup create `
  --tenant <CANONICAL_TENANT> `
  --destination <NEW_BACKUP_DIRECTORY>

.\backend.exe operator backup verify `
  --bundle <ABSOLUTE_BUNDLE>
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
