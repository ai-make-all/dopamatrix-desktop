## 7. Reproduction Evidence Package — REQUIRED BEFORE FORMAL CODE DIAGNOSIS

Before Codex produces its formal root-cause report, reproduce the issue once on the current branch and attach evidence.

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
   - Left menu: `素材库`
   - Page: `数字资产管理 (DAM)`
   - UI source: `web_ui/src/views/AssetsView.vue`

4. Import the test assets into DAM.

5. Apply tag `汽车减震器` to the following Hook candidate assets:
   - `12.mp4`
   - `13.mp4`
   - `16.mp4`
   - `58.mp4`

6. Open:
   - Left menu: `矩阵工厂`
   - Page: `矩阵工厂`
   - Tab: `AI智能创作`
   - UI source: `web_ui/src/views/WorkspaceView.vue`

7. Enter prompt:

   `探索汽车减震器的神奇世界，感受每一次颠簸都被轻柔化解的惊艳体验!@hook:汽车减震器`

8. Click:

   `AI起草`

9. Open / enter:

   `编排战术板`

   - UI source: `web_ui/src/views/DslOrchestratorDrawer.vue`

10. Manually define the Beat-level candidate pools by dragging the following assets into the corresponding slots:

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

11. Confirm that the tactical board contains:

    - Hook candidates: `4`
    - Context candidates: `2`
    - Build candidates: `1`
    - BGM: `44444.mp3`

12. Set batch size:

    `4`

13. Set other options:

    - 画幅: `9:16竖屏`
    - 语种: `EN英语`
    - 语音: `启动`
    - 字幕: `启动`

14. Click:

    `确认并直接渲染`

15. Wait until all four render tasks complete.

16. Open / observe the generated result list.

17. Record:
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

In this reproduction, the AI first generated the Beat / tag structure.

Before rendering, the operator manually dragged the allowed physical assets
into the corresponding Beat slots.

Therefore:

- Beat candidate-pool definition: `USER CONTROLLED`
- final asset selection inside each Beat candidate pool: `SYSTEM / RESOLVER CONTROLLED`
- unrestricted automatic retrieval from the entire DAM library: `NO`

This is important for INV-001:

The duplicated outputs were generated from explicitly constrained Beat-level
candidate pools, not from an unrestricted search across all DAM assets.

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


#### Terminology note

`Hook / Context / Build` in this document represent the Beat slot into which
the operator placed each asset for this reproduction.

They should NOT automatically be interpreted as the literal value of an
internal database or code field such as `asset.role`.

Where visible in the DAM UI, the video assets use the DSL / track定位:

`main_v_track`

The exact internal role-field semantics remain:

`需要 Codex 源码确认`


#### Candidate capacity

User-visible candidate structure:

- Hook: `4`
- Context: `2`
- Build: `1`

Theoretical visual combinations based only on the visible user-defined pool:

`4 × 2 × 1 = 8`

Requested batch size:

`4`

Effective resolver-valid combination capacity after internal tag filtering,
scoring, usage_count, ranking or other resolver rules:

`需要 Codex 源码确认`

Therefore the visible candidate pool appears to provide more than one possible
visual combination, but this does not yet prove that all 8 combinations are
valid inside the current resolver implementation.


#### Effective asset sequences actually selected by the system

The following sequences are confirmed from the backend FFmpeg render logs.

##### Output `25cbb299`

Selected video sequence:

1. Hook: `13.mp4`
2. Context: `18.mp4`
3. Build: `24.mp4`

GlobalTimeline:

`beat_actual_starts=[0.0, 17.206, 31.239]`

Total master timeline:

`37.739s`

Master output:

`output/master_video_25cbb299.mp4`


##### Output `ab585c71`

Selected video sequence:

1. Hook: `58.mp4`
2. Context: `28.mp4`
3. Build: `24.mp4`

GlobalTimeline:

`beat_actual_starts=[0.0, 3.933, 19.133]`

Total master timeline:

`25.633s`

Master output:

`output/master_video_ab585c71.mp4`


##### Output `6451b32e`

Selected video sequence:

1. Hook: `13.mp4`
2. Context: `28.mp4`
3. Build: `24.mp4`

GlobalTimeline:

`beat_actual_starts=[0.0, 17.206, 32.406]`

Total master timeline:

`38.906s`

Master output:

`output/master_video_6451b32e.mp4`


##### Output `db4d3533`

Selected video sequence:

1. Hook: `13.mp4`
2. Context: `28.mp4`
3. Build: `24.mp4`

GlobalTimeline:

`beat_actual_starts=[0.0, 17.206, 32.406]`

Total master timeline:

`38.906s`

Master output:

`output/master_video_db4d3533.mp4`


#### Important selection observation

`6451b32e` and `db4d3533` received exactly the same:

- Hook asset: `13.mp4`
- Context asset: `28.mp4`
- Build asset: `24.mp4`
- asset order
- GlobalTimeline start positions
- total master timeline duration

Therefore these two variants were already effectively identical at the
asset-selection / render-plan stage.

