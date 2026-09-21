# VAR-001 Phase 3D-2I-B-2B-2R-H4-R0
# Packaged Operator CLI Source / Contract Audit

## 1. Executive Summary

This is a source-read-only, evidence-only audit. It implements no H4 command.
Claims use four labels:

- **SOURCE-PROVEN** — directly established by current source;
- **FROZEN-REQUIREMENT** — inherited from accepted architecture/operations;
- **PROPOSED-FOR-CHATGPT-REVIEW** — a future H4 contract, not implementation;
- **BLOCKED / NOT-PROVEN** — current source cannot establish the property.

The H1 seam is real: `main.py` resolves bootstrap state and checks the
`operator` prefix before dotenv, FastAPI, database, routers, logger, Ngrok, or
render imports. Current behavior is only an H1 placeholder returning exit code
2. RuntimePaths, DPAPI SecretStore, the H3 profile/snapshot service, tenant
schema initializer, and tenant backup/verify functions are reusable cores.

H4 orchestration is missing. Current services do not by themselves enforce
prior-state transitions, readiness/backup/Delivery approval gates, a
maximum-per-review BPS delta, governed generation changes, operator
serialization, backend quiescence, or atomic Assignment Secret rotation plus
new-generation snapshot replacement. Read-only status helpers also open SQLite
in ways that may create a database/table on a fresh install.

Two packaging facts require ChatGPT decisions before implementation:

1. `build_backend.py` builds with `--windowed` and generated `backend.spec`
   has `console=False`; reliable terminal stdout/stderr for
   `backend.exe operator ...` is therefore **NOT-PROVEN**.
2. no cross-process server/operator lock exists. Static Seed mutation is
   restart-activated and must not race a running backend or a second operator.

Audit classification:

```text
VAR001_PHASE3D2IB2B2RH4R0_PACKAGED_OPERATOR_CLI_SOURCE_CONTRACT_AUDIT_COMPLETE
VAR001_PHASE3D2IB2B2RH4R0_IMPLEMENTATION_GATE_REVIEW_REQUIRED
```

## 2. Scope / Non-Goals

Performed:

- read current Git metadata, source, local ignored handoff, and accepted docs;
- traced bootstrap/import order, runtime roots, profile/secret transactions,
  tenant provisioning, backup/verify, packaging, and field procedures;
- proposed contracts and bounded implementation slices for ChatGPT review.

Not performed:

- no source, test, packaging, runbook, existing report, handoff, DB, runtime,
  index, tag, branch, or remote mutation;
- no pytest, service, build, migration, tenant creation, profile apply, secret
  rotation, backup, restore, or network operation;
- no H0-H3 reopening and no H4 production implementation;
- no H5 claim that packaged `.env` or Ngrok debt is already removed.

## 3. Git Baseline

All values matched before the report was created:

| Fact | Actual | Result |
|---|---|---|
| Branch | `feature/var-001-variation-policy` | MATCH |
| HEAD | `bc5840d80502a39e06afab4c172846a1412f1955` | MATCH |
| HEAD summary | `bc5840d (HEAD -> feature/var-001-variation-policy, origin/feature/var-001-variation-policy) feat(v1.5): harden Philippine Seed runtime snapshot` | MATCH |
| Local origin ref | `bc5840d80502a39e06afab4c172846a1412f1955` | MATCH |
| Immutable RC1 | `5f534b180dd2ae9fa9212e6632a44746669d7e6f` | MATCH |
| Initial `git status --short` | empty | CLEAN |
| Initial index delta | empty | CLEAN |
| Target report | absent | SAFE TO CREATE |

Only local refs were read; no fetch or pull occurred.

## 4. Governing Evidence Read

The complete local coordination entry was read first:

- `.codex-local/handoffs.md` — current phase, closed-phase gates, current Git
  anchor, and H4-R0 questions.

Accepted evidence was consulted narrowly, not re-audited:

- `doc/investigations/VAR001_PHASE3D2IB2B2R_RELEASE_PACKAGING_HANDOFF_PREFLIGHT.md`;
- `doc/investigations/VAR001_PHASE3D2IB2B2RH0R1_BOOTSTRAP_RUNTIME_SOURCE_EXCERPTS.md`;
- `doc/investigations/VAR001_PHASE3D2IB2B2RH1_RUNTIME_PATHS_BOOTSTRAP_IMPLEMENTATION.md`;
- `doc/investigations/VAR001_PHASE3D2IB2B2RH2_DPAPI_SECRET_CREDENTIAL_MIGRATION_IMPLEMENTATION.md`;
- H3 implementation, H3-R1, H3-R2, and H3-R3 reports;
- tenant identity constitution, provisioning audit, and provisioning acceptance;
- runtime-config/secret constitution and release-field boundary;
- Philippine Seed Execution Pack and Canary/backup runbooks.

The current source remains implementation authority.

## 5. Exact Source Inventory

| Area | Current source and narrow anchors | Audit use |
|---|---|---|
| Early bootstrap | `main.py:21-41`; `src/api/bootstrap.py:16-44` | argv prefix, RuntimePaths initialization, placeholder, pre-app import order |
| Runtime roots | `src/api/runtime_paths.py:42-52,58-69,97-165,168-201` | packaged/source/test roots and directory mutation |
| Static provider | `src/api/runtime_config.py:39-88,96-131` | immutable process snapshot and no packaged env fallback |
| Global/tenant DB | `src/api/database.py:71-80,398-407,417-480` | import-time Engine, canonicalization, lazy tenant initialization |
| Seed profile | `src/api/policy_profiles.py:190-347,374-535,539-716` | materialization, exact validation, persistence, startup load |
| Secret store | `src/api/secret_store.py:24-100,227-372,487-517` | allowlist, safe codes, DPAPI-backed status/read/write behavior |
| Diagnostics core | `src/api/reservation_rollout_readiness.py`; `src/api/reservation_rollout_control.py:342-408,795-898`; `src/api/reservation_diagnostics.py` | readiness, breaker, rollout and summary evidence |
| HTTP adapters | `src/api/routes_reservation_diagnostics.py:158-285` | current route wrappers; not suitable as CLI dependency |
| Dynamic Delivery | `src/api/delivery_output.py:46-102`; `src/api/settings_router.py:53-129` | Delivery prerequisite and read-through side effects |
| Tenant backup | `src/api/backup_restore.py:1-180,384-454,510-617,635-773` | source backup/verify/restore primitives and CLI |
| Packaging | `build_backend.py:61-97,153-236`; `backend.spec:4-38` | PyInstaller graph and console mode |
| Tauri sidecar | `web_ui/src-tauri/tauri.conf.json:27-38`; `web_ui/src-tauri/src/lib.rs:63-112` | external binary inclusion and no-argument normal spawn |

