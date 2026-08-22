# INV-001 Gate 3 Phase 3A-1 — Exact Main-Visual Variant Planner Core Report

Phase 3A-1 已完成：AI Draft exact policy 现在进入有界 Planner V1，生成唯一 authoritative `CompilationPlan` 后再创建 child execution。73 项 INV-001 回归全部通过；未 commit、未 push。

## 1. Baseline

- Branch: `fix/creative-duplicate-detection`
- Starting commit: `648ce4787d368274b918d799d28eecda0f62b313`
- Starting worktree: `CLEAN`

## 2. AI Draft Mode Boundary

Planner 唯一激活条件为：

```python
payload.variant_planning_policy == "exact_main_visual"
```

没有使用 prompt、timeline、mode、endpoint provenance 或 non-Blind heuristic 推断 AI Draft。

- populated `/submit-dsl` + exact：允许进入 Planner V1
- Blind + exact：继续返回 422
- Manual + exact：继续返回 422
- `/render-dsl` + exact：继续返回 422
- omitted/legacy：保持现有行为

关键入口位于 [routes_dsl.py](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:137>)。

## 3. Files Changed

- [dsl_parser.py](</E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:123>)
  - 抽取共享 resolver candidate primitives。
  - 新增 main-X candidate discovery。
  - 新增 explicit main selection materialization。
  - 保持 legacy locked/smart selection 行为。

- [routes_dsl.py](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:179>)
  - exact fingerprint。
  - lazy/bounded combination planning。
  - capacity/warning semantics。
  - authoritative plan handoff。
  - Phase 2 finalizer integration。

- [test_inv001_planning_policy.py](</E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_planning_policy.py:91>)
  - 将临时 501 测试更新为 Planner coordinator dispatch 测试。

- [test_inv001_variant_planning.py](</E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_variant_planning.py:139>)
  - 新增 786 行 focused Phase 3A-1 测试。

没有修改 frontend、数据库、媒体节点或公共 API schema。

## 4. Planner Architecture

实际 exact 调用链：

```text
Formal AI Draft
→ /submit-dsl
→ request-time preview CompilationPlan
→ render_batch_worker(variant_planning_policy="exact_main_visual")
→ DSLParserNode.discover_main_visual_candidates()
→ lazy Cartesian combination enumeration
→ materialize_with_main_selections()
→ exact fingerprint validation
→ accepted authoritative CompilationPlans
→ allocate execution_id/file_sid
→ concurrent render_worker(plan_is_authoritative=True)
→ Phase 2 aggregation/finalization
```

Rejected 或 invalid planning candidates 不会获得 execution identity。

## 5. Resolver Reuse

没有在 `routes_dsl.py` 复制 eligibility 或 ranking 规则。

`DSLParserNode` 的 legacy resolution、candidate discovery 和 explicit materialization 共用：

- locked physical hash 查询、deleted filtering、axis classification 和 hash ordering
- locked semantic fallback 的 `_query_by_tags(limit=5)` 与 `_score_candidates`
- smart `_query_by_tags(limit=20)`、hard-tag veto 和 `_score_candidates`
- safe-shot fallback 的相同 DB eligibility query
- 当前 exhausted/usage/tag 规则

Legacy Smart safe-shot 仍只执行随机 `.first()`；exact discovery/materialization 才枚举 `.all()`，避免改变 legacy 查询规模。

## 6. Candidate Discovery Contract

每个有序 Beat 返回：

```python
List[List[MainVisualCandidate]]
```

每个 candidate 只包含 session-independent：

- `asset_id`
- normalized `file_hash`

规则：

- 仅接收 registry 中 `X_BASE` / `X_STRUCTURE`。
- 每个 Beat 按 normalized `file_hash` 去重。
- 保留 resolver 提供的候选优先顺序。
- 不把 Y/BGM 放入 main candidate pool。
- effective capacity 来自 resolver-valid pools，不使用 UI 可见的理论乘积作保证。

## 7. Explicit Selection Materialization

Planner 选定每个 Beat 的 `MainVisualCandidate` 后，重新调用同一个 parser materialization boundary。

Parser 要求候选同时匹配：

- `asset_id`
- normalized `file_hash`
- 当前 resolver eligibility

不匹配时抛出：

```text
PLANNER_SELECTION_MISMATCH
```

