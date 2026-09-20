# VAR-001 Phase 3D-2I-B-2B-2R-H3-R1
# Philippine Seed Transition Representability Source Proof

## 1. Executive Result

The H3 profile/snapshot layer can represent every frozen Philippine Seed
transition requested for future H4 operator commands without making `stage`
runtime authority:

- SAFE-OFF/P0: Balanced `0`, Exact `0`, kill `true`, warmup thresholds;
- P2 pre-arm: Balanced `3000`, Exact `0`, kill `true`, P3-W warmup
  thresholds, same tenant and generation;
- P3-W activation: the same effective policy with kill changed to `false`;
- P3-W and P3-A containment: kill changed to `true` while retaining BPS,
  generation, threshold family, lease/Readiness settings, tenant, and secret;
- governed P3-A BPS changes inside `1000..4000` without automatic ramp or
  generation/secret rotation.

`stage` selects and validates the reviewed policy family during materialization,
but it is not passed into the Reservation runtime mapping. P3-W and P3-A
compatibility deliberately accept either boolean kill state, so containment
does not invalidate the applied snapshot.

No production fix is required. Direct transition-specific regression tests are
missing for all five scenarios requested by this review, so the evidence
classification is the test-follow-up classification rather than the fully
closed source-and-test classification.

## 2. Repository / Worktree Baseline

| Fact | Value |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| HEAD | `ad55cd6a41a0e9f7e1504aac7a5e07886a9f019a` |
| Commit | `ad55cd6 feat(v1.5): harden runtime secret storage` |
| H3 state | intentionally uncommitted |
| Initial `git diff --check` | PASS; only LF-to-CRLF notices |

The initial status contained only the accepted H3 source/test/report delta.
No `.env`, SQLite database, tenant database, output media, backup, secret, or
build artifact was present. This R1 did not modify production source, tests, the
H3 report, runtime databases, or environment state.

Policy authority was rechecked against the Final Philippine Seed Policy Freeze,
Runbook, Execution Pack, and Runtime Config/Secret Constitution. In particular:

- P2 prepares non-zero BPS while kill remains true;
- P3-W disables kill last in the same generation;
- routine BPS and kill changes preserve the generation;
- KILL preserves current generation/breaker evidence;
- stage labels are non-authoritative transition/audit metadata.

## 3. Profile Application Service Signature

Current source, `src/api/policy_profiles.py:554-567`:

```python
def apply_philippine_seed_profile(
    store: SecretStore,
    *,
    tenant_id: str,
    generation: str,
    stage: PhilippineSeedStage | str,
    balanced_basis_points: int | None = None,
    lease_profile: tuple[int, int] = (180, 45),
    rollback_window: str = "7d",
    kill_switch: bool | None = None,
    audit_metadata: Mapping[str, str] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    secret_factory: Callable[[], str] = lambda: secrets.token_urlsafe(48),
) -> ProfileApplicationResult:
```

It delegates the effective-state calculation directly, at
`src/api/policy_profiles.py:569-577`:

```python
values = materialize_philippine_seed_profile(
    tenant_id=tenant_id,
    generation=generation,
    stage=stage,
    balanced_basis_points=balanced_basis_points,
    lease_profile=lease_profile,
    rollback_window=rollback_window,
    kill_switch=kill_switch,
)
```

Answers:

1. The caller controls `kill_switch` independently for P3-W/P3-A. Omitting it
   chooses the reviewed default (`false`); explicitly passing `true` produces
   containment.
2. The caller controls Balanced BPS inside the stage policy envelope. SAFE-OFF
   permits only `0`; P3-W/P3-A permit `1000..4000`, defaulting to `3000`.
3. `stage` selects a reviewed threshold/window family and validates its
   compatibility. It does not determine request-time rollout behavior and does
   not force the kill value for P3-W/P3-A.
4. Future H4 input shapes are:
   - pre-arm: `stage=P3_W`, reviewed BPS, `kill_switch=True`;
   - activation: same inputs except `kill_switch=False`;
   - kill: preserve active stage/BPS/generation and pass `kill_switch=True`;
   - de-ramp/ramp: preserve active stage/generation and pass a reviewed BPS,
     with kill held true during the controlled edit and disabled last when the
     operator reactivates.

H3 exposes materialization/application capability only. It does not implement
those H4 commands or make ramp decisions.

## 4. Effective Kill-Switch Authority

Current materialization, `src/api/policy_profiles.py:226-252`:

