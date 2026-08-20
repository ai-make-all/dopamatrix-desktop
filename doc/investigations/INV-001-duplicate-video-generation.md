# INV-001 — Duplicate Video Generation

**Project:** DopaMatrix Desktop  
**Investigation Type:** Root-cause investigation / Matrix batch diversity and execution integrity  
**Current Working Branch:** `fix/creative-duplicate-detection`  
**Priority:** P0 product-quality defect  
**Status:** Reproduction evidence complete; ready for Codex Gate 1 read-only investigation  
**Current Evidence Scope:** AI Draft mode  
**Owner Model Flow:** ChatGPT (scope / architecture gate) → Codex (repo-level root-cause investigation / high-risk implementation) → Sonnet (bounded implementation / tests / docs as assigned)

---

## 1. Problem Background

DopaMatrix Matrix generation has exhibited a recurring batch-level duplicate-content defect.

Observed behavior includes:

- `batch_size > 1`
- multiple generated outputs inside the same batch
- multiple outputs receiving the same effective visual asset combination
- visually identical outputs even when the final MP4 file hashes differ
- in some cases, fully identical final MP4 files

The defect has now been formally reproduced and documented in:

- `INV-001-repro-001`
- `INV-001-repro-002`
- `INV-001-repro-003`
- `INV-001-experiment-summary.md`

This investigation is no longer constrained by an immediate event-release deadline.

The objective is therefore not to produce a time-boxed workaround.

### Current investigation objective

The goal is:

> Determine the complete verified root cause of duplicate Variant generation in the current DopaMatrix architecture, including the relationship among candidate-pool handling, batch execution, asset selection, execution identity, Context isolation and rendering.

After the root cause is verified:

> Implement the smallest architecturally correct fix that resolves the verified causal mechanism without unnecessary Matrix Engine redesign.

The investigation may cross multiple modules if the evidence and current code show that the causal chain crosses those modules.

---

## 2. Evidence State

### 2.1 Verified facts

The following are treated as verified facts for the current INV-001 investigation:

1. The current working branch is:

   `fix/creative-duplicate-detection`

2. Formal reproduction evidence currently covers:

   `AI 智能起草（AI Draft）`

3. Repro001 and Repro002 both reproduce within-batch visual duplication with:

   `batch_size = 4`

4. Repro001 contains a verified visual duplicate pair.

5. Repro002 contains:

   - a three-output visual duplicate group
   - a two-output full exact duplicate pair

6. Duplicate visual content is already present at the `master_video` stage.

7. Different master output filenames can still contain identical decoded video content.

8. Multiple generated executions can receive the same complete Beat-level asset combination and identical `GlobalTimeline`.

9. The Build slot contains only one candidate:

   `24.mp4`

   Therefore Build reuse is expected in the current reproduction.

10. Hook and Context contain multiple user-visible candidates.

11. Repro001 and Repro002 show shared task/history identity anomalies and:

   `UNIQUE constraint failed: task_history.task_id`

12. Batch executions have also been observed using shared TTS/subtitle intermediate writable paths.

13. Repro003 (`batch_size = 1`) provides a single-item execution control, but it is not a strict one-variable batch-size A/B experiment because its AI Draft prompt differs from Repro001 and Repro002.

14. Final/master output-path collision is not required to explain the verified visual duplicate.

15. Final-file SHA256 alone is not sufficient to detect visual-content duplication.

### 2.2 Not yet verified

The following remain source-code investigation questions:

- whether candidate resolution occurs before or after batch expansion
- whether a resolved plan is copied to multiple executions
- whether multiple executions share mutable Context state
- whether random seeds are identical
- whether selection is deterministic Top-1
- whether `usage_count` timing creates a race
- whether batch-level reservation exists
- whether effective resolver-valid candidate capacity is smaller than the visible candidate pool
- whether fallback/default behavior forces reuse
- whether cache contributes to any part of the defect
- whether shared execution identity directly causes visual duplication
- whether TTS/subtitle path sharing directly causes audio divergence
- whether AI Draft and Blind Mode share the same root cause
- whether current code has a distinct variant/execution identity
- whether current candidate selection state is batch-local, execution-local, or globally shared

