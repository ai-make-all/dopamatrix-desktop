# VAR-001
# Phase 2A
# Coverage Diagnostics Contract Architecture Audit Report

## 1. Baseline

- Branch: `feature/var-001-variation-policy`
- HEAD: `f3a651aa298edccc2c3f93df616ae687a15dfab7`
- HEAD: `docs(var-001): record balanced real-media acceptance`
- Tag: `var-001-balanced-coverage-v1`
- Initial worktree: clean
- Phase 1A, 1B, 1C-A and 1C-B history present
- No backend or frontend service was started

## 2. Current Planning Result Contract

Current [_VariantPlanningResult](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:212):

```python
@dataclass(frozen=True)
class _VariantPlanningResult:
    plans: tuple[CompilationPlan, ...]
    fingerprints: tuple[_MainVisualFingerprint, ...]
    examined_combinations: int
    candidate_space_size: int
    termination_reason: str
    warning_codes: tuple[str, ...]
```

| Diagnostic fact | Classification | Current evidence |
|---|---|---|
| Accepted plans | ALREADY_AVAILABLE | `plans` |
| Accepted fingerprints | ALREADY_AVAILABLE | `fingerprints` |
| Examined count | ALREADY_AVAILABLE | `examined_combinations` |
| Full Cartesian size | ALREADY_AVAILABLE | `candidate_space_size` |
| Termination reason | ALREADY_AVAILABLE | Existing enum-like constants |
| Warning codes | ALREADY_AVAILABLE | `warning_codes` |
| Requested count | DERIVABLE_DURING_PLANNING | Planner argument |
| Planned/accepted count | DERIVABLE_DURING_PLANNING | `len(plans)` |
| Selected hashes | ALREADY_AVAILABLE | Fingerprint components |
| Selected asset IDs | ALREADY_AVAILABLE | Accepted plans |
| Per-Beat pool size | LOST_AFTER_PLANNING | Pools are local variables |
| Zero-count eligible candidates | LOST_AFTER_PLANNING | Local `coverage` contains them |
| Final per-Beat histogram | LOST_AFTER_PLANNING | Local `coverage` |
| Preview seeded state | LOST_AFTER_PLANNING | Local `preview_selections` |
| Search budget | LOST_AFTER_PLANNING | Function argument, not returned |
| Planning policy | LOST_AFTER_PLANNING | Coordinator argument, not persisted |
| Materialization rejection count | NOT CURRENTLY AVAILABLE | Branch exists; no counter |
| Invalid-plan rejection count | NOT CURRENTLY AVAILABLE | Branch exists; no counter |
| Duplicate-fingerprint rejection count | NOT CURRENTLY AVAILABLE | Branch exists; no counter |

## 3. Balanced Planner Available State

At balanced-planning completion in [_plan_exact_main_visual_balanced_variants](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:824):

| Field | Type | Owner | Lifetime | Returned? |
|---|---|---|---|---|
| `candidate_pools` | `list[list[MainVisualCandidate]]` | Planner | Function-local | No |
| `candidate_space_size` | `int` | Planner | Function-local | Yes |
| `coverage` | `list[dict[str, int]]` | Planner | Function-local | No |
| `accepted_plans` | `list[CompilationPlan]` | Planner | Function-local | Tuple copy |
| `accepted_fingerprints` | fingerprint list | Planner | Function-local | Tuple copy |
| `used_fingerprints` | set | Planner | Function-local | No |
| `examined_keys` | selection-key set | Planner | Function-local | Count only |
| `preview_selections` | optional candidate tuple | Planner | Function-local | No |
| `preview_fingerprint` | fingerprint tuple | Planner | Preview branch | No |
| `search_budget` | `int` | Caller/planner | Invocation | No |
| `selection_mismatch_seen` | `bool` | Planner | Function-local | Warning only |
| Invalid-plan count | — | — | Not recorded | No |
| Duplicate rejection count | — | — | Not recorded | No |
| `termination_reason` | `str` | Planner | Function-local | Yes |

The required truth exists before return. Diagnostics do not require resolver re-execution.

## 4. Candidate Pool Evidence

Actual [MainVisualCandidate](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:76):

