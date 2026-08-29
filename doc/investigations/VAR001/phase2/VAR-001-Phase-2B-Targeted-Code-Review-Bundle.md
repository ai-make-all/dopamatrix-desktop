# VAR-001 Phase 2B Targeted Code Review Bundle

Strict read-only review completed. No files were created or modified, and no tests or runtime processes were started.

## A. Git Status

```text
 M src/api/routes_dsl.py
 M tests/test_var001_policy_integration.py
?? tests/test_var001_coverage_diagnostics.py
```

```text
src/api/routes_dsl.py                   | 439 +++++++++++++++++++++++++++++++-
tests/test_var001_policy_integration.py |  21 +-
2 files changed, 434 insertions(+), 26 deletions(-)
```

The untracked diagnostics test is not included in `git diff --stat`.

## B. Production Diff

Logical output name:

```text
VAR-001-Phase2B-routes_dsl-production-diff.txt
```

The complete production diff was emitted verbatim during this review. It contains these and only these production hunks:

```diff
diff --git a/src/api/routes_dsl.py b/src/api/routes_dsl.py
index a8d5923..a92941a 100644
--- a/src/api/routes_dsl.py
+++ b/src/api/routes_dsl.py
@@ -207,6 +207,64 @@ _PLANNING_TRUE_SPACE_EXHAUSTED = "TRUE_SPACE_EXHAUSTED"
 _PLANNING_SEARCH_LIMIT_REACHED = "PLANNING_SEARCH_LIMIT_REACHED"
 _EXACT_MAIN_VISUAL_SEARCH_BUDGET = 4096
 
+_COVERAGE_DIAGNOSTICS_TYPE = "balanced_axis_coverage"
+_COVERAGE_DIAGNOSTICS_VERSION = 1
+_BALANCED_VARIANT_PLANNING_POLICY = "exact_main_visual_balanced"
+_BALANCED_COVERAGE_SUMMARY_EVENT = "BalancedCoverageSummary"
+_COVERAGE_FIXED_BY_CAPACITY = "FIXED_BY_CAPACITY"
+_COVERAGE_VARIABLE_BALANCED = "VARIABLE_BALANCED"
+_COVERAGE_VARIABLE_TARGET_NOT_MET = "VARIABLE_TARGET_NOT_MET"
+
+
+@dataclass(frozen=True)
+class _CoverageHistogramEntryV1:
+    normalized_file_hash: str
+    asset_id: int
+    count: int
+
+
+@dataclass(frozen=True)
+class _CoverageBeatDiagnosticsV1:
+    beat_index: int
+    beat_identity: str
+    role: str
+    pool_size: int
+    selected_histogram: tuple[_CoverageHistogramEntryV1, ...]
+    selected_count: int
+    unique_used: int
+    unused_count: int
+    ideal_floor: Optional[int]
+    ideal_ceil: Optional[int]
+    max_min_gap: Optional[int]
+    classification: Optional[str]
+
+
+@dataclass(frozen=True)
+class _CoverageRejectionCountsV1:
+    materialization_mismatch_count: int
+    invalid_plan_count: int
+    duplicate_fingerprint_reject_count: int
+
+
+@dataclass(frozen=True)
+class _CoverageDiagnosticsV1:
+    diagnostics_type: str
+    version: int
+    variant_planning_policy: str
+    requested_count: int
+    accepted_count: int
+    candidate_space_size: int
+    search_budget: int
+    examined_count: int
+    proposal_attempted_count: int
+    termination_reason: str
+    preview_seeded: bool
+    preview_child_index: Optional[int]
+    preview_fingerprint_digest: Optional[str]
+    accepted_fingerprint_digests: tuple[str, ...]
+    rejection_counts: _CoverageRejectionCountsV1
+    beats: tuple[_CoverageBeatDiagnosticsV1, ...]
+
 
 @dataclass(frozen=True)
 class _VariantPlanningResult:
@@ -216,6 +274,7 @@ class _VariantPlanningResult:
     candidate_space_size: int
     termination_reason: str
     warning_codes: tuple[str, ...]
+    coverage_diagnostics: Optional[_CoverageDiagnosticsV1] = None
```

Serializer and builder:

