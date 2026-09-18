# VAR-001 Phase 3D-2I-B-1C
# Final Philippine Seed Policy Freeze

Policy version: **V1.5 PHILIPPINE SEED POLICY v1.0**

## 1. Executive Freeze

The Philippine V1.5 Seed policy is frozen for a staggered, one-tenant-at-a-time
Controlled Canary of `exact_main_visual_balanced`.

The initial Canary exposure is **3000 basis points** for the one active tenant.
`exact_main_visual` remains at **0 basis points**. The lease profile is
**180 / 45 seconds**, Readiness uses a **7-day** cohort with **10** authoritative
ENFORCE and **10** planning-observed tasks, and the initial rollback window is
**7 days**. Canary warmup keeps quality and cleanup rollback maxima at `1.0`
until five fully observed Canary tasks exist, while authority-loss,
terminal-persist-failure, and worker-config-failure remain zero-tolerance from
the first Canary.

This freeze resolves the small-denominator and evidence-starvation hazards from
the 1B technical challenge without changing source architecture. It is a Seed
operating constitution, not Philippine production acceptance, V1.5 GA
authorization, universal Default-ON approval, blind-fission qualification, or
an L3 implementation.

No current-source contradiction was found.

## 2. Scope

This policy governs the initial Philippine Seed use of:

- AI Draft -> Tactical Board -> `exact_main_visual_balanced` -> L1 -> L2
  Reservation -> Controlled Canary;
- three initial tenants, activated sequentially;
- server-side omitted-request assignment only;
- the existing Readiness, Rollout, breaker, kill-switch, Reservation, and
  diagnostics contracts;
- the accepted Two-Root Delivery model.

It does not modify code, tests, SQLite, environment, Vue, or the operator
runbook. Current source and test contracts take precedence over this document
if a future source change makes any statement stale; such a change is a
rebaseline trigger.

## 3. Authoritative Operator Facts

| Fact | Frozen input |
|---|---|
| Initial tenants | 3: elevator, beauty, villa/water-heating |
| Final rendered output volume | 10--30 videos/day/tenant |
| Public Matrix task volume | Must be measured; rough estimate only is 2.5--7.5/day when batch size 4 fills |
| Typical batch size | 4 |
| Candidate pools | Initially small; operators replenish continuously |
| Operators | 3 total; usually only 1 concurrently active |
| Peak public-task concurrency | Approximately 5, mainly consecutive submissions by one operator |
| Staffed hours | 09:00--12:00, 14:00--17:00, 19:00--21:00 |
| Unattended hours | 12:00--14:00, 17:00--19:00, 21:00--09:00 |
| Host | 24-hour always-on; sleep is not expected |
| Manual kill-switch SLA | Greater than 2 hours; no guaranteed overnight response |
| Human review cadence | Every 3 days |
| Assignment-secret custodian | Tech Lead |
| Generation approver | Tech Lead |

Rendered Outputs/day is not interchangeable with public Matrix Tasks/day.
Operations must record public tasks/day, rendered outputs/day, and successful
outputs/public task separately.

## 4. Freeze Philosophy

The policy has four layers:

1. **Immutable safety rules**: authority, durability, identity, containment,
   evidence preservation, and no automatic ramp.
2. **Initial Seed values**: the first production-like operating point.
3. **Approved adjustment envelope**: controlled changes that do not require a
   new 1A/1B/1C cycle.
4. **Rebaseline triggers**: assumption or source changes that require a narrow
   policy review before proceeding.

A three-day review is a checkpoint, not a deadline to ramp. Evidence, not
elapsed time, controls the decision.

## 5. V1.5 Qualified Product Path

Qualified path:

```text
AI Draft
  -> Tactical Board
  -> exact_main_visual_balanced
  -> L1 same-batch uniqueness
  -> L2 cross-task Reservation Authority
  -> server-side Controlled Canary
```

Ordinary Vue submissions omit `reservation_conflict_mode`. The server may
promote an eligible omitted request to `ROLLOUT_CANARY` / `ENFORCE`. There is
no customer-facing Reservation or Canary control.

