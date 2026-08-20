# INV-001 Codex Read-Only Root Cause Report

调查基线：

- Branch：`fix/creative-duplicate-detection`
- Commit：`965ed0564306d670c78c3454b8ba42764516c1c6`
- 已按指定顺序阅读 investigation、experiment summary、Repro001/002/003、原始日志、SHA-256 和截图，之后才进入源码。
- 对 `data/dopamatrix_testduplicate.db` 仅使用 SQLite read-only URI 查询。
- 未修改任何代码、测试、配置、文档、数据库或 Git 历史；未启动生成任务。
- 当前 worktree 中已有的 investigation/evidence 变更保持原样。

证据标记：

- **OBSERVED EVIDENCE**：实验、日志、截图、SHA-256、只读数据库现状。
- **CURRENT CODE FACT**：当前 commit 的可直接验证行为。
- **INFERENCE**：由 evidence 与代码联合得到、但没有被专门日志直接记录的推导。
- **RECOMMENDATION**：仅建议，不执行。

---

## 1. Executive Summary

1. AI Draft 的实际 render plan 不是 batch 前解析一次再复制；batch 展开后，四个 worker 分别重新解析同一份 unresolved DSL。
2. 用户意图中的 Hook 四候选在前端没有以四个 hash 提交；实际提交的是 `44444.mp3 + hook:汽车减震器`，后端再通过标签重建四视频隐式池。
3. Hook resolver 对相同旧 `usage_count` 快照评分、取 Top-1；同分时才用随机熵打破平局。四个并发 worker 的选择在任何 usage 更新之前全部完成。
4. Context 的两个显式 hash 通过 `random.choice` 有放回独立抽取；Build 单候选 `24.mp4` 固定重复。
5. 当前不存在 batch-scoped combination claim、reservation、used-combination state 或重复检查。因此相同 Hook + Context + Build 组合是当前算法明确允许的结果。
6. 两个 worker 的有序 visual `CompilationPlan` 一旦相同，确定性的 timeline adapter 会产生相同主轨；相同源媒体进一步形成相同 `GlobalTimeline` 和 master visual。
7. 共享 `task_id` 没有进入 resolver，不能造成上述资产选择碰撞；它是独立的 execution identity 缺陷。
8. 该 identity 缺陷直接造成共享 MP3/VTT/ASS writable path 和 `TaskHistory.task_id` UNIQUE collision，但其对 Repro001/002 音频 hash 分组的具体因果仍证据不足。

---

## 2. Current AI Draft Call Chain

```text
WorkspaceView.draftBlueprint
  → POST /api/v1/tasks/draft-blueprint
  → Director 返回 semantic tags / scripts
  → applyBlueprintTimelineToTracks
  → AI Draft Tactical Board

DslOrchestratorDrawer
  → 用户编辑 tag/physical items
  → submitRenderTask
  → emit confirm(directRender=true)

WorkspaceView.onOrchestratorConfirm
  → buildTimelineFromTracks
  → POST /api/v1/tasks/submit-dsl
  → one request, batch_size=4

routes_dsl.submit_dsl
  → request-thread preview/validation parse
  → create one task_id
  → render_batch_worker

render_batch_worker
  → create four file_sid
  → ThreadPoolExecutor
  → four render_worker calls
  → same task_id + same raw DSL
  → different file_sid

each render_worker
  → _parse_plan_from_db
  → DSLParserNode.parse_and_resolve
  → execution-local CompilationPlan
  → compile_plan_to_timeline
  → execution-local WorkflowContext
  → TTS
  → Subtitle
  → Compositor master
  → Compositor final
  → Cover
  → per-worker TaskHistory INSERT
  → post-render usage_count update

render_batch_worker
  → aggregate output assets
  → one WS completed event
```

关键代码位置：

- AI Draft 初稿：[WorkspaceView.vue:289](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:289)
- Draft 映射到轨道：[WorkspaceView.vue:224](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:224)
- Drawer confirm：[DslOrchestratorDrawer.vue:424](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/DslOrchestratorDrawer.vue:424)
- 最终 DSL/payload：[WorkspaceView.vue:334](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:334)
- `/submit-dsl`：[routes_dsl.py:878](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:878)
- Batch expansion：[routes_dsl.py:625](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:625)
- Worker effective parse：[routes_dsl.py:245](/E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:245)
- Resolver：[dsl_parser.py:90](/E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:90)
- Timeline adapter：[dsl_adapter.py:43](/E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_adapter.py:43)

**CURRENT CODE FACT：** `routes_dsl.py:930-939` 在 batch expansion 前确实解析一次 plan，但 `routes_dsl.py:970-994` 传给 batch worker 的是重新构造的 raw `StoryDSLPayload`，没有传递该 authoritative plan。

**结论：** “有效选择发生在 batch 前并把 resolved plan 复制给 workers”是 **DISPROVED**。前置 plan 只是校验/响应快照；真正用于 master render 的 plan 在每个 worker 中重新产生。

当前 DSL 路径也没有调用 `WorkflowEngine.run`；它在 `routes_dsl.py` 内直接串联 TTS、Subtitle、Compositor 和 Cover nodes。

---

## 3. Candidate Pool Lifecycle

### 3.1 截图揭示的真实战术板状态

三轮 `03-select-assets.png` 均显示总计“5 已装填”：

