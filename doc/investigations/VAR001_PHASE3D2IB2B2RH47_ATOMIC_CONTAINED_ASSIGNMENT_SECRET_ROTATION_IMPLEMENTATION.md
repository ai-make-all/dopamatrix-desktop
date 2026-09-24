# VAR-001 H4-7 Atomic Contained Assignment Secret Rotation

## 1. Scope

This report records the bounded H4-7 implementation of:

```text
secret assignment rotate
  --tenant ID
  --expected-generation G
  --new-generation G2
  --backup-bundle PATH
  --approval-ref REF
```

The implementation adds no other secret command, generic generation edit,
recovery, import, export, reveal, force path, automatic containment, restore,
packaging, H4-8, H5, or H6 work.

## 2. Baseline

```text
branch=feature/var-001-variation-policy
HEAD=aa57869cef93cf7e0aaf09fa815d513a3bb6e091
origin/feature/var-001-variation-policy=aa57869cef93cf7e0aaf09fa815d513a3bb6e091
v1.5-phseed-rc1=5f534b180dd2ae9fa9212e6632a44746669d7e6f
initial_worktree=clean
initial_index=empty
```

No Git mutation was performed.

## 3. H4-7-R0 Rotation Authority Decision Closure

The governing independent authority gate is:

```text
VAR001_PHASE3D2IB2B2RH47R0_ROTATION_AUTHORITY_DECISION_PASS
```

The decision closes the final reconnaissance blocker as follows:

- all four canonical Seed states with `kill=true` are rotation-eligible:
  `SAFE_OFF`, `P3_W`, `P3_A/7d`, and `P3_A/24h`;
- P3_A/24h rotation preserves `stage=P3_A`, `rollback_window=24h`, and
  `kill=true`; it does not activate traffic or weaken H4-6's separate
  transition/activation fail-closed rule;
- every P3_W/P3_A state with `kill=false` is rejected without automatic
  containment;
- both supplied generations use the strict H4-6 tenant-bound operator
  validator;
- generation authority is valid-and-different only; there is no invented
  same-day, monotonic-date, monotonic-revision, or `rN+1` rule;
- a generated Secret equal to the authoritative old Secret fails before write
  with exit 4 and
  `OPERATOR_ASSIGNMENT_SECRET_ROTATION_NO_CHANGE`;
- rotation has no idempotent-success result: a repeated request fails the
  authoritative expected-generation precondition.

## 4. Production Delta

### New rotation service

`src/api/operator_secret.py` implements:

- strict approved-tenant validation;
- strict expected/new generation validation;
- bounded approval-ref validation;
- H4-5 backup reverify and exact tenant match before RuntimePaths;
- H4-3 OS mutation barrier;
- one caller-owned global SQLite connection;
- one checked `BEGIN IMMEDIATE` transaction;
- authoritative snapshot and current Secret reread/decrypt;
- complete canonical prestate validation;
- local CSPRNG generation only after prestate validation;
- same-value rejection before any write;
- connection-bound Secret write and decrypt verification;
- new-generation canonical snapshot build and reread validation;
- same-transaction snapshot write;
- one commit or complete rollback;
- bounded stable outcomes without secret-derived data.

### CLI dispatch

`src/api/operator_cli.py` retains the frozen grammar and replaces only the
rotate placeholder dispatch with a lazy call to `rotate_assignment_secret()`.
The existing human and one-object JSON output contract remains authoritative.

### Placeholder inventory

The now-obsolete H4-7 placeholder assertions were removed or converted to
dispatch proof in:

- `tests/test_var001_operator_cli.py`;
- `tests/test_var001_operator_status.py`;
- `tests/test_var001_runtime_mutation_foundation.py`;
- `tests/test_var001_operator_backup.py`;
- `tests/test_var001_operator_tenant_provision.py`.

No unrelated test contract was changed.

## 5. Pure Input and External Evidence Order

Execution order before mutation is:

```text
approved tenant validation
-> expected-generation strict validation
-> new-generation strict validation
-> approval-ref validation
-> supplied generations must differ
-> complete H4-5 backup verification
-> exact bundle tenant match
-> RuntimePaths initialization
-> H4-3 mutation barrier
```

Corrupt, missing, or wrong-tenant backup evidence therefore fails before
RuntimePaths, the barrier, SQLite, Secret generation, or mutation.

## 6. Authoritative Transaction

Inside one caller-owned SQLite connection, H4-7 executes:

```text
BEGIN IMMEDIATE
-> reread canonical snapshot row
-> reread current secure row
-> decrypt and validate current Secret
-> parse/canonical-validate snapshot with current Secret
-> validate tenant, expected generation, embedded generation, and kill=true
-> generate a new Secret locally
-> validate nonempty string
-> reject new == old
-> SecretStore._set_on_connection(new Secret)
-> connection-bound row reread/decrypt/equality verification
-> copy all current effective values
-> replace only RESERVATION_ROLLOUT_GENERATION
-> build snapshot with unchanged stage and new Secret
-> canonical_json()
-> parse/canonical validate with new Secret
-> _write_snapshot_on_connection()
-> one commit
```

