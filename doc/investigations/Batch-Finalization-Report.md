# INV-001 Gate 3 Phase 2 — Batch Finalization Report

## 1. Baseline

- Branch: `fix/creative-duplicate-detection`
- Starting commit: `96eb6ee9399aff19aa3a74fa8ca209556e76205a`
- Starting status: CLEAN
- 未创建分支、commit 或 push。

## 2. Files Changed

- [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:139)
  - 增加内部 `_ChildResult`。
  - `render_worker` 改为返回结构化 child result。
  - TaskHistory 写入迁移到 coordinator。
  - `batch_size=1` 和 `batch_size>1` 统一进入 `render_batch_worker`。
  - 增加稳定聚合、partial/failure 计算和唯一 terminal WS。

- [compositor.py](E:/dopaworkspace/dopamatrix-desktop/src/nodes/compositor.py:139)
  - 使用显式 `ws_terminal_managed_by_coordinator` 标记。
  - coordinator child 抑制三个 `failed` 发送点。
  - legacy direct-call 行为保持。

- [test_inv001_execution_isolation.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_execution_isolation.py:75)
  - Phase 1 dispatch 测试适配统一 coordinator。
  - 继续验证 child identity 与 Context contract。

- [test_inv001_batch_finalization.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_batch_finalization.py:181)
  - 新增 15 个 Phase 2 focused tests。

## 3. Finalization Contract Implemented

Child 现在负责：

- execution-local resolve/Timeline/Context
- TTS、Subtitle、Compositor、Cover
- final assets/hash
- usage_count 原有回写
- 返回 `_ChildResult`

Coordinator 现在负责：

- 创建并 dispatch child
- 收集和稳定排序 child results
- 决定 completed/partial/failed
- 写一条 TaskHistory
- 发送一个 terminal WebSocket event

## 4. Single-Child Path

`submit_dsl`、`submit_manual`、`render_dsl` 无论 batch size，均调度 `render_batch_worker`。

`batch_size=1` 时 coordinator 直接调用一次 child execution，不创建 `ThreadPoolExecutor(1)`，但仍经过完全相同的 history/terminal finalizer。

## 5. Child Result Structure

内部 `_ChildResult` 包含：

- `child_index`
- `execution_id`
- `file_sid`
- `outcome`
- `assets`
- `elapsed`
- `error_code`
- 精简 `error_message`
- execution-local `prompt_details` snapshot

未加入 fingerprint、Variant ID 或 Phase 3 planning 字段。

## 6. TaskHistory Migration

BEFORE：

```text
each render_worker
→ TaskHistory(shared task_id)
→ INSERT / commit
```

AFTER：

```text
all child results
→ stable aggregation
→ coordinator
→ exactly one TaskHistory INSERT
```

保留：

- shared `task_id`
- requested `batch_size`
- coordinator wall-clock `duration`
- successful final `output_assets`
- JSON-text `prompt_details`
- `created_at`

Top-level legacy `meta` / `timeline` 来自按 `child_index` 排序后的第一个成功 child。新增 `planning_summary` 和 `children` metadata，不修改数据库 schema。零成功时不写 history。

## 7. Terminal WebSocket Ownership

已调整的 terminal 来源：

- worker 空 Timeline：不再发送 `failed`
- worker 主视觉预检失败：不再发送 `failed`
- worker render 完成：不再发送 `completed/failed`
- Compositor FFmpeg 缺失：coordinator child 不发送 `failed`
- Compositor master render 失败：coordinator child 不发送 `failed`
- Compositor variant render 失败：coordinator child 不发送 `failed`

Compositor 的 running/progress 保留。没有 coordinator marker 的 legacy direct call 仍保持原有 failed 行为。

Coordinator 最终发送一次：

```text
completed | failed
```

并包含 optional additive fields：

- `partial`
- `requestedCount`
- `plannedCount`
- `succeededCount`
- `failedCount`
- `historyPersisted`
- `warningCodes`
- `assets`

## 8. Partial / Failure Semantics

| 情况 | Terminal | History |
|---|---|---|
| 全部成功 | `completed`, `partial=false` | 一行，全部成功输出 |
| 部分 child 失败 | `completed`, `partial=true` | 一行，仅成功输出 |
| 全部失败 | `failed`, `partial=false` | 不写 |
| History commit 失败 | 保持 `completed`/原 partial 状态；`historyPersisted=false`；`HISTORY_PERSIST_FAILED` | 写入失败但不重新 render |

