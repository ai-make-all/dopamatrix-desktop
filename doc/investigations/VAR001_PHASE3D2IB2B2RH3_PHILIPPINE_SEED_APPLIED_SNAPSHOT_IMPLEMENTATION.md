# VAR-001 Phase 3D-2I-B-2B-2R-H3
# Philippine Seed Profile & Applied Runtime Snapshot Implementation

## 1. Executive Result

H3 is complete. Current source now defines one reviewed `philippine-seed-v1`
profile, persists one complete canonical applied snapshot, atomically creates a
missing Assignment Secret with that snapshot, activates one immutable packaged
process mapping, and supplies every production Reservation loader from the
explicit runtime source.

Missing, corrupt, partial, unsupported, stage-incompatible, or secret-invalid
packaged state produces an in-memory SAFE-OFF provider with an empty Seed
mapping. It never merges environment or writes a fallback snapshot. No H4
operator command, UI control, automatic apply, automatic ramp, or H5 `.env`
cleanup was implemented.

No source/runtime-proven blocker remains.

## 2. Repository Baseline

| Fact | Value |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| Starting HEAD | `ad55cd6a41a0e9f7e1504aac7a5e07886a9f019a` |
| Starting commit | `ad55cd6 feat(v1.5): harden runtime secret storage` |
| Starting worktree | clean |
| Remote tracking state | synchronized with `origin/feature/var-001-variation-policy` |
| RC1 tag target | `5f534b180dd2ae9fa9212e6632a44746669d7e6f` |

H2 was committed and pushed before H3. RC1 was verified and was not moved.

## 3. H3 Scope

Implemented only:

- source-proven Seed key inventory;
- code-owned Philippine Seed profile and governance;
- complete canonical applied snapshot in global `app_settings`;
- bounded atomic profile application service;
- Assignment Secret generate/reuse through H2 `secure_settings`;
- packaged startup activation and SAFE-OFF failure states;
- immutable process-generation `RuntimeConfigProvider` installation;
- explicit Reservation mapping source migration;
- focused and regression tests.

No frontend, Tauri, build, `.env`, Ngrok, Delivery, backup, tenant registry,
operator CLI, version, tag, Reservation authority, planner, Task Identity,
Ledger, Historical, or rollout algorithm change was made.

## 4. Current 33-Key Source Inventory

Current loader maps prove the exact inventory:

| Group | Count | Keys |
|---|---:|---|
| Lease | 2 | `RESERVATION_LEASE_TTL_SECONDS`, `RESERVATION_HEARTBEAT_INTERVAL_SECONDS` |
| Readiness | 13 | `RESERVATION_ROLLOUT_READINESS_WINDOW`, `RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS`, `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS`, `RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS`, the three Readiness coverage minima, zero-plan/partial maxima, authority/persist/worker-lease-config/cleanup maxima |
| Rollout Control | 18 | enabled, generation, tenant allowlist, Exact BPS, Balanced BPS, Assignment Secret, kill switch, rollback window, minimum Canary tasks, three rollback coverage minima, and six rollback maxima |

The implementation exports source-derived frozen key sets from the three
existing loader modules and fails closed if their union is not exactly 33.

## 5. 32 Non-Secret / 1 Secret Classification

The sole secret runtime key is:

```text
RESERVATION_ROLLOUT_ASSIGNMENT_SECRET
```

The other 32 keys are persisted as strings in `effective_values`. The secret
is excluded from that mapping and from snapshot JSON. It is inserted only into
the in-memory mapping after successful secure-store resolution.

## 6. Philippine Seed Profile Identity

```text
profile_name    = philippine-seed-v1
profile_version = 1.0
schema_version  = 1
```

The profile is source code in `src/api/policy_profiles.py`, not a mutable DB
default, Settings payload, environment file, YAML/TOML artifact, or UI option.

## 7. Frozen Profile Values

The materializer reproduces policy v1.0:

- Lease default `180/45`; approved alternative `300/60` only.
- Readiness `7d`, counts `10/10/0`, coverage `1.0/1.0/1.0`, quality
  `.30/.20`, safety `0/0/0`, cleanup `.10`.
- Rollout control enabled, Exact BPS `0`, one canonical tenant, governed
  generation, minimum Canary count `5`, rollback coverage `1.0/1.0/1.0`.
