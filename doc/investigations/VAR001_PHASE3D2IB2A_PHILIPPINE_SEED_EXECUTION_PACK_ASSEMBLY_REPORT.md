# VAR-001 Phase 3D-2I-B-2A
# Philippine Seed Execution Pack Assembly Report

## 1. Executive Result

The frozen V1.5 Philippine Seed Policy v1.0 has been translated into a
source-valid operator execution package without activating Canary or changing
runtime state.

The stable Seed Runbook now references the 1C policy freeze, contains the
frozen values, and no longer contains `TO_BE_DECIDED_BY_2I_B_SEED_POLICY`.
The new Execution Pack provides per-tenant P0--P3 worksheets, complete
environment manifests, evidence tables, controlled restart instructions,
change-control records, and safety cards.

No source contradiction blocks execution. This assembly is documentation
preparation only and is not Philippine production acceptance.

## 2. Inputs Read

The following were read in full before document assembly; current file hashes
were also checked so prior accepted content was not confused with a stale
copy:

- `VAR001_PHASE3D2IB1C_FINAL_PHILIPPINE_SEED_POLICY_FREEZE.md`
- `VAR001_PHASE3D2IB1B_SEED_POLICY_TECHNICAL_CHALLENGE.md`
- `VAR001_PHASE3D2IB1A_PHILIPPINE_SEED_POLICY_FACT_PACK.md`
- `DOPAMATRIX_V15_PHILIPPINE_SEED_CANARY_RUNBOOK.md`
- `VAR001_PHASE3D2IA2_MANUAL_FULLSTACK_ACCEPTANCE.md`
- `VAR001_V15_TENANT_DELIVERY_OUTPUT_RUNTIME_ACCEPTANCE.md`

Current source was then inspected for Lease, Readiness, Rollout, diagnostics,
backup/restore, Delivery Root, router mounting, `.env` loading, and backend
launch behavior.

## 3. Source Revalidation

Current source confirms:

- lease keys are `RESERVATION_LEASE_TTL_SECONDS` and
  `RESERVATION_HEARTBEAT_INTERVAL_SECONDS`, with finite positive values and
  heartbeat no greater than TTL/3;
- Readiness accepts `7d`, nonnegative count minima, and rates in `[0,1]`;
- Rollout accepts generation `[A-Za-z0-9._-]{1,64}`, bps `0..10000`,
  minimum Canary count at least 1, rollback window `7d`, and rates `[0,1]`;
- `minimum_canary_task_count` remains status-only; rollback begins with the
  first Canary;
- all 1C frozen values are within current source domains;
- diagnostic routes remain read-only and tenant-scoped by `X-Local-User`;
- Delivery Root remains the machine-global `delivery_root` app setting;
- backup/verify/restore remain CLI subcommands, not public HTTP endpoints.

## 4. Runbook Synchronization

Updated `DOPAMATRIX_V15_PHILIPPINE_SEED_CANARY_RUNBOOK.md` to:

- reference 1C as numeric/governance authority and the Execution Pack as the
  per-tenant evidence worksheet;
- freeze Balanced/Exact at 3000/0 bps and the envelope at 1000--4000;
- freeze Lease, Readiness, rollback, warmup, and post-warmup values;
- document one-tenant stagger and serial-through-planning pacing;
- map activation explicitly through P0, P1, P2, P3-W, and P3-A;
- state controlled backend restart after every environment change;
- restrict breaker fault injection to staging/synthetic evidence;
- require real-Seed restart drills to occur only after active work drains.

Final independent review found and corrected two operator-text synchronization
defects:

1. the bootstrap precondition wording was too broad: it could be read as
   blocking P1 while Readiness was legitimately `INSUFFICIENT_EVIDENCE` or
   while the P0--P2 kill switch was intentionally true;
2. the real-Seed kill-switch drill unnecessarily required a new Explicit
   ENFORCE task after P3, contrary to the frozen routine-Explicit prohibition.