| Beat | 轨道内实际 item | 前端含义 | Backend visual selection |
|---|---|---|---|
| Hook | `44444.mp3` physical + `hook:汽车减震器` semantic tag | BGM hash + 标签约束 | 标签查询重建隐式视频池 |
| Context | `28.mp4` + `18.mp4` physical | 两个显式 hash 候选 | `random.choice` 选一 |
| Build | `24.mp4` physical | 一个显式 hash | 固定 `24.mp4` |

`12/13/16/58` 显示在上方按 Hook tag 筛选的素材仓库中，并非四个都作为 physical pills 放进 Hook 轨道。

因此应区分：

- **用户意图层：** Hook 是四候选池。
- **前端数据层：** Hook 四个视频 identity 没有进入 DSL，进入的是标签约束。
- **后端有效池：** resolver 在 tenant DAM 中按该标签重新查得四个视频。

### 3.2 前端数据结构

`dslTracks[].items[]` 是两种对象的混合数组：

```text
physical_asset:
  uuid, id, hash, asset_type, file_path, name, manifest

semantic_tag:
  uuid, tag
```

不存在以下字段：

```text
candidate_pool
resolved_asset
selected_asset
selection_seed
execution_id
variant_id
selected_combination
used_assets
```

[WorkspaceView.vue:337-350](/E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:337) 确定性序列化：

```text
address_mode = physicals.length > 0 ? "locked" : "smart"
asset_hashes = all physical hashes
semantic_tags = all semantic tags
```

据截图和 builder，可以强推提交的核心结构为：

```text
Hook:
  address_mode = locked
  asset_hashes = [hash(44444.mp3)]
  semantic_tags = ["hook:汽车减震器"]

Context:
  address_mode = locked
  asset_hashes = [hash(28.mp4), hash(18.mp4)]
  semantic_tags = []

Build:
  address_mode = locked
  asset_hashes = [hash(24.mp4)]
  semantic_tags = []
```

这是 **INFERENCE**，因为现有 frontend log 没有保存实际 POST body；但截图状态和 builder 都是确定性的。

### 3.3 必答问题

1. **用户拖入的是 candidate list 还是 resolved asset？**

   是混合语义：

   - Context：两个 physical assets 构成显式候选列表。
   - Build：一个 physical asset，实际等价固定选择。
   - Hook：不是四个 physical 候选；是一个 semantic tag 定义的隐式候选池，外加一个 BGM physical。
   - 都不是 submit 前已经生成的最终 resolved visual plan。

2. **每个 Beat 是否保存全部 candidate assets？**

   - Context：是，两个 hash 都保留。
   - Build：是，但只有一个。
   - Hook：不保存四个视频 hash，只保存 tag，后端重新查询有效池。

3. **submit 前是否已经解析成单 asset？**

   没有。`buildTimelineFromTracks` 保留全部 physical hash 和 tag。

4. **真正 selection 在哪里？**

   `src/api/dsl_parser.py::DSLParserNode._resolve_locked`：

   - Context：`lines 207-215` 的 `random.choice(x_track)`。
   - Hook：`lines 236-276` 的 locked-X tag fallback，最终取 `scored_fb[0]`。
   - Build：单一 X candidate，无抽取。

5. **selection 在 batch expansion 前还是后？**

   有一次被丢弃的 preview selection 在前；权威 render selection 在 batch expansion 后，每个 worker 独立执行。

6. **是否复制同一个 resolved plan？**

   否，**DISPROVED**。四个 worker 接收同一 raw DSL，但各自产生新的 `CompilationPlan`。

7. **为什么独立 execution 仍然选中相同候选？**

   - Hook：并发读取相同旧 usage 排名；没有即时 claim/update；同分时随机仍可碰撞。
   - Context：`random.choice` 有放回选择，允许多个 worker 选同一 hash。
   - Build：只有 `24.mp4`，重复是预期。
   - 系统从不检查最终三 Beat 组合是否已被同 batch 其他 worker 使用。

8. **不同 execution 是否拥有独立 selection state？**

   - 各自有独立 DB Session、parser 对象和 result plan。
   - 但没有 execution-local RNG；使用 module-global `random`。
   - 没有 batch diversity state。
   - usage 来源是同一数据库快照。
   - 因此对象是 execution-local 的，选择策略却不是 combination-isolated 的。

---

## 4. Identity Model

| 概念 | 当前实现 | 结论 |
|---|---|---|
| Request `session_id` | 可选；本次前端未发送 | 通常为空 |
| `task_id` | `payload.session_id` 或 UUID4，`routes_dsl.py:967` | batch 内四 worker 共享 |
| `WorkflowContext.session_id` | 等于共享 `task_id` | batch-scoped runtime namespace |
| Formal `batch_id` | 无字段、无对象 | **NOT PRESENT** |
| `execution_id` | 无正式字段 | **NOT PRESENT** |
| `variant_id` | render/request/context/history 主链无此概念 | **NOT PRESENT** |
| `file_sid` | 每 child 一个随机 8 hex，`routes_dsl.py:658` | 仅文件名 suffix |
| `context.config["session_id"]` | 等于 `file_sid`，单任务退化为 `task_id[:8]` | master/final/cover namespace |
| `TaskHistory.id` | DB 自增主键 | history row identity，不是 execution identity |

不要把共享 UUID 预先称为 `batch_id`。源码真实名称是 `task_id`；只是在 batch 路径中，它事实上承担了一部分 batch/UI-card 语义。

Identity contract 目前内部不一致：

