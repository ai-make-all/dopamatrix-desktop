# INV-001 Gate 2 — Fix Architecture Plan

## 1. Executive Summary

Baseline：

- Branch：`fix/creative-duplicate-detection`
- Commit：`9c03d81391e1b253aef7fe0eaf166efa8d7c228e`
- Worktree：`CLEAN`
- 相对 Gate 1.5 基线，`src/`、`web_ui/`、`tests/` 无代码变化。
- 本轮未修改 repository，未运行测试或视频生成。

推荐的最小正确改造是：

1. 由 `render_batch_worker` 继续承担 batch 生命周期协调，并调用一个小型 planning helper。
2. 对非 Blind DSL，在启动 `ThreadPoolExecutor` 前生成并接受 N 个 authoritative `CompilationPlan`。
3. 使用 resolver-valid layer-0 candidates 做有限、无放回的完整组合规划；随机性不再承担唯一性保证。
4. 用 batch-local fingerprint set 验证 ordered `(beat, layer-0 file_hash)` 不重复。
5. worker 同时接收 `CompilationPlan + raw DSL`，但 plan 优先且禁止重新 resolve；raw DSL 只服务 TTS、字幕和元数据。
6. 为每个已接受 child 创建 full execution UUID；`task_id` 继续是共享 UI/WS/batch identity。
7. TTS/VTT/ASS 使用 full execution namespace；master/final/cover 继续使用其短文件 token。
8. `TaskHistory` 从 worker 移到 batch aggregation boundary，每个成功或部分成功的 submitted task 只写一行。
9. 不引入 DB Ledger、schema migration、持久 reservation、语义相似度或 render 串行化。
10. Blind Mode 只共享 identity、terminal WS 和 persistence 修复；本轮不声称其 visual diversity 已被解决。

---

## 2. Target Batch Variant Planning Contract

### 2.1 非 Blind / AI Draft 目标调用链

```text
POST /api/v1/tasks/submit-dsl
→ RenderDSLRequest
→ StoryDSLPayload
→ request-time preview CompilationPlan
→ shared task_id
→ render_batch_worker              # batch coordinator；batch_size=1 也经过它
    → batch planning helper
        → DSLParserNode 使用当前 resolver eligibility/filter/ranking
        → resolver-valid layer-0 candidate lists
        → finite combination enumeration without replacement
        → authoritative CompilationPlan × M
        → exact visual fingerprint validation
        → PlannedChildExecution × M
    → ThreadPoolExecutor
        → render_worker(
              plan=authoritative_plan,
              dsl_payload=raw_dsl_metadata,
              execution_id=...,
              file_sid=...
          )
            → compile_plan_to_timeline
            → Timeline
            → WorkflowContext
            → TTSNode / SubtitleNode
            → FFmpegCompositorNode
            → CoverNode
            → child result
    → stable child-index aggregation
    → one TaskHistory INSERT
    → one terminal WebSocket event
```

其中：

```text
requested batch_size = N
accepted unique plan count = M
0 <= M <= N
```

如果有效容量不足，`M` 可以小于 `N`，但不得用重复 plan 补足。

### 2.2 Blind Mode 保留路径

```text
render_batch_worker
→ N child executions
→ each worker DirectorNode
→ child raw DSL
→ child CompilationPlan
→ Timeline / render
→ common aggregation / history / terminal WS
```

Blind 当前在 worker 内生成 DSL，不能在不拆分 Director 阶段的情况下直接套用 AI Draft 的 pre-plan-all contract。因此：

- execution isolation、TaskHistory、terminal WS 聚合：共享实施。
- AI Draft exact-combination planning：不自动外推到 Blind。
- Blind exact diversity：需要独立 evidence 和后续两阶段设计。

### 2.3 Contract invariants

- `task_id` 始终表示 submitted task / batch / UI card。
- 每个 accepted child 有且只有一个 execution identity。
- accepted authoritative plan 不得被 worker 静默重新 resolve。
- 同 batch accepted fingerprints 必须唯一。
- 所有 accepted plans 完成后，才允许启动昂贵 render。
- child 不得发送 batch-level terminal `completed/failed`。
- batch 内不需要数据库 reservation。

---

## 3. Variant Planning Design

### 3.1 Planning owner

推荐：

- `render_batch_worker` 保持 batch coordinator。
- 抽取一个小型 helper 负责候选发现、组合枚举、plan materialization 和 fingerprint validation。
- 不创建大型 Planner service、公共 Pydantic schema 或新数据库模型。

职责划分：

```text
render_batch_worker
  owns:
    task lifecycle
    requested batch size
    child identities
    executor launch
    result aggregation
    persistence
    terminal WS

small planning helper
  owns:
    candidate alternatives
    finite combination enumeration
    CompilationPlan acceptance
    exact fingerprint uniqueness
    capacity result
```

resolver eligibility 仍必须由 `DSLParserNode` 提供。不得在 `routes_dsl.py` 复制 `_query_by_tags`、`_score_candidates`、hard-tag veto 或 axis classification。

### 3.2 Plan all first vs incremental submit

