# INV-001 Gate 3 Phase 5 — Formal Repro001 / Repro002 Real-Media Closure Report

## 1. Baseline

- Branch: `fix/creative-duplicate-detection`
- Commit: `5a5639ca6afc055fff90355093aa2b43be6f8cc4`
- Starting worktree: CLEAN
- No source/test/frontend/schema changes were made.

## 2. Formal Repro Procedure Recovery

Procedure recovered from:

- [Experiment Summary](E:/dopaworkspace/dopamatrix-desktop/doc/investigations/evidence/INV-001-experiment-summary.md)
- [Repro001 Report](E:/dopaworkspace/dopamatrix-desktop/doc/investigations/evidence/INV-001-repro-001/INV-001-repro-001.md)
- [Repro001 SHA Log](E:/dopaworkspace/dopamatrix-desktop/doc/investigations/evidence/INV-001-repro-001/logs/SHA-256.log)
- [Repro002 Report](E:/dopaworkspace/dopamatrix-desktop/doc/investigations/evidence/INV-001-repro-002/INV-001-repro-002.md)
- [Repro002 SHA Log](E:/dopaworkspace/dopamatrix-desktop/doc/investigations/evidence/INV-001-repro-002/logs/SHA-256.log)

Recovered common procedure:

- Tenant: `testduplicate`
- Formal AI Draft workflow
- `variant_planning_policy=exact_main_visual`
- Batch size: 4
- Aspect: 9:16
- Language: EN
- TTS/subtitles enabled
- Hook: 12/13/16/58 plus `hook:汽车减震器`
- Context: 18/28
- Build: 24
- BGM: 44444.mp3
- Complete Tauri/backend restart between runs
- No DB, usage, asset, or project reset

Historical decoded-video method was reused exactly:

```powershell
.\ffmpeg.exe -v error -i "<file>" -map 0:v:0 -f hash -hash sha256 -
```

## 3. Environment

- Python: `3.12.10`
- Node: `v22.23.1`
- npm: `10.9.8`
- FFmpeg: `8.0.1 essentials_build`
- Backend: real `main.py` process
- Frontend: real Vite development server
- Desktop: real Tauri debug application
- Local backend/frontend health checks: HTTP 200

Runtime evidence:

- Repro001: `C:\Users\chenp\AppData\Local\Temp\INV001-Phase5-20260824-174832`
- Repro002: `C:\Users\chenp\AppData\Local\Temp\INV001-Phase5-Repro002-20260824-180316`

## 4. Preflight Candidate Capacity

Real read-only SQLite plus production `DSLParserNode` discovery produced:

| Beat | Asset | Asset ID | Normalized file hash | Type |
|---|---:|---:|---|---|
| Hook | 12.mp4 | 1 | `846de2afceaf8677a4e7bcdb680762ec` | video |
| Hook | 13.mp4 | 2 | `f0a5c247219ff997f6bdf9800e5e96dd` | video |
| Hook | 16.mp4 | 3 | `969c8e2660ad513d7fa52ebb8b05d18b` | video |
| Hook | 58.mp4 | 11 | `e1d29ce2e193377c8b561e998ff0036d` | video |
| Context | 18.mp4 | 4 | `df00ae61ef305f355027e7fa8070142b` | video |
| Context | 28.mp4 | 6 | `08a1691d53b489f44eaab7e9db24fd38` | video |
| Build | 24.mp4 | 5 | `0e1afdd45dcc40f3235e800c445755b8` | video |

Effective exact-combination capacity:

`4 × 2 × 1 = 8`

All assets were resolver-valid, present, not deleted, and not exhausted. Capacity was therefore sufficient for both batch-size-4 runs.

Phase 4 preflight also proved that physical BGM ID 17 could be returned again by semantic Y resolution:

- Path: `F:\test\44444.mp3`
- Hash: `4a113f7af281e54fd8311d7a10ac8daf`

This was a real defect-triggering shape, not an artificial non-duplicate control.

## 5. Historical Failure Baseline

| Historical run | Failure |
|---|---|
| Repro001 | `6451b32e` and `db4d3533` both resolved to 13→28→24 and had identical master/final decoded-video hashes |
| Repro002 | `5a9895d4`, `470778f4`, `13e26247` all resolved to 12→18→24 |
| Repro002 | `470778f4` and `13e26247` were full exact duplicates |
| Both | Children shared one full task UUID |
| Both | TTS/VTT/ASS writable paths shared that UUID |
| Both | Multiple TaskHistory inserts used the same unique `task_id` |
| Hook | Physical and semantic resolution could append the same BGM twice |

## 6. Closure Repro001 Input

Prompt:

> 探索汽车减震器的神奇世界，感受每一次颠簸都被轻柔化解的惊艳体验!@hook:汽车减震器

