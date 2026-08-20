# INV-001 Gate 1 Code Evidence Bundle

## 1. Baseline

- **Branch:** `fix/creative-duplicate-detection`
- **Commit:** `965ed0564306d670c78c3454b8ba42764516c1c6`
- **Worktree:** `DIRTY`
- 本轮开始和结束时 HEAD/status 一致；未修改 repository。

```text
 M doc/investigations/INV-001-duplicate-video-generation.md
 D doc/investigations/evidence/INV-001-repro-001.md
?? "doc/investigations/INV-001 Codex Read-Only Root Cause Report.md"
?? doc/investigations/evidence/INV-001-experiment-summary.md
?? doc/investigations/evidence/INV-001-repro-001/
?? doc/investigations/evidence/INV-001-repro-002/
?? doc/investigations/evidence/INV-001-repro-003/
```

这些均为调查开始前已经存在的 worktree 状态。

---

## 2. Batch / Worker Evidence

### A1a — Batch 前 preview / validation parse

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`submit_dsl`

**Lines**  
`929-939`

**CURRENT CODE**

```python
else:
    # ── Step 1: DSL 解析 → CompilationPlan ───────────────────────────
    try:
        dsl_payload = StoryDSLPayload(
            engine_type=payload.engine_type,
            timeline=payload.timeline,
            meta=payload.meta,
            user_hard_tags=payload.user_hard_tags,
        )
        parser = DSLParserNode(db)
        plan = parser.parse_and_resolve(dsl_payload)
```

**CURRENT CODE FACT**

- 非 Blind 请求在 HTTP request context 中先产生一个 `CompilationPlan`。
- 该 plan 用于后续 resolved-beats validation 和 response snapshot。
- 这里尚未展开 batch children。

**Why this matters**

证明 batch 前确实存在一次 preview/validation resolution，但不能单凭这一段认定它是 render authoritative plan。

**Supports**

`Q1 / Q2`

---

### A1b — task_id、batch_size、raw worker payload 与 batch dispatch

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`submit_dsl`

**Lines**  
`966-994`

**CURRENT CODE**

```python
# ── Step 3: 生成唯一 task_id，按 batch_size 选择 worker ──────────────
task_id    = payload.session_id or str(uuid.uuid4())
batch_size = payload.batch_size

# 原始 DSL Payload（未执行寻址），下发给 Worker 实现运行时动态抽卡
dsl_payload_for_worker: Optional[StoryDSLPayload] = None if is_blind else StoryDSLPayload(
    engine_type=payload.engine_type,
    timeline=payload.timeline,
    meta=payload.meta,
    user_hard_tags=payload.user_hard_tags,
)

_worker_kw: dict[str, Any] = {
    "blind_dsl": is_blind,
    "engine_type": payload.engine_type,
    "director_mode": payload.mode,
    "enable_tts": payload.enable_tts,
    "enable_subtitles": payload.enable_subtitles,
}

if batch_size > 1:
    background_tasks.add_task(
        render_batch_worker,
        dsl_payload_for_worker,
        task_id,
        payload.aspect_ratio, payload.target_duration, payload.tenant_id,
        payload.prompt, batch_size, payload.test_language,
        **_worker_kw,
    )
```

**CURRENT CODE FACT**

- `batch_size` 首次从 `RenderDSLRequest` 读取于 line 968。
- `task_id` 在 batch 展开前只生成一次。
- batch worker 接收的是重新构造的 unresolved `StoryDSLPayload`。
- A1a 中的 `plan` 没有出现在这次 `render_batch_worker` 调用参数中。
- `resolved_plan` 因未显式传入而保持默认 `None`。

**Why this matters**

直接证明 preview plan 没有成为当前 AI Draft batch render 的 authoritative plan。

**Supports**

`Q1 / Q2 / Q5`

---

### A1c — Response 返回的是 preview plan snapshot

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`submit_dsl`

**Lines**  
`1014-1019`

**CURRENT CODE**

```python
# ── Step 4: 返回 CompilationPlan 快照 + 任务元数据 ─────────────────
return DSLSubmitResponse(
    **plan.model_dump(),
    task_id=task_id,
    task_ids=[task_id],
    render_status="rendering",
```

**CURRENT CODE FACT**

- HTTP response 嵌入 A1a 产生的 plan。
- `task_ids` 实际只含共享 `task_id` 一项。
- 该 response plan 与 worker 后续重新 resolve 的 plan 没有对象传递关系。

**Why this matters**

人工 Review 不能把 response 中的 plan 当作任一 child 最终实际使用的 plan。

**Supports**

`Q1 / Q2`

---

### A2a — Batch coordinator 只有一个 optional resolved_plan slot

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_batch_worker`

**Lines**  
`625-641`

**CURRENT CODE**

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
) -> None:
```

**CURRENT CODE FACT**

- Coordinator 当前可以接收一个 `CompilationPlan`。
- 参数类型不是 `List[CompilationPlan]`，也不是 child-to-plan mapping。
- 当前函数没有 authoritative child-plans collection。

**Why this matters**

现有签名已包含 plan handoff 概念，但不能直接表达 N 个独立 authoritative child plans。

**Supports**

`Q1 / Q2`

---

### A2b — N 个 child、shared task_id/raw DSL、per-child file_sid

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_batch_worker`

**Lines**  
`653-679`

**CURRENT CODE**

```python
logger.info(
    "[render_batch_worker] 批量渲染启动 task_id=%s batch=%d",
    task_id, batch_size,
)

sub_sids = [uuid.uuid4().hex[:8] for _ in range(batch_size)]
all_assets: list[dict] = []

with ThreadPoolExecutor(max_workers=batch_size) as pool:
    future_map = {
        pool.submit(
            render_worker,
            None if blind_dsl else resolved_plan,
            task_id,
            aspect_ratio, target_duration, tenant_id,
            prompt, batch_size, test_language,
            sid,
            True,
            blind_dsl=blind_dsl,
            engine_type=engine_type,
            director_mode=director_mode,
            dsl_payload=None if blind_dsl else dsl_payload,
            enable_tts=enable_tts,
            enable_subtitles=enable_subtitles,
        ): sid
        for sid in sub_sids
    }
```

**CURRENT CODE FACT**

- `batch_size` 同时决定 `sub_sids` 数量和 executor worker 数量。
- 每个 child 收到相同 `task_id`。
- 非 Blind children 收到相同 `dsl_payload` 对象。
- 每个 child 收到一个从 `sub_sids` 取出的 8-hex `file_sid`。
- 所有 children 如果接收 `resolved_plan`，接收的也是同一个单一对象。
- 当前没有 per-child authoritative plan list。
- 代码没有检查随机 8-hex `sub_sids` 是否碰撞。

**Why this matters**

独立回答 coordinator 当前拥有什么、children 为什么共享 raw DSL，以及 identity 如何分裂。

**Supports**

`Q1 / Q2 / Q4 / Q5`

---

### A3a — Worker 同时接受 plan 与 raw DSL

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_worker`

**Lines**  
`132-149`

**CURRENT CODE**

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
    suppress_completed_ws: bool = False,
    *,
    blind_dsl: bool = False,
    engine_type: str = "content",
    director_mode: str = "auto",
    dsl_payload: Optional[StoryDSLPayload] = None,
    enable_tts: bool = True,
    enable_subtitles: bool = True,
```

**CURRENT CODE FACT**

- Worker API 已有 `plan` 参数。
- Worker 也有独立 `dsl_payload` 参数。
- `task_id` 与 `file_sid` 是不同参数。

**Why this matters**

当前 worker contract 已存在 pre-resolved plan handoff slot，不需要从零发明新的 visual plan 类型。

**Supports**

`Q2 / Q5`

---

### A3b — 每次 worker resolve 创建新 Session 和 parser

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`_parse_plan_from_db`

**Lines**  
`77-82`

**CURRENT CODE**

```python
def _parse_plan_from_db(tenant_id: str, payload: StoryDSLPayload) -> CompilationPlan:
    """在 Worker 线程内打开租户库会话，执行 DSLParserNode。"""
    _tenant_engine = get_tenant_engine(tenant_id)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_tenant_engine)
    with _SessionLocal() as db:
        return DSLParserNode(db).parse_and_resolve(payload)
```

**CURRENT CODE FACT**

- 每次 helper 调用打开一个 Session。
- 每次创建一个新 `DSLParserNode`。
- 返回一个新 `CompilationPlan`。

**Why this matters**

证明 execution-local plan 不是由共享 Context 或浅拷贝产生，而是由每个 worker 重新解析产生。

**Supports**

`Q1 / Q2 / Q4`

---

### A3c — raw DSL 优先于传入 plan

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_worker`