The repeated use of `24.mp4` in Build is expected because the Build candidate
pool contains only one asset.

The diagnostically important repeat is:

- Hook had 4 visible candidates, but both variants selected `13.mp4`
- Context had 2 visible candidates, but both variants selected `28.mp4`

Why multiple workers selected the same Hook + Context combination remains:

`需要 Codex 源码诊断确认`

### 7.4 Output evidence

Requested batch size:

`4`

Four final MP4 outputs were produced.

The shared task ID observed repeatedly across multiple render workers is:

`28eb0081-a6ba-4c31-932d-9f4fc13f9d71`

The intended semantic of this ID (batch-level, task-level, or other)
and whether a separate variant-level identity exists remain:

`需要 Codex 源码确认`


#### Output 1 — `final_en_db4d3533.mp4`

Local absolute path:

`E:\dopaworkspace\dopamatrix-desktop\output\final_en_db4d3533.mp4`

Associated master:

`E:\dopaworkspace\dopamatrix-desktop\output\master_video_db4d3533.mp4`

File SHA256:

`897218F1494545B36A07D6E6CEEE1FD347C0A90BE437E33EC02FFC8F52A6DEC1`

Decoded video SHA256:

`be8cff6ff299a1e8c5ab491f7654d8d8ea76cdc1ce7b7ff6282e46f5d58e2a53`

Decoded master-video SHA256:

`bf57b604d0379a5adbde7d098418703d1c728ef434b2f5c4418c282a3a5ed4e8`

Decoded audio SHA256:

`aee13809a5c5d97b1bbe3c4650063d430a8ea0db36e87ff33d9ba351ab8d1e65`

File size:

`8.44M`

Final media duration:

`38s`


#### Output 2 — `final_en_25cbb299.mp4`

Local absolute path:

`E:\dopaworkspace\dopamatrix-desktop\output\final_en_25cbb299.mp4`

Associated master:

`E:\dopaworkspace\dopamatrix-desktop\output\master_video_25cbb299.mp4`

File SHA256:

`1BE0D63531490CFBF759A7BB22447D0AE4AB241E38DB46F8880C9A1FF9303B0F`

Decoded video SHA256:

`c2de3e7abe0b43a8ec7487970c6730c49e3a6a6e3f6e461c32334a137c2113d5`

Decoded master-video SHA256:

`6a2adb701a7caed769a19d9d93000c87d5f7eb11efc03eff93206e298e5b2944`

Decoded audio SHA256:

`ca763565f5fc86ff28c3d76d34daffcc641ab2990b702c257abe65ed5ef3d054`

File size:

`8.27M`

Final media duration:

`37s`


#### Output 3 — `final_en_6451b32e.mp4`

Local absolute path:

`E:\dopaworkspace\dopamatrix-desktop\output\final_en_6451b32e.mp4`

Associated master:

`E:\dopaworkspace\dopamatrix-desktop\output\master_video_6451b32e.mp4`

File SHA256:

`519AEBADE259AD006E8E10A596C55371C517C829074AEBEC3C401BBE867D94C4`

Decoded video SHA256:

`be8cff6ff299a1e8c5ab491f7654d8d8ea76cdc1ce7b7ff6282e46f5d58e2a53`

Decoded master-video SHA256:

`bf57b604d0379a5adbde7d098418703d1c728ef434b2f5c4418c282a3a5ed4e8`

Decoded audio SHA256:

`fe68a82e5739870327a7eb69331e3084194007681388a432e14bb8fad6aede78`

File size:

`8.44M`

Final media duration:

`38s`


#### Output 4 — `final_en_ab585c71.mp4`

Local absolute path:

`E:\dopaworkspace\dopamatrix-desktop\output\final_en_ab585c71.mp4`

Associated master:

`E:\dopaworkspace\dopamatrix-desktop\output\master_video_ab585c71.mp4`

File SHA256:

`48A2C2BF76DDABA970CF78D3CC5926FE5ADA4AE9D4EC0E43BB54484E30CBE150`

Decoded video SHA256:

`06d845f80b90d44edbd94e807cd97ca0afd9259dc812a57dc9e2e68bb60f9a4a`

Decoded master-video SHA256:

`a48a264d3047f41143bd60eb1cc7787e9f1b16e35eb9761228c0cd0802545b3b`

Decoded audio SHA256:

`f5def724ef0f3da505333df34151e2862aa7658af94563d79038e1085e404201`

File size:

`6.23M`

Final media duration:

`25s`


#### Verified duplicate pair

Verified pair:

- `final_en_db4d3533.mp4`
- `final_en_6451b32e.mp4`

File-level SHA256:

`DIFFERENT`

Decoded-video SHA256:

`IDENTICAL`

Both:

`be8cff6ff299a1e8c5ab491f7654d8d8ea76cdc1ce7b7ff6282e46f5d58e2a53`

Corresponding master-video decoded SHA256:

`IDENTICAL`

Both:

`bf57b604d0379a5adbde7d098418703d1c728ef434b2f5c4418c282a3a5ed4e8`

Decoded-audio SHA256:

`DIFFERENT`

