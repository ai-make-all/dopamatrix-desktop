# VAR-001 Phase 3D-2I-B-2B-2R-H3-R2
# Philippine Seed Transition Regression Closure

## 1. Executive Result

The five direct transition regression gaps identified by H3-R1 are closed.
All focused, affected Reservation/Task, H2/H1, and full repository pytest runs
pass with no failures or errors. The tests exercise the persisted applied
snapshot and packaged runtime-provider seam; containment tests additionally
exercise the ordinary omitted-mode resolver and prove `DEFAULT_OFF` from the
effective kill switch.

No H3 production contradiction was found and no production source was changed
by R2. Stage remains non-authoritative metadata, generation and Assignment
Secret remain stable across ordinary transitions, and process snapshots remain
immutable until a newly initialized provider is loaded.

## 2. H3-R1 Test Gaps

The preserved R1 artifact source-proved transition representability but found
five direct `TEST_GAP` items:

1. P2 pre-arm with P3-W policy, BPS 3000, and kill=true;
2. disable-kill-last activation preserving all other governed state;
3. P3-W kill containment preserving non-zero BPS and generation;
4. P3-A kill containment preserving tightened thresholds;
5. governed same-generation P3-A BPS change.

R2 added one direct regression for each gap in
`tests/test_var001_seed_applied_snapshot.py`. R1 was not rewritten.

## 3. P2 Pre-Arm Regression

`test_p2_prearm_is_complete_but_stage_does_not_activate_canary` applies:

```text
stage=P3_W
tenant=T
generation=G
Balanced=3000
Exact=0
kill=true
rollback window=7d
warmup quality/cleanup maxima=1.0/1.0/1.0
```

The test reparses and validates the persisted canonical snapshot, checks its
stage/tenant/generation and exact warmup values, proves the secret is not in
snapshot JSON, loads a packaged/test provider, and calls the actual omitted-mode
resolver. The result is `OFF / DEFAULT_OFF` because effective kill is true.

`H3R2_P2_PREARM_REGRESSION_PROVEN = PASS`

## 4. Disable-Kill-Last Regression

`test_disable_kill_last_preserves_prearm_state_until_restart` starts from the
pre-arm snapshot, reapplies the same tenant, generation, BPS, Exact value,
Lease, Readiness, rollback window, and warmup thresholds with kill=false, and
compares the complete effective mappings after removing only the kill key.

It also proves the existing provider retains kill=true after the database
transition, while a newly loaded provider observes kill=false and Balanced
3000. The secure Assignment Secret value is unchanged and absent from snapshot
JSON.

`H3R2_DISABLE_KILL_LAST_REGRESSION_PROVEN = PASS`

## 5. P3-W Kill Containment Regression

`test_p3w_kill_containment_preserves_authoritative_state` starts from active
P3-W and reapplies kill=true. Complete mapping comparison proves that only the
kill key changes. Balanced remains 3000; tenant, generation, Lease, Readiness,
rollback window, warmup thresholds, Exact BPS, and Assignment Secret remain
unchanged. The resulting provider returns `OFF / DEFAULT_OFF` for omitted
traffic.

`H3R2_P3W_KILL_CONTAINMENT_REGRESSION_PROVEN = PASS`

## 6. P3-A Kill Containment Regression

`test_p3a_kill_containment_preserves_tightened_policy` starts from P3-A with an
approved non-zero BPS and kill=false, then reapplies kill=true. It proves only
the kill key changes and explicitly checks that Balanced remains non-zero,
generation remains `G`, coverage remains 1.0, safety remains 0, and tightened
zero-plan/partial/cleanup maxima remain `.30/.20/.20`. The Assignment Secret is
unchanged and absent from snapshot JSON.

`H3R2_P3A_KILL_CONTAINMENT_REGRESSION_PROVEN = PASS`

## 7. Governed BPS Change Regression

`test_p3a_governed_bps_change_preserves_all_other_authority` reapplies a P3-A
snapshot from one approved BPS to another approved BPS inside `1000..4000`.
Complete mapping comparison proves only the Balanced BPS key changes. Tenant,
generation, Exact=0, kill state, Lease, Readiness, tightened thresholds, and
Assignment Secret remain unchanged.

The test intentionally asserts absolute H3 envelope behavior only. It does not
encode KEEP/RAMP/DE_RAMP, automatic ramping, or the H4 per-review operator
change rule.

`H3R2_GOVERNED_BPS_CHANGE_REGRESSION_PROVEN = PASS`

## 8. Stage Non-Authority Regression

The P2 pre-arm test directly combines `stage=P3_W`, Balanced 3000, and
kill=true, then calls the production omitted-mode resolver. The result remains
`DEFAULT_OFF`. No Reservation source was changed to read stage.

`H3R2_STAGE_NON_AUTHORITY_REGRESSION_PROVEN = PASS`

## 9. Generation / Secret Stability

All repeated-apply transition tests explicitly preserve and compare generation.
No pre-arm activation, P3-W containment, P3-A containment, or BPS change
rotates it.

Each repeated-apply test reads the synthetic secret only inside its isolated
temporary test process, proves exact value stability, checks that the second
apply reports no secret creation, and proves the secret is absent from the
persisted snapshot text. It is not logged, printed, or recorded here.

- `H3R2_GENERATION_STABILITY_PROVEN = PASS`
- `H3R2_ASSIGNMENT_SECRET_STABILITY_PROVEN = PASS`

