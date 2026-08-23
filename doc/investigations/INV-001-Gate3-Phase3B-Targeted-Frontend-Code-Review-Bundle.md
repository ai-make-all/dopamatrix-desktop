# INV-001 Gate 3 Phase 3B —
# Targeted Frontend Code Review Bundle

## 1. Baseline

```text
HEAD:
ea1f7e0cbffb1325790135abadfd977ac352c235
```

```text
 M web_ui/src/stores/useQueueStore.ts
 M web_ui/src/views/QueueView.vue
 M web_ui/src/workers/queueWorker.ts
?? doc/investigations/INV-001-Gate3-Phase3B-Planner-Capacity-Warning-UX-Report.md
?? web_ui/src/utils/renderOutcome.ts
?? web_ui/tests/
```

```text
 web_ui/src/stores/useQueueStore.ts | 14 ++++++
 web_ui/src/views/QueueView.vue     | 90 +++++++++++++++++++++++++++++++++++---
 web_ui/src/workers/queueWorker.ts  | 28 ++++++++++++
 3 files changed, 127 insertions(+), 5 deletions(-)
```

`git diff --stat` 不包含 untracked mapper、tests 和 report。

`git diff --check`：PASS，仅有 LF→CRLF 提示。

## 2. Render Outcome Mapper

完整文件：[renderOutcome.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/utils/renderOutcome.ts)

```ts
export const RENDER_WARNING_CODES = {
  insufficientCapacity: 'INSUFFICIENT_UNIQUE_CAPACITY',
  searchLimit: 'PLANNING_SEARCH_LIMIT_REACHED',
  childFailure: 'CHILD_EXECUTION_FAILED',
  historyFailure: 'HISTORY_PERSIST_FAILED',
} as const

export interface RenderOutcomeSource {
  status?: string
  type?: string
  partial?: boolean
  requestedCount?: number
  plannedCount?: number
  succeededCount?: number
  failedCount?: number
  historyPersisted?: boolean
  warningCodes?: string[]
}

export interface RenderOutcomeSummary {
  severity: 'warning' | 'error'
  headline: string
  details: string[]
  text: string
}

function count(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? Math.floor(value)
    : undefined
}

/** Map backend terminal facts to one deterministic, user-facing outcome summary. */
export function deriveRenderOutcomeSummary(
  source: RenderOutcomeSource,
): RenderOutcomeSummary | null {
  const warningCodes = Array.isArray(source.warningCodes) ? source.warningCodes : []
  const warnings = new Set(warningCodes)
  const requested = count(source.requestedCount)
  const planned = count(source.plannedCount)
  const succeeded = count(source.succeededCount)
  const failed = count(source.failedCount)

  const insufficient = warnings.has(RENDER_WARNING_CODES.insufficientCapacity)
  const searchLimited = warnings.has(RENDER_WARNING_CODES.searchLimit)
  const childFailed = warnings.has(RENDER_WARNING_CODES.childFailure)
  const historyFailed = source.historyPersisted === false
    && warnings.has(RENDER_WARNING_CODES.historyFailure)
  const hasVisibleWarning = insufficient || searchLimited || childFailed || historyFailed
  const status = source.status ?? source.type

  // New exact-success payloads and legacy payloads keep the existing success UX.
  if (!hasVisibleWarning) return null

  const zeroOutput = status === 'failed' && succeeded === 0
  let headline: string
  const details: string[] = []

  if (zeroOutput && insufficient) {
    headline = '未生成任何版本：当前素材组合无法形成可执行的不同主视觉版本。'
  } else if (zeroOutput && searchLimited) {
    headline = '未生成任何版本：本次规划达到搜索上限，未在搜索范围内找到可执行组合；可能仍存在其他有效组合。'
  } else if (
    requested !== undefined
    && planned !== undefined
    && succeeded !== undefined
    && succeeded < planned
  ) {
    headline = `已完成 ${succeeded} 个输出；规划 ${planned}/${requested} 个。`
  } else if (requested !== undefined && succeeded !== undefined) {
    headline = `已生成 ${succeeded}/${requested} 个版本。`
  } else if (status === 'failed') {
    headline = '本次未生成可用版本。'
  } else {
    headline = '视频已生成。'
  }

  if (insufficient && !zeroOutput) {
    const plannedLabel = planned === undefined ? '有限数量的' : `${planned} 个`
    details.push(`当前素材组合只能形成 ${plannedLabel}不同的主视觉版本。`)
  }
  if (searchLimited && !zeroOutput) {
    details.push('本次规划达到搜索上限，可能仍存在其他有效组合。')
  }
  if (childFailed) {
    details.push(
      failed === undefined
        ? '部分已规划版本生成失败。'
        : `另有 ${failed} 个已规划版本生成失败。`,
    )
  }
  if (historyFailed) {
    details.push('视频已生成，但历史记录保存失败。')
  }

  return {
    severity: status === 'failed' ? 'error' : 'warning',
    headline,
    details,
    text: [headline, ...details].join(' '),
  }
}
```

