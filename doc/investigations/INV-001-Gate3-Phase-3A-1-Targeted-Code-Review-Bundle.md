# INV-001 Gate 3 Phase 3A-1 —
# Targeted Code Review Bundle

## 1. Baseline

```text
git rev-parse HEAD
648ce4787d368274b918d799d28eecda0f62b313
```

```text
git status --short
 M src/api/dsl_parser.py
 M src/api/routes_dsl.py
 M tests/test_inv001_planning_policy.py
?? doc/investigations/INV-001-Gate3-Phase-3A-1.md
?? tests/test_inv001_variant_planning.py
```

Phase 3A-1 尚未 commit。

```text
git diff --stat
 src/api/dsl_parser.py                | 600 ++++++++++++++++++++++-------------
 src/api/routes_dsl.py                | 389 +++++++++++++++++++++--
 tests/test_inv001_planning_policy.py |  24 +-
 3 files changed, 754 insertions(+), 259 deletions(-)
```

`git diff --stat` 不包含两个 untracked 文件。新测试文件共 786 行。未跟踪的调查文档没有纳入本次实现 diff 审计，也未被修改。

```text
git diff --check
PASS
```

仅有 LF→CRLF working-copy 提示，没有 whitespace error。

## 2. Parser Diff Map

文件：[dsl_parser.py](</E:/dopaworkspace/dopamatrix-desktop/src/api/dsl_parser.py:62>)

| 分组 | Function / Class | Current lines | 状态 | Purpose |
|---|---|---:|---|---|
| A | `parse_and_resolve` | 116–120 | changed | 复用 `_prepare_payload` 和 `_compile_plan` |
| A | `_prepare_payload` | 168–169 | new extraction | 为 legacy/discovery/materialization设置相同 hard-tag state |
| A | `_compile_plan` | 171–201 | new extraction | 统一 legacy 与 explicit plan compilation |
| A | `_resolve_beat` | 206–241 | changed | 增加可选 `explicit_main` 分发 |
| B | `normalize_file_hash` | 62–64 | new | exact candidate/fingerprint hash normalization |
| B | `is_main_visual_asset_type` | 67–72 | new | main-X registry validation |
| B | `MainVisualCandidate` | 75–80 | new | session-independent candidate identity |
| B | `MainVisualSelectionMismatch` | 83–84 | new | explicit selection invariant error |
| C | `discover_main_visual_candidates` | 122–152 | new | 为每个有序 Beat 生成 resolver-valid main-X pool |
| C | `_discover_main_visual_assets` | 348–367 | new | locked/smart discovery dispatch |
| D | `materialize_with_main_selections` | 154–165 | new | 显式选择 materialization |
| D | `_match_explicit_main` | 327–346 | new | 当前 DB eligibility + ID/hash revalidation |
| D | `_resolve_locked` explicit branch | 370–476 | changed | selected main 绕过 legacy random selection |
| D | `_resolve_smart` explicit branch | 547–670 | changed | selected main 绕过 legacy top-1 |
| E | `_load_locked_hash_assets` | 248–291 | new extraction | 共享 physical hash lookup/X-Y classification |
| E | `_locked_main_candidate_assets` | 293–325 | new extraction | 共享 locked main pool与 semantic fallback |
| E | `_smart_fallback_query` | 482–496 | new extraction | 共享 safe-shot eligibility query |
| E | `_query_smart_fallback_assets` | 498–508 | new | legacy `.first()` / exact `.all()` fetch boundary |
| E | `_smart_candidate_assets` | 510–545 | new extraction | 共享 smart query、scoring和 main-X filtering |
| E | `_query_by_tags` | 676–712 | unchanged body | 原有 deleted/exhausted/tag/query-limit rules |
| E | `_score_candidates` | 761–808 | unchanged body | 原有 hard veto/usage/random tie ranking |
| F | legacy locked selection | 400–406 | changed structure, unchanged semantics | 仍为 multiple X `random.choice`；fallback仍取 score top-1 |
| F | legacy Smart fallback | 573–581 | changed structure, unchanged semantics | 非 explicit path仍执行 SQL random + `.first()` |
| G | unrelated changes | — | none found | 无无关 parser refactor |

结论：600 行 diff 的规模来自把两个较大的 legacy resolver 分支拆为共享 discovery/materialization primitives；未发现 G 类无关改动。

## 3. MainVisualCandidate Contract

```python
def normalize_file_hash(value: object) -> str:
    return str(value or "").strip().lower()


def is_main_visual_asset_type(asset_type: str) -> bool:
    return ASSET_REGISTRY.get(str(asset_type), {}).get("axis_type") in (
        "X_BASE",
        "X_STRUCTURE",
    )


@dataclass(frozen=True)
class MainVisualCandidate:
    asset_id: int
    file_hash: str
```

CURRENT CODE FACT：

- Dataclass equality默认比较 `asset_id + file_hash`。
- Candidate pool dedup不是用 dataclass equality，而是显式按 normalized `file_hash`：

```python
seen_hashes: set[str] = set()
for asset, _matched in candidates:
    normalized_hash = normalize_file_hash(getattr(asset, "file_hash", ""))
    if not normalized_hash or normalized_hash in seen_hashes:
        continue
    seen_hashes.add(normalized_hash)
    pool.append(
        MainVisualCandidate(
            asset_id=cast(int, asset.id),
            file_hash=normalized_hash,
        )
    )
```

