# VAR-001 Phase 1A
# Targeted Balanced Planner Core Code Review Bundle

## 1. Baseline

```text
branch: feature/var-001-variation-policy
HEAD:   6618f61d21fffc3abf6f3f324c21d842ec8355a7
```

Working tree:

```text
 M src/api/routes_dsl.py
?? tests/test_var001_balanced_axis_coverage.py
```

`git diff --check`: PASS. The CRLF message is a working-copy warning, not a diff error.

## 2. Production Diff

The production diff contains exactly two hunks:

| Hunk | Classification |
|---|---|
| `import heapq` | A. balanced runtime support |
| New contiguous private block after the existing exact planner | B–H |

New block:

- `_BalancedCandidateWindowEntry`: A
- `_selection_from_cartesian_ordinal`: B
- `_stratified_cartesian_ordinals`: C
- `_balanced_candidate_window`: D
- `_initial_main_visual_coverage`: E
- `_projected_main_visual_coverage_score`: F
- `_update_main_visual_coverage`: G
- `_plan_exact_main_visual_balanced_variants`: H

Results:

```text
I. existing exact planner modification: NONE
J. production routing/policy activation: NONE
K. unrelated change: NONE
```

Production implementation: [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:638).

## 3. Existing Exact Planner Preservation

`git diff --unified=0` shows only:

```text
@@ -34,0 +35 @@ import hashlib
@@ -615,0 +617,303 @@ def _plan_exact_main_visual_variants(
```

The second hunk begins after the old function’s existing return. No line inside `_plan_exact_main_visual_variants()` changed.

Current production caller:

```python
def _plan_exact_main_visual_variants_from_db(...):
    ...
    return _plan_exact_main_visual_variants(
        DSLParserNode(db),
        dsl_payload,
        requested_count,
        preview_plan=preview_plan,
    )
```

There is no production call to `_plan_exact_main_visual_balanced_variants()`.

**EXACT_CONTROL_UNCHANGED**

## 4. Mixed-Radix Decoder

Complete helper:

```python
def _selection_from_cartesian_ordinal(
    candidate_pools: Sequence[Sequence[MainVisualCandidate]],
    ordinal: int,
) -> tuple[MainVisualCandidate, ...]:
    """Decode a rightmost-fastest flat Cartesian ordinal without materializing it."""
    if not candidate_pools or any(not pool for pool in candidate_pools):
        raise ValueError("candidate pools must be non-empty")

    candidate_space_size = prod(len(pool) for pool in candidate_pools)
    if ordinal < 0 or ordinal >= candidate_space_size:
        raise ValueError("Cartesian ordinal is outside candidate space")

    remaining = ordinal
    candidate_indexes = [0] * len(candidate_pools)
    for beat_index in range(len(candidate_pools) - 1, -1, -1):
        remaining, candidate_indexes[beat_index] = divmod(
            remaining,
            len(candidate_pools[beat_index]),
        )
    return tuple(
        candidate_pools[beat_index][candidate_index]
        for beat_index, candidate_index in enumerate(candidate_indexes)
    )
```

Actual behavior:

- `[2,2,2]`: rightmost radix changes fastest.
- `[4,2,1,2,2]`: radix `1` always decodes to index `0`; surrounding ordering remains correct.
- `[4]`: ordinals `0..3` map directly to its four candidates.
- Ordinal `0`: first Cartesian tuple.
- Ordinal `N-1`: last Cartesian tuple.
- Negative ordinal: `ValueError`.
- Ordinal `>= N`: `ValueError`.
- Empty pool collection or any empty pool: `ValueError`.

Complete equivalence test:

```python
def test_mixed_radix_decoding_matches_itertools_product(self):
    pools = _pools(2, 3, 2)
    expected = list(product(*pools))

    actual = [
        routes_dsl._selection_from_cartesian_ordinal(pools, ordinal)
        for ordinal in range(len(expected))
    ]

    self.assertEqual(actual, expected)
```

It compares every position, not merely set equality.

## 5. Stratified Ordinals

Complete helper:

