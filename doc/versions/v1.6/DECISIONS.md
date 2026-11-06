# DopaMatrix 1.6 — DECISIONS

> **用途：** DopaMatrix 1.6 产品 Owner 正式批准的决策记录。本文档记录产品约束和验收边界，**不构成工程实施、合并、构建、安装、迁移或发布授权**。
>
> **实际仓库目标路径（依据 Owner 提供的 Cursor 截图）：** `doc/versions/v1.6/DECISIONS.md`
> **当前内容：** D16-001 v1.0、D16-002 v1.0、D16-003 v1.0、D16-004-A v1.0、D16-004-B v1.0、D16-004-C v1.0、D16-005 v1.0、D16-006 v1.0（均为 FROZEN 决策）
> **记录日期：** 2026-11-06

## 决策索引

| ID | 决策名称 | 版本 | 状态 | Owner 批准日期 |
|---|---|---|---|---|
| D16-001 | DopaMatrix 1.6 Milestone & Operational Boundary Contract | v1.0 | **FROZEN** | 2026-11-05 |
| D16-002 | Release Engineering 1.0 Safety & Delivery Contract | v1.0 | **FROZEN** | 2026-11-05 |
| D16-003 | Seed Operations Reliability & Human Recovery Contract | v1.0 | **FROZEN** | 2026-11-05 |
| D16-004-A | Studio Core Identity, Hierarchy & Ownership Contract | v1.0 | **FROZEN** | 2026-11-06 |
| D16-004-B | Tenant Data Plane Isolation Contract | v1.0 | **FROZEN** | 2026-11-06 |
| D16-004-C | Idle-only Switch & Runtime State Contract | v1.0 | **FROZEN** | 2026-11-06 |
| D16-005 | Control Plane, Membership & Device Activation Contract | v1.0 | **FROZEN** | 2026-11-06 |
| D16-006 | Historical Creative Memory V1 & Novelty Policy Contract | v1.0 | **FROZEN** | 2026-11-06 |

---

## D16-001 — DopaMatrix 1.6 Milestone & Operational Boundary Contract

**Status:** FROZEN
**Version:** v1.0
**Date:** 2026-11-05
**Approved by:** Product Owner
**Approval date:** 2026-11-05
**Scope:** DopaMatrix 1.6

### 1. 决策目标

将 DopaMatrix 1.6 划分为两个有明确交付边界、验收条件和授权 Gate 的里程碑，以优先保障菲律宾种子运营可靠性，再建设 Studio 多租户能力。

本决策不改变现有 1.5 Frozen Architecture，不重新开启 Closed Phases，不解除任何现存 Production HOLD。

### 2. Milestone A — Seed Reliability Baseline

1. 聚焦健康素材导入、人工编排、单 Task 内 Batch2、输出完整性检查及人工补救。
2. 素材技术完整性检查采用 MUST_AUTO / HUMAN_ALLOWED / MUST_STOP 三层合同。
3. 系统必须阻止明确不合格素材进入正常生产；人工可以更换、补拍或重新导入素材。
4. 不要求首发自动修复坏帧、重生视频或实现全自动运营。
5. 保留已验证范围内的单 Task Batch2；不开放未经验证的跨 Task 并发、整个失败 Task 自动重提或 UNKNOWN 执行资源复用。
6. 必须保证 Child 执行身份、输出保护、异常可解释及必要的人工 QC。
7. 任何正式 Build、Upgrade、Release 均须满足适用的 RE-0 数据安全合同。
8. 本里程碑不以完整 Studio、云端 IAM、CRM 或多租户控制平台作为交付前提。

Milestone A 达成不自动批准菲律宾安装。既有 Production HOLD 必须根据原工程 Gate 和 Owner 授权单独处理。

### 3. Milestone B — Studio Workspace MVP

1. 支持一个 Operator、一个 Windows 用户、一个 Tauri 会话管理多个获授权 Tenant。
2. 首版采用单 Active Tenant 模式。
3. 首版采用 Idle-only Switch，切换前必须验证本地执行系统处于安全静止状态。
4. 任务创建时必须绑定不可变的 Tenant 与 Execution Identity。
5. Tenant 之间的业务数据库、素材、Output、配置、缓存、前端状态、后台执行及实时订阅必须实施必要隔离。
6. Control Plane 首发范围以最小 Customer/Tenant/Operator/Membership、设备授权及受控初始化闭环为目标，具体实体合同在独立决策中冻结。
7. 不开放跨 Tenant 后台并发、多设备业务视频同步、自助建户或复杂计费。

Milestone B 不得破坏 Milestone A 的已验收生产能力，也不得假定已有 1.5 数据自动完成 Tenant 归属迁移。

### 4. Idle-only Switch 安全定义

只有在所有相关 Task 和 Child 已安全终结、执行进程及资源无未决风险、没有 UNKNOWN 或孤儿执行、授权有效，并能安全切换 Tenant 数据上下文时，才允许切换。

Running、Queued、Cancelling、Unresolved 和资源状态不确定的执行均不得被视为 Idle。

切换失败必须 Fail Closed，不得允许跨 Tenant 身份、数据和运行状态混用。

### 5. Release 与数据保护边界

RE-0 是任何新真实客户发布或升级路径的最低安全前置合同。

Build、Package、DEV RESET 不得隐式修改或清理真实 RuntimePaths、SQLite、Output、Delivery、Backup 和 Secure Settings。

涉及 Schema 变化的升级必须具备迁移前保护、迁移后验证及明确的恢复策略。

Binary Rollback 不等于 Data Rollback。

### 6. 里程碑验收规则

- A 必须通过健康素材、异常输入、Batch2 独立结果、人工补救、媒体完整性及适用发布安全验证。
- B 必须通过身份授权、Tenant 数据隔离、执行绑定、Idle-only Switch、异常恢复及升级兼容验证。
- 功能验收、发布工程验收和生产安装授权是不同 Gate，不能相互替代。
- 所有关键验收必须绑定可追溯的代码版本、安装制品、测试条件和证据。

### 7. 架构与工程权限

本决策只冻结产品目标、阶段边界及验收约束，不直接授权 Codex 修改代码、数据库、构建脚本、安装程序或真实生产数据。

涉及 Frozen Architecture 的变更必须通过独立 ADR 和工程 Owner 审批。

### 8. 不在 D16-001 中冻结的细节

以下内容由后续独立决策处理：

- D16-002：Release Engineering 1.0 的具体安全合同。
- D16-003：Seed Operations 异常处理与人工责任的完整验收标准。
- D16-004：Tenant/Workspace 模型、数据归属与切换协议。
- D16-005：Control Plane 最小授权及设备激活合同。

**Freeze record:** Product Owner 于 2026-11-05 明确回复“批准冻结 D16-001 v1.0”。因此，D16-001 v1.0 的状态由 `PROPOSED_FOR_FREEZE` 更新为 **`FROZEN`**。

**Implementation authority:** **NOT_GRANTED**。该产品冻结不解除 `PHILIPPINES_INSTALL = HOLD`、`LOCAL-P-R1 = FAIL/HOLD` 或其他尚未解除的工程 / Production HOLD；如需真实工程操作，应依据最新权威工程 Handoff 和独立 Owner 授权办理。

---

## D16-002 — Release Engineering 1.0 Safety & Delivery Contract

**Status:** FROZEN
**Version:** v1.0
**Date:** 2026-11-05
**Owner:** Product Owner
**Approval date:** 2026-11-05
**Scope:** DopaMatrix 1.6-A / 1.6-B
**Depends On:** D16-001 v1.0 — FROZEN
**Implementation Authority:** NOT_GRANTED

### 1. 决策目标

建立 DopaMatrix 在真实客户数据环境下的最低安全构建、安装、升级、卸载、恢复和发布合同。

Release Engineering 不仅负责生成安装包，更必须保证生产数据受到保护、升级具有明确安全边界、安装制品可以追溯、失败具备可验证的恢复方案。

本决策遵守 D16-001 已冻结的两阶段交付策略：

- 1.6-A：Seed Reliability Baseline。
- 1.6-B：Studio Workspace MVP。

不得改变 1.5 Frozen Architecture、重新审计 Closed Phases 或自动解除既有 Production HOLD。

### 2. Release Engineering 分层策略

#### RE-0 — Minimum Production Safety

作为 1.6 的 P0 安全基础，优先建立：

1. 构建与生产数据逻辑隔离。
2. 真实生产路径所有权和访问边界。
3. 受控人工发布。
4. 不可变安装制品身份与校验记录。
5. 安全安装、升级和卸载合同。
6. 适用的备份、恢复与兼容性验收。
7. 明确的 Release Gate 和批准记录。

RE-0 不要求建设完整自动化 CI/CD 或集中更新系统。

人工操作不能替代必须通过的安全检查。

#### RE-1 — Repeatable Release Engineering

在 RE-0 基础上进一步完善：

- 可重复隔离构建。
- 标准化升级迁移及恢复流程。
- 自动化回归和兼容性测试。
- 规范的 Release Manifest、Receipt 和归档。
- 系统化备份与恢复演练。

实际升级所需的关键安全能力不得仅因划入 RE-1 而延期。

#### RE-2 — Fleet & Update Automation

原则上安排在 1.7+：

- 自动更新。
- 灰度发布。
- 集中化设备版本管理。
- 多设备发布状态监控。

不作为 1.6-A 的强制交付前提。

### 3. 数据所有权与路径保护合同

#### RE0-01 — Path Ownership

将文件与目录划分为三个逻辑区域：

**A. Source / Build Zone**

源代码、构建中间文件、临时制品及经过明确授权的可清理构建目录。

**B. Runtime Data Zone**

业务 SQLite、生产素材、Output、Delivery、生产配置、持久化状态、必要的运行日志及 Secure Settings。

**C. Backup / Recovery Zone**

备份数据、恢复清单、恢复验证记录及必要的受保护恢复资料。

#### RE0-02 — Non-destructive Build

1. Build、Package 和 DEV RESET 必须与真实客户 Runtime Data、Backup/Recovery 建立明确隔离。
2. 不得隐式删除、覆盖、重置或修改真实生产数据库、素材、Output、Delivery、Backup 和 Secure Settings。
3. 破坏性操作仅可作用于明确授权的目标路径。
4. 路径归属不明确、实际解析路径越界或无法证明安全时，必须拒绝破坏性操作。
5. 不允许通过构建流程隐式重新 Seed、清库或重建客户生产数据。
6. 必须区分测试环境 Reset 与真实客户环境 Upgrade。

#### RE0-03 — Existing 1.5 Compatibility

1. 1.6-A 不强制迁移现有 1.5 生产数据物理目录。
2. 首先建立逻辑隔离、安全路径审查及非破坏性操作合同。
3. 如果现有路径无法满足安全边界，必须先停止受影响操作，单独提出变更方案。
4. 任何未来的数据目录迁移，必须另行定义数据清单、兼容性、迁移流程和恢复 Gate。
5. 不得以本决策为依据直接修改 Frozen Architecture。

### 4. 安装制品身份与发布管理

#### RE0-04 — Immutable Artifact

每个可交付安装制品必须具备：

- Source Git Commit。
- 软件版本与构建配置标识。
- 唯一 Artifact Identity。
- SHA256 校验值。
- Release Manifest。
- 适用的测试与验收证据。
- 发布渠道、目标范围及审批记录。

不同内容的安装制品不得复用同一制品身份。

不得通过覆盖原安装包来替代已归档的发布证据。

SHA256 负责字节完整性核验，不单独构成可信发布来源的身份认证。发布来源及交付渠道必须受控。

#### RE0-05 — Controlled Manual Release

RE-0 首发采用受控人工发布。

允许人工发起构建、检查、安装和升级，但不得绕过任何适用的强制 Gate。

每次真实客户安装或升级，必须能够明确识别：

