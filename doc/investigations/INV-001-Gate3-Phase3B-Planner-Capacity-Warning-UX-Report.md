# INV-001 Gate 3 Phase 3B —
# Planner Capacity Warning UX Report

## 1. Baseline

- Branch: `fix/creative-duplicate-detection`
- Starting commit: `ea1f7e0cbffb1325790135abadfd977ac352c235`
- Starting worktree: CLEAN
- 未创建 branch、commit 或 push。

## 2. Existing WS → UI Flow

真实路径：

`routes_dsl.py terminal_payload`
→ WebSocket `WS_UPDATE`
→ [useQueueStore.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/stores/useQueueStore.ts:125)
→ Web Worker
→ [queueWorker.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/workers/queueWorker.ts:210)
→ Pinia `tasks`
→ [QueueView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue:600)

Audit 结果：

- WebSocket Store 原样转发整个 envelope。
- Backend capacity fields 已完整发送，无需 backend 修改。
- Worker 原先只保留 `status/assets` 等字段，会丢弃 planning outcome fields。
- 完成卡片原先只显示“已完成”和资产数量，不区分部分规划或 warning。

## 3. Files Changed

- [queueWorker.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/workers/queueWorker.ts:39)
  - 扩展 `QueueTask`、`WsUpdatePayload`。
  - 保存 terminal outcome fields。

- [useQueueStore.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/stores/useQueueStore.ts:257)
  - Worker 不可用时的 fallback 路径同样保留 outcome fields。

- [QueueView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue:50)
  - 显示完成/失败 planning warning。
  - 从 TaskHistory `planning_summary` 恢复已持久化 warning。

- [renderOutcome.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/utils/renderOutcome.ts:34)
  - 新增 deterministic pure warning mapper。

- [renderOutcome.test.mjs](E:/dopaworkspace/dopamatrix-desktop/web_ui/tests/renderOutcome.test.mjs:1)
  - UX1–UX8 无依赖 Node contract tests。

## 4. Frontend State Contract

`QueueTask` 现在 additive 保留：

- `partial`
- `requestedCount`
- `plannedCount`
- `succeededCount`
- `failedCount`
- `historyPersisted`
- `warningCodes`

旧 payload 缺少这些字段时仍正常工作。

TaskHistory 水合还会读取现有 `prompt_details.planning_summary`，因此 capacity/child warnings 在页面刷新后仍可恢复。`HISTORY_PERSIST_FAILED` 因历史记录实际未落库，只能由实时 WS 展示。

## 5. Warning Mapping

- `INSUFFICIENT_UNIQUE_CAPACITY`
  - 显示实际生成数量和请求数量。
  - 明确说明当前素材组合只能形成有限数量的不同主视觉版本。

- `PLANNING_SEARCH_LIMIT_REACHED`
  - 明确表示达到本次规划搜索上限。
  - 明确保留“可能仍存在其他有效组合”。
  - 不声称素材空间真正耗尽。

- `CHILD_EXECUTION_FAILED`
  - 显示已规划数量与成功输出数量。
  - 单独说明有多少已规划版本生成失败。

- `HISTORY_PERSIST_FAILED`
  - 明确表示视频已经生成。
  - 仅提示历史记录保存失败，不将其表达为 render failure。

多 warning 按以下稳定顺序组合：

`planning warning → child failure → history persistence warning`

## 6. Requested / Planned / Succeeded Semantics

示例：

```text
requested=4, planned=3, succeeded=2
```

用户看到：

```text
已完成 2 个输出；规划 3/4 个。
```

随后显示 planning capacity 原因及 child render failure，避免把 planned 数量误报为成功输出数量。

## 7. Zero-Plan UX

`INSUFFICIENT_UNIQUE_CAPACITY`：

```text
未生成任何版本：当前素材组合无法形成可执行的不同主视觉版本。
```

`PLANNING_SEARCH_LIMIT_REACHED`：

```text
未生成任何版本：本次规划达到搜索上限，未在搜索范围内找到可执行组合；可能仍存在其他有效组合。
```

两者保持严格语义区分。

## 8. Legacy Compatibility

Legacy completed payload 没有新增字段或 warning 时：

- mapper 返回 `null`
- 状态仍显示“已完成”
- 不显示额外 warning
- 原有资产轮播和成功 UX 不变

## 9. Actual User-Visible Surface

Warning 出现在现有 Queue 页面：

- `completed` task：完成卡片状态改为“部分完成”或“已完成·注意”，并在卡片第二行显示黄色 warning banner。
- `failed`/zero-plan task：现有失败监控条的主文本区域显示具体 planning failure，完整内容同时提供 `title`。
- 页面刷新后，已落库的 planning warning 会从 TaskHistory 恢复。

不是 `console.log` 或仅存于 state；信息已进入实际模板 DOM。

## 10. Backend Changes

NONE。

未修改 `routes_dsl.py` 或任何 Planner/backend 文件。

## 11. Test / Contract Verification

使用 Node 22 内建 test runner，无新增依赖：

```powershell
node.exe --experimental-strip-types --test tests/renderOutcome.test.mjs
```

结果：

```text
tests 8
pass 8
fail 0
```

覆盖：

- UX1：完整成功，无 warning
- UX2：2/4 true capacity exhaustion
- UX3：7/20 search limit，不误报 exhaustion
- UX4：planning shortage 与 child failure 同时保留
- UX5：render success + history persistence warning
- UX6：zero-plan true exhaustion
- UX7：zero-plan search limit
- UX8：legacy payload compatibility

## 12. Frontend Build

Codex shell 存在 PATH mismatch，因此使用已安装 npm 的绝对路径：

```powershell
npm.cmd run build
```

结果：

```text
vite v7.3.1
136 modules transformed
✓ built in 6.37s
```

PASS。仅有既有 Browserslist freshness 和 Login dynamic/static import warning。

## 13. INV-001 Regression

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

结果：

```text
Ran 77 tests in 0.683s
OK
```

## 14. Scope Audit

确认未修改：

- Planner algorithm
- candidate resolver
- fingerprint
- combination enumeration
- search budget
- authoritative handoff
- TaskHistory backend semantics
- BGM logic
- database schema/models
- TTS/Subtitle/Compositor/Cover
- frontend planning policy

## 15. Risks / Open Questions

- 项目没有现成 Vue component test framework。本 Phase 使用 Node 内建 runner验证 pure mapping，并通过 Vite production build；未引入 Vitest/Jest。
- 未执行浏览器 screenshot/E2E。实际模板绑定和可见 DOM 已静态核对并通过 Vue/Vite 编译。
- `HISTORY_PERSIST_FAILED` 无法在刷新后恢复，这是该 warning 所表达的数据库写入失败的自然结果；实时 WS 卡片仍会显示。

## 16. Git Review

```text
 M web_ui/src/stores/useQueueStore.ts
 M web_ui/src/views/QueueView.vue
 M web_ui/src/workers/queueWorker.ts
?? web_ui/src/utils/renderOutcome.ts
?? web_ui/tests/
```

Tracked diff：

```text
 web_ui/src/stores/useQueueStore.ts | 14 ++++++
 web_ui/src/views/QueueView.vue     | 90 +++++++++++++++++++++++++++++++++++---
 web_ui/src/workers/queueWorker.ts  | 28 ++++++++++++
 3 files changed, 127 insertions(+), 5 deletions(-)
```

`git diff --stat` 不包含两个 untracked 新文件。

`git diff --check`：PASS，仅有现有 LF→CRLF 提示。

未 commit、未 push、未进入 Phase 4。