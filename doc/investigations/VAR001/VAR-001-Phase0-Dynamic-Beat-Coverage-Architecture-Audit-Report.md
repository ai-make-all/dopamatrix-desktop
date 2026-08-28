# VAR-001
# Phase 0
# Dynamic Beat Coverage Architecture Audit Report

## 1. Baseline

| Check | Result |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| HEAD | `6618f61d21fffc3abf6f3f324c21d842ec8355a7` |
| Worktree | CLEAN |
| FP-001B | HEAD contains `feat(fp-001): add runtime fingerprint observability` |

Recent history:

```text
6618f61 feat(fp-001): add runtime fingerprint observability
0b6bb27 docs(fp-001): record runtime fingerprint observability acceptance
35d63cd feat(fp-001): add versioned planning fingerprint contract
d2119d7 docs(fp-001): record fingerprint contract hardening review
885cc54 docs(fp-001): record fingerprint contract audit
93359b6 Merge brand unification into integration base
5a5639c inv-001-final-closed
9d589c4 docs(inv-001): record phase 4 review
```

No files were modified during this audit.

## 2. Current Planner Architecture

### Current terminology

| Term | Current implementation correspondence |
|---|---|
| Beat | One ordered `DSLBeatNode` in `StoryDSLPayload.timeline`, later one `BeatCompilationResult` in `CompilationPlan.beats`. |
| Axis | VAR concept corresponding to one ordered `candidate_pools[beat_index]`. This is distinct from the existing media `axis_type` values `X_BASE`, `X_STRUCTURE`, and `Y_LAYER`. |
| Candidate pool | `List[MainVisualCandidate]` for one Beat. |
| Main-X candidate | Frozen `MainVisualCandidate(asset_id, file_hash)` whose asset type belongs to `X_BASE` or `X_STRUCTURE`, with a non-empty normalized hash. |
| Fixed Beat | No current named type; derivable when `len(pool) == 1`. |
| Variable Beat | No current named type; derivable when `len(pool) >= 2`. |
| Candidate combination | Tuple returned by `itertools.product(*candidate_pools)`, containing one candidate per ordered Beat. |
| Accepted plan | Valid preview or materialized `CompilationPlan` appended to `accepted_plans` after fingerprint validation and uniqueness checks. |
| Fingerprint | `_MainVisualFingerprint`: ordered tuple of `(beat_index, beat_identity, 0, normalized_file_hash)`. |
| Preview seed | Request-time `resolved_plan`, remapped to current pools by `_preview_selection()` and accepted first when valid. |
| Coverage count | No current planner structure. It can be derived from accepted fingerprints, but no per-axis counter currently exists. |
| Search budget | Maximum number of unique selection keys admitted into `examined_keys`; production value is 4096. |

### Source map

| File / symbol | Role | Input | Output | Caller |
|---|---|---|---|---|
| [WorkspaceView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:310) `draftBlueprint()` / `blindFission()` | AI Draft request construction | UI tracks and draft result | `submit-dsl` payload with policy | User UI |
| [schemas.py](E:/dopaworkspace/dopamatrix-desktop/src/api/schemas.py:358) `RenderDSLRequest` | Policy/API validation | JSON payload | Validated request | `submit_dsl()` |
| [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:138) `_requests_exact_main_visual()` | Exact-policy predicate | Request | Boolean | Route guard/submission |
| [dsl_parser.py](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:122) `discover_main_visual_candidates()` | Dynamic per-Beat discovery | DSL timeline | Ordered pools | Exact planner |
| [dsl_parser.py](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:75) `MainVisualCandidate` | Lightweight selection reference | Asset ID/hash | Frozen candidate | Pools/product |
| [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:489) `_preview_selection()` | Validate/remap preview | Preview, DSL, pools | Candidate tuple or `None` | Exact planner |
| [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:483) `_selection_key()` | Selection identity | Candidate tuple | Tuple of `(asset_id, file_hash)` | Preview/product dedup |
| [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:530) `_plan_exact_main_visual_variants()` | Enumeration, validation, acceptance | Parser, DSL, count, preview | `_VariantPlanningResult` | DB planner wrapper |
| [dsl_parser.py](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:154) `materialize_with_main_selections()` | Authoritative plan materialization | DSL + explicit candidates | `CompilationPlan` | Exact planner |
| [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:224) `_exact_main_visual_fingerprint()` | Hard INV identity validation | Plan | `_MainVisualFingerprint` | Planner/coordinator/worker |
| [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1294) `render_batch_worker()` | Policy branch and authoritative handoff | DSL, preview, policy | Child work/results | Background task |
| [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:761) `render_worker()` | Render accepted authoritative plan | Plan/fingerprint/identity | Child result | Coordinator |

Current planner core:

```python
candidate_space_size = (
    prod(len(pool) for pool in candidate_pools)
    if candidate_pools and all(candidate_pools)
    else 0
)

if preview_selections is not None and candidate_space_size:
    ...
    accepted_plans.append(preview_plan)
    accepted_fingerprints.append(preview_fingerprint)
    used_fingerprints.add(preview_fingerprint)

for combination in product(*candidate_pools):
    combination_key = _selection_key(combination)
    if combination_key in examined_keys:
        continue
    if len(examined_keys) >= search_budget:
        break
    examined_keys.add(combination_key)
    materialized = parser.materialize_with_main_selections(...)
    fingerprint = _exact_main_visual_fingerprint(materialized)
    ...
    if fingerprint in used_fingerprints:
        continue
    accepted_plans.append(materialized)
    accepted_fingerprints.append(fingerprint)
    used_fingerprints.add(fingerprint)
    if len(accepted_plans) >= requested_count:
        break
```

## 3. Policy Ownership

Current flow:

```text
AI Draft
→ WorkspaceView sets exact_main_visual
→ DslOrchestratorDrawer returns that policy
→ WorkspaceView submit-dsl payload
→ RenderDSLRequest Literal validation
→ submit_dsl background-task kwargs
→ render_batch_worker exact branch
→ _plan_exact_main_visual_variants_from_db
```

Evidence:

- AI Draft sets `EXACT_MAIN_VISUAL_PLANNING_POLICY` after blueprint creation at [WorkspaceView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:339).
- Generic submission defaults to `legacy` at [WorkspaceView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:381).
- API default is `legacy`; allowed values are currently only `legacy` and `exact_main_visual` at [schemas.py](E:/dopaworkspace/dopamatrix-desktop/src/api/schemas.py:402).
- `submit_dsl()` forwards the explicit value without mode inference at [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1819).
- The coordinator owns the policy branch at [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1323).

Balanced Coverage should be a new `variant_planning_policy`, not a silent rewrite of `exact_main_visual`. The natural ownership remains the coordinator/planner layer.

## 4. Dynamic Beat Contract

Production evidence:

- Discovery loops over `payload.timeline`.
- Materialization enumerates `payload.timeline`.
- `CompilationPlan.beats` is built from that same loop.
- Candidate pool count is validated against dynamic timeline length.
- `product(*candidate_pools)` accepts any number of pools.
- Fingerprinting loops over `plan.beats`.
- Timeline compilation uses `len(plan.beats)` and enumerates it at [dsl_adapter.py](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_adapter.py:70).

Hard-code classification:

| Occurrence | Classification |
|---|---|
| Content UI template: Hook/Context/Build/Reveal/CTA | A — UI/template definition only |
| UA UI template: Problem/Failure/Near Win/Reward | A — UI/template definition only |
| Director prompt examples and first-Beat `hook:` constraint | A — generation prompt/template only |
| INV/FP test fixtures using named 3/5 Beats | B — test fixture only |
| Exact planner fixed Beat names/count | None |
| DSL resolver fixed Beat names/count | None |

The built-in UI exposes five content tracks and four UA tracks, but the backend planner does not encode either count.

**DYNAMIC_BEAT_PLANNER: PROVEN**

## 5. Beat Ordering

Order is preserved end to end:

```text
dslTracks array order
→ submitted timeline list order
→ discover_main_visual_candidates loop order
→ candidate_pools outer-list order
→ _compile_plan enumerate(payload.timeline)
→ CompilationPlan.beats order
→ itertools.product argument order
→ fingerprint beat_index order
```

No production sort reorders Beats.

- Candidate sorting only reorders candidates inside a Beat pool.
- Preview validation zips preview Beats, DSL nodes, and pools by index.
- Materialization uses `selections[beat_index]`.
- Accepted plans retain their own original Beat order.

Beat index is therefore stable through planning. Filtering inactive tracks in the frontend can remove Beats before submission, but it does not reorder those that remain.

## 6. Candidate Discovery

`MainVisualCandidate` contains only:

```python
@dataclass(frozen=True)
class MainVisualCandidate:
    asset_id: int
    file_hash: str
```

Planning-time metadata:

| Field | In candidate | Available elsewhere |
|---|---:|---|
| `asset_id` | Yes | — |
| normalized `file_hash` | Yes | — |
| `file_path` | No | Only after materialization |
| `asset_type` | No | Used before candidate creation |
| `usage_count` | No | Used by resolver ordering |
| exhaustion state | No | Used by resolver eligibility |
| resolver score | No | Not exposed |
| tags/matched tags | No | Resolver only |
| Beat identity | No | Parallel DSL node by index |
| Beat role | No | Parallel DSL node by index |
| pool ordinal | Implicit | List position only |

Eligibility includes:

- X-axis registry type.
- Current locked/smart addressing rules.
- Required tags and hard-tag veto where applicable.
- deleted/exhausted rules appropriate to the resolver path.
- non-empty normalized file hash.
- first candidate per normalized hash.

Candidate pools therefore represent resolver-eligible source identities, but strip quality metadata after discovery.

## 7. Candidate Ordering

### Locked path

- Assets are fetched without a complete SQL ordering.
- They are then sorted according to `node.asset_hashes` order.
- Explicit locked X candidates retain that order.
- Semantic fallback is ranked through `_score_candidates()`.

### Smart tagged path

- Initial DB query orders by `usage_count ASC`, but ties have no explicit DB tie-break.
- It caps database rows at 200.
- Python tag filtering stops after the requested limit, normally 20.
- `_score_candidates()` sorts by:

```text
-soft_match_count
is_exhausted penalty
usage_count
random.random()
```

### Smart fallback

- SQL uses `ORDER BY random()`.
- Exact discovery requests all fallback candidates, preserving that random order.

### Preview

Request-time preview resolution may additionally use:

- `random.choice()` for multiple locked X candidates.
- Random score tie-breaking for smart candidates.
- SQL random fallback ordering.

### Other influences

- `asset_id` and `file_hash` are not general ordering tie-breakers.
- `_selection_key` detects already examined full selections; it does not rank candidates.
- Python list order is preserved.
- Dict order does not control candidate order.

Conclusion: candidate ordering is **not deterministic for a fixed database state**. Nondeterministic sources are SQL `random()`, `random.random()`, preview `random.choice()`, and unspecified DB ordering among equal `usage_count` values.

## 8. Enumeration Algorithm

Current implementation uses the lazy iterator returned by:

```python
from itertools import product

for combination in product(*candidate_pools):
    ...
```

It does not precompute the Cartesian list.

For:

```text
A = [A1, A2]
B = [B1, B2]
C = [C1, C2]
```

actual enumeration is:

```text
A1 B1 C1
A1 B1 C2
A1 B2 C1
A1 B2 C2
A2 B1 C1
A2 B1 C2
A2 B2 C1
A2 B2 C2
```

The rightmost Beat changes fastest; the leftmost changes slowest.

## 9. Axis Imbalance Root Cause

A batch of four can legally become:

```text
A1 B1 C1
A1 B1 C2
A1 B2 C1
A1 B2 C2
```

because:

1. Product order is lexicographic.
2. The planner stops immediately after four accepted plans.
3. `used_fingerprints` rejects only duplicate full combinations.
4. There are no per-Beat usage counters.
5. There is no coverage score or fairness objective.
6. Resolver order determines which candidate is `A1`.
7. Preview may consume one accepted slot while the remaining plans still come from the beginning of the product.

For an early axis, let `S` be the product of all suffix pool sizes. Candidate `A2` is not reached until `S` combinations have been traversed. If `S >= 4096`, the current search window may never reach `A2`.

Therefore Hook-same-×4 can be fully INV-correct. It is an optimization gap, not an INV regression.

## 10. Preview Seed

Current preview behavior:

- `submit_dsl()` resolves one request-time plan.
- That plan is passed as `resolved_plan`.
- The exact coordinator passes it as `preview_plan`.
- `_preview_selection()` requires matching Beat count, Beat identity, asset ID, normalized hash, and current pool membership.
- A valid preview is appended before product enumeration.
- Its selection key enters `examined_keys`.
- Its fingerprint enters `used_fingerprints`.
- Child identities are later zipped to accepted plans in accepted order.

Current product semantics are therefore:

**A — valid preview becomes child 0 exactly.**

The preview’s components do not directly alter later pool ordering or pin individual axes. They only:

- consume one accepted slot;
- consume one examined full selection key;
- consume one full fingerprint.

If preview Hook is H1, the planner has no explicit rule favoring H1 afterward. H1 repetition occurs when early product combinations also contain H1, commonly because of pool order and lexicographic traversal.

## 11. Resolver Ranking

| Signal | Classification |
|---|---|
| Deleted filter | HARD ELIGIBILITY |
| Smart exhausted filter | HARD ELIGIBILITY |
| X-axis asset type | HARD ELIGIBILITY |
| Required hard tags | HARD ELIGIBILITY |
| At least one smart semantic-tag match | HARD ELIGIBILITY |
| Stable non-empty file hash | HARD ELIGIBILITY for exact planning |
| Soft match count | SOFT QUALITY/RANKING |
| Usage count | SOFT QUALITY/RANKING |
| Random tie-break | SOFT RANKING/DIVERSITY |
| Locked DSL hash order | Explicit user/request preference |
| `video_role` | Not used by DSL exact resolver |

A new balanced policy may select a lower-ranked—but still eligible—candidate to improve coverage. Phase 1 should retain current pool/enumeration ordinal as a late tie-break so resolver preference is not discarded unnecessarily.