`exact_main_visual` automatic Canary starts and remains at 0 bps under this
initial policy. Legacy blind fission is a `DEFAULT_OFF` compatibility path and
is not qualified by this Seed. V1.5 release is not blocked on integrating that
legacy path with Balanced planning.

## 6. Immutable Safety Rules

1. A verified tenant backup exists before Balanced omitted Canary bps becomes
   non-zero.
2. The machine-global Delivery Root and the tenant-derived Delivery subtree
   are verified before activation; Delivery remains a non-authoritative copy.
3. Internal `<project-root>/output/`, TaskHistory, Fingerprint records, and the
   tenant backup remain authoritative.
4. L2 is concurrent authority, not historical deduplication.
5. Authority loss, terminal persistence failure, and worker lease-config
   failure have maximum rate 0 from the first Canary.
6. Any such safety event is a `KILL` classification. The automatic breaker is
   retained, and staffed operators also activate the kill switch immediately.
7. Routine Explicit ENFORCE stops after P3 starts. It is allowed only for
   documented technical diagnosis with Tech Lead approval.
8. No automatic BPS ramp and no requirement to reach 100% Default-ON in V1.5.
9. Unfavorable evidence is never erased by cosmetic generation rotation.
10. One tenant at a time may have non-zero omitted Balanced Canary exposure
    during the initial stagger.
11. Early Seed is **serial through planning, concurrent after planning** while
    diagnostic/planning coverage minima remain 1.0.
12. Risk-increasing changes occur only at the beginning of a staffed block
    with at least two staffed hours remaining.

## 7. Seed Operational Prerequisites

Before P1 and again before P3-W:

- record the reviewed application commit/tag;
- select one canonical tenant using backup quality, Delivery verification,
  asset readiness, and stable operator ownership, not a permanently frozen
  business-name priority;
- complete and independently verify the accepted V1.5 tenant backup;
- configure and verify the lease profile;
- configure the complete Readiness key set;
- configure the complete Rollout key set without exposing the assignment
  secret;
- verify Delivery Root persistence and
  `<root>/tenants/<canonical-tenant>/projects/_default/` isolation;
- confirm omitted traffic remains `DEFAULT_OFF` during P0--P2;
- prove no unresolved task lifecycle, SQLite lock, heartbeat, cleanup, or
  authority defect;
- preserve summary, Readiness, and rollout-status evidence.

Delivery Root is a prerequisite, not a Canary policy variable. One global root
is allowed; the tenant directory is derived automatically.

## 8. Tenant Activation

Only one tenant may be present in the active non-zero Canary allowlist during
the initial stagger. Other tenants remain at Balanced bps 0 / `DEFAULT_OFF`,
may replenish assets, and may prepare backups, Delivery paths, and P1 evidence.

Before advancing to the next tenant, the current tenant must have at least one
reviewed post-warmup cohort, no unresolved authority-safety event, no
unresolved cleanup root cause, and preserved evidence. Statistics are never
combined across tenant databases.

Changing to the next tenant is controlled activation: place the current
tenant back at zero omitted exposure, preserve its evidence, select the next
canonical tenant, and issue that tenant's approved generation name. It is not
a rebaseline while the one-at-a-time model and all other assumptions hold.

## 9. P0–P3 State Machine