```python
def _coverage_diagnostics_v1_payload(
    diagnostics: _CoverageDiagnosticsV1,
) -> dict[str, Any]:
    """Serialize CoverageDiagnosticsV1 without leaking internal representations."""
    return {
        "type": diagnostics.diagnostics_type,
        "version": diagnostics.version,
        "variant_planning_policy": diagnostics.variant_planning_policy,
        "requested_count": diagnostics.requested_count,
        "accepted_count": diagnostics.accepted_count,
        "candidate_space_size": diagnostics.candidate_space_size,
        "search_budget": diagnostics.search_budget,
        "examined_count": diagnostics.examined_count,
        "proposal_attempted_count": diagnostics.proposal_attempted_count,
        "termination_reason": diagnostics.termination_reason,
        "preview_seeded": diagnostics.preview_seeded,
        "preview_child_index": diagnostics.preview_child_index,
        "preview_fingerprint_digest": diagnostics.preview_fingerprint_digest,
        "accepted_fingerprint_digests": list(
            diagnostics.accepted_fingerprint_digests
        ),
        "rejection_counts": {
            "materialization_mismatch_count": (
                diagnostics.rejection_counts.materialization_mismatch_count
            ),
            "invalid_plan_count": diagnostics.rejection_counts.invalid_plan_count,
            "duplicate_fingerprint_reject_count": (
                diagnostics.rejection_counts.duplicate_fingerprint_reject_count
            ),
        },
        "beats": [
            {
                "beat_index": beat.beat_index,
                "beat_identity": beat.beat_identity,
                "role": beat.role,
                "pool_size": beat.pool_size,
                "selected_histogram": [
                    {
                        "normalized_file_hash": entry.normalized_file_hash,
                        "asset_id": entry.asset_id,
                        "count": entry.count,
                    }
                    for entry in beat.selected_histogram
                ],
                "selected_count": beat.selected_count,
                "unique_used": beat.unique_used,
                "unused_count": beat.unused_count,
                "ideal_floor": beat.ideal_floor,
                "ideal_ceil": beat.ideal_ceil,
                "max_min_gap": beat.max_min_gap,
                "classification": beat.classification,
            }
            for beat in diagnostics.beats
        ],
    }


def _build_coverage_diagnostics_v1(
    dsl_payload: StoryDSLPayload,
    candidate_pools: Sequence[Sequence[MainVisualCandidate]],
    coverage: Sequence[dict[str, int]],
    accepted_fingerprints: Sequence[_MainVisualFingerprint],
    *,
    requested_count: int,
    candidate_space_size: int,
    search_budget: int,
    examined_count: int,
    proposal_attempted_count: int,
    termination_reason: str,
    preview_seeded: bool,
    materialization_mismatch_count: int,
    invalid_plan_count: int,
    duplicate_fingerprint_reject_count: int,
) -> _CoverageDiagnosticsV1:
    """Freeze authoritative completed balanced-planner coverage as V1 diagnostics."""
    beat_count = len(dsl_payload.timeline)
    if len(candidate_pools) != beat_count or len(coverage) != beat_count:
        raise ValueError("COVERAGE_DIAGNOSTICS_BEAT_COUNT_MISMATCH")
    if any(
        value < 0
        for value in (
            requested_count,
            candidate_space_size,
            search_budget,
            examined_count,
            proposal_attempted_count,
            materialization_mismatch_count,
            invalid_plan_count,
            duplicate_fingerprint_reject_count,
        )
    ):
        raise ValueError("COVERAGE_DIAGNOSTICS_NEGATIVE_COUNTER")

    expected_space_size = (
        prod(len(pool) for pool in candidate_pools)
        if candidate_pools and all(candidate_pools)
        else 0
    )
    if candidate_space_size != expected_space_size:
        raise ValueError("COVERAGE_DIAGNOSTICS_CANDIDATE_SPACE_MISMATCH")

    accepted_count = len(accepted_fingerprints)
    preview_count = 1 if preview_seeded else 0
    if preview_count > accepted_count:
        raise ValueError("COVERAGE_DIAGNOSTICS_PREVIEW_STATE_INVALID")
    if examined_count != proposal_attempted_count + preview_count:
        raise ValueError("COVERAGE_DIAGNOSTICS_EXAMINED_PARTITION_INVALID")
    non_preview_accepted_count = accepted_count - preview_count
    if proposal_attempted_count != (
        non_preview_accepted_count
        + materialization_mismatch_count
        + invalid_plan_count
        + duplicate_fingerprint_reject_count
    ):
        raise ValueError("COVERAGE_DIAGNOSTICS_PROPOSAL_PARTITION_INVALID")

    normalized_pools: list[tuple[tuple[str, MainVisualCandidate], ...]] = []
    for beat_index, pool in enumerate(candidate_pools):
        normalized_pool: list[tuple[str, MainVisualCandidate]] = []
        seen_hashes: set[str] = set()
        for candidate in pool:
            normalized_hash = normalize_file_hash(candidate.file_hash)
            if not normalized_hash:
                raise ValueError(
                    "COVERAGE_DIAGNOSTICS_CANDIDATE_IDENTITY_INVALID: "
                    f"Beat {beat_index}"
                )
            if normalized_hash in seen_hashes:
                continue
            seen_hashes.add(normalized_hash)
            normalized_pool.append((normalized_hash, candidate))
        normalized_pools.append(tuple(normalized_pool))

    authoritative_counts = [
        {normalized_hash: 0 for normalized_hash, _candidate in pool}
        for pool in normalized_pools
    ]
    for fingerprint in accepted_fingerprints:
        if len(fingerprint) != beat_count:
            raise ValueError("COVERAGE_DIAGNOSTICS_FINGERPRINT_BEAT_COUNT_MISMATCH")
        for expected_index, component in enumerate(fingerprint):
            beat_index, beat_identity, layer_index, normalized_file_hash = component
            expected_identity = str(dsl_payload.timeline[expected_index].beat).strip()
            if (
                beat_index != expected_index
                or beat_identity != expected_identity
                or layer_index != 0
            ):
                raise ValueError("COVERAGE_DIAGNOSTICS_FINGERPRINT_ORDER_MISMATCH")
            if normalized_file_hash not in authoritative_counts[beat_index]:
                raise ValueError("COVERAGE_DIAGNOSTICS_SELECTED_HASH_OUTSIDE_POOL")
            authoritative_counts[beat_index][normalized_file_hash] += 1

    beat_diagnostics: list[_CoverageBeatDiagnosticsV1] = []
    for beat_index, (node, normalized_pool, axis_coverage) in enumerate(
        zip(dsl_payload.timeline, normalized_pools, coverage)
    ):
        pool_hashes = tuple(normalized_hash for normalized_hash, _ in normalized_pool)
        if tuple(axis_coverage) != pool_hashes:
            raise ValueError("COVERAGE_DIAGNOSTICS_COVERAGE_POOL_MISMATCH")
        if any(type(count) is not int or count < 0 for count in axis_coverage.values()):
            raise ValueError("COVERAGE_DIAGNOSTICS_COVERAGE_COUNT_INVALID")
        if axis_coverage != authoritative_counts[beat_index]:
            raise ValueError("COVERAGE_DIAGNOSTICS_COVERAGE_AUTHORITY_MISMATCH")

        full_counts = [axis_coverage[normalized_hash] for normalized_hash in pool_hashes]
        pool_size = len(normalized_pool)
        selected_count = sum(full_counts)
        if pool_size and selected_count != accepted_count:
            raise ValueError("COVERAGE_DIAGNOSTICS_SELECTED_COUNT_MISMATCH")
        if not pool_size and selected_count != 0:
            raise ValueError("COVERAGE_DIAGNOSTICS_EMPTY_POOL_HAS_SELECTIONS")

        selected_histogram = tuple(
            _CoverageHistogramEntryV1(
                normalized_file_hash=normalized_hash,
                asset_id=candidate.asset_id,
                count=axis_coverage[normalized_hash],
            )
            for normalized_hash, candidate in normalized_pool
            if axis_coverage[normalized_hash] > 0
        )
        unique_used = len(selected_histogram)
        unused_count = pool_size - unique_used
        if unique_used > pool_size or unused_count < 0:
            raise ValueError("COVERAGE_DIAGNOSTICS_UNIQUE_COUNT_INVALID")

        if pool_size == 0:
            ideal_floor = None
            ideal_ceil = None
            max_min_gap = None
            classification = None
        else:
            ideal_floor, remainder = divmod(accepted_count, pool_size)
            ideal_ceil = ideal_floor if remainder == 0 else ideal_floor + 1
            max_min_gap = max(full_counts) - min(full_counts)
            target_counts = sorted(
                [ideal_ceil] * remainder
                + [ideal_floor] * (pool_size - remainder)
            )
            target_met = (
                len(full_counts) == pool_size
                and all(type(count) is int and count >= 0 for count in full_counts)
                and sum(full_counts) == accepted_count
                and sorted(full_counts) == target_counts
            )
            if pool_size == 1:
                classification = _COVERAGE_FIXED_BY_CAPACITY
            elif target_met:
                classification = _COVERAGE_VARIABLE_BALANCED
            else:
                classification = _COVERAGE_VARIABLE_TARGET_NOT_MET

        beat_diagnostics.append(
            _CoverageBeatDiagnosticsV1(
                beat_index=beat_index,
                beat_identity=str(node.beat),
                role=str(node.role),
                pool_size=pool_size,
                selected_histogram=selected_histogram,
                selected_count=selected_count,
                unique_used=unique_used,
                unused_count=unused_count,
                ideal_floor=ideal_floor,
                ideal_ceil=ideal_ceil,
                max_min_gap=max_min_gap,
                classification=classification,
            )
        )

    accepted_digests = tuple(
        _main_visual_planning_fingerprint_contract(fingerprint).fingerprint_digest
        for fingerprint in accepted_fingerprints
    )
    if len(accepted_digests) != accepted_count:
        raise ValueError("COVERAGE_DIAGNOSTICS_DIGEST_COUNT_MISMATCH")
    preview_digest = accepted_digests[0] if preview_seeded else None
    diagnostics = _CoverageDiagnosticsV1(
        diagnostics_type=_COVERAGE_DIAGNOSTICS_TYPE,
        version=_COVERAGE_DIAGNOSTICS_VERSION,
        variant_planning_policy=_BALANCED_VARIANT_PLANNING_POLICY,
        requested_count=requested_count,
        accepted_count=accepted_count,
        candidate_space_size=candidate_space_size,
        search_budget=search_budget,
        examined_count=examined_count,
        proposal_attempted_count=proposal_attempted_count,
        termination_reason=termination_reason,
        preview_seeded=preview_seeded,
        preview_child_index=0 if preview_seeded else None,
        preview_fingerprint_digest=preview_digest,
        accepted_fingerprint_digests=accepted_digests,
        rejection_counts=_CoverageRejectionCountsV1(
            materialization_mismatch_count=materialization_mismatch_count,
            invalid_plan_count=invalid_plan_count,
            duplicate_fingerprint_reject_count=duplicate_fingerprint_reject_count,
        ),
        beats=tuple(beat_diagnostics),
    )
    json.dumps(
        _coverage_diagnostics_v1_payload(diagnostics),
        ensure_ascii=False,
        allow_nan=False,
    )
    return diagnostics
```

