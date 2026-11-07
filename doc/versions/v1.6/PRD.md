# DopaMatrix 1.6 — PRD v1.0 Baseline & Requirement Traceability

> **Document status:** FROZEN — Owner-approved Product Scope Baseline
> **Version:** PRD v1.0 (approved R1 scope; 59 requirements / 34 AC scenarios)
> **Date:** 2026-11-07
> **Owner approval date:** 2026-11-07
> **Product Owner:** DopaMatrix Product Owner
> **Source of truth:** `doc/versions/v1.6/DECISIONS.md`，D16-001～D16-006 共八项 FROZEN 决策
> **Decision Git baseline:** `docs/v1.6-product-baseline` / `123a2fb`（DECISIONS.md 的已审远程基线；本 PRD 尚未提交/Push）
> **Intended project path:** `doc/versions/v1.6/PRD.md`（独立 Docs Worktree；本交付不直接写入用户仓库）
> **Implementation authority:** **NOT_GRANTED**
> **Engineering verification:** **NOT_VERIFIED**（未针对当前工程候选版本执行只读差距审查）

## 1. PRD 目的与优先级定义

本文件把八项 FROZEN 产品决策转化为**可审查、可追溯、可验收**的产品需求。PRD 不能修改 DECISIONS 的既有合同；遇冲突以已冻结决策为准，提交单独变更提案，不得静默改写。

- **P0-A：1.6-A Seed Reliability Baseline**，含真正升级/发布所必需的 RE-0 数据安全能力；不强制等 Studio 完成。
- **P0-B：1.6-B Studio Workspace MVP**，依赖 1.6-A 的安全出片与发布工程底线；不开放跨 Tenant 并发。
- **P1-L3：Historical Creative Memory V1**，独立功能包；M0 数据不破坏原则是相关工作的普遍约束，M1–M3 不阻塞 A/B 发布。
- **Candidate / 1.7+：** temporal pHash、Historical ENFORCE、Attribution-aware Learning、自动更新/设备 Fleet、完整 Project ACL，不属于本次 P0 验收。

**P0 需求数量不等于新开发模块数量**：区分强制安全结果、已验证旧路径与可受控人工流程。**优先级不是已实施状态**。本 PRD 所列工程状态暂为 `NOT_VERIFIED`，后续只读工程审查再细分 `EXISTING_VERIFIED / GAP / ADR_REQUIRED / NOT_VERIFIED`。只有实际候选代码、制品及适用证据才能将工程状态改为 PASS。

## 2. 使用者与核心场景

| Persona | 目标场景 | 首版边界 |
|---|---|---|
| 菲律宾 Seed Operator | 选健康源片、人工编排、单 Task Batch2、逐条 QC、必要人工补救 | 可人工补拍和部分交付；不能绕过强制 Gate |
| Seed 技术/发布 Operator | 隔离构建、确认升级安全、管理受控制品和恢复 | RE-0 受控人工流程；不等于已获生产安装授权 |
| Studio Operator | 一个 Windows 用户和 Tauri 会话管理多个获授权 Tenant | 单 Active Tenant、Idle-only Switch |
| 平台授权管理员 | 审核开通 Tenant、管理 Membership 和 Installation | 不默认可读取客户全部业务素材 |
| Creative Operator（L3） | 查询规划/成品历史，选择复用或继续实验 | Historical Advisory，不默认 ENFORCE |

## 3. 业务主流程与硬边界

**1.6-A：** 素材导入 → 技术 Import Gate → 人工 Story/Matrix → 单 Task Batch2 → 各 Child Output Gate → 每条 Human QC → 受控交付 / 人工恢复。

**1.6-B：** 管理员开通 → Operator Membership + Installation Grant + Tenant Entitlement → 单 Active Tenant → Global Quiescence + Switch Barrier → 安全切换 → Tenant-scoped 生产。任何 AUTH PASS 都不能代替生产发布 Gate。

**L3 P1：** 已授权 Tenant 的历史规划证据查询 → 精确成品身份 → 覆盖说明 / Advisory → 人工受控复用；历史检索异常可降级，跨 Tenant 或完整性风险不可降级。

