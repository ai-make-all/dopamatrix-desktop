# VAR-001 Phase 2C Targeted Code Review Bundle

Targeted review found two concrete edge-path issues:

- `VAR2C-RF-01`: historical hydration can overwrite valid live diagnostics with `undefined`.
- `VAR2C-RF-02`: an exception after diagnostics validation but before coordinator completion can leave diagnostics attached to a `VARIANT_PLANNING_FAILED` terminal response.

No files were modified and no tests or services were run.

## A. Git Status

```text
 M src/api/routes_dsl.py
 M tests/test_var001_coverage_diagnostics.py
 M web_ui/src/stores/useQueueStore.ts
 M web_ui/src/views/QueueView.vue
 M web_ui/src/workers/queueWorker.ts
?? web_ui/src/utils/coverageDiagnostics.ts
?? web_ui/tests/coverageDiagnostics.test.mjs
```

```text
src/api/routes_dsl.py                     |  2 ++
tests/test_var001_coverage_diagnostics.py | 11 ++++++++---
web_ui/src/stores/useQueueStore.ts        |  4 ++++
web_ui/src/views/QueueView.vue            |  3 +++
web_ui/src/workers/queueWorker.ts         | 10 ++++++++++
5 files changed, 27 insertions(+), 3 deletions(-)
```

The stat excludes the two untracked files.

## B. Backend Terminal Transport

Current implementation in [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:2056):