- `asset_type` 不存入 candidate。
- `asset_type` 在 discovery candidate list生成时由 registry X classification约束，materialization后又由 fingerprint helper重新检查。
- 不携带 ORM object、path、tags或usage state，因此 candidate 可以安全离开创建它的 SQLAlchemy session。
- Materialization通过 `asset_id + normalized file_hash` 重新找到当前 resolver-valid ORM asset。

## 4. Repro Hook Discovery

关键 registry：

```python
ASSET_REGISTRY = {
    "video": {"axis_type": "X_BASE"},
    "scene_master_video": {"axis_type": "X_STRUCTURE"},
    "audio_bgm": {"axis_type": "Y_LAYER"},
    ...
}
```

Physical hash classification：

```python
for asset in assets:
    axis_type = _axis_type_for_asset(asset)
    matched = _intersect_tags(asset, node.semantic_tags)
    if axis_type in ("X_BASE", "X_STRUCTURE"):
        x_track.append((asset, matched))
    elif axis_type == "Y_LAYER":
        y_from_hash.append((asset, matched))
```

Locked semantic main fallback：

```python
if x_track:
    return list(x_track)

# semantic fallback only runs when at least one locked hash resolved
# but none was main-X.
if not hash_assets or not node.semantic_tags:
    return []

x_video_types = [
    asset_type
    for asset_type, registry in ASSET_REGISTRY.items()
    if registry.get("axis_type") in ("X_BASE", "X_STRUCTURE")
]
fallback = self._query_by_tags(
    tags=node.semantic_tags,
    asset_types=x_video_types,
    limit=5,
)
return _score_candidates(
    fallback,
    user_hard_tags=self._user_hard_tags,
    request_tags=node.semantic_tags,
)
```

因此对于：

```text
physical hash = 44444.mp3
asset_type = audio_bgm
semantic_tags = ["hook:汽车减震器"]
```

实际路径是：

```text
44444.mp3 resolves into hash_assets
→ axis_type=Y_LAYER
→ y_from_hash gets BGM
→ x_track remains empty
→ hash_assets is non-empty
→ semantic_tags is non-empty
→ _query_by_tags(asset_types=X types, limit=5)
→ _score_candidates
→ all scored semantic X candidates enter discovery pool
```

结论：physical BGM 不会阻止 semantic Hook X candidates进入 Planner pool。

边界事实：如果 physical hash 本身没有匹配任何当前 DB asset，则 `hash_assets` 为空，现有 legacy parity规则不会触发 semantic X fallback。

## 5. Context Multi-X Discovery

Discovery：

```python
if node.address_mode == "locked":
    hash_assets, x_track, _y_from_hash, _warnings = (
        self._load_locked_hash_assets(node)
    )
    return self._locked_main_candidate_assets(
        node,
        hash_assets=hash_assets,
        x_track=x_track,
    )
```

`_locked_main_candidate_assets`：

```python
if x_track:
    return list(x_track)
```

因此 Context 的多个 physical X hashes 全部进入 candidate pool；discovery阶段不调用 `random.choice`。

Legacy resolution仍保留：

```python
if explicit_main is not None:
    chosen = self._match_explicit_main(main_candidates, explicit_main, node)
elif x_track:
    chosen = random.choice(x_track) if len(x_track) > 1 else x_track[0]
elif main_candidates:
    chosen = main_candidates[0]
```

结论：

- Exact discovery：返回全部 resolver-valid Context X。
- Legacy execution：multiple physical X仍随机选择一个。

## 6. Fixed Build

Build只有一个 valid X时：

```text
Build pool = [MainVisualCandidate(build_asset_id, build_hash)]
pool size = 1
```

Planner协调状态只有：

```python
used_fingerprints: set[_MainVisualFingerprint] = set()
```

定向搜索结果：

```text
used_assets       NO MATCH
excluded_assets   NO MATCH
reserved_assets   NO MATCH
reservation       NO MATCH
claim             NO MATCH
used_fingerprints routes_dsl.py only
```

所以 Cartesian combinations可以重复使用同一 Build：

```text
(Hook12, Context18, Build24)
(Hook13, Context18, Build24)
(Hook12, Context28, Build24)
```

只要完整 ordered fingerprint不同，组合就是合法的。

## 7. Legacy Resolver Parity

| Legacy behavior | Review status | Evidence |
|---|---|---|
| Locked physical X | UNCHANGED SEMANTICS | 仍按 hash查询、仅过滤 deleted、按 request hash order排序 |
| Locked exhausted physical X | UNCHANGED SEMANTICS | physical locked query没有新增 exhausted filter |
| Locked semantic fallback | UNCHANGED SEMANTICS | 仍为 X types、`limit=5`、`_score_candidates`、legacy top-1 |
| Smart semantic query | UNCHANGED SEMANTICS | 仍为 `_query_by_tags(... asset_types=None, limit=20)` |
| Hard-tag veto | UNCHANGED SEMANTICS | `_score_candidates` body未修改 |
| Usage/exhausted scoring | UNCHANGED SEMANTICS | sort key仍含 exhausted、usage_count、random tie |
| Safe-shot fallback | UNCHANGED LEGACY SEMANTICS | 仍为 SQL random ordering + one `.first()` |
| Context multiple physical X | UNCHANGED SEMANTICS | 仍为 `random.choice(x_track)` |
| Y resolution | UNCHANGED SEMANTICS | explicit main选择后仍执行现有 semantic Y query |

Current scoring：