- SAFE-OFF: Balanced `0`, kill `true`, warmup thresholds, `7d`.
- P3-W default: Balanced `3000`, approved active envelope `1000..4000`, warmup
  quality/cleanup `1.0`, safety `0`, `7d`.
- P3-A: Balanced `1000..4000`, quality `.30/.20`, cleanup `.20`, safety `0`,
  and governed rollback window `7d` or eligible `24h`.

Local A2 values are not profile defaults.

## 8. Profile Governance Validation

Governance runs after the unchanged source parsers. It rejects:

- a tenant changed by canonicalization or `default`;
- an invalid generation;
- a key-set/type mismatch;
- Exact BPS other than zero;
- Balanced BPS outside SAFE-OFF `0` or active `1000..4000`;
- lease pairs outside `180/45` and `300/60`;
- Readiness drift;
- coverage or safety drift;
- rollback threshold combinations inconsistent with the reviewed stage;
- more or fewer than one active tenant.

## 9. Applied Snapshot Schema

One global `app_settings` row uses key:

```text
operational_runtime_snapshot_v1
```

Its exact object fields are:

```text
schema_version
profile_name
profile_version
applied_at_utc
audit_metadata
tenant_allowlist
generation
stage
effective_values
assignment_secret
```

Unknown, missing, duplicate, mistyped, non-object, or inconsistent fields are
rejected.

## 10. Canonical JSON Contract

Serialization uses UTF-8-compatible JSON text with:

