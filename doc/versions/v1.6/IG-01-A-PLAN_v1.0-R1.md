# IG-01-A-PLAN v1.0-R1 — Minimal Asset Identity & Re-import Remediation Plan

日期：2026-11-19  
状态：`REVISED PROPOSED IMPLEMENTATION PLAN / OWNER REVIEW REQUIRED / DOCUMENT ONLY`

**Revision Basis：** 基于原始 `IG-01-A-PLAN — Minimal Asset Identity & Re-import Remediation Plan`（531 行）制作；原计划中的调查事实、既有章节、证据锚点和未关闭事项继续继承，除本 R1 明确列出的语义修订外不作重写。

**Revision Boundary：** 本版只修订逻辑身份语义、资格状态维度、ACK 阻断、Purge 保留、IG-01-A/IG-02-B 边界、Generation 事件矩阵及 Seed 旧客户端保护；不选择物理 Schema，不扩大文件 Allowlist，不授权实现或测试。

**本计划仅定义行为、依赖、候选文件及验收要求，不授权实现，也不选择新的物理 Schema。**

## 1. Executive Recommendation

建议采用以下最小路线：

> 保留现有 Asset ID、MD5 判重和历史事实；补齐明确的源版本引用、独立资格证明、资产变更失效规则及逐文件结果。随后单独实施 IG-02 的 Task Admission 和 Actual-use Freshness。

不重建多版本 DAM，不重写历史记录，不把 `LocalAsset.id`、MD5 或路径升级解释为不可变内容身份。

计划可以收敛到行为和验收层，但**尚不能作为可直接执行的文件修改授权**。物理持久化合同、Schema/Restore Readiness、可信授权、COMPAT 和 G1 等依赖仍未关闭。

### Authority readback（继承 INV-01 记录；R1 未重新核验）

| 项目 | INV-01 当时记录值（R1 未重新核验） |
|---|---|
| Main Root | `E:\dopaworkspace\dopamatrix-desktop` |
| Branch | `fix/rc2-final-render-reliability` |
| HEAD | `6fb87450a6b06aaf8f32a0636990f47dcf9ba62e` |
| Tracked Worktree / Index | CLEAN / EMPTY，前后相同 |
| Untracked | 仅既有 `doc/versions/v1.6/DECISIONS.md` |
| Handoff | 32359 bytes |
| Handoff SHA256 | `E2FDAD70CBB096CD20C83C80265A03F3322A8F693FD8CA88DE0AC78C8D6CA991` |
| AGENTS SHA256 | `1513CB2B78E22850697D4F75809E77E7125EF4DE485747E1E11B32CA53ED7645` |

Handoff 的 `NOT_INSTALLED` 头部仍是已知 stale metadata，INV-01 当时没有修改。Git 身份、状态及 Index 查询前后均为 INV-01 记录的 Native Exit `0`；R1 不将其作为本轮重新验证结果。

### 输入及证据层级

- **已接受源码基线**：本对话中的 `IG-01-A-INV-01` 完整报告。下文源码锚点继承该报告；本轮没有重新读取或扩大工程源码审计。
- **本轮直接核对的冻结记录**：IG-00 FROZEN RECORD、OD-01～04、DD2-01～05、AUTH-ACK-01A Owner Gap Resolution。D2、D16、PRD、Acceptance Matrix 的既有引用和结论按原计划继承；本轮不重新审计，也不声称逐项重新核验。
- **适用性限制**：文件可读取、设计已冻结，不等于工程实现或运行资格已经成立。

本文使用：

| 标签 | 含义 |
|---|---|
| `FROZEN PRODUCT CONTRACT` | 已批准的产品义务 |
| `FROZEN DESIGN DECISION` | 已批准的设计方向和条件 |
| `PROPOSED IMPLEMENTATION PLAN` | 本计划提出、待独立批准的工程切分 |
| `OPEN ENGINEERING GATE` | 实施或验收前尚缺的合同/证据 |
| `NOT_VERIFIED` | 未验证 |
| `NOT_AUTHORIZED` | 没有执行权限 |

下文 `D/` 指：

`E:\dopaworkspace\dopamatrix-v1.6-docs\doc\versions\v1.6\`

## 2. INV-01 Finding-to-Remediation Mapping

| INV-01 Finding | 最小整改目标 | 必须保留 | 主要依赖 |
|---|---|---|---|
| INV01-01：Restore 只清除删除标志 | Restore 不得直接恢复 Seed 资格；当前源重新验证、建立当前 Generation | 原 Asset ID、历史记录、原片 | 资格失效、STORAGE、授权、验证能力 |
| INV01-02：活跃 MD5 重复不替换路径 | 返回明确 `DUPLICATE_EXISTING`；禁止把重复识别为新路径替换成功 | MD5 兼容判重 | 逐文件结果、明确替换合同 |
| INV01-03：路径变化可脱离记录身份 | 资格绑定实际源版本；Task 在准入和使用时核验同一版本 | 不原位改写历史 Task/Output | Source Identity、Freshness、IG-02、G1 |
| INV01-04：Restore 与 Revival 不同 | 分别处理两条变更链，但统一要求重新资格验证、旧 Operation 失效 | 既有 ID；两种操作的区分 | 当前 Head/Generation 条件提交 |
| INV01-05：汇总计数无法定位单文件结果 | 每个输入返回 outcome、技术状态、原因、下一步及可用身份引用 | 可兼容保留旧汇总字段 | API/UI 合同、旧客户端保护 |
| INV01-06：历史输入追溯不统一 | 新 Task 能保留实际使用版本；旧记录按原证据解释，不补造 | 历史 JSON、ID、输出、既有语义 | 独立 Task Binding 持久化合同 |

来源：INV-01 第 3～12 节；核心源码为 `routes_assets.py:import_asset:42–97`、`restore_asset:255–265`、`models.py:LocalAsset:266–293`，历史引用见第 9 节。

## 3. Current Asset Identity Semantics

`INV-01 ACCEPTED SOURCE BASELINE`：

| 当前对象/字段 | 当前真实含义 | 不能解释为 |
|---|---|---|
| `LocalAsset.id` | Tenant 数据库内的素材行身份 | 不可变内容版本 |
| `file_hash` | Import 使用的 MD5 判重键 | SHA256、当前完整 Proof |
| `file_path` | 被保存和消费的路径字符串 | 稳定原片对象或所有权证明 |
| 文件名 | UI 从路径显示的 basename | 判重键或版本键 |
| `asset_name` | 人工可读名称 | 内容身份 |
| `is_deleted` | 回收站逻辑状态 | 媒体技术状态 |
| `usage_count/is_exhausted` | 使用/防疲劳状态 | 媒体健康 PASS |
| `manifest` | 通用扩展载荷 | 已存在的资格 Authority |

来源：`src/api/models.py:LocalAsset:266–293`；`routes_assets.py:compute_md5:34–40`、`import_asset:64–91`；`AssetsView.vue:template:626–628`。

必须保留两个结论：

1. **同名重导入没有统一的“新 ID”结果**：取决于 MD5 命中及删除状态。
2. **当前未发现技术 Proof 合同**：不能将旧元数据保留描述为已经证实的“旧 PASS 继承”。

本计划不重新定义 `file_hash`，不全局替换现有 MD5，也不改变既有规划/防重身份语义。

## 4. Proposed Minimum 1.6 Content Version Semantics

### 4.1 逻辑对象必须分离（不构成物理 Schema）

以下是逻辑身份与引用模型，不是表、字段、Manifest Schema、编码格式或 DDL 方案：

```text
Tenant
  → Asset Identity
      ├─ Content Version Identity
      └─ Source Binding Revision