**全局硬边界：** Frozen Architecture 不重设；Closed Phases 不复审；不解除 `LOCAL-P-R1 = FAIL/HOLD`、`PHILIPPINES_INSTALL = HOLD`、`ARCHITECTURE_EXCEPTION = BLOCKED`、`A1_ACTIVATION_BLOCKED = TRUE`、`A2 = NOT_APPROVED` 及其他未解除的 Production HOLD；不许可代码、构建、迁移、安装、发布。

### 3.1 P0 最小实现规则

- P0 是验收与安全义务，**不等于逐条新建 UI、服务、数据库或自动化系统**。
- 已冻结允许人工处理的 QC、部分交付、发布审批与受控恢复，可以使用有证据的安全人工流程。
- 对未批准的外部素材引用，关闭该功能属于安全合规的候选做法，不意味着允许绕过受管素材边界。
- 1.5 旧数据必须保护；不要求 1.6-B 上线前完成全部历史资产认领。
- 当前 Candidate P/Q 的实现状态一律 NOT_VERIFIED，直到获得适用版本的权威工程证据。

## 4. P0-A：Seed Reliability Requirements

| Requirement ID | 必须满足的产品行为 | 最小验收判据 | 冻结依据 |
|---|---|---|---|
| A-IMP-01 | 在声明支持的输入范围内进行结构、所需流和有界完整解码技术检查 | 未通过/未完成/覆盖无法证明则不得进入正常生产；提供可操作原因；具体支持规格待工程证据确定 | D16-003 §3 |
| A-IMP-02 | 区分损坏/截断、不支持规格、AI 内容理解失败 | 分别给出可区分原因；正常 VFR 不因帧率可变而一律拒绝 | D16-003 §3 |
| A-IMP-03 | 验证结果绑定实际用于生产的素材版本 | 验证后源内容变化或一致性不可信时重新检验或停止 | D16-003 §3; D16-004-B §5 |
| A-IMP-04 | 人工补拍、更换、重新导入形成闭环 | 替换后必须重新检查；不允许人工跳过技术阻断 | D16-003 §§2–3 |
| A-OPS-01 | 复用已有且经验证的人工 Story/Matrix 编排路径 | Operator 可选择现有支持的 Hook/片段/配方/参数，系统校验必要技术参数；不以全自动 Story Mining 为前提 | D16-003 §4 |
| A-BAT-01 | 一个 Task 内保留有界 Batch2 两 Child 产出 | 两 Child 各自执行身份、产物身份及技术结果可追溯 | D16-001 §2; D16-003 §5 |
| A-BAT-02 | 限制未经验证的跨 Task 并发与整体自动重提 | 跨 Task 并发不开放；整个失败 Task 不自动重提 | D16-003 §5 |
| A-BAT-03 | 处理单 Child 成功、另一 Child 失败 | 保留成功 Child；整体不显示全部成功；失败原因可见 | D16-003 §8 |
| A-BAT-04 | UNKNOWN、孤儿执行和资源冲突 Fail Closed | 无法确认安全终结时拒绝危险重试、复用和覆盖 | D16-003 §§5,9 |
| A-OUT-01 | 各 Child 对实际文件、所需媒体流和适用可读性/解码/规格独立执行 Output Gate | 进程成功不等于技术 PASS；任一必需检查失败不得标记合格或允许交付；具体检查集需获批 | D16-003 §6 |
| A-OUT-02 | Output/历史产物受身份和路径保护 | 重试和同名输出不能覆盖旧产物；保留失败诊断 | D16-003 §§5–6,9 |
| A-QC-01 | Execution、Output Validation、Human QC、Delivery Eligibility 语义分离 | 四类结果可分辨；不以单一 Completed 代替全部 | D16-003 §7 |
| A-QC-02 | 每条拟交付实际 Output 逐条人工视听 QC，允许受控人工留痕 | 逐条确认画面、音频、字幕与连贯性并可追溯；不强制首发完整 QC Approval Engine | D16-003 §10 |
| A-QC-03 | 客户交付约定允许、Operator 明确确认时可受控部分交付 | 仅经技术 PASS 与 Human QC 的 Child 可交付；记录客户允许依据、计划/实际数量、产物身份、确认人与原因；不得算完整履约 | D16-003 §§8,10 |
| A-REC-01 | 安全终结后才允许人工新 Attempt | 新执行可追踪、输出独立；不重建既有状态机为默认方案 | D16-003 §9 |
| A-REC-02 | Seed 采用人工有界补救，不以智能修复作为首发条件 | 坏素材可人工补拍/替换；不要求自动修帧；任何修复仍须通过技术 Gate，严禁盲目重提整个失败 Task | D16-001 §2; D16-003 §9 |