`checked_immediate_transaction()` rolls back on every exception. The focused
suite injects failures after the Secret write and during new-row decrypt
verification and proves that both Secret and snapshot rows remain byte-for-byte
unchanged.

The ordinary H3 `apply_philippine_seed_profile()` API is not called because it
owns another connection.

## 7. Current Secret Is Mandatory

Rotation is not recovery. The service fails before Secret generation or write
when:

- the current Secret row is absent;
- DPAPI/protector decrypt fails;
- decrypted Secret data is blank or corrupt;
- the snapshot is missing, malformed, noncanonical, or cannot be validated
  with the current Secret.

No missing or corrupt Secret state triggers replacement generation.

## 8. Stage and Containment Matrix

| Canonical current state | Result |
|---|---|
| SAFE_OFF / kill=true / 7d warmup | rotation allowed |
| P3_W / kill=true / 7d warmup | rotation allowed |
| P3_A / kill=true / 7d active | rotation allowed |
| P3_A / kill=true / 24h active | rotation allowed |
| P3_W / kill=false | exit 4, no write |
| P3_A / 7d / kill=false | exit 4, no write |
| P3_A / 24h / kill=false | exit 4, no write |

The service has no stage whitelist beyond successful canonical H3 parsing and
the explicit `kill=true` containment check.

## 9. Generation Contract

Both generations must have exact form:

```text
phseed-<derived-tenantcode>-bal-YYYYMMDD-rN
```

The calendar date must be real, `N >= 1`, and tenant code must correspond to
the exact approved tenant. Inside `BEGIN IMMEDIATE`, the canonical snapshot
generation and embedded rollout generation must both equal
`--expected-generation`.

The suite directly accepts:

```text
old=phseed-elv0001-bal-20260921-r1
new=phseed-elv0001-bal-20240103-r9
```

This proves there is no date or revision sequencing policy.

## 10. Complete Preservation

Successful rotation changes only:

- secure-row ciphertext and storage timestamp;
- `RESERVATION_ROLLOUT_GENERATION`;
- snapshot applied timestamp;
- bounded audit metadata;
- canonical snapshot bytes necessarily reflecting those values.

It preserves:

- canonical tenant and one-entry tenant allowlist;
- stage;
- Balanced and Exact BPS;
- `kill=true`;
- both Lease values;
- all Readiness values and thresholds;
- rollback window;
- warmup or active rollback threshold family;
- every other non-secret effective value.

Tests compare the complete 32-key mapping and require that only the generation
entry differs.

## 11. P3_A/24h and Restart Semantics

The mandatory P3_A/24h regression proves:

- rotation returns `ROTATED`;
- stage remains `P3_A`;
- window remains `24h`;
- kill remains true;
- BPS, Lease, Readiness, and active thresholds remain unchanged;
- the current provider retains the old generation and Secret;
- a newly loaded provider observes the new generation and Secret.

The CLI reports `restart_required=true`; it does not claim a restart occurred.

## 12. Audit Metadata

The replacement snapshot writes only:

```text
operator_command=secret.assignment.rotate
approval_ref=<validated external reference>
```

Approval-ref is external metadata, not authentication or evidence of genuine
human approval. Generations remain authoritative in the prestate and resulting
snapshot and are not duplicated in audit metadata. No separate evidence
database is introduced.

## 13. Output and Redaction

Success status is exactly:

```text
ROTATED
```

Approved data keys are exactly:

```text
tenant
old_generation
new_generation
kill_switch
assignment_secret_status
restart_required
```

The message and data contain no Secret value, length, hash, prefix, suffix,
ciphertext, protector blob, HMAC material, raw snapshot, or 32-key mapping.
Human success uses stdout only. JSON mode emits one schema-version-1 object to
stdout with empty stderr.

## 14. Repeat Rotation

After successful `G -> G2`, an identical second invocation still reverifies
the backup and enters the authoritative transaction, where current generation
`G2` does not equal expected generation `G`. It exits 4 with
`OPERATOR_SEED_SNAPSHOT_STATE_INVALID`, does not generate another Secret, and
writes nothing. There is no `ALREADY_ROTATED`.

## 15. Focused Tests

New focused file:

```text
tests/test_var001_operator_secret_rotation.py
```

Coverage includes:

- SAFE_OFF, P3_W, P3_A/7d, and P3_A/24h success;
- full 32-key policy preservation;
- current/new provider restart boundary;
- caller-owned connection enforcement;
- all required active-state rejections;
- expected/new strict and cross-tenant generation rejection;
- same-generation rejection;
- authoritative generation mismatch;
- nonsequential historical generation success;
- generated same-Secret no-write failure;
- stale repeated rotation;
- backup ordering and tenant match;
- absent, corrupt, and blank old Secret;
- malformed snapshot;
- new-row decrypt verification rollback;
- post-Secret-write rollback;
- authoritative in-transaction reread;
- actual mutation-barrier contention;
- human/JSON dispatch, bounded shape, and redaction.

## 16. Verification

