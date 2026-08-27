# FP-001 Targeted Architecture Review Bundle

## 1. Baseline

```text
branch:
feature/var-001-variation-policy

HEAD:
93359b61a0dbd0eb55c4b19c81961f91ffb2196b

git status --short:
?? doc/investigations/DopaMatrix-Creative-Fingerprint-Contract-Audit-Report.md
```

分支和 HEAD 符合要求，但工作树在本次审查开始前已经存在一个未跟踪文件：

`doc/investigations/DopaMatrix-Creative-Fingerprint-Contract-Audit-Report.md`

本次审查未读取、修改、删除或纳入该文件。最终状态与初始状态一致。

---

## 2. Built-In Beat Identity

来源：[WorkspaceView.vue:149](</E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:149>)

```js
const dslTemplates = {
  content: [
    { id: 'hook',    name: '👑 Hook',    role: 'hook' },
    { id: 'context', name: '📖 Context', role: 'body' },
    { id: 'build',   name: '🛠️ Build',   role: 'body' },
    { id: 'reveal',  name: '✨ Reveal',  role: 'body' },
    { id: 'cta',     name: '🎯 CTA',     role: 'cta'  },
  ],
  ua: [
    { id: 'problem',  name: '💥 Problem',  role: 'hook' },
    { id: 'failure',  name: '💀 Failure',  role: 'body' },
    { id: 'near_win', name: '📈 Near Win', role: 'body' },
    { id: 'reward',   name: '🏆 Reward',   role: 'cta'  },
  ],
}

const currentTemplate = ref('content')

const dslTracks = ref(dslTemplates.content.map(t => ({
  ...t,
  items: [],
  script_text: '',
  visual_script: '',
  emotion: '',
})))
```

当前字段语义：

| 字段 | 当前作用 | 普通编辑面板可编辑 |
|---|---|---:|
| `track.id` | 写入 DSL 的 `beat` 字段 | 否 |
| `track.name` | UI 显示标签 | 否 |
| `track.role` | 写入 DSL 的语义角色 | 否 |
| `script_text` | 台词 | 是 |
| `visual_script` | 分镜描述 | 是 |
| `emotion` | 情绪 | 是 |
| `text_position` | 文本位置 | 是 |

Blueprint 结果按位置映射，而不是按 Beat 名称匹配：

来源：[WorkspaceView.vue:246](</E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:246>)

```js
function applyBlueprintTimelineToTracks(apiTimeline) {
  const rows = Array.isArray(apiTimeline) ? apiTimeline : []
  dslTracks.value = dslTracks.value.map((track, index) => {
    // 用索引直接对位：LLM 的 beat 字段是自由文本，不做字符串匹配
    const row = rows[index]
    if (!row || !Array.isArray(row.semantic_tags)) {
      return {
        ...track,
        items: [],
        script_text: '',
        visual_script: '',
        emotion: '',
      }
    }

    // ...
    return {
      ...track,
      items,
      script_text: row.script_text || '',
      visual_script: row.visual_script || '',
      emotion: row.emotion || '',
    }
  })
}
```

这里的 `...track` 保留内置 `id/name/role`，LLM 返回的自由文本 Beat 不会覆盖内置身份。

DSL 构造：

来源：[WorkspaceView.vue:357](</E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:357>)

```js
function buildTimelineFromTracks() {
  return dslTracks.value
    .map(track => {
      const physicals = track.items.filter(i => i.type === 'physical_asset' || !i.type)
      const tags      = track.items.filter(i => i.type === 'semantic_tag')
      const layoutHints = {}
      physicals.forEach(pill => {
        if (pill.layout) layoutHints[pill.hash] = pill.layout
      })

      const beatNode = {
        beat:          track.id,
        role:          track.role,
        script_text:   track.script_text   || '',
        visual_script: track.visual_script || '',
        emotion:       track.emotion       || '',
        address_mode:  physicals.length > 0 ? 'locked' : 'smart',
        asset_hashes:  physicals.map(i => i.hash),
        semantic_tags: tags.map(i => i.tag),
      }
      if (Object.keys(layoutHints).length > 0) beatNode.layout_hints = layoutHints
      return beatNode
    })
    .filter(b => b.asset_hashes.length > 0 || b.semantic_tags.length > 0)
}
```

