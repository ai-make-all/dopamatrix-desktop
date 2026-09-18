# VAR-001 Phase 3D-2I-B-2B-1T-A
# Real Tenant Identity Provisioning Audit

## 1. Executive Result

Current source safely supports the proposed production identity pattern `^[a-z]{2}-[a-z0-9]{3,5}-[0-9]{4}$`. In particular, `ph-elv-0001` and `ph-bty-0001` pass through the current canonicalization unchanged, fit every relevant path segment, and are accepted by tenant rollout and Delivery validation.

Current source has no explicit tenant-create API, CLI, or registry. A tenant SQLite database is lazily created by `src.api.database.get_tenant_engine()`, which initializes the application schema and Fingerprint Ledger V2 before caching the Engine. That function is the narrowest source-native provisioning mechanism and can be invoked directly in a one-shot operator process without creating a creative task.

HTTP diagnostics must not be used as a provisioning probe: their `Depends(get_db)` dependency invokes `get_tenant_engine()` before the read-only handler and can create an unknown tenant database.

No production code change is required for controlled V1.5 provisioning. Human approval is still required for the first two canonical IDs, the villa / water-heating vertical, its canonical ID, and the Tenant Short Code pattern.

Final classification:

`VAR001_PHASE3D2IB2B1T_IDENTITY_READY_WAITING_OPERATOR_APPROVAL`

## 2. Repository Baseline

| Fact | Result |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| HEAD | `5f534b180dd2ae9fa9212e6632a44746669d7e6f` |
| Latest commit | `5f534b1 docs(v1.5): assemble Philippine seed execution pack` |
| Initial status | Only the expected untracked `VAR001_PHASE3D2IB2B1_FIRST_TENANT_P0_PREFLIGHT.md` |

The 1C Policy Freeze, Seed Canary Runbook, Seed Execution Pack, 2A Assembly Report, 2B-1 P0 Preflight, and Backup/Restore Runbook were read in full. Current source and relevant current test contracts were then inspected. No service, database, environment, task, backup, restore, or rollout state was touched.

## 3. Current Tenant Canonicalization

Authoritative implementation: `src/api/database.py::canonical_tenant_id()`.

Exact behavior:

1. A missing, empty, or otherwise falsey input becomes `default`.
2. The function retains each character for which Python `str.isalnum()` is true, plus `_` and `-`.
3. Every other character is deleted rather than rejected. This includes whitespace, `/`, `\`, `.`, `:`, and other punctuation.
4. If deletion leaves an empty string, the result becomes `default`.
5. `os.path.normcase()` is applied. On Windows this folds case to the platform filename identity; on POSIX it does not provide lowercase normalization.
6. The backend imposes no explicit tenant-ID length limit. The current Vue login input has `maxlength=32`, but direct API headers are not constrained by it.

Consequences:

- hyphen and underscore are both source-valid;
- Unicode letters/digits are source-valid because `isalnum()` is broader than ASCII;
- whitespace is not trimmed as a unit; it is deleted wherever it appears;
- traversal punctuation is removed, so an unsafe raw value may collide with a different clean value;
- case behavior is platform-dependent;
- `default` is the missing/empty fallback, not a real production identity;
- a candidate must be checked using `raw == canonical_tenant_id(raw)`, not merely by accepting the transformed result.

Request authority comes from `X-Local-User` through `request_tenant_id()`. `RenderDSLRequest.tenant_id` is only an optional declaration; DSL routes reject it when its canonical value differs from the authoritative header. The frontend stores the login/workspace label in localStorage key `dopamatrix_user` and assigns it to the axios `X-Local-User` default header. The login trims outer whitespace but otherwise accepts a broad 32-character value.

Some WebSocket routing and operator-audit labels use the raw header while tenant database selection uses the canonical value. Production operators must therefore use the exact approved lowercase Canonical Tenant ID everywhere; transformed aliases are unsafe even when they reach the same database.

Source-validation result for `ph-elv-0001`:

| Check | Result |
|---|---|
| Lowercase ASCII | PASS |
| Hyphens retained | PASS |
| No deleted character | PASS |
| Windows case fold changes value | NO |
| Valid Delivery segment | PASS |
| Valid rollout allowlist canonical identity | PASS |
| Filename-safe under current derivation | PASS |

`ph-elv-0001` is source-safe.

## 4. Current Tenant Creation Mechanism

Current-source answers:

| Question | Source truth |
|---|---|
| Explicit tenant-create API | None found |
| Tenant-create CLI | None found |
| Tenant registry | None found |
| Lazy creation | Yes |
| Initializer | `get_tenant_engine(tenant_id)` |
| Application schema initializer | `initialize_application_schema(engine)` |
| Ledger initializer | `ensure_fingerprint_ledger_schema(engine)` |
| Fake task required | No |

`get_tenant_engine()` performs this sequence under an Engine-cache lock:

1. canonicalize the supplied identity;
2. derive `sqlite:///./data/dopamatrix_<canonical>.db`;
3. create a SQLAlchemy Engine and enable tenant foreign keys;
4. run `initialize_application_schema()`, which checks incompatible task identity, creates current ORM tables, applies additive schema evolution, and verifies rollout metadata consistency;
5. run `ensure_fingerprint_ledger_schema()`, creating or validating Ledger V2;
6. cache the Engine only after all initialization succeeds.