```python
def render_batch_worker(
    dsl_payload: Optional[StoryDSLPayload],
    task_id: str,
    aspect_ratio: str = "9:16",
    target_duration: int = 15,
    tenant_id: str = "default",
    prompt: Optional[str] = None,
    batch_size: int = 1,
    test_language: str = "en",
    *,
    blind_dsl: bool = False,
    engine_type: str = "content",
    director_mode: str = "auto",
    enable_tts: bool = True,
    enable_subtitles: bool = True,
    resolved_plan: Optional[CompilationPlan] = None,
    variant_planning_policy: str = "legacy",
) -> dict[str, Any]:
    """
    批量矩阵渲染 Worker（Phase 5.9）。

    所有 batch size 都经过本 coordinator。每个 child 仅返回 execution-local
    result；本函数稳定聚合、写入一条 TaskHistory，并发送唯一 terminal WS。
    """
    batch_start = time.time()
    logger.info(
        "[render_batch_worker] 批量渲染启动 task_id=%s batch=%d",
        task_id, batch_size,
    )

    planning_warning_codes: list[str] = []
    coverage_diagnostics_payload: Optional[dict[str, Any]] = None
    child_work: list[_ChildWork] = []
    planning_function = None
    if variant_planning_policy == "exact_main_visual":
        planning_function = _plan_exact_main_visual_variants_from_db
    elif variant_planning_policy == "exact_main_visual_balanced":
        planning_function = _plan_exact_main_visual_balanced_variants_from_db

    if planning_function is not None:
        if blind_dsl or dsl_payload is None:
            logger.error(
                "[render_batch_worker] authoritative planning received unsupported/missing "
                "DSL task_id=%s policy=%s blind=%s",
                task_id,
                variant_planning_policy,
                blind_dsl,
            )
            planning_warning_codes.append("VARIANT_PLANNING_FAILED")
        else:
            try:
                planning_result = planning_function(
                    tenant_id,
                    dsl_payload,
                    batch_size,
                    preview_plan=resolved_plan,
                )
                computed_fingerprints = tuple(
                    _exact_main_visual_fingerprint(plan)
                    for plan in planning_result.plans
                )
                if (
                    computed_fingerprints != planning_result.fingerprints
                    or len(set(computed_fingerprints)) != len(computed_fingerprints)
                ):
                    raise ValueError(
                        "PLANNER_RESULT_INVALID: authoritative plans/fingerprints mismatch"
                    )
                if variant_planning_policy == _BALANCED_VARIANT_PLANNING_POLICY:
                    if planning_result.coverage_diagnostics is None:
                        raise ValueError("COVERAGE_DIAGNOSTICS_MISSING")
                    coverage_diagnostics_payload = (
                        _validated_coverage_diagnostics_payload(
                            planning_result.coverage_diagnostics,
                            planning_result,
                            computed_fingerprints,
                        )
                    )
                    _emit_balanced_coverage_summary(
                        task_id,
                        coverage_diagnostics_payload,
                    )
                elif planning_result.coverage_diagnostics is not None:
                    raise ValueError("COVERAGE_DIAGNOSTICS_UNEXPECTED_FOR_EXACT_POLICY")
                planning_warning_codes.extend(planning_result.warning_codes)
                identities = (
                    _create_child_executions(task_id, len(planning_result.plans))
                    if planning_result.plans
                    else []
                )
                child_work = [
                    _ChildWork(
                        execution=identity,
                        authoritative_plan=plan,
                        visual_fingerprint=fingerprint,
                    )
                    for identity, plan, fingerprint in zip(
                        identities,
                        planning_result.plans,
                        planning_result.fingerprints,
                    )
                ]
                logger.info(
                    "[render_batch_worker] authoritative planning task_id=%s policy=%s "
                    "requested=%d planned=%d examined=%d space=%d reason=%s warnings=%s",
                    task_id,
                    variant_planning_policy,
                    batch_size,
                    len(child_work),
                    planning_result.examined_combinations,
                    planning_result.candidate_space_size,
                    planning_result.termination_reason,
                    planning_warning_codes,
                )
            except Exception:
                logger.exception(
                    "[render_batch_worker] authoritative planning failed task_id=%s "
                    "policy=%s",
                    task_id,
                    variant_planning_policy,
                )
                planning_warning_codes.append("VARIANT_PLANNING_FAILED")
    elif variant_planning_policy == "legacy":
        child_work = [
            _ChildWork(execution=child)
            for child in _create_child_executions(task_id, batch_size)
        ]
    else:
        logger.error(
            "[render_batch_worker] unsupported variant planning policy task_id=%s policy=%s",
            task_id,
            variant_planning_policy,
        )
        planning_warning_codes.append("VARIANT_PLANNING_FAILED")

    child_results: list[_ChildResult] = []

    def _execute_child(work: _ChildWork) -> _ChildResult:
        child = work.execution
        child_start = time.time()
        try:
            result = render_worker(
                (
                    work.authoritative_plan
                    if work.authoritative_plan is not None
                    else (None if blind_dsl else resolved_plan)
                ),
                task_id,
                aspect_ratio, target_duration, tenant_id,
                prompt, batch_size, test_language,
                child.file_sid,
                execution_id=child.execution_id,
                child_index=child.child_index,
                blind_dsl=blind_dsl,
                engine_type=engine_type,
                director_mode=director_mode,
                dsl_payload=None if blind_dsl else dsl_payload,
                plan_is_authoritative=work.authoritative_plan is not None,
                visual_fingerprint=work.visual_fingerprint,
                enable_tts=enable_tts,
                enable_subtitles=enable_subtitles,
            )
            if not isinstance(result, _ChildResult):
                raise TypeError("render_worker must return _ChildResult")
            if (
                result.child_index != child.child_index
                or result.execution_id != child.execution_id
                or result.file_sid != child.file_sid
            ):
                raise ValueError("render_worker returned mismatched child identity")
            return result
        except Exception as exc:
            logger.exception(
                "[render_batch_worker] child 异常 task_id=%s execution_id=%s "
                "child_index=%d file_sid=%s",
                task_id, child.execution_id, child.child_index, child.file_sid,
            )
            return _failed_child_result(
                child,
                "CHILD_EXCEPTION",
                str(exc),
                time.time() - child_start,
            )

    if len(child_work) == 1:
        child_results.append(_execute_child(child_work[0]))
    elif len(child_work) > 1:
        with ThreadPoolExecutor(max_workers=len(child_work)) as pool:
            future_map = {
                pool.submit(_execute_child, work): work.execution
                for work in child_work
            }
            for future in as_completed(future_map):
                child = future_map[future]
                try:
                    child_results.append(future.result())
                except Exception as exc:
                    logger.exception(
                        "[render_batch_worker] future 收口异常 task_id=%s execution_id=%s "
                        "child_index=%d file_sid=%s",
                        task_id, child.execution_id, child.child_index, child.file_sid,
                    )
                    child_results.append(
                        _failed_child_result(child, "CHILD_FUTURE_FAILED", str(exc))
                    )

    child_results.sort(key=lambda result: result.child_index)
    for result in child_results:
        log_method = logger.info if result.succeeded else logger.warning
        log_method(
            "[render_batch_worker] child 收口 task_id=%s execution_id=%s "
            "child_index=%d file_sid=%s outcome=%s assets=%d error_code=%s",
            task_id, result.execution_id, result.child_index, result.file_sid,
            "succeeded" if result.succeeded else "failed",
            len(result.assets), result.error_code,
        )
    successful_results = [result for result in child_results if result.succeeded]
    all_assets = [
        dict(asset)
        for result in successful_results
        for asset in result.assets
    ]
    succeeded_count = len(successful_results)
    failed_count = len(child_results) - succeeded_count
    planned_count = len(child_results)
    partial = succeeded_count > 0 and (
        failed_count > 0 or planned_count < batch_size
    )
    warning_codes = list(dict.fromkeys(planning_warning_codes))
    if failed_count and "CHILD_EXECUTION_FAILED" not in warning_codes:
        warning_codes.append("CHILD_EXECUTION_FAILED")

    history_persisted = False
    elapsed = time.time() - batch_start
    if succeeded_count:
        try:
            _persist_task_history(
                task_id=task_id,
                tenant_id=tenant_id,
                prompt=prompt,
                batch_size=batch_size,
                elapsed=elapsed,
                child_results=child_results,
                output_assets=all_assets,
                warning_codes=warning_codes,
                coverage_diagnostics=coverage_diagnostics_payload,
            )
            history_persisted = True
            logger.info(
                "[render_batch_worker] 历史记录写入成功 task_id=%s outputs=%d",
                task_id, len(all_assets),
            )
        except Exception:
            warning_codes.append("HISTORY_PERSIST_FAILED")
            logger.exception(
                "[render_batch_worker] 历史记录写入失败 task_id=%s；保留渲染结果",
                task_id,
            )

    final_status = "completed" if succeeded_count else "failed"
    terminal_payload: dict[str, Any] = {
        "taskId": task_id,
        "status": final_status,
        "generation_mode": director_mode,
        "partial": partial,
        "requestedCount": batch_size,
        "plannedCount": planned_count,
        "succeededCount": succeeded_count,
        "failedCount": failed_count,
        "historyPersisted": history_persisted,
        "warningCodes": warning_codes,
    }
    if all_assets:
        terminal_payload["assets"] = all_assets
    if coverage_diagnostics_payload is not None:
        terminal_payload["coverageDiagnostics"] = coverage_diagnostics_payload

    try:
        ws_manager.broadcast_sync(
            {"type": "WS_UPDATE", "payload": terminal_payload},
            user_id=tenant_id,
        )
        logger.info(
            "[render_batch_worker] task_id=%s status=%s partial=%s "
            "succeeded=%d failed=%d assets=%d history_persisted=%s",
            task_id, final_status, partial, succeeded_count, failed_count,
            len(all_assets), history_persisted,
        )
    except Exception:
        logger.exception(
            "[render_batch_worker] WS 广播失败 task_id=%s", task_id,
        )

    return terminal_payload
```

Validation ordering is proven: the assignment only happens after `_validated_coverage_diagnostics_payload()` returns successfully. If that validator raises, Python does not perform the assignment, so the initialized `None` remains and the terminal field is absent.

There is, however, a later failure edge:

