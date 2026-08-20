# INV-001 Gate 3 Phase 1 — Code Review Bundle

## 1. Git Baseline

```powershell
git rev-parse HEAD
```

```text
9c03d81391e1b253aef7fe0eaf166efa8d7c228e
```

Branch：

```text
fix/creative-duplicate-detection
```

```powershell
git status --short
```

```text
 M src/api/routes_dsl.py
 M src/nodes/compositor.py
 M src/nodes/cover_node.py
 M src/nodes/subtitle.py
 M src/nodes/tts_node.py
?? doc/investigations/INV-001-Gate2-Fix-Architecture-Plan.md
?? doc/investigations/INV-001-Gate3-Phase1-Execution-Isolation-Report.md
?? tests/test_inv001_execution_isolation.py
?? tests/test_inv001_execution_paths.py
```

```powershell
git diff --stat
```

```text
 src/api/routes_dsl.py   | 179 ++++++++++++++++++++++++++++++++++++++++--------
 src/nodes/compositor.py |  50 ++++++++++++--
 src/nodes/cover_node.py |  36 ++++++++--
 src/nodes/subtitle.py   |  41 ++++++++++-
 src/nodes/tts_node.py   |  37 ++++++++--
 5 files changed, 296 insertions(+), 47 deletions(-)
```

结论：

- Phase 1 尚未 commit。
- 两个测试文件未跟踪，因此普通 `git diff --stat` 不会列出它们。
- 两个 investigation 文档不属于本次指定的七文件 implementation review scope，未纳入以下 diff 审查。

## 2. Child Identity Creation

来源：[routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:129)

```python
@dataclass(frozen=True)
class _ChildExecution:
    """Internal identity envelope for one submitted render execution."""

    child_index: int
    execution_id: str
    file_sid: str


def _create_child_executions(task_id: str, child_count: int) -> list[_ChildExecution]:
    """Create child identities while keeping ``task_id`` as the batch identity."""
    if child_count < 1:
        raise ValueError("child_count must be at least 1")

    children: list[_ChildExecution] = []
    used_execution_ids: set[str] = set()
    used_file_sids: set[str] = set()

    for child_index in range(child_count):
        for _attempt in range(100):
            execution_uuid = uuid.uuid4()
            execution_id = str(execution_uuid)
            file_sid = execution_uuid.hex[:8]
            if (
                execution_id != task_id
                and execution_id not in used_execution_ids
                and file_sid not in used_file_sids
            ):
                break
        else:
            raise RuntimeError("unable to allocate a unique child execution identity")

        used_execution_ids.add(execution_id)
        used_file_sids.add(file_sid)
        children.append(
            _ChildExecution(
                child_index=child_index,
                execution_id=execution_id,
                file_sid=file_sid,
            )
        )

    return children
```

代码事实：

- `execution_id` 来自新的 `uuid.uuid4()`，并以带连字符的完整 UUID 字符串保存。
- `file_sid = execution_uuid.hex[:8]`，直接由同一个 execution UUID 派生。
- `used_execution_ids` 和 `used_file_sids` 都是当前 helper 调用生命周期内的 batch-local set。
- UUID 或 8 字符 token 碰撞时重新生成，单个 child 最多尝试 100 次。
- `child_index` 由 `range(child_count)` 分配，为零起始索引。
- `execution_id == task_id` 会被拒绝。
- helper 每次调用重新执行 `uuid.uuid4()`，因此 rerun 自然获得新的 execution ID。

batch=1 也使用相同 helper：

```python
child_execution = _create_child_executions(task_id, 1)[0]
```

该代码在三个 single-child dispatch 分支中出现：

- AI Draft / Blind `submit_dsl`：line 1104
- Manual `submit_manual`：line 1224
- `render_dsl`：line 1366

没有单独的 `task_id[:8]` 单任务规则。

## 3. Dispatch and Call-Site Audit

### Batch dispatch

来源：[routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:713)