提交时，该 timeline 原样进入 `/submit-dsl` payload：

来源：[WorkspaceView.vue:399](</E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/WorkspaceView.vue:399>)

```js
const payload = {
  engine_type: currentTemplate.value,
  timeline,
  // ...
}

await axios.post(`${store.API_BASE}/api/v1/tasks/submit-dsl`, payload)
```

结论：

- 内置定义中的 `track.id` 没有直接重命名 UI。
- `track.name` 是显示文本，未作为 DSL Beat identity 使用。
- 但是模板导入是正常 UI 功能，并且能整体替换 track；因此用户虽然不能“编辑内置 ID”，却可以通过导入让活动 track 获得任意 ID。
- 所以内置 `track.id` 是稳定的代码常量，但不是系统级不可变身份。

---

## 3. Template / Recipe Identity

### Track normalization

来源：[DslOrchestratorDrawer.vue:184](</E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/DslOrchestratorDrawer.vue:184>)

```js
function normalizeDslTracks(tracks, options = {}) {
  const { resetItems = false } = options
  return (tracks || []).map(track => {
    const cloned = JSON.parse(JSON.stringify(track))
    return {
      ...cloned,
      emotion:       cloned.emotion       || '',
      text_position: cloned.text_position || cloned.position || 'center',
      position:      cloned.text_position || cloned.position || 'center',
      visual_script: cloned.visual_script || '',
      script_text:   cloned.script_text   || '',
      items:         resetItems ? [] : (cloned.items || []),
    }
  })
}
```

该函数：

- 原样保留 `id/name/role`。
- 不生成 ID。
- 不 trim、校验或去重 ID。
- 不验证 track schema。

Drawer 构造 DSL 时同样直接使用 `track.id`：

来源：[DslOrchestratorDrawer.vue:399](</E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/DslOrchestratorDrawer.vue:399>)

```js
function buildTimelineFromLocalTracks() {
  return localTracks.value
    .map(track => {
      const physicals = track.items.filter(i => i.type === 'physical_asset' || !i.type)
      const tags = track.items.filter(i => i.type === 'semantic_tag')
      const layoutHints = buildLayoutHints(track, physicals)
      const beatNode = {
        beat:          track.id,
        role:          track.role,
        script_text:   track.script_text   || '',
        visual_script: track.visual_script || '',
        emotion:       track.emotion       || '',
        text_position: track.text_position || track.position || 'center',
        address_mode:  physicals.length > 0 ? 'locked' : 'smart',
        asset_hashes:  physicals.map(i => i.hash),
        semantic_tags: tags.map(i => i.tag),
      }
      if (Object.keys(layoutHints).length > 0) beatNode.layout_hints = layoutHints
      return beatNode
    })
    .filter(b => b.asset_hashes.length > 0 || b.semantic_tags.length > 0)
}
```

### Export/import

来源：[DslOrchestratorDrawer.vue:533](</E:/dopaworkspace/dopamatrix-desktop/web_ui/src/views/DslOrchestratorDrawer.vue:533>)