```python
hard_veto_tags = normalized_hard & normalized_req

if hard_veto_tags:
    survivors = []
    for asset, matched in candidates:
        asset_tag_set = {t.lstrip("#").lower() for t in (asset.tags or [])}
        if hard_veto_tags.issubset(asset_tag_set):
            survivors.append((asset, matched))
    candidates = survivors

def _score(pair):
    asset, matched = pair
    return (
        -len(matched),
        1 if bool(asset.is_exhausted) else 0,
        int(asset.usage_count) if asset.usage_count is not None else 0,
        random.random(),
    )
```

Safe-shot fetch split：

```python
def _query_smart_fallback_assets(self, *, enumerate_all: bool):
    query = self._smart_fallback_query()
    if enumerate_all:
        return query.all()
    first = query.first()
    return [first] if first is not None else []
```

调用规则：

```python
# Exact discovery
enumerate_fallback=True

# Legacy resolution
enumerate_fallback=explicit_main is not None
```

所以普通 legacy `explicit_main=None` 使用 `.first()`；`.all()`只用于 exact discovery或 exact explicit materialization。

## 8. Candidate Discovery

核心逻辑：

```python
def discover_main_visual_candidates(
    self,
    payload: StoryDSLPayload,
) -> List[List[MainVisualCandidate]]:
    self._prepare_payload(payload)
    pools: List[List[MainVisualCandidate]] = []

    for node in payload.timeline:
        candidates = self._discover_main_visual_assets(node)
        seen_hashes: set[str] = set()
        pool: List[MainVisualCandidate] = []

        for asset, _matched in candidates:
            normalized_hash = normalize_file_hash(
                getattr(asset, "file_hash", "")
            )
            if not normalized_hash or normalized_hash in seen_hashes:
                continue
            seen_hashes.add(normalized_hash)
            pool.append(
                MainVisualCandidate(
                    asset_id=cast(int, asset.id),
                    file_hash=normalized_hash,
                )
            )
        pools.append(pool)

    return pools
```

Resolver dispatch：

```python
if node.address_mode == "locked":
    hash_assets, x_track, _y, _warnings = self._load_locked_hash_assets(node)
    return self._locked_main_candidate_assets(
        node,
        hash_assets=hash_assets,
        x_track=x_track,
    )

if node.address_mode == "smart" and node.semantic_tags:
    _ranked, main_candidates, _fallback = self._smart_candidate_assets(
        node,
        enumerate_fallback=True,
    )
    return main_candidates

return []
```

Eligibility facts：

- X only：由 `_axis_type_for_asset(...) in ("X_BASE", "X_STRUCTURE")`控制。
- Y excluded：classification不会把 `Y_LAYER`加入 main pool。
- Locked physical：过滤 deleted；不额外过滤 exhausted。
- Semantic locked/smart：`_query_by_tags`过滤 deleted和exhausted。
- Smart safe-shot：过滤 deleted和exhausted。
- Hard tags：通过现有 `_score_candidates` veto。
- Locked semantic query limit：5。
- Smart semantic query limit：20；底层先按 usage取最多200条检查。
- Candidate order：保留 resolver/scoring order。
- Dedup：normalized file hash。
- 任一 Beat无候选：该 Beat pool为空，Cartesian effective space变为0。

## 9. Explicit Materialization

入口：

```python
def materialize_with_main_selections(
    self,
    payload: StoryDSLPayload,
    selections: Sequence[MainVisualCandidate],
) -> CompilationPlan:
    if len(selections) != len(payload.timeline):
        raise MainVisualSelectionMismatch(
            "PLANNER_SELECTION_MISMATCH: "
            "selection count does not match Beat count"
        )
    self._prepare_payload(payload)
    return self._compile_plan(payload, selections=selections)
```

每个 Beat绑定：

```python
for beat_index, beat_node in enumerate(payload.timeline):
    explicit_main = (
        selections[beat_index] if selections is not None else None
    )
    result = self._resolve_beat(
        beat_node,
        explicit_main=explicit_main,
    )
```

当前 DB/eligibility重验证：

```python
matches = [
    pair
    for pair in candidates
    if cast(int, pair[0].id) == selection.asset_id
    and normalize_file_hash(getattr(pair[0], "file_hash", ""))
        == selection.file_hash
]
if len(matches) != 1:
    raise MainVisualSelectionMismatch(
        "PLANNER_SELECTION_MISMATCH: ..."
    )
return matches[0]
```

Layer-0 construction：

```python
if explicit_main is not None:
    chosen = self._match_explicit_main(
        main_candidates,
        explicit_main,
        node,
    )
elif x_track:
    chosen = random.choice(x_track) if len(x_track) > 1 else x_track[0]
elif main_candidates:
    chosen = main_candidates[0]

if chosen is not None:
    asset, matched = chosen
    layers.append(
        _make_layer(
            layer_index=0,
            asset=asset,
            matched_tags=matched,
        )
    )
```

问题逐项回答：

1. Selected X再进入 `random.choice`？  
   **NO。** `explicit_main`分支优先。

2. Selected X再被 `scored_fb[0]`替换？  
   **NO。** Scoring只构造 resolver-valid ordered candidate list；`_match_explicit_main`从该列表精确找回指定 ID/hash。

3. Y/BGM/SFX是否继续解析？  
   **YES。** Locked path随后继续执行 hash Y和semantic Y；Smart path继续从原 ranked list挂载 Y。

4. 未选择的其他 X能否进入layer-0？  
   **NO。** Locked只构造一个 chosen layer-0；Smart loop额外要求 `asset.id == chosen_id`。

5. Discovery后asset deleted/changed？  
   - deleted或不再resolver-valid：当前 candidate list中找不到，抛 `PLANNER_SELECTION_MISMATCH`。
   - normalized hash改变：ID/hash联合匹配失败。
   - 不会静默改选其他 candidate。