Materialized plan 随后再次验证 main hashes 与 selected tuple 一致。资产在 discovery 后被删除或失效时会立即 fail-fast，而不是静默生成无主视觉 plan。

## 8. Exact Fingerprint

Fingerprint 位于 [routes_dsl.py](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:204>)：

```text
ordered(
  beat_index,
  trimmed beat identity,
  layer_index = 0,
  normalized file_hash
)
```

验证要求：

- plan 至少包含一个 Beat
- 每个 Beat 恰好一个 layer-0
- layer-0 必须属于 main-X asset type
- file hash 非空且稳定
- Beat identity 非空

Y layer、BGM、TTS、字幕以及其他音频差异均不进入 Level-1 fingerprint。

同一 Build 可以跨 variants 重复；禁止的只是完整有序 combination fingerprint 重复。

## 9. Preview Seed Behavior

Request-time preview 只有满足以下条件才作为第一个 seed：

- Beat 数量和顺序匹配
- fingerprint 合法
- 每个 main layer 的 `asset_id + normalized file_hash` 仍在当前 candidate pool 中

有效 preview：

- 计为第一个 examined/accepted combination
- `batch_size=1` 时直接复用，避免额外 materialization

Stale 或 invalid preview：

- 不接受
- 从当前 resolver-valid candidate space 开始规划

## 10. Search Bound

内部 search budget：

```python
_EXACT_MAIN_VISUAL_SEARCH_BUDGET = 4096
```

当前 `RenderDSLRequest.batch_size` 上限为 20，因此预算显著大于支持的 requested child count，同时限制异常大 candidate space 的请求成本。

算法：

- lazy `itertools.product`
- 每个 candidate tuple 最多访问一次
- 不执行 whole-plan random retry
- randomness 只影响 resolver candidate ordering，不承担 uniqueness 保证

结束原因严格区分：

- `REQUEST_SATISFIED`
- `TRUE_SPACE_EXHAUSTED`
- `PLANNING_SEARCH_LIMIT_REACHED`

只有完整有限空间被遍历后，才报告真实 capacity exhaustion。

## 11. Capacity Semantics

对于 requested `N`、accepted `M`：

- `M == N`：正常执行。
- `0 < M < N` 且空间耗尽：
  - 执行 M 个 child
  - `partial=true`
  - `INSUFFICIENT_UNIQUE_CAPACITY`
- `0 < M < N` 且搜索预算耗尽：
  - 执行 M 个 child
  - `partial=true`
  - `PLANNING_SEARCH_LIMIT_REACHED`
- `M == 0`：
  - 不创建 execution identity
  - 不启动 executor
  - Phase 2 finalizer 发出 failed terminal
  - 不写空 TaskHistory

不会 clone 已接受 plan 补足 N。

`requestedCount=N`，`plannedCount=M`，TaskHistory `batch_size` 继续保存 requested N。

## 12. Authoritative Plan Handoff

每个 accepted child 通过内部 `_ChildWork` 绑定：

- `_ChildExecution`
- authoritative `CompilationPlan`
- exact visual fingerprint

Worker 新增明确内部 contract：

```python
plan_is_authoritative=True
```

此时：

- 必须存在 `plan`
- visual resolution 不再调用 `_parse_plan_from_db`
- Timeline 从传入 plan 编译
- raw DSL 仍保留，用于 TTS script、subtitle source、meta 和 history metadata

相关实现位于 [routes_dsl.py](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:516>)。

## 13. Manual Compatibility

Manual：

- 默认 policy 仍为 `legacy`
- exact policy 继续明确返回 422 unsupported
- 不调用 exact planner
- legacy worker 仍执行原有 DSL resolution
- 不强制 uniqueness
- explicit user selection semantics 未改变

## 14. Blind Compatibility

Blind：

- exact policy 继续返回 `EXACT_MAIN_VISUAL_UNSUPPORTED_FOR_BLIND`
- legacy Blind 仍执行：

```text
Director
→ child DSL
→ resolver
→ CompilationPlan
→ render
```

本阶段不保证 Blind exact uniqueness，也未引入 Blind planner。

## 15. Phase 1 / Phase 2 Compatibility

保持：

- shared `task_id`
- unique `execution_id`
- derived `file_sid`
- contiguous accepted `child_index=0..M-1`
- TTS/VTT/ASS child namespace
- stable child ordering
- one TaskHistory row per submitted task
- one coordinator-owned terminal WS
- history persistence failure isolation