### 4.1 必须保留的异常语义

- **MUST_AUTO：** 输入/输出技术检查、执行身份与危险操作阻断。
- **HUMAN_ALLOWED：** Hook/剧情/配方选择、补拍、更换素材、人工 QC、明确确认部分交付。
- **MUST_STOP：** 已知损坏或未完成验证、UNKNOWN/孤儿执行、输出冲突、无法验证的重新执行、未满足交付条件。
- Batch2 一个 Child 成功、另一个失败时，仅成功 Child 可在独立技术 PASS、Human QC 及客户交付约定允许的前提下受控部分交付。
- 人工重新执行仅能在旧执行安全终结后开展，须有独立身份与独立 Output；**PRD 不指定数据库新状态或表结构**。

## 5. P0-A：Release Engineering RE-0 Requirements

| Requirement ID | 必须满足的产品行为 | 最小验收判据 | 冻结依据 |
|---|---|---|---|
| RE-01 | 明确 Build、Runtime Data、Backup/Recovery 三域所有权并只读核验实际路径 | Build/Package/DEV RESET 不隐式删除、覆盖或修改真实 SQLite、素材、Output/Delivery、Backup、Secure Settings；不能仅凭文件夹名称判断 | D16-002 §§3,7 (RE-G0/G1) |
| RE-02 | 有不可信路径/破坏性操作时 Fail Closed | 路径解析越界或路径归属未知时停止受影响操作 | D16-002 §3 (RE0-01~03) |
| RE-03 | 每份安装制品不可变且可追踪 | 记录 Git Commit、构建配置、制品身份、SHA256、Manifest、验收与审批 | D16-002 §4 (RE0-04) |
| RE-04 | RE-0 受控人工发布，不以自动 CI/CD 为首发要求 | 人工记录制品、目标设备/环境、批准人及安装结果；任何强制 Gate 不得跳过 | D16-002 §4 (RE0-05) |
| RE-05 | 升级前执行版本、任务、路径及恢复 Preflight | 存在 UNKNOWN/孤儿写入、无恢复条件或不兼容时阻断升级 | D16-002 §5 (RE0-06) |
| RE-06 | 真实升级必须有已验证一致性备份与完整数据集恢复方案 | 在授权隔离环境/副本验证 SQLite、素材/Output 引用及恢复软件兼容；仅有备份文件不是恢复 PASS | D16-002 §5 (RE0-07) |
| RE-07 | 迁移失败安全停机、保护原数据 | Binary Rollback 不视为 Data Rollback；不无证据自动覆盖恢复 | D16-002 §5 (RE0-08) |
| RE-08 | 普通卸载默认保留客户生产数据 | 卸载不删数据库、素材、Output、Delivery、备份；删除需单独明确授权 | D16-002 §6 (RE0-09) |
| RE-09 | RE-G0～G5 发布 Gate 可追踪 | G0～G4 提供适用证据；G5 严格绑定安装制品、目标、Owner 批准 | D16-002 §7 |
| RE-10 | 1.5 路径先逻辑隔离，不强制一次性物理迁移 | 不隐式迁移/清库；特殊路径缺陷停机并单独审批 | D16-002 §3 (RE0-03) |

### 5.1 Release Gate 定义

| Gate | 产品需要的证据 | 不能代替的授权 |
|---|---|---|
| RE-G0 Read-only Inventory | Build/Package/Reset/Install/Uninstall/Migration 脚本和 RuntimePaths 只读清单 | 不授权整改或 Build |
| RE-G1 Data Safety Boundary | 路径所有权、潜在破坏性操作、越界规则与阻断证明 | 不授权修改真实数据 |
| RE-G2 Isolated Build | 受控构建不碰生产数据；制品 ID/SHA256/Manifest | 不等于发布许可 |
| RE-G3 Install/Upgrade | Fresh/Upgrade、不兼容/异常阻断、卸载保留数据 | 不等于恢复 PASS |
| RE-G4 Backup/Recovery | 一致性备份、隔离恢复、引用与软件兼容性验证 | 不等于可以安装菲律宾 |
| RE-G5 Pilot Release | 精确制品、设备、证据、Owner 批准及现存 HOLD 独立解除 | 没有授权必须维持 HOLD |

