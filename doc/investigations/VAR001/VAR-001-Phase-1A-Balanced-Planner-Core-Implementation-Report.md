# VAR-001
# Phase 1A
# Balanced Planner Core Implementation Report

## 1. Baseline

- Branch: `feature/var-001-variation-policy`
- HEAD: `6618f61d21fffc3abf6f3f324c21d842ec8355a7`
- Initial worktree: clean
- Base commit: `feat(fp-001): add runtime fingerprint observability`

## 2. Files Changed

- Modified: [src/api/routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:638)
- Added: [tests/test_var001_balanced_axis_coverage.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_var001_balanced_axis_coverage.py:1)

No optional report file was created.

## 3. Existing Exact Planner Preservation

The body of `_plan_exact_main_visual_variants()` remains unchanged.

The new balanced implementation is a separate private function. Existing lexicographic `itertools.product`, preview handling, early stopping, uniqueness, budget, capacity, and warning behavior remain the production control.

## 4. Balanced Core Architecture

Added `_plan_exact_main_visual_balanced_variants()` using:

- Existing candidate discovery
- Existing preview validation
- A bounded lightweight candidate window
- Greedy coverage-aware selection
- Existing authoritative materialization
- Existing exact fingerprint hard gate
- Existing `_VariantPlanningResult`

The helper is not connected to any production request path.

## 5. Candidate Window

`_balanced_candidate_window()`:

- Uses the full lightweight Cartesian space when it fits the remaining budget.
- Uses deterministic stratified ordinals for larger spaces.
- Stores candidate tuples, selection keys, and ordinals—not `CompilationPlan` objects.
- Skips preview/already-examined keys.
- Does not consume budget until a proposal is actually attempted.

## 6. Mixed-Radix Ordinal Mapping

`_selection_from_cartesian_ordinal()` decodes rightmost-fastest mixed-radix ordinals without constructing the full product list.

Tests prove exact positional equivalence with `itertools.product()`.

## 7. Large-Space Stratification

`_stratified_cartesian_ordinals()` implements:

```text
floor(i × (N - 1) / (W - 1))
```

using integer arithmetic. It includes both ends of the Cartesian space and prevents systematic first-4096 lexicographic-prefix starvation.

## 8. Preview Handling

A valid preview:

- Remains accepted plan index 0.
- Enters `examined_keys`.
- Enters `used_fingerprints`.
- Consumes one search-budget key.
- Seeds coverage from its authoritative exact fingerprint.

Invalid or stale previews retain existing `_preview_selection()` behavior.

## 9. Coverage State

Coverage is represented as:

```text
coverage[beat_index][normalized_file_hash] = accepted_count
```

All eligible candidate hashes begin at zero. Fixed axes remain present but do not contribute a fairness penalty.

Coverage changes only after authoritative acceptance.

## 10. Coverage Score

The deterministic lexicographic score is:

```text
(
  maximum projected variable-axis gap,
  sum of projected variable-axis gaps,
  sum of projected variable-axis MSE,
  Cartesian ordinal,
  selection key
)
```

No role weighting, resolver score, historical data, or randomness is used.

## 11. Greedy Selection

For every accepted coverage state, the planner:

1. Scores all remaining lightweight proposals.
2. Selects the minimum deterministic score.
3. Marks that selection key examined.
4. Materializes only that proposal.
5. Continues through invalid or duplicate proposals without changing coverage.
6. Rescores after each successful acceptance.

## 12. Authoritative Materialization

Every proposal still passes through:

```text
materialize_with_main_selections()
→ _exact_main_visual_fingerprint()
→ selected/materialized hash validation
```

Failed materialization and selection mismatch consume examined budget but do not produce children or update coverage.

## 13. Exact Fingerprint Hard Gate

The existing `_MainVisualFingerprint` and `_exact_main_visual_fingerprint()` remain authoritative.

Accepted plans must satisfy:

```python
fingerprint not in used_fingerprints
```

No VAR-specific identity was introduced.

## 14. Budget Semantics

- Existing default budget remains 4096.
- Only actually attempted selection keys consume budget.
- Preview consumes one key under existing semantics.
- Lightweight scoring and window construction do not consume budget.
- Tests confirm examined combinations never exceed the injected budget.

## 15. Capacity vs Search Limit

Preserved semantics:

- Complete global space examined and still underfilled: `INSUFFICIENT_UNIQUE_CAPACITY`
- Global space larger than examined budget/window: `PLANNING_SEARCH_LIMIT_REACHED`

Window exhaustion in a large space is not treated as proof of true capacity exhaustion.

## 16. Dynamic Beat Behavior

The implementation operates exclusively over dynamic candidate-pool and fingerprint sequences.

Direct tests cover 3, 5, and 7 Beats. No Hook, Context, Build, Reveal, or CTA-specific production logic was added.

## 17. Determinism

Given identical pools, preview, budget, and materialization outcomes:

- Stratified ordinals are identical.
- Scores and tie-breaks are identical.
- Proposal order is identical.
- Accepted fingerprints are identical.

No new random source was introduced.

## 18. Tests Added

25 tests were added:

- VAR1: P=4, batch 4 gives `1/1/1/1`
- VAR2: 4×2, batch 6 gives target `2/2/1/1`
- VAR3: complete 2×2 combination set
- VAR4: fixed-axis behavior
- VAR5: golden 4×2×1×2×2 distribution
- VAR6: existing fingerprint uniqueness
- VAR7: preview remains child 0 and seeds coverage
- VAR8: budget bound
- VAR9: true capacity exhaustion
- VAR10: search-limit distinction
- VAR11–VAR13: dynamic 3/5/7 Beats
- VAR14: balanced 4×3×2 unequal pools
- VAR15: deterministic repeated execution
- Invalid best materialization
- Duplicate authoritative fingerprint
- Large-space stratification
- Mixed-radix equivalence
- Lightweight materialization count
- Unused-versus-overused score
- Fixed-axis score exclusion
- Ordinal/key tie-breaking
- Historical exact-planner control
- No production policy activation

Result: **25/25 PASS**

## 19. INV Regression

Command:

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

Result: **82 tests PASS**

## 20. FP Regression

Command:

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_fp001_*.py" -q
```

Result: **42 tests PASS**

## 21. Performance Audit

Confirmed:

- No unbounded full Cartesian list
- Window bounded by remaining search budget
- No storage of window-sized `CompilationPlan` collections
- Only selected proposals are materialized
- No source-file reads
- No rendering
- No history lookup
- No database work

Expected scoring complexity is approximately `O(B × W × D)`, plus bounded failed attempts.

## 22. Scope Audit

Production changes are confined to `src/api/routes_dsl.py`.

No changes to:

- Schema or request policy
- Frontend
- `dsl_parser.py`
- Models or database
- Worker/rendering pipeline
- Fingerprint semantics
- FP-001 observability
- Historical novelty

`exact_main_visual_balanced` appears only in tests that prove it has not been activated.

## 23. Review Findings

NONE.

`py_compile` passed for both changed Python files. `git diff --check` passed. The displayed LF/CRLF notice is a Git working-copy warning, not a diff error.

## 24. Final Git Status

```text
 M src/api/routes_dsl.py
?? tests/test_var001_balanced_axis_coverage.py
```

No commit or push was performed. Phase 1B and real-media testing were not started.

VAR001_PHASE1A_CORE_PASS