| 方案 | Correctness | Complexity | Concurrency | Testability | 判断 |
|---|---:|---:|---:|---:|---|
| 全部 planning 完成后启动 executor | 高 | 低到中 | render 仍完全并发 | 高 | **推荐** |
| plan/claim/submit 交错 | 可实现 | 高 | 可略早启动首个 render | 低 | 不推荐 |
| workers 内独立 resolve 后 claim | 中 | 中到高 | 高 | 中 | 不推荐 |

全量先规划的优势：

- render 前已经知道唯一容量。
- 不会在发现容量不足时已有部分 FFmpeg 在运行。
- 不需要取消或回滚已启动的 child。
- batch-local state 只在一个短时串行阶段读写。
- 测试可以直接检查 accepted plans，不依赖线程时序。

Planning 可以继续发生在 BackgroundTask 中，以保持 HTTP 202 快速返回；要求只是发生在该 background coordinator 启动 executor 之前。

### 3.3 `_parse_plan_from_db()` 的角色

当前 `_parse_plan_from_db()` 可以生成一个 `CompilationPlan`，但不能原样作为可靠的 batch planner，因为：

- Context 多候选使用有放回 `random.choice`。
- Hook fallback 仍可能连续选择相同 `scored_fb[0]`。
- 它不暴露实际有效候选列表。
- 它不接受完整组合选择或 exclusion。

推荐的小调整边界：

1. 让 `DSLParserNode` 提供窄范围的内部能力：

   - 列出每个 Beat 的 resolver-valid main-X candidates。
   - 根据明确的 per-Beat main choice materialize `CompilationPlan`。

2. `_parse_plan_from_db()` 可继续作为单 plan / legacy primitive，或增加可选的 predetermined main-selection 参数。

3. batch planner 使用同一短时 DB read session 完成候选发现和 plan materialization。

不能将“重复调用黑盒 `_parse_plan_from_db()`，直到随机得到不同 plan”作为可靠实现。

### 3.4 Child plan structure

不应只传递 `List[CompilationPlan]`，因为 executor submission 还需要将 identity、plan 和 fingerprint 绑定。

推荐使用内部 frozen dataclass 或等价 typed structure，概念字段为：

```text
child_index
execution_id
file_sid
CompilationPlan
visual_fingerprint
```

它：

- 不是公共 API schema。
- 不是 DB model。
- 不是未来 semantic Variant。
- 不要求命名为 `ChildPlan`。
- 只在一次 batch 生命周期中存在。

`CompilationPlan` 当前不是 type-level frozen model。最小修复不必修改 `schemas.py`，但应：

- 接受时建立独立 deep copy。
- 此后按只读对象处理。
- worker entry 可重算 fingerprint 作为 invariant check。
- 禁止 mutation 后静默 re-resolve。

### 3.5 Preview plan 的使用

非 Blind 请求已经生成 request-time preview plan。推荐：

- 对它执行相同的有效性校验。
- 有效时作为第一个 accepted candidate seed。
- batch planner 枚举其余组合并排除该 fingerprint。
- `batch_size=1` 时直接作为唯一 authoritative plan。

这同时：

- 避免无意义的第二次 resolve。
- 使 response 中的 preview 尽量对应实际第一个输出。
- 复用当前已经存在的 `resolved_plan` 概念。

如果 planning 开始时该 preview 引用的资产已被删除或不再有效，应拒绝 seed 并重新规划，而不是强制 render stale plan。

---

## 4. Exact Diversity Gate Design

这里的 “Gate” 只是一个窄范围 invariant，不创建通用 Diversity Gate 子系统。

### 4.1 Fingerprint

推荐 fingerprint：

```text
tuple(
  (
    beat_index,
    beat.beat,
    0,
    normalize(layer_0.file_hash)
  )
  for beat_index, beat in enumerate(plan.beats)
)
```

其中：

- 使用 `CompilationPlan.beats` 的真实顺序。
- `beat_index` 明确表达位置；即使 Beat 名称重复也不会歧义。
- `layer_index` 固定为 `0`。
- `file_hash` 做大小写和空白规范化。
- accepted AI Draft plan 中，每个当前战术板 visual Beat 应有且只有一个合法 main-X layer。

以当前 INV-001 为例：

```text
(
  (0, "Hook",    0, hash_13),
  (1, "Context", 0, hash_28),
  (2, "Build",   0, hash_24)
)
```

它足够解决 INV-001，因为同一 batch 内：

- target duration、aspect ratio 和 render settings 共享。
- layer-0 file hashes 决定 main track 的 ordered source clips。
- `compile_plan_to_timeline` 对这些 inputs 做确定性转换。
- 已验证重复发生在相同 Hook/Context/Build main sequence。

本 fingerprint 不覆盖：

- Y layers、BGM、SFX。
- 字幕和 TTS。
- semantic/perceptual similarity。
- CLIP、pHash、MMR。
- 跨 batch fatigue。
- 通用 overlay/layout 等价性。

这些均不属于本次 Level 1 causal mechanism。

### 4.2 Batch-local state

仅在本次 planning 生命周期中维护：

```text
accepted fingerprint set
accepted child execution list
planning warnings/counts
```

生命周期：

```text
render_batch_worker starts
→ state created
→ planning accepts/rejects plans
→ executor receives accepted list
→ aggregation completes
→ state released
```

不需要：

- DB table。
- migration。
- persistent Ledger。
- long transaction。
- cross-process lock。
- render serialization。

### 4.3 Collision algorithms comparison