RE-1 可重复自动化应逐项评估，但**不得将真实升级所必需的备份恢复安全能力从 RE-0 拖延到 RE-1**。RE-2 Fleet/自动更新按既定 1.7+ 后置。

## 6. P0-B：Studio Workspace Requirements

| Requirement ID | 必须满足的产品行为 | 最小验收判据 | 冻结依据 |
|---|---|---|---|
| B-ID-01 | Customer/Tenant/Workspace/Project 对象语义和精确基数 | Customer 在 Provision 前可有 0 Tenant，开通后可有多个；每 Tenant 明确 Customer 管理归属；Tenant 1:1 Workspace、1:N Project；每 Project 只属一个 Tenant | D16-004-A §§2–3 |
| B-ID-02 | Tenant 为客户级强制隔离主体 | Project 不宣称强安全 ACL；需项目间保密时使用独立 Tenant | D16-004-A §§4,6 |
| B-ID-03 | Operator 通过 Membership 可服务多个 Tenant | 不能以 Customer 归属或 Windows 用户代替 Membership | D16-004-A §§3,5; D16-005 §4 |
| B-DB-01 | 每 Tenant 独立 SQLite 是产品目标，保留单 FastAPI 网关方向 | 访问必须可信绑定 Tenant；现有 1.5 连接管理兼容性 NOT_VERIFIED，不自动批准重构 | D16-004-B §3 |
| B-DB-02 | 不以可变全局 db_path 作为无保护切换实现 | 旧 A 请求不得写入 B 数据库；实施机制经只读审查/必要 ADR | D16-004-B §3 |
| B-FILE-01 | 素材、Output、中间文件、缓存、交付记录具 Tenant 归属 | 相同文件名和旧执行残留不得跨 Tenant 覆盖或串用 | D16-004-B §4 |
| B-FILE-02 | 外部源引用为可选能力，未获批准前必须关闭该生产路径 | 若启用，需独立核准实际路径/重解析、Tenant 归属及生产内容与 Import PASS 一致性；不要求首版必须开发外部引用 | D16-004-B §5 |
| B-EXEC-01 | Task/Child/Attempt Tenant 身份不可变 | 创建时可信绑定；后续 UI 切换不改变执行归属 | D16-004-B §6 |
| B-CACHE-01 | API、订阅、缓存、缩略图与历史结果按 Tenant 隔离 | A 的延迟结果不得更新 B Workspace；本地 API 不越过授权 | D16-004-B §7; D16-004-C §5 |
| B-LEG-01 | 1.5 历史数据先安全保留；任何认领必须核实归属再受控映射 | VERIFIED/UNRESOLVED/CONFLICT 分流；归属不明不得自动认领或清理；不强制 B 首发完成全部旧数据认领 | D16-004-A §9; D16-004-B §8 |
| B-BACK-01 | Tenant 级恢复须验证数据一致性、其他 Tenant 安全及授权有效性 | 恢复 A 不覆盖 B；已撤销授权不能恢复；允许已验证的受控人工恢复，不强制全新 Backup UI | D16-004-B §10; D16-005 §14 |
| B-SW-01 | 切换时先建立可信运行时准入屏障，再检验全局静止并提交切换 | 阻断新 Task/Child 及其他冲突性有状态操作；前端禁用按钮不能替代后端屏障 | D16-004-C §3 |
| B-SW-02 | 全局安全静止而非仅 UI Completed | Queued、Running、Cancelling、UNKNOWN、孤儿进程、未结束写入阻断切换 | D16-004-C §2 |
| B-SW-03 | 目标授权及上下文验证通过后才进入 Tenant | 仅单 Active Tenant；失败安全回 A 或 Locked | D16-004-C §§4–5,7 |
| B-SW-04 | 运行时已安全静止时允许保留待 QC/Delivery 记录后切换 | 原 Tenant/Project 的 QC/Delivery 状态保留；未保存编辑需提示或安全保存；不强制全面自动保存 | D16-004-C §6 |
| B-SW-05 | 切换中崩溃重启必须重新核验 | 旧 Active Tenant 标记不足以恢复生产；有 UNKNOWN 时 Fail Closed | D16-004-C §8 |
| B-CP-01 | 管理员审核创建正式 Tenant，受控初始化 | 官网 Lead 不自动建户；初始化不能清空旧数据 | D16-005 §3 |
| B-CP-02 | 采用最小授权管理员、日常 Operator 角色及 Membership 管理 | Operator 不能自提权，平台管理员不自动获得全部客户生产数据访问权；授权变更和撤销可追溯 | D16-005 §§4,13 |
| B-CP-03 | Installation/Device 授权与 Membership 分开 | 复制配置不能自动激活；设备授权不代表任何人员有权访问 | D16-005 §§5,7 |
| B-AUTH-01 | 人员/设备/Tenant 有效性联合授权 Gate | 任何一项无效即拒绝新受保护操作，且不可绕过现有生产 HOLD | D16-005 §§6–7,18 |
| B-AUTH-02 | 首次登录/激活/首次授权必须在线 | 离线不得新建 Membership 或新增 Tenant 使用资格 | D16-005 §8 |
| B-AUTH-03 | 8 小时是离线租约候选最大绝对期限，不是必须达到的离线服务承诺 | 签发后起算，绑定 Operator+Installation+Tenant+权限范围；断网/重启/回拨不续期；租约不替代 Operator Session；时间不可信则拒绝 | D16-005 §8 |
| B-AUTH-04 | 首发离线仅继续当前 Tenant，禁止离线切换 | 当前租约有效且 Gates 均满足才继续受限操作 | D16-005 §§8–9,12 |
| B-AUTH-05 | 撤权/到期阻断新 Task/Child 与其他受保护操作，现有执行安全收尾 | 尚未启动的 Child 在到期后不可新启动；不盲目 Kill、不自动重提或无限运行；未重新授权不得交付 | D16-005 §§10–11 |
| B-AUTH-06 | 设备/人员失效或卸载不自动删客户数据 | 恢复旧业务数据不等于恢复过期/被撤销授权 | D16-005 §§10,14; D16-002 §6 |

