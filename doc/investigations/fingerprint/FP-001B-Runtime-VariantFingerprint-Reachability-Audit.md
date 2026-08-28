# FP-001B
# Runtime VariantFingerprint Reachability Audit

## 1. Baseline

```text
branch:
feature/var-001-variation-policy

HEAD:
35d63cd905c96fd2fa5d62162023ee07de3110fe
```

当前未提交文件：

```text
 M src/api/routes_dsl.py
?? doc/investigations/fingerprint/FP-001B-Runtime-Fingerprint-Observability-Implementation-Report.md
?? doc/investigations/fingerprint/FP-001B-Small-Fix-up-Report.md
?? doc/investigations/fingerprint/FP-001B-Targeted-Runtime-Observability-Code-Review-Bundle.md
?? tests/test_fp001_fingerprint_observability.py
```

`git diff --stat`：

```text
src/api/routes_dsl.py | 197 ++++++++++++++++++++++++++++++++++++++++++++++++++
1 file changed, 197 insertions(+)
```

`git diff --check`：通过。仅报告现存 LF→CRLF 提示，无 whitespace error。

---

## 2. FP-001B Source Presence

当前工作树中的实现完整存在于 [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:181)。

关键定义：

```python
_MainVisualFingerprint = tuple[tuple[int, str, int, str], ...]

_MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE = "main_visual_planning"
_MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION = 1
_MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM = "md5"
_VARIANT_FINGERPRINT_EVENT = "VariantFingerprint"
_VARIANT_FINGERPRINT_PHASE = "authoritative_worker_start"
_MAX_LOGGED_FINGERPRINT_COMPONENTS = 32
_MAX_LOGGED_BEAT_IDENTITY_CHARS = 128
_MAX_LOGGED_SOURCE_HASH_CHARS = 128
```

已确认存在：

- `_MainVisualPlanningFingerprintContract`
- `_main_visual_planning_fingerprint_contract`
- `_main_visual_planning_log_components`
- `_variant_fingerprint_event_payload`
- `_emit_authoritative_variant_fingerprint`
- `render_worker(... visual_fingerprint=...)`
- `_execute_child(... visual_fingerprint=work.visual_fingerprint)`

关键 handoff：

```python
plan_is_authoritative=work.authoritative_plan is not None,
visual_fingerprint=work.visual_fingerprint,
```

结论：

`FP001B_SOURCE_PRESENT`

---

## 3. Runtime Process Provenance

审计时没有正在运行的 DopaMatrix、Python、Uvicorn、backend sidecar 或 Tauri 后端进程；端口 8000 也没有可见监听者。

因此无法从当前进程恢复最新测试的：

- PID
- executable path
- command line
- working directory
- process start time
- Python 与 bundled executable 分类

最新测试进程已经退出。

实际运行进程类别：`NOT PROVEN`。

---

## 4. Runtime Source Provenance

若运行方式是当前仓库下的 Python：

```python
from src.api import routes_dsl
```

则 `main.py` 应加载：

```text
E:\dopaworkspace\dopamatrix-desktop\src\api\routes_dsl.py
```

支持当前源码运行的证据：

- `routes_dsl.py` 最后修改：`2026-08-27T22:07:29+08:00`
- 最新日志的 backend lifespan 启动：`2026-08-27 22:19:39`
- 日志包含 `execution_id/child_index/file_sid` compositor 事件；这些行来自 `2026-08-21` 的 commit `96eb6ee9`
- 工作区现存 sidecar 构建于 `2026-08-03`，不可能包含上述 8 月 21 日代码

因此，现存的 8 月 3 日 sidecar 可以排除为本次真实运行后端。

但由于进程已经退出，不能排除工作区外另一个较新的 executable，也不能直接证明当时的命令行。

结论：

`RUNTIME_CURRENT_SOURCE_EXPECTED`

最终证明等级仍为：`RUNTIME_SOURCE_NOT_PROVEN`。

