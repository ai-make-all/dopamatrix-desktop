# VAR-001 Phase 2D-B Runtime Visual Acceptance Report

## 1. Baseline

工作区仅包含预期 Phase 2D-A 文件：

```text
 M web_ui/src/views/QueueView.vue
?? web_ui/src/components/CoverageDiagnosticsPanel.vue
?? web_ui/src/utils/coveragePresentation.ts
?? web_ui/tests/coveragePresentation.test.mjs
```

无无关变更；`git diff --check` 通过。

## 2. NB-01 Polish

已将未知 termination reason 从：

```text
规划状态：FUTURE_REASON
```

调整为：

```text
FUTURE_REASON
```

最终界面呈现为：

```text
规划状态 | FUTURE_REASON
```

同步更新既有测试，无其他语义变化。

## 3. Runtime Commands

仓库支持的实际命令：

```powershell
.\venv_build\Scripts\python.exe main.py
```

```powershell
cd web_ui
npm run dev
```

当前运行状态：

| Service | Address | PID | Result |
|---|---|---:|---|
| Backend | `http://127.0.0.1:8000` | 10080 | Health PASS |
| Frontend | `http://localhost:5173` | 4104 | HTTP 200 |

浏览器已打开到当前 Vite 前端。服务保持运行。

## 4. Historical Coverage Task

已只读检查所有本地租户 SQLite 数据库。

结果：没有找到包含以下内容的现有历史记录：

```text
planning_summary.coverage_diagnostics
```

因此无法复用既有 Phase 2B/2C balanced 任务。

## 5. Collapsed State

PENDING USER VISUAL EVIDENCE。

## 6. Expand / Collapse

PENDING USER VISUAL EVIDENCE。

## 7. DynamicScroller Scroll / Recycle

PENDING USER VISUAL EVIDENCE。

## 8. Display Values

PENDING LIVE BALANCED TASK。

## 9. Planning Context

PENDING LIVE BALANCED TASK。

## 10. Internal Data Hidden

源码和测试已证明不渲染内部字段；实际浏览器视觉确认仍待真实 diagnostics 卡片。

## 11. Live Balanced Task

需要用户通过正式 UI 创建一个真实任务：

1. 在已打开的 Chrome 中使用正常工作区标识登录。
2. 进入 Workspace。
3. 使用正式 AI Draft。
4. 使用已验证的 5 Beats：

```text
Hook
Context
Build
Reveal
CTA
```

5. 设置 `batch_size = 4`。
6. 正常提交并立即进入 Queue。
7. 不刷新页面，等待 Coverage 摘要通过 live WS 出现。
8. 等待任务终态。

## 12. Live → History

任务完成后：

1. 记录 Coverage 摘要及展开后的数值。
2. 刷新 Queue 页面。
3. 定位同一任务。
4. 确认 historical hydration 后显示相同 Coverage 内容。

## 13. Partial / Failed Case

当前没有可复用的 diagnostics-bearing partial/failed 历史任务。

```text
SOURCE/TEST PROVEN — NOT RUNTIME REPRODUCED
```

该项不是阻塞条件。

## 14. Narrow Width

真实任务完成后，请将浏览器宽度调整至约 760px 或更窄，并确认：

- planning context 变为两列
- 表格只在面板内部横向滚动
- Queue 页面本身没有破坏性横向溢出

## 15. UI-RF-01 Boundary

未修改 generation-mode badge 或 `getModeLabel`。不要将该 badge 用作 balanced policy 证据。

## 16. Runtime Findings

目前没有观察到 Coverage 运行时缺陷；但尚无真实 diagnostics 卡片可供视觉验收，不能判定 PASS。

请完成任务后回复：

```text
VAR001_PHASE2D_LIVE_TASK_COMPLETED
workspace=<登录使用的工作区标识>
```

并附上以下人工观察结果：

```text
live summary without refresh: PASS/FAIL
expand-collapse x3: PASS/FAIL
scroll away/back: PASS/FAIL
narrow width: PASS/FAIL
refresh history equality: PASS/FAIL
```

## 17. Test / Build Results

```text
Frontend normalizer + presentation:
19 PASS
```

```text
Vite production build:
141 modules transformed
PASS
```

仅有既有 Browserslist 和 `Login.vue` chunk 提示。

## 18. Final Git Status

```text
 M web_ui/src/views/QueueView.vue
?? web_ui/src/components/CoverageDiagnosticsPanel.vue
?? web_ui/src/utils/coveragePresentation.ts
?? web_ui/tests/coveragePresentation.test.mjs
```

未提交、未推送。Backend 与 frontend 当前保持运行。

PHASE2D_USER_VISUAL_EVIDENCE_REQUIRED