### 6.1 Studio 的默认安全模型

- Customer 负责商业归属；Tenant 是客户级强制数据隔离；Workspace 是 Tenant 1:1 UI 投影；Project 是 Tenant 内业务组织，不承诺完整 Project ACL。
- Studio 同一时刻仅一个 Active Tenant；Tenant 切换不得自动取消任务，也不得仅靠前端禁用按钮实施 Switch Barrier。
- 每 Tenant 独立 SQLite 为目标模型，保留单 FastAPI 网关。**现有 1.5 单 SQLite 连接管理兼容性仍为 NOT_VERIFIED**；若触及 Frozen Architecture，先 ADR。
- 外部素材引用未经独立安全审查前不得默认成为生产路径；共享物理文件或相同 SHA256 不等于跨 Tenant 共享授权。
- 同一 Windows 用户下的隔离承诺为应用级，不承诺阻止具有文件系统权限的本机管理员直接读取本地文件。
- 离线租约的**8 小时是候选最长上限**，从最近在线签发时开始的绝对期限；实际启用需要时间可信性、撤销和运行任务收尾的独立验收，不能把“候选”改写成当前可用能力。

## 7. P1：Historical Creative Memory V1 Requirements

| Requirement ID | 必须满足的产品行为 | 最小验收判据 | 冻结依据 |
|---|---|---|---|
| L3-M0-01 | 历史事实不可改写，派生索引不替代 L1/L2 | FP-001/Task/Execution/Ledger 含义保持；无证据不猜测 | D16-006 §§2,4–5 |
| L3-M0-02 | 归属维度与索引覆盖维度分离 | VERIFIED/UNRESOLVED/CONFLICT 与 NOT_INDEXED/INDEXED/INDEX_ERROR/SOURCE_UNAVAILABLE 独立 | D16-006 §6 |
| L3-M0-03 | Schema Migration 与 Historical Backfill 分离，按批准维护窗口进行回填 | 不清库、不默认与生产并发；安全重入、算法/证据版本可追溯；失败不损毁 Output/Ledger | D16-006 §§4,12 |
| L3-M1-01 | 同 Tenant 以兼容 FP-001 查询历史规划 | PLANNED/RENDERED/FAILED 明确区分，不兼容版本不直接比 | D16-006 §7 |
| L3-M2-01 | 稳定、经确认输出建立 SHA256 精确身份 | 同 FP 可不同文件；跨 Tenant 相同哈希不授权跨租户访问 | D16-006 §8 |
| L3-M3-01 | 向 Operator 展示历史证据与覆盖范围 | 可看来源、时间、状态、成品可用性、缺口；No Match 不宣称全新 | D16-006 §§6,9 |
| L3-M3-02 | Historical Policy 维持 OFF/OBSERVE/ADVISORY 独立语义，不默认 ENFORCE | 查询失败显示不可用不视为无历史；不改变 L2 Reservation/Canary；Tenant 安全异常则阻断受影响操作 | D16-006 §§10,13 |
| L3-M3-03 | Operator 可人工查看、继续实验或在获准范围内复用 | 复用需满足归属、素材使用权及 QC/Delivery；不默认强制实现自动渲染前复用引擎 | D16-006 §§9,11 |

