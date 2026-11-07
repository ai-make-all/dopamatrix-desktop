# DopaMatrix 1.6 — ENGINEERING_DEPENDENCIES.md

> **Status:** FROZEN — Owner Approved Planning Baseline（只冻结调查顺序/证据要求，不授权工程操作）
> **Version:** v1.0 / 2026-11-07（批准的 v0.2 内容正式归档）
> **Decision baseline:** 8 项 D16 决策 FROZEN
> **PRD baseline:** 59 条需求 FROZEN · commit `e67dd39`
> **Acceptance baseline:** 34 个 AC + 12 组 AS FROZEN · 工程全部 NOT_RUN/NOT_VERIFIED
> **Implementation / Read-only Audit Authority:** NOT_GRANTED
> **Owner approval:** 2026-11-07 · Engineering Dependencies v0.2 内容获明确同意

## 1. 目的与可信证据层级

本文件只规划后续**只读调查的最小集合、先后关系和 Stop Rules**，不对 1.5 当前代码实现状态下结论。

证据层级：最新权威 `.codex-local/handoffs.md` 与其明确指向的工程证据 → 指定 Branch/Commit 的真实源码及只读静态核验 → 相应 Candidate 的测试制品/日志。历史报告可以作为线索，不能跨 Candidate 自动继承 PASS。

Docs Worktree 从旧的 `origin/main` 建立，其代码不是 RC2 Candidate P/Q 的权威工程现状。需在另行批准的工程工作区进行只读核验。

## 2. 交付依赖与真实优先级

| 阶段 | 切片 | 先决事实 | 后继产品动作 | 不允许推断 |
|---|---|---|---|---|
| E0 | 权威 Engineering Handoff/分支、HOLD 清单 | 1.5 Frozen Architecture、Closed Phases 保持有效 | 制定最小只读证据范围 | 产品冻结 = 工程授权 |
| E1 | RE-G0 路径与破坏性操作清单（AUD-01） | RuntimePaths、SQLite、Backup、Output 所有权 | 形成 RE-G1 风险分类 | 未观察到事故 = 路径安全 PASS |
| E2 | Seed 当前 Candidate P/Q 差距（AUD-03/04/05） | 当前实际制品/源码身份、Batch2 与媒体检查边界 | 定义最小 P0 补救切片 | Q 通过 = P 已有能力 |
| E3 | 升级恢复安全（AUD-02） | 备份一致性、实际恢复证据、升级兼容 | 判定 RE-G2/G3/G4 工程前置 | Backup 存在 = Restore PASS |
| E4 | Studio Identity/Data Plane（AUD-06/07） | 旧数据归属、网关 DB 与文件生命周期 | 判定 1.6-B 设计与 ADR | Tenant 逻辑字段 = 完整隔离 |
| E5 | Switch/Control Plane（AUD-08/09） | E4 数据上下文可信、运行时静止事实 | 1.6-B 受控设计切片 | UI 隐藏切换 = 后端 Barrier |
| E6 | L3 前向兼容与历史血统（AUD-10） | 只读来源与 Tenant 归属，支持维护窗口 | 独立 P1 功能评估 | No Match = Proven Novelty |

E1/E2 可作为两个**分别授权**的只读审查包；不代表批准并行执行，也不得因产品规划触发对生产环境的实际扫描或修改。E3 的真实恢复演练属于后续**测试授权**，不属于只读调查。

## 3. 十个只读工程调查包

| Audit | 范围 | 必须回答的 Evidence Question | 产品/验收映射 | 默认状态 |
|---|---|---|---|---|
| AUD-01 | Release Paths | Build/Package/Reset 实际解析路径有哪些？哪些可能触达客户 SQLite、Output、Backup、Secure Settings？ | RE-01/02/10 · AS-01 · AC-RE01 | NOT_VERIFIED |
| AUD-02 | Upgrade/Recovery/Uninstall | 当前提供什么安全升级、备份、恢复、卸载保护？有哪些可追溯证据而不是只看脚本名称？ | RE-05/06/07/08/09 · AS-01 · AC-RE02/03/06 | NOT_VERIFIED |
| AUD-03 | Import Gate | P 与 Q 各自支持哪些媒体流/完整解码、版本一致性、损坏区分？差异在哪？ | A-IMP-01..04 · AS-12 · AC-A02/03/08 | NOT_VERIFIED |
| AUD-04 | Task/Batch2/Attempt | 单 Task Batch2、成功 Child 保留、UNKNOWN/孤儿、Attempt 来源及输出安全边界？ | A-BAT-01..04/A-REC-01 · AC-A01/04/05/09 | NOT_VERIFIED |
| AUD-05 | Output/QC/Delivery | 实际媒体检查粒度？逐条人工 QC、部分交付在现有 UI/SOP 如何保证？ | A-OUT-01/02 A-QC-01..03 · AC-A06/07 | NOT_VERIFIED |
| AUD-06 | Studio Identity/Legacy | 现有 Customer/Tenant/Project 标识和旧数据归属依据？哪些无法可信映射？ | B-ID-01..03/B-LEG-01 · AS-02/03/07 | NOT_VERIFIED |
| AUD-07 | Tenant Data Plane | 单 FastAPI 的 SQLite 连接生命周期/缓存/Output/Task 归属如何保障？哪里冲突 Frozen Architecture？ | B-DB/B-FILE/B-EXEC/B-CACHE/B-BACK · AS-04/05/06 | NOT_VERIFIED |
| AUD-08 | Idle-only Switch | 有无可证的 Global Quiescence、Switch Barrier、旧响应失效、崩溃 Locked？ | B-SW-01..05 · AC-B03/04/05/12 | NOT_VERIFIED |
| AUD-09 | Membership/Installation | 首次在线、Operator vs Device 授权、8h 绝对租约、撤权执行收尾能否安全达到？ | B-CP/B-AUTH · AS-07/08/09 | NOT_VERIFIED |
| AUD-10 | L3 Provenance | FP-001、Ledger、Child/Attempt/Output 血统和版本能否支持受控历史查询/Backfill？ | L3-M0..M3 · AS-10 · AC-L301..306 | NOT_VERIFIED |