```text
validator succeeds
→ coverage_diagnostics_payload assigned
→ child identity allocation/list construction/logger unexpectedly raises
→ broad except appends VARIANT_PLANNING_FAILED
→ coverage_diagnostics_payload is not cleared
→ terminal includes coverageDiagnostics
```

This can produce `plannedCount == 0`, `VARIANT_PLANNING_FAILED`, and a non-empty planning diagnostics payload.

Finding:

`VAR2C-RF-02`
`COVERAGE_DIAGNOSTICS_SURVIVES_POST_VALIDATION_COORDINATOR_FAILURE`

## C. CoverageDiagnostics V1 Normalizer

Complete [coverageDiagnostics.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/utils/coverageDiagnostics.ts):

```ts
export type CoverageClassificationV1 =
  | 'FIXED_BY_CAPACITY'
  | 'VARIABLE_BALANCED'
  | 'VARIABLE_TARGET_NOT_MET'

export interface CoverageHistogramEntryV1 {
  normalized_file_hash: string
  asset_id: number
  count: number
}

export interface CoverageBeatDiagnosticsV1 {
  beat_index: number
  beat_identity: string
  role: string
  pool_size: number
  selected_histogram: CoverageHistogramEntryV1[]
  selected_count: number
  unique_used: number
  unused_count: number
  ideal_floor: number | null
  ideal_ceil: number | null
  max_min_gap: number | null
  classification: CoverageClassificationV1 | null
}

export interface CoverageRejectionCountsV1 {
  materialization_mismatch_count: number
  invalid_plan_count: number
  duplicate_fingerprint_reject_count: number
}

export interface CoverageDiagnosticsV1 {
  type: 'balanced_axis_coverage'
  version: 1
  variant_planning_policy: 'exact_main_visual_balanced'
  requested_count: number
  accepted_count: number
  candidate_space_size: number
  search_budget: number
  examined_count: number
  proposal_attempted_count: number
  termination_reason: string
  preview_seeded: boolean
  preview_child_index: number | null
  preview_fingerprint_digest: string | null
  accepted_fingerprint_digests: string[]
  rejection_counts: CoverageRejectionCountsV1
  beats: CoverageBeatDiagnosticsV1[]
}

type UnknownRecord = Record<string, unknown>

const CLASSIFICATIONS = new Set<CoverageClassificationV1>([
  'FIXED_BY_CAPACITY',
  'VARIABLE_BALANCED',
  'VARIABLE_TARGET_NOT_MET',
])

const SHA256_HEX = /^[0-9a-f]{64}$/

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value)
}

function isNonNegativeInteger(value: unknown): value is number {
  return isInteger(value) && value >= 0
}

function isNullableNonNegativeInteger(value: unknown): value is number | null {
  return value === null || isNonNegativeInteger(value)
}

function isDigest(value: unknown): value is string {
  return typeof value === 'string' && SHA256_HEX.test(value)
}

function normalizeHistogramEntry(value: unknown): CoverageHistogramEntryV1 | undefined {
  if (!isRecord(value)) return undefined
  if (
    typeof value.normalized_file_hash !== 'string'
    || value.normalized_file_hash.trim().length === 0
    || !isInteger(value.asset_id)
    || !isInteger(value.count)
    || value.count <= 0
  ) {
    return undefined
  }
  return {
    normalized_file_hash: value.normalized_file_hash,
    asset_id: value.asset_id,
    count: value.count,
  }
}

function normalizeBeat(value: unknown): CoverageBeatDiagnosticsV1 | undefined {
  if (!isRecord(value) || !Array.isArray(value.selected_histogram)) return undefined
  if (
    !isNonNegativeInteger(value.beat_index)
    || typeof value.beat_identity !== 'string'
    || typeof value.role !== 'string'
    || !isNonNegativeInteger(value.pool_size)
    || !isNonNegativeInteger(value.selected_count)
    || !isNonNegativeInteger(value.unique_used)
    || !isNonNegativeInteger(value.unused_count)
    || !isNullableNonNegativeInteger(value.ideal_floor)
    || !isNullableNonNegativeInteger(value.ideal_ceil)
    || !isNullableNonNegativeInteger(value.max_min_gap)
    || !(
      value.classification === null
      || (
        typeof value.classification === 'string'
        && CLASSIFICATIONS.has(value.classification as CoverageClassificationV1)
      )
    )
  ) {
    return undefined
  }

  const selectedHistogram: CoverageHistogramEntryV1[] = []
  for (const entry of value.selected_histogram) {
    const normalized = normalizeHistogramEntry(entry)
    if (!normalized) return undefined
    selectedHistogram.push(normalized)
  }

  return {
    beat_index: value.beat_index,
    beat_identity: value.beat_identity,
    role: value.role,
    pool_size: value.pool_size,
    selected_histogram: selectedHistogram,
    selected_count: value.selected_count,
    unique_used: value.unique_used,
    unused_count: value.unused_count,
    ideal_floor: value.ideal_floor,
    ideal_ceil: value.ideal_ceil,
    max_min_gap: value.max_min_gap,
    classification: value.classification as CoverageClassificationV1 | null,
  }
}

export function normalizeCoverageDiagnostics(
  value: unknown,
): CoverageDiagnosticsV1 | undefined {
  if (!isRecord(value)) return undefined
  if (
    value.type !== 'balanced_axis_coverage'
    || value.version !== 1
    || value.variant_planning_policy !== 'exact_main_visual_balanced'
    || !isNonNegativeInteger(value.requested_count)
    || !isNonNegativeInteger(value.accepted_count)
    || !isNonNegativeInteger(value.candidate_space_size)
    || !isNonNegativeInteger(value.search_budget)
    || !isNonNegativeInteger(value.examined_count)
    || !isNonNegativeInteger(value.proposal_attempted_count)
    || typeof value.termination_reason !== 'string'
    || typeof value.preview_seeded !== 'boolean'
    || !(value.preview_child_index === null || isInteger(value.preview_child_index))
    || !(value.preview_fingerprint_digest === null || isDigest(value.preview_fingerprint_digest))
    || !Array.isArray(value.accepted_fingerprint_digests)
    || !value.accepted_fingerprint_digests.every(isDigest)
    || !isRecord(value.rejection_counts)
    || !isNonNegativeInteger(value.rejection_counts.materialization_mismatch_count)
    || !isNonNegativeInteger(value.rejection_counts.invalid_plan_count)
    || !isNonNegativeInteger(value.rejection_counts.duplicate_fingerprint_reject_count)
    || !Array.isArray(value.beats)
  ) {
    return undefined
  }

  const beats: CoverageBeatDiagnosticsV1[] = []
  for (const beat of value.beats) {
    const normalized = normalizeBeat(beat)
    if (!normalized) return undefined
    beats.push(normalized)
  }

  return {
    type: 'balanced_axis_coverage',
    version: 1,
    variant_planning_policy: 'exact_main_visual_balanced',
    requested_count: value.requested_count,
    accepted_count: value.accepted_count,
    candidate_space_size: value.candidate_space_size,
    search_budget: value.search_budget,
    examined_count: value.examined_count,
    proposal_attempted_count: value.proposal_attempted_count,
    termination_reason: value.termination_reason,
    preview_seeded: value.preview_seeded,
    preview_child_index: value.preview_child_index,
    preview_fingerprint_digest: value.preview_fingerprint_digest,
    accepted_fingerprint_digests: [...value.accepted_fingerprint_digests],
    rejection_counts: {
      materialization_mismatch_count: value.rejection_counts.materialization_mismatch_count,
      invalid_plan_count: value.rejection_counts.invalid_plan_count,
      duplicate_fingerprint_reject_count: value.rejection_counts.duplicate_fingerprint_reject_count,
    },
    beats,
  }
}
```

