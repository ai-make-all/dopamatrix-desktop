# INV-001 Gate 3 Phase 1 — Execution Isolation Report

Phase 1 已完成。Child execution identity、TTS/VTT/ASS writable namespace 及 master/final/cover 短文件 token 已隔离；未实施 Phase 2、Planner、Diversity、TaskHistory 或 WebSocket 终态改造。

## 1. Baseline

- Branch: `fix/creative-duplicate-detection`
- Starting commit: `9c03d81391e1b253aef7fe0eaf166efa8d7c228e`
- Starting worktree: dirty
- Starting status:

```text
?? doc/investigations/INV-001-Gate2-Fix-Architecture-Plan.md
```

该 Gate 2 文档为本轮开始前已存在的未跟踪文件，本轮未修改。

## 2. Files Changed

- [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:130)
  - 增加内部 `_ChildExecution`。
  - 统一创建、验证和传播 child identity。
  - batch=1 与 batch>1 使用同一身份规则。
  - 增加 child 级日志关联。

- [tts_node.py](E:/dopaworkspace/dopamatrix-desktop/src/nodes/tts_node.py:42)
  - MP3/VTT 改用完整 `execution_id`。
  - 保留明确的 legacy/direct-call fallback。

- [subtitle.py](E:/dopaworkspace/dopamatrix-desktop/src/nodes/subtitle.py:40)
  - 精准 VTT 和降级字幕路径均改用完整 `execution_id`。
  - 保留 legacy fallback。

- [compositor.py](E:/dopaworkspace/dopamatrix-desktop/src/nodes/compositor.py:67)
  - master/final 优先使用明确的 `file_sid`。
  - 旧 factory 仍可 fallback 到 legacy `config["session_id"]`。

- [cover_node.py](E:/dopaworkspace/dopamatrix-desktop/src/nodes/cover_node.py:124)
  - cover 优先使用 `file_sid`。
  - 保留原有 legacy fallback 顺序。

- [test_inv001_execution_isolation.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_execution_isolation.py:86)
  - child identity、dispatch、Context、disabled flags 测试。

- [test_inv001_execution_paths.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_execution_paths.py:48)
  - TTS/VTT/ASS、master/final/cover、legacy fallback 测试。

没有修改 `WorkflowContext`、schema、model、数据库、frontend 或 investigation 文档。

## 3. Identity Contract Implemented

- `task_id`
  - 保持 submitted task / batch / UI / WebSocket identity。
  - 一个 batch 中所有 child 共享。
  - 未用于新 writable namespace。

- `execution_id`
  - 每个 child 创建一个完整 UUID4。
  - batch=1 同样创建。
  - 同一任务重新提交会生成新 ID。
  - 明确验证不等于 `task_id`。

- `file_sid`
  - 由 `execution_id` 的 UUID hex 前 8 位派生。
  - 只用于短输出文件名。
  - coordinator 检测 batch-local collision 并重新生成，最多尝试 100 次。
  - 不是 authoritative identity，也不是 `variant_id`。

- `child_index`
  - 内部使用零起始索引。
  - batch=1 为 `0`，batch=4 为 `0..3`。

## 4. Context Propagation

`render_worker` 当前设置：

```text
context.session_id                 = task_id
context.config["execution_id"]     = full child UUID
context.config["file_sid"]         = derived short token
context.config["child_index"]      = zero-based child index
```

新 API 路径不再写入 `context.config["session_id"]`。

如果带有新 child marker 的 Context 缺失 `execution_id` 或 `file_sid`，相应 writable/output node 会 fail-fast，不会回退到共享 `task_id`。

## 5. TTS / VTT Isolation

旧 API batch 路径：

```text
voice_<shared-task-id>_<lang>.mp3
voice_<shared-task-id>_<lang>.vtt
```

新路径：

```text
voice_<full-execution-id>_<lang>.mp3
voice_<full-execution-id>_<lang>.vtt
```

MP3 的 `wb` 和 VTT 的 `w` 写入模式未改变，但不同 child 不再共享目标路径。

旧 `run_factory` / `run_matrix_factory` 直接调用缺少 `execution_id`，因此保留带 warning 的 legacy fallback；测试覆盖了真实的 `batch_size>1` legacy Context 形态。

## 6. Subtitle ASS Isolation

旧 API batch 路径：

```text
sub_<shared-task-id>_<lang>.ass
```

新路径：

```text
sub_<full-execution-id>_<lang>.ass
```

精准 VTT 分支和降级 Dialogue 分支都使用同一个 execution namespace。无文本 skip 行为保持不变。

## 7. Output Filename Compatibility

用户可见命名格式保持不变：

```text
master_video_<file_sid>.mp4
final_<lang>_<file_sid>.mp4
cover_<file_sid>.jpg
```