## 10. Selection Invariant

Planner materialization后检查：

```python
materialized = parser.materialize_with_main_selections(
    dsl_payload,
    combination,
)
fingerprint = _exact_main_visual_fingerprint(materialized)

selected_hashes = tuple(
    candidate.file_hash for candidate in combination
)
materialized_hashes = tuple(
    row[3] for row in fingerprint
)

if selected_hashes != materialized_hashes:
    raise MainVisualSelectionMismatch(
        "PLANNER_SELECTION_MISMATCH: "
        "selected and materialized hashes differ"
    )
```

Mismatch处理：

```python
except MainVisualSelectionMismatch:
    selection_mismatch_seen = True
    logger.exception(
        "[variant_planner] explicit selection materialization mismatch"
    )
    continue
```

因此 mismatch combination不会进入：

```python
accepted_plans.append(materialized)
```

也不会到达 worker。

联合保证：

- Parser `_match_explicit_main`验证 `asset_id + normalized hash`。
- Planner再验证materialized ordered main hashes。
- Fingerprint helper再验证layer-0与main-X type。

## 11. Fingerprint

Return type：

```python
_MainVisualFingerprint = tuple[
    tuple[int, str, int, str],
    ...
]
```

完整 helper：

```python
def _exact_main_visual_fingerprint(
    plan: CompilationPlan,
) -> _MainVisualFingerprint:
    if not plan.beats:
        raise ValueError(
            "MAIN_VISUAL_PLAN_INVALID: plan has no Beats"
        )

    fingerprint: list[tuple[int, str, int, str]] = []

    for beat_index, beat in enumerate(plan.beats):
        main_layers = [
            layer
            for layer in beat.layers
            if layer.layer_index == 0
        ]
        if len(main_layers) != 1:
            raise ValueError(
                "MAIN_VISUAL_PLAN_INVALID: Beat "
                f"{beat.beat!r} has {len(main_layers)} layer-0 assets"
            )

        main_layer = main_layers[0]
        if not is_main_visual_asset_type(main_layer.asset_type):
            raise ValueError(
                "MAIN_VISUAL_PLAN_INVALID: Beat "
                f"{beat.beat!r} layer 0 is not a main-X asset"
            )

        normalized_hash = normalize_file_hash(main_layer.file_hash)
        if not normalized_hash:
            raise ValueError(
                f"MAIN_VISUAL_PLAN_INVALID: "
                f"Beat {beat.beat!r} has no stable file_hash"
            )

        beat_identity = str(beat.beat).strip()
        if not beat_identity:
            raise ValueError(
                "MAIN_VISUAL_PLAN_INVALID: Beat identity is empty"
            )

        fingerprint.append(
            (beat_index, beat_identity, 0, normalized_hash)
        )

    return tuple(fingerprint)
```

结论：

- 包含 Beat position和Beat identity。
- 固定layer index 0。
- hash trim + lowercase。
- 每个Beat必须恰好一个layer-0。
- layer-0必须为main-X。
- 空plan、缺main、重复main、非visual main、空hash、空Beat identity均拒绝。
- Y layers完全不被遍历，因此只改变Y不会改变fingerprint。

## 12. Preview Seed

Preview validation：

```python
if (
    preview_plan is None
    or len(preview_plan.beats) != len(dsl_payload.timeline)
):
    return None

try:
    _exact_main_visual_fingerprint(preview_plan)
except ValueError:
    return None
```

Beat order与candidate membership：

```python
for beat_index, (beat, node, pool) in enumerate(
    zip(preview_plan.beats, dsl_payload.timeline, candidate_pools)
):
    if beat.beat != node.beat:
        return None

    main_layer = next(
        layer for layer in beat.layers
        if layer.layer_index == 0
    )
    normalized_hash = normalize_file_hash(main_layer.file_hash)

    match = next(
        (
            candidate
            for candidate in pool
            if candidate.asset_id == main_layer.asset_id
            and candidate.file_hash == normalized_hash
        ),
        None,
    )
    if match is None:
        return None
    selections.append(match)
```

Acceptance：

```python
if preview_selections is not None and candidate_space_size:
    preview_key = _selection_key(preview_selections)
    preview_fingerprint = _exact_main_visual_fingerprint(preview_plan)

    examined_keys.add(preview_key)
    accepted_plans.append(preview_plan)
    accepted_fingerprints.append(preview_fingerprint)
    used_fingerprints.add(preview_fingerprint)
```

逐项回答：

- A. Beat count/order：验证count；逐Beat验证`beat.beat == node.beat`。
- B. Main ID/hash：必须仍存在于当前 resolver-valid pool。
- C. Fingerprint：accept前验证。
- D. Accepted fingerprints：加入。
- E. Budget：preview key加入`examined_keys`，占用一个budget slot。
- F. `batch_size=1` valid preview：accepted count立刻满足request，不materialize。
- G. Stale main：candidate membership失败，preview被跳过。
- H. Auxiliary Y/file path：**保持preview原对象中的值**。代码直接执行`accepted_plans.append(preview_plan)`，没有重新materialize preview。

REVIEW OBSERVATION：main asset ID/hash/eligibility得到当前验证，但preview中的main `file_path`和辅助Y snapshot没有刷新，存在request-time preview到background planning之间的窄staleness窗口。

## 13. Combination Enumeration

核心循环：