**Lines**  
`244-273`

**CURRENT CODE**

```python
else:
    if dsl_payload is not None:
        # 动态运行时寻址：Worker 线程内独立重新执行资产抽卡，
        # 确保批量并发时各子任务命中不同素材（_score_candidates + random.choice）
        working_plan = _parse_plan_from_db(tenant_id, dsl_payload)
        logger.info(
            "[render_worker] task_id=%s 动态寻址完成 resolved=%d/%d",
            task_id,
            working_plan.summary.resolved_beats,
            working_plan.summary.total_beats,
        )
        if working_plan.summary.resolved_beats == 0:
            return []
    elif plan is not None:
        working_plan = plan
    else:
        return []

# ── 1. CompilationPlan → Timeline ─────────────────────────────
assert working_plan is not None, "working_plan must be resolved before this point"
timeline = compile_plan_to_timeline(
    working_plan, target_duration=target_duration,
)
```

**CURRENT CODE FACT**

- 只要 `dsl_payload is not None`，worker 就重新调用 resolver。
- 即使同时传入 `plan`，该 plan 分支也不会执行。
- 当 `dsl_payload is None` 且 `plan` 存在时，worker 可直接把该 plan 交给 timeline compiler。
- 当前 AI Draft batch 为 children 传入 raw DSL，因此全部重新 resolve。

**Why this matters**

这是 authoritative plan 无法在当前 AI Draft 路径直接生效的精确条件分支。

**Supports**

`Q1 / Q2 / Q4`

---

### A4a — TTS script 当前直接依赖 raw DSL

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_worker`

**Lines**  
`327-337`

**CURRENT CODE**

```python
# 单轨原位提取：从 dsl_payload.timeline 各 Beat 的 script_text 聚合
_active_payload = dsl_payload
_beat_texts = [
    b.script_text.strip()
    for b in (_active_payload.timeline if _active_payload else [])
    if b.script_text and b.script_text.strip()
]

if _beat_texts:
    _tts_lang = test_language or "en"
    context.set_asset("tts_script", {_tts_lang: "\n".join(_beat_texts)})
```

**CURRENT CODE FACT**

- TTS script 不是从 `working_plan.beats[].script_text` 读取。
- 当前读取来源是 raw `dsl_payload.timeline`。
- 若 authoritative plan 模式把 `dsl_payload` 设为 `None`，这里不会得到 Beat scripts。

**Why this matters**

证明 visual plan handoff 可以绕过 resolver，但完整 AI Draft worker 还存在 raw DSL 的非视觉依赖。

**Supports**

`Q2`

---

### A4b — Subtitle duration 当前依赖 raw DSL Beats

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_worker`

**Lines**  
`363-381`

**CURRENT CODE**

```python
if enable_subtitles:
    tts_script: dict = context.get_asset("tts_script") or {}
    _translations: dict = {
        lang: text
        for lang, text in tts_script.items()
        if text and str(text).strip()
    }
    # Beat 时长累加；若 LLM 未提供 duration，回退至 target_duration
    _beats_for_dur = _active_payload.timeline if _active_payload else []
    _total_duration = sum(
        float(b.duration) for b in _beats_for_dur if b.duration
    )
    if _total_duration <= 0:
        _total_duration = float(target_duration)

    context.config["translations"] = _translations
    context.config["subtitle_start"] = 0.0
    context.config["subtitle_end"] = _total_duration
```

**CURRENT CODE FACT**

- Subtitle 总时长优先读取 raw DSL Beat durations。
- raw DSL 不存在时退化为 `target_duration`。
- 该依赖不参与 visual asset selection 或 timeline compilation。

**Why this matters**

进一步限定 Q2：pre-resolved visual plan 已够 render，但当前字幕语义并非完全 plan-only。

**Supports**

`Q2`

---

### A4c — Social metadata 当前依赖 raw DSL

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_worker`

**Lines**  
`474-483`

**CURRENT CODE**

```python
_social_fields: dict = {}
if dsl_payload is not None and dsl_payload.meta is not None:
    try:
        _meta_dump = dsl_payload.meta.model_dump()
        _social_fields = {
            k: _meta_dump[k]
            for k in ("social_title", "social_caption", "social_hashtags")
            if _meta_dump.get(k)
        }
```

**CURRENT CODE FACT**

- Social metadata 读取 raw DSL `meta`。
- `CompilationPlan` 本身没有 `meta` 字段。

**Why this matters**

authoritative `CompilationPlan` 不能单独替代 worker 当前全部输入；raw DSL 或等价 metadata 输入仍有非视觉用途。

**Supports**

`Q2`

---

### A4d — History 同时读取 raw meta 与 resolved plan

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_worker`

**Lines**  
`530-543`

**CURRENT CODE**

```python
if render_ok and collected_assets:
    try:
        _elapsed = round(time.time() - _start_time, 1)
        _prompt_details: dict[str, Any] = {
            "meta": (
                dsl_payload.meta.model_dump()
                if dsl_payload is not None and dsl_payload.meta is not None
                else None
            ),
            "timeline": [
                b.model_dump() for b in (working_plan.beats if working_plan else [])
            ],
        }
```

**CURRENT CODE FACT**

- History timeline snapshot 来自 resolved `working_plan`.
- History meta 来自 raw `dsl_payload`.
- 二者在当前代码中承担不同数据职责。

**Why this matters**

Q2 的最小边界不能简单删除 raw DSL 参数；只需阻止它触发 resolver，并保留当前非视觉消费者所需数据。

**Supports**

`Q2 / Q5`

---

## 3. Resolver Evidence

### B1 — CompilationPlan 按 payload Beat 顺序创建

**File**  
`src/api/dsl_parser.py`

**Function / Class**  
`DSLParserNode.parse_and_resolve`

**Lines**  
`90-117`

**CURRENT CODE**

```python
def parse_and_resolve(self, payload: StoryDSLPayload) -> CompilationPlan:
    self._user_hard_tags: List[str] = list(
        getattr(payload, "user_hard_tags", None) or []
    )

    beat_results: List[BeatCompilationResult] = []
    unresolved: List[str] = []

    for beat_node in payload.timeline:
        result = self._resolve_beat(beat_node)
        beat_results.append(result)
        if not result.resolved:
            unresolved.append(beat_node.beat)

    resolved_count = sum(1 for r in beat_results if r.resolved)

    return CompilationPlan(
        engine_type=payload.engine_type,
        beats=beat_results,
        unresolved_beats=unresolved,
        summary=CompilationPlanSummary(
            total_beats=len(beat_results),
            resolved_beats=resolved_count,
            unresolved_beats=len(unresolved),
        ),
    )
```

**CURRENT CODE FACT**

- `payload.timeline` 顺序被保留为 `CompilationPlan.beats` 顺序。
- 每个 Beat resolution result 被放入一个现有 `BeatCompilationResult`。
- 完整 execution 组合在函数返回的 `CompilationPlan` 中同时存在。

**Why this matters**

`CompilationPlan` 是当前最早能对完整 Hook/Context/Build resolution 做一次整体 fingerprint 的现有对象。

**Supports**

`Q1 / Q3 / Q4`

---

### B2 — Explicit multi-hash X selection uses random.choice

**File**  
`src/api/dsl_parser.py`

**Function / Class**  
`DSLParserNode._resolve_locked`

**Lines**  
`190-215`

**CURRENT CODE**

```python
x_track: List[Tuple[LocalAsset, List[str]]] = []
y_from_hash: List[Tuple[LocalAsset, List[str]]] = []

for asset in x_assets:
    axis_type = _axis_type_for_asset(asset)
    matched = _intersect_tags(asset, node.semantic_tags)
    if axis_type in ("X_BASE", "X_STRUCTURE"):
        x_track.append((asset, matched))
    elif axis_type == "Y_LAYER":
        y_from_hash.append((asset, matched))

# 多候选备选池：随机抽取一个 X 轴主素材
if len(x_track) > 1:
    chosen_x = random.choice(x_track)
    logger.info(
        "[DSLParser] locked X轴备选池 %d 个候选，随机抽取 asset_id=%d",
        len(x_track),
        chosen_x[0].id,
    )
    x_track = [chosen_x]
```

**CURRENT CODE FACT**

