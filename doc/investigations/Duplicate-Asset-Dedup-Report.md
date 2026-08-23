# INV-001 Gate 3 Phase 4 —
# BGM / Y-Layer Duplicate Asset Dedup Report

## 1. Baseline

- Branch: `fix/creative-duplicate-detection`
- Starting commit: `fbfbca1bcd9d728b6453f2e941e8ed77dea4afc7`
- Starting worktree: CLEAN
- 未 commit、未 push

## 2. Root Cause Reconfirmation

问题确认存在于 [`DSLParserNode._resolve_locked`](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:370)：

1. `_load_locked_hash_assets()` 将 physical `audio_bgm` 分类到 `y_from_hash`。
2. physical Y 首先被加入 Beat layers。
3. 随后的 semantic Y query 独立返回匹配素材。
4. 原代码未共享任何 Y identity set，因此同一 BGM 可再次被 append。

实际路径：

```text
locked physical hash
→ _load_locked_hash_assets()
→ y_from_hash
→ append physical Y

semantic_tags
→ _query_by_tags(... Y asset types ...)
→ semantic Y assets
→ append semantic Y
```

当同一 BGM 同时属于 physical hash 和 semantic query 结果时，原实现会形成两个 `ResolvedLayer`。

## 3. Files Changed

- [`src/api/dsl_parser.py`](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:380)

  新增 Beat-local Y identity state、稳定去重 helper，并接入 Locked 与 Smart Y layer assembly。

- [`tests/test_inv001_y_layer_dedup.py`](E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_y_layer_dedup.py:1)

  新增 5 个真实 SQLite / production parser 回归测试，覆盖 Y1–Y9。

## 4. Dedup Identity Contract

核心 helper 位于 [`_y_asset_identity`](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:757) 和 [`_append_unique_y_layers`](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:765)。

Identity 优先级：

1. normalized `file_hash`
2. 缺少有效 hash 时 fallback 到 `asset_id`

行为：

- hash 会 trim 并统一大小写。
- first occurrence wins。
- 保持输入顺序。
- identity set 仅在单次 Beat resolution 内存在。
- 不按 `asset_type` 去重，因此两个不同 BGM 或 BGM + SFX 均可保留。
- 不读写数据库，不增加 reservation 或全局状态。

## 5. Physical vs Semantic Precedence

Locked 路径先处理 physical `y_from_hash`，再处理 semantic Y，并共享同一个 Beat-local identity set：

- physical merge: [`dsl_parser.py:433`](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:433)
- semantic merge: [`dsl_parser.py:455`](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:455)

因此相同 media identity 冲突时：

```text
physical explicit Y → retained
semantic duplicate Y → skipped
```

测试还刻意让 semantic ranking 更偏好另一个 BGM，以证明显式 physical occurrence 的位置与优先级没有被 semantic ranking 替代。

## 6. Resolver Integration

修复位于 shared parser Y-layer assembly boundary，而非 Planner：

```text
legacy parse_and_resolve
             └─ _resolve_locked / _resolve_smart
exact materialization
             └─ _compile_plan
                └─ _resolve_beat
                   └─ _resolve_locked
```

因此 Legacy 和 Exact explicit-main materialization 自动共享同一去重规则。

## 7. Locked Compatibility

保持不变：

- physical X resolution
- semantic X fallback
- Context multi-X `random.choice`
- hard-tag filtering
- semantic query limits/ranking
- exhausted/usage behavior
- layout hints

唯一变化是同 Beat 内相同 Y media 不再重复 append。

Formal Hook shape 已验证：

```text
physical BGM
+ semantic Hook tag
→ semantic video remains layer-0
→ physical BGM remains one Y layer
```

## 8. Smart Compatibility

Smart path没有 Locked 路径的 physical + semantic 双入口，但其 ranked results 可能包含不同数据库行、normalized hash 相同的 Y media。

Smart assembly 复用同一 helper：

- normal main-X path: [`dsl_parser.py:623`](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:623)
- no-main legacy assembly: [`dsl_parser.py:657`](E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:657)

没有改变：