```python
candidate_pools = parser.discover_main_visual_candidates(
    dsl_payload
)

candidate_space_size = (
    prod(len(pool) for pool in candidate_pools)
    if candidate_pools and all(candidate_pools)
    else 0
)

for combination in product(*candidate_pools):
    combination_key = _selection_key(combination)

    if combination_key in examined_keys:
        continue

    if len(examined_keys) >= search_budget:
        break

    examined_keys.add(combination_key)

    try:
        materialized = parser.materialize_with_main_selections(
            dsl_payload,
            combination,
        )
        fingerprint = _exact_main_visual_fingerprint(
            materialized
        )
        ...
    except MainVisualSelectionMismatch:
        ...
        continue
    except ValueError:
        ...
        continue

    if fingerprint in used_fingerprints:
        continue

    accepted_plans.append(materialized)
    accepted_fingerprints.append(fingerprint)
    used_fingerprints.add(fingerprint)

    if len(accepted_plans) >= requested_count:
        break
```

审计结论：

- `itertools.product`为lazy tuple iterator。
- `examined_keys`保证包括preview在内的tuple最多访问一次。
- `used_fingerprints`阻止duplicate fingerprint进入accepted list。
- 达到requested N立即停止。
- 没有whole-plan retry loop。
- 没有DB reservation。
- 没有used-assets exclusion。
- 单个Hook/Context/Build asset可在不同完整组合中重复。
- Resolver randomness只影响candidate order，不承担uniqueness保证。

## 14. Search-Budget Boundary

```python
_EXACT_MAIN_VISUAL_SEARCH_BUDGET = 4096
```

Budget check顺序：

```python
if len(examined_keys) >= search_budget:
    break
examined_keys.add(combination_key)
# materialize the just-added combination
```

Termination顺序：

```python
if len(accepted_plans) >= requested_count:
    termination_reason = "REQUEST_SATISFIED"
    warning_codes = []
elif len(examined_keys) >= candidate_space_size:
    termination_reason = "TRUE_SPACE_EXHAUSTED"
    warning_codes = ["INSUFFICIENT_UNIQUE_CAPACITY"]
else:
    termination_reason = "PLANNING_SEARCH_LIMIT_REACHED"
    warning_codes = ["PLANNING_SEARCH_LIMIT_REACHED"]
```

边界回答：

1. 第4096个tuple是否examined？  
   **YES。** 进入前count=4095，不触发break；先add成为4096，再materialize。

2. 什么情况产生`SEARCH_LIMIT_REACHED`？  
   Accepted不足N、examined=4096，并且`candidate_space_size > 4096`。

3. 第4096个tuple正好满足N？  
   **REQUEST_SATISFIED**，因为accepted-count判断优先。

4. Candidate space恰好4096且不足N？  
   **TRUE_SPACE_EXHAUSTED**。`examined == candidate_space_size`判断优先于search-limit fallback。

5. Preview如何影响count？  
   Valid preview先加入`examined_keys`，因此剩余最多materialize 4095个不同tuple；总examined仍最多4096。

结论：空间恰好耗尽与预算命中不存在当前代码歧义。

## 15. Capacity Cases

| Case | Planning reason | Warning | Planned | Execution allocation |
|---|---|---|---:|---|
| requested=4, space=8, accepted=4 | `REQUEST_SATISFIED` | none | 4 | 4 |
| requested=4, space=2, accepted=2 | `TRUE_SPACE_EXHAUSTED` | `INSUFFICIENT_UNIQUE_CAPACITY` | 2 | 2 |
| requested=20, space>4096, examined=4096, accepted=7 | `PLANNING_SEARCH_LIMIT_REACHED` | `PLANNING_SEARCH_LIMIT_REACHED` | 7 | 7 |
| non-empty space, all finite tuples materialized invalid, space≤4096 | `TRUE_SPACE_EXHAUSTED` | `INSUFFICIENT_UNIQUE_CAPACITY`；可能附加`PLANNER_SELECTION_MISMATCH` | 0 | 0 |
| only all budget-examined tuples invalid, but unexamined tuples remain | `PLANNING_SEARCH_LIMIT_REACHED` | `PLANNING_SEARCH_LIMIT_REACHED`；可能附加mismatch | 0 | 0 |

只有完整space遍历完毕时，invalid plans导致的capacity=0才被称为true exhaustion。

## 16. Zero-Plan Finalization

Identity allocation：

```python
identities = (
    _create_child_executions(
        task_id,
        len(planning_result.plans),
    )
    if planning_result.plans
    else []
)

child_work = [
    ...
]
```

Dispatch：

```python
child_results: list[_ChildResult] = []

if len(child_work) == 1:
    child_results.append(_execute_child(child_work[0]))
elif len(child_work) > 1:
    with ThreadPoolExecutor(...) as pool:
        ...
```

M=0时两个分支均不执行。

Finalizer：

```python
successful_results = [
    result for result in child_results
    if result.succeeded
]
succeeded_count = len(successful_results)
failed_count = len(child_results) - succeeded_count
planned_count = len(child_results)

history_persisted = False
if succeeded_count:
    _persist_task_history(...)

final_status = "completed" if succeeded_count else "failed"
```

Terminal：

```python
terminal_payload = {
    "taskId": task_id,
    "status": final_status,
    "partial": partial,
    "requestedCount": batch_size,
    "plannedCount": planned_count,
    "succeededCount": succeeded_count,
    "failedCount": failed_count,
    "historyPersisted": history_persisted,
    "warningCodes": warning_codes,
}

ws_manager.broadcast_sync(...)
```

确认：

- 无execution ID。
- 无executor。
- `child_results=[]`合法。
- `_persist_task_history`内部虽有`next(success)`，但仅在`succeeded_count > 0`时调用。
- 无TaskHistory。
- terminal=`failed`。
- requestedCount=N。
- plannedCount=0。
- planner warnings保留。
- 正常finalizer路径只执行一次terminal broadcast。

