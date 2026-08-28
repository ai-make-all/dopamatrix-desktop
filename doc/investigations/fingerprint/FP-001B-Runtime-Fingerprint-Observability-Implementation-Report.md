# FP-001B
# Runtime Fingerprint Observability Implementation Report

## 1. Baseline

```text
Branch:
feature/var-001-variation-policy

HEAD:
35d63cd905c96fd2fa5d62162023ee07de3110fe

Initial status:
CLEAN
```

Recent history:

```text
35d63cd feat(fp-001): add versioned planning fingerprint contract
d2119d7 docs(fp-001): record fingerprint contract hardening review
885cc54 docs(fp-001): record fingerprint contract audit
93359b6 Merge branch 'refactor/dopamatrix-brand-unification'...
5a5639c fix(inv-001): deduplicate per-beat y-layer media
```

Committed FP-001A definitions were verified before modification:

```text
type:                  main_visual_planning
version:               1
source hash algorithm: md5
digest:                SHA-256 over canonical UTF-8 JSON
```

## 2. Files Changed

- [routes_dsl.py:184](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:184>)
  - Runtime event constants.
  - Bounded component extraction.
  - Authoritative event payload builder.
  - Protected diagnostic and INFO emitter.
  - Optional worker parameter.
  - `_ChildWork → render_worker` forwarding.
  - Authoritative worker-entry emission.

- [test_fp001_fingerprint_observability.py:1](</E:/dopaworkspace/dopamatrix-desktop/tests/test_fp001_fingerprint_observability.py:1>)
  - 14 focused observability tests covering FO1–FO14.

No other production files changed.

## 3. Existing Contract Preservation

Unchanged:

- `_MainVisualFingerprint`
- `_exact_main_visual_fingerprint`
- `normalize_file_hash`
- FP-001A constants and canonicalization semantics
- canonical JSON format
- SHA-256 digest construction
- `_selection_key`
- `used_fingerprints`
- preview fingerprint equality
- candidate enumeration
- capacity/search budget
- coordinator uniqueness invariant

Runtime uniqueness still uses the existing tuple/set contract. Digest is not involved in planner acceptance.

The observability digest is built through the committed helper:

```py
_main_visual_planning_fingerprint_contract(worker_fingerprint)
```

No duplicate canonicalization or digest implementation was introduced.

## 4. Fingerprint Worker Handoff

Existing `_ChildWork` semantics remain unchanged:

```py
@dataclass(frozen=True)
class _ChildWork:
    execution: _ChildExecution
    authoritative_plan: Optional[CompilationPlan] = None
    visual_fingerprint: Optional[_MainVisualFingerprint] = None
```

`render_worker` now accepts a keyword-only optional parameter:

```py
visual_fingerprint: Optional[_MainVisualFingerprint] = None
```

Coordinator forwarding:

```py
result = render_worker(
    # ...
    plan_is_authoritative=work.authoritative_plan is not None,
    visual_fingerprint=work.visual_fingerprint,
    # ...
)
```

Exact data flow:

```text
planning_result.fingerprints
→ coordinator recomputes and validates plan/fingerprint invariant
→ child execution identity allocation
→ _ChildWork(
      execution,
      authoritative_plan,
      visual_fingerprint
  )
→ _execute_child(work)
→ render_worker(
      authoritative plan,
      execution identity,
      visual_fingerprint=work.visual_fingerprint
  )
```

Manual, blind, legacy and direct callers may continue omitting the parameter.

## 5. Authoritative Recompute

At authoritative worker entry:

```text
plan_is_authoritative == True
and plan is not None
```

the worker:

1. Accepts the authoritative plan.
2. Recomputes the current runtime tuple using `_exact_main_visual_fingerprint(plan)`.
3. Builds the FP-001A contract from that recomputed tuple.
4. Compares the planner-provided tuple with the recomputed tuple.
5. Emits the event using the recomputed authoritative digest.

Match states:

| Condition | `planner_fingerprint_match` |
|---|---:|
| Planner tuple equals worker tuple | `true` |
| Planner tuple differs | `false` |
| Planner tuple missing | `null` |

On mismatch, the event digest remains derived from the authoritative plan actually entering execution. The stale planner tuple is not logged as runtime truth.

## 6. VariantFingerprint Event Contract

