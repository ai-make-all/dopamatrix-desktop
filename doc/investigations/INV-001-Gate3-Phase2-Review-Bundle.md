# INV-001 Gate 3 Phase 2 — Targeted Code Review Bundle

## 1. Baseline

```text
branch: fix/creative-duplicate-detection
HEAD:   96eb6ee9399aff19aa3a74fa8ca209556e76205a
```

`git status --short`：

```text
 M src/api/routes_dsl.py
 M src/nodes/compositor.py
 M tests/test_inv001_execution_isolation.py
?? doc/investigations/Batch-Finalization-Report.md
?? tests/test_inv001_batch_finalization.py
```

Phase 2 尚未 commit。

`git diff --stat`：

```text
 src/api/routes_dsl.py                    | 552 +++++++++++++++++--------------
 src/nodes/compositor.py                  |  20 +-
 tests/test_inv001_execution_isolation.py |  80 ++++-
 3 files changed, 385 insertions(+), 267 deletions(-)
```

注意：未跟踪的 `tests/test_inv001_batch_finalization.py` 和 investigation report 不计入 `git diff --stat`。

---

## 2. Child Result Contract

### A1 — `_ChildResult`

[src/api/routes_dsl.py:138](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:138)

```python
@dataclass(frozen=True)
class _ChildResult:
    """Internal result envelope returned by one child render execution."""

    child_index: int
    execution_id: str
    file_sid: str
    outcome: str
    assets: list[dict]
    elapsed: float
    error_code: Optional[str]
    error_message: Optional[str]
    prompt_details: dict[str, Any]

    @property
    def succeeded(self) -> bool:
        return self.outcome == "succeeded" and bool(self.assets)
```

Code fact：

- Child identity、outcome、assets、elapsed、错误摘要和 history snapshot 被绑定在一个 immutable envelope 中。
- `outcome="succeeded"` 但没有资产时，`succeeded` 仍为 `False`。

### A2 — `render_worker` signature

[src/api/routes_dsl.py:239](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:239)

```python
def render_worker(
    plan: Optional[CompilationPlan],
    task_id: str,
    aspect_ratio: str = "9:16",
    target_duration: int = 15,
    tenant_id: str = "default",
    prompt: Optional[str] = None,
    batch_size: int = 1,
    test_language: str = "en",
    file_sid: Optional[str] = None,
    *,
    execution_id: str,
    child_index: int,
    blind_dsl: bool = False,
    engine_type: str = "content",
    director_mode: str = "auto",
    dsl_payload: Optional[StoryDSLPayload] = None,
    enable_tts: bool = True,
    enable_subtitles: bool = True,
) -> _ChildResult:
```

### A3 — Result factory and normal success

[src/api/routes_dsl.py:287](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:287)

```python
collected_assets: list[dict] = []
_start_time: float = time.time()
working_plan: Optional[CompilationPlan] = plan

def _result(
    outcome: str,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> _ChildResult:
    return _ChildResult(
        child_index=child_index,
        execution_id=execution_id,
        file_sid=resolved_file_sid,
        outcome=outcome,
        assets=[dict(asset) for asset in collected_assets],
        elapsed=round(time.time() - _start_time, 3),
        error_code=error_code,
        error_message=(error_message[:500] if error_message else None),
        prompt_details=_child_prompt_details(dsl_payload, working_plan),
    )
```

[src/api/routes_dsl.py:654](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:654)

```python
if render_ok and collected_assets:
    return _result("succeeded")
if not render_ok:
    return _result("failed", "RENDER_FAILED", "compositor did not complete")
return _result("failed", "NO_FINAL_OUTPUT", "render produced no final output")
```

### A4 — Failure and early-return mapping

| Condition | Result |
|---|---|
| Blind prompt missing | `BLIND_PROMPT_MISSING` |
| Blind timeline empty | `BLIND_TIMELINE_EMPTY` |
| Blind/non-Blind zero resolved beats | `PLAN_UNRESOLVED` |
| No DSL and no plan | `PLAN_MISSING` |
| Compiled timeline empty | `TIMELINE_EMPTY` |
| No layer-0 main visual | `MAIN_VISUAL_MISSING` |
| Compositor returns failure | `RENDER_FAILED` |
| Render succeeds but no final assets | `NO_FINAL_OUTPUT` |
| TTS/subtitle/render or other exception | `CHILD_EXCEPTION` |