| 算法 | 问题 | 判断 |
|---|---|---|
| 重新 resolve 整个 plan | 仍可能持续命中 Hook Top-1 / Context 同一随机项 | 不可靠 |
| 全局排除 used assets | 会错误禁止 Build 重复，也会减少合法组合 | 不采用 |
| batch-local penalty | 只能降低重复概率，不能保证唯一 | 不采用 |
| 随机 bounded retry | 能终止，但有效替代存在时仍可能错误耗尽 | 不作为主算法 |
| resolver-valid combination enumeration | 有限、无放回、可计算容量、硬唯一 | **推荐** |

### 4.4 推荐算法

1. 对每个 Beat 调用当前 resolver 的候选发现逻辑。
2. 保留当前：

   - DB existence/deleted/exhausted rules。
   - asset axis classification。
   - tag query limits。
   - hard-tag veto。
   - usage/ranking rules。

3. 每个 Beat 的 main candidates 按 `file_hash` 去重。
4. 当前 scoring 只决定候选优先顺序，不再决定唯一性。
5. 对候选列表做 lazy Cartesian combination enumeration。
6. 每个完整组合最多访问一次。
7. 用明确的 main selection materialize 一个 `CompilationPlan`。
8. 计算 fingerprint。
9. fingerprint 未使用且 plan 可渲染时接受。
10. 达到 `batch_size` 或有限组合空间耗尽时停止。

对于当前 evidence：

```text
Hook effective candidates
× Context effective candidates
× Build effective candidates
```

Build 的单候选可以在所有不同组合中重复。约束对象是完整 fingerprint，而不是单 asset。

### 4.5 Retry budget

推荐：

```text
random re-resolve retry budget = 0
```

有界性来自有限组合规划：

```text
each unique candidate tuple is visited at most once
stop when:
  accepted_count == requested batch_size
or:
  finite effective space is exhausted
```

如果在按 hash 去重并强制 main selection 后仍产生重复 fingerprint，说明：

- materialization 没有遵守指定 selection；
- candidate normalization 有 bug；
- planner invariant 被破坏。

该情况应记录结构化错误并拒绝该 child，不能再次随机 resolve。

### 4.6 Effective capacity

必须区分：

```text
user-visible theoretical capacity
!=
resolver-valid candidate capacity
!=
successfully materialized effective capacity
```

实际 capacity 必须在以下步骤后确定：

- asset DB 命中。
- deleted/exhausted 过滤。
- X/Y axis 分类。
- hard-tag veto。
- tag query limit。
- file-hash 去重。
- main layer validation。
- plan materialization。

因此 `4 × 2 × 1 = 8` 不能直接作为通用 capacity 结论。

---

## 5. Authoritative CompilationPlan Handoff

### 5.1 Worker contract

推荐非 Blind 分支顺序：

```text
if authoritative plan is present:
    working_plan = authoritative plan
    raw DSL remains metadata-only
elif raw DSL is present:
    legacy resolve fallback
else:
    fail
```

Blind 分支暂时保持：

```text
if blind_dsl and no authoritative blind child plan:
    DirectorNode
    → child DSL
    → resolve
```

核心 invariant：

> accepted authoritative visual plan must not be silently replaced by worker-side resolution.

### 5.2 `plan is not None` vs `resolve_assets=False`

推荐使用：

```text
plan is not None
→ plan is authoritative
```

不推荐额外 `resolve_assets=False` flag。

原因：

- flag 会制造 `False + no plan` 非法组合。
- `plan + resolve_assets=True` 的优先级不明确。
- 调用方可能忘记同步 flag。
- `plan` 本身已经是足够明确的 capability signal。
- 对旧调用方只传 raw DSL 的行为仍可兼容。

### 5.3 Raw DSL 保留职责

`dsl_payload` 继续提供：

- Beat `script_text` 聚合。
- subtitle duration。
- social metadata。
- history request metadata。
- Blind 生成后的 child script data。

它不再参与已批准 child 的 visual asset selection。

无需将 raw DSL 与 plan 合并成巨大新对象。

### 5.4 Worker 职责变化

```text
BEFORE:
select
→ resolve
→ plan
→ timeline
→ context
→ TTS/subtitle/render
→ history
→ terminal WS

AFTER:
consume approved plan
→ timeline
→ child context
→ TTS/subtitle/render
→ return structured child result
```

继续保留在 worker 的职责：

- `compile_plan_to_timeline`
- `WorkflowContext` construction
- TTS
- Subtitle
- FFmpeg
- Cover
- output hash collection
- 当前 usage update
- child-level logging

退出 worker 的职责：

- 非 Blind asset selection
- TaskHistory INSERT
- batch completion determination
- terminal task WebSocket

`/submit-dsl`、`/submit-manual` 和 non-Blind `/render-dsl` 都共享 worker，因此必须一起遵守 plan-first contract。不能把同一个 preview plan复制给 N 个 children。

---

## 6. Child Execution Identity

### 6.1 Identity layers

| Identity | 语义 | 生命周期 |
|---|---|---|
| `task_id` | submitted task / batch / UI / WS identity | 整个 batch |
| `execution_id` | 一次 child render execution | 单 child execution |
| `file_sid` | 从 execution ID 派生的短输出命名 token | 单 child execution |
| future `variant_id` | semantic/product Variant identity | **本轮不存在，也不创建** |