**L3 发布策略：** M0 作为所有相关升级/数据处理必须满足的非破坏性约束；M1、M2、M3 是 V1 CORE，不成为 1.6-A 或 1.6-B 的自动发布阻断项。Temporal pHash 是 1.6 P1 单独候选，Historical ENFORCE 和高级归因学习原则上后置。L3 Index Coverage 不完整不能被美化为“绝对无重复”。

## 8. 最小端到端验收矩阵（Scenario Baseline）

| AC ID | 验收情景 | 预期判定 | 所属 Gate |
|---|---|---|---|
| AC-A01 | 好原片完成导入、Batch2 双 Child、技术检查与逐条人工 QC | 两条均合格且身份独立；不以进程完成替代 QC | A + RE 适用 Gate |
| AC-A02 | 截断或损坏视频；正常 VFR 对照 | 损坏拦截、VFR 不被无依据拒绝 | A |
| AC-A03 | 通过检测后更换/修改源文件 | 旧验证结果不可无条件复用 | A |
| AC-A04 | Batch2 一个 Child 失败 | 保留合格 Child，整体不假称全部成功 | A |
| AC-A05 | UNKNOWN/孤儿进程时重试 | 不允许危险重试或覆盖 | A |
| AC-A06 | 技术合格但人工 QC 不通过 | 禁止合格交付 | A |
| AC-A07 | 客户只接受两条但实际只有一条合格 | 不可声称完整履约 | A |
| AC-RE01 | Build/DEV RESET 面对真实 Runtime/Backup 路径 | 不破坏客户数据 | RE-G0～G2 |
| AC-RE02 | 实际升级含 Schema 变化及恢复演练 | 已验证一致性备份和隔离恢复，否则 STOP | RE-G3/G4 |
| AC-RE03 | 普通卸载和重新安装 | 数据保留；授权另行核验 | RE-G3/G4 |
| AC-RE04 | 候选制品欲安装菲律宾设备 | HOLD 未解除不得执行 | RE-G5 + 既有生产 Gate |
| AC-B01 | 同设备两 Operator 和两 Tenant | Membership/Installation/Entitlement 三重约束有效 | B |
| AC-B02 | Tenant A 旧请求返回，当前 B | 不可污染 B 的数据库/缓存/界面 | B |
| AC-B03 | Task 正运行/Queued/UNKNOWN 时切换 | Barrier 拒绝，且不自动 Kill | B |
| AC-B04 | 运行静止但仍有待人工 QC | 允许授权切换，保留原业务状态 | B |
| AC-B05 | 切换过程中目标 DB 不可用或应用崩溃 | 可安全回原 Tenant 或 Locked，不混合上下文 | B |
| AC-B06 | 1.5 无可信归属旧素材 | 不自动归到当前 Tenant，不删库 | B + RE |
| AC-B07 | 租约在 Batch2 运行中到期 | 新执行准入停止；安全收尾；未授权不交付 | B |
| AC-B08 | 离线 8h 上限到期、系统时间回退 | 不可重启/改时间自行续期 | B |
| AC-L301 | Historical FP 命中 PLANNED/FAILED/RENDERED | 证据语义不混淆 | L3 |
| AC-L302 | 相同 FP，不同 SHA256；相同 SHA256，跨 Tenant | 不混淆规划与字节重复；不跨 Tenant 泄露 | L3 |
| AC-L303 | 历史索引未覆盖 / Output 已丢失 | No Match 不等于 Proven Novelty；保留原 Ledger 事实 | L3 |
| AC-L304 | Historical 服务不可用但 Seed Gates 安全 | 明示不可用、可降级；权限或完整性异常必须阻断 | L3 |
| AC-A08 | 不支持的编码与 AI 剧情分析失败对照 | 能区分技术不支持和语义分析错误，不能把后者误报媒体损坏 | A |
| AC-A09 | 旧执行已安全终结后发起独立 Attempt | 新身份可追踪；原成功 Output 不覆盖；UNKNOWN 时拒绝 | A |
| AC-RE05 | 同名不同字节的两份安装制品 | 身份/SHA256/Manifest 区分且来源可追溯 | RE-G2 |
| AC-RE06 | 仅有备份文件、没有成功恢复证据 | RE-G4 不得 PASS，真实升级阻断 | RE-G4 |
| AC-B09 | 外部素材路径越界、链接重解析或内容在检查后变化 | 未获批准引用拒绝；获批引用不得读错 Tenant/素材版本 | B |
| AC-B10 | 管理员无业务 Membership，尝试读取客户数据；复制设备配置 | 拒绝越权业务读取和配置克隆授权 | B |
| AC-B11 | 恢复 Tenant A 时 Tenant B 数据仍存在 | B 不受影响，失效授权不因恢复旧数据而恢复 | B + RE-G4 |
| AC-B12 | 切换前存在未保存编辑及待 QC 记录 | 编辑不静默丢失，QC/交付记录继续归属原 Tenant | B |
| AC-B13 | 在线撤权、断网租约未过期与到期后的比较 | 已知撤权禁止新操作；断网承认到期前有限延迟；到期无新准入 | B |
| AC-L305 | 历史 OFF/OBSERVE/ADVISORY 与 L2 并存 | L3 不暗中改变 L2 ENFORCE/Canary，也不默认硬阻断 | L3 |
| AC-L306 | 历史 Backfill 中断、重入及 Output 缺失 | 不伪造重复记录、不删原 Ledger，覆盖状态可解释 | L3 |