The corrected Runbook gates only entry into P3-W/non-zero omitted Canary on
READY plus backup, lease, breaker, Delivery, and approval checks. The real
Seed kill-switch drill now proves omitted `DEFAULT_OFF` after controlled
restart without deliberately creating Explicit ENFORCE traffic. Explicit
bypass re-demonstration is staging/synthetic only; the factual source behavior
is unchanged.

The Philippine Seed copy-paste summary example was also aligned to the frozen
`window=7d`. The generic endpoint contract still lists all four supported
windows and retains the source default of `24h`.

Unrelated runbook history, source-valid routes, secret handling, backup-first
discipline, L1/L2/L3 distinctions, and UI boundaries were preserved.

## 5. Execution Pack Structure

The new pack contains:

1. execution header without a secret-value field;
2. three-tenant selection sheet;
3. P0 BACKUP_AND_OFF checklist;
4. complete source-valid environment manifest;
5. environment apply/restart procedure;
6. P1 authority and 10+ task evidence tables;
7. P2 gate-by-gate READY checklist;
8. exact P3-W activation sequence;
9. first-five fully observed Canary worksheet;
10. pre-change P3-A cohort evaluation;
11. three-day review and BPS decision template;
12. reusable Change-Control log;
13. KILL, HOLD_ASSET, unattended-hours, Delivery, and backup cards;
14. source-verified diagnostic command templates;
15. tenant-stagger exit gate and execution result.

No real tenant ID, tenant code, execution date, generation instance, Delivery
path, backup ID, operator identity, or secret was invented.

## 6. Environment-Key Verification

Every environment key in the 1C freeze exists in current source. No key name
has changed.

The intentionally different worker keys were preserved exactly:

```text
Readiness:
RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE

Rollback:
RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE
```

The Execution Pack enumerates all 2 Lease, 13 Readiness, and 18 Rollout keys
with P0/P1/P2, P3-W, and P3-A values plus restart, secret, and Change-Control
classification.

## 7. Restart / Reload Semantics

`main.py` calls `load_env()` once at module startup. `load_env()` reads the
packaged executable directory `.env` (or normal dotenv search path) with
`override=False`. Lease, Readiness, and Rollout loaders read the current
process `os.environ` when evaluated, but the application exposes no supported
operator endpoint that mutates or reloads those environment variables.

Therefore editing deployment environment / `.env` requires a controlled
backend restart. Development `uvicorn --reload` and debug mutation of
`os.environ` are not production operator mechanisms.

Delivery Root is different: it is persisted through the app-settings API and
does not itself require restart.

## 8. P0–P3 Mapping

| State | Execution-Pack control |
|---|---|
| P0 | Backup/Delivery verified; Lease and complete env sets configured; Balanced/Exact 0/0; kill true; omitted OFF |
| P1 | Central Tech Operator; normal diverse Balanced Explicit ENFORCE; 10/10 counts; serial through planning; no manufactured contention |
| P2 | Exact Readiness state READY; every gate PASS; breaker clear; kill true; Tech Lead approval |
| P3-W | Balanced 3000 prepared while killed; restart/check; kill false last; warmup quality/cleanup 1.0 and safety 0 |
| P3-A | Five fully observed tasks plus pre-change cohort evaluation; same-generation .30/.20/.20 tightening only if current cohort passes |

The pack explicitly warns that the source status milestone of five does not
delay rollback evaluation.

## 9. Secret Handling

The assignment secret is represented only as:

```text
<LOAD_FROM_SECURE_OPERATOR_CHANNEL>
```

The header records only YES/NO for secure loading. Tables and logs prohibit
secret values. No example, fake secret, HMAC input, or secret-derived data was
added.

## 10. Delivery Root Handling

Current source confirms:

```text
GET  /api/v1/settings/delivery-root
POST /api/v1/settings/delivery-root
```