```python
json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

Activation also requires the persisted text to equal its canonical
re-serialization. The application service accepts an injectable clock, and
deterministic tests prove identical inputs/timestamp produce identical text.

## 11. Snapshot Key Completeness

`effective_values` must contain exactly the 32 source-derived non-secret keys,
all with string values. It is never merged with profile defaults,
environment, or prior process state. Partial Readiness/Rollout state, an
unknown key, or the Assignment Secret in the non-secret set is invalid.

## 12. Assignment Secret Reference Contract

The only persisted reference is:

```json
{"key_name":"reservation_rollout_assignment_secret","status":"PRESENT"}
```

Snapshot schema contains no plaintext, DPAPI ciphertext, value length, hash,
prefix, suffix, or HMAC intermediate. Activation additionally proves the
referenced H2 secret is readable.

## 13. Atomic Profile Application

`apply_philippine_seed_profile()` accepts bounded concepts: tenant,
generation, stage/effective intent, approved BPS/lease/window options, and
bounded audit metadata. It derives all 32 values and validates them through
the current loaders.

Within one caller-owned SQLite connection/transaction it:

1. ensures the two existing global tables;
2. reads or creates the Assignment Secret;
3. protects, inserts, reads back, decrypts, and verifies a new secret;
4. constructs, serializes, and reparses the canonical snapshot;
5. replaces the single snapshot row;
6. commits both or rolls both back.

Forced snapshot-write and secret protect/verify failures prove no split commit.

## 14. Assignment Secret Generation / Reuse

If absent during explicit profile application, a secret is created with
`secrets.token_urlsafe(48)` and never returned or logged. An existing readable
secret is reused. Reapplication does not rotate it. A corrupt/error state
fails with `OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE` and is not replaced.

Ordinary startup never generates a secret.

## 15. Startup Snapshot Activation

Packaged lifespan ordering is now:

```text
RuntimePaths
-> global application schema
-> H2 secure schema/OpenAI migration
-> applied snapshot load and validation
-> Assignment Secret secure read
-> immutable RuntimeConfigProvider install
-> request serving
```

The snapshot is loaded once. There is no per-task snapshot DB read.

## 16. Static Operational Snapshot

`RuntimeConfigProvider` defensively copies the activated 33-key in-memory
mapping behind `MappingProxyType`. Installation is idempotent only for the
same provider; conflicting process-generation installation fails closed.

Dynamic machine-setting reads remain separate. Delivery Root, OpenAI,
Cloudflare, and LLM settings are not members of the Seed snapshot.

## 17. Missing / Invalid Snapshot SAFE-OFF

Status is explicitly one of:

- `ACTIVE`;
- `SAFE_OFF_MISSING`;
- `SAFE_OFF_INVALID`.

Missing state installs an empty in-memory mapping with
`OPERATIONAL_SNAPSHOT_MISSING`. Invalid/corrupt/schema/profile/stage/secret
state installs an empty mapping with a bounded error. No fallback snapshot is
persisted and no environment value repairs it.

With no valid mapping, omitted/default requests remain OFF. Explicit ENFORCE
still follows the existing route contract; because a valid lease cannot be
proven from missing/invalid operational authority, it fails the existing
lease preflight instead of using environment fallback.

## 18. Stage Metadata Compatibility

`SAFE_OFF`, `P3_W`, and `P3_A` are stored only as audit/transition metadata.
No stage key enters the runtime mapping and no Reservation consumer branches
on stage. Startup validates stage compatibility against the effective BPS,
kill containment, rollback window, and threshold combination and rejects a
mismatch.

## 19. Reservation Loader Source Migration

Every production invocation of the Lease, Readiness, and Rollout loaders now
passes an explicit mapping. The final audit found:

```text
NO_BARE_PRODUCTION_LOADER_CALLS
```

PACKAGED and TEST use only the installed static mapping. SOURCE_DEVELOPMENT
uses the single explicit `reservation_runtime_mapping()` environment adapter.
The loader default arguments remain for direct development/test compatibility;
their parser, all-or-none, validation, and dataclass behavior is unchanged.

## 20. Packaged Assignment Secret Source Switch

Packaged snapshot activation reads
`secure_settings.reservation_rollout_assignment_secret`, validates it, and
adds it only to the in-memory Rollout loader mapping. Packaged runtime cannot
obtain it from process environment. HMAC message, bucketing, generation,
breaker, and assignment semantics are unchanged.

## 21. Source Development Compatibility

Source development retains the existing environment-backed Seed behavior
behind one mode-checked adapter. Dotenv is still loaded by normal source/server
startup because H5 owns Production NO-`.env`. H3 does not claim global
environment removal.

The current Runbook/Execution Pack environment procedures remain historical
operator text and must be synchronized to packaged H4 commands only after
that command surface exists.

## 22. Test Isolation

H3 tests use temporary RuntimePaths, a temporary global SQLite database,
synthetic values, and a deterministic fake protector. They do not touch real
LocalAppData, developer/tenant DBs, output, Delivery, backup, `.env`, or real
credentials.

## 23. Tests Added / Updated

Initially added `tests/test_var001_seed_applied_snapshot.py` with 17 tests
covering:

- exact inventory and frozen profile values;
- approved/rejected governance;
- canonical schema/key/duplicate/type/stage validation;
- atomic application, rollback, reuse, and corrupt secret behavior;
- valid/missing/invalid/corrupt startup activation;
- no packaged environment fallback;
- immutable process snapshot/restart behavior.

Updated one static importer assertion in
`tests/test_var001_reservation_rollout_control.py` to recognize
`policy_profiles.py` as the required existing-validator consumer. It does not
expand Reservation authority.

## 24. Focused Test Results

| Suite | Result |
|---|---:|
| H3 focused | 17 passed, 17 subtests passed |
| H2 + H1 affected rerun | 45 passed, 3 subtests passed |
| Failed static assertion + H3 rerun after bounded correction | 18 passed, 17 subtests passed |

## 25. Reservation Regression Results

Lease, Readiness, Rollout Control, runtime acceptance, terminal, planner,
diagnostics, Reservation public activation, public Reservation activation,
clean Task Identity, and public lifecycle guard were run together:

```text
212 passed
128 subtests passed
0 failed / 0 errors
```

The first run had one H3-caused static allowlist assertion because the new
profile module intentionally imports the Readiness loader. The assertion was
narrowly updated and the full group passed on rerun.

Additional Fingerprint Ledger, Phase3C Ledger, Tenant Delivery, V1.5
Backup/Restore, planning policy, balanced-axis, matrix/export, and FP suites:

```text
180 passed
1 existing POSIX-only skip
37 subtests passed
```

## 26. Full Pytest Result

Command:

```text
.\venv_build\Scripts\python.exe -m pytest tests -q
```

Result:

```text
599 passed
1 skipped
234 subtests passed
0 failures / 0 errors
120 warnings
137.17s
```

The baseline increase from 582 to 599 is exactly the 17 new H3 tests. The
existing skip and warning classes remain non-failing.

## 27. Seed Environment Authority Audit

All Seed environment-name matches were classified:

- key declarations/profile constants: expected;
- existing loader `environ=None` fallback: retained semantic compatibility;
- `runtime_config.reservation_runtime_mapping()`: the sole mode-checked
  SOURCE_DEVELOPMENT environment adapter;
- `main.py` source-development provider construction after dotenv: temporary
  H5 compatibility;
- packaged snapshot bridge: secure Assignment Secret plus persisted 32-key
  mapping only;
- tests/docs: synthetic/evidence uses.

There are no bare production loader calls. `PUBLIC_BASE_URL` and other
non-Seed environment debt remain H5 work and are not falsely claimed removed.

## 28. Scope Check

No operator CLI, HTTP mutation API, Seed Settings UI, automatic apply/ramp,
stage-driven runtime state machine, secret rotation, tenant creation,
Reservation acquire/confirm/renew/fence/release change, HMAC change, planner
change, Task Identity change, Ledger change, Delivery change, backup change,
Tauri change, `.env` removal, Ngrok change, version/tag change, build, service
start, or production DB mutation occurred.

## 29. Git Diff

Tracked implementation delta before this report:

```text
8 files changed, 196 insertions(+), 21 deletions(-)
```

Untracked additions before this report:

- `src/api/policy_profiles.py` (711 lines);
- `tests/test_var001_seed_applied_snapshot.py` (573 lines).

At the initial H3 closure, the new H3 report was the only documentation
addition. The later R1/R2 evidence artifacts are recorded in Section 30A.
`git diff --check` passes; line-ending notices are informational.

## 30. Git Status

Expected final uncommitted H3 delta:

```text
 M main.py
 M src/api/reservation_lease.py
 M src/api/reservation_rollout_control.py
 M src/api/reservation_rollout_readiness.py
 M src/api/routes_dsl.py
 M src/api/routes_reservation_diagnostics.py
 M src/api/runtime_config.py
 M tests/test_var001_reservation_rollout_control.py