Boundary review:

- No unsafe whole-object cast to `CoverageDiagnosticsV1`.
- The classification cast occurs only after string and enum membership validation.
- No coverage mathematics is recomputed.
- Histogram order is preserved by ordered iteration and `push`.
- Fresh top-level, Beat, histogram, rejection, and digest arrays/objects are constructed.
- P=0/null is accepted.
- B<P is accepted because histogram length is not compared to `pool_size`.

## D. Queue Worker

Current types in [queueWorker.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/workers/queueWorker.ts:18):

```ts
import {
  normalizeCoverageDiagnostics,
  type CoverageDiagnosticsV1,
} from '../utils/coverageDiagnostics'

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
  coverageDiagnostics?: CoverageDiagnosticsV1
}

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
  coverageDiagnostics?: unknown
}
```

Worker emission and message handling:

```ts
function _broadcastTick(): void {
  // 发出浅拷贝，防止 transferable 意外污染内部状态
  ;(self as DedicatedWorkerGlobalScope).postMessage({
    type:    'TICK',
    payload: {
      tasks: _tasks.slice(),
      stats: { ..._stats },
    },
  })
}

;(self as DedicatedWorkerGlobalScope).onmessage = (event: MessageEvent) => {
  const msg = event.data as { type: string; payload?: unknown }
  if (!msg?.type) return

  switch (msg.type) {

    case 'WS_UPDATE':
      _handleWsUpdate(msg.payload as WsUpdatePayload)
      break

    case 'INIT_TASKS': {
      const incoming = msg.payload
      if (Array.isArray(incoming)) {
        _tasks = (incoming as QueueTask[]).filter(t => t && typeof t.id === 'string')
        _recomputeStats()
        _broadcastTick()
      }
      break
    }

    case 'STOP':
      clearInterval(_tickInterval)
      break

    default:
      break
  }
}
```

Live create/update:

```ts
function _handleWsUpdate(payload: WsUpdatePayload): void {
  if (!payload?.taskId) return

  const existing = _tasks.find(t => t.id === payload.taskId)
  const coverageDiagnostics = normalizeCoverageDiagnostics(payload.coverageDiagnostics)

  if (!existing) {
    const now = new Date()
    const ts  = now.toLocaleTimeString('zh', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })

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
      coverageDiagnostics,
    })
  } else {
    const prevType = existing.type

    existing.type = payload.status
    if (payload.partial !== undefined) existing.partial = payload.partial
    if (payload.requestedCount !== undefined) existing.requestedCount = payload.requestedCount
    if (payload.plannedCount !== undefined) existing.plannedCount = payload.plannedCount
    if (payload.succeededCount !== undefined) existing.succeededCount = payload.succeededCount
    if (payload.failedCount !== undefined) existing.failedCount = payload.failedCount
    if (payload.historyPersisted !== undefined) existing.historyPersisted = payload.historyPersisted
    if (Array.isArray(payload.warningCodes)) existing.warningCodes = [...payload.warningCodes]
    if (coverageDiagnostics) existing.coverageDiagnostics = coverageDiagnostics
    if (payload.mode || payload.generation_mode) {
      existing.mode = payload.mode || payload.generation_mode
      existing.generation_mode = payload.generation_mode || payload.mode
    }

    if (payload.assets?.length) {
      existing.assets = payload.assets
        .filter(a => a && typeof a === 'object')
        .map(a => ({
          ...a,
          file_path:  typeof a.file_path  === 'string' ? a.file_path  : (typeof a.path === 'string' ? a.path : ''),
          file_hash:  typeof a.file_hash  === 'string' ? a.file_hash  : (typeof a.hash === 'string' ? a.hash : ''),
          cover_path: typeof a.cover_path === 'string' ? a.cover_path : undefined,
        }))
    }

    const nowMs  = Date.now()
    const nowStr = new Date(nowMs).toLocaleTimeString('zh', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })

    if (prevType !== 'completed' && payload.status === 'completed') {
      existing.endTime = nowMs
      existing.endTs   = nowStr

      if (existing.startTime) {
        const durationSec  = (nowMs - existing.startTime) / 1_000
        existing.duration  = durationSec.toFixed(1) + 's'
        _recordCompletedDuration(durationSec)
      }

    } else if (
      (prevType === 'pending' || prevType === 'running') &&
      payload.status === 'failed'
    ) {
      existing.endTime = nowMs
      existing.endTs   = nowStr
    }
  }

  _recomputeStats()
  _broadcastTick()
}
```