- 多个 physical X candidates 时，选择方法是 `random.choice`。
- 选择结果只覆盖该次调用的 local `x_track`。
- 原候选池、raw DSL 或 sibling worker state 没有被移除/更新。
- 不存在 sibling exclusion 参数。

**Why this matters**

这是 Context `18/28` 有放回 collision 的直接源码证据。

**Supports**

`Q3 / Q4`

---

### B3a — BGM 被定义为 Y_LAYER

**File**  
`src/api/dsl_parser.py`

**Function / Class**  
`ASSET_REGISTRY` / `_axis_type_for_asset`

**Lines**  
`45-58`, `66-71`

**CURRENT CODE**

```python
ASSET_REGISTRY = {
    "video": {"axis_type": "X_BASE"},
    "scene_master_video": {"axis_type": "X_STRUCTURE"},
    "audio_bgm": {"axis_type": "Y_LAYER"},
    "audio_sfx": {"axis_type": "Y_LAYER"},
    "sfx": {"axis_type": "Y_LAYER"},
    "sticker": {"axis_type": "Y_LAYER"},
    "logo": {"axis_type": "Y_LAYER"},
    "image": {"axis_type": "Y_LAYER"},
    "vfx": {"axis_type": "Y_LAYER"},
    "text_template": {"axis_type": "Y_LAYER"},
}
```

```python
def _axis_type_for_asset(asset: LocalAsset) -> str | None:
    raw = getattr(asset, "asset_type", None)
    if raw is None:
        return None
    return ASSET_REGISTRY.get(str(raw), {}).get("axis_type")
```

**CURRENT CODE FACT**

- `audio_bgm` 明确属于 Y layer。
- Hook 的 BGM physical hash 不会成为 X/main video。

**Why this matters**

证明 Hook 即使被序列化为 `locked`，其 physical BGM 也不能满足 X track，从而触发后续 tag fallback。

**Supports**

`Q3 / Q4 / Secondary`

---

### B3b — Locked-X tag fallback query and scoring

**File**  
`src/api/dsl_parser.py`

**Function / Class**  
`DSLParserNode._resolve_locked`

**Lines**  
`240-255`

**CURRENT CODE**

```python
if next_layer_idx == 0 and node.semantic_tags:
    x_video_types = [
        t for t, v in ASSET_REGISTRY.items()
        if v.get("axis_type") in ("X_BASE", "X_STRUCTURE")
    ]
    x_fallback = self._query_by_tags(
        tags=node.semantic_tags,
        asset_types=x_video_types,
        limit=5,
    )
    if x_fallback:
        scored_fb = _score_candidates(
            x_fallback,
            user_hard_tags=self._user_hard_tags,
            request_tags=node.semantic_tags,
        )
```

**CURRENT CODE FACT**

- Fallback 条件是尚无 X layer 且 Beat 存在 semantic tags。
- 查询被限定为 X video types。
- 查询结果进入 `_score_candidates`。

**Why this matters**

这是 Hook 从 tag-defined DAM pool 产生最终 X candidate ranking 的真实选择路径。

**Supports**

`Q3 / Q4`

---

### B3c — Hook 最终取 scored_fb[0]

**File**  
`src/api/dsl_parser.py`

**Function / Class**  
`DSLParserNode._resolve_locked`

**Lines**  
`267-276`

**CURRENT CODE**

```python
if x_fallback and scored_fb:
    fb_asset, fb_matched = scored_fb[0]
    layers.insert(
        0,
        _make_layer(
            layer_index=0,
            asset=fb_asset,
            matched_tags=fb_matched,
        ),
    )
```

**CURRENT CODE FACT**

- Hook fallback 不随机选整个 list；它取 scoring 后的第一项。
- 该项被写为 `layer_index=0`，成为主视觉层。

**Why this matters**

同一旧 usage 排名和同分随机熵可以使多个 children 得到同一个 Hook layer 0。

**Supports**

`Q3 / Q4`

---

### B3d — Tag query reads exhaustion/deletion/usage state

**File**  
`src/api/dsl_parser.py`

**Function / Class**  
`DSLParserNode._query_by_tags`

**Lines**  
`535-557`

**CURRENT CODE**

```python
query = self._db.query(LocalAsset).filter(
    LocalAsset.is_exhausted.is_(False),
    LocalAsset.is_deleted.is_(False),
)
if asset_types:
    query = query.filter(LocalAsset.asset_type.in_(asset_types))

candidates: List[LocalAsset] = (
    query.order_by(LocalAsset.usage_count.asc()).limit(200).all()
)

results: List[Tuple[LocalAsset, List[str]]] = []
target_set = {t.lstrip("#").lower() for t in tags}

for asset in candidates:
    asset_tags = asset.tags or []
    normalized = {t.lstrip("#").lower() for t in asset_tags}
    matched = list(target_set & normalized)
    if matched:
        results.append((asset, matched))
    if len(results) >= limit:
        break
```

**CURRENT CODE FACT**

- Hook fallback 读取数据库中的 `is_exhausted`、`is_deleted` 和 `usage_count`。
- 候选先按 `usage_count` 升序读取。
- 这里没有读取 sibling selection state。

**Why this matters**

解释 sibling workers 的 planning 结果只可能感知已提交到 DB 的旧 usage，而不是兄弟 child 刚完成的本轮选择。

**Supports**

`Q4`

---

### B4 — Candidate scoring key

**File**  
`src/api/dsl_parser.py`

**Function / Class**  
`_score_candidates`

**Lines**  
`645-655`

**CURRENT CODE**

```python
def _score(pair: Tuple[LocalAsset, List[str]]) -> Tuple[int, int, int, float]:
    asset, matched = pair
    soft_match_count = len(matched)
    return (
        -soft_match_count,
        1 if bool(asset.is_exhausted) else 0,
        cast(int, asset.usage_count) if asset.usage_count is not None else 0,
        random.random(),
    )

return sorted(candidates, key=_score)
```

**CURRENT CODE FACT**

当前 key 顺序明确为：

1. `-soft_match_count`
2. `is_exhausted`
3. `usage_count`
4. `random.random()`

随机只作为最后一层排序维度。

**Why this matters**

证明 Hook 不是纯随机池选择，也不是永远固定 deterministic Top-1；它是 usage-ranked Top-1 with random tie entropy。

**Supports**

`Q3 / Q4`

---

### B5 — usage update 位于 render/history 之后

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_worker`

**Lines**  
`575-602`

**CURRENT CODE**

```python
# ── 6d. 疲劳值回写 ───────────────────────────────────────────────
if render_ok and working_plan:
    try:
        used_asset_ids: set[int] = set()
        for beat in working_plan.beats:
            for layer in beat.layers:
                if layer.asset_id:
                    used_asset_ids.add(layer.asset_id)

        if used_asset_ids:
            _tenant_engine = get_tenant_engine(tenant_id)
            _SessionLocal = sessionmaker(
                autocommit=False, autoflush=False, bind=_tenant_engine
            )
            with _SessionLocal() as db:
                now = datetime.utcnow()
                assets = (
                    db.query(LocalAsset)
                    .filter(
                        LocalAsset.id.in_(used_asset_ids),
                        LocalAsset.is_deleted.is_(False),
                    )
                    .all()
                )
                for asset in assets:
                    asset.usage_count = (asset.usage_count or 0) + 1
                    asset.last_used_at = now
                db.commit()
```

**CURRENT CODE FACT**

源码位置顺序为：

```text
resolve at 245-248
→ timeline/context
→ compositor at 449
→ history INSERT at 530-564
→ usage update at 575-602
```

- 只有 `render_ok` 后才回写 usage。
- planning 时没有 early update/claim。
- 每 worker 独立执行 read-modify-write。

**Why this matters**

siblings 在 planning 阶段无法看到其他 child 本轮刚选择的 Hook。

**Supports**

`Q4`

---

### B6 — Batch combination state targeted search

**File**  
`src/api/routes_dsl.py`  
`src/api/dsl_parser.py`  
`src/api/dsl_adapter.py`

**Function / Class**  
Current submit/batch/resolver/adapter main path

**Lines**  
Targeted whole-file search

**CURRENT CODE / SEARCH**

```text
Search scope:
  src/api/routes_dsl.py
  src/api/dsl_parser.py
  src/api/dsl_adapter.py

Search terms:
  used_assets
  selected_combinations
  reservation
  claim
  excluded_assets
  excluded_combinations
  variant_plan
  combination fingerprint

Result:
  NO MATCHES
```

Separate search:

```text
used_asset_ids:
  routes_dsl.py:578
  routes_dsl.py:582
  routes_dsl.py:584
  routes_dsl.py:594