Qualification Proof
  → 绑定 Content Version + Source Binding Revision + 流/策略/工具/证据
      ├─ Generation
      └─ Operation Identity

Task Source Binding
  → 精确引用 Asset + Content Version + Source Binding Revision + 当前有效 Proof

Output / Creative Lineage
  → 引用实际 Task Source Binding（由 IG-02-B 及后续独立范围承接）
```

| 概念 | 最低语义 | 不得替代的概念 |
|---|---|---|
| **Asset Identity** | 保留现有 `LocalAsset.id`；表示 Tenant 约束下的逻辑素材身份 | 内容版本、路径授权、Proof |
| **Content Version Identity** | 表示实际内容字节的一次明确版本；用于区分同一 Asset 内容发生变化前后 | 来源路径、来源授权、资格激活 |
| **Source Binding Revision** | 表示某个 Asset 对获授权实际源对象/位置及其已观察内容的受控绑定版本 | 仅凭路径、文件名或哈希形成的权限证明 |
| **Qualification Proof** | 对特定 Content Version、Source Binding Revision、流、策略和工具完成验证的证据 | Asset 的永久属性或跨来源通用凭据 |
| **Generation** | 一次资格流程的代次，用于隔离新旧验证、确认和迟到结果 | Content Version 或 Task/Render Attempt Generation |
| **Operation Identity** | 一次具体资格操作及其两阶段确认的身份 | 内容身份或独立授权主体 |
| **Task Source Binding** | Task/Child 接受并实际使用的精确 Asset、版本、来源绑定和 Proof 引用 | “当前 Asset 最新 Head”或动态追随最新版本 |
| **Output / Creative Lineage** | 新输出与其实际 Task Source Binding 的关系 | 对旧历史进行反向补造的完整血统账本 |

六个核心身份/资格概念（Asset、Content Version、Source Binding Revision、Proof、Generation、Operation）必须保持语义独立；Task Source Binding 和 Output Lineage 是下游引用关系，不因此并入 IG-01-A 的实施范围。

### 4.2 Content Version 与 Source Binding Revision 的变化规则

`PROPOSED IMPLEMENTATION PLAN`：

- **实际字节改变，即使路径不变：** 必须建立新的 Content Version Identity，并推进 Source Binding Revision，以表示该来源绑定现在指向了不同的实际内容；旧 Proof 不再允许当前源正常使用。
- **来源路径/对象改变，即使实际字节完全相同：** Content Version Identity 可以保持相同；必须建立新的 Source Binding Revision，重新确认来源授权和绑定，不得静默沿用旧 Operation 的确认或把旧 Proof 自动扩展到新来源。
- **路径和字节均未变化：** 不能仅凭路径、size、mtime 或 legacy MD5 推导资格仍然新鲜；必须依赖适用的实际字节身份、来源绑定和既有 Gate 证据。
- SHA256 和实际字节数属于内容描述；**单独相同 SHA256 不构成 Tenant 权限、路径权限、来源授权或 Proof 复用权**。
- 文件名、路径、size、mtime、legacy MD5 均不能单独建立 Content Version、Source Binding Revision 或资格。
- 无可信版本/来源绑定证据的旧行按 `NOT_EVALUATED` 投影，不批量生成版本、Proof 或 PASS。
- 以上为逻辑变化规则，不承诺本轮已经具备持续监测、不可变文件句柄或消除所有 TOCTOU 窗口的实现能力。

### 4.3 Version、Generation、Proof 与 Operation 的区别

| 概念 | 何时变化 |
|---|---|
| Content Version Identity | 实际内容字节变化时变化；字节相同不因路径变化自动变成不同内容版本 |
| Source Binding Revision | 来源对象/位置重绑定，或同一来源位置观察到实际内容变化时变化 |
| Qualification Generation | 新资格验证、重新确认、撤销/替代旧资格操作时按获批合同推进；不复用 Task/Render Attempt Generation |
| Proof Identity | 对某一 Content Version + Source Binding Revision 完成一次具体策略/工具验证时建立 |
| Operation Identity | 一次资格操作及其两阶段确认的身份；必须绑定当前 Tenant、Asset、版本/来源绑定、Generation |

同一 Content Version 可以对应多个 Source Binding Revision；同一来源路径也可能因内容改变而对应新的 Content Version 和 Source Binding Revision。同一版本可能因策略变化重新验证；新 Generation 不自动等于新内容。同样，重新生成 Operation ID 不证明字节未变。

冻结依据：`D/IG-00…FROZEN.md:§6.3:329–348`；`D/AUD-03-D1_SEED_IMPORT_GATE_CONTRACT.md:§8:157–169`。

## 5. Qualification Proof Binding and Invalidation Rules

### 5.1 必须绑定的逻辑信息

继承 D2-05，不新增物理 Schema：

```text
可信 Tenant 授权上下文
+ Asset Identity
+ Content Version Identity
+ Source Binding Revision
+ 获授权的实际源路径/对象及其绑定事实
+ SHA256 / 实际字节身份
+ Selected Stream
+ Profile / Policy / Checker / Tool Identity
+ 完整验证证据
+ 必要资源责任条件
+ 当前 Generation / Operation / 两阶段确认
```

依据：`D/AUD-03-D1_SEED_IMPORT_GATE_CONTRACT.md:159–167`；`D/IG-00…FROZEN.md:329–354,524–528`。

**未来 Tenant 必须来自经批准、可验证的服务端授权上下文；不得信任 Body 自报 Tenant。当前实际授权来源仍为 UNKNOWN / NOT_VERIFIED。**

Content Version 描述实际内容；Source Binding Revision 描述该 Asset 对获授权来源对象/位置及已观察内容的具体绑定。二者必须分别引用，不能用一个 `source_revision/version` 字段的含混语义替代。

### 5.2 失效规则

| 事件 | 最低处理 |
|---|---|
| 实际字节变化（包括同一路径原位替换） | 新 Content Version + 新 Source Binding Revision；原 Proof 不再允许当前源正常使用；重验或阻断 |
| 路径/来源对象重绑定，字节相同 | Content Version 可保持；建立新 Source Binding Revision；重新确认源权限，不自动继承旧 Operation 确认或激活资格 |
| 路径/来源对象重绑定且字节变化 | 新 Content Version + 新 Source Binding Revision；旧 Proof 失效并重新资格验证 |
| Trash | 当前资格不可选，撤销当前激活能力并使旧 Operation/迟到结果不能再激活；保留历史绑定事实 |
| Trash Restore | 不恢复旧 PASS；重新确认当前源绑定并启动新资格流程 |
| 同 MD5 Revival | MD5 只负责兼容判重；源重绑定时建立新 Source Binding Revision，必要时建立新 Content Version；新资格 Generation，不凭 MD5 沿用旧资格 |
| Checker/Tool/Profile/Policy 变化 | 按已批准兼容规则重新认证；规则缺失则 Fail Closed |
| 授权过期、撤销或不可验证 | 不能执行受保护的激活或正常资格消费 |
| DB Restore / Schema 非就绪 | 当前资格不可用，不自动恢复历史 PASS；遵守 DD2-04 的可信恢复 barrier |
| 迟到验证结果/ACK/Recover | 仅当前绑定与 Generation 可提交；不得覆盖新 Head 或重新激活已撤销资格 |
| Native/Reader/Pipe/Handle UNKNOWN | 不产生 PASS，并保留既有资源安全阻断；不得将 UNKNOWN 降格成普通媒体错误 |

失效当前资格，**不等于删除旧 Proof、历史 Task 或 Output**。

### 5.3 原子性要求

在未来批准的持久化合同中，以下事实必须一致：

- 当前 Asset Head 所指向的 Content Version 与 Source Binding Revision；
- 当前资格 Proof、Generation、Operation 及其两阶段确认事实；
- Generation 的建立和旧操作撤销；
- 验证结果对当前版本/来源绑定的条件提交；
- ACK 对当前 Operation/Generation 的条件激活；
- Trash/Purge 对迟到验证、ACK、Recover 和旧幂等请求的拒绝；
- Purge 后必要的历史引用、幂等墓碑及资源 UNKNOWN 责任记录仍可被安全解释。

长时间哈希、解码不得持有 SQLite 长写事务。数据库事务也不能被描述为与文件变化、进程退出或 HTTP 送达构成一个原子事务。

这些是能力要求，不是本轮选定的表、列、索引、保留期限或 DDL。

### 5.4 Generation 与 Source Binding Revision 事件矩阵

下表是逻辑行为矩阵，不是数据库更新脚本；具体条件提交和持久化方式仍须独立批准。

| 操作/事件 | Content Version Identity | Source Binding Revision | Qualification Generation / Operation |
|---|---|---|---|
| Fresh Import | 建立当前实际内容版本 | 建立当前获授权来源绑定 | 建立新资格 Generation / Operation |
| Active Duplicate | 不因重复请求自动创建现有 Asset 的新版本 | 不把提交的新路径自动绑定到已有 Asset | 不自动继承新请求的 ACK/Proof；返回重复事实及既有资格事实 |
| 同一路径实际字节改变 | 建立新版本 | 推进来源绑定版本，记录新观察内容 | 撤销旧操作激活能力，启动新资格 Generation |
| 不同路径重绑定、字节相同 | 内容版本可保持 | 必须建立新来源绑定版本 | 旧 Operation 确认不复用；新资格流程 |
| 不同路径重绑定、字节改变 | 建立新版本 | 建立新来源绑定版本 | 新资格 Generation / Operation |
| Trash | 保留历史版本 | 保留历史绑定事实 | 撤销当前激活能力并推进失效 fence；不终止运行中 Task |
| Trash Restore | 不预设内容未变；重新确认 | 重新确认当前来源，建立新的有效绑定事实 | 不恢复旧 PASS；启动新资格 Generation |
| 同 MD5 Revival | 以实际字节证据确定是否同一内容版本 | 因来源重绑定建立新绑定版本 | 新资格 Generation / Operation |
| Purge | 退役当前 Asset 引用；不反向改写历史事实 | 退役当前绑定；保留必要引用语义 | 撤销当前激活能力；保留必要 Proof/Operation/幂等墓碑/UNKNOWN 记录，防止旧 ID 或请求复活资格 |

**特别限制：** Active Duplicate 只表示兼容判重命中，不等于对新提交路径完成授权、重绑定、重新验证或 PASS。Purge 也不等于可以删除仍被当前 Head、未完成 ACK、资源 UNKNOWN 或历史引用所需的证明记录。

## 6. Import Outcome, Technical Validation and Qualification Activation Contract

### 6.1 三个独立维度

R1 将原计划的两个维度明确拆分为三个维度。三者回答不同问题，不得合并为一个 `status`，也不得用某一维度的成功推导另外两个维度成功。

| 维度 | 回答的问题 | 语义边界 |
|---|---|---|
| **Import Outcome** | 本次输入/操作发生了什么？ | 新建、重复、恢复、复活、拒绝或未完成等导入处置事实；只有 `DUPLICATE_EXISTING` 是本计划必须保留的明确 outcome 语义，其他枚举名称另行批准 |
| **Technical Validation** | 对选定的实际源、流和工具完成了什么技术验证？ | 记录未评估、验证中、技术拒绝、无法验证、不支持 Profile 等验证事实；技术检查成功完成不等于资格已激活 |
| **Qualification Activation** | 这个精确 Asset + Content Version + Source Binding Revision + Proof 是否满足 Seed 使用资格？ | 记录尚不可用、等待确认、已激活或已失效等资格生命周期事实；只有满足全部冻结条件后才可能为 `PASS` |

技术验证沿用既有 D2 语义：

```text
NOT_EVALUATED
PENDING
REJECTED
UNVERIFIED
UNSUPPORTED_PROFILE
```

以上技术状态不包含 `PENDING_ACK`。技术验证成功完成是验证事实，不在本计划中另造新的 API 枚举。

资格激活维度继承 OD-03 Option B：

- `PENDING_ACK` 表示 Phase-1 验证结果已经持久化，但客户端尚未完成合法 ACK；它不是“媒体技术验证仍在进行”，也不是可供 Seed 使用的资格。
- `PASS` 只表示当前精确版本/来源绑定的资格已满足全部适用条件，且合法 ACK 已持久化；它不是单纯的解码成功或 Import 成功。
- 当前 AUTH-ACK-01A 阻断下，ACK 不能激活 PASS；因此不能把未来状态模型的定义误读为当前具备激活能力。

`PENDING_ACK` 继承 OD-03，不是新增 Task Terminal State。最终 API 字段名、序列化形式及枚举集合须遵守已冻结合同并另行审批；本计划不冻结新枚举。

### 6.2 每个输入最低返回

继承 D2 §6，每个输入应在安全边界内分别表达：

- 安全的文件显示标识；
- Import outcome；
- Technical Validation 结果/状态；
- Qualification Activation 状态（不可用时不得伪造）；
- 稳定原因及运营下一步；
- 合法范围内的 Asset ID；
- 适用的 Content Version、Source Binding Revision、Proof/Operation 引用。

不得泄露其他 Tenant 信息、凭据或不必要的私有完整路径。

### 6.3 兼容与失败

- 可兼容保留 `success_count/skipped_count/message`，但不能用注册成功数、重复跳过数或技术验证成功代替资格 `PASS`。
- Seed 旧客户端不能因忽略新字段而绕过 Gate；缺少获批协议能力时后端必须安全拒绝受保护资格激活/使用。
- 不全局破坏非 Seed 的 1.5 使用场景；Seed 范围必须由获批的服务端策略识别，不能相信客户端自报。
- 部分批次逐文件结算，保留已合格成员和既有数据；不做整批破坏性回滚。
- 工具异常、未知、不支持和损坏必须区分；`AI_ANALYSIS_FAILED` 不等于损坏。
- 真实资源 UNKNOWN 不能仅改名为 `UNVERIFIED` 后放弃责任。
- ACK 只确认收到特定 Phase-1 结果，不证明媒体健康、源新鲜度、源路径授权或 Native Resource Cleanup。

依据：`D/AUD-03-D1_SEED_IMPORT_GATE_CONTRACT.md:73–86,121–137`；`D/IG-00…FROZEN.md:350–354`；`IG-00 OD-03 §5`；`DD2-02`。

### 6.4 Seed 旧客户端与后端统一保护（继承 DD1-R1 D9）

以下是既有冻结设计约束的显式回读，不是本 R1 新增的协议字段或 Seed 范围授权：

| 情况 | 后端最低规则 |
|---|---|
| Seed 缺少 `qualification_protocol_version` | 在业务写入/长时间哈希前拒绝，返回稳定错误；不得以 `success_count` 表示资格成功 |
| Seed 使用未知/旧协议 | 拒绝，不走 legacy fallback |
| 旧 Import API | 同一 Seed Backend Gate，不保留旁路 |
| Direct API | 与 UI 遵守同一 Tenant、协议、Readiness、资格及 ACK 边界 |
| 旧客户端只读取 `success_count` | 不因此获得资格；正常 Task Admission 仍由独立 IG-02-B Gate 阻断 non-PASS |
| 新旧客户端并存 | 后端是唯一资格权威；不得隐式 ACK |
| 明确非 Seed 的 1.5 场景 | 保留原批准行为，不全局改变 |
| Seed Scope 无法确定 | 不将未知默认视为非 Seed 放行；返回策略未就绪并 Fail Closed |

Seed/非 Seed 的可信判定必须来自获批的后台策略；不能由请求 Body 自报，也不能仅凭静态 Tenant allowlist 推导已经完成 Seed 授权。

依据：`IG-00-DD1-R1 §D9`；`IG-00 FROZEN RECORD §5`；`AUTH-ACK-01A OWNER GAP RESOLUTION §4–8`。

## 7. Restore / Revival / Duplicate / Replacement Handling

| 操作 | 1.6-A 最小目标行为 | ID/历史保护 |
|---|---|---|
| Fresh Import | 同一 Backend Gate 验证实际输入；注册结果和资格结果分开；两阶段条件满足后才可 PASS | 创建合法新记录，不影响旧记录 |
| 活跃同 MD5重复 | 明确返回 `DUPLICATE_EXISTING`；不静默采用输入的新路径，不自动变成替换成功 | 保留原 ID及路径语义；旧资格须独立检查 |
| Trash | 逻辑隔离并撤销当前可选资格及迟到激活能力 | 不删原片、历史、良好输出 |
| Trash Restore | 保留原 ID；不能仅以 `is_deleted=False` 恢复资格；重新验证当前源 | 不回写旧任务 |
| 同 MD5 Revival | 保留现有身份；源重绑定、Generation 和资格操作一致处理；重新验证 | 不继承旧 PASS，不重解释历史 |
| 不同内容替换 | 优先使用独立、可证明的新源引用，重新导入并显式重选 | 保留旧 Asset 和输出；不要求覆盖旧行 |
| 同路径原位替换 | 不是安全人工 SOP；检测到变化则阻断旧资格和使用 | 不声称能够自动恢复已丢失旧字节 |
| Purge | 撤销当前 Head/激活能力，拒绝迟到验证、ACK、Recover 和旧幂等请求；按获批保留规则保留必要证明及墓碑 | 不自动删除原片、历史事实、仍被引用的 Proof、未完成 ACK 或资源 UNKNOWN 责任记录 |

### 同 MD5 新路径的特殊边界

不能简单规定“所有替换都新建 Asset 行”，因为当前 `file_hash` 有唯一约束。来源：`src/api/models.py:LocalAsset:273–275`。

最小计划因此是：

1. 普通重复导入不承担替换职责。
2. 如确需重绑定现有 Asset，必须有明确操作意图、当前授权、源 Revision/Generation、旧引用保护及重新验证。
3. 上述安全更新合同未获批时，拒绝把新路径当成替换完成；不通过修改 MD5、解除唯一约束或自动 Purge 绕过。

本计划不要求先建立完整多版本 UI，也不批准新替换端点。

### 7.1 Purge、Operation 与幂等墓碑保护

Purge 的最小逻辑约束继承 IG-00-DD1-R1，不在本计划中选择物理保留表或具体期限：

- 当前 Head 仍需要的 Proof、未完成 ACK、资源状态为 UNKNOWN 的记录，不得因 Asset 行 Purge 而自动删除。
- 已退役 Operation 可以在未来获批的保留策略下缩减非必要结果；但至少保留足以识别请求已处理/已退役的幂等墓碑，防止旧 key 再次启动验证或激活。
- 幂等墓碑至少应能维持 key 摘要、Operation 关联及已处理/已退役事实；不得保存不必要的原始凭据。
- 本初始方案不自动删除墓碑。达到获批容量上限时，拒绝新的资格操作；不得静默删除仍有安全意义的墓碑、当前 Head 所需 Proof 或 UNKNOWN 责任记录。
- Purge 后不得通过 Asset ID 复用、迟到 ACK/Recover、旧 Operation 或重复请求重新激活已退役 Asset 的资格。
- 具体保留期限、压缩规则、容量阈值和清理机制均未建立，必须另行设计、测量和批准。

依据：`IG-00-DD1-R1 §D8`；`IG-00-DD1-R1 §C4`；`IG-00 OD-02 §4.2–4.4`。

另须区分：

- **Trash Restore**：资产行的逻辑恢复。
- **Tenant DB Restore**：整个持久化数据集恢复，受 DD2-04 的跨恢复/崩溃 barrier 约束。

## 8. Task Admission and Actual-use Freshness

这是 **IG-02-B 的独立义务**，不能打包成 IG-01 的附带完成项。

### 8.1 Task Admission

在正常 Task 创建/接受之前，对所有选中视频验证：

- 当前 Tenant 和调用方权限；
- Asset 未删除且属于允许的 Seed 入口；
- 精确源版本；
- 当前已激活、适用且新鲜的 Proof；
- Schema、Restore 和资源安全前置条件；
- Batch2 中每个实际选中源的独立资格。

不存在有效证明时，不启动正常 TTS/Render；诊断记录不能被误认为正常生产准入。

### 8.2 Task Source Binding

接受的 Task 应保留精确版本和 Proof 引用，不能只保留“当前 Asset ID”并在之后自动跟随最新 Head。

- `asset_id → 当前最新版` 不能代替已接受的绑定。
- 非 authoritative 路径如在 Worker 重新解析，必须核对结果与接受的绑定，不能静默更换。
- 重新选择不是自动重试；仍须遵守现有 Attempt/UNKNOWN 限制。

当前重解析与 authoritative-plan 分支的证据来自 INV-01：`src/api/routes_dsl.py:render_worker:2720–2757`。

### 8.3 Actual-use Freshness

在实际消费前核验仍是合格的同一源版本；若出现变化，阻断，不通过“重新查最新行”修正旧 Task。

**仅做一次使用前哈希不能宣称消除了检查与消费之间的所有变化窗口。**实际读取/约束机制必须在独立设计、COMPAT 和既有 G1 边界内证明；无法证明则停止该接线路径，不新增 Native Owner 或第二 Runner。

### 8.4 IG-01-A 与 IG-02-B 的责任边界

| 工作流 | IG-01-A 负责 | IG-02-B 独立负责 |
|---|---|---|
| Asset Identity / Content Version / Source Binding Revision | 定义并建立素材身份、内容版本、来源绑定及其变化/失效语义 | 消费已建立的精确引用，不重新解释素材身份 |
| Qualification Proof | 建立与精确内容/来源绑定关联的资格事实及当前状态 | 在 Task Admission 时验证 Proof 是否当前、适用且已激活 |
| Task Admission | 不实现、不接线、不改变现有 Task 生命周期 | 对所有实际选中源执行准入检查；无有效资格不得启动正常 TTS/Render |
| Task Source Binding | 定义后续引用所需的精确身份语义，不修改 Task/Child 持久化 | 在 Task/Child 接受时固定 Asset、Content Version、Source Binding Revision 和 Proof，不动态跟随最新 Head |
| Actual-use Freshness | 提供来源/资格事实供检查 | 在实际消费前核对同一源版本；不能用一次哈希或重新读取最新 Asset 行替代证明 |
| Output / Creative Lineage | 不重写既有历史或输出 | 在独立获批范围内使新 Output 能关联实际 Task Source Binding；不回填旧历史 |

IG-01-A 的完成不能替代 IG-02-B；IG-02-B 的规划或实现也不能反向使未合格 Asset 获得 Proof。不得在 IG-01-A 切片中顺便修改 Task History、Legacy Output、Batch2 或 Task/Child/Attempt 生命周期。

依据：`IG-00-DD2 §7`；`IG-00 OD-02 §4.2`；`AUD-03-D1-D2 v1.0`。

依据：`D/AUD-03-D1_SEED_IMPORT_GATE_CONTRACT.md:63–71,163–167`。

## 9. Task History / Output Compatibility

### 保留当前事实

INV-01 已确认：

- DSL 历史可保存计划中的 Asset ID、路径、MD5；
- Legacy 输出主要关联任务及输出文件；
- 当前历史不是统一不可变输入版本账本。

锚点：

- `src/api/routes_dsl.py:_child_prompt_details:2516–2531`
- `routes_dsl.py:_build_task_history_record:3071–3124`
- `src/api/services.py:run_matrix_job:219–297`
- `src/api/models.py:TaskHistory:299–316`

### 未来最小要求

- IG-01-A 仅定义 Asset、Content Version、Source Binding Revision 与 Proof 的精确引用语义；不实现新 Task/Child 的持久化绑定。
- 新 Task/Child 的实际源版本引用由独立 IG-02-B 在 Task Admission/接受阶段建立，并能供后续 Output Lineage 精确引用。
- 新 Output 与实际 Task Source Binding 的关联属于 IG-02-B 或后续独立获批范围；不因此授权修改 Legacy Output/历史模型。
- 历史记录继续保留原 Asset ID、路径、MD5及既有执行身份。
- 旧记录缺少版本证据时明确缺失，不从当前 Asset 行反向补造。
- 撤销当前资格不删除历史输入描述、旧 Proof 或良好输出。
- 不改变 FP-001、Planning FP、Reservation Authority、Task/Child/Attempt 的既有语义。
- 不因为旧源丢失而声称旧输出从未存在或自动删除其记录。

**新绑定的持久化位置仍需独立批准。**本计划不选择写入现有 JSON、扩展 Manifest 或创建新表作为已批准实现。

符合：`D/DECISIONS.md:D16-006 §4:1846–1877、§5:1879–1894、§12:2009–2019`。

## 10. Future Asset Identity Architecture Compatibility Map

| 1.6-A 最低能力 | 未来架构演进 | 为什么不需要丢弃现有 ID |
|---|---|---|
| 保留 `LocalAsset.id` | 映射到正式 Asset Identity | 现有行身份持续可引用 |
| 明确源版本逻辑引用 | 可映射到专用 AssetVersion 对象 | 不把 ID/路径/MD5当版本主键 |
| 独立资格事实 | 可扩展正式 Proof 对象 | Proof 与素材身份、内容版本分离 |
| 精确 Task Source Binding | 可扩展专用 TaskBinding | 未来可索引已有明确绑定，不必重解释旧任务 |
| 输出关联实际绑定 | 可扩展完整 Lineage/Attribution | 从新事实开始积累，不要求补造历史 |
| legacy 无证据明确未验证 | 后续受控认领或补证 | 不把未知旧数据错误迁成可信版本 |

**前向兼容承诺的范围**：逻辑关系、引用语义和历史事实可保留；不是承诺未来永远不需要经过批准的附加迁移。

全版本管理、全量血统和历史回填不是 1.6-A 的前提。

## 11. Existing Main Source File Impact Map

以下仅为未来文件审批候选，非修改 Allowlist。

| 文件/符号 | INV-01 基线位置 | 候选影响 |
|---|---|---|
| `src/api/routes_assets.py` | `import_asset:42–97`；`get_assets:136–165`；Trash/Restore/Purge:242–277 | 统一 Backend Gate、逐文件结果、Mutation/资格一致性 |
| `src/api/schemas.py` | LocalAsset 请求/响应:222–270；`ResolvedLayer:337–346` | outcome/status 分离；新源版本引用的 API 表达，须另批合同 |
| `web_ui/src/views/AssetsView.vue` | Import:155–210；Trash:380–439；Restore:498–521 | 明确重复/未合格状态与人工操作反馈，不作客户端资格 Authority |
| `src/api/models.py` | `LocalAsset:266–293`；`TaskHistory:299–316` | 保留旧模型语义；仅在物理设计获批后评估资格持久化映射 |
| `src/api/database.py` | `get_db:509–522` | 经单独批准的 Readiness 接线；不借自动初始化放行 |
| `src/api/dsl_parser.py` | locked:248–292；`_make_layer:735–754` | IG-02 精确源绑定与资格解析 |
| `src/api/routes_dsl.py` | admission/use 相关边界；`render_worker:2720–2757`；历史:3071–3124 | IG-02 准入、重解析核对、新 Task 历史绑定 |
| `src/api/dsl_adapter.py` | `compile_plan_to_timeline:124–143` | 优先保持纯转换；如需传递绑定，另行批准，不自动扩大修改范围 |
| `src/api/services.py`、`routes_history.py` | Legacy 历史写入/读取 | 当前为兼容保护对象；不默认纳入 IG-01 修改 |

冻结候选文件继续准确表述：

- `src/api/import_qualification.py`：**Future Candidate New File；不得假定 Main 已存在；未授权创建。**
- `src/services/source_media_integrity.py`：**Future Main Candidate，可来自 Q-derived narrow logic；Q 中存在不等于 Main 已存在，也不构成创建授权。**
- `src/nodes/compositor.py`：仅属于独立 COMPAT 审批；不得借资产整改改变 Runner 生命周期。
- Schema Preparation 入口、Startup hook、测试文件：精确名单须独立批准，不默认新增 CLI 或新模块。

依据：`D/IG-00…FROZEN.md:§10:532–551`。

## 12. IG-00 / DD2 Dependency and Gate Map

| 依赖 | 已冻结内容 | 当前阻断及影响 |
|---|---|---|
| OD-01 / DD2-01 | 现有 Main Runner 的 opt-in bounded Observer；typed exception A | COMPAT Runtime 未验证；不得新增 Runner/Owner |
| OD-02 | 每 Tenant SQLite 内独立小型资格记录 | 物理设计、Schema、FK/Purge/历史保护未获实施授权 |
| OD-03 | Two-Phase Qualification Activation | 技术完成≠PASS；PENDING_ACK 不能用于生产 |
| OD-04 | 分阶段预算测量方法 | 正式数值仍 `NOT_ESTABLISHED`；Native 阶段受 G1阻断 |
| DD2-02 | Tenant-level ACK 产品语义 | 真实调用方授权未证明 |
| DD2-03 | Recover 候选凭据/幂等/CAS方向 | API安全与客户端资格未关闭；Recover不可用 |
| DD2-04 | 受控 DB Restore 后重验 | 跨 DB恢复和崩溃存活的可信 barrier 未证明 |
| DD2-05 | 显式离线 Schema Preparation | 不自动 `create_all/evolve_schema`；无 DDL/CLI/Startup授权 |
| AUTH-ACK-01 | Option B，消费既有可信权威 | 不得创建第二套 Membership Authority |
| AUTH-ACK-01A | Option C Gap Resolution | 外部权威 UNKNOWN；01B未进入 |
| G1 | UNKNOWN custody BLOCKED | 阻断依赖其安全结论的 Native验证/运行接线 |
| S0-OPS / Allowlist | 独立支持范围、Backend enforcement | 实际 SOP、设备、工具和健康正向路径未验证 |

依据：OD 文件 §§3–7；DD2 文件 §§2–7；`D/AUTH-ACK-01A_OWNER_GAP_RESOLUTION_v0.1_OWNER_APPROVED.md:30–95,117–155`。

### 当前必须承认的结果

`AUTH-ACK-01A` 已由 Owner 于 2026-11-18 选择并冻结 `Option C — EXTERNAL_AUTHORITY_STATUS_UNKNOWN`。其精确含义是：已审查的 RC2 范围内没有找到可复用的 Trusted Authorization Source，但审查范围外的外部 Control Plane/License Service 是否存在仍为 UNKNOWN；不得将 UNKNOWN 改写为不存在或可用。

因此当前状态必须保持：

```text
EXTERNAL_CONTROL_PLANE = UNKNOWN
TRUSTED_AUTHORIZATION_SOURCE = NOT_VERIFIED
ACK = FAIL_CLOSED
PENDING_ACK = NON_QUALIFIED
RECOVER = UNAVAILABLE
AUTH-ACK-01B = NOT_ENTERED
```

在可信来源证据、服务端授权边界及相应独立 Owner Gate 未关闭前，不允许 ACK 激活 PASS，不允许启用 Recover，不允许离线 ACK/Recover、人工 PASS、临时本地 issuer 或客户端旁路。

即使未来可独立完成纯逻辑或 UI/API 结果整改，**在当前 AUTH-ACK、G1 及存储条件下，也不能宣告完整 IG-01 健康激活正向路径已经可交付**。

不能通过取消 ACK、添加本地 issuer、人工 PASS、隐藏后台验证或换 Runner来关闭这一依赖。

## 13. Minimal Implementation Slices

以下顺序是审批提案，不是自动执行队列。每片均须 Owner 明确批准源文件、测试和执行范围。

| Slice | 目的 / 最小候选文件 | 现有 → 目标行为 | 依赖 | 验收证据 / Owner批准 |
|---|---|---|---|---|
| **P1：身份与结果合同** | `routes_assets.py`、`schemas.py`；资格模块仅作未来候选 | 汇总注册结果 → 每文件 outcome/status/引用；建立纯身份、失效规则 | 本计划及 API兼容合同获批 | 纯规则/序列化隔离测试、旧汇总兼容；不含 Native或DB写入授权 |
| **P2：资格存储与 Readiness** | 未来资格模块；必要 `models.py/database.py`；准备入口另定 | 无持久资格 → 当前版本/Generation/Operation可条件提交 | OD-02、DD2-04/05；物理设计、备份/回滚、维护权限 | 专用隔离 SQLite准备/失败/重启/迟到提交/Purge验收；须单独 DDL与测试授权 |
| **P3：COMPAT与窄验证适配** | `compositor.py`、未来 integrity候选及资格适配 | 当前观察不足 → 完整有界双通道证据，保留旧调用 | DD2-01文件级批准、G1、工具/Profile/Budget条件 | 单元故障测试后，另批 Synthetic Native及打包证据；不改变 Owner/Wait/Close |
| **P4：Import/Mutation统一接线** | `routes_assets.py`、资格模块、`schemas.py`、`AssetsView.vue` | 注册/恢复即普通可见 → 资格未完成不可正常 Seed选用；变更一致失效 | P1/P2/P3；可信 Tenant/路径授权；Seed范围和旧客户端保护 | Import、Restore、Revival、Trash、重复、替换、混合批次及历史保护的集成证据 |
| **P5：两阶段激活接线（BLOCKED / NOT ENTERED）** | 仅保留未来候选，不列入当前实施队列 | 未来设计目标仍为技术结果持久化为 `PENDING_ACK`，只有合法、持久化 ACK 才可能进入 `PASS`；当前 ACK 不得激活 | 必须先有 Owner 提供的可信外部权威证据、独立获批只读评估、完整服务端授权/安全 Gate、P2 前置条件及 `AUTH-ACK-01B` 的正式进入与实施授权；当前条件均未满足 | 当前不执行、不创建端点、不测试真实凭据；保持 `ACK=FAIL_CLOSED`、`PENDING_ACK=NON_QUALIFIED`、`RECOVER=UNAVAILABLE`。不得本地 issuer、人工/离线 ACK、自动重试或客户端旁路 |
| **P6：IG-02-B独立接线** | `dsl_parser.py`、`routes_dsl.py`、共享资格/Freshness；其他入口另批 | ID/MD5/path消费 → Task接受及实际使用绑定精确版本 | 已合格IG-01 Proof；G1；实际Seed Allowlist | 准入前阻断、使用前变化、每Child绑定、旧计划不重定向、历史保留；独立实施批准 |

依赖说明：

- P1 的纯合同工作不需要先建设完整 DAM 或 L3。
- P2、P3及授权依赖可分别规划，不能在运行时用任一项替代其他项。
- P4/P5 的完整正向资格验收必须合流。
- P6 可先规划，但不能凭 Q历史或 IG-01 完成而视为已通过。
- Slice 是否可以分阶段交付源码，与是否允许启用 Seed 生产是两个问题。

## 14. Acceptance Criteria and Evidence Requirements

以下是既有验收的工程细化候选，不新增 PRD要求或自动授权测试。所有结果当前为 `NOT_RUN / NOT_VERIFIED`。

| 场景/断言 | 最低证据 | 既有追溯 |
|---|---|---|
| 健康新源 | 分别证明 Import Outcome、Technical Validation、Qualification Activation；实际选中流完整验证、精确 Content Version/Source Binding Revision、持久化及合法 ACK 后才可激活 | IG-T01；A-IMP-01；AC-A01；OD-03（当前正向 ACK 受 AUTH-ACK 阻断） |
| 同名同字节/活跃重复 | 明确Duplicate；不把新路径当已替换；独立返回旧资格事实 | IG-T07/T16 |
| 同名不同字节 | 新旧身份可区分；旧绑定不能自动取得新字节 | IG-T09/T11；AC-A03 |
| 同MD5不同路径 | Content Version 可相同但 Source Binding Revision 必须变化；不凭哈希授予新路径权限或复用 Proof | IG-T07/T08/T13 |
| Trash → Restore | 原 ID 保留；旧资格不恢复；当前源重新确认并启动新资格 Generation | IG-T08；A-IMP-03/04 |
| Trash → Revival | 旧Operation失效；新路径、Revision/Generation一致；重验 | IG-T08/T11 |
| 原位修改，包括同size/mtime | 无法沿用旧Proof；Task接受与实际使用均阻断 | IG-T09/T12；AC-A03 |
| 旧结果/ACK迟到 | 不能覆盖新 Content Version、Source Binding Revision 或 Generation，不能恢复已删除/已 Purge 资格 | IG-T07/T08/T14及DD2协议断言 |
| 混合批次 | 每文件结果；保留已合格成员及旧输出，无整批破坏性回滚 | IG-T07/T14 |
| 旧行无Proof/旧客户端/直接API | 同一Backend边界；不能由旧汇总或ID绕过 | IG-T10/T12 |
| 跨Tenant或授权缺失 | 哈希、Token、ID均不能扩大权限；保持non-PASS | IG-T13；D16-004-B；DD2-02/03 |
| Schema/Restore失败、重启 | 非就绪；旧备份 PASS 不能自动生效；不得绕过可信 Restore barrier | DD2-04/05；IG-T08/T14 |
| Native/观察/清理失败 | non-PASS与资源责任分开；不伪造EOF/Reap/Close | IG-T06/T14/T15 |
| 新任务/输出血统 | 可定位实际源版本；旧历史未回写、旧输出未覆盖 | IG-T11；AS-12；AC-A03/A09 |
| Purge 与幂等墓碑 | 当前 Head/未完成 ACK/UNKNOWN 记录受保护；旧 key 不得重新启动或激活；容量不足时安全拒绝新操作 | IG-00-DD1-R1 §D8；DD2-04/05 |
| 人工补救健康闭环 | 新源、重验、显式重选、IG-02及安全新执行全部成立 | IG-T11/T16；AS-12 |

证据必须分层：

1. 静态审查及纯规则 Mock/Unit；
2. 专用临时数据库的事务/兼容证据；
3. 独立 Synthetic Native；
4. Main 集成；
5. Packaged Runtime；
6. 获授权代表性素材、实际设备与适用发布 Gate。

上层证据不能由下层 PASS 自动继承。S0-OPS及文件大小、时长、CPU、Memory、Concurrency、Timeout和Observation正式阈值仍为 `NOT_ESTABLISHED`。

## 15. Deferred Future Architecture Scope

以下明确后置，不作为 1.6-A 首发前置：

- 全 AssetVersion 历史管理与多版本 UI；
- 完整不可变 Lineage Ledger；
- Historical Creative Memory 全量建设；
- 跨项目高级资产复用；
- 历史输入重建、全量版本补录或 Backfill；
- 全 DAM 生命周期重构；
- 智能修帧、自动转码或全自动修复。

**不可后置的是**：新源版本能够区分、Proof精确绑定、失效规则、正常 Task 两道资格边界、旧历史与良好输出保护。

## 16. Risk Register

| 风险 | 等级/状态 | 最小控制及停止条件 |
|---|---|---|
| 以 Asset ID/MD5 代替版本 | P0-Seed | 分离 Asset、Content Version、Source Binding Revision；不能证明精确版本/来源则拒绝资格 |
| Content Version 与 Source Binding Revision 混用 | P0-Seed | 同路径内容变化与不同路径同内容必须分别处理；不能用单一含混 revision 表示两者 |
| Import Outcome、Technical Validation、Qualification Activation 混为一态 | P0-Seed | 三维独立返回；Import/技术成功不能推导 Seed PASS |
| 检查与消费间源变化 | P0-Seed / OPEN | Actual-use绑定需要独立机制证据；不以一次哈希声称解决 |
| 同MD5替换违反现有唯一约束 | P0-Seed，条件性 | 不通用强制新行、不改hash绕约束；安全重绑定未闭合就拒绝 |
| Restore/Revival误恢复PASS | P0-Seed | 新资格验证、旧操作失效；不能只改删除标志 |
| 授权来源未知导致激活不可交付 | OPEN ENGINEERING GATE / BLOCKED | ACK Fail Closed，PENDING_ACK non-qualified，Recover 不可用；不建第二 Authority；P5 不进入实施队列 |
| Purge 删除当前仍需的 Proof/Operation/UNKNOWN 记录或幂等墓碑 | P0-Seed / OPEN | 保留当前 Head、未完成 ACK、资源 UNKNOWN 和必要墓碑；容量不足时拒绝新资格操作，不静默清理 |
| Schema/DB恢复使旧资格复活 | 安全Gate未闭合 | 显式Preparation、Readiness和可信Restore barrier；不批准DDL |
| Native UNKNOWN被包装为普通导入失败 | 安全Gate / BLOCKED | 保留原资源责任和G1；停止相关Native路径 |
| 为补血统重写旧历史 | 数据保护风险 | 仅新增获批事实；未知历史不补造 |
| 全局破坏1.5 Legacy | 兼容风险 | 精确Seed范围；其他入口的修改单独授权 |
| 为等待完整DAM/L3无限扩大范围 | 交付风险 | 只保留第15节的最低身份义务 |
| 永久拒绝掩盖健康正向缺失 | 验收风险 | 完整交付必须证明健康源可在合格预算和授权下激活使用 |

若实现必须改变 Frozen Architecture、Task生命周期、Native Ownership、CLI冻结语法或新增存储体系，停止对应切片，返回 Owner/ADR，不在本计划中默许。

## 17. Explicit Authorization and Stop Record

本 R1 完成的是：**对原 IG-01-A-PLAN 进行有边界的文档语义修订**。本轮没有新增工程源码审计，没有重新验证 Main HEAD/Worktree，没有选择新的物理 Schema，没有编写接口、测试或迁移。

原计划中的 Main Root、Branch、HEAD、Tracked Worktree、Index、Handoff 和 AGENTS 身份均为 INV-01 继承证据；R1 未重新核验，不得将其描述为本轮新验证结果。

```text
IG-01-A-PLAN = R1_FOR_OWNER_REVIEW / DOCUMENT_ONLY
PLAN_APPROVAL = PENDING_OWNER_APPROVAL
PLAN_FREEZE = NOT_EFFECTIVE

