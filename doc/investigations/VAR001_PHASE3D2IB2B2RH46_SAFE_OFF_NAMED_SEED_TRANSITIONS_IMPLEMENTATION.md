# VAR-001 Phase 3D-2I-B-2B-2R-H4-6
# SAFE_OFF + Named Seed Transitions Implementation

## 1. Phase Identity

H4-6 implements exactly these packaged-operator commands:

```text
backend.exe operator [--json] seed apply-safe-off --tenant ID --generation G --approval-ref REF [--lease-profile 180-45|300-60]
backend.exe operator [--json] seed prearm-p3w --tenant ID --generation G --backup-bundle PATH --approval-ref REF
backend.exe operator [--json] seed activate --tenant ID --generation G --backup-bundle PATH --approval-ref REF
backend.exe operator [--json] seed kill --tenant ID --generation G --reason-code CODE
backend.exe operator [--json] seed set-balanced-bps --tenant ID --generation G --bps N --backup-bundle PATH --approval-ref REF
backend.exe operator [--json] seed transition-p3a --tenant ID --generation G --rollback-window 7d|24h --backup-bundle PATH --approval-ref REF
```

The source implementation, focused tests, relevant H3/H4 regression, and full
backend regression pass. This is implementation evidence for independent
ChatGPT review, not an independent FINAL PASS.

## 2. Governing Authority

The implementation follows root `AGENTS.md`, `.codex-local/handoffs.md`, the
accepted Grok 4.7 H4-6 source map, H4-R0/R2 operator grammar, H3 applied
snapshot and transition closures, H4-3 mutation foundation, H4-5 backup and
Delivery source, and the independent authority decision:

```text
VAR001_PHASE3D2IB2B2RH46R0_SEED_TRANSITION_AUTHORITY_DECISION_PASS
```

H0-H5 were not redesigned. H4-7 was not started.

## 3. Repository Baseline

- Branch: `feature/var-001-variation-policy`
- HEAD/origin: `fb9a990b8020cfb3f402ef267e5438a16d14639f`
- Immutable RC1: `5f534b180dd2ae9fa9212e6632a44746669d7e6f`
- Initial worktree: clean
- Initial index: empty

## 4. Exact Tenant and Generation Boundary

All six commands reuse the H4-4 exact three-ID allowlist:

| Canonical tenant | Required generation tenant code |
|---|---|
| `ph-elv-0001` | `elv0001` |
| `ph-bty-0001` | `bty0001` |
| `ph-hwh-0001` | `hwh0001` |

The new operator-only validator requires exact lowercase
`phseed-<tenantcode>-bal-YYYYMMDD-rN`. The code must match the supplied
canonical tenant, the date must be a real calendar date, and the revision must
be a canonical positive integer. Historical valid dates are accepted. No
sanitizer can turn an invalid input into a valid generation. Invalid input is
exit 3, `OPERATOR_SEED_GENERATION_INVALID`.

H3's generic `_validate_generation()` was not changed.

## 5. H4-6-R0 Authority Decision Closure

The implementation records and applies:

```text
VAR001_PHASE3D2IB2B2RH46R0_SEED_TRANSITION_AUTHORITY_DECISION_PASS
```

The closure is implemented exactly as follows:

1. `--rollback-window 24h` remains parser-valid, but every otherwise valid H4-6
   request fully reverifies its backup and then fails closed with exit 4,
   `P3A_24H_ELIGIBILITY_NOT_PROVABLE`, before RuntimePaths, the mutation
   barrier, any snapshot/audit/timestamp write, or any secret write.
2. Exact same-target `prearm-p3w`, `activate`, `set-balanced-bps`, and
   `transition-p3a 7d` return respectively `ALREADY_PREARMED`,
   `ALREADY_ACTIVE`, `ALREADY_SET`, and `ALREADY_TRANSITIONED`, exit 0, with
   no write. The existing `ALREADY_APPLIED` and `ALREADY_CONTAINED` rules are
   preserved.
3. `--reason-code` has a dedicated public validation result: string, 1..256
   characters, nonblank after `strip()`, and no Unicode category `Cc`.
   Invalid input is exit 3, `OPERATOR_REASON_CODE_INVALID`.
4. Every command uses the strict operator generation boundary in Section 4.
5. Evidence gates are command-specific: no extra Readiness, breaker, or
   Delivery gate was added to SAFE_OFF, kill, or Balanced BPS; no independent
   Delivery gate was added to P3-A.

Approval reference remains an external record reference only. It is not
authentication, authorization, proof of human approval, proof of staffed
days, or proof of human cohort review.

## 6. One Barrier and One Caller-Owned Transaction

`operator_seed.py` does not call `apply_philippine_seed_profile()`. Each
mutation uses:

1. pure command validation;
2. full H4-5 backup verification where required;
3. mutable RuntimePaths initialization;
4. the existing H4-3 OS-held mutation barrier;
5. one caller-owned connection to the global `dopamatrix.db`;
6. `checked_immediate_transaction()` and `BEGIN IMMEDIATE`;
7. in-transaction snapshot and Assignment Secret reread;
8. complete canonical parse and command-prestate validation;
9. command-specific current evidence gates;
10. H3 materialization/build/canonical-parse and the existing connection-bound
    snapshot writer;
11. one commit, or rollback on every exception.

The connection is closed explicitly. No second lock, snapshot revision column,
or nested H3-owned connection was added.

## 7. Canonical Snapshot and Secret Seam

The service reuses:

- `parse_applied_operational_snapshot()`;
- `materialize_philippine_seed_profile()`;
- `build_applied_operational_snapshot()`;
- `_write_snapshot_on_connection()`;
- `SecretStore._read_row()`, `_decrypt_row()`, and `_set_on_connection()`.

Only an initial absent SAFE_OFF snapshot may create an absent Assignment
Secret. A valid pre-existing secret is reused. Every later transition requires
and preserves the same valid secret. H4-6 never rotates it and never emits its
value, hash, length, prefix, suffix, ciphertext, or a secret-derived value.

## 8. Backup Reverification

`prearm-p3w`, `activate`, `set-balanced-bps`, and `transition-p3a` invoke the
existing `verify_operator_backup()` during every command. Success data's
canonical tenant must exactly equal the target tenant.

Verification occurs even for `ALREADY_*` and before the 24-hour fail-closed
result. Corrupt, missing, relative, or wrong-tenant bundles cannot be bypassed
by a no-op target. No second backup verifier was created.

## 9. Delivery, Readiness, Breaker, and Cohort Sources

- Delivery uses the accepted H4-5 `read_current_delivery_root()` and
  `derive_tenant_delivery_root()` source. Its active-WAL current-value behavior
  and sidecar-free stale-read protection are unchanged.
- Readiness calls `reservation_rollout_readiness()` directly over a read-only
  SQLAlchemy session for the existing tenant DB.
- Breaker and rollout metrics use the non-mutating
  `reservation_rollout_status()` projection from that same tenant DB.
- Both evidence calls share one observation timestamp and the canonical
  applied runtime mapping.
- No HTTP request, `X-Local-User`, CLI boolean, new evidence table, or
  `get_tenant_engine()` schema-initializing path is used.

P3-A 7-day cohort evidence requires at least five canary tasks; complete
diagnostic/planning/terminal coverage; zero-plan at most 0.30; partial-plan at
most 0.20; zero authority-loss, terminal-persist-failure, and worker-config
failure; cleanup-warning at most 0.20; READY Readiness; and a clear breaker.

## 10. Command Contract

| Command | Authoritative prestate and gates | Actual mutation | Same-target result |
|---|---|---|---|
| `apply-safe-off` | absent snapshot; no backup/evidence/Delivery | complete SAFE_OFF, BPS `0/0`, kill `true`; create secret only if absent | `ALREADY_APPLIED` |
| `prearm-p3w` | same identity SAFE_OFF; tenant backup; READY; breaker clear; Delivery valid | P3_W, Balanced `3000`, Exact `0`, kill `true`, warmup family | `ALREADY_PREARMED` |
| `activate` | same identity contained P3_W/P3_A; tenant backup; READY; breaker clear; Delivery valid | kill `true` to `false` only | `ALREADY_ACTIVE` |
| `kill` | same identity P3_W/P3_A; no external evidence gate | kill `false` to `true` only | `ALREADY_CONTAINED` |
| `set-balanced-bps` | same identity contained P3_W/P3_A; Exact `0`; tenant backup; BPS `1000..4000`, absolute delta at most `1000` | Balanced BPS only | `ALREADY_SET` |
| `transition-p3a 7d` | same identity contained P3_W; tenant backup; READY; breaker clear; cohort pass | P3_A active threshold family; BPS/Exact/kill/lease/secret preserved | `ALREADY_TRANSITIONED` |
| `transition-p3a 24h` | valid tenant backup is still required | no mutation; fail closed | not applicable |

Backup-bearing no-ops still reverify the backup. Pre-arm, activation, and P3-A
no-ops still apply their current source-provable evidence gates.

## 11. No-Write and Atomicity Proof

Focused tests compare the serialized snapshot, applied timestamp/audit
metadata, secret ciphertext, and secret update timestamp across every
`ALREADY_*` path. They remain identical.

Tests also prove:

- an authoritative prestate change before the checked read is observed and
  invalid command state is rejected;
- real H4-3 lock contention returns the stable busy result without mutation;
- a failure after an initial secret write rolls back secret, snapshot, and
  schema DDL together;
- wrong-stage, missing-snapshot, generation-mismatch, BPS-bound, and evidence
  failures leave the canonical state unchanged.