Remaining production hunks:

```diff
@@ -852,6 +1227,11 @@ def _plan_exact_main_visual_balanced_variants(
     examined_keys: set[tuple[tuple[int, str], ...]] = set()
     selection_mismatch_seen = False
     coverage = _initial_main_visual_coverage(candidate_pools)
+    preview_seeded = False
+    proposal_attempted_count = 0
+    materialization_mismatch_count = 0
+    invalid_plan_count = 0
+    duplicate_fingerprint_reject_count = 0
@@
         used_fingerprints.add(preview_fingerprint)
         _update_main_visual_coverage(coverage, preview_fingerprint)
+        preview_seeded = True
@@
             _score, proposal = heapq.heappop(scored_entries)
             examined_keys.add(proposal.selection_key)
+            proposal_attempted_count += 1
@@
             except MainVisualSelectionMismatch:
                 selection_mismatch_seen = True
+                materialization_mismatch_count += 1
@@
             except ValueError:
+                invalid_plan_count += 1
@@
             if fingerprint in used_fingerprints:
+                duplicate_fingerprint_reject_count += 1
                 continue
@@
+    coverage_diagnostics = _build_coverage_diagnostics_v1(
+        dsl_payload,
+        candidate_pools,
+        coverage,
+        accepted_fingerprints,
+        requested_count=requested_count,
+        candidate_space_size=candidate_space_size,
+        search_budget=search_budget,
+        examined_count=len(examined_keys),
+        proposal_attempted_count=proposal_attempted_count,
+        termination_reason=termination_reason,
+        preview_seeded=preview_seeded,
+        materialization_mismatch_count=materialization_mismatch_count,
+        invalid_plan_count=invalid_plan_count,
+        duplicate_fingerprint_reject_count=duplicate_fingerprint_reject_count,
+    )
@@
         warning_codes=tuple(warning_codes),
+        coverage_diagnostics=coverage_diagnostics,
     )
@@
 def _persist_task_history(
@@
+    coverage_diagnostics: Optional[dict[str, Any]] = None,
 ) -> None:
@@
+    planning_summary: dict[str, Any] = {
+        "requested_count": batch_size,
+        "planned_count": len(child_results),
+        "succeeded_count": sum(result.succeeded for result in child_results),
+        "failed_count": sum(not result.succeeded for result in child_results),
+        "warning_codes": list(warning_codes),
+    }
+    if coverage_diagnostics is not None:
+        planning_summary["coverage_diagnostics"] = coverage_diagnostics
@@
-        "planning_summary": {
-            ...
-        },
+        "planning_summary": planning_summary,
@@
     planning_warning_codes: list[str] = []
+    coverage_diagnostics_payload: Optional[dict[str, Any]] = None
@@
+                if variant_planning_policy == _BALANCED_VARIANT_PLANNING_POLICY:
+                    if planning_result.coverage_diagnostics is None:
+                        raise ValueError("COVERAGE_DIAGNOSTICS_MISSING")
+                    coverage_diagnostics_payload = (
+                        _validated_coverage_diagnostics_payload(
+                            planning_result.coverage_diagnostics,
+                            planning_result,
+                            computed_fingerprints,
+                        )
+                    )
+                    _emit_balanced_coverage_summary(
+                        task_id,
+                        coverage_diagnostics_payload,
+                    )
+                elif planning_result.coverage_diagnostics is not None:
+                    raise ValueError("COVERAGE_DIAGNOSTICS_UNEXPECTED_FOR_EXACT_POLICY")
@@
                 warning_codes=warning_codes,
+                coverage_diagnostics=coverage_diagnostics_payload,
             )
```

