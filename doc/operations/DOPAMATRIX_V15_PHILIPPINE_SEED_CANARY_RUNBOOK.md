# DopaMatrix V1.5 Philippine Seed Canary Runbook

## Status

This document is the stable operating procedure for Phase 3D-2I-B. It has not
been executed against a real Philippine production tenant and is not evidence
of Philippine production acceptance.

Numeric and governance policy comes from
`doc/investigations/VAR001_PHASE3D2IB1C_FINAL_PHILIPPINE_SEED_POLICY_FREEZE.md`
(V1.5 PHILIPPINE SEED POLICY v1.0). Per-tenant execution evidence is captured
in `DOPAMATRIX_V15_PHILIPPINE_SEED_EXECUTION_PACK.md`.

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
`NOT_CONFIGURED` means readiness env is absent; keep omitted requests
explicit-only until 2I-B policy configures it.

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
3. Record the reviewed application commit/tag and a new rollout generation.
4. Create and independently verify a complete tenant backup using
   `DOPAMATRIX_V15_BACKUP_RESTORE_RUNBOOK.md` **before** enabling seed canary
   (allowlist / enabled / non-zero basis points / kill switch inactive).
5. Confirm the tenant's authoritative asset references are complete.
6. Confirm Reservation lease TTL and heartbeat are set to 180 and 45 seconds.
   Valid configuration requires both keys; heartbeat must not exceed one
   third of TTL.
7. Query `GET /api/v1/diagnostics/reservation/readiness?planning_policy=...`
   with header `X-Local-User: <canonical-tenant>` and record every gate.
8. Query `GET /api/v1/diagnostics/reservation/rollout-status?planning_policy=...`
   with the same header and record `state`, kill-switch implication
   (`KILL_SWITCHED`), `breakerTripped`, `rolloutGeneration`,
   `readinessState`, and `canaryBasisPoints`.
9. Query `GET /api/v1/diagnostics/reservation/summary?window=...` with the
   same header and record the minimum seed-decision fields above.
10. Confirm the tenant appears on `RESERVATION_ROLLOUT_TENANT_ALLOWLIST` and
    the selected policy has the intended basis points **only after** backup
    verification succeeded. Do not print, screenshot, commit, or paste the
    assignment secret into any artifact.

Do not enter P3-W or activate non-zero omitted Canary unless Readiness is
exactly `READY_FOR_CONTROLLED_CANARY`, backup is verified, lease configuration
is valid, no breaker is latched for the generation, the Delivery prerequisite
remains valid, and the Tech Lead activation approval is recorded.

During P1, `INSUFFICIENT_EVIDENCE` is expected while the 10/10 Explicit
ENFORCE bootstrap evidence accumulates. Kill switch `true` during P0, P1, and
P2 is intentional containment and is not a bootstrap blocker. It is disabled
last only when entering P3-W after every activation gate above passes.

## Configuration authority

All of the following are backend environment keys. Frozen values and stage
transitions are in the Execution Pack environment manifest. Rollout control
and Readiness each require their **complete** key set; a partial set is
invalid.

Lease:

- `RESERVATION_LEASE_TTL_SECONDS`
- `RESERVATION_HEARTBEAT_INTERVAL_SECONDS`

Rollout control:

- `RESERVATION_ROLLOUT_CONTROL_ENABLED`
- `RESERVATION_ROLLOUT_GENERATION`
- `RESERVATION_ROLLOUT_TENANT_ALLOWLIST`
- `RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS`
- `RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS`
- `RESERVATION_ROLLOUT_ASSIGNMENT_SECRET`
- `RESERVATION_ROLLOUT_KILL_SWITCH`
- `RESERVATION_ROLLOUT_ROLLBACK_WINDOW`
- `RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS`
- `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_DIAGNOSTIC_COVERAGE_RATE`
- `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_PLANNING_COVERAGE_RATE`
- `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_TERMINAL_COVERAGE_RATE`
- `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE`
- `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE`
- `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE`
- `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE`
- `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE`
- `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE`

Readiness (distinct keys; do not reuse the rollback-prefixed names):

