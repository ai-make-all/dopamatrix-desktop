## 7. Reproduction Evidence Package — REQUIRED BEFORE FORMAL CODE DIAGNOSIS

Before Codex produces its formal root-cause report, reproduce the issue once on the current branch and attach evidence.

#### Control-run scope

Repro003 uses `batch_size = 1`.

It is used as a single-item execution control, but it is not a strict
one-variable batch-size A/B experiment because its AI Draft prompt differs
from Repro001 and Repro002.

See:

`../INV-001-experiment-summary.md`

for the full cross-run comparison.

### 7.1 Environment

Fill in:

```text
Date/time:2026-08-15
Git branch: fix/creative-duplicate-detection
Git commit:965ed0564306d670c78c3454b8ba42764516c1c6
Run mode: tauri dev + manually started Python backend
OS:Win11
Tenant:testduplicate
Project:N/A
Recipe / template:N/A
```

### 7.2 Exact user steps

Record the shortest reproducible flow from opening the product to output creation.

1. Launch DopaMatrix.

2. Select tenant:
   - Tenant: `testduplicate`

3. Open:
   - Left menu: `矩阵工厂`
   - Page: `矩阵工厂`
   - Tab: `AI智能创作`
   - UI source: `web_ui/src/views/WorkspaceView.vue`

4. Enter prompt:

   `体验无与伦比的驾驶舒适感，感受汽车减震器带来的平稳与安全，让每一次出行都如同行驶在云端!@hook:汽车减震器`

5. Click:

   `AI起草`

6. Open / enter:

   `编排战术板`

   - UI source: `web_ui/src/views/DslOrchestratorDrawer.vue`

7. Manually define the Beat-level candidate pools by dragging the following assets into the corresponding slots:

    Hook:
    semantic constraint = hook:汽车减震器
    Effective backend candidate pool:       
    - `12.mp4`
    - `13.mp4`
    - `16.mp4`
    - `58.mp4`

    Context:
    explicit physical candidates:    
    - `18.mp4`
    - `28.mp4`

    Build:
    explicit physical candidates:    
    - `24.mp4`

    BGM:
    - `44444.mp3`

8. Confirm that the tactical board contains:

    - Hook candidates: `4`
    - Context candidates: `2`
    - Build candidates: `1`
    - BGM: `44444.mp3`

9. Set batch size:

    `1`

10. Set other options:

    - 画幅: `9:16竖屏`
    - 语种: `EN英语`
    - 语音: `启动`
    - 字幕: `启动`

11. Click:

    `确认并直接渲染`

12. Wait until the single render task completes.

13. Open / observe the generated result list.

14. Record:
    - generated filenames
    - output paths
    - task ID
    - file SHA256
    - decoded-video SHA256
    - decoded-audio SHA256
    - screenshots
    - backend logs

### 7.3 Input assets

#### Generation mode

Mode:

`AI 智能起草（AI Draft）`

Repro003 is the single-output control run for INV-001.

The existing DAM assets and Beat-level candidate-pool structure from the
previous reproduction runs were reused.

Requested batch size:

`1`

The purpose of this run is not to evaluate diversity inside a batch, but to
observe the normal single-item generation path without multi-worker batch
expansion.


#### User-defined candidate pools

The Beat-level candidate structure remains:

##### Hook

- `12.mp4`
- `13.mp4`
- `16.mp4`
- `58.mp4`

##### Context

- `18.mp4`
- `28.mp4`

##### Build

- `24.mp4`

##### BGM

- `44444.mp3`


#### Effective asset sequence selected by the system

Backend FFmpeg logs confirm that the single generated output selected:

1. Hook: `16.mp4`
2. Context: `28.mp4`
3. Build: `24.mp4`

Effective visual sequence:

`16.mp4 → 28.mp4 → 24.mp4`

GlobalTimeline:

`beat_actual_starts=[0.0, 41.587, 56.787]`

Total master timeline:

`63.287s`

Master output:

`output/master_video_4e584d52.mp4`

BGM input:

`F:\test\44444.mp3`


#### Control-group observation

Only one visual asset combination was resolved because:

`batch_size = 1`

Therefore Repro003 cannot by itself test within-batch duplicate selection.

Its role is to provide a control path for comparison with Repro001 and
Repro002:

Repro001 / Repro002:
`batch_size = 4`

Repro003:
`batch_size = 1`

Whether the internal resolver implementation differs between batch_size=1
and batch_size>1 remains:

`需要 Codex 源码诊断确认`

### 7.4 Output evidence

Requested batch size:

`1`

One final MP4 output was produced.


#### Execution identity observed in runtime artifacts

The following UUID is observed in TTS / subtitle intermediate artifact names:

`4e584d52-68cd-46b9-927a-f8457f810d97`

Examples:

- `voice_4e584d52-68cd-46b9-927a-f8457f810d97_en.mp3`
- `voice_4e584d52-68cd-46b9-927a-f8457f810d97_en.vtt`
- `sub_4e584d52-68cd-46b9-927a-f8457f810d97_en.ass`