Do not convert any item above into an implementation assumption without source-code evidence.

---

## 3. Core Design Principles

### 3.1 Controlled Variation, not random variation

A mature Matrix Engine should not solve diversity by simply running the same generator N times with more randomness.

The target principle is:

> Plan intentional differences first, then render.

Long-term target flow:

```text
Matrix Intent
    ↓
Variant Planning
    ↓
Diversity Constraints / Gate
    ↓
Asset Resolution
    ↓
Render Intent / Timeline
    ↓
Pre-render duplicate checks
    ↓
Concurrent Render
    ↓
Post-render validation
```

These principles are architectural guardrails, not pre-approved implementation requirements.

INV-001 must first determine the current root cause.

Only the portions required by the verified causal mechanism should be implemented during the initial fix.

### 3.2 Planning and rendering are different concurrency domains

If batch-level reservation becomes necessary:

```text
select / check / reserve
    = short, atomic, serialized where required

FFmpeg / render / AI generation
    = concurrent long-running work
```

Do **not** fix the defect by forcing all render workers to run serially.

### 3.3 Reservation is not long-term usage

If current code proves that asset reuse is caused by concurrent selection, distinguish:

```text
batch reservation
    = "this asset / combination is already claimed by another execution in this batch"

historical usage
    = "this asset has been used in completed outputs over time"
```

Do not assume that a historical usage counter alone can provide batch-local uniqueness.

### 3.4 No market-specific hardcoding

Do not introduce logic such as:

```python
if market == "philippines":
    special_duplicate_logic()
```

Market / language / platform presets may later configure a generic Diversity Policy, but duplicate prevention must remain a generic Matrix Engine capability.

### 3.5 Investigation scope may be broad; implementation scope must be causal

The investigation may follow the complete real call chain across frontend, backend, database and renderer.

The implementation scope must still be determined by the verified root cause.

> Investigation scope can be wide. Implementation scope must remain evidence-driven.

---

## 4. Current Investigation Scope

### 4.1 Required investigation scope

Codex may trace across all code required to explain the causal chain, including:

- AI Draft UI candidate-pool representation
- frontend submission payload
- DSL serialization / transformation
- `batch_size` handling
- execution creation
- identity generation
- Context creation / copying / sharing
- candidate filtering and selection
- randomness / seed handling
- usage / fatigue state
- batch-local selection state
- timeline construction
- master render inputs
- output filename / path generation
- intermediate TTS/subtitle resources
- history persistence
- cache, if actually present
- Blind Mode architecture for read-only comparison after the AI Draft path is understood

The investigation scope is determined by the real call chain, not by a pre-selected list of files.

### 4.2 Investigation success criterion

Gate 1 succeeds when the report can explain, with current-code evidence:

> Why multiple executions in one batch can produce the same effective visual asset combination and timeline, causing identical master-video content.

It must also classify the shared identity / TTS / history anomalies as:

- direct root cause
- contributing defect
- or independent defect

### 4.3 Implementation remains gated

No architectural mechanism is pre-approved.

Possible mechanisms such as:

- Variant ID
- independent seed
- batch reservation
- batch-local `used_assets` state
- combination fingerprint
- timeline / render-plan hash
- Diversity Gate
- database schema changes

must be justified by the verified root cause.

---

## 5. Explicit Non-Goals for INV-001 Root-Cause Investigation

Do not expand INV-001 into the complete Matrix Engine 1.5 / 2.0 roadmap.

Unless the verified root cause requires otherwise, this investigation does **not** pre-approve:

- CLIP embedding similarity
- video pHash / perceptual deduplication
- MMR / Max-Min diversity ranking
- cross-batch fatigue control
- full semantic signature architecture
- automatic asset-cluster recognition
- full Story DSL 2.0 changes
- full Semantic Timeline refactor
- Matrix Lab redesign
- market-specific diversity presets
- variation-strength UI
- complete candidate-capacity UI
- broad Review Queue redesign
- unrelated brand refactoring
- unrelated webhook refactoring