`WorkflowContext.session_id` 继续等于 shared `task_id`。

### 6.2 Options comparison

| Option | 优点 | 缺点 | 判断 |
|---|---|---|---|
| 继续只用 8-char `file_sid` | 改动最小 | 无完整 identity、日志语义和生命周期 | 不推荐 |
| full child UUID + short suffix | 隔离可靠、日志可关联、兼容现有输出名形态 | batch1 输出 suffix 来源变化 | **推荐** |
| `task_id + child index` | 可读、batch 内唯一 | 重试/排序耦合，用户 session_id 可控，文件名长 | 不推荐 |
| 新 DB Variant ID | 可持久化 | 超出本轮，需 schema | 不采用 |

### 6.3 Recommended lifecycle

1. duplicate planning candidate 不分配 identity。
2. plan 被 batch planner 接受后生成一次 full UUID。
3. 将其与 `child_index + plan + fingerprint` 绑定。
4. 派生短 `file_sid`，并在当前 batch 内检查短 suffix 唯一。
5. worker、结果、日志和 history metadata 全程携带 full ID。
6. 真正重跑 child 时生成新的 execution ID。
7. execution ID 不等同于未来 semantic variant ID。

`batch_size=1` 也应生成 full execution UUID，避免继续保留两套 child identity 规则。

### 6.4 Context propagation

推荐最小传播：

```text
context.session_id = task_id

context.config["execution_id"] = full execution UUID
context.config["file_sid"] = short output suffix
context.config["session_id"] = short output suffix   # 迁移期兼容 compositor/cover
context.config["child_index"] = child index
```

因此本轮不强制修改 `WorkflowContext` 类型定义。

### 6.5 WebSocket

- `taskId` 继续只使用 shared `task_id`。
- 不为每个 child 创建新的 UI task card。
- running/progress 可以添加可选：

```text
executionId
childIndex
```

- terminal event 只由 coordinator 发一次。
- `DSLSubmitResponse.task_ids` 不应填入 execution IDs；当前它实际承载的是 shared task identity，字段描述与运行语义的不一致可后续清理。

---

## 7. TTS / Subtitle Isolation

### 7.1 Path contract

推荐：

```text
voice_<full-execution-id>_<lang>.mp3
voice_<full-execution-id>_<lang>.vtt
sub_<full-execution-id>_<lang>.ass
```

使用 full UUID 的原因：

- 这些是 writable intermediate files。
- `wb` / `w` 会截断现有内容。
- full UUID 消除 batch 内共享路径和 8-char 理论碰撞。
- Windows 路径长度影响可忽略。

master/final/cover 可以继续使用短 suffix：

```text
master_video_<file_sid>.mp4
final_<lang>_<file_sid>.mp4
cover_<file_sid>.jpg
```

full `execution_id` 是 identity authority；`file_sid` 只是输出 token。

### 7.2 Node changes

- `TTSNode` 不再读取 shared `context.session_id` 构造 MP3/VTT。
- `SubtitleNode` 不再读取 shared `context.session_id` 构造 ASS。
- 两者读取明确的 execution namespace。
- 缺失 execution identity 应 fail fast 或使用仅限 legacy direct-call 的明确 fallback，不能在 batch 路径回退到 shared task ID。

### 7.3 Failure policy

本轮不重新定义 TTS/Subtitles 产品级 fallback：

- `enable_tts=False`：保持跳过。
- `enable_subtitles=False`：保持跳过。
- 无文本导致 node skip：保持。
- 写入/执行异常：该 child 失败，兄弟继续。
- 已存在但未形成 final output 的 master/partial artifact 不计为成功结果。

---

## 8. TaskHistory / Persistence Boundary

### 8.1 Row semantics

`TaskHistory` 应保持：

```text
one row per submitted task / batch
```

依据：

- `task_id` 唯一。
- 模型拥有 `batch_size`。
- `output_assets` 本身是 JSON collection。
- 旧 Matrix 路径先聚合所有 outputs，再 INSERT 一行。
- history/approval readers 已按一行包含多个 assets 工作。

不应把 `task_id` 改成 child execution ID 来绕过 UNIQUE constraint。

### 8.2 Worker responsibility removal

`render_worker` 不再执行：

```text
TaskHistory(...)
db.add(...)
db.commit()
```

worker 返回内部 child result，建议至少包含：

```text
child_index
execution_id
file_sid
fingerprint
assets
outcome
error_code
elapsed
working plan snapshot/reference
```

这不是 API 或 DB schema。

### 8.3 Aggregation boundary

`render_batch_worker` 已经拥有：

- futures completion。
- `all_assets`。
- task ID。
- request metadata。
- batch timing。

因此它是最小正确 persistence boundary。

所有提交路径，包括 `batch_size=1`，应经过同一个 coordinator/finalizer。单 child 可直接调用 worker，不必一定创建 `ThreadPoolExecutor(1)`。

### 8.4 History row contents

推荐：

- `task_id`：shared submitted task ID。
- `prompt`：原请求 prompt。
- `batch_size`：requested count。
- `duration`：planning + concurrent render 的 coordinator wall-clock 时间。
- `output_assets`：仅成功 final outputs。
- `prompt_details`：