## C. Diagnostics Contracts

Exact current definitions are shown in section B. All four diagnostics containers and `_VariantPlanningResult` are frozen dataclasses.

Notable contract properties:

- `_VariantPlanningResult.coverage_diagnostics` is final, nullable, and defaults to `None`.
- Selected histogram is an immutable tuple.
- Accepted digests are an immutable tuple.
- No `CompilationPlan`, DB session, path, or asset model is stored inside diagnostics.

## D. Serializer / Builder

The complete serializer and builder are reproduced in section B.

Invariant coverage includes:

- Beat/pool/coverage length
- Non-negative counters
- Candidate-space consistency
- Preview/examined partition
- Proposal outcome partition
- Valid normalized identities
- Fingerprint Beat order and layer index
- Selected hash membership
- Coverage equality with authoritative fingerprints
- Integer/non-negative coverage counts
- Per-Beat selected count
- Unique/unused bounds
- Full-vector floor/ceil classification
- Digest count
- Plain JSON serialization

## E. Balanced Planner Counter Integration

Exact current planner region:

```python
coverage = _initial_main_visual_coverage(candidate_pools)
preview_seeded = False
proposal_attempted_count = 0
materialization_mismatch_count = 0
invalid_plan_count = 0
duplicate_fingerprint_reject_count = 0

preview_selections = _preview_selection(
    preview_plan,
    dsl_payload,
    candidate_pools,
)
if preview_selections is not None and candidate_space_size:
    preview_key = _selection_key(preview_selections)
    preview_fingerprint = _exact_main_visual_fingerprint(preview_plan)
    examined_keys.add(preview_key)
    accepted_plans.append(preview_plan)
    accepted_fingerprints.append(preview_fingerprint)
    used_fingerprints.add(preview_fingerprint)
    _update_main_visual_coverage(coverage, preview_fingerprint)
    preview_seeded = True

window = _balanced_candidate_window(
    candidate_pools,
    candidate_space_size,
    search_budget - len(examined_keys),
    excluded_keys=examined_keys,
)

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
        proposal_attempted_count += 1
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
                raise MainVisualSelectionMismatch(
                    "PLANNER_SELECTION_MISMATCH: selected and materialized hashes differ"
                )
        except MainVisualSelectionMismatch:
            selection_mismatch_seen = True
            materialization_mismatch_count += 1
            logger.exception(
                "[variant_planner] explicit balanced selection materialization mismatch"
            )
            continue
        except ValueError:
            invalid_plan_count += 1
            logger.warning(
                "[variant_planner] rejected invalid balanced main-visual plan",
                exc_info=True,
            )
            continue

        if fingerprint in used_fingerprints:
            duplicate_fingerprint_reject_count += 1
            continue
        accepted_plans.append(materialized)
        accepted_fingerprints.append(fingerprint)
        used_fingerprints.add(fingerprint)
        _update_main_visual_coverage(coverage, fingerprint)
        accepted_this_round = True
        break

    if not accepted_this_round:
        break

if len(accepted_plans) >= requested_count:
    termination_reason = _PLANNING_REQUEST_SATISFIED
    warning_codes: list[str] = []
elif len(examined_keys) >= candidate_space_size:
    termination_reason = _PLANNING_TRUE_SPACE_EXHAUSTED
    warning_codes = ["INSUFFICIENT_UNIQUE_CAPACITY"]
else:
    termination_reason = _PLANNING_SEARCH_LIMIT_REACHED
    warning_codes = ["PLANNING_SEARCH_LIMIT_REACHED"]
if selection_mismatch_seen:
    warning_codes.append("PLANNER_SELECTION_MISMATCH")

coverage_diagnostics = _build_coverage_diagnostics_v1(
    dsl_payload,
    candidate_pools,
    coverage,
    accepted_fingerprints,
    requested_count=requested_count,
    candidate_space_size=candidate_space_size,
    search_budget=search_budget,
    examined_count=len(examined_keys),
    proposal_attempted_count=proposal_attempted_count,
    termination_reason=termination_reason,
    preview_seeded=preview_seeded,
    materialization_mismatch_count=materialization_mismatch_count,
    invalid_plan_count=invalid_plan_count,
    duplicate_fingerprint_reject_count=duplicate_fingerprint_reject_count,
)

return _VariantPlanningResult(
    plans=tuple(accepted_plans),
    fingerprints=tuple(accepted_fingerprints),
    examined_combinations=len(examined_keys),
    candidate_space_size=candidate_space_size,
    termination_reason=termination_reason,
    warning_codes=tuple(warning_codes),
    coverage_diagnostics=coverage_diagnostics,
)
```