## 6. Packaged Startup / Import Graph Proof

### Current order

**SOURCE-PROVEN:** `main.py:14-31` imports only stdlib plus
`src.api.bootstrap`, calls `prepare_bootstrap(sys.argv)`, and exits through the
placeholder when `__name__ == "__main__"` and argv element 1 is `operator`.
Dotenv begins at `main.py:37-41`; FastAPI/database/router imports begin at
`main.py:58-85`; `FastAPI(...)` is constructed at `main.py:190-200`; Uvicorn is
entered only at `main.py:301-312`.

**SOURCE-PROVEN:** `prepare_bootstrap()` recognizes only the exact second argv
token (`src/api/bootstrap.py:22-29`). No parser or command dispatcher exists.
The placeholder prints `OPERATOR_COMMANDS_NOT_IMPLEMENTED_H1` and returns 2
(`src/api/bootstrap.py:42-44`).

**SOURCE-PROVEN:** the earliest current interception point is
`main.py:29-31`. A future explicit import such as an operator dispatcher inside
that branch can run and exit without importing the normal application graph.
It must remain before `apply_server_compatibility_cwd()`, dotenv, and all
application imports.

### Side-effect caveat

**SOURCE-PROVEN:** interception is not completely mutation-free today.
`prepare_bootstrap()` first calls `initialize_runtime_paths()`
(`bootstrap.py:25`), which creates the runtime root and tenant `data/`
directory (`runtime_paths.py:156-165,192-194`). It does not create `output/`,
open SQLite, or initialize schema.

**PROPOSED-FOR-CHATGPT-REVIEW:** parse the operator namespace before normal
application imports, then let the dispatcher initialize RuntimePaths only for
commands that require them. `help` and syntax-error paths should use the
side-effect-free `resolve_runtime_paths()` or no runtime path at all. This is a
bounded bootstrap refactor, not an architecture redesign.

### Command-module import discipline

**PROPOSED-FOR-CHATGPT-REVIEW:** the dispatcher module must import only stdlib
and bootstrap-safe path types at module import. Command handlers lazily import
database, policy, secret, tenant, diagnostics, or backup modules after the
operator branch has been selected. No command imports `main.py`, a router, or
the FastAPI app.

`src.api.database` constructs an absolute-path SQLAlchemy Engine at import
(`database.py:71-80`) but does not initialize schema until a connection path is
used. `src.api.backup_restore` currently imports `database` at module scope
(`backup_restore.py:26-31`). This is acceptable only after operator dispatch;
it is not bootstrap-safe before dispatch.

### Packaged inclusion and terminal behavior

**SOURCE-PROVEN:** PyInstaller analyzes `main.py` with one-file packaging
(`build_backend.py:198-209`). A normal explicit Python import from the future
operator branch should enter the static graph. Dynamically named/importlib-only
modules would need a hidden import; current generated spec has none
(`backend.spec:4-16`). Final inclusion remains a built-artifact test, not a
source-only guarantee.

**SOURCE-PROVEN:** Tauri bundles `bin/backend` as `externalBin` and starts it
with no operator arguments (`tauri.conf.json:27-31`; `lib.rs:79-95`). Ordinary
desktop startup therefore remains server mode.

**BLOCKED / NOT-PROVEN:** PyInstaller is invoked with `--windowed`
(`build_backend.py:203-206`) and the generated spec says `console=False`
(`backend.spec:19-38`). Reliable terminal stdout/stderr and exit-code evidence
for an independently invoked Windows `backend.exe operator ...` is not proven.
ChatGPT must choose a console-capable single binary, a separately packaged
operator executable, or another reviewed output channel. A silent GUI-subsystem
binary is not an acceptable field CLI contract.

## 7. Existing Capability Inventory

| Capability | Classification | Existing authority | Reuse boundary |
|---|---|---|---|
| Pre-app `operator` recognition | SOURCE-PROVEN | `main.py:29-31`, `prepare_bootstrap()` | Replace placeholder with bounded dispatcher |
| Packaged runtime root | SOURCE-PROVEN | `RuntimePaths`, `initialize_runtime_paths()` | Reuse; never CWD for mutable authority |
| Immutable process config | SOURCE-PROVEN | `RuntimeConfigProvider` | Reuse; mutations require restart |
| Snapshot load/fail-closed | SOURCE-PROVEN | `load_applied_runtime_config_provider()` | Reuse internally; project safe status only |
| H3 materialization/validation | SOURCE-PROVEN | `materialize_philippine_seed_profile()`, validators | Reuse unchanged policy values |
| Atomic ordinary apply | SOURCE-PROVEN | `apply_philippine_seed_profile()` | Reuse for named transitions after orchestration guards |
| SAFE_OFF/P3_W/P3_A representation | SOURCE-PROVEN | `policy_profiles.py:208-347` | Reuse; stage is metadata/validation only |
| Assignment Secret create-if-absent | SOURCE-PROVEN | apply service lines 584-620 | Reuse only for initial ordinary apply |
| Assignment Secret status | SOURCE-PROVEN with adapter need | `SecretStore.get_status()` | Output enum only; avoid schema-creating status read |
| Assignment Secret rotation | MISSING | none | New atomic rotation+snapshot service required |
| Readiness/rollout/summary calculation | SOURCE-PROVEN | non-router service functions | Reuse with explicit tenant Session/mapping |
| Tenant schema initialization | SOURCE-PROVEN | `get_tenant_engine()` | Strict pre-validation/collision/verification adapter required |
| Tenant registry / approved-ID persistence | MISSING | none | Do not invent authority silently; decision required |
| Backup create/verify | SOURCE-PROVEN | `create_backup_bundle()`, `verify_backup_bundle()` | Pass `RuntimePaths.runtime_root`; add CLI path guards |
| Packaged backup entry | MISSING | source `python -m` only | Add operator adapter/static inclusion |
| Operator concurrency/quiescence lock | MISSING | none found | Required before mutations |
| Stable operator exit taxonomy | MISSING | backup CLI only returns 0/2 | Proposed below |