Child 部分失败使用 `CHILD_EXECUTION_FAILED` warning。

## 9. Stable Aggregation

所有 child result 在 finalization 前按 `child_index` 排序，然后：

- 选择第一个成功 child 的 legacy metadata
- 序列化 `prompt_details.children`
- flatten successful assets
- 生成 terminal assets

因此 futures 完成顺序不会影响 history 或 WS 输出顺序。

## 10. Blind / Manual Compatibility

- Blind 仍在 child 内执行 Director 和 resolver。
- Manual 仍保留 raw DSL 优先触发 execution-local resolve 的现有行为。
- AI Draft candidate selection、Manual explicit intent、Blind Director 行为均未改变。
- 旧 `run_matrix_job` 路径未修改。
- 本 Phase 未修改 frontend；backend 已提供 partial/count/warning 字段，但现有 UI 尚未新增显式 warning 展示。

## 11. Tests Added

| Test contract | Coverage |
|---|---|
| T1 | batch_size=1，一行 history、一个 completed |
| T2 | batch_size=4，一行 history、4 outputs、一个 terminal |
| T3 | 成功 worker 不创建 TaskHistory |
| T4 | 3 success + 1 fail，completed partial |
| T5 | 全失败，无 history，一个 failed |
| T6 | history commit failure 不反转 render success |
| T7 | worker 不发送 terminal completed |
| T8 | worker 两个早退及 Compositor 三个失败分支均不终结 task |
| T9 | reverse future completion 后仍按 child_index 排序 |
| T10 | Blind 继续走 Director，finalization 一次 |
| T11 | Manual 继续 raw DSL resolve，finalization 一次 |

另覆盖 legacy Compositor failed WS 行为保持。

## 12. Test Results

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_execution_*.py" -q
```

结果：`Ran 24 tests — OK`

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_batch_finalization.py" -q
```

结果：`Ran 15 tests — OK`

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

结果：`Ran 39 tests — OK`

```powershell
.\venv_build\Scripts\python.exe -m py_compile src/api/routes_dsl.py src/nodes/compositor.py tests/test_inv001_execution_isolation.py tests/test_inv001_execution_paths.py tests/test_inv001_batch_finalization.py
```

结果：PASS

预期的模拟 history commit/FFmpeg failure 日志在测试中出现，但断言全部通过。

## 13. Scope Audit

以下均未改变：

- candidate resolution
- CompilationPlan generation
- asset scoring
- `random.choice`
- usage_count 算法
- Variant planning
- fingerprint
- Diversity policy
- BGM merge
- Manual diversity semantics
- Blind diversity semantics
- TTS/Subtitle identity contract
- DB schema/migration
- frontend

## 14. Risks / Open Questions

- 用户复用同一 `session_id/task_id` 发起两个独立提交时，仍可能撞 `TaskHistory.task_id`；现在会保留视频并报告 `HISTORY_PERSIST_FAILED`。
- 同一 task 下多个 child 的 running/progress 仍可能交错；本 Phase 仅统一 terminal ownership。
- partial warning 的显式 UI 展示尚未实施。
- usage_count 并发 read-modify-write 风险保持未变。
- `schemas.py` 的 batch identity 描述债务未处理。
- `datetime.utcnow()` 会产生 Python 3.12 deprecation warning；保持了原 persistence 时间语义，本 Phase 未扩展清理。
- 未执行正式视频生成、真实网络 TTS 或 installer build。

## 15. Git Review

`git status --short`：

```text
 M src/api/routes_dsl.py
 M src/nodes/compositor.py
 M tests/test_inv001_execution_isolation.py
?? tests/test_inv001_batch_finalization.py
```

`git diff --stat`：

```text
 src/api/routes_dsl.py                    | 552 +++++++++++++++++--------------
 src/nodes/compositor.py                  |  20 +-
 tests/test_inv001_execution_isolation.py |  80 ++++-
 3 files changed, 385 insertions(+), 267 deletions(-)
```

新测试文件仍为 untracked，因此普通 `git diff --stat` 不包含其 634 行。

`git diff --check`：PASS，仅有现有 LF→CRLF working-copy warnings。

未 commit，未 push，未进入 Phase 3。