## 4. E1 / E2 只读调查精确边界（**候选授权范围，尚未获批**）

### E1 — AUD-01（RE-G0 Path & Destructive Surface Inventory）

**允许申请的调查动作：** 读取权威 Handoff、列出并阅读当前候选版本中的 Build/Package/Reset/Install/Uninstall 相关源码与静态配置、记录源码路径/行号、标出可能写入或删除路径的入口及其保护条件。

**必须回报：** 实际候选 Branch/Commit、被审查文件清单、路径来源/解析规则、保护资产清单、确定风险/待证风险、可复核证据、与 `RE-G0/RE-G1` 关系。

**禁止：** 运行 Build/Reset/Installer、真实数据路径探测、清理文件、导出客户数据、自动备份/恢复、调整权限/配置。

### E2 — AUD-03/04/05（Seed P/Q Static Gap Review）

**允许申请的调查动作：** 分别读取 Candidate P/Q 的权威源码/报告；做只读静态比较，记录已验证/未验证的输入、Batch2、Output、QC、人工补救行为与现存 HOLD。

**必须回报：** P/Q 分别列证据，不跨版本继承 PASS；每项映射到对应 Requirement/AC；明确只读证据不能替代运行测试。

**禁止：** 修改 Test、启动服务、调用本地生产 API、触发 FFmpeg/Playwright、运行真实素材检测、重提 Task、写 SQLite、恢复/迁移数据或自动继续到 Codex 实施。

## 5. Stop Rules 与 Gate 边界

1. 未找到最新权威 Engineering Handoff 或候选 Commit 不明确：**STOP**，不得猜测工程状态。
2. 真实文件归属/执行权限无法确认：**STOP**，不得扫描、移动或修改真实客户数据。
3. 需要启动应用、运行测试或访问数据库以确认结论：记录 `RUNTIME_VERIFICATION_REQUIRED`，另行申请测试授权。
4. 发现与 Frozen Architecture 冲突：标 `ADR_REVIEW_REQUIRED`；不得在只读审查中直接修改架构。
5. 审查发现既有 HOLD：如实保留，不得以 PRD/AC FROZEN 覆盖或解除。
6. 任何候选代码修复、Commit/Push、Build、Installer、Migration、Backfill 需要新的明确 Owner 授权。

## 6. 工程调查结果的统一记录格式

每条结论必须包含：

`AUD_ID | Requirement/AC/AS IDs | Authority Handoff | Candidate Branch/Commit | Source Evidence (file:line) | Existing Verified / GAP / NOT_VERIFIED | Safety/ADR State | Required Runtime Evidence | Release HOLD | Recommendation | Owner Decision`

报告必须区分：历史已通过、当前静态可证、需运行时验证、当前已知缺口、存在架构例外。不要简单把所有字段压缩成 PASS/FAIL。

## 7. 首发范围约束与后续审批点

- 1.6-A 第一目标：健康素材 + 单 Task Batch2 + Output Gate + 逐条人工 QC + 有界人工补救；RE-0 是任何实际发布/升级的安全前置。
- 1.6-B 仍为独立 MVP：Tenant 数据隔离 / Idle-only Switch / Membership / Installation，必须通过 A 回归及适用 RE Gates。
- L3 独立 P1，M0 强制兼容原则有效，不自动阻塞 A/B；任何 P1 回填或索引仍需独立授权。
- 本文档已获 Owner 审查同意，作为 `FROZEN` **工程依赖与只读调查规划基线**；**不授权 E1/E2 或其他 Audit 的实际只读调查**。未来只对明确的 Audit ID、数据源和只读动作范围另行授权；其他操作不包含在批准中。


## 8. Owner Freeze Record

**Freeze record:** Product Owner 于 2026-11-07 明确同意 `ENGINEERING_DEPENDENCIES.md v0.2` 的内容。故该已审查内容正式归档为 **v1.0 FROZEN — Planning Baseline**。本次仅冻结调查划分、优先级、证据与 Stop Rules；没有授权任何 Codex / 只读源码调查 / 实际工程变更 / 测试 / Build / Commit / Push / 安装或发布。

**Engineering / Read-only Audit Authority: NOT_GRANTED.** 未来每次 Audit 均需明确 Owner 授权。所有 1.5 Frozen Architecture、Closed Phases 与 Production HOLD 继续有效。
