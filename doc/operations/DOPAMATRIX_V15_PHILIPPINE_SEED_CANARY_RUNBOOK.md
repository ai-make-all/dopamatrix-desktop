# DopaMatrix V1.5 Philippine Seed Canary Runbook

## Status

This document is the stable operating procedure for Phase 3D-2I-B. It has not
been executed against a real Philippine production tenant and is not evidence
of Philippine production acceptance.

Numeric and governance policy comes from
`doc/investigations/VAR001_PHASE3D2IB1C_FINAL_PHILIPPINE_SEED_POLICY_FREEZE.md`
(V1.5 PHILIPPINE SEED POLICY v1.0). Per-tenant execution evidence is captured
in `DOPAMATRIX_V15_PHILIPPINE_SEED_EXECUTION_PACK.md`.

The packaged operator entry is:

```text
backend.exe operator [--json] <namespace> <command> [arguments]
```

Use the installed `backend.exe`; do not substitute source-only Python module
commands. H4 state mutations require the normal server to be quiescent because
the running server holds the same runtime-mutation barrier. A successful
mutation that reports `restart_required=true` requires a controlled server
restart before the already-loaded provider sees the new snapshot. The CLI does
not perform that restart.

Product release status and a tenant's Reservation canary exposure are
separate decisions. A tenant may deliberately remain at a controlled
partial canary exposure; universal 100% Default-ON is not a V1.5 GA
requirement. Initial Balanced exposure is 3000 basis points for one active
tenant; the approved V1.5 Seed envelope is 1000--4000 basis points.

Ordinary seed-operator creative work stays:

AI Draft → Tactical Board → Render

Controlled Canary is server-side operational governance. Do not require a
customer-facing Reservation, canary, basis-point, generation, readiness,
breaker, or kill-switch UI control.

Reservation Authority (L2) coordinates concurrently active public tasks. It
is not same-batch uniqueness (L1) and is not historical duplicate prevention
(future L3). L2 does not mean a video generated yesterday cannot be generated
again.

Frozen Seed values are summarized below and fully enumerated in the Execution
Pack. Do not copy Phase 3D-2I-A2 local manual-acceptance test values into
Philippine defaults.

- qualified policy: `exact_main_visual_balanced`;
- initial Balanced / Exact exposure: 3000 / 0 basis points;
- lease TTL / heartbeat: 180 / 45 seconds;
- Readiness: 7d, minimum ENFORCE/planning/conflict 10/10/0, all coverage
  minima 1.0, quality maxima .30/.20, authority/persist/worker maxima 0,
  cleanup maximum .10;
- rollback: 7d, minimum Canary task status milestone 5;
- P3-W rollback quality/cleanup maxima 1.0, safety maxima 0, coverage 1.0;
- P3-A rollback maxima .30/.20/.20, safety maxima 0, coverage 1.0;
- no automatic ramp; serial through planning and concurrent after planning.

## Operator identity and diagnostic routes

Tenant routing for these operator APIs is the request header `X-Local-User`.
The server canonicalizes it with the same `canonical_tenant_id` used for
tenant SQLite. Do not send tenant identity as a query parameter or JSON body
field on these endpoints.

Current mounted routes (`main.py` prefix `/api/v1` + router
`/diagnostics/reservation`):

```text
GET /api/v1/diagnostics/reservation/summary?window=24h
GET /api/v1/diagnostics/reservation/readiness?planning_policy=<policy>
GET /api/v1/diagnostics/reservation/rollout-status?planning_policy=<policy>
```

`<policy>` must be exactly `exact_main_visual` or
`exact_main_visual_balanced`. `window` is optional on summary and must be one
of `1h`, `24h`, `7d`, `30d` (default `24h`).

All three GETs are read-only. They do not admit tasks, trip breakers, or
change Reservation authority.

Example (replace origin and tenant; never log secrets):

```text
curl -H "X-Local-User: <canonical-tenant>" ^
  "http://127.0.0.1:8000/api/v1/diagnostics/reservation/readiness?planning_policy=exact_main_visual_balanced"

curl -H "X-Local-User: <canonical-tenant>" ^
  "http://127.0.0.1:8000/api/v1/diagnostics/reservation/rollout-status?planning_policy=exact_main_visual_balanced"

curl -H "X-Local-User: <canonical-tenant>" ^
  "http://127.0.0.1:8000/api/v1/diagnostics/reservation/summary?window=7d"
```