Representative resolver/timeline paths:

```python
if working_plan.summary.resolved_beats == 0:
    return _result("failed", "PLAN_UNRESOLVED", "DSL resolved no beats")
elif plan is not None:
    working_plan = plan
else:
    return _result("failed", "PLAN_MISSING", "no CompilationPlan or DSL payload")

timeline = compile_plan_to_timeline(
    working_plan, target_duration=target_duration,
)
if not timeline.tracks:
    return _result(
        "failed",
        "TIMELINE_EMPTY",
        "main video timeline is empty",
    )
```

Visual precheck:

```python
if _valid_main_clips == 0:
    return _result(
        "failed",
        "MAIN_VISUAL_MISSING",
        "no valid layer-0 main visual clips",
    )
```

Generic exception:

```python
except Exception as exc:
    logger.exception(...)
    return _result("failed", "CHILD_EXCEPTION", str(exc))
```

Compositor exceptions are normalized first:

[src/api/routes_dsl.py:929](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:929)

```python
try:
    compositor.execute(context)
    return True
except Exception:
    logger.exception(...)
    return False
```

Result：

- Worker main `try` 内未发现 `return []`、`return None` 或 uncaught `Exception`。
- TTS、Subtitle、timeline、render generic exceptions 均进入 `CHILD_EXCEPTION` 或 `RENDER_FAILED`。
- Phase 1 identity validation 位于 worker `try` 之前，非法 direct call 会 fail-fast；但 coordinator 的 `_execute_child` 会捕获该异常并转为 `_ChildResult(CHILD_EXCEPTION)`。正常 coordinator-created child 不会丢失 result contract。

---

## 3. Single-Child Finalization

三个生产入口均提交 `render_batch_worker`：

- `submit_dsl`：[routes_dsl.py:1200](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1200)
- `submit_manual`：[routes_dsl.py:1302](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1302)
- `render_dsl`：[routes_dsl.py:1428](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1428)

```python
background_tasks.add_task(
    render_batch_worker,
    dsl_payload_for_worker,
    task_id,
    ...
)
```

Manual 路径同样进入 coordinator，并携带现有 preview plan：

```python
background_tasks.add_task(
    render_batch_worker,
    dsl_payload,
    task_id,
    ...
    **{**worker_kwargs, "resolved_plan": plan},
)
```

Single-child 分支：

[src/api/routes_dsl.py:825](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:825)

```python
if batch_size == 1:
    child_results.append(_execute_child(child_executions[0]))
else:
    ...
```

该分支之后没有提前返回，继续执行共同的：

```text
sort
→ aggregate
→ TaskHistory persistence
→ terminal payload
→ one WS broadcast
```

没有第二套 single-child TaskHistory 或 terminal WS logic。

---

## 4. Batch Result Collection

[src/api/routes_dsl.py:782](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:782)

```python
child_executions = _create_child_executions(task_id, batch_size)
child_results: list[_ChildResult] = []

def _execute_child(child: _ChildExecution) -> _ChildResult:
    child_start = time.time()
    try:
        result = render_worker(
            None if blind_dsl else resolved_plan,
            task_id,
            aspect_ratio, target_duration, tenant_id,
            prompt, batch_size, test_language,
            child.file_sid,
            execution_id=child.execution_id,
            child_index=child.child_index,
            ...
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
        return _failed_child_result(
            child,
            "CHILD_EXCEPTION",
            str(exc),
            time.time() - child_start,
        )
```

Concurrent branch：

```python
with ThreadPoolExecutor(max_workers=batch_size) as pool:
    future_map = {
        pool.submit(_execute_child, child): child
        for child in child_executions
    }
    for future in as_completed(future_map):
        child = future_map[future]
        try:
            child_results.append(future.result())
        except Exception as exc:
            child_results.append(
                _failed_child_result(
                    child,
                    "CHILD_FUTURE_FAILED",
                    str(exc),
                )
            )
```