```python
def _stratified_cartesian_ordinals(
    candidate_space_size: int,
    sample_count: int,
) -> tuple[int, ...]:
    """Return deterministic evenly spaced ordinals spanning the full space."""
    if candidate_space_size < 0:
        raise ValueError("candidate_space_size must be non-negative")
    if sample_count < 0:
        raise ValueError("sample_count must be non-negative")
    if candidate_space_size == 0 or sample_count == 0:
        return ()
    if sample_count >= candidate_space_size:
        return tuple(range(candidate_space_size))
    if sample_count == 1:
        return (0,)
    return tuple(
        sample_index * (candidate_space_size - 1) // (sample_count - 1)
        for sample_index in range(sample_count)
    )
```

Boundary behavior:

| N | W | Result |
|---:|---:|---|
| 1 | 1 | `(0,)` |
| >1 | 1 | `(0,)` |
| N | N | `range(N)` |
| 5 | 4 | `(0,1,2,4)` |
| 100 | 10 | `(0,11,22,33,44,55,66,77,88,99)` |

There is no division-by-zero path: `W=0` and `W=1` return before division.

For `N>W>1`, `(N-1)/(W-1)>1`, so sampled ordinals are strictly increasing, unique, in range, and include both `0` and `N-1`. For the unavoidable `W=1` case, only ordinal `0` is returned.

**STRATIFIED_ORDINALS_SAFE**

## 6. Candidate Window

Complete helper:

```python
def _balanced_candidate_window(
    candidate_pools: Sequence[Sequence[MainVisualCandidate]],
    candidate_space_size: int,
    max_entries: int,
    *,
    excluded_keys: set[tuple[tuple[int, str], ...]],
) -> tuple[_BalancedCandidateWindowEntry, ...]:
    """Build a bounded lightweight full-space or stratified proposal window."""
    if max_entries <= 0 or candidate_space_size <= 0:
        return ()

    remaining_space_size = max(candidate_space_size - len(excluded_keys), 0)
    if remaining_space_size <= max_entries:
        ordinals: Sequence[int] = range(candidate_space_size)
    else:
        ordinals = _stratified_cartesian_ordinals(
            candidate_space_size,
            min(max_entries, candidate_space_size),
        )

    entries: list[_BalancedCandidateWindowEntry] = []
    seen_keys = set(excluded_keys)
    for ordinal in ordinals:
        selections = _selection_from_cartesian_ordinal(candidate_pools, ordinal)
        selection_key = _selection_key(selections)
        if selection_key in seen_keys:
            continue
        seen_keys.add(selection_key)
        entries.append(
            _BalancedCandidateWindowEntry(
                selections=selections,
                selection_key=selection_key,
                cartesian_ordinal=ordinal,
            )
        )
        if len(entries) >= max_entries:
            break
    return tuple(entries)
```

Small space iterates the complete range and filters excluded keys. Large space generates exactly `max_entries` stratified ordinals and then filters.

Window entry:

```python
@dataclass(frozen=True)
class _BalancedCandidateWindowEntry:
    selections: tuple[MainVisualCandidate, ...]
    selection_key: tuple[tuple[int, str], ...]
    cartesian_ordinal: int
```

It contains no `CompilationPlan`, `ResolvedLayer`, DB session, `LocalAsset`, or media payload.

## 7. Window Underfill

**WINDOW_CAN_UNDERFILL_AFTER_SKIP**

Example:

```text
remaining budget = 10
sampled ordinals = 10
preview key matches one sampled ordinal
resulting window = 9 proposals
```

The helper does not continue with replacement ordinals after a sampled key is skipped.

Current planner supplies only zero or one excluded key—the validated preview. Therefore, practical production impact is bounded to:

- At most one unused search-budget slot.
- At most one fewer accepted child than a deterministic refill could potentially recover.
- Exact uniqueness remains intact.
- The result remains `PLANNING_SEARCH_LIMIT_REACHED`, not false capacity exhaustion.

Severity: **MEDIUM — planning-capacity utilization; blocks Phase 1B activation, but does not affect INV correctness.**

## 8. Coverage Initialization