| State | Entry condition | Allowed actions | Forbidden actions | Exit condition |
|---|---|---|---|---|
| **P0 BACKUP_AND_OFF** | Tenant selected; omitted traffic demonstrably OFF | Verify backup, Delivery Root, tenant isolation, lease, configs, asset readiness; keep kill switch true and Balanced bps 0 | Non-zero omitted Canary; real fault injection; customer controls | All prerequisites independently verified |
| **P1 EXPLICIT_ENFORCE_BOOTSTRAP** | P0 complete; Central Tech Operator owns submissions | Submit normal diverse production-like Explicit ENFORCE tasks; serialize through planning; collect at least 10 authoritative and 10 planning-observed tasks | Manufactured same-FP contention; ordinary operator ENFORCE; omitted Canary | Readiness evidence is complete and reviewed |
| **P2 READY** | Readiness is exactly `READY_FOR_CONTROLLED_CANARY`; backup and Delivery remain valid | Review every gate; prepare BPS/generation record; set non-zero BPS while kill switch remains true; query status | Canary activation when any gate is unknown/failed, breaker latched, or evidence unresolved | Tech Lead approves activation at start of staffed block |
| **P3-W CANARY_WARMUP** | Kill switch is disabled last; Balanced 3000 bps; one tenant; warmup rollback thresholds active | Ordinary omitted UI traffic; serial through planning; monitor every task; KEEP/DE_RAMP/HOLD_ASSET/KILL | Routine Explicit ENFORCE; quality/cleanup threshold tightening without cohort review; unattended risk increase | At least 5 fully observed Canary tasks and pre-change cohort review supports tightening |
| **P3-A CANARY_ACTIVE** | Five-task review passed; same-generation post-warmup thresholds installed | KEEP/RAMP/DE_RAMP/HOLD_ASSET within envelope; three-day review | Automatic ramp; evidence-reset rotation; second simultaneous tenant | Continue within envelope, KILL, or REBASELINE |

The source may report `CANARY_ACTIVE` immediately when count reaches five.
Operational P3-A nevertheless requires the manual pre-change review. If the
cohort would violate tightened thresholds, remain on HOLD/DE_RAMP/HOLD_ASSET;
do not rotate generation to manufacture a clean cohort.

## 10. Lease Policy

Initial profile:

```text
RESERVATION_LEASE_TTL_SECONDS=180
RESERVATION_HEARTBEAT_INTERVAL_SECONDS=45
```

This satisfies the source invariant `heartbeat <= TTL / 3`. TTL is the stale
owner horizon, not a render deadline. The always-on host makes 180/45 a
balanced initial choice.

Approved envelope: **180/45 or 300/60**. Move to 300/60 under Change Control
if actual scheduling pauses, SQLite contention, or host sleep/pause behavior
make 180/45 fragile. Do not use 120/30 or 90/25 for the first real Seed.

## 11. Readiness Policy

Initial Readiness is frozen as:

| Item | Value |
|---|---:|
| Window | `7d` |
| Minimum authoritative ENFORCE tasks | 10 |
| Minimum planning-observed tasks | 10 |
| Minimum conflict tasks | 0 |
| Diagnostic coverage minimum | 1.0 |
| Planning coverage minimum | 1.0 |
| Terminal coverage minimum | 1.0 |
| Zero-plan conflict maximum | 0.30 |
| Partial-plan maximum | 0.20 |
| Authority-loss maximum | 0 |
| Terminal-persist-failure maximum | 0 |
| Worker-lease-config-failure maximum | 0 |
| Cleanup-warning maximum | 0.10 |

`minimum_conflict_tasks = 0` is deliberate: no organic or manufactured
contention is required to become READY. With planning observations and zero
conflicts, the source produces a real zero rate, not UNKNOWN.

Readiness includes matching-policy Explicit ENFORCE and Canary ENFORCE rows.
That shared cohort is why routine Explicit ENFORCE stops after P3 begins.

## 12. Submission Pacing

V1.5 Seed uses:

```text
SERIAL THROUGH PLANNING
CONCURRENT AFTER PLANNING
```

A new public Matrix task may be submitted after the prior task has completed
planning and entered rendering. Multiple rendering tasks may coexist. This
prevents an admitted-but-unobserved row from temporarily reducing 1.0
diagnostic/planning coverage and causing `READINESS_LOST` on the next omitted
resolution.

Removing this operational rule while 1.0 coverage remains authoritative is a
rebaseline trigger.

## 13. Exposure Policy

| Policy | Initial bps | Approved envelope |
|---|---:|---:|
| `exact_main_visual` | 0 | 0 for initial V1.5 Seed |
| `exact_main_visual_balanced` | 3000 | 1000--4000 |

