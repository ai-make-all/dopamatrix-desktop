# INV-001 — Duplicate Video Generation

**Project:** DopaMatrix Desktop  
**Investigation Type:** Release-blocking defect / Matrix batch generation  
**Current Working Branch:** `fix/creative-duplicate-detection`  
**Priority:** P0 for the next Philippines seed-user build  
**Status:** Investigation ready; reproduction evidence pending  
**Owner Model Flow:** ChatGPT (scope/architecture gate) → Codex (repo-level read-only investigation / high-risk code change) → Sonnet (bounded implementation/tests/docs as assigned)

---

## 1. Business Background

The Philippines marketing team needs a new DopaMatrix installer for next week's activity. Their immediate requirement is to generate multiple usable video variants in one batch.

DopaMatrix 1.0 has previously exhibited a release-blocking failure mode:

- `batch_size > 1`
- multiple videos are requested in the same batch
- two or more outputs can be completely identical
- in earlier testing, a batch of 4 could produce 4 identical videos

This defect directly blocks the seed-user workflow because a "matrix batch" that returns duplicated outputs has little or no usable UA testing value.

### Current release objective

This investigation does **not** attempt to complete the full Matrix Engine 1.5 roadmap.

The immediate goal is:

> Identify the verified root cause of exact duplicate outputs and implement the smallest safe fix required to prevent a batch from silently producing completely identical videos.

---

## 2. Known Facts

The following are treated as known project facts for this investigation:

1. The current working branch is `fix/creative-duplicate-detection`.
2. DopaMatrix 1.0 does not yet have a formal `Variant Planning` + `Diversity Gate` layer.
3. The product has observed batch-level duplicate video output in real testing.
4. DopaMatrix Desktop uses Tauri + local FastAPI/Python backend + SQLite + FFmpeg/render workers.
5. Rendering throughput should remain concurrent where safe; duplicate prevention must not be implemented by serializing all video rendering.
6. Philippines-specific defaults are not the deduplication engine. The fix must remain a generic Matrix Engine capability.

### Not yet verified

The following are **not** facts until proven by reproduction evidence or current source code:

- whether all duplicated outputs have identical file hashes
- whether duplicated videos overwrite the same output path
- whether render cache is involved
- whether multiple variants receive the same seed
- whether the Asset Resolver repeatedly selects the same Top-1 asset
- whether batch-level asset reservation is missing
- whether `Render Intent` objects are identical
- whether a race around `usage_count` contributes to the problem
- whether locked/fallback asset behavior is involved

Do not convert any item above into an implementation assumption without evidence.

---

## 3. Core Design Principles

### 3.1 Controlled Variation, not random variation

A mature Matrix Engine should not solve diversity by "running the same generator N times with more randomness."

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

For the current hotfix, implement only the parts of this flow that are required by the verified root cause.

### 3.2 Planning and rendering are different concurrency domains

If batch-level reservation becomes necessary:

```text
select / check / reserve
    = short, atomic, serialized where required

FFmpeg / render / AI generation
    = concurrent long-running work
```

Do **not** fix the bug by forcing all render workers to run serially.

### 3.3 Reservation is not long-term usage

If current code proves that asset reuse is caused by concurrent selection, distinguish:

```text
batch reservation
    = "this asset is already claimed by another variant in this batch"

historical usage
    = "this asset has been used in completed outputs over time"
```

Do not rely only on a usage counter that updates after rendering completes.

### 3.4 No Philippines-specific hardcoding

Do not introduce logic such as:

```python
if market == "philippines":
    special_duplicate_logic()
```

Market/language/platform presets may later configure a generic Diversity Policy, but duplicate prevention must remain generic.

---

## 4. Current Release Scope

### P0 — Must investigate before changing architecture

Codex must determine the current behavior of:

1. `batch_size` input and batch loop
2. batch/variant identity
3. seed/randomness generation
4. Asset Resolver behavior
5. `usage_count` / asset usage update timing
6. Render Intent / timeline construction
7. output filename/path construction
8. render cache and cache key, if any
9. concurrency boundary between planning/selection and rendering
10. whether batch-level reservation already exists in any form

### P0 — Current success criterion

At minimum:

- a requested batch must not silently return multiple file-level identical outputs
- outputs must not be duplicated because of path overwrite or cache reuse
- each output must remain traceable to its batch/task/variant identity or equivalent current-project identifiers
- if the system cannot produce the requested number of valid variants, it must fail/return partial/warn rather than silently duplicate output

### Conditional P1 — Implement only if root cause requires it