Direct `WS_UPDATE` semantics are correct:

- Valid diagnostics replace the stored value.
- Absent, `undefined`, malformed, or unknown-version diagnostics normalize to `undefined`.
- The conditional assignment then preserves an existing valid value.

`INIT_TASKS` differs: it replaces the entire worker task array without a field-level merge.

## E. Queue Store

Type ownership and worker TICK handling in [useQueueStore.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/stores/useQueueStore.ts:12):

```ts
import { defineStore } from 'pinia'
import { ref }         from 'vue'
import { normalizeCoverageDiagnostics } from '../utils/coverageDiagnostics'

export type { QueueTask, QueueTaskAsset, QueueStats, TaskStatus, WsUpdatePayload } from '../workers/queueWorker'
import type { QueueTask, QueueStats, WsUpdatePayload } from '../workers/queueWorker'

const tasks = ref<QueueTask[]>([])
const stats = ref<QueueStats>({ ...EMPTY_STATS })

function initWorker(): void {
  if (_worker) return

  if (typeof Worker === 'undefined') {
    console.warn('[QueueStore] 当前环境不支持 Web Worker，降级为直接状态更新。')
    return
  }

  _worker = new Worker(
    new URL('../workers/queueWorker.ts', import.meta.url),
    { type: 'module' }
  )

  _worker.onmessage = (event: MessageEvent) => {
    const { type, payload } = (event.data ?? {}) as {
      type: string
      payload?: { tasks: QueueTask[]; stats: QueueStats }
    }

    if (type === 'TICK' && payload) {
      tasks.value = payload.tasks
      stats.value = payload.stats
    }
  }
}
```

Update, initialization, and fallback paths:

```ts
function pushTaskUpdate(payload: WsUpdatePayload): void {
  if (!payload?.taskId) return

  if (_worker) {
    _worker.postMessage({ type: 'WS_UPDATE', payload })
  } else {
    _fallbackUpdate(payload)
  }
}

function initTasks(initialTasks: QueueTask[]): void {
  if (!Array.isArray(initialTasks)) return

  if (_worker) {
    _worker.postMessage({ type: 'INIT_TASKS', payload: initialTasks })
  } else {
    tasks.value = initialTasks
  }
}

function _fallbackUpdate(payload: WsUpdatePayload): void {
  const existing = tasks.value.find(t => t.id === payload.taskId)
  const coverageDiagnostics = normalizeCoverageDiagnostics(payload.coverageDiagnostics)
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
    if (coverageDiagnostics) existing.coverageDiagnostics = coverageDiagnostics
  } else {
    const now = new Date()
    const ts  = now.toLocaleTimeString('zh', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
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
      coverageDiagnostics,
    })
  }

  const counts = tasks.value.reduce(
    (acc, t) => { acc[t.type] = (acc[t.type] ?? 0) + 1; return acc },
    {} as Record<string, number>
  )
  stats.value = {
    totalPending:         counts['pending']   ?? 0,
    totalRunning:         counts['running']   ?? 0,
    totalCompleted:       counts['completed'] ?? 0,
    totalFailed:          counts['failed']    ?? 0,
    estimatedETA_seconds: 0,
  }
}
```

The direct worker and fallback update paths preserve existing valid diagnostics when an update omits the field.

The snapshot path does not merge:

```ts
tasks.value = initialTasks
```

or, in the worker:

```ts
_tasks = (incoming as QueueTask[]).filter(...)
```

Its safety therefore depends entirely on the objects supplied by historical hydration.

## F. Historical Hydration

Current source in [QueueView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue:35):

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

function parseRecordMeta(record: any): Record<string, any> {
  return parseRecordDetails(record).meta || {}
}

