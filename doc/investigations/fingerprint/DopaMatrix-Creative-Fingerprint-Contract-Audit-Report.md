# FP-001
# DopaMatrix Creative Fingerprint Contract Audit Report

## 1. Baseline

| Check | Result |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| HEAD | `93359b61a0dbd0eb55c4b19c81961f91ffb2196b` |
| Worktree | CLEAN |
| `inv-001-final-closed` ancestor check | Exit code `0` — PROVEN |
| Audit mode | Strict read-only |
| Tests executed | None; source/test audit only |

`git log -5 --oneline --decorate`:

```text
93359b6 (HEAD -> feature/var-001-variation-policy, origin/integration/dopamatrix-v1.1-base, origin/feature/var-001-variation-policy, integration/dopamatrix-v1.1-base) Merge branch 'refactor/dopamatrix-brand-unification' into integration/dopamatrix-v1.1-base
5a5639c (tag: inv-001-final-closed) fix(inv-001): deduplicate per-beat y-layer media
9d589c4 docs(inv-001): record phase 4 y-layer dedup review
fbfbca1 feat(inv-001): surface planner capacity warnings
b73e6a6 docs(inv-001): record phase 3B capacity warning review
```

## 2. Fingerprint Source Map

| File / symbol | Class | Purpose | Input | Output | Callers / consumers |
|---|---|---|---|---|---|
| [routes_dsl.py:179](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:179>) `_MainVisualFingerprint` | A | Runtime type alias | — | Ordered tuple of components | Planner/coordinator |
| [routes_dsl.py:204](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:204>) `_exact_main_visual_fingerprint` | A + B | Validates and identifies ordered main-X plan | `CompilationPlan` | `_MainVisualFingerprint` | Preview, candidate planner, coordinator invariant |
| [routes_dsl.py:238](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:238>) `_selection_key` | B | Marks candidate tuples as examined | Ordered `MainVisualCandidate` sequence | Tuple of `(asset_id, file_hash)` | Planner search loop |
| [dsl_parser.py:62](</E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:62>) `normalize_file_hash` | A + B | Shared stored-hash normalization | Any object | `str` | Candidate discovery, materialization validation, main fingerprint, Y dedup |
| [dsl_parser.py:75](</E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:75>) `MainVisualCandidate` | B | Session-independent candidate reference | DB asset ID/hash | Frozen `(asset_id, normalized hash)` object | Discovery/materialization/planner |
| [dsl_parser.py:122](</E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:122>) `discover_main_visual_candidates` | B | Builds ordered, normalized, hash-deduplicated candidate pools | `StoryDSLPayload` | One pool per Beat | Exact planner |
| [dsl_parser.py:154](</E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:154>) `materialize_with_main_selections` | B | Creates authoritative plan using explicit main selections | DSL + candidates | `CompilationPlan` | Exact planner |
| [routes_dsl.py:285](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:285>) `_plan_exact_main_visual_variants` | B | Enumerates and accepts unique main fingerprints | Parser, DSL, count, preview | Plans + fingerprints + capacity metadata | DB wrapper/coordinator |
| [routes_dsl.py:188](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:188>) `_VariantPlanningResult` | A + B | Keeps accepted plans positionally paired with fingerprints | Planner state | Immutable result envelope | Coordinator |
| [routes_dsl.py:198](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:198>) `_ChildWork` | A + D | Temporarily binds execution, plan, fingerprint | Accepted plan/fingerprint + identity | In-memory child envelope | Coordinator; fingerprint is not forwarded |
| [routes_dsl.py:1040](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1040>) `render_batch_worker` | B | Revalidates fingerprints, allocates child identities, submits workers | Planning result | Child executions | `render_worker` |
| [dsl_parser.py:756](</E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:756>) `_y_asset_identity` | D | Per-Beat Y-layer dedup identity | `LocalAsset` | `("file_hash", hash)` or `("asset_id", id)` | Y-layer materialization only; not main fingerprint |
| [routes_assets.py:34](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_assets.py:34>) `compute_md5` | D | Full source-file MD5 for DAM import/dedup | Source file | MD5 string | `LocalAsset.file_hash` |
| [routes_dsl.py:882](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:882>) output hash block | C | Quick rendered-output identifier | First 64 KiB of final output | MD5 string | `_ChildResult.assets`, TaskHistory |
| [compositor.py:98](</E:/dopaworkspace/dopamatrix-desktop/src/nodes/compositor.py:98>) `_quick_hash` | C | Equivalent quick hash helper | First 64 KiB/path fallback | MD5 string | No current production caller found |
| [services.py:53](</E:/dopaworkspace/dopamatrix-desktop/src/api/services.py:53>) `_md5_file` | C | Full rendered-file MD5 in separate service pipeline | Entire output file | MD5 string | `VideoAsset.file_hash` |
| [models.py:67](</E:/dopaworkspace/dopamatrix-desktop/src/api/models.py:67>) `VideoAsset` | C | Persisted rendered asset/hash model | Render result | DB row | Separate service pipeline |
| [models.py:98](</E:/dopaworkspace/dopamatrix-desktop/src/api/models.py:98>) `LocalAsset` | D | Persisted source asset and source hash | Imported media | DB row | Resolver/planner |

The exact helper responsible for INV-001 batch-local main-visual uniqueness is:

```text
_exact_main_visual_fingerprint
    +
used_fingerprints: set[_MainVisualFingerprint]
```

## 3. Current Fingerprint Contract

Complete production definition:

```python
_MainVisualFingerprint = tuple[tuple[int, str, int, str], ...]


def _exact_main_visual_fingerprint(
    plan: CompilationPlan,
) -> _MainVisualFingerprint:
    """Validate and fingerprint the ordered layer-0 main visual sequence."""
    if not plan.beats:
        raise ValueError("MAIN_VISUAL_PLAN_INVALID: plan has no Beats")

    fingerprint: list[tuple[int, str, int, str]] = []
    for beat_index, beat in enumerate(plan.beats):
        main_layers = [layer for layer in beat.layers if layer.layer_index == 0]
        if len(main_layers) != 1:
            raise ValueError(
                "MAIN_VISUAL_PLAN_INVALID: Beat "
                f"{beat.beat!r} has {len(main_layers)} layer-0 assets"
            )
        main_layer = main_layers[0]
        if not is_main_visual_asset_type(main_layer.asset_type):
            raise ValueError(
                "MAIN_VISUAL_PLAN_INVALID: Beat "
                f"{beat.beat!r} layer 0 is not a main-X asset"
            )
        normalized_hash = normalize_file_hash(main_layer.file_hash)
        if not normalized_hash:
            raise ValueError(
                f"MAIN_VISUAL_PLAN_INVALID: Beat {beat.beat!r} has no stable file_hash"
            )
        beat_identity = str(beat.beat).strip()
        if not beat_identity:
            raise ValueError("MAIN_VISUAL_PLAN_INVALID: Beat identity is empty")
        fingerprint.append((beat_index, beat_identity, 0, normalized_hash))

    return tuple(fingerprint)
```

Authoritative shape:

```python
tuple[
    tuple[
        int,  # beat_index
        str,  # stripped beat.beat identity
        int,  # literal 0
        str,  # normalized layer-0 file_hash
    ],
    ...
]
```

| Contract item | Actual behavior |
|---|---|
| Input | `CompilationPlan` |
| Output | `_MainVisualFingerprint` |
| Outer type | Tuple |
| Component type | Four-element tuple |
| Component order | `beat_index`, `beat_identity`, `0`, `normalized_file_hash` |
| Beat traversal | `enumerate(plan.beats)` |
| Layer traversal | Filter `beat.layers` for `layer_index == 0` |
| `asset_id` | Not included |
| File path | Not included |
| Asset type | Validated, but not stored in component |
| `role` | Not included |
| Resolved flag | Not included directly |
| Y layers | Not traversed |

## 4. Dynamic Beat Behavior

`_exact_main_visual_fingerprint` iterates `enumerate(plan.beats)`. No fingerprint code branches on Hook, Context, Build, Reveal, CTA, or on a fixed Beat count.

Conceptual 3-Beat result:

```python
(
    (0, beat_0_identity, 0, hash_0),
    (1, beat_1_identity, 0, hash_1),
    (2, beat_2_identity, 0, hash_2),
)
```

Conceptual 5-Beat result:

```python
(
    (0, beat_0_identity, 0, hash_0),
    (1, beat_1_identity, 0, hash_1),
    (2, beat_2_identity, 0, hash_2),
    (3, beat_3_identity, 0, hash_3),
    (4, beat_4_identity, 0, hash_4),
)
```

Every Beat must contain exactly one valid layer-0 main-X asset; otherwise the complete fingerprint operation fails.

The built-in frontend content template happens to define five tracks, but that is not fingerprint logic. The backend helper itself is count-agnostic.

**DYNAMIC_BEAT_FINGERPRINT: PROVEN**

## 5. Beat Identity

### End-to-end origin

```text
Built-in frontend template
    track.id = "hook" / "context" / "build" / "reveal" / "cta"
    track.name = human-readable display label
        ↓
buildTimelineFromTracks()
    beat: track.id
        ↓
RenderDSLRequest.timeline: List[DSLBeatNode]
    DSLBeatNode.beat: str
        ↓
DSLParserNode._compile_plan()
    BeatCompilationResult.beat = node.beat
        ↓
CompilationPlan.beats[*].beat
        ↓
str(beat.beat).strip()
        ↓
fingerprint component[1]
```

Evidence:

- Built-in IDs and display labels are separate at [WorkspaceView.vue:149](</E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:149>).
- Submission uses `beat: track.id`, not `track.name`, at [WorkspaceView.vue:357](</E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:357>).
- `DSLBeatNode.beat` is a plain `str`, not an enum/UUID/database reference, at [schemas.py:259](</E:/dopaworkspace/dopamatrix-desktop/src/api/schemas.py:259>).
- Parser copies `node.beat` into `BeatCompilationResult.beat` at [dsl_parser.py:205](</E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:205>).
- Imported recipe JSON can replace track objects, including IDs, without a stable-ID validation contract at [DslOrchestratorDrawer.vue:548](</E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/DslOrchestratorDrawer.vue:548>).
- Direct API callers can submit any schema-valid string.

Classification:

| Candidate meaning | Finding |
|---|---|
| Display label | No, built-in `track.name` is not submitted |
| Built-in internal template key | Yes, on the normal frontend path |
| Enum | No |
| Stable UUID | No |
| Database ID | No |
| Localized text | Possible for external/imported callers, but not required |
| Arbitrary string | Yes, at backend contract level |
| Role | No; `role` is a separate excluded field |

### Rename scenario

If the actual submitted `beat`/`CompilationPlan.beat` value changes:

```text
"Reveal" → "Product Reveal"
```

then the component changes and the full fingerprint changes, even when every asset hash is unchanged.

If only the frontend display label `track.name` changes while `track.id == "reveal"` remains unchanged, the fingerprint does not change.

**FP-RISK-01 — BEAT_IDENTITY_RENAME_INSTABILITY**

Impact:

- Batch-local uniqueness: normally non-disruptive because all candidates in one request are materialized from the same DSL and therefore use the same Beat identities.
- Historical ledger: serious false-negative risk. The same ordered visual sources can be treated as novel after a recipe/template/API Beat-ID rename, case change, or Unicode representation change.

## 6. Canonicalization

Exact normalization code:

```python
def normalize_file_hash(value: object) -> str:
    """Return the stable exact-content key used by INV-001 planning."""
    return str(value or "").strip().lower()
```

Behavior:

| Input | Result |
|---|---|
| `"ABC"` | `"abc"` |
| `"abc"` | `"abc"` |
| `" ABC "` | `"abc"` |
| `None` | `""` |
| `""` | `""` |
| `"123"` | `"123"` |
| `"00123"` | `"00123"` |
| numeric `123` | `"123"` |
| numeric `0` | `""`, because `0 or ""` selects `""` |
| `"not-a-valid-hash"` | `"not-a-valid-hash"` |

