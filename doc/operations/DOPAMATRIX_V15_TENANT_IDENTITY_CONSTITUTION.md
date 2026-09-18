# DopaMatrix V1.5
# Tenant Identity Constitution

## 1. Purpose

This constitution defines the operator-controlled identity contract for real V1.5 tenants. It narrows the broader behavior currently accepted by the application into one portable, immutable production namespace. It does not create a tenant, add a registry table, authorize a rollout, or change source code.

The rules in this document govern provisioning and all later use of a real tenant. Current source remains the implementation authority; where source accepts more values than this constitution, production operators must apply the narrower constitution.

## 2. Identity Layers

The identity layers are intentionally separate:

| Layer | Purpose | Authority |
|---|---|---|
| Canonical Tenant ID | Tenant SQLite selection, request tenant boundary, Delivery subtree, backup identity, rollout tenant input | Authoritative and immutable |
| Tenant Short Code | Generation names, worksheets, alerts, and human communication | Stable operator alias only |
| Display Name | Customer-facing or operator-facing mutable label | Business metadata only |
| Public Task ID | One server-owned render execution | Not tenant identity |
| Reservation owner-attempt ID | One internal Reservation authority attempt | Not tenant identity |
| Child execution ID | One child execution | Not tenant identity |
| Rollout Generation | One governed rollout epoch | Not tenant identity |

For supported V1.5 requests, `X-Local-User` must contain the exact Canonical Tenant ID. Tenant Short Code, display name, business name, task ID, attempt ID, execution ID, and Generation must never be substituted into that header.

## 3. Canonical Tenant ID

The V1.5 production format is:

```text
<country>-<vertical>-<sequence4>
```

The exact policy regex is:

```text
^[a-z]{2}-[a-z0-9]{3,5}-[0-9]{4}$
```

Additional rules:

- ASCII lowercase only;
- length is therefore 11 through 13 characters;
- country, vertical, and sequence are separated by literal hyphens;
- underscore is not permitted by the production constitution even though current source accepts it;
- the submitted raw identity must already equal its canonical form;
- no whitespace, slash, backslash, dot, colon, Unicode letter/digit, or other punctuation is permitted;
- an identity must never rely on source canonicalization to remove or change characters;
- `0000` is forbidden; the sequence range is `0001` through `9999`.

`ph-elv-0001` and `ph-bty-0001` are unchanged by current source and are source-safe. This constitution is deliberately narrower than `canonical_tenant_id()`, which currently retains any `str.isalnum()` character plus `_` and `-`, drops other characters, applies platform `normcase`, and has no explicit backend length limit.

## 4. Country Code

The country segment is the ISO 3166-1 alpha-2 code stored as lowercase ASCII. Philippine tenants use `ph`.

Country is business metadata embedded in the V1.5 slug for operator clarity. Application business logic must not infer current country policy solely by parsing the slug.

## 5. Vertical Code Registry

Vertical codes form a controlled operator registry:

- lowercase ASCII;
- 3 through 5 alphanumeric characters;
- semantic classification only;
- stable after first production use;
- never authorization, database authority, billing authority, or Reservation authority;
- never reassigned to a different meaning after production use.

Initial registry proposal:

| Business category | Vertical code | Status | Note |
|---|---|---|---|
| Elevator | `elv` | Proposed for approval | Clear, compact category code |
| Beauty | `bty` | Proposed for approval | Clear, compact category code |
| Villa / water-heating | `hwh` | Recommended, approval required | “home water heating”; closest to the stated category without claiming HVAC scope |

Alternatives for villa / water-heating are `hwt` (“home / water heating”) and `hva` (only if the approved business scope truly includes HVAC / heating / ventilation). `hwh` is the technical recommendation, but the final choice remains `OPERATOR_APPROVAL_REQUIRED`.

## 6. Sequence Allocation

Sequence numbers are allocated independently within `(country, vertical)`:

```text
ph-elv-0001
ph-elv-0002
ph-bty-0001
th-elv-0001
```

Rules:

- allocate the next unused value in `0001..9999`;
- preserve the approved allocation in the provisioning/change-control record;
- never reuse a sequence retired from production;
- never renumber an existing tenant to close a gap;
- a business-name or classification change does not cause resequencing.

V1.5 has no database-backed tenant registry, so the approved operator allocation record is the registry of allocations. Collision checks against current tenant DB filenames, Delivery namespaces, backup namespaces, and prior records are mandatory before provisioning.

## 7. Tenant Short Code

Tenant Short Code is a stable non-authoritative operator alias. The accepted value domain is:

```text
^[a-z][a-z0-9-]{2,11}$
```

The recommended V1.5 pattern is:

```text
<vertical><sequence4>
```

Examples:

```text
elv0001
bty0001
```

The two-digit alternative (`elv01`) is shorter but creates a policy migration at sequence 100 and loses direct alignment with the four-digit canonical allocation. The four-digit pattern remains compact, deterministic, readable, and avoids that migration.

Tenant Short Code is not globally authoritative across countries. In Southeast Asia-wide dashboards or records it must be paired with the Canonical Tenant ID or country context. A future `th-elv-0001` may also use local alias `elv0001`; that is acceptable only because the alias is never a lookup authority.

Operator approval of this short-code pattern is required before first provisioning.

## 8. Generation Mapping

The frozen Philippine Seed format remains:

```text
phseed-<tenantcode>-bal-YYYYMMDD-rN
```

Format illustrations only:

```text
phseed-elv0001-bal-YYYYMMDD-r1
phseed-bty0001-bal-YYYYMMDD-r1
```