```text
meta                         # 保持现有 key
timeline                     # 首个 accepted plan，兼容旧 reader
planning_summary:
  requested_count
  planned_count
  succeeded_count
  failed_count
  warning_codes
children:
  child_index
  execution_id
  visual_fingerprint
  accepted plan snapshot
  outcome
  output hashes
```

只进入日志、不持久化：

- rejected candidate 全量明细。
- 每次 combination iterator trace。
- traceback。
- 高频 progress。
- RNG/tie-break 调试细节。

### 8.5 Persistence ordering

推荐 finalization 顺序：

```text
aggregate child results
→ write one TaskHistory row
→ emit one terminal WS
```

如果 history 写入失败：

- 已成功落盘的视频不能被反向判为 render failure。
- terminal WS 保持 `completed/partial`，附加 `historyPersisted=false` warning。
- 记录 error log。

如果零 final outputs：

- 发送 `failed`。
- 不写空 TaskHistory，因为当前 model 没有 status 字段，现有 history UI 会把任何 history row 当作 completed。

---

## 9. Capacity and Failure Semantics

### 9.1 WebSocket status contract

不要新增 `"partial"` status。当前前端状态机只有：

```text
pending
running
completed
failed
```

推荐：

```text
status = "completed"   if succeeded_count > 0
status = "failed"      if succeeded_count == 0
```

附加向后兼容字段：

```text
partial
requestedCount
plannedCount
succeededCount
failedCount
warningCodes
assets
```

旧前端会忽略未知字段。若产品要求 UI 明确展示 warning，可小幅扩展 Queue UI，但不改变 task status 枚举。

### 9.2 Required cases

| Case | 推荐行为 |
|---|---|
| 1. 请求 4，规划 4 unique，全部成功 | 并发 render 4；一次 `completed` WS；一条 history，4 outputs |
| 2. 请求 4，只能规划 3 unique | 只 render 3；禁止复制；`completed + partial=true + INSUFFICIENT_UNIQUE_CAPACITY`；history `batch_size=4`、outputs=3 |
| 3. 某 candidate plan unresolved | 不交给 worker；从有限候选空间尝试下一不同组合；已接受 siblings 不回滚；最终零 plan 则 failed、不开 executor |
| 4. planning 成功，某 render child 失败 | 其他 children 继续；至少一项成功则 completed/partial 和一条 history；全失败则 failed/no history |
| 5. 同 fingerprint 多次 collision | 不随机重试、不 duplicate fallback；每个 unique tuple 最多访问一次；空间耗尽后按 capacity shortage 表达 |
| 6. TTS/Subtitle 某 child 失败 | 保持现有 node 级行为；只影响该 child；master-only/orphan artifact 不进入 outputs/history |

### 9.3 Output ordering

当前 `as_completed` 会让 `all_assets` 顺序随线程完成顺序变化。

引入 `child_index` 后应：

```text
collect results by child_index
→ stable sort
→ flatten assets
```

这样：

- history output 顺序稳定。
- plan/fingerprint/output 映射可审计。
- 测试不依赖线程调度。

### 9.4 No silent duplicate fallback

任何情况下都禁止：

```text
unique capacity < requested batch_size
→ clone accepted plan to fill requested count
```

如未来产品需要允许 duplicate fallback，必须是显式用户选项；不属于本次默认语义。

---

## 10. Secondary BGM Dedup

该项是独立 audio defect，不属于主视觉 planning。

### 10.1 Fix boundary

位置：

```text
DSLParserNode._resolve_locked
hash-resolved Y collection
+
semantic Y query
→ merge boundary
→ layer construction/index assignment
```

推荐在同一 Beat 内维护：

```text
seen_y_asset_ids
```

过程：

1. physical hash Y 加入时登记 `asset.id`。
2. semantic Y query 返回后，已有 ID 跳过。
3. 新 ID 保留并登记。
4. layer index 保持连续。

### 10.2 Dedup identity

推荐：

```text
asset_id
```

原因：

- 当前 defect 是同一 DB asset 从两条路径进入。
- `LocalAsset.file_hash` 当前也是 unique，但 `asset_id` 更直接表达 resolver object identity。
- 不需要 hash normalization。
- 不会错误合并未来可能具有不同业务身份的独立资产记录。

### 10.3 Legal multiple Y layers

保持：

- 不同 asset IDs 的多个 BGM/SFX/overlay。
- 同一资产在不同 Beats 中出现。
- physical Y 的原始顺序。
- semantic query 中其他独立 Y assets。

仅删除同一 Beat 内、同一 asset 通过 hash 和 semantic 两条路径重复进入的 layer。

建议独立 commit。

---

## 11. Concurrency Model

### 11.1 ThreadPoolExecutor 前

串行、短时：

```text
candidate discovery
resolver filtering/ranking
candidate hash dedup
combination enumeration
CompilationPlan materialization
fingerprint computation
duplicate accept/reject
capacity decision
child execution identity creation
```

特点：

- 只读 DB session。
- 不持有 render 期间 transaction。
- 不写 persistent reservation。
- 不依赖 usage_count 更新实现 sibling coordination。

### 11.2 继续并发

```text
compile_plan_to_timeline
WorkflowContext creation
TTS
VTT
Subtitle ASS
FFmpeg master
final mux
Cover
output hashing
```