The explicit `7d` in this Philippine Seed evidence example is the frozen
initial decision window. The endpoint itself continues to support `1h`,
`24h`, `7d`, and `30d`, and its omitted-window default remains `24h`.

Readiness `state` values: `NOT_CONFIGURED`, `INSUFFICIENT_EVIDENCE`,
`BLOCKED`, `READY_FOR_CONTROLLED_CANARY`.
Recommendations: `KEEP_EXPLICIT_ONLY` or
`ELIGIBLE_FOR_CONTROLLED_DEFAULT_ON_CANARY`.
`NOT_CONFIGURED` means Readiness authority is absent; keep omitted requests
explicit-only until the governed Seed workflow configures it.

Rollout-status `state` values: `DISABLED`, `NOT_ELIGIBLE`, `WARMING_UP`,
`CANARY_ACTIVE`, `KILL_SWITCHED`, `AUTO_ROLLED_BACK`.

Minimum seed-decision fields:

- summary: `enforceTaskCount`, `planningObservedTaskCount`,
  `completedTaskCount`, `failedTaskCount`, `conflictTaskCount`,
  `reservationConflictCount`, `zeroPlanConflictCount`,
  `zeroPlanConflictRate`, `partialPlanCount`, `authorityLossCount`,
  `terminalPersistFailureCount`, `workerLeaseConfigFailureCount`,
  `cleanupWarningCount`
- readiness: `state`, `recommendation`, `gates`,
  `leaseConfigurationReady`, `authoritativeEnforceTaskCount`
- rollout-status: `state`, `rolloutGeneration`, `canaryBasisPoints`,
  `readinessState`, `breakerTripped`, `breakerReason`, `canaryTaskCount`

## Preconditions

1. Select one Philippine seed tenant using a safe operator label. Only one
   tenant may have non-zero omitted Balanced Canary exposure during the
   initial stagger. Do not put
   tenant business content or task IDs in the acceptance summary.
2. Use the qualified Seed policy `exact_main_visual_balanced`.
3. Record the reviewed application commit/tag, canonical tenant, generation,
   approval/change references, operators, and approvers. `--approval-ref` is
   external metadata; it is not authentication and is not stored as a second
   tenant or generation authority.
4. With the server quiescent, explicitly provision an approved tenant when it
   does not already exist:

   ```text
   backend.exe operator tenant provision --tenant <canonical-tenant> --approval-ref <reference>
   ```

   Provisioning is not implicit in status or Seed commands. Only the three
   approved Philippine tenant IDs are accepted.
5. Establish contained initial state with:

   ```text
   backend.exe operator seed apply-safe-off --tenant <canonical-tenant> --generation <generation> --approval-ref <reference>
   ```

   Initial SAFE_OFF uses Balanced/Exact `0/0`, kill `true`, rollback `7d`, and
   lease `180/45` unless the reviewed paired lease profile `300/60` is
   explicitly selected. If the Assignment Secret is absent it is generated
   locally and stored under DPAPI CurrentUser. Operators may observe only
   `PRESENT`, `ABSENT`, or `ERROR`; never record Secret material.
6. Perform the controlled restart required after an applied SAFE_OFF mutation,
   then record packaged read-only status:

   ```text
   backend.exe operator config status
   backend.exe operator seed status --tenant <canonical-tenant>
   backend.exe operator secret assignment status
   ```

7. Create and independently verify a complete tenant backup **before**
   enabling Seed Canary:

   ```text
   backend.exe operator backup create --tenant <canonical-tenant> --destination <absolute-new-directory>
   backend.exe operator backup verify --bundle <absolute-bundle>
   ```

   The destination must be new, absolute, and outside RuntimePaths, internal
   output, and Delivery. Commands that require a backup synchronously reverify
   the bundle and its tenant; the backup is not Assignment Secret recovery.
   Restore remains governed by
   `DOPAMATRIX_V15_BACKUP_RESTORE_RUNBOOK.md` and is not exposed by H4.
8. Confirm Delivery Root and the tenant's authoritative asset references are
   complete. Delivery remains the machine-global `delivery_root` app setting,
   not backup or TaskHistory authority.
9. Query `GET /api/v1/diagnostics/reservation/readiness?planning_policy=...`
   with header `X-Local-User: <canonical-tenant>` and record every gate.