Normalization:

| Operation | Behavior |
|---|---|
| Trim whitespace | Yes |
| Lowercase | Yes |
| Uppercase | No |
| String-cast | Yes, after falsy-value substitution |
| Validate hex | No |
| Validate MD5/SHA length | No |
| Reject missing | Normalizer does not; fingerprint helper rejects the empty normalized result |
| Tag hash algorithm | No |

`ResolvedLayer.file_hash` is schema-typed as `str`, and `LocalAsset.file_hash` is non-nullable, but empty/invalid nonempty formats are not rejected by the fingerprint helper beyond the empty-string check.

Two DB rows or plan layers with the same normalized `file_hash` produce the same fingerprint hash component. Candidate discovery also collapses normalized-equal hashes and preserves the first resolver candidate.

Beat identity canonicalization is separate:

```python
beat_identity = str(beat.beat).strip()
```

It trims outer whitespace, but does not lowercase, Unicode-normalize, or map aliases.

## 7. Ordering Semantics

Plan A:

```text
Beat0 = X
Beat1 = Y
```

Plan B:

```text
Beat0 = Y
Beat1 = X
```

Assuming `X` and `Y` have different normalized hashes, the fingerprints differ.

Order is encoded twice:

1. Outer tuple component order follows `plan.beats`.
2. Every component explicitly contains `beat_index`.

The same asset used at Beat0 versus Beat3 produces a different component because `beat_index` differs. In normal plans, Beat identity will generally also differ.

Reordering complete `(Beat identity, asset)` pairs still changes tuple position and `beat_index`, so equality remains order-sensitive.

## 8. Layer Contract

Valid main-X asset types are determined through `ASSET_REGISTRY`:

```text
video              → X_BASE
scene_master_video → X_STRUCTURE
```

Only the unique layer with `layer_index == 0` contributes.

For:

```text
Layer 0 = main video A
Layer 1 = BGM
Layer 2 = sticker
Layer 3 = SFX
```

only Layer 0 affects the fingerprint.

| Condition | Production behavior |
|---|---|
| Plan has no Beats | Reject with `ValueError` |
| Layer 0 missing | Reject |
| Duplicate layer 0 | Reject, even if duplicates reference the same media |
| Layer 0 has Y/audio/unknown type | Reject |
| Layer 0 has empty normalized hash | Reject |
| Beat identity empty after trim | Reject |
| Beat has only Y layers | Reject |
| One Beat invalid in a multi-Beat plan | Reject the entire fingerprint operation |
| Layer 1+ changes | No fingerprint change |

The Phase 4 `_y_asset_identity` fallback to `asset_id` is unrelated and is not used by the Main Visual Planning Fingerprint.

## 9. Included / Excluded Dimensions

| Dimension | Status | Evidence/meaning |
|---|---|---|
| Beat order | INCLUDED | Outer tuple order and `beat_index` |
| Beat identity | INCLUDED | Stripped `beat.beat` |
| main-X `file_hash` | INCLUDED | Normalized layer-0 hash |
| main-X `asset_id` | EXCLUDED | Used during selection, absent from fingerprint |
| Y layers | EXCLUDED | Not traversed |
| BGM | EXCLUDED | Y layer |
| SFX | EXCLUDED | Y layer |
| VFX | EXCLUDED | Y layer |
| Stickers | EXCLUDED | Y layer |
| TTS | EXCLUDED | Worker/runtime stage |
| Voice | EXCLUDED | Worker/runtime stage |
| Voice model | EXCLUDED | Not read |
| Language | EXCLUDED | Not read |
| Subtitle enablement | EXCLUDED | Not read |
| Subtitle text | EXCLUDED | Not read |
| Aspect ratio | EXCLUDED | Not read |
| Duration | EXCLUDED | Not read |
| Transition | EXCLUDED | Not read |
| Render settings | EXCLUDED | Not read |
| Cover | EXCLUDED | Generated after render |
| CTA text | EXCLUDED | Script/text fields not read |
| Prompt text | EXCLUDED | Not read |
| Final binary encoding | EXCLUDED | Fingerprint precedes render |
| FFmpeg parameters | EXCLUDED | Fingerprint precedes compositor |
| Tenant | EXCLUDED | Planner is scoped externally by tenant DB |
| Project | EXCLUDED | No project field in fingerprint |
| Campaign | EXCLUDED | No campaign field in fingerprint |
| `execution_id` | EXCLUDED | Allocated later |
| `file_sid` | EXCLUDED | Allocated later |
| `task_id` | EXCLUDED | Batch identity, not fingerprint input |

Asset type is **CONDITIONAL** in validation: it must be main-X, but its value is not retained in the tuple.

## 10. Equality Semantics

If:

```text
fingerprint(A) == fingerprint(B)
```

the implementation has proven only that both valid plans have:

- The same Beat count.
- The same ordered sequence of zero-based Beat positions.
- The same stripped `beat.beat` strings at those positions.
- Exactly one valid main-X layer at each position.
- Equal lowercase/trimmed stored layer-0 `file_hash` strings at each position.

It has not independently read or compared the media files during fingerprint generation.

| Claim | Proven by equal fingerprints? |
|---|---|
| Same ordered main-visual planning structure | Yes, for the four defined component fields |
| Same source-file bytes | Only insofar as stored hashes correctly and collision-freely represent immutable files; not independently proven |
| Same final video binary | No |
| Same decoded visual stream | No |
| Perceptually similar video | No |
| Semantically similar creative | No |
| Same audio | No |
| Same subtitles | No |

If:

```text
fingerprint(A) != fingerprint(B)
```

only this is proven:

> At least one component differs in Beat count, tuple position/index, stripped Beat identity, or normalized stored layer-0 hash.

Non-equality does not prove that the source media look different. Re-encodes, crops, two visually identical files, Beat renames, hash-format changes, or stale hashes can all produce inequality without meaningful visual novelty.

Planning fingerprint, rendered hash, perceptual fingerprint, and semantic similarity are distinct contracts.

## 11. Planner Lifecycle