`Timeline` compile 可以保留在 worker，因为：

- plan 已经冻结。
- adapter 不负责 asset selection。
- 每 child 创建独立 Timeline 和 Context。
- 可以减少 coordinator 工作并保留现有边界。

### 11.3 Executor 后

串行聚合：

```text
child result collection
stable child ordering
success/partial/failure calculation
one TaskHistory persistence
one terminal WS
```

### 11.4 Terminal WS ownership

当前仅抑制 child `completed`，但预检和 Compositor 仍可发 shared-task `failed`。

应将 contract 升级为：

```text
coordinator mode:
  child suppresses all terminal completed/failed
  child may emit running/progress with execution correlation
  coordinator emits exactly one terminal event
```

否则一个 child 可以先把整批 UI task 标为 failed，随后 coordinator 又发 completed。

---

## 12. Backward Compatibility

| Area | 影响与策略 |
|---|---|
| AI Draft | 预期行为变化：同 batch exact main combination 唯一；preview 可作为第一个 authoritative plan |
| Blind Mode | 不套用 AI Draft pre-planner；继续 worker-local Director/resolve；共享 identity/history/terminal WS 修复 |
| `batch_size=1` | 通过统一 coordinator/finalizer；复用 preview plan；生成正式 child execution ID；仍只有一个 task/history |
| `batch_size>1` | 所有 accepted plans 在 executor 前完成；render 并发不变 |
| `/submit-manual` | 同为 non-Blind DSL，必须创建 N plans；不能复用同一 preview plan给所有 children |
| `/render-dsl` | timeline 非空时遵守相同 plan-first contract |
| TTS disabled | execution namespace 注入但节点不运行，无功能变化 |
| Subtitles disabled | 同上 |
| Frontend submit payload | 不需要修改 |
| `task_id` / UI card | 保持一个 shared task ID |
| WebSocket status | 保持四态；只增加可选 partial/count/correlation 字段 |
| TaskHistory readers | 一行多 assets 与现有 reader 一致；`prompt_details` additive fields 后向兼容 |
| Approval/Matrix readers | 继续按 shared `task_id + asset hash` 工作 |
| Output/runtime path | 保持 `output/` 平面目录和 master/final/cover 命名形态；中间文件 token 改为 full execution UUID |
| Installer/Tauri/runtime cwd | 不需要修改 |
| Usage count | 仍在 render 后更新；不再被视作 batch coordination mechanism |

Blind Mode 的风险必须单独测试，但不能把 AI Draft evidence 表述为 Blind root-cause proof。

---

## 13. File Impact Map

### MUST CHANGE

- `src/api/routes_dsl.py`

  - batch planning coordinator。
  - plan-first worker contract。
  - internal child plan/result structures。
  - execution identity。
  - batch_size=1 finalizer。
  - one-row TaskHistory。
  - terminal WS ownership。
  - stable aggregation。

- `src/api/dsl_parser.py`

  - resolver-valid main-candidate discovery。
  - explicit main-selection materialization boundary。
  - BGM Y-layer dedup。

- `src/nodes/tts_node.py`

  - MP3/VTT 使用 execution namespace。

- `src/nodes/subtitle.py`

  - ASS 使用 execution namespace。

- `src/nodes/compositor.py`

  - coordinator mode 下抑制 child terminal `failed`。
  - 可选 execution correlation。
  - master/final suffix contract保持。

- 新增 INV-001 focused tests，例如：

  - `tests/test_inv001_batch_planning.py`
  - `tests/test_inv001_execution_isolation.py`

### LIKELY / CONDITIONAL CHANGE

- `web_ui/src/workers/queueWorker.ts`
- Queue 展示组件

仅当 Gate 3 要求在 UI 上显示 `partial/warning`。不能新增 `partial` task status。

- `src/core/context.py`

仅当实现时决定把 `execution_id/file_sid/child_index` 作为显式 optional fields；推荐最小方案先使用清晰的 config keys，因此不是必改。

### SHOULD NOT CHANGE

- `src/api/dsl_adapter.py`
- `src/api/schemas.py`
- `src/api/models.py`
- 数据库 schema / migration
- `src/api/services.py`
- `src/nodes/cover_node.py`
- `web_ui/src/views/WorkspaceView.vue`
- `web_ui/src/views/DslOrchestratorDrawer.vue`
- installer / build / Tauri 配置
- frontend submit payload

`CompilationPlan`、request/response 和 TaskHistory 现有 schema 已足够；无需为了内部 child execution structure 创建正式 schema。

---

## 14. Implementation Slices / Commit Plan

推荐顺序不是先写一个巨大 Batch Planner commit。

### Slice B — Execution Isolation

- full child execution UUID。
- short `file_sid` derivation/uniqueness。
- child identity propagation。
- TTS/VTT/ASS namespace。
- structured child logs。
- internal child result envelope。

原因：先消除共享 writable paths，后续并发测试才可信。

### Slice C — Persistence / Terminal Boundary

- coordinator 独占 terminal WS。
- suppress all child terminal events。
- `render_worker` 移除 TaskHistory INSERT。
- batch aggregate 写一行。
- batch_size=1 也走同一 finalizer。
- stable child-index output ordering。
- partial/failure count contract。