```python
@dataclass(frozen=True)
class MainVisualCandidate:
    asset_id: int
    file_hash: str
```

Candidate discovery:

- Produces one pool per ordered dynamic Beat.
- Normalizes each `file_hash`.
- Deduplicates each Beat pool by normalized hash.
- Preserves resolver-produced order.
- Does not carry paths, tags or media payloads.

Evidence levels:

| Level | Audit strength | Size/privacy | Assessment |
|---|---|---|---|
| A: `pool_size` | Proves `P`, unused count and coverage math | Minimal | Sufficient for V1 |
| B: size + pool digest | Also identifies the request-time ordered pool cryptographically | Small | Useful later, not required for V1 |
| C: full identities | Identifies every unused candidate | Potentially large and sensitive | Not justified for V1 |

Recommendation: V1 persists Level A plus the selected histogram. It can prove how many candidates were unused, though not their identities.

Full candidate hashes are unnecessary for V1 mathematics.

## 5. Coverage Mathematics

For each Beat:

```text
P = eligible normalized-hash candidate count
B = accepted authoritative plan count
q = floor(B / P)
r = B mod P
```

Ideal distribution:

- `r` candidates receive `q + 1`
- `P - r` candidates receive `q`

Derived fields:

```text
ideal_floor = q
ideal_ceil  = q if r == 0 else q + 1
unique_used = number of selected hashes
unused_count = P - unique_used
```

The selected histogram may contain only used hashes. For coverage calculations, append `unused_count` conceptual zeroes.

Example:

```text
P=4, stored histogram=2/2
full vector=2/2/0/0
max_min_gap=2
```

`max_min_gap <= 1` is equivalent to the ideal floor/ceil distribution only after validating:

- vector length is `P`
- counts are non-negative integers
- counts sum to `B`

The V1 builder should verify those invariants and then use the explicit floor/ceil test.

## 6. Coverage Status Taxonomy

Recommended per-Beat V1 enum:

```text
FIXED_BY_CAPACITY
VARIABLE_BALANCED
VARIABLE_TARGET_NOT_MET
```

Definitions:

- `FIXED_BY_CAPACITY`: `P == 1`. Repetition is required and is not imbalance.
- `VARIABLE_BALANCED`: `P > 1` and every eligible count is `ideal_floor` or `ideal_ceil`, with exactly `r` candidates at the ceiling.
- `VARIABLE_TARGET_NOT_MET`: `P > 1` and the ideal condition is false.

For `P == 0`:

- Per-Beat classification should be `null`.
- Treat it as a planning/capacity failure at task level.
- Do not label it as normal coverage.

Do not use `CONSTRAINED_BY_*` as per-Beat classifications in V1. Current evidence is combination/task-level and cannot prove that one specific rejection caused one specific Beat’s imbalance.

## 7. Rejection / Constraint Evidence

Current loop branches distinguish:

1. `MainVisualSelectionMismatch`
2. Invalid materialized plan via `ValueError`
3. Duplicate authoritative fingerprint
4. Accepted proposal

Phase 2B can add counters locally without restructuring:

```text
proposal_attempted_count
materialization_mismatch_count
invalid_plan_count
duplicate_fingerprint_reject_count
accepted_count
```

Semantics:

- Increment proposal attempts when a non-preview proposal enters materialization.
- Preview is represented separately and remains included in `examined_count`.
- Increment rejection counters only in their existing branches.
- Coverage remains updated only after acceptance.

Counters prove that constraints occurred. They do not, alone, prove exclusive causality for a particular Beat distribution.

## 8. Search Diagnostics

Retain current terminology:

```text
REQUEST_SATISFIED
TRUE_SPACE_EXHAUSTED
PLANNING_SEARCH_LIMIT_REACHED
```

Required V1 fields:

- `search_budget`
- `examined_count`
- `candidate_space_size`
- `termination_reason`

Interpretation:

- `REQUEST_SATISFIED`: accepted count reached requested count.
- `TRUE_SPACE_EXHAUSTED`: all global selection keys were examined.
- `PLANNING_SEARCH_LIMIT_REACHED`: global space remained when bounded search stopped.