---

## 5. Dev / Tauri Startup Path

配置证据：

- [package.json](E:/dopaworkspace/dopamatrix-desktop/web_ui/package.json:6) 的 `dev` 仅启动 Vite。
- [tauri.conf.json](E:/dopaworkspace/dopamatrix-desktop/web_ui/src-tauri/tauri.conf.json:9) 的 `beforeDevCommand` 是 `npm run dev`。
- [lib.rs](E:/dopaworkspace/dopamatrix-desktop/web_ui/src-tauri/src/lib.rs:79) 明确规定：
  - debug/Tauri dev：跳过 sidecar，需要手工启动 `python main.py`
  - production：启动 bundled `backend` sidecar
- [main.py](E:/dopaworkspace/dopamatrix-desktop/main.py:237)：

```python
if is_prod:
    uvicorn.run(app, host="127.0.0.1", port=8000, log_config=None)
else:
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
```

- [build_backend.py](E:/dopaworkspace/dopamatrix-desktop/build_backend.py:198) 使用 PyInstaller 打包 `main.py`，再复制到 Tauri sidecar 目录。

正常 Tauri dev + `python main.py` 使用当前 Python source。

可能运行旧代码的路径：

- production Tauri 使用未重建的 bundled sidecar
- 手工启动旧 backend executable
- 使用无 `--reload` 的 Python/Uvicorn 进程，并在进程启动后修改源码

结论：

`DEV_RUNTIME_SOURCE_DIRECT`

同时，production/runtime 确实存在 stale-binary 风险。

---

## 6. Logging Initialization

后端日志初始化位于 [logger.py](E:/dopaworkspace/dopamatrix-desktop/src/core/logger.py:30)：

```python
from loguru import logger

def setup_logger() -> None:
    logger.remove()
    if sys.stdout is not None:
        logger.add(sys.stdout, level="INFO", ...)
    logger.add(
        os.path.join(LOG_DIR, "dopamatrix_{time:YYYY-MM-DD}.log"),
        level="INFO",
        ...
    )
```

[main.py](E:/dopaworkspace/dopamatrix-desktop/main.py:40) 导入并调用该 Loguru 配置：

```python
from src.core.logger import setup_logger, logger
setup_logger()
```

仓库中未找到：

- `logging.basicConfig`
- 标准库 `dictConfig/fileConfig`
- stdlib → Loguru InterceptHandler
- 对 `src.api.routes_dsl` 的显式 level/handler 配置

Uvicorn 默认 logging config 只配置 `uvicorn`、`uvicorn.error`、`uvicorn.access`，没有配置 root logger。

---

## 7. Logger Comparison

### routes_dsl

[routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:81)：

```python
logger = logging.getLogger(__name__)
```

这是 Python 标准库 logging。

### compositor

[compositor.py](E:/dopaworkspace/dopamatrix-desktop/src/nodes/compositor.py:16)：

```python
from src.core.logger import logger
```

这是项目 Loguru logger。

同时 [base_node.py](E:/dopaworkspace/dopamatrix-desktop/src/core/base_node.py:29)：

```python
def log(self, message: str) -> None:
    logger.info(f"[{self.name}] {message}")
```

最新实际日志中可见的 TTS、Subtitle、Compositor、Cover 全部通过该 Loguru sink 输出。

结论：

`LOGGER_SOURCE_DIFFERENCE_FOUND`

---

## 8. Effective Logger State

在未导入应用、无启动副作用的只读 Python 进程中：

```text
root:
level=30
effective_level=30
disabled=False
handlers=[]

src.api.routes_dsl:
level=0
effective_level=30
disabled=False
propagate=True
handlers=[]

src.nodes.compositor (stdlib object，实际 compositor 不使用它):
level=0
effective_level=30
disabled=False
propagate=True
handlers=[]
```

含义：