The target is **5--10 fully observed Canary tasks per tenant per rolling
7-day window**, not a percentage. Operations must measure real public Matrix
Tasks/day before adjustment.

Use:

```text
expected_canary_7d ~= public_tasks_per_day * 7 * basis_points / 10000
```

At each three-day review:

- `<5` and safety clean: KEEP or RAMP within the envelope;
- `5--10` and healthy: KEEP preferred; RAMP only for a documented learning or
  business reason;
- materially `>10` with adequate evidence: KEEP or DE_RAMP.

Maximum routine BPS movement is 1000 per review.

## 14. Human Review Cadence

Review every three days. A review records cohort counts, integer event counts,
rates, coverage, Readiness gates, rollout status, breaker/kill state, asset
capacity, public tasks/day, outputs/day, and successful outputs/public task.

Permitted decisions: `KEEP`, `RAMP`, `DE_RAMP`, `HOLD_ASSET`, `KILL`, and
`REBASELINE`. A stage may stay unchanged over multiple reviews.

## 15. Rollback Window

Initial rollback window: **7d**. A 24-hour window is not used during the
low-volume early Seed because an empty or one-task cohort alternates between
no evaluation and a 100% single-event rate.

Changing to **24h** is allowed only after at least five fully observed Canary
tasks per 24 hours are sustained for three consecutive staffed days and the
safety and quality evidence is healthy. Readiness may remain at 7d.

## 16. Warmup Rollback Policy

During P3-W, until five fully observed current-cohort Canary tasks exist:

| Rollback gate | Maximum/minimum |
|---|---:|
| Diagnostic coverage minimum | 1.0 |
| Planning coverage minimum | 1.0 |
| Terminal coverage minimum | 1.0 |
| Zero-plan maximum | 1.0 |
| Partial-plan maximum | 1.0 |
| Cleanup-warning maximum | 1.0 |
| Authority-loss maximum | 0 |
| Terminal-persist-failure maximum | 0 |
| Worker-config-failure maximum | 0 |

This avoids latching a generation solely because one of N=1--4 tasks has a
legitimate L2 quality/capacity shortfall or cleanup uncertainty. It does not
relax authority safety. Shared Readiness remains active.

`RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS=5` is only the source
`WARMING_UP`/`CANARY_ACTIVE` status milestone. It is not an admission gate, a
rollback warmup gate, or an evaluation delay.

## 17. Post-Warmup Rollback Policy

At five fully observed Canary tasks, evaluate the existing cohort before any
threshold change:

```text
THRESHOLD_TIGHTENING_REQUIRES_PRE_CHANGE_COHORT_EVALUATION
```

If the cohort would immediately fail, do not tighten, rotate, or hide evidence.
Choose HOLD, DE_RAMP, HOLD_ASSET, or investigation.

If the cohort supports tightening, remain in the same generation and use:

| Rollback gate | Maximum/minimum |
|---|---:|
| Coverage minima | 1.0 / 1.0 / 1.0 |
| Zero-plan maximum | 0.30 |
| Partial-plan maximum | 0.20 |
| Cleanup-warning maximum | 0.20 |
| Authority / persist / worker maximum | 0 / 0 / 0 |

Every cleanup warning is manually investigated even when the aggregate rate
passes.

## 18. Asset-Sufficiency Handling

Zero-plan and partial-plan events can indicate small or low-diversity asset
pools rather than an authority defect. Review them with catalog growth,
concurrency, batch size, public tasks/day, outputs/day, and outputs/task.

When authority safety is clean but capacity/diversity explains weak planning,
choose `HOLD_ASSET`: do not increase exposure, replenish assets, keep or reduce
BPS, and review again. Never weaken authority-safety thresholds to compensate
for missing assets.

## 19. Safety and Kill Policy

Any authority loss, terminal persistence failure, or worker lease-config
failure causes:

1. `KILL` classification;
2. immediate kill-switch activation while staffed;
3. halt of routine Explicit ENFORCE;
4. evidence preservation and root-cause investigation;
5. breaker containment on subsequent omitted resolution under current source;
6. re-arm only through an approved new generation after remediation.

