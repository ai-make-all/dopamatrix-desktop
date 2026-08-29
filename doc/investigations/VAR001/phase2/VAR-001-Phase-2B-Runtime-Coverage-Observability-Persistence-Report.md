# VAR-001
# Phase 2B
# Runtime Coverage Observability & Persistence Report

## 1. Baseline

- Branch: `feature/var-001-variation-policy`
- HEAD: `f3a651aa298edccc2c3f93df616ae687a15dfab7`
- Phase 1 tag: `var-001-balanced-coverage-v1`
- Initial worktree: clean

## 2. Files Changed

- [src/api/routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:220)
- [test_var001_coverage_diagnostics.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_var001_coverage_diagnostics.py:92)
- [test_var001_policy_integration.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_var001_policy_integration.py:285)

The Phase 1B integration fixtures now obtain balanced results from the real balanced planner, satisfying the new mandatory diagnostics contract.

## 3. CoverageDiagnosticsV1 Contract

Added private frozen contracts:

- `_CoverageHistogramEntryV1`
- `_CoverageBeatDiagnosticsV1`
- `_CoverageRejectionCountsV1`
- `_CoverageDiagnosticsV1`

Contract identity:

- `type = balanced_axis_coverage`
- `version = 1`
- `variant_planning_policy = exact_main_visual_balanced`

## 4. Planning Result Extension

`_VariantPlanningResult` now has a final nullable field:

```python
coverage_diagnostics: Optional[_CoverageDiagnosticsV1] = None
```

Behavior:

- Balanced planner: populated
- Existing exact planner: `None`
- Legacy: bypasses the authoritative planner result path

## 5. Candidate Pool Evidence

Per Beat, diagnostics retain:

- Request-time hash-deduplicated `pool_size`
- Selected histogram only
- No unused candidate identities

Coverage identity uses normalized `file_hash`. `asset_id` is presentation metadata only.

## 6. Coverage Mathematics

For accepted planning count `B` and pool size `P`:

- `ideal_floor = B // P`
- `ideal_ceil = ideal_floor` when divisible, otherwise `ideal_floor + 1`
- `unused_count = P - unique_used`
- `max_min_gap` includes conceptual zero counts for unused candidates

`P=0` is handled without division.

## 7. Coverage Classification

Implemented exactly:

- `FIXED_BY_CAPACITY`
- `VARIABLE_BALANCED`
- `VARIABLE_TARGET_NOT_MET`

Balanced classification validates the complete vector, its length, non-negative integer counts, sum, and exact floor/ceil distribution.

## 8. Selected Histogram

Entries are emitted in captured candidate-pool order:

```json
{
  "normalized_file_hash": "...",
  "asset_id": 123,
  "count": 2
}
```

Unused hashes are not serialized.

## 9. Counter Semantics

Added additive counters at existing lifecycle points:

- `proposal_attempted_count`
- `materialization_mismatch_count`
- `invalid_plan_count`
- `duplicate_fingerprint_reject_count`

Preview and scored-but-unattempted window entries are excluded from proposal attempts.

## 10. Counter Invariants

Builder enforces:

```text
examined_count
= proposal_attempted_count + preview_seeded_count
```

and:

```text
proposal_attempted_count
= non_preview_accepted_count
+ materialization_mismatch_count
+ invalid_plan_count
+ duplicate_fingerprint_reject_count
```

No uncovered proposal outcome branch was found.

## 11. Search Diagnostics

Persisted directly from the completed planner:

- `candidate_space_size`
- Actual invocation `search_budget`
- Final `examined_count`
- Existing `termination_reason`

Warning-code semantics remain outside CoverageDiagnosticsV1 and are unchanged.

## 12. Preview Provenance

When a preview is validated and accepted first:

- `preview_seeded = true`
- `preview_child_index = 0`
- `preview_fingerprint_digest` equals accepted digest index 0

Otherwise all preview-specific nullable fields remain `None`.

## 13. Policy Provenance

Diagnostics explicitly record:

```text
exact_main_visual_balanced
```

No frontend generation-mode or AI Draft identity is used.

## 14. Fingerprint Digest Bridge

All accepted digests and the preview digest use the existing FP-001A builder:

```text
_MainVisualFingerprint
→ main_visual_planning canonical JSON
→ SHA-256
```

No new fingerprint type or digest algorithm was introduced.

## 15. Builder Source of Truth

`_build_coverage_diagnostics_v1()` runs inside the balanced planner after:

- Preview processing
- Greedy selection termination
- Final authoritative coverage updates
- Rejection counters
- Termination determination

It does not reconstruct data from workers, FFmpeg, render outcomes, DB re-query, or a second resolver call.

## 16. Coordinator Validation

Before trusting diagnostics, the coordinator verifies:

- Accepted counts match plans and fingerprints
- Examined count, candidate-space size, and termination reason match
- Accepted digest order matches coordinator-recomputed authoritative fingerprints

A mismatch prevents child execution and uses the existing authoritative planning failure path.

## 17. BalancedCoverageSummary Event