## 8. Reuse-vs-Gap Matrix

| Domain | Direct reuse | Safe adapter/orchestration required | Missing capability |
|---|---|---|---|
| Bootstrap | Runtime mode/root resolution | early argv parser and lazy command imports | real dispatcher/help/output contract |
| Runtime status | path dataclass; snapshot loader | non-mutating DB/table inspection; redacted projection | stable human/JSON schema |
| Seed apply | H3 materializer, validator, atomic apply | prior-state CAS, readiness/breaker/backup/Delivery gates, command lock | named transitions and change-control audit inputs |
| Kill | H3 accepts kill=true with same stage/BPS | preserve current snapshot fields and expected generation | named containment command |
| BPS | H3 absolute envelope 1000..4000 | compare current BPS; require killed state; max delta 1000 | reviewed edit command; no automatic decision |
| Generation | H3 syntax validation | compare old/new and restrict allowed epoch transitions | general governed rebaseline contract remains undecided |
| Secret | DPAPI store and caller-owned connection helper | present/absent/error projection | atomic explicit rotation with contained new-generation snapshot |
| Tenant | canonicalizer, schema/Ledger initializer | strict constitution, collision barrier, post-create verification | packaged provision command and registry/allowlist decision |
| Backup | online SQLite copy, manifest, hashes, verify, cleanup | bind source root to RuntimePaths; destination safety | packaged create/verify commands |
| Packaging | one-file sidecar static graph | explicit operator module inclusion | console-safe operator execution not proven |

## 9. Proposed Minimal Command Tree

All syntax below is **PROPOSED-FOR-CHATGPT-REVIEW**, not implemented:

```text
backend.exe operator config status [--json]
backend.exe operator tenant provision --tenant ID --tenant-code CODE --approval-ref REF
backend.exe operator seed status --tenant ID [--json]
backend.exe operator seed apply-safe-off --tenant ID --generation G --approval-ref REF [--lease-profile 180-45|300-60]
backend.exe operator seed prearm-p3w --tenant ID --generation G --verified-backup PATH --approval-ref REF
backend.exe operator seed activate --tenant ID --generation G --approval-ref REF
backend.exe operator seed kill --tenant ID --generation G --reason-code CODE
backend.exe operator seed set-balanced-bps --tenant ID --generation G --bps N --approval-ref REF
backend.exe operator seed transition-p3a --tenant ID --generation G --rollback-window 7d|24h --verified-backup PATH --approval-ref REF
backend.exe operator secret assignment status [--json]
backend.exe operator secret assignment rotate --tenant ID --expected-generation G --new-generation G2 --verified-backup PATH --approval-ref REF
backend.exe operator backup create --tenant ID --destination ABSOLUTE_NEW_DIRECTORY
backend.exe operator backup verify --bundle ABSOLUTE_BUNDLE_DIRECTORY
```

Named commands own stage/threshold semantics. There is deliberately no generic
`set KEY=VALUE`, raw snapshot import, plaintext-secret argument, automatic
ramp, arbitrary allowlist edit, or generic generation edit. Restore-to-staging
already exists in source but is outside the minimum H4 capability list in this
audit.

## 10. Per-Command Contract Matrix

The two tables together record every required field for every proposed
command. `REF` is a non-secret change/approval reference. Raw secrets are never
accepted as arguments.

### 10.1 Inputs, authority, validation, and preconditions

| Exact proposed syntax | Class | Authority/source service | Required arguments | Prohibited/defaulted arguments | Validation | Preconditions |
|---|---|---|---|---|---|---|
| `operator config status [--json]` | read-only | RuntimePaths; non-mutating snapshot/table inspection | none | no tenant, mutation, secret, or raw DB path; human format default | runtime mode recognized; root resolvable | none; missing DB is reported, not created |
| `operator tenant provision --tenant ID --tenant-code CODE --approval-ref REF` | mutating | strict identity adapter then `get_tenant_engine()` | exact ID, non-authoritative short code, approval ref | no customer name, force, overwrite, HTTP header, or DB path | constitution regex; sequence range; approved country/vertical; raw equals canonical; short-code mapping; reserved/case-normalized DB/sidecar, Delivery, backup collisions | server quiescent; exclusive operator lock; all collision checks pass |
| `operator seed status --tenant ID [--json]` | read-only | non-mutating snapshot reader; secret status projection; readiness/rollout/summary services | exact tenant | no secret display, mutation, stage override, or environment fallback | exact canonical tenant; snapshot canonical/profile-valid if present | tenant DB already exists; status must never provision it |
| `operator seed apply-safe-off --tenant ID --generation G --approval-ref REF [--lease-profile 180-45\|300-60]` | mutating | H3 `apply_philippine_seed_profile()` | tenant, generation, approval | no BPS/stage/kill/threshold/secret input; lease defaults `180-45` | exact tenant; generation governance; lease enum; H3 validators | initial missing snapshot, or separately approved contained rebaseline; server quiescent; lock; tenant provisioned |
| `operator seed prearm-p3w --tenant ID --generation G --verified-backup PATH --approval-ref REF` | mutating | H3 apply plus diagnostics and backup verify | current tenant/generation, bundle, approval | BPS fixed 3000; Exact 0; kill true; warmup fixed; no new generation/secret | bundle valid/tenant-matching; snapshot valid; readiness READY; breaker clear; Delivery/Lease valid | current SAFE_OFF same tenant/generation; server quiescent; lock |
| `operator seed activate --tenant ID --generation G --approval-ref REF` | mutating | H3 apply preserving current effective family | current tenant/generation, approval | no BPS/stage/threshold/lease/secret edit | current P3_W/P3_A; snapshot valid; readiness READY; breaker clear; BPS in envelope | kill=true; pre-arm/tightening restart-verified; backup/Delivery current; server quiescent; lock |
| `operator seed kill --tenant ID --generation G --reason-code CODE` | mutating/risk-reducing | H3 apply preserving stage/family | current tenant/generation, bounded reason | no BPS/generation/threshold/tenant/lease/secret change | current snapshot valid and identity exact | server quiescent; lock; P3_W/P3_A; already killed is idempotent |
| `operator seed set-balanced-bps --tenant ID --generation G --bps N --approval-ref REF` | mutating | H3 apply preserving stage/family | current tenant/generation, integer BPS, approval | no Exact/stage/kill/threshold/lease/secret edit | `1000..4000`; absolute delta from current `<=1000`; Exact remains 0 | P3_W/P3_A, kill=true, same identity, server quiescent, lock; no automatic decision |
| `operator seed transition-p3a --tenant ID --generation G --rollback-window 7d\|24h --verified-backup PATH --approval-ref REF` | mutating | H3 P3_A materialization plus diagnostics | current identity, window, bundle, approval | no BPS/generation/tenant/lease/secret change; kill fixed true | P3_W cohort passes reviewed active thresholds; readiness READY; breaker clear; bundle tenant match | current P3_W kill=true; server quiescent; lock; human review recorded |
| `operator secret assignment status [--json]` | read-only | non-mutating secure-row inspection and DPAPI verification | none | no value/hash/length/ciphertext/prefix/suffix | fixed allowlisted key only | missing DB/table yields ABSENT without creation |
| `operator secret assignment rotate --tenant ID --expected-generation G --new-generation G2 --verified-backup PATH --approval-ref REF` | mutating/high-risk | new caller-owned SecretStore+snapshot transaction | tenant, old/new generation, bundle, approval | no supplied secret, force, same generation, or active state | snapshot valid; kill=true; `G2 != G`; governed generation; valid matching bundle | server quiescent; lock; containment restart-verified; remediation/change control complete |
| `operator backup create --tenant ID --destination ABS` | mutating derived artifact | `create_backup_bundle()` | exact tenant, absolute new destination | no `--project-root`, overwrite, Delivery source, relative path | tenant exact; DB exists; destination physical/absent/outside runtime output and Delivery | tenant provisioned; parent usable; ordinary DB writes allowed |
| `operator backup verify --bundle ABS` | read-only | `verify_backup_bundle()` | absolute bundle | no tenant override, repair, overwrite, restore, relative path | format, paths, hashes, catalog, SQLite integrity | bundle exists/readable; no runtime DB required |

