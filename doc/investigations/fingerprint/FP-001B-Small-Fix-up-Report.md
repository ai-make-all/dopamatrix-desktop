# FP-001B
# Small Fix-up Report
# Bounded Runtime Component Presentation

## 1. Finding

Fixed:

```text
FP1B-RF-01
COMPONENT_LOG_FIELDS_NOT_LENGTH_BOUNDED
```

The existing 32-component cap bounded list length but did not bound individual `beat_identity` or abnormal `normalized_file_hash` strings.

## 2. Files Changed

- [routes_dsl.py:187](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:187>)
  - Added presentation-only length constants.
  - Added pure bounding helper.
  - Bounded component presentation fields.
  - Added `component_fields_truncated`.

- [test_fp001_fingerprint_observability.py:388](</E:/dopaworkspace/dopamatrix-desktop/tests/test_fp001_fingerprint_observability.py:388>)
  - Added FO15–FO19.
  - Added normal event assertion for the new flag.

No other production files changed.

The two untracked Markdown reports existed at fix-up baseline and were not modified.

## 3. Presentation Limits

New constants:

```py
_MAX_LOGGED_BEAT_IDENTITY_CHARS = 128
_MAX_LOGGED_SOURCE_HASH_CHARS = 128
```

These constants are used only by VariantFingerprint component presentation.

They are not referenced by:

- `_MainVisualFingerprint`
- `_exact_main_visual_fingerprint`
- `normalize_file_hash`
- canonical payload
- canonical bytes
- digest builder
- planner equality

Normal values remain fully visible:

```text
hook/context/build/reveal/cta: unchanged
32-character MD5:             unchanged
```

## 4. Bounding Helper

New pure helper:

```py
def _bounded_fingerprint_log_string(
    value: object,
    max_chars: int,
) -> tuple[str, bool]:
    """Return a deterministic presentation-only string and truncation state."""
    text = str(value)
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True
```

Properties:

- Deterministic.
- Does not modify the input.
- Python string slicing is Unicode-safe at the code-point level.
- Normal strings do not raise.
- Returns an explicit truncation state.
- Adds no dependency.

Application is limited to component presentation:

```py
displayed_beat_identity, beat_identity_truncated = (
    _bounded_fingerprint_log_string(
        beat_identity,
        _MAX_LOGGED_BEAT_IDENTITY_CHARS,
    )
)

displayed_file_hash, file_hash_truncated = (
    _bounded_fingerprint_log_string(
        normalized_file_hash,
        _MAX_LOGGED_SOURCE_HASH_CHARS,
    )
)
```

## 5. Canonical/Digest Preservation

The authoritative data flow remains:

```py
worker_fingerprint = _exact_main_visual_fingerprint(plan)
contract = _main_visual_planning_fingerprint_contract(worker_fingerprint)
```

Only afterward is bounded presentation constructed:

```py
_main_visual_planning_log_components(
    plan,
    worker_fingerprint,
)
```

Therefore the FP-001A builder still receives the complete original:

- Beat identity
- normalized source hash
- ordered tuple
- complete Beat list

The following remain unchanged:

- `_MainVisualFingerprint`
- canonical payload
- canonical bytes
- SHA-256 digest

FO15 and FO16 independently compare the event digest with a digest computed from the full, untruncated tuple.

## 6. Event Contract Update

New top-level field:

```text
component_fields_truncated
```

Meaning:

```text
true  = at least one logged beat_identity or normalized_file_hash was shortened
false = all logged component string fields were presented in full
```

Existing `components_truncated` retains its original meaning:

```text
true = Beat/component list exceeded the 32-entry presentation cap
```

The two states are independent:

| Scenario | `components_truncated` | `component_fields_truncated` |
|---|---:|---:|
| Normal 3/5 Beat | false | false |
| One long Beat ID | false | true |
| 33 normal Beats | true | false |
| 33 Beats plus long logged field | true | true |

Neither flag enters canonical payload or digest equality.

## 7. Tests Added

| Test | Evidence |
|---|---|
| FO15 | Long Unicode Beat identity is bounded to 128; tuple retains full identity; digest uses full tuple |
| FO16 | Abnormal 200-character normalized hash is bounded to 128; tuple and digest retain all 200 characters |
| FO17 | `hook` and normal 32-character MD5 remain unchanged; field flag is false |
| FO18 | More than 32 normal components sets list truncation true and field truncation false |
| FO19 | Component-count and field-length truncation can both independently be true |

Existing FO1–FO14 remain intact:

- FO13 still proves observability failure is non-blocking.
- FO14 still proves exactly one VariantFingerprint INFO.

Focused observability result:

```text
Ran 19 tests in 0.092s
OK
```

## 8. Existing FP Regression

Command:

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_fp001_*.py" -q
```

Result:

```text
FP-001A: 15 tests
FP-001B: 19 tests
Total:   34 tests

Ran 34 tests in 0.086s
OK
```

## 9. INV Regression

Command:

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

Result:

```text
Ran 82 tests in 0.726s
OK
```

No INV tuple, planning, capacity, preview, coordinator or worker regression was detected.

Additional checks:

```text
py_compile:       PASS
git diff --check: PASS
```

The only diff-check output was the repository’s LF→CRLF warning.

## 10. Log Payload Proof

Plan-derived arbitrary component strings are now bounded:

| Component field | Bound |
|---|---:|
| `beat_identity` | 128 Python characters |
| `normalized_file_hash` | 128 Python characters |
| `beat_index` | Integer |
| `asset_id` | Integer |

Component count remains bounded to 32.

The full fingerprint digest remains an unshortened 64-character lowercase SHA-256 hex string.

Execution identity fields are generated/validated internal identifiers and were explicitly outside this fix-up.

**LOG_PAYLOAD_FULLY_BOUNDED**

## 11. Scope Audit

| Check | Result |
|---|---:|
| A. Canonical tuple unchanged | YES |
| B. Digest unchanged | YES |
| C. Planner semantics unchanged | YES |
| D. Only presentation strings bounded | YES |
| E. Normal MD5 remains full | YES |
| F. Normal Beat ID remains full | YES |
| G. Long Beat ID bounded | YES |
| H. Long abnormal hash bounded | YES |
| I. `components_truncated` semantics preserved | YES |
| J. `component_fields_truncated` separate | YES |
| K. Exactly-one INFO unchanged | YES |
| L. Non-blocking behavior unchanged | YES |

No changes to DB, TaskHistory, frontend, API schema, worker handoff, mismatch/missing behavior, Historical Ledger or source hashing.

## 12. Review Findings

**NONE**

## 13. Final Git Status

```text
 M src/api/routes_dsl.py
?? doc/investigations/fingerprint/FP-001B-Runtime-Fingerprint-Observability-Implementation-Report.md
?? doc/investigations/fingerprint/FP-001B-Targeted-Runtime-Observability-Code-Review-Bundle.md
?? tests/test_fp001_fingerprint_observability.py
```

Tracked diff remains confined to:

```text
src/api/routes_dsl.py
```

No commit or push performed.

**FP001B_FIXUP_PASS**