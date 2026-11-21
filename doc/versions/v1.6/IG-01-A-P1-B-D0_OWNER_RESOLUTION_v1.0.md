# IG-01-A-P1-B-D0 — OWNER RESOLUTION v1.0

**Project:** DopaMatrix 1.6-A Seed Reliability  
**Decision Date:** 2026-11-21  
**Owner Disposition:** APPROVE_ALL_RECOMMENDED_WITH_C01_C02  
**Status:** OWNER_APPROVED / DESIGN_FROZEN

**Source:** IG-01-A-P1-B-D0_OWNER_DECISION_PACKET_v0.1

## 1. Formal Approval

The Product Owner formally approves and freezes decisions D0-01 through D0-06, subject to mandatory implementation-readiness conditions C01 and C02.

This approval freezes the bounded P1-B API contract and scope. It does not authorize engineering implementation, test execution, Git operations or runtime integration.

## 2. Frozen Decisions

### D0-01 — API Compatibility

**APPROVED: Option C**

- Preserve `POST /api/v1/assets/import`.
- Requests without `result_format` retain the exact legacy three-field response.
- Explicit `?result_format=p1b-info-v1` selects an independent informational response DTO.
- Preserve original legacy field names, types, requiredness, meanings and default behavior.
- Invalid, empty, unknown or conflicting format selection must receive a controlled HTTP 400 response before Import business mutations or hashing.
- Response-format selection is not Tenant, Actor, Seed Scope or Qualification authority.
- No new endpoint is authorized.
- No modification of existing P1-A contracts or acceptance tests.

### D0-02 — Ordered Per-Input Results

**APPROVED: Ordered In-Memory Observation Ledger**

- Preserve every original input and input_index.
- Do not merge duplicate paths, filenames or MD5 values.
- Distinguish observed branch intent from confirmed persisted results.
- CREATED and REVIVED require confirmed persistence and valid Asset ID.
- Missing Content Version, Source Binding, Proof, Generation and Operation references remain explicitly NOT_ESTABLISHED.
- Do not create a persisted result ledger or new qualification identities.

### D0-03 — Transaction and Failure Semantics

**APPROVED: Preserve Existing Single Commit**

- Preserve current asset mutation, transaction and legacy failure behavior.
- Informational per-input results are promised only for successfully completed requests with sufficient evidence.
- Request-level failure may continue using the existing safe non-2xx response.
- Do not manufacture complete per-input success results after failed or uncertain transactions.
- Commit success, response serialization and HTTP delivery remain separate facts.
- No automatic retry, rollback claims, Recover or idempotency guarantee is introduced.
- The full D2 error-result obligation remains open.

### D0-04 — Intra-Batch Duplicate

**APPROVED: No Transaction Remediation in P1-B**

- Preserve existing MD5 and Asset identity semantics.
- Do not add flush, deduplication, upsert, per-input commit or retry.
- Preserve the distinction between an already persisted Duplicate and an uncommitted same-MD5 input.
- Treat the newly identified batch conflict as a static risk, not a verified runtime defect.
- Any transaction remediation requires a separate Owner-approved work package.

### D0-05 — Qualification and Seed Boundary

**APPROVED: Informational Only**

- Technical Validation remains NOT_EVALUATED without actual validation evidence.
- Qualification Activation remains NOT_QUALIFIED without all required frozen qualification evidence.
- No fabricated PASS, PENDING_ACK, Proof, Generation, Operation or trusted authorization.
- Preserve all Tenant, Membership, Seed Scope, ACK and Task Admission gates.
- No new qualification authority or client bypass is authorized.

### D0-06 — Error, Privacy and Operator Contract

**APPROVED: Conservative Evidence-Based Classification**

- Preserve existing approved reason and operator-action enumerations.
- Do not classify media as damaged based merely on file existence, hashing or registration.
- Use the safe display label `input-<input_index>` for this bounded response.
- Do not expose private paths, credentials, raw exceptions, stack traces or internal consistency facts.
- Preserve P1-A serialization validation and public-output revalidation.
- Do not modify the UI or global error handler.

## 3. Mandatory E0 Conditions

### C01 — FastAPI Response Compatibility

E0 must establish the feasibility of:

1. Exact legacy default-response preservation.
2. Independent opt-in response validation.
3. P1-A revalidation before publication.
4. Correct two-format OpenAPI representation.
5. Controlled HTTP 400 for invalid format selections before business mutation.

Failure to establish these conditions means STOP. No implementation authorization.

### C02 — Post-Commit Asset ID Evidence