Exactly one batch event is emitted:

```text
[BalancedCoverageSummary]
```

Envelope:

```json
{
  "event": "BalancedCoverageSummary",
  "task_id": "...",
  "coverage_diagnostics": { "...": "V1 payload" }
}
```

It uses the existing DopaMatrix Loguru sink.

## 18. Log Failure Semantics

Loguru emission is best-effort and guarded.

A logger exception:

- Does not fail planning
- Does not fail children
- Does not add product warning codes
- Does not recurse through the failing logger

## 19. Planning Summary Persistence

Balanced history adds:

```text
planning_summary.coverage_diagnostics
```

Existing planning summary fields remain unchanged.

Exact and legacy histories omit the coverage field rather than storing `null`.

## 20. TaskHistory Persistence

The existing `TaskHistory.prompt_details` Text JSON is used.

No new column, model, table, or migration was introduced.

## 21. Planning vs Render Count Semantics

A controlled test proved:

- Planner accepted: 4
- Render succeeded: 3
- Diagnostics `accepted_count`: 4

Coverage diagnostics describe planning truth, not render outcomes.

## 22. JSON / Payload Bounds

The explicit serializer produces plain JSON-compatible data and passes:

```python
json.dumps(payload, ensure_ascii=False, allow_nan=False)
```

Dynamic Unicode Beat metadata and nullable fields are supported without a custom encoder.

## 23. Privacy / Data Minimization

Payload excludes:

- Paths and filenames
- Prompts
- Raw DSL
- Tags
- Media data
- Unused candidate hashes

A `P=20, B=4` test confirms only selected histogram entries are serialized.

## 24. Exact Policy Preservation

`exact_main_visual`:

- Still routes to the existing exact planner
- Has `coverage_diagnostics = None`
- Emits no `BalancedCoverageSummary`
- Persists no coverage field

## 25. Legacy Preservation

Legacy:

- Does not invoke diagnostics builder
- Emits no coverage summary
- Persists no coverage field
- Retains historical worker-local semantics

## 26. Phase 1 Selection Preservation

The production diff adds counters and the terminal diagnostics builder only.

No changes were made to:

- Mixed-radix decoding
- Stratified ordinals
- Candidate window membership
- Coverage score
- Heap ordering
- Proposal selection
- Preview placement
- Fingerprint acceptance
- Search-budget termination
- Accepted-plan order

`PHASE1_BALANCED_SELECTION_UNCHANGED`

## 27. Tests Added

Coverage mapping:

- COV1: golden `4×2×1×2×2`, digest bridge
- COV2: fixed axis
- COV3: `P=4, B=4`
- COV4: `P=4, B=6`
- COV5: `B<P`
- COV6: injected search budget
- COV7: materialization mismatch
- COV8: duplicate authoritative fingerprint
- COV9: preview provenance
- COV10: policy provenance and exact isolation
- COV11: TaskHistory nested persistence
- COV14: dynamic 3/5/7 Beats

Additional coverage:

- Target-not-met builder case
- `P=0`
- Invalid-plan counter
- No-preview invariants
- Accepted digest ordering
- Coordinator digest mismatch
- Planning versus render count
- Exactly-one summary and call order
- Logger failure
- Unicode/JSON serialization
- Payload bounds/privacy
- Exact/legacy absence

Focused diagnostics: **14 tests passed**.

## 28. VAR Regression

```text
Ran 50 tests
OK
```

## 29. INV Regression

```text
Ran 85 tests
OK
```

## 30. FP Regression

```text
Ran 42 tests
OK
```

## 31. Production Diff Audit

Changed hunk classifications:

- A. Diagnostics contract types: present
- B. Nullable planning-result field: present
- C. Additive planner counters: present
- D. Diagnostics builder: present
- E. Serializer: present
- F. Coordinator authoritative validation: present
- G. Loguru summary: present
- H. Planning summary persistence: present
- I. Selection algorithm change: **NONE**
- J. Fingerprint semantic change: **NONE**
- K. Live WS/API exposure: **NONE**
- L. Unrelated production change: **NONE**

## 32. DB Migration Audit

No changes to models, schemas, database initialization, or migrations.

`PHASE2B_NO_DB_MIGRATION`

## 33. Frontend / Live API Audit

- `web_ui/`: unchanged
- Terminal WebSocket payload: unchanged
- HTTP schemas: unchanged
- No `coverageDiagnostics` live field

`PHASE2B_FRONTEND_UNCHANGED`

## 34. Review Findings

NONE

Controlled mismatch/rejection stack traces and the existing `datetime.utcnow()` deprecation warning appeared during tests; they are expected test evidence and not regressions.

## 35. Final Git Status

```text
 M src/api/routes_dsl.py
 M tests/test_var001_policy_integration.py
?? tests/test_var001_coverage_diagnostics.py
```

- `py_compile`: PASS
- `git diff --check`: PASS
- No commit or push performed
- Backend/frontend not started
- No real media run performed

VAR001_PHASE2B_OBSERVABILITY_PASS