```python
def _initial_main_visual_coverage(
    candidate_pools: Sequence[Sequence[MainVisualCandidate]],
) -> list[dict[str, int]]:
    return [
        {
            normalize_file_hash(candidate.file_hash): 0
            for candidate in pool
        }
        for pool in candidate_pools
    ]
```

- P=1: one zero counter.
- P>1: every normalized content identity begins at zero.
- Duplicate normalized hashes collapse into one counter.

Production discovery already guarantees per-Beat normalized-hash deduplication:

```python
normalized_hash = normalize_file_hash(...)
if not normalized_hash or normalized_hash in seen_hashes:
    continue
seen_hashes.add(normalized_hash)
```

## 9. Preview Coverage

```python
if preview_selections is not None and candidate_space_size:
    preview_key = _selection_key(preview_selections)
    preview_fingerprint = _exact_main_visual_fingerprint(preview_plan)
    examined_keys.add(preview_key)
    accepted_plans.append(preview_plan)
    accepted_fingerprints.append(preview_fingerprint)
    used_fingerprints.add(preview_fingerprint)
    _update_main_visual_coverage(coverage, preview_fingerprint)
```

Coverage uses the accepted authoritative preview fingerprint—not the preview selection tuple.

The preview:

- Is appended before every planned proposal.
- Remains `accepted_plans[0]`.
- Adds exactly one key to `examined_keys`.
- Seeds both uniqueness and coverage.

## 10. Coverage Authority

Complete updater:

```python
def _update_main_visual_coverage(
    coverage: Sequence[dict[str, int]],
    fingerprint: _MainVisualFingerprint,
) -> None:
    if len(fingerprint) != len(coverage):
        raise ValueError("accepted fingerprint Beat count does not match coverage")
    for beat_index, _beat_identity, _layer_index, normalized_file_hash in fingerprint:
        if beat_index < 0 or beat_index >= len(coverage):
            raise ValueError("accepted fingerprint Beat index is outside coverage")
        if normalized_file_hash not in coverage[beat_index]:
            raise ValueError("accepted fingerprint hash is outside candidate pool")
        coverage[beat_index][normalized_file_hash] += 1
```

Normal proposals call it only after:

```python
if fingerprint in used_fingerprints:
    continue
accepted_plans.append(materialized)
accepted_fingerprints.append(fingerprint)
used_fingerprints.add(fingerprint)
_update_main_visual_coverage(coverage, fingerprint)
```

**COVERAGE_AUTHORITY_AUTHORITATIVE**

## 11. Coverage Score

Returned tuple:

```python
return (
    max(axis_gaps, default=0),
    sum(axis_gaps),
    sum(axis_mses),
    entry.cartesian_ordinal,
    entry.selection_key,
)
```

Per-axis calculation:

```python
projected_counts = list(axis_coverage.values())
candidate_position = tuple(axis_coverage).index(candidate_hash)
projected_counts[candidate_position] += 1
axis_gap = max(projected_counts) - min(projected_counts)
target = sum(projected_counts) / len(projected_counts)
axis_mse = sum(
    (count - target) ** 2 for count in projected_counts
) / len(projected_counts)
```

This is the required order and MSE is divided by pool size.

Python float arithmetic is deterministic enough for identical in-process inputs here. Iteration uses ordered selections, coverage sequences, and insertion-ordered dictionaries; no set iteration participates in score accumulation.

## 12. Zero-Count Semantics

All histogram values—including zeros—are copied before the hypothetical increment.

For:

```text
A1=1 A2=0 A3=0 A4=0
```

- Propose A1 → `[2,0,0,0]`, gap `2`, MSE `0.75`
- Propose A2 → `[1,1,0,0]`, gap `1`, MSE `0.25`

A2 therefore wins before ordinal/key tie-breaking.

The pure score test independently confirms an unused candidate outranks an overused candidate.

## 13. Fixed-Axis Exclusion

```python
if len(axis_coverage) <= 1:
    continue
```

Fixed axes contribute nothing to maximum gap, summed gap, or MSE.

The test evaluates the same proposal with fixed-axis counts `1` and `100` and asserts identical first three score fields.

## 14. Greedy Loop