Future-level exception 会保留原始：

- `child_index`
- `execution_id`
- `file_sid`

并转换为 `CHILD_FUTURE_FAILED`。它不会从 coordinator 直接逃逸。

---

## 5. Stable Aggregation

[src/api/routes_dsl.py:847](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:847)

```python
child_results.sort(key=lambda result: result.child_index)

successful_results = [
    result for result in child_results if result.succeeded
]
all_assets = [
    dict(asset)
    for result in successful_results
    for asset in result.assets
]

succeeded_count = len(successful_results)
failed_count = len(child_results) - succeeded_count
partial = 0 < succeeded_count < len(child_results)
warning_codes = ["CHILD_EXECUTION_FAILED"] if failed_count else []
```

Final status：

```python
final_status = "completed" if succeeded_count else "failed"
```

因此 `as_completed` 的线程完成顺序不会改变：

- `children` 顺序
- history `output_assets` 顺序
- terminal `assets` 顺序

---

## 6. TaskHistory Persistence

### Coordinator persistence

[src/api/routes_dsl.py:695](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:695)

```python
def _persist_task_history(
    *,
    task_id: str,
    tenant_id: str,
    prompt: Optional[str],
    batch_size: int,
    elapsed: float,
    child_results: list[_ChildResult],
    output_assets: list[dict],
    warning_codes: list[str],
) -> None:
    first_success = next(
        result for result in child_results if result.succeeded
    )
    legacy_details = first_success.prompt_details
    ...
    history_record = TaskHistory(
        task_id=task_id,
        prompt=prompt or "",
        batch_size=batch_size,
        duration=round(elapsed, 1),
        output_assets=output_assets,
        prompt_details=json.dumps(prompt_details, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    history_engine = get_tenant_engine(tenant_id)
    HistorySession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=history_engine,
    )
    with HistorySession() as db:
        db.add(history_record)
        db.commit()
```

### Search result

```text
src/api/models.py:131:class TaskHistory(Base):
src/api/routes_dsl.py:733:    history_record = TaskHistory(
src/api/services.py:262:            history_record = TaskHistory(
```

Classification：

| Location | Classification |
|---|---|
| `models.py:131` | Model declaration，不是 INSERT |
| `routes_dsl.py:733` | A — Phase 2 coordinator persistence |
| `services.py:262` | B — legacy Matrix `run_matrix_job` aggregate history |
| Unexpected duplicate path | None |

旧 Matrix 路径本身只构造一条 aggregate history：

```python
if history_assets:
    history_record = TaskHistory(
        task_id=session_id,
        prompt=prompt,
        batch_size=batch_size,
        duration=real_duration,
        output_assets=history_assets,
        created_at=_now(),
    )
    db.add(history_record)
```

未发现 C 类 unexpected duplicate write。

---

## 7. `prompt_details` Compatibility

[src/api/routes_dsl.py:707](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:707)

```python
first_success = next(
    result for result in child_results if result.succeeded
)
legacy_details = first_success.prompt_details
prompt_details: dict[str, Any] = {
    "meta": legacy_details.get("meta"),
    "timeline": legacy_details.get("timeline") or [],
    "planning_summary": {
        "requested_count": batch_size,
        "planned_count": len(child_results),
        "succeeded_count": sum(
            result.succeeded for result in child_results
        ),
        "failed_count": sum(
            not result.succeeded for result in child_results
        ),
        "warning_codes": list(warning_codes),
    },
    "children": [
        {
            "child_index": result.child_index,
            "execution_id": result.execution_id,
            "file_sid": result.file_sid,
            "outcome": (
                "succeeded" if result.succeeded else "failed"
            ),
            "elapsed": result.elapsed,
            "error_code": result.error_code,
            "output_assets": [
                dict(asset) for asset in result.assets
            ],
            "timeline": (
                result.prompt_details.get("timeline") or []
            ),
        }
        for result in child_results
    ],
}
```

Answers：