- `schemas.py:382-385` 描述 batch 为“N 个独立任务，每个唯一 task_id”。
- `schemas.py:474-475` 描述 `task_ids` 长度等于 `batch_size`。
- 实际返回 `task_ids=[task_id]`，见 `routes_dsl.py:1015-1018`。
- `render_batch_worker` 注释明确所有 child 共用一个 task_id，目的是 Queue 只展示一张卡片。

### 两层文件身份

每个 worker 同时存在：

```text
context.session_id           = shared full task UUID
context.config["session_id"] = execution-local 8-char file_sid
```

消费者：

| 消费者 | 使用的身份 |
|---|---|
| master video | `context.config["session_id"]` |
| final video | `context.config["session_id"]` |
| cover | `context.config["session_id"]` |
| TTS MP3/VTT | `context.session_id` |
| subtitle ASS | `context.session_id` |
| WS taskId | `context.session_id` / task_id |
| TaskHistory.task_id | task_id |

这解释了：

- 不同 execution 生成不同 `master_video_<short-id>.mp4`。
- 同时共享 `voice_<full-UUID>_en.mp3/.vtt` 和 `sub_<full-UUID>_en.ass`。

`file_sid` 不是正式 execution identity；它没有完整生命周期、持久化字段或唯一约束。

---

## 5. Context Isolation Analysis

### Shared

| Shared item | 说明 |
|---|---|
| `StoryDSLPayload` object | 同一引用传给所有 workers |
| `timeline`、`asset_hashes`、`semantic_tags` lists | raw payload 内嵌列表共享，但当前只读 |
| `task_id` / `WorkflowContext.session_id` 值 | 四 worker 相同 |
| module-global `random` | 所有 resolver 共用 |
| tenant DB state | 各 Session 读取同一数据库 |
| output directory | 相同目录 |
| TTS/VTT/ASS physical paths | 由共享 full task UUID 构造 |
| TaskHistory unique key | 同一个 task_id |
| WS task identity | 同一个 taskId |

### Execution-local

| Execution-local item | 说明 |
|---|---|
| SQLAlchemy Session | `_parse_plan_from_db` 每次新建 |
| `DSLParserNode` | 每 worker 新建 |
| `CompilationPlan` / resolved assets | 每 worker 新建 |
| `Timeline` / Track / Clip tree | 每 worker重新 compile |
| `WorkflowContext` instance | `routes_dsl.py:296-305` 每次新建 |
| Context `config/assets/variants` dictionaries | `context.py:31-43` 实例字段 |
| node outputs | 存于各自 Context |
| TTS script dictionary | 每个 Context 新建 |
| Compositor/TTS/Subtitle/Cover node instances | 每 worker 新建 |
| `file_sid` | 每 child 不同 |
| master/final/cover path | 由 `file_sid` 隔离 |
| collected outputs/history ORM object | worker-local |

### Copy 结论

- 未发现 `copy.copy` 或 `deepcopy` 生成 Context。
- Context 不是浅拷贝，而是全新构造。
- raw DSL 是引用共享，但 parser 只遍历它并构造新的 resolved objects。
- `_apply_layout_hints` 修改的是新建 `ResolvedLayer`，不是共享 DSL node。

因此：

- `shared mutable Context`：**DISPROVED**
- `shallow-copy contamination`：**DISPROVED**
- shared raw DSL reference：**VERIFIED**
- shared raw DSL mutation causing collision：**DISPROVED**

---

## 6. Asset Selection Analysis

### 6.1 Hook：tag-defined fallback + usage-ranked Top-1

Hook 被前端标为 `locked`，因为 Beat 内存在 physical BGM。但该 hash 是 Y-axis audio，不是 X-axis video。

`_resolve_locked` 的实际行为：

1. 按 BGM hash 查询。
2. 将其分为 Y layer，X track 为空。
3. 因存在 `semantic_tags=["hook:汽车减震器"]`，进入 locked-X fallback。
4. `_query_by_tags` 查询 X video types。
5. `_score_candidates` 按以下 key 排序：

```text
-soft_match_count
is_exhausted
usage_count
random.random()
```

6. 取 `scored_fb[0]`。

查询过滤：

- `is_exhausted=False`
- `is_deleted=False`
- asset type 属于 X video types
- Python 侧精确 tag 交集
- query 先按 `usage_count` 升序，最多 200 条
- Hook fallback 最多取 5 个匹配

没有：

- duration filter
- video role filter
- file-existence/availability filter
- batch claim
- same-combination filter
- render-before reservation

### 6.2 Hook usage 状态与三轮结果的对应

**OBSERVED EVIDENCE：**

- Repro001 前，四个 Hook 视频 usage 均为 0。
- Repro001 结果：13 被选 3 次，58 被选 1 次。
- Repro002 前截图中的累积状态：12=0、16=0、58=1、13=3。
- Repro002 四 worker 最终全部选中 12。
- Repro003 前：16 仍是唯一 usage=0；结果选择 16。

**CURRENT CODE FACT：**

- 四个 batch worker 的 Hook 选择都发生在 TTS/render 之前。
- usage 更新位于 `routes_dsl.py:575-602`，在 render/history 之后。
- Repro001/002 日志显示四个 TTS 都已启动时，尚没有任何 worker 到达 usage 更新。

**INFERENCE：**