Current exact flow:

```text
Request DSL
  → request-time parse_and_resolve preview CompilationPlan
  → background coordinator
  → discover_main_visual_candidates
  → MainVisualCandidate(asset_id, normalized file_hash)
  → Cartesian product combination
  → _selection_key for examined-combination tracking
  → materialize_with_main_selections
  → authoritative CompilationPlan
  → _exact_main_visual_fingerprint
  → selected hashes vs materialized fingerprint hashes check
  → used_fingerprints membership check
  → accepted plans/fingerprints
  → coordinator recomputes every accepted fingerprint
  → validates positional equality and uniqueness
  → allocates child execution_id/file_sid
  → binds execution + authoritative plan + fingerprint in _ChildWork
  → render_worker receives authoritative plan
  → worker bypasses re-resolution
```

Timing findings:

| Question | Answer |
|---|---|
| Before or after materialization? | After materialization for normal candidates |
| Before or after child identity allocation? | Before |
| Does a duplicate-rejected candidate receive `execution_id`? | No |
| Does an invalid/mismatched candidate receive `execution_id`? | No |
| Is accepted fingerprint recomputed? | Yes, coordinator recomputes all accepted plans |
| Is child identity allocated only after invariant validation? | Yes |
| Is the accepted plan authoritative in worker? | Yes |
| Does worker receive the fingerprint itself? | No |

The coordinator verifies:

```python
computed_fingerprints == planning_result.fingerprints
```

and:

```python
len(set(computed_fingerprints)) == len(computed_fingerprints)
```

before calling `_create_child_executions`.

The same accepted `CompilationPlan` is assigned to `_ChildWork.authoritative_plan`, passed to `render_worker`, and used directly when `plan_is_authoritative=True`. The worker does not re-run the resolver. This is also covered by `test_a1_a2_a3_authoritative_plan_bypasses_resolver_and_raw_dsl_supplies_metadata`.

One observability gap remains: `_ChildWork.visual_fingerprint` is assigned but never passed into `render_worker`, result metadata, logs, or persistence.

## 12. Preview Interaction

A request-time preview can become the first accepted exact plan if:

- It has the same Beat count as the submitted DSL.
- Its fingerprint validates.
- Each preview Beat identity equals the corresponding DSL Beat identity.
- Its layer-0 `asset_id` and normalized hash match a current candidate.
- Candidate space is nonzero.

Fingerprint timing:

1. `_preview_selection` invokes `_exact_main_visual_fingerprint(preview_plan)` for validation.
2. If mapping succeeds, the planner invokes the same helper again to create `preview_fingerprint`.
3. The preview plan/fingerprint is appended before Cartesian enumeration.

Normal candidates and preview use exactly the same fingerprint helper and component semantics. Their eligibility paths differ, but their fingerprint contract does not.

**SAME CONTRACT**

## 13. Runtime Observability

### Directly logged today

| Data | Current status |
|---|---|
| Full planning fingerprint | Not logged |
| Fingerprint digest | Not defined or logged |
| Fingerprint components | Not logged as a unified event |
| Accepted fingerprint | Not logged |
| Duplicate-rejected fingerprint | Not logged |
| Child `task_id` | Logged |
| Child `execution_id` | Logged |
| `child_index` | Logged |
| `file_sid` | Logged |
| Beat identity | Logged by parser in some messages |
| Beat index | Logged by preview/adapter in some messages |
| Selected main asset ID | Logged in locked resolution |
| Selected main hash | Locked resolution logs only a shortened hash |
| Smart-selected main ID/hash | No equivalent unified planner fingerprint log |
| Main file paths | Visible through adapter/debug and full FFmpeg command |
| Full FFmpeg command | Logged |

There is no single event that binds:

```text
task_id
+ execution_id
+ child_index
+ ordered Beat components
+ accepted fingerprint
```

Consequently, sequences such as:

```text
12 → 28 → 24 → 68 → 108
```

had to be reconstructed from the ordered compositor inputs/FFmpeg command and then correlated with LocalAsset or `TaskHistory.prompt_details.children[].timeline`. The compositor logs file paths and execution identity, while TaskHistory stores the resolved timelines, but neither presents the exact planning fingerprint as one explicit event.

## 14. Persistence

The main-visual fingerprint is not persisted in:

- `TaskHistory` columns.
- `prompt_details`.
- `planning_summary`.
- `children` metadata.
- Source asset metadata.
- Output asset metadata.
- `VideoAsset`.
- Any SQLite/other table or migration found in the repository.

`TaskHistory.prompt_details.children[].timeline` does indirectly persist successful workers’ resolved Beat/layer data, including Beat identity, asset ID, and file hash. Engineers can recompute a fingerprint from that data, but the fingerprint, its version, and canonical serialized bytes are not stored.

`_ChildWork.visual_fingerprint` exists only in coordinator memory. It disappears after coordination and is not forwarded to the child result.

The output `file_hash` persisted by this route is a first-64-KiB MD5 of the rendered output. It is not the planning fingerprint.

**CURRENT MAIN-VISUAL FINGERPRINT IS EPHEMERAL**

## 15. Serialization

Current representation:

```text
Python tuple
→ Python set membership
→ Python tuple equality
```

Not found:

- Canonical serialized string.
- Canonical JSON.
- Length-prefixed encoding.
- SHA-256 fingerprint digest.
- `fingerprint_type`.
- `fingerprint_version`.
- Persistent serialization tests.

Python tuple representation is not a durable, language-independent historical-data format.

**CANONICAL_SERIALIZATION_NOT_DEFINED**

## 16. Historical Novelty Suitability

| Scenario | Classification | Reason |
|---|---|---|
| A. Exact same ordered main-asset combination | SUFFICIENT | With unchanged Beat identities and normalized hashes, equality is exact under the current planning contract |
| B. Different DB rows, same normalized hashes | SUFFICIENT | `asset_id` is excluded; discovery also collapses normalized-equal hashes |
| C. Same sources, Beat renamed | NOT SUFFICIENT | Beat identity change creates a false novel result |
| D. Same content re-encoded, different file hash | NOT SUFFICIENT | Stored file hash changes |
| E. Same source cropped/re-edited | NOT SUFFICIENT | New bytes/hash produce a different fingerprint |
| F. Different files that look identical | NOT SUFFICIENT | No perceptual analysis |
| G. Semantically similar creative with different videos | NOT SUFFICIENT | No semantic analysis |

