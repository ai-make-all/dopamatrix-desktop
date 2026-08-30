# VAR-001 Phase 2D-B
# Historical Hydration Runtime Root-Cause Audit

## 1. Runtime Baseline

- Branch: `feature/var-001-variation-policy`
- HEAD: `41f72eb2744cb8028277aaa5ac4ebbb05fc19f9e`
- Backend: Python PID `10080`, listening on `127.0.0.1:8000`
- Frontend: Node PID `4104`, listening on `[::1]:5173`
- Backend start: `2026-08-30 10:20:12`
- Frontend start: `2026-08-30 10:19:32`
- 两个进程均保持运行，未重启或修改。

当前仅有预期 Phase 2D-A 文件：

```text
 M web_ui/src/views/QueueView.vue
?? web_ui/src/components/CoverageDiagnosticsPanel.vue
?? web_ui/src/utils/coveragePresentation.ts
?? web_ui/tests/coveragePresentation.test.mjs
```

`git diff --check`：通过；仅有既存 LF/CRLF 提示。

## 2. Target Task Identity

最新真实 balanced 任务：

| 字段 | 值 |
|---|---|
| task_id | `6b7f2606-64c5-4ef7-a25d-f01d02fe0cae` |
| tenant/workspace | `testduplicate` |
| created_at（DB/UTC） | `2026-08-30 02:31:53.886877` |
| created_at（UTC+8） | `2026-08-30 10:31:53.886877` |
| batch_size | `4` |
| duration | `79.0` 秒 |
| output count | `4` |

运行日志中的 CoverNode 同样绑定 `tenant_id=testduplicate`。

## 3. TaskHistory Persistence

```text
TASKHISTORY_ROW_FOUND = YES
```

只读 SQLite 查询确认目标行存在：

```text
task_id         = 6b7f2606-64c5-4ef7-a25d-f01d02fe0cae
batch_size      = 4
duration        = 79.0
output_count    = 4
```

活动日志中未捕获 `_persist_task_history` 的成功或失败消息：

```text
HISTORY_PERSIST_RUNTIME = NO_EVIDENCE
```

但数据库目标行、4 个输出资产及完整 `prompt_details` 已证明 `_persist_task_history()` 实际完成。日志中也没有 `HISTORY_PERSIST_FAILED`。

## 4. Coverage Persistence

目标 TaskHistory 的 `prompt_details` 解码成功：

```text
PLANNING_SUMMARY_FOUND = YES
COVERAGE_DIAGNOSTICS_FOUND = YES
```

Planning summary：

```text
requested_count = 4
planned_count   = 4
succeeded_count = 4
failed_count    = 0
```

持久化 diagnostics 与刷新前 UI 一致：

- 4 个 `VARIABLE_BALANCED`
- 1 个 `FIXED_BY_CAPACITY`
- policy: `exact_main_visual_balanced`
- termination: `REQUEST_SATISFIED`
- preview seeded: `true`

因此 Coverage 数据没有在 persistence 边界丢失。

## 5. Tenant DB Mapping

目标任务仅出现在：

```text
task_id
6b7f2606-64c5-4ef7-a25d-f01d02fe0cae

tenant/workspace
testduplicate

database
E:\dopaworkspace\dopamatrix-desktop\data\dopamatrix_testduplicate.db
```

扫描其他本地 tenant DB 未发现同一 task_id。

## 6. `/tasks/today` Route Contract

预期路由定义位于 [routes_history.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_history.py:84)：

```python
@tasks_router.get("/today", ...)
def get_tasks_today(db: Session = Depends(get_db)) -> list:
```

预期请求契约：

- Method: `GET`
- Path: `/api/v1/tasks/today`
- Header: `X-Local-User`
- 无必需 query 参数
- `get_db()` 使用 `X-Local-User`，缺失时才回退为 `default`

实际存在路由优先级冲突：

1. [main.py](E:/dopaworkspace/dopamatrix-desktop/main.py:171) 先注册核心 task router。
2. 核心 router 前缀为 `/tasks`。
3. 其中 [routes.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes.py:142) 定义：

```python
@router.get("/{task_id}")
def get_task(task_id: int, ...):
```