- Repro002 的四个 worker 都看到同一个 pre-batch usage 排名。
- 当时 12 与 16 是最低 usage 的同分候选；随机 tie-break 四次都把 12 排到首位。
- 同 batch 内 12 被选中后，不会立即改变其他 worker 的候选排序。
- Repro003 单 execution 则看到 16 为唯一最小 usage，因而 Top-1 实际确定性落到 16。

这不是“候选池只剩一个”，而是当前 ranking + late feedback 把相同候选持续暴露给并发 workers。

### 6.3 Context：显式 multi-hash + random choice

Context 的 `asset_hashes` 包含 `28.mp4` 和 `18.mp4`。

`dsl_parser.py:207-215`：

```python
if len(x_track) > 1:
    chosen_x = random.choice(x_track)
    x_track = [chosen_x]
```

特点：

- 有放回。
- 不读取 `usage_count`。
- 不读取 `is_exhausted`。
- 不看同 batch 已选择内容。
- 不存在 execution seed。
- 不存在组合唯一性约束。

因此三个 Repro002 execution 都选中 18，并不要求共享 Context、缓存或相同 seed；这是该选择算法允许的普通 collision。

### 6.4 Build：固定候选

Build 只有 `24.mp4`。单 X candidate 不调用随机逻辑，所有 execution 固定选 24。

`24.mp4` 重复不是根因，也不应被禁止。

### 6.5 Candidate validity / shortage

只读数据库当前快照和三轮真实选择共同确认：

- `12/13/16/58` 均为 active video。
- 均带 `hook:汽车减震器`。
- 均 `is_deleted=0`、`is_exhausted=0`。
- `18/28/24` 也都是 active video。
- 三轮运行累计实际命中过全部四个 Hook 视频。
- 同一 batch 内 Context 的 18 和 28 都曾被选择。

所以本 evidence state 中：

- Hook 实际池不是 singleton。
- Context 实际池不是 singleton。
- candidate shortage/filter collapse：**DISPROVED**。

源码与 DB 共同支持最多 8 个不同有序主轨组合，但这些组合并非在每轮中等概率；尤其 Hook 的 usage ranking 会显著改变分布。

### 6.6 Random state

- `dsl_parser.py:26` 使用 module-level `import random`。
- 生产主链未发现 `random.seed`、per-execution `Random()` 或 seed 字段。
- workers 共享同一个 module-global RNG state。
- 这不是“四个 execution 被赋予相同 seed 并各自重放相同序列”。

因此：

- module-global RNG：**VERIFIED**
- identical per-execution seed：**DISPROVED**
- independent seed 能保证唯一：**DISPROVED**

即使每 worker 使用不同 seed，有放回抽取仍然可能碰撞。

### 6.7 Batch visibility

一个 execution 选中 asset 后：

- 不写 batch-local `used_assets`。
- 不写 `selected_combinations`。
- 不 claim asset 或组合。
- 不在 render 前更新 usage。
- 同 batch 其他 workers 在选择阶段看不到这个选择。

这就是多个 execution 能形成同一 Hook + Context + Build 的直接机制。

---

## 7. Earliest Duplicate Point

### Cause locations

- **FILE:** `src/api/dsl_parser.py`
- **FUNCTION:** `DSLParserNode._resolve_locked`
- **Hook selection:** approximately `lines 236-276`
- **Context selection:** `lines 207-215`

### Earliest complete equivalent object

- **FILE:** `src/api/dsl_parser.py`
- **FUNCTION:** `DSLParserNode.parse_and_resolve`
- **CODE LOCATION:** `lines 90-117`
- **OBJECT:** execution-local `CompilationPlan`, containing ordered `BeatCompilationResult.beats[].layers[]`

在最后一个 Beat 完成 resolution 后，两条 execution 的完整 visual plan 已可比较。

推荐用于判断等价的现有对象指纹：

```text
tuple(
  (
    beat.beat,
    layer.layer_index,
    layer.asset_type,
    layer.file_hash,
    layer.layout
  )
  for beat in plan.beats
  for layer in layer_index_order
  if layer affects visual rendering
)
```

对本次已验证素材结构，可缩小为：

```text
(
  Hook.layer_index_0.file_hash,
  Context.layer_index_0.file_hash,
  Build.layer_index_0.file_hash
)
```

即：

```text
13 → 28 → 24
```

或：

```text
12 → 18 → 24
```

当上述 visual fingerprint、DSL render settings 和源文件状态相同时，两个 execution 在这里已经“注定”得到相同主视觉输入。

随后：

- `dsl_adapter.py:78-203` 确定性映射同一 ordered layers 为同一 `main_v_track`。
- Compositor 根据相同源视频实际时长产生相同 `GlobalTimeline`。
- Compositor 的 output suffix 不同只改变文件路径，不改变 visual inputs。

`WorkflowContext` 要到 `routes_dsl.py:296-305` 才创建，因此 shared task/TTS identity 不可能反向导致更早发生的 asset collision。

---

## 8. Evidence-to-Code Mapping