代码事实：

- 缺失或非法 count 不会默认成 `0`，而是归一化为 `undefined`，避免 legacy payload 显示 `0/0`。
- `warningCodes` 非数组时归一化为空数组。
- 多 warning 顺序固定为：
  `capacity → search limit → child failure → history failure`。
- `status` 兼容 WS payload 的 `status` 和 QueueTask 的 `type`。
- 没有已识别 warning 时返回 `null`，保持既有 UX。

Unknown warning code：

- 不会 crash。
- 单独出现时被忽略，mapper 返回 `null`。
- mapper 不修改 task status，因此不会把 failed task改成 completed。
- 与已知 warning 同时出现时，已知 warning仍正常显示。

## 3. Queue Worker Propagation

### A. QueueTask

[queueWorker.ts:39](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/workers/queueWorker.ts:39)

```ts
export interface QueueTask {
  id: string
  type: TaskStatus
  prompt: string
  mode?: string
  generation_mode?: string
  ts: string
  startTime: number
  startTs: string
  endTime?: number
  endTs?: string
  duration?: string
  assets?: QueueTaskAsset[]
  partial?: boolean
  requestedCount?: number
  plannedCount?: number
  succeededCount?: number
  failedCount?: number
  historyPersisted?: boolean
  warningCodes?: string[]
}
```

### B. WsUpdatePayload

```ts
export interface WsUpdatePayload {
  taskId: string
  status: TaskStatus
  prompt?: string
  mode?: string
  generation_mode?: string
  assets?: QueueTaskAsset[]
  startTime?: number
  partial?: boolean
  requestedCount?: number
  plannedCount?: number
  succeededCount?: number
  failedCount?: number
  historyPersisted?: boolean
  warningCodes?: string[]
}
```

### C. New-task handling

[queueWorker.ts:210](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/workers/queueWorker.ts:210)

```ts
_tasks.unshift({
  id:        payload.taskId,
  type:      payload.status ?? 'pending',
  prompt:    (payload.prompt?.trim() ? payload.prompt : '正在解析任务描述...').slice(0, 120),
  mode:      payload.mode || payload.generation_mode,
  generation_mode: payload.generation_mode || payload.mode,
  ts,
  startTime: payload.startTime ?? Date.now(),
  startTs:   ts,
  assets:    payload.assets ?? [],
  partial: payload.partial,
  requestedCount: payload.requestedCount,
  plannedCount: payload.plannedCount,
  succeededCount: payload.succeededCount,
  failedCount: payload.failedCount,
  historyPersisted: payload.historyPersisted,
  warningCodes: Array.isArray(payload.warningCodes) ? [...payload.warningCodes] : undefined,
})
```

### D. Existing-task merge

```ts
existing.type = payload.status
if (payload.partial !== undefined) existing.partial = payload.partial
if (payload.requestedCount !== undefined) existing.requestedCount = payload.requestedCount
if (payload.plannedCount !== undefined) existing.plannedCount = payload.plannedCount
if (payload.succeededCount !== undefined) existing.succeededCount = payload.succeededCount
if (payload.failedCount !== undefined) existing.failedCount = payload.failedCount
if (payload.historyPersisted !== undefined) existing.historyPersisted = payload.historyPersisted
if (Array.isArray(payload.warningCodes)) existing.warningCodes = [...payload.warningCodes]
```

所有七个字段均被保留。

Running/progress update 缺少 optional fields 时，因为使用 `!== undefined` 条件，不会清空之前保存的 terminal metadata。

## 4. Store Fallback Parity

[useQueueStore.ts:257](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/stores/useQueueStore.ts:257)