- `src.api.routes_dsl` 的 `logger.info(...)` 低于有效 WARNING 等级
- INFO 在进入 handler 前即被标准库 logging 丢弃
- 项目 Loguru INFO file sink 不接收该 stdlib logger
- compositor 使用的是另一套 Loguru logger，所以 INFO 正常可见

这不是 FP emitter 独有的问题；该模块原有的全部 INFO 都受影响。

---

## 9. AI Draft Frontend Flow

实际 AI Draft 数据流位于 [WorkspaceView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:310)。

### draft-blueprint 请求

```javascript
await axios.post(
  `${store.API_BASE}/api/v1/tasks/draft-blueprint`,
  {
    prompt: pureText || raw,
    mode: scriptMode.value,
    duration: targetDuration.value,
    langs: [testLanguage.value],
    available_tags: availableTags.value,
    user_hard_tags: hardTags,
  },
)
```

成功后：

```javascript
orchestratorDirectRender.value = true
orchestratorVariantPlanningPolicy.value =
  EXACT_MAIN_VISUAL_PLANNING_POLICY
```

### Drawer handoff

[DslOrchestratorDrawer.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/DslOrchestratorDrawer.vue:425)：

```javascript
if (props.directRender) {
  emit('confirm', {
    ...
    directRender: props.directRender,
    variantPlanningPolicy: props.variantPlanningPolicy,
  })
}
```

### Workspace submit

```javascript
if (directRender) {
  blindFission({
    variantPlanningPolicy,
  })
}
```

最终 payload：

```javascript
{
  engine_type: currentTemplate.value,
  timeline,
  aspect_ratio: aspectRatio.value,
  target_duration: targetDuration.value,
  batch_size: batchSize.value,
  test_language: testLanguage.value,
  tenant_id: store.loggedInUser || 'default',
  mode: scriptMode.value,
  variant_planning_policy: variantPlanningPolicy,
  ...
}
```

提交至：

```text
POST /api/v1/tasks/submit-dsl
```

---

## 10. Variant Planning Policy

前端常量：

```javascript
const LEGACY_VARIANT_PLANNING_POLICY = 'legacy'
const EXACT_MAIN_VISUAL_PLANNING_POLICY = 'exact_main_visual'
```

AI Draft 路径显式设置并透传：

```text
variant_planning_policy = exact_main_visual
```

它不是从 UI badge、`mode` 或 timeline 推断出来的。

结论：

`AI_DRAFT_EXACT_POLICY_PROVEN`

---

## 11. Result-Card Badge Audit

[QueueView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue:237)：

```typescript
function getModeLabel(task: QueueTask): string {
  const mode = String(
    (task as any).mode || (task as any).generation_mode || ''
  ).toLowerCase()

  if (mode === 'director') return 'AI起草模式'
  if (mode === 'blind') return '极速闭眼裂变'
  return '手工战术板模式'
}
```

后端 terminal payload 在 [routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1528) 写入：

```python
"generation_mode": director_mode
```

而 AI Draft 实际 `director_mode` 来源于 `payload.mode`，当前值为：

```text
auto
或
rewrite
```

QueueView 不识别 `auto/rewrite`，因此落入默认的“手工战术板模式”。

页面刷新后的历史水合还有第二个问题：

- `TaskHistory` 没有 generation mode 字段
- `/tasks/today` 序列化结果不返回 generation mode
- QueueView 最终 fallback 为 `manual`

主分类：

`UI_MODE_BADGE_MAPPING_BUG`

并伴随历史水合层面的 `UI_MODE_METADATA_MISSING`。

该 badge 与 `variant_planning_policy` 没有关系。

---

## 12. Latest Task Policy Evidence

只读查询：

```text
database:
data/dopamatrix_testduplicate.db

task_id:
34529159-1cb3-4e31-8e9c-270570ab0ba4
```

记录：

```text
batch_size: 4
output assets: 4
requested_count: 4
planned_count: 4
succeeded_count: 4
failed_count: 0
children: 4
```