```

**CURRENT CODE FACT**

- 所列 selection/planning coordination terms 在当前主链中无匹配。
- 唯一相似变量 `used_asset_ids` 位于 B5 的 post-render usage update。
- 它不参与 resolver，也不在 render 前阻止 sibling reuse。

**Why this matters**

Batch-local combination state：**NOT PRESENT IN CURRENT MAIN PATH**。

该结论限定在所列主链文件和搜索词，不声称整个 repository 不存在其他同义或旧路径实现。

**Supports**

`Q4`

---

## 4. CompilationPlan / Timeline Evidence

### C1a — ResolvedLayer 已包含 render-relevant identity

**File**  
`src/api/schemas.py`

**Function / Class**  
`ResolvedLayer`

**Lines**  
`306-323`

**CURRENT CODE**

```python
class ResolvedLayer(BaseModel):
    layer_index: int
    asset_id:    int
    file_path:   str
    asset_type:  str
    file_hash:   str
    asset_name:  Optional[str]  = None
    matched_tags: List[str]     = Field(default_factory=list)
    manifest:    Optional[dict] = None
    layout:      Optional[str]  = Field(
        default=None,
        description=(
            "DSL 最高级空间排版意图；"
            "取值：'center' | 'bottom_center' | 'top_center' | ..."
        ),
    )
```

**CURRENT CODE FACT**

现有 resolved layer 已包含：

- `layer_index`
- `asset_id`
- `file_path`
- `asset_type`
- `file_hash`
- `layout`

**Why this matters**

不需要为了 INV-001 exact visual-combination comparison 发明新的 render intent 数据类型。

**Supports**

`Q3`

---

### C1b — BeatCompilationResult 与 CompilationPlan 结构

**File**  
`src/api/schemas.py`

**Function / Class**  
`BeatCompilationResult` / `CompilationPlan`

**Lines**  
`326-351`

**CURRENT CODE**

```python
class BeatCompilationResult(BaseModel):
    beat:         str
    role:         str
    address_mode: str
    layers:       List[ResolvedLayer] = Field(default_factory=list)
    resolved:     bool
    warnings:     List[str] = Field(default_factory=list)
    script_text:  Optional[str] = None


class CompilationPlanSummary(BaseModel):
    total_beats:      int
    resolved_beats:   int
    unresolved_beats: int


class CompilationPlan(BaseModel):
    engine_type:      str
    beats:            List[BeatCompilationResult]
    unresolved_beats: List[str] = Field(default_factory=list)
    summary:          CompilationPlanSummary
```

**CURRENT CODE FACT**

- `CompilationPlan.beats` 保存有序 Beat results。
- 每个 Beat 保存有序 resolved layers。
- `script_text` 已存在于 resolved Beat result。
- 类型没有声明 `frozen=True` 或其他 type-level immutability config。

**Why this matters**

该对象足以表达当前完整视觉组合，但“冻结”目前只能是调用约定，不是 schema 强制的 immutable type guarantee。

**Supports**

`Q1 / Q2 / Q3`

---

### C2a — Adapter 按 Beat 和 layer_index 确定性遍历

**File**  
`src/api/dsl_adapter.py`

**Function / Class**  
`compile_plan_to_timeline`

**Lines**  
`64-89`

**CURRENT CODE**

```python
timeline = Timeline()

main_v_track = Track(name="main_video", z_index=0, track_type="video")
overlay_z = 1

n_beats = len(plan.beats)
beat_duration: float = target_duration / max(n_beats, 1)

for beat_idx, beat_result in enumerate(plan.beats):
    if not beat_result.resolved or not beat_result.layers:
        continue

    beat_start: float = beat_idx * beat_duration

    for layer in sorted(
        beat_result.layers,
        key=lambda lyr: lyr.layer_index,
    ):
```

**CURRENT CODE FACT**

- Beat 顺序来自 `plan.beats`。
- Layer 顺序由 `layer_index` 排序。
- Beat duration 只由 `target_duration` 和 Beat 数决定。
- 对 `dsl_adapter.py` 的定向搜索未发现 `random`、`shuffle` 或 `choice`。

**Why this matters**

相同 plan 和 target duration 会经过同一遍历顺序；adapter 本身不引入新的选择随机性。

**Supports**

`Q2 / Q3`

---

### C2b — layer_index 0 进入 main_v_track

**File**  
`src/api/dsl_adapter.py`

**Function / Class**  
`compile_plan_to_timeline`

**Lines**  
`131-147`

**CURRENT CODE**

```python
if layer.layer_index == 0:
    main_v_track.add_clip(
        Clip(
            file_path=layer.file_path,
            start_time=0.0,
            duration=beat_duration,
            beat_index=beat_idx,
        )
    )
    logger.debug(
        "[DSLAdapter] beat[%d] → main_v_track: %s",
        beat_idx, layer.file_path,
    )
```

**CURRENT CODE FACT**

- 每个 Beat 的 `layer_index == 0` resolved file path 被追加到同一个 `main_v_track`。
- 插入顺序跟随 C2a 的 Beat 顺序。
- 这里没有 resolver 或 asset selection。

**Why this matters**

当前 INV-001 的 Hook→Context→Build exact combination 可直接从 plan 的 layer 0 序列映射到主视频轨。

**Supports**

`Q2 / Q3`

---

### C2c — Timeline 最终包含 main_v_track

**File**  
`src/api/dsl_adapter.py`

**Function / Class**  
`compile_plan_to_timeline`

**Lines**  
`201-213`

**CURRENT CODE**

```python
if main_v_track.clips:
    timeline.add_track(main_v_track)
    logger.info(
        "[DSLAdapter] main_v_track: %d clips, %d overlay tracks, %d audio tracks",
        len(main_v_track.clips),
        sum(1 for t in timeline.tracks if t.track_type == "overlay"),
        len(timeline.audio_tracks),
    )
else:
    logger.warning("[DSLAdapter] 主视频轨为空")

return timeline
```

**CURRENT CODE FACT**

- 完成后的 `Timeline` 直接返回。
- Main visual clips 已在返回前聚合到 `main_v_track`。

**Why this matters**

提供 `CompilationPlan → Timeline` 的现有明确 handoff。

**Supports**

`Q2 / Q3`

---

### C3a — Timeline 注入 execution-local Context

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_worker`

**Lines**  
`269-305`

**CURRENT CODE**

```python
assert working_plan is not None, "working_plan must be resolved before this point"
timeline = compile_plan_to_timeline(
    working_plan, target_duration=target_duration,
)

if not timeline.tracks:
    return []

context = WorkflowContext(
    session_id=task_id,
    aspect_ratio=aspect_ratio,
    target_duration=target_duration,
    tenant_id=tenant_id,
    batch_size=batch_size,
    test_language=test_language,
)
context.set_asset("timeline", timeline)
```

**CURRENT CODE FACT**

- Resolver 输出先转换为 Timeline。
- 新 `WorkflowContext` 在 selection 和 timeline compilation 之后才创建。
- Timeline 以 `"timeline"` key 放入 Context。

**Why this matters**

证明 authoritative visual plan 到 Context 之间已有一个可识别、无额外 resolution 的边界。

**Supports**

`Q2 / Q4`

---

### C3b — Context 被直接交给 Compositor

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_worker`

**Lines**  
`448-458`

**CURRENT CODE**

```python
# ── 5b. 引擎点火 ───────────────────────────────────────────────
render_ok = _run_compositor(FFmpegCompositorNode(), context)

# ── 5c. 封面抽帧 ───────────────────────────────────────────────
if render_ok:
    logger.info(
        "[render_worker] task_id=%s 渲染完成，启动 CoverNode 封面抽帧...",
        task_id,
    )
    cover_ok = _run_cover_node(CoverNode(), context)
```

**CURRENT CODE FACT**

- Compositor 输入是包含 Timeline 的 Context。
- `render_worker` 不在这里重新访问 resolver。

**Why this matters**

冻结 visual plan 后的实际 render handoff 已存在。

**Supports**

`Q2`

---

### C3c — Compositor 从 Context 读取 Timeline

**File**  
`src/nodes/compositor.py`

**Function / Class**  
`FFmpegCompositorNode.execute`

**Lines**  
`627-633`

**CURRENT CODE**

```python
def execute(self, context: WorkflowContext) -> WorkflowContext:

    # 1. 从 Context 读取 Timeline
    timeline: Timeline = context.get_asset("timeline")
    if not timeline:
        self.log("Warning: no 'timeline' found in Context, skipping render.")
        return context