## 12. 24-Hour Human-Evidence Boundary

The CLI does not approximate three staffed days or reviewed Tech Lead change
control from one metrics read. A healthy cohort and an approval reference do
not enable 24 hours. No eligibility database was added.

The CLI also does not claim to prove a staffed block, an approver's identity,
genuine human review, authentic external approval, or a physical restart.

## 13. Provider and Restart Semantics

An actual snapshot write returns `restart_required=true`. A no-write result
returns `restart_required=false`. H4-6 never mutates an already-loaded process
provider. A focused test loads a contained snapshot provider, activates the
persisted snapshot, proves the old provider remains killed, and proves only a
new provider load observes activation.

## 14. Output and Error Contract

Human success uses stdout and failure uses stderr. JSON uses exactly one
schema-version-1 object on stdout with empty stderr. Result data contains only
canonical tenant, generation, stage, BPS, kill, rollback window, secret status,
and restart-required state.

Stable categories are:

| Category | Exit |
|---|---:|
| parser usage | 2 |
| tenant/generation/approval/reason/BPS shape | 3 |
| invalid state/evidence, lock busy, 24h unprovable | 4 |
| missing tenant or backup | 5 |
| backup or snapshot integrity | 6 |
| RuntimePaths/barrier/SQLite/evidence subsystem | 8 |
| bounded unexpected failure | 9 |

The one-transaction design has no normal partial-success exit 7.

## 15. Focused H4-6 Evidence

Final command:

```text
.\venv_build\Scripts\python.exe -m pytest tests\test_var001_operator_seed_transitions.py -q --basetemp <unique-isolated-temp>
```

Result: `25 passed, 39 subtests passed`, zero failures/errors. The one warning
is pytest's pre-existing inability to write `.pytest_cache` in the workspace.

The suite covers strict generation for all three tenants, historical dates,
cross-tenant and malformed rejection, the complete six-command mutation
matrix, all six no-write states, backup-on-no-op, corrupt/wrong-tenant backup,
24-hour fail-closed behavior and zero mutation, reason bounds, source-specific
gates, secret create/reuse/non-rotation, stale prestate, lock contention,
rollback atomicity, provider immutability, CLI dispatch, and one-stream JSON/
human output.

## 16. Relevant H3/H4 Regression

Final selected command covered H3 snapshot/profile/transition, rollout control,
Readiness, lease, Delivery, H4-3 mutation, H4-5 backup verifier, operator CLI,
status, tenant provisioning, RuntimePaths/bootstrap, packaged console, and
backup/restore.

Result: `288 passed, 2 skipped, 365 subtests passed`, zero failures/errors.
The two skips are existing complementary platform-specific tests. Warnings are
existing framework/deprecation and pytest-cache warnings.

## 17. Full Backend Regression

Final command:

```text
.\venv_build\Scripts\python.exe -m pytest tests -q --basetemp <unique-isolated-temp>
```

Authoritative result: `734 passed, 2 skipped, 455 subtests passed`, zero
failures/errors, with 121 existing framework/deprecation/cache warnings.

The first full attempt had `731 passed, 2 skipped, 2 setup errors` solely
because pytest could not scan its pre-existing default
`%TEMP%\pytest-of-chenp` directory (`WinError 5`). The complete suite was
rerun with a fresh isolated temp root and passed. After the final stale-prestate
test was added, the final complete suite above was run again and passed.

## 18. Compile and Source Checks

The repository-recorded Python 3.12.10 environment was used:

```text
.\venv_build\Scripts\python.exe
```

`py_compile` passed for every changed/new Python file. `git diff --check`
passes. The Git index remains empty.

## 19. Changed Files

- `src/api/operator_seed.py` — new bounded H4-6 transition service.
- `src/api/operator_cli.py` — lazy dispatch for the six Seed commands.
- `tests/test_var001_operator_seed_transitions.py` — focused H4-6 suite.
- `tests/test_var001_operator_cli.py` — H4-7-only placeholder inventory.
- `tests/test_var001_operator_status.py` — H4-7-only placeholder inventory.
- `tests/test_var001_runtime_mutation_foundation.py` — H4-7-only placeholder inventory.
- `tests/test_var001_operator_backup.py` — H4-7-only placeholder inventory.
- `tests/test_var001_reservation_rollout_control.py` — direct Readiness importer inventory includes the authorized H4-6 service.
- this tracked implementation report.
- ignored H4-6 final source review bundle.

## 20. Unchanged Protected Production Files

No production change was made to:

- `policy_profiles.py`;
- `database.py`;
- `runtime_mutation.py`;
- `operator_backup.py`;
- `backup_restore.py`;
- `delivery_output.py`;
- `secret_store.py`;
- Readiness, rollout/breaker, lease, RuntimePaths, or provider modules.

