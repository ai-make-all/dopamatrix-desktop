# VAR-001
# Phase 1C-B
# Balanced Real-Media Runtime Acceptance Report

## 1. Git / Source Baseline

- Branch: `feature/var-001-variation-policy`
- HEAD: `4a2d6d6de66d2d7dcd8a9b96bc7fbe56ac44f25e`
- HEAD commit: `feat(var-001): activate balanced planning for AI draft`
- Stage A worktree: clean
- Phase 1A, Phase 1B, and Phase 1C-A commits were present at HEAD.
- Frontend source retained `exact_main_visual` and added/selected `exact_main_visual_balanced` for the successful formal AI Draft path.
- Backend schema retained all three policies: `legacy`, `exact_main_visual`, and `exact_main_visual_balanced`.
- Backend routing retained the old exact planner for `exact_main_visual` and selected the balanced planner for `exact_main_visual_balanced`.

## 2. Backend Runtime Provenance

- Port `127.0.0.1:8000` listener PID: `2632`
- Listener process: `D:\Python\Python312\python.exe main.py`
- Listener parent PID: `7776`
- Parent process: `E:\dopaworkspace\dopamatrix-desktop\venv_build\Scripts\python.exe main.py`
- Process start: `2026-08-29 10:27:40 +08:00`
- Phase 1C-A commit time: `2026-08-29 10:17:23 +08:00`
- `WorkspaceView.vue` modification time: `2026-08-29 09:48:32 +08:00`
- Development `main.py` uses `uvicorn.run("main:app", ..., reload=True)`.

The serving process was started from the current workspace after the Phase 1C-A source and commit existed.

`CURRENT_VAR001_SOURCE_RUNTIME_PROVEN`

Runtime classification: `CURRENT_SOURCE_PYTHON`.

## 3. Frontend / Policy Provenance

Stage A confirmed that Vite's normal port `5173` was not listening and no workspace Vite/Node process was active. Codex did not start the frontend. The human subsequently started it and executed exactly one formal AI Draft, 5-Beat, batch-4 task.

The committed policy path is:

```text
AI Draft success
-> BALANCED_MAIN_VISUAL_PLANNING_POLICY
-> exact_main_visual_balanced
-> orchestratorVariantPlanningPolicy
-> DslOrchestratorDrawer generic pass-through
-> blindFission({ variantPlanningPolicy })
-> submit-dsl.variant_planning_policy
-> backend balanced-policy route
-> _plan_exact_main_visual_balanced_variants_from_db
```

Neither the Loguru window nor TaskHistory contains a direct `variant_planning_policy` field for the target task.

`DIRECT_RUNTIME_POLICY_FIELD_NOT_PERSISTED`

Policy provenance therefore rests on the committed current-source chain, proven current-source backend process, and the human-confirmed formal AI Draft action. No direct persisted policy field is claimed.

## 4. Pre-Run Log Baseline

- Baseline time: `2026-08-29T10:34:55.6107367+08:00`
- Active log: `C:\Users\chenp\AppData\Local\DopaMatrixOrg\DopaMatrix\Logs\dopamatrix_2026-08-29.log`
- Baseline byte offset: `757`
- Baseline counts:
  - `VariantFingerprint`: 0
  - `FINGERPRINT_OBSERVABILITY_MISSING`: 0
  - `FINGERPRINT_OBSERVABILITY_MISMATCH`: 0
  - `FINGERPRINT_OBSERVABILITY_FAILED`: 0
  - `VARIANT_PLANNING_FAILED`: 0
  - `INSUFFICIENT_UNIQUE_CAPACITY`: 0
  - `PLANNING_SEARCH_LIMIT_REACHED`: 0
- Latest pre-run task: `4c584137-7ee8-429b-9d98-b44f1fd783ec`
- Pre-run `dopamatrix_testduplicate.db` TaskHistory count/max id: `10 / 10`

All runtime evidence below was isolated from bytes after offset 757.

## 5. Target Task

- Tenant: `testduplicate`
- Task ID: `07a81ec5-8647-449e-a829-b1b8af80acdc`
- TaskHistory id: `11`
- TaskHistory created: `2026-08-29 02:41:30.185335` (SQLite UTC; `10:41:30 +08:00`)
- First authoritative event: `2026-08-29 10:40:09 +08:00`
- Duration: `80.4s`
- Requested: 4
- Planned: 4
- Succeeded: 4
- Failed: 0
- Warning codes: empty
- Terminal result: succeeded

