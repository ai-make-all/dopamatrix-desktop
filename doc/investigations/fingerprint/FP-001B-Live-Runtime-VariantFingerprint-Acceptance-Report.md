# FP-001B
# Live Runtime VariantFingerprint Acceptance Report

## 1. Runtime Provenance

Port 8000 remained active throughout the audit.

```text
Listener PID: 18800
Process: python.exe
Executable: D:\Python\Python312\python.exe
Command: python.exe main.py
Start: 2026-08-28 15:55:36 +08:00
```

Uvicorn reload parent:

```text
PID: 19000
Executable:
E:\dopaworkspace\dopamatrix-desktop\venv_build\Scripts\python.exe

Command:
"E:\dopaworkspace\dopamatrix-desktop\venv_build\Scripts\python.exe" main.py
```

Runtime classification:

`CURRENT_SOURCE_PYTHON`

Final listener check confirmed PID `18800` was still running.

## 2. Source Provenance

```text
Source:
E:\dopaworkspace\dopamatrix-desktop\src\api\routes_dsl.py

Source modified:
2026-08-28 10:25:54 +08:00

Backend started:
2026-08-28 15:55:36 +08:00
```

The process started after the FP-001B source was written. Development entry also has `reload=True`.

Health check:

```json
{
  "status": "DopaMatrix Engine is running",
  "version": "0.5.0",
  "db": "connected"
}
```

`CURRENT_FP001B_SOURCE_RUNTIME_PROVEN`

## 3. Log Sink

Active DopaMatrix Loguru file:

```text
C:\Users\chenp\AppData\Local\DopaMatrixOrg\DopaMatrix\Logs\
dopamatrix_2026-08-28.log
```

Pre-run marker:

```text
size: 757 bytes
lines: 4
VariantFingerprint: 0
MISSING: 0
MISMATCH: 0
FAILED: 0
```

After the run:

```text
size: 37,252 bytes
lines: 276
normal VariantFingerprint: 4
MISSING: 0
MISMATCH: 0
FAILED: 0
```

## 4. Real Task

```text
task_id:
4c584137-7ee8-429b-9d98-b44f1fd783ec

tenant:
testduplicate

batch_size:
4

requested/planned/succeeded/failed:
4 / 4 / 4 / 0

duration:
119.1 seconds
```

Current-source flow plus four authoritative worker events proves the live request entered exact authoritative planning. The UI badge was not used as evidence.

## 5. Child Identities

| Child | execution_id | file_sid |
|---:|---|---|
| 0 | `62aad459-c67d-45db-8cc3-4ef396c3a76a` | `62aad459` |
| 1 | `5ee524d3-fc38-4834-9178-e77398310829` | `5ee524d3` |
| 2 | `2cf66cf6-4376-4e3f-bea8-4c39d4a20726` | `2cf66cf6` |
| 3 | `4b0b4d3e-45ff-4d02-9c3e-12fe4b2547c7` | `4b0b4d3e` |

All execution IDs and file SIDs are distinct.

## 6. VariantFingerprint Events

`VARIANT_FINGERPRINT_COUNT = 4`

| Child | execution_id | file_sid | Digest prefix | Beats | Match | Components | Truncated / fields |
|---:|---|---|---|---:|---|---:|---|
| 0 | `62aad459…` | `62aad459` | `e34ff61c1d7f` | 5 | true | 5 | false / false |
| 1 | `5ee524d3…` | `5ee524d3` | `1601c8695be0` | 5 | true | 5 | false / false |
| 2 | `2cf66cf6…` | `2cf66cf6` | `e1142b8554ce` | 5 | true | 5 | false / false |
| 3 | `4b0b4d3e…` | `4b0b4d3e` | `6cb5ee08fbdd` | 5 | true | 5 | false / false |

All four full digests are distinct and match `^[0-9a-f]{64}$`.

## 7. Event Contract

All four events satisfy:

```text
event: VariantFingerprint
phase: authoritative_worker_start
fingerprint_type: main_visual_planning
fingerprint_version: 1
source_hash_algorithm: md5
fingerprint_digest: 64 lowercase hexadecimal
beat_count: 5
planner_fingerprint_match: true
components count: 5
components_truncated: false
component_fields_truncated: false
```

## 8. Diagnostics

For the new task:

```text
FINGERPRINT_OBSERVABILITY_MISSING: 0
FINGERPRINT_OBSERVABILITY_MISMATCH: 0
FINGERPRINT_OBSERVABILITY_FAILED: 0
```

No FP observability finding.

## 9. Ordered Components

### Child 0 — `62aad459`