### Focused H4-7

```text
.\venv_build\Scripts\python.exe -m pytest tests\test_var001_operator_secret_rotation.py -q --basetemp <fresh-isolated-temp>
21 passed, 13 subtests passed, 0 failed, 0 errors, 1 warning
```

### Relevant H2/H3/H4

```text
.\venv_build\Scripts\python.exe -m pytest tests\test_var001_operator_secret_rotation.py tests\test_var001_dpapi_secret_store.py tests\test_var001_seed_applied_snapshot.py tests\test_var001_operator_status.py tests\test_var001_runtime_mutation_foundation.py tests\test_var001_operator_backup.py tests\test_var001_operator_seed_transitions.py tests\test_var001_operator_cli.py tests\test_var001_operator_tenant_provision.py tests\test_var001_runtime_paths_bootstrap.py tests\test_var001_packaged_console_contract.py tests\test_var001_v15_backup_restore.py -q --basetemp <fresh-isolated-temp>
242 passed, 2 skipped, 374 subtests passed, 0 failed, 0 errors, 3 warnings
```

### Full backend

```text
.\venv_build\Scripts\python.exe -m pytest tests -q --basetemp <fresh-isolated-temp>
757 passed, 2 skipped, 580 subtests passed, 0 failed, 0 errors, 121 warnings
```

The skips and warnings are existing platform, framework deprecation, and
pytest cache conditions.

### Compile and diff

```text
py_compile changed/new Python: exit 0
git diff --check: exit 0
IDE lints: none
```

## 17. Protected Modules

No modification was required to:

```text
src/api/policy_profiles.py
src/api/secret_store.py
src/api/runtime_mutation.py
src/api/operator_backup.py
src/api/backup_restore.py
src/api/operator_seed.py
src/api/database.py
```

No dependency, package, build, installer, frontend, Tauri, Rust, or runtime
artifact change was made.

## 18. Classification

```text
VAR001_PHASE3D2IB2B2RH47_ATOMIC_CONTAINED_ASSIGNMENT_SECRET_ROTATION_IMPLEMENTATION_PASS
```

This is an implementation result, not an independent ChatGPT FINAL PASS.
No commit or push was performed. H4-8 remains unstarted.

## 19. H4-7-R1 Existing-DB Non-Create Open Fixup

Independent source review issued:

```text
VAR001_PHASE3D2IB2B2RH47R1_EXISTING_DB_NONCREATE_OPEN_FIXUP_REQUIRED
```

The review confirmed that the original H4-7 default connection factory used:

```python
sqlite3.connect(database, timeout=5.0)
```

Although the production path first checked `settings_db_path.is_file()`, that
check and the later SQLite open were not atomic. If the database disappeared
between them, ordinary SQLite read/write-create behavior could leave a new
empty database at the authoritative RuntimePaths location even though
subsequent prestate validation failed.

R1 changes only the H4-7 connection factory. It resolves the existing database
strictly and opens its file URI with `mode=rw`:

```python
uri = database.resolve(strict=True).as_uri() + "?mode=rw"
sqlite3.connect(uri, uri=True, timeout=5.0)
```

The open retains read/write transaction authority but cannot create the main
database, schema, directories, WAL, SHM, or rollback journal. A disappearance
or open failure remains bounded by the existing `OSError`/`sqlite3.Error`
mapping to exit 8 and `OPERATOR_SEED_SUBSYSTEM_FAILED`; raw exception text is
not emitted. The preliminary `is_file()` check remains the ordinary clearly
missing-state projection but is no longer creation protection.

Two direct regressions were added:

- `_default_connection()` against a missing path raises and leaves no main DB,
  WAL, SHM, or journal;
- a valid fixture is renamed after the `is_file()` guard but immediately
  before the real connection factory opens it. The command returns exit 8,
  does not call the Secret factory, does not recreate any SQLite artifact at
  the original path, and preserves the renamed original bytes exactly.

The repeat-rotation regression now injects one counting backup verifier across
both calls. It proves count 1 after the successful first call and count 2
after the stale second call, while the second Secret factory is not called,
both rows remain unchanged, and no `ALREADY_ROTATED` result is returned.

The transaction architecture and all accepted H4-7 contracts are unchanged:

```text
backup reverify
-> RuntimePaths
-> H4-3 barrier
-> existing-only global DB open
-> BEGIN IMMEDIATE
-> authoritative prestate validation
-> Secret generation/write/decrypt verification
-> new-generation snapshot build/write
-> one commit or rollback
```

Superseding R1 verification:

- focused H4-7:
  `23 passed, 13 subtests passed`, zero failures/errors;
- relevant H2/H3/H4:
  `244 passed, 2 skipped, 374 subtests passed`, zero failures/errors;
- full backend:
  `759 passed, 2 skipped, 580 subtests passed`, zero failures/errors;
- every changed/new Python file: `py_compile` exit 0;
- `git diff --check`: exit 0;
- IDE diagnostics: none.

No protected foundation module, grammar, dependency, package, commit, remote
state, or H4-8 implementation changed.