## F. Coordinator Validation / Log / Child Order

```python
planning_warning_codes: list[str] = []
coverage_diagnostics_payload: Optional[dict[str, Any]] = None
child_work: list[_ChildWork] = []
planning_function = None
if variant_planning_policy == "exact_main_visual":
    planning_function = _plan_exact_main_visual_variants_from_db
elif variant_planning_policy == "exact_main_visual_balanced":
    planning_function = _plan_exact_main_visual_balanced_variants_from_db

if planning_function is not None:
    if blind_dsl or dsl_payload is None:
        ...
    else:
        try:
            planning_result = planning_function(
                tenant_id,
                dsl_payload,
                batch_size,
                preview_plan=resolved_plan,
            )
            computed_fingerprints = tuple(
                _exact_main_visual_fingerprint(plan)
                for plan in planning_result.plans
            )
            if (
                computed_fingerprints != planning_result.fingerprints
                or len(set(computed_fingerprints)) != len(computed_fingerprints)
            ):
                raise ValueError(
                    "PLANNER_RESULT_INVALID: authoritative plans/fingerprints mismatch"
                )
            if variant_planning_policy == _BALANCED_VARIANT_PLANNING_POLICY:
                if planning_result.coverage_diagnostics is None:
                    raise ValueError("COVERAGE_DIAGNOSTICS_MISSING")
                coverage_diagnostics_payload = (
                    _validated_coverage_diagnostics_payload(
                        planning_result.coverage_diagnostics,
                        planning_result,
                        computed_fingerprints,
                    )
                )
                _emit_balanced_coverage_summary(
                    task_id,
                    coverage_diagnostics_payload,
                )
            elif planning_result.coverage_diagnostics is not None:
                raise ValueError("COVERAGE_DIAGNOSTICS_UNEXPECTED_FOR_EXACT_POLICY")
            planning_warning_codes.extend(planning_result.warning_codes)
            identities = (
                _create_child_executions(task_id, len(planning_result.plans))
                if planning_result.plans
                else []
            )
            child_work = [
                _ChildWork(
                    execution=identity,
                    authoritative_plan=plan,
                    visual_fingerprint=fingerprint,
                )
                for identity, plan, fingerprint in zip(
                    identities,
                    planning_result.plans,
                    planning_result.fingerprints,
                )
            ]
```

Visible order:

```text
planner result
→ authoritative fingerprint recomputation
→ plan/fingerprint invariant
→ diagnostics validation and serialization
→ BalancedCoverageSummary
→ child identities
→ _ChildWork
```

## G. Logging Helper

Loguru alias remains local and explicit:

```python
from src.core.logger import logger as fingerprint_logger
```

Existing module logger remains:

```python
logger = logging.getLogger(__name__)
```

Complete coverage emitter:

```python
def _emit_balanced_coverage_summary(
    task_id: str,
    coverage_diagnostics: dict[str, Any],
) -> None:
    """Emit one best-effort batch coverage event through the project Loguru sink."""
    try:
        event_json = json.dumps(
            {
                "event": _BALANCED_COVERAGE_SUMMARY_EVENT,
                "task_id": task_id,
                "coverage_diagnostics": coverage_diagnostics,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        fingerprint_logger.info(f"[BalancedCoverageSummary] {event_json}")
    except Exception:
        pass
```