No numeric resolver score survives in `MainVisualCandidate`; only pool position acts as a ranking proxy.

## 12. Fixed vs Variable Beats

- `P=0`: candidate space becomes zero; no plan is accepted.
- `P=1`: the Beat is fixed by capacity.
- `P>=2`: the Beat is variable and eligible for balancing.

For `Build=[24]` and batch 4:

```text
Build distribution = {24: 4}
```

This is `FIXED_BY_CAPACITY`, not imbalance.

Future diagnostics should report for each Beat:

```text
pool_size
selected histogram
classification:
  FIXED_BY_CAPACITY when pool_size == 1
  VARIABLE_BALANCED / VARIABLE_IMBALANCED when pool_size > 1
```

VariantFingerprint events alone cannot prove `FIXED_BY_CAPACITY` because they do not contain pool sizes.

## 13. Coverage Mathematics

For pool size `P > 0` and accepted batch size `B`:

```text
q = floor(B / P)
r = B mod P
```

Ideal distribution:

- `r` candidates receive `q + 1`.
- `P - r` candidates receive `q`.
- Maximum count minus minimum count is at most 1.

Examples:

| P | B | Ideal |
|---:|---:|---|
| 4 | 4 | `1,1,1,1` |
| 4 | 6 | `2,2,1,1` |
| 2 | 4 | `2,2` |
| 1 | 4 | `4` — fixed |

When `B < P`, unused candidates count as zero, producing `1/0` counts with a maximum difference of 1.

## 14. Multi-Axis Balancing

For `2×2`, batch 4, all combinations produce perfect balance:

```text
A1 B1
A1 B2
A2 B1
A2 B2
```

For `4×2`, batch 4, a balanced set is:

```text
A1 B1
A2 B2
A3 B1
A4 B2
```

Competing objectives are:

1. Preserve hard resolver eligibility.
2. Preserve exact full-fingerprint uniqueness.
3. Maximize distinct candidate use on every variable Beat.
4. Minimize per-axis count spread.
5. Avoid letting a large pool dominate smaller pools.
6. Respect preview child 0.
7. Preserve resolver preference as a tie-break.
8. Respect the 4096 search bound.

Phase 1 V1 should treat dynamic Beats equally. It should not assume Hook is primary.

## 15. Diversity Role / Schema Audit

Current structures contain:

- `beat`: arbitrary string.
- `role`: arbitrary required string.
- Built-in roles such as `hook`, `body`, and `cta`.
- `video_role` on `LocalAsset`, unused by this planner.
- No diversity weight, priority, primary-axis, or coverage-role field.

`role` suitability for coverage weighting: **PARTIAL**.

Reasons:

- It is semantically descriptive.
- It is not enum-validated.
- It is not unique: Context, Build, and Reveal all use `body`.
- Imported/custom tracks can provide arbitrary roles.
- It does not express relative diversity importance.

**NO_CURRENT_DIVERSITY_ROLE_SCHEMA**

Phase 1 does not require a new field. Equal weighting by ordered Beat index is sufficient for useful balancing.

If later required, a durable `coverage_weight` or `diversity_role` belongs on `DSLBeatNode` and corresponding template/import UI—not only in an opaque planner config. That is future design work.

## 16. Search Budget

Production bound:

```python
_EXACT_MAIN_VISUAL_SEARCH_BUDGET = 4096
```

Current budget counts unique full selection keys added to `examined_keys`.

- Valid preview: counts as one examined key.
- Each non-preview examined key is materialized once.
- Invalid materialization still consumes budget.
- Duplicate fingerprint still consumes budget.
- Product keys skipped because already examined do not consume additional budget.
- Candidate discovery DB queries are not counted.
- Preview request-time materialization is not performed inside this planner loop.

Consequently, on the non-preview path, one examined key normally means one full plan materialization and one fingerprint attempt.

For a huge lexicographic space, leading-axis candidates can lie entirely beyond the first 4096 keys.

## 17. Capacity vs Search Limit

Current distinction:

```text
accepted >= requested
→ REQUEST_SATISFIED

accepted < requested
and examined_keys >= candidate_space_size
→ TRUE_SPACE_EXHAUSTED
→ INSUFFICIENT_UNIQUE_CAPACITY

otherwise
→ PLANNING_SEARCH_LIMIT_REACHED
```

`candidate_space_size` is the exact product of discovered, hash-deduplicated pool lengths. It is a **pre-materialization selection-space size**, not a proven count of valid accepted fingerprints.

All combinations are not guaranteed materializable: production explicitly handles `MainVisualSelectionMismatch`, invalid plans, and duplicate fingerprints.

A future algorithm must preserve:

- all selection keys exhausted → capacity warning;
- bounded subset/window exhausted while unexamined keys remain → search-limit warning.

It must not report balanced-window exhaustion as true global capacity exhaustion.