```python
child_executions = _create_child_executions(task_id, batch_size)
all_assets: list[dict] = []

with ThreadPoolExecutor(max_workers=batch_size) as pool:
    future_map = {
        pool.submit(
            render_worker,
            None if blind_dsl else resolved_plan,
            task_id,
            aspect_ratio, target_duration, tenant_id,
            prompt, batch_size, test_language,
            child.file_sid,
            True,
            execution_id=child.execution_id,
            child_index=child.child_index,
            blind_dsl=blind_dsl,
            engine_type=engine_type,
            director_mode=director_mode,
            dsl_payload=None if blind_dsl else dsl_payload,
            enable_tts=enable_tts,
            enable_subtitles=enable_subtitles,
        ): child
        for child in child_executions
    }
```

`render_worker` 实际收到：

- `task_id`：共享 batch identity。
- `execution_id`：完整 child UUID。
- `file_sid`：由该 UUID 派生的短 token。
- `child_index`：零起始 child index。

### Single-child dispatch

AI Draft / Blind：

```python
child_execution = _create_child_executions(task_id, 1)[0]
background_tasks.add_task(
    render_worker,
    None,
    task_id,
    payload.aspect_ratio, payload.target_duration, payload.tenant_id,
    payload.prompt, 1, payload.test_language,
    child_execution.file_sid,
    False,
    **{
        **_worker_kw,
        "dsl_payload": dsl_payload_for_worker,
        "execution_id": child_execution.execution_id,
        "child_index": child_execution.child_index,
    },
)
```

Manual 和 `render_dsl` 使用相同 identity helper 和四字段传递方式。

### 定向搜索

执行：

```powershell
rg "render_worker\(" src tests
```

结果包含：

```text
tests/test_inv001_execution_isolation.py:170: def fake_render_worker(
tests/test_inv001_execution_isolation.py:243: routes_dsl.render_worker(
tests/test_inv001_execution_isolation.py:289: routes_dsl.render_worker(
tests/test_inv001_execution_isolation.py:341: routes_dsl.render_worker(
src/api/routes_dsl.py:202:def render_worker(
```

生产 dispatch 采用 callable reference `render_worker,`，不带左括号，所以补充搜索后确认以下生产位点：

```text
src/api/routes_dsl.py:752   pool.submit(render_worker, ...)
src/api/routes_dsl.py:1106  submit_dsl BackgroundTasks
src/api/routes_dsl.py:1226  submit_manual BackgroundTasks
src/api/routes_dsl.py:1368  render_dsl BackgroundTasks
```

审计结论：

- 所有四个生产调用点均提供 `execution_id`、`file_sid`、`child_index`。
- batch 和 single-child 都保留 shared `task_id`。
- 未找到遗漏新必填 keyword-only 参数的生产调用点。
- 测试中的三个 direct worker 调用也全部提供新参数。

## 4. WorkflowContext Propagation

来源：[routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:376)

```python
context = WorkflowContext(
    session_id=task_id,
    aspect_ratio=aspect_ratio,
    target_duration=target_duration,
    tenant_id=tenant_id,
    batch_size=batch_size,
    test_language=test_language,
)
context.set_asset("timeline", timeline)

context.config["execution_id"] = execution_id
context.config["file_sid"] = resolved_file_sid
context.config["child_index"] = child_index
context.config["enable_tts"] = enable_tts
context.config["enable_subtitles"] = enable_subtitles
```

最终语义：

```text
context.session_id             = shared task_id
config["execution_id"]         = full child UUID
config["file_sid"]             = UUID-derived short token
config["child_index"]          = child index
```

定向检查确认 `routes_dsl.py` 新 API path 不再设置：

```python
context.config["session_id"] = file_sid
```

`config["session_id"]` 目前只存在于 TTS、Subtitle、Compositor、Cover 的 legacy fallback 分支，以及旧 `run_matrix_factory.py`。

## 5. Validation and Legacy Boundary

### Worker-entry validation

来源：[routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:174)