Do not create new database tables merely because they appear in long-term design notes.

First prove they are necessary.

---

## 6. Root-Cause Investigation Map

These statuses reflect reproduction evidence only.

Codex must confirm the underlying current-code mechanism.

| ID | Candidate mechanism | Current status |
|---|---|---|
| H1 | Same seed/randomness across executions | `NOT ENOUGH EVIDENCE` |
| H2 | Deterministic / repeated candidate selection | `NOT ENOUGH EVIDENCE` |
| H3 | `usage_count` race between concurrent executions | `NOT ENOUGH EVIDENCE` |
| H4 | Candidate pool becomes smaller after internal filtering | `NOT ENOUGH EVIDENCE` |
| H5 | Fallback/default behavior forces reuse | `NOT ENOUGH EVIDENCE` |
| H6 | Multiple outputs receive identical effective asset sequence + timeline | `VERIFIED` |
| H7 | Cache contributes to duplicated planning/rendering | `NOT ESTABLISHED` |
| H8 | Final/master output-path collision is required for visual duplication | `DISPROVED AS NECESSARY EXPLANATION` |
| H9 | Each worker independently re-resolves candidates | `NOT ENOUGH EVIDENCE` |
| H10 | Candidate selection occurs once before batch expansion and the resolved plan is copied | `NOT ENOUGH EVIDENCE` |
| H11 | Shared mutable Context contributes to selection duplication | `NOT ENOUGH EVIDENCE` |
| H12 | Shared task/execution identity exists in batch runs | `VERIFIED` |
| H13 | Shared TTS/subtitle writable paths exist | `VERIFIED` |
| H14 | Identity/path defects directly cause visual duplication | `NOT ENOUGH EVIDENCE` |
| H15 | AI Draft and Blind Mode share the same root cause | `NOT ENOUGH EVIDENCE` |

Additional mechanisms may be added if current source code reveals a causal path not listed here.

This table is not an exhaustive root-cause taxonomy.

---

## 7. Completed Reproduction Evidence Package

Formal evidence collection is complete.

Read:

1. `doc/investigations/evidence/INV-001-experiment-summary.md`

2. `doc/investigations/evidence/INV-001-repro-001/INV-001-repro-001.md`

3. `doc/investigations/evidence/INV-001-repro-002/INV-001-repro-002.md`

4. `doc/investigations/evidence/INV-001-repro-003/INV-001-repro-003.md`

Each reproduction directory contains its own evidence such as:

- screenshots
- backend/frontend logs
- file SHA256 results
- decoded-video hashes
- decoded-audio hashes
- decoded master-video hashes

### Evidence authority

The experiment summary is the canonical cross-run interpretation.

The individual repro documents and raw logs are the canonical detailed evidence.

If a summary statement and raw evidence appear inconsistent, the raw evidence must be re-checked before drawing a conclusion.

### Current formal evidence scope

All three formal reproduction runs use:

`AI 智能起草（AI Draft）`

The evidence package does not yet formally establish the root cause of duplicate behavior in other generation modes.

---

## 8. Codex Gate 1 — Read-Only Root-Cause Investigation

Reproduction evidence is complete.

The detailed Gate 1 execution instruction is supplied separately at runtime to Codex.

The runtime Gate 1 instruction is authoritative if it differs from older investigation notes.

Core requirements:

- `READ ONLY`
- inspect the experiment summary and reproduction evidence before implementation
- trace the complete real call chain
- do not restrict investigation to a pre-selected backend function
- distinguish evidence / code fact / inference / recommendation
- identify the earliest duplicate point
- classify primary and secondary defects
- do not implement a fix during Gate 1
- if root cause cannot be proven statically, request targeted instrumentation or a controlled Repro004
- do not infer Blind Mode root cause from AI Draft evidence alone

Gate 1 output:

`INV-001 Codex Read-Only Root Cause Report`

---