原因：为 primary planning 提供干净的 batch lifecycle boundary。

### Slice A — Batch Visual Planning

- resolver-valid candidate exposure。
- finite combination enumeration。
- exact fingerprint。
- batch-local accepted set。
- capacity semantics。
- authoritative plan handoff。
- worker plan-first。
- preview plan seed。

该 slice 完成后才真正关闭 verified primary causal mechanism。

### Slice D — Secondary BGM Dedup

- `asset_id` dedup。
- 独立 unit test。
- 不与 visual planning 逻辑混合。

### Slice E — Full Regression

- Repro001/002 frozen inputs。
- batch4 concurrency。
- intermediate path isolation。
- one history row。
- one terminal WS。
- Blind architecture regression。

每个 slice 自带对应 unit tests；Slice E 只负责跨 slice 回归，不能把全部测试推迟到最后。

---

## 15. Test Plan

本节仅设计，不执行测试。

### 15.1 Unit tests

#### Fingerprint

- 相同 ordered Beat/layer-0 hash → 相同 fingerprint。
- 任一 layer-0 hash 不同 → 不同。
- Beat 顺序不同 → 不同。
- Y/audio layers 不影响本次 fingerprint。
- missing/duplicate main layer → planning validation failure。
- hash 大小写规范化。

#### Combination planning

- candidate list 按 file hash 去重。
- finite enumeration 不重复。
- Build 单候选可以在所有组合中复用。
- preview seed 不会再次进入 accepted list。
- effective capacity 2、request 4 → 只返回 2。
- space exhaustion 后立即终止。
- 不调用随机 whole-plan retry。
- fingerprint invariant failure 不进入 executor。

#### Authoritative handoff

同时传：

```text
plan != None
dsl_payload != None
```

断言：

- `_parse_plan_from_db` 调用次数为 0。
- `compile_plan_to_timeline` 使用传入 plan。
- raw DSL 仍提供 TTS script。
- raw DSL 仍提供 subtitle duration。
- raw DSL meta 仍进入 output/history metadata。

#### Identity

- N full execution UUID 唯一。
- short suffix batch 内唯一。
- batch_size=1 也有 execution ID。
- execution ID 不等于 task ID。
- rerun 产生新 execution ID。

#### TTS/Subtitle

- MP3/VTT/ASS 包含 full execution namespace。
- 两个 concurrent child 路径不同。
- 不含 shared task ID 作为唯一 token。
- disabled 时不创建路径。

#### TaskHistory / WS

- worker 不 INSERT history。
- coordinator 只 INSERT 一行。
- child terminal WS 被完全抑制。
- coordinator 只发送一次 terminal。
- partial 使用 completed + optional fields。
- 全失败不写空 history。

#### BGM

- 同 asset ID 从 hash + semantic 命中只保留一次。
- 不同 Y asset IDs 全部保留。
- layer index 连续。
- 不同 Beat 不做跨 Beat dedup。

### 15.2 Integration tests

使用：

- isolated/in-memory tenant DB。
- fake/mocked FFmpeg。
- mocked edge-tts。
- temporary output directory。
- fake WS manager。
- thread barrier 强制 concurrent child execution。

覆盖：

1. `batch_size=1`。
2. `batch_size=4`。
3. Hook 多个 resolver-valid candidates。
4. Context 多个 physical candidates。
5. Build 固定单候选。
6. same raw DSL → four authoritative plans。
7. accepted fingerprints 全部唯一。
8. 每个 worker 不重新 resolve。
9. Timeline/Context 为独立对象。
10. MP3/VTT/ASS paths 全部不同。
11. master/final/cover suffix 全部不同。
12. TaskHistory 恰好一行。
13. output_assets 与成功 children 数一致。
14. 一个 child 失败，其余继续。
15. 全部失败时一次 failed WS、无 history。
16. child failure 不提前改变 shared task 终态。
17. `/submit-dsl`、`/submit-manual`、`/render-dsl` non-Blind contract 一致。
18. TTS/Subtitles 开关回归。

### 15.3 Regression tests

冻结 Repro001 / Repro002 对应的 DSL 和 candidate DB state，不运行正式视频：

```text
Hook candidates > 1
Context candidates > 1
Build = fixed
batch_size = 4
```

断言：

- 有效替代组合存在时，accepted visual fingerprints 无重复。
- 不依赖“多运行几次大概率不重复”。
- 同 fingerprint 永远不会进入两个 render workers。
- TaskHistory 无 UNIQUE collision。
- TTS/VTT/ASS 无共享 writable path。
- 只有一个 terminal WS。

Repro003 用于确认 batch_size=1 路径兼容，不把它当作 concurrency 根因证明。

Blind regression 只验证：

- Director 仍在 child worker 路径执行。
- 不会错误接受空 preview plan 为 authoritative render plan。
- identity/history/terminal changes 不破坏现有执行。

不声称 Blind diversity 已被验证。

---

## 16. Design Decision Table

