# Phase 3A-0 Final Verification

## Node / npm Resolution

当前 Codex shell：

- `where.exe node` → unresolved
- `where.exe npm` → unresolved
- `Get-Command node` → unresolved
- `Get-Command npm` → unresolved
- `node -v` / `npm -v` → unresolved

结论：`CODEX_SHELL_PATH_MISMATCH`，不是 Node/npm 未安装。

通过 PATH 中的绝对安装路径执行成功：

- Node: `v22.23.1`
- npm: `10.9.8`

当前 Codex PATH：

```text
C:\Users\chenp\.codex\tmp\arg0\codex-arg0FzcLiU;C:\Windows\system32;C:\Windows;C:\Windows\System32\Wbem;C:\Windows\System32\WindowsPowerShell\v1.0\;C:\Windows\System32\OpenSSH\;C:\Program Files\Git\cmd;C:\Users\chenp\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.22_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v22.23.1-win-x64;C:\Users\chenp\.cargo\bin;D:\Python\Python312\Scripts\;D:\Python\Python312\;d:\Users\chenp\AppData\Local\Programs\cursor\resources\app\codeBin;C:\Users\chenp\AppData\Local\Microsoft\WindowsApps;D:\Users\chenp\AppData\Local\Programs\cursor\resources\app\bin;C:\Users\chenp\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.22_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v22.23.1-win-x64;;c:\Users\chenp\.cursor\extensions\openai.chatgpt-26.721.30844-win32-x64\bin\windows-x86_64
```

未安装或升级任何软件，未修改系统环境。

## Package Scripts

仓库根目录没有 `package.json`。

[web_ui/package.json](/E:/dopaworkspace/dopamatrix-desktop/web_ui/package.json) 提供：

```json
{
  "dev": "vite",
  "build": "vite build",
  "preview": "vite preview",
  "tauri": "tauri"
}
```

没有独立 `typecheck` 或 frontend test script，因此选择现有 `build` 脚本作为 compile validation。

## AI Draft Policy Wiring

[WorkspaceView.vue](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:179) 分别维护：

- `orchestratorDirectRender`
- `orchestratorVariantPlanningPolicy`

`/draft-blueprint` 成功并装填 tracks 后，在 [WorkspaceView.vue:339](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:339) 设置：

```javascript
orchestratorDirectRender.value = true
orchestratorVariantPlanningPolicy.value = EXACT_MAIN_VISUAL_PLANNING_POLICY
```

Drawer 确认后，通过：

```javascript
blindFission({ variantPlanningPolicy })
```

最终 HTTP payload 包含：

```javascript
variant_planning_policy: variantPlanningPolicy
```

因此 Formal AI Draft 明确发送 `exact_main_visual`，不存在根据 timeline/tracks 非空自动推断 exact policy 的逻辑。

## Generic Call-Site Audit

生产代码中 `blindFission(` 只有以下调用：

| Caller | Workflow intent | Explicit policy | HTTP policy |
|---|---|---|---|
| [WorkspaceView.vue:212](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:212) | Formal AI Draft Drawer confirm | Drawer 传入 | `exact_main_visual` |
| [WorkspaceView.vue:518](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:518) | Ctrl+Enter | omitted | `legacy` |
| [WorkspaceView.vue:633](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:633) | 普通极速裂变，包括普通 populated timeline | omitted | `legacy` |

`blindFission(options = {})` 使用：

```javascript
options.variantPlanningPolicy ?? LEGACY_VARIANT_PLANNING_POLICY
```

因此 generic path 明确落到 `legacy`。

手工 Tactical Board 不调用 `blindFission`：Drawer 直接调用 `/submit-manual`，请求省略 policy，由后端 schema 默认成 `legacy`。打开手工 Drawer 时也会显式重置 direct-render 与 planning policy 状态。

## Drawer Contract

[DslOrchestratorDrawer.vue:28](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/DslOrchestratorDrawer.vue:28) 将两者定义为独立 props：

```javascript
directRender:          { type: Boolean, default: false },
variantPlanningPolicy: { type: String,  default: 'legacy' },
```

Direct-render confirm 分别转发：

```javascript
directRender: props.directRender,
variantPlanningPolicy: props.variantPlanningPolicy,
```

Drawer 没有实现 `directRender == exact_main_visual` 推断。

Manual branch：

- 直接提交 `/submit-manual`
- confirm metadata 使用 `directRender: false`
- planning policy 使用 `legacy`

## Backend Guard Matrix

Backend 只读取 [RenderDSLRequest.variant_planning_policy](/E:/dopaworkspace/dopamatrix-desktop/src/api/schemas.py:402)，默认值为 `legacy`；没有使用 prompt、mode、timeline 或 endpoint heuristic 推断 policy。

| Request | Result |
|---|---|
| AI Draft populated `/submit-dsl` + exact | HTTP 501 `EXACT_MAIN_VISUAL_PLANNER_NOT_IMPLEMENTED` |
| Blind `/submit-dsl` + exact | HTTP 422 `EXACT_MAIN_VISUAL_UNSUPPORTED_FOR_BLIND` |
| `/submit-manual` + exact | HTTP 422 `EXACT_MAIN_VISUAL_UNSUPPORTED_FOR_SUBMIT_MANUAL` |
| populated `/render-dsl` + exact | HTTP 422 `EXACT_MAIN_VISUAL_UNSUPPORTED_FOR_RENDER_DSL` |
| legacy / omitted | Guard returns normally；existing behavior preserved |

Option B guarded behavior保持不变；exact policy 不会静默进入 legacy resolver。

## Frontend Build Result

执行：

```powershell
& 'C:\Users\chenp\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.22_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v22.23.1-win-x64\npm.cmd' run build
```

结果：`PASS`

```text
vite v7.3.1
135 modules transformed
✓ built in 12.37s
```

非阻塞既有告警：

- `caniuse-lite` 数据约 6 个月未更新
- `Login.vue` 同时存在 dynamic/static import，不能拆为独立 chunk

未执行 `npm install`，未升级依赖或修改 lockfile。

## INV-001 Regression Result

执行：

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

结果：

```text
Ran 49 tests in 0.389s
OK
```

Phase 1、Phase 2 与 Phase 3A-0 policy tests 全部通过。

## Review Findings

NONE

环境记录：`CODEX_SHELL_PATH_MISMATCH` 已通过绝对 executable path 绕过，不是代码或机器安装缺陷。

## Git Status

Branch：

```text
fix/creative-duplicate-detection
```

HEAD：

```text
c81e5abffdb7a23a81f86301c8ad63b170ea0eea
```

`git status --short`：

```text
 M src/api/routes_dsl.py
 M src/api/schemas.py
 M web_ui/src/views/DslOrchestratorDrawer.vue
 M web_ui/src/views/WorkspaceView.vue
?? doc/investigations/INV-001-Gate3-Phase-3A-0.md
?? tests/test_inv001_planning_policy.py
```

`git diff --stat`：

```text
src/api/routes_dsl.py                      | 55 ++++++++++++++++++++++++++++++
src/api/schemas.py                         |  7 ++++
web_ui/src/views/DslOrchestratorDrawer.vue | 12 +++----
web_ui/src/views/WorkspaceView.vue         | 42 +++++++++++++++++++----
4 files changed, 103 insertions(+), 13 deletions(-)
```

`git diff --check`：`PASS`，仅输出 Git 的 LF→CRLF working-copy warning。本轮未修改、commit 或 push 任何文件。