```python
def _validate_child_execution(
    *,
    task_id: str,
    execution_id: str,
    file_sid: Optional[str],
    child_index: int,
) -> str:
    if child_index < 0:
        raise ValueError("child_index must be non-negative")
    if not execution_id or execution_id == task_id:
        raise ValueError("execution_id must be present and differ from task_id")

    try:
        execution_uuid = uuid.UUID(execution_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("execution_id must be a full UUID") from exc

    expected_file_sid = execution_uuid.hex[:8]
    if file_sid != expected_file_sid:
        raise ValueError("file_sid must be derived from execution_id")
    return expected_file_sid
```

因此：

- 缺少 keyword-only `execution_id` / `child_index`：Python 调用绑定直接抛出 `TypeError`。
- 空 `execution_id`：`ValueError`。
- `execution_id == task_id`：`ValueError`。
- 非 UUID execution ID：`ValueError`。
- 缺失或错误 `file_sid`：`ValueError`。
- 负数 child index：`ValueError`。

### Validation placement

实际顺序：

```python
resolved_file_sid = _validate_child_execution(...)
logger.info("[render_worker] child 开始 ...")

collected_assets: list[dict] = []
_start_time: float = time.time()

try:
    ...
```

主 `try/except/finally` 从 line 254 才开始。

影响：

- identity validation 异常不会进入 `render_worker` 自己的 `except/finally`。
- batch path 中异常由 `future.result()` 抛出，并由 coordinator 的 child exception logger 记录。
- single BackgroundTask path 没有 batch coordinator 包装，validation 异常向 BackgroundTask 调用方传播，且不会产生 worker child-start/finish log。
- 见 RF-01。

### Node-level child marker

TTS / Subtitle：

```python
if "child_index" in context.config or "file_sid" in context.config:
    raise RuntimeError("... child context is missing execution_id")
```

Compositor / Cover：

```python
if "child_index" in context.config or "execution_id" in context.config:
    raise RuntimeError("... child context is missing file_sid")
```

当前新 API path 在节点执行前无条件写入全部三个 marker，因此：

- 当前 batch path 缺 execution ID 或 file token 时会在 worker entry 或 node resolver fail-fast。
- 当前 batch path 没有静默退化为 shared `task_id` 的正常执行分支。

Legacy 检测本质上依赖“没有任何新 child marker”，而不是显式的 legacy provenance flag，见 RF-02。

### 已确认真实 legacy callers

```text
run_matrix_factory.py
run_factory.py
test_tts.py
test_subtitle.py
```

例如 `run_matrix_factory.py`：

```python
context = WorkflowContext(
    session_id=session_id,
    ...
    batch_size=batch_size,
)
context.config["session_id"] = session_id
```

该路径没有 `execution_id/file_sid/child_index`，但 `context.session_id` 已是旧的 per-child token，因此进入 legacy fallback。

## 6. TTS / VTT Diff

来源：[tts_node.py](E:/dopaworkspace/dopamatrix-desktop/src/nodes/tts_node.py:42)

### Namespace resolution

```python
def _resolve_execution_namespace(context: WorkflowContext) -> str:
    execution_id = context.config.get("execution_id")
    if execution_id:
        return str(execution_id)

    if "child_index" in context.config or "file_sid" in context.config:
        raise RuntimeError("[TTSNode] child context is missing execution_id")

    legacy_id = (
        getattr(context, "session_id", None)
        or context.config.get("session_id")
        or "default"
    )
    logger.warning(
        f"[TTSNode] execution_id missing; using legacy direct-call namespace={legacy_id}"
    )
    return str(legacy_id)
```

优先级：

```text
config["execution_id"]
→ fail-fast when a new child marker exists
→ context.session_id legacy fallback
→ config["session_id"] legacy fallback
→ "default"
```

### Writable paths

```python
execution_id = _resolve_execution_namespace(context)
output_path = self._output_dir / f"voice_{execution_id}_{target_lang}.mp3"
vtt_path    = self._output_dir / f"voice_{execution_id}_{target_lang}.vtt"
```

### Write modes

MP3：

```python
with open(str(output_path), "wb") as audio_file:
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_file.write(chunk["data"])
```