- 安装制品。
- 目标设备与目标环境。
- 适用数据版本。
- 验收证据。
- 发布批准人。
- 安装结果及失败状态。

产品验收通过不等于获得生产安装授权。

### 5. Upgrade、Backup 与 Recovery

#### RE0-06 — Upgrade Preflight

真实客户升级前必须检查：

1. 目标软件版本及数据版本兼容性。
2. 当前执行任务及相关后台进程是否处于安全静止状态。
3. 是否存在 UNKNOWN、孤儿进程或未完成的危险写入。
4. 生产数据路径是否明确、可访问且受到保护。
5. 是否具备足够资源和满足要求的恢复条件。
6. 适用的迁移与恢复证据是否已通过。

任一强制前提不满足时，必须停止危险升级。

#### RE0-07 — Backup & Restore

真实生产数据升级必须具备已验证的备份与恢复方案。

备份保护范围应覆盖恢复业务所必需的数据集合，包括适用的 SQLite、素材、Output、配置、业务引用关系以及必要的安全凭据恢复条件。

数据库备份必须采用经过验证的一致性方法。

必须能够验证：

- 备份数据可读取且一致。
- 数据库结构和必要关系有效。
- 业务文件与数据库引用可恢复匹配。
- 恢复后的软件版本能够使用该数据。
- 恢复过程不会意外覆盖其他有效客户数据。

备份文件存在不等于恢复能力通过。

应使用获批准的隔离测试环境或测试副本进行恢复验证。不得为了演练直接破坏真实客户数据。

#### RE0-08 — Migration & Failure Handling

1. 任何 Schema 变化必须先具备适用的迁移前数据保护、迁移后验证及明确恢复方案。
2. Binary Rollback 不等于 Data Rollback。
3. 不允许默认以重新安装旧版软件来处理已发生不兼容数据迁移的环境。
4. 对迁移中断、数据版本不兼容、资源不足或执行状态异常，应采用 Fail Closed。
5. 恢复动作必须基于已验证策略，不能默认自动覆盖现有数据。
6. 无法证明安全恢复时，停止生产操作、保留原始数据和必要诊断证据，进入人工恢复流程。

不承诺未经验证的零数据损失或自动无感回滚能力。

### 6. Uninstall 与 Data Retention

#### RE0-09 — Preserve-by-default

普通卸载默认保留客户生产数据。

卸载程序二进制与删除客户业务数据必须分离。

默认不得删除：

- 业务数据库。
- 生产素材。
- Output / Delivery。
- 业务相关配置。
- 备份及恢复资料。

对需要清除本地生产数据的情况，应另行设计明确授权、范围确认和安全删除流程。

数据保留不等于永久保留所有设备授权或安全凭据；相关安全凭据、注销和重新激活行为须满足独立授权合同，并确保数据不会因此被意外破坏。

卸载、重新安装及重新连接原有生产数据必须经过兼容性验收。

### 7. Release Engineering 前置 Gate

#### RE-G0 — Read-only Inventory

只读核验现有 Build、Package、Reset、Install、Uninstall、Migration 相关脚本和路径。

确定真实 RuntimePaths、SQLite、Output、Backup、Secure Settings 的使用与所有权。

#### RE-G1 — Data Safety Boundary

识别破坏性操作、清理规则、路径越界风险和生产数据写入边界。

明确缺陷、整改要求及不可执行路径。

#### RE-G2 — Isolated Build Validation

在受控隔离环境证明构建、打包及清理不会影响受保护的生产数据。

验证制品身份、校验值及 Manifest。

#### RE-G3 — Installation & Upgrade Validation

验证 Fresh Install、现有支持版本 Upgrade、版本不兼容、安全静止检查、异常停止及卸载数据保留。

#### RE-G4 — Backup & Recovery Validation

验证适用的数据备份一致性、恢复可用性、业务引用完整性及故障处理。

#### RE-G5 — Pilot Release Authorization

绑定安装制品、验收证据、目标环境及 Owner 授权。

现存 Production HOLD 未解除前，不允许通过本 Gate 获得菲律宾生产安装许可。

所有 Gate 必须提供可追溯的执行证据。具体检查手段、测试覆盖范围和负责角色应在获批的工程审查计划中定义。

### 8. 既有工程状态及 HOLD 保护

本决策不更改现有工程事实或生产授权。

保留已知状态：

- `LOCAL-P-R1 = FAIL/HOLD`
- `PHILIPPINES_INSTALL = HOLD`
- `G1-A1 = READ_ONLY CLOSED`
- `ARCHITECTURE_EXCEPTION = BLOCKED`
- `A1_ACTIVATION_BLOCKED = TRUE`
- `A2 = NOT_APPROVED`
- Production Lifecycle Receipt、Ownership、Runtime Guard、Q2 Final 等现存 HOLD

Candidate P/Main 与 Candidate Q 的分支、验证证据及安装制品必须明确区分。

不得将 Candidate Q 的实验或素材完整性检查能力宣称为 Candidate P 既有安装包能力。

对历史构建脚本可能存在的 destructive path，当前工程实况标记为 **NOT_VERIFIED**，必须通过后续授权的只读审查确认，不得直接假定缺陷仍然存在。

D16-002 的产品批准不改变上述任何 HOLD。

### 9. 工程实施与审批权限

本决策仅冻结 Release Engineering 产品安全原则、范围和验收约束。

不授予以下操作权限：

- 修改代码或构建脚本。
- 重置或迁移数据库。
- 删除、复制或修改真实客户生产数据。
- 运行 Build / Package / Installer。
- 修改 AGENTS、工程 Handoff 或冻结架构。
- Commit、Push、Tag 或发布。
- 在菲律宾设备安装或升级。

后续只读审查、工程实现、测试、构建、发布和安装应分别依据适用的授权及 Gate 进行。

如需更改 Frozen Architecture，必须单独提交 ADR 并获得 Owner 审批。

### 10. 本决策不冻结的实施细节

以下细节进入后续技术审查与独立设计：

1. 实际 RuntimePaths 清单和路径解析方法。
2. 具体构建、打包和清理脚本的整改方式。
3. SQLite 备份与恢复机制选择。
4. 数据目录物理迁移方案。
5. Installer / Uninstaller 实际技术实现。
6. Release Manifest 和 Receipt 的具体字段结构。
7. CI/CD、自动更新和集中设备管理方案。
8. 未来多 Tenant 备份、恢复及设备授权生命周期细节。

以上实施细节不得降低本决策规定的安全标准。

### 11. 冻结记录

**Freeze record:** Product Owner 于 2026-11-05 明确回复“批准冻结 D16-002 v1.0”。因此，D16-002 v1.0 的状态由 `PROPOSED_FOR_FREEZE` 更新为 **`FROZEN`**。

**Implementation authority:** **NOT_GRANTED**。D16-002 产品冻结不构成 RE-G0 只读工程审查、源码修改、构建、数据库迁移、安装或生产发布授权；`PHILIPPINES_INSTALL = HOLD` 及其他既有工程 / Production HOLD 继续有效。
---

## D16-003 — Seed Operations Reliability & Human Recovery Contract

**Status:** FROZEN
**Version:** v1.0
**Date:** 2026-11-05
**Approved by:** Product Owner
**Approval date:** 2026-11-05
**Scope:** DopaMatrix 1.6-A — Seed Reliability Baseline
**Depends On:** D16-001 v1.0 / D16-002 v1.0 — FROZEN
**Implementation Authority:** NOT_GRANTED

### 1. 决策目标

建立面向菲律宾运营团队及少量种子用户的可靠生产工作流。

核心路径为：

**健康素材 → Import Quality Gate → 人工 Story/Matrix 编排 → Single Task Batch2 → Output Quality Gate → Human QC → Delivery。**

1.6-A 优先追求安全、稳定、可解释、可人工补救的生产能力。

不追求首发无人值守、不要求自动修复所有素材问题，也不开放未经验证的跨 Task 并发。

### 2. Seed Operations 三层责任合同

#### MUST_AUTO

系统必须自动执行关键技术检查、安全校验及必要的状态管理。

包括素材完整性检查、输出完整性检查、执行身份识别和危险操作阻断。

#### HUMAN_ALLOWED

运营人员可以人工选择素材、调整创意方案、补拍或更换素材、执行视听 QC、决定安全的重新生产与交付。

#### MUST_STOP

出现以下情况时必须阻断受影响的危险操作：

- 明确不合格的输入素材。
- 关键检查尚未通过。
- UNKNOWN 或未安全终结的执行资源。
- 可能覆盖已有业务产物的输出冲突。
- 无法确认安全的重新执行。
- 不符合强制技术检查或交付条件的输出。

**人工操作不得绕过 MUST_STOP。**

### 3. Import Quality Gate

1. 系统必须对输入素材的基本结构、选定媒体流和完整解码进行有界技术验证。
2. 明确损坏、截断或不符合已声明技术输入合同的素材必须拒绝正常生产。
3. 不得仅因 VFR 判定素材损坏。
4. AI 无法理解剧情不等于媒体编码损坏。
5. 素材尚在检测中时，不得被标记为可正常生产。
6. 技术损坏、格式不支持和 AI 分析失败应提供可区分的处理提示。
7. 允许人工补拍、更换及重新导入；新素材必须重新验证。
8. 生产实际使用的素材必须与已通过验证的素材版本一致；一致性无法证明时必须重新检查或阻断使用。
9. 首发需要明确支持的格式、编码和技术检测边界，不承诺能够识别所有潜在媒体异常。

不要求自动修帧、重生损坏视频或建设复杂的内部恶意篡改防御。

### 4. Human Story / Matrix Operation

种子期允许运营人员：

- 人工选择 Story Node、Hook 和剧情片段。
- 调整情绪结构与创意配方。
- 选择或替换素材。
- 修改已支持的任务参数。
- 人工判断 AI 无法可靠处理的内容问题。

系统负责已定义的必要参数校验和生产安全约束。

不以全自动 Story Mining、全自动情绪编排或无人审核作为首发条件。

### 5. Single Task / Batch2 Contract

1. 保留一个逻辑 Task 内两个 Child 的有界 Batch2 能力。
2. 两个 Child 必须具备可区分的执行身份及各自输出。
3. 未经验证的跨 Task 并发继续禁止。
4. 不允许自动重新提交整个失败 Task。
5. 不允许盲目复用 UNKNOWN 执行资源。
6. 不允许同名覆盖或旧执行残留破坏已有业务产物。
7. 两个 Child 的技术结果必须独立识别和记录。
8. 历史 Batch2 成功证据不能自动代替当前候选制品的验收。

本合同不批准重新设计既有 Task/Child 执行架构。

### 6. Output Quality Gate

每个 Child 的输出必须独立接受技术完整性验证。

验证要求应覆盖适用的文件可读性、媒体流完整性、解码可用性及已定义的输出规格合同。

执行返回成功不能直接代表媒体健康。

输出检查失败时：

- 不得标记为技术合格。
- 不得进入合格交付。
- 应保留必要的失败原因与输出身份。
- 不得自动触发整个 Task 重新执行。

自动技术检查不取代人工内容 QC。

### 7. Execution / Validation / QC / Delivery 语义

必须区分四种逻辑判断：

1. **Execution State**：生产执行是否完成、失败或处于未知状态。
2. **Output Validation**：生成媒体是否通过技术检查。
3. **Human QC**：运营人员是否完成必要的视听和内容验收。
4. **Delivery Eligibility**：该产物是否满足实际交付条件。

执行成功不等于输出合格。

输出技术合格不等于人工 QC 通过。

人工 QC 通过也不代表已经完成实际交付。

四种语义必须可以区分，但不强制立即修改既有数据库状态枚举。

### 8. Batch2 Partial Success

当同一 Task 内一个 Child 成功、另一个 Child 失败时：

