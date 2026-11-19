# IG-01-A-PLAN v1.0-R1 — Owner Approval & Design Freeze Record

**Project:** DopaMatrix 1.6-A Seed Reliability  
**Record Date:** 2026-11-19  
**Record Version:** v0.1  
**Status:** FROZEN / OWNER APPROVED / DOCUMENT ONLY

---

## 1. Formal Owner Approval

The Owner formally approves and freezes:

`IG-01-A-PLAN v1.0-R1 — Minimal Asset Identity & Re-import Remediation Plan`

Approval scope:

- Accept the complete R1 document without further modification.
- Accept all eight R1 revision items (R1-01 through R1-08).
- Freeze the logical identity model, qualification semantics, invalidation rules, and implementation boundaries.
- Preserve all existing Frozen Product Contracts and Frozen Design Decisions.
- Preserve every OPEN, BLOCKED, NOT_VERIFIED, NOT_AUTHORIZED and NOT_GRANTED condition.

**Owner Decision: APPROVED.**

**Design Freeze: EFFECTIVE.**

This approval freezes the planning and design boundaries only. It does not authorize engineering implementation or operational deployment.

## 2. Approved Source Document Identity

| Item | Approved value |
|---|---|
| Document | IG-01-A-PLAN_v1.0-R1.md |
| Revision | v1.0-R1 |
| Date | 2026-11-19 |
| File size | 48,759 bytes |
| SHA256 | `A6922A05109FA6C2CB73E7B0E0B6063F9E372B1D3E8A3D064AD38F63D163F86` |
| Review | PASS |
| Content modification required | NO |

The SHA256 above was independently recalculated against the uploaded R1 file and matches the Owner-provided PowerShell evidence.

The approved R1 source document must remain unchanged.

## 3. Frozen Design Decisions

The following eight revision items are formally accepted:

| ID | Frozen decision |
|---|---|
| R1-01 | Separate Asset Identity, Content Version Identity, Source Binding Revision, Qualification Proof, Generation and Operation Identity. |
| R1-02 | Distinguish actual content changes from source-path/object rebinding. |
| R1-03 | Keep Import Outcome, Technical Validation and Qualification Activation as three independent dimensions. |
| R1-04 | Preserve AUTH-ACK-01A Option C. ACK remains blocked; P5 remains NOT ENTERED. |
| R1-05 | Protect Purge-related Proof, Operation, pending ACK, UNKNOWN custody and idempotency tombstones. |
| R1-06 | Keep IG-01-A and IG-02-B responsibilities strictly separated. |
| R1-07 | Freeze the logical Generation and Source Binding Revision event matrix. |
| R1-08 | Preserve unified Seed backend protection for old clients, old APIs and Direct API. |

These decisions are planning and behavioral constraints. They do not constitute physical Schema selection, DDL approval or implementation permission.

## 4. Frozen Scope and Exclusions

### 4.1 IG-01-A responsibilities

- Asset Identity preservation.
- Content Version Identity semantics.
- Source Binding Revision semantics.
- Qualification Proof binding and invalidation rules.
- Import Outcome / Technical Validation / Qualification Activation separation.
- Restore, Revival, Duplicate, Replacement and Purge behavioral requirements.
- Historical asset and output protection.
- Forward compatibility with future Asset Version and Lineage architecture.

### 4.2 Explicitly excluded

- Full DAM lifecycle reconstruction.
- Full multi-version Asset UI.
- Full Historical Creative Memory implementation.
- Historical Task/Output backfill.
- IG-02-B Task Admission implementation.
- Actual-use Freshness implementation.
- Task/Child/Attempt lifecycle modification.
- Batch2 redesign.
- Native Owner or Runner redesign.
- Physical Schema selection or DDL.
- Automatic migration or database evolution.

## 5. Preserved Dependencies and OPEN Gates

The following statuses remain unchanged:

| Gate | Frozen status |
|---|---|
| G1 Native Custody | BLOCKED |
| COMPAT Runtime | NOT_VERIFIED |
| Schema / Restore Barrier | NOT_VERIFIED / NOT_AUTHORIZED |
| External Control Plane | UNKNOWN |
| Trusted Authorization Source | NOT_VERIFIED |
| ACK | FAIL_CLOSED |
| PENDING_ACK | NON_QUALIFIED |
| RECOVER | UNAVAILABLE |
| AUTH-ACK-01B | NOT_ENTERED |
| P5 | BLOCKED / NOT_ENTERED |
| S0-OPS | OPEN / NOT_VERIFIED |
| Seed Allowlist | NOT_VERIFIED |
| Budget Thresholds | NOT_ESTABLISHED |
| DAM Import Certification | HOLD |
| Philippines Installation | HOLD |
| Production | HOLD |