The pack uses GET for preflight verification and identifies Delivery Root as
machine-global, not tenant-scoped environment configuration. The derived
tenant contract remains:

```text
<root>/tenants/<canonical-tenant>/projects/_default/
```

TaskHistory, backup, and future L3 authority remain internal `output/`.

## 11. Backup Handling

Current `src.api.backup_restore` and the accepted backup runbook confirm:

```powershell
.\venv_build\Scripts\python.exe -m src.api.backup_restore backup `
  --tenant <CANONICAL_TENANT> `
  --destination <NEW_BACKUP_DIRECTORY>

.\venv_build\Scripts\python.exe -m src.api.backup_restore verify `
  --bundle <BACKUP_ID>
```

These commands were reused without inventing an endpoint. Normal Seed
activation does not perform a destructive restore. Restore remains isolated
`restore-to-staging` tooling under the separate backup runbook.

## 12. Diagnostics Routes

Current router mounting proves these routes remain correct:

- `GET /api/v1/diagnostics/reservation/readiness?planning_policy=exact_main_visual_balanced`
- `GET /api/v1/diagnostics/reservation/rollout-status?planning_policy=exact_main_visual_balanced`
- `GET /api/v1/diagnostics/reservation/summary?window=7d`
- `GET /api/v1/settings/delivery-root`

The first three use the authoritative tenant selected by `X-Local-User`.
Delivery Root is global; the command template retains the header only to keep
operator context explicit.

## 13. Scope Check

Changed documentation only:

- modified Seed Canary Runbook;
- added Seed Execution Pack;
- added this Assembly Report.

No production code, Vue, test, SQLite, environment, service, render, backup,
Delivery setting, secret, commit, or push was touched. No tests were run
because this phase expressly prohibited runtime/test activity.

## 14. Findings

| Required finding | Result |
|---|---|
| Every 1C environment key exists | YES |
| Any key name changed | NO |
| Environment edits require backend restart | YES; no supported hot reload |
| Diagnostics routes current | YES |
| Backup commands current | YES |
| Delivery Root commands current | YES |
| Any 1C value impossible in current source | NO |
| Source blocker | NONE |

Post-review synchronization corrections:

| Review item | Disposition |
|---|---|
| P1 bootstrap blocked by broad READY/kill wording | Corrected; P1 insufficient evidence and kill=true are explicitly expected |
| Real-Seed kill drill required Explicit ENFORCE bypass task | Corrected; omitted-mode proof only, with controlled restart |
| Seed summary copy-paste window | Corrected to explicit `7d`; endpoint default remains `24h` |

These were documentation synchronization defects, not source contradictions,
policy changes, or runtime findings. The Execution Pack required no change.

Operational warning: a restart loads the new environment but does not cancel
or rewrite already-running tasks. Risk-increasing restart/change procedures
remain staffed-block operations, and restart drills require drained work.

## 15. Git Status

Baseline:

```text
feature/var-001-variation-policy
d634d805dd5d3db620869333fda476e441249a2c
d634d80 docs(v1.5): freeze Philippine seed policy
(clean worktree)
```

Final documentation-only result:

```text
 M doc/operations/DOPAMATRIX_V15_PHILIPPINE_SEED_CANARY_RUNBOOK.md
?? doc/operations/DOPAMATRIX_V15_PHILIPPINE_SEED_EXECUTION_PACK.md
?? doc/investigations/VAR001_PHASE3D2IB2A_PHILIPPINE_SEED_EXECUTION_PACK_ASSEMBLY_REPORT.md
```

No commit or push.

`git diff --check` returned no errors. The tracked Runbook diff is 77
insertions and 43 deletions; the two untracked artifacts are listed by status
and are not included in ordinary `git diff --stat` until tracked.

## 16. Final Classification

VAR001_PHASE3D2IB2A_PHILIPPINE_SEED_EXECUTION_PACK_READY