| Evidence | OBSERVED EVIDENCE | Code mapping | 能证明什么 |
|---|---|---|---|
| Repro001 duplicate pair | db4d3533、6451b32e 都是 13→28→24；相同 GlobalTimeline 和 decoded master/final video | Hook score Top-1 + Context `random.choice` + fixed Build；无 combination claim | 两次独立 resolution 可以碰撞成同一 visual plan |
| Repro001 audio differs | duplicate visual pair 的 decoded audio 不同 | TTS paths 共享，但 captured final-read 时序不足以闭合具体因果 | audio divergence 原因仍未确定 |
| Repro002 triple | 5a9895d4、470778f4、13e26247 都是 12→18→24；同 master decoded video | Hook workers 读取相同 pre-batch usage；Context 有放回抽取；Build fixed | 选择策略与三重组合碰撞直接吻合 |
| Repro002 exact pair | 470778f4、13e26247 final file/video/audio/master 全相同 | 相同 visual plan 已解释 video；共享 TTS path可能增加 final 相同概率 | full exact duplicate 的 audio 部分不能仅靠静态代码归因 |
| Shared task UUID | batch 内 TTS/history 使用同一 UUID | `task_id` 只生成一次；所有 child 共用 | shared task identity **VERIFIED** |
| Different master suffix | 每 output 有不同 8-char suffix | batch worker 为每 child 生成 `file_sid`；Compositor 读 config session ID | master/final output path collision **DISPROVED** |
| Shared MP3/VTT/ASS | 四 worker 使用同一 voice/sub path | TTS/Subtitle 读 full `context.session_id` | intermediate writable path isolation defect **VERIFIED** |
| TaskHistory UNIQUE | Repro001/002 各出现三次 UNIQUE failure | 每 worker INSERT，同一 unique task_id | history persistence placement defect **VERIFIED** |
| Current history rows | batch4 history row 只保留一个 output asset | first successful child wins；batch aggregate 不写 history | 其余三个 output history 丢失 |
| Repro003 | batch1 只有一个 plan/chain，无 UNIQUE collision，选 16→28→24 | 单 worker只 INSERT 一次；当时16为 Hook 最低 usage | 是 single-item control，不是 strict batch-size A/B |
| Repro003 prompt differs | natural-language prompt 不同 | Draft/DSL 可能不同 | 禁止据此宣告 concurrency 是唯一根因 |

---

## 9. Root Cause Table

| Candidate cause | Status | 判定 |
|---|---|---|
| Effective asset selection occurs only before batch expansion | **DISPROVED** | batch 前 plan 仅校验；workers 实际重新选择 |
| Same resolved plan copied to workers | **DISPROVED** | 传入的是 raw DSL |
| Shared raw DSL payload | **VERIFIED** | 同一对象引用传入四线程，但当前只读 |
| Shared task identity | **VERIFIED** | 四 worker 共用 task_id |
| Missing formal batch identity | **VERIFIED** | `batch_id` **NOT PRESENT** |
| Missing variant/execution identity | **VERIFIED** | 只有 file suffix，没有正式 child identity |
| Shared mutable Context | **DISPROVED** | 每 worker 新建 Context |
| Shallow-copy contamination | **DISPROVED** | 无 Context copy；plan/timeline 新建 |
| Shared payload mutation contamination | **DISPROVED** | parser 未修改输入 DSL |
| Identical per-execution seed | **DISPROVED** | 没有 per-execution seed |
| Module-global shared RNG | **VERIFIED** | `random.choice/random.random` 共用 module state |
| Purely deterministic Top-1 selection | **DISPROVED** | Hook 是 ranked Top-1，但同分含随机；Context 是 random choice |
| Random collision | **VERIFIED** | Context 和 Hook tie-break 都允许并与结果一致 |
| Usage-count stale snapshot / feedback race | **VERIFIED** | Hook workers 在任何 usage 更新前完成选择 |
| Concurrent usage increment lost update | **NOT ENOUGH EVIDENCE** | read-modify-write 有风险，但本 evidence 未证明丢增量 |
| No batch reservation/combination state | **VERIFIED** | 当前路径不存在 |
| Candidate shortage | **DISPROVED** | 源码、DB 和三轮实际命中证明多候选有效 |
| Hook locked-X tag fallback is used | **VERIFIED** | Hook hash 只有 BGM/Y，X 来自 tag fallback |
| Fallback collapses Hook to one valid candidate | **DISPROVED** | 四个 Hook videos 均有效 |
| Identical effective asset sequence | **VERIFIED** | Repro001/002 原始证据 |
| Identical timeline | **VERIFIED** | Repro001/002 原始证据 |
| Final/master output path collision | **DISPROVED** | `file_sid` 隔离 |
| Shared TTS/subtitle writable path | **VERIFIED** | 源码与并发日志共同证明 |
| Shared TTS path causes master visual duplicate | **DISPROVED** | master visual 在 final audio/subtitle mix 之前确定 |
| Shared TTS path explains exact observed audio grouping | **NOT ENOUGH EVIDENCE** | final read/write overlap在捕获日志中未成立 |
| TaskHistory UNIQUE collision | **VERIFIED** | N inserts + one shared unique task_id |
| Cache involvement | **NOT ENOUGH EVIDENCE** | 当前主链机制为 **NOT ESTABLISHED** |
| Concurrency is required for any duplicate | **DISPROVED** | 有放回选择即使串行也可碰撞 |
| Concurrency amplifies Hook reuse | **LIKELY** | concurrent workers看不到 post-render usage feedback，证据与代码强吻合 |

### Cache check

当前主链未发现：

- render result cache
- resolver result cache
- timeline cache
- DSL result cache
- TTS result reuse
- final result reuse

UI 的 `initialTracksCache` 是编辑器 reset snapshot；SQLAlchemy engine cache 是连接基础设施；它们不复用 resolved plan 或 render result。

结论：cache root cause **NOT ESTABLISHED**。

---

## 10. Primary vs Secondary Bugs

### PRIMARY CAUSES