Phase 2 finalizer未被复制或替换；只扩展了 requested/planned capacity 与 planner warning 输入。

## Phase 3A-0 Transition

Before：

```text
exact_main_visual
→ HTTP 501
→ EXACT_MAIN_VISUAL_PLANNER_NOT_IMPLEMENTED
```

After：

```text
exact_main_visual
→ 202 submission
→ render_batch_worker
→ Planner V1
→ authoritative child plans
→ normal Phase 1/2 lifecycle
```

生产源码中已不存在 `EXACT_MAIN_VISUAL_PLANNER_NOT_IMPLEMENTED`。

Legacy/omitted requests不进入 Planner，行为保持不变。

## 16. Tests Added

- F1–F6：fingerprint equality/difference/order/Y exclusion/hash normalization/invalid main validation。
- P1–P4：Hook×Context×fixed Build 结构性四组合、Build reuse、candidate dedup、无重复 fingerprint。
- P5–P7：tuple 单次访问、无随机 retry、有限确定终止。
- C1：capacity=2/request=4，不重复补位。
- C2：search limit 与 true exhaustion 分离。
- C3：零 plan 不创建 identity、不 render。
- C4：preview 仅在当前有效时复用。
- A1–A3：authoritative worker 不 resolver；Timeline 使用 approved plan；raw DSL 仍提供 script/meta。
- A4：explicit selected main 确实成为 layer-0，Y layers 保留。
- A5：coordinator 不向两个 workers 下发相同 fingerprint。
- M1：exact policy 调用 planner。
- M2：Manual legacy 不调用 planner。
- M3：Blind legacy 保持 Director path。
- M4：generic legacy coordinator 不触发 exact planning。
- P0-TRANSITION：exact `/submit-dsl` 不再 501，并进入 coordinator/planner lifecycle。
- 补充回归：discovery 后 asset 删除时 fail-fast；legacy/exact Smart fallback fetch scope 分离。

## 17. Test Results

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

结果：

```text
Ran 73 tests in 0.586s
OK
```

```powershell
.\venv_build\Scripts\python.exe -m py_compile src/api/routes_dsl.py src/api/dsl_parser.py tests/test_inv001_variant_planning.py tests/test_inv001_planning_policy.py
```

结果：PASS。

```powershell
git diff --check
```

结果：PASS。仅输出既有 Git LF→CRLF working-copy warning，无 whitespace error。

未运行真实视频、网络 TTS、Repro001 或 Repro002。

## 18. Scope Audit

确认未实施：

- BGM Y-layer dedup
- frontend 修改或 Phase 3B warning UI
- DB schema/migration
- Variant ID
- persistent Ledger/reservation
- pHash / CLIP / MMR
- Blind planner
- Manual diversity
- semantic/perceptual dedup
- usage_count 算法或 transaction 修改
- Phase 1 identity contract修改
- Phase 2 persistence/terminal ownership重构

## 19. Risks / Open Questions

- Capacity warning目前完整存在于 backend terminal/history metadata，但用户可见呈现仍属于 Phase 3B。
- Fingerprint只保证 exact decoded-source hash combination，不处理感知相似。
- 4096 search budget可能在极大有效空间中提前终止；此时会如实报告 `PLANNING_SEARCH_LIMIT_REACHED`。
- Preview seed重新验证了当前 main candidate identity，但没有重新生成其辅助 Y layers/file-path snapshot；当前 request→background 间隔通常很短，后续可考虑是否总是 rematerialize seed。
- Planner coordination是单次 batch-local、单进程内存状态，不提供 cross-batch 或 distributed reservation。
- 已知 usage_count 并发更新风险与 BGM double-Y 问题保持未修。

## 20. Git Review

当前状态：

```text
 M src/api/dsl_parser.py
 M src/api/routes_dsl.py
 M tests/test_inv001_planning_policy.py
?? tests/test_inv001_variant_planning.py
```

Tracked diff：

```text
src/api/dsl_parser.py                | 600 ++++++++++++++++++++++-------------
src/api/routes_dsl.py                | 389 +++++++++++++++++++++--
tests/test_inv001_planning_policy.py |  24 +-
3 files changed, 754 insertions(+), 259 deletions(-)
```

新测试文件：

```text
tests/test_inv001_variant_planning.py | 786 insertions
```

未 commit，未 push，未开始 Phase 3B。