E0 must establish whether valid persisted Asset IDs can be obtained after the existing commit without additional SQL, flush, refresh, transaction changes or fabricated identities.

If this cannot be established within the approved candidate scope, STOP.

No implementation authorization.

## 4. Candidate Implementation Boundary

Future implementation candidates only:

- `src/api/routes_assets.py`
- `src/api/schemas.py`
- `tests/test_ig01a_p1b_import_results.py`

These are not currently authorized for modification.

All other source files, existing P1-A tests, UI, Tenant IAM, database models, Native code and frozen documents remain excluded.

## 5. Preserved Gates

G1 Native Custody remains BLOCKED.

COMPAT Runtime and Schema/Restore remain NOT_VERIFIED.

Trusted Authorization Source remains NOT_VERIFIED.

ACK remains FAIL_CLOSED.

PENDING_ACK remains NON_QUALIFIED.

Recover remains UNAVAILABLE.

AUTH-ACK-01B and P5 remain NOT_ENTERED.

Seed Allowlist, DAM Import Certification, Philippines Installation, Production and Release remain on their existing HOLD conditions.

The previously identified 63-character PLAN hash reference discrepancy remains documented and unmodified.

## 6. Authorization Record

```text
D0_OWNER_RESOLUTION = APPROVED
D0_01_TO_D0_06 = FROZEN
C01 = MANDATORY
C02 = MANDATORY

P1B_DESIGN_FREEZE = EFFECTIVE
P1B_E0 = NEXT_CANDIDATE

E0_EXECUTION = NOT_AUTHORIZED
P1B_IMPLEMENTATION = NOT_AUTHORIZED
TEST_EXECUTION = NOT_AUTHORIZED
SQLITE_NATIVE_RUNTIME = NOT_AUTHORIZED
GIT_MUTATION = NOT_AUTHORIZED
BUILD_INSTALL_RELEASE = NOT_AUTHORIZED
```

**END — OWNER RESOLUTION v1.0**

---

## Addendum A — D0-01-C01A Selector Cardinality Clarification

**Decision Date:** 2026-11-21  
**Owner Disposition:** APPROVED  
**Status:** FROZEN CLARIFICATION / ADDITIVE ONLY  
**Evidence Trigger:** IG-01-A-P1-B-E0_CONTROLLED_IMPLEMENTATION_READINESS_REPORT, C01 Selector review

The Product Owner explicitly clarifies D0-01's handling of repeated `result_format` query parameters. This addendum is a narrow, binding clarification; it does not revise or supersede the original D0-01 through D0-06 decisions.

| Occurrences of `result_format` | Observed value(s) | Contractual response |
|---|---|---|
| 0 | Absent | Existing Legacy response and behavior unchanged |
| 1 | Exactly `p1b-info-v1` | Independent informational response DTO |
| 1 | Empty, unknown or malformed | Controlled HTTP 400, `CONTRACT_INVALID` |
| 2 or more | Identical valid, identical invalid, or conflicting values | Controlled HTTP 400, `CONTRACT_INVALID` |

Mandatory boundaries:

- Evaluate cardinality without collapsing repeated query parameters into a single value.
- Reject invalid or repeated selection before Import hashing, asset lookup or business mutation; this is not a claim about pre-dependency execution.
- Do not echo raw selector values, private paths or untrusted exception details.
- Do not silently fall back to Legacy after any explicit but invalid selection.
- Selector selection never establishes Actor, Membership, Tenant authority, Seed Scope, qualification or ACK eligibility.
- Keep the original Legacy DTO, P1-A contracts, one-commit transaction, and all open gates unchanged.
- The E0 conclusion remains `CONDITIONAL_READINESS` as executed; this addendum resolves the identified Owner-level selector ambiguity but does not assert runtime verification or grant I1 implementation authority.

```text
D0_01_C01A = APPROVED / FROZEN
SELECTOR_ZERO_OCCURRENCES = LEGACY
SELECTOR_SINGLE_VALID = INFORMATIONAL
SELECTOR_SINGLE_INVALID = HTTP_400_CONTRACT_INVALID
SELECTOR_MULTIPLE_ANY = HTTP_400_CONTRACT_INVALID
D0_01_TO_D0_06 = UNCHANGED / FROZEN
C01_C02 = MANDATORY
P1B_I1_IMPLEMENTATION = NOT_AUTHORIZED
P1B_I1_TESTS = NOT_AUTHORIZED
DOC1_GIT_STAGE_COMMIT_PUSH = NOT_AUTHORIZED
SEED_PRODUCTION = HOLD
RELEASE = HOLD
```

**END — D0-01-C01A ADDENDUM A**