Settings matched the recovered Formal Repro procedure exactly.

## 7. Closure Repro001 Planning

- Task ID: `7542061e-750e-4ac0-b066-729f0acad657`
- Requested: 4
- Planned: 4
- Succeeded: 4
- Failed: 0
- Warning codes: none
- Termination: request satisfied; the internal termination enum was not persisted separately.

Accepted main-X combinations:

1. 16→18→24
2. 16→28→24
3. 58→18→24
4. 58→28→24

`len(set(fingerprints)) == 4`

## 8. Closure Repro001 Child Identity

| Child | execution_id | file_sid |
|---:|---|---|
| 0 | `66298294-3d86-4479-af20-679df4b15787` | `66298294` |
| 1 | `cda0cbe5-64ea-4193-8fd7-97b812c62262` | `cda0cbe5` |
| 2 | `3b5573b9-9869-47bf-a0fd-72fa98ed011e` | `3b5573b9` |
| 3 | `06e76cc5-f7d1-4262-bfd6-407ebd860c11` | `06e76cc5` |

- Full execution IDs: 4/4 unique
- File tokens: 4/4 unique
- Child indices: exactly `0,1,2,3`

## 9. Closure Repro001 Actual Main-X Plans

The persisted `prompt_details.children[].timeline` and actual FFmpeg input commands agreed:

| Child | Hook | Context | Build |
|---:|---|---|---|
| 0 | ID 3 / 16.mp4 | ID 4 / 18.mp4 | ID 5 / 24.mp4 |
| 1 | ID 3 / 16.mp4 | ID 6 / 28.mp4 | ID 5 / 24.mp4 |
| 2 | ID 11 / 58.mp4 | ID 4 / 18.mp4 | ID 5 / 24.mp4 |
| 3 | ID 11 / 58.mp4 | ID 6 / 28.mp4 | ID 5 / 24.mp4 |

This proves that authoritative plans were not merely planned; their selected inputs reached the real compositor.

## 10. Closure Repro001 Y-Layer Evidence

Every Hook contained:

- Layer 0: selected video/main-X
- Layer 1: BGM ID 17
- No second occurrence of BGM ID 17

Per-Beat same-hash BGM occurrence count: `1`.

Duplicate count: `0`.

## 11. Closure Repro001 Media Hashes

| SID | Master file SHA-256 | Master decoded-video SHA-256 | Final file SHA-256 | Final decoded-video SHA-256 |
|---|---|---|---|---|
| `66298294` | `f1fcda7cc1dd80e4aee5aceab3ddd425ce477b9ce29d64ce111648d7b92e7e35` | `d570071c9749f6b33f7f70cf70cf52da603873739c553516a3143cb4e159e356` | `5022abac8279a8c9b0d5a09b1703dc6df81f58459b390c542be837b4b50f1013` | `2d390948b67ab374140c2cb153ec2844e798339b34119ffbd4f5303970ac0da6` |
| `cda0cbe5` | `b9ace0343f5bac73a763402f8f2b5b4e873e8048d80ec60e7f9d0a8013e9467a` | `54b4e3bfb84aff5b8becf6cbf0808a0979db44230971c43f5e8fb933fae8939f` | `38e15567b761c83f219355318da89b7ed0ca82b52a1d5a6be49c969d08e91835` | `258ba6df694279291e9c09903badc8caadc06ab53fdbc453c2cbdce741eb7fb6` |
| `3b5573b9` | `96629c02044c102bf3fb6ef87f17113276a75d294dbadfe567b8c02081ca3aaa` | `a9a0f3d619ee1ddac6b5f2ac9470bfc95a466f352d0c292d60e5087836f67e9e` | `d1b968330a7eb0f4afc8826591fe7a56012f5f4a42bcd90b2d8260f39eee747d` | `39e8056160311aec85b06842ed55eec16fdccdb50e5eb4ad80e3e753a7cce9fb` |
| `06e76cc5` | `bd60378f0c8463e5fc272cc2e77e4b153966fbe822fd042466fd5a9ba1c92cdb` | `a48a264d3047f41143bd60eb1cc7787e9f1b16e35eb9761228c0cd0802545b3b` | `ea1a9b0b71e5b21eb91e731d639aa734e26ae8e31217b247f3f4d4d0c48ad957` | `987a76f5f430fbf1b20be012ea68facbf4e5932f1d4309224d0a028197944da6` |

Result:

- Master file hashes: 4/4 unique
- Master decoded-video hashes: 4/4 unique
- Final file hashes: 4/4 unique
- Final decoded-video hashes: 4/4 unique
- Supplemental decoded-audio hashes: 4/4 unique

## 12. Closure Repro001 History / WS