## 9. Required Codex Report Quality Bar

A valid report must cite current project files / functions, not just architecture theory.

Bad:

```text
The project probably needs a Batch Diversity Ledger.
```

Good:

```text
backend/path_x.py:function_y creates each batch execution.

resolver/path_z.py:function_a receives the candidate list after batch expansion.

function_a reads the same usage state for all concurrent executions and
returns the same highest-scored asset before any batch-local selection state
is updated.

Therefore multiple executions can select the same candidate before any
selection is visible to the others.
```

The exact example above is illustrative only.

Codex must use the real project implementation.

The report must distinguish:

```text
OBSERVED EVIDENCE
CURRENT CODE FACT
INFERENCE
RECOMMENDATION
```

If Codex cannot prove the root cause, it must request targeted instrumentation rather than redesign the Matrix Engine.

A valid report should answer not only:

> where the duplicate appears

but also:

> what exact current-code mechanism permits it to occur.

---

## 10. Decision Gate After Codex Report

No implementation begins automatically after the Gate 1 report.

ChatGPT / project owner reviews the report first.

The following are example decision paths, not an exhaustive root-cause taxonomy.

If Codex proves a different causal mechanism, the implementation plan should follow the verified code path rather than force the result into one of these examples.

### Path A — Candidate resolution occurs once before batch expansion

Possible implementation direction:

- move or repeat the appropriate planning/selection step at the correct execution boundary
- ensure each execution receives its intended independent Variant input
- add regression verification

Do not introduce Ledger / Planner unless separately required.

### Path B — Concurrent candidate-selection race

Possible implementation direction:

- introduce the smallest batch-scoped state / reservation mechanism compatible with current code
- keep check + reserve short
- allow expensive rendering to remain concurrent

Do not put FFmpeg / AI / file scanning inside a long SQLite transaction.

### Path C — Deterministic / identical execution state

Possible implementation direction:

- correct variant/execution identity
- correct seed / variation state if proven relevant
- ensure mutable Context is isolated where required
- add regression verification

### Path D — Candidate shortage / filtering collapse

Possible implementation direction:

- make effective capacity explicit
- do not silently clone an existing Variant
- return partial / warning / failure behavior appropriate to current API/UI

### Path E — Cache / reuse bug

Possible implementation direction:

- correct cache identity
- ensure all variant-changing inputs participate where required
- add compatibility/invalidation behavior only if necessary

### Path F — Multiple verified causes

Sequence the fix by causal layer.

A likely shape may be:

```text
identity / Context correctness
→ candidate planning / selection correctness
→ batch-local diversity state if required
→ persistence / intermediate-path correctness
→ user-facing shortage behavior
```

But the actual sequence must follow the verified code path.

Avoid broad rewrites.

---

## 11. Post-Fix Acceptance Criteria

Final acceptance criteria will be refined after root-cause confirmation.

At minimum, the fix must prove:

1. The documented batch reproduction no longer produces unintended duplicate effective visual plans when valid alternatives exist.

2. Visual duplicate validation must not rely only on final-file SHA256.

3. `batch_size = 1` remains compatible with existing behavior.

4. `batch_size = 4` remains concurrent where safe.

5. A batch must not silently clone an already-selected Variant merely to satisfy requested batch size.

6. When valid diversity capacity is insufficient, behavior must be explicit rather than silently duplicative.

7. Generated executions must remain independently traceable in logs/state.

8. Shared writable intermediate-path races must be resolved if Codex proves them unsafe.

9. History persistence must not produce identity collisions under supported batch execution.

10. No frequent `database is locked` regression is introduced by the fix.

11. Focused INV-001 regression coverage must be added before release.

12. The verified Repro001 / Repro002 duplicate scenarios must be rerun after the fix.

Perceptual / semantic similarity systems such as CLIP or pHash are not required for the initial exact visual-plan duplicate fix unless the verified root cause shows otherwise.

---

## 12. Git and Release Constraints

Current work remains on:

```text
fix/creative-duplicate-detection
```

During Gate 1 investigation:

- do not merge `refactor/dopamatrix-brand-unification`
- do not merge back to `feature/v1.1-webhook-telegraf`
- do not create another Matrix 1.5 feature branch
- do not modify source code during the read-only investigation
- keep later investigation/fix commits small and reviewable

Suggested future history after Gate 1 review:

```text
docs: finalize INV-001 investigation evidence
fix: <verified duplicate root-cause fix>
test: add INV-001 regression coverage
```

### Release integration note

The duplicate fix will be validated on this branch first.

Branch integration, brand migration and installer packaging are downstream release-management tasks.

They must not constrain or bias Codex Gate 1 root-cause investigation.

The current fix branch must not automatically be treated as the final installer source.

---

## 13. Agent Responsibilities

### ChatGPT

Responsible for:

- business priority
- scope control
- architecture gate
- distinguishing facts vs assumptions
- reviewing Codex reports
- approving the implementation path
- preventing premature architecture expansion
- release decision support

### Codex

Primary for:

- repository-wide code archaeology
- root-cause localization
- candidate-pool lifecycle tracing
- batch / execution / Context analysis
- concurrency / SQLite / main-generation-chain analysis
- high-risk backend changes after Gate 1 approval
- reviewing difficult failures

### Sonnet

Best used for bounded tasks such as:

- focused helper functions
- tests and fixtures
- documentation
- structured API response changes
- small UI changes
- secondary code review

### Collaboration rule

Do not let Codex and Sonnet simultaneously modify the same set of files.

One task → one primary model → report / review → next task.

---

## 14. Future Matrix Engine Roadmap — NOT PRE-APPROVED BY INV-001

Potential future Matrix Engine capabilities may include:

- formal Matrix Plan
- formal Variant Plan
- Diversity Policy
- Batch Diversity Ledger
- canonical Render Intent / effective-plan hash
- opening 3-second signature
- asset-cluster constraints
- candidate-capacity checking
- controlled `test_goal`
- variation strength
- structured partial-generation responses
- Review Queue variant-difference explanation
- persistent reservation state / recovery
- automatic asset clustering
- pHash
- CLIP embedding
- subtitle / hook semantic similarity
- MMR / Max-Min diversity
- cross-batch fatigue
- attribution-driven regeneration

These are target capabilities, not assumptions about what must be implemented for INV-001.

The existence of this roadmap must not be used to reverse-engineer the answer to the current defect.

---

## 15. Cross-Mode Note

Users have also observed duplicate-video behavior in other generation modes, including Blind / highly automated generation flows.

However, the current formal INV-001 evidence package covers only:

`AI Draft`

Therefore:

- Codex may perform a read-only architecture comparison across modes
- Codex may identify shared downstream infrastructure
- Codex may identify mode-specific candidate / resolver logic
- Codex may identify the earliest common convergence point

But Codex must **not** claim that different modes share the same root cause unless supported by source-code proof or additional formal evidence.

A future shared Diversity Control layer may be appropriate, but it is not pre-approved by INV-001.

---

## 16. Working Summary

INV-001 is now in root-cause investigation phase.

Current sequence:

```text
engineering context
    ↓
completed reproduction evidence
    ↓
experiment summary
    ↓
Codex Gate 1 read-only source investigation
    ↓
verified causal chain
    ↓
human architecture review
    ↓
fix design
    ↓
implementation
    ↓
focused regression
    ↓
release integration
```

The objective is not to force the smallest possible patch.

The objective is:

> The smallest architecturally correct fix that fully addresses the verified root cause.

The long-term product principle remains:

> DopaMatrix Matrix Engine should evolve from batch rendering toward controlled variation: meaningful Variant differences should be intentional, traceable and verifiable before rendering.

### Final investigation principle

> Investigation scope can be wide. Implementation scope must remain evidence-driven.

Do not implement Matrix Engine 1.5 merely because it is architecturally attractive.

Do not artificially restrict the investigation to a local hotfix merely because the defect was originally discovered under release pressure.

First prove the real causal chain.