1. **Combination-unaware selection**

   Hook 和 Context 都是按 Beat 独立选择，系统没有记录或拒绝已出现的完整有序组合。

2. **Selection with replacement**

   Context 明确使用 `random.choice` 有放回抽取；Hook 同分随机排序也允许多个 execution 得到同一 Top-1。

3. **Hook feedback arrives too late**

   Hook 使用 `usage_count` 作为 ranking 维度，但 usage 只在完整 render 之后更新。四 worker 在选择阶段看到同一旧状态，无法感知兄弟 execution 已选中的 Hook。

直接故障链：

```text
same unresolved DSL
→ four worker-local resolves
→ same DB usage snapshot
→ Hook ranked selection can repeat
→ Context random choice can repeat
→ Build fixed
→ no complete-combination claim
→ equal CompilationPlan visual fingerprint
→ equal Timeline/GlobalTimeline
→ equal master visual
```

### SECONDARY DEFECTS

1. **Shared task identity / missing execution identity**

   与视觉 resolver 无数据依赖，是 **INDEPENDENT DEFECT**。它与 visual duplication 是同一 batch execution model 暴露出的 sibling defect，不是同一直接因果链。

2. **TaskHistory persistence boundary错误**

   当前模型意图是 one row per submitted task/batch：

   - `TaskHistory.task_id` unique。
   - 一行同时包含 `batch_size` 和列表型 `output_assets`。
   - 旧 Matrix 路径先聚合 outputs，再写一行 history。

   DSL 路径却在每个 child 内 INSERT。因此即使四 workers 串行执行，第二次起仍会 UNIQUE；并发只决定哪一个 output first-wins。

3. **TTS/VTT/ASS shared writable namespace**

   `TTSNode` 对共享 MP3 使用 `"wb"`，对 VTT 使用 `"w"`；Subtitle 对共享 ASS 使用 `"w"`，均无 lock、临时文件或 atomic rename。

   Repro002 已观察到第一个 worker 读取共享 VTT 后，其他 TTS workers 仍会覆盖同一路径。

   但 captured final FFmpeg commands 都在最后一次 TTS/subtitle write 完成约 25–28 秒后才启动。因此：

   - 并发 overwrite risk：**VERIFIED**
   - final 在 sibling writer 写入时读取：本次 **NOT OBSERVED**
   - 对 Repro001/002 audio hash pattern 的直接解释：**NOT ENOUGH EVIDENCE**

4. **BGM Y-layer duplicated**

   Drawer 会把轨道 semantic tags PATCH 到新拖入的 physical asset。Repro001 日志显示 `44444.mp3` 获得 Hook tag。

   Locked resolver 随后：

   - 按 hash 添加一次 BGM Y layer；
   - 再按相同 semantic tag 查询 Y layer，又添加一次；
   - 两集合没有去重。

   Repro001/002 final FFmpeg commands 均可见同一 `44444.mp3` 两次输入。它可能影响音频语义，但与 master visual duplicate 无关。

5. **Preview plan 不代表实际 render plan**

   `/submit-dsl` 响应中的前置 `CompilationPlan` 被丢弃；workers 会重新随机 resolve。它是 observability/contract defect，不是 duplicate 的直接原因。

---

## 11. AI Draft vs Blind Mode Architecture Comparison

| 维度 | AI Draft | Blind / 极速闭眼 |
|---|---|---|
| 前端触发 | 先 `/draft-blueprint`，用户编辑战术板 | prompt 非空且战术板无 blocks |
| submit timeline | 非空 raw DSL | `timeline=[]` |
| Backend 判定 | `_is_blind_fission=False` | prompt + empty timeline → true |
| Director 调用 | Draft 阶段调用一次 | 每个 render worker 独立调用 |
| Candidate representation | 用户编辑后的 tag/hash mix | Director 每 worker生成的 tags/DSL |
| Hook/Context selection | 本 evidence：locked fallback + locked multi-hash | 通常进入 tag/smart resolver，具体取决于 Director 输出 |
| Resolver | `DSLParserNode` | 同一个 `DSLParserNode` |
| Context | 每 execution 新建 | 每 execution 新建 |
| Batch worker | `render_batch_worker` | 同一个 worker model |
| Timeline compiler | `compile_plan_to_timeline` | 相同 |
| Compositor | `FFmpegCompositorNode` | 相同 |
| Usage logic | render 后更新 | 相同 |
| Identity/history/TTS defect | 存在 | 共享同一实现，架构上也存在 |
| 正式 duplicate evidence | 有 | 无 |

Blind 路径：

```text
empty timeline + prompt
→ each worker fetches available tags
→ each worker DirectorNode.draft_blueprint(temp=0.92)
→ worker-local DSL
→ _parse_plan_from_db
→ DSLParserNode
→ CompilationPlan
→ common render pipeline
```

两条路径最早汇合于：

```text
routes_dsl._parse_plan_from_db
→ DSLParserNode.parse_and_resolve
→ CompilationPlan
```

之后完全共享 timeline/compositor/identity/persistence 路径。

### Blind-specific source fact

前端虽然把 `user_hard_tags` 放入 submit payload，但 Blind worker 的 Director 调用没有接收这些 hard tags，Blind 创建的 `StoryDSLPayload` 也没有携带它们。前端又已从 prompt 中剥离 `@tag`。

这是 source-verified architecture defect，但没有 Blind reproduction evidence，不能据此宣告 Blind duplicate root cause。

### Confirm-and-Render 命名