## 17. Warning Propagation

Planner：

```python
planning_warning_codes.extend(
    planning_result.warning_codes
)
```

Finalizer：

```python
warning_codes = list(
    dict.fromkeys(planning_warning_codes)
)

if (
    failed_count
    and "CHILD_EXECUTION_FAILED" not in warning_codes
):
    warning_codes.append("CHILD_EXECUTION_FAILED")
```

`CHILD_EXECUTION_FAILED`只追加，不覆盖planning warning。

Terminal：

```python
"warningCodes": warning_codes
```

TaskHistory：

```python
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
}
```

因此：

- `INSUFFICIENT_UNIQUE_CAPACITY`保留。
- `PLANNING_SEARCH_LIMIT_REACHED`保留。
- 有child失败时再追加`CHILD_EXECUTION_FAILED`。
- M=0不写history，但terminal保留planning warning。

## 18. Child Identity Timing

Identity allocation发生在：

```text
planner returns accepted plans
→ coordinator recomputes/validates all fingerprints
→ verifies fingerprints are unique
→ _create_child_executions(task_id, len(plans))
```

关键代码：

```python
if (
    computed_fingerprints != planning_result.fingerprints
    or len(set(computed_fingerprints))
        != len(computed_fingerprints)
):
    raise ValueError("PLANNER_RESULT_INVALID: ...")

identities = (
    _create_child_executions(
        task_id,
        len(planning_result.plans),
    )
    if planning_result.plans
    else []
)
```

所以以下均不会获得identity：

- rejected combination
- materialization-invalid combination
- fingerprint duplicate
- planning exception
- zero-capacity candidate space

`_create_child_executions`使用：

```python
for child_index in range(child_count):
```

因此accepted M children的indices固定为`0..M-1`，没有rejected-candidate gaps。

## 19. Authoritative Child Binding

完整结构：

```python
@dataclass(frozen=True)
class _ChildWork:
    execution: _ChildExecution
    authoritative_plan: Optional[CompilationPlan] = None
    visual_fingerprint: Optional[_MainVisualFingerprint] = None
```

绑定：

```python
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
```

Dispatch：

```python
def _execute_child(work: _ChildWork):
    child = work.execution

    result = render_worker(
        work.authoritative_plan
        if work.authoritative_plan is not None
        else (None if blind_dsl else resolved_plan),
        task_id,
        ...,
        execution_id=child.execution_id,
        child_index=child.child_index,
        dsl_payload=None if blind_dsl else dsl_payload,
        plan_is_authoritative=(
            work.authoritative_plan is not None
        ),
    )
```

每个single-child或future闭包收到自己的`_ChildWork`，没有从共享preview `resolved_plan`替换exact child plan。

## 20. Worker Handoff

Authoritative branch：

```python
if blind_dsl:
    ...
else:
    if plan_is_authoritative:
        if plan is None:
            return _result(
                "failed",
                "AUTHORITATIVE_PLAN_MISSING",
                "authoritative child requires CompilationPlan",
            )
        working_plan = plan

    elif dsl_payload is not None:
        working_plan = _parse_plan_from_db(
            tenant_id,
            dsl_payload,
        )

    elif plan is not None:
        working_plan = plan
    else:
        return _result(...)
```

Timeline：

```python
timeline = compile_plan_to_timeline(
    working_plan,
    target_duration=target_duration,
)
```

Raw DSL TTS：

```python
_active_payload = dsl_payload
_beat_texts = [
    beat.script_text.strip()
    for beat in (
        _active_payload.timeline
        if _active_payload else []
    )
    if beat.script_text and beat.script_text.strip()
]
```

Raw DSL meta：

```python
if dsl_payload is not None and dsl_payload.meta is not None:
    meta = dsl_payload.meta.model_dump()
```

因此 authoritative=True + plan + raw DSL：

- `_parse_plan_from_db`不执行。
- Parser visual resolver不执行。
- `working_plan = plan`。
- Timeline使用provided plan。
- TTS/script/meta继续读取raw DSL。

Legacy Manual：

- `plan_is_authoritative=False`
- `dsl_payload is not None`
- 因此优先执行`_parse_plan_from_db`
- 即使Manual coordinator同时传入preview `resolved_plan`，也不会自动变成authoritative。

## 21. Call-Site Audit

生产代码中只有一个真正的`render_worker(...)`调用：`render_batch_worker._execute_child`。

| Flow | Coordinator policy | Worker path | Authoritative |
|---|---|---|---|
| AI Draft exact `/submit-dsl` | explicit `exact_main_visual` | planned `_ChildWork` | `True` |
| Generic populated `/submit-dsl` | request default/explicit `legacy` | worker-local DSL resolve | `False` |
| Manual `/submit-manual` | coordinator default `legacy` | worker-local DSL resolve | `False` |
| Blind `/submit-dsl` | `legacy`; exact被422 guard | Director→DSL→resolver | `False` |
| populated `/render-dsl` | coordinator default `legacy`; exact被422 guard | worker-local DSL resolve | `False` |
| Blind `/render-dsl` | `legacy`; exact被422 guard | Director→DSL→resolver | `False` |

Production coordinator callers：

```text
submit_dsl     → BackgroundTasks.add_task(render_batch_worker, ...)
submit_manual  → BackgroundTasks.add_task(render_batch_worker, ...)
render_dsl     → BackgroundTasks.add_task(render_batch_worker, ...)
```

