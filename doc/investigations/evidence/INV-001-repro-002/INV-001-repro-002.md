## 7. Reproduction Evidence Package — REQUIRED BEFORE FORMAL CODE DIAGNOSIS

Before Codex produces its formal root-cause report, reproduce the issue once on the current branch and attach evidence.

#### Relation to other runs

Repro002 uses the same DAM asset set, Beat candidate pools and rendering
options as Repro001, but uses a different AI Draft prompt.

See:

`../INV-001-experiment-summary.md`

for the cross-run control analysis.

### 7.1 Environment

Fill in:

```text
Date/time:2026-08-14
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

   `无论是颠簸的山路还是城市的平坦街道，汽车减震器都能带来无与伦比的驾驶舒适感，让你在每一次旅程中都能享受平稳与安宁的体验。@hook:汽车减震器`

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

    `4`

10. Set other options:

    - 画幅: `9:16竖屏`
    - 语种: `EN英语`
    - 语音: `启动`
    - 字幕: `启动`

11. Click:

    `确认并直接渲染`

12. Wait until all four render tasks complete.

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

Repro002 reuses the same DAM assets, user-defined Beat candidate pools,
batch size and rendering options used in Repro001.

However, Repro002 uses a different AI Draft prompt.

Therefore this run is not an exact same-input repetition of Repro001.
Its purpose is to verify whether duplicate generation can recur across
a fresh application/server run and a new AI Draft while keeping the
candidate-pool structure unchanged.

The AI first generated the Beat / tag structure.

Before rendering, the operator manually dragged the same allowed physical
assets into the corresponding Beat slots.

Therefore:

- Beat candidate-pool definition: `USER CONTROLLED`
- final asset selection inside each Beat candidate pool: `SYSTEM / RESOLVER CONTROLLED`
- unrestricted automatic retrieval from the entire DAM library: `NO`

Repro002 intentionally reuses the same candidate pools as Repro001 in order
to test whether duplicate generation can be reproduced across a fresh
application/server run.


#### DAM asset identity

| Asset | DAM ID | File Hash (DB) | Database | Asset Type | Assigned Beat |
|---|---:|---|---|---|---|
| `12.mp4` | 1 | `846de2afceaf8677a4e7bcdb680762ec` | `dopamatrix_testduplicate.db` | video | Hook |
| `13.mp4` | 2 | `f0a5c247219ff997f6bdf9800e5e96dd` | `dopamatrix_testduplicate.db` | video | Hook |
| `16.mp4` | 3 | `969c8e2660ad513d7fa52ebb8b05d18b` | `dopamatrix_testduplicate.db` | video | Hook |
| `58.mp4` | 11 | `e1d29ce2e193377c8b561e998ff0036d` | `dopamatrix_testduplicate.db` | video | Hook |
| `18.mp4` | 4 | `df00ae61ef305f355027e7fa8070142b` | `dopamatrix_testduplicate.db` | video | Context |
| `28.mp4` | 6 | `08a1691d53b489f44eaab7e9db24fd38` | `dopamatrix_testduplicate.db` | video | Context |
| `24.mp4` | 5 | `0e1afdd45dcc40f3235e800c445755b8` | `dopamatrix_testduplicate.db` | video | Build |
| `44444.mp3` | 17 | `4a113f7af281e54fd8311d7a10ac8daf` | `dopamatrix_testduplicate.db` | audio | BGM |


#### User-defined candidate pools

##### Hook

Allowed candidates:

- `12.mp4`
  - DAM asset ID: `1`
  - file_path: `F:\test\sucai\12.mp4`
  - Asset type: `video`
  - Assigned Beat: `Hook`

- `13.mp4`
  - DAM asset ID: `2`
  - file_path: `F:\test\sucai\13.mp4`
  - Asset type: `video`
  - Assigned Beat: `Hook`

- `16.mp4`
  - DAM asset ID: `3`
  - file_path: `F:\test\sucai\16.mp4`
  - Asset type: `video`
  - Assigned Beat: `Hook`

- `58.mp4`
  - DAM asset ID: `11`
  - file_path: `F:\test\sucai\58.mp4`
  - Asset type: `video`
  - Assigned Beat: `Hook`


##### Context

Allowed candidates:

- `18.mp4`
  - DAM asset ID: `4`
  - file_path: `F:\test\sucai\18.mp4`
  - Asset type: `video`
  - Assigned Beat: `Context`

- `28.mp4`
  - DAM asset ID: `6`
  - file_path: `F:\test\sucai\28.mp4`
  - Asset type: `video`
  - Assigned Beat: `Context`


##### Build

Allowed candidate:

- `24.mp4`
  - DAM asset ID: `5`
  - file_path: `F:\test\sucai\24.mp4`
  - Asset type: `video`
  - Assigned Beat: `Build`


##### BGM

- `44444.mp3`
  - DAM asset ID: `17`
  - file_path: `F:\test\44444.mp3`
  - Asset type: `audio / BGM`
  - Assigned Beat / track: `BGM`


#### Candidate capacity

User-visible candidate structure:

- Hook: `4`
- Context: `2`
- Build: `1`

Theoretical visual combinations based only on the visible user-defined pool:

`4 × 2 × 1 = 8`

Requested batch size:

`4`

Effective resolver-valid combination capacity after internal filtering,
scoring, usage_count, randomization or other resolver rules:

`需要 Codex 源码确认`


#### Effective asset sequences actually selected by the system

The following effective sequences are confirmed from the Repro002 backend
FFmpeg logs.


##### Output `5a9895d4`

Selected video sequence:

1. Hook: `12.mp4`
2. Context: `18.mp4`
3. Build: `24.mp4`

GlobalTimeline:

`beat_actual_starts=[0.0, 14.419, 28.452]`

Total master timeline:

`34.952s`

Master output:

`output/master_video_5a9895d4.mp4`


##### Output `470778f4`

Selected video sequence:

1. Hook: `12.mp4`
2. Context: `18.mp4`
3. Build: `24.mp4`

GlobalTimeline:

`beat_actual_starts=[0.0, 14.419, 28.452]`

Total master timeline:

`34.952s`

Master output:

`output/master_video_470778f4.mp4`


##### Output `13e26247`

Selected video sequence:

1. Hook: `12.mp4`
2. Context: `18.mp4`
3. Build: `24.mp4`

GlobalTimeline:

`beat_actual_starts=[0.0, 14.419, 28.452]`

Total master timeline:

`34.952s`

Master output:

`output/master_video_13e26247.mp4`


##### Output `8698f4c5`

Selected video sequence:

1. Hook: `12.mp4`
2. Context: `28.mp4`
3. Build: `24.mp4`

GlobalTimeline:

`beat_actual_starts=[0.0, 14.419, 29.619]`

Total master timeline:

`36.119s`

Master output:

`output/master_video_8698f4c5.mp4`


#### Important selection observation

Three generated outputs:

- `5a9895d4`
- `470778f4`
- `13e26247`

received exactly the same:

- Hook asset: `12.mp4`
- Context asset: `18.mp4`
- Build asset: `24.mp4`
- asset order
- GlobalTimeline start positions
- total master timeline duration

Therefore these three generated items were already effectively identical at
the asset-selection / render-plan stage.

The fourth generated item, `8698f4c5`, differs at least in the Context slot:

- Hook: `12.mp4`
- Context: `28.mp4`
- Build: `24.mp4`

The repeated use of `24.mp4` is expected because Build has only one candidate.

The diagnostically important behavior is:

- all four generated items selected the same Hook asset: `12.mp4`
  even though Hook had 4 visible candidates
- three of four generated items selected the same Context asset: `18.mp4`
  even though Context had 2 visible candidates
- three of four generated items therefore received the exact same complete
  visual asset combination

Why the resolver allowed this collision remains:

`需要 Codex 源码诊断确认`

### 7.4 Output evidence

Requested batch size:

`4`

Four final MP4 outputs were produced.

The shared task ID observed repeatedly across multiple render workers is:

`6efe634a-2a42-4d44-bd3a-dd8e2d938c19`

The intended semantic of this ID and whether a separate variant-level
identity exists remain:

`需要 Codex 源码确认`


#### Output 1 — `final_en_8698f4c5.mp4`

Local absolute path:

`E:\dopaworkspace\dopamatrix-desktop\output\final_en_8698f4c5.mp4`

Associated master:

`E:\dopaworkspace\dopamatrix-desktop\output\master_video_8698f4c5.mp4`

File SHA256:

`87674E2511CDB547BB85466CC496CC2AE01528514BCCED025C45E1DDF65B8708`

Decoded video SHA256:

`2f1c1310b4861e27034c2bcac3ea42818f9b06781ddb6cd0da675850da733f7d`

Decoded master-video SHA256:

`5fed04da5e0bc52cc96ddac0c7d0e3ef8ed5be6b18d6faf232aa8e533422177e`

Decoded audio SHA256:

`9a7461b58b68610f145706cfa377d4ebdfb83636d6373a7cca59a8b64389d73f`

File size:

`8M`

Final media duration:

`36s`


#### Output 2 — `final_en_13e26247.mp4`

Local absolute path:

`E:\dopaworkspace\dopamatrix-desktop\output\final_en_13e26247.mp4`

Associated master:

`E:\dopaworkspace\dopamatrix-desktop\output\master_video_13e26247.mp4`

File SHA256:

`CD288C9373D21F59278192ABD157C68A10138B0CBB8FBF5A50760637CBF61A3D`

Decoded video SHA256:

`6a150bb5db571385b9a20a1a38cf4f3d8dbbe5539508595adf1f666baec7f59e`

Decoded master-video SHA256:

`940eb569632c2308ee9ecd61c5413372020accb7bfa3cbde03c9adb0ad4d13f1`

Decoded audio SHA256:

`7d3fd9dc7f4f72e38d4104f60492e970bc52f42dee3bf6e809ad2c49f97ab186`

File size:

`7.81M`

Final media duration:

`34s`


#### Output 3 — `final_en_5a9895d4.mp4`

Local absolute path:

`E:\dopaworkspace\dopamatrix-desktop\output\final_en_5a9895d4.mp4`

Associated master:

`E:\dopaworkspace\dopamatrix-desktop\output\master_video_5a9895d4.mp4`

File SHA256:

`A38036AFB898DE858735BCDECD878450FC270E8FA8E1942819A0AB902F87F781`

Decoded video SHA256:

`6a150bb5db571385b9a20a1a38cf4f3d8dbbe5539508595adf1f666baec7f59e`

Decoded master-video SHA256:

`940eb569632c2308ee9ecd61c5413372020accb7bfa3cbde03c9adb0ad4d13f1`

Decoded audio SHA256:

`59f5a31058c726508ee4fcc2ca3455a5c94cdee3e9862708b6e511df26049d35`

File size:

`7.81M`

Final media duration:

`34s`


#### Output 4 — `final_en_470778f4.mp4`

Local absolute path:

`E:\dopaworkspace\dopamatrix-desktop\output\final_en_470778f4.mp4`

Associated master:

`E:\dopaworkspace\dopamatrix-desktop\output\master_video_470778f4.mp4`

File SHA256:

`CD288C9373D21F59278192ABD157C68A10138B0CBB8FBF5A50760637CBF61A3D`

Decoded video SHA256:

`6a150bb5db571385b9a20a1a38cf4f3d8dbbe5539508595adf1f666baec7f59e`

Decoded master-video SHA256:

`940eb569632c2308ee9ecd61c5413372020accb7bfa3cbde03c9adb0ad4d13f1`

Decoded audio SHA256:

`7d3fd9dc7f4f72e38d4104f60492e970bc52f42dee3bf6e809ad2c49f97ab186`

File size:

`7.81M`

Final media duration:

`34s`


#### Verified three-output visual duplicate group

The following three outputs are a verified visual-duplicate group:

- `final_en_5a9895d4.mp4`
- `final_en_470778f4.mp4`
- `final_en_13e26247.mp4`

All three have the same decoded-video SHA256:

`6a150bb5db571385b9a20a1a38cf4f3d8dbbe5539508595adf1f666baec7f59e`

Their corresponding master videos also have the same decoded-video SHA256:

`940eb569632c2308ee9ecd61c5413372020accb7bfa3cbde03c9adb0ad4d13f1`

Their backend render plans also use the same:

`12.mp4 → 18.mp4 → 24.mp4`

and the same GlobalTimeline:

`beat_actual_starts=[0.0, 14.419, 28.452]`

`total=34.952s`


#### Verified full exact duplicate pair

Within the three-output visual duplicate group, the following two files are
even stronger duplicates:

- `final_en_470778f4.mp4`
- `final_en_13e26247.mp4`

They have identical:

- final file SHA256
- decoded-video SHA256
- decoded-audio SHA256
- decoded master-video SHA256
- effective visual asset sequence
- GlobalTimeline

File SHA256 for both:

`CD288C9373D21F59278192ABD157C68A10138B0CBB8FBF5A50760637CBF61A3D`

Decoded video SHA256 for both:

`6a150bb5db571385b9a20a1a38cf4f3d8dbbe5539508595adf1f666baec7f59e`

Decoded audio SHA256 for both:

`7d3fd9dc7f4f72e38d4104f60492e970bc52f42dee3bf6e809ad2c49f97ab186`

Decoded master-video SHA256 for both:

`940eb569632c2308ee9ecd61c5413372020accb7bfa3cbde03c9adb0ad4d13f1`

Classification:

`FULL EXACT DUPLICATE`


#### Visual duplicate with different audio / binary

`final_en_5a9895d4.mp4` has the same decoded visual content and the same
decoded master-video content as `470778f4` and `13e26247`.

However:

- its final file SHA256 is different
- its decoded audio SHA256 is different

Therefore `5a9895d4` belongs to the same visual-duplicate group, but is not a
full binary / full A/V duplicate of the other two.


#### Related backend identity anomaly

Multiple render workers attempted to persist history using the same shared:

`task_id = 6efe634a-2a42-4d44-bd3a-dd8e2d938c19`

The backend produced:

`sqlite3.IntegrityError: UNIQUE constraint failed: task_history.task_id`

Status:

`VERIFIED SECONDARY DEFECT`

Whether the shared task identity directly contributes to duplicate asset
selection remains:

`需要 Codex 源码诊断确认`

### 7.5 Duplicate classification

#### Type A — file-level exact duplicate

Definition:

- final MP4 SHA256 is identical

Repro002 result:

`VERIFIED`

Verified exact pair:

- `final_en_470778f4.mp4`
- `final_en_13e26247.mp4`

Both final MP4 files have:

`SHA256 = CD288C9373D21F59278192ABD157C68A10138B0CBB8FBF5A50760637CBF61A3D`

Their decoded video and decoded audio hashes are also identical.

Classification:

`VERIFIED FULL EXACT DUPLICATE`


#### Type B — visually identical but binary different

Definition:

- final MP4 SHA256 differs
- decoded video content is identical

Repro002 result:

`VERIFIED`

Three-output visual duplicate group:

- `final_en_5a9895d4.mp4`
- `final_en_470778f4.mp4`
- `final_en_13e26247.mp4`

All three decoded-video hashes are identical:

`6a150bb5db571385b9a20a1a38cf4f3d8dbbe5539508595adf1f666baec7f59e`

All three corresponding master-video decoded hashes are also identical:

`940eb569632c2308ee9ecd61c5413372020accb7bfa3cbde03c9adb0ad4d13f1`

However, `5a9895d4` has a different final file SHA256 and a different decoded
audio SHA256 from the other two.

Therefore Repro002 contains both:

- `FULL EXACT DUPLICATE`
- `VISUAL DUPLICATE WITH DIFFERENT AUDIO/BINARY`


#### Type C — final output path / overwrite suspicion

Definition:

- multiple variants reference the same final output path/name
- an earlier output appears overwritten or reused

Repro002 result:

`NOT OBSERVED AS THE PRIMARY VISUAL-DUPLICATE MECHANISM`

The three visually identical generated items use different master and final
output paths:

- `master_video_5a9895d4.mp4`
- `master_video_470778f4.mp4`
- `master_video_13e26247.mp4`

and:

- `final_en_5a9895d4.mp4`
- `final_en_470778f4.mp4`
- `final_en_13e26247.mp4`

Despite different master filenames, all three master videos have identical
decoded visual content.

Therefore final/master output-path collision is not required to explain the
visual duplication.


#### Related classification — duplicate Variant selection

Repro002 proves that three generated outputs received the exact same
Beat-level visual combination:

- Hook: `12.mp4`
- Context: `18.mp4`
- Build: `24.mp4`

The visible candidate pools contained:

- Hook: 4 candidates
- Context: 2 candidates
- Build: 1 fixed candidate

The repeated Build asset is expected.

The diagnostically important behavior is:

- all 4 generated outputs selected Hook `12.mp4`
- 3 of 4 selected Context `18.mp4`
- 3 of 4 therefore received the exact same complete visual asset sequence

Status:

`VERIFIED DUPLICATE ASSET COMBINATION`

Why the resolver produced this collision across concurrent workers remains:

`需要 Codex 源码诊断确认`


#### Related classification — master-stage duplicate

Three corresponding master videos:

- `master_video_5a9895d4.mp4`
- `master_video_470778f4.mp4`
- `master_video_13e26247.mp4`

have identical decoded-video SHA256:

`940eb569632c2308ee9ecd61c5413372020accb7bfa3cbde03c9adb0ad4d13f1`

Status:

`VERIFIED MASTER-STAGE VISUAL DUPLICATE`

This proves that visual duplication already exists before final:

- TTS/audio mixing
- subtitle burn-in
- final MP4 muxing


#### Related classification — batch/variant identity collision

Multiple render workers share:

`task_id = 6efe634a-2a42-4d44-bd3a-dd8e2d938c19`

and multiple workers attempt to insert history rows using the same ID,
causing:

`UNIQUE constraint failed: task_history.task_id`

Status:

`VERIFIED SECONDARY DEFECT`

Whether the shared identity is causally connected to duplicate asset
selection remains:

`需要 Codex 源码诊断确认`


#### Repro002 overall conclusion

Repro002 reproduces the duplicate-video defect more strongly than Repro001.

The verified failure chain is:

AI Draft
→ same user-defined Beat candidate pools as Repro001
→ batch request produces=4
→ all four generated items select Hook `12.mp4`
→ three generated items also select Context `18.mp4`
→ three generated items receive `12.mp4 → 18.mp4 → 24.mp4`
→ identical GlobalTimeline
→ different master filenames
→ identical decoded master-video content
→ identical decoded final-video content across three outputs
→ two of those outputs additionally have identical decoded audio
→ those same two final MP4 files have identical full-file SHA256

Therefore Repro002 verifies two duplicate classes simultaneously:

1. `VISUAL CONTENT DUPLICATE`
2. `FULL EXACT DUPLICATE`

The primary root-cause investigation boundary remains upstream of the master
render:

`batch expansion`
→ `worker / Context isolation`
→ `Beat-level asset resolution`
→ `candidate scoring / randomness / usage state`
→ `timeline / effective render-plan generation`

A separate concurrency/identity investigation is also required for:

`shared task identity`
→ `shared TTS/subtitle writable paths`
→ `task_history UNIQUE collision`

The exact causal relationship among these mechanisms remains:

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