Possible additions include:

- independent variant seed / variation key
- batch-scoped `used_assets` or reservation
- Render Intent canonical hash
- batch duplicate gate
- candidate exhaustion handling

These are **conditional**, not pre-approved database/schema work.

---

## 5. Explicit Non-Goals for the Philippines Hotfix

Do not expand this task into the complete Matrix Engine 1.5/2.0 roadmap.

Unless the verified root cause requires otherwise, this release does **not** include:

- CLIP embedding similarity
- video pHash/perceptual deduplication
- MMR / Max-Min diversity ranking
- cross-batch fatigue control
- full semantic signature architecture
- automatic asset-cluster recognition
- full Story DSL 2.0 changes
- full Semantic Timeline refactor
- Matrix Lab redesign
- Philippines-specific preset UI
- variation-strength UI
- complete candidate-capacity UI
- broad Review Queue redesign
- unrelated brand refactoring
- unrelated webhook refactoring

Do not create new database tables merely because they appear in the long-term design notes. First prove they are necessary.

---

## 6. Root-Cause Hypothesis Map

These are investigation hypotheses, not implementation instructions.

| ID | Hypothesis | Evidence to collect | Typical fix if verified |
|---|---|---|---|
| H1 | Same seed/randomness for multiple variants | compare seed/random values per generated item | make seed/variation identity variant-specific |
| H2 | Asset Resolver always selects same Top-1 candidate | log selected asset IDs and candidate scores | batch-aware selection / used-assets penalty or reservation |
| H3 | Usage updates only after render completion, creating a race | inspect selection → usage update timing | reserve at selection time, keep transaction short |
| H4 | Locked mode forces same asset set | inspect DSL/recipe mode and `asset_hashes` | explicit locked-mode behavior / partial result / controlled fallback |
| H5 | Fallback repeatedly selects same default asset | inspect fallback path and selected IDs | batch-aware fallback / fail with candidate shortage |
| H6 | Render Intents are identical | canonicalize and compare effective render inputs | regenerate/reselect before render or add uniqueness gate |
| H7 | Cache key omits variant-changing inputs | inspect cache key composition and cache hits | include effective variant/render inputs in key |
| H8 | Output path/name collision causes overwrite/reuse | compare task IDs, output paths and file timestamps | unique path per generated item |
| H9 | Worker independently re-resolves assets after planning | trace resolver calls in worker path | freeze resolved render input before enqueue |
| H10 | Candidate pool is actually too small | record candidate pool size after filters | partial/warning instead of silent duplication |

---

## 7. Reproduction Evidence Package — REQUIRED BEFORE FORMAL CODE DIAGNOSIS

Before Codex produces its formal root-cause report, reproduce the issue once on the current branch and attach evidence.

### 7.1 Environment

Fill in:

```text
Date/time:
Git branch: fix/creative-duplicate-detection
Git commit:
Run mode: tauri dev / packaged installer
OS:
Tenant:
Project:
Recipe / template:
```

### 7.2 Exact user steps

Record the shortest reproducible flow from opening the product to output creation.

Template:

```text
1. Launch DopaMatrix.
2. Select tenant/project: ...
3. Open: ...
4. Import/select assets: ...
5. Select recipe/template: ...
6. Set batch size: ...
7. Set other options: ...
8. Click: ...
9. Wait for all tasks to finish.
10. Observe outputs: ...
```

### 7.3 Input assets

Record exact filenames and, if visible, asset IDs/hashes:

```text
Asset 1:
Asset 2:
Asset 3:
...
```

Do not rename the source files after reproduction until the investigation is complete.

### 7.4 Output evidence

For each generated output:

```text
Output 1
- UI/task ID:
- filename:
- full path:
- size:
- duration:
- created time:

Output 2
...
```

### 7.5 Duplicate classification

Classify the observed duplicate:

**Type A — file-level exact duplicate**

- SHA-256 is identical

**Type B — visually identical but binary different**

- SHA-256 differs
- content appears the same

**Type C — path/overwrite suspicion**

- multiple tasks reference the same output path/name
- earlier file appears replaced or reused

Do not use "looks the same" as the only diagnostic fact if file-level evidence can be collected.

### 7.6 Screenshots

Capture, where available:

- Matrix/batch settings before generation
- task list while generating
- completed result cards
- duplicate outputs shown side-by-side
- output filenames/paths
- any error/warning
- relevant console/backend log window

Use stable filenames such as:

```text
INV-001-01-batch-settings.png
INV-001-02-task-list.png
INV-001-03-duplicate-results.png
INV-001-04-output-files.png
INV-001-05-backend-log.png
```