四个 child 均持久化了：

- `child_index`
- `execution_id`
- `file_sid`
- `outcome=succeeded`
- 5 个 ordered Beats：`hook/context/build/reveal/cta`

`prompt_details` 顶层只有：

```text
meta
timeline
planning_summary
children
```

未发现：

```text
variant_planning_policy
director_mode
blind_dsl
generation_mode
```

结论：

`POLICY_NOT_PERSISTED`

因此 TaskHistory 本身不能独立证明该具体 task 的 policy。

---

## 13. Submit-DSL Backend Branch

[routes_dsl.py](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:137)：

```python
def _requests_exact_main_visual(payload):
    return payload.variant_planning_policy == "exact_main_visual"
```

`submit_dsl()`：

```python
_worker_kw = {
    "blind_dsl": is_blind,
    "engine_type": payload.engine_type,
    "director_mode": payload.mode,
    ...
    "variant_planning_policy": payload.variant_planning_policy,
}

if _requests_exact_main_visual(payload):
    _worker_kw["resolved_plan"] = plan

background_tasks.add_task(
    render_batch_worker,
    dsl_payload_for_worker,
    task_id,
    ...
    **_worker_kw,
)
```

`render_batch_worker()`：

```python
if variant_planning_policy == "exact_main_visual":
    planning_result = _plan_exact_main_visual_variants_from_db(...)
```

Legacy/other policy 则直接为请求的 batch size 创建 `_ChildWork`，不携带 authoritative plan/fingerprint。

---

## 14. Exact Authoritative Coordinator Path

当前 exact path：

```text
submit-dsl
→ _requests_exact_main_visual
→ preview plan seed
→ render_batch_worker
→ _plan_exact_main_visual_variants_from_db
→ planning_result.plans + fingerprints
→ coordinator recompute/uniqueness invariant
→ _create_child_executions
→ _ChildWork(authoritative_plan, visual_fingerprint)
→ _execute_child
→ render_worker
```

Coordinator pairing：

```python
_ChildWork(
    execution=identity,
    authoritative_plan=plan,
    visual_fingerprint=fingerprint,
)
```

Worker handoff：

```python
plan_is_authoritative=work.authoritative_plan is not None,
visual_fingerprint=work.visual_fingerprint,
```

Worker authoritative entry：

```python
if plan_is_authoritative:
    if plan is None:
        ...
    working_plan = plan
    _emit_authoritative_variant_fingerprint(
        working_plan,
        planner_fingerprint=visual_fingerprint,
        task_id=task_id,
        execution_id=execution_id,
        child_index=child_index,
        file_sid=resolved_file_sid,
    )
```

紧接着才执行：

```python
timeline = compile_plan_to_timeline(working_plan, ...)
```

因此，在当前 FP-001B source 下，只要 exact authoritative child 到达 `render_worker`，emitter 必定在 timeline/TTS/Subtitle/Compositor 之前被调用。

结论：

`EXACT_PATH_REACHES_FP001B_EMITTER`

---

## 15. Non-Authoritative Path

Legacy 分支：

```python
child_work = [
    _ChildWork(execution=child)
    for child in _create_child_executions(task_id, batch_size)
]
```

因此 `batch_size=4` 可以产生四个 worker。

进入 worker 时：

```python
plan_is_authoritative = False
visual_fingerprint = None
dsl_payload != None
```

随后每个 worker 独立执行：

```python
working_plan = _parse_plan_from_db(tenant_id, dsl_payload)
```

Locked resolver 对多个 X candidates 使用：

```python
random.choice(x_track)
```

Smart resolver排序也包含：

```python
random.random()
```

所以 non-authoritative batch=4 可以独立抽取主视觉，并可能偶然得到四个不同完整组合。

结论：四个组合唯一本身不能证明 exact policy。

---

## 16. Existing Routes_DSL Logger Probes