1. 必须保留成功 Child 的有效结果。
2. 整体 Task 不得被认定为 Batch2 全部成功。
3. 不自动重新执行失败 Child 或整个 Task。
4. 失败 Child 的结果、原因和安全状态必须可追溯。
5. 成功 Child 仍须通过独立 Output Gate 和 Human QC。
6. `PARTIAL` 可以是产品聚合展示语义，不要求首发直接新增底层状态枚举。
7. 单个合格 Child 不得被用于虚假宣称两个 Child 均已完成。

如果已有结果的安全身份或完整性仍不明确，不能仅因部分成功展示就放行交付。

### 9. Human Recovery & Independent Attempt

1. 允许人工更换素材、调整编排并请求新的生产操作。
2. 只有在相关旧执行、子进程、文件写入和资源状态已安全终结时，才允许启动可能冲突的新执行。
3. 新执行必须具备独立、可追踪的 Attempt 或等价执行身份。
4. 新输出不得覆盖原有合格产物。
5. UNKNOWN、孤儿执行和资源冲突必须采用 Fail Closed。
6. 不允许未经验证的自动重提或危险原地重跑。
7. 新 Attempt 在既有 Task 中承载还是通过新的逻辑 Task 承载，由后续工程审查决定。
8. 不强制在 1.6-A 重建 Task 状态机、数据库模型或调度系统。

人工重新执行是受控的新操作，不是对原失败执行的无条件继续。

### 10. Human QC & Delivery

#### Human QC

种子期每个拟交付视频必须逐条接受必要的人工视听验收。

检查范围包括适用的画面、声音、字幕、剧情连贯性及创意交付要求。

人工 QC 必须基于实际拟交付产物完成，不能仅以其前序母带或其他 Child 的检查结果替代。

#### Partial Delivery

允许受控部分交付，但必须同时满足：

1. 被交付 Child 已通过输出技术检查。
2. 已完成必要的人工 QC。
3. 客户交付要求允许减少数量或接受部分交付。
4. Operator 明确确认此次部分交付。
5. 可记录原定数量、实际交付数量、交付产物身份、确认人和未完成原因。
6. 不得将部分交付记录为完整履约。

种子期允许利用现有能力或受控人工记录完成交付确认，不要求首发建设完整的 Delivery Approval Engine。

### 11. 最低运营验收矩阵

至少覆盖以下场景：

1. 健康业务原片正常导入与产出。
2. 明确损坏或截断素材被阻断。
3. 正常 VFR 素材不被无依据拒绝。
4. 不支持的编码与损坏文件能够得到适当区分。
5. AI 剧情理解失败不被误判为编码损坏。
6. 人工替换素材后必须重新验证。
7. 已验证素材发生变化时不会无条件复用旧 PASS。
8. Batch2 两个 Child 分别成功并通过媒体检查。
9. Batch2 一成功一失败，保留独立结果。
10. 任务 UNKNOWN 时危险重试被阻断。
11. 同名输出、历史进程残留等冲突不破坏已有产物。
12. 技术检查不合格的输出无法进入合格交付。
13. 技术检查通过但人工 QC 失败的输出不被当作合格交付。
14. 安全终结后人工重新执行具有独立身份及安全输出边界。
15. 符合交付要求时，成功 Child 可以经明确确认完成部分交付。
16. 客户要求两个合格产物时，不允许以一个合格 Child 声称完整交付。

每项验收必须绑定适用的候选版本、测试条件和可追溯证据。

具体自动化测试实现及 UI 方案另行审批。

### 12. 既有工程边界与授权

本决策遵守 D16-001、D16-002 已冻结的产品合同。

保留 1.5 Frozen Architecture、Closed Phases，以及全部未解除的工程和 Production HOLD。

尤其保留：

- `LOCAL-P-R1 = FAIL/HOLD`
- `PHILIPPINES_INSTALL = HOLD`
- `ARCHITECTURE_EXCEPTION = BLOCKED`
- `A1_ACTIVATION_BLOCKED = TRUE`
- `A2 = NOT_APPROVED`
- Production Lifecycle Receipt / Ownership / Runtime Guard / Q2 Final 等现存 HOLD

Candidate P 与 Candidate Q 的实际能力、分支及安装制品不得混淆。

D16-003 通过产品审查，不代表现有工程已通过 Seed RC 验收。

本决策不授权 Codex：

- 修改代码、数据库或状态机。
- 修改 Frozen Architecture。
- Build / Commit / Push。
- 执行真实素材测试。
- 安装或升级菲律宾设备。
- 解除任何工程或生产 HOLD。

涉及 Frozen Architecture 的实施变更，必须通过独立 ADR 和 Owner 审批。

### 13. 冻结条件与后续实施

Product Owner 明确批准 D16-003 v1.0 后，决策状态方可更新为 `FROZEN`。

冻结后：

1. 本决策成为 1.6-A Seed Operations 的正式产品行为与验收合同。
2. 具体工程适配需以真实源码和最新工程 Handoff 为依据。
3. 任何测试、整改、构建与发布都必须另行授权。
4. 首发优先保障健康素材和单 Task Batch2 的安全生产路径。
5. 不因本决策而提前扩张跨 Task 并发、全自动重试或复杂 Delivery 系统。

**Freeze record:** Product Owner 于 2026-11-05 明确回复“批准冻结 D16-003 v1.0”。因此，D16-003 v1.0 的状态由 `PROPOSED_FOR_FREEZE` 更新为 **`FROZEN`**。

**Implementation authority:** **NOT_GRANTED**。本次产品冻结不授权任何工程操作，不解除 `PHILIPPINES_INSTALL = HOLD`、`LOCAL-P-R1 = FAIL/HOLD` 或其他尚未解除的工程 / Production HOLD。

---

## D16-004-A — Studio Core Identity, Hierarchy & Ownership Contract

**Status:** FROZEN
**Version:** v1.0
**Date:** 2026-11-06
**Owner:** Product Owner
**Approval date:** 2026-11-06
**Scope:** DopaMatrix 1.6-B — Studio Workspace MVP
**Depends On:** D16-001 / D16-002 / D16-003 — FROZEN
**Related:** D16-004-B / D16-004-C / D16-005 / D16-006
**Implementation Authority:** NOT_GRANTED

### 1. 决策目标

建立 DopaMatrix Studio 的 Customer、Tenant、Workspace、Project 四类核心业务对象、层级关系、数据归属与授权边界。

首发目标是在一个 Windows 用户、一个 Tauri 会话中，让一个 Operator 安全访问多个获授权客户 Tenant。

本决策遵守 D16-001 已冻结的单 Active Tenant、Idle-only Switch 和不开放跨 Tenant 后台并发等约束。

### 2. 核心对象定义

#### Customer / Organization

商业客户与客户管理主体。

负责商业关系、合同关系、客户归属和后续客户服务管理。

Customer 本身不构成本地生产数据的直接访问授权。

#### Tenant

DopaMatrix 强制的客户级数据隔离与授权边界。

Tenant 具有稳定、不可变的身份。

各类业务数据、生产执行、输出和历史创意记录必须具有可信的 Tenant 归属。

#### Studio Workspace

与 Tenant 1:1 对应的逻辑 UI 工作空间。

Workspace 是 Tenant 的运营界面和工作上下文，不是独立的安全主体。

1.6-B 不建设独立 Workspace IAM 或 Workspace Membership。

#### Project

Tenant 内部的业务生产组织单位。

负责组织 Story、Matrix、Factory、QC、Attribution 及相关业务资产。

Project 不默认构成独立的强安全隔离主体。

### 3. 对象层级与基数

1. Customer 允许管理多个 Tenant；种子期默认每个正式客户一个 Tenant。
2. Customer 在完成 Provision 前可以尚无 Tenant。
3. 每个已创建 Tenant 在同一时刻具有明确的 Customer 管理归属。
4. Tenant 与逻辑 Studio Workspace 为 1:1。
5. Tenant 可以拥有多个 Project。
6. 每个 Project 只能归属一个 Tenant。
7. Operator 与 Tenant 为 N:M，通过 Membership 获得访问授权。
8. Operator 的跨 Tenant Membership 不改变任一 Tenant 的数据所有权。
9. Project 的跨 Tenant 转移不得通过简单修改归属 ID 实现。

Customer 商业管理关系、合同付款关系与业务数据权利归属必须能够区分；不得仅凭付款关系自动授权访问客户生产资产。

### 4. Tenant 安全边界

1. Tenant 是强制的客户级授权和业务数据隔离主体。
2. Customer 归属不能替代有效 Membership。
3. Device Activation 不能替代 Operator Membership。
4. 前端 Active Tenant 选择不能单独构成可信授权。
5. 后端及本地数据访问必须依据可信身份和 Tenant 上下文进行约束。
6. Task、Child、Attempt、Output、QC 与 Historical Memory 必须具有明确且可追溯的 Tenant 归属。
7. Task 创建后的 Tenant 身份不得因 UI 切换被改变。
8. Tenant 数据隔离必须覆盖数据库、素材、Output、缓存、查询、事件订阅及必要的执行资源。
9. 数据或权限归属无法确认时必须 Fail Closed。

具体 SQLite、进程、路径和缓存实现由 D16-004-B 独立审查。

### 5. Operator 代运营模型

1. 一个 Operator 可以通过多个 Membership 服务不同 Tenant。
2. 同一 Tauri 会话任一时刻只有一个 Active Tenant。
3. Operator 不拥有跨 Tenant 自动汇总、检索或复用客户业务数据的权限。
4. 不允许因为 Operator 同时属于多个 Tenant，就建立跨客户共享业务数据库或历史创意库。
5. Operator 切换 Tenant 时必须遵守 D16-001 的 Idle-only Switch。
6. 设备授权及 Membership 失效、撤销、离线有效性等细节由 D16-005 冻结。

1.6-B 不开放跨 Tenant 后台任务并发。

### 6. Project 权限边界

种子期以 Tenant Membership 为主要访问授权机制。

Project 主要负责业务组织、数据归属、筛选和工作流管理。

1.6-B 不强制实现完整 Project 级 ACL。

因此：

1. Project 级 UI 筛选不得被描述为强安全隔离。
2. 不能向客户承诺同 Tenant 内不同 Project 之间具有完整保密边界。
3. 对需要严格业务部门隔离的客户，应使用独立 Tenant，或在未来提供经过验证的 Project ACL。
4. 不得使用仅靠前端隐藏内容的方式替代真实权限控制。

### 7. 资产归属和复用

资产逻辑归属分为：

- Tenant Shared Assets。
- Project Owned Assets。
- Platform Public Assets。

同 Tenant 内可按产品规则共享客户公共资产，例如品牌 Logo、公共 Story Bible 和获准共享的创意模板。

Project Owned 资产必须保留明确来源与项目归属。

跨 Project 引用应保留必要的来源、版本、关联和使用权信息。

跨 Tenant 的客户业务资产默认禁止共享或复用。

平台公共模板应采用独立授权与资产归属规则，不得与客户专属数据混淆。

本决策不要求立即重构现有 DAM 或 Story Bible 数据结构。

### 8. Historical Creative Memory 归属

D16-006 Historical Creative Memory V1 必须遵守 Tenant 级数据隔离。

1. 历史创意索引具有明确 Tenant 归属。
2. 历史记录保留适用的 Project 来源。
3. 同 Tenant 内可以支持经过授权的跨 Project 查询与复用。
4. Project 默认筛选只是产品体验，不构成独立权限隔离。
5. 跨 Tenant 历史检索和客户专属创意复用默认禁止。
6. Historical Ledger、Planning FP、Render Fingerprint 与历史索引不得因 Tenant 切换而发生归属混淆。
7. 历史数据缺失或无法验证时，不得自动认定其属于当前 Tenant。

D16-006 仍为 1.6 P1 候选，具体实现范围尚未冻结。

### 9. 1.5 历史数据归属