### 10.2 State, transaction, concurrency, output, failure, and tests

| Command | State read / mutated | Transaction / locking / idempotency | Restart | Safe output | Exit / rollback | Tests required | Evidence status |
|---|---|---|---|---|---|---|---|
| `config status` | reads mode/root and DB/snapshot presence; mutates none | read-only; repeatable; no mutation lock | no | version, mode, root availability, snapshot status/error; JSON v1; no DB/secret values | 0 or 2/3/5/8/9; no rollback | no app imports; fresh install no files; redaction; JSON | adapter PROPOSED; roots SOURCE-PROVEN |
| `tenant provision` | reads namespaces; creates tenant DB/schema/Ledger only | existing DDL is not one all-or-none transaction; server-quiescent + exclusive lock; existing is conflict | no provider activation | canonical ID, relative DB name, schema/Ledger/zero-data result | 0 or 2/3/4/7/8/9; preserve partial DB and return review code | validation/collisions, schema/Ledger/zero rows, injected partial failure | initializer SOURCE-PROVEN; command PROPOSED |
| `seed status` | reads snapshot, secret state, tenant diagnostics; none mutated | read-only; repeatable; must not lazy-provision | no | stage metadata, tenant/generation/BPS/kill/lease/family/readiness/breaker; secret enum only | 0 or 2/3/5/6/8/9 | missing/invalid/corrupt, no env/secret/tenant creation | cores SOURCE-PROVEN; projection PROPOSED |
| `apply-safe-off` | reads prior snapshot/secret; writes snapshot and secret only if absent | H3 single transaction; lock; exact prior-state check; exact reapply policy to review | required | SAFE_OFF, identity, 0/0, kill true, secret PRESENT/created boolean, restart required | 0 or 2/3/4/8/9; H3 rollback | missing/existing secret, atomic faults, no rotation, restart | H3 apply SOURCE-PROVEN; prior guard PROPOSED |
| `prearm-p3w` | reads current/evidence/bundle; writes P3_W 3000/kill=true | H3 transaction after gates; lock + stale-state guard; same target may be no-op | required | P3_W, 3000, kill true, same generation/secret, backup VALID | 0 or 2/3/4/5/6/8/9; no write on failed gate | every precondition; preservation; stage non-authority | representation SOURCE-PROVEN; orchestration PROPOSED |
| `activate` | reads contained state/evidence; writes kill true->false only | H3 transaction; lock + stale guard; already active behavior to review | required | kill change and preservation summary | 0 or 2/3/4/6/8/9; no write on gate failure | disable-kill-last, preservation, stale/evidence failures | representation SOURCE-PROVEN; command PROPOSED |
| `kill` | reads current; writes kill false->true only | H3 transaction; lock + stale guard; already true returns `ALREADY_CONTAINED` without rewrite | required | contained plus same BPS/generation/family/secret | 0 or 2/3/4/8/9; atomic snapshot | P3_W/P3_A preservation, idempotency, restart | representation/tests SOURCE-PROVEN; command PROPOSED |
| `set-balanced-bps` | reads current; writes BPS and audit/timestamp only | H3 transaction; lock + stale guard; same BPS no-op preferred | required | old/new BPS, delta, preserved fields | 0 or 2/3/4/8/9; reject before write | envelope/delta edges; killed precondition; no automatic ramp | envelope SOURCE-PROVEN; delta FROZEN/PROPOSED |
| `transition-p3a` | reads P3_W/cohort/bundle; writes P3_A family/window with kill true | H3 transaction; lock + stale guard; exact target no-op preferred | required, then separate activate | P3_A family/window, same BPS/generation/secret, kill true | 0 or 2/3/4/6/8/9 | thresholds, cohort gates, same generation, kill-last separation | representation SOURCE-PROVEN; orchestration PROPOSED |
| `secret assignment status` | reads fixed row/decryptability; mutates none | read-only and repeatable | no | exactly PRESENT/ABSENT/ERROR; JSON v1 | 0 or 2/8/9 | fresh absent no DB creation; corrupt; no derived material | enum SOURCE-PROVEN; adapter PROPOSED |
| `secret assignment rotate` | reads killed snapshot/secret/bundle; writes new secret + new-generation snapshot | one new caller-owned transaction; exclusive lock + CAS; never silently repeat | required | ROTATED, old/new generation, kill true, secret PRESENT; no derived data | 0 or 2/3/4/5/6/8/9; both writes rollback together | containment/same-gen reject, injected atomic faults, redaction, restart | connection helper SOURCE-PROVEN; rotation MISSING |
| `backup create` | reads tenant DB/catalog/output; writes staging/final bundle | online backup + staging publish; same destination rejected | no | VALID, tenant, bundle, counts/asset count; JSON v1 | 0 or 2/3/4/5/6/8/9; staging removed, final absent | root binding, destination safety, concurrent writes, cleanup, no Delivery | core SOURCE-PROVEN; packaged adapter PROPOSED |
| `backup verify` | reads bundle; mutates none | read-only/repeatable | no | VALID, tenant, asset/count summary | 0 or 2/3/5/6/8/9 | every manifest/hash/path/catalog/integrity failure; no repair | SOURCE-PROVEN core; packaged adapter PROPOSED |

