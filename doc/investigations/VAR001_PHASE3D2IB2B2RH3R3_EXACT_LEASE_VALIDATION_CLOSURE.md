# VAR-001 Phase 3D-2I-B-2B-2R-H3-R3
# Exact Lease Profile Validation Closure

## 1. Executive Result

ChatGPT final source review found a real fail-closed validation defect in
`validate_philippine_seed_effective_values(...)`: the frozen Lease membership
check converted parsed positive finite floats to `int`, so non-canonical input
could truncate to an approved pair. H3-R3 reproduced the defect before changing
production code, replaced only that membership check with exact canonical
string-pair validation, and passed the focused and full regression gates.

The exact approved persisted representations remain:

- `("180", "45")`
- `("300", "60")`

Final H3-R3 classification:

```text
VAR001_PHASE3D2IB2B2RH3R3_EXACT_LEASE_VALIDATION_CLOSURE_PASS
```

This is not the independent ChatGPT H3 final-pass decision.

## 2. Repository Baseline

The closure began from the intentionally dirty H3/R1/R2 worktree without
resetting, restoring, stashing, cleaning, staging, committing, or pushing it.

```text
branch: feature/var-001-variation-policy
HEAD:   ad55cd6a41a0e9f7e1504aac7a5e07886a9f019a
RC1:    5f534b180dd2ae9fa9212e6632a44746669d7e6f
```

The previously existing H3 production, test, R1, and R2 changes were preserved.

## 3. Defect and Trigger

The prior check was semantically equivalent to:

```python
(
    int(lease.reservation_lease_ttl_seconds),
    int(lease.reservation_heartbeat_interval_seconds),
) not in _APPROVED_LEASES
```

The general Lease loader correctly accepts positive finite numeric values and
enforces the heartbeat relationship. That loader is broader than the frozen
Philippine Seed profile contract. Applying `int(...)` at the profile boundary
therefore admitted non-canonical representations through truncation or numeric
equivalence.

The regression covers all required invalid string pairs:

```text
("180.9", "45.1")
("300.9", "60.1")
("180.0", "45.0")
("0300", "060")
```

## 4. Red-Light Reproduction Before Production Fix

The new test was added first and then executed against the old production
implementation with this exact node ID:

```powershell
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_seed_applied_snapshot.py::SeedInventoryAndProfileTests::test_noncanonical_lease_snapshot_values_fail_closed -q
```

Complete failure output:

```text
uuuuuuF                                                                  [100%]
================================== FAILURES ===================================
_ SeedInventoryAndProfileTests.test_noncanonical_lease_snapshot_values_fail_closed _

self = <tests.test_var001_seed_applied_snapshot.SeedInventoryAndProfileTests testMethod=test_noncanonical_lease_snapshot_values_fail_closed>

    def test_noncanonical_lease_snapshot_values_fail_closed(self):
        legal_values = dict(
            materialize_philippine_seed_profile(
                tenant_id=TENANT,
                generation=GENERATION,
                stage=PhilippineSeedStage.SAFE_OFF,
            )
        )
        invalid_pairs = (
            ("180.9", "45.1"),
            ("300.9", "60.1"),
            ("180.0", "45.0"),
            ("0300", "060"),
        )
        for ttl, heartbeat in invalid_pairs:
            drifted = dict(legal_values)
            drifted["RESERVATION_LEASE_TTL_SECONDS"] = ttl
            drifted["RESERVATION_HEARTBEAT_INTERVAL_SECONDS"] = heartbeat
>           with self.subTest(ttl=ttl, heartbeat=heartbeat), self.assertRaisesRegex(
                OperationalProfilePolicyError,
                OPERATIONAL_PROFILE_POLICY_VIOLATION,
            ):
E           AssertionError: OperationalProfilePolicyError not raised

tests\test_var001_seed_applied_snapshot.py:274: AssertionError
_ SeedInventoryAndProfileTests.test_noncanonical_lease_snapshot_values_fail_closed _
ttl = '180.9', heartbeat = '45.1'
_ SeedInventoryAndProfileTests.test_noncanonical_lease_snapshot_values_fail_closed _
ttl = '300.9', heartbeat = '60.1'
_ SeedInventoryAndProfileTests.test_noncanonical_lease_snapshot_values_fail_closed _
ttl = '180.0', heartbeat = '45.0'
_ SeedInventoryAndProfileTests.test_noncanonical_lease_snapshot_values_fail_closed _
ttl = '0300', heartbeat = '060'

self = <tests.test_var001_seed_applied_snapshot.SeedInventoryAndProfileTests testMethod=test_noncanonical_lease_snapshot_values_fail_closed>

    def test_noncanonical_lease_snapshot_values_fail_closed(self):
        legal_values = dict(
            materialize_philippine_seed_profile(
                tenant_id=TENANT,
                generation=GENERATION,
                stage=PhilippineSeedStage.SAFE_OFF,
            )
        )
        invalid_pairs = (
            ("180.9", "45.1"),
            ("300.9", "60.1"),
            ("180.0", "45.0"),
            ("0300", "060"),
        )
        for ttl, heartbeat in invalid_pairs:
            drifted = dict(legal_values)
            drifted["RESERVATION_LEASE_TTL_SECONDS"] = ttl
            drifted["RESERVATION_HEARTBEAT_INTERVAL_SECONDS"] = heartbeat
            with self.subTest(ttl=ttl, heartbeat=heartbeat), self.assertRaisesRegex(
                OperationalProfilePolicyError,
                OPERATIONAL_PROFILE_POLICY_VIOLATION,
            ):
                validate_philippine_seed_effective_values(
                    drifted,
                    stage=PhilippineSeedStage.SAFE_OFF,
                    assignment_secret=SYNTHETIC_SECRET,
                )

        for ttl, heartbeat in (("180", "45"), ("300", "60")):
            approved = dict(legal_values)
            approved["RESERVATION_LEASE_TTL_SECONDS"] = ttl
            approved["RESERVATION_HEARTBEAT_INTERVAL_SECONDS"] = heartbeat
            with self.subTest(approved_ttl=ttl, approved_heartbeat=heartbeat):
                validate_philippine_seed_effective_values(
                    approved,
                    stage=PhilippineSeedStage.SAFE_OFF,
                    assignment_secret=SYNTHETIC_SECRET,
                )

        self.apply()
        payload = json.loads(self.snapshot_text())
        payload["effective_values"]["RESERVATION_LEASE_TTL_SECONDS"] = "180.9"
        payload["effective_values"][
            "RESERVATION_HEARTBEAT_INTERVAL_SECONDS"
        ] = "45.1"
        invalid_serialized = canonical_snapshot_json(payload)
        self.assertEqual(
            invalid_serialized,
            canonical_snapshot_json(json.loads(invalid_serialized)),
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE app_settings SET key_value = ? WHERE key_name = ?;",
                (invalid_serialized, OPERATIONAL_SNAPSHOT_SETTING_KEY),
            )

        environment_fallback = dict(legal_values)
        environment_fallback[ASSIGNMENT_SECRET_ENVIRONMENT_KEY] = (
            "synthetic-environment-assignment-secret"
        )
        with temporary_test_runtime_paths(self.root / "runtime-invalid-lease") as paths:
            with patch.dict(os.environ, environment_fallback, clear=False):
                provider = load_applied_runtime_config_provider(paths, self.store)
                with temporary_runtime_config_provider(provider):
                    active_mapping = reservation_runtime_mapping()

>       self.assertEqual(
            provider.static_operational_status,
            StaticOperationalStatus.SAFE_OFF_INVALID,
        )
E       AssertionError: <StaticOperationalStatus.ACTIVE: 'ACTIVE'> != <StaticOperationalStatus.SAFE_OFF_INVALID: 'SAFE_OFF_INVALID'>

tests\test_var001_seed_applied_snapshot.py:322: AssertionError
=========================== short test summary info ===========================
SUBFAILED(ttl='180.9', heartbeat='45.1') tests/test_var001_seed_applied_snapshot.py::SeedInventoryAndProfileTests::test_noncanonical_lease_snapshot_values_fail_closed
SUBFAILED(ttl='300.9', heartbeat='60.1') tests/test_var001_seed_applied_snapshot.py::SeedInventoryAndProfileTests::test_noncanonical_lease_snapshot_values_fail_closed
SUBFAILED(ttl='180.0', heartbeat='45.0') tests/test_var001_seed_applied_snapshot.py::SeedInventoryAndProfileTests::test_noncanonical_lease_snapshot_values_fail_closed
SUBFAILED(ttl='0300', heartbeat='060') tests/test_var001_seed_applied_snapshot.py::SeedInventoryAndProfileTests::test_noncanonical_lease_snapshot_values_fail_closed
FAILED tests/test_var001_seed_applied_snapshot.py::SeedInventoryAndProfileTests::test_noncanonical_lease_snapshot_values_fail_closed
5 failed, 2 subtests passed in 2.45s
```