1. Legacy `timeline` 来自按 `child_index` 排序后的第一个 successful child。
2. 如果 child 0 失败、child 1 成功，legacy timeline 来自 child 1。
3. 所有值 JSON-safe：**NOT PROVEN**。正常 schema 字段、IDs、paths、counts 都是 primitive/list/dict；但 `ResolvedLayer.manifest` 和通用 asset dict 的嵌套值没有在该函数内做 JSON-safe validation。`json.dumps` 失败会进入 history failure isolation。
4. `execution_id`、`file_sid` 已在 `_ChildResult` 中保存为 `str`，直接写入 JSON。
5. 没有写入 traceback 或 `Exception` object。Persisted child error metadata 只有 `error_code`；`error_message` 不进入 history。
6. 不保存 `WorkflowContext` 或 compiled runtime `Timeline` object。保存的是 `BeatCompilationResult.model_dump()` 产生的 plan snapshot。

Legacy snapshot 构造：

```python
return {
    "meta": meta,
    "timeline": [
        beat.model_dump()
        for beat in (
            working_plan.beats
            if working_plan is not None
            else []
        )
    ],
}
```

---

## 8. History Failure Isolation

[src/api/routes_dsl.py:868](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:868)

```python
history_persisted = False
elapsed = time.time() - batch_start

if succeeded_count:
    try:
        _persist_task_history(...)
        history_persisted = True
    except Exception:
        warning_codes.append("HISTORY_PERSIST_FAILED")
        logger.exception(
            "[render_batch_worker] 历史记录写入失败 "
            "task_id=%s；保留渲染结果",
            task_id,
        )

final_status = "completed" if succeeded_count else "failed"
```

History exception 被局部捕获，之后仍继续：

```text
terminal payload construction
→ terminal broadcast
→ return terminal payload
```

因此：

- 成功 render 不会被重新定义为 render failure。
- `historyPersisted=false`。
- `warningCodes` 增加 `HISTORY_PERSIST_FAILED`。
- 已生成 assets 保留。
- 不重新 render，也不删除输出。

---

## 9. Terminal WS Global Audit

### A — Coordinator terminal owner

[src/api/routes_dsl.py:910](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:910)

```python
ws_manager.broadcast_sync(
    {"type": "WS_UPDATE", "payload": terminal_payload},
    user_id=tenant_id,
)
```

这是当前 `routes_dsl` submitted-task 主链唯一 terminal emit。

### C — Child running/progress only

Master progress：

```python
self._ws_broadcast(
    task_id,
    user_id,
    {"status": "running", "progress": pct},
)
```

Variant progress：

```python
self._ws_broadcast(
    task_id,
    user_id,
    {"status": "running", "progress": pct, "lang": lang},
)
```

位置：

- [compositor.py:779](/E:/dopaworkspace/dopamatrix-desktop/src/nodes/compositor.py:779)
- [compositor.py:1051](/E:/dopaworkspace/dopamatrix-desktop/src/nodes/compositor.py:1051)

### B — Legacy/direct-call failed terminal

[compositor.py:794](/E:/dopaworkspace/dopamatrix-desktop/src/nodes/compositor.py:794)

```python
except FileNotFoundError:
    if not self._coordinator_owns_terminal(context):
        self._ws_broadcast(
            task_id, user_id, {"status": "failed"}
        )
```

```python
except subprocess.CalledProcessError as exc:
    if not self._coordinator_owns_terminal(context):
        self._ws_broadcast(
            task_id, user_id, {"status": "failed"}
        )
    ...
    raise RuntimeError(...)
```

```python
try:
    self._render_variant(context, output_path, ffmpeg_bin)
except Exception:
    if not self._coordinator_owns_terminal(context):
        self._ws_broadcast(
            task_id, user_id, {"status": "failed"}
        )
    raise
```

### Separate legacy/service paths

`src/api/services.py` 的 old Matrix job 仍拥有自己的：

- running at line 146
- completed at line 294
- failed at line 322

它不调用 `routes_dsl.render_worker`，属于独立 legacy pipeline。