## 11. Exit-Code Proposal

This taxonomy is **PROPOSED-FOR-CHATGPT-REVIEW**, not frozen:

| Exit | Category | Examples |
|---:|---|---|
| 0 | success | valid status, completed mutation, valid backup |
| 2 | usage | unknown command or invalid/missing argument |
| 3 | validation/policy | invalid tenant/generation/BPS/profile compatibility |
| 4 | state/precondition/concurrency | backend active, lock busy, stale generation, wrong stage/kill, readiness/breaker/approval gate failure |
| 5 | not found | tenant DB, bundle, required snapshot, or namespace missing |
| 6 | integrity/verification | invalid backup/snapshot/schema/Ledger evidence |
| 7 | partial mutation review | tenant initialization left a preserved partial DB |
| 8 | platform/storage/secret subsystem | DPAPI, filesystem, SQLite, or runtime-root failure |
| 9 | bounded internal failure | unexpected error mapped without traceback or unsafe context |

Each failure also has one stable symbolic code. Human output is bounded;
`--json` is one object with `schema_version`, `command`, `status`, `error_code`,
and approved non-sensitive fields. Existing backup `0/2` is a precedent, not a
complete taxonomy (`backup_restore.py:724-769`).

## 12. Transaction / Concurrency / Restart Matrix

| Operation | Existing atomicity | Gap | Restart |
|---|---|---|---|
| status | none needed | non-mutating read adapters required | no |
| ordinary apply | secret create-if-absent + snapshot share one transaction (`policy_profiles.py:584-620`) | no prior-state CAS, process lock, or quiescence proof | required |
| kill/BPS/stage transition | representable through ordinary apply | same CAS/lock gap; H3 has no transition preconditions | required |
| secret rotation | SecretStore supports caller-owned connection (`secret_store.py:300-331`) | no atomic rotation+snapshot service | required |
| tenant provision | initializer disposes on failure (`database.py:436-461`) | no all-or-none DDL or process lock; partial file may remain | server must be quiescent |
| backup create | online SQLite snapshot + staging publish (`backup_restore.py:384-454`) | packaged root/path adapter | no |
| backup verify | read-only | packaged entry only | no |

**BLOCKED / NOT-PROVEN:** no current process lock, PID/instance authority,
operator lock, or snapshot compare-and-swap exists. SQLite writer
serialization alone permits last-writer-wins after stale reads.

**PROPOSED-FOR-CHATGPT-REVIEW:** use a small runtime-root lock protocol: server
holds a lifetime active lock; Seed/secret/tenant mutations require its absence
and an exclusive operator lock; status/verify may coexist; backup create may
coexist with the server. Re-read expected tenant/generation/stage inside the
mutation boundary. The exact Windows crash-releasing primitive requires review;
a PID-file existence check alone is insufficient.

## 13. Seed Transition Governance Proof

| Boundary | Evidence | H4 obligation |
|---|---|---|
| pre-arm first | P3_W permits non-zero BPS with either kill value (`policy_profiles.py:237-255,334-339`) | prearm writes 3000/kill=true; activate is separate |
| disable kill last | same materializer can preserve P3_W and set kill false | activate accepts no other edits |
| containment preservation | P3_W/P3_A compatibility does not require kill=false (`policy_profiles.py:334-345`) | kill changes only kill |
| Exact always 0 | materializer/validator (`policy_profiles.py:264,313`) | expose no Exact input |
| Balanced 1000..4000 | materializer/validator (`policy_profiles.py:238-244,336-343`) | reject outside envelope |
| delta <=1000 | frozen runbook `DOPAMATRIX_V15_PHILIPPINE_SEED_CANARY_RUNBOOK.md:253-256`; not in H3 | compare persisted BPS; no automatic ramp |
| one non-zero tenant | H3 requires one allowlist member (`policy_profiles.py:312`) | bind all transitions to current tenant; no generic allowlist edit |
| generation governed | H3 validates syntax only (`policy_profiles.py:199-205`) | preserve except initial/explicit reviewed epoch command |
| stage non-authority | stage use is confined to `policy_profiles.py`; provider gets effective mapping (`policy_profiles.py:699-705`) | never use stage in request-time Reservation |
| static immutability | copied `MappingProxyType`; conflicting reinstall rejected (`runtime_config.py:60-79,96-111`) | report restart required; no hot reload |
| no ordinary rotation | apply generates only if absent, otherwise reuses (`policy_profiles.py:588-606`) | rotation remains separate high-risk command |

**BLOCKED / NOT-PROVEN:** H3 does not enforce delta, prior-state order,
backup/Delivery/readiness gates, or governed generation epochs. H4 must add
reviewed orchestration without changing frozen policy semantics.

## 14. Secret-Safety / Redaction Contract

**SOURCE-PROVEN:** the secure allowlist is fixed (`secret_store.py:24-38`),
public SecretStore error text is stable (`secret_store.py:59-100`), writes
encrypt and decrypt-verify on the caller connection (`secret_store.py:300-331`),
and snapshots persist only key name plus PRESENT status
(`policy_profiles.py:385-400`). Startup never generates; ordinary apply creates
only when absent and otherwise reuses (`policy_profiles.py:584-606`).

