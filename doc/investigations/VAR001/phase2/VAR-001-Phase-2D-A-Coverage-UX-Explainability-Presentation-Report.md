# VAR-001
# Phase 2D-A
# Coverage UX / Explainability Presentation Report

## 1. Baseline

- Branch: `feature/var-001-variation-policy`
- HEAD: `41f72eb2744cb8028277aaa5ac4ebbb05fc19f9e`
- Phase 2C commit present: `41f72eb feat(var-001): expose and normalize coverage diagnostics`
- Initial worktree: clean

## 2. Existing Queue Card Audit

Coverage 面板插入任务卡提示/结果摘要之后、资产轮播之前。

由于原列表使用固定高度虚拟化，无法安全展开，processing 与 completed 列表改用项目已有的 `DynamicScroller`，卡片现有内容和视觉结构未重构。

## 3. Files Changed

- [QueueView.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/QueueView.vue)
- [CoverageDiagnosticsPanel.vue](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/components/CoverageDiagnosticsPanel.vue)
- [coveragePresentation.ts](E:/dopaworkspace/dopamatrix-desktop/web_ui/src/utils/coveragePresentation.ts)
- [coveragePresentation.test.mjs](E:/dopaworkspace/dopamatrix-desktop/web_ui/tests/coveragePresentation.test.mjs)

## 4. Component Architecture

`CoverageDiagnosticsPanel` 接受强类型：

```ts
diagnostics: CoverageDiagnosticsV1
```

组件不读取原始 WS/history 数据，也不调用 normalizer。

`coveragePresentation.ts` 只负责标签、摘要和文本格式化。

## 5. Render Condition

两个任务列表均严格使用：

```vue
v-if="item.coverageDiagnostics"
```

因此：

- 完成任务有 diagnostics：显示
- 失败任务有 diagnostics：显示
- 旧任务无 diagnostics：不显示
- 不依赖任务 mode、warning、asset 或 child 数量

## 6. Collapsed Summary

使用原生 `<details>/<summary>`，默认折叠。

摘要只统计后端 classification，例如：

```text
覆盖：4 个可变 Beat 均衡 · 1 个容量固定
```

不重新判断是否均衡。

## 7. Beat Coverage Table

表格保持后端 Beat 顺序，展示：

- Beat
- 可用候选：`pool_size`
- 已使用：`unique_used`
- 未使用：`unused_count`
- 分布：`selected_histogram[].count`
- 状态：后端 classification 映射

空 Beat identity 回退为 `Beat {beat_index + 1}`。

## 8. Distribution Semantics

分布严格保留已选 histogram 顺序：

```text
1 / 1 / 1 / 1
```

未使用候选仅在“未使用”列显示，不伪造 `0` 的候选位置。

## 9. Status Labels

- `FIXED_BY_CAPACITY` → `容量固定`
- `VARIABLE_BALANCED` → `均衡`
- `VARIABLE_TARGET_NOT_MET` → `未达到均衡目标`
- `null` → `状态不可用`

状态始终包含文字，不依赖颜色表达。

## 10. Reason Text

四种状态均提供约束范围内的解释。

未将 search limit、materialization、duplicate rejection 等任务级原因归因到单个 Beat。

## 11. Planning Context

展开区域显示：

- `accepted_count / requested_count`
- `examined_count / candidate_space_size`
- `search_budget`
- `termination_reason`

没有使用 render `succeededCount` 代替规划接受数量。

## 12. Termination Reason

使用当前后端常量：

- `REQUEST_SATISFIED` → 已满足请求数量
- `TRUE_SPACE_EXHAUSTED` → 已检查全部候选组合
- `PLANNING_SEARCH_LIMIT_REACHED` → 已达到规划搜索上限

未知未来值使用中性原始值展示且不会抛错。

## 13. Rejection Context

三个 rejection count 全为零时隐藏。

存在非零值时，以任务级信息显示映射不匹配、无效计划和重复组合数量。

## 14. Preview Provenance

`preview_seeded=true` 时显示：

```text
预览种子已作为第 1 个计划纳入覆盖统计。
```

不显示 preview digest。

## 15. Accessibility

- 使用原生 `<details>/<summary>`
- 支持键盘操作
- 使用语义化 `<table>`、`scope="col"` 和 `scope="row"`
- focus-visible 有明确轮廓
- 所有状态均有文字

## 16. Responsive / Styling

- 复用 QueueView 的深色背景、边框和字体色
- 表格容器允许横向滚动
- 窄屏 planning context 改为两列
- 动态虚拟列表重新测量展开高度，避免卡片重叠或撑宽页面

## 17. Internal Data Hidden

用户界面未渲染：

- `normalized_file_hash`
- `accepted_fingerprint_digests`
- `preview_fingerprint_digest`
- `asset_id`
- 原始 policy/type/version

`PHASE2D_INTERNAL_HASHES_HIDDEN`

`PHASE2D_ASSET_IDS_HIDDEN`

## 18. No Frontend Reclassification

没有新增：

- `ideal_floor`/`ideal_ceil` 计算
- `max_min_gap` 计算
- B/P 除法
- Coverage/Balance Score
- classification 推导

`PHASE2D_FRONTEND_RECLASSIFICATION_NONE`

## 19. UI-RF-01 Boundary

`getModeLabel`、generation-mode badge 和 authoring mode 逻辑无 diff。

`UI_RF_01_UNCHANGED`

## 20. Historical Novelty Boundary

新增生产文件不包含 Historical Novelty、ledger、perceptual 或 semantic similarity 实现。

## 21. Presentation Tests

新增 8 项测试，覆盖：

- healthy/attention/all-fixed/null/zero-Beat 摘要
- histogram 顺序和不伪造零值
- 四种状态标签及原因
- 三个已知 termination reason 和未知值
- rejection 零值隐藏与非零展示
- preview provenance
- completed/failed 状态独立接入
- disclosure、table 与内部字段隐藏

结果：`8 PASS`

## 22. Normalizer Regression

既有 Phase 2C normalizer 测试：

```text
11 PASS
```

与展示测试合并执行：

```text
19 PASS
```

Normalizer 生产源码未修改。

## 23. Frontend Build

```text
vite v7.3.1
141 modules transformed
build PASS
```

既有非阻塞提示：

- Browserslist 数据较旧
- `Login.vue` 同时被静态和动态导入

## 24. VAR Regression

```text
Ran 52 tests
OK
```

## 25. INV Regression

```text
Ran 85 tests
OK
```

## 26. FP Regression

```text
Ran 42 tests
OK
```

## 27. Production Diff Audit

- Backend `src/api/routes_dsl.py`: empty
- `queueWorker.ts`: empty
- `useQueueStore.ts`: empty
- `coverageDiagnostics.ts`: empty
- DB/planner/fingerprint/TaskHistory：无修改
- `git diff --check`: PASS

## 28. Review Findings

NONE

## 29. Final Git Status

```text
 M web_ui/src/views/QueueView.vue
?? web_ui/src/components/CoverageDiagnosticsPanel.vue
?? web_ui/src/utils/coveragePresentation.ts
?? web_ui/tests/coveragePresentation.test.mjs
```

未提交，未推送，未启动服务或真实媒体任务。

VAR001_PHASE2D_UI_IMPLEMENTATION_PASS