只有exact planner生成非空`work.authoritative_plan`，而flag由：

```python
work.authoritative_plan is not None
```

产生。

## 22. Phase 3A-0 Transition

全局搜索：

```text
rg "EXACT_MAIN_VISUAL_PLANNER_NOT_IMPLEMENTED" src web_ui tests
NO MATCH
```

Policy guard：

```python
if not _requests_exact_main_visual(payload):
    return

if is_blind:
    raise HTTPException(422, ...)

if flow == "submit_dsl":
    return
```

Exact submit dispatch：

```python
_worker_kw = {
    ...
    "variant_planning_policy":
        payload.variant_planning_policy,
}

if _requests_exact_main_visual(payload):
    _worker_kw["resolved_plan"] = plan

background_tasks.add_task(
    render_batch_worker,
    dsl_payload_for_worker,
    task_id,
    ...,
    **_worker_kw,
)
```

Coordinator：

```python
if variant_planning_policy == "exact_main_visual":
    planning_result = (
        _plan_exact_main_visual_variants_from_db(...)
    )
```

所以当前生产链：

```text
exact_main_visual /submit-dsl
→ HTTP 202 response
→ scheduled coordinator
→ Planner V1
→ authoritative child execution
```

Legacy requests仍跳过Planner分支。

## 23. Critical Test Evidence

测试文件：[test_inv001_variant_planning.py](</E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_variant_planning.py:233>)

### T-A / T-B — Repro-like + fixed Build reuse

层级：真实SQLite + production `DSLParserNode` + pure planner。

```python
for file_hash in (
    "hook-12", "hook-13",
    "context-18", "context-28",
    "build-24",
):
    self._add_asset(file_hash)

payload = _payload([
    ["hook-12", "hook-13"],
    ["context-18", "context-28"],
    ["build-24"],
])

parser = DSLParserNode(self.db)
preview = parser.parse_and_resolve(payload)

result = routes_dsl._plan_exact_main_visual_variants(
    parser,
    payload,
    4,
    preview_plan=preview,
)

self.assertEqual(len(result.plans), 4)
self.assertEqual(len(set(result.fingerprints)), 4)
self.assertEqual(
    {fp[2][3] for fp in result.fingerprints},
    {"build-24"},
)
```

### T-C / T-D — Capacity与search-limit区分

层级：pure planner + `_RecordingParser`。

```python
result = routes_dsl._plan_exact_main_visual_variants(
    parser_with_capacity_two,
    payload,
    4,
)
self.assertEqual(len(result.plans), 2)
self.assertEqual(
    result.termination_reason,
    "TRUE_SPACE_EXHAUSTED",
)
self.assertEqual(
    result.warning_codes,
    ("INSUFFICIENT_UNIQUE_CAPACITY",),
)
```

```python
result = routes_dsl._plan_exact_main_visual_variants(
    parser_with_space_four,
    payload,
    4,
    search_budget=1,
)
self.assertEqual(
    result.termination_reason,
    "PLANNING_SEARCH_LIMIT_REACHED",
)
self.assertNotIn(
    "INSUFFICIENT_UNIQUE_CAPACITY",
    result.warning_codes,
)
```

### T-E — M=0 no execution/render

层级：production coordinator/finalizer。

```python
terminal = routes_dsl.render_batch_worker(
    payload,
    "zero-plan-batch",
    batch_size=4,
    variant_planning_policy="exact_main_visual",
)

create_children.assert_not_called()
worker.assert_not_called()
persist.assert_not_called()

self.assertEqual(terminal["status"], "failed")
self.assertEqual(terminal["plannedCount"], 0)
self.assertEqual(ws.call_count, 1)
```

### T-F — Authoritative plan + raw DSL

层级：production `render_worker`。

```python
result = routes_dsl.render_worker(
    plan,
    "authoritative-task",
    prompt="metadata prompt",
    file_sid=child.file_sid,
    execution_id=child.execution_id,
    child_index=child.child_index,
    dsl_payload=dsl_payload,
    plan_is_authoritative=True,
)

resolver.assert_not_called()
compile_timeline.assert_called_once_with(
    plan,
    target_duration=15,
)
self.assertEqual(
    captured_tts,
    {"en": "raw DSL narration"},
)
self.assertEqual(
    result.prompt_details["meta"]["social_title"],
    "title",
)
```

### T-G — Selected tuple materializes into main layer

层级：真实SQLite + production parser。

```python
pools = parser.discover_main_visual_candidates(payload)
selected = next(
    candidate
    for candidate in pools[0]
    if candidate.asset_id == second.id
)

plan = parser.materialize_with_main_selections(
    payload,
    [selected],
)

main = [
    layer
    for layer in plan.beats[0].layers
    if layer.layer_index == 0
]

self.assertEqual(
    [(layer.asset_id, layer.file_hash) for layer in main],
    [(second.id, "smart-b")],
)
self.assertNotEqual(first.id, main[0].asset_id)
```

### T-H — Physical BGM + semantic Hook fallback

**MISSING TEST**

生产源码证明路径正确，但没有测试构造：

```text
physical locked audio_bgm
+ semantic Hook tag
+ semantic X candidates
```

并通过真实parser discovery断言X pool。

### T-I — Legacy Context random.choice preserved

**MISSING DIRECT ASSERTION**

Repro-like test在生成preview时会经过legacy parse，但没有mock/assert `random.choice`调用。它只断言exact planning期间不调用random choice。

### T-J — Manual planner not invoked

现有测试覆盖production Manual worker-local resolution：