```

**CURRENT CODE FACT**

- Compositor 消费的是 Context 中已经编译好的 Timeline。
- Compositor 不接收 raw DSL 或 `CompilationPlan`。

**Why this matters**

证实 visual planning 与 actual compositor 之间可以通过现有 Timeline/Context boundary 分离。

**Supports**

`Q2`

---

## 5. Identity Evidence

### D1a — Request session_id 是可选值

**File**  
`src/api/schemas.py`

**Function / Class**  
`RenderDSLRequest`

**Lines**  
`369-373`

**CURRENT CODE**

```python
session_id: Optional[str] = Field(
    default=None,
    description="可选：指定 session_id；留空则由引擎自动生成 UUID。",
)
```

**CURRENT CODE FACT**

- Caller 可提供 `session_id`。
- 默认没有 caller-supplied session identity。

**Why this matters**

`task_id` 可能由外部 session_id 直接决定，不应假定它永远由 backend 新建。

**Supports**

`Q5`

---

### D1b — task_id 生成

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`submit_dsl`

**Lines**  
`966-968`

**CURRENT CODE**

```python
# ── Step 3: 生成唯一 task_id，按 batch_size 选择 worker ──────────────
task_id    = payload.session_id or str(uuid.uuid4())
batch_size = payload.batch_size
```

**CURRENT CODE FACT**

- `task_id` 等于 caller session_id 或一个 UUID4。
- 一次 submit 只执行一次该赋值。
- batch children 不各自生成 task_id。

**Why this matters**

共享 task/UI identity 是当前明确代码语义。

**Supports**

`Q5`

---

### D2 — child file_sid 生成与传递

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_batch_worker`

**Lines**  
`658-669`

**CURRENT CODE**

```python
sub_sids = [uuid.uuid4().hex[:8] for _ in range(batch_size)]
all_assets: list[dict] = []

with ThreadPoolExecutor(max_workers=batch_size) as pool:
    future_map = {
        pool.submit(
            render_worker,
            None if blind_dsl else resolved_plan,
            task_id,
            aspect_ratio, target_duration, tenant_id,
            prompt, batch_size, test_language,
            sid,
```

**CURRENT CODE FACT**

- 每个 child 获得一个 8-hex `file_sid` 参数。
- `file_sid` 不是 request/schema/model 字段。
- 全 repo `src`/`web_ui` 搜索显示 `file_sid` 只出现在 `routes_dsl.py` 的参数、赋值和注释中。
- 它未被持久化，也没有 child index 或 uniqueness check。

**Why this matters**

`file_sid` 已承担部分 child namespace，但当前生命周期很窄。

**Supports**

`Q5`

---

### D3a — WorkflowContext.session_id 与 config 是不同字段

**File**  
`src/core/context.py`

**Function / Class**  
`WorkflowContext.__init__`

**Lines**  
`10-17`, `31-43`

**CURRENT CODE**

```python
def __init__(
    self,
    session_id: Optional[str] = None,
    aspect_ratio: str = "9:16",
    test_language: str = "en",
    target_duration: int = 15,
    batch_size: int = 1,
    script_mode: str = "auto",
    tenant_id: str = "default",
):
    self.session_id = session_id or str(uuid.uuid4())
```

```python
self.config: Dict[str, Any] = {}

self.assets: Dict[str, Any] = {
    "script": "",
    "audio_master": "",
    "video_master": "",
}

self.variants: Dict[str, Dict[str, str]] = {}
```

**CURRENT CODE FACT**

- `context.session_id` 是明确 attribute。
- `context.config` 是另一个独立 dictionary。
- `assets/config/variants` 均为 per-instance containers。

**Why this matters**

解释为何不同 consumers 可以读取两个不同 identity namespace。

**Supports**

`Q5`

---

### D3b — render_worker 写入 full task UUID 与 short file_sid

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_worker`

**Lines**  
`296-313`

**CURRENT CODE**

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

sid8 = file_sid or task_id[:8]
context.config["session_id"] = sid8
```

**CURRENT CODE FACT**

```text
context.session_id           = shared full task_id
context.config["session_id"] = child file_sid, or task_id[:8] for single mode
```

**Why this matters**

这是 master/final 与 TTS/subtitle 路径身份分裂的直接来源。

**Supports**

`Q5`

---

### D4a — Master 使用 config session_id；WS 使用 Context session_id

**File**  
`src/nodes/compositor.py`

**Function / Class**  
`FFmpegCompositorNode.execute`

**Lines**  
`658-666`

**CURRENT CODE**

```python
task_id: str = context.session_id
user_id: str = context.tenant_id
session_id: str = context.config.get("session_id", "")
sid_suffix = f"_{session_id}" if session_id else ""
output_path = f"output/master_video{sid_suffix}.mp4"

map_args = ["-map", "[outv]", "-an"]
```

**CURRENT CODE FACT**

- Master filename 使用 `context.config["session_id"]`。
- Compositor task/WS identity 使用 `context.session_id`。
- Master 是无音频 `-an` 输出。

**Why this matters**

不同 child 可拥有不同 master path，同时仍属于同一 UI task。

**Supports**

`Q5`

---

### D4b — Final 使用 config session_id

**File**  
`src/nodes/compositor.py`

**Function / Class**  
`FFmpegCompositorNode._render_variants`

**Lines**  
`817-834`

**CURRENT CODE**

```python
task_id: str = context.session_id
user_id: str = context.tenant_id

timeline: Timeline = context.get_asset("timeline")
audio_tracks = timeline.audio_tracks if timeline else []

for lang, assets in context.variants.items():
    ass_path: str = assets.get("subtitle_ass", "")
    voice_path: str = assets.get("voice_audio", "")
    session_id: str = context.config.get("session_id", "")
    sid_suffix = f"_{session_id}" if session_id else ""
    final_path = f"output/final_{lang}{sid_suffix}.mp4"
```

**CURRENT CODE FACT**

- Final filename使用 child `config["session_id"]`。
- Final 读取 TTS/ASS path 值，但这些 path 如何命名由 E1/E2 决定。
- WS task identity仍是 full `context.session_id`。

**Why this matters**

final output namespace 已 child-local，而中间 voice/subtitle namespace并未对齐。

**Supports**

`Q5`

---

### D4c — Cover 使用 config session_id

**File**  
`src/nodes/cover_node.py`

**Function / Class**  
`CoverNode.execute`

**Lines**  
`78-82`

**CURRENT CODE**

```python
session_id: str = context.config.get("session_id", context.session_id)
output_dir = os.path.dirname(video_path) or "output"
cover_path = os.path.join(output_dir, f"cover_{session_id}.jpg")
logger.info("[CoverNode] 封面输出路径: %s", cover_path)
```

**CURRENT CODE FACT**

- Cover 优先使用 child `config["session_id"]`。
- 只有该 config key 缺失时才 fallback 到 shared `context.session_id`。

**Why this matters**

现有 `file_sid` 已经被 master/final/cover 三类 child output 使用。

**Supports**

`Q5`

---

### D4d — Batch WebSocket 保持 shared task_id

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_batch_worker`

**Lines**  
`700-713`

**CURRENT CODE**

```python
final_status = "completed" if all_assets else "failed"
ws_manager.broadcast_sync(
    {
        "type": "WS_UPDATE",
        "payload": {
            "taskId": task_id,
            "status": final_status,
            "generation_mode": director_mode,
            **({"assets": all_assets} if all_assets else {}),
        },
    },
    user_id=tenant_id,
)
```

**CURRENT CODE FACT**

- Batch completion event 使用 shared `task_id`。
- 所有 child outputs 被放入同一个 event payload。
- `file_sid` 不作为 WS task identity。

**Why this matters**

证明 child namespace 与现有 batch/UI identity 可以保持为两个不同层次。

**Supports**

`Q5`

---

### D4e — Identity consumer cross-reference

| Consumer | Identity source | Evidence |
|---|---|---|
| Master | `context.config["session_id"]` | D4a |
| Final | `context.config["session_id"]` | D4b |
| Cover | config session ID, fallback Context session ID | D4c |
| TTS MP3/VTT | `context.session_id` | E1a |
| Subtitle ASS | `context.session_id` | E2a |
| TaskHistory | shared `task_id` | F2 |
| WebSocket | shared `task_id` / `context.session_id` | D4a, D4b, D4d |

---

## 6. TTS / Subtitle Evidence

### E1a — TTS path 使用 Context session_id

**File**  
`src/nodes/tts_node.py`

**Function / Class**  
`TTSNode.execute`

**Lines**  
`188-190`

**CURRENT CODE**

```python
session_id = getattr(
    context,
    "session_id",
    context.config.get("session_id", "default"),
)
output_path = self._output_dir / f"voice_{session_id}_{target_lang}.mp3"
vtt_path    = self._output_dir / f"voice_{session_id}_{target_lang}.vtt"
```

**CURRENT CODE FACT**

- `WorkflowContext` 始终存在 `session_id` attribute，因此正常路径使用 full shared task UUID。
- `context.config["session_id"]` 只在 attribute 不存在时才可能成为 fallback。
- Path 不包含 `file_sid` 参数本身。

**Why this matters**

batch children 的 MP3/VTT path 相同。

**Supports**

`Q5`

---

### E1b — TTS 使用 destructive write modes

**File**  
`src/nodes/tts_node.py`

**Function / Class**  
`TTSNode._run_tts_async`

**Lines**  
`92-107`

**CURRENT CODE**

```python
communicate = edge_tts.Communicate(
    text,
    voice,
    rate=self._rate,
    boundary="WordBoundary",
)
submaker = edge_tts.SubMaker()