The current fingerprint is suitable for batch-local exact planning-combination uniqueness. It is not yet a safe durable historical contract without identity, hash, serialization, and version hardening.

## 17. Fingerprint Taxonomy

| Layer | Name | Input | Production time | Cost | Equality means | Primary use |
|---|---|---|---|---|---|---|
| L1 | Main Visual Planning Fingerprint | Ordered Beat identities/positions and main-X source identities | After plan materialization, before execution allocation | `O(Beats)`, no media I/O | Same defined planning components | Batch uniqueness, exact combination history |
| L2 | Rendered Exact Content Hash | Final binary bytes or canonical decoded streams | After render | `O(output bytes)` or full decode once | Exact binary equality or exact decoded-stream equality, depending on explicitly named subtype | Output integrity/exact duplicate detection |
| L3 | Perceptual Video Fingerprint | Sampled/decoded visual frames and temporal features | After render/import | Moderate/high decode and feature cost | Distance below a defined perceptual threshold | Near-duplicate visual detection |
| L4 | Semantic Creative Signature | Visual/audio/text embeddings, themes, emotions, concepts | After assets/text are available | Highest model/embedding cost | Semantic distance/similarity, not exact equality | Creative diversity, discovery, thematic repetition control |

L2 binary and decoded-stream hashes must be separate fingerprint types. They do not have the same equality meaning.

## 18. Versioning

Proposed stable engineering name for the current conceptual rule:

```text
main_visual_planning_v1
```

Future records should carry:

```text
fingerprint_type
fingerprint_version
fingerprint_digest
```

A version must be immutable once historical data exists.

A new version is required when changing any of:

- Beat identity semantics.
- Whitespace/case/Unicode canonicalization.
- Source hash algorithm or validation.
- Included axes/layers.
- Component order or schema.
- Canonical serialization.
- Treatment of missing values.
- Tenant/project inclusion policy.

Historical records must never silently compare digests generated under different versions.

## 19. Proposed Canonical Digest

**FUTURE / PROPOSED — not current behavior**

Options:

| Encoding | Assessment |
|---|---|
| Delimiter-separated string | Reject; ambiguous unless every value is escaped correctly |
| Length-prefixed binary components | Safe but bespoke and harder to inspect or implement consistently across languages |
| Canonical JSON | Recommended; inspectable, delimiter-safe, order-preserving, language-independent when rules are explicit |

Recommended flow:

```text
validated ordered components
→ explicit versioned JSON object
→ deterministic canonical UTF-8 JSON bytes
→ SHA-256
→ lowercase hexadecimal digest
```

Example schema:

```json
{
  "fingerprint_type": "main_visual_planning",
  "fingerprint_version": 1,
  "beats": [
    {
      "beat_index": 0,
      "beat_identity": "hook",
      "layer_index": 0,
      "source_hash_algorithm": "md5",
      "normalized_file_hash": "..."
    }
  ]
}
```

Required canonical rules:

- Fixed field names and data types.
- Beat array order is significant.
- UTF-8 encoding.
- Deterministic object-key ordering.
- No insignificant whitespace.
- Explicit Unicode normalization decision.
- Explicit source-hash algorithm.
- No floating-point fields.
- Digest over canonical bytes, not language-native object display.

A recognized canonical JSON profile such as JCS-style canonicalization is safer than an application-specific delimiter format.

## 20. Proposed Runtime Log Contract

**FUTURE / PROPOSED**

Event:

```text
VariantFingerprint
```

Recommended structured fields:

| Field | Logging treatment |
|---|---|
| `task_id` | Full |
| `execution_id` | Full structured field |
| `child_index` | Full |
| `file_sid` | Full |
| `fingerprint_type` | Full |
| `fingerprint_version` | Full |
| `fingerprint_digest` | Full structured field; short form only in human message |
| `beat_count` | Full |
| `beat_index` | Full |
| Stable Beat identity | Full but length-bounded |
| `asset_id` | Full |
| Normalized source hash | Full structured field; shortened in human message |
| Raw video data | Omit |
| Full DSL/prompt | Omit |
| Secrets/tokens | Omit |
| Unbounded manifests | Omit |

Human-readable example:

```text
VariantFingerprint phase=authoritative_worker_start task_id=... child=2
execution_id=... file_sid=7f20a481 type=main_visual_planning version=1
digest=sha256:92b6d1a8c9ef beats=[0:hook#12@a81e…,1:context#28@41fc…,2:build#24@7ca2…]
```

### Timing evaluation

| Point | Recommendation |
|---|---|
| A. Candidate considered | Do not log at INFO; too noisy. Optional sampled DEBUG |
| B. Candidate accepted | Useful for planner diagnostics, but child identity does not yet exist |
| C. Execution identity allocated | Good point to bind digest to child identity |
| D. Worker starts authoritative plan | Best definitive point for “which fingerprint did this child render?” |
| E. Compositor starts | Redundant and too late; compositor should consume an already-audited plan |

Minimal production contract:

- Preserve the existing batch planning summary.
- Emit one INFO `VariantFingerprint` event at authoritative worker start.
- Recompute or validate the digest from the authoritative plan at worker entry.
- Include `task_id`, `execution_id`, `child_index`, `file_sid`, full digest, and ordered bounded components.
- Optionally emit coordinator binding at DEBUG or as an invariant metric.

## 21. Historical Ledger Architecture

**FUTURE / PROPOSED**

Lookup key:

```text
tenant/project scope
+ fingerprint_type
+ fingerprint_version
+ fingerprint_digest
```

The digest should be indexed. Exact novelty lookup becomes a point/index query:

```text
Does an indexed row already exist for this scope, type, version, and digest?
```

Recommended conceptual behavior:

- Tenant/project/campaign scope should be database columns, not silently mixed into the content digest.
- A compound index should cover the complete lookup key.
- Store the canonical component payload or sufficient audit metadata alongside the digest.
- On a digest match, canonical bytes/components may be compared if collision defense is required.
- Never compare different fingerprint versions as equivalent.
- Write the accepted/rendered relationship only at a defined lifecycle point.

No source schema or ledger currently implements this.

## 22. Performance Model

For L1 historical lookup:

```text
Fingerprint construction: O(number_of_beats)
Indexed lookup: expected O(log N) with a B-tree, or implementation-dependent near-O(1) with a hash index
```

It does not require:

```text
O(number_of_historical_videos × video_size)
```

because historical media is not reopened or frame-compared for every candidate.

For L2, full output hashing costs `O(video_size)` once per generated video, not once per historical comparison.

L3/L4 similarity are different workloads. Approximate search can conceptually use:

- ANN/vector indexes.
- HNSW.
- LSH.
- Other perceptual/vector-search structures.

Those layers must not replace exact L1 set/index equality.

## 23. VAR-001 Interaction

Required future selection layering:

```text
resolver eligibility
→ exact fingerprint construction/validation
→ batch-local exact uniqueness
→ balanced axis coverage
→ historical novelty
→ optional perceptual diversity
```

VAR-001 Phase 1 should optimize which unique fingerprints are selected. It must not weaken or bypass:

```python
fingerprint not in used_fingerprints
```

The current architecture can support this layering because it already centralizes:

- Candidate discovery.
- Explicit materialization.
- Fingerprint computation.
- Exact uniqueness.
- Accepted-plan/fingerprint pairing.
- Authoritative worker handoff.

However, the current planner immediately accepts the first unique fingerprints encountered in Cartesian product order. Balanced coverage will need selection/ranking logic around that boundary while retaining exact uniqueness as a hard invariant.

Historical novelty and perceptual diversity are not currently implemented.

## 24. Existing Test Coverage

| Test | File | What it proves |
|---|---|---|
| `test_f1_same_ordered_main_hashes_have_same_fingerprint` | `tests/test_inv001_variant_planning.py` | Equal Beat identities and ordered hashes produce equality |
| `test_f2_one_main_hash_difference_changes_fingerprint` | Same | One main hash change changes fingerprint |
| `test_f3_beat_order_changes_fingerprint` | Same | Beat/asset order changes fingerprint |
| `test_f4_y_layer_difference_does_not_change_level_one_fingerprint` | Same | BGM/Y difference is excluded |
| `test_f5_hash_case_and_whitespace_are_normalized` | Same | Hash lowercasing/trimming |
| `test_f6_missing_conflicting_or_nonvisual_main_fails_validation` | Same | Missing layer 0, duplicate layer 0, and non-main media reject |
| `test_p1_p2_p4_and_structural_repro_plan_four_unique_combinations` | Same | Dynamic 3-Beat planning and four full-combination fingerprints |
| `test_p3_candidate_hash_dedup_preserves_first_resolver_candidate` | Same | Normalized-equal hashes from different candidate rows collapse |
| `test_explicit_locked_selection_fails_fast_if_asset_disappears` | Same | Stale explicit selection rejects during materialization |
| `test_p5_p6_p7_each_tuple_materialized_once_and_terminates_finitely` | Same | Candidate selection keys prevent repeated tuple visits |
| `test_c1_true_capacity_two_does_not_duplicate_fill_request_four` | Same | Capacity shortage does not duplicate-fill |
| `test_c4_preview_is_seeded_only_when_current_and_valid` | Same | Valid preview is accepted first; stale preview is replaced |
| `test_a5_exact_coordinator_binds_unique_plans_after_planning` | Same | Unique authoritative plans reach workers |
| `test_a1_a2_a3_authoritative_plan_bypasses_resolver_and_raw_dsl_supplies_metadata` | Same | Worker renders the accepted authoritative plan |
| `test_ai_draft_exact_policy_schedules_planner_coordinator` | `tests/test_inv001_planning_policy.py` | Exact request carries preview into coordinator |
| `test_ai_draft_direct_render_carries_exact_policy` | Same | Frontend exact-policy route is explicit |
| `test_y6_exact_explicit_materialization_uses_shared_y_dedup` | `tests/test_inv001_y_layer_dedup.py` | Exact materialization retains shared Y dedup behavior |
| `test_batch_size_four_writes_one_stably_ordered_history_and_terminal` | `tests/test_inv001_batch_finalization.py` | Child history is ordered by child index |

Missing or incomplete coverage:

- Explicit 5-Beat fingerprint equality/shape test.
- Arbitrary-length parameterized fingerprint test.
- Direct assertion of the complete four-field component tuple.
- Beat identity rename/case/Unicode normalization tests.
- UI display-name-only rename test.
- Same normalized hash with different `asset_id` tested directly against helper equality.
- Empty `file_hash` test.
- `None`, numeric, invalid-format, and wrong-length hash tests.
- Empty plan and empty Beat identity tests.
- Exact selected-hash/materialized-hash mismatch branch.
- Coordinator rejection of tampered `planning_result.fingerprints`.
- Duplicate fingerprint caused by different candidate selection keys.
- Y exclusion across sticker/VFX/SFX/text-template types, not only BGM.
- Fingerprint persistence absence/shape guard.
- Canonical serialization/version/digest tests, because no such contract exists.
- Runtime child-to-fingerprint log contract test.

## 25. Historical Stability Risks