```python
terminal = routes_dsl.render_batch_worker(
    dsl_payload,
    "phase2-manual",
    resolved_plan=plan,
)

parse_plan.assert_called_once_with(
    "default",
    dsl_payload,
)
director.assert_not_called()
```

但没有直接patch/assert exact planner helper未调用。

### T-K — Blind planner not invoked

现有测试覆盖production Blind Director path：

```python
terminal = routes_dsl.render_batch_worker(
    None,
    "phase2-blind",
    prompt="blind prompt",
    blind_dsl=True,
)

director.draft_blueprint.assert_called_once()
```

同样没有直接patch/assert exact planner helper未调用。

### T-L — Exact request no longer 501

层级：production endpoint scheduling + production coordinator；planner DB wrapper被mock。

```python
response = routes_dsl.submit_dsl(
    request,
    background,
    db=Mock(),
)

scheduled = background.add_task.call_args

terminal = scheduled.args[0](
    *scheduled.args[1:],
    **scheduled.kwargs,
)

self.assertEqual(response.render_status, "rendering")
planner.assert_called_once()
self.assertEqual(terminal["status"], "completed")
self.assertEqual(terminal["plannedCount"], 1)
```

## 24. Test Quality Review

现有Repro-like主测试没有绕过parser discovery：

```text
real SQLite LocalAsset rows
→ DSLParserNode.parse_and_resolve preview
→ DSLParserNode.discover_main_visual_candidates
→ planner
→ explicit materialized CompilationPlans
```

因此确实存在一条真实：

```text
DSLParserNode discovery
→ planner
→ CompilationPlan
```

集成测试，并覆盖：

```text
Hook physical multi-X
Context physical multi-X
Build fixed
request=4
```

但它没有覆盖Formal Repro Hook的真实地址形态：

```text
Hook physical BGM/Y
+ semantic tag fallback/X
```

结论：

```text
MISSING INTEGRATION TEST:
Formal Repro Hook address shape
(physical BGM + semantic X fallback)
```

算法边界测试使用`_RecordingParser`是合理的pure-planner隔离，但不能替代上述resolver-parity集成场景。

## 25. Scope Audit

| Scope | Result |
|---|---|
| Frontend Vue | UNCHANGED |
| DB schema/migrations | UNCHANGED |
| `models.py` | UNCHANGED |
| TTS | UNCHANGED |
| Subtitle | UNCHANGED |
| Compositor | UNCHANGED |
| Cover | UNCHANGED |
| `services.py` | UNCHANGED |
| BGM dedup | NOT IMPLEMENTED |
| usage_count update algorithm | UNCHANGED |
| Blind planner | NOT IMPLEMENTED |
| Manual diversity | NOT IMPLEMENTED |
| Phase 3B warning UI | NOT IMPLEMENTED |

Tracked implementation diff只涉及：

```text
src/api/dsl_parser.py
src/api/routes_dsl.py
tests/test_inv001_planning_policy.py
```

另有untracked focused test和untracked investigation document。

`dsl_parser.py`最后一个修改hunk结束于当前约662行；既有`_query_by_tags`和`_score_candidates`实现体没有被改写。未发现unrelated refactor。

## 26. Review Findings

### RF3A1-01 — Preview seed preserves stale auxiliary snapshot

Current candidate discovery重新验证了preview main `asset_id + hash + resolver eligibility`，但accepted seed直接保存原`preview_plan`，没有重新materialize。

影响：

- Y layers保持request-time snapshot。
- Main/Y `file_path`保持request-time值。
- 若request响应到background planning之间相关DB记录的path或Y eligibility改变，seed与其他materialized plans的freshness不同。

这不破坏当前exact main-hash uniqueness，但属于authoritative-plan staleness风险。

### RF3A1-02 — Missing Formal Repro Hook integration test

缺少：

```text
physical BGM/Y hash
+ Hook semantic tag
→ semantic X discovery
→ full planner
```

的真实SQLite/parser集成测试。生产代码静态路径正确，但关键resolver parity缺乏自动回归锁定。

### RF3A1-03 — Missing direct legacy/mode negative assertions

缺少直接测试：

- legacy Context multi-X确实调用`random.choice`
- Manual coordinator不调用exact planner helper
- Blind coordinator不调用exact planner helper

现有测试覆盖了最终legacy behavior和generic legacy planner bypass，但没有对这三个特定contract做直接mock assertion。

未发现已证实的exact-combination、budget、zero-plan、identity或authoritative-handoff生产代码错误。

## 27. Test Results

```powershell
.\venv_build\Scripts\python.exe -m unittest discover -s tests -p "test_inv001_*.py" -q
```

```text
Ran 73 tests in 0.546s
OK
```

测试日志包含预期的mocked FFmpeg/history-failure路径输出；没有运行正式媒体生成。

```powershell
.\venv_build\Scripts\python.exe -m py_compile src/api/routes_dsl.py src/api/dsl_parser.py tests/test_inv001_variant_planning.py tests/test_inv001_planning_policy.py
```

```text
PASS
```

```powershell
git diff --check
```

```text
PASS
```

仅有LF→CRLF提示，无diff whitespace错误。

## 28. Final Git Status

```text
 M src/api/dsl_parser.py
 M src/api/routes_dsl.py
 M tests/test_inv001_planning_policy.py
?? doc/investigations/INV-001-Gate3-Phase-3A-1.md
?? tests/test_inv001_variant_planning.py
```

HEAD保持：

```text
648ce4787d368274b918d799d28eecda0f62b313
```

本轮未修改任何文件、未commit、未push、未进入Phase 3B。