## 18. Materialization Cost

Each examined combination currently:

1. Calls `materialize_with_main_selections()`.
2. Re-runs `_compile_plan()` over every Beat.
3. Re-runs locked/smart resolver queries.
4. Resolves main and Y layers.
5. Allocates Pydantic `ResolvedLayer`, `BeatCompilationResult`, and `CompilationPlan` objects.
6. Computes and validates the exact fingerprint.
7. Compares selected and materialized hashes.

This is substantially more expensive than scoring `MainVisualCandidate` tuples.

Coverage scores can be computed from:

```text
beat_index
pool size
candidate asset_id
candidate normalized hash
current accepted histograms
preview selection
```

Full materialization remains mandatory before acceptance because only the authoritative plan plus `_exact_main_visual_fingerprint()` proves the INV contract.

## 19. Exact Fingerprint Invariant

Current hard acceptance rule is:

```python
if fingerprint in used_fingerprints:
    continue
```

Then and only then:

```python
accepted_plans.append(materialized)
accepted_fingerprints.append(fingerprint)
used_fingerprints.add(fingerprint)
```

Balanced Coverage must never replace or weaken this check.

Safe layering:

```text
resolver eligibility
→ coverage-aware proposal ordering
→ authoritative materialization
→ _exact_main_visual_fingerprint validation
→ used_fingerprints hard uniqueness gate
→ accepted-plan coverage counters update
```

The optimization may choose which candidate to try next, but only a validated unique fingerprint may affect accepted coverage.

## 20. Algorithm Options

| Criterion | A Reordered Cartesian | B Round-Robin | C Bounded Enumeration + Greedy | D Beam / Priority Queue |
|---|---|---|---|---|
| Correctness safety | High if hard gate retained | Medium; needs collision/fallback handling | High | Medium-high |
| Coverage quality | Medium; moves rather than removes axis bias | Good on simple pools | High | Potentially high |
| Dynamic Beats | Yes | Yes | Yes | Yes |
| Unequal pools | Weak/medium | Medium; cycle periods can align badly | High | High |
| Preview compatibility | Manageable | More special cases | Natural: seed counters first | Natural but complex |
| 4096 compatibility | High | High | High with bounded window | Harder |
| True exhaustion | Easy if full enumeration remains | Difficult without fallback | Preservable | Difficult |
| Determinism | Depends on pool order | Deterministic with fixed offsets | Deterministic on fixed pools | Sensitive to scoring/frontier |
| Complexity | Low | Low-medium | Medium | High |
| Historical novelty extension | Limited | Limited | Natural extra score/filter | Natural |
| Debuggability | High | Medium | High | Low-medium |
| Main risk | Bias shifts to another axis | Repeats/subset due modular cycles | Score/window design | Over-engineering |

Rejected conclusions:

- A alone cannot guarantee balanced coverage.
- B alone cannot reliably prove exhaustion or cover unequal products without a second fallback algorithm.
- D is unnecessary for batch sizes capped at 20 and a 4096 window.

## 21. Recommended Algorithm

Recommend **Option C: bounded lightweight enumeration plus greedy balanced selection**, implemented lazily/interleaved:

1. Discover current dynamic candidate pools.
2. Validate pool count and calculate product size.
3. Validate and accept preview first, if present.
4. Build a bounded set/schedule of at most 4096 lightweight selection tuples.
5. For spaces larger than 4096, use a deterministic stratified mixed-radix schedule—not the first 4096 raw lexicographic tuples.
6. Score remaining tuples against accepted per-Beat histograms.
7. Pick the best tuple.
8. Materialize it exactly once.
9. Compute the authoritative existing fingerprint.
10. Apply the existing `used_fingerprints` hard gate.
11. Update coverage counters only after acceptance.
12. Continue until request satisfaction, true exhaustion, or search-limit exhaustion.

Do not store thousands of full `CompilationPlan` objects. Store lightweight candidate tuples and materialize the proposed next choice on demand.

## 22. Determinism / Tie-Breaking

Current resolver discovery is intentionally/non-explicitly random. Therefore same database state does not currently guarantee the same pools or preview.

Recommended Phase 1 contract:

- Controlled randomness may remain in upstream candidate discovery.
- Given identical ordered pools, preview, request count, and budget, balanced selection must be deterministic.
- Balanced selection itself must not introduce additional randomness.

Recommended equal-score tie-break:

1. Current bounded enumeration ordinal, preserving resolver/pool preference.
2. Full `_selection_key` tuple.
3. Within any newly generated stratified ordering, normalized hash then asset ID.

Do not use preview proximity as a tie-break after preview has been accepted; that would encourage repeating preview components.

## 23. Coverage Metrics

Recommended Phase 1 diagnostic contract per Beat:

```text
beat_index
beat_identity
pool_size
selected_count
histogram: normalized_file_hash → count
max_min_gap
unique_used
classification
```

Primary metric:

```text
max_count - min_count
```

Include zero counts for available but unused candidates.

Secondary metric:

```text
unique_used / min(pool_size, accepted_batch_size)
```

Avoid entropy and Gini in Phase 1.

Conceptual greedy score after hypothetically adding a combination:

```text
variable axes only:
  axis_gap = max(histogram) - min(histogram)
  axis_deviation = mean squared deviation from accepted_count / pool_size

combination score:
  max(axis_gap),
  sum(normalized axis_deviation),
  enumeration ordinal,
  selection_key
```

Fixed axes are excluded. Equal Beat weights are used in V1.

## 24. 5-Beat Acceptance Model

Candidate space:

```text
Hook    4
Context 2
Build   1
Reveal  2
CTA     2

Total = 4 × 2 × 1 × 2 × 2 = 32
```

For batch 4, one ideal set is:

```text
H1 C1 B1 R1 T1
H2 C2 B1 R2 T2
H3 C1 B1 R2 T1
H4 C2 B1 R1 T2
```

Result:

| Beat | Distribution |
|---|---|
| Hook | `1/1/1/1` |
| Context | `2/2` |
| Build | `4` fixed |
| Reveal | `2/2` |
| CTA | `2/2` |
| Full combinations | `4/4` unique |

This target is achievable when the discovered Cartesian model remains independently materializable. It is not universally guaranteed when materialization invalidates combinations, the bounded window excludes needed combinations, or future dependencies constrain axes.

## 25. Preview Handling

For preview:

```text
H1 C1 B1 R1 T1
```

retain it as child 0 and initialize counters with it.

A valid continuation is:

```text
child0 H1 C1 B1 R1 T1  preview
child1 H2 C2 B1 R2 T2
child2 H3 C1 B1 R2 T1
child3 H4 C2 B1 R1 T2
```

The preview must count in coverage counters. Excluding it would optimize only children 1–3 and could make the final four-child distribution imbalanced.

If perfect balance cannot coexist with a fixed preview, preserve preview and exact uniqueness, then minimize imbalance softly. Do not fail planning solely for coverage.

## 26. Runtime Observability

FP-001B VariantFingerprint already exposes:

- child identity;
- full digest;
- `beat_count`;
- ordered Beat index and identity;
- authoritative asset ID;
- normalized source hash;
- planner/worker match.

Phase 1 real-media validation can aggregate the four runtime events by `beat_index` and normalized hash, verify the per-axis histograms, and confirm all full digests are unique without reconstructing FFmpeg inputs.

VariantFingerprint is sufficient for selected-output acceptance when expected pool sizes are known from the test fixture.

A future single coordinator summary event would help distinguish fixed capacity from imbalance by exposing bounded pool sizes and final histograms. It is useful but not required for Phase 1 implementation or acceptance.

## 27. Historical Novelty Boundary

Required layering remains:

```text
resolver eligibility
→ exact batch uniqueness
→ Balanced Axis Coverage
→ Historical Novelty
→ optional Perceptual Diversity
```

Phase 1 requires no historical ledger.

Future `main_visual_sequence_v1` or indexed ledger results can be introduced as:

- a hard exclusion for exact historical repeats; or
- a soft penalty in the combination score.

They must remain versioned and separate from `main_visual_planning_v1`. Current tuple and digest semantics must not change.

## 28. Policy Naming

Recommended new policy:

```text
exact_main_visual_balanced
```

It communicates both layers:

- `exact_main_visual`: hard full-combination uniqueness.
- `balanced`: soft axis-coverage strategy.

Avoid `balanced_axis` alone because it does not communicate the exact uniqueness contract. Avoid changing the meaning of `exact_main_visual`.

## 29. Backward Compatibility

| Policy | Required behavior |
|---|---|
| `legacy` | Existing worker-local resolver behavior unchanged |
| `exact_main_visual` | Existing preview, product order, early stop, capacity, budget, warnings, and coordinator behavior unchanged |
| `exact_main_visual_balanced` | Reuse exact materialization/fingerprint invariants, add coverage-aware selection |

`exact_main_visual` should remain source-path and selection-order compatible for existing callers. Silently changing it would make rollout, regression comparison, and INV evidence ambiguous.

A new policy provides clean A/B comparison and rollback.

## 30. Existing Test Coverage