The lifecycle is:

```python
while (
    len(accepted_plans) < requested_count
    and len(examined_keys) < search_budget
):
    remaining_entries = [
        entry for entry in window if entry.selection_key not in examined_keys
    ]
    if not remaining_entries:
        break

    scored_entries = [
        (_projected_main_visual_coverage_score(entry, coverage), entry)
        for entry in remaining_entries
    ]
    heapq.heapify(scored_entries)
    accepted_this_round = False

    while scored_entries and len(examined_keys) < search_budget:
        _score, proposal = heapq.heappop(scored_entries)
        examined_keys.add(proposal.selection_key)
        try:
            materialized = parser.materialize_with_main_selections(
                dsl_payload,
                proposal.selections,
            )
            fingerprint = _exact_main_visual_fingerprint(materialized)
            selected_hashes = tuple(
                candidate.file_hash for candidate in proposal.selections
            )
            materialized_hashes = tuple(row[3] for row in fingerprint)
            if selected_hashes != materialized_hashes:
                raise MainVisualSelectionMismatch(...)
        except MainVisualSelectionMismatch:
            selection_mismatch_seen = True
            ...
            continue
        except ValueError:
            ...
            continue

        if fingerprint in used_fingerprints:
            continue

        accepted_plans.append(materialized)
        accepted_fingerprints.append(fingerprint)
        used_fingerprints.add(fingerprint)
        _update_main_visual_coverage(coverage, fingerprint)
        accepted_this_round = True
        break

    if not accepted_this_round:
        break
```

Only the chosen proposal is materialized. Coverage is rescored after each acceptance.

## 15. Failed Proposal Lifecycle

A proposal is added to `examined_keys` before materialization. On the next outer iteration:

```python
remaining_entries = [
    entry for entry in window if entry.selection_key not in examined_keys
]
```

Within its current heap it was already popped. Consequently, invalid, mismatched, and duplicate proposals cannot be retried.

**FAILED_PROPOSALS_NOT_RETRIED**

Invalid-materialization test proves:

- 3 examined attempts
- 2 accepted plans
- Coverage updater called exactly twice
- Failed first candidate absent from accepted histogram
- Planner continues to the other candidates

Duplicate test proves:

- Different keys `(asset 1, same)` and `(asset 2, same)`
- Both materialize to the same exact fingerprint
- Three proposals attempted
- Only two fingerprints accepted
- Coverage updater called exactly twice
- Planner continues to `other`

## 16. Budget Semantics

Balanced-planner writes to `examined_keys` occur only at:

```python
examined_keys.add(preview_key)
examined_keys.add(proposal.selection_key)
```

Window construction uses a separate local `seen_keys` and does not consume budget.

The loop checks:

```python
len(examined_keys) < search_budget
```

before proposal insertion. A valid preview reduces `max_entries` by one:

```python
search_budget - len(examined_keys)
```

Thus budget 4096 permits at most:

```text
1 preview + 4095 non-preview attempts = 4096
```

It cannot reach 4097.

## 17. Capacity vs Search Limit

Termination:

```python
if len(accepted_plans) >= requested_count:
    REQUEST_SATISFIED
elif len(examined_keys) >= candidate_space_size:
    TRUE_SPACE_EXHAUSTED / INSUFFICIENT_UNIQUE_CAPACITY
else:
    SEARCH_LIMIT_REACHED / PLANNING_SEARCH_LIMIT_REACHED
```

Results:

- Case A: complete small space examined → capacity warning.
- Case B: large bounded window exhausted → search-limit warning.
- Case C: preview collision underfills the window, examined count remains below budget and global keys remain → still search-limit warning.

True exhaustion relies on `len(examined_keys) >= candidate_space_size`. This is sound for production candidate pools because discovery deduplicates each pool by normalized hash and Cartesian selection keys are unique.

## 18. Golden Tests

VAR2 uses 4×2 capacity 8, requests 6, and asserts:

```python
sorted(histogram) == [1, 1, 2, 2]
len(fingerprints) == 6
len(set(fingerprints)) == 6
```

VAR5 exercises the actual balanced planner with `4×2×1×2×2`, requesting 4, and asserts:

```text
Hook:    1/1/1/1
Context: 2/2
Build:   4
Reveal:  2/2
CTA:     2/2
```

However, VAR5 does not contain its own `4/4 unique` assertion. VAR6 separately repeats the same fixture and proves authoritative exact-fingerprint uniqueness.

VAR7 proves:

- Preview object is exactly `plans[0]`.
- Its fingerprint is `fingerprints[0]`.
- Hook and the three 2-candidate axes reach ideal distributions.

VAR7 does not locally assert full fingerprint uniqueness.

## 19. Dynamic Beat Tests

VAR11, VAR12, and VAR13 invoke `_balanced()` with respectively 3, 5, and 7 two-candidate pools.

For every generated plan they assert:

- Four plans returned.
- Four unique fingerprints.
- Beat names preserve submitted dynamic order.
- Fingerprint beat indexes equal `range(beat_count)`.
- Fingerprint beat identities equal the submitted names.

They exercise the actual balanced planner, not standalone fingerprint helpers.

## 20. Determinism

VAR15 constructs one ordered `4×3×2` pool set and executes the balanced planner three separate times.

It compares:

- Accepted ordered source-hash sequences across all three results.
- Complete fingerprint tuples across all three results.

No result cache is reused.

## 21. Old Exact Control

The control test directly invokes `_plan_exact_main_visual_variants()` with `2×2×2`, request 4, and asserts:

```text
A1 B1 C1
A1 B1 C2
A1 B2 C1
A1 B2 C2
```

This confirms historical rightmost-fastest lexicographic behavior remains intact.

## 22. Production Activation Audit

Production search results:

```text
_plan_exact_main_visual_balanced_variants:
  definition only

exact_main_visual_balanced:
  no production matches
```

Current schema remains:

```python
Literal["legacy", "exact_main_visual"]
```

Current coordinator remains routed through `_plan_exact_main_visual_variants_from_db()`, which invokes the old exact planner.

`WorkspaceView.vue`, `schemas.py`, and `render_batch_worker` have no balanced-policy activation or diff.

## 23. INV / FP Preservation

No changed lines exist in:

- `_MainVisualFingerprint`
- `_exact_main_visual_fingerprint`
- `_main_visual_planning_fingerprint_contract`
- `VariantFingerprint` event construction/emission
- Worker handoff
- FP canonical serialization or digest

The new core reuses the existing exact fingerprint; it introduces no new identity contract.

## 24. Test Results

| Suite | Result |
|---|---:|
| VAR Phase 1A | 25/25 PASS |
| INV-001 | 82/82 PASS |
| FP-001 | 42/42 PASS |
| `py_compile` | PASS |
| `git diff --check` | PASS |

VAR10’s displayed mismatch trace is deliberately generated by its forced failure fixture; the test passes.

## 25. Review Findings

**VAR1A-RF-01 — STRATIFIED_WINDOW_PREVIEW_COLLISION_NOT_REFILLED**

- Severity: medium
- Scope: search-budget/capacity utilization
- Impact: current production-shaped caller can lose one non-preview attempt when the preview is a sampled ordinal.
- Correctness: does not weaken exact uniqueness and does not misclassify true exhaustion.
- Recommendation: fix before Phase 1B activation.

**VAR1A-RF-02 — VAR5_LOCAL_UNIQUENESS_ASSERTION_MISSING**

- Severity: low, test evidence
- VAR6 proves uniqueness using the same fixture, but the golden VAR5 test itself does not assert 4/4 unique fingerprints.

**VAR1A-RF-03 — VAR7_LOCAL_UNIQUENESS_ASSERTION_MISSING**

- Severity: low, test evidence
- Preview placement and compensation are proven, but the preview golden test does not locally assert full fingerprint uniqueness.

## 26. Final Classification

VAR001_PHASE1A_FIXUP_REQUIRED

## 27. Final Git Status

```text
 M src/api/routes_dsl.py
?? tests/test_var001_balanced_axis_coverage.py
```

No files were modified during this review. No commit, push, policy activation, or Phase 1B work was performed.