- `RESERVATION_ROLLOUT_READINESS_WINDOW`
- `RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS`
- `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS`
- `RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS`
- `RESERVATION_ROLLOUT_MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE`
- `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE`
- `RESERVATION_ROLLOUT_MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE`
- `RESERVATION_ROLLOUT_MAXIMUM_ZERO_PLAN_CONFLICT_RATE`
- `RESERVATION_ROLLOUT_MAXIMUM_PARTIAL_PLAN_RATE`
- `RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE`
- `RESERVATION_ROLLOUT_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE`
- `RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE`
- `RESERVATION_ROLLOUT_MAXIMUM_CLEANUP_WARNING_RATE`

`RESERVATION_ROLLOUT_ASSIGNMENT_SECRET` is required when rollout control is
configured. Never print it, never screenshot it, never include it in
acceptance artifacts, and never commit it. Do not place an example secret in
this runbook.

Do not put these controls in an end-user request or frontend toggle. Explicit
ENFORCE requests retain their existing B2 semantics; the canary governs
omitted/default mode assignment.

Do not reuse Phase 3D-2I-A2 local test numbers (including TTL 30, heartbeat 5,
minimum ENFORCE 3, minimum conflict 1, max zero-plan 0.34, balanced 10000
basis points, or generation `v15-gate5-local-001`) as Philippine defaults.

The production `.env` is loaded once during backend startup. Although policy
loaders consult the running process environment at evaluation time, there is
no supported API that mutates or reloads those variables. After changing any
Seed environment value, perform a controlled backend restart and re-query
Readiness and rollout status. Do not assume hot reload. Delivery Root is not
an environment variable; it is the machine-global `delivery_root` app setting
managed by `GET/POST /api/v1/settings/delivery-root`.

## Seed activation sequence

Follow this order. Do not enable omitted-request canary before a verified
backup exists.

1. Select tenant and planning policy; record application commit/tag.
2. Complete backup + independent verify
   (`DOPAMATRIX_V15_BACKUP_RESTORE_RUNBOOK.md`).
3. Keep omitted traffic `DEFAULT_OFF`: Balanced bps 0 and kill switch true.
4. Confirm lease 180/45 and complete Readiness/Rollout configuration.
5. P1: Central Tech Operator submits normal diverse Explicit ENFORCE Balanced
   tasks, serial through planning, until authoritative/planning counts are at
   least 10/10. Do not manufacture contention; conflict minimum is 0.
6. P2: query summary, Readiness, and rollout-status with `X-Local-User`; every
   Readiness gate must pass and state must be `READY_FOR_CONTROLLED_CANARY`.
7. Prepare Balanced bps 3000 while kill switch remains true, restart the
   backend, and re-query evidence.
8. At the beginning of a staffed block with at least two hours remaining,
   disable the kill switch last, restart, and re-query rollout status.
9. P3-W: use ordinary omitted-mode UI work; observe `WARMING_UP`. Rollback is
   evaluated from the first Canary even though the status milestone is 5.
10. At five fully observed Canary tasks, evaluate the existing cohort before
    tightening thresholds. Do not rotate generation to hide a failing cohort.
11. P3-A: only after that review, tighten rollback zero-plan/partial/cleanup
    maxima to .30/.20/.20 in the same generation, restart, and verify.
12. Monitor summary + Readiness quality/safety fields for the 7d windows.
13. If required, set `RESERVATION_ROLLOUT_KILL_SWITCH` and prove
   `rollout-status.state=KILL_SWITCHED` and the next omitted request is
   `DEFAULT_OFF`.
14. Preserve diagnostics evidence. Restore only under the accepted backup
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
the next stage.

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
2. set `RESERVATION_ROLLOUT_KILL_SWITCH=true` through approved environment
   control;
3. perform the controlled backend restart required for environment changes;
4. re-query rollout-status and prove `state=KILL_SWITCHED`;
5. submit the next ordinary omitted-mode AI Draft → Render request and prove
   durable effective mode is `OFF` / `DEFAULT_OFF` with null rollout metadata;
6. confirm already-running work was not cancelled or rewritten;
7. record diagnostics and lifecycle outcomes (the omitted OFF task must not
   enter the ENFORCE summary cohort);
8. restore the reviewed kill-switch value only through controlled environment
   configuration and backend restart;
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
5. Introduce a new reviewed rollout generation and prove only that new
   generation can re-enter the readiness/assignment process.
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