```python
if selected_stage is PhilippineSeedStage.SAFE_OFF:
    if balanced_basis_points not in (None, 0):
        raise OperationalProfilePolicyError()
    balanced = 0
    killed = True if kill_switch is None else kill_switch
    if killed is not True or rollback_window != "7d":
        raise OperationalProfilePolicyError()
    rollback_thresholds = _ROLLBACK_WARMUP
else:
    balanced = 3000 if balanced_basis_points is None else balanced_basis_points
    if (
        isinstance(balanced, bool)
        or not isinstance(balanced, int)
        or not 1000 <= balanced <= 4000
    ):
        raise OperationalProfilePolicyError()
    killed = False if kill_switch is None else kill_switch
    if not isinstance(killed, bool):
        raise OperationalProfilePolicyError()
    if selected_stage is PhilippineSeedStage.P3_W:
        if rollback_window != "7d":
            raise OperationalProfilePolicyError()
        rollback_thresholds = _ROLLBACK_WARMUP
    else:
        if rollback_window not in {"7d", "24h"}:
            raise OperationalProfilePolicyError()
        rollback_thresholds = _ROLLBACK_ACTIVE
```

The effective value is then written from `killed`, not inferred later from the
stage (`src/api/policy_profiles.py:261-266`):

```python
"RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS": "0",
"RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS": str(balanced),
"RESERVATION_ROLLOUT_KILL_SWITCH": "true" if killed else "false",
"RESERVATION_ROLLOUT_ROLLBACK_WINDOW": rollback_window,
```

Therefore the effective kill-switch key is the runtime authority. `stage` only
chooses/validates the reviewed profile family.

## 5. P2 Pre-Arm Representability

Application call shape:

```python
apply_philippine_seed_profile(
    store,
    tenant_id=T,
    generation=G,
    stage=PhilippineSeedStage.P3_W,
    balanced_basis_points=3000,
    kill_switch=True,
    rollback_window="7d",
)
```

Relevant materialized values are:

```text
RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS=0
RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS=3000
RESERVATION_ROLLOUT_KILL_SWITCH=true
RESERVATION_ROLLOUT_ROLLBACK_WINDOW=7d
warmup zero-plan/partial/cleanup maxima=1.0/1.0/1.0
generation=G
tenant_allowlist=T
```

The P3-W compatibility predicate at
`src/api/policy_profiles.py:328-333` is:

```python
compatible = (
    1000 <= balanced <= 4000
    and control.rollback_evaluation_window == "7d"
    and warmup
)
```

It contains no `control.kill_switch is False` condition. Thus non-zero BPS and
kill=true form a valid complete P3-W-policy snapshot. Because request-time
rollout checks the effective kill key, omitted traffic remains OFF during this
pre-arm state. No new generation or environment fallback is required.

**H3_P2_PREARM_REPRESENTABLE**

## 6. P3-W Disable-Kill-Last Representability

Starting from the preceding snapshot, H4 can call the same service with the
same `tenant_id=T`, `generation=G`, `stage=P3_W`, BPS `3000`, lease profile and
rollback window, changing only `kill_switch=False`.

The materializer keeps warmup thresholds by the P3-W branch
(`src/api/policy_profiles.py:245-248`), and compatibility still succeeds under
`src/api/policy_profiles.py:328-333`. The fixed Readiness map and caller-selected
lease pair are unchanged. Reapplication also reuses the existing Assignment
Secret rather than rotating it (`src/api/policy_profiles.py:582-600`).

At request time, the effective kill switch is checked before BPS assignment at
`src/api/reservation_rollout_control.py:668-678`:

```python
if (
    configuration is None
    or not configuration.enabled
    or configuration.kill_switch
    or planning_policy not in _ALLOWED_POLICIES
    or canonical_tenant not in configuration.tenant_allowlist
):
    return _default_off_decision()
basis_points = configuration.canary_basis_points(planning_policy)
```

Changing the effective key from true to false, after controlled restart, is the
actual authority change. No stage-based request-time branch exists.

**H3_P3W_DISABLE_KILL_LAST_REPRESENTABLE**

## 7. Active Kill Containment

For active P3-W, the same application call can preserve `T`, `G`, BPS `3000`,
P3-W warmup thresholds and lease/Readiness values while changing only
`kill_switch` from false to true. P3-W compatibility does not inspect kill.

For active P3-A, the same is true with:

```python
stage=PhilippineSeedStage.P3_A
balanced_basis_points=<same approved 1000..4000 value>
kill_switch=True
rollback_window=<same 7d or 24h value>
```

P3-A compatibility at `src/api/policy_profiles.py:334-339` is:

```python
compatible = (
    1000 <= balanced <= 4000
    and control.rollback_evaluation_window in {"7d", "24h"}
    and active
)
```

Again, no kill=false constraint exists. The profile keeps the active
`.30/.20/.20` threshold family. The caller passes the same generation, the
existing secure secret is read at lines 595-600, and no secret factory is used.

Consequently containment does not force BPS to zero, rotate generation, reset
thresholds, or rotate the secret.

**H3_ACTIVE_KILL_CONTAINMENT_REPRESENTABLE**