The helper reads but does not mutate `coverage_diagnostics`. Logger or serialization failure cannot escape.

## H. Persistence Plumbing

Payload lifetime starts once before policy routing:

```python
coverage_diagnostics_payload: Optional[dict[str, Any]] = None
```

Balanced validation assigns it once:

```python
coverage_diagnostics_payload = (
    _validated_coverage_diagnostics_payload(
        planning_result.coverage_diagnostics,
        planning_result,
        computed_fingerprints,
    )
)
```

That same object is passed to persistence:

```python
_persist_task_history(
    task_id=task_id,
    tenant_id=tenant_id,
    prompt=prompt,
    batch_size=batch_size,
    elapsed=elapsed,
    child_results=child_results,
    output_assets=all_assets,
    warning_codes=warning_codes,
    coverage_diagnostics=coverage_diagnostics_payload,
)
```

Persistence:

```python
def _persist_task_history(
    *,
    task_id: str,
    tenant_id: str,
    prompt: Optional[str],
    batch_size: int,
    elapsed: float,
    child_results: list[_ChildResult],
    output_assets: list[dict],
    warning_codes: list[str],
    coverage_diagnostics: Optional[dict[str, Any]] = None,
) -> None:
    first_success = next(result for result in child_results if result.succeeded)
    legacy_details = first_success.prompt_details
    planning_summary: dict[str, Any] = {
        "requested_count": batch_size,
        "planned_count": len(child_results),
        "succeeded_count": sum(result.succeeded for result in child_results),
        "failed_count": sum(not result.succeeded for result in child_results),
        "warning_codes": list(warning_codes),
    }
    if coverage_diagnostics is not None:
        planning_summary["coverage_diagnostics"] = coverage_diagnostics
    prompt_details: dict[str, Any] = {
        "meta": legacy_details.get("meta"),
        "timeline": legacy_details.get("timeline") or [],
        "planning_summary": planning_summary,
        "children": [
            {
                "child_index": result.child_index,
                "execution_id": result.execution_id,
                "file_sid": result.file_sid,
                "outcome": "succeeded" if result.succeeded else "failed",
                "elapsed": result.elapsed,
                "error_code": result.error_code,
                "output_assets": [dict(asset) for asset in result.assets],
                "timeline": result.prompt_details.get("timeline") or [],
            }
            for result in child_results
        ],
    }
    history_record = TaskHistory(
        task_id=task_id,
        prompt=prompt or "",
        batch_size=batch_size,
        duration=round(elapsed, 1),
        output_assets=output_assets,
        prompt_details=json.dumps(prompt_details, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
```

No second builder or coverage calculation appears in logging or persistence.

## I. Exact / Legacy Preservation

```python
if variant_planning_policy == "exact_main_visual":
    planning_function = _plan_exact_main_visual_variants_from_db
elif variant_planning_policy == "exact_main_visual_balanced":
    planning_function = _plan_exact_main_visual_balanced_variants_from_db
```

Only balanced enters the summary branch:

```python
if variant_planning_policy == _BALANCED_VARIANT_PLANNING_POLICY:
    ...
    _emit_balanced_coverage_summary(...)
elif planning_result.coverage_diagnostics is not None:
    raise ValueError("COVERAGE_DIAGNOSTICS_UNEXPECTED_FOR_EXACT_POLICY")
```

Legacy remains:

```python
elif variant_planning_policy == "legacy":
    child_work = [
        _ChildWork(execution=child)
        for child in _create_child_executions(task_id, batch_size)
    ]
```

The old exact planner constructs `_VariantPlanningResult` without the optional field, so its value remains `None`.

## J. Targeted Tests

### A. Counter partition and rejection counters

```python
def test_cov7_mismatch_and_invalid_counters_partition_attempts(self):
    for exception_type, counter_name in (
        (MainVisualSelectionMismatch, "materialization_mismatch_count"),
        (ValueError, "invalid_plan_count"),
    ):
        pools = _pools(3)
        first_key = routes_dsl._selection_key((pools[0][0],))

        def fail_first(payload, selections, key, exc=exception_type):
            if key == first_key:
                raise exc("controlled rejection")
            return _plan_for_selections(payload, selections)

        result, _parser, _ = _balanced(
            pools,
            2,
            parser=_SyntheticParser(pools, fail_first),
        )
        data = _payload_for(result)
        self.assertEqual(data["proposal_attempted_count"], 3)
        self.assertEqual(data["examined_count"], 3)
        self.assertEqual(data["rejection_counts"][counter_name], 1)
        self.assertEqual(data["accepted_count"], 2)
        self.assertEqual(data["beats"][0]["selected_count"], 2)


def test_cov8_duplicate_fingerprint_rejection_does_not_change_coverage(self):
    pools = [[
        _candidate(1, "same"),
        _candidate(2, "same"),
        _candidate(3, "other"),
    ]]
    result, _parser, _ = _balanced(pools, 3)
    data = _payload_for(result)
    self.assertEqual(data["proposal_attempted_count"], 3)
    self.assertEqual(
        data["rejection_counts"]["duplicate_fingerprint_reject_count"], 1
    )
    self.assertEqual(data["accepted_count"], 2)
    self.assertEqual(data["beats"][0]["pool_size"], 2)
    self.assertEqual(
        [row["count"] for row in data["beats"][0]["selected_histogram"]],
        [1, 1],
    )
```

