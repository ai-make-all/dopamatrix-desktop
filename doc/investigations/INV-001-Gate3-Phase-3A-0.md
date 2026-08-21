# INV-001 Gate 3 Phase 3A-0 —
# Planning Policy Contract Report

## 1. Baseline

```text
branch: fix/creative-duplicate-detection
starting commit: c81e5abffdb7a23a81f86301c8ad63b170ea0eea
starting worktree: CLEAN
```

未创建 branch、未 commit、未 push。

## 2. Previous Blocker

此前 Backend 无法区分：

```text
Formal AI Draft populated timeline
vs
generic populated-timeline /submit-dsl
```

`mode=auto|rewrite` 仅描述 Director 行为；timeline、prompt、meta 和 endpoint 都不能证明 AI Draft provenance。

本次没有绕过该结论，而是建立了显式 request policy contract。

## 3. Planning Policy Contract

在 [schemas.py:402](/E:/dopaworkspace/dopamatrix-desktop/src/api/schemas.py:402) 的 `RenderDSLRequest` 增加：

```python
variant_planning_policy: Literal[
    "legacy",
    "exact_main_visual",
] = Field(default="legacy")
```

语义：

- `legacy`：保持现有 worker-local resolution。
- `exact_main_visual`：请求 Exact Main-Visual Variant Planning。
- 字段省略：自动得到 `legacy`。
- 非法值：Pydantic validation failure。
- `mode=auto|rewrite` 语义未改变。

## 4. Frontend Provenance / Intent Plumbing

Frontend-local workflow provenance 与 planning policy 已分离。

Formal AI Draft：

```text
/draft-blueprint success
→ orchestratorDirectRender = true
→ orchestratorVariantPlanningPolicy = exact_main_visual
→ Drawer confirm 原样回传两者
→ blindFission({ variantPlanningPolicy })
→ HTTP payload.variant_planning_policy
```

关键位置：

- AI Draft 成功后明确设置 policy：[WorkspaceView.vue:337](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:337)
- AI Draft direct-render intent 单独保存：[WorkspaceView.vue:338](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:338)
- Drawer 分别接收 `directRender` 和 policy：[DslOrchestratorDrawer.vue:28](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/DslOrchestratorDrawer.vue:28)
- Confirm event 透传 policy：[DslOrchestratorDrawer.vue:425](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/DslOrchestratorDrawer.vue:425)
- HTTP payload：[WorkspaceView.vue:409](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:409)

Generic submission：

- 通用 `blindFission()` 默认 `legacy`。
- Ctrl+Enter 和普通“极速裂变”按钮均调用无 policy 参数的 `blindFission()`。
- 手工打开战术板时同时重置 `directRender=false` 和 policy=`legacy`。
- 不再用“tracks 非空”推断 AI Draft。

## 5. Backend Recognition

[routes_dsl.py:129](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:129)：

```python
def _requests_exact_main_visual(
    payload: RenderDSLRequest,
) -> bool:
    return (
        payload.variant_planning_policy
        == "exact_main_visual"
    )
```

Backend 不读取以下信号推断 policy：

- prompt
- timeline 是否为空
- mode
- meta
- non-Blind
- endpoint provenance

Blind detection仍由独立 `_is_blind_fission()` 完成；planning behavior authority 只来自新字段。

## 6. Blind Behavior

Blind + `legacy`：行为不变。

Blind + `exact_main_visual`：

```text
HTTP 422
EXACT_MAIN_VISUAL_UNSUPPORTED_FOR_BLIND
```

Guard 在 resolver、task identity、BackgroundTask dispatch 之前执行，不会静默进入 legacy render。

## 7. Manual Behavior

`/submit-manual`：

- 字段省略或 `legacy`：现有 parse/dispatch 行为不变。
- 不自动设置 exact policy。
- 显式传入 `exact_main_visual`：HTTP 422  
  `EXACT_MAIN_VISUAL_UNSUPPORTED_FOR_SUBMIT_MANUAL`

这避免 Manual 被 populated tracks 或其他 heuristic 自动纳入 exact diversity。

## 8. Direct Render Behavior

`/render-dsl`：

- 字段省略或 `legacy`：现有行为不变。
- 不自动应用 exact planning。
- 显式 exact、非 Blind：HTTP 422  
  `EXACT_MAIN_VISUAL_UNSUPPORTED_FOR_RENDER_DSL`
- Blind + exact：使用专用 Blind unsupported error。

## 9. Temporary Pre-Planner Behavior