| Risk | Source-grounded finding | Severity |
|---|---|---|
| Beat rename instability | Submitted `beat` string is included | BLOCKER FOR HISTORICAL LEDGER |
| Built-in display-name dependency | `track.name` is not submitted | NONE |
| Template/recipe ID dependency | `track.id` is submitted and imported IDs are not stability-controlled | BLOCKER FOR HISTORICAL LEDGER |
| Case/Unicode instability | Beat identity only uses `.strip()` | BLOCKER FOR HISTORICAL LEDGER |
| Missing hash | Accepted fingerprints reject missing/empty hashes | NONE |
| Invalid hash format | Nonempty arbitrary strings are accepted | BLOCKER FOR HISTORICAL LEDGER |
| Hash algorithm ambiguity | Algorithm not carried in component | BLOCKER FOR HISTORICAL LEDGER |
| Source MD5 collision strength | DAM source identity currently uses MD5 | BLOCKER FOR HISTORICAL LEDGER |
| Asset content mutation | Fingerprint trusts stored DB hash and does not re-read source files | BLOCKER FOR HISTORICAL LEDGER |
| Serialization undefined | Python tuple only | BLOCKER FOR HISTORICAL LEDGER |
| Cross-version ambiguity | No type/version | BLOCKER FOR HISTORICAL LEDGER |
| Fingerprint ephemeral | No persisted value/index | BLOCKER FOR HISTORICAL LEDGER |
| No structured child fingerprint log | Exact child mapping cannot be read directly | BLOCKER FOR RUNTIME LOGGING |
| Fingerprint not forwarded to worker | `_ChildWork` binding ends at coordinator boundary | BLOCKER FOR RUNTIME LOGGING |
| Tenant/project excluded | Safe if used as indexed scope columns; unsafe if digest alone is treated globally | NON-BLOCKING |
| Dynamic Beat count | Iteration is dynamic | NONE |
| Asset ID excluded | Same normalized content identity intentionally collapses rows | NON-BLOCKING |
| No explicit 5-Beat test | Production code is dynamic, but regression guard is missing | NON-BLOCKING |

## 26. Source Code Map

| Role | File / symbol |
|---|---|
| Frontend built-in Beat IDs | `web_ui/src/views/WorkspaceView.vue::dslTemplates` |
| Frontend DSL submission | `WorkspaceView.vue::buildTimelineFromTracks` |
| Imported recipe identity | `DslOrchestratorDrawer.vue::handleTemplateUpload` |
| Beat request model | `src/api/schemas.py::DSLBeatNode` |
| Backend Beat propagation | `src/api/dsl_parser.py::_resolve_beat`, `_compile_plan` |
| Source-hash normalization | `src/api/dsl_parser.py::normalize_file_hash` |
| Candidate identity | `MainVisualCandidate` |
| Candidate discovery | `DSLParserNode.discover_main_visual_candidates` |
| Explicit plan materialization | `DSLParserNode.materialize_with_main_selections` |
| Fingerprint generation | `src/api/routes_dsl.py::_exact_main_visual_fingerprint` |
| Candidate search key | `src/api/routes_dsl.py::_selection_key` |
| Exact planner | `src/api/routes_dsl.py::_plan_exact_main_visual_variants` |
| Preview mapping | `src/api/routes_dsl.py::_preview_selection` |
| Coordinator invariant | `src/api/routes_dsl.py::render_batch_worker` |
| Authoritative handoff | `_ChildWork` and `render_worker(plan_is_authoritative=True)` |
| TaskHistory persistence | `_child_prompt_details`, `_persist_task_history` |
| Runtime compositor logs | `src/nodes/compositor.py::execute`, `_render_variant` |
| Source file hash | `src/api/routes_assets.py::compute_md5` |
| Quick rendered hash | `src/api/routes_dsl.py::render_worker` output collection |
| Full rendered hash, separate path | `src/api/services.py::_md5_file` |
| Fingerprint tests | `tests/test_inv001_variant_planning.py` |
| Policy/preview route tests | `tests/test_inv001_planning_policy.py` |
| Authoritative execution tests | `tests/test_inv001_variant_planning.py`, `test_inv001_execution_isolation.py` |
| Persistence tests | `tests/test_inv001_batch_finalization.py` |
| Y identity tests | `tests/test_inv001_y_layer_dedup.py` |

## 27. Obsidian-Ready Knowledge Base

# DopaMatrix Fingerprint Architecture

## 1. Why Fingerprints Exist

**CURRENT:** DopaMatrix uses a Main Visual Planning Fingerprint to prevent two accepted children in one exact-planning batch from rendering the same ordered main-X visual combination.

The fingerprint is a planning identity. It is not a rendered-media hash, perceptual fingerprint, or semantic signature.

## 2. Current Main Visual Planning Fingerprint V1

**CURRENT conceptual name:** `main_visual_planning_v1`

Production helper:

```text
src/api/routes_dsl.py::_exact_main_visual_fingerprint
```

Input:

```text
CompilationPlan
```

Runtime output:

```python
tuple[tuple[int, str, int, str], ...]
```

## 3. Canonical Components

For every ordered Beat:

```text
beat_index
stripped Beat identity
literal layer_index 0
lowercase/trimmed main-X file_hash
```

Exact component:

```python
(beat_index, beat_identity, 0, normalized_file_hash)
```

`asset_id` is not included.

## 4. Equality Semantics

Equal fingerprints mean the same ordered Beat positions, stripped Beat identities, and normalized stored main-X hashes.

They do not prove:

- Same final video bytes.
- Same decoded video.
- Same audio or subtitles.
- Perceptual similarity.
- Semantic similarity.

## 5. Dynamic Beat Support

**CURRENT — PROVEN:** The helper iterates `enumerate(plan.beats)` and does not require fixed Hook/Context/Build/Reveal/CTA positions.

Every Beat must have exactly one valid layer-0 main-X asset.

## 6. Included Dimensions

**CURRENT:**

- Beat order.
- Beat index.
- Beat identity.
- Normalized main-X source hash.
- Layer-0/main-X validity as a precondition.

## 7. Excluded Dimensions

**CURRENT:**

- Main asset database ID.
- Y layers, BGM, SFX, VFX, stickers.
- TTS, voice, language, subtitles.
- Prompt/script/CTA text.
- Duration, aspect ratio, transitions.
- FFmpeg settings and binary encoding.
- Cover.
- Tenant/project/campaign.
- Task, execution, and output identities.

## 8. Current Planner Usage

**CURRENT:**

```text
discover candidates
→ enumerate selections
→ materialize CompilationPlan
→ compute fingerprint
→ reject duplicates
→ accept unique plans
→ recompute coordinator invariant
→ allocate child identity
→ render authoritative plan
```