function parseHistoryOutcome(record: any) {
  const summary = parseRecordDetails(record).planning_summary
  if (!summary || typeof summary !== 'object') return {}

  const requestedCount = summary.requested_count
  const plannedCount = summary.planned_count
  const succeededCount = summary.succeeded_count
  const failedCount = summary.failed_count
  const coverageDiagnostics = normalizeCoverageDiagnostics(summary.coverage_diagnostics)
  return {
    partial: succeededCount > 0 && (failedCount > 0 || plannedCount < requestedCount),
    requestedCount,
    plannedCount,
    succeededCount,
    failedCount,
    historyPersisted: true,
    warningCodes: Array.isArray(summary.warning_codes) ? [...summary.warning_codes] : [],
    coverageDiagnostics,
  }
}
```

Historical construction and merging:

```ts
async function fetchTodayTasks(): Promise<Map<string, QueueTask>> {
  const hydratedById = new Map<string, QueueTask>()
  try {
    const userId = appStore.loggedInUser || 'default'
    const resp = await fetch(`${appStore.API_BASE}/api/v1/tasks/today`, {
      headers: { 'X-Local-User': userId },
    })
    if (!resp.ok) return hydratedById

    const records: any[] = await resp.json()

    const todayCompleted: QueueTask[] = records.map(r => {
      const createdAt = new Date(r.created_at)
      const ts = createdAt.toLocaleTimeString('zh', {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      })
      const recordMeta = parseRecordMeta(r)
      return {
        id:        r.task_id,
        type:      'completed' as const,
        prompt:    r.prompt || '',
        ts,
        startTime: createdAt.getTime(),
        startTs:   ts,
        endTs:     ts,
        duration:  r.duration != null ? `${Number(r.duration).toFixed(1)}s` : '',
        mode:      r.mode || r.generation_mode || recordMeta.mode || 'manual',
        generation_mode: r.generation_mode || r.mode || recordMeta.mode || 'manual',
        ...parseHistoryOutcome(r),
        assets: (r.output_assets || [])
          .filter((asset: any) => asset.status !== 'DELETED')
          .map((asset: any) => normalizeHistoryAsset(asset, recordMeta)),
      }
    })

    todayCompleted.forEach(t => hydratedById.set(t.id, t))

    const mergedTasks = queueStore.tasks.map(t =>
      t.type === 'completed' && hydratedById.has(t.id)
        ? { ...t, ...hydratedById.get(t.id)! }
        : t
    )
    const existingIds = new Set(mergedTasks.map(t => t.id))
    const newTasks = todayCompleted.filter(t => !existingIds.has(t.id))
    queueStore.initTasks([...mergedTasks, ...newTasks])
  } catch (err) {
    console.warn('[QueueView] fetchTodayTasks 失败（已忽略）:', err)
  }
  return hydratedById
}
```

No template hunk changed. The complete QueueView diff contains only:

- one script import
- one normalization call
- one returned data property

Therefore no visible Coverage UI exists.

## G. Live / Historical Shape Proof

### A. Live balanced terminal

```ts
QueueTask {
  ...
  coverageDiagnostics: CoverageDiagnosticsV1
}
```

Source path:

```text
terminal_payload.coverageDiagnostics
→ WS_UPDATE.payload
→ normalizeCoverageDiagnostics(payload.coverageDiagnostics)
→ QueueTask.coverageDiagnostics
```

### B. Historical balanced task

```ts
QueueTask {
  ...
  coverageDiagnostics: CoverageDiagnosticsV1
}
```

Source path:

```text
prompt_details.planning_summary.coverage_diagnostics
→ normalizeCoverageDiagnostics(summary.coverage_diagnostics)
→ parseHistoryOutcome()
→ historical QueueTask
```

### C. Historical old task

If `planning_summary` does not exist, `parseHistoryOutcome()` returns `{}` and the property is absent.

If `planning_summary` exists but `coverage_diagnostics` does not, the normalized value is `undefined` and the constructed task contains:

```ts
coverageDiagnostics: undefined
```

Both represent “diagnostics unavailable” to consumers.

`PHASE2C_SINGLE_NORMALIZER_SOURCE_PROVEN`

## H. Store Erase Semantics

Direct `WS_UPDATE` paths do not erase an existing valid value:

```ts
if (coverageDiagnostics) existing.coverageDiagnostics = coverageDiagnostics
```

However, historical hydration has a real erase path:

```text
existing live completed task
coverageDiagnostics = valid V1

→ historical record has planning_summary
   but coverage_diagnostics is missing/malformed

→ parseHistoryOutcome returns
   coverageDiagnostics: undefined

→ { ...t, ...hydratedById.get(t.id)! }

→ historical undefined overwrites live valid value

→ initTasks replaces the entire task snapshot
```

Therefore absence does not consistently mean “no new information.”

Finding:

`VAR2C-RF-01`
`COVERAGE_DIAGNOSTICS_CAN_BE_ERASED_BY_ABSENT_UPDATE`

The direct live worker/fallback merge is safe; the defect is in historical merge plus snapshot replacement.

## I. Targeted Tests

The complete frontend test file is [coverageDiagnostics.test.mjs](E:/dopaworkspace/dopamatrix-desktop/web_ui/tests/coverageDiagnostics.test.mjs). Its assertions cover:

```js
test('valid V1 normalizes five Beats and returns a detached copy', () => {
  const source = representativePayload()
  const normalized = normalizeCoverageDiagnostics(source)

  assert.ok(normalized)
  assert.equal(normalized.beats.length, 5)
  assert.deepEqual(normalized, source)
  assert.notStrictEqual(normalized, source)
  assert.notStrictEqual(normalized.beats, source.beats)
  assert.notStrictEqual(normalized.beats[0].selected_histogram, source.beats[0].selected_histogram)
  assert.notStrictEqual(normalized.rejection_counts, source.rejection_counts)
  assert.notStrictEqual(
    normalized.accepted_fingerprint_digests,
    source.accepted_fingerprint_digests,
  )
})

test('old or absent diagnostics fail closed without throwing', () => {
  assert.equal(normalizeCoverageDiagnostics(undefined), undefined)
  assert.equal(normalizeCoverageDiagnostics(null), undefined)
  assert.equal(normalizeCoverageDiagnostics({}), undefined)
})

test('identity fields are independently enforced', () => {
  for (const [field, invalid] of [
    ['type', 'other'],
    ['version', 2],
    ['variant_planning_policy', 'exact_main_visual'],
  ]) {
    const payload = representativePayload()
    payload[field] = invalid
    assert.equal(normalizeCoverageDiagnostics(payload), undefined, field)
  }
})

test('unsafe structural shapes fail closed', () => {
  const mutations = [
    payload => { payload.beats[0].pool_size = -1 },
    payload => { payload.accepted_count = '4' },
    payload => { payload.beats[0].classification = 'UNKNOWN' },
    payload => { payload.accepted_fingerprint_digests[0] = 'not-a-digest' },
    payload => { payload.beats = {} },
    payload => { payload.beats[0].selected_histogram[0].count = 0 },
  ]

  for (const mutate of mutations) {
    const payload = representativePayload()
    mutate(payload)
    assert.equal(normalizeCoverageDiagnostics(payload), undefined)
  }
})