变化仅在 token 来源：

```text
before: config["session_id"] / ambiguous session token
after:  config["file_sid"] derived from execution_id
```

Compositor 与 Cover 均已增加 execute-level fake-FFmpeg/fake-extraction 测试，证明实际 handoff 使用 `file_sid`。

## 8. Blind / Manual Compatibility

以下入口均获得相同的 execution isolation：

- AI Draft `submit-dsl`
- Blind `submit-dsl`
- Manual `submit-manual`
- `render-dsl`
- batch=1
- batch>1

未改变任何模式的：

- asset selection
- resolver
- diversity policy
- CompilationPlan 行为
- Manual explicit-user-intent 语义

旧 Matrix factory 路径继续通过明确的 legacy fallback 工作。

## 9. Tests Added

新增 23 个 focused tests，覆盖：

- batch=1 execution identity。
- batch=4 四个 execution/file token 唯一、共享 task ID。
- file token collision retry。
- 同一 endpoint rerun 产生新 execution ID。
- AI Draft、Blind、Manual、render-dsl dispatch。
- Context identity propagation。
- TTS/Subtitle disable flags 独立行为及 batch flag propagation。
- 两个 child 的 MP3/VTT/ASS 路径隔离。
- VTT 精准字幕分支。
- empty script/text skip。
- legacy factory/direct-call fallback。
- 新 child 缺 identity/file token 时 fail-fast。
- master/final/cover 命名与实际 handoff。

## 10. Test Results

PASS：

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_execution_*.py" -q
```

结果：

```text
Ran 23 tests
OK
```

PASS：

```powershell
.\venv_build\Scripts\python.exe -m py_compile src/api/routes_dsl.py src/nodes/tts_node.py src/nodes/subtitle.py src/nodes/compositor.py src/nodes/cover_node.py tests/test_inv001_execution_isolation.py tests/test_inv001_execution_paths.py
```

PASS：

```powershell
git diff --check
```

只有现有 Git LF→CRLF working-copy warning。

Pytest runner 不可用：

```powershell
.\venv_build\Scripts\python.exe -m pytest --version
```

```text
No module named pytest
```

因此使用标准库 `unittest` 执行；新增测试仍采用 pytest 可收集的测试命名。未运行正式视频生成、网络 TTS 或真实 FFmpeg。

## 11. Out-of-Scope Findings

本轮有意未处理：

- `render_worker` 内 per-child TaskHistory INSERT。
- `task_history.task_id` UNIQUE collision。
- coordinator-owned terminal WebSocket。
- partial result/status。
- authoritative batch plans。
- exact diversity/fingerprint/planner。
- BGM double Y-layer。
- Blind/Manual diversity。
- DB schema 和 migration。

另外，[schemas.py](E:/dopaworkspace/dopamatrix-desktop/src/api/schemas.py:382) 的 `batch_size` 描述仍写着每个 child 拥有唯一 `task_id`，与正式 shared-task identity contract 不一致；按 Phase 1 文件范围未修改。

## 12. Risks / Open Questions

- `file_sid` 是 32-bit 短 token；本实现保证 batch 内唯一，但不提供跨 batch 的持久唯一保证。
- worker identity validation 位于主 `try/finally` 之前。若未来内部调用错误地传入非法 identity，会 fail-fast，但 single BackgroundTask 不会打印正常 child-finish 日志。
- legacy fallback 依赖旧 factory 的 `context.session_id` 本身已是 child-specific；新增测试锁定了这一兼容行为。
- 本轮没有执行真实媒体集成测试，只执行了 mock resolver、mock TTS 和 mock FFmpeg 的 focused tests。

## 13. Git Review

当前：

```text
 M src/api/routes_dsl.py
 M src/nodes/compositor.py
 M src/nodes/cover_node.py
 M src/nodes/subtitle.py
 M src/nodes/tts_node.py
?? doc/investigations/INV-001-Gate2-Fix-Architecture-Plan.md
?? tests/test_inv001_execution_isolation.py
?? tests/test_inv001_execution_paths.py
```

`git diff --stat`：

```text
 src/api/routes_dsl.py   | 179 ++++++++++++++++++++++++++++++++++++++++--------
 src/nodes/compositor.py |  50 ++++++++++++--
 src/nodes/cover_node.py |  36 ++++++++--
 src/nodes/subtitle.py   |  41 ++++++++++-
 src/nodes/tts_node.py   |  37 ++++++++--
 5 files changed, 296 insertions(+), 47 deletions(-)
```

两个新增测试文件尚未跟踪，因此不会出现在普通 `git diff --stat` 中。Gate 2 文档是 starting worktree 已存在文件，不属于 Phase 1。

未 commit、push、merge 或开始 Phase 2。等待人工 Review。