The automatic breaker remains mandatory because the manual response SLA is
greater than two hours and overnight response is not guaranteed. A cleanup
warning alone is not authority loss, but always requires investigation.

## 20. Unattended-Hours Policy

No BPS increase, threshold tightening, new generation, lease-profile change,
or tenant-allowlist expansion may occur during 12:00--14:00, 17:00--19:00, or
21:00--09:00.

Risk-increasing changes occur only at the beginning of a staffed block and
must leave at least two staffed hours for observation. Risk-reducing actions
such as kill, de-ramp, or restoring BPS to zero may be taken whenever an
authorized operator is available.

## 21. Explicit ENFORCE Authority

During P1, only the Central Tech Operator may submit Explicit ENFORCE, using
normal diverse production-like tasks. Philippine creative operators receive
no ENFORCE control.

After P3 starts, routine Explicit ENFORCE is prohibited. The sole exception is
documented diagnosis or incident investigation approved by the Tech Lead.
Explicit ENFORCE bypasses rollout kill switch/breaker and shares the Readiness
cohort, so its use must be recorded and its terminal diagnostic observed before
interpreting Readiness.

## 22. Generation Governance

Format:

```text
phseed-<tenantcode>-bal-YYYYMMDD-rN
```

The Tech Lead approves generations and safeguards the assignment secret.

Keep the same generation for ordinary BPS changes, rollback-threshold tuning,
kill-switch toggling, and lease-profile adjustment. A new generation is
required after a breaker latch and remediation, after `READINESS_LOST` and
remediation, for a deliberately new tenant activation epoch, or after a
material authority/rollout behavior change.

Do not rotate merely because metrics are unfavorable. Every rotation records
the reason, approver, backup checkpoint, root cause/remediation, and evidence
reviewed. Rotation changes HMAC assignment and the rollback cohort; it is not
an evidence-cleaning operation.

## 23. Tenant Staggering

The allowlist contains only the currently active non-zero tenant during the
initial stagger. Enabling the next tenant requires:

- a reviewed post-warmup cohort for the current tenant;
- zero unresolved authority safety events;
- zero unresolved cleanup root causes;
- preserved diagnostics and change-control records;
- the next tenant's verified backup, Delivery path, assets, P1 evidence, and
  P2 READY state;
- current tenant returned to zero omitted exposure before the next is enabled.

Each tenant retains independent Readiness interpretation, Canary evidence,
Delivery subtree, backup, and operator record.

## 24. Dynamic Adjustment Envelope

Without a full re-freeze, Change Control may perform:

- Balanced BPS changes within 1000--4000, no more than 1000 per review;
- lease profile switch 180/45 <-> 300/60;
- rollback window 7d -> 24h only after the stated eligibility test;
- P3-W to P3-A threshold tightening after pre-change cohort evaluation;
- same-generation kill-switch toggling;
- one-at-a-time tenant stagger under the same product/authority assumptions;
- Delivery Root path changes on the same machine while preserving Two-Root
  authority.

Readiness numeric changes, removal of serial-through-planning, or changes
outside these bounds require rebaseline unless separately approved by a newer
policy freeze.

## 25. Change-Control Record

Every change records timestamp, tenant, old value, new value, reason,
operator, approver where required, pre-change cohort evidence, and post-change
review.