**FROZEN-REQUIREMENT:** status emits only PRESENT/ABSENT/ERROR. Never emit
plaintext, ciphertext, hash, length, prefix/suffix, tokenized URL, raw/chained
exception, or secret-bearing traceback. Rotation accepts no secret input and
requires containment, new generation, verified change control, atomic
secret+snapshot write, and controlled restart.

**BLOCKED / NOT-PROVEN:** `SecretStore.get_status()` calls `get_secret()`, whose
normal SQLite path creates `secure_settings` if absent
(`secret_store.py:339-365`). A read-only adapter must report an absent DB/table
without creating it and DPAPI-check an existing row without exposing material.

## 15. Tenant Provision Findings

### Reusable core

**SOURCE-PROVEN:** `get_tenant_engine()` canonicalizes the input, derives the
RuntimePaths tenant DB, creates an Engine, runs application schema checks and
Fingerprint Ledger initialization, disposes on exception, and caches only a
successful Engine (`database.py:436-461`). A one-shot operator process avoids
long-lived cache concerns. No creative task is required.

### Validation and collision gaps

**SOURCE-PROVEN:** `canonical_tenant_id()` is a sanitizer, not the production
constitution: it retains `isalnum`, `_`, and `-`, drops other characters,
case-normalizes, and defaults empty to `default` (`database.py:417-428`). The
frozen production grammar is narrower:
`^[a-z]{2}-[a-z0-9]{3,5}-[0-9]{4}$`, ASCII lowercase, sequence 0001..9999,
raw equals canonical, reserved namespace excluded
(`DOPAMATRIX_V15_TENANT_IDENTITY_CONSTITUTION.md:26-51,151-164`).

**PROPOSED-FOR-CHATGPT-REVIEW:** before importing/using the initializer, the
command must validate the constitution and approved vertical registry, then
check all of these for the exact target across the full namespace barrier:

- DB, `-wal`, and `-shm` absence plus case-normalized filename collision;
- no existing Delivery tenant subtree owned by another allocation;
- no backup namespace collision;
- no reserved/test identity or prior failed allocation;
- server quiescence and exclusive operator lock.

`tenant-code` is recorded only as the approved operator alias and must match
`<vertical><sequence4>`; it is never passed to DB, request, Reservation, backup,
or Delivery authority.

### Failure and verification

**SOURCE-PROVEN / historical accepted evidence:** failure disposes the Engine
but may leave a partial SQLite file; automatic deletion was deliberately not
the accepted provisioning behavior. H4 must stop, preserve the file and safe
error class, return exit 7, and prohibit retry/overwrite pending review.

**MISSING:** no production service performs the full post-provision acceptance
as one bounded operation. The operator adapter must reopen separately and
verify SQLite integrity, application tables/rollout metadata, Ledger schema
version 2, and zero business rows without dumping records. This is bounded
field tooling, not a tenant registry or AUTH-001.

**BLOCKED / DECISION:** current V1.5 has no persisted approved-tenant registry.
The packaged provision command can enforce the constitution and current
approved verticals, but proof of prior human allocation remains an external
`--approval-ref`. ChatGPT must decide whether first H4 supports only the three
approved Philippine IDs or the general frozen grammar/registry.

## 16. Backup / Verify Findings

**SOURCE-PROVEN:** the existing bundle is tenant-scoped. It includes:

- one SQLite-consistent tenant DB snapshot using SQLite online backup
  (`backup_restore.py:167-179,403-406`);
- only TaskHistory-catalogued authoritative assets under internal `output/`,
  never an orphan scan (`backup_restore.py:1-7,407-430`);
- manifest version/application/tenant/counts, byte sizes and SHA-256
  (`backup_restore.py:433-449`);
- path confinement, exact catalog coverage, hashes, and SQLite integrity during
  verify (`backup_restore.py:510-617`);
- temporary staging cleanup on failure and atomic final publish
  (`backup_restore.py:396-454`).

**FROZEN-REQUIREMENT:** the bundle does not include global `dopamatrix.db`,
DPAPI secrets, Delivery copies, orphan output, or future L3 authority. H4 must
not broaden the accepted backup format under the guise of CLI packaging.

**SOURCE-PROVEN GAP:** `create_backup_bundle()` defaults
`project_root="."` and resolves tenant DB and output from that root
(`backup_restore.py:384-410`). The source CLI exposes `--project-root`
(`backup_restore.py:696-717`). A packaged command must remove that user-facing
authority and always pass `RuntimePaths.runtime_root`.

**PROPOSED-FOR-CHATGPT-REVIEW:** the H4 adapter additionally requires an
absolute physically canonical new destination, rejects overwrite, and rejects
a destination inside the runtime root/internal output or configured Delivery
subtree. `backup verify` depends only on the supplied bundle and may run without
opening the runtime DB. Successful create already self-verifies before publish.

**SOURCE-PROVEN:** existing source CLI returns JSON and 0 on success, one stable
error code and 2 for `BackupRestoreError` (`backup_restore.py:720-769`). H4 can
reuse payload content while mapping distinct failure categories to the proposed
taxonomy.

## 17. Packaging / PyInstaller / Tauri Findings

| Finding | Classification | Evidence / consequence |
|---|---|---|
| one-file backend is the sidecar source | SOURCE-PROVEN | `build_backend.py:198-228` |
| static `main.py` imports are analyzed | SOURCE-PROVEN design | explicit future operator imports should be collected; built-artifact proof still required |
| no hidden imports/resources in generated spec | SOURCE-PROVEN | `backend.spec:4-16`; importlib-only command modules are unsafe without build changes |
| Tauri external binary is `bin/backend` | SOURCE-PROVEN | `tauri.conf.json:27-31` |
| Tauri normal launch passes no operator args | SOURCE-PROVEN | `lib.rs:79-95`; remains server mode |
| command CWD need not be authority | SOURCE-PROVEN | RuntimePaths absolute paths; H4 backup must explicitly pass runtime root |
| console output reliability | BLOCKED / NOT-PROVEN | `--windowed` and `console=False` conflict with a terminal CLI contract |
| backup/operator module inclusion | PROPOSED | use explicit static imports after early dispatch; verify in packaged smoke tests |
| `.env` still a Tauri resource | SOURCE-PROVEN deferred H5 | `tauri.conf.json:31`; H4 must not claim production NO-`.env` completion |
| build script mutates dev state | SOURCE-PROVEN pre-existing blocker | `build_backend.py:97-150,185-209`; H4 does not execute/redesign it |