现有 1.5 数据的 Tenant 与 Project 归属需要独立验证。

建议采用以下产品状态：

- VERIFIED：可信证据能够支持归属。
- UNRESOLVED：归属缺失或证据不足。
- CONFLICT：存在相互冲突的归属证据。

1. 不允许按当前登录 Operator 自动认领全部历史数据。
2. 不允许按当前 Active Tenant 隐式重写旧数据归属。
3. 不能仅凭文件夹名称推断数据所有权。
4. 无法确认归属的旧数据必须保留并限制业务访问。
5. 归属冲突必须进入独立人工审查。
6. 任何归属映射、迁移和恢复必须遵守 D16-002 的 Release Engineering 安全合同。
7. 不允许以清空 1.5 数据作为 Studio 多租户升级的常规路径。
8. 不得改变既有 FP-001、Ledger、Task 和 Execution 的冻结业务语义。

上述状态不要求直接修改现有数据库枚举。

### 10. Workspace 与运行身份

Studio Workspace 是 Active Tenant 的 UI 投影。

首版必须遵守：

1. Active Tenant 身份明确且可验证。
2. Workspace 切换需经过授权检查。
3. 切换前必须满足全局执行安全静止要求。
4. 不允许旧 Tenant 的延迟请求或缓存结果污染新 Tenant。
5. 切换失败不能留下混合身份与数据状态。
6. 任何运行中的 Task 不允许因为 Workspace 切换改变 Tenant 或 Project 归属。

具体切换事务、缓存失效、订阅处理及异常恢复由 D16-004-C 冻结。

### 11. 最低产品验收场景

至少覆盖：

1. 一个 Customer 拥有多个 Tenant。
2. 一个 Tenant 拥有多个 Project。
3. 一个 Operator 获授权进入多个 Tenant。
4. 未获授权的 Operator 无法访问其他 Tenant。
5. Device Activation 不绕过 Membership。
6. Tenant 内不同 Project 保留明确归属。
7. Tenant 公共 Story Bible 可以被授权 Project 引用。
8. Project 私有资产不被自动改变归属。
9. 跨 Tenant 客户资产默认不共享。
10. Historical Memory 不发生跨 Tenant 结果泄露。
11. 切换 Tenant 不改变已有 Task 的执行归属。
12. 旧 Tenant 延迟响应不能污染新 Tenant。
13. 需要 Project 级严格保密的场景不会被错误宣称为已支持。
14. 1.5 历史数据归属不明时不得自动认领。
15. 已验证归属的历史数据能够通过受控方式建立新 Tenant 关联。
16. 归属冲突不会触发隐式迁移、删除或覆盖。

验收必须基于真实工程证据，产品合同本身不构成 Engineering PASS。

### 12. 首发非目标

1. 独立 Workspace IAM。
2. 完整 Project 级 ACL。
3. 复杂 Agency 多级组织授权。
4. 跨 Tenant 客户资产自动共享。
5. 跨 Tenant 后台任务并发。
6. 多设备业务视频同步。
7. 自动清理或重新归属全部 1.5 数据。
8. 完整跨客户 Creative Memory。
9. 复杂商业计费与自助注册。

上述能力不得因本决策而自动加入 1.6-B P0。

### 13. 架构及工程约束

本决策只冻结产品对象语义、层级、授权范围及数据归属原则。

不授权：

- 新建或修改数据库 Schema。
- 改造 FastAPI/SQLite 连接管理。
- 实施 Tenant 文件目录迁移。
- 修改现有 Task/Child/Attempt 状态模型。
- 修改 Frozen Architecture。
- 运行数据修复、Build、安装或发布。
- 修改 AGENTS、工程 Handoff 或生产 HOLD。

涉及既有 Frozen Architecture 的变更必须通过独立 ADR 和 Owner 审批。

### 14. 后续独立决策

- D16-004-B：Tenant Data Plane Isolation Contract。
- D16-004-C：Idle-only Switch & Runtime State Contract。
- D16-005：Control Plane、Membership & Device Activation。
- D16-006：Historical Creative Memory V1。

各决策应保持共同的 Tenant 身份语义。

### 15. 冻结条件

Product Owner 明确批准 D16-004-A v1.0 后，决策状态方可由 `PROPOSED_FOR_FREEZE` 更新为 `FROZEN`。

冻结 D16-004-A 不代表 D16-004-B、D16-004-C 或完整 Studio Workspace MVP 已完成设计与验收。

本决策不解除：

- `PHILIPPINES_INSTALL = HOLD`
- `LOCAL-P-R1 = FAIL/HOLD`
- `ARCHITECTURE_EXCEPTION = BLOCKED`
- `A1_ACTIVATION_BLOCKED = TRUE`
- `A2 = NOT_APPROVED`
- 其他未解除的工程及 Production HOLD。

**Freeze record:** Product Owner 于 2026-11-06 明确回复“批准冻结 D16-004-A v1.0”。因此，D16-004-A v1.0 的状态由 `PROPOSED_FOR_FREEZE` 更新为 **`FROZEN`**。

**Implementation authority:** **NOT_GRANTED**。本次产品冻结不授权任何工程操作，不解除 `PHILIPPINES_INSTALL = HOLD`、`LOCAL-P-R1 = FAIL/HOLD` 或其他尚未解除的工程 / Production HOLD。

---

## D16-004-B — Tenant Data Plane Isolation Contract

**Status:** FROZEN
**Version:** v1.0
**Date:** 2026-11-06
**Approved by:** Product Owner
**Approval date:** 2026-11-06
**Scope:** DopaMatrix 1.6-B — Studio Workspace MVP
**Depends On:** D16-001 / D16-002 / D16-003 / D16-004-A — FROZEN
**Related:** D16-004-C / D16-005 / D16-006
**Implementation Authority:** NOT_GRANTED

### 1. 决策目标

建立 DopaMatrix Studio 的 Tenant Data Plane 隔离合同，确保不同 Tenant 的数据库、素材、Output、执行状态、缓存、历史创意索引和备份恢复具有明确、可信且可验证的业务归属。

首版采用：

- 单 FastAPI 网关。
- 每 Tenant 独立 SQLite 目标模型。
- Tenant-scoped 业务数据及执行上下文。
- 受管素材和 Output 隔离。
- 应用级强制 Tenant 安全边界。
- 1.5 历史数据先验证归属，再进行受控映射。

本决策不开放未经验证的跨 Task 或跨 Tenant 后台并发。

### 2. Tenant 数据隔离总原则

1. Tenant 是唯一强制的客户级业务数据隔离主体。
2. 每个业务对象必须具有可信且可追溯的 Tenant 归属。
3. Tenant 归属不得仅由前端当前选择的 Workspace 决定。
4. 所有业务读取、写入和执行操作必须使用经过验证的 Tenant 上下文。
5. 无法确认 Tenant 身份、权限或资源归属时，必须 Fail Closed。
6. 数据隔离必须覆盖数据库、文件、Output、缓存、历史索引、异步请求、后台执行及备份恢复。
7. 不允许通过共享全局状态导致不同 Tenant 的业务数据混用。

### 3. SQLite Data Plane

#### B1 — Tenant-isolated SQLite

1. 1.6-B 以每 Tenant 独立 SQLite 作为正式目标模型。
2. 保留单 FastAPI 网关架构方向。
3. 不要求为每个 Tenant 启动独立 FastAPI 服务。
4. 数据库访问必须具有可信 Tenant 绑定。
5. 不允许通过无保护的全局 `db_path` 变更，使旧请求访问错误 Tenant 数据库。
6. 连接、事务及异步执行必须遵守 Tenant 归属。
7. 设备级最小注册信息可以独立管理，但不得因此建立混合客户业务数据空间。
8. 实际连接管理、连接池生命周期及数据库定位方式必须由后续工程审查决定。

现有 1.5 单 SQLite 连接管理与多 Tenant SQLite 目标之间的兼容性标记为 **NOT_VERIFIED**。

如果实现涉及 Frozen Architecture，必须先提交 ADR 并经 Owner 审批。

本决策不自动批准连接池重构、多网关部署或共享 SQLite 替代方案。

### 4. 文件与资产隔离

#### B2 — Managed Asset Ownership

1. 所有受管业务素材必须具有明确 Tenant 归属。
2. Project Owned 与 Tenant Shared Assets 必须保留适用的业务来源。
3. 新增生产 Output 必须具有明确 Tenant、Project 及执行身份关联。
4. 不同 Tenant 不得因为文件名称相同而覆盖或混淆产物。
5. 临时渲染文件、缩略图、音频缓存和 Delivery 文件同样必须具有受控归属。
6. 文件路径和数据空间定位不得依赖可由用户自由构造的显示名称。
7. 不得因 Tenant 切换改变已存在资产或 Output 的归属。
8. 清理、移动、删除与恢复操作必须受到 D16-002 数据安全合同约束。

不要求在 1.6-B 首发时强制复制全部历史素材或重构现有 DAM。

### 5. External Source Reference

外部原始素材引用是候选能力，不默认获得生产使用授权。

如允许外部引用，必须满足：

1. 引用具有明确 Tenant 与资产身份。
2. 实际访问路径必须经过安全解析与边界检查。
3. 必须防止目录穿越、符号链接、Junction 或路径重解析造成的越权访问。
4. 不允许通过引用读取其他 Tenant 的受管私有资产。
5. 生产使用的实际素材内容必须与 Import Gate 已验证版本一致。
6. 无法证明内容一致性或来源归属时，必须重新验证或停止正常生产。
7. 不允许仅凭同一物理文件路径或相同 SHA256 自动建立跨 Tenant 共享授权。

外部引用的具体技术实现、支持范围和安全验收必须独立审查。

在批准前，应限制于已验证安全的素材使用路径。

### 6. Task / Child / Attempt Execution Identity

1. Task 创建时绑定可信且不可变的 Tenant 身份。
2. Task 必须保留适用的 Project 业务归属。
3. Child 与 Attempt 必须具有可追溯的 Tenant、Task 和执行身份。
4. 执行进程、相关文件写入及 Output 不得脱离原始 Tenant。
5. Active Tenant 变化不能修改已有 Task 的归属。
6. 未安全终结的执行资源不得被其他 Tenant 复用。
7. UNKNOWN、孤儿执行和未明确归属的写入必须阻断受影响的危险操作。
8. 不允许为了支持 Tenant 隔离而直接重构已冻结的 Task/Child 状态模型。

执行身份的具体实现必须在遵守 D16-003 的前提下独立审查。

### 7. Cache / Session / Async State Isolation

1. 所有包含客户业务信息的缓存必须具有明确 Tenant 作用域。
2. Factory、QC、Assets、Story、Matrix 和 Historical Memory 查询不得跨 Tenant 错误返回。
3. 旧 Tenant 的延迟 API 响应不能污染新 Active Tenant。
4. 旧 Tenant 的事件订阅、缩略图加载及诊断状态必须受到身份和生命周期约束。
5. 不得通过 Tauri 本地调用或直接访问本地 API 绕过必要的 Tenant 授权检查。
6. 在 Tenant 身份无法确认时，不得将缓存结果当作有效业务数据。
7. 切换失败不得留下跨 Tenant 混合状态。

具体 Session Epoch、缓存失效、订阅关闭及切换事务由 D16-004-C 独立冻结。

### 8. 1.5 历史数据归属与兼容

#### B4 — Verified Legacy Ownership

已有 1.5 业务数据必须先确认可信归属，再受控纳入新的 Tenant Data Plane。

沿用 D16-004-A 的三类归属语义：

- VERIFIED
- UNRESOLVED
- CONFLICT

规则：