**当前所有 AC 的工程执行结果：NOT_VERIFIED。** 上表定义的是未来验收判据，不是已经通过的测试报告。没有预设“全部完成的工期”或未获批准的具体媒体规格。

**场景数由 23 补强为 34，新增场景只核验原 FROZEN 安全约束，不新增产品功能。** 单个端到端场景可覆盖多项需求；需求级断言仍必须单独留证。

## 9. 需求追踪与工程证据登记约定

每条需求的后续追踪记录应具有字段：`req_id / decision_ref / milestone / priority / candidate_commit / candidate_artifact / implementation_state / test_case / evidence_uri / release_gate / owner / updated_at`。

跟踪状态必须拆分为三个互不代替的维度：

- **Engineering evidence:** `NOT_VERIFIED` / `EXISTING_VERIFIED` / `GAP`。
- **Architecture approval:** `NO_ADR_IDENTIFIED` / `ADR_REVIEW_REQUIRED` / `ADR_APPROVED`（仅在适用时记录）。
- **Release / Gate approval:** `HOLD` / `NOT_AUTHORIZED` / `PASS_WITH_EVIDENCE`（按 Gate 记录）。

建议跟踪字段补充 `requirement_type / ac_ids / evidence_state / architecture_status / gate_status / responsible_role`。不得用单一 `PASS` 同时代表功能验收、工程实施授权和生产安装许可。

## 10. 依赖顺序与风险