选择了 Option B：guarded error。

Formal AI Draft 当前发送 `exact_main_visual` 后，Backend 返回：

```text
HTTP 501
EXACT_MAIN_VISUAL_PLANNER_NOT_IMPLEMENTED
```

原因：

- Phase 3A-0 只证明 intent 能无歧义到达 Backend。
- 继续 legacy render 会让用户误以为 exact uniqueness 已得到保证。
- Guard 在 preview/resolver/render dispatch 前执行，不创建 task 或 child execution。
- Frontend 现有错误处理会展示 501 和完整 error code。

因此，在真正 Phase 3A Planner 合入前，Formal AI Draft direct render 暂时被明确阻断。这是有意的 transient behavior。

## 10. Files Changed

- [schemas.py](/E:/dopaworkspace/dopamatrix-desktop/src/api/schemas.py)：新增 backward-compatible Literal policy 字段。
- [routes_dsl.py](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py)：显式 policy recognition 和 pre-planner guards。
- [WorkspaceView.vue](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue)：AI Draft intent、generic legacy default、HTTP payload。
- [DslOrchestratorDrawer.vue](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/DslOrchestratorDrawer.vue)：分离 direct-render provenance 和 planning policy。
- [test_inv001_planning_policy.py](/E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_planning_policy.py)：10 项 focused tests。

## 11. Tests Added

| Requirement | Coverage |
|---|---|
| P0-1 omitted → legacy | `test_omitted_policy_defaults_to_legacy` |
| P0-2 exact backend-visible | `test_exact_policy_is_backend_visible_without_mode_heuristics` |
| P0-3 invalid policy | `test_invalid_policy_fails_schema_validation` |
| P0-4 AI Draft payload exact | `test_ai_draft_direct_render_carries_exact_policy` |
| P0-5 generic submission legacy | `test_generic_submission_explicitly_defaults_to_legacy` |
| P0-6 Blind exact rejected | `test_blind_exact_policy_is_explicitly_unsupported` |
| P0-7 Manual unchanged | `test_manual_default_policy_preserves_dispatch` |
| P0-8 render-dsl unchanged | `test_render_dsl_default_policy_preserves_dispatch` |
| Explicit exact on unsupported endpoints | `test_manual_and_direct_render_do_not_silently_accept_exact_policy` |
| Pre-planner no false guarantee | `test_ai_draft_exact_policy_is_guarded_until_planner_exists` |

Frontend contract tests inspect the production Vue wiring. No Vue test framework currently exists in `web_ui`.

## 12. Test Results

Focused policy tests：

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_planning_policy.py" -q
```

```text
Ran 10 tests
OK
```

Required INV-001 regression：

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

```text
Ran 49 tests
OK
```

Compile check：

```powershell
.\venv_build\Scripts\python.exe -m py_compile src/api/schemas.py src/api/routes_dsl.py tests/test_inv001_planning_policy.py
```

```text
PASS
```

Frontend build was attempted but unavailable：

```text
NODE_NOT_FOUND
NPM_NOT_FOUND
```

现有 `node_modules/.bin/vite` wrapper 仍依赖缺失的 Node runtime，因此未安装工具或修改环境。

额外 full unittest discovery 发现两个 unrelated environment failures：

```text
test_approval_service.py: ModuleNotFoundError: pytest
test_matrix_export.py:    ModuleNotFoundError: pytest
```

没有修改这些无关测试。Required INV-001 suite 全部通过。

## 13. Scope Audit

确认未实施：

- Candidate discovery
- Combination enumeration
- Fingerprint
- Diversity Gate
- Authoritative `CompilationPlan × N`
- Search budget
- Capacity/warning semantics
- Planner warnings
- BGM fix
- Blind planner
- Manual diversity
- Variant ID
- Ledger
- DB schema/migration
- UI toggle或Variation Strategy UI

未修改：

- `dsl_parser.py`
- `dsl_adapter.py`
- compositor
- TTS
- Subtitle
- models
- services
- DB schema

## 14. Git Review

`git status --short`：

```text
 M src/api/routes_dsl.py
 M src/api/schemas.py
 M web_ui/src/views/DslOrchestratorDrawer.vue
 M web_ui/src/views/WorkspaceView.vue
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

未跟踪的新测试文件共 187 行，不包含在上述 tracked diff stat 中。

`git diff --check`：PASS；仅有现有 Git LF→CRLF 提示，无 whitespace error。

未 commit、未 push、未开始 Phase 3A Planner。