| Parameter | Initial Value | Approved Envelope | Review Trigger | Requires New Generation? | Requires Rebaseline? | Approver |
|---|---|---|---|---|---|---|
| Balanced BPS | 3000 at P3-W | 1000--4000; max 1000 change/review | Every 3-day review; sample outside 5--10/7d | No | Only outside envelope | Central Tech Operator; Tech Lead for exception |
| Lease profile | 180/45 | 180/45 or 300/60 | Scheduling/SQLite pause or host behavior | No | Yes outside envelope | Tech Lead |
| Rollback window | 7d | 7d; 24h after eligibility | >=5 fully observed/24h for 3 staffed days | No | Yes for other window policy | Tech Lead |
| Warmup rollback thresholds | quality/cleanup 1.0; safety 0; coverage 1.0 | Frozen P3-W values | Each warmup task | No | Yes if altered outside defined transition | Tech Lead |
| Post-warmup thresholds | zero .30, partial .20, cleanup .20, safety 0, coverage 1.0 | These values after cohort review | At >=5 fully observed; every 3 days | No | Yes for other threshold policy | Tech Lead |
| Tenant allowlist | One active canonical tenant | One non-zero tenant at a time | Tenant stagger review | Yes for new tenant activation epoch | No while stagger assumptions hold | Tech Lead |
| Generation | `phseed-<tenantcode>-bal-YYYYMMDD-rN` | Source-safe format; governed rotations only | Breaker/readiness remediation, tenant epoch, material authority change | It is the generation change | Material behavior change may | Tech Lead |
| Delivery Root | Verified machine-global absolute path | Any usable same-machine path preserving Two-Root contract | Disk/location maintenance | No | No; architecture review if Two-Root breaks | Tech Lead / machine operator |
| Serial-Through-Planning | Required | Required while coverage minima are 1.0 | Any concurrency-process change | No | Yes if removed | Tech Lead |

## 26. Rebaseline / Re-freeze Triggers

Rebaseline before proceeding when:

- more than one tenant needs simultaneous non-zero Canary before the initial
  stagger completes;
- serial-through-planning is removed while 1.0 coverage is authoritative;
- operator concurrency materially changes;
- host behavior exceeds both approved lease profiles;
- useful sustained BPS must leave 1000--4000;
- scale makes the 7-day policy unrepresentative;
- source changes Readiness denominators or shared-cohort semantics;
- source changes rollback warmup/evaluation semantics;
- L2 authority scope changes;
- multi-machine/distributed Reservation is introduced;
- project routing becomes a policy denominator instead of only a Delivery
  namespace;
- the Two-Root authority contract is challenged;
- a source-valid frozen value becomes impossible.

Rebaseline is a narrow policy review, not automatic repetition of every prior
engineering phase.

## 27. Future L3 Data Boundary

Canary count is rollout-governance evidence and is not a proxy for future L3
Historical Creative Memory volume. Future L3 may use all permitted production
history, including task, planning FP, child execution, source hashes, rendered
output/hash where available, and planning/Beat detail where available.

Delivery copies are not an L3 source. Internal authoritative output and
TaskHistory remain the backfill boundary. No L3 behavior is implemented or
authorized here.

## 28. Drill Boundaries

| Drill | Frozen class | Rule |
|---|---|---|
| Backup verify | `SAFE_ON_REAL_SEED` | Required checkpoint |
| Tenant Delivery Root verify | `SAFE_ON_REAL_SEED` | Verify isolation and non-authority |
| Kill-switch drill | `SAFE_ON_REAL_SEED` | Future omitted requests only; not task cancellation |
| Restart drill | `CONTROLLED_REAL_SEED_ONLY_AFTER_DRAIN` | Drain active tasks; otherwise staging |
| Breaker fault injection | `STAGING_OR_SYNTHETIC_ONLY` | Never manufacture bad real work |
| Forced same-FP contention | `STAGING_OR_SYNTHETIC_ONLY` | Deliberately produces a loser |
| Lease-expiry fault | `STAGING_OR_SYNTHETIC_ONLY` | Can waste/fence real output |
| SQLite outage/lock injection | `STAGING_OR_SYNTHETIC_ONLY` | Persistence risk |

## 29. Frozen Environment-Value Table

Rollout control and Readiness are all-or-none key sets. Booleans use source
forms `true`/`false`. The secret below is a placeholder, never a value to print
or commit.

### Lease

| Environment key | Frozen value |
|---|---|
| `RESERVATION_LEASE_TTL_SECONDS` | `180` |
| `RESERVATION_HEARTBEAT_INTERVAL_SECONDS` | `45` |

### Readiness