| 依赖工作 | 性质 | 风险/下一步 |
|---|---|---|
| RE-G0 与当前工程 Handoff 定点只读调查 | 必要但未授权 | 真实路径、备份恢复、Candidate P/Q 证据必须分开 |
| A 生产链路的真实候选制品验证 | 必要但未授权 | 健康原片、损坏阻断、Batch2、Output、QC |
| B 独立 SQLite 与单网关兼容性 | 高风险 NOT_VERIFIED | 只读核验连接生命周期；架构冲突先 ADR |
| B 旧素材引用、1.5 数据归属 | 高风险 NOT_VERIFIED | 外部路径与历史归属未确认先阻断危险处理 |
| B 时钟可信性与授权撤销/收尾 | 高风险 NOT_VERIFIED | 未通过则缩短或关闭离线生产，不能降低安全 Gate |
| L3 FP-001、Ledger、Output 血统 | 高风险 NOT_VERIFIED | 先限制范围的 Provenance Audit，再选增量索引 |

**推荐排序：** 冻结 PRD 范围 → 独立批准只读 RE-G0/工程差距调查 → 核验 A 与 RE-0 安全缺口 → 制定 A 最小整改方案 → A 验收及独立发布审批 → B 产品需求工程设计与 ADR（如需）→ B 验收 → L3 P1 独立安排。此序列不表示必须等 B 完成才开始 L3 的只读设计，也不新增 D16-001 未批准的 1.6-C 里程碑。

## 11. 明确非目标与待工程定义项目

**非目标：** 跨 Task/跨 Tenant 未验证并发、整个失败 Task 自动重提、AI 自动修帧、完整自动 Story Mining、企业级 Project ACL、CRM/计费/自助租户、Fleet/自动更新、跨设备业务视频同步、pHash 的默认强制实现、Historical ENFORCE、跨 Tenant Creative Memory。

**待独立工程/验收方案定义（不是本轮 PRD 缺陷或隐式授权）：** 支持输入/输出格式与边界阈值；Output QC 技术检查集；现有 Task/Child/Attempt 的承载方案；RuntimePaths 与真实备份恢复机制；SQLite 连接管理；外部素材引用的路径安全与 TOCTOU 防护；Tenant Switch Barrier/Locked 具体机制；离线 8h 时间可信性和安全收尾；旧 1.5 数据归属证据；L3 具体 Backfill/算法版本。

## 12. 里程碑完成定义与变更控制

**1.6-A 功能完成条件：** 相关 P0-A 需求及 AC-A 与适用 RE-G0～G4 在被批准的候选制品上有 PASS 证据。**生产安装**仍需 RE-G5 与所有现存 HOLD 的独立正式解除；不能因 A 完成而默认放行菲律宾。

**1.6-B 功能完成条件：** 所有 P0-B 需求及 AC-B 经候选版本验收，且证明没有破坏 A 的已验证生产安全；涉及升级还需适用 RE-Gates。仍需独立发布批准。

**L3 V1 完成条件：** M0～M3 产品约束与适用 AC-L3 在实际候选版本验证；不以 pHash/ENFORCE 作为默认完成标准，也不作为 A/B 的自动前置条件。

**变更控制：** PRD 只能解释和拆分 FROZEN 决策，不能修改其语义；涉及新增范围/安全边界/里程碑调整必须由 Owner 独立决定，涉及 Frozen Architecture 的实施变更必须 ADR。PRD 的 Owner 审核与工程授权是两次独立动作。

## 13. Owner 冻结记录与下一步

**Freeze record:** Product Owner 于 2026-11-07 明确回复“接受批准 PRD v1.0-R1 产品范围基线”。因此，R1 的 **59 条 Requirement ID、34 个 Scenario ID、优先级归属及安全边界** 获批准，PRD 正式标记为 **FROZEN (Product Scope Baseline v1.0)**。

- 本次批准仅冻结产品范围、验收目标与决策追踪，并不证明相应能力已经实现或测试 PASS。
- `DECISIONS.md` 的八项 FROZEN 决策仍高于 PRD；若有冲突不得静默修改原合同，须提出独立 Owner 审批。
- 后续 `ACCEPTANCE_MATRIX.md` 和 `ENGINEERING_DEPENDENCIES.md` 属于待审查的执行规划文件，**不是已冻结工程事实**。
- 本 PRD 不授权只读工程调查、源码修改、数据库迁移、Build、Commit、Push、安装或生产发布；具体操作须独立授权。
- 所有 1.5 Frozen Architecture、Closed Phases 与现存 Production HOLD 不受影响。