10. Query `GET /api/v1/diagnostics/reservation/rollout-status?planning_policy=...`
   with the same header and record `state`, kill-switch implication
   (`KILL_SWITCHED`), `breakerTripped`, `rolloutGeneration`,
   `readinessState`, and `canaryBasisPoints`.
11. Query `GET /api/v1/diagnostics/reservation/summary?window=...` with the
   same header and record the minimum seed-decision fields above.
12. Confirm packaged Seed status names the intended single tenant, generation,
    kill state, Exact `0`, and reviewed Balanced basis points only after backup
    verification succeeded. Do not print, screenshot, commit, or paste the
    Assignment Secret into any artifact.

Do not enter P3-W or activate non-zero omitted Canary unless Readiness is
exactly `READY_FOR_CONTROLLED_CANARY`, backup is verified, lease configuration
is valid, no breaker is latched for the generation, the Delivery prerequisite
remains valid, and the Tech Lead activation approval is recorded.

During P1, `INSUFFICIENT_EVIDENCE` is expected while the 10/10 Explicit
ENFORCE bootstrap evidence accumulates. Kill switch `true` during P0, P1, and
P2 is intentional containment and is not a bootstrap blocker. It is disabled
last only when entering P3-W after every activation gate above passes.

## Packaged operator authority

Read-only evidence commands are separate from mutation:

```text
backend.exe operator config status
backend.exe operator seed status --tenant <canonical-tenant>
backend.exe operator secret assignment status
backend.exe operator backup verify --bundle <absolute-bundle>
```

Status does not provision a tenant, initialize absent storage, acquire the
mutation barrier, or reload a running provider. An active SQLite WAL may cause
status to fail closed rather than mutate or return stale data; preserve the
bounded error as evidence and resolve it through the controlled lifecycle, not
by editing sidecars.

Governed mutation commands are:

```text
backend.exe operator tenant provision ...
backend.exe operator seed apply-safe-off ...
backend.exe operator seed prearm-p3w ...
backend.exe operator seed activate ...
backend.exe operator seed kill ...
backend.exe operator seed set-balanced-bps ...
backend.exe operator seed transition-p3a --rollback-window 7d ...
backend.exe operator secret assignment rotate ...
```

Run mutations only while the normal server is quiescent. Successful writes
report whether restart is required; they do not restart the server. After a
successful state mutation, perform a controlled restart and re-query packaged
status plus the read-only diagnostic routes before admitting work.

P3-W preparation uses `seed prearm-p3w` with a currently valid tenant-matched
backup. It prepares Balanced `3000`, Exact `0`, and kill `true`. Activation is
a separate `seed activate` command and disables kill last only after external
Readiness, Delivery, breaker, staffed-block, backup, and human-approval gates
all pass. Containment uses `seed kill`; do not edit a raw kill value.

Routine contained Balanced changes use `seed set-balanced-bps`. Values remain
inside `1000--4000` and may move by at most `1000` at each three-day reviewed
checkpoint. There is no automatic ramp. P3-A tightening uses
`seed transition-p3a --rollback-window 7d`; raw rollback-threshold editing is
not an operator procedure. `P3_A/24h` transition/activation is not currently
machine-authorized by H4-6, so this runbook intentionally provides no working
24-hour transition recipe.

Assignment Secret rotation is separate from ordinary Seed mutation:

```text
backend.exe operator secret assignment rotate --tenant <canonical-tenant> --expected-generation <old-generation> --new-generation <new-generation> --backup-bundle <absolute-bundle> --approval-ref <reference>
```

Rotation requires containment (`kill=true`), a valid tenant-matched backup,
an existing decryptable Secret, and a different valid generation. It creates
the new Secret locally, atomically binds the new generation, remains killed,
and requires restart. It is an incident/change-control operation, not a
routine cohort reset, recovery/export mechanism, or way to hide a failing
cohort.

Do not put these controls in an end-user request or frontend toggle. Explicit
ENFORCE requests retain their existing B2 semantics; the canary governs
omitted/default mode assignment. Do not reuse Phase 3D-2I-A2 local test values
as Philippine defaults.