Only one new TaskHistory row appeared across the tenant databases after the Stage A baseline. The target window is unambiguous.

## 6. VariantFingerprint Events

Exactly four target-task events were present.

| Child | execution_id | file_sid | SHA-256 digest | Beats | Match | Components | Truncated flags |
|---:|---|---|---|---:|---|---:|---|
| 0 | `28ff62eb-92fd-4b66-8890-8b66f66c1fe3` | `28ff62eb` | `884c831c7caa7a50ac286d61443bad7ef23a03568e47610938cb3c42f43b7bd1` | 5 | true | 5 | false / false |
| 1 | `34e08280-8168-478c-aa5f-b2c6fc4b4c8a` | `34e08280` | `53bd8bb63a2beff9058065c513dc77983a4193ec7aa04175071eb3577a9d7f4f` | 5 | true | 5 | false / false |
| 2 | `34642fb0-98db-484f-a41c-081d261eb376` | `34642fb0` | `7c41e3f2fc9cc6b667b1a658fd4309f904a44b29181e41fb8204e18bd19e9508` | 5 | true | 5 | false / false |
| 3 | `efd2ae4d-6c0e-4789-bb62-5a1b814d3859` | `efd2ae4d` | `6b0cecfdc7a47d7c6752f636c6ac434a6b6feab17dab49ed5d8536cc387d90f3` | 5 | true | 5 | false / false |

Every event had:

- `event = VariantFingerprint`
- `phase = authoritative_worker_start`
- `fingerprint_type = main_visual_planning`
- `fingerprint_version = 1`
- `source_hash_algorithm = md5`
- a valid 64-character lowercase hexadecimal SHA-256 digest
- `beat_count = 5`
- `planner_fingerprint_match = true`
- `components_truncated = false`
- `component_fields_truncated = false`

Child counts were `{0: 1, 1: 1, 2: 1, 3: 1}`.

`VARIANT_FINGERPRINT_EXACTLY_ONCE_PASS`

## 7. Planner / Worker Agreement

All four authoritative worker recomputations matched their planner-provided tuples.

Post-baseline target window:

- `FINGERPRINT_OBSERVABILITY_MISSING`: 0
- `FINGERPRINT_OBSERVABILITY_MISMATCH`: 0
- `FINGERPRINT_OBSERVABILITY_FAILED`: 0

`PLANNER_WORKER_FINGERPRINT_AGREEMENT_PASS`

## 8. Execution Isolation

- Shared task ID: `07a81ec5-8647-449e-a829-b1b8af80acdc`
- Unique execution IDs: 4/4
- Unique file SIDs: 4/4
- Child indices: `0, 1, 2, 3`
- Child outcomes: succeeded x4
- Voice, VTT, ASS, master, final, and cover filenames are child-scoped by execution ID and/or file SID.
- No output-path collision was observed.

## 9. Full Fingerprint Uniqueness

- Digests collected: 4
- Valid SHA-256 digests: 4
- Unique digests: 4

`FULL_FINGERPRINT_UNIQUENESS_PASS`

## 10. Candidate Pool Evidence

TaskHistory persists:

- first-success resolved timeline
- child resolved timelines
- planning summary
- child execution metadata and outputs

It does not persist the submitted `StoryDSLPayload` candidate selectors or the exact request-time per-Beat candidate pools. The persisted timelines contain selected resolved layers, not all eligible candidates. Re-running discovery from current DAM state would not be authoritative request-time evidence and was not performed.

`CANDIDATE_POOL_EVIDENCE_NOT_PERSISTED`

`POOL_CAPACITY_CLASSIFICATION_UNAVAILABLE`

Consequently, no Beat is formally labelled `FIXED_BY_CAPACITY`, and theoretical global optimality is not claimed.

## 11. Selected Axis Histograms

The authoritative fingerprint components produced these selected histograms:

### Beat 0 — hook

- `f0a5c247219ff997f6bdf9800e5e96dd` (`13.mp4`): 1
- `e1d29ce2e193377c8b561e998ff0036d` (`58.mp4`): 1
- `846de2afceaf8677a4e7bcdb680762ec` (`12.mp4`): 1
- `969c8e2660ad513d7fa52ebb8b05d18b` (`16.mp4`): 1
- Unique selected: 4
- Selected count: 4