This establishes both halves of the defect: all four invalid pairs escaped the
frozen profile validator, and a representative canonical persisted snapshot
activated as `ACTIVE` instead of failing closed.

## 5. Minimal Production Correction

`src/api/policy_profiles.py` now derives canonical string pairs from the
unchanged business-value set:

```python
_APPROVED_LEASES = frozenset({(180, 45), (300, 60)})
_APPROVED_LEASE_VALUE_PAIRS = frozenset(
    (str(ttl), str(heartbeat)) for ttl, heartbeat in _APPROVED_LEASES
)
```

The frozen profile validator compares the original effective-value strings
directly:

```python
(
    values[RESERVATION_LEASE_TTL_ENV],
    values[RESERVATION_HEARTBEAT_INTERVAL_ENV],
) not in _APPROVED_LEASE_VALUE_PAIRS
```

The existing Lease loader is still invoked first and its general parsing and
relationship validation are unchanged. No float equality, rounding,
truncation, numeric tolerance, new Lease profile, schema change, or
materializer change was introduced.

## 6. Regression Added

The independently collected test method is:

```text
test_noncanonical_lease_snapshot_values_fail_closed
```

It starts with a legal complete 32-key effective mapping, replaces the two
Lease strings directly, and proves:

- every required non-canonical pair raises
  `OperationalProfilePolicyError` with
  `OPERATIONAL_PROFILE_POLICY_VIOLATION`;
- exact `180/45` and `300/60` strings still validate;
- a persisted canonical snapshot carrying `180.9/45.1` loads as
  `StaticOperationalStatus.SAFE_OFF_INVALID`;
- both provider static mapping and active Reservation runtime mapping are
  empty even when a complete environment fallback is present;
- loading the invalid snapshot does not rewrite its database value.

The test uses synthetic data, temporary RuntimePaths, and a temporary SQLite
database only.

## 7. Post-Fix Test Results

### Exact node

```powershell
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_seed_applied_snapshot.py::SeedInventoryAndProfileTests::test_noncanonical_lease_snapshot_values_fail_closed -q
```

```text
1 passed, 6 subtests passed in 1.71s
```

### Complete H3 focused module

```powershell
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_seed_applied_snapshot.py -q
```

```text
23 passed, 23 subtests passed in 9.37s
```

The subtest increase from 17 to 23 is intentional: four invalid pairs and two
approved pairs are individually exercised. The five H3-R2 transition tests
remain in this green focused module.

### H2 + H1 affected regression

```powershell
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_dpapi_secret_store.py tests/test_var001_runtime_paths_bootstrap.py -q
```

```text
45 passed, 2 warnings, 3 subtests passed in 28.26s
```

### Reservation / Task regression