- `db4d3533`:
  `aee13809a5c5d97b1bbe3c4650063d430a8ea0db36e87ff33d9ba351ab8d1e65`

- `6451b32e`:
  `fe68a82e5739870327a7eb69331e3084194007681388a432e14bb8fad6aede78`

Therefore:

- effective asset sequence: `IDENTICAL`
- GlobalTimeline: `IDENTICAL`
- decoded master visual content: `IDENTICAL`
- decoded final visual content: `IDENTICAL`
- decoded audio content: `DIFFERENT`
- full final MP4 binary: `DIFFERENT`

This pair is therefore a verified:

`VISUAL CONTENT DUPLICATE`

It is NOT a full binary / full A/V duplicate.


#### Related backend identity anomaly

Multiple render workers in this batch attempted to persist history records
using the same task ID:

`28eb0081-a6ba-4c31-932d-9f4fc13f9d71`

The backend produced:

`sqlite3.IntegrityError: UNIQUE constraint failed: task_history.task_id`

This is treated as a separate verified batch/variant identity or persistence
defect.

Whether it directly contributes to duplicate asset selection remains:

`需要 Codex 源码诊断确认`

### 7.5 Duplicate classification

#### Type A — file-level exact duplicate

Definition:

- final MP4 SHA256 is identical

Repro001 result:

`NOT OBSERVED`

All four final MP4 outputs have different file-level SHA256 values.

Therefore Repro001 does not contain a verified file-level exact duplicate.


#### Type B — visually identical but binary different

Definition:

- final MP4 SHA256 differs
- decoded video content is identical

Repro001 result:

`VERIFIED`

Verified pair:

- `final_en_db4d3533.mp4`
- `final_en_6451b32e.mp4`

Their file SHA256 values are different.

Their decoded-video SHA256 values are identical:

`be8cff6ff299a1e8c5ab491f7654d8d8ea76cdc1ce7b7ff6282e46f5d58e2a53`

Their corresponding master videos also have identical decoded-video SHA256:

`bf57b604d0379a5adbde7d098418703d1c728ef434b2f5c4418c282a3a5ed4e8`

Backend logs additionally show that both variants use the same effective
visual asset sequence:

`13.mp4 → 28.mp4 → 24.mp4`

and the same GlobalTimeline:

`beat_actual_starts=[0.0, 17.206, 32.406]`

`total=38.906s`

Their decoded audio hashes are different.

Classification:

`VERIFIED VISUAL DUPLICATE / NOT FULL A/V DUPLICATE`

This proves that the visual duplicate already exists before final audio,
subtitle and MP4 mux processing.


#### Type C — final output path / overwrite suspicion

Definition:

- multiple variants reference the same final output path/name
- an earlier output appears overwritten or reused

Repro001 result:

`NOT OBSERVED AS THE PRIMARY VISUAL-DUPLICATE MECHANISM`

The verified duplicate pair uses different final output paths:

- `final_en_db4d3533.mp4`
- `final_en_6451b32e.mp4`

and different master output paths:

- `master_video_db4d3533.mp4`
- `master_video_6451b32e.mp4`

Despite different master filenames, the decoded master-video content is
identical.

Therefore a final/master output-path collision is not required to explain
this verified visual duplicate.


#### Related classification — duplicate Variant selection

Repro001 also proves that two different generated outputs received the same
Beat-level asset combination:

- Hook: `13.mp4`
- Context: `28.mp4`
- Build: `24.mp4`

The user-defined candidate pools contained:

- Hook: 4 visible candidates
- Context: 2 visible candidates
- Build: 1 fixed candidate

Therefore the duplicated Build asset (`24.mp4`) is expected.

The diagnostically important collision is that two generated variants both
selected:

- the same Hook candidate: `13.mp4`
- the same Context candidate: `28.mp4`

Status:

`VERIFIED DUPLICATE ASSET COMBINATION`

Why the resolver allowed this collision remains:

`需要 Codex 源码诊断确认`


#### Related classification — batch/variant identity collision

Multiple render workers also share:

`task_id = 28eb0081-a6ba-4c31-932d-9f4fc13f9d71`

and multiple workers attempt to insert history rows using this same ID,
causing:

`UNIQUE constraint failed: task_history.task_id`

Status:

`VERIFIED SECONDARY DEFECT`

Whether this shared identity is causally connected to the duplicate asset
selection remains:

`需要 Codex 源码诊断确认`


#### Repro001 overall conclusion

Repro001 verifies the following failure chain:

AI Draft
→ user-defined Beat candidate pools
→ system selection pipeline selects assets for each generated item
→ two generated items receive the same Hook + Context + Build combination
→ identical GlobalTimeline
→ different master filenames
→ identical decoded master-video content
→ different final filenames
→ identical decoded final-video content
→ different decoded audio content
→ different full-file SHA256

Therefore the primary visual-duplication investigation boundary is now:

`batch expansion`
→ `worker / Context isolation`
→ `Beat-level asset resolution`
→ `candidate scoring / randomness / usage state`
→ `timeline / effective render-plan generation`

The exact root cause remains:

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