IG-01-A_IMPLEMENTATION = NOT_GRANTED
IG-02-B_IMPLEMENTATION = NOT_GRANTED
STORAGE_DDL = NOT_AUTHORIZED

SOURCE_REPOSITORY_MUTATION = NONE
TEST_MUTATION = NONE
REPOSITORY_FILE_CREATION = NONE
HANDOFF_MUTATION = NONE
FROZEN_CONTRACT_MUTATION = NONE

TEST_EXECUTION = NONE
NATIVE_MEDIA_OR_HELPER_EXECUTION = NONE
SQLITE_ACCESS = NONE
DDL_OR_MIGRATION = NONE
CUSTOMER_MEDIA_ACCESS = NONE
EXTERNAL_SERVICE_ACCESS = NONE
CREDENTIAL_ACCESS = NONE

GIT_MUTATION = NONE
BUILD_PACKAGE_INSTALL_RELEASE = NONE

G1_NATIVE_CUSTODY = BLOCKED
COMPAT_RUNTIME = NOT_VERIFIED
SCHEMA_RESTORE_BARRIER = NOT_VERIFIED / NOT_AUTHORIZED

EXTERNAL_CONTROL_PLANE = UNKNOWN
TRUSTED_AUTHORIZATION_SOURCE = NOT_VERIFIED
ACK = FAIL_CLOSED
PENDING_ACK = NON_QUALIFIED
RECOVER = UNAVAILABLE
AUTH-ACK-01B = NOT_ENTERED
P5 = BLOCKED / NOT_ENTERED