A separate `search_limit_reached` boolean would duplicate `termination_reason` and is unnecessary.

## 9. Preview Provenance

The planner can accurately capture:

```text
preview_seeded
preview_child_index
preview_fingerprint_digest
```

Truth is available immediately after `_preview_selection()` succeeds.

Contract:

- `preview_seeded = true` only when the preview was validated, accepted and inserted first.
- `preview_child_index = 0` when seeded; otherwise `null`.
- Digest is produced using the existing FP-001A planning-fingerprint builder.
- No full preview plan needs persistence.

## 10. Policy Provenance

Current flow:

```text
RenderDSLRequest.variant_planning_policy
→ render_batch_worker(... variant_planning_policy=...)
→ exact or balanced planner routing
```

Policy is not currently placed in TaskHistory or terminal payload.

Recommendation:

```text
planning_summary.coverage_diagnostics.variant_planning_policy
```

should be the single persisted source for balanced diagnostics.

Do not duplicate the same value at multiple levels of `planning_summary`.

Phase 2B should activate diagnostics only when:

```text
variant_planning_policy == exact_main_visual_balanced
```

## 11. Planning Summary

Current producer: [_persist_task_history](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1584).

Current shape:

```json
{
  "requested_count": 4,
  "planned_count": 4,
  "succeeded_count": 4,
  "failed_count": 0,
  "warning_codes": []
}
```

Properties:

- Plain JSON-compatible `dict`
- Not a Pydantic model
- Constructed after child completion
- Nested inside `prompt_details`
- Serialized with `json.dumps(..., ensure_ascii=False)`
- Consumed by `QueueView.parseHistoryOutcome()`

Recommended extension:

```json
{
  "requested_count": 4,
  "planned_count": 4,
  "succeeded_count": 4,
  "failed_count": 0,
  "warning_codes": [],
  "coverage_diagnostics": {
    "...": "CoverageDiagnosticsV1"
  }
}
```

## 12. TaskHistory Persistence

[TaskHistory](E:/dopaworkspace/dopamatrix-desktop/src/api/models.py:131) stores:

```python
prompt_details = Column(Text, nullable=True)
```

The whole details object is JSON-encoded into this text column. SQLite has no declared application size limit on this field.

[History serialization](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_history.py:26) returns `prompt_details` unchanged.

Therefore CoverageDiagnosticsV1 can be nested inside existing `planning_summary` without schema or migration changes.

`NO_MIGRATION_PATH_PROVEN`

Limitation: TaskHistory is currently written only when at least one child succeeds. A zero-output planning failure can expose diagnostics through log/live terminal data, but not historical TaskHistory without a separate persistence-policy change.

## 13. Terminal / API Data Flow

Current flow:

```text
_VariantPlanningResult
    ├─ plans/fingerprints → coordinator invariant → _ChildWork → workers
    └─ warning_codes      → coordinator aggregation
                                  │
                                  ├─ child results
                                  │      ↓
                                  ├─ _persist_task_history
                                  │      ↓
                                  ├─ prompt_details JSON text
                                  │      ↓
                                  ├─ GET /history
                                  └─ GET /tasks/today

Coordinator terminal payload
    ↓
WS_UPDATE
    ↓
queueWorker
    ↓
useQueueStore
    ↓
QueueView
```

Current terminal payload includes counts and warnings but not `planning_summary` or coverage diagnostics.

Historical APIs already expose `prompt_details`; no new DB read endpoint is required for historical coverage.

## 14. Frontend Task Data Flow

Historical completed tasks:

- [QueueView.parseRecordDetails](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue:34) parses `prompt_details`.
- [parseHistoryOutcome](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue:50) maps `planning_summary` to the queue task shape.
- [fetchTodayTasks](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue:101) hydrates `/tasks/today`.

Live tasks:

- [WsUpdatePayload](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/workers/queueWorker.ts:70)
- [_handleWsUpdate](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/workers/queueWorker.ts:210)
- Pinia queue store
- QueueView completed card

Other historical consumers:

- `/history` → HistoryView
- `/history` → ApprovalView

Current QueueTask has no coverage field.

## 15. Live / Historical Compatibility

Current live and historical task shapes differ:

- Live uses camelCase terminal fields.
- Historical data embeds snake_case planning fields inside JSON text.

A normalization layer already exists for outcome counts.

Phase 2C should extend that pattern:

```text
live payload.coverageDiagnostics
historical planning_summary.coverage_diagnostics
                    ↓
normalizeCoverageDiagnostics()
                    ↓
QueueTask.coverageDiagnostics
                    ↓
one Coverage UX
```

Existing tasks without diagnostics must produce:

```text
coverageDiagnostics = undefined
```

The UX should omit the panel or show “Diagnostics unavailable”; absence must never imply failure.

## 16. CoverageDiagnosticsV1 Proposed Contract

```json
{
  "type": "balanced_axis_coverage",
  "version": 1,
  "variant_planning_policy": "exact_main_visual_balanced",

  "requested_count": 4,
  "accepted_count": 4,
  "candidate_space_size": 32,

  "search_budget": 4096,
  "examined_count": 4,
  "proposal_attempted_count": 3,
  "termination_reason": "REQUEST_SATISFIED",

  "preview_seeded": true,
  "preview_child_index": 0,
  "preview_fingerprint_digest": "64-lowercase-hex-or-null",

  "accepted_fingerprint_digests": [
    "ordered-child-0-digest",
    "ordered-child-1-digest"
  ],

  "rejection_counts": {
    "materialization_mismatch": 0,
    "invalid_plan": 0,
    "duplicate_fingerprint": 0
  },

  "beats": [
    {
      "beat_index": 0,
      "beat_identity": "hook",
      "role": "hook",

      "pool_size": 4,
      "selected_count": 4,
      "unique_used": 4,
      "unused_count": 0,

      "selected_histogram": [
        {
          "normalized_file_hash": "md5-value",
          "asset_id": 12,
          "count": 1
        }
      ],

      "ideal_floor": 1,
      "ideal_ceil": 1,
      "max_min_gap": 0,
      "classification": "VARIABLE_BALANCED"
    }
  ]
}
```

`accepted_fingerprint_digests` provides a bounded bridge to the exact VariantFingerprint events and proves which authoritative accepted batch the aggregate describes.

## 17. Pool Digest Decision

V1 does not require `pool_digest`.

Reason:

- `pool_size + selected_histogram` is mathematically sufficient.
- The contract only promises the count of unused candidates, not their identities.
- No current UX or persistence lookup consumes a pool digest.

If added later, recommended design:

```json
{
  "type": "main_visual_candidate_pool",
  "version": 1,
  "source_hash_algorithm": "md5",
  "beat_index": 0,
  "ordered_normalized_file_hashes": ["...", "..."]
}
```

Serialize deterministic UTF-8 canonical JSON and hash with SHA-256.

Ordering should be resolver order, not sorted hashes, because pool order affects Cartesian ordinals and deterministic tie-breaking.

Digest equality would mean the same ordered normalized candidate pool at that Beat index under that digest version. It would not mean semantic or rendered-video equality.

## 18. Selected Histogram Representation

Recommended representation: option B.

```json
[
  {
    "normalized_file_hash": "...",
    "asset_id": 12,
    "count": 2
  }
]
```

Advantages:

- Stable JSON structure
- Explicit ordering
- Easy frontend iteration
- Supports presentation `asset_id`
- Avoids JSON object-key semantics
- Naturally bounded by unique selected candidates

Order entries by their request-time candidate-pool order.

Counts-only representation loses selected identity. Hash-keyed objects have weaker ordering and evolution semantics.

## 19. Asset / Beat Metadata

`normalized_file_hash` is the selected-source identity.

`asset_id`:

- Useful for DAM drill-down.
- Presentation metadata only.
- Must not affect fingerprint or coverage equality.
- Should be omitted for an impossible unresolved mapping rather than fabricated.

Beat fields:

- `beat_index`: authoritative within-task axis position.
- `beat_identity`: current submitted Beat string.
- `role`: UX presentation metadata.

Current Beat identity can be arbitrary/custom and mutable. The diagnostics contract must not describe it as a durable cross-version Beat definition ID.

## 20. Payload Bounds

V1 avoids full candidate lists.

For each Beat:

- Histogram entries ≤ accepted count
- `accepted_count ≤ batch_size ≤ 20`
- Each entry contains one MD5 string and small numeric fields

Expected size:

```text
O(Beat count × min(pool_size, accepted_count))
```

No:

- paths
- tags
- prompts
- full DSL
- media payloads
- unused candidate identities

Absolute Beat count and Beat-string length are not bounded by current Pydantic schema. This is an architecture risk for unusual payloads, but V1 remains proportional to accepted components rather than full candidate pools.

Persistent diagnostics should not be truncated. Log and persistence must derive from the same payload.

## 21. Logging Architecture

Phase 2B should emit one batch-level Loguru event:

```text
[BalancedCoverageSummary]
```

Emission point:

1. Balanced planner returns.
2. Coordinator recomputes and validates plan/fingerprint pairing.
3. Coverage diagnostics payload is validated.
4. Emit exactly one batch event.
5. Allocate/bind children and start workers.

This occurs before worker rendering and describes the precise authoritative result handed to `_ChildWork`.

Use the existing DopaMatrix Loguru sink under an explicit coverage/observability alias. Do not migrate all `routes_dsl` stdlib logging.

Event envelope may add `task_id`, while `coverage_diagnostics` remains the same payload object used for persistence.

## 22. Observability Failure Semantics

| Failure | Recommended handling |
|---|---|
| Diagnostics detects impossible planner invariants | Hard authoritative-planning failure |
| Canonical JSON contract contains non-JSON-safe data | Hard contract failure before workers |
| Loguru emission fails | Non-blocking engineering warning |
| TaskHistory persistence fails | Existing non-blocking `HISTORY_PERSIST_FAILED` behavior |
| Frontend cannot render diagnostics | Omit diagnostics panel; render result remains valid |

Examples of hard invariant failures:

- Histogram sum differs from accepted count.
- Selected hash is outside its captured pool.
- Beat count differs from accepted fingerprints.
- Accepted fingerprint digests do not match accepted fingerprints.

The log sink itself must never become a render requirement.

## 23. Diagnostics Source of Truth

Build diagnostics inside the balanced planner after:

- candidate pools are known
- preview handling has completed
- greedy selection has terminated
- all accepted fingerprints are known
- final coverage counters are complete
- termination reason is known

Build before returning `_VariantPlanningResult`.

Do not reconstruct coverage from:

- FFmpeg
- rendered output
- TaskHistory
- worker plans
- a second resolver run

This timing is feasible without changing selection behavior.

## 24. Backward Compatibility

Recommended `_VariantPlanningResult` extension:

```python
coverage_diagnostics: Optional[_CoverageDiagnosticsV1] = None
```

It must be the final field with a default.

Behavior:

- Balanced planner: populated.
- Old exact planner: `None`.
- Legacy: continues bypassing `_VariantPlanningResult`.
- Existing tuple equality, fingerprints, preview, capacity, window and scoring remain unchanged.

Recommended policy choice: generic nullable result contract, activated only for balanced planning.

## 25. UX Information Architecture

Collapsed task-card summary:

```text
4 variable Beats balanced · 1 fixed by capacity
```

Expanded table:

| Beat | Eligible | Used | Distribution | Status |
|---|---:|---:|---|---|
| Hook | 4 | 4 | 1 / 1 / 1 / 1 | Balanced |
| Context | 2 | 2 | 2 / 2 | Balanced |
| Build | 1 | 1 | 4 | Fixed by capacity |

Do not introduce a synthetic score such as `0.87`.

Primary UX metrics:

- Eligible
- Used
- Unused
- Distribution
- Status
- Optional task-level constraint evidence

Suggested reason semantics:

- Fixed: “Only 1 eligible main-visual candidate was available for this Beat.”
- Balanced: “4 outputs were distributed across 4 eligible candidates as evenly as possible.”
- Target not met: state the observed distribution.
- Search limit: show as task-level context, not an invented per-Beat cause.

## 26. UI-RF-01 Boundary

Keep separate:

```text
authoring_mode
variant_planning_policy
coverage_status
```

Coverage UX must not infer AI Draft/manual mode.