test('P=0 and B<P backend edge shapes are preserved without frontend math', () => {
  const zeroPool = representativePayload()
  zeroPool.beats[0] = {
    beat_index: 0,
    beat_identity: 'hook',
    role: 'X',
    pool_size: 0,
    selected_histogram: [],
    selected_count: 0,
    unique_used: 0,
    unused_count: 0,
    ideal_floor: null,
    ideal_ceil: null,
    max_min_gap: null,
    classification: null,
  }
  assert.deepEqual(normalizeCoverageDiagnostics(zeroPool)?.beats[0], zeroPool.beats[0])

  const fewerSelectionsThanPool = representativePayload()
  const normalized = normalizeCoverageDiagnostics(fewerSelectionsThanPool)
  assert.ok(normalized)
  assert.equal(normalized.beats[0].pool_size, 4)
  assert.equal(normalized.beats[0].selected_histogram.length, 2)
  assert.equal(normalized.beats[0].unused_count, 2)
  assert.equal(normalized.beats[0].classification, 'VARIABLE_BALANCED')
})

test('live and historical paths share one normalizer and produce equal objects', () => {
  const payload = representativePayload()
  const live = normalizeCoverageDiagnostics(payload)
  const planningSummary = { coverage_diagnostics: payload }
  const historical = normalizeCoverageDiagnostics(planningSummary.coverage_diagnostics)
  assert.deepEqual(live, historical)

  const root = fileURLToPath(new URL('../', import.meta.url))
  const worker = readFileSync(`${root}src/workers/queueWorker.ts`, 'utf8')
  const store = readFileSync(`${root}src/stores/useQueueStore.ts`, 'utf8')
  const queueView = readFileSync(`${root}src/views/QueueView.vue`, 'utf8')
  assert.match(worker, /normalizeCoverageDiagnostics\(payload\.coverageDiagnostics\)/)
  assert.match(store, /normalizeCoverageDiagnostics\(payload\.coverageDiagnostics\)/)
  assert.match(queueView, /normalizeCoverageDiagnostics\(summary\.coverage_diagnostics\)/)
})
```

These tests do not cover the historical merge erase path identified in RF-01.

Backend Phase 2C assertions in [test_var001_coverage_diagnostics.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_var001_coverage_diagnostics.py:336):

```python
def test_coordinator_validates_then_emits_once_before_children_and_persists_same_payload(self):
    result, _parser, payload = _balanced(_pools(4, 2, 1, 2, 2), 4)
    order = []
    persisted = []
    emitted = []
    original_validate = routes_dsl._validated_coverage_diagnostics_payload

    def validate(*args):
        order.append("validate")
        return original_validate(*args)

    def emit(_task_id, coverage_payload):
        order.append("summary")
        emitted.append(coverage_payload)

    def worker(plan, _task_id, *args, file_sid=None, **kwargs):
        order.append("child")
        resolved_sid = file_sid or args[-1]
        return _successful_child(plan, resolved_sid, kwargs)

    def persist(**kwargs):
        persisted.append(kwargs["coverage_diagnostics"])

    with (
        patch.object(
            routes_dsl,
            "_validated_coverage_diagnostics_payload",
            side_effect=validate,
        ),
        patch.object(
            routes_dsl,
            "_emit_balanced_coverage_summary",
            side_effect=emit,
        ) as summary,
    ):
        terminal, worker_mock, _persist = _run_balanced_coordinator(
            payload,
            result,
            worker_side_effect=worker,
            persist_side_effect=persist,
        )

    self.assertEqual(order[:3], ["validate", "summary", "child"])
    summary.assert_called_once()
    self.assertEqual(worker_mock.call_count, 4)
    self.assertEqual(len(emitted), 1)
    self.assertIs(emitted[0], persisted[0])
    self.assertEqual(emitted[0], _payload_for(result))
    self.assertIs(terminal["coverageDiagnostics"], emitted[0])
```

Validation-failure absence:

```python
def test_coordinator_digest_mismatch_is_hard_and_emits_nothing(self):
    result, _parser, payload = _balanced(_pools(2), 2)
    bad_diagnostics = replace(
        result.coverage_diagnostics,
        accepted_fingerprint_digests=("0" * 64,) * 2,
    )
    bad_result = replace(result, coverage_diagnostics=bad_diagnostics)
    with patch.object(
        routes_dsl, "_emit_balanced_coverage_summary"
    ) as summary:
        terminal, worker, _persist = _run_balanced_coordinator(payload, bad_result)

    summary.assert_not_called()
    worker.assert_not_called()
    self.assertEqual(terminal["plannedCount"], 0)
    self.assertIn("VARIANT_PLANNING_FAILED", terminal["warningCodes"])
    self.assertNotIn("coverageDiagnostics", terminal)
```

Identity-failure absence:

```python
def test_coordinator_contract_identity_mismatch_is_hard(self):
    result, _parser, payload = _balanced(_pools(2), 2)
    invalid_fields = (
        {"diagnostics_type": "invalid_type"},
        {"version": 999},
        {"variant_planning_policy": "exact_main_visual"},
    )

    for replacement in invalid_fields:
        with self.subTest(replacement=replacement):
            bad_diagnostics = replace(
                result.coverage_diagnostics,
                **replacement,
            )
            bad_result = replace(
                result,
                coverage_diagnostics=bad_diagnostics,
            )
            with patch.object(
                routes_dsl,
                "_emit_balanced_coverage_summary",
            ) as summary:
                terminal, worker, _persist = _run_balanced_coordinator(
                    payload,
                    bad_result,
                )

            summary.assert_not_called()
            worker.assert_not_called()
            self.assertEqual(terminal["plannedCount"], 0)
            self.assertIn(
                "VARIANT_PLANNING_FAILED",
                terminal["warningCodes"],
            )
            self.assertNotIn("coverageDiagnostics", terminal)