No Gate is considered closed merely because this plan has been frozen.

## 6. Existing Frozen Decisions Remain Authoritative

This record does not amend or supersede:

- AUD-03-D1-D2 v1.0.
- IG-00 OD-01 through OD-04.
- IG-00 DD2-01 through DD2-05.
- AUTH-ACK-01 Option B.
- AUTH-ACK-01A Option C.
- D16-001 through D16-006.
- Approved PRD and Acceptance Matrix.

Where a dependency remains open, its original restrictions continue to apply.

## 7. Engineering Authorization Boundary

The following permissions are explicitly NOT GRANTED:

```text
IG-01-A IMPLEMENTATION = NOT_GRANTED
IG-02-B IMPLEMENTATION = NOT_GRANTED

SOURCE CODE MODIFICATION = NOT_AUTHORIZED
TEST EXECUTION = NOT_AUTHORIZED
SQLITE ACCESS = NOT_AUTHORIZED
DDL / MIGRATION = NOT_AUTHORIZED

NATIVE PROCESS EXECUTION = NOT_AUTHORIZED
REAL CUSTOMER MEDIA ACCESS = NOT_AUTHORIZED
EXTERNAL SERVICE ACCESS = NOT_AUTHORIZED
CREDENTIAL ACCESS = NOT_AUTHORIZED

GIT STAGE / COMMIT / PUSH / TAG = NOT_AUTHORIZED

BUILD / PACKAGE / INSTALL / UPGRADE = NOT_AUTHORIZED
RELEASE = NOT_AUTHORIZED

HANDOFF MUTATION = NOT_AUTHORIZED
PRODUCTION DATA MUTATION = NOT_AUTHORIZED
```

Every subsequent engineering slice requires a separate, explicit Owner authorization identifying its precise scope.

Historical permissions for previous Docs commits and pushes are consumed and do not constitute standing permissions.

## 8. Implementation Planning Status

The R1 implementation slices remain proposals:

- P1 — Identity and Result Contract.
- P2 — Qualification Storage and Readiness.
- P3 — COMPAT and Narrow Validation Adapter.
- P4 — Import/Mutation Unified Integration.
- P5 — Two-Phase Activation: BLOCKED / NOT ENTERED.
- P6 — IG-02-B Independent Integration.

No slice is automatically authorized by this freeze.

Each slice must independently establish its dependencies, source-file allowlist, test scope, acceptance criteria and Owner approval.

## 9. Change Control

1. The approved R1 source document must not be overwritten.
2. Any future changes to the frozen plan require a new revision or formally controlled addendum.
3. Frozen decisions cannot be silently reinterpreted during engineering implementation.
4. Newly discovered evidence must be recorded separately and reviewed against existing frozen decisions.
5. Any implementation that requires changing Frozen Architecture or an approved safety boundary must stop and return to the Owner for a separate decision.

## 10. Final Freeze Declaration

```text
IG-01-A-PLAN_v1.0-R1 = FROZEN

OWNER_APPROVAL = APPROVED
DESIGN_FREEZE = EFFECTIVE

SOURCE_DOCUMENT_INTEGRITY = VERIFIED
CONTENT_REVISION_REQUIRED = NO

FROZEN_REVISION_ITEMS = R1-01 ... R1-08

OPEN_GATES = PRESERVED
ENGINEERING_AUTHORIZATION = NOT_GRANTED
TEST_AUTHORIZATION = NOT_GRANTED
DDL_AUTHORIZATION = NOT_GRANTED
NATIVE_AUTHORIZATION = NOT_GRANTED

GIT_COMMIT = NOT_AUTHORIZED
GIT_PUSH = NOT_AUTHORIZED

DAM_IMPORT_CERTIFICATION = HOLD
PHILIPPINES_INSTALL = HOLD
PRODUCTION = HOLD
```

**Final Owner Decision:**

IG-01-A-PLAN v1.0-R1 is formally approved and frozen.

All unresolved dependencies, safety conditions and engineering authorization boundaries remain effective.

**END OF OWNER APPROVAL & DESIGN FREEZE RECORD**