The current test contract proves opening a new tenant Engine creates the Ledger schema and that a failed Ledger migration does not poison the Engine cache. A failed initialization disposes the Engine and re-raises. Source does not automatically remove a partially created SQLite file, so failure cleanup must be controlled and evidence-preserving.

Any route using `Depends(get_db)` invokes `request_tenant_id()` and `get_tenant_engine()` before the handler runs. This includes Reservation summary, readiness, and rollout-status GET routes. Therefore changing `X-Local-User` to an unknown value and merely querying diagnostics can create tenant state. The handler is read-only, but dependency initialization is not filesystem-read-only.

The safe 2B-1T-B mechanism is a direct, one-shot invocation of `get_tenant_engine()` from the project/installation root after collision checks and approval. It must not submit a creative task and must not use an HTTP request as the creation trigger.

## 5. Tenant Storage Mapping

| Domain | Tenant mapping | Identity used |
|---|---|---|
| SQLite | `<root>/data/dopamatrix_<canonical-tenant>.db` | Canonical Tenant ID |
| VideoTask / TaskHistory / assets | Tables in the selected tenant SQLite DB; no separate tenant column | Physical tenant Engine |
| Fingerprint Ledger | Ledger V2 tables in the same tenant SQLite DB | Physical tenant Engine |
| Reservation | Reservation rows in the same tenant Ledger; authority owner remains owner-attempt ID + slot | Physical tenant Engine, not short code |
| Reservation diagnostics / breaker | Tenant-local ORM tables in the selected DB | Physical tenant Engine |
| Rollout allowlist | Exact canonical strings; configuration rejects values changed by canonicalization | Canonical Tenant ID |
| Rollout HMAC input | Canonical tenant + policy + task ID + generation | Canonical Tenant ID, never Tenant Code as tenant authority |
| Delivery | `<DELIVERY_ROOT>/tenants/<canonical>/projects/_default/` | Exact canonical tenant segment |
| Exports | Tenant-derived Delivery export directory when configured; tenant-bound filename and lookup | Canonical Tenant ID |
| Backup | CLI canonicalizes `--tenant`; manifest stores canonical identity | Canonical Tenant ID |
| Restore | `data/dopamatrix_<manifest-canonical>.db` under isolated staging | Manifest Canonical Tenant ID |
| Future L3 boundary | Internal authoritative output + TaskHistory, as already documented; Delivery excluded | Tenant-local authority, not short code |

There is no current `tenant_code`, display-name, country-code, or vertical-code field in production source. Business logic does not currently parse those values from tenant identity. V1.5 Tenant Short Code therefore remains documentation/change-control metadata only.

## 6. Proposed Identity Contract Validation

Proposed production regex:

```text
^[a-z]{2}-[a-z0-9]{3,5}-[0-9]{4}$
```

This is a safe strict subset of current source behavior:

- every character is retained by `canonical_tenant_id()`;
- lowercase removes the cross-platform case-fold ambiguity;
- hyphens are explicitly retained;
- 11–13 characters are comfortably within the Vue 32-character UI limit and ordinary filename constraints;
- no path separator, drive marker, dot segment, whitespace, or Windows reserved-device name can be formed;
- Delivery validation accepts the canonical segment;
- rollout configuration accepts the exact canonical value.

Source does not enforce country validity, vertical-registry membership, four-digit range `0001..9999`, immutability, or reserved production names. Those are frozen operator controls for V1.5. The lack of source enforcement does not make the proposed strings unsafe, but it prohibits casual self-service tenant creation.

## 7. Tenant Short-Code Decision

Recommended V1.5 pattern:

```text
<vertical><sequence4>
```

Examples: `elv0001`, `bty0001`.

