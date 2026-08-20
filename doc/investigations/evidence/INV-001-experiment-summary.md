# INV-001 — Experiment Summary

**Investigation:** Duplicate Video Generation  
**Branch:** `fix/creative-duplicate-detection`  
**Formal reproduction runs:** 3  
**Generation mode tested:** `AI 智能起草（AI Draft）`  
**Status:** Evidence collection complete / Codex Gate 1 ready

---

## 1. Executive Summary

INV-001 has been reproduced in two independent `batch_size = 4`
AI Draft runs.

The evidence confirms that the duplicate-video defect is not limited to
final MP4 container identity.

Two duplicate classes have been observed:

1. `VISUAL CONTENT DUPLICATE`
   - different final MP4 binaries may still contain identical decoded video

2. `FULL EXACT DUPLICATE`
   - final file SHA256, decoded video and decoded audio can all be identical

Most importantly, decoded-video hashes of the corresponding `master_video`
files are already identical.

Therefore the visual duplicate is already present before final:

- TTS/audio mixing
- subtitle burn-in
- final MP4 muxing/container output

The verified visual-duplication boundary is therefore at or before:

effective asset selection
→ timeline / effective render-plan construction
→ master-video render

The exact upstream cause remains unverified and requires Codex source-code
analysis.

---

## 2. Experiment Matrix

| Run | Mode | Prompt | Batch Size | Candidate Pools | Result |
|---|---|---|---:|---|---|
| Repro001 | AI Draft | Prompt A + `@hook:汽车减震器` | 4 | Hook 4 / Context 2 / Build 1 | 2 of 4 outputs are visual duplicates |
| Repro002 | AI Draft | Prompt B + `@hook:汽车减震器` | 4 | Hook 4 / Context 2 / Build 1 | 3 of 4 are visual duplicates; 2 are full exact duplicates |
| Repro003 | AI Draft | Prompt C + `@hook:汽车减震器` | 1 | Hook 4 / Context 2 / Build 1 | Single-item execution control |

All three runs use:

- tenant: `testduplicate`
- same DAM asset set
- same Beat candidate-pool structure
- same BGM
- same rendering options
- fresh application/backend run
- same Git commit:
  `965ed0564306d670c78c3454b8ba42764516c1c6`

---

## 3. User-Controlled Candidate Pools

The formal INV-001 reproductions do NOT use unrestricted automatic retrieval
from the entire DAM.

The operator manually defines the allowed Beat-level candidate pools before
rendering.

### Hook
semantic constraint = hook:汽车减震器
Effective backend candidate pool:
- `12.mp4`
- `13.mp4`
- `16.mp4`
- `58.mp4`

Candidate count:

`4`

### Context
explicit physical candidates:
- `18.mp4`
- `28.mp4`

Candidate count:

`2`

### Build
explicit physical candidates:
- `24.mp4`

Candidate count:

`1`

### BGM

- `44444.mp3`

Theoretical user-visible visual combination count:

`4 × 2 × 1 = 8`

This value represents only the visible candidate combinations.

The effective number of combinations considered valid by the current
selection implementation after internal filtering, scoring, usage state,
randomness or other rules remains:

`TO BE VERIFIED BY CODEX`

The repeated use of `24.mp4` is expected because Build contains only one
candidate.

The diagnostically important duplication occurs in Beat slots that contain
multiple candidates.

---

## 4. Repro001 Result

Requested:

`batch_size = 4`

Effective generated visual sequences include:

- `13.mp4 → 18.mp4 → 24.mp4`
- `58.mp4 → 28.mp4 → 24.mp4`
- `13.mp4 → 28.mp4 → 24.mp4`
- `13.mp4 → 28.mp4 → 24.mp4`

Verified duplicate pair:

- `final_en_db4d3533.mp4`
- `final_en_6451b32e.mp4`

Both use:

`13.mp4 → 28.mp4 → 24.mp4`

Both have the same:

- GlobalTimeline
- decoded master-video SHA256
- decoded final-video SHA256

Their decoded audio SHA256 values differ.

Their final file SHA256 values also differ.

Classification:

`VERIFIED VISUAL CONTENT DUPLICATE`

Repro001 therefore proves that binary file inequality does not guarantee
visual Variant diversity.

---

## 5. Repro002 Result

Requested:

`batch_size = 4`

Three generated outputs use:

`12.mp4 → 18.mp4 → 24.mp4`

with the same GlobalTimeline:

`beat_actual_starts=[0.0, 14.419, 28.452]`

Those three outputs have identical decoded final-video SHA256 and identical
decoded master-video SHA256.

Therefore:

`3 / 4 outputs = VERIFIED VISUAL CONTENT DUPLICATE GROUP`

Within this group:

- `final_en_470778f4.mp4`
- `final_en_13e26247.mp4`

also have identical:

- final file SHA256
- decoded-video SHA256
- decoded-audio SHA256
- decoded master-video SHA256
- effective visual asset sequence
- GlobalTimeline

Classification:

`VERIFIED FULL EXACT DUPLICATE`

Repro002 is the strongest reproduction of INV-001.

---

## 6. Repro003 — Single-Item Execution Control