VTT：

```python
with open(str(vtt_path), "w", encoding="utf-8", newline="\n") as vtt_file:
    vtt_file.write(vtt_content)
```

证明：

若 `execution_id=A` 与 `execution_id=B` 且 `A != B`，在相同 output directory 和 language 下分别生成：

```text
voice_A_<lang>.mp3
voice_B_<lang>.mp3

voice_A_<lang>.vtt
voice_B_<lang>.vtt
```

新 child execution 不会得到相同 writable filename。

## 7. Subtitle ASS Diff

来源：[subtitle.py](E:/dopaworkspace/dopamatrix-desktop/src/nodes/subtitle.py:40)

Namespace resolution 与 TTS 对齐：

```python
execution_id = context.config.get("execution_id")
if execution_id:
    return str(execution_id)

if "child_index" in context.config or "file_sid" in context.config:
    raise RuntimeError("[SubtitleNode] child context is missing execution_id")

legacy_id = (
    getattr(context, "session_id", None)
    or context.config.get("session_id")
    or "default"
)
return str(legacy_id)
```

### Precise-VTT branch

```python
if vtt_path and os.path.exists(vtt_path):
    cues = self._parse_vtt(vtt_path)
    if cues:
        execution_id = _resolve_execution_namespace(context)
        ass_path = str(output_dir / f"sub_{execution_id}_{target_lang}.ass")
        ...
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
        context.set_variant_asset(target_lang, "subtitle_ass", ass_path)
        return context
```

### Fallback Dialogue branch

```python
if not text:
    return context

execution_id = _resolve_execution_namespace(context)
ass_path = str(output_dir / f"sub_{execution_id}_{target_lang}.ass")
...
with open(ass_path, "w", encoding="utf-8") as f:
    f.write(ass_content)
context.set_variant_asset(target_lang, "subtitle_ass", ass_path)
```

结论：

- 两个分支都调用同一个 `_resolve_execution_namespace()`。
- 两个分支都构造 `sub_<execution-id>_<lang>.ass`。
- 无可用文本时在解析 identity 前返回，不产生 writable file，因此不会产生路径碰撞。

## 8. Compositor / Cover Diff

### Compositor

来源：[compositor.py](E:/dopaworkspace/dopamatrix-desktop/src/nodes/compositor.py:67)

```python
@staticmethod
def _resolve_file_sid(context: WorkflowContext) -> str:
    file_sid = context.config.get("file_sid")
    if file_sid:
        return str(file_sid)

    if "child_index" in context.config or "execution_id" in context.config:
        raise RuntimeError(
            "[FFmpegCompositorNode] child context is missing file_sid"
        )

    return str(context.config.get("session_id") or "")
```

NEW PATH：

```text
config["file_sid"]
```

LEGACY FALLBACK：

```text
config["session_id"]
```

Master：

```python
output_path = self._master_output_path(context)
# output/master_video_<file_sid>.mp4
```

Final：

```python
final_path = self._final_output_path(context, lang)
# output/final_<lang>_<file_sid>.mp4
```

`context.session_id` 仍只作为 WS `task_id`：

```python
task_id: str = context.session_id
```

它没有用于新 child master/final filename。

### Cover

来源：[cover_node.py](E:/dopaworkspace/dopamatrix-desktop/src/nodes/cover_node.py:124)

```python
@staticmethod
def _resolve_file_sid(context: WorkflowContext) -> str:
    file_sid = context.config.get("file_sid")
    if file_sid:
        return str(file_sid)

    if "child_index" in context.config or "execution_id" in context.config:
        raise RuntimeError("[CoverNode] child context is missing file_sid")

    return str(context.config.get("session_id") or context.session_id)
```

NEW PATH：

```text
config["file_sid"]
```

LEGACY FALLBACK：

```text
config["session_id"]
→ context.session_id
```

Cover path：

```python
return os.path.join(
    output_dir,
    f"cover_{cls._resolve_file_sid(context)}.jpg",
)
```