Rejected candidates do not receive child execution identities.

## 9. Runtime Observability Today

**CURRENT:** There is no structured fingerprint event, digest, or direct child-to-fingerprint log.

Engineers must correlate:

- Parser logs.
- Task/execution/file IDs.
- TaskHistory child timelines.
- FFmpeg input paths and commands.

The fingerprint is not passed into the worker.

## 10. Versioning Policy

**FUTURE / PROPOSED:**

Every durable fingerprint must carry:

```text
fingerprint_type
fingerprint_version
fingerprint_digest
```

Changing identity semantics, canonicalization, included dimensions, source-hash rules, or serialization requires a new immutable version.

## 11. Historical Novelty Usage

**FUTURE / PROPOSED:**

Use an indexed lookup on:

```text
tenant/project
+ fingerprint_type
+ fingerprint_version
+ fingerprint_digest
```

Do not reopen and compare every historical video.

## 12. Future Fingerprint Layers

**FUTURE / PROPOSED:**

- L1 — Main Visual Planning Fingerprint.
- L2 — Rendered Exact Content Hash.
- L3 — Perceptual Video Fingerprint.
- L4 — Semantic Creative Signature.

Each layer has distinct inputs and equality semantics.

## 13. Known Risks

**CURRENT:**

- Beat-ID rename instability.
- Beat case/Unicode instability.
- Undefined canonical serialization.
- No explicit version.
- Ephemeral runtime-only representation.
- Unvalidated source hash format/algorithm.
- Stored source hash is trusted without render-time file verification.
- No explicit child fingerprint event.

## 14. Source Code Map

```text
Frontend Beat IDs:
  web_ui/src/views/WorkspaceView.vue

Beat schema:
  src/api/schemas.py::DSLBeatNode

Beat propagation and normalization:
  src/api/dsl_parser.py

Fingerprint:
  src/api/routes_dsl.py::_exact_main_visual_fingerprint

Planner:
  src/api/routes_dsl.py::_plan_exact_main_visual_variants

Coordinator/handoff:
  src/api/routes_dsl.py::render_batch_worker
  src/api/routes_dsl.py::render_worker

Persistence:
  src/api/routes_dsl.py::_persist_task_history

Tests:
  tests/test_inv001_variant_planning.py
  tests/test_inv001_planning_policy.py
  tests/test_inv001_batch_finalization.py
```

## 15. Engineering Rules

1. Batch-local exact uniqueness remains mandatory.
2. Balanced coverage may rank only among exact-unique fingerprints.
3. Do not interpret L1 equality as rendered/perceptual/semantic equality.
4. Do not persist Python tuple display as a historical contract.
5. Define type, immutable version, canonical serialization, and digest first.
6. Use a stable Beat identifier, not a mutable display label.
7. Tag the source-hash algorithm.
8. Scope historical lookup by tenant/project columns.
9. Emit a worker-start event binding child identity to fingerprint digest.
10. Never silently compare different fingerprint versions.

## 28. Review Findings

### A. BLOCKS_RUNTIME_OBSERVABILITY

- **FP-OBS-01:** No full fingerprint, digest, component, accepted, or duplicate-rejected structured event.
- **FP-OBS-02:** `_ChildWork.visual_fingerprint` is not forwarded to `render_worker`.
- **FP-OBS-03:** No authoritative worker-start fingerprint validation/log binding.
- **FP-OBS-04:** Engineers must reconstruct child composition from TaskHistory and FFmpeg inputs.

### B. BLOCKS_HISTORICAL_LEDGER

- **FP-RISK-01:** Submitted Beat identity rename changes fingerprint.
- **FP-LEDGER-01:** Fingerprint is ephemeral and not persisted.
- **FP-LEDGER-02:** Canonical serialization is undefined.
- **FP-LEDGER-03:** Fingerprint type/version are undefined.
- **FP-LEDGER-04:** Beat identity is an arbitrary string without stability, case, or Unicode rules.
- **FP-LEDGER-05:** Source-hash algorithm/format is not encoded or validated.
- **FP-LEDGER-06:** Current DAM identity is MD5-based.
- **FP-LEDGER-07:** Fingerprint trusts stored hash/file binding without source revalidation.
- **FP-LEDGER-08:** No indexed tenant/project/type/version/digest ledger exists.

### C. NON_BLOCKING_FOR_VAR001_PHASE1

- Current fingerprint is dynamic-Beat and deterministic for a valid materialized plan.
- Current `used_fingerprints` set provides the necessary batch-local hard uniqueness boundary.
- Balanced coverage can operate over exact-unique fingerprints.
- Y/audio/text/render dimensions remain intentionally outside L1.
- Tenant/project can remain external scope columns.
- Missing 5-Beat, rename, empty-hash, and coordinator-tamper regression tests should be added later, but do not invalidate the current Phase 1 uniqueness primitive.
- Historical-ledger hardening is not a prerequisite for batch-local balanced coverage.

## 29. Final Classification

**FINGERPRINT_CONTRACT_NEEDS_HARDENING**

## 30. Next-Step Recommendation

**Option 2: FP-001A — Contract Hardening, then Runtime Observability**

Recommended order:

1. Freeze stable Beat identity semantics.
2. Define source-hash algorithm/validity and mutation assumptions.
3. Define `main_visual_planning_v1`.
4. Define canonical JSON bytes and SHA-256 digest.
5. Add type/version/digest contract tests.
6. Add the child-bound authoritative worker-start log event.
7. Defer persistence/schema work to the later Historical Ledger phase.
8. Proceed with VAR-001 Phase 1 while preserving current batch-local exact uniqueness.

This hardening is required for a durable historical ledger and clean digest-based observability. It does not require reopening INV-001 correctness or delaying balanced batch-local selection design.

## 31. Final Git Status

Final safety checks:

```text
git status --short
```

Output: empty.

```text
git diff --stat
```

Output: empty.

**NO MODIFICATIONS. No code, tests, schemas, migrations, logs, commits, or pushes were created.**