### B. Coordinator digest mismatch

```python
def test_coordinator_digest_mismatch_is_hard_and_emits_nothing(self):
    result, _parser, payload = _balanced(_pools(2), 2)
    bad_diagnostics = replace(
        result.coverage_diagnostics,
        accepted_fingerprint_digests=("0" * 64,) * 2,
    )
    bad_result = replace(result, coverage_diagnostics=bad_diagnostics)
    with patch.object(
        routes_dsl, "_emit_balanced_coverage_summary"
    ) as summary:
        terminal, worker, _persist = _run_balanced_coordinator(payload, bad_result)

    summary.assert_not_called()
    worker.assert_not_called()
    self.assertEqual(terminal["plannedCount"], 0)
    self.assertIn("VARIANT_PLANNING_FAILED", terminal["warningCodes"])
```

### C. Exactly once and before child execution

```python
def test_coordinator_validates_then_emits_once_before_children_and_persists_same_payload(self):
    result, _parser, payload = _balanced(_pools(4, 2, 1, 2, 2), 4)
    order = []
    persisted = []
    emitted = []
    original_validate = routes_dsl._validated_coverage_diagnostics_payload

    def validate(*args):
        order.append("validate")
        return original_validate(*args)

    def emit(_task_id, coverage_payload):
        order.append("summary")
        emitted.append(coverage_payload)

    def worker(plan, _task_id, *args, file_sid=None, **kwargs):
        order.append("child")
        resolved_sid = file_sid or args[-1]
        return _successful_child(plan, resolved_sid, kwargs)

    def persist(**kwargs):
        persisted.append(kwargs["coverage_diagnostics"])

    with (
        patch.object(
            routes_dsl,
            "_validated_coverage_diagnostics_payload",
            side_effect=validate,
        ),
        patch.object(
            routes_dsl,
            "_emit_balanced_coverage_summary",
            side_effect=emit,
        ) as summary,
    ):
        terminal, worker_mock, _persist = _run_balanced_coordinator(
            payload,
            result,
            worker_side_effect=worker,
            persist_side_effect=persist,
        )

    self.assertEqual(order[:3], ["validate", "summary", "child"])
    summary.assert_called_once()
    self.assertEqual(worker_mock.call_count, 4)
    self.assertEqual(len(emitted), 1)
    self.assertIs(emitted[0], persisted[0])
    self.assertEqual(emitted[0], _payload_for(result))
    self.assertNotIn("coverageDiagnostics", terminal)
```

### D. Logger failure is non-blocking

```python
def test_summary_loguru_payload_and_logger_failure_are_nonblocking(self):
    result, _parser, payload = _balanced(_pools(2), 2)
    captured = []
    with patch.object(
        routes_dsl.fingerprint_logger,
        "info",
        side_effect=lambda message: captured.append(message),
    ):
        terminal, worker, _persist = _run_balanced_coordinator(payload, result)

    self.assertEqual(terminal["status"], "completed")
    self.assertEqual(worker.call_count, 2)
    self.assertEqual(len(captured), 1)
    self.assertTrue(captured[0].startswith("[BalancedCoverageSummary] "))
    event = json.loads(captured[0].split(" ", 1)[1])
    self.assertEqual(event["event"], "BalancedCoverageSummary")
    self.assertEqual(event["coverage_diagnostics"], _payload_for(result))

    with patch.object(
        routes_dsl.fingerprint_logger,
        "info",
        side_effect=RuntimeError("sink failed"),
    ):
        terminal, worker, _persist = _run_balanced_coordinator(payload, result)
    self.assertEqual(terminal["status"], "completed")
    self.assertEqual(worker.call_count, 2)
```

### E. TaskHistory persistence

```python
def test_cov11_taskhistory_persists_nested_payload_without_schema_change(self):
    result, _parser, _payload_value = _balanced(_pools(2), 2)
    coverage_payload = _payload_for(result)
    child = _successful_child(
        result.plans[0],
        "file-a",
        {"child_index": 0, "execution_id": "exec-a"},
    )
    added = []

    class SessionContext:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _traceback):
            return False

        def add(self, row):
            added.append(row)

        def commit(self):
            return None

    with (
        patch.object(routes_dsl, "get_tenant_engine", return_value="engine"),
        patch.object(
            routes_dsl,
            "sessionmaker",
            return_value=lambda: SessionContext(),
        ),
    ):
        routes_dsl._persist_task_history(
            task_id="coverage-history",
            tenant_id="tenant-a",
            prompt="prompt",
            batch_size=2,
            elapsed=1.0,
            child_results=[child],
            output_assets=child.assets,
            warning_codes=[],
            coverage_diagnostics=coverage_payload,
        )
        routes_dsl._persist_task_history(
            task_id="exact-history",
            tenant_id="tenant-a",
            prompt="prompt",
            batch_size=1,
            elapsed=1.0,
            child_results=[child],
            output_assets=child.assets,
            warning_codes=[],
        )

    details = json.loads(added[0].prompt_details)
    self.assertEqual(
        details["planning_summary"]["coverage_diagnostics"],
        coverage_payload,
    )
    self.assertFalse(hasattr(added[0], "coverage_diagnostics"))
    exact_details = json.loads(added[1].prompt_details)
    self.assertNotIn(
        "coverage_diagnostics",
        exact_details["planning_summary"],
    )
```