The implementation uses their existing accepted seams.

## 21. Forbidden-Scope Audit

PASS: no H4-7 rotation; no secret disclosure; no restore; no auto-ramp; no
arbitrary tenant; no force/rebaseline/overwrite; no second lock/verifier/
evidence store/policy system; no HTTP/X-Local-User authority; no provider
hot-reload; no claim of human proof/restart completion; no H0-H5 redesign; no
Tauri/Rust/frontend/packaging/dependency/AGENTS/handoff/RC1 mutation.

## 22. Declarations

```text
NO COMMIT PERFORMED
NO PUSH PERFORMED
H4_7_NOT_STARTED
NO_PACKAGED_REBUILD_PERFORMED
```

## 23. Implementation Classification

```text
VAR001_PHASE3D2IB2B2RH46_SAFE_OFF_NAMED_SEED_TRANSITIONS_IMPLEMENTATION_PASS
```

Independent ChatGPT review remains required before commit, push, or H4-7.

## 24. H4-6-R1 Independent Source Review Fixup

Independent source review issued:

```text
VAR001_PHASE3D2IB2B2RH46R1_24H_ACTIVATION_AND_COHORT_TYPE_FIXUP_REQUIRED
```

The review confirmed two narrow defects in the original H4-6 implementation.

First, the activation planner accepted any canonical P3_W or P3_A snapshot and
copied its current rollback window into a kill-disabled target. A contained
`P3_A / 24h / kill=true` snapshot therefore became `kill=false`, and an
already-active `P3_A / 24h / kill=false` snapshot returned `ALREADY_ACTIVE`.
Both outcomes positively authorized a 24-hour active policy despite H4-6
lacking machine-provable 24-hour eligibility.

The R1 regression was run against the pre-fix source. Both kill states returned
exit 0 instead of exit 4. The activate planner now checks the authoritative
snapshot after the H4-3 barrier, `BEGIN IMMEDIATE`, and in-transaction reread.
When `stage is P3_A` and the canonical rollback window is `24h`, it raises
`P3A_24H_ELIGIBILITY_NOT_PROVABLE`, exit 4, before target construction or any
snapshot, audit, timestamp, or secret write. Backup verification and exact
tenant matching still happen before RuntimePaths and the checked transaction,
so a corrupt or wrong-tenant bundle wins before the state rejection.

The guard is activation-specific. It does not change H3 representation of
P3_A/24h and does not block containment. A direct regression starts from
`P3_A / 24h / kill=false`, invokes `seed kill`, and proves that only kill
changes to true while stage, window, tenant, generation, BPS, Lease, Readiness,
thresholds, and Assignment Secret remain unchanged. Direct regressions also
prove P3_A/7d activation and `ALREADY_ACTIVE` remain accepted.

Second, `_cohort_ready()` previously coerced values with `float(...)`. That
accepted booleans, numeric strings, Decimal values, positive infinity in
minimum fields, and negative infinity in maximum fields. The pre-fix targeted
run reproduced 31 failing subtests while four unaffected targeted tests passed.

R1 now requires `canaryTaskCount` to have exact built-in `int` type, excluding
`bool`, and to be at least five. Every rate must have exact built-in `int` or
`float` type, excluding `bool`; floating-point rates must pass
`math.isfinite()`. There is no string, Decimal, or numeric-like coercion.
Missing keys, `None`, booleans, numeric/arbitrary strings, NaN, both
infinities, and unsupported numeric-like objects all return false without
escaping an exception. Existing thresholds are unchanged.

New direct tests cover:

- P3_A/24h activation rejection for both `kill=true` and `kill=false`;
- no serialized snapshot, timestamp, audit, ciphertext, or secret timestamp
  change on either rejection;
- corrupt and wrong-tenant backup precedence;
- P3_A/24h kill containment and complete non-kill preservation;
- preserved P3_A/7d activation and active no-op;
- valid baseline and integer rate metrics;
- exact rejection of bool, numeric strings, arbitrary strings, Decimal, NaN,
  positive/negative infinity, `None`, floating-point task count, and missing
  keys for every required metric.

Superseding R1 validation:

- targeted R1 fix tests:
  `4 passed, 114 subtests passed`, zero failures/errors;
- full focused H4-6 transition suite:
  `30 passed, 155 subtests passed`, zero failures/errors;
- relevant H3/H4 regression:
  `293 passed, 2 skipped, 481 subtests passed`, zero failures/errors;
- full backend regression:
  `739 passed, 2 skipped, 571 subtests passed`, zero failures/errors;
- every changed/new Python file: `py_compile` exit 0;
- `git diff --check`: exit 0.

The skips and warnings remain existing platform/framework/cache conditions.
No protected H3/H4 production module, operator grammar, dependency, package,
commit, or remote state changed. H4-7 remains unstarted.