`src/api/routes_ws.py:250` 还存在 `[STRESS_TEST]` synthetic completed event，不属于视频 render child 主链。

### D — Unexpected coordinator-child terminal leak

未发现。

---

## 10. Coordinator Marker

Marker 写入：

[src/api/routes_dsl.py:418](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:418)

```python
context = WorkflowContext(
    session_id=task_id,
    ...
)
...
context.config["execution_id"] = execution_id
context.config["file_sid"] = resolved_file_sid
context.config["child_index"] = child_index
context.config["ws_terminal_managed_by_coordinator"] = True
```

Marker 读取：

[src/nodes/compositor.py:138](/E:/dopaworkspace/dopamatrix-desktop/src/nodes/compositor.py:138)

```python
@staticmethod
def _coordinator_owns_terminal(
    context: WorkflowContext,
) -> bool:
    return (
        context.config.get(
            "ws_terminal_managed_by_coordinator"
        )
        is True
    )
```

结论：

- 所有 new `routes_dsl.render_worker` child 在 compositor 执行前都设置 marker。
- Missing-FFmpeg、master process failure、variant failure 三条 failed branch 都读取同一 marker。
- Legacy direct-call context 不设置 marker时，返回 `False`，保持原有 failed WS 行为。

---

## 11. Final Terminal Payload

[src/api/routes_dsl.py:894](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:894)

```python
final_status = "completed" if succeeded_count else "failed"
terminal_payload: dict[str, Any] = {
    "taskId": task_id,
    "status": final_status,
    "generation_mode": director_mode,
    "partial": partial,
    "requestedCount": batch_size,
    "plannedCount": len(child_results),
    "succeededCount": succeeded_count,
    "failedCount": failed_count,
    "historyPersisted": history_persisted,
    "warningCodes": warning_codes,
}
if all_assets:
    terminal_payload["assets"] = all_assets

try:
    ws_manager.broadcast_sync(
        {"type": "WS_UPDATE", "payload": terminal_payload},
        user_id=tenant_id,
    )
except Exception:
    logger.exception(...)
```

正常 finalizer path 只有一个 `broadcast_sync` 调用点。

`assets` 在至少一个成功输出存在时加入；zero-success 时字段省略，逻辑资产数量为 0。

---

## 12. Outcome Matrix

| Case | status | partial | History row | historyPersisted | warningCodes | Assets |
|---|---|---:|---:|---:|---|---:|
| A: 4 success | `completed` | `false` | Yes, one | `true` | `[]` | 4 |
| B: 3 success + 1 failure | `completed` | `true` | Yes, one | `true` | `CHILD_EXECUTION_FAILED` | 3 |
| C: 0 success | `failed` | `false` | No | `false` | `CHILD_EXECUTION_FAILED` | 0; field omitted |
| D: 3 success + 1 failure + history commit failure | `completed` | `true` | No committed row | `false` | `CHILD_EXECUTION_FAILED`, `HISTORY_PERSIST_FAILED` | 3 |

---

## 13. Critical Test Evidence

Test file：[tests/test_inv001_batch_finalization.py](/E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_batch_finalization.py)

### Test boundary

T1/T2/T4/T5/T9 directly call production `render_batch_worker` and use a real in-memory SQLite `TaskHistory` table, but mock `render_worker`:

```python
patch.object(
    routes_dsl,
    "render_worker",
    side_effect=fake_render_worker,
),
patch.object(
    routes_dsl,
    "get_tenant_engine",
    return_value=self.engine,
),
...
terminal = routes_dsl.render_batch_worker(
    None,
    task_id,
    prompt="test prompt",
    batch_size=batch_size,
)
```

### T1 — batch_size=1

```python
self.assertEqual(len(calls), 1)
self.assertEqual(calls[0]["task_id"], "phase2-single")
self.assertEqual(len(rows), 1)
self.assertEqual(rows[0].task_id, "phase2-single")
self.assertEqual(rows[0].batch_size, 1)
self.assertEqual(terminal["status"], "completed")
self.assertFalse(terminal["partial"])
self.assertEqual(ws.call_count, 1)
```