### F. Planning accepted 4, render succeeded 3

```python
def test_planning_accepted_count_survives_one_render_failure(self):
    result, _parser, payload = _balanced(_pools(4, 2), 4)
    persisted = []

    def worker(plan, _task_id, *args, file_sid=None, **kwargs):
        resolved_sid = file_sid or args[-1]
        if kwargs["child_index"] == 3:
            return _failed_child(plan, resolved_sid, kwargs)
        return _successful_child(plan, resolved_sid, kwargs)

    terminal, _worker, _persist = _run_balanced_coordinator(
        payload,
        result,
        worker_side_effect=worker,
        persist_side_effect=lambda **kwargs: persisted.append(
            kwargs["coverage_diagnostics"]
        ),
    )
    self.assertEqual(terminal["succeededCount"], 3)
    self.assertEqual(persisted[0]["accepted_count"], 4)
```

### G. `P=4, B=2` conceptual zero case

```python
below, _parser, _ = _balanced(_pools(4, 2), 2)
below_beat = _payload_for(below)["beats"][0]
self.assertEqual(below_beat["unique_used"], 2)
self.assertEqual(below_beat["unused_count"], 2)
self.assertEqual(
    (below_beat["ideal_floor"], below_beat["ideal_ceil"]),
    (0, 1),
)
self.assertEqual(below_beat["max_min_gap"], 1)
self.assertEqual(below_beat["classification"], "VARIABLE_BALANCED")
```

### H. `VARIABLE_TARGET_NOT_MET`

```python
def test_target_not_met_and_zero_pool_pure_builder_boundaries(self):
    pools = _pools(4)
    payload = _payload(pools)
    fingerprints = tuple(
        ((0, "Beat-0", 0, hash_value),)
        for hash_value in ("b0-0", "b0-0", "b0-1", "b0-1")
    )
    diagnostics = routes_dsl._build_coverage_diagnostics_v1(
        payload,
        pools,
        [{"b0-0": 2, "b0-1": 2, "b0-2": 0, "b0-3": 0}],
        fingerprints,
        requested_count=4,
        candidate_space_size=4,
        search_budget=4,
        examined_count=4,
        proposal_attempted_count=4,
        termination_reason="REQUEST_SATISFIED",
        preview_seeded=False,
        materialization_mismatch_count=0,
        invalid_plan_count=0,
        duplicate_fingerprint_reject_count=0,
    )
    beat = routes_dsl._coverage_diagnostics_v1_payload(diagnostics)["beats"][0]
    self.assertEqual(beat["max_min_gap"], 2)
    self.assertEqual(beat["classification"], "VARIABLE_TARGET_NOT_MET")

    empty_pools = [[]]
    empty_payload = _payload(empty_pools)
    empty = routes_dsl._build_coverage_diagnostics_v1(
        empty_payload,
        empty_pools,
        [{}],
        (),
        requested_count=1,
        candidate_space_size=0,
        search_budget=1,
        examined_count=0,
        proposal_attempted_count=0,
        termination_reason="TRUE_SPACE_EXHAUSTED",
        preview_seeded=False,
        materialization_mismatch_count=0,
        invalid_plan_count=0,
        duplicate_fingerprint_reject_count=0,
    )
    empty_beat = routes_dsl._coverage_diagnostics_v1_payload(empty)["beats"][0]
    self.assertIsNone(empty_beat["classification"])
    self.assertIsNone(empty_beat["ideal_floor"])
    self.assertIsNone(empty_beat["ideal_ceil"])
    self.assertIsNone(empty_beat["max_min_gap"])
```

Phase 2B compatibility changes:

```diff
 def test_var1b10_capacity_warning_propagates_without_duplicate_fill(self):
     pools = _pools(2)
-    payload = _payload(pools)
-    plans = [...]
-    result = _planning_result(...)
+    result, _parser, payload = _balanced(pools, 4)

 def test_var1b11_search_limit_warning_propagates(self):
     pools = _pools(2, 2)
-    payload = _payload(pools)
-    plan = ...
-    result = _planning_result(...)
+    result, _parser, payload = _balanced(pools, 4, search_budget=1)
```

## K. Phase 1 Selection Diff Check

Changed-line search results:

```text
_selection_from_cartesian_ordinal_CHANGED_LINES=0
_stratified_cartesian_ordinals_CHANGED_LINES=0
_balanced_candidate_window_CHANGED_LINES=0
_projected_main_visual_coverage_score_CHANGED_LINES=0
heapq.heapify_CHANGED_LINES=0
heapq.heappop_CHANGED_LINES=0
scored_entries =_CHANGED_LINES=0
```

The `_balanced_candidate_window` name appears once in five-line diff context because diagnostics counters were inserted before the unchanged call. No line within the call or helper changed.

No changed line affects:

- Mixed-radix decoding
- Stratified ordinal calculation
- Candidate-window membership
- Coverage score tuple
- Heap construction
- Heap pop ordering
- Proposal choice

`PHASE1_SELECTION_DIFF_NONE`

Final status remains:

```text
 M src/api/routes_dsl.py
 M tests/test_var001_policy_integration.py
?? tests/test_var001_coverage_diagnostics.py
```

No code, test, report file, commit, or runtime state was changed during this review.