Event constants:

```py
_VARIANT_FINGERPRINT_EVENT = "VariantFingerprint"
_VARIANT_FINGERPRINT_PHASE = "authoritative_worker_start"
_MAX_LOGGED_FINGERPRINT_COMPONENTS = 32
```

Event payload:

```text
event
phase

task_id
execution_id
child_index
file_sid

fingerprint_type
fingerprint_version
source_hash_algorithm
fingerprint_digest

beat_count
planner_fingerprint_match

components
components_truncated
```

Normal event shape:

```json
{
  "event": "VariantFingerprint",
  "phase": "authoritative_worker_start",
  "task_id": "...",
  "execution_id": "...",
  "child_index": 2,
  "file_sid": "...",
  "fingerprint_type": "main_visual_planning",
  "fingerprint_version": 1,
  "source_hash_algorithm": "md5",
  "fingerprint_digest": "<full 64-character SHA-256>",
  "beat_count": 5,
  "planner_fingerprint_match": true,
  "components": [],
  "components_truncated": false
}
```

The event is emitted as deterministic compact JSON:

```py
logger.info(
    "[VariantFingerprint] %s",
    json.dumps(
        event,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ),
)
```

This JSON formatting is only the log representation. Digest construction continues to use the FP-001A canonical bytes helper.

## 7. Runtime Emission Point

Mandatory INFO is emitted in `render_worker`:

```text
AFTER
  child execution identity validation
  authoritative plan non-null validation
  working_plan = plan

BEFORE
  compile_plan_to_timeline
  WorkflowContext creation
  TTS
  subtitles
  compositor
  cover
```

Semantic meaning:

```text
This child entered authoritative rendering with this exact
main_visual_planning v1 fingerprint.
```

Normal successful observability produces exactly one `[VariantFingerprint]` INFO per authoritative child.

No coordinator DEBUG event was added.

## 8. Component Diagnostics

Each logged component contains:

```text
beat_index
beat_identity
asset_id
normalized_file_hash
```

Component order follows the authoritative worker fingerprint and authoritative plan Beat order.

`asset_id` is extracted only from the authoritative plan’s unique `layer_index == 0` layer.

It is not obtained from:

- candidate selection state
- preview state
- database lookup
- source file
- global context

`asset_id` is not passed into the FP-001A builder and is not part of digest equality. FO6 verifies that changing only `asset_id` changes component diagnostics but not the digest.

Full normalized source hashes and the full 64-character fingerprint digest are logged.

No prompt, DSL payload, raw media, path, tokens or secrets are included.

## 9. Log Bounding

Maximum logged components:

```text
32
```

For `beat_count > 32`:

- `beat_count` retains the full count.
- `fingerprint_digest` remains derived from the complete authoritative tuple.
- Only the first 32 component diagnostics are emitted.
- `components_truncated = true`.

For 3-Beat and 5-Beat plans:

- All components are included.
- `components_truncated = false`.

Only presentation is truncated; canonical bytes and digest are never truncated.

## 10. Non-Blocking Failure Semantics

Protected conditions include:

- planner fingerprint missing
- planner/worker mismatch
- authoritative recomputation exception
- FP-001A contract builder exception
- component extraction exception
- JSON log formatting exception
- INFO logger exception
- diagnostic logger exception

Diagnostics:

```text
FINGERPRINT_OBSERVABILITY_MISSING
FINGERPRINT_OBSERVABILITY_MISMATCH
FINGERPRINT_OBSERVABILITY_FAILED
```

These are logger diagnostics only.

They do not introduce:

- `_ChildResult.error_code`
- product `warning_codes`
- planner rejection
- HTTP error
- WebSocket terminal fields
- TaskHistory failure
- render failure

The diagnostic message detail is bounded to 300 characters. Diagnostic logging itself is wrapped so a logger exception cannot affect rendering.

Tests prove successful rendering continues after:

- mismatched planner tuple
- missing planner tuple
- contract builder failure

## 11. Legacy / Non-Authoritative Compatibility

For:

```text
plan_is_authoritative == false
```

the observability emitter is not invoked.

Therefore:

- `visual_fingerprint=None` produces no fingerprint-required warning.
- No `VariantFingerprint` event is required.
- Existing direct calls remain valid.
- Manual/blind/legacy resolver behavior remains unchanged.