No real Generation is created by this constitution. A Generation is chosen only after tenant approval, short-code approval, execution date, revision, and Tech Lead approval.

```text
Canonical Tenant ID != Tenant Short Code != Rollout Generation
```

The Canonical Tenant ID remains a separate input to rollout assignment. Tenant Short Code appears only inside the human-governed Generation naming convention.

## 9. Reserved Names

Real production tenants must never use these existing local/test identities:

- `default`
- `v15_acceptance`
- `v15_delivery_a`
- `v15_delivery_b`

`default` is the missing/empty-header fallback and is permanently reserved for compatibility/development behavior.

The production regex already excludes root prefixes such as `test-`, `dev-`, `demo-`, `staging-`, `acceptance-`, and `v15-`. To prevent semantic misuse inside an otherwise valid slug, the Vertical Code Registry also reserves non-production tokens `test`, `dev`, `demo`, and `v15`. Longer `staging` and `acceptance` tokens are outside the 3–5 character domain.

No production identity may be approved merely because current source can sanitize it into a valid filename. Raw input must match the approved canonical value exactly.

## 10. Immutability Rules

After first production provisioning:

| Identity | Rule |
|---|---|
| Canonical Tenant ID | Immutable |
| Tenant Short Code | Stable operator alias; change only through an exceptional migration plan, never as DB authority |
| Display Name | Mutable |
| Country / vertical classification | Business metadata; may evolve without renaming the canonical tenant |

Do not rename the Canonical Tenant ID because customer branding changes, a business name changes, the vertical broadens, or a display label changes. A rename would change the SQLite filename, Delivery subtree, backup identity, rollout allowlist/HMAC input, and operational evidence boundary.

## 11. Authority Boundaries

Canonical Tenant ID is used for:

- tenant database Engine selection;
- `data/dopamatrix_<canonical-tenant>.db` physical filename;
- per-tenant TaskHistory, VideoTask, diagnostics, breaker, Fingerprint Ledger, and Reservation storage through that Engine;
- rollout allowlist membership and deterministic assignment input;
- Delivery `tenants/<canonical-tenant>/` subtree;
- tenant-aware export lookup;
- backup manifest tenant identity and restore filename.

TaskHistory and Reservation tables do not carry a separate tenant column; their tenant boundary is the selected physical tenant database. Reservation ownership remains owner-attempt identity plus slot, not Canonical Tenant ID or Tenant Short Code.

Tenant Short Code must not be used for tenant database selection, authorization, Reservation authority, TaskHistory authority, billing, secret derivation, or request routing.

Current WebSocket and some operator-label paths retain the raw `X-Local-User` value, while database selection canonicalizes it. Therefore real operators must always send the exact lowercase Canonical Tenant ID; aliases and values that depend on transformation are prohibited.

## 12. Delivery / Backup Mapping

For proposed tenant `ph-elv-0001`, the source-derived mappings are:

```text
Tenant SQLite:
<project-or-installation-root>/data/dopamatrix_ph-elv-0001.db

Delivery project root:
<DELIVERY_ROOT>/tenants/ph-elv-0001/projects/_default/

Render delivery:
<DELIVERY_ROOT>/tenants/ph-elv-0001/projects/_default/renders/<YYYY-MM-DD>/<task_id>/

Export delivery:
<DELIVERY_ROOT>/tenants/ph-elv-0001/projects/_default/exports/
```

Backup receives the Canonical Tenant ID, never the short code:

```powershell
.\venv_build\Scripts\python.exe -m src.api.backup_restore backup `
  --tenant ph-elv-0001 `
  --destination <new-backup-directory>
```

Delivery is non-authoritative. TaskHistory and internal `output/` remain authoritative, and backup continues to follow TaskHistory catalog truth.

## 13. Southeast Asia Expansion

The canonical grammar naturally supports other ISO country codes while allocating sequences independently by `(country, vertical)`, for example `th-elv-0001`.

Expansion rules:

- approve country and vertical registry entries before allocation;
- keep canonical identities lowercase and immutable;
- do not assume a Tenant Short Code is globally unique;
- use Canonical Tenant ID in machine authority and cross-country records;
- do not infer current country, market, language, billing, or policy behavior solely from slug parsing.

## 14. V1.5 vs Future 2.0

V1.5 intentionally has no tenant registry table and no separate persisted display-name or business-metadata model. The slug carries country/vertical/sequence for controlled operator readability, not as a general metadata API.

A future 2.0 model may explicitly separate:

```text
tenant_internal_id
canonical_tenant_slug
tenant_code
country_code
vertical_code
display_name
```

That future model must preserve the V1.5 Canonical Tenant ID as an immutable migration key. No 2.0 schema or API is implemented or authorized here.

## 15. Initial Philippine Proposal

This is a proposal only; no tenant has been provisioned.

| Business category | Country code | Vertical code | Sequence | Proposed Canonical Tenant ID | Proposed Tenant Code | Status | Reason / unresolved input |
|---|---|---|---|---|---|---|---|
| Elevator | `ph` | `elv` | `0001` | `ph-elv-0001` | `elv0001` | OPERATOR_APPROVAL_REQUIRED | Canonical ID and short-code pattern require approval |
| Beauty | `ph` | `bty` | `0001` | `ph-bty-0001` | `bty0001` | OPERATOR_APPROVAL_REQUIRED | Canonical ID and short-code pattern require approval |
| Villa / water-heating | `ph` | `hwh` recommended | `0001` | `ph-hwh-0001` if approved | `hwh0001` if approved | OPERATOR_APPROVAL_REQUIRED | Vertical code remains unresolved; alternatives are `hwt` and scope-dependent `hva` |

Real customer company names are deliberately excluded.