DAM_IMPORT_CERTIFICATION = HOLD
PHILIPPINES_INSTALL = HOLD
PRODUCTION = HOLD
```

**STOP — 等待 Owner 对 R1 计划进行审阅/批准，以及对后续精确切片另行授予权限；不自动进入任何实施、测试、数据库、Native 或发布工作。**

## 18. R1 Revision Record

### 18.1 本次修订内容

| 修订项 | R1 处理 | 范围限制 |
|---|---|---|
| R1-01：身份语义 | 明确分离 Asset Identity、Content Version Identity、Source Binding Revision、Qualification Proof、Generation、Operation Identity；Task Source Binding/Output Lineage 作为下游引用 | 逻辑模型，不创建物理 Schema |
| R1-02：内容与来源变化 | 明确同路径内容变化、不同路径同内容两种不同变化规则 | 不声称已解决 TOCTOU 或实现实际监控 |
| R1-03：状态维度 | Import Outcome、Technical Validation、Qualification Activation 三维独立；`PENDING_ACK` 归属激活维度 | 不冻结新 API 枚举或序列化字段 |
| R1-04：ACK 阻断 | 明确继承 AUTH-ACK-01A Option C；P5 标记 `BLOCKED / NOT ENTERED` | 不进入 AUTH-ACK-01B，不建立本地 issuer/人工或离线 ACK |
| R1-05：Purge 保护 | 补充当前 Head、未完成 ACK、UNKNOWN 记录、Proof/Operation 和幂等墓碑保留；容量不足时拒绝新操作 | 不指定物理表、保留期限或清理机制 |
| R1-06：IG-01/IG-02 边界 | 明确 IG-01-A 建立素材身份/来源/资格事实；IG-02-B 负责 Task Admission、Task Source Binding 和 Actual-use Freshness | 不改 Task/Child/Attempt、Task History、Legacy Output 或 Batch2 |
| R1-07：Generation 矩阵 | 补充 Fresh Import、Duplicate、内容变化、来源重绑定、Trash、Restore、Revival、Purge 的逻辑矩阵 | 不定义 DDL 或具体条件更新 SQL |
| R1-08：旧客户端保护 | 显式继承 DD1-R1 D9 的 Seed 协议、旧 API、Direct API、success_count 和未知 Seed Scope 保护 | 不批准 Seed Allowlist 或路由启用 |

### 18.2 原计划中明确保留的内容

- INV-01 六项调查发现、源码锚点及其证据层级；
- 现有 `LocalAsset.id`、MD5 判重和 1.5 历史事实保护；
- 不批量回填历史、不重写 Task History/Output、不建设完整多版本 DAM/L3；
- OD-01～04、DD2-01～05、AUTH-ACK-01 Option B、AUTH-ACK-01A Option C 的冻结含义；
- G1、COMPAT Runtime、Schema/Restore、S0-OPS、Seed Allowlist 等未关闭 Gate；
- P1～P4、P6 的候选规划及所有独立授权要求；P5 保留为未来候选但当前明确阻断；
- 原有候选文件映射、Acceptance Matrix 追溯、风险和 Deferred Scope。

### 18.3 R1 不构成的事项

```text
DESIGN_FREEZE = NOT_GRANTED
ENGINEERING_IMPLEMENTATION = NOT_GRANTED
TEST_AUTHORIZATION = NOT_GRANTED
SQLITE_ACCESS / DDL / MIGRATION = NOT_AUTHORIZED
NATIVE / REAL_MEDIA = NOT_AUTHORIZED
GIT / BUILD / INSTALL / RELEASE = NOT_AUTHORIZED
```

**R1 交付状态：DOCUMENT-ONLY / FOR OWNER REVIEW。**