- query scope/limit
- scoring/ranking
- hard-tag behavior
- usage/exhausted behavior
- safe-shot fallback
- main-X selection

Distinct BGM/SFX 仍按原排名顺序保留。

## 9. Exact Planner Compatibility

测试通过真实链路：

```text
discover_main_visual_candidates()
→ materialize_with_main_selections()
→ shared _resolve_locked()
→ Y dedup
→ authoritative CompilationPlan
```

结果：

- selected video 保持 layer-0。
- physical + semantic 同一 BGM 只出现一次。
- 未修改 Planner、fingerprint、Cartesian enumeration、search budget 或 authoritative handoff。

## 10. Cross-Beat Behavior

每次 `_resolve_locked` / `_resolve_smart` 调用都会新建 identity set。

因此：

```text
Beat 1 → BGM A once
Beat 2 → BGM A once
```

没有 cross-Beat、cross-variant 或 batch-global BGM exclusion。

## 11. Layer Index Integrity

Helper 只在成功 append 时递增 `next_layer_idx`。

验证结果：

- Locked：main `0`，Y layers `1..N`
- Smart with main：main `0`，Y layers `1..N`
- Smart no-main legacy：仍从 `0` 连续编号
- 跳过 duplicate 后不会产生 `0, 1, 3` 等空洞

## 12. Tests Added

测试文件：[`test_inv001_y_layer_dedup.py`](E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_y_layer_dedup.py:69)

| Requirement | Coverage |
|---|---|
| Y1 | physical A + semantic A → A once |
| Y2 | physical A + semantic A/B → A once、B once |
| Y3 | 相同 A 跨两个 Beats → 每个 Beat once |
| Y4 | physical BGM + semantic Hook X → video layer-0、BGM once |
| Y5 | 通过真实 `parse_and_resolve()` 验证 |
| Y6 | 通过 discovery + explicit materialization 验证 |
| Y7 | 不同 Y assets / 相同类型继续共存 |
| Y8 | main-X asset 与 layer-0 语义保持 |
| Y9 | 不同 DB rows、normalized hash 相同 → 一次 |
| Smart audit | normalized-identical BGM 去重，distinct SFX 保留 |

所有测试均使用：

- in-memory SQLite
- real `LocalAsset`
- production `DSLParserNode`
- production query/scoring/materialization paths

## 13. INV-001 Regression

执行：

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

结果：

```text
Ran 82 tests in 0.677s

OK
```

日志中的模拟 child failure、history commit failure 和 FFmpeg failure 是既有负向测试场景，不是测试失败。

## 14. Python / Diff Checks

执行：

```powershell
.\venv_build\Scripts\python.exe -m py_compile src/api/dsl_parser.py tests/test_inv001_y_layer_dedup.py
git diff --check
```

结果：PASS。

Git 仅提示工作区 LF 将来可能被 Git 转换为 CRLF；没有 whitespace error。

## 15. Scope Audit

确认未修改：

- Phase 3A Planner
- exact fingerprint
- combination enumeration
- planning search budget
- capacity semantics
- `routes_dsl.py` coordinator/finalizer
- frontend
- DB models/schema/migrations
- TTS
- Subtitle
- Compositor
- Cover
- usage_count algorithm

未增加 warning、global BGM state、reservation 或音频策略。

## 16. Risks / Open Questions

- normalized hash identity会把仅大小写或首尾空白不同的 hash 视为同一 media；这符合本 Phase 的 stable media identity contract。
- `asset_id` fallback 仅用于缺少有效 hash 的 legacy asset。
- 未执行真实媒体 Repro；按约束留给 Phase 5。

## 17. Review Findings

NONE

## 18. Git Review

`git status --short`：

```text
 M src/api/dsl_parser.py
?? tests/test_inv001_y_layer_dedup.py
```

`git diff --stat`：

```text
src/api/dsl_parser.py | 96 +++++++++++++++++++++++++++++++++++++--------------
1 file changed, 71 insertions(+), 25 deletions(-)
```

新增测试文件当前为 untracked，因此标准 `git diff --stat` 不包含它；文件为 207 行。

`git diff --check`：PASS。

未 commit，未 push。