| Test | File | Evidence |
|---|---|---|
| `test_p3_candidate_hash_dedup_preserves_first_resolver_candidate` | `test_inv001_variant_planning.py` | Normalized-hash dedup and first candidate retention |
| `test_locked_discovery_preserves_current_deleted_exhausted_and_axis_rules` | Same | Locked discovery eligibility |
| `test_formal_hook_physical_bgm_semantic_x_discovery_and_planning` | Same | Semantic fallback main-X discovery; Y exclusion |
| `test_p5_p6_p7_each_tuple_materialized_once_and_terminates_finitely` | Same | Finite product traversal; every 2×2 key examined once |
| `test_c4_preview_is_seeded_only_when_current_and_valid` | Same | Valid preview first; stale preview rejected |
| `test_p1_p2_p4_and_structural_repro_plan_four_unique_combinations` | Same | Four unique full fingerprints across three Beats |
| `test_a5_exact_coordinator_binds_unique_plans_after_planning` | Same | Accepted plans handed to authoritative children |
| `test_c1_true_capacity_two_does_not_duplicate_fill_request_four` | Same | True capacity warning |
| `test_c2_search_limit_is_not_reported_as_capacity_exhaustion` | Same | Search limit distinct from capacity |
| `test_c3_zero_candidate_space_accepts_no_plan` | Same | Zero-space behavior |
| `test_f3_beat_order_changes_fingerprint` | Same | Ordered fingerprint semantics |
| `test_fp7_five_dynamic_beats_preserve_ordered_components` | `test_fp001_fingerprint_contract.py` | Five-Beat fingerprint only |
| `test_fp8_arbitrary_beat_counts_are_deterministic` | Same | 1/3/7-Beat fingerprint only |
| Planning policy route/frontend tests | `test_inv001_planning_policy.py` | Explicit exact policy and legacy compatibility |

Missing coverage:

- Exact assertion of current product enumeration order.
- Dedicated `_selection_key` shape/order test.
- Dynamic 5- and 7-Beat planner tests.
- Deterministic candidate-order tie test.
- Resolver pool membership/order under equal ranking signals.
- Any per-axis coverage test.
- Preview-inclusive coverage counters.
- Large-space leading-axis reach under the 4096 bound.
- Balanced policy compatibility with capacity and search warnings.

## 31. Phase 1 Test Plan

| ID | Required proof |
|---|---|
| VAR1 | `P=4, B=4 → 1/1/1/1` |
| VAR2 | `P=4, B=6 → 2/2/1/1` |
| VAR3 | `2×2, B=4` selects all four combinations |
| VAR4 | `P=1` repeats ×B and is classified fixed |
| VAR5 | `4×2×1×2×2, B=4` reaches ideal coverage |
| VAR6 | All accepted existing fingerprints remain unique |
| VAR7 | Valid preview remains child 0 and counts toward coverage |
| VAR8 | Candidate window and examined attempts never exceed 4096 |
| VAR9 | True insufficient capacity preserves existing warning |
| VAR10 | Search-limit warning remains distinct |
| VAR11 | Dynamic 3-Beat balanced planning |
| VAR12 | Dynamic 5-Beat balanced planning |
| VAR13 | Dynamic 7-Beat balanced planning |
| VAR14 | Unequal pool sizes and floor/ceil distributions |
| VAR15 | Equal-score tie-break deterministic for fixed pools |
| VAR16 | `legacy` path unchanged |
| VAR17 | Existing `exact_main_visual` output order unchanged |
| Additional | Invalid materialization is skipped without updating coverage |
| Additional | Duplicate fingerprint is skipped without updating coverage |
| Additional | `candidate_space > 4096` exposes early-axis alternatives in bounded window |
| Additional | VariantFingerprint events reproduce selected histograms |

## 32. Performance Constraints

Phase 1 constraints:

- No unbounded Cartesian list.
- At most 4096 lightweight candidate combinations in a window.
- At most 4096 authoritative materialization attempts.
- No storage of 4096 full `CompilationPlan` objects.
- No source-file reads.
- No rendering during planning.
- No historical-media work.
- No DB migration.
- Preserve batch maximum 20.
- Scoring target: approximately `O(B × W × D)`, with `B≤20`, `W≤4096`, and dynamic Beat count `D`.

Approximate lightweight storage:

- Five candidate references in a Python tuple are roughly tens of bytes plus tuple overhead.
- 4096 five-Beat tuples are roughly 0.3–0.5 MiB for tuple/reference bodies.
- Scores, list storage, keys, and bookkeeping can raise this to a few MiB.
- Twenty-Beat tuples remain bounded, approximately under 1 MiB for raw tuple/reference bodies before bookkeeping.

Full Pydantic plans could be substantially larger and must not be retained for the full window.

## 33. Proposed File Scope

| File | Why | Phase 1 change |
|---|---|---|
| `src/api/routes_dsl.py` | Planner/coordinator policy ownership | New private balanced planner/helpers and new policy branch; reuse existing fingerprint/materialization |
| `src/api/schemas.py` | Request policy validation | Add `exact_main_visual_balanced` to existing Literal; no new field |
| `web_ui/src/views/WorkspaceView.vue` | AI Draft activation | Send new balanced policy after feature acceptance |
| `tests/test_var001_balanced_axis_coverage.py` | Focused VAR contract | VAR1–VAR17 and added edge cases |
| `tests/test_inv001_planning_policy.py` | Policy routing compatibility | New-policy route assertions only |