| Environment key | Frozen value |
|---|---|
| `RESERVATION_ROLLOUT_READINESS_WINDOW` | `7d` |
| `RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS` | `10` |
| `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS` | `10` |
| `RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS` | `0` |
| `RESERVATION_ROLLOUT_MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE` | `1.0` |
| `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE` | `1.0` |
| `RESERVATION_ROLLOUT_MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE` | `1.0` |
| `RESERVATION_ROLLOUT_MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | `0.30` |
| `RESERVATION_ROLLOUT_MAXIMUM_PARTIAL_PLAN_RATE` | `0.20` |
| `RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE` | `0` |
| `RESERVATION_ROLLOUT_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | `0` |
| `RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE` | `0` |
| `RESERVATION_ROLLOUT_MAXIMUM_CLEANUP_WARNING_RATE` | `0.10` |

### Rollout control

| Environment key | P0--P2 safe value | P3-W | P3-A after review |
|---|---|---|---|
| `RESERVATION_ROLLOUT_CONTROL_ENABLED` | `true` | `true` | `true` |
| `RESERVATION_ROLLOUT_GENERATION` | `phseed-<tenantcode>-bal-YYYYMMDD-rN` | same | same |
| `RESERVATION_ROLLOUT_TENANT_ALLOWLIST` | `<CANONICAL_ACTIVE_TENANT>` | same single tenant | same single tenant |
| `RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS` | `0` | `0` | `0` |
| `RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS` | `0` | `3000` | `3000` unless reviewed adjustment |
| `RESERVATION_ROLLOUT_ASSIGNMENT_SECRET` | `<SECRET_FROM_SECURE_OPERATOR_CHANNEL>` | unchanged | unchanged |
| `RESERVATION_ROLLOUT_KILL_SWITCH` | `true` | `false` only after final P2 check | `false` unless containment |
| `RESERVATION_ROLLOUT_ROLLBACK_WINDOW` | `7d` | `7d` | `7d` initially; eligible `24h` later |
| `RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS` | `5` | `5` | `5` |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_DIAGNOSTIC_COVERAGE_RATE` | `1.0` | `1.0` | `1.0` |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_PLANNING_COVERAGE_RATE` | `1.0` | `1.0` | `1.0` |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_TERMINAL_COVERAGE_RATE` | `1.0` | `1.0` | `1.0` |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | `1.0` | `1.0` | `0.30` |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE` | `1.0` | `1.0` | `0.20` |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE` | `0` | `0` | `0` |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | `0` | `0` | `0` |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE` | `0` | `0` | `0` |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE` | `1.0` | `1.0` | `0.20` |

Activation ordering: keep kill switch `true`, set the reviewed P3-W BPS and
all other values, verify Readiness/status, then set kill switch `false` last at
the beginning of a staffed block.

Not environment variables:

- Delivery Root: machine-global `dopamatrix.db` / `app_settings` key
  `delivery_root`, managed by `GET/POST /api/v1/settings/delivery-root`;
- tenant identity: authoritative canonical request tenant, not an env-backed
  path segment;
- human review records, backup evidence, and operator approvals.

## 30. Policy State / Decision Table

### State summary

| State | Governing exposure | Evidence objective | Normal next state |
|---|---|---|---|
| P0 | Omitted OFF | Backup/Delivery/config safety | P1 |
| P1 | Explicit ENFORCE only | 10/10 fully observed Readiness evidence | P2 |
| P2 | Omitted OFF | READY and final activation review | P3-W |
| P3-W | Balanced 3000 bps; warmup thresholds | 5 fully observed Canary tasks | P3-A or HOLD/KILL |
| P3-A | Reviewed 1000--4000 bps; tightened thresholds | Stable 5--10/7d evidence | KEEP/RAMP/DE_RAMP/HOLD/KILL |

### Human decision table

| Decision | When | Action | Canary BPS behavior | Generation behavior | Asset action | Safety action |
|---|---|---|---|---|---|---|
| `KEEP` | Evidence healthy and sample useful | Continue and record | Unchanged | Same | Continue normal replenishment | Continue monitoring |
| `RAMP` | Safety clean; evidence target unmet or documented learning need | Increase at staffed-block start | +<=1000, never above 4000 | Same | Confirm capacity first | Observe >=2 staffed hours |
| `DE_RAMP` | Excess exposure, noisy quality, or caution without safety breach | Reduce exposure | -<=1000 normally; larger reduction allowed for safety | Same | Investigate/replenish | Monitor; kill if safety emerges |
| `HOLD_ASSET` | Authority clean; small/diversity-poor catalog explains quality | Freeze or reduce exposure | No increase | Same | Replenish and review catalog | Do not weaken safety thresholds |
| `KILL` | Any authority/persist/worker-config safety event or unverifiable critical state | Set kill switch; stop routine Explicit ENFORCE; preserve evidence | Future omitted effectively OFF | Preserve current generation/breaker evidence; new generation only after remediation | Stop risky creative traffic as appropriate | Immediate containment and investigation |
| `REBASELINE` | Assumption/source leaves envelope | Keep/de-risk traffic; conduct narrow policy review | No increase; normally OFF/low until approved | Change only if new authority epoch justified | Reassess capacity | Preserve all prior evidence |

## 31. What Is Not Frozen

This document does not freeze:

- a permanent first business tenant;
- a real tenant code, date, generation instance, or assignment secret;
- automatic ramp dates or a 100% Default-ON destination;
- a fixed Delivery disk path;
- public-task volume inferred from output volume;
- catalog size or composition;
- Philippine production acceptance or GA authorization;
- blind-fission Balanced integration;
- future L3 Historical Creative Memory design or indexing.

## 32. Findings Carried Forward

| Finding | Policy disposition |
|---|---|
| RF-02: minimum canary tasks is not rollback warmup | Explicitly treated only as status/review milestone; P3-W uses separate permissive quality/cleanup thresholds |
| RF-03: low-BPS/short-window starvation | Initial BPS 3000 and rollback 7d; target measured 5--10 tasks, not percentage; 24h requires sustained >=5/day |
| RF-04: small-denominator single-event trip | N=1--4 quality/cleanup maxima are 1.0; safety remains 0; tighten only after cohort review |
| RF-05: Explicit ENFORCE contaminates shared Readiness | Routine Explicit ENFORCE prohibited after P3; technical exception only with approval and recorded interpretation |
| RF-06: cleanup warning overclassified | Warmup tolerance 1.0, post-warmup .20, mandatory manual investigation; never called authority loss |
| RF-09: generation rotation can mask evidence | Same generation for routine changes; rotation requires reason, approval, backup, remediation, and prior-evidence review |

No source-code change is required for these mitigations.

## 33. Release Boundary

This artifact freezes **V1.5 PHILIPPINE SEED POLICY v1.0** only. Actual
tenant activation still requires the P0--P3 evidence and operational actions
defined here and in the runbook. This is not:

- Philippine production acceptance;
- V1.5 GA authorization;
- universal or 100% Default-ON approval;
- legacy blind-fission qualification;
- L3 implementation.

The accepted Tenant Delivery runtime result remains a prerequisite:
`VAR001_V15_TENANT_DELIVERY_OUTPUT_RUNTIME_ACCEPTANCE_FINAL_PASS`.

## 34. Git Status

Pre-write repository state:

```text
git branch --show-current
feature/var-001-variation-policy

git rev-parse HEAD
14d61fc2f4021e8bda55a87086e730eebfec5f43

git log -1 --oneline
14d61fc feat(v1.5): isolate tenant delivery output

git status --short
(clean)
```

This phase creates only:

```text
?? doc/investigations/VAR001_PHASE3D2IB1C_FINAL_PHILIPPINE_SEED_POLICY_FREEZE.md
```

No production, Vue, test, SQLite, environment, runbook, or accepted evidence
artifact was modified. No tests, services, or renders were run. No commit or
push was performed.

VAR001_PHASE3D2IB1C_FINAL_PHILIPPINE_SEED_POLICY_FREEZE_PASS