ChatGPT must resolve whether the same binary becomes console-capable or H4
ships a separate console operator binary. If the same binary is retained, H4
tests must prove Tauri can start it without an unwanted visible console while
manual invocation has working stdout, stderr, and exit codes.

## 18. Runbook `.env` -> CLI Mapping

This is a synchronization map only; no runbook was changed. H5 still owns final
NO-`.env` cleanup.

| Current manual/source procedure | Future H4 capability | Evidence label / note |
|---|---|---|
| inspect runtime/profile state through env + HTTP diagnostics | `config status`; `seed status --tenant` | PROPOSED; underlying status services SOURCE-PROVEN |
| create tenant with source venv/get_tenant_engine | `tenant provision` | PROPOSED packaged wrapper |
| set all Seed env keys to 0/0 + kill true | `seed apply-safe-off` | H3 materialization SOURCE-PROVEN |
| generate/load Assignment Secret securely | apply-safe-off creates if absent; `secret assignment status` | H3/H2 SOURCE-PROVEN; command PROPOSED |
| P2 edit Balanced=3000 while kill remains true | `seed prearm-p3w` | transition SOURCE-PROVEN; evidence orchestration PROPOSED |
| restart then disable kill last | `seed activate` followed by controlled restart | FROZEN-REQUIREMENT |
| incident set kill=true, same generation | `seed kill` followed by restart | transition SOURCE-PROVEN |
| reviewed BPS edit, max +/-1000 | `seed set-balanced-bps` while contained | delta is FROZEN, H4 orchestration PROPOSED |
| tighten P3-A thresholds/window while killed | `seed transition-p3a`, restart/evidence, then `seed activate` | transition SOURCE-PROVEN |
| rotate Assignment Secret only after containment/new generation | `secret assignment rotate` | service MISSING; contract PROPOSED |
| `python -m src.api.backup_restore backup` | `backup create` | core SOURCE-PROVEN; packaged root adapter PROPOSED |
| `python -m src.api.backup_restore verify` | `backup verify` | core SOURCE-PROVEN; packaged entry PROPOSED |

Relevant stale source-era text remains in the Execution Pack at lines 88-92,
154-170, 258-327, 376-397, and 441-452, and in the Canary Runbook at lines
210-249 and 303-326. H4 implementation must not edit those until command
behavior is accepted and tested; final production `.env` removal remains H5.

## 19. Required Test Matrix for Future H4 Implementation

No tests were run in H4-R0. Future slices require isolated tests with temporary
RuntimePaths, synthetic secrets/protectors, temporary SQLite, and no network.

| Test family | Required proof |
|---|---|
| bootstrap/import | operator help/usage/commands dispatch before dotenv/FastAPI/router/database; no Uvicorn; normal server path unchanged |
| status purity | fresh status creates no root/DB/table/tenant; absent/invalid/corrupt states; stable human/JSON; no secret-derived output |
| packaged I/O | actual built Windows command has stdout/stderr/exit codes; Tauri normal sidecar launch remains acceptable |
| locking | running server blocks every mutation; concurrent operators serialize/fail; crash releases lock; status/backup policy matches contract |
| tenant | grammar/reserved/case/sidecar/Delivery/backup collisions; success schema/Ledger V2/zero rows; injected partial failure preserved; no HTTP/task traffic |
| SAFE_OFF | complete 32-key canonical snapshot, 0/0, kill true, one tenant, approved Lease, create-if-absent/reuse secret atomicity |
| pre-arm | all backup/Delivery/readiness/breaker gates; P3_W+3000+kill true; same generation/secret; omitted remains OFF after provider load |
| activate | only kill changes; disable-kill-last; stale/evidence failures; old process provider unchanged until restart |
| kill | P3_W/P3_A preserve BPS/generation/family/tenant/Lease/Readiness/secret; idempotent contained result |
| BPS | envelope and delta boundaries; killed-only; same generation; no auto-ramp |
| P3-A | cohort gate, exact active thresholds, 7d/24h rules, kill remains true, separate activate |
| rotation | contained-only, new-generation-only, secure random internal generation, one-transaction rollback faults, no secret output/chaining |
| backup | RuntimePaths source root, tenant validation, online writes, catalog-only assets, destination alias/nesting, existing target, staging cleanup |
| verify | format/path/hash/catalog/count/integrity failures; no runtime DB; no mutation |
| regression | H1 bootstrap/runtime paths; H2 secret/redaction; H3 snapshot/transitions/exact Lease; tenant isolation/Ledger; backup/restore; Reservation/Task; full pytest |

## 20. Recommended Bounded H4 Implementation Slices

These are proposals for ChatGPT to accept, reorder, split, or reject.

### Slice H4-1 — Dispatcher, output, and packaged-console gate

- Goal: replace the placeholder with a bootstrap-safe parser/help shell and
  freeze error/JSON/exit behavior; prove a usable Windows output strategy.
- Allowed production: `main.py`, `src/api/bootstrap.py`, new
  `src/api/operator_cli.py`; packaging files only after console decision.
- Tests/docs: new operator-bootstrap tests and one slice report.
- Non-goals: DB, status, tenant, Seed, secret, backup commands.
- Gate: ChatGPT resolves same-binary vs separate-console-binary and accepts
  exit taxonomy.

### Slice H4-2 — Non-mutating status projections

- Goal: `config status`, `seed status`, Assignment Secret status without fresh
  filesystem/schema/tenant mutation or disclosure.
- Allowed production: operator module plus a narrow read-only status service;
  minimal public helper additions in `policy_profiles.py`/`secret_store.py` if
  needed; no router import.
- Tests: fresh-install purity, invalid snapshot, DPAPI error, tenant-not-found,
  human/JSON redaction.
- Non-goals: any mutation, rotation, HTTP/UI.
- Gate: H4-1 accepted and green.

### Slice H4-3 — Mutation quiescence and state-CAS foundation

- Goal: reviewed cross-process server-active/operator-mutation locking and
  expected-state checks.
- Allowed production: bootstrap/server lifecycle, new narrow lock module,
  operator service; no policy changes.
- Tests: concurrent process/lock/crash/stale-state matrices.
- Non-goals: profile values, tenant creation, backup, secret rotation.
- Gate: ChatGPT freezes the lock primitive and mutation lifecycle.