This result covers both requested sub-results:

- P3-W kill containment: REPRESENTABLE;
- P3-A kill containment: REPRESENTABLE.

## 8. P3-A / BPS Change Representability

P3-A accepts caller-selected Balanced BPS from `1000` through `4000` at
`src/api/policy_profiles.py:235-241`. It retains:

- Exact BPS `0` from line 261;
- the caller-provided unchanged generation and tenant from lines 259-260;
- active rollback thresholds selected at lines 249-252;
- fixed Readiness values inserted at line 257;
- the same approved lease profile at lines 222-224 and 255-256;
- the existing Assignment Secret at lines 582-600.

Thus future H4 can materialize a reviewed ramp or de-ramp by changing only
`balanced_basis_points` (and controlling kill as required by the operational
sequence). The service does not schedule, choose, or automatically apply a
ramp. The policy rule limiting routine movement to 1000 per review remains an
H4 operator-command/change-control obligation; H3 enforces the absolute
`1000..4000` envelope and complete snapshot validity.

**H3_GOVERNED_BPS_CHANGE_REPRESENTABLE**

## 9. Stage Compatibility Matrix

| Stage label | BPS | Kill accepted | Rollback window | Threshold family | Result |
|---|---:|---|---|---|---|
| `SAFE_OFF` | exactly `0` | only `true` | exactly `7d` | warmup | valid |
| `P3_W` | `1000..4000` | `true` or `false` | exactly `7d` | warmup | valid |
| `P3_A` | `1000..4000` | `true` or `false` | `7d` or `24h` | active `.30/.20/.20` | valid |

The exact validation source is `src/api/policy_profiles.py:318-341`. SAFE_OFF
explicitly requires kill=true. Neither P3-W nor P3-A requires kill=false.
Therefore:

- a P3-W or P3-A label can coexist with kill=true containment;
- P3-W pre-arm is valid with non-zero BPS and kill=true;
- a KILL snapshot does not become invalid solely because kill was activated;
- no additional authoritative stage or artificial generation is needed.

The label describes the reviewed threshold/profile family. The effective kill
key describes containment.

## 10. Stage Runtime Non-Authority

A production search for `stage ==`, `stage is`, `snapshot.stage`,
`PhilippineSeedStage`, and `.stage` across `main.py`, `src/api`, `src/services`,
`src/nodes`, and `run_matrix_factory.py` found stage logic only in
`src/api/policy_profiles.py`:

- enum and input parsing;
- profile threshold selection;
- snapshot serialization/parsing;
- stage/effective-value compatibility validation;
- audit result reporting.

`AppliedOperationalSnapshot.to_payload()` persists stage separately while
`effective_values` contains the actual runtime mapping
(`src/api/policy_profiles.py:379-394`). Activation copies only
`snapshot.effective_values` and the secure secret into the provider
(`src/api/policy_profiles.py:689-699`):

```python
runtime_mapping = dict(snapshot.effective_values)
runtime_mapping[ASSIGNMENT_SECRET_ENVIRONMENT_KEY] = assignment_secret
return RuntimeConfigProvider.create(
    paths=paths,
    static_operational_mapping=runtime_mapping,
    static_operational_status=StaticOperationalStatus.ACTIVE,
)
```

No `stage` entry is added. Reservation runtime code consumes only loader
configuration derived from this mapping. Canary assignment, kill, BPS,
breaker, HMAC bucket, lease, and Readiness do not reference stage.

**H3_STAGE_RUNTIME_NON_AUTHORITY_SOURCE_PROVEN**

## 11. Missing/Invalid Snapshot No-Env Proof

Packaged startup calls `load_applied_runtime_config_provider()` and installs its
result once (`main.py:130-148`). Missing state returns a provider whose mapping
is exactly `{}` (`src/api/policy_profiles.py:637-648,657-676`). Invalid state
returns the same empty mapping with `SAFE_OFF_INVALID`
(`src/api/policy_profiles.py:700-710`).

`reservation_runtime_mapping()` distinguishes source development from packaged
and test modes (`src/api/runtime_config.py:119-131`):

```python
if paths.mode is RuntimeMode.SOURCE_DEVELOPMENT:
    return os.environ
provider = get_runtime_config_provider()
if provider is None or provider.paths != paths:
    return _EMPTY_MAPPING
return provider.static_operational_mapping
```

The existing loaders use identity against `None`, not truthiness:

```python
source = os.environ if environ is None else environ
```

This is present at:

- lease: `src/api/reservation_lease.py:101-109`;
- Readiness: `src/api/reservation_rollout_readiness.py:183-194`;
- Rollout: `src/api/reservation_rollout_control.py:342-353`.