with open(str(output_path), "wb") as audio_file:
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_file.write(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            submaker.feed(chunk)

srt_content = submaker.get_srt()
vtt_content = "WEBVTT\n\n" + srt_content.replace(",", ".")
with open(str(vtt_path), "w", encoding="utf-8", newline="\n") as vtt_file:
    vtt_file.write(vtt_content)
```

**CURRENT CODE FACT**

- MP3 以 `"wb"` 打开。
- VTT 以 `"w"` 打开。
- 本函数没有 lock、child suffix、临时路径或 atomic rename。

**Why this matters**

共享 path 不只是共同读取；它是共享 writable namespace。

**Supports**

`Q5`

---

### E2a — Subtitle ASS path 与 primary write

**File**  
`src/nodes/subtitle.py`

**Function / Class**  
`SubtitleNode.execute`

**Lines**  
`394-418`

**CURRENT CODE**

```python
target_lang = getattr(context, "test_language", "en") or "en"

session_id = getattr(
    context,
    "session_id",
    context.config.get("session_id", "default"),
)
ass_path = str(output_dir / f"sub_{session_id}_{target_lang}.ass")
vtt_path: str = (
    context.variants.get(target_lang) or {}
).get("vtt_path", "")

if vtt_path and os.path.exists(vtt_path):
    cues = self._parse_vtt(vtt_path)
    if cues:
        chunks = self._chunk_cues(cues, max_chars=25)
        ass_content = self._build_ass_from_cues(...)
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
        context.set_variant_asset(
            target_lang,
            "subtitle_ass",
            ass_path,
        )
        return context
```

**CURRENT CODE FACT**

- ASS path 使用 full `context.session_id`。
- Precision/VTT 分支以 `"w"` 写入共享 ASS。
- `context.variants` 是 child-local dictionary，但保存的 physical path string 相同。

**Why this matters**

execution-local Context 并没有自动带来 physical path isolation。

**Supports**

`Q5`

---

### E2b — Subtitle fallback 也覆盖同一 ASS

**File**  
`src/nodes/subtitle.py`

**Function / Class**  
`SubtitleNode.execute`

**Lines**  
`432-444`

**CURRENT CODE**

```python
t_start = float(context.config.get("subtitle_start", 0.0))
t_end   = float(context.config.get("subtitle_end", 5.0))
ass_content = self._build_ass_fallback(
    text=text,
    t_start=t_start,
    t_end=t_end,
    lang=target_lang,
    font_name=font_name,
    font_size=font_size,
    max_chars=max_chars,
)
with open(ass_path, "w", encoding="utf-8") as f:
    f.write(ass_content)
context.set_variant_asset(target_lang, "subtitle_ass", ass_path)
```

**CURRENT CODE FACT**

- Fallback path 仍使用同一个 `ass_path`。
- Fallback 分支也以 `"w"` 覆盖文件。

**Why this matters**

ASS collision 不局限于 VTT precision mode。

**Supports**

`Q5`

---

### E3 — TTS/Subtitle 不包含 child namespace

**File**  
`src/nodes/tts_node.py`  
`src/nodes/subtitle.py`

**Function / Class**  
Whole-file targeted search

**Lines**  
Whole files

**CURRENT CODE / SEARCH**

```text
Search terms:
  file_sid
  child_index
  execution_id

Result:
  NO MATCHES
```

**CURRENT CODE FACT**

TTS/Subtitle path 中的 child namespace：**NOT PRESENT**。

**Why this matters**

当前 `file_sid` 无法隔离 MP3/VTT/ASS，因为这些 nodes 完全看不到它。

**Supports**

`Q5`

---

## 7. TaskHistory Evidence

### F1a — TaskHistory model

**File**  
`src/api/models.py`

**Function / Class**  
`TaskHistory`

**Lines**  
`131-145`

**CURRENT CODE**

```python
class TaskHistory(Base):
    __tablename__ = "task_history"

    id             = Column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
    )
    task_id        = Column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    prompt         = Column(String, nullable=False)
    batch_size     = Column(Integer, nullable=False, default=1)
    duration       = Column(Float, nullable=False, default=0.0)
    output_assets  = Column(JSON, nullable=False)
    prompt_details = Column(Text, nullable=True)
    created_at     = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
    )
```

**CURRENT CODE FACT**

- `task_id` 有 unique constraint。
- 同一 row 包含 `batch_size`。
- 同一 row 的 `output_assets` 是 JSON collection，而非单 output FK。
- Model 没有 child/execution ID 字段。

**Why this matters**

当前模型形状更接近 one history row per submitted task/batch，而非 one row per child。

**Supports**

`Q5`

---

### F1b — 旧 Matrix 路径聚合后写一条 History

**File**  
`src/api/services.py`

**Function / Class**  
`run_matrix_job`

**Lines**  
`258-271`

**CURRENT CODE**

```python
# 4.6 写入 TaskHistory 记录历史
if history_assets:
    real_duration = round(time.time() - start_time, 1)
    history_record = TaskHistory(
        task_id=session_id,
        prompt=prompt,
        batch_size=batch_size,
        duration=real_duration,
        output_assets=history_assets,
        created_at=_now(),
    )
    db.add(history_record)
    logger.info(
        "[services] 往 task_history 表中写入了 1 条历史归档记录"
    )
```

**CURRENT CODE FACT**

- 该路径把聚合后的 `history_assets` 一次写入一个 TaskHistory。
- `batch_size` 与整个 assets list 同属该 row。

**Why this matters**

与 F1a 一起支持当前数据模型的 batch/task-level persistence 语义。

**Supports**

`Q5`

---

### F2 — DSL render_worker 每 child INSERT 同一 task_id

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_worker`

**Lines**  
`549-564`

**CURRENT CODE**

```python
_history_record = TaskHistory(
    task_id=task_id,
    prompt=_history_prompt,
    batch_size=batch_size,
    duration=_elapsed,
    output_assets=collected_assets,
    prompt_details=_details_json,
    created_at=datetime.utcnow(),
)
_hist_engine = get_tenant_engine(tenant_id)
_HistSession = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=_hist_engine,
)
with _HistSession() as _db:
    _db.add(_history_record)
    _db.commit()
```

**CURRENT CODE FACT**

- 该代码位于 `render_worker`，所以 batch4 最多执行四次。
- 四个 workers 的 `task_id` 相同。
- 每个 row 只包含该 child 的 `collected_assets`。
- F1a 要求 `task_id` unique。

因此当前代码直接形成：

```text
multiple INSERT
+ same task_id
+ unique constraint
→ UNIQUE violation
```

即使 workers 串行运行，第二次 INSERT 仍会失败。

**Why this matters**

证明 TaskHistory collision 不需要改变 batch/UI task identity 即可解释。

**Supports**

`Q5`

---

### F3 — Batch aggregation 已拥有完整 all_assets

**File**  
`src/api/routes_dsl.py`

**Function / Class**  
`render_batch_worker`

**Lines**  
`681-713`

**CURRENT CODE**