4. `/tasks/today` router 到 [main.py](E:/dopaworkspace/dopamatrix-desktop/main.py:175) 才注册。

因此 `/api/v1/tasks/today` 首先匹配更早注册的 `/api/v1/tasks/{task_id}`，随后 FastAPI 尝试把 `"today"` 解析为整数并返回 422。真正的 `get_tasks_today()` 从未执行。

## 7. Direct API Request

使用 QueueView 的精确请求形式：

```http
GET http://127.0.0.1:8000/api/v1/tasks/today
X-Local-User: testduplicate
```

实际结果：

```text
TASKS_TODAY_STATUS = 422
```

响应：

```json
{
  "detail": [
    {
      "type": "int_parsing",
      "loc": ["path", "task_id"],
      "msg": "Input should be a valid integer, unable to parse string as an integer",
      "input": "today"
    }
  ]
}
```

以 `X-Local-User: default` 请求也得到相同 422，证明失败发生在 tenant 数据选择之前，不是 tenant 内容差异导致。

作为对照：

```http
GET /api/v1/history/
X-Local-User: testduplicate
```

结果：

```text
HTTP 200
records = 12
target records = 1
```

目标记录包含：

- TaskHistory row
- 4 个 output assets
- planning_summary
- coverage_diagnostics

```text
TARGET_TASK_IN_HISTORY_API = N/A
```

`/tasks/today` 没有产生可检查的 2xx history response。

## 8. DB vs API Comparison

最早失败边界为 Gate B：

```text
DB row                         YES
coverage diagnostics persisted YES
generic /history/ serialization YES
/tasks/today                   HTTP 422
QueueView mapping reached       NO
INIT_TASKS reached              NO
```

这不是：

- TaskHistory persistence failure
- tenant DB selection failure
- date filter排除
- frontend mapping丢弃
- Worker INIT_TASKS 丢弃

而是历史专用 endpoint 在路由分派阶段失败。

## 9. Refresh Tenant Identity

```text
LIVE_TASK_TENANT = testduplicate
REFRESH_HISTORY_TENANT = RUNTIME_VALUE_NOT_OBSERVABLE
TENANT_MATCH = NOT PROVEN
```

浏览器请求头没有出现在 Uvicorn access log 中，因此不伪造其运行时值。

不过 tenant identity 不能解释本次故障：

- 使用准确 tenant `testduplicate` 仍返回相同 422。
- 使用 `default` 也返回相同 422。
- 422 明确来自 path `task_id="today"` 的整数解析，而不是 tenant DB 内容。

## 10. Login/App-State Rehydration

[appStore.js](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/stores/appStore.js:13) 的 `initAuth()` 同步读取：

```javascript
localStorage.getItem('dopamatrix_user')
```

并恢复：

```javascript
loggedInUser.value = stored
axios.defaults.headers.common['X-Local-User'] = stored
```

[main.js](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/main.js:15) 在路由安装和应用挂载前调用 `appStore.initAuth()`。

因此没有源码证据支持以下时序：

```text
QueueView先请求default
→ 稍后才恢复登录用户
```

即使该时序发生，当前 endpoint 也会在 tenant 解析前以同样的 422 失败。

## 11. Fetch Timing

[QueueView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue:168) 在 `onMounted()` 中依次执行：

```typescript
queueStore.initWorker()
queueStore.connectEventBus(appStore.loggedInUser || 'default')
fetchTodayTasks()
```

`fetchTodayTasks()` 发出：

```typescript
fetch(`${appStore.API_BASE}/api/v1/tasks/today`, {
  headers: { 'X-Local-User': userId },
})
```

关键失败处理为：

```typescript
if (!resp.ok) return hydratedById
```

因此 422 会：

- 静默返回空 Map
- 不解析错误体
- 不构建 `todayCompleted`
- 不调用 `queueStore.initTasks(...)`
- 不显示 hydration 错误

这直接解释刷新后的空白 Queue。

## 12. Date/Timezone Filtering

预期 `/tasks/today` 使用 UTC 整日范围：

```python
day_start = 2026-08-30 00:00:00 UTC
day_end   = 2026-08-31 00:00:00 UTC
```