| Candidate | Compactness | Capacity / migration | Mapping clarity | SEA consideration | Verdict |
|---|---|---|---|---|---|
| `<vertical><sequence2>` | Best | Requires a rule change after 99 | Loses the canonical four-digit form | Country still external | Reject for V1.5 |
| `<vertical><sequence4>` | Still compact | Covers the frozen 0001–9999 range | Direct deterministic mapping | Must be paired with country/canonical ID outside Philippine context | Recommend |

The short code satisfies `^[a-z][a-z0-9-]{2,11}$` but remains non-authoritative. Philippine Generation illustrations become `phseed-elv0001-bal-YYYYMMDD-r1` and `phseed-bty0001-bal-YYYYMMDD-r1`. No real Generation is selected here.

`TENANT_SHORT_CODE_PATTERN_APPROVAL` remains pending.

## 8. Reserved Namespace

The following exact identities are reserved and must not be reused:

- `default`
- `v15_acceptance`
- `v15_delivery_a`
- `v15_delivery_b`

Real production identities must match the production regex and use an approved Vertical Code Registry entry. Root prefixes `test-`, `dev-`, `demo-`, `staging-`, `acceptance-`, and `v15-` are excluded by that grammar. Vertical tokens `test`, `dev`, `demo`, and `v15` are also reserved so that forms such as `ph-test-0001` cannot enter the production registry.

The known local files identify only `default`, `v15_acceptance`, `v15_delivery_a`, and `v15_delivery_b`; they do not prove a mapping to the real Philippine business tenants and must not be repurposed.

## 9. Initial Philippine Tenant Proposal

No tenant is provisioned by this table.

| Business category | Country code | Vertical code | Sequence | Proposed Canonical Tenant ID | Proposed Tenant Code | Status | Reason / unresolved input |
|---|---|---|---|---|---|---|---|
| Elevator | `ph` | `elv` | `0001` | `ph-elv-0001` | `elv0001` | OPERATOR_APPROVAL_REQUIRED | Canonical ID and short-code approval pending |
| Beauty | `ph` | `bty` | `0001` | `ph-bty-0001` | `bty0001` | OPERATOR_APPROVAL_REQUIRED | Canonical ID and short-code approval pending |
| Villa / water-heating | `ph` | `hwh` recommended | `0001` | `ph-hwh-0001` if approved | `hwh0001` if approved | OPERATOR_APPROVAL_REQUIRED | Vertical code unresolved; `hwt` and scope-dependent `hva` remain alternatives |

No real customer company name is attached.

## 10. Collision Prevention

Before 2B-1T-B creates anything, it must prove all of the following in one staffed, operator-reviewed record:

1. the approved raw ID exactly matches the production regex;
2. `canonical_tenant_id(approved_id) == approved_id`;
3. it is not a reserved exact name and uses an approved vertical;
4. no `data/dopamatrix_<approved_id>.db` exists;
5. no tenant DB filename collides after case folding, even on a case-sensitive host;
6. no associated `-wal` or `-shm` sidecar indicates an existing/incomplete tenant;
7. no Delivery subtree for the canonical ID already exists; any existing subtree is a STOP condition until ownership is proven;
8. no approved backup namespace/bundle already claims the canonical ID;
9. the `(country, vertical, sequence)` allocation and Tenant Short Code are absent from prior production records;
10. the backend is drained/stopped for the one-shot initialization so no HTTP request can race lazy creation.

Do not delete, overwrite, rename into place, or reuse an existing tenant to resolve a collision.

## 11. Safe Provisioning Procedure

The exact 2B-1T-B procedure is:

1. **Approval lock** — record approved Canonical Tenant ID, Vertical Code Registry decision, Tenant Short Code, application commit/tag, Tech Lead, and provisioning operator.
2. **Pure validation** — validate the strict production regex, sequence range, reserved namespace, and exact equality with `canonical_tenant_id()`.
3. **Filesystem collision check** — inspect filenames only; prove the DB path and its case-folded equivalent do not exist, and prove no sidecars or failed prior attempt occupy the namespace.
4. **Delivery/backup collision check** — using the already approved Delivery Root and backup parent, prove the derived Delivery subtree and intended backup namespace do not belong to another tenant. Do not create either as part of identity provisioning.
5. **Quiescence** — drain and keep the backend stopped. Do not submit tasks, call diagnostics, enable Canary, or send Reservation traffic.
6. **Creation operation** — from the installation/project root, use the repository virtual environment in a one-shot operator process to call `src.api.database.get_tenant_engine(<approved-canonical-id>)`; dispose the returned Engine before process exit. Do not import/start `main.py` and do not call an HTTP route.
7. **Schema initialization** — rely only on the source-native sequence already inside `get_tenant_engine()`: application schema initialization followed by Fingerprint Ledger V2 initialization. Do not manually create tables and do not insert a VideoTask.
8. **Verification** — reopen through `get_tenant_engine()` in a separate verification process; prove SQLite integrity, required application tables, rollout metadata checks, tenant foreign keys, required Ledger tables, and Ledger schema version 2. Confirm creative/operational tables contain no fabricated tasks, TaskHistory, occurrences, Reservations, diagnostics, or breaker rows. The Ledger schema-version metadata row is expected.
9. **Evidence** — preserve timestamp, commit/tag, exact canonical ID, short code, approvers, collision results, schema/ledger verification result, zero creative-row counts, and the safe relative DB filename. Record no customer content or secret.
10. **Release to later P0 work** — only after verification, mark identity provisioned. Asset loading, Delivery verification, backup, Seed environment application, P1 tasks, and Canary remain later separately approved operations.

Failure rollback:

- If validation or collision checking fails, perform no creation.
- If initialization fails, the source disposes the Engine and does not cache it, but a partial SQLite file may remain.
- Keep the backend stopped, preserve the bounded error evidence, and quarantine only files proven to have been created by this failed attempt (DB and any sidecars) outside the active `dopamatrix_<id>.db` namespace under operator change control.
- Do not overwrite, delete, or rename any pre-existing tenant file.
- Do not retry against the partial active filename. Root cause and quarantine must be reviewed before a fresh controlled attempt.

This procedure creates no fake creative task and emits no Canary or Reservation traffic.

## 12. Whether Code Change Is Required

`NO` for controlled V1.5 provisioning.

The existing `get_tenant_engine()` path is sufficient to create and validate an empty real-tenant schema without creative work. A dedicated tenant registry/API could improve future self-service governance, atomic failed-file cleanup, and typo prevention, but it is not required for this manually approved first-tenant operation and would exceed this phase.

Operational limitation to retain: unknown `X-Local-User` values can lazily create DB files on routes with `get_db`. The constitution therefore requires exact canonical headers and forbids HTTP probing before provisioning. If DopaMatrix later permits untrusted/self-service tenant headers, source enforcement and an explicit registry become mandatory hardening.

## 13. Operator Decisions Still Required

| Decision | Status |
|---|---|
| `ELEVATOR_CANONICAL_ID_APPROVAL` | PENDING |
| `BEAUTY_CANONICAL_ID_APPROVAL` | PENDING |
| `VILLA_WATER_HEATING_VERTICAL_CODE` | PENDING (`hwh` recommended; `hwt` / scope-dependent `hva` alternatives) |
| `VILLA_WATER_HEATING_CANONICAL_ID_APPROVAL` | PENDING |
| `TENANT_SHORT_CODE_PATTERN_APPROVAL` | PENDING (`<vertical><sequence4>` recommended) |

Provisioning must not begin until the relevant tenant's canonical ID, vertical allocation, and short code are approved. First-tenant selection, asset readiness, Delivery Root, backup destination, release tag, named operators, assignment-secret presence, and staffed apply block remain governed by the existing 2B-1 P0 preflight.

## 14. Scope Check

This audit:

- read source and documentation only;
- did not open, query, create, rename, or modify any tenant SQLite database;
- did not change `.env` or process environment;
- did not start/stop/restart the backend;
- did not submit tasks, create backups, restore backups, alter Delivery Root, generate a secret, create a tag, commit, or push;
- did not modify the existing P0 preflight artifact;
- created only the Tenant Identity Constitution and this audit.

No Reservation, rollout, Task Identity, Delivery, backup, Ledger, Historical, or future L3 architecture was changed.

## 15. Git Status

Expected final untracked files:

```text
?? doc/investigations/VAR001_PHASE3D2IB2B1_FIRST_TENANT_P0_PREFLIGHT.md
?? doc/investigations/VAR001_PHASE3D2IB2B1T_TENANT_IDENTITY_PROVISIONING_AUDIT.md
?? doc/operations/DOPAMATRIX_V15_TENANT_IDENTITY_CONSTITUTION.md
```

No commit or push was performed.

## 16. Final Classification

The proposed identity model is source-safe and the existing schema initializer provides a clean no-task provisioning mechanism. Specific real-tenant identities and the short-code decision still require human approval.

`VAR001_PHASE3D2IB2B1T_IDENTITY_READY_WAITING_OPERATOR_APPROVAL`