```ts
if (existing) {
  existing.type = payload.status
  if (payload.assets?.length) existing.assets = payload.assets
  if (payload.partial !== undefined) existing.partial = payload.partial
  if (payload.requestedCount !== undefined) existing.requestedCount = payload.requestedCount
  if (payload.plannedCount !== undefined) existing.plannedCount = payload.plannedCount
  if (payload.succeededCount !== undefined) existing.succeededCount = payload.succeededCount
  if (payload.failedCount !== undefined) existing.failedCount = payload.failedCount
  if (payload.historyPersisted !== undefined) existing.historyPersisted = payload.historyPersisted
  if (Array.isArray(payload.warningCodes)) existing.warningCodes = [...payload.warningCodes]
} else {
  tasks.value.unshift({
    id:        payload.taskId,
    type:      payload.status ?? 'pending',
    prompt:    payload.prompt ?? '',
    ts,
    startTime: payload.startTime ?? Date.now(),
    startTs:   ts,
    assets:    payload.assets ?? [],
    partial: payload.partial,
    requestedCount: payload.requestedCount,
    plannedCount: payload.plannedCount,
    succeededCount: payload.succeededCount,
    failedCount: payload.failedCount,
    historyPersisted: payload.historyPersisted,
    warningCodes: Array.isArray(payload.warningCodes) ? [...payload.warningCodes] : undefined,
  })
}
```

字段级结果：`PARITY`。

但真实 WebSocket receiver 当前是：

```ts
_ws.onmessage = (event: MessageEvent) => {
  // parse envelope...
  _worker?.postMessage(envelope)
}
```

它没有：

```ts
if (!_worker && envelope.type === 'WS_UPDATE') {
  _fallbackUpdate(...)
}
```

因此 `_fallbackUpdate()` 仅覆盖 `pushTaskUpdate()` compatibility bridge，不覆盖 Worker 不可用时的真实 socket `onmessage`。详见 RF3B-01。

## 5. TaskHistory Hydration

[QueueView.vue:34](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue:34)

```ts
function parseRecordDetails(record: any): Record<string, any> {
  let details = record?.prompt_details || {}
  if (typeof details === 'string') {
    try {
      details = JSON.parse(details)
    } catch {
      details = {}
    }
  }
  return details && typeof details === 'object' ? details : {}
}

function parseHistoryOutcome(record: any) {
  const summary = parseRecordDetails(record).planning_summary
  if (!summary || typeof summary !== 'object') return {}

  const requestedCount = summary.requested_count
  const plannedCount = summary.planned_count
  const succeededCount = summary.succeeded_count
  const failedCount = summary.failed_count
  return {
    partial: succeededCount > 0 && (failedCount > 0 || plannedCount < requestedCount),
    requestedCount,
    plannedCount,
    succeededCount,
    failedCount,
    historyPersisted: true,
    warningCodes: Array.isArray(summary.warning_codes) ? [...summary.warning_codes] : [],
  }
}
```

Task creation:

```ts
return {
  id:        r.task_id,
  type:      'completed' as const,
  prompt:    r.prompt || '',
  // ...
  ...parseHistoryOutcome(r),
  assets: (r.output_assets || [])
    .filter((asset: any) => asset.status !== 'DELETED')
    .map((asset: any) => normalizeHistoryAsset(asset, recordMeta)),
}
```

映射：

| TaskHistory | QueueTask |
|---|---|
| `requested_count` | `requestedCount` |
| `planned_count` | `plannedCount` |
| `succeeded_count` | `succeededCount` |
| `failed_count` | `failedCount` |
| `warning_codes` | `warningCodes` |

结论：

1. `planning_summary` 缺失：返回 `{}`，安全。
2. malformed JSON `prompt_details`：catch 后返回 `{}`，安全。
3. legacy history：无 planning fields，不显示 warning，安全。
4. `HISTORY_PERSIST_FAILED` 表示 history commit 失败，因此没有对应 row 可供刷新恢复。
5. capacity warning 刷新后进入 `QueueTask`，随后走同一个 `deriveRenderOutcomeSummary()`。

## 6. Mapper Call-Site Audit

Production matches：

- Mapper/constants/messages：
  - `web_ui/src/utils/renderOutcome.ts`
- Import/调用：
  - `QueueView.vue:18`
  - `QueueView.vue:25-27`
- State plumbing：
  - `queueWorker.ts`
  - `useQueueStore.ts`
- History snake_case → camelCase：
  - `QueueView.vue:50-66`

未发现其他 production file 复制 capacity/search-limit/child/history 文案。

## 7. QueueView Logic

[QueueView.vue:18](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue:18)

```ts
import { deriveRenderOutcomeSummary } from '../utils/renderOutcome'

function getOutcomeSummary(task: QueueTask) {
  return deriveRenderOutcomeSummary(task)
}

function completedStatusLabel(task: QueueTask): string {
  if (!getOutcomeSummary(task)) return '已完成'
  return task.partial ? '部分完成' : '已完成·注意'
}
```

Label semantics：