An existing authoritative direct test does not provide the new optional tuple. It now emits the required missing diagnostic, recomputes from its authoritative plan, emits the runtime event, and continues successfully.

## 12. Tests Added

| ID | Coverage |
|---|---|
| FO1 | `_ChildWork.visual_fingerprint` is forwarded explicitly to `render_worker` |
| FO2 | Event binds `event`, `phase`, task, execution, child index and file SID |
| FO3 | Type/version/source algorithm match committed FP-001A contract |
| FO4 | Digest equals FP-001A contract built from authoritative plan |
| FO5 | Five Beats produce five complete ordered components |
| FO6 | `asset_id` changes do not affect digest |
| FO7 | Matching planner tuple reports `true` |
| FO8 | Mismatch warns, logs authoritative digest and render succeeds |
| FO9 | Missing tuple reports `null`, warns and render succeeds |
| FO10 | Non-authoritative missing tuple produces no new diagnostic/event |
| FO11 | More than 32 Beats truncates components but not digest/count |
| FO12 | Three- and five-Beat plans do not truncate |
| FO13 | Contract/logging failures do not escape observability boundary or fail render |
| FO14 | Normal authoritative worker emits exactly one event |

Focused FP-001B result:

```text
Ran 14 tests
OK
```

## 13. INV-001 Regression

Command:

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

Result:

```text
Ran 82 tests in 0.711s
OK
```

Existing simulated failure logs and deprecation warnings did not affect results.

INV tuple equality, planner selection, capacity, coordinator behavior and authoritative handoff remain passing.

## 14. FP-001 Regression

Command:

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_fp001_*.py" -q
```

Result:

```text
FP-001A: 15 tests
FP-001B: 14 tests
Total:   29 tests

Ran 29 tests in 0.085s
OK
```

## 15. Worker Call-Site Audit

Nine actual `render_worker(...)` call sites were inspected, excluding its definition and module documentation:

| Classification | Count |
|---|---:|
| Production coordinator call | 1 |
| Existing legacy/direct test calls | 6 |
| Existing authoritative direct test | 1 |
| New mixed authoritative/non-authoritative test harness | 1 |
| Total | 9 |

Only the production coordinator forwards:

```py
visual_fingerprint=work.visual_fingerprint
```

Other callers do not require mechanical edits because the parameter is keyword-only with default `None`.

## 16. Persistence Audit

Fingerprint digest/event is not stored in:

- `TaskHistory`
- `prompt_details`
- `planning_summary`
- children metadata
- SQLite
- `LocalAsset`
- `VideoAsset`
- output metadata

No schema or migration was added.

FP-001B remains runtime logging only.

## 17. Scope Audit

Self-review:

| Check | Result |
|---|---:|
| A. INV tuple unchanged | YES |
| B. Planner acceptance unchanged | YES |
| C. Digest uses committed FP-001A builder | YES |
| D. Fingerprint explicitly reaches worker | YES |
| E. Worker recomputes authoritative tuple | YES |
| F. Event uses authoritative recomputation | YES |
| G. Planner mismatch does not fail render | YES |
| H. Observability exception does not fail render | YES |
| I. One INFO event per authoritative child | YES |
| J. Non-authoritative flows unchanged | YES |
| K. No DB persistence | YES |
| L. No UX warning changes | YES |
| M. No Historical Ledger | YES |
| N. No visual-sequence fingerprint | YES |
| O. No source rehash | YES |

No changes to:

- frontend/API schemas
- `dsl_parser.py`
- models/DB
- FFmpeg/compositor
- TTS
- Subtitle
- Cover
- BGM/Y dedup
- requirements
- output naming

Checks:

```text
py_compile:       PASS
git diff --check: PASS
```

The only `diff --check` output is the repository’s LF→CRLF warning.

## 18. Review Findings

**NONE**

## 19. Final Git Status

```text
 M src/api/routes_dsl.py
?? tests/test_fp001_fingerprint_observability.py
```

Tracked diff:

```text
src/api/routes_dsl.py | 162 insertions
```

The new untracked test file is not included in `git diff --stat`.

No commit or push performed. FP-001B stops here; VAR-001, Historical Ledger and other fingerprint families were not started.