直接回答：

1. Master token：`config["file_sid"]`。
2. Final token：`config["file_sid"]`。
3. Cover token：`config["file_sid"]`。
4. 当前新 child path 不会使用 shared `task_id`：缺 `file_sid` 时 child marker 会触发 fail-fast。
5. FFmpeg 参数、编码、轨道处理、copy、抽帧时序均未改变。变化限定于 token resolution、路径 helper、identity logging 和 fail-fast。
6. Cover 对 legacy `config["session_id"]=""` 的边缘行为与旧代码略有不同，见 RF-03。

## 9. Phase Scope Audit

对 `routes_dsl.py` 的 changed lines 做了专项搜索。除删除旧“指纹隔离/文件名指纹”注释外，未命中下列业务机制。

| 项目 | 审计结果 |
|---|---|
| TaskHistory INSERT / persistence | UNCHANGED |
| `task_history` schema | UNCHANGED |
| terminal completed WS | UNCHANGED |
| terminal failed WS ownership | UNCHANGED |
| partial status | UNCHANGED |
| candidate resolution | UNCHANGED |
| CompilationPlan generation | UNCHANGED |
| fingerprint | UNCHANGED；只删除了旧的误导性“文件名指纹”注释 |
| Diversity | UNCHANGED |
| Planner | UNCHANGED |
| BGM resolution | UNCHANGED |

与 WS 相关的变化仅有：

- child correlation 日志。
- `_run_compositor` / `_run_cover_node` exception log 增加 identity 字段。
- API description 澄清 `task_id` 和 `file_sid` 语义。

没有修改 WS payload、terminal status 或 ownership。

## 10. Critical Test Evidence

测试文件：

- [test_inv001_execution_isolation.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_execution_isolation.py:87)
- [test_inv001_execution_paths.py](E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_execution_paths.py:49)

### H1 — batch_size=1

```python
child = routes_dsl._create_child_executions(task_id, 1)[0]

parsed = uuid.UUID(child.execution_id)
self.assertNotEqual(child.execution_id, task_id)
self.assertEqual(child.child_index, 0)
self.assertEqual(child.file_sid, parsed.hex[:8])
```

状态：PRESENT。

### H2 / H3 — batch_size=4 和实际 dispatch 参数

```python
routes_dsl.render_batch_worker(
    None,
    task_id,
    batch_size=4,
    enable_tts=False,
    enable_subtitles=False,
)

self.assertEqual(len(calls), 4)
self.assertEqual({call["task_id"] for call in calls}, {task_id})
self.assertEqual({call["child_index"] for call in calls}, {0, 1, 2, 3})
self.assertEqual(len({call["execution_id"] for call in calls}), 4)
self.assertEqual(len({call["file_sid"] for call in calls}), 4)

for call in calls:
    self.assertEqual(
        call["file_sid"],
        uuid.UUID(call["execution_id"]).hex[:8],
    )
```

Fake worker 实际捕获：

```python
{
    "task_id": received_task_id,
    "execution_id": kwargs["execution_id"],
    "child_index": kwargs["child_index"],
    "file_sid": file_sid,
}
```

状态：PRESENT。

### H4 — Context propagation

```python
routes_dsl.render_worker(
    _renderable_plan(),
    task_id,
    file_sid=child.file_sid,
    execution_id=child.execution_id,
    child_index=child.child_index,
)

context = captured_contexts[0]
self.assertEqual(context.session_id, task_id)
self.assertEqual(context.config["execution_id"], child.execution_id)
self.assertEqual(context.config["file_sid"], child.file_sid)
self.assertEqual(context.config["child_index"], 0)
self.assertNotIn("session_id", context.config)
```

状态：PRESENT。

### H5 / H6 — MP3 和 VTT 路径隔离

```python
self.assertNotEqual(paths[0][0], paths[1][0])
self.assertNotEqual(paths[0][1], paths[1][1])

for execution_id, (mp3_path, vtt_path) in zip(execution_ids, paths):
    self.assertEqual(Path(mp3_path).name, f"voice_{execution_id}_en.mp3")
    self.assertEqual(Path(vtt_path).name, f"voice_{execution_id}_en.vtt")
```