```js
function exportTemplate() {
  const data = JSON.stringify(localTracks.value, null, 2)
  const blob = new Blob([data], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `dopa_recipe_${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function handleTemplateUpload(event) {
  const file = event.target.files?.[0]
  if (!file) return

  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const importedTracks = JSON.parse(e.target.result)
      if (!Array.isArray(importedTracks)) {
        throw new Error('Template must be an array')
      }

      const hasExistingScript =
        localTracks.value.some(t => t.script_text && t.script_text.length > 0)

      if (hasExistingScript) {
        const choice = window.confirm(/* ... */)
        if (choice) {
          localTracks.value = importedTracks.map((t, index) => {
            const currentTrack = localTracks.value[index] || {}
            return {
              ...t,
              script_text: currentTrack.script_text || '',
              emotion: currentTrack.emotion || t.emotion,
            }
          })
          props.showToast('🛡️ 骨架已应用，AI 台词已保留！')
          return
        }
      }

      localTracks.value = importedTracks
      props.showToast('⚔️ 模板全量覆盖成功！')
    } catch (err) {
      props.showToast('❌ 模板解析失败，非法的 JSON 格式')
    } finally {
      event.target.value = ''
    }
  }
  reader.readAsText(file)
}
```

结论：

A. imported template 能否提供任意 `track.id`？  
**YES。** 唯一结构校验是顶层必须为数组。

B. duplicate track IDs 是否允许？  
**YES。** 导入逻辑不拒绝。Vue 使用 `:key="track.id"`，重复值还可能造成前端组件 identity 冲突，但这不是导入验证。

C. empty IDs 是否允许？  
**导入层 YES。**

- `id: ""` 不被拒绝。
- 缺失 `id` 也不被 importer 拒绝。
- 后端 `beat` 是必填字符串；缺失字段通常会在 request validation 阶段失败。
- 空字符串可进入 schema，但后续 INV fingerprint helper 会因空 Beat identity 拒绝计划。

D. namespace/version/schema ID 是否存在？  
**NONE。** 导出的 recipe 是裸 track 数组，没有 recipe namespace、schema version、template version 或 definition ID。

E. 是否存在等价稳定字段？  
**NONE for Beat identity。**

仓库中存在其他领域的 `slot_key`，用于 scene-master manifest 槽位，不进入 `DSLBeatNode → CompilationPlan → fingerprint` 链路，不能作为现有 Beat identity。

---

## 4. Backend Beat Schema

来源：[schemas.py:259](</E:/dopaworkspace/dopamatrix-desktop/src/api/schemas.py:259>)

```py
class DSLBeatNode(BaseModel):
    beat:          str            = Field(...)
    role:          str            = Field(...)
    address_mode:  str            = Field(...)
    asset_hashes:  List[str]      = Field(default_factory=list)
    semantic_tags: List[str]      = Field(default_factory=list)
    script_text:   Optional[str]  = Field(default="")
    visual_script: Optional[str]  = Field(default="")
    emotion:       Optional[str]  = Field(default="")
    layout_hints:  Dict[str, str] = Field(default_factory=dict)
    tts_params:    Optional[str]  = Field(default="")
    duration:      Optional[float] = Field(default=None)

    social_title:    Optional[str] = Field(default=None)
    social_caption:  Optional[str] = Field(default=None)
    social_hashtags: Optional[str] = Field(default=None)
    emotional_tag:   Optional[str] = Field(default=None)
```

来源：[schemas.py:326](</E:/dopaworkspace/dopamatrix-desktop/src/api/schemas.py:326>)

```py
class BeatCompilationResult(BaseModel):
    beat:         str
    role:         str
    address_mode: str
    layers:       List[ResolvedLayer] = Field(default_factory=list)
    resolved:     bool
    warnings:     List[str] = Field(default_factory=list)
    script_text:  Optional[str] = Field(default=None)
```

来源：[schemas.py:343](</E:/dopaworkspace/dopamatrix-desktop/src/api/schemas.py:343>)

```py
class CompilationPlan(BaseModel):
    engine_type:      str
    beats:            List[BeatCompilationResult]
    unresolved_beats: List[str] = Field(default_factory=list)
    summary:          CompilationPlanSummary