```

Planning/render count separation:

```python
def test_planning_accepted_count_survives_one_render_failure(self):
    result, _parser, payload = _balanced(_pools(4, 2), 4)
    persisted = []

    def worker(plan, _task_id, *args, file_sid=None, **kwargs):
        resolved_sid = file_sid or args[-1]
        if kwargs["child_index"] == 3:
            return _failed_child(plan, resolved_sid, kwargs)
        return _successful_child(plan, resolved_sid, kwargs)

    terminal, _worker, _persist = _run_balanced_coordinator(
        payload,
        result,
        worker_side_effect=worker,
        persist_side_effect=lambda **kwargs: persisted.append(
            kwargs["coverage_diagnostics"]
        ),
    )
    self.assertEqual(terminal["succeededCount"], 3)
    self.assertEqual(terminal["coverageDiagnostics"]["accepted_count"], 4)
    self.assertEqual(persisted[0]["accepted_count"], 4)
```

Exact and legacy absence:

```python
def test_exact_and_legacy_do_not_emit_or_persist_coverage(self):
    pools = _pools(2)
    payload = _payload(pools)
    exact_result = routes_dsl._plan_exact_main_visual_variants(
        _SyntheticParser(pools), payload, 2
    )
    self.assertIsNone(exact_result.coverage_diagnostics)

    persisted = []

    def worker(plan, _task_id, *args, file_sid=None, **kwargs):
        resolved_sid = file_sid or args[-1]
        return _successful_child(plan, resolved_sid, kwargs)

    with (
        patch.object(
            routes_dsl,
            "_plan_exact_main_visual_variants_from_db",
            return_value=exact_result,
        ),
        patch.object(routes_dsl, "render_worker", side_effect=worker),
        patch.object(
            routes_dsl,
            "_persist_task_history",
            side_effect=lambda **kwargs: persisted.append(kwargs),
        ),
        patch.object(routes_dsl, "_emit_balanced_coverage_summary") as summary,
        patch.object(routes_dsl.ws_manager, "broadcast_sync"),
    ):
        exact_terminal = routes_dsl.render_batch_worker(
            payload,
            "exact-task",
            batch_size=2,
            variant_planning_policy="exact_main_visual",
        )
    summary.assert_not_called()
    self.assertIsNone(persisted[0]["coverage_diagnostics"])
    self.assertNotIn("coverageDiagnostics", exact_terminal)

    persisted.clear()
    resolved = _plan_for_selections(payload, (pools[0][0],))
    with (
        patch.object(routes_dsl, "render_worker", side_effect=worker),
        patch.object(
            routes_dsl,
            "_persist_task_history",
            side_effect=lambda **kwargs: persisted.append(kwargs),
        ),
        patch.object(routes_dsl, "_emit_balanced_coverage_summary") as summary,
        patch.object(routes_dsl.ws_manager, "broadcast_sync"),
    ):
        legacy_terminal = routes_dsl.render_batch_worker(
            payload,
            "legacy-task",
            batch_size=1,
            resolved_plan=resolved,
            variant_planning_policy="legacy",
        )
    summary.assert_not_called()
    self.assertIsNone(persisted[0]["coverage_diagnostics"])
    self.assertNotIn("coverageDiagnostics", legacy_terminal)
```

The backend tests do not cover an exception occurring after successful validation but before completion of the authoritative coordinator block.

## J. Production Diff

Backend:

```diff
diff --git a/src/api/routes_dsl.py b/src/api/routes_dsl.py
@@
     if all_assets:
         terminal_payload["assets"] = all_assets
+    if coverage_diagnostics_payload is not None:
+        terminal_payload["coverageDiagnostics"] = coverage_diagnostics_payload
```

Worker:

```diff
+import {
+  normalizeCoverageDiagnostics,
+  type CoverageDiagnosticsV1,
+} from '../utils/coverageDiagnostics'
...
+  coverageDiagnostics?: CoverageDiagnosticsV1
...
+  coverageDiagnostics?: unknown
...
+  const coverageDiagnostics = normalizeCoverageDiagnostics(payload.coverageDiagnostics)
...
+      coverageDiagnostics,
...
+    if (coverageDiagnostics) existing.coverageDiagnostics = coverageDiagnostics
```

Store:

```diff
+import { normalizeCoverageDiagnostics } from '../utils/coverageDiagnostics'
...
+    const coverageDiagnostics = normalizeCoverageDiagnostics(payload.coverageDiagnostics)
...
+      if (coverageDiagnostics) existing.coverageDiagnostics = coverageDiagnostics
...
+        coverageDiagnostics,
```

Historical hydration:

```diff
+import { normalizeCoverageDiagnostics } from '../utils/coverageDiagnostics'
...
+  const coverageDiagnostics = normalizeCoverageDiagnostics(summary.coverage_diagnostics)
...
+    coverageDiagnostics,
```

The untracked utility produces no ordinary `git diff`; its complete current source is captured in section C.

No QueueView template hunk changed.

## K. Final Answers

1. Can any live WS path drop a valid coverage payload?

   Direct `WS_UPDATE` handling: **No**. Absent or invalid diagnostics do not overwrite an existing valid value.

   Subsequent historical hydration/`INIT_TASKS`: **Yes**, through RF-01.

2. Can any store update erase previously valid coverage because the next update omits the field?

   **Yes.** Historical hydration can construct `coverageDiagnostics: undefined`, overwrite the live field through object spread, and replace the worker/store snapshot.

3. Do live and historical tasks end with the same `QueueTask.coverageDiagnostics` type?

   **Yes, when valid and present:** `CoverageDiagnosticsV1`. Old/malformed records produce `undefined`.

4. Does frontend recompute any backend coverage math?

   **No.**

5. Does the normalizer mutate source data?

   **No.** It constructs detached objects and arrays.

6. Does the QueueView template expose any Coverage UI?

   **No.**

7. Did Phase 2C modify Phase 2B persistence semantics?

   **No.**

8. Did Phase 2C modify planner behavior?

   **No.**

Review findings:

```text
VAR2C-RF-01
COVERAGE_DIAGNOSTICS_CAN_BE_ERASED_BY_ABSENT_UPDATE

VAR2C-RF-02
COVERAGE_DIAGNOSTICS_SURVIVES_POST_VALIDATION_COORDINATOR_FAILURE
```