| Index | Beat | Asset | Normalized file hash |
|---:|---|---:|---|
| 0 | hook | 3 | `969c8e2660ad513d7fa52ebb8b05d18b` |
| 1 | context | 4 | `df00ae61ef305f355027e7fa8070142b` |
| 2 | build | 5 | `0e1afdd45dcc40f3235e800c445755b8` |
| 3 | reveal | 9 | `4a401508673b74f0817403b3e210cf15` |
| 4 | cta | 19 | `9f442bc76dfcbc1a6f205cbfd063de73` |

### Child 1 — `5ee524d3`

| Index | Beat | Asset | Normalized file hash |
|---:|---|---:|---|
| 0 | hook | 3 | `969c8e2660ad513d7fa52ebb8b05d18b` |
| 1 | context | 6 | `08a1691d53b489f44eaab7e9db24fd38` |
| 2 | build | 5 | `0e1afdd45dcc40f3235e800c445755b8` |
| 3 | reveal | 12 | `e405c756bcaa27c30c6cf58c4f25907a` |
| 4 | cta | 19 | `9f442bc76dfcbc1a6f205cbfd063de73` |

### Child 2 — `2cf66cf6`

| Index | Beat | Asset | Normalized file hash |
|---:|---|---:|---|
| 0 | hook | 3 | `969c8e2660ad513d7fa52ebb8b05d18b` |
| 1 | context | 6 | `08a1691d53b489f44eaab7e9db24fd38` |
| 2 | build | 5 | `0e1afdd45dcc40f3235e800c445755b8` |
| 3 | reveal | 12 | `e405c756bcaa27c30c6cf58c4f25907a` |
| 4 | cta | 13 | `05aafeb34a45642cab1dd44706d96b4f` |

### Child 3 — `4b0b4d3e`

| Index | Beat | Asset | Normalized file hash |
|---:|---|---:|---|
| 0 | hook | 3 | `969c8e2660ad513d7fa52ebb8b05d18b` |
| 1 | context | 6 | `08a1691d53b489f44eaab7e9db24fd38` |
| 2 | build | 5 | `0e1afdd45dcc40f3235e800c445755b8` |
| 3 | reveal | 9 | `4a401508673b74f0817403b3e210cf15` |
| 4 | cta | 19 | `9f442bc76dfcbc1a6f205cbfd063de73` |

All orders are exactly:

```text
0 hook
1 context
2 build
3 reveal
4 cta
```

## 10. FFmpeg Inputs

The first five master inputs before BGM were:

| Child | Ordered main-video sequence | Sixth input |
|---:|---|---|
| 0 | `16 → 18 → 24 → 55 → 03333` | `44444.mp3` |
| 1 | `16 → 28 → 24 → 68 → 03333` | `44444.mp3` |
| 2 | `16 → 28 → 24 → 68 → 108` | `44444.mp3` |
| 3 | `16 → 28 → 24 → 55 → 03333` | `44444.mp3` |

Each master filter graph confirms:

```text
concat=n=5
```

## 11. Fingerprint / FFmpeg Alignment

Read-only DAM lookup proved:

| Asset | Hash | Media path |
|---:|---|---|
| 3 | `969c8e…d18b` | `F:\test\sucai\16.mp4` |
| 4 | `df00ae…142b` | `F:\test\sucai\18.mp4` |
| 5 | `0e1afd…55b8` | `F:\test\sucai\24.mp4` |
| 6 | `08a169…fd38` | `F:\test\sucai\28.mp4` |
| 9 | `4a4015…cf15` | `F:\test\sucai\55.mp4` |
| 12 | `e405c7…907a` | `F:\test\sucai\68.mp4` |
| 13 | `05aafe…6b4f` | `F:\test\sucai\108.mp4` |
| 19 | `9f442b…de73` | `F:\test\sucai\03333.mp4` |

Both asset path and stored normalized hash were compared for every component.

```text
Child 0 FINGERPRINT_FFMPEG_ALIGNMENT: PASS
Child 1 FINGERPRINT_FFMPEG_ALIGNMENT: PASS
Child 2 FINGERPRINT_FFMPEG_ALIGNMENT: PASS
Child 3 FINGERPRINT_FFMPEG_ALIGNMENT: PASS
```

## 12. Combination Uniqueness

```text
16 → 18 → 24 → 55 → 03333
16 → 28 → 24 → 68 → 03333
16 → 28 → 24 → 68 → 108
16 → 28 → 24 → 55 → 03333
```

Full ordered combinations:

`4 / 4 UNIQUE`

No balanced-axis evaluation was performed.

## 13. Render Outputs