1. VERIFIED 数据可在批准的流程下建立 Tenant 关联。
2. UNRESOLVED 数据必须保留并限制业务访问。
3. CONFLICT 数据不得自动认领或迁移。
4. 不得根据当前 Operator、Active Tenant 或文件夹名称自动认领旧数据。
5. 不允许通过清空 1.5 SQLite、Ledger 或 Output 完成 Studio 升级。
6. 旧 Task、Execution、FP-001 和 Ledger 身份及业务语义不得被随意重定义。
7. 历史数据归属映射不得覆盖原始证据。
8. 实际迁移或数据映射必须通过独立工程审批及 D16-002 适用 Gate。

Software Upgrade 与 Tenant Claiming 是不同过程，不得未经批准合并成自动清库或隐式归属操作。

### 9. Historical Creative Memory Isolation

1. D16-006 Historical Creative Memory 归属于 Tenant Data Plane。
2. 历史 Planning FP、Render Identity、Historical Ledger 及其索引必须具有明确 Tenant 归属。
3. 同 Tenant 内可以支持授权范围内的跨 Project 检索。
4. 跨 Tenant 客户业务历史默认禁止共享。
5. 数据缺失、索引不完整或归属未知不得自动认定为没有历史记录。
6. 不允许为了建立历史索引改变现有 L1/L2 的冻结业务语义。
7. Historical Backfill 不得默认与生产渲染并发运行。
8. L3 的实施与启用仍须独立产品及工程授权。

### 10. Tenant Backup & Recovery

#### B6 — Tenant-scoped Recovery

1. 每个 Tenant 的恢复目标应定义为一致性的业务数据集。
2. 备份范围应覆盖适用的 SQLite、素材、Output、业务引用、配置和必要的恢复条件。
3. 不能仅因 SQLite 文件存在就声称具备恢复能力。
4. 恢复必须验证目标 Tenant 身份及数据归属。
5. 恢复 Tenant A 不得覆盖、重置或污染 Tenant B。
6. 恢复不得自动重新授予已撤销或过期的 Membership 和设备授权。
7. 恢复失败必须保护原始数据并保留必要诊断证据。
8. 备份、恢复与升级必须遵守 D16-002 的数据保护及 Release Gate。
9. 不允许将二进制回滚直接等同于数据库或业务数据回滚。

本决策不批准立即开发独立备份系统或执行任何真实数据恢复。

### 11. 本地安全范围

#### B3 — Application-level Tenant Isolation

1. 1.6-B 首发必须实现应用级强制 Tenant 隔离。
2. Studio UI、FastAPI、业务数据访问、执行及缓存必须共同遵守授权边界。
3. 不允许仅靠前端菜单隐藏实现隔离。
4. 不允许通过本地 API 或应用内部调用绕过 Tenant 身份约束。
5. 不宣称能够抵御拥有同一 Windows 用户直接文件访问权限的恶意人员或系统管理员。
6. 企业级文件加密、操作系统账户级安全和独立密钥隔离不列入本次首发 P0。
7. 不因上述安全范围限制而放宽应用内部的跨 Tenant 访问保护。

### 12. 最低产品验收矩阵

1. Tenant A 和 Tenant B 具有独立业务数据库。
2. A 的业务操作不能读取或修改 B 的数据库。
3. 旧请求不能因 Active Tenant 改变而访问错误数据库。
4. 不同 Tenant 的受管素材和 Output 不会串用。
5. 相同文件名不会导致跨 Tenant 覆盖。
6. 外部素材引用无法绕过归属和内容一致性检查。
7. Task/Child/Attempt 具有可信且稳定的 Tenant 归属。
8. A 的未安全终结执行不能被 B 错误复用。
9. A 的历史事件、缓存或异步响应不能污染 B。
10. 未授权 Operator 无法通过 UI 或本地业务接口访问其他 Tenant。
11. Tenant Shared Assets 与 Project Owned Assets 保留明确来源。
12. Tenant B 的 Historical Memory 查询不返回 A 的私有历史数据。
13. 1.5 数据归属不明时不会自动认领。
14. 1.5 旧数据在升级期间得到保护，不被清库重建。
15. 对 Tenant A 的备份及恢复不会修改 Tenant B。
16. 恢复后业务数据引用、授权边界和必要生产资产具有一致性。

验收必须绑定实际候选版本、测试环境及可追溯证据。

产品决策冻结不等于上述场景已通过工程验收。

### 13. 实施依赖与审批边界

后续工程实施前必须完成适用的只读审查，至少确认：

- 现有 FastAPI 单网关与 SQLite 连接管理结构。
- 实际 RuntimePaths 与业务文件归属。
- Import、Factory、Output、QC 的读写边界。
- Task/Child/Attempt 身份与后台执行生命周期。
- 缓存、事件和异步查询的 Tenant 作用域。
- 1.5 历史数据归属证据。
- 现有 Backup / Restore / Upgrade 路径。

任何无法从真实源码和工程证据确认的事实必须标记 **NOT_VERIFIED**。

不得因为产品合同需要实现多 Tenant，就自动批准：

- 新增多个 FastAPI 网关。
- 重构 SQLite 连接池。
- 修改 Frozen Task/Child 状态机。
- 迁移或清理真实生产目录。
- 改写历史 FP-001 / Ledger。
- 执行 Build、Commit、安装或发布。

如确需调整 Frozen Architecture，必须先提交独立 ADR 并获得 Owner 授权。

### 14. 后续独立决策

- D16-004-C：Idle-only Switch & Runtime State Contract。
- D16-005：Control Plane、Membership & Device Activation。
- D16-006：Historical Creative Memory V1。

上述决策必须遵守本合同的 Tenant 身份与数据隔离原则。

### 15. 冻结条件

Product Owner 明确批准 D16-004-B v1.0 后，状态方可由 `PROPOSED_FOR_FREEZE` 更新为 `FROZEN`。

冻结 D16-004-B 不代表 D16-004-C 或完整 Studio Workspace MVP 已通过验收。

本决策不解除：

- `PHILIPPINES_INSTALL = HOLD`
- `LOCAL-P-R1 = FAIL/HOLD`
- `ARCHITECTURE_EXCEPTION = BLOCKED`
- `A1_ACTIVATION_BLOCKED = TRUE`
- `A2 = NOT_APPROVED`
- Production Lifecycle Receipt / Ownership / Runtime Guard / Q2 Final 等其他现存 HOLD

**Freeze record:** Product Owner 于 2026-11-06 明确回复“批准冻结 D16-004-B v1.0”。因此，D16-004-B v1.0 的状态由 `PROPOSED_FOR_FREEZE` 更新为 **`FROZEN`**。

**Implementation authority:** **NOT_GRANTED**。本次产品冻结不授权任何工程操作，不解除 `PHILIPPINES_INSTALL = HOLD`、`LOCAL-P-R1 = FAIL/HOLD` 或其他尚未解除的工程 / Production HOLD。

---

## D16-004-C — Idle-only Switch & Runtime State Contract

**Status:** FROZEN
**Version:** v1.0
**Date:** 2026-11-06
**Approved by:** Product Owner
**Approval date:** 2026-11-06
**Scope:** DopaMatrix 1.6-B Studio Workspace MVP
**Depends On:** D16-001 / D16-002 / D16-003 / D16-004-A / D16-004-B — FROZEN
**Related:** D16-005 / D16-006
**Implementation Authority:** NOT_GRANTED

### 1. 决策目标

在一个 Operator、一个 Windows 用户、一个 Tauri 会话和一个 FastAPI 网关的运行环境下，建立安全的 Active Tenant 切换合同。

1.6-B 首版采用 **Idle-only Switch**。

Tenant 切换必须保证旧租户执行已安全静止、目标租户授权有效、数据上下文不会混合、切换失败能够安全停止或恢复。

不得借此开放跨 Task 或跨 Tenant 后台并发。

### 2. Global Execution Quiescence

Global Execution Quiescence 指所有相关生产执行及可能造成租户数据冲突的操作已经达到可验证的安全静止状态。

切换检查必须覆盖适用的：

- Task / Child / Attempt 执行状态。
- FFmpeg、Playwright 等相关子进程生命周期。
- 待执行、取消中和收尾中的生产任务。
- Output、临时文件及关键业务数据写入。
- 可能影响数据一致性的备份、恢复、迁移或维护操作。
- UNKNOWN、孤儿执行及无法确认归属的危险资源。

不得仅依据前端 Completed 或单个 Task 状态判断 Idle。

安全终结的失败任务不必永久阻断切换。

已持久化、等待人工 QC 或 Delivery 的业务记录，在不存在其他危险执行时，不构成运行时繁忙。

### 3. Switch Barrier

Tenant 切换必须建立可信的运行时准入屏障。

要求：

1. 开始切换时，先阻止新的冲突性生产操作进入。
2. 在屏障有效期间检查 Global Execution Quiescence。
3. 必须避免检查通过与提交切换之间出现新的生产任务。
4. 屏障必须覆盖所有适用的任务创建及后台执行入口。
5. 前端按钮禁用不能替代后端运行时约束。
6. 未通过切换 Gate 时，不得进入目标 Tenant。
7. 切换成功后，只有目标 Tenant 上下文通过验证，才能恢复相应操作准入。
8. 失败时，屏障解除或恢复必须经过安全状态验证。

具体锁、Epoch、准入控制及事务实现由后续工程审查决定。

### 4. Authorization Gate

切换目标 Tenant 前必须确认：

1. 当前 Operator 身份有效。
2. Operator 对目标 Tenant 具有适用的 Membership。
3. 当前设备具有适用的授权。
4. 目标 Tenant 的本地数据空间具备安全访问条件。
5. 授权校验失败时不得进入目标 Tenant。

离线授权、撤销、失效时间和重新激活策略由 D16-005 独立冻结。

不得因设备已经激活就默认 Operator 可以访问全部本地 Tenant。

### 5. Context Transition

切换必须保证当前有效租户上下文具有唯一、可信的身份。

在旧 Tenant 上下文退出和新 Tenant 上下文生效期间，必须防止：

- 旧数据库连接写入目标 Tenant 数据库。
- 旧 Task 或 Child 改变所属 Tenant。
- 旧缓存结果显示在新 Workspace。
- 旧 API 异步响应污染新 Tenant。
- 旧事件订阅继续驱动新 Workspace 状态。
- 旧素材、Output、QC 或 Historical Memory 关联到新 Tenant。
- 切换中的未验证上下文接受生产操作。

所有业务访问必须遵守 D16-004-B 的 Tenant 数据隔离合同。

只有在目标上下文通过必要校验后，才能将切换认定为成功。

不允许同时出现两个 Active Tenant。

### 6. Human QC 与未完成业务状态

已安全终结的生产任务，即使存在未完成的人工 QC、交付确认或业务审核，也允许在满足其他安全条件时切换 Tenant。

要求：

1. QC 和 Delivery 状态必须保留原 Tenant 与 Project 归属。
2. 切换不得自动将待审核视频标记为通过或失败。
3. 切换不得删除未交付的合格 Output。
4. 已持久化的待审核业务可以在重新进入原 Tenant 后继续处理。
5. 如果存在尚未保存的编辑操作，系统应提供明确提示或安全保存机制，不能静默丢弃用户修改。

Human QC 是业务完成条件，不自动等同运行时执行锁。

### 7. Switch Failure & Recovery

当切换失败时：

1. 不得进入混合 Tenant 状态。
2. 如原 Tenant 的授权、数据库访问和运行时上下文仍可证明安全，可以恢复原 Tenant。
3. 如无法证明原 Tenant 安全，必须进入禁止生产的 Locked State。
4. Locked State 不得触发自动清库、删除 Output 或重新归属资产。
5. 不允许通过前端页面回退代替后端安全恢复。
6. 不得自动强制结束未知生产进程。
7. 必须保留可用于故障定位的必要状态与诊断证据。
8. 解锁和恢复必须经过适用的安全验证。

不得提供绕过关键安全检查的普通 Operator 强制切换入口。

### 8. Crash / Restart Safety

应用或后端在切换期间异常退出后：