状态：PRESENT。

### H7 — ASS 路径隔离

```python
self.assertNotEqual(paths[0], paths[1])
for execution_id, ass_path in zip(execution_ids, paths):
    self.assertEqual(Path(ass_path).name, f"sub_{execution_id}_en.ass")
    self.assertTrue(Path(ass_path).is_file())
```

另有 precise-VTT branch 测试：

```python
context.set_variant_asset("en", "vtt_path", str(vtt_path))
SubtitleNode().execute(context)
self.assertEqual(Path(ass_path).name, f"sub_{execution_id}_en.ass")
```

状态：PRESENT。

### H8 — master/final/cover 使用 file_sid

Helper-level：

```python
self.assertEqual(
    FFmpegCompositorNode._master_output_path(context),
    "output/master_video_deadbeef.mp4",
)
self.assertEqual(
    FFmpegCompositorNode._final_output_path(context, "en"),
    "output/final_en_deadbeef.mp4",
)
self.assertEqual(
    CoverNode._cover_output_path(context, os.path.join("output", "video.mp4")),
    os.path.join("output", "cover_deadbeef.jpg"),
)
```

Execute-level fake FFmpeg：

```python
node.execute(context)

self.assertEqual(
    context.get_asset("video_master"),
    "output/master_video_44444444.mp4",
)
self.assertEqual(
    context.variants["en"]["final_video"],
    "output/final_en_44444444.mp4",
)
self.assertEqual(commands[0][-1], "output/master_video_44444444.mp4")
self.assertEqual(commands[1][-1], "output/final_en_44444444.mp4")
```

Cover execute handoff 也有独立测试。

状态：PRESENT。

### H9 — new child missing identity fail-fast

```python
context.config["child_index"] = 0
with self.assertRaisesRegex(RuntimeError, "missing execution_id"):
    TTSNode(output_dir=directory).execute(context)
```

Subtitle 同样测试 `missing execution_id`。

Compositor/Cover：

```python
with self.assertRaisesRegex(RuntimeError, "missing file_sid"):
    FFmpegCompositorNode._master_output_path(context)

with self.assertRaisesRegex(RuntimeError, "missing file_sid"):
    CoverNode._cover_output_path(context, ...)
```

状态：PRESENT。

### H10 — legacy fallback

TTS：

```python
context = WorkflowContext(
    session_id="legacy-child",
    test_language="en",
    batch_size=4,
)
context.config["session_id"] = "legacy-child"
...
self.assertEqual(
    Path(context.variants["en"]["voice_audio"]).name,
    "voice_legacy-child_en.mp3",
)
```

Subtitle 和 master/final/cover legacy fallback 均有对应断言。

状态：PRESENT。

### H11 — disabled behavior

两个开关同时关闭：

```python
enable_tts=False,
enable_subtitles=False,
...
tts_node.assert_not_called()
subtitle_node.assert_not_called()
```

独立开关组合：

```python
for enable_tts, enable_subtitles in ((False, True), (True, False)):
    ...
    self.assertEqual(tts_node.called, enable_tts)
    self.assertEqual(subtitle_node.called, enable_subtitles)
```

batch dispatch 还断言两个 flag 传播到四个 children。

状态：PRESENT。

本次要求的 H1–H11 均存在，没有 `MISSING TEST`。

## 11. Test Results

重新执行：

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_execution_*.py" -q
```

结果：

```text
Ran 23 tests in 0.178s
OK
```

语法检查：

```powershell
.\venv_build\Scripts\python.exe -m py_compile `
  src/api/routes_dsl.py `
  src/nodes/tts_node.py `
  src/nodes/subtitle.py `
  src/nodes/compositor.py `
  src/nodes/cover_node.py `
  tests/test_inv001_execution_isolation.py `
  tests/test_inv001_execution_paths.py
```

结果：PASS。

Diff quality：

```powershell
git diff --check
```