## 10. Restart Activation Semantics

The disable-kill-last test loads the pre-arm process provider before reapply.
After reapply, that provider still exposes its immutable kill=true mapping.
Only a new `load_applied_runtime_config_provider()` result observes kill=false.
No hot reload or provider mutation was introduced.

`H3R2_STATIC_RESTART_SEMANTICS_PRESERVED = PASS`

## 11. Focused Test Results

Command:

```text
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_seed_applied_snapshot.py -q
```

Result:

```text
22 passed
17 subtests passed
0 failed / 0 errors
6.01s (final rerun)
```

The pre-R2 module contained 17 tests. The increase to 22 is exactly the five
transition regressions.

## 12. Reservation / H2 / H1 Regression

H2 secret-store plus H1 runtime/bootstrap:

```text
45 passed
3 subtests passed
0 failed / 0 errors
22.15s
```

The same Reservation/Task group used by H3, including rollout-control, Lease,
Readiness, runtime acceptance, terminal, planner, diagnostics, both public
activation suites, clean Task Identity, and lifecycle guard:

```text
212 passed
128 subtests passed
0 failed / 0 errors
93.31s
```

`H3R2_RESERVATION_SEMANTICS_UNCHANGED = PASS`

## 13. Full Pytest Result

Command:

```text
.\venv_build\Scripts\python.exe -m pytest tests -q
```

Result:

```text
604 passed
1 skipped
234 subtests passed
120 warnings
0 failed / 0 errors
141.78s (final rerun)
```

The pre-R2 baseline was 599 passed, one skipped, and 234 subtests. No existing
test was lost; the five-test increase exactly matches R2.

## 14. Scope Check

R2 changed only:

- `tests/test_var001_seed_applied_snapshot.py`;
- the bounded H3 implementation-report closure subsection;
- this R2 evidence artifact.

No production source, Reservation algorithm, policy materializer, snapshot
schema, secret architecture, HMAC, stage semantics, RuntimePaths, frontend,
Tauri, `.env`, database, tenant, output, Delivery, backup, build, version, or
tag was changed. No real secret, network, service, or production runtime state
was used. No H4 operator command or ramp decision was implemented.

- `H3R2_NO_PRODUCTION_SOURCE_FIX_REQUIRED = PASS`
- `H3R2_NO_H4_SCOPE_CREEP = PASS`

## 15. Git Diff

Final tracked diff summary:

```text
8 files changed, 196 insertions(+), 21 deletions(-)
```

Git does not include untracked files in that statistic. The H3/R1/R2 untracked
additions are the 711-line profile module, 821-line focused test module,
511-line H3 report, 483-line R1 proof, and this R2 report. R2's code delta is
test-only; the underlying H3 production delta remains the intentionally
uncommitted accepted implementation.

## 16. Git Status

Final state:

```text
 M main.py
 M src/api/reservation_lease.py
 M src/api/reservation_rollout_control.py
 M src/api/reservation_rollout_readiness.py
 M src/api/routes_dsl.py
 M src/api/routes_reservation_diagnostics.py
 M src/api/runtime_config.py
 M tests/test_var001_reservation_rollout_control.py
?? doc/investigations/VAR001_PHASE3D2IB2B2RH3R1_TRANSITION_REPRESENTABILITY_SOURCE_PROOF.md
?? doc/investigations/VAR001_PHASE3D2IB2B2RH3R2_TRANSITION_REGRESSION_CLOSURE.md
?? doc/investigations/VAR001_PHASE3D2IB2B2RH3_PHILIPPINE_SEED_APPLIED_SNAPSHOT_IMPLEMENTATION.md
?? src/api/policy_profiles.py
?? tests/test_var001_seed_applied_snapshot.py
```

Because the H3 focused test and report were already untracked, Git reports R2
edits within them as untracked files rather than separate `M` lines. No commit
or push was performed.

## 17. Final Classification

- `H3R2_P2_PREARM_REGRESSION_PROVEN = PASS`
- `H3R2_DISABLE_KILL_LAST_REGRESSION_PROVEN = PASS`
- `H3R2_P3W_KILL_CONTAINMENT_REGRESSION_PROVEN = PASS`
- `H3R2_P3A_KILL_CONTAINMENT_REGRESSION_PROVEN = PASS`
- `H3R2_GOVERNED_BPS_CHANGE_REGRESSION_PROVEN = PASS`
- `H3R2_STAGE_NON_AUTHORITY_REGRESSION_PROVEN = PASS`
- `H3R2_GENERATION_STABILITY_PROVEN = PASS`
- `H3R2_ASSIGNMENT_SECRET_STABILITY_PROVEN = PASS`
- `H3R2_STATIC_RESTART_SEMANTICS_PRESERVED = PASS`
- `H3R2_RESERVATION_SEMANTICS_UNCHANGED = PASS`
- `H3R2_NO_PRODUCTION_SOURCE_FIX_REQUIRED = PASS`
- `H3R2_NO_H4_SCOPE_CREEP = PASS`

R2:

`VAR001_PHASE3D2IB2B2RH3R2_TRANSITION_REGRESSION_CLOSURE_PASS`

Final H3:

`VAR001_PHASE3D2IB2B2RH3_SEED_APPLIED_SNAPSHOT_PASS`