1. 不得直接信任持久化的旧 Active Tenant 标记。
2. 重启必须重新确认授权与必要执行资源状态。
3. 必须识别可能遗留的执行进程、文件写入及 UNKNOWN 资源。
4. 不能通过重启绕过此前未解决的运行时冲突。
5. 无法确认安全时应限制生产操作。
6. 已有真实生产数据不得因重启恢复流程受到破坏。

重启恢复不得被视为重新授权生产环境或解除现存工程 HOLD。

### 9. 切换操作与生产执行的关系

1. 不允许在切换时自动取消正常运行的 Task。
2. 不允许自动 Kill 正在使用的 FFmpeg / Playwright 子进程。
3. 不允许将 Tenant A 尚未终结的任务迁移到 Tenant B。
4. 不允许借助 Tenant 切换重新执行失败 Task。
5. 不允许未安全终结的资源跨 Tenant 复用。
6. 不开放跨 Tenant 后台渲染。
7. 不开放未经验证的跨 Task 并发。

如需停止任务，应使用独立、经验证的执行停止与恢复流程。

### 10. 最低验收矩阵

D16-004-C 至少覆盖：

1. 无任务、无危险资源时正常切换 Tenant。
2. Batch2 任意 Child 运行时拒绝切换。
3. Task 排队或取消过程中拒绝危险切换。
4. Task 失败但安全终结后允许切换。
5. Task 完成但子进程残留时拒绝切换。
6. UNKNOWN 或孤儿执行时拒绝切换。
7. 检查 Idle 与提交切换之间的新 Task 请求不能穿透屏障。
8. 目标 Tenant 授权失效时不能切换。
9. 目标 SQLite 无法安全访问时不能进入目标 Tenant。
10. Tenant A 的旧 API 响应不能更新 Tenant B 的业务页面。
11. Tenant A 的缓存、事件、历史索引不能污染 B。
12. 切换失败时能够安全恢复 A，或进入 Locked State。
13. Locked State 不能继续发起危险生产操作。
14. 切换过程中崩溃，重启后不会直接信任旧 Active Tenant。
15. Batch2 安全结束但人工 QC 未完成时可以切换，并保留待审核状态。
16. 切换过程中不删除、不覆盖已有客户产物。
17. 连续 A→B→A 切换不会产生跨 Tenant 数据和执行身份混用。
18. 不满足 Gate 时，不允许通过直接调用本地 API 绕过限制。

每项验收应绑定实际候选代码、测试条件、运行状态及可追溯证据。

产品合同冻结不代表工程验收已经通过。

### 11. 首发非目标

1. 跨 Tenant 后台任务同时执行。
2. Tenant 切换时自动迁移正在运行的任务。
3. 自动 Kill 所有旧租户进程。
4. 可跳过安全检查的强制切换。
5. 全面分布式调度系统。
6. 多设备之间的实时运行时同步。
7. 完整企业级终端防恶意文件访问机制。

上述能力不得因 D16-004-C 冻结而自动加入 1.6-B P0。

### 12. 工程与架构约束

本决策只冻结产品切换行为、安全状态和验收边界。

不直接授权：

- 修改 Tauri/FastAPI/SQLite 实现。
- 重构任务调度器或 Task/Child 状态机。
- 增加多网关或多进程部署。
- 修改 Frozen Architecture。
- 迁移、删除或修复真实客户数据。
- 执行 Build、Commit、安装或发布。
- 解除原有 Production HOLD。

任何涉及 Frozen Architecture 的必要改动，必须单独提交 ADR 并经 Owner 审批。

实际工程能力必须根据最新权威工程 Handoff 与源码证据核验，未经验证的能力标记为 NOT_VERIFIED。

### 13. 相关决策

本合同必须遵守：

- D16-001：双里程碑与 Idle-only Switch 原则。
- D16-002：数据保护、升级和发布安全。
- D16-003：有界 Batch2、人工 QC 与安全补救。
- D16-004-A：Tenant 身份与数据归属。
- D16-004-B：Tenant Data Plane Isolation。

D16-005 进一步冻结 Membership、设备授权、离线及撤销机制。

D16-006 Historical Creative Memory 必须遵守本合同的租户运行时隔离边界。

### 14. 冻结条件

Product Owner 明确批准 D16-004-C v1.0 后，状态方可由 PROPOSED_FOR_FREEZE 更新为 FROZEN。

冻结 D16-004-C 不代表整个 Studio Workspace MVP 已完成工程设计或验收。

本决策不解除：

- PHILIPPINES_INSTALL = HOLD
- LOCAL-P-R1 = FAIL/HOLD
- ARCHITECTURE_EXCEPTION = BLOCKED
- A1_ACTIVATION_BLOCKED = TRUE
- A2 = NOT_APPROVED
- Production Lifecycle Receipt / Ownership / Runtime Guard / Q2 Final 等其他现存 HOLD

**Freeze record:** Product Owner 于 2026-11-06 明确回复“批准冻结 D16-004-C v1.0”。因此，D16-004-C v1.0 的状态由 `PROPOSED_FOR_FREEZE` 更新为 **`FROZEN`**。

**Implementation authority:** **NOT_GRANTED**。本次产品冻结不授权任何工程操作，不解除 `PHILIPPINES_INSTALL = HOLD`、`LOCAL-P-R1 = FAIL/HOLD` 或其他尚未解除的工程 / Production HOLD。
---

## D16-005 — Control Plane, Membership & Device Activation Contract

**Status:** FROZEN
**Version:** v1.0
**Date:** 2026-11-06
**Approved by:** Product Owner
**Approval date:** 2026-11-06
**Scope:** DopaMatrix 1.6-B — Studio Workspace MVP
**Depends On:** D16-001 / D16-002 / D16-003 / D16-004-A / D16-004-B / D16-004-C — FROZEN
**Related:** D16-006 — Historical Creative Memory V1
**Implementation Authority:** NOT_GRANTED

### 1. 决策目标

建立 DopaMatrix Studio 最小可用的云端 Control Plane，实现客户开通、Operator 身份与 Membership、Installation/Device 授权、Tenant 使用资格、受控本地初始化及安全撤销。

Control Plane 负责授权和客户生命周期；Local Data Plane 负责真实生产及客户业务数据。

首版以少量种子客户、菲律宾代运营团队为主要使用场景。

不建设完整商业 SaaS IAM、CRM、计费或设备 Fleet Management 平台。

### 2. 最小对象模型

首版包含以下逻辑对象：

- **Customer**：客户商业管理与归属。
- **Tenant**：客户级数据隔离及授权主体。
- **Operator**：Studio 业务人员身份。
- **Membership**：Operator 对 Tenant 的访问授权。
- **Installation**：本地 Studio 安装实例身份。
- **Device Authorization**：Installation 对目标 Tenant 的使用授权。
- **Tenant Entitlement**：Tenant 的最小使用资格与状态。
- **Audit Record**：关键授权与生命周期事件记录。

沿用 D16-004-A 已冻结的 Customer / Tenant / Workspace / Project 对象语义。

上述对象为产品逻辑模型，不要求立即建立同名数据库表。

### 3. Tenant Provision

1. 正式 Tenant 必须经平台管理员审核并明确创建。
2. 官网 Lead Intake 不自动创建正式 Tenant。
3. Customer、Tenant、初始 Membership、Installation 授权及本地初始化必须具备可信关联。
4. 不允许未经授权的普通 Operator 创建正式 Tenant。
5. 本地 Provision 必须具有明确操作权限及安全边界。
6. 不得简单将现有 CLI 或 PowerShell Provision 包装为可执行任意高权限操作的前端按钮。
7. 初始化失败或中断不得清库、覆盖 Output 或隐式认领历史客户数据。
8. 旧数据归属必须遵守 D16-004-A / B，并通过适用的 D16-002 Gate。

种子期允许管理员人工完成开通和审核，不要求客户自助建户。

### 4. Operator & Membership

1. Operator 是业务身份，不等同于 Windows 用户。
2. 一个 Operator 可以通过多个 Membership 访问不同 Tenant。
3. Membership 必须绑定 Operator、Tenant、授权范围、有效状态及必要的生命周期信息。
4. 种子期采用最小角色模型：平台授权管理员与日常 Operator。
5. 平台管理员的管理权限不自动等于读取所有客户生产数据的业务权限。
6. 普通 Operator 不得自行扩大 Membership。
7. 不在本期建设完整 Project 级 ACL。
8. 当前 Operator 退出、身份变化或授权失效时，旧业务会话不得继续作为有效身份使用。
9. Membership 授予、变更及撤销必须保留必要审计证据。

具体后台管理界面和角色权限颗粒度由后续实施设计确定。

### 5. Installation / Device Authorization

1. Device 与 Installation 的业务语义必须能够区分。
2. Installation 是本地软件的主要授权实例身份。
3. 一个 Installation 可以经批准获得多个 Tenant 的使用授权。
4. Installation 授权不替代 Operator Membership。
5. 首次激活必须在线完成可信验证。
6. 不允许仅通过复制配置文件或替换显示设备编号取得新 Installation 授权。
7. 重新安装、设备更换、设备撤销及重新激活必须具有受控生命周期。
8. 无法验证 Installation 身份或授权时，不得开放受保护业务操作。
9. 设备授权撤销不得自动清理客户业务数据库、素材、Output 或备份。

具体设备密钥、操作系统安全存储及凭据轮换方案另行审查。

不得在本产品决策中宣称已具备抵御本地管理员攻击或设备克隆的完整硬件级安全能力。

### 6. Tenant Entitlement

Tenant 使用资格必须明确且可验证。

1. Tenant 应具有可判断的有效、暂停或失效状态。
2. 业务访问必须满足相应使用资格。
3. 首发可由平台管理员人工管理状态。
4. 不要求完整自动计费、支付、订阅续费或复杂配额系统。
5. Tenant 状态变更不得自动删除客户生产数据。

Entitlement 的商业运营细则不应改变 Tenant 数据归属。

### 7. Authorization Gate

受保护的业务操作必须同时满足：

- 当前 Operator 身份有效。
- 目标 Tenant Membership 有效。
- Installation 对目标 Tenant 具有有效授权。
- Tenant Entitlement 有效。
- 适用的本地运行时及数据安全 Gate 已通过。

在线状态下必须使用足够新鲜、可信的授权结果。

离线状态下仅允许使用满足本决策第 8 章的受限租约。

授权不明确、过期、冲突或不可验证时必须 Fail Closed。

前端 Tenant Selector、Windows 登录状态或本地旧配置文件不得单独构成授权依据。

授权通过不代表 Production Gate 通过。

### 8. Offline Authorization Lease

#### 8.1 首发策略

1. 首次登录、首次 Installation 激活和首次获取 Tenant 授权必须在线。
2. 首发允许当前已授权 Active Tenant 在有效离线租约内执行受限的本地业务操作。
3. 不允许离线切换至其他 Tenant。
4. 不允许离线切换 Operator 并继承原有授权。
5. 不允许离线新增 Membership、设备授权或 Tenant Entitlement。

#### 8.2 租约有效期

1. 菲律宾种子期采用最长 **8 小时**作为首发离线租约候选上限。
2. 租约从最近一次成功的在线授权校验及有效签发时刻开始计时。
3. 租约必须具有明确的签发与到期语义。
4. 断网不重新开始计时。
5. 重启、休眠、程序关闭或普通本地活动不得延长租约。
6. 只能通过新的有效在线授权校验签发新租约。
7. 可以根据运营和安全风险采用更短有效期，不得未经 Owner 批准突破 8 小时上限。
8. 本策略不承诺 8 小时内一定可以完成任意长度的生产任务。

8 小时作为产品候选策略，实际采用前必须通过离线与时钟安全验收。

#### 8.3 租约作用域

离线授权必须绑定：

- Operator。
- Installation。
- Tenant。
- 必要的权限范围。
- 有效期限及授权来源。