- Exactly one TaskHistory row for the shared task ID
- `batch_size=4`
- Four successful outputs in stable child-index order
- `historyPersisted=true`
- No `UNIQUE constraint` failure
- No `HISTORY_PERSIST_FAILED`
- No `CHILD_EXECUTION_FAILED`

Runtime logs do not serialize terminal WS payloads. Exactly-one ownership is cross-proven by:

- Every real child had `ws_terminal_managed_by_coordinator=true` through the production worker path.
- Compositor terminal failure emits are suppressed for coordinator children.
- Production finalizer contains one terminal `broadcast_sync` call.
- Exactly one coordinator history row was committed.
- The formal UI received the completed outcome.
- Focused finalizer tests assert one terminal call; all passed.

Terminal WS count: PASS, with source/runtime/test cross-evidence rather than packet-level capture.

## 13. Repro001 Result

PASS.

No repeated main fingerprint, decoded master video, child identity, writable path, history row, or same-Beat BGM occurrence.

## 14. Environment Restart Evidence

After Repro001:

- Tauri, WebView, Cargo, Vite, backend, and child processes were stopped.
- Ports 8000 and 5173 were confirmed free.
- Database, project, assets, usage counts, and output history were not reset.
- A new full application environment was started.
- Repro001 app PID: `15480`
- Repro002 app PID: `3196`
- New backend/frontend health checks returned 200.

## 15. Closure Repro002 Input

Prompt:

> 无论是颠簸的山路还是城市的平坦街道，汽车减震器都能带来无与伦比的驾驶舒适感，让你在每一次旅程中都能享受平稳与安宁的体验。@hook:汽车减震器

All other settings and candidate pools matched the Formal Repro procedure.

## 16. Closure Repro002 Planning

- Task ID: `f5747e7c-5f73-4982-8a83-4ff948c60424`
- Requested: 4
- Planned: 4
- Succeeded: 4
- Failed: 0
- Warning codes: none

Accepted combinations:

1. 16→18→24
2. 16→28→24
3. 58→18→24
4. 58→28→24

`len(set(fingerprints)) == 4`

## 17. Closure Repro002 Child Identity

| Child | execution_id | file_sid |
|---:|---|---|
| 0 | `6035e558-6161-4ad3-9032-c6e952afb455` | `6035e558` |
| 1 | `add2f9ad-0913-4b48-bc4b-900dd90020c5` | `add2f9ad` |
| 2 | `ea346cc8-b063-4e2a-928d-bd0d952267ca` | `ea346cc8` |
| 3 | `060c034d-2a60-4a51-bc5d-952455f8750e` | `060c034d` |

All execution IDs and file tokens were unique.

## 18. Closure Repro002 Actual Main-X Plans

| Child | Hook | Context | Build |
|---:|---|---|---|
| 0 | ID 3 / 16.mp4 | ID 4 / 18.mp4 | ID 5 / 24.mp4 |
| 1 | ID 3 / 16.mp4 | ID 6 / 28.mp4 | ID 5 / 24.mp4 |
| 2 | ID 11 / 58.mp4 | ID 4 / 18.mp4 | ID 5 / 24.mp4 |
| 3 | ID 11 / 58.mp4 | ID 6 / 28.mp4 | ID 5 / 24.mp4 |

TaskHistory timelines and real FFmpeg input commands matched for all four children.

## 19. Closure Repro002 Y-Layer Evidence

For every Hook:

- Layer 0 was the authoritative video/main-X.
- BGM ID 17 appeared once at layer 1.
- No duplicate occurrence of its normalized hash existed.

Phase 4 real-media result: PASS.

## 20. Closure Repro002 Media Hashes

| SID | Master file SHA-256 | Master decoded-video SHA-256 | Final file SHA-256 | Final decoded-video SHA-256 |
|---|---|---|---|---|
| `6035e558` | `f1fcda7cc1dd80e4aee5aceab3ddd425ce477b9ce29d64ce111648d7b92e7e35` | `d570071c9749f6b33f7f70cf70cf52da603873739c553516a3143cb4e159e356` | `69f49ddfb98980b72e2c89bb60836da00a55c1ea012c7d98509ebcdf9918af84` | `f966499fdf8be06ab048ef465fdbcb7583d6f9e8f80c73ac6a900ea5b282faa6` |
| `add2f9ad` | `b9ace0343f5bac73a763402f8f2b5b4e873e8048d80ec60e7f9d0a8013e9467a` | `54b4e3bfb84aff5b8becf6cbf0808a0979db44230971c43f5e8fb933fae8939f` | `4131814c39a2e408f8e1a9313deda6cd3df2d5e5f5b5e7c8b2043e19ccb03bc8` | `f05d2dde6af2228589ccbfa28798338d0566517234af4aecda5833bc194691be` |
| `ea346cc8` | `96629c02044c102bf3fb6ef87f17113276a75d294dbadfe567b8c02081ca3aaa` | `a9a0f3d619ee1ddac6b5f2ac9470bfc95a466f352d0c292d60e5087836f67e9e` | `35c41b5dd1b52e03bdd22fe1986ff62d77db361bfa93527c3268c2a9e055029d` | `9c2bf932ba2cac112dde90d398f3eea06f7879297bfe6069e42fe86e2d6c271e` |
| `060c034d` | `bd60378f0c8463e5fc272cc2e77e4b153966fbe822fd042466fd5a9ba1c92cdb` | `a48a264d3047f41143bd60eb1cc7787e9f1b16e35eb9761228c0cd0802545b3b` | `2a2a5934438dcebef064fcbf406ce6aa6ab300f78274fd121d41d69163d9084f` | `a0356afb98532627b4acc2baa6e55cd2b4c84219084fbb7537e175172a1fbbfc` |