### 7.7 Logs

Preserve the log interval covering:

```text
batch submission
→ task creation
→ asset resolution
→ render intent/timeline creation
→ render enqueue
→ FFmpeg/render completion
→ output path returned
```

Do not trim away task IDs, timestamps, asset IDs or output paths.

---

## 8. Codex Gate 1 — Read-Only Repository Investigation

**Do not run this gate until Section 7 reproduction evidence has been collected.**

Codex may pre-read this document earlier, but the formal investigation report should be based on both:

1. this engineering context
2. the real reproduction evidence
3. the current repository source code

### Codex instruction

```text
You are the DopaMatrix Creative Engine Debug Engineer.

CURRENT BRANCH
fix/creative-duplicate-detection

PRIMARY CONTEXT
Read:
doc/investigations/INV-001-duplicate-video-generation.md

Also inspect the reproduction evidence referenced in Section 7.

TASK MODE
READ ONLY.
Do not modify source code, schema, configuration, tests, docs, or git history.

OBJECTIVE
Trace the exact current code path that can produce duplicate videos when batch_size > 1, and separate verified code facts from hypotheses.

REQUIRED INVESTIGATION

1. Locate where batch_size enters the backend.
2. Locate the exact batch loop / task creation path.
3. Determine what uniquely identifies each generated item:
   - task_id
   - batch_id if present
   - variant_id if present
   - variant_index or equivalent
4. Trace seed/randomness generation and compare how it changes across batch items.
5. Trace Asset Resolver calls:
   - candidate construction
   - filtering
   - scoring
   - Top-1 or sampling behavior
   - fallback
   - locked/smart mode
6. Determine when usage_count or equivalent asset-use state is updated.
7. Determine whether any batch-scoped used-assets/reservation mechanism exists.
8. Trace the effective Render Intent / timeline / FFmpeg input for each batch item.
9. Trace output filename and output path creation.
10. Search for render/result caching:
    - cache key
    - cache lookup
    - cache reuse
    - whether variant-changing inputs participate in the key
11. Determine whether render workers re-resolve or mutate assets after task creation.
12. Map the reproduction evidence to the relevant log/code path.

IMPORTANT CONSTRAINTS

- Do not assume MatrixBatch, MatrixVariant, BatchAssetReservation or new DB tables are required.
- Do not implement Variant Planner yet.
- Do not introduce pHash, CLIP embedding, MMR or semantic similarity.
- Do not hardcode Philippines-specific behavior.
- Do not serialize the full FFmpeg/render pipeline as a workaround.
- Do not create a new git branch.
- Do not merge any branch.

REQUIRED REPORT

Produce:
"INV-001 Codex Read-Only Investigation Report"

The report must contain:

A. Executive finding
B. Reproduction evidence interpretation
C. Current code call chain
D. Key files and exact functions
E. Current identifiers/data passed per batch item
F. Root-cause hypotheses table with status:
   - VERIFIED
   - LIKELY
   - DISPROVED
   - NOT ENOUGH EVIDENCE
G. Verified root cause(s), if proven
H. Evidence for each verified cause
I. Smallest safe fix options, ranked
J. Whether DB/schema changes are actually necessary
K. Files that would need modification
L. Regression risks
M. Additional evidence needed, if root cause is not yet proven

Do not implement any fix.
```

---

## 9. Required Codex Report Quality Bar

A valid report must cite current project files/functions, not just architecture theory.

Bad:

```text
The project probably needs a Batch Diversity Ledger.
```

Good:

```text
backend/path_x.py:function_y creates each batch item.
resolver/path_z.py:function_a is called independently for every item.
function_a sorts candidates descending and returns candidates[0].
usage is updated only in function_b after render completion.
Therefore all concurrently created items can select the same asset before any usage update occurs.
```

The report must distinguish:

```text
OBSERVED USER FACT
CURRENT CODE FACT
INFERENCE
RECOMMENDATION
```

If Codex cannot prove the root cause, it must request targeted instrumentation rather than redesign the Matrix Engine.

---

## 10. Decision Gate After Codex Report

No implementation begins automatically after the report.

ChatGPT / project owner reviews the report and selects one of the following paths.

### Path A — Output path / overwrite bug

Implement only:

- unique output identity/path
- collision protection
- regression verification

Do not introduce Ledger/Planner unless separately required.

### Path B — Cache-key bug

Implement only:

- correct cache identity
- cache invalidation/compatibility as needed
- regression verification