结果：exit code `0`。仅输出 Git 的 LF→CRLF working-copy warning。

未执行：

- 正式视频生成。
- 真实网络 TTS。
- 真实 FFmpeg。
- installer build。

## 12. Diff Size / Quality Review

```powershell
git diff --numstat -- `
  src/api/routes_dsl.py `
  src/nodes/tts_node.py `
  src/nodes/subtitle.py `
  src/nodes/compositor.py `
  src/nodes/cover_node.py
```

```text
151  28  src/api/routes_dsl.py
44   6   src/nodes/compositor.py
30   6   src/nodes/cover_node.py
39   2   src/nodes/subtitle.py
32   5   src/nodes/tts_node.py
```

注意：两个新增测试文件未跟踪，因此不出现在 `git diff --numstat`。

`routes_dsl.py` 规模拆解：

- Identity structure：`_ChildExecution` dataclass。
- Identity creation：UUID、短 token、batch-local collision set、bounded retry。
- Identity validation：UUID、task inequality、child index、derived file token。
- Worker contract：新增 required `execution_id` / `child_index`。
- Context propagation：三个明确 config 字段，移除新 path 的 legacy alias。
- Batch dispatch：将 child record 传入 `pool.submit`，future map 保存完整 child identity。
- Single dispatch：三个 endpoint 分支统一调用相同 helper。
- Logging：child start/finish/error、compositor/cover wrapper correlation。
- API description：澄清 shared task ID 与 child file token。
- Other：没有业务 resolver、persistence、WS ownership 或 render pipeline 修改。

未发现与 Phase 1 无关的明显新增业务代码。

## 13. Review Findings

### RF-01 — Identity validation 位于 worker 主 try/finally 之前

`_validate_child_execution()` 在 child-start logger、`collected_assets` 初始化和主 `try` 之前执行。

影响：

- batch malformed identity 会由 coordinator future exception logger 记录。
- single BackgroundTask malformed identity 不会进入 worker 的 child-error/finish logger。
- 当前所有生产调用点均使用 identity factory，因此不影响正常 accepted child；属于异常路径 observability 缺口。

### RF-02 — Legacy boundary 依赖 marker absence，不是显式 provenance

TTS/Subtitle/Compositor/Cover 将“没有任何新 child marker”的 Context 视为 legacy。

当前调用图安全，因为 `routes_dsl.render_worker` 无条件写入全部三个 marker；已知无 marker 调用者确实是旧 factory/direct-call。

但 helper 本身不能区分：

```text
真实 legacy Context
vs
未来错误构造且完全遗漏所有 markers 的新 Context
```

如果未来新路径遗漏全部 markers，TTS/Subtitle 可能回退到 `context.session_id`；如果该值是 shared task ID，则可能恢复 writable-path collision。当前代码路径不存在这一状态。

### RF-03 — Cover 的显式空 legacy alias 行为发生轻微变化

旧代码：

```python
context.config.get("session_id", context.session_id)
```

若 key 存在但值为 `""`，结果为空 token。

新代码：

```python
context.config.get("session_id") or context.session_id
```

相同输入会回退到 `context.session_id`。

因此该边缘输入的 cover filename 从：

```text
cover_.jpg
```

变为：

```text
cover_<context.session_id>.jpg
```

已知 legacy factory 使用非空 token，因此未发现当前实际调用受影响。除该 token fallback 边缘语义外，没有其他 render/output 行为变化。

## 14. Final Git Status

```text
 M src/api/routes_dsl.py
 M src/nodes/compositor.py
 M src/nodes/cover_node.py
 M src/nodes/subtitle.py
 M src/nodes/tts_node.py
?? doc/investigations/INV-001-Gate2-Fix-Architecture-Plan.md
?? doc/investigations/INV-001-Gate3-Phase1-Execution-Isolation-Report.md
?? tests/test_inv001_execution_isolation.py
?? tests/test_inv001_execution_paths.py
```

没有修改、format、commit、push 或进入 Phase 2。等待人工 Review。