`UI-RF-01 — GENERATION_MODE_BADGE_STALE_OR_INCORRECT` remains out of scope.

## 27. Historical Novelty Boundary

CoverageDiagnosticsV1 must remain independent of:

- historical fingerprint ledger
- past-task novelty
- perceptual fingerprints
- semantic similarity

Layering remains:

```text
Batch exact uniqueness
→ Balanced Coverage
→ Coverage Diagnostics
→ Historical Novelty
```

Pool size and coverage status describe one request-time candidate space only.

## 28. Privacy / Data Minimization

Persist:

- counts
- normalized hashes for selected candidates
- selected asset IDs
- Beat index/current Beat text
- policy and bounded planning facts

Do not persist:

- absolute file paths
- filenames
- raw tags
- prompts
- full DSL
- raw media
- unused candidate identities
- source contents

Hash and asset ID remain tenant-scoped diagnostic metadata.

## 29. Test Plan

- COV1: `4×2×1×2×2`, batch 4
- COV2: `P=1` → `FIXED_BY_CAPACITY`
- COV3: `P=4, B=4` → `1/1/1/1`
- COV4: `P=4, B=6` → `2/2/1/1`
- COV5: `P=4, B=2` → `1/1/0/0`
- COV6: search-limit fields and termination
- COV7: materialization counter
- COV8: duplicate-fingerprint counter
- COV9: preview seeded/index/digest
- COV10: balanced policy provenance
- COV11: TaskHistory nested persistence
- COV12: terminal/live exposure
- COV13: historical task without diagnostics
- COV14: dynamic 3/5/7 Beats
- COV15: strict JSON serializability
- COV16: old exact returns diagnostics `None` and is unchanged
- COV17: legacy remains unchanged

Also test accepted fingerprint digests against FP-001A and VariantFingerprint construction.

## 30. Performance Constraints

Diagnostics must not:

- rerun candidate discovery
- query DB after planning
- materialize extra plans
- inspect media files
- scan historical tasks
- expand the search window

Expected complexity:

```text
Build pool sizes: O(number of Beats)
Build histograms: O(Beats × accepted plans)
Serialize: O(Beats × unique selected candidates)
```

Memory is bounded by accepted components rather than full pool contents.

## 31. Migration Decision

TaskHistory already stores extensible JSON text in `prompt_details`.

No model, column, schema evolution or SQL migration is required for nested coverage diagnostics.

`NO_MIGRATION_PATH_PROVEN`

## 32. Proposed Phase 2B Scope

| File | Change |
|---|---|
| `src/api/routes_dsl.py` | Private frozen diagnostics types/helpers, additive counters, nullable planning-result field, batch Loguru event, planning-summary persistence |
| `tests/test_var001_coverage_diagnostics.py` | Focused COV contract, persistence and compatibility tests |

Not required:

- `models.py`
- `schemas.py`
- frontend
- DB migration
- fingerprint changes
- planner selection changes

## 33. Proposed Phase 2C Scope

Backend/live exposure:

- `src/api/routes_dsl.py`: include the same diagnostics payload in terminal WS data.

Frontend normalization, without presentation styling:

- `web_ui/src/workers/queueWorker.ts`: type and forward `coverageDiagnostics`.
- `web_ui/src/stores/useQueueStore.ts`: preserve the field.
- `web_ui/src/views/QueueView.vue` or a small utility: normalize historical `planning_summary.coverage_diagnostics` and live `coverageDiagnostics`.

`routes_history.py` need not change because it already exposes `prompt_details`.

## 34. Proposed Phase 2D Scope

Likely frontend files:

| File | Role |
|---|---|
| `web_ui/src/views/QueueView.vue` | Result-card summary and expansion entry point |
| `web_ui/src/components/CoverageDiagnosticsPanel.vue` | Coverage table/details |
| Optional shared diagnostics utility/type | Validation and reason-text mapping |

No backend selection behavior belongs in Phase 2D.

## 35. Architecture Risks