?? doc/investigations/VAR001_PHASE3D2IB2B2RH3_PHILIPPINE_SEED_APPLIED_SNAPSHOT_IMPLEMENTATION.md
?? src/api/policy_profiles.py
?? tests/test_var001_seed_applied_snapshot.py
```

No `.env`, SQLite DB, tenant DB, secret/ciphertext artifact, output media,
Delivery media, backup, build artifact, or installer is present.

## 30A. H3-R1 / H3-R2 Transition Regression Closure

H3-R1 source review proved that the production materializer can represent P2
pre-arm, disable-kill-last P3-W activation, P3-W/P3-A kill containment, and
governed same-generation BPS changes without making `stage` request-time
authority. It historically classified five exact scenarios as `TEST_GAP` and
returned:

```text
VAR001_PHASE3D2IB2B2RH3R1_TRANSITION_TEST_FOLLOWUP_REQUIRED
```

H3-R2 added five direct tests, bringing the focused module to 22 tests. They
prove:

- P3-W metadata with BPS 3000 and kill=true is a valid P2 pre-arm snapshot and
  omitted traffic remains `DEFAULT_OFF`;
- disable-kill-last changes only effective kill authority, with the current
  process provider unchanged until a newly loaded provider observes it;
- P3-W containment preserves non-zero BPS, generation, warmup thresholds,
  Lease, Readiness, tenant, and Assignment Secret;
- P3-A containment preserves active thresholds, BPS, generation, and secret;
- governed P3-A BPS replacement preserves every other effective authority and
  does not implement an automatic ramp decision.

Closure results:

```text
H3 focused:             22 passed, 17 subtests passed
Reservation / Task:    212 passed, 128 subtests passed
H2 + H1:                45 passed, 3 subtests passed
Full pytest:           604 passed, 1 skipped, 234 subtests passed
Failures / errors:       0
```

No production source correction was required. R1 remains unchanged as the
historical artifact that found the five test gaps; R2 closes all five. The H3
final classification remains:

```text
VAR001_PHASE3D2IB2B2RH3_SEED_APPLIED_SNAPSHOT_PASS
```

## 31. Deferred H4-H6 Work

- H4: packaged operator CLI, profile/status/apply transitions, tenant and
  generation operator inputs, packaged provisioning/backup commands, and
  active Runbook/Execution Pack synchronization.
- H5: packaged NO-`.env`, Tauri `.env` removal, Ngrok/network cleanup, and
  remaining non-Seed configuration debt.
- H6: isolated RC2 build, installer/artifact security acceptance, checksums,
  manifest, and Philippine handoff.

## 32. Final Classification

- `H3_SEED_KEY_INVENTORY_32_PLUS_1_PROVEN = PASS`
- `H3_PHILIPPINE_SEED_V1_PROFILE_PROVEN = PASS`
- `H3_FROZEN_POLICY_VALUES_PROVEN = PASS`
- `H3_SNAPSHOT_SINGLE_ROW_PROVEN = PASS`
- `H3_SNAPSHOT_COMPLETE_KEYSET_PROVEN = PASS`
- `H3_SNAPSHOT_CANONICAL_JSON_PROVEN = PASS`
- `H3_EXISTING_VALIDATORS_REUSED = PASS`
- `H3_PROFILE_GOVERNANCE_VALIDATION_PROVEN = PASS`
- `H3_STAGE_NON_AUTHORITATIVE_PROVEN = PASS`
- `H3_STAGE_COMPATIBILITY_FAIL_CLOSED_PROVEN = PASS`
- `H3_ASSIGNMENT_SECRET_NOT_IN_SNAPSHOT = PASS`
- `H3_ASSIGNMENT_SECRET_SECURE_SOURCE_PROVEN = PASS`
- `H3_ASSIGNMENT_SECRET_NO_AUTO_ROTATION_PROVEN = PASS`
- `H3_ATOMIC_SNAPSHOT_SECRET_APPLY_PROVEN = PASS`
- `H3_PACKAGED_VALID_SNAPSHOT_ACTIVATION_PROVEN = PASS`
- `H3_PACKAGED_MISSING_SNAPSHOT_SAFE_OFF_PROVEN = PASS`
- `H3_PACKAGED_INVALID_SNAPSHOT_SAFE_OFF_PROVEN = PASS`
- `H3_PACKAGED_NO_SEED_ENV_FALLBACK_PROVEN = PASS`
- `H3_STATIC_SNAPSHOT_RESTART_SEMANTICS_PROVEN = PASS`
- `H3_EXPLICIT_ENFORCE_SEMANTICS_UNCHANGED = PASS`
- `H3_RESERVATION_SEMANTICS_UNCHANGED = PASS`
- `H3_H2_SECRET_ARCHITECTURE_PRESERVED = PASS`
- `H3_NO_OPERATOR_CLI_IMPLEMENTED_EARLY = PASS`
- `H3_NO_SETTINGS_UI_IMPLEMENTED = PASS`
- `H3_PRODUCTION_NO_ENV_NOT_FALSELY_CLAIMED = PASS`

`VAR001_PHASE3D2IB2B2RH3_SEED_APPLIED_SNAPSHOT_PASS`

## 33. H3-R3 Exact Lease Validation Closure

The independent ChatGPT final source review found a real narrow validation
defect after H3-R2: the frozen Lease membership check converted loader-parsed
floats with `int(...)`. Non-canonical persisted strings such as `180.9/45.1`,
`300.9/60.1`, `180.0/45.0`, and `0300/060` could therefore compare equal to an
approved integer pair.

H3-R3 first added and ran
`test_noncanonical_lease_snapshot_values_fail_closed` against the old
implementation. The honest red result was `5 failed, 2 subtests passed`: all
four invalid pairs escaped validation, and a representative invalid persisted
snapshot activated as `ACTIVE` instead of `SAFE_OFF_INVALID`.

The production correction is limited to `src/api/policy_profiles.py`. It
derives the exact canonical string pairs `180/45` and `300/60` from the
unchanged `_APPROVED_LEASES` set and compares the original 32-key effective
mapping strings directly. The general Lease loader, snapshot schema,
materializer, stage semantics, generation governance, Assignment Secret,
Reservation behavior, and H3-R2 transitions are unchanged.

Post-fix closure results:

```text
Exact R3 node:          1 passed, 6 subtests passed
H3 focused:            23 passed, 23 subtests passed
H2 + H1:               45 passed, 3 subtests passed
Reservation / Task:   212 passed, 128 subtests passed
Full pytest:          605 passed, 1 skipped, 240 subtests passed
Failures / errors:      0
```

The detailed reproduction, production diff, test commands, and scope evidence
are preserved in:

```text
doc/investigations/VAR001_PHASE3D2IB2B2RH3R3_EXACT_LEASE_VALIDATION_CLOSURE.md
```

H3-R1 and H3-R2 remain unchanged historical evidence. H3-R3 closes the exact
Lease validation defect with:

```text
VAR001_PHASE3D2IB2B2RH3R3_EXACT_LEASE_VALIDATION_CLOSURE_PASS
```