Not required:

- DB/models/migration.
- New Beat schema field.
- `dsl_parser.py` behavior change.
- Worker/compositor/TTS/subtitle/cover changes.
- Fingerprint contract changes.
- Historical ledger.

## 34. Architecture Risks

| Risk | Evidence | Phase 1 treatment |
|---|---|---|
| Lexicographic leading-axis starvation | Current `itertools.product` order | Stratified bounded window |
| Upstream pool nondeterminism | SQL/Python randomness | Deterministic selection conditional on discovered pools |
| Preview silently displaced | Preview currently accepted first | Preserve as child 0 |
| Preview ignored in fairness | No current counters | Seed counters with preview |
| Pre-validation capacity overstates materializable capacity | Mismatch/invalid branches exist | Preserve hard validation and exhaustion distinction |
| Expensive eager validation | Full resolver/materialization per key | Lightweight score, materialize selected attempts only |
| Role-based weighting unsafe | Arbitrary/non-unique role | Equal Beat weights in V1 |
| Search-window exhaustion mislabeled capacity | Space may exceed 4096 | Preserve search-limit warning |
| Coverage score weakens INV | Risk if digest replaces tuple gate | Existing tuple/set gate remains authoritative |
| Exact policy compatibility | Existing callers/tests | New policy; do not modify old behavior |

No evidence-backed architecture blocker remains. Phase 1 should stop if implementation would require changing fingerprint semantics, losing preview child 0, changing capacity warning meaning, or making coverage a render/planning correctness failure.

## 35. ADR

**Problem:** Exact full-combination uniqueness does not optimize per-Beat candidate distribution.

**Current behavior:** A preview seed followed by lexicographic Cartesian traversal, full-fingerprint dedup, and early termination.

**Hard invariants:**

- Existing resolver eligibility.
- Existing `_MainVisualFingerprint` tuple.
- Existing `_exact_main_visual_fingerprint()`.
- `used_fingerprints` uniqueness.
- Preview child 0.
- Search-budget bound.
- Capacity/search-limit distinction.
- Authoritative plan handoff.

**Decision:** Add `exact_main_visual_balanced`, using a bounded stratified lightweight candidate window and deterministic greedy coverage selection. Materialize only selected attempts; accept only after existing fingerprint validation and uniqueness.

**Rejected:**

- In-place exact policy change: backward-compatibility risk.
- Reordered product alone: residual axis bias.
- Direct round-robin alone: collision/exhaustion weaknesses.
- Beam/priority search: excessive Phase 1 complexity.

**Search budget:** Remains 4096; true exhaustion is reported only when the complete selection space is exhausted.

**Preview:** Valid preview remains child 0 and initializes coverage counts.

**Dynamic Beats:** All scoring state is indexed from dynamic candidate pools; no named Beat assumptions.

**Historical novelty:** Deferred and later introduced as a separate signal.

## 36. Final Recommendation

1. **New policy or in-place change?**  
   Introduce `exact_main_visual_balanced`.

2. **Algorithm?**  
   Bounded stratified lightweight enumeration plus greedy balanced selection—Option C.

3. **New schema fields?**  
   No new data fields. Only extend the existing policy Literal.

4. **Frontend changes?**  
   Yes, minimally, to request the new policy for AI Draft after Phase 1 acceptance.

5. **DB changes?**  
   No.

6. **Entirely planner-side?**  
   The balancing algorithm can remain planner-side. Product activation additionally needs the policy enum and frontend request value.

7. **Historical Novelty required now?**  
   No.

8. **Can VariantFingerprint support real-media validation?**  
   Yes. It directly supplies authoritative ordered components and full digests. Candidate pool sizes may be recorded separately by the test fixture; optional planner summary logging can be deferred.

## 37. Final Classification

**PHASE_1_READY**

Exact Phase 1 boundary:

- Add the new `exact_main_visual_balanced` request policy.
- Implement bounded, dynamic-Beat, preview-aware greedy coverage selection in the planner.
- Reuse current candidate discovery, authoritative materialization, tuple fingerprint, uniqueness set, coordinator invariant, and worker handoff.
- Preserve `legacy` and `exact_main_visual` behavior.
- Preserve 4096 budget and existing capacity/search warnings.
- Add VAR1–VAR17 tests.
- No logging, persistence, history, DB, resolver, or fingerprint changes.

## 38. Final Git Status

Final checks:

```text
git status --short
<empty>

git diff --stat
<empty>
```

Read-only safety result: **PASS**. No modifications, commits, pushes, or Phase 1 implementation were performed.