### Path C — Identical Render Intent

Implement the smallest pre-render uniqueness mechanism required by current architecture.

Possible scope:

- independent variation/seed
- canonical Render Intent hash
- retry/reselect
- explicit partial result if no valid alternative exists

### Path D — Concurrent asset-selection race

Implement the smallest batch-scoped reservation model compatible with current code.

Preferred principle:

```text
short check + reserve transaction
then concurrent render
```

Do not put FFmpeg/AI/file scanning inside SQLite transactions.

### Path E — Candidate shortage / locked-mode behavior

Do not silently duplicate.

Return a clear partial/failure/warning state appropriate to the existing API/UI.

### Path F — Multiple verified causes

Sequence the fix by causal layer:

```text
identity/path/cache correctness
→ planning/selection correctness
→ reservation if required
→ user-facing shortage behavior
```

Avoid a broad rewrite.

---

## 11. Hotfix Acceptance Criteria

Final acceptance criteria will be refined after root-cause confirmation, but the release must at least prove:

1. The documented reproduction no longer produces exact duplicate outputs.
2. Batch generation does not overwrite/reuse the same output path unintentionally.
3. Multiple generated items remain independently traceable in logs/state.
4. `batch_size = 1` remains compatible with existing behavior.
5. `batch_size = 4` succeeds when the current system has enough valid variation capacity.
6. If the system cannot generate the requested number safely, it does not silently clone output to reach the requested count.
7. No frequent `database is locked` regression is introduced.
8. Existing render concurrency is not unnecessarily serialized.
9. A focused regression note/test is added for INV-001 before release.

For the first Philippines RC, file-level exact-duplicate prevention is release-blocking. Perceptual/semantic diversity scoring is not.

---

## 12. Git and Release Constraints

Current work remains on:

```text
fix/creative-duplicate-detection
```

During investigation:

- do not merge `refactor/dopamatrix-brand-unification`
- do not merge back to `feature/v1.1-webhook-telegraf`
- do not create another Matrix 1.5 feature branch
- keep investigation and fix commits small and reviewable

Suggested history:

```text
docs: add INV-001 duplicate video investigation context
fix: <verified minimal duplicate root-cause fix>
test: add INV-001 regression coverage
```

### Important release-integration note

The current fix branch was created from the webhook feature line, while DopaMatrix brand migration exists on a separate branch.

Therefore, after the duplicate fix passes regression, the Philippines installer must be built from an explicitly reviewed integration state that contains both:

- the required DopaMatrix brand changes
- the verified duplicate-video fix

Do not assume the current fix branch alone is the final installer source.

The exact merge/release branch strategy will be decided after the hotfix is verified.

---

## 13. Agent Responsibilities

### ChatGPT

Responsible for:

- business priority
- scope control
- architecture gate
- distinguishing facts vs assumptions
- reviewing Codex reports
- approving the minimal implementation path
- release decision support

### Codex

Primary for:

- repository-wide code archaeology
- root-cause localization
- high-risk backend changes
- concurrency / SQLite / main-generation-chain changes
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

One task → one primary model → report/review → next task.

---

## 14. Future Matrix Engine 1.5 Backlog — NOT THIS HOTFIX

Once the Philippines release blocker is resolved, the broader 1.5 roadmap may include:

- formal Matrix Plan
- formal Variant Plan
- Diversity Policy
- Batch Diversity Ledger
- canonical Render Intent hash
- opening 3-second signature
- asset-cluster constraints
- candidate-capacity checking
- controlled `test_goal`
- variation strength
- structured partial-generation responses
- Review Queue variant-difference explanation
- persistent reservation state/recovery

Later 1.8/2.0 directions may include:

- automatic asset clustering
- pHash
- CLIP embedding
- subtitle/hook semantic similarity
- MMR / Max-Min diversity
- cross-batch fatigue
- attribution-driven regeneration

These are target capabilities, not assumptions about what must be implemented for INV-001.

---

## 15. Working Summary

For this release:

> Do not solve "video diversity" as a broad architecture project before proving why the current batch produces exact duplicates.

The immediate sequence is:

```text
INV-001 context
    ↓
reproduce + preserve evidence
    ↓
Codex read-only code investigation
    ↓
verified root cause
    ↓
minimal fix plan
    ↓
implementation
    ↓
focused regression
    ↓
reviewed brand + fix integration
    ↓
Philippines RC installer
```

The long-term product principle remains:

> DopaMatrix Matrix Engine should evolve from "batch rendering" toward "controlled variation": plan meaningful differences first, then render.
