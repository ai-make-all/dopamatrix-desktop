```python
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


def _validated_coverage_diagnostics_payload(
    diagnostics: _CoverageDiagnosticsV1,
    planning_result: _VariantPlanningResult,
    computed_fingerprints: Sequence[_MainVisualFingerprint],
) -> dict[str, Any]:
    """Validate the balanced diagnostics against coordinator-approved truth."""
    accepted_count = len(computed_fingerprints)
    if (
        diagnostics.accepted_count != accepted_count
        or len(planning_result.plans) != accepted_count
        or len(planning_result.fingerprints) != accepted_count
        or diagnostics.examined_count != planning_result.examined_combinations
        or diagnostics.candidate_space_size != planning_result.candidate_space_size
        or diagnostics.termination_reason != planning_result.termination_reason
    ):
        raise ValueError("COVERAGE_DIAGNOSTICS_COORDINATOR_COUNT_MISMATCH")
    coordinator_digests = tuple(
        _main_visual_planning_fingerprint_contract(fingerprint).fingerprint_digest
        for fingerprint in computed_fingerprints
    )
    if diagnostics.accepted_fingerprint_digests != coordinator_digests:
        raise ValueError("COVERAGE_DIAGNOSTICS_COORDINATOR_DIGEST_MISMATCH")
    payload = _coverage_diagnostics_v1_payload(diagnostics)
    json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return payload


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

1. Accepted-count equality across diagnostics, plans, and fingerprints: **YES**.

2. Examined-count equality: **YES**.

3. Candidate-space-size equality: **YES**.

4. Termination-reason equality: **YES**.

5. Ordered FP-001A digest recomputation and comparison: **YES**.

6. Explicit `type`/`version`/`policy` validation in this validator: **NO**. Those values are assigned by the builder, but this function does not independently verify them before serialization.

7. Mutation of inputs or returned coverage data: **NO**. It reads the inputs, creates a new digest tuple, and serializes a newly created payload dictionary.

VALIDATOR_SOURCE_CAPTURE_COMPLETE