- capacity shortage / child partial：`partial=true` → `部分完成`
- full render + history failure：`partial=false` → `已完成·注意`
- exact success / legacy payload：mapper `null` → `已完成`

`requestedCount`、`plannedCount`、`succeededCount` 只在 mapper 中分别读取，没有相互替代。

## 8. User-Visible Template

### Failed / zero-plan

[QueueView.vue:530](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue:530)

```vue
<p
  class="ms-prompt"
  :class="{ 'ms-prompt--warning': !!getOutcomeSummary(item) }"
  :title="getOutcomeSummary(item)?.text || item.prompt || ''"
>{{ getOutcomeSummary(item)?.text || item.prompt || '（无描述）' }}</p>
```

Zero-plan mapper结果直接进入失败监控条 DOM。

### Completed card status

```vue
<span
  :class="[
    'status-badge',
    getOutcomeSummary(item) ? 'badge-outcome-warning' : 'badge-completed',
  ]"
>{{ completedStatusLabel(item) }}</span>
```

### Completed warning banner

```vue
<div
  v-if="getOutcomeSummary(item)"
  class="row-outcome-warning"
  :class="`row-outcome-warning--${getOutcomeSummary(item)?.severity}`"
  :title="getOutcomeSummary(item)?.text"
>
  {{ getOutcomeSummary(item)?.text }}
</div>
```

Mapper结果实际绑定到 status badge 和 warning banner，不是 console/store-only 实现。

## 9. Multi-Warning Semantics

输入：

```text
requested=4
planned=3
succeeded=2
failed=1
partial=true
warningCodes=[
  INSUFFICIENT_UNIQUE_CAPACITY,
  CHILD_EXECUTION_FAILED
]
```

输出：

- Status label：`部分完成`
- Headline：`已完成 2 个输出；规划 3/4 个。`
- Capacity clause：`当前素材组合只能形成 3 个不同的主视觉版本。`
- Child clause：`另有 1 个已规划版本生成失败。`

最终 banner：

```text
已完成 2 个输出；规划 3/4 个。 当前素材组合只能形成 3 个不同的主视觉版本。 另有 1 个已规划版本生成失败。
```

History failure 输入：

```text
requested=4
planned=4
succeeded=4
partial=false
historyPersisted=false
warningCodes=[HISTORY_PERSIST_FAILED]
```

输出：

- QueueTask status仍是 `completed`
- Status label：`已完成·注意`
- Banner：`已生成 4/4 个版本。 视频已生成，但历史记录保存失败。`
- Mapper只返回展示 severity，不修改 render status。

## 10. Legacy Compatibility

输入：

```json
{
  "status": "completed",
  "assets": []
}
```

行为：

- Missing counts → `undefined`，不会成为 `0`
- Missing `warningCodes` → `[]`
- `hasVisibleWarning=false`
- mapper返回 `null`
- Label仍为 `已完成`
- Banner不渲染
- 不显示 `0/0`
- 不被标为 partial
- 不 crash

## 11. Test Evidence

测试直接 import production mapper：

```js
import { deriveRenderOutcomeSummary } from '../src/utils/renderOutcome.ts'
```

关键测试：

```js
test('UX2 true capacity warning states 2 of 4 and proven capacity', () => {
  const result = deriveRenderOutcomeSummary({
    status: 'completed', partial: true,
    requestedCount: 4, plannedCount: 2, succeededCount: 2, failedCount: 0,
    historyPersisted: true, warningCodes: ['INSUFFICIENT_UNIQUE_CAPACITY'],
  })
  assert.match(result.text, /2\/4/)
  assert.match(result.text, /只能形成 2 个不同的主视觉版本/)
})
```

```js
test('UX3 search limit states 7 of 20 without claiming exhaustion', () => {
  const result = deriveRenderOutcomeSummary({
    status: 'completed', partial: true,
    requestedCount: 20, plannedCount: 7, succeededCount: 7, failedCount: 0,
    historyPersisted: true, warningCodes: ['PLANNING_SEARCH_LIMIT_REACHED'],
  })
  assert.match(result.text, /7\/20/)
  assert.match(result.text, /达到搜索上限/)
  assert.match(result.text, /可能仍存在其他有效组合/)
  assert.doesNotMatch(result.text, /只有 7 个|素材不足/)
})
```

```js
test('UX4 planning and child failures both remain visible', () => {
  const result = deriveRenderOutcomeSummary({
    status: 'completed', partial: true,
    requestedCount: 4, plannedCount: 3, succeededCount: 2, failedCount: 1,
    historyPersisted: true,
    warningCodes: ['INSUFFICIENT_UNIQUE_CAPACITY', 'CHILD_EXECUTION_FAILED'],
  })
  assert.match(result.text, /已完成 2 个输出；规划 3\/4 个/)
  assert.match(result.text, /只能形成 3 个不同的主视觉版本/)
  assert.match(result.text, /1 个已规划版本生成失败/)
})
```