### Beat 1 — context

- `df00ae61ef305f355027e7fa8070142b` (`18.mp4`): 2
- `08a1691d53b489f44eaab7e9db24fd38` (`28.mp4`): 2
- Unique selected: 2
- Selected count: 4

### Beat 2 — build

- `0e1afdd45dcc40f3235e800c445755b8` (`24.mp4`): 4
- Unique selected: 1
- Selected count: 4

### Beat 3 — reveal

- `4a401508673b74f0817403b3e210cf15` (`55.mp4`): 2
- `e405c756bcaa27c30c6cf58c4f25907a` (`68.mp4`): 2
- Unique selected: 2
- Selected count: 4

### Beat 4 — cta

- `9f442bc76dfcbc1a6f205cbfd063de73` (`03333.mp4`): 2
- `05aafeb34a45642cab1dd44706d96b4f` (`108.mp4`): 2
- Unique selected: 2
- Selected count: 4

Ordered accepted sequences:

```text
child0: 13 -> 18 -> 24 -> 55 -> 03333
child1: 58 -> 28 -> 24 -> 68 -> 108
child2: 12 -> 28 -> 24 -> 68 -> 03333
child3: 16 -> 18 -> 24 -> 55 -> 108
```

## 12. Coverage Evaluation

Observed selected-axis distribution is the strong balanced pattern expected from the established fixture:

```text
Beat0: 1/1/1/1
Beat1: 2/2
Beat2: 4 selected from one observed source
Beat3: 2/2
Beat4: 2/2
Full fingerprints: 4/4 unique
```

No avoidable repetition is visible inside the accepted selected set. However, because eligible request-time pool sizes were not persisted, zero-count eligible candidates and the theoretical optimum cannot be independently reconstructed. Runtime coverage is therefore positive but capacity-qualified.

## 13. Leading-Axis Evaluation

Historical exact-control Beat 0 used one selected source four times. The balanced run used four distinct Beat 0 hashes across four children.

```text
Historical exact Beat0 unique sources: 1
Current balanced Beat0 unique sources: 4
Observed improvement: +3 unique selected sources
```

This is strong real-media evidence that leading-axis lexicographic starvation was removed for the accepted batch. It is not a strict causal A/B result because resolver ordering contains randomness and the request-time pool was not persisted.

## 14. Preview Evidence

TaskHistory has no explicit request-preview identity or `preview_is_child_0` field. Child 0 is the first persisted child and its resolved timeline is used as the top-level successful timeline, but that does not independently prove preview lineage.

Runtime preview lineage: `NOT PERSISTED / NOT PROVEN`.

This is not a failure because Phase 1A/1B automated tests already prove the preview contract.

## 15. Real Media Outputs

All required artifacts exist and have non-zero sizes.

| file_sid | Master bytes | Final bytes | Cover bytes |
|---|---:|---:|---:|
| `28ff62eb` | 11,037,286 | 11,336,121 | 77,227 |
| `34e08280` | 9,111,408 | 9,346,721 | 119,410 |
| `34642fb0` | 10,345,868 | 10,720,842 | 135,559 |
| `efd2ae4d` | 28,807,426 | 28,420,520 | 178,332 |

- Masters: 4/4
- Finals: 4/4
- Covers: 4/4
- TaskHistory aggregate outputs: 4

## 16. TTS / Subtitle / Compositor / Cover / BGM

- TTS MP3 and VTT: present for all four execution IDs.
- Subtitle ASS: present for all four execution IDs.
- Master compositor completion: 4/4.
- Final compositor completion: 4/4.
- Cover extraction: 4/4.
- Final commands used one BGM source (`F:\test\44444.mp3`) alongside the child voice track.
- No duplicate-BGM evidence was observed.
- Post-baseline application log contained no `WARNING` or `ERROR` lines.

## 17. Optional FFmpeg Sanity

LocalAsset read-only lookup mapped every fingerprint asset ID/hash to its source path. The first five master inputs matched the five authoritative fingerprint components in order for all children:

| Child | Fingerprint source order | FFmpeg main-input order | Result |
|---:|---|---|---|
| 0 | `13,18,24,55,03333` | `13,18,24,55,03333` | PASS |
| 1 | `58,28,24,68,108` | `58,28,24,68,108` | PASS |
| 2 | `12,28,24,68,03333` | `12,28,24,68,03333` | PASS |
| 3 | `16,18,24,55,108` | `16,18,24,55,108` | PASS |