| Risk | Impact | Mitigation |
|---|---|---|
| `_VariantPlanningResult` test constructors | Adding a required field breaks tests | Nullable final field with default |
| Rejection presence mistaken for causality | Misleading UX | Keep counters/task termination separate from per-Beat status |
| TaskHistory only persists successful tasks | Failed planning lacks historical diagnostics | Log/live terminal only; defer failed-task persistence |
| Mutable Beat identity | Weak cross-version identity | Treat as current-task presentation metadata |
| Live/history shape differences | Duplicate UI implementations | One normalization function |
| stdlib logger suppression | Missing runtime event | Use project Loguru sink locally |
| No absolute Beat/string bound | Large diagnostic event possible | No full pools; keep complexity proportional and test payload sizes |
| Full candidate list omitted | Cannot name unused assets | V1 promises unused count only |
| Pool order can vary | Cross-run pool comparison difficult | Optional ordered pool digest later |
| Ad hoc JSON Text storage | No DB-level validation | Strict builder and JSON serialization tests |

None is an architecture blocker for Phase 2B.

## 36. ADR

### Problem

Phase 1 proved selected balanced distributions but lost request-time candidate-pool and coverage evidence after planning.

### Phase 1 evidence gap

TaskHistory could not prove pool size, zero-count candidates, ideal distribution, capacity-fixed repetition, policy or preview lineage.

### Source of truth

The completed balanced planner state before `_VariantPlanningResult` return.

### Ownership

A private versioned frozen `CoverageDiagnosticsV1` contract adjacent to the planner result in `routes_dsl.py`.

### Candidate evidence

Persist pool size plus selected histogram. Do not persist full pools in V1.

### Coverage math

Use accepted count, full eligible vector including conceptual zeroes, and exact floor/ceil validation.

### Status taxonomy

Per Beat:

```text
FIXED_BY_CAPACITY
VARIABLE_BALANCED
VARIABLE_TARGET_NOT_MET
```

Keep constraint evidence task-level.

### Policy provenance

Persist `exact_main_visual_balanced` inside the diagnostics contract.

### Preview provenance

Persist seeded flag, child index 0 and existing planning-fingerprint digest.

### Persistence

Nest one diagnostics payload inside existing `planning_summary`.

### Logging

Emit one `[BalancedCoverageSummary]` Loguru event after coordinator validation and before workers.

### API strategy

Historical exposure already exists through `prompt_details`; Phase 2C adds live terminal forwarding and normalization.

### UX strategy

One live/historical normalized payload, concise summary plus expandable Beat table.

### Backward compatibility

Balanced populated; old exact nullable; legacy absent.

### No-migration decision

Existing TaskHistory JSON text is sufficient.

### Historical Novelty boundary

Coverage is request-local and does not carry historical novelty meaning.

## 37. Final Recommendations

1. Build CoverageDiagnosticsV1 at the end of the balanced planner, before return.
2. Add nullable `coverage_diagnostics` to `_VariantPlanningResult`.
3. Persist per-Beat `pool_size` plus selected histogram.
4. Do not persist full candidate hashes.
5. Do not add `pool_digest` in V1; reserve the versioned ordered design for later.
6. Yes, existing `planning_summary` can store it without migration.
7. Activate diagnostics only for `exact_main_visual_balanced`.
8. Keep `exact_main_visual` behavior unchanged and diagnostics-null.
9. Keep legacy diagnostics absent/null.
10. Use `FIXED_BY_CAPACITY`, `VARIABLE_BALANCED`, `VARIABLE_TARGET_NOT_MET`.
11. Include preview provenance.
12. Persist `variant_planning_policy` inside the diagnostics contract.
13. Emit one batch-level Loguru event.
14. Yes, the same nested payload can support live and historical UX through normalization.
15. Phase 2B requires no frontend changes.
16. Phase 2B requires no DB changes.

## 38. Final Classification

No stop condition was found:

- Candidate pools remain available at a safe construction point.
- Coverage classification requires no resolver rerun.
- Planning summary accepts JSON-compatible extension.
- Live/historical shapes can share one normalized contract.
- Fingerprint semantics do not need modification.

The final classification value appears at the end of this report.

## 39. Final Git Status

Final safety commands:

```text
git status --short
git diff --stat
```

Both were empty.

- No production modifications
- No test modifications
- No report file created
- No service started
- No commit or push

`PHASE_2B_READY`