### T2 — batch_size=4

```python
self.assertEqual(len(calls), 4)
self.assertEqual(
    {call["task_id"] for call in calls},
    {"phase2-four"},
)
self.assertEqual(len(rows), 1)
self.assertEqual(rows[0].task_id, "phase2-four")
self.assertEqual(rows[0].batch_size, 4)
self.assertEqual(
    [asset["file_path"] for asset in rows[0].output_assets],
    [
        "final_0.mp4",
        "final_1.mp4",
        "final_2.mp4",
        "final_3.mp4",
    ],
)
self.assertEqual(ws.call_count, 1)
self.assertEqual(
    ws.call_args.args[0]["payload"]["status"],
    "completed",
)
```

### T4 — Partial child failure

```python
failed_indices={0},
...
self.assertEqual(len(rows), 1)
self.assertEqual(
    [asset["file_path"] for asset in rows[0].output_assets],
    ["final_1.mp4", "final_2.mp4", "final_3.mp4"],
)
self.assertEqual(details["meta"], {"source_child": 1})
self.assertEqual(
    details["timeline"],
    [{"beat": "Beat-1"}],
)
self.assertEqual(terminal["status"], "completed")
self.assertTrue(terminal["partial"])
self.assertEqual(terminal["succeededCount"], 3)
self.assertEqual(terminal["failedCount"], 1)
self.assertEqual(ws.call_count, 1)
```

### T5 — All failed

```python
self.assertEqual(self._history_rows(), [])
self.assertEqual(terminal["status"], "failed")
self.assertFalse(terminal["partial"])
self.assertEqual(terminal["succeededCount"], 0)
self.assertEqual(terminal["failedCount"], 4)
self.assertEqual(ws.call_count, 1)
```

### T6 — History persistence failure

This directly calls production coordinator, with persistence helper forced to raise:

```python
patch.object(
    routes_dsl,
    "_persist_task_history",
    side_effect=RuntimeError("commit failed"),
),
...
terminal = routes_dsl.render_batch_worker(
    None,
    "phase2-history-failure",
    batch_size=1,
)

self.assertEqual(terminal["status"], "completed")
self.assertFalse(terminal["historyPersisted"])
self.assertIn(
    "HISTORY_PERSIST_FAILED",
    terminal["warningCodes"],
)
self.assertEqual(terminal["succeededCount"], 1)
self.assertEqual(ws.call_count, 1)
```

### T8 — Worker/compositor terminal suppression

Actual production worker boundary:

```python
result = routes_dsl.render_worker(
    plan,
    task_id,
    file_sid=child.file_sid,
    execution_id=child.execution_id,
    child_index=child.child_index,
)

self.assertTrue(result.succeeded)
task_history.assert_not_called()
ws.assert_not_called()
```

Actual compositor failed branch:

```python
context.config[
    "ws_terminal_managed_by_coordinator"
] = True
...
node.execute(context)

statuses = [
    call.args[2]["status"]
    for call in broadcasts.call_args_list
]
self.assertEqual(statuses, ["running"])
```

Separate tests cover:

- missing FFmpeg
- master process failure
- variant failure
- legacy failed-event preservation

### T9 — Reverse completion ordering

```python
def reverse_completion(futures):
    completed = list(futures)
    return iter(
        sorted(
            completed,
            key=lambda future: (
                future.result().child_index
            ),
            reverse=True,
        )
    )

...
self.assertEqual(
    [
        child["child_index"]
        for child in details["children"]
    ],
    [0, 1, 2, 3],
)
self.assertEqual(
    [
        asset["file_path"]
        for asset in terminal["assets"]
    ],
    [
        "final_0.mp4",
        "final_1.mp4",
        "final_2.mp4",
        "final_3.mp4",
    ],
)
```

### T10 — Blind compatibility

This calls production coordinator and production worker; Director, resolver and external render effects are mocked:

```python
terminal = routes_dsl.render_batch_worker(
    None,
    "phase2-blind",
    prompt="blind prompt",
    batch_size=1,
    blind_dsl=True,
    enable_tts=False,
    enable_subtitles=False,
)

director.draft_blueprint.assert_called_once()
self.assertEqual(
    db.query(TaskHistory).count(),
    1,
)
self.assertEqual(terminal["status"], "completed")
self.assertEqual(ws.call_count, 1)
```

### T11 — Manual compatibility

Also calls production coordinator and worker:

```python
terminal = routes_dsl.render_batch_worker(
    dsl_payload,
    "phase2-manual",
    batch_size=1,
    blind_dsl=False,
    resolved_plan=plan,
)

parse_plan.assert_called_once_with(
    "default",
    dsl_payload,
)
director.assert_not_called()
self.assertEqual(
    db.query(TaskHistory).count(),
    1,
)
self.assertEqual(terminal["status"], "completed")
self.assertEqual(ws.call_count, 1)
```

---

## 14. Call-Site Audit

Production definitions/calls:

```text
src/api/routes_dsl.py:239   def render_worker(
src/api/routes_dsl.py:753   def render_batch_worker(
src/api/routes_dsl.py:788       result = render_worker(
src/api/routes_dsl.py:1201      render_batch_worker,
src/api/routes_dsl.py:1303      render_batch_worker,
src/api/routes_dsl.py:1429      render_batch_worker,
```

Classification：

| Caller | Coordinator |
|---|---|
| `submit_dsl` | Yes |
| `submit_manual` | Yes |
| `render_dsl` | Yes |
| Production direct `render_worker` caller | Only nested coordinator `_execute_child` |
| Other production caller | None found |

Blind and non-Blind are selected through coordinator arguments; neither bypasses finalization.

---

## 15. Scope Audit

| Area | Result |
|---|---|
| Candidate resolver | UNCHANGED |
| `random.choice` | UNCHANGED |
| `_score_candidates` | UNCHANGED |
| CompilationPlan generation | UNCHANGED; only `working_plan` snapshot retention/result plumbing changed |
| `usage_count` algorithm | UNCHANGED |
| Variant Planner | UNCHANGED / NOT IMPLEMENTED |
| Fingerprint | UNCHANGED / NOT IMPLEMENTED |
| Diversity | UNCHANGED / NOT IMPLEMENTED |
| BGM resolution/merge | UNCHANGED |
| TTS identity | UNCHANGED |
| Subtitle identity | UNCHANGED |
| Frontend | UNCHANGED |
| Manual diversity semantics | UNCHANGED |
| Blind diversity semantics | UNCHANGED |
| DB schema/migrations | UNCHANGED |

Changed production behavior is limited to：

- `_ChildResult` return contract
- coordinator aggregation/finalization
- one TaskHistory write
- terminal WS ownership
- compositor child terminal suppression

Known `schemas.py` batch-size description debt remains unchanged.

---

## 16. Review Findings

**NONE**

Non-blocking evidence qualification：`prompt_details` complete JSON safety is **NOT PROVEN** for arbitrary nested `manifest`/asset dictionaries; persistence failure is isolated by the implemented finalizer contract.

---

## 17. Test Results

### Focused INV-001 suite

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

Result：

```text
Ran 39 tests in 0.420s

OK
```

Observed non-failing warning：

```text
DeprecationWarning: datetime.datetime.utcnow() is deprecated
```

### Compile check

```powershell
.\venv_build\Scripts\python.exe -m py_compile src/api/routes_dsl.py src/nodes/compositor.py tests/test_inv001_batch_finalization.py tests/test_inv001_execution_isolation.py tests/test_inv001_execution_paths.py
```

Result：PASS.

### Diff quality

```powershell
git diff --check
```

Result：PASS；没有 whitespace errors。Git 仅报告 tracked Python files 下一次写入时可能发生 LF → CRLF 转换。

---

## 18. Final Git Status

```text
 M src/api/routes_dsl.py
 M src/nodes/compositor.py
 M tests/test_inv001_execution_isolation.py
?? doc/investigations/Batch-Finalization-Report.md
?? tests/test_inv001_batch_finalization.py
```

本轮未修改文件、未 commit、未 push、未进入 Phase 3。