Each master command then had one BGM/audio input after the five main-video inputs.

Temporal evidence also passed: all four VariantFingerprint events occurred at `10:40:09`, before the first TTS and compositor activity for the batch.

## 18. Warning / Error Audit

Post-baseline target window counts:

- `VARIANT_PLANNING_FAILED`: 0
- `INSUFFICIENT_UNIQUE_CAPACITY`: 0
- `PLANNING_SEARCH_LIMIT_REACHED`: 0
- fingerprint missing/mismatch/failed diagnostics: 0
- child failures: 0
- TaskHistory warning codes: empty
- Loguru `WARNING`: 0
- Loguru `ERROR`: 0

No VAR, FP, INV, or render regression was observed.

## 19. Historical Exact Control Comparison

This is a historical reference comparison, not a strict causal A/B experiment.

| Dimension | Historical `exact_main_visual` | Current `exact_main_visual_balanced` |
|---|---|---|
| Beat0 | `16 x4` — 1 unique | `12/13/16/58 x1` — 4 unique |
| Beat1 | `18 x1, 28 x3` | `18 x2, 28 x2` |
| Beat2 | `24 x4` | `24 x4` |
| Beat3 | `55 x2, 68 x2` | `55 x2, 68 x2` |
| Beat4 | `03333 x3, 108 x1` | `03333 x2, 108 x2` |
| Full fingerprint uniqueness | 4/4 | 4/4 |
| Render success | 4/4 | 4/4 |

## 20. Acceptance Gates

| Gate | Result | Evidence |
|---|---|---|
| A — Current source runtime provenance | PASS | Current workspace Python/reload process, started after Phase 1C-A source |
| B — Balanced AI Draft policy provenance | PASS | Committed source chain + human formal AI Draft; direct field not persisted |
| C — 5-Beat batch-4 target identification | PASS | One new task, four events, five components each |
| D — Four authoritative children | PASS | Four child identities and TaskHistory children |
| E — VariantFingerprint exactly once x4 | PASS | One event for each child index 0..3 |
| F — Planner/worker match true x4 | PASS | Four `true`, zero diagnostics |
| G — Full fingerprint uniqueness 4/4 | PASS | Four valid, unique SHA-256 digests |
| H — Balanced selected-axis distribution | PARTIAL | Ideal observed selected pattern; pool sizes not persisted |
| I — Leading-axis diversity improvement | PASS (observed) | Beat0 selected uniqueness improved 1 to 4 |
| J — Execution isolation | PASS | Unique execution IDs/file SIDs and scoped artifacts |
| K — Real media outputs 4/4 | PASS | Four masters, finals, and covers, all non-zero |
| L — No FP/INV/render regression | PASS | Zero diagnostics/failures; FFmpeg alignment 4/4 |
| M — No `VARIANT_PLANNING_FAILED` | PASS | Zero post-baseline occurrences |

## 21. Coverage Classification

The accepted distribution is strongly balanced and exactly matches the expected selected pattern, including four-way Beat0 exposure. Nevertheless, the request-time eligible pools were not persisted, so theoretical optimality including unused eligible candidates cannot be independently proven.

`BALANCED_COVERAGE_RUNTIME_PARTIAL`

## 22. Review Findings

### VAR1CB-RF-01 — Candidate-pool evidence is not persisted

Severity: acceptance-evidence limitation; not a runtime correctness failure.

Impact: prevents formal calculation of per-Beat `P`, `q`, `r`, zero-count eligible candidates, and theoretical optimum for this historical task. It does not invalidate the successful balanced-planner chain, observed distribution, exact uniqueness, or real-media results.

No implementation fix was made during this read-only acceptance.

## 23. Final Classification

All hard runtime, uniqueness, worker-agreement, execution-isolation, media-output, and FFmpeg-alignment gates passed. The classification is partial only because candidate-pool persistence is insufficient to prove theoretical coverage optimality after the fact.

`VAR001_PHASE1CB_REAL_MEDIA_ACCEPTANCE_PARTIAL`

## 24. Final Git Status

Expected and permitted Stage B change only:

```text
?? doc/investigations/variation/VAR-001-Phase1C-B-Balanced-Real-Media-Runtime-Acceptance-Report.md
```

No production or test source was modified. No commit or push was performed.