```js
test('UX5 history failure preserves render success', () => {
  const result = deriveRenderOutcomeSummary({
    status: 'completed', partial: false,
    requestedCount: 4, plannedCount: 4, succeededCount: 4, failedCount: 0,
    historyPersisted: false, warningCodes: ['HISTORY_PERSIST_FAILED'],
  })
  assert.match(result.text, /已生成 4\/4 个版本/)
  assert.match(result.text, /视频已生成，但历史记录保存失败/)
  assert.doesNotMatch(result.text, /视频生成失败/)
})
```

```js
test('UX6 zero-plan true exhaustion has capacity wording', () => {
  const result = deriveRenderOutcomeSummary({
    type: 'failed', partial: false,
    requestedCount: 4, plannedCount: 0, succeededCount: 0, failedCount: 0,
    historyPersisted: false, warningCodes: ['INSUFFICIENT_UNIQUE_CAPACITY'],
  })
  assert.match(result.text, /未生成任何版本/)
  assert.match(result.text, /无法形成可执行的不同主视觉版本/)
})
```

```js
test('UX7 zero-plan search limit does not claim true exhaustion', () => {
  const result = deriveRenderOutcomeSummary({
    type: 'failed', partial: false,
    requestedCount: 4, plannedCount: 0, succeededCount: 0, failedCount: 0,
    historyPersisted: false, warningCodes: ['PLANNING_SEARCH_LIMIT_REACHED'],
  })
  assert.match(result.text, /达到搜索上限/)
  assert.match(result.text, /可能仍存在其他有效组合/)
  assert.doesNotMatch(result.text, /素材组合无法形成|素材不足/)
})
```

```js
test('UX8 legacy completed payload keeps existing behavior', () => {
  assert.equal(deriveRenderOutcomeSummary({ status: 'completed' }), null)
})
```

## 12. Frontend Field Audit

| Category | Locations |
|---|---|
| A. Type/state plumbing | `queueWorker.ts`, `useQueueStore.ts` |
| B. History hydration | `QueueView.vue:50-66` |
| C. Mapper | `renderOutcome.ts` |
| D. UI consumption | `QueueView.vue:25-31`, template lines 530–605 |
| E. Unexpected duplicate logic | NONE |

Warning messages are centralized in the mapper.

## 13. Scope Audit

Tracked implementation diff only contains:

```text
web_ui/src/stores/useQueueStore.ts
web_ui/src/views/QueueView.vue
web_ui/src/workers/queueWorker.ts
```

另有 untracked frontend mapper/tests 和 investigation report。

未修改：

- `src/api/*`
- Planner
- resolver
- DB/schema/models
- BGM
- TTS
- Subtitle
- Compositor
- Cover

## 14. Test / Build Results

Node mapper tests：

```text
tests 8
pass 8
fail 0
```

Frontend build：

```text
vite v7.3.1
136 modules transformed
✓ built in 6.55s
```

仅有既有 Browserslist freshness 与 Login import warning。

INV-001 regression：

```text
Ran 77 tests in 0.648s
OK
```

未安装或升级依赖。

## 15. Review Findings

### RF3B-01 — Real WebSocket lacks Worker-unavailable fallback dispatch

`useQueueStore.ts` 的真实 socket receiver 使用：

```ts
_worker?.postMessage(envelope)
```

当 Web Worker 不可用或初始化失败时，该 WS envelope 会被静默丢弃。字段完整的 `_fallbackUpdate()` 只由 `pushTaskUpdate()` 调用，没有从 `_ws.onmessage` 接管真实 `WS_UPDATE`。

影响：

- 正常支持 Web Worker 的当前主路径不受影响。
- Worker 不可用环境无法完成：
  `WebSocket → fallback → task state → UI`
- 这是 wiring gap，不是字段 parity 或 mapper语义错误。

本轮按要求只记录，未修复。

## 16. Final Git Status

```text
 M web_ui/src/stores/useQueueStore.ts
 M web_ui/src/views/QueueView.vue
 M web_ui/src/workers/queueWorker.ts
?? doc/investigations/INV-001-Gate3-Phase3B-Planner-Capacity-Warning-UX-Report.md
?? web_ui/src/utils/renderOutcome.ts
?? web_ui/tests/
```

未修改文件、未 commit、未 push、未进入 Phase 4。