```powershell
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_reservation_lease.py tests/test_var001_reservation_rollout_readiness.py tests/test_var001_reservation_rollout_control.py tests/test_var001_reservation_runtime_acceptance.py tests/test_var001_reservation_terminal.py tests/test_var001_planner_reservation.py tests/test_var001_reservation_diagnostics.py tests/test_var001_reservation_public_activation.py tests/test_var001_public_reservation_activation.py tests/test_var001_clean_task_identity.py tests/test_var001_public_task_lifecycle_guard.py -q
```

```text
212 passed, 100 warnings, 128 subtests passed in 95.37s
```

### Full pytest regression

```powershell
.\venv_build\Scripts\python.exe -m pytest tests -q
```

```text
605 passed, 1 skipped, 120 warnings, 240 subtests passed in 146.05s
```

No failure or error occurred. The existing skip count did not increase.

### Static compilation

```powershell
.\venv_build\Scripts\python.exe -m py_compile src/api/policy_profiles.py tests/test_var001_seed_applied_snapshot.py
```

Exit code: `0`.

## 8. Preserved Authority and Scope

- Assignment Secret storage, validation, and no-rotation semantics are
  unchanged.
- Stage remains validation/audit metadata and is not runtime rollout
  authority.
- Generation, BPS, kill-switch, Readiness, Rollout, and Reservation algorithms
  are unchanged.
- Snapshot schema and runtime schema are unchanged.
- The only H3-R3 production-code edit is in `src/api/policy_profiles.py`.
- No H4 command, transition governance, or operator behavior was implemented.
- H3-R1 and H3-R2 artifacts remain unchanged historical evidence.

## 9. Security and Runtime-State Boundary

No real Secret, ciphertext, credential, `.env`, production database, tenant
database, output, Delivery artifact, backup, service, build, migration, or
network request was used. Tests used only synthetic secrets and temporary
isolated state. No Git staging, commit, or push occurred. `handoffs.md` was not
created or updated.

## 10. Final Git Evidence

`git diff --check` completed with exit code `0` and no output.

`git diff --stat` reports the preserved tracked H3 delta (the H3 production,
test, and report additions are untracked and therefore are not included in
this Git stat):

```text
 main.py                                          |  38 ++++++--
 src/api/reservation_lease.py                     |   3 +
 src/api/reservation_rollout_control.py           |  27 ++++--
 src/api/reservation_rollout_readiness.py         |  18 +++-
 src/api/routes_dsl.py                            |   9 +-
 src/api/routes_reservation_diagnostics.py        |  13 ++-
 src/api/runtime_config.py                        | 108 ++++++++++++++++++++++-
 tests/test_var001_reservation_rollout_control.py |   1 +
 8 files changed, 196 insertions(+), 21 deletions(-)
```

Final `git status --short`:

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
?? doc/investigations/VAR001_PHASE3D2IB2B2RH3R3_EXACT_LEASE_VALIDATION_CLOSURE.md
?? doc/investigations/VAR001_PHASE3D2IB2B2RH3_PHILIPPINE_SEED_APPLIED_SNAPSHOT_IMPLEMENTATION.md
?? src/api/policy_profiles.py
?? tests/test_var001_seed_applied_snapshot.py
```

Compared with the initial inventory, H3-R3 added only its allowed evidence
artifact and changed only the three already allowed H3 files. No unrelated
path appeared.

## 11. Proof Markers

- `H3R3_NONCANONICAL_LEASE_REPRODUCED = PASS`
- `H3R3_EXACT_LEASE_STRING_VALIDATION = PASS`
- `H3R3_INVALID_SNAPSHOT_SAFE_OFF = PASS`
- `H3R3_APPROVED_LEASE_PAIRS_PRESERVED = PASS`
- `H3R3_H3R2_TRANSITIONS_PRESERVED = PASS`
- `H3R3_FULL_REGRESSION = PASS`
- `H3R3_SCOPE_CONTROL = PASS`

`VAR001_PHASE3D2IB2B2RH3R3_EXACT_LEASE_VALIDATION_CLOSURE_PASS`