| Decision | RECOMMENDED OPTION | ALTERNATIVES CONSIDERED | WHY | REGRESSION RISK |
|---|---|---|---|---|
| 1. Batch planning location | `render_batch_worker` 作为 coordinator，调用小 helper；plan all before executor | 大型 planner service；worker 内 claim；incremental submit | 复用现有 batch 生命周期和 aggregation boundary，render 保持并发 | 中 |
| 2. Authoritative handoff | `plan is not None` 即 authoritative；raw DSL metadata-only | `resolve_assets=False` flag；DSL 永远优先 | 单一优先级，无非法 flag 组合，兼容 raw-only callers | 中 |
| 3. Exact fingerprint | ordered `(beat_index, beat identity, layer_index=0, normalized file_hash)` | Timeline hash；全 layer hash；pHash/CLIP | 最早现有对象，精确覆盖 INV-001 main visual sequence | 低 |
| 4. Collision algorithm | resolver-valid candidate enumeration without replacement | whole-plan retry；used-assets exclusion；penalty；random retry | 唯一同时保证有限终止、容量可知和完整组合唯一的方案 | 中 |
| 5. Retry budget | 零次随机 re-resolve；每个 unique tuple 最多访问一次 | 固定 N 次随机 retry；无限 retry | 不依赖概率；到 N 或 finite space exhausted 即停止 | 低 |
| 6. Insufficient capacity | 只 render 可用 unique plans；`completed + partial`；零计划 failed | fail whole request；静默 duplicate；强制补足 | 保留有价值结果且不破坏 exact uniqueness | 中，主要是 UI 表达 |
| 7. Child identity | full execution UUID；短 `file_sid` 仅作 output token | 8-char SID 即 identity；task_id+index；DB Variant ID | 兼顾隔离、关联和现有输出命名 | 低到中 |
| 8. TTS/subtitle namespace | MP3/VTT/ASS 使用 full execution UUID | shared task ID；仅 8-char suffix；per-batch directory | 消除 writable collision 和理论短 token collision | 低 |
| 9. TaskHistory boundary | coordinator 聚合后 one row per submitted task | per-worker row；child task_id row；DB schema change | 与 unique task_id、batch_size、JSON outputs 和旧 Matrix 一致 | 中 |
| 10. BGM dedup boundary | `_resolve_locked` hash+semantic Y merge 时按 `asset_id` 去重 | file_hash dedup；adapter 后去重；compositor 去重 | 在重复最早出现位置修复，不影响独立 Y layers | 低 |

---

## 17. Risks / Open Questions

以下均不是进入 Gate 3 的阻断性设计缺口，但实施时必须显式守住。

1. **Blind Mode 未获得 exact diversity guarantee**

   本计划有意不拆分 Blind Director 阶段。不能在验收说明中声称 Blind visual duplication 已修复。

2. **Resolver candidate parity**

   新 candidate discovery 必须严格复用当前：

   - query limits
   - hard tags
   - asset axis
   - deleted/exhausted
   - locked fallback
   - smart ranking

   如果另写一套简化过滤器，effective capacity 会与真实 resolver 漂移。

3. **`CompilationPlan` 不是 frozen type**

   本轮采用逻辑只读 contract。若实施发现 mutation 风险，再评估 type-level frozen；不应预先扩大 schema 改动。

4. **Externally reused `session_id`**

   Caller 可以提供 `payload.session_id`。两个独立提交若复用同一 task ID，仍可能撞 `TaskHistory.task_id`。这不是 batch child collision，属于独立 idempotency/validation 问题。

5. **Shared progress interleaving**

   多个 child 的 running progress 仍可能在同一 task card 上交错甚至回退。添加 `executionId` 可改善可观测性，但完整 batch progress aggregation 不属于 INV-001。

6. **Concurrent usage_count updates**

   当前 render 后的 read-modify-write 仍可能存在独立丢增量风险。primary uniqueness 不得依赖 usage_count；本 Gate 不扩大为 fatigue transaction 重构。

7. **Partial warning UI**

   Backend semantics 已确定。若 project owner 要求用户在当前 UI 显式看到容量不足，需要小幅 Queue state/UI 修改；仍不应增加新的 task status。

8. **Short output suffix**

   batch 内应检查 `file_sid` 唯一。跨 batch 的 8-char 理论碰撞仍存在；改为更长 token 或 execution-scoped directory 属于 optional hardening。

9. **Preview timing**

   HTTP 返回发生在剩余 batch planning 前。推荐将 preview 作为第一 accepted plan；若 planning 时资产状态变化，应通过 WS warning 表达，不得 render stale plan。

10. **`task_ids` 字段语义**

    当前 response schema 描述暗示长度等于 batch size，但运行时只有一个 shared task ID。本轮不能用 child execution IDs 填充该字段，否则会破坏 identity 分层。

---

## 18. Gate 3 Readiness

**READY FOR IMPLEMENTATION**

Ready scope：

- AI Draft / non-Blind exact main-visual combination uniqueness。
- authoritative `CompilationPlan` handoff。
- finite batch-local planning。
- full child execution namespace。
- TTS/VTT/ASS isolation。
- one-row TaskHistory aggregation。
- coordinator-owned terminal WS。
- secondary BGM Y-layer dedup。
- no DB schema or migration。

Gate 3 必须保持以下边界：

- 不实施 Blind two-phase diversity planner。
- 不引入 semantic/perceptual similarity。
- 不引入 persistent Ledger。
- 不用随机 retry 代替 finite combination planning。
- 不把 `execution_id` 命名或持久化为 semantic `variant_id`。
- 不为防重复串行化 FFmpeg render。