Result:

- Master file hashes: 4/4 unique
- Master decoded-video hashes: 4/4 unique
- Final file hashes: 4/4 unique
- Final decoded-video hashes: 4/4 unique
- Supplemental decoded-audio hashes: 4/4 unique

Identical master hashes across Repro001 and Repro002 correspond to identical authoritative visual plans across separate runs. This is expected deterministic rendering and is not an intra-batch duplicate.

## 21. Closure Repro002 History / WS

- One TaskHistory row
- `batch_size=4`
- Four successful outputs
- Stable child ordering
- No history collision
- No terminal warning
- Exactly-one terminal ownership cross-check: PASS

The only runtime stderr issue was an unrelated ngrok authentication failure during startup. Local backend, frontend, Tauri, TTS, subtitles, and FFmpeg rendering all completed normally.

## 22. Repro002 Result

PASS.

The historical 12→18→24 three-child duplication pattern did not recur.

## 23. Output Collision Audit

For every child in both runs, all of the following existed under its own namespace:

- `master_video_<file_sid>.mp4`
- `final_en_<file_sid>.mp4`
- `cover_<file_sid>.jpg`
- `voice_<full-execution-id>_en.mp3`
- `voice_<full-execution-id>_en.vtt`
- `sub_<full-execution-id>_en.ass`

No shared writable child path or overwrite evidence was observed.

## 24. Cache Audit

Runtime logs contained no:

- cache hit
- rendered-master reuse
- final-video reuse
- result reuse

Fresh FFmpeg commands and new mtimes were recorded for every child.

`NO CACHE BEHAVIOR OBSERVED`

## 25. Before / After Comparison

| Defect | Historical | Closure |
|---|---|---|
| Repro001 repeated main combination | Present | 4/4 unique |
| Repro001 repeated master decoded video | Present | 4/4 unique |
| Repro002 repeated main combination | Three identical | 4/4 unique |
| Repro002 full exact duplicate | Present | None |
| Child execution identity | Shared UUID | Four full UUIDs |
| File token | Ambiguous/shared lifecycle | Four unique file_sids |
| TTS/VTT/ASS paths | Shared | Child isolated |
| TaskHistory | UNIQUE collision | One row per batch |
| Terminal ownership | Child competition | Coordinator-owned once |
| Same-Beat BGM | Could appear twice | One occurrence |

## 26. Real-Media Closure Matrix

| Metric | Repro001 | Repro002 |
|---|---:|---:|
| Requested | 4 — PASS | 4 — PASS |
| Planned | 4 — PASS | 4 — PASS |
| Succeeded | 4 — PASS | 4 — PASS |
| Unique execution_id | 4/4 — PASS | 4/4 — PASS |
| Unique file_sid | 4/4 — PASS | 4/4 — PASS |
| Unique main fingerprint | 4/4 — PASS | 4/4 — PASS |
| Unique master file SHA | 4/4 — PASS | 4/4 — PASS |
| Unique master decoded-video hash | 4/4 — PASS | 4/4 — PASS |
| Unique final file SHA | 4/4 — PASS | 4/4 — PASS |
| Unique final decoded-video hash | 4/4 — PASS | 4/4 — PASS |
| Same-Beat BGM duplicates | 0 — PASS | 0 — PASS |
| TaskHistory rows | 1 — PASS | 1 — PASS |
| Terminal WS ownership/count | 1 — PASS | 1 — PASS |
| INV-001 warnings | None — PASS | None — PASS |
| Result | PASS | PASS |

## 27. INV-001 Regression Tests

Command:

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

Result:

```text
Ran 82 tests in 0.795s
OK
```

## 28. Git Status

Final state:

- Branch: `fix/creative-duplicate-detection`
- Commit: `5a5639ca6afc055fff90355093aa2b43be6f8cc4`
- Worktree: CLEAN
- `git diff --check`: PASS
- Ports 8000/5173: released
- No commit or push performed

## 29. Final Classification

FINAL CLOSED