```

现有字段评估：

| 字段 | 能否作为独立、稳定 Beat definition identity |
|---|---:|
| `beat` | 否；任意字符串，来源可被 recipe import 替换 |
| `role` | 否；多个 Beat 共用 `body` |
| `engine_type` | 否；只标识 content/ua，不标识具体 Beat |
| Beat 在列表中的 index | 只表示当前序列位置，不表示跨 recipe 的语义身份 |
| `asset_id` / `file_hash` | 素材身份，不是 Beat 定义身份 |

结论：

**No stable Beat identity exists in the current end-to-end data model.**

内置 `track.id` 是可复用的迁移种子，但当前没有独立、经过验证和版本化的稳定 Beat definition 字段。

---

## 5. Visual vs Structural Identity

| 方案 | Equality 精确含义 | Historical visual duplicate | VAR balanced coverage | Experiment attribution / recipe lineage |
|---|---|---|---|---|
| Option A：`beat_index + main source hash` | Beat 数量相同，且每个顺序位置使用相同规范化主素材 hash；Beat 名称可不同 | 最适合精确“视觉源序列重复”查询 | 当前 Phase 1 足够；轴可按位置组织 | 不足；不同 recipe/语义槽会合并 |
| Option B：`beat_index + stable Beat semantic identity + main source hash` | 相同视觉源序列，并且处于相同稳定语义槽/recipe 结构 | 作为唯一视觉重复键过窄；recipe 更名或结构迁移可能造成假新颖 | 跨 recipe 做语义槽覆盖时更有价值 | 适合，但前提是先建立真正稳定的 Beat definition identity |

结合当前产品模型：

- 当前 Beat 轴主要由有序数组位置驱动。
- Blueprint 映射明确按 index 对位。
- 内置 `track.id` 不是完整的跨 recipe 稳定身份。
- `role` 粒度不足。
- recipe 没有 namespace/version。

因此这两种身份不应被强行合并：

- **Durable Visual Sequence Identity**：排除 Beat 显示/语义名称。
- **Durable Planning Structure Identity**：未来使用独立、稳定、版本化的 Beat definition identity。

当前 INV tuple 仍然包含 `beat_identity`，不能在 FP-001A 中静默改变。

---

## 6. Source Hash Lifecycle

### Hash creation

来源：[routes_assets.py:34](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_assets.py:34>)

```py
def compute_md5(file_path: str) -> str:
    """计算文件的 MD5 值（适合大文件）"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()
```

该循环读取至 EOF，因此是完整文件 MD5，不是抽样 hash。

### Import/store lifecycle

来源：[routes_assets.py:42](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_assets.py:42>)

```py
for file_path in asset_in.file_paths:
    if not os.path.exists(file_path):
        skipped_count += 1
        continue

    try:
        file_hash = compute_md5(file_path)
    except Exception:
        skipped_count += 1
        continue

    existing = db.execute(
        select(LocalAsset).where(LocalAsset.file_hash == file_hash)
    ).scalar_one_or_none()

    if existing:
        if existing.is_deleted:
            existing.is_deleted = False
            existing.file_path = file_path
            existing.asset_type = asset_in.asset_type
            existing.video_role = asset_in.video_role
            existing.tags = asset_in.tags
            existing.entity_id = asset_in.entity_id
            existing.asset_name = asset_in.asset_name
            success_count += 1
        else:
            skipped_count += 1
        continue

    new_asset = LocalAsset(
        file_hash=file_hash,
        file_path=file_path,
        asset_type=asset_in.asset_type,
        video_role=asset_in.video_role,
        tags=asset_in.tags,
        entity_id=asset_in.entity_id,
        asset_name=asset_in.asset_name,
    )
    db.add(new_asset)
```

模型定义：

来源：[models.py:98](</E:/dopaworkspace/dopamatrix-desktop/src/api/models.py:98>)

```py
class LocalAsset(Base):
    __tablename__ = "local_assets_inventory"

    id        = Column(Integer, primary_key=True, index=True, autoincrement=True)
    file_hash = Column(String(64), unique=True, nullable=False, index=True)
    file_path = Column(String(512), nullable=False)
    # ...
```

答案：

A. 是否对完整文件计算？  
**YES。** 以 4096-byte chunk 读取至 EOF。

B. 何时计算？  
在 `/assets/import` 处理每个现存路径时，数据库查重和创建/复活之前。

C. 现有 `LocalAsset.path/file_hash` 能否更新？

- `file_path`：仅发现“同 hash 的已逻辑删除记录被重新导入”时更新。
- `file_hash`：未找到创建后的生产更新路径。
- 普通资产编辑 API 未提供 path/hash 替换。

D. 相同路径文件之后改变，数据库 hash 会刷新吗？  
**NO。**

E. 是否有后台验证或重新 hash？  
**NONE FOUND。**

F. `file_hash` 是否有数据库唯一约束？  
**YES。** `unique=True, nullable=False, index=True`。

G. 不同 DB 行能否共享相同 hash？  
同一数据库的 `local_assets_inventory` 表中，精确相同字符串不能共存。跨不同数据库不受此约束。

---

## 7. Source Mutation Model

**SOURCE_IDENTITY_MUTABLE**

理由：

- DopaMatrix 保存的是外部本地绝对路径。
- 导入时计算一次 MD5。
- 没有复制到内容寻址的不可变存储。
- 没有文件 watcher。
- 没有 worker 启动前重新 hash。
- 没有后台 re-hash reconciliation。

因此，如果：

```text
F:\test\sucai\12.mp4
```

被原地替换，`LocalAsset.file_hash` 不会自动变化。计划可能继续携带旧 hash，但 FFmpeg 从路径读取的是新内容。

对未来 ledger 的影响：

- 存储 hash 当前证明的是“导入时文件内容”，不是必然的“实际渲染时文件内容”。
- 若 ledger 声称能够精确代表已渲染源文件，需要额外明确以下二者之一：
  - 强制素材导入后内容不可变；或
  - 在 authoritative execution/ledger 记录点验证实际文件 hash。
- 在该问题解决前，ledger 可以记录 planning identity，但不能无条件宣称它是 rendered-source exact identity。

---

## 8. Hash Infrastructure

当前主素材 source hash 算法：

```text
MD5
```

生产代码搜索结果：

- 完整文件 MD5：资产导入。
- JSON MD5：虚拟 text-template 防重。
- 其他局部 MD5：输出文件或 compositor quick hash 等不同用途。
- SHA-256 helper：**NONE**
- 通用、带算法标识的 hash helper：**NONE**
- `hash_algorithm` schema/model 字段：**NONE**

模型注释中出现过 “MD5（或 SHA-256）” 描述，但不存在相应 SHA-256 生产实现，不能视为基础设施证据。

结论：

**SHA-256 INFRASTRUCTURE: NONE**

未来契约必须显式标记当前 source hash 为 MD5，不能把现有值无版本地解释为通用 content digest。

---

## 9. Child Fingerprint Handoff

### Current types

来源：[routes_dsl.py:183](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:183>)

```py
_MainVisualFingerprint = tuple[tuple[int, str, int, str], ...]


@dataclass(frozen=True)
class _VariantPlanningResult:
    plans: tuple[CompilationPlan, ...]
    fingerprints: tuple[_MainVisualFingerprint, ...]
    examined_combinations: int
    candidate_space_size: int
    termination_reason: str
    warning_codes: tuple[str, ...]


@dataclass(frozen=True)
class _ChildWork:
    execution: _ChildExecution
    authoritative_plan: Optional[CompilationPlan] = None
    visual_fingerprint: Optional[_MainVisualFingerprint] = None
```

### Child identity allocation

来源：[routes_dsl.py:434](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:434>)

```py
def _create_child_executions(
    task_id: str,
    child_count: int,
) -> list[_ChildExecution]:
    if child_count < 1:
        raise ValueError("child_count must be at least 1")

    children = []
    used_execution_ids = set()
    used_file_sids = set()

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

### Authoritative pairing

来源：[routes_dsl.py:1081](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1081>)

```py
computed_fingerprints = tuple(
    _exact_main_visual_fingerprint(plan)
    for plan in planning_result.plans
)

if (
    computed_fingerprints != planning_result.fingerprints
    or len(set(computed_fingerprints)) != len(computed_fingerprints)
):
    raise ValueError(
        "PLANNER_RESULT_INVALID: authoritative plans/fingerprints mismatch"
    )

identities = (
    _create_child_executions(task_id, len(planning_result.plans))
    if planning_result.plans
    else []
)

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

此时以下对象已被可靠绑定：

```text
accepted plan
+ accepted fingerprint
+ child_index
+ execution_id
+ file_sid
→ _ChildWork
```

### Drop point

来源：[routes_dsl.py:1141](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:1141>)

```py
def _execute_child(work: _ChildWork) -> _ChildResult:
    child = work.execution
    try:
        result = render_worker(
            (
                work.authoritative_plan
                if work.authoritative_plan is not None
                else (None if blind_dsl else resolved_plan)
            ),
            task_id,
            aspect_ratio,
            target_duration,
            tenant_id,
            prompt,
            batch_size,
            test_language,
            child.file_sid,
            execution_id=child.execution_id,
            child_index=child.child_index,
            blind_dsl=blind_dsl,
            engine_type=engine_type,
            director_mode=director_mode,
            dsl_payload=None if blind_dsl else dsl_payload,
            plan_is_authoritative=work.authoritative_plan is not None,
            enable_tts=enable_tts,
            enable_subtitles=enable_subtitles,
        )
```

`work.visual_fingerprint` 没有传入 `render_worker`。

`render_worker` 当前签名中也没有 fingerprint 参数：

来源：[routes_dsl.py:516](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:516>)

```py
def render_worker(
    plan: Optional[CompilationPlan],
    task_id: str,
    # ...
    *,
    execution_id: str,
    child_index: int,
    # ...
    plan_is_authoritative: bool = False,
    enable_tts: bool = True,
    enable_subtitles: bool = True,
) -> _ChildResult:
```

精确丢失位置：

```text
_ChildWork.visual_fingerprint
→ _execute_child()
→ render_worker(...) call omits it
```

---

## 10. Minimal Observability Path

| 方案 | 评价 |
|---|---|
| A. 显式传给 `render_worker` | 最清晰。保留 planner 接受值与 child identity 的绑定；不需要 resolver、DB 或全局状态 |
| B. 只保留在 `_ChildWork`，调用前记录 | 行数最少，但只能证明 coordinator 准备/派发了该 child，不能证明 worker 实际以此 plan 进入执行 |
| C. worker 从 authoritative plan 重算 | 可以验证 worker 收到的 plan，但不能单独证明它与 planner 接受的 fingerprint 配对一致；还会重复计算 |
| D. 放入 Context/config metadata | 间接、弱类型，而且 Context 建立较晚，无法覆盖 worker 早期失败 |

推荐：

**A. Pass `visual_fingerprint` explicitly to `render_worker`.**

推荐的数据流：

```text
planning_result fingerprint
→ _ChildWork.visual_fingerprint
→ render_worker(explicit keyword argument)
→ authoritative worker-entry log
```

未来 digest 可以：

- coordinator 基于接受的 tuple 生成并一同传递；或
- worker 对传入 tuple 生成并验证。

C 可以作为额外一致性检查，但不应替代显式 handoff。

---

## 11. Logging Timing

### Mandatory INFO

推荐在：

```text
render_worker
→ child identity validation 已通过
→ authoritative plan 非空确认
→ working_plan = plan
→ timeline/compositor 开始之前
```

记录一次 mandatory INFO。

该位置具备：

- `task_id`
- `execution_id`
- `child_index`
- `file_sid`
- authoritative plan
- planner 接受的 fingerprint
- future digest

同时能覆盖“worker 已启动但 compositor 前失败”的情况。

目标事件语义：

```text
This child entered authoritative rendering with this exact accepted fingerprint.
```

### Optional DEBUG

在 coordinator 完成 identity allocation 和 `_ChildWork` 构造后记录一次 DEBUG：

```text
accepted fingerprint → allocated child identity
```

用于排查调度与 pairing，但不应再增加第二个默认 INFO，避免重复日志。

推荐结论：

- Mandatory INFO：worker authoritative-plan entry。
- Optional DEBUG：coordinator allocation/pairing。
- 不建议只在 compositor 开始时记录，因为此前失败的 child 会完全失去 fingerprint 证据。

---

## 12. INV-001 Compatibility

当前 fingerprint helper：

来源：[routes_dsl.py:204](</E:/dopaworkspace/dopamatrix-desktop/src/api/routes_dsl.py:204>)

```py
def _exact_main_visual_fingerprint(
    plan: CompilationPlan,
) -> _MainVisualFingerprint:
    if not plan.beats:
        raise ValueError("MAIN_VISUAL_PLAN_INVALID: plan has no Beats")

    fingerprint = []
    for beat_index, beat in enumerate(plan.beats):
        main_layers = [
            layer for layer in beat.layers
            if layer.layer_index == 0
        ]
        if len(main_layers) != 1:
            raise ValueError(...)

        main_layer = main_layers[0]
        if not is_main_visual_asset_type(main_layer.asset_type):
            raise ValueError(...)

        normalized_hash = normalize_file_hash(main_layer.file_hash)
        if not normalized_hash:
            raise ValueError(...)

        beat_identity = str(beat.beat).strip()
        if not beat_identity:
            raise ValueError(...)

        fingerprint.append(
            (beat_index, beat_identity, 0, normalized_hash)
        )

    return tuple(fingerprint)
```

FP-001A 必须保持以下行为不变：

- `_exact_main_visual_fingerprint` tuple shape 和 validation。
- `used_fingerprints` 的 Python tuple/set equality。
- preview seed 通过同一 helper 计算 fingerprint。
- planner candidate capacity/search/warning 行为。
- coordinator 的 plan/fingerprint pairing 和 uniqueness invariant。
- accepted authoritative plan 不重新 resolver。
- `_ChildWork` 中 plan/fingerprint/identity 的现有顺序配对。

能否在不改变当前 tuple equality 的情况下增加 canonical digest/logging？

**YES。**

安全的 additive 边界是：

```text
existing tuple
→ new canonical serialization
→ new digest
→ explicit handoff/logging
```

planner 的所有接受、拒绝和 set membership 仍使用原 tuple。

如果以后建立不含 Beat identity 的 visual-sequence digest，应使用新的 `fingerprint_type/version`，不能静默改变 INV-001 tuple 的含义。

---

## 13. Existing Tests

测试集中在 [test_inv001_variant_planning.py](</E:/dopaworkspace/dopamatrix-desktop/tests/test_inv001_variant_planning.py:140>)。

| Test | Evidence |
|---|---|
| `test_f1_same_ordered_main_hashes_have_same_fingerprint` | 相同 Beat 名和相同有序 hash 产生相同 fingerprint |
| `test_f2_one_main_hash_difference_changes_fingerprint` | 一个主素材 hash 变化会改变 fingerprint |
| `test_f3_beat_order_changes_fingerprint` | 交换 Beat 名称与素材顺序后 fingerprint 不同；没有隔离证明究竟是 Beat 名还是 hash 顺序导致 |
| `test_f4_y_layer_difference_does_not_change_level_one_fingerprint` | Y-layer 差异不影响 fingerprint |
| `test_f5_hash_case_and_whitespace_are_normalized` | hash 大小写及首尾空格被规范化 |
| `test_f6_missing_conflicting_or_nonvisual_main_fails_validation` | 缺失、重复或非视觉 layer 0 被拒绝 |
| `test_p1_p2_p4_and_structural_repro_plan_four_unique_combinations` | 动态 3-Beat candidate pools 生成四个唯一组合 |
| `test_a5_exact_coordinator_binds_unique_plans_after_planning` | coordinator 将两个唯一 authoritative plans 交给 worker，并设置 `plan_is_authoritative=True` |
| `test_a1_a2_a3_authoritative_plan_bypasses_resolver_and_raw_dsl_supplies_metadata` | authoritative worker 不调用 resolver，传入 plan 直接交给 timeline compiler |

明确缺口：

- 没有“只将 `Reveal` 改成 `Product Reveal`，素材和顺序完全不变”的隔离测试。
- 没有显式 5-Beat fingerprint 测试。
- 没有测试 `_ChildWork.visual_fingerprint` 到 worker 的 handoff，因为当前没有该 handoff。
- coordinator pairing 测试通过 worker 收到的 plan 重算 fingerprint，不证明 worker 收到了 planner 原始 fingerprint 对象。
- 没有 source path 被原地替换后 hash stale 的生命周期测试。

---

## 14. Review Findings

### FP-A-01 — BUILT_IN_ID_LOCALLY_STABLE

内置 `track.id` 是源码常量，没有直接 UI rename 控件；`track.name` 是展示字段。

### FP-A-02 — IMPORTED_TRACK_ID_UNVALIDATED

Recipe importer 仅验证顶层为数组。任意、重复、空或缺失 `track.id` 均不在导入时拒绝。

### FP-A-03 — NO_DURABLE_BEAT_IDENTITY

当前不存在系统级 stable Beat definition identity。没有 namespace、schema version、recipe slot ID 或独立 backend 字段。

### FP-A-04 — ROLE_NOT_UNIQUE_IDENTITY

`role` 不能替代 Beat identity；多个 content Beat 都使用 `body`。

### FP-A-05 — VISUAL_AND_STRUCTURAL_IDENTITY_ARE_DISTINCT

视觉源序列重复与 recipe/实验结构归因是两种不同 equality contract，不应共用一个未区分类型的 digest。

### FP-A-06 — SOURCE_HASH_IS_FULL_FILE_MD5

物理素材在导入时计算完整文件 MD5，同一数据库表中由唯一约束防止精确 hash 重复。

### FP-A-07 — SOURCE_ASSET_CAN_MUTATE_BEHIND_STORED_HASH

外部绝对路径内容可被原地替换，数据库 hash 不会自动刷新。

### FP-A-08 — HASH_ALGORITHM_METADATA_ABSENT

没有 SHA-256 helper、通用 hash abstraction 或 `hash_algorithm` 字段。

### FP-A-09 — FINGERPRINT_DROPPED_AT_WORKER_CALL

`_ChildWork` 已正确绑定 fingerprint 与 child identity，但 `_execute_child()` 调用 `render_worker()` 时未传 fingerprint。

### FP-A-10 — CLEAN_ADDITIVE_HANDOFF_EXISTS

显式新增 worker fingerprint 参数即可完成 handoff；不需要 resolver、DB、global state 或 planner 语义改变。

### FP-A-11 — WORKER_ENTRY_IS_AUTHORITATIVE_LOG_POINT

Worker 完成 identity validation 并接受 authoritative plan 后，是回答“child N 实际开始渲染哪个 fingerprint”的最可靠 mandatory INFO 点。

### FP-A-12 — INV_EQUALITY_CAN_REMAIN_UNCHANGED

Canonical digest 和 observability 可以完全建立在现有 tuple 之上，不需要改变 INV-001 equality contract。

---

## 15. Architecture Decision Table

| Decision | Evidence | Recommendation |
|---|---|---|
| Durable visual-sequence identity | 当前 Beat 名称来自可替换字符串；视觉顺序由 Beat index 和主素材 hash 决定 | 建立独立 visual-sequence fingerprint type，排除 Beat 显示/语义名称 |
| Durable planning-structure identity | 内置 ID 有用，但 recipe import 无校验、namespace 或 version | 在稳定 Beat definition contract 建立后，作为独立 structural fingerprint type |
| Beat identity inclusion | 当前 INV tuple 包含 `beat_identity`；直接删除会改变 closed contract | 保留当前 INV tuple；visual duplicate digest 排除它，structural digest 使用未来稳定 ID |
| Source hash algorithm treatment | 当前实际值为完整文件 MD5；无 algorithm metadata | 显式记录 `md5` 和 fingerprint version；不能静默解释为 SHA-256 |
| Source mutation policy | 外部绝对路径可变，无 re-hash | 将 source identity 明确标为 mutable；ledger 精确承诺前必须规定 immutable 或执行时验证 |
| Canonical digest | 当前只有 Python tuple equality | 从现有 tuple 添加确定性序列化和版本化 digest，不替换 tuple equality |
| Runtime log handoff | `_ChildWork` 已有 plan/fingerprint/identity 完整配对 | 显式传入 `render_worker`；worker authoritative entry 记录 mandatory INFO |
| INV compatibility | planner、preview、capacity、coordinator invariant 都依赖现有 helper | Additive only；不修改 helper tuple shape、validation 或 `used_fingerprints` |

---

## 16. Final Git Status

最终检查：

```text
git branch --show-current
feature/var-001-variation-policy

git rev-parse HEAD
93359b61a0dbd0eb55c4b19c81961f91ffb2196b

git status --short
?? doc/investigations/DopaMatrix-Creative-Fingerprint-Contract-Audit-Report.md

git diff --stat
<empty>
```

最终状态与审查开始时完全一致。没有 tracked file 修改；未跟踪报告文件是启动时已有状态。

未实施 FP-001A。未修改代码、测试或 schema。未启动 VAR-001。未 commit，未 push。