目标记录时间：

```text
2026-08-30 02:31:53 UTC
```

明确处于该范围内。

而且实际请求在调用 `get_tasks_today()` 前已经 422，日期过滤根本未执行。因此 UTC/UTC+8 边界不可能是本次最早失败原因。

## 13. QueueView Historical Mapping

若 API 返回 2xx，当前映射会：

1. 解析 `prompt_details`
2. 读取 `planning_summary`
3. 使用单一 `normalizeCoverageDiagnostics()`
4. 创建 `type: 'completed'` 的 QueueTask
5. 载入 output assets
6. 调用 `queueStore.initTasks([...mergedTasks, ...newTasks])`

通用 `/history/` 返回的目标记录具备这些映射需要的全部字段。

本次映射没有丢弃目标任务，因为它根本未获得任何 response records。

## 14. Store / Worker `INIT_TASKS`

[useQueueStore.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/stores/useQueueStore.ts:251) 会把传入快照发送给 Worker：

```typescript
_worker.postMessage({ type: 'INIT_TASKS', payload: initialTasks })
```

[queueWorker.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/workers/queueWorker.ts:196) 接收后：

```typescript
_tasks = incoming.filter(t => t && typeof t.id === 'string')
_recomputeStats()
_broadcastTick()
```

目标 task_id 为合法字符串，若被传入不会被过滤。

实际发生的是：

```text
HTTP 422
→ fetchTodayTasks提前return
→ initTasks未调用
→ Worker保持初始空_tasks
→ 后续TICK持续广播空列表
```

因此 INIT_TASKS 不是丢失边界。

## 15. Browser Network Evidence

没有使用浏览器 DevTools，因此不伪造 Network 面板截图。

但运行时 backend access log 已捕获刷新请求：

```text
OPTIONS /api/v1/tasks/today HTTP/1.1 200 OK
GET     /api/v1/tasks/today HTTP/1.1 422 Unprocessable Entity
```

该序列紧接在目标任务四个 cover/media 请求之后，符合用户执行完整页面刷新后的时序。

随后只读直接请求复现了相同 422，并取得精确 FastAPI validation detail。

## 16. Matrix QC Boundary

“矩阵质检舱”对应独立路由 `/approval` 和 `ApprovalView.vue`。

“战果阅兵场”属于 `WorkspaceView → QueueView → completed tab`。

因此矩阵质检舱的内容与本次 Queue 历史 hydration 判断无关；未检查或修改其 Coverage UI。

## 17. Root Cause

最早失败边界是后端历史 endpoint 的请求分派：

```text
/tasks/{task_id} 注册在前
→ /tasks/today 被解释为 task_id="today"
→ int path validation 失败
→ HTTP 422
→ QueueView静默返回空 hydration
→ 战果阅兵场刷新后无历史任务
```

TaskHistory、CoverageDiagnostics、tenant DB、历史序列化、前端 normalizer 和 Worker INIT_TASKS 均不在最早失败边界。

## 18. Recommended Minimal Fix Scope

仅作设计建议，未实施：

- 调整 FastAPI 路由注册优先级，使静态 `/api/v1/tasks/today` 在动态 `/api/v1/tasks/{task_id}` 之前注册。
- 增加一个路由级回归测试，证明 `/tasks/today` 命中今日历史 handler，而不是进入整数 `task_id` 校验。
- 可另行评估 QueueView 对非 2xx 的可见诊断；这不是恢复 endpoint reachability 所必需的首要修复。

无需修改：

- TaskHistory schema/persistence
- CoverageDiagnostics contract
- Queue mapping/normalizer
- Store/Worker
- Coverage UX
- Planner或 fingerprint

## 19. Git Status

审计过程未修改任何文件：

```text
 M web_ui/src/views/QueueView.vue
?? web_ui/src/components/CoverageDiagnosticsPanel.vue
?? web_ui/src/utils/coveragePresentation.ts
?? web_ui/tests/coveragePresentation.test.mjs
```

后端、前端进程仍保持运行。未重启、未提交、未推送。

VAR2D-B-RF-03B  
HISTORY_ENDPOINT_REQUEST_FAILED