Packaged production does not bundle, search or load a `.env` file. Packaged
configuration authority is limited to RuntimePaths, the global database, the
versioned operational profile/snapshot, DPAPI secure settings and reviewed
fixed defaults. Delivery Root remains the machine-global `delivery_root` app
setting managed by `GET/POST /api/v1/settings/delivery-root`.
Source-development environment adapters are not packaged field authority.

## Seed activation sequence

Follow this order. Do not enable omitted-request canary before a verified
backup exists.

1. Select tenant and planning policy; record application commit/tag,
   generation, approval/change references, operators, and approvers.
2. Quiesce the server. Provision the approved tenant explicitly if required,
   then apply SAFE_OFF. An exact repeat may return `ALREADY_APPLIED` without
   rewriting state or rotating the Secret.
3. Complete the controlled restart and capture `config status`, tenant
   `seed status`, and Assignment Secret status (`PRESENT` only, never value).
4. Create and independently verify the packaged backup. Keep omitted traffic
   `DEFAULT_OFF`: Balanced bps 0 and kill switch true.
5. Confirm Delivery, lease 180/45, diagnostics, staffing, and human approvals.
6. P1: Central Tech Operator submits normal diverse Explicit ENFORCE Balanced
   tasks, serial through planning, until authoritative/planning counts are at
   least 10/10. Do not manufacture contention; conflict minimum is 0.
7. P2: query summary, Readiness, and rollout-status with `X-Local-User`; every
   Readiness gate must pass and state must be `READY_FOR_CONTROLLED_CANARY`.
8. Quiesce the server and run `seed prearm-p3w` with the verified bundle. It
   prepares Balanced 3000 while kill remains true. Restart and re-query.
9. At the beginning of a staffed block with at least two hours remaining,
   quiesce the server and run `seed activate` with the reverified bundle.
   Activation disables kill last. Restart and re-query rollout status.
10. P3-W: use ordinary omitted-mode UI work; observe `WARMING_UP`. Rollback is
   evaluated from the first Canary even though the status milestone is 5.
11. At five fully observed Canary tasks, evaluate the existing cohort before
    tightening thresholds. Do not rotate generation to hide a failing cohort.
12. P3-A: only after that review, quiesce the server and run
    `seed transition-p3a --rollback-window 7d` with the verified bundle.
    Restart, verify the .30/.20/.20 post-warmup thresholds, and activate
    separately only after all gates pass again.
13. Monitor summary + Readiness quality/safety fields for the 7d windows.
14. Routine contained BPS changes use `seed set-balanced-bps`, a reverified
    bundle, the 1000--4000 envelope, and the ±1000/three-day policy.
15. If containment is required, quiesce the server, run `seed kill`, perform
    the controlled restart, and prove `rollout-status.state=KILL_SWITCHED`
    and the next omitted request is `DEFAULT_OFF`.
16. Preserve diagnostics evidence. Restore only under the accepted backup
    contract; do not treat restore-to-staging as live-tenant overwrite.

## Initial stage and observation

Initial Balanced exposure is 3000 basis points. Later values must remain in
the 1000--4000 envelope and move by at most 1000 basis points per three-day
review. No stage is automatic and 100% Default-ON is not required. Before
every increase, an operator reviews and signs the current evidence.

For each observation period, record at least:

- total admitted and authoritative ENFORCE task counts;
- diagnostic, planning, and terminal observation coverage;
- Reservation conflict attempts and conflict-task rate;
- zero-plan conflict rate;
- partial-plan rate;
- authority-loss rate;
- terminal-persistence-failure rate;
- worker lease-configuration-failure rate;
- cleanup-warning rate;
- readiness state and every failed/unknown gate;
- breaker state and reason;
- task lifecycle anomalies, SQLite lock errors, and heartbeat/thread leaks.

Use the configured readiness/rollback windows. Do not cherry-pick only healthy
minutes or infer safety from a small denominator.

## Ramp decision

An operator may increase the stage only when:

1. the three-day review checkpoint is reached and the relevant cohort is
   fully observed;
2. required evidence counts and coverage pass;
3. all safety rates remain within configured thresholds;
4. no unexplained authority loss, terminal persistence failure, lock residue,
   or stuck task exists;
5. the breaker is not latched and the kill switch is inactive;
6. the prior backup remains verified or a newer verified backup exists.

Record the decision and approver. A healthy stage does not schedule or imply
the next stage. Apply an approved contained change with
`seed set-balanced-bps`, then perform the required controlled restart and
post-change status/diagnostic checks.