Therefore passing `{}` cannot trigger an `environ or os.environ` fallback.
The Rollout loader returns `None`, and the omitted-mode resolver returns
`DEFAULT_OFF` at `src/api/reservation_rollout_control.py:663-678`. Lease returns
an unconfigured object; Readiness returns `None`. No Seed environment merge
occurs in packaged mode.

**H3_EMPTY_MAPPING_NO_ENV_FALLBACK_SOURCE_PROVEN**

## 12. Atomic Apply Reconfirmation

`apply_philippine_seed_profile()` opens one caller-owned connection/transaction
at `src/api/policy_profiles.py:579`:

```python
with closing(store._connect()) as conn, conn:
```

On that same `conn`, it creates/reads secure schema state, writes a missing
secret through `store._set_on_connection(conn, ...)`, constructs and reparses
the snapshot, and replaces the snapshot row
(`src/api/policy_profiles.py:580-614`).

`SecretStore._set_on_connection()` uses the supplied connection for secure
INSERT, readback, decrypt, and equality verification
(`src/api/secret_store.py:300-331`):

```python
conn.execute("INSERT OR REPLACE INTO secure_settings ...", ...)
persisted = self._read_row(conn, key_name)
if persisted is None or self._decrypt_row(persisted) != value:
    raise SecretValueCorrupt()
```

Only after that verification does H3 write the snapshot row on the same
transaction. Leaving the context commits; any exception rolls back both.

**H3_ATOMIC_SECRET_SNAPSHOT_SOURCE_PROVEN**

## 13. Test Coverage Gaps

Current `tests/test_var001_seed_applied_snapshot.py` directly proves general
profile materialization, stage mismatch, atomicity, secret reuse, activation,
SAFE-OFF behavior, and immutable process snapshots. It does not directly lock
the complete operational transition matrix requested by R1.

| Required direct scenario | Current evidence | Classification |
|---|---|---|
| P2 pre-arm: BPS 3000 + kill true + warmup + same generation | no direct test | `TEST_GAP` |
| Disable kill last: pre-arm snapshot to P3-W active, otherwise identical | only a SAFE_OFF-to-P3-W/kill-false restart test exists | `TEST_GAP` |
| P3-W KILL containment preserving non-zero BPS/generation/thresholds/secret | no direct test | `TEST_GAP` |
| P3-A KILL containment preserving active thresholds/BPS/generation/secret | no direct test | `TEST_GAP` |
| Governed same-generation BPS change inside envelope | individual BPS materialization exists, but no transition/reapply preservation test | `TEST_GAP` |

The existing test at lines 546-568 proves that a newly loaded provider observes
a P3-W snapshot while the old provider remains immutable. It does not begin
from a pre-arm P3-W snapshot and does not prove kill-only transition identity.
The stage materialization test at lines 176-206 proves accepted individual
states, not transition preservation.

No tests were added or run in this read-only R1.

## 14. Findings Requiring Follow-Up

No production/source representability defect was found. In particular:

- P2 pre-arm is not blocked by a kill=false stage constraint;
- P3-W/P3-A containment does not force BPS zero or generation rotation;
- request-time runtime authority does not branch on stage;
- empty packaged mappings cannot fall through to process environment;
- atomic secret/snapshot application remains source-proven.

The narrow follow-up is test-only: add direct transition regressions for the
five `TEST_GAP` rows before treating the transition contract as regression-
closed for H4. H4 must also enforce the operational sequencing/approval rules,
including maximum routine BPS movement, because H3 intentionally provides no
automatic ramp engine.

Production fix needed: **NO**.

## 15. Git Status

Expected delta after this review is the existing H3 work plus only:

```text
?? doc/investigations/VAR001_PHASE3D2IB2B2RH3R1_TRANSITION_REPRESENTABILITY_SOURCE_PROOF.md
```

Final `git diff --check` and exact `git status --short` are recorded in the
completion response. No commit or push was performed.

## 16. Final Classification

- `H3_P2_PREARM_REPRESENTABLE = PASS`
- `H3_P3W_DISABLE_KILL_LAST_REPRESENTABLE = PASS`
- `H3_ACTIVE_KILL_CONTAINMENT_REPRESENTABLE = PASS`
- `H3_GOVERNED_BPS_CHANGE_REPRESENTABLE = PASS`
- `H3_STAGE_RUNTIME_NON_AUTHORITY_SOURCE_PROVEN = PASS`
- `H3_EMPTY_MAPPING_NO_ENV_FALLBACK_SOURCE_PROVEN = PASS`
- `H3_ATOMIC_SECRET_SNAPSHOT_SOURCE_PROVEN = PASS`
- direct transition regression closure = `TEST_FOLLOWUP_REQUIRED`

`VAR001_PHASE3D2IB2B2RH3R1_TRANSITION_TEST_FOLLOWUP_REQUIRED`