“确认并直接渲染”在当前代码中不是独立 mode：

- AI Draft 按钮：emit 回 Workspace，最终走 `/submit-dsl`。
- 从空板手工装填：Drawer 可直接走 `/submit-manual`。
- `/submit-manual` 仍会把 raw DSL 传给 batch workers；由于 `render_worker` 优先处理 `dsl_payload`，batch child 仍重新 resolve。

### Future shared boundary

若未来统一精确组合控制，最合理的 shared boundary 是：

```text
each execution has an effective CompilationPlan
→ batch coordinator checks/claims visual fingerprint
→ compile_plan_to_timeline
```

但这只是架构位置建议，不构成 Blind Mode 根因认定。

---

## 12. Minimal Fix Options

不实施。按 root-cause coverage、改动量、风险和架构正确性排序：

| 排名 | Option | Root coverage | Change size | Regression risk | Architectural correctness |
|---|---|---:|---:|---:|---:|
| 1 | Batch coordinator 在 render 前产生并 claim N 个不同 visual-combination fingerprint，再把 authoritative `CompilationPlan` 交给 workers | 完整 | 中 | 中 | 高 |
| 2 | 保留 per-worker resolve，但在 `CompilationPlan` 边界原子 claim 完整组合；碰撞时带 exclusion 进行 bounded re-resolve | 完整，前提是正确处理 capacity | 小到中 | 中到高 | 中 |
| 3 | 仅把 usage_count 提前原子更新/reserve | 只覆盖 Hook stale ranking，不覆盖 Context collision | 小 | 中 | 低；不可作为独立完整修复 |

Option 1 的关键不是建立新的 Variant Planner 或 DB Ledger，而是在现有 batch coordinator 中完成一个最小的、render-before 的组合协调步骤。

不能使用全局 `used_assets` 简单禁止素材复用：

- Build 必须重复 `24.mp4`。
- Context 只有两个候选，batch4 中单素材重复是合法的。
- 应禁止的是完整有序组合重复，而非任意单 asset 重复。

Independent seed 也不是有效修复；不同 seed 仍允许相同组合。

---

## 13. Does the Fix Need These Concepts?

| Concept | 判定 | 原因 |
|---|---|---|
| Variant ID | **OPTIONAL HARDENING** | 视觉根因不依赖正式 Variant ID；但 secondary identity/TTS/history 修复需要可靠 child execution namespace，可复用/提升现有 `file_sid` |
| Independent seed | **NOT REQUIRED FOR ROOT CAUSE** | 不能保证无碰撞 |
| Batch reservation | **REQUIRED NOW** | 需要一个 batch-local、原子的组合 claim 或等价串行规划；不要求 DB Ledger |
| Used-assets state | **NOT REQUIRED FOR ROOT CAUSE** | 单 asset 必须允许复用；完整组合才是正确约束 |
| Combination fingerprint | **REQUIRED NOW** | 是精确识别 `Hook→Context→Build` 重复的最小对象 |
| Timeline/render-plan hash | **OPTIONAL HARDENING** | 可做 late-stage safety/observability；根因在更早的 CompilationPlan 已可识别 |
| DB schema change | **NOT REQUIRED FOR ROOT CAUSE** | in-memory batch claim 足够；现有 TaskHistory schema 也已支持一行聚合多个 outputs |
| Diversity Gate | **NOT REQUIRED FOR ROOT CAUSE** | 不需要通用 Gate 子系统；一个窄范围 exact-combination invariant 即可 |

对于 verified secondary defects，一个 execution-scoped identity/namespace 应当修复，但它不必被命名为 Variant ID，也不必引入 schema migration。

---

## 14. Recommended Fix Sequence

1. **先固定测试合同和 execution isolation**

   - 明确 `task_id` 是 batch/UI identity。
   - 统一使用 child namespace 隔离 MP3/VTT/ASS/master/final/cover。
   - 将 TaskHistory 写入移动到 batch aggregate boundary，一行保存全部 outputs。
   - 这一步不声称修复 visual duplication，但能消除测试和观测中的并发污染。

2. **再修主视觉 selection boundary**

   - 在昂贵 render 前形成 N 个 authoritative `CompilationPlan`。
   - 对完整有序 visual fingerprint 做 batch-local claim。
   - 避免 worker 在收到已批准的 plan 后再次随机 resolve。
   - FFmpeg render 本身仍可并发。

3. **最后定义容量不足语义**

   当实际唯一组合数小于 `batch_size` 时必须显式决定：

   - 返回较少 variants；
   - 明确报告 capacity insufficient；
   - 或允许重复并明确标记。

   不能无限 retry，也不能静默退回 duplicate。

4. **Blind Mode 单独验证**

   在 AI Draft 修复和测试稳定后，再以 Blind 专属 evidence 验证是否需要复用相同控制边界；不要从本报告直接推导 Blind 根因。

---

## 15. Tests Required