租约不允许转移至其他 Operator、Installation 或 Tenant 使用。

离线租约不是永久使用许可证，也不能替代用户身份会话的有效性。

#### 8.4 时间安全

1. 不允许通过修改 Windows 系统时间延长离线授权。
2. 不允许使用可自行刷新的本地时间戳作为唯一授权依据。
3. 应采用可验证的时间与租约有效性约束。
4. 当系统无法证明有效期仍然可信时，必须 Fail Closed。
5. 不承诺抵御已控制本地操作系统的高权限恶意人员。

具体可信时间、凭据验证及重启恢复机制由后续工程审查决定。

### 9. Offline Operation Scope

有效离线租约下，可以在已授权的当前 Tenant 中进行受限本地业务操作，包括：

- 已授权业务数据访问。
- Story / Matrix 人工编排。
- 满足现有工程和生产 Gate 的有界本地生产。
- Output 技术检查。
- 人工 QC。

首发不开放：

- 离线 Tenant / Operator 切换。
- 离线新增或扩大授权。
- 离线设备重新激活。
- 依赖云端确认的客户对外交付或发布授权。

离线生产不能绕过 `PHILIPPINES_INSTALL = HOLD` 或其他现存生产限制。

### 10. Revocation & Expiration

#### 10.1 在线撤销

当客户端可信地获知 Operator Membership、Installation Authorization 或 Tenant Entitlement 已失效时，必须立即拒绝新受保护操作的准入。

不得在已知撤销后继续使用旧租约启动新任务。

#### 10.2 离线撤销

完全离线时无法保证实时获知云端权限撤销。

已签发租约可能在有效期内继续提供受限授权。

该延迟风险必须通过有限有效期和受控权限范围进行约束。

产品不得承诺离线状态下云端撤销立即生效。

#### 10.3 租约到期

租约到期或可信性失效后：

1. 禁止启动新的 Task、Child 和其他受保护生产操作。
2. 禁止新的敏感业务读取、编辑提交和对外交付。
3. 允许显示必要的非敏感授权、故障及恢复信息。
4. 不得通过重新启动应用自动恢复过期授权。
5. 网络恢复后必须重新验证 Operator、Installation 与 Tenant 状态。
6. 不得自动删除或重新归属客户业务资产。

### 11. Running Task Safety

当租约到期或授权被撤销时，已经运行的 Task 必须遵守安全生命周期要求。

1. 禁止新任务和新的未获授权执行准入。
2. 禁止整个失败 Task 自动重提。
3. 不允许未经验证地强制 Kill FFmpeg、Playwright 或其他执行进程。
4. 应优先采用已经验证的安全暂停、停止或终结机制。
5. 对尚未安全终结的 Child 和资源必须保留可追溯状态。
6. 必要的安全收尾不应被当作继续新增生产权限。
7. 产出不得在未重新确认授权与交付条件前自动作为合格交付。
8. 不允许通过持有一个长时间运行的 Task 无限延续过期授权的业务生产能力。
9. 具体运行中执行处理的边界和时限，必须经独立工程审查和验收确定。

本合同不要求 1.6-B 重建已有 Task/Child 生命周期系统。

### 12. Studio Session & Switching

1. 同一 Studio 会话任一时刻只有一个 Active Tenant。
2. Tenant 切换遵守 D16-004-C Idle-only Switch。
3. Operator 登出或身份切换必须使原业务会话失效。
4. 不允许旧 Operator 的缓存、事件或请求污染新会话。
5. 首发禁止离线 Tenant 切换。
6. 崩溃或重启后不能仅凭保存的 Active Tenant 标记恢复授权。
7. 若现有有效租约、身份、时间和执行状态均能安全验证，可在获批范围内恢复当前 Tenant；否则进入受限 Locked 状态。
8. 不开放跨 Tenant 后台任务并发。

### 13. Audit & Security

关键审计事件包括：

- Customer / Tenant 开通。
- Membership 授予、变更和撤销。
- Installation 激活、撤销及重新激活。
- Tenant Entitlement 变更。
- 关键授权成功与失败。
- 离线租约签发、到期及重新验证。
- 必要的安全锁定与恢复结果。

离线产生的必要审计记录应在本地受控保存，并在恢复网络后按批准策略同步。

审计记录不得包含不必要的客户视频、完整业务内容、访问密钥或敏感凭据。

审计结果必须可追溯，但本决策不宣称具备企业级防篡改审计能力。

### 14. Data Protection

1. Control Plane 不要求上传全部本地生产 SQLite、剧集素材或 Output。
2. Operator 或设备撤权不得隐式删除客户数据。
3. 恢复旧数据库不得恢复已经撤销的云端权限。
4. Tenant 初始化和数据映射必须遵守 D16-002、D16-004-A、D16-004-B。
5. 不允许利用授权更新执行未经批准的数据迁移、清理或覆盖。
6. 离线租约过期不得导致客户原始数据丢失。
7. 备份与恢复能力必须独立通过适用 Gate。

### 15. 首发验收矩阵

至少验证：

1. 平台管理员创建 Customer / Tenant。
2. 普通 Operator 无法自行创建正式 Tenant。
3. 一个 Operator 获得多个 Tenant Membership。
4. 未授权 Operator 被拒绝访问其他 Tenant。
5. 已激活设备不能替代 Operator Membership。
6. 已授权 Operator 不能绕过 Installation 授权。
7. 不同 Operator 共用 Windows 用户时业务会话隔离。
8. 不同 Installation 不因复制配置而自动获得授权。
9. Tenant Entitlement 失效时拒绝新生产。
10. 首次登录与激活必须在线。
11. 当前 Tenant 有效租约内允许获准离线操作。
12. 离线 Tenant / Operator 切换被拒绝。
13. 租约从签发时刻计时，断网不重置。
14. 8 小时到期后拒绝新受保护操作。
15. 重启、休眠和时钟回退不能无授权延长有效期。
16. 在线获知 Membership 撤销后阻断新操作。
17. 离线撤销风险不超过已签发租约的有效期边界。
18. Batch2 执行期间租约到期时不进行危险强制终止或自动重提。
19. 授权失效的产物不会自动获得交付资格。
20. 网络恢复后重新核验 Operator、Installation 和 Tenant。
21. 崩溃恢复不能绕过授权或运行时安全 Gate。
22. 设备撤销或重装不会隐式清除历史业务数据。
23. 无法验证时间、授权或运行状态时 Fail Closed。
24. 离线审计与在线同步不泄露不必要的客户业务数据。

实际验收必须绑定候选版本、设备环境、测试条件及可追溯证据。

产品决策冻结不构成工程 PASS。

### 16. 首发非目标

- 完整 SaaS IAM / CRM。
- 客户自助创建正式 Tenant。
- 复杂计费与自动支付。
- 完整 Project ACL。
- 多设备实时同步业务视频。
- 永久离线使用许可证。
- 离线跨 Tenant 切换。
- 跨 Tenant 后台渲染。
- 完整设备 Fleet Management。
- 企业级终端管理员防攻击能力。
- 全自动任务撤权恢复和无感续跑。

上述能力不自动加入 1.6-B P0。

### 17. 架构与工程权限

本决策仅冻结 Control Plane、Membership、设备授权、离线租约及撤销的产品目标与安全边界。

不批准：

- 修改现有 FastAPI、Tauri 或 SQLite 代码。
- 实施身份服务或设备密钥系统。
- 修改现有 Provision 或安装器。
- 重建 Task/Child 状态机。
- 执行数据库迁移、备份恢复或真实数据操作。
- Build、Commit、Push、Tag、安装或生产发布。
- 修改 Frozen Architecture 或绕过既有 Closed Phases。

涉及 Frozen Architecture 的实施变更须独立提交 ADR 并经 Owner 审批。

任何当前工程能力均需根据权威工程 Handoff 及真实源码核验，未经核验标记为 NOT_VERIFIED。

### 18. 既有 HOLD

本决策不解除：

- `PHILIPPINES_INSTALL = HOLD`
- `LOCAL-P-R1 = FAIL/HOLD`
- `ARCHITECTURE_EXCEPTION = BLOCKED`
- `A1_ACTIVATION_BLOCKED = TRUE`
- `A2 = NOT_APPROVED`
- Production Lifecycle Receipt / Ownership / Runtime Guard / Q2 Final 等现存 HOLD

云端授权通过、设备激活完成或离线租约有效，均不构成生产发布批准。

### 19. 冻结条件

由 Product Owner 明确批准 D16-005 v1.0 后，状态方可由 `PROPOSED_FOR_FREEZE` 更新为 `FROZEN`。

冻结后，本决策成为 1.6-B Studio Control Plane 的正式产品与验收合同，但不授予任何工程实施权限。

**Freeze record:** Product Owner 于 2026-11-06 明确回复“批准冻结 D16-005 v1.0”。因此，D16-005 v1.0 的状态由 `PROPOSED_FOR_FREEZE` 更新为 **`FROZEN`**。

**Implementation authority:** **NOT_GRANTED**。本次产品冻结不授权任何工程操作，不解除 `PHILIPPINES_INSTALL = HOLD`、`LOCAL-P-R1 = FAIL/HOLD` 或其他尚未解除的工程 / Production HOLD。

---

## D16-006 — Historical Creative Memory V1 & Novelty Policy Contract

**Status:** FROZEN
**Version:** v1.0
**Date:** 2026-11-06
**Approved by:** Product Owner
**Approval date:** 2026-11-06
**Scope:** DopaMatrix 1.6 P1 — Historical Creative Memory V1
**Depends On:** D16-001 / D16-002 / D16-003 / D16-004-A / D16-004-B / D16-004-C / D16-005 — FROZEN
**Implementation Authority:** NOT_GRANTED

### 1. 决策目标

为 DopaMatrix 建立可信的 Historical Creative Memory V1，实现历史创意精准检索、实际成品身份识别及受控复用建议。

本能力必须回答：

1. 这个 Creative Planning Identity 过去是否使用过？
2. 过去对应哪些 Task、Execution 与实际成品？
3. 历史证据是否完整、可信并属于当前授权 Tenant？
4. 当前创意应该提示重复、允许复用，还是继续开展新实验？

Historical Creative Memory 不等于简单的永久去重系统。

V1 不默认对历史重复执行硬阻断。

### 2. 三层重复治理边界

DopaMatrix 继续保留三个独立层次：

#### L1 — Same-batch Uniqueness

同一 Batch 内 FP-001 完整规划身份的唯一性。

保留已冻结的 Hard Invariant，不允许 Historical Policy 覆盖或削弱。

#### L2 — Reservation Authority

负责活跃任务之间的短生命周期规划占用和并发协调。

保留现有 Reservation、Readiness、Controlled Canary 及相关冻结语义。

L3 不重构或接管 Reservation Authority。

#### L3 — Historical Creative Memory

负责查询历史生产证据、判断重复类型，并向 Planner 和 Operator 提供受控复用建议。

历史重复不自动等于当前生产冲突。

L3 不授权开放未经验证的跨 Task 并发。

### 3. V1 功能范围

#### M0 — Historical Provenance & Forward Compatibility

强制数据兼容和证据可信合同。

#### M1 — Historical Exact Planning

基于现有 FP-001 与 Ledger，识别相同规划身份的历史记录。

#### M2 — Exact Render Identity

为经验证的实际输出建立 SHA256 等精确文件身份及来源关联。

#### M3 — Historical Advisory & Human Reuse

向 Operator 提供历史匹配、证据覆盖及受控复用提示。

#### M4 — Perceptual Similarity

FFmpeg 抽帧和 temporal pHash 属于 1.6 P1 扩展候选，不作为 V1 核心验收的默认强制项。

#### M5 — Creative Memory Intelligence

CLIP/SigLIP、向量检索、Attribution-aware Memory 及高级 REUSE/MUTATE/AVOID 策略原则上后置至 1.7+。