正常 submit-dsl/exact render 中本应执行的既有 INFO 包括：

- submit-dsl request：[routes_dsl.py:1752](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1752)
- preview plan resolved：[routes_dsl.py:1799](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1799)
- background dispatch：[routes_dsl.py:1852](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1852)
- batch worker start：[routes_dsl.py:1329](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1329)
- exact planner summary：[routes_dsl.py:1382](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1382)
- child worker start：[routes_dsl.py:809](E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:809)

这些都是 fingerprint 之前已经存在的同模块 INFO probes。

最新日志中：

```text
src.api.routes_dsl: 0
routes_dsl: 0
submit-dsl: 0
render_worker: 0
```

所以缺失不是 `VariantFingerprint` 单点问题，而是整个 `routes_dsl` stdlib INFO 可见性问题。

正常成功路径不要求产生 routes_dsl WARNING/ERROR，因此相关关键词为 0 不能进一步证明 emitter mismatch/missing 分支是否发生。

---

## 17. Runtime Log Search

本地日志：

```text
C:\Users\chenp\AppData\Local\DopaMatrixOrg\DopaMatrix\Logs\
dopamatrix_2026-08-27.log
```

精确计数：

| Search term | Count |
|---|---:|
| `VariantFingerprint` | 0 |
| `FINGERPRINT_OBSERVABILITY` | 0 |
| `main_visual_planning` | 0 |
| `planner_fingerprint_match` | 0 |
| `src.api.routes_dsl` | 0 |
| `exact_main_visual` | 0 |
| `variant_planning_policy` | 0 |
| `render_worker` | 0 |
| latest task_id | 20 |

latest task 的 20 条记录来自：

- TTSNode
- SubtitleNode
- `src.nodes.compositor`
- CoverNode

这与 Loguru sink 的来源完全吻合。

---

## 18. Temporal Analysis

预期顺序：

```text
submit-dsl
→ exact coordinator
→ authoritative worker entry
→ VariantFingerprint INFO
→ compile timeline
→ TTS
→ Subtitle
→ compositor
```

实际 Loguru 文件：

```text
backend lifespan start
→ 无 routes_dsl INFO
→ TTS
→ Subtitle
→ compositor
→ Cover
```

假设评估：

- H1 emitter not reached：与当前 AI Draft exact source flow 不符，但该 task policy 未持久化。
- H2 routes_dsl INFO suppressed：源码和有效 logger level 直接支持。
- H3 stale runtime code：旧 workspace sidecar 存在，但其版本无法产生实际日志中的 8 月 21 日 execution-isolation 行；实际 stale runtime 未证明。
- H4 different log sink：已证明 routes_dsl 与 compositor 使用不同 logger 系统；这是 H2 的底层机制。
- H5 non-authoritative execution：用户确认 AI Draft，当前 frontend 明确发送 exact；TaskHistory 不足以单独复核该具体请求。

最符合全部现有证据的是 H2。

---

## 19. Backend Reload / Restart Semantics

开发入口：

```python
uvicorn.run("main:app", ..., reload=True)
```

因此通过 `python main.py` 启动时启用 source auto-reload。

源码注释也推荐：

```text
uvicorn main:app --reload --port 8000
```

以下路径没有自动加载源码变更：

- frozen backend：`reload` 未启用
- 手工执行 `uvicorn main:app` 且不带 `--reload`
- bundled Tauri sidecar

如果 backend 在 FP-001B 修改前启动且没有 reload，确实足以解释缺失事件；但本次日志中的 lifespan 启动时间晚于源码修改时间。

---

## 20. Process Start vs Source Change Evidence

```text
routes_dsl.py modified:
2026-08-27 22:07:29 +08:00

backend lifespan first log:
2026-08-27 22:19:39 +08:00

workspace sidecar modified:
2026-08-03 20:46:22 +08:00
```

结论：