Requested:

`batch_size = 1`

One effective visual sequence was generated:

`16.mp4 → 28.mp4 → 24.mp4`

Observed runtime topology:

one execution chain
→ one TTS/subtitle artifact set
→ one GlobalTimeline
→ one master video
→ one final video

No within-batch duplicate comparison is possible because only one output
exists.

No `UNIQUE constraint failed: task_history.task_id` error was observed in
the collected Repro003 log.

Repro003 is therefore classified as:

`SINGLE-ITEM EXECUTION CONTROL`

It is NOT proof that the duplicate defect cannot exist in any single-item
code path.

---

## 7. Verified Duplicate Boundary

### VERIFIED

Visual duplication exists at the `master_video` stage.

Repro001:

`2 master videos`
have identical decoded-video SHA256.

Repro002:

`3 master videos`
have identical decoded-video SHA256.

Therefore the following are NOT required to explain the primary visual
duplicate:

- final output filename collision
- final MP4 container metadata
- final muxing
- final TTS/audio mixing
- subtitle burn-in

The primary visual duplicate must already exist by the time the effective
master render inputs / timeline are constructed.

---

## 8. Related Verified Execution / Identity Defects

In both `batch_size = 4` reproductions, multiple render executions are
observed using the same shared task identity when persisting history.

The backend reports:

`UNIQUE constraint failed: task_history.task_id`

Batch runs also show shared TTS/subtitle intermediate-path behavior.

These are treated as:

`VERIFIED SECONDARY EXECUTION / IDENTITY DEFECTS`

Their causal relationship to duplicate asset selection is NOT yet proven.

Codex must determine whether:

- they share the same upstream cause as visual duplication
- they are independent concurrency defects
- or they amplify one another

---

## 9. Experimental Control and Limitations

### Shared conditions across all three runs

- same tenant
- same DAM asset set
- same `@hook:汽车减震器` constraint
- same manually defined Beat candidate pools
- same rendering options
- same generation mode: AI Draft
- same Git commit
- fresh application/backend run before each reproduction

### Changed conditions

- natural-language AI Draft prompt differs between runs
- Repro001: `batch_size = 4`
- Repro002: `batch_size = 4`
- Repro003: `batch_size = 1`

Therefore Repro003 is NOT a strict one-variable batch-size A/B experiment.

The evidence supports comparison of:

multi-output execution behavior
vs
single-output execution behavior

but does NOT by itself prove that:

- `batch_size`
- concurrency
- shared Context
- random seed
- usage_count
- candidate scoring
- absence of reservation

is the root cause.

Those mechanisms remain source-code investigation targets.

---

## 10. Current Evidence Status

| Question | Status |
|---|---|
| Does duplicate visual content really occur? | `VERIFIED` |
| Can final MP4 files differ while visual content is identical? | `VERIFIED` |
| Can completely identical final MP4 files occur? | `VERIFIED` |
| Does visual duplication already exist at master-video stage? | `VERIFIED` |
| Can multiple generated items receive the same complete Beat asset combination? | `VERIFIED` |
| Is final/master filename collision required to explain the visual duplicate? | `NO` |
| Does batch_size=4 show shared task/history identity anomalies? | `VERIFIED` |
| Does batch_size=1 show the same history collision in collected evidence? | `NOT OBSERVED` |
| Is concurrency proven as the root cause? | `NO` |
| Is shared Context proven as the root cause? | `NO` |
| Is identical random seed proven? | `NO` |
| Is deterministic Top-1 selection proven? | `NO` |
| Is usage_count race proven? | `NO` |
| Is missing batch reservation proven as root cause? | `NO` |
| Is candidate exhaustion proven? | `NO` |
| Is cache involved? | `NOT ESTABLISHED` |

---

## 11. Formal Investigation Boundary for Codex Gate 1

Codex should investigate upstream of the verified master-video duplicate.

Priority trace:

`submit-dsl`
→ batch request / execution expansion
→ execution identity / Context creation
→ Beat-level asset selection
→ candidate filtering / scoring / randomness / usage state
→ effective timeline / render-plan construction
→ master render

A separate but related trace should investigate:

execution identity
→ TTS/subtitle intermediate paths
→ task_history persistence

The purpose of Gate 1 is to determine the causal relationship between these
two areas.

No implementation should begin until the root-cause report is reviewed.

---

## 12. Scope Limitation

All three formal INV-001 reproduction runs in this evidence package use:

`AI 智能起草（AI Draft）`

Duplicate behavior has not yet been formally reproduced and documented here
for other generation modes.

Therefore this evidence package must NOT be used to claim that another mode
shares the same root cause.

Architecture comparison with other modes may be performed by Codex in
read-only mode, but any cross-mode root-cause conclusion requires separate
evidence or source-code proof.

---

## 13. Next Step

Evidence collection for Codex Gate 1 is complete.

Next action:

`Codex Read-Only Root Cause Investigation`

If Codex cannot distinguish the remaining candidate mechanisms from static
source analysis, a targeted instrumentation run or strict frozen-DSL
batch-size control may be added as Repro004.

No additional reproduction is required before the initial Codex Gate 1
review.