### 4. M0 — 历史数据血统与前向兼容

#### M0-A — Immutable Historical Truth

1. 保留原有 Task、Child、Execution、FP-001 和 Ledger 的业务身份与语义。
2. L3 索引是对历史事实的派生证据。
3. 不允许通过重写已有生产事实满足历史检索要求。
4. 不允许为了实现 L3 重建 Reservation Authority。
5. 任何无法从既有数据证明的历史关系不得自动推断为可信事实。

#### M0-B — Missing Historical Assets

1. 已有 Ledger 证据不因视频文件丢失而自动删除。
2. 历史成品缺失时应明确其不可用状态。
3. 索引不完整不能被解释为从未生产。
4. 缺失历史身份或来源时不得虚构关联。

#### M0-C — Controlled Backfill

1. Historical Backfill 与 Schema Migration 分离。
2. 首发优先采用受控维护窗口或经过批准的非冲突执行方式。
3. 不默认允许 Backfill 与生产渲染并发运行。
4. Backfill 必须可记录进度、安全重入，并保留失败诊断。
5. Backfill 失败不得修改、删除或覆盖原始 Output 和 Ledger。

#### M0-D — V1 Scope

V1 核心交付范围为 Historical Exact Planning、Exact Render Identity 和 Historical Advisory。

pHash 是可独立评估的扩展候选。

Historical ENFORCE 不纳入首发默认能力。

### 5. Historical Provenance Contract

在数据证据允许的范围内，历史记录应具备以下可追溯关系：

- Tenant Identity。
- Project Identity。
- Task / Child Identity。
- Execution / Attempt Identity。
- FP-001 Identity 及适用语义版本。
- Historical Ledger Evidence。
- Artifact / Output Reference。
- Production Time 与必要状态证据。

具体字段与关系结构必须以真实工程审查结果为依据。

本决策不要求直接创建同名数据库字段或修改既有状态机。

### 6. Historical Ownership & Coverage

历史数据必须分别管理：

#### Ownership

沿用 D16-004-A：

- VERIFIED
- UNRESOLVED
- CONFLICT

#### Index Coverage

应能够区分：

- NOT_INDEXED
- INDEXED
- INDEX_ERROR
- SOURCE_UNAVAILABLE

上述为产品逻辑状态，不强制新增同名数据库枚举。

历史索引覆盖情况与 Tenant 归属必须分开管理。

**No Match 不等于 Proven Novelty。**

历史检索必须能够说明适用的查询范围、索引覆盖情况及未覆盖的限制，不得以不完整检索结果宣称创意绝对全新。

### 7. M1 — Historical Exact Planning

1. 通过兼容的 FP-001 规划身份检索历史记录。
2. 必须区分 PLANNED、RENDERED、FAILED 等已有 Ledger 证据语义。
3. 不能将仅 PLANNED 的记录误认为已有实际成品。
4. 不能将 FAILED 自动解释为成功生产。
5. 相同 FP-001 不等于实际 Output 字节完全一致。
6. 不兼容的指纹语义或版本不得无依据直接比较。
7. 历史记录应关联适用的 Task、时间和业务来源。
8. 检索必须遵守 Tenant 授权和数据隔离。
9. V1 仅提供历史证据和建议，不默认执行 Hard Reject。

具体历史查询接口与索引方式后续审查。

### 8. M2 — Exact Render Identity

1. 以经确认完成、稳定且具有可信来源的成品作为精确身份索引对象。
2. SHA256 用于识别文件字节一致性。
3. SHA256 必须关联 Artifact/Output 身份及原执行来源。
4. 同一 FP-001 产生的不同文件不能直接视为字节相同。
5. 相同 SHA256 不能自动证明素材使用权相同。
6. 相同 SHA256 的不同 Tenant 资产不能自动合并客户数据归属。
7. 原始文件不可用时必须明确索引证据限制。
8. SHA256 不能替代视觉感知相似度判断。
9. 完全相同的历史成品不自动等于永久禁止重新生成或交付。

Render SHA256 通常在实际成品生成后取得，不宣称仅靠此能力即可阻止渲染前重复计算。

### 9. M3 — Historical Advisory & Human Reuse

V1 应能够为 Operator 展示：

- 历史是否存在相同规划身份。
- 历史记录数量和适用时间范围。
- 相关项目及产出状态。
- 历史成品是否可用。
- 历史证据和索引覆盖情况。
- 当前检查结果的不确定性。

推荐的 Operator 行为包括：

- 查看历史。
- 继续当前创意实验。
- 在授权范围内选择复用。
- 修改 Creative Recipe 或 Hook 形成新候选。

是否复用历史成品必须满足当前 Tenant/Project 的授权、素材使用权及适用 QC/Delivery 条件。

V1 不要求自动替代运营人员做最终复用决策。

### 10. Historical Policy

首版沿用历史讨论中已有的产品政策边界：

- OFF
- OBSERVE
- ADVISORY

V1 不增加默认 Historical ENFORCE。

Historical Policy 必须与 L2 Reservation Policy 的启用和灰度控制保持独立。

历史匹配只形成对应策略所允许的观察、诊断或提示行为。

不得因为 Reservation ENFORCE 或 Default-ON 生效，就自动开启 Historical Hard Block。

任何未来 SELECTIVE BLOCK 或 Historical ENFORCE，均须独立审查误判率、业务例外、权限、回退及发布 Gate。

现有代码是否完整实现上述模式及其具体行为，需要后续只读工程验证。

### 11. Tenant / Project Scope

1. Historical Creative Memory 必须归属明确 Tenant。
2. 每条记录保留适用的 Project 来源。
3. 当前 Operator 只能检索其获授权 Tenant 的历史数据。
4. 同 Tenant 内可以按授权条件跨 Project 查询与复用。
5. Project 筛选不能被虚假描述为独立安全 ACL。
6. 不同 Tenant 的私有历史创意默认隔离。
7. 不允许跨 Tenant 暴露匹配记录、客户文件、历史效果或其他私有业务证据。
8. 不允许仅凭相同 FP 或 SHA256 建立跨 Tenant 的业务访问授权。
9. Tenant 切换时的历史缓存与异步结果必须遵守 D16-004-C。

本合同不建设跨客户 Creative Memory 数据共享平台。

### 12. Schema Evolution & Backfill

1. 优先采用附加事实和增量索引设计。
2. 不允许以清空 1.5 真实生产数据库作为正常升级路径。
3. Schema Migration 必须满足 D16-002 的备份、恢复和兼容性要求。
4. Historical Backfill 必须与 Schema Migration 独立管理。
5. Backfill 应具备安全重入和明确失败记录。
6. 索引算法、版本及生成时间必须可追溯。
7. 任何 Backfill 不得破坏已有客户生产事实。
8. 不要求历史索引一次性达到 100% 覆盖率才能启动正常 Seed 工作流。
9. 不默认启用与生产渲染相冲突的后台索引作业。

### 13. Historical Failure Policy

1. Historical Advisory 不可用时，必须提示检查不可用或覆盖不足。
2. 不得将查询失败显示为“历史无重复”。
3. 在其他生产安全 Gate 均满足时，允许继续正常 Seed 工作流。
4. 如果异常涉及 Tenant 授权、数据归属或生产数据完整性，必须阻止受影响的危险操作。
5. 不允许通过自动清库、重新 Seed 或删除旧索引以掩盖故障。
6. 诊断与恢复不得自动触发未经授权的整个 Task 重提。

### 14. 最低验收矩阵

至少覆盖以下场景：

1. 相同 FP-001 的历史规划记录可以准确匹配。
2. 不同 FP-001 的规划不会被错误标记为完全相同。
3. PLANNED 与 RENDERED 被正确区分。
4. FAILED 历史记录不会被认定为成功成品。
5. 同一规划产生不同视频时不会错误视为 SHA256 一致。
6. 字节完全一致的成品可识别精确文件重复。
7. SHA256 一致不导致跨 Tenant 自动共享。
8. 1.5 历史数据原始身份和 Ledger 语义保留。
9. 旧视频文件缺失时，保留已有历史事实。
10. 索引未覆盖完整历史时不宣称绝对全新。
11. 历史归属 UNRESOLVED / CONFLICT 时不发生未授权访问。
12. 同 Tenant 内历史记录保留 Project 来源。
13. 不同 Tenant 的 Historical Memory 不发生信息泄露。
14. Operator 可以理解匹配依据和证据限制。
15. 合法复用历史成品必须满足相应授权和交付合同。
16. Historical ADVISORY 不默认阻断生产。
17. Historical 检索异常不会无条件阻塞健康 Seed 生产。
18. Backfill 中断、重复执行或失败不破坏原始数据。
19. Schema Migration 不以清空真实数据库为前提。
20. Historical Policy 不改变 L1/L2 的既有硬约束与发布控制。

全部验收必须绑定候选版本、测试数据、Tenant 范围和可追溯工程证据。

### 15. 版本与发布范围

D16-006 作为 DopaMatrix 1.6 的 P1 独立功能包规划。

1. M0 的数据保护原则立即作为相关设计的强制兼容约束。
2. M1、M2、M3 为 Historical Creative Memory V1 的核心目标。
3. M4 需要真实数据样本和误判验证后另行确定是否进入 1.6。
4. M5 原则上后置至 1.7+。
5. 不将完整 L3 V1 自动加入 1.6-A Seed Reliability 发布阻断项。
6. 不将完整 L3 V1 自动加入 1.6-B Studio Workspace MVP 的强制发布阻断项。
7. 如果 L3 功能进入某个实际安装制品，则必须通过该功能适用的隔离、数据安全和验收 Gate。
8. L3 不能绕过原有 Production HOLD。

本决策不新增强制性的 1.6-C 发行里程碑。

### 16. 工程实施与架构权限

本决策不直接授权：

- 重新设计 FP-001 或 Ledger。
- 修改 Reservation Authority。
- 新增数据库 Schema 或执行 Migration。
- 扫描客户历史视频或实施 Backfill。
- 计算历史文件 SHA256 或 pHash。
- 新增 AI 模型、向量库或索引服务。
- 修改 Task/Child/Attempt 状态模型。
- 执行 Build、Commit、Push、安装或发布。

涉及 Frozen Architecture 的变更必须单独提交 ADR 并经 Owner 审批。

实际能力、既有索引和历史关联完整性在获得最新工程证据之前均为 NOT_VERIFIED。

### 17. 既有 HOLD

本决策不解除：

- `PHILIPPINES_INSTALL = HOLD`
- `LOCAL-P-R1 = FAIL/HOLD`
- `ARCHITECTURE_EXCEPTION = BLOCKED`
- `A1_ACTIVATION_BLOCKED = TRUE`
- `A2 = NOT_APPROVED`
- Production Lifecycle Receipt / Ownership / Runtime Guard / Q2 Final 等其他现存工程及 Production HOLD。

D16-006 产品冻结、功能实现或历史索引验收，均不能替代正式生产发布授权。

### 18. 冻结条件

Product Owner 明确批准 D16-006 v1.0 后，状态方可从 `PROPOSED_FOR_FREEZE` 更新为 `FROZEN`。

冻结后，本决策成为 Historical Creative Memory V1 的正式产品范围、数据兼容及验收合同。

冻结不意味着 L3 已经实现，也不授予工程实施权限。

**Freeze record:** Product Owner 于 2026-11-06 明确回复“批准冻结 D16-006 v1.0”。因此，D16-006 v1.0 的状态由 `PROPOSED_FOR_FREEZE` 更新为 **`FROZEN`**。

**Implementation authority:** **NOT_GRANTED**。本次产品冻结不授权任何工程操作，不解除 `PHILIPPINES_INSTALL = HOLD`、`LOCAL-P-R1 = FAIL/HOLD` 或其他尚未解除的工程 / Production HOLD。