| Child | Master | Final | Cover |
|---:|---:|---:|---:|
| 0 | 28,247,254 bytes | 27,814,978 bytes | 178,209 bytes |
| 1 | 28,127,860 bytes | 27,671,770 bytes | 178,209 bytes |
| 2 | 28,693,434 bytes | 28,337,442 bytes | 178,209 bytes |
| 3 | 28,400,554 bytes | 28,028,781 bytes | 178,209 bytes |

Logs contain one master-success and one final-success event per child. TaskHistory records all four children as `succeeded`.

```text
Masters: 4/4
Finals: 4/4
Covers: 4/4
```

## 14. Execution Isolation

Confirmed:

```text
shared task_id: 1
unique execution_id: 4
unique file_sid: 4
```

Each child has execution-scoped:

- `voice_<execution_id>_en.mp3`
- `voice_<execution_id>_en.vtt`
- `sub_<execution_id>_en.ass`
- `master_video_<file_sid>.mp4`
- `final_en_<file_sid>.mp4`
- `cover_<file_sid>.jpg`

Execution isolation: `PASS`

## 15. BGM Sanity

Every final FFmpeg command contained exactly three inputs:

```text
1 master video
1 execution-scoped voice
1 BGM: F:\test\44444.mp3
```

Per child:

```text
voice inputs: 1
BGM inputs: 1
```

`BGM_DEDUP_SANITY: PASS`

## 16. Temporal Ordering

Physical log-line ordering:

| Child | FP event | First TTS | Subtitle | Compositor |
|---:|---:|---:|---:|---:|
| 0 | 5 | 10 | 40 | 75 |
| 1 | 6 | 16 | 53 | 142 |
| 2 | 7 | 14 | 27 | 76 |
| 3 | 9 | 18 | 66 | 177 |

For all children:

```text
VariantFingerprint
<
TTS
<
Compositor
```

This validates the `authoritative_worker_start` phase meaning.

## 17. Exactly Once

| Child | Normal VariantFingerprint INFO |
|---:|---:|
| 0 | 1 |
| 1 | 1 |
| 2 | 1 |
| 3 | 1 |

`EXACTLY_ONCE: PASS`

## 18. Logger Runtime Visibility

Previous real run:

```text
VariantFingerprint = 0
```

Current logger-aligned real run:

```text
VariantFingerprint = 4
```

The events are present in the normal DopaMatrix Loguru file alongside:

- TTS
- Subtitle
- Compositor
- Cover

`FP001B_LOGURU_RUNTIME_VISIBILITY: PASS`

## 19. Known Unrelated Warnings

Only one warning was visible:

```text
Ngrok authentication failure; local backend fallback remained active.
```

It occurred during backend startup before the test and is unrelated to FP-001B.

No task-related WARNING or ERROR was recorded.

UI-RF-01 was not evaluated or modified.

## 20. Acceptance Table

| Gate | Result |
|---|---|
| Current source runtime provenance | PASS |
| AI Draft exact policy | PASS |
| 4 child executions | PASS |
| VariantFingerprint INFO ×4 | PASS |
| main_visual_planning v1 | PASS |
| 5 Beats ×4 | PASS |
| planner match true ×4 | PASS |
| No fingerprint diagnostics | PASS |
| Fingerprint ↔ FFmpeg alignment ×4 | PASS |
| Exactly-once ×4 | PASS |
| 4 unique full combinations | PASS |
| 4 master renders | PASS |
| 4 final renders | PASS |
| 4 covers | PASS |
| Execution isolation | PASS |
| BGM dedup sanity | PASS |
| Loguru runtime visibility | PASS |

## 21. Final Classification

FP001B_REAL_MEDIA_ACCEPTANCE_PASS

## 22. Commit Recommendation

FP001B_APPROVED_FOR_COMMIT

No commit or push was performed.

## 23. Final Git Status

```text
branch:
feature/var-001-variation-policy

HEAD:
35d63cd905c96fd2fa5d62162023ee07de3110fe

status:
 M src/api/routes_dsl.py
?? doc/investigations/fingerprint/FP-001B-Logger-Alignment-Small-Fix-up-Report.md
?? doc/investigations/fingerprint/FP-001B-Runtime-Fingerprint-Observability-Implementation-Report.md
?? doc/investigations/fingerprint/FP-001B-Runtime-VariantFingerprint-Reachability-Audit.md
?? doc/investigations/fingerprint/FP-001B-Small-Fix-up-Report.md
?? doc/investigations/fingerprint/FP-001B-Targeted-Runtime-Observability-Code-Review-Bundle.md
?? tests/test_fp001_fingerprint_observability.py
```

`git diff --check` passed with only the existing LF→CRLF advisory. Backend remains running.