### Slice H4-4 — Packaged tenant provisioning

- Goal: strict constitution/collision barrier, one-shot initializer, independent
  verification, zero-business-data evidence, partial-review semantics.
- Allowed production: operator handler plus new tenant-provision service;
  `database.py` only if a narrow non-router helper is unavoidable.
- Tests: complete tenant matrix and injected failure; existing tenant/Ledger
  regressions.
- Non-goals: registry/AUTH-001, Login/UI, creative work, tenant switching.
- Gate: H4-3 plus ChatGPT decision on three-ID-only vs general grammar.

### Slice H4-5 — Packaged backup create/verify

- Goal: adapt accepted backup core to RuntimePaths and safe destinations.
- Allowed production: operator handler and `backup_restore.py` adapter/helper;
  no bundle-format change.
- Tests: packaged-root binding, paths/aliases, atomic cleanup, concurrency,
  verify matrix; existing backup/restore regression.
- Non-goals: live restore, global DB/secret backup, Delivery/L3 authority.
- Gate: H4-1; lock policy clarifies backup coexistence.

### Slice H4-6 — SAFE_OFF and named Seed transitions

- Goal: apply-safe-off, pre-arm, activate, kill, BPS edit, and P3-A transition
  with frozen evidence gates and restart output.
- Allowed production: operator/orchestration service and the narrowest H3
  helper extension needed for caller-owned prior-state validation.
- Tests: full Section 19 transition matrix and all H3 regressions.
- Non-goals: rotation, automatic ramp, generic key/stage/generation edit, UI.
- Gate: H4-2/3/5; ChatGPT freezes command names/preconditions.

### Slice H4-7 — Explicit Assignment Secret rotation

- Goal: separate contained/new-generation atomic rotation command.
- Allowed production: operator service plus narrow
  `policy_profiles.py`/`secret_store.py` caller-owned transaction helper.
- Tests: security, atomic faults, concurrency/CAS, restart, no output leakage;
  full H2/H3 regressions.
- Non-goals: ordinary apply rotation, secret import/export/reveal/recovery.
- Gate: H4-6 and independent security review.

### Slice H4-8 — Packaged smoke and documentation synchronization

- Goal: prove actual sidecar inclusion/CLI I/O and update Runbook/Execution Pack
  from source-era steps to accepted commands.
- Allowed files: packaging only as accepted in H4-1, operator tests, the two
  field docs, implementation/acceptance report.
- Tests: built binary commands in clean temporary runtime root, artifact scan,
  normal Tauri launch, no dev DB/output contamination.
- Non-goals: H5 `.env`/Ngrok cleanup or H6 final installer acceptance.
- Gate: all prior H4 slices independently reviewed.

## 21. Risks / Blockers / Decisions Required from ChatGPT

| ID | Decision or risk | Current result |
|---|---|---|
| H4R0-01 | same `backend.exe` console-capable vs separate operator binary | BLOCKED: current windowed build does not prove CLI output |
| H4R0-02 | exact exit taxonomy and JSON schema | PROPOSED, not frozen |
| H4R0-03 | exact Windows cross-process/server-quiescence lock | BLOCKED: no current primitive |
| H4R0-04 | status must be strictly non-mutating on fresh install | RECOMMEND YES; existing status helpers can create DB/table |
| H4R0-05 | provision only three approved Philippine IDs or general frozen grammar/vertical registry | DECISION REQUIRED |
| H4R0-06 | apply-safe-off initial-only vs explicit governed contained rebaseline/switch path | DECISION REQUIRED; no silent tenant replacement |
| H4R0-07 | stale-state/CAS mechanism without changing snapshot schema | DESIGN REVIEW REQUIRED |
| H4R0-08 | backup/Delivery/readiness evidence supplied as paths vs persisted approval records | PROPOSED bundle path + live evidence; no new evidence DB proposed |
| H4R0-09 | general incident generation-rebaseline command | DEFERRED; arbitrary generation edit intentionally absent |
| H4R0-10 | rotation service placement and atomic snapshot contract | MISSING; separate security slice required |
| H4R0-11 | whether packaged operator includes restore-to-staging in H4 | DEFERRED; not required by minimum command tree |
| H4R0-12 | build script destructive release preparation | remains packaging hardening debt; H4 must not execute it in dev worktree |

No frozen-architecture contradiction was found. The gaps are bounded H4
orchestration/packaging decisions, not reasons to reopen H0-H3.

## 22. Files Changed

Only this new report is intended:

```text
doc/investigations/VAR001_PHASE3D2IB2B2RH4R0_PACKAGED_OPERATOR_CLI_SOURCE_CONTRACT_AUDIT.md
```

Production code: 0 changes. Tests: 0. Packaging: 0. Runbooks/Execution Pack:
0. Existing reports: 0. `.codex-local/handoffs.md`: 0. Git index: 0.

Final read-only scope checks:

```text
git diff --check
exit 0; no output

git diff --cached --name-status
exit 0; no output

git status --short
?? doc/investigations/VAR001_PHASE3D2IB2B2RH4R0_PACKAGED_OPERATOR_CLI_SOURCE_CONTRACT_AUDIT.md
```

## 23. Final Classification

Source-proven foundations:

- pre-application-graph operator prefix seam;
- explicit packaged RuntimePaths and immutable RuntimeConfigProvider;
- DPAPI CurrentUser secret store and safe status enum;
- atomic ordinary profile apply with no automatic secret rotation;
- all frozen SAFE_OFF/P3_W/P3_A effective states and containment semantics;
- source-native tenant schema/Ledger initializer;
- tenant-scoped online backup and full verify primitives.

Missing/review-gated capabilities:

- real dispatcher and packaged console-safe output;
- non-mutating status projection;
- quiescence/locking/CAS;
- named transition precondition orchestration;
- strict packaged tenant provision/verification command;
- RuntimePaths-bound packaged backup/verify entry;
- explicit atomic contained new-generation secret rotation.

```text
VAR001_PHASE3D2IB2B2RH4R0_PACKAGED_OPERATOR_CLI_SOURCE_CONTRACT_AUDIT_COMPLETE
VAR001_PHASE3D2IB2B2RH4R0_IMPLEMENTATION_GATE_REVIEW_REQUIRED
```

H4 implementation is not authorized by this report and awaits independent
ChatGPT review. No H4 final-pass claim is made.