| Test | 必须断言 |
|---|---|
| `batch_size=1` AI Draft | 原有单执行行为不回归；一条 history；所有路径可用 |
| `batch_size=4`，Hook >1、Context >1、Build=1 | 生成四个不同完整组合；允许 Build 重复 |
| Explicit multi-hash resolver | Context 两候选都可选；不能因排序退化成固定 Top-1 |
| Tag fallback resolver | Hook 查询得到真实四候选；记录 usage ranking；不把 BGM当 X |
| Concurrent selection barrier | 即使四 workers 同时看到相同 usage snapshot，组合 claim 仍保证唯一 |
| Duplicate-combination prevention | 相同 `(Hook,Context,Build)` 不得进入两个 render workers |
| Capacity shortage | 不死循环、不静默 duplicate；返回明确结果 |
| Context isolation | 四个 `WorkflowContext`、plans、timelines、node maps 均不同对象 |
| Intermediate path isolation | 每 child 的 MP3/VTT/ASS path 唯一，无并发 writer |
| Master/final path isolation | 每 child suffix 唯一 |
| History persistence | batch4 正好一条 TaskHistory，`output_assets` 含四项，无 UNIQUE error |
| Usage update | 更新次数/计数正确；并发 increment 不丢失 |
| Same visual-plan fingerprint | 相同 fingerprint 应被 selection boundary 拒绝，而不是等 render 后靠 file hash 才发现 |
| Blind architecture regression | 独立测试 Director-per-worker 与 shared boundary；不能以 AI Draft 测试代替 |
| BGM Y deduplication | 同一个 BGM 不因 hash+tag 被加入两次；作为独立 secondary fix 测试 |

随机相关测试不应依赖概率通过。应使用可控 chooser 或固定候选顺序构造必碰撞场景，验证 combination invariant，而不是“跑很多次希望没有重复”。

---

## 16. Unresolved Questions / Required Instrumentation

### 静态源码已经足够回答的内容

无需 Repro004 即可确认：

- effective selection 发生在 batch expansion 后。
- resolved plan 没有被复制。
- Hook 使用 tag fallback/usage ranking。
- Context 使用有放回 `random.choice`。
- 不存在 batch combination state。
- shared identity 不进入 resolver。
- TTS/subtitle 路径共享。
- TaskHistory collision 的直接原因。

### 尚未完全闭合的问题

1. 现有 evidence 没有保存实际 `/submit-dsl` request body；当前 Hook/Context/Build payload 是截图与确定性 builder 的强推断。
2. 没有日志记录每个 worker 当时看到的完整 candidate IDs、usage、score tuple 和随机熵。
3. Repro001 的 decoded audio 不同，以及 Repro002 部分音频相同的直接机制尚未证明。
4. 没有 Blind Mode 正式 reproduction evidence。
5. 当前链路没有建立 cache 机制，但不能通过现有日志证明任意未来/外部组件绝无缓存。

### Minimal instrumentation 建议

不要执行；如需审计，最小记录如下。

#### Frontend

位置：`WorkspaceView.blindFission`，POST 前。

每次提交记录一次 sanitized payload：

```text
batch_size
blind flag
beat
address_mode
asset_hashes
semantic_tags
target_duration
aspect_ratio
```

#### Batch coordinator

位置：`render_batch_worker`。

每个 child 记录：

```text
task_id
child_index
file_sid
thread_name
submission timestamp
```

#### Resolver

位置：

- `_resolve_locked`
- `_query_by_tags`
- `_score_candidates`

每 Beat 记录：

```text
task_id
file_sid
beat
input asset_hashes
input semantic_tags
effective candidate asset_id/hash
asset_type
usage_count
is_exhausted
matched tags
already-computed score tuple / tie entropy
chosen asset_id/hash
selection monotonic timestamp
```

记录随机 entropy 时必须保存已经计算的值，不能为了日志额外调用一次 `random.random()`。

#### Post-resolution

位置：`render_worker`，`_parse_plan_from_db` 返回后、timeline compile 前。

记录：

```text
task_id
file_sid
ordered visual CompilationPlan fingerprint
all render-relevant layers
```

#### Usage update

位置：`routes_dsl.py:575-602`。

记录：

```text
task_id
file_sid
asset_id
usage before
usage after
commit timestamp
```

#### TTS / Subtitle / Final input

记录：

```text
task_id
file_sid
thread
path
open-start monotonic_ns
close monotonic_ns
size
SHA-256
```

记录点：

- `TTSNode._run_tts_async`：MP3/VTT open/close。
- `SubtitleNode.execute`：VTT read 前后、ASS close。
- Final compositor `Popen` 前：voice/ASS/BGM path、size、hash。

### Repro004 建议

不要执行。若人工决定进行严格实验：

```text
Frozen:
  exact submitted DSL JSON
  exact candidate/tag state
  same DB starting snapshot
  same render settings
  same media files
  same source commit

Run A:
  one submission, batch_size=4

Run B:
  four sequential submissions, batch_size=1
  starting from a separate clone of the same initial DB snapshot
  allow normal usage feedback between B1–B4
```

必须在 timeline compile 前保存每次 `CompilationPlan` visual fingerprint。

单独一次 `batch_size=1` 仍不能证明“没有重复”；四个顺序单任务与一个并发 batch4 的对照，才能检查 late usage feedback 对 Hook reuse 的放大作用。该实验不改变“Context 有放回选择本身即可碰撞”的源码事实。

---

**最终判定：**

AI Draft master visual duplication 的主因是 **batch 内缺少完整 visual-combination coordination**，并由 Hook 的 pre-render shared usage snapshot 和 Context 的 with-replacement random selection共同具体产生。

Shared task identity、TaskHistory UNIQUE collision、共享 TTS/subtitle path 是同一 batch execution model 暴露出的 **独立 secondary defects**；它们不进入 asset resolver，不能解释最早已经形成的重复 `CompilationPlan`、Timeline 和 master visual。

调查到此停止，等待人工 Review。