```python
for future in as_completed(future_map):
    sid = future_map[future]
    try:
        assets = future.result()
        if assets:
            all_assets.extend(assets)
            logger.info(
                "[render_batch_worker] 子任务完成 sid=%s assets=%d",
                sid,
                len(assets),
            )
    except Exception:
        logger.exception(
            "[render_batch_worker] 子任务异常 sid=%s",
            sid,
        )

final_status = "completed" if all_assets else "failed"
ws_manager.broadcast_sync(
    {
        "type": "WS_UPDATE",
        "payload": {
            "taskId": task_id,
            "status": final_status,
            "generation_mode": director_mode,
            **({"assets": all_assets} if all_assets else {}),
        },
    },
    user_id=tenant_id,
)
```

**CURRENT CODE FACT**

- Coordinator 在 futures 全部完成后拥有聚合 `all_assets`。
- 同一位置还拥有 shared `task_id`、`batch_size`、`prompt` 等函数参数。
- 当前这里只发 WS completed；没有创建 `TaskHistory`。

**Why this matters**

现有 batch aggregate boundary 已掌握完整 outputs list，足以让人工判断 one-row persistence 是否应位于该现有边界。

**Supports**

`Q5`

---

## 8. Frontend Serialization Evidence

### G1 — Tactical Board physical/tag item model

**File**  
`web_ui/src/views/DslOrchestratorDrawer.vue`

**Function / Class**  
`cloneAsset` / `cloneTag`

**Lines**  
`495-513`

**CURRENT CODE**

```javascript
function cloneAsset(asset) {
  return {
    uuid:       `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    type:       'physical_asset',
    id:         asset.id,
    hash:       asset.file_hash,
    asset_type: asset.asset_type || 'video',
    file_path:  asset.file_path,
    name:       asset.file_path.split(/[/\\]/).pop(),
    manifest:   asset.manifest ?? null,
  }
}