- 没有出现 `process_start < FP001B source modification` 的证据。
- 如果测试使用 Python source，启动发生在 FP-001B 修改之后。
- 工作区 sidecar 明显早于 FP-001B：

`STALE_RUNTIME_ARTIFACT_EVIDENCE`

但该 8 月 3 日 artifact 也早于实际日志中使用的 8 月 21 日 execution-isolation 代码，因此它不是本次测试后端。

由于进程已退出，仍不能把实际 executable/source path 提升到完全证明。

---

## 21. Root-Cause Classification

主分类：

**B. FP001B_INFO_LOGGER_SUPPRESSED**

直接证据：

1. `routes_dsl` 使用 stdlib `logging.getLogger(__name__)`。
2. 它没有 handler，预期 effective level 为 WARNING。
3. FP event 使用 `logger.info(...)`。
4. 项目实际日志文件由 Loguru sink 维护。
5. compositor/TTS/Subtitle/Cover 使用 Loguru，所以 INFO 可见。
6. 同一工作流所有既有 routes_dsl INFO 同样全部缺失。

剩余假设排序：

1. `FP001B_LOG_SINK_MISMATCH`——已证明，是 INFO suppression 的底层配置原因。
2. `FP001B_RUNTIME_USING_STALE_CODE`——实际运行来源未完全证明，但现有 workspace stale sidecar已被日志代码年代排除。
3. `FP001B_EMITTER_NOT_REACHED`——latest task policy 未持久化，因而无法用 DB 独立排除；但与已确认的 AI Draft current-source flow 不符。

`FP001B_REAL_REQUEST_NON_AUTHORITATIVE` 没有实际 request/backend 证据支持。

---

## 22. UI Badge Separate Finding

### UI-RF-01
### GENERATION_MODE_BADGE_STALE_OR_INCORRECT

当前原因：

- AI Draft 请求使用 `mode=auto|rewrite`
- terminal payload 将该值写为 `generation_mode`
- QueueView 仅识别 `director|blind`
- 其他任何值都显示“手工战术板模式”
- 历史记录又不持久化/返回 generation mode

当前实际数据源：

```text
live queue:
WS terminal generation_mode = director_mode

history hydration:
no persisted generation mode → manual fallback
```

未来正确数据源应是明确、持久化的 generation workflow/mode 元数据；不应从 `variant_planning_policy` 推断，因为两者表达不同维度。

该 finding 不参与 FP-001B reachability 根因分类。

---

## 23. Recommended Next Action

唯一建议：

**执行一个最小 FP-001B logger-alignment fix-up：让 `VariantFingerprint` INFO 进入现有 Loguru backend sink，然后复跑同一 AI Draft 5-Beat batch=4 验收。**

本审计未实施该动作。

---

## 24. Final Git Status

最终状态与基线一致：

```text
 M src/api/routes_dsl.py
?? doc/investigations/fingerprint/FP-001B-Runtime-Fingerprint-Observability-Implementation-Report.md
?? doc/investigations/fingerprint/FP-001B-Small-Fix-up-Report.md
?? doc/investigations/fingerprint/FP-001B-Targeted-Runtime-Observability-Code-Review-Bundle.md
?? tests/test_fp001_fingerprint_observability.py
```

没有由本次只读审计产生的文件修改。

---

FP001B_SOURCE_PRESENT:
YES

AI_DRAFT_EXACT_POLICY:
PROVEN

EXACT_PATH_REACHES_FP001B_EMITTER:
YES

RUNTIME_CURRENT_SOURCE:
NOT_PROVEN

ROUTES_DSL_INFO_VISIBLE:
NO

UI_MODE_BADGE_TRUSTWORTHY:
NO

ROOT_CAUSE:
FP001B_INFO_LOGGER_SUPPRESSED

NEXT_ACTION:
将 VariantFingerprint INFO 对齐到现有 Loguru sink，并复跑同一 AI Draft 验收。