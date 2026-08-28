# VAR-001 Phase 1A
# Targeted Small Fix-up Report

## 1. Findings Addressed

- `VAR1A-RF-01` — preview collision now receives bounded deterministic refill.
- `VAR1A-RF-02` — VAR5 now locally asserts 4/4 unique fingerprints.
- `VAR1A-RF-03` — VAR7 now locally asserts 4/4 unique fingerprints.

## 2. Files Changed

- [src/api/routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:693)
- [tests/test_var001_balanced_axis_coverage.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_var001_balanced_axis_coverage.py:173)

No other files changed.

## 3. RF-01 Window Refill Design

The large-space path now oversamples by the exclusion count:

```python
sample_count = min(
    candidate_space_size,
    max_entries + len(excluded_keys),
)
ordinals = _stratified_cartesian_ordinals(
    candidate_space_size,
    sample_count,
)
```

It then retains existing behavior:

```python
if selection_key in seen_keys:
    continue
...
if len(entries) >= max_entries:
    break
```

For a production-shaped single preview collision:

```text
desired entries: 10
sampled ordinals: 11
excluded preview: 1
returned entries: 10
```

Small-space full-range enumeration remains unchanged.

## 4. Bound / Performance Proof

Large-space work is bounded by:

```text
sample_count <= max_entries + len(excluded_keys)
```

For current production semantics, exclusions are zero or one preview key. With a valid preview and budget 4096:

```text
max_entries = 4095
sample_count <= 4096
```

The fix introduces no:

- Full Cartesian scan
- `CompilationPlan` window
- Extra authoritative materialization
- Source-file access
- Database work
- Randomness

Only lightweight candidate tuples, keys, and ordinals are oversampled.

## 5. Search Budget Preservation

Window construction still uses only its local `seen_keys`. It does not modify `examined_keys`.

Budget consumption remains restricted to:

```python
examined_keys.add(preview_key)
examined_keys.add(proposal.selection_key)
```

Therefore:

```text
1 preview + at most 4095 attempted proposals = at most 4096 examined keys
```

No budget definition or warning semantics changed.

## 6. Leading-Axis Stratification Preservation

The refill still uses `_stratified_cartesian_ordinals()` across the complete ordinal range. It does not fall back to a lexicographic prefix.

The existing large-space test continues to prove:

```text
raw prefix: H1 only
stratified window: H1, H2, H3, H4
first ordinal: 0
last ordinal: N-1
```

## 7. RF-01 Regression Test

Added:

```python
test_large_space_refills_preview_collision_to_remaining_budget
```

Fixture:

```text
candidate space: 4 × 64 = 256
remaining budget: 10
excluded preview: ordinal 0
```

Assertions prove:

- Original 10-sample schedule leaves 9 entries after filtering.
- Fixed helper returns 10 entries.
- Preview key is absent.
- All 10 selection keys are unique.

## 8. VAR5 Local Uniqueness

Added directly to the golden five-Beat test:

```python
self.assertEqual(len(result.fingerprints), 4)
self.assertEqual(len(set(result.fingerprints)), 4)
```

All existing `4×2×1×2×2` coverage assertions remain unchanged. VAR6 remains an independent hard-gate test.

## 9. VAR7 Local Uniqueness

Added directly to the preview test:

```python
self.assertEqual(len(result.fingerprints), 4)
self.assertEqual(len(set(result.fingerprints)), 4)
```

Retained:

- Preview object at `plans[0]`
- Preview fingerprint at `fingerprints[0]`
- Preview-aware coverage compensation
- Ideal final axis histograms

## 10. VAR Tests

```text
Ran 26 tests
OK
```

All previous 25 tests plus the RF-01 regression passed.

## 11. INV Regression

```text
Ran 82 tests
OK
```

No INV-001 regression.

## 12. FP Regression

```text
Ran 42 tests
OK
```

No fingerprint contract or observability regression.

## 13. Exact Control Preservation

`git diff --unified=0` still shows additions only after the existing exact planner’s return:

```text
@@ -34,0 +35 @@ import hashlib
@@ -615,0 +617,307 @@ def _plan_exact_main_visual_variants(
```

No line inside `_plan_exact_main_visual_variants()` changed. Its historical lexicographic control test passes.

## 14. Production Activation Audit

Production search confirms:

- `_plan_exact_main_visual_balanced_variants()` has definition only.
- No `exact_main_visual_balanced` production policy.
- No schema change.
- No frontend change.
- No `render_batch_worker` routing.
- No live request can invoke the balanced core.

## 15. Scope Audit

The production fix changes only the large-space ordinal count inside `_balanced_candidate_window()`.

Unchanged:

- Mixed-radix decoder
- Coverage initialization/score/update
- Greedy lifecycle
- Exact fingerprint
- Search-budget constant
- Capacity/search-limit classification
- Existing exact planner
- Worker and rendering behavior

`py_compile` and `git diff --check` passed.

## 16. Review Findings

NONE.

## 17. Final Git Status

```text
 M src/api/routes_dsl.py
?? tests/test_var001_balanced_axis_coverage.py
```

No commit or push was performed. Phase 1B, frontend activation, and real-media testing were not started.

VAR001_PHASE1A_FIXUP_PASS