function cloneTag(tag) {
  return {
    uuid: `tag_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    type: 'semantic_tag',
    tag,
  }
}
```

**CURRENT CODE FACT**

- Physical item 携带 asset hash、type 和 path。
- Semantic item 只携带 tag。
- UI drag UUID 不进入 backend selection identity。

**Why this matters**

解释一个 Beat 可以同时包含 physical asset 和 semantic tag，并形成不同 backend candidate representations。

**Supports**

`Q3 / Q4`

---

### G2 — buildTimelineFromTracks serialization

**File**  
`web_ui/src/views/WorkspaceView.vue`

**Function / Class**  
`buildTimelineFromTracks`

**Lines**  
`334-355`

**CURRENT CODE**

```javascript
function buildTimelineFromTracks() {
  return dslTracks.value
    .map(track => {
      const physicals = track.items.filter(
        i => i.type === 'physical_asset' || !i.type
      )
      const tags = track.items.filter(
        i => i.type === 'semantic_tag'
      )
      const layoutHints = {}
      physicals.forEach(pill => {
        if (pill.layout) layoutHints[pill.hash] = pill.layout
      })
      const beatNode = {
        beat:          track.id,
        role:          track.role,
        script_text:   track.script_text || '',
        visual_script: track.visual_script || '',
        emotion:       track.emotion || '',
        address_mode:  physicals.length > 0 ? 'locked' : 'smart',
        asset_hashes:  physicals.map(i => i.hash),
        semantic_tags: tags.map(i => i.tag),
      }
      if (Object.keys(layoutHints).length > 0) {
        beatNode.layout_hints = layoutHints
      }
      return beatNode
    })
    .filter(
      b => b.asset_hashes.length > 0 ||
           b.semantic_tags.length > 0
    )
}
```

**CURRENT CODE FACT**

- Beat 有任一 physical item 就序列化为 `locked`。
- 所有 physical hashes 都被保留为 `asset_hashes`。
- 所有 tags 都被保留为 `semantic_tags`。
- 前端不在此处选择单一最终 asset。

对本次 UI 状态：

- Hook：BGM physical 使其成为 locked，但 X 视频来自 tag fallback。
- Context：两个 video hashes 构成 locked multi-X candidates。
- Build：一个 video hash 构成 fixed locked X。

**Why this matters**

固定 UI → backend candidate representation 边界。

**Supports**

`Q3 / Q4`

---

### G3a — Drawer confirm 回写 batch settings并触发 submit

**File**  
`web_ui/src/views/WorkspaceView.vue`

**Function / Class**  
`onOrchestratorConfirm`

**Lines**  
`178-195`

**CURRENT CODE**

```javascript
function onOrchestratorConfirm({
  tracks,
  template,
  directRender,
  params,
  meta,
}) {
  dslTracks.value = tracks
  currentTemplate.value = template
  draftMeta.value = meta ?? draftMeta.value

  if (params) {
    batchSize.value       = params.batchSize
    aspectRatio.value     = params.aspectRatio
    testLanguage.value    = params.language
    enableTts.value       = params.enableTts
    enableSubtitles.value = params.enableSubtitles
  }

  if (directRender) {
    import('vue').then(({ nextTick }) => {
      nextTick(() => { blindFission() })
    })
  }
}
```

**CURRENT CODE FACT**

- Drawer confirm 将完整 tracks 和 batch settings 回写 Workspace。
- 前端没有创建 N 个 child execution objects。
- `directRender` 触发一次 `blindFission()` submit 流程。

**Why this matters**

batch expansion 是 backend 行为，不是前端发起四个独立任务。

**Supports**

`Q1 / Q5`

---

### G3b — submit payload 与 API boundary

**File**  
`web_ui/src/views/WorkspaceView.vue`

**Function / Class**  
`blindFission`

**Lines**  
`377-403`

**CURRENT CODE**

```javascript
const blind = hasPrompt && !hasBlocks
const timeline = blind ? [] : buildTimelineFromTracks()

try {
  const payload = {
    engine_type:      currentTemplate.value,
    timeline,
    aspect_ratio:     aspectRatio.value,
    target_duration:  targetDuration.value,
    batch_size:       batchSize.value,
    test_language:    testLanguage.value,
    tenant_id:        store.loggedInUser || 'default',
    mode:             scriptMode.value,
    user_hard_tags:   hardTags,
    meta:             draftMeta.value,
    enable_tts:       enableTts.value,
    enable_subtitles: enableSubtitles.value,
    ...(hasPrompt && { prompt: pureText || rawPrompt }),
  }

  const resp = await axios.post(
    `${store.API_BASE}/api/v1/tasks/submit-dsl`,
    payload,
  )
```

**CURRENT CODE FACT**

- 一次 POST 携带完整 timeline 和 `batch_size`。
- Payload 可携带 prompt。
- Payload literal 中没有 `session_id`。
- 没有 `execution_id`、`variant_id`、seed 或 combination state。

**Why this matters**

固定 AI Draft 从 UI 到 backend 的 identity 和 planning input boundary。

**Supports**

`Q1 / Q4 / Q5`

---

## 9. Secondary BGM Evidence

标记：**SECONDARY / AUDIO ISSUE**

### S1 — Dropped physical asset inherits track semantic tags

**File**  
`web_ui/src/views/DslOrchestratorDrawer.vue`

**Function / Class**  
`onTrackChange`

**Lines**  
`684-700`, `712-717`

**CURRENT CODE**

```javascript
const trackTags = track.items
  .filter(i => i.type === 'semantic_tag')
  .map(i => i.tag)
  .filter(Boolean)

if (trackTags.length === 0) {
  return
}

const liveAsset = props.dbAssetList.find(
  a => a.id === element.id
)
const existingSet = new Set(liveAsset?.tags || [])
const missingTags = trackTags.filter(
  t => !existingSet.has(t)
)
```

```javascript
const resp = await axios.patch(
  `${props.apiBase}/api/v1/assets/${element.id}/append-tags`,
  { tags: missingTags },
)
```

**CURRENT CODE FACT**

- Physical asset 被拖入带 semantic tag 的 track 后，会继承缺失 tags。
- 因此 Hook track 中的 BGM 可以获得 Hook semantic tag。

**Why this matters**

为同一个 BGM 同时从 hash 和 semantic query 被发现提供前端来源。

**Supports**

`Secondary`

---

### S2 — Hash-resolved Y layer 被直接追加

**File**  
`src/api/dsl_parser.py`

**Function / Class**  
`DSLParserNode._resolve_locked`

**Lines**  
`295-311`

**CURRENT CODE**

```python
for asset, matched in y_from_hash:
    layers.append(
        _make_layer(
            layer_index=next_layer_idx,
            asset=asset,
            matched_tags=matched,
        )
    )
    logger.info(
        "[DSLParser] locked Y轴锁定命中 layer=%d asset_id=%d "
        "type=%s tags=%s",
        next_layer_idx,
        asset.id,
        asset.asset_type,
        matched,
    )
    next_layer_idx += 1
```

**CURRENT CODE FACT**

- BGM physical hash 被分类到 `y_from_hash` 后无条件追加到 layers。
- 没有记录已追加 asset IDs 供后续 semantic query 去重。

**Why this matters**

证明 duplicate Y layer 的第一条进入路径。

**Supports**

`Secondary`

---

### S3 — Semantic-tag Y layer 再次独立追加

**File**  
`src/api/dsl_parser.py`

**Function / Class**  
`DSLParserNode._resolve_locked`

**Lines**  
`315-338`

**CURRENT CODE**

```python
if node.semantic_tags:
    y_assets = self._query_by_tags(
        tags=node.semantic_tags,
        asset_types=_y_layer_asset_types(),
        limit=5,
    )
    if next_layer_idx == 0:
        next_layer_idx = 1
    for asset, matched in y_assets:
        layers.append(
            _make_layer(
                layer_index=next_layer_idx,
                asset=asset,
                matched_tags=matched,
            )
        )
        logger.info(
            "[DSLParser] locked Y轴锁定命中 layer=%d asset_id=%d tags=%s",
            next_layer_idx,
            asset.id,
            matched,
        )
        next_layer_idx += 1
```

**CURRENT CODE FACT**

- Semantic Y query 结果被第二个独立 loop 追加。
- 该 loop 没有检查 asset 是否已存在于 `y_from_hash` 或 `layers`。
- Hash Y 与 semantic Y 之间没有 dedup in this function path。

**Why this matters**

同一 BGM 可进入两个 Y layers。该问题属于 audio-layer defect，不解释主视觉 layer 0 collision。

**Supports**

`Secondary`

---

## 10. Gate 2 Readiness Cross-Check

### Q1 — Coordinator 能否在 worker 启动前创建多个独立 CompilationPlan？

**Answer:** `REQUIRES SMALL REFACTOR`

**Evidence:** `A1a, A1b, A2a, A2b, A3b, B1`

事实基础：

- `_parse_plan_from_db` 已能从 raw DSL 创建一个新 plan。
- `render_batch_worker` 已拥有 raw DSL、tenant、batch_size。
- 但当前 coordinator 没有执行 resolution loop。
- 当前 `resolved_plan` 只有单一 slot，不是 N 个 child plans。
- `CompilationPlan` 类型没有正式 frozen/immutable 配置。

因此当前 coordinator **没有** authoritative child plans；现有类型和 resolver boundary 已存在，但需要小范围结构调整才能在 worker 启动前拥有 N 个独立 plans。

---

### Q2 — Worker 能否在最小改动下接受 authoritative pre-resolved CompilationPlan？

**Answer:** `REQUIRES SMALL REFACTOR`

**Evidence:** `A3a, A3c, A4a, A4b, A4c, A4d, C1b, C2a, C3a, C3b, C3c`

事实基础：

- `render_worker` 已有 `plan` 参数。
- `dsl_payload is None && plan is not None` 时，当前代码已经会直接 compile plan，不再 resolve。
- 但只要 raw DSL 非空，raw DSL 分支优先并重新 resolve。
- TTS script、subtitle Beat durations、social meta 和 history meta 当前仍读取 raw DSL。
- Visual render path本身只依赖 `CompilationPlan → Timeline → Context → Compositor`。

所以不是零改动 `YES`，也不是缺乏结构支持；状态为 `REQUIRES SMALL REFACTOR`。

---

### Q3 — 当前最早、最稳定的 exact visual-combination fingerprint 基于什么对象？

**Answer:** `CompilationPlan`

**Evidence:** `B1, C1a, C1b, C2a, C2b`

针对 INV-001 当前 Hook→Context→Build exact main-visual problem，最小现有字段为：

```text
ordered tuple(
  beat.beat,
  layer.file_hash
)
for each beat in CompilationPlan.beats
for layer where layer.layer_index == 0
```

即当前 evidence 中的：

```text
Hook hash → Context hash → Build hash
```

理由：

- Beat 顺序已由 `CompilationPlan.beats` 保存。
- 主视觉由 `layer_index == 0` 明确表示。
- `file_hash` 标识 resolver 选定的物理素材。
- Adapter 按相同顺序确定性映射为 `main_v_track`。

若比较包含 overlay 的完整当前视觉 plan，现有 `asset_type`、`layer_index`、`file_hash`、`layout` 也已在 `ResolvedLayer` 中；这不改变 INV-001 主轨 fingerprint 的最小答案。

---

### Q4 — 防止同 batch 完整组合重复的最小 coordination boundary 在哪里？

**Answer:** `render_batch_worker` 中，child planning 完成后、`pool.submit(render_worker, ...)` 之前；对应 worker 内部边界是 `_parse_plan_from_db` 返回后、`compile_plan_to_timeline` 之前。

**Evidence:** `A2a, A2b, A3b, A3c, B1, B2, B6, C3a`

精确当前代码边界：

```text
DSLParserNode.parse_and_resolve
→ CompilationPlan available
→ [batch-local exact-combination coordination boundary]
→ compile_plan_to_timeline
→ Context
→ Compositor
```

当前 coordinator 在 `routes_dsl.py:661` 直接开始 submit futures，尚未拥有 child plans；当前 worker 在 `routes_dsl.py:248` resolve，并在 `:271` compile。除此之外，主链没有 batch combination state。

这里只定位边界，不给出 Gate 2 实现。

---

### Q5 — 最小可提升为 child execution namespace 的已有 identity 是什么？

**Answer:** `file_sid`，状态为 `REQUIRES SMALL REFACTOR`

**Evidence:** `D1b, D2, D3a, D3b, D4a-D4e, E1a-E3, F1a-F3`

当前已经具备：

- batch coordinator 为每 child 生成 `file_sid`。
- worker 收到它。
- master、final、cover 已通过 `context.config["session_id"]` 使用它。
- shared `task_id` 可继续服务 Queue/WS/batch identity。

当前缺失：

- 只有 8 hex，无碰撞检查。
- 无 formal `execution_id` 语义。
- 无 child index。
- 不进入 request/response/schema/model/history。
- 不进入 TTS/Subtitle。
- 不进入 structured logs/WS child correlation。
- 不持久化。
- 单任务模式使用 `task_id[:8]`，与 batch child 来源不同。

对当前三个 isolation defect的代码边界判断：

- MP3/VTT/ASS collision：现有 `file_sid` 尚未进入对应 nodes，见 E1–E3。
- Master/final/cover：已使用该 child namespace，见 D4a–D4c。
- TaskHistory UNIQUE：在当前模型中不应把 batch `task_id` 改成 child ID；F1/F3 显示模型与 aggregate boundary更接近“shared task_id + one aggregated history row”。

因此 `file_sid` 可以作为已有 child namespace 基础，但当前还不是完整 execution identity。

---

## 11. Evidence Gaps

1. **CompilationPlan formal freeze**

   当前 visual path 未找到对 `plan/working_plan` attribute 的赋值，adapter 也只读 plan；但 `CompilationPlan` 没有 `frozen=True`。  
   是否要求 type-level immutability：源码没有现成决定。

2. **Exact runtime POST body**

   当前源码确定 serializer 规则，但 repository evidence 没有保存 Repro001/002 实际 network request body。具体 Hook payload 是由截图状态与确定性 builder 联合推导。

3. **file_sid uniqueness guarantee**

   `uuid.uuid4().hex[:8]` 被注释称为唯一 suffix，但当前代码没有 collision check 或持久化 unique constraint。

4. **Generic future visual fingerprint**

   本 Bundle 只证明 INV-001 当前主轨 exact combination 可由 ordered layer-0 hashes 标识。是否把 text/overlay/layout/manifest 全部纳入未来通用 fingerprint，不由当前源码决定。

5. **Broader semantic equivalents of reservation**

   B6 是对当前 submit/batch/resolver/adapter 主链和指定词项的定向搜索。没有声称整个 repository 绝对不存在旧路径或不同命名的相似机制。

6. **TTS/subtitle race 的具体 output hash 因果**

   源码足以证明 shared writable paths，但不能仅靠源码决定 Repro001/002 中每个 final audio hash 由哪一次 overwrite 产生。

7. **Critical Gate 2 readiness**

   Q1–Q5 均已有足够源码证据作人工架构判断；没有剩余 `NOT ENOUGH EVIDENCE` 阻止进入后续人工 Review。

本轮证据抽取到此停止。未修改 repository，等待人工 Review。