The exact semantic of this UUID in the current source code
(task ID / session ID / execution ID / other) remains:

`需要 Codex 源码确认`

Unlike Repro001 and Repro002, only one worker is involved in this control run,
so no cross-worker identity collision can be evaluated from this run alone.


#### Output — `final_en_4e584d52.mp4`

Local absolute path:

`E:\dopaworkspace\dopamatrix-desktop\output\final_en_4e584d52.mp4`

Associated master:

`E:\dopaworkspace\dopamatrix-desktop\output\master_video_4e584d52.mp4`

Effective visual sequence:

`16.mp4 → 28.mp4 → 24.mp4`

GlobalTimeline:

`beat_actual_starts=[0.0, 41.587, 56.787]`

Total master timeline:

`63.287s`

File SHA256:

`8A19FC0A8DE6D076AAD42B8A205C0B3335D8B0B22A2B6E17367F37E7B9B1CF46`

Decoded video SHA256:

`5d0192de722ccaf6ff5f80728b4715f096895910b3f4d5b16919e31b1c9c3f90`

Decoded master-video SHA256:

`54b4e3bfb84aff5b8becf6cbf0808a0979db44230971c43f5e8fb933fae8939f`

Decoded audio SHA256:

`b31dfaa4e5fe1d7be0bdcdcc4f5ac3d0236e1836606f1f3913a94264ca8b4b69`

File size:

`24.1M`

Final media duration:

`63s`


#### Render-path observation

The backend log shows one normal single-item chain:

`submit-dsl`
→ `TTS`
→ `Subtitle`
→ `Timeline / Master Render`
→ `master_video_4e584d52.mp4`
→ `final_en_4e584d52.mp4`

The final render uses:

- `master_video_4e584d52.mp4`
- `voice_4e584d52-68cd-46b9-927a-f8457f810d97_en.mp3`
- `sub_4e584d52-68cd-46b9-927a-f8457f810d97_en.ass`
- `44444.mp3`

No second output exists in this batch for duplicate comparison.

### 7.5 Duplicate classification

#### Type A — file-level exact duplicate

Definition:

- two or more final MP4 outputs have identical file SHA256

Repro003 result:

`NOT APPLICABLE`

Reason:

`batch_size = 1`

Only one final MP4 was generated, so no second output exists for
file-level duplicate comparison.


#### Type B — visually identical but binary different

Definition:

- two or more generated outputs have different file SHA256
- decoded video content is identical

Repro003 result:

`NOT APPLICABLE`

Reason:

Only one generated output exists in this batch.


#### Type C — final output path / overwrite suspicion

Definition:

- multiple generated items unintentionally reference the same final/master
  output path

Repro003 result:

`NOT OBSERVED`

Only one master and one final output are present:

- `master_video_4e584d52.mp4`
- `final_en_4e584d52.mp4`

Therefore no within-batch master/final path collision is observable in this
single-output control run.


#### Related classification — batch/variant identity collision

Repro003 result:

`NOT OBSERVED IN THE COLLECTED LOG`

Only one execution chain is present.

A single UUID is used for the TTS/subtitle intermediate artifacts:

`4e584d52-68cd-46b9-927a-f8457f810d97`

Unlike Repro001 and Repro002, there are no multiple concurrent workers in
this run attempting to use the same identity.

No `UNIQUE constraint failed: task_history.task_id` error was observed in
the collected Repro003 backend log.

This does NOT prove that the identity model is correct.

It only shows that the collision observed in the batch_size=4 runs is not
observable in this single-worker control run.


#### Repro003 overall conclusion

Repro003 successfully produced one output through the single-item generation
path:

AI Draft
→ user-defined Beat candidate pools
→ system produces one effective asset combination
→ `16.mp4 → 28.mp4 → 24.mp4`
→ one GlobalTimeline
→ one master video
→ one final video

No within-batch duplicate comparison is possible because:

`batch_size = 1`

Therefore Repro003 should be interpreted as a:

`SINGLE-ITEM EXECUTION CONTROL`

not as proof that the duplicate-video defect does not exist in the
single-item code path.

When compared with Repro001 and Repro002:

- batch_size=1:
  one execution chain, one output, no observable worker-to-worker collision

- batch_size=4:
  multiple execution chains, repeated visual asset combinations,
  repeated master-video content, and shared identity anomalies

This comparison increases the diagnostic value of investigating:

`batch expansion`
→ `multi-worker execution`
→ `Context / identity isolation`
→ `asset resolution / usage state`

However, the comparison alone does NOT prove that concurrency is the root
cause.

The causal mechanism remains:

`需要 Codex 源码诊断确认`

### 7.6 Screenshots

- `./screenshots/00-Tenant-input.png`
- `./screenshots/01-prepare-assets.png`
- `./screenshots/02-input-prompt.png`
- `./screenshots/03-select-assets.png`
- `./screenshots/04-task-running.png`
- `./screenshots/05-generated-results.png`
- `./screenshots/06-output-files.png`

### 7.7 Logs

- `./logs/backend.log`
- `./logs/frontend-console.log`
- `./logs/SHA-256.log`