## Rollback conditions

Stop ramping and place omitted requests in OFF when any configured breaker
condition is met, readiness is lost, lease configuration becomes invalid,
authority loss or terminal persistence failure is unexplained, task lifecycle
truth becomes inconsistent, or operators cannot verify diagnostics.

Already-running tasks are not cancelled by the rollout control. Explicit
ENFORCE remains the existing public B2 contract. Incident response must not
rewrite Reservation authority, Ledger occurrences, or TaskHistory.

## Kill-switch drill

For a real Seed drill while Readiness is healthy and an omitted request would
otherwise be selected for ENFORCE:

1. record current `GET /api/v1/diagnostics/reservation/rollout-status`;
2. quiesce the server and run:

   ```text
   backend.exe operator seed kill --tenant <canonical-tenant> --generation <generation> --reason-code <approved-code>
   ```

3. perform the controlled backend restart required by the successful
   mutation; `restart_required=true` does not mean the CLI restarted it;
4. re-query rollout-status and prove `state=KILL_SWITCHED`;
5. submit the next ordinary omitted-mode AI Draft → Render request and prove
   durable effective mode is `OFF` / `DEFAULT_OFF` with null rollout metadata;
6. confirm already-running work was not cancelled or rewritten;
7. record diagnostics and lifecycle outcomes (the omitted OFF task must not
   enter the ENFORCE summary cohort);
8. reactivation, if approved, uses the separate backup-backed
   `seed activate` command only after all external gates pass again;
9. re-query Readiness and rollout-status before further Canary work.

The kill switch factually does not govern Explicit ENFORCE. Do not submit a
new Explicit ENFORCE task solely to re-demonstrate that bypass during a real
P3 Seed drill: such a bypass drill is `STAGING_OR_SYNTHETIC_ONLY`. On a real
production incident, Explicit ENFORCE is permitted only as a documented
diagnosis/incident exception approved by the Tech Lead under the 1C policy.

## Breaker / rollback drill

Use staging or synthetic evidence only. Do not inject rollback failures into
real Philippine creative work.

1. Configure controlled evidence that crosses one existing rollback threshold.
2. Prove the breaker latches for the current policy and generation.
3. Prove future omitted requests resolve to OFF.
4. Restore healthy metrics and prove that recovery does not auto-rearm.
5. Only after remediation, backup verification, containment, and independent
   approval, use the separate `secret assignment rotate` incident workflow
   for a new generation. Prove only that reviewed generation can re-enter the
   readiness/assignment process; rotation is not routine breaker reset.
6. Record reason code, timestamps, observations, and operator decision without
   recording assignment secrets or raw HMAC material.

## Restart drill

Perform this drill on real Seed only after all active tasks are drained;
otherwise use staging.

1. Record rollout generation, breaker status, and current diagnostic counts.
2. Restart the application normally.
3. Confirm the tenant DB and TaskHistory remain readable.
4. Confirm a latched breaker remains latched and rollout does not silently
   reset or auto-rearm.
5. Re-run `GET /api/v1/diagnostics/reservation/readiness` and
   `GET /api/v1/diagnostics/reservation/rollout-status` with `X-Local-User`.
6. Verify a backup bundle and confirm authoritative asset paths still resolve.
7. Confirm no old Reservation heartbeat or owner-attempt identity is resumed.

## Incident notes

For every anomaly record UTC time, safe tenant label, application commit/tag,
planning policy, rollout generation, stage, aggregate metrics, breaker/kill
switch state, bounded error codes, containment action, and operator decision.
Do not include prompt text, raw creative content, assignment secrets, HMAC
values, owner-attempt IDs, or tenant database paths.

## Exit criteria for Phase 3D-2I-B

- backup-before-canary and independent verification succeeded;
- readiness and configured evidence gates remained satisfied;
- the selected manual stage completed its observation period;
- the safe real-Seed kill-switch drill and controlled post-drain restart drill
  produced expected behavior; destructive breaker/fault evidence remains
  staging or synthetic;
- no unresolved authority, terminal persistence, task lifecycle, SQLite lock,
  heartbeat, or cleanup defect remains;
- evidence is recorded in the seed acceptance template and independently
  reviewed.

Local automated tests and this runbook do not satisfy these production exit
criteria.
