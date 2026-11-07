# DopaMatrix 1.6 — ACCEPTANCE_MATRIX.md

> **Status:** FROZEN — Owner Approved Acceptance Baseline（测试仍 NOT_RUN）
> **Version:** v1.0 / 2026-11-07（批准的 v0.2 内容正式归档）
> **Parent PRD:** PRD.md v1.0 — FROZEN
> **Decision baseline:** DECISIONS.md D16-001～D16-006 — 8 FROZEN
> **Engineering Authority:** NOT_GRANTED
> **Evidence:** 所有条目 NOT_VERIFIED，未执行任何工程测试

## 1. 用途与证据语义

- 将已冻结的 59 条 Requirement ID 映射到现有 34 个端到端 AC 场景（反向映射亦见 §3）。**映射不是通过、也不意味着断言覆盖充分**。
- 每个 E2E 场景执行时须绑定候选 Git Commit、Artifact SHA256、环境、Tenant/Project 样本、执行命令与输出证据、异常处理记录、Reviewer、时间。
- 工程实现证据 `NOT_VERIFIED / EXISTING_VERIFIED / GAP`；架构审批 `NO_ADR_IDENTIFIED / ADR_REVIEW_REQUIRED / ADR_APPROVED`；Release Gate `HOLD / NOT_AUTHORIZED / PASS_WITH_EVIDENCE`，三者独立。
- 1.6-A 通过不解除菲律宾生产 HOLD；RE-G5 是独立许可，不能从需求级 PASS 自动推导。

## 2. 逐需求追踪矩阵（59 项）

| Requirement | 里程碑 | 产品行为摘要 | 已规划场景 | 测试覆盖提醒 | 工程证据 |
|---|---|---|---|---|---|
| `A-IMP-01` | 1.6-A Seed | 在声明支持的输入范围内进行结构、所需流和有界完整解码技术检查 | `AC-A01`, `AC-A02` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-IMP-02` | 1.6-A Seed | 区分损坏/截断、不支持规格、AI 内容理解失败 | `AC-A02`, `AC-A08` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-IMP-03` | 1.6-A Seed | 验证结果绑定实际用于生产的素材版本 | `AC-A03` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-IMP-04` | 1.6-A Seed | 人工补拍、更换、重新导入形成闭环 | `AC-A02`, `AC-A03` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-OPS-01` | 1.6-A Seed | 复用已有且经验证的人工 Story/Matrix 编排路径 | `AC-A01` | 人工选取/编辑有效参数的 UI/API 范围待明确 | NOT_VERIFIED |
| `A-BAT-01` | 1.6-A Seed | 一个 Task 内保留有界 Batch2 两 Child 产出 | `AC-A01` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-BAT-02` | 1.6-A Seed | 限制未经验证的跨 Task 并发与整体自动重提 | `AC-A05`, `AC-A09` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-BAT-03` | 1.6-A Seed | 处理单 Child 成功、另一 Child 失败 | `AC-A04` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-BAT-04` | 1.6-A Seed | UNKNOWN、孤儿执行和资源冲突 Fail Closed | `AC-A05`, `AC-A09` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-OUT-01` | 1.6-A Seed | 各 Child 对实际文件、所需媒体流和适用可读性/解码/规格独立执行 Output Gate | `AC-A01`, `AC-A06` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-OUT-02` | 1.6-A Seed | Output/历史产物受身份和路径保护 | `AC-A05`, `AC-A09` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-QC-01` | 1.6-A Seed | Execution、Output Validation、Human QC、Delivery Eligibility 语义分离 | `AC-A01`, `AC-A06` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-QC-02` | 1.6-A Seed | 每条拟交付实际 Output 逐条人工视听 QC，允许受控人工留痕 | `AC-A01`, `AC-A06` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-QC-03` | 1.6-A Seed | 客户交付约定允许、Operator 明确确认时可受控部分交付 | `AC-A04`, `AC-A07` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-REC-01` | 1.6-A Seed | 安全终结后才允许人工新 Attempt | `AC-A09` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `A-REC-02` | 1.6-A Seed | Seed 采用人工有界补救，不以智能修复作为首发条件 | `AC-A02`, `AC-A09` | 人工补拍/替换后的再次 Gate 证据需补原子断言 | NOT_VERIFIED |
| `RE-01` | RE-0 | 明确 Build、Runtime Data、Backup/Recovery 三域所有权并只读核验实际路径 | `AC-RE01` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `RE-02` | RE-0 | 有不可信路径/破坏性操作时 Fail Closed | `AC-RE01` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `RE-03` | RE-0 | 每份安装制品不可变且可追踪 | `AC-RE05` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `RE-04` | RE-0 | RE-0 受控人工发布，不以自动 CI/CD 为首发要求 | `AC-RE04` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `RE-05` | RE-0 | 升级前执行版本、任务、路径及恢复 Preflight | `AC-RE02` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `RE-06` | RE-0 | 真实升级必须有已验证一致性备份与完整数据集恢复方案 | `AC-RE02`, `AC-RE06` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `RE-07` | RE-0 | 迁移失败安全停机、保护原数据 | `AC-RE02`, `AC-RE06` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `RE-08` | RE-0 | 普通卸载默认保留客户生产数据 | `AC-RE03` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `RE-09` | RE-0 | RE-G0～G5 发布 Gate 可追踪 | `AC-RE01`, `AC-RE02`, `AC-RE04` | RE-G0/G1/G2/G3/G4/G5 各独立 Gate 的签字证据尚需逐项细化 | NOT_VERIFIED |
| `RE-10` | RE-0 | 1.5 路径先逻辑隔离，不强制一次性物理迁移 | `AC-RE01` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-ID-01` | 1.6-B Studio | Customer/Tenant/Workspace/Project 对象语义和精确基数 | `AC-B01` | Customer 0..N Tenant、Workspace 1:1、Project 归属需要独立对象基数断言 | NOT_VERIFIED |
| `B-ID-02` | 1.6-B Studio | Tenant 为客户级强制隔离主体 | `AC-B01`, `AC-B10` | Project 非强 ACL 的负向访问与真实权限边界需独立断言 | NOT_VERIFIED |
| `B-ID-03` | 1.6-B Studio | Operator 通过 Membership 可服务多个 Tenant | `AC-B01` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-DB-01` | 1.6-B Studio | 每 Tenant 独立 SQLite 是产品目标，保留单 FastAPI 网关方向 | `AC-B02`, `AC-B11` | 每 Tenant 独立 SQLite 的物理隔离及旧连接生命周期需独立断言 | NOT_VERIFIED |
| `B-DB-02` | 1.6-B Studio | 不以可变全局 db_path 作为无保护切换实现 | `AC-B02` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-FILE-01` | 1.6-B Studio | 素材、Output、中间文件、缓存、交付记录具 Tenant 归属 | `AC-B02`, `AC-B09` | 临时文件、Output 和 Delivery 的跨租户隔离需独立验证 | NOT_VERIFIED |
| `B-FILE-02` | 1.6-B Studio | 外部源引用为可选能力，未获批准前必须关闭该生产路径 | `AC-B09` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-EXEC-01` | 1.6-B Studio | Task/Child/Attempt Tenant 身份不可变 | `AC-B03`, `AC-B05` | Task/Child/Attempt 不可变 Tenant identity 的跨切换持久化断言需补齐 | NOT_VERIFIED |
| `B-CACHE-01` | 1.6-B Studio | API、订阅、缓存、缩略图与历史结果按 Tenant 隔离 | `AC-B02` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-LEG-01` | 1.6-B Studio | 1.5 历史数据先安全保留；任何认领必须核实归属再受控映射 | `AC-B06` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-BACK-01` | 1.6-B Studio | Tenant 级恢复须验证数据一致性、其他 Tenant 安全及授权有效性 | `AC-B11` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-SW-01` | 1.6-B Studio | 切换时先建立可信运行时准入屏障，再检验全局静止并提交切换 | `AC-B03` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-SW-02` | 1.6-B Studio | 全局安全静止而非仅 UI Completed | `AC-B03` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-SW-03` | 1.6-B Studio | 目标授权及上下文验证通过后才进入 Tenant | `AC-B05` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-SW-04` | 1.6-B Studio | 运行时已安全静止时允许保留待 QC/Delivery 记录后切换 | `AC-B04`, `AC-B12` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-SW-05` | 1.6-B Studio | 切换中崩溃重启必须重新核验 | `AC-B05` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-CP-01` | 1.6-B Studio | 管理员审核创建正式 Tenant，受控初始化 | `AC-B01`, `AC-B06` | 管理员审核创建正式 Tenant 与失败 Provision 需独立正/负向断言 | NOT_VERIFIED |
| `B-CP-02` | 1.6-B Studio | 采用最小授权管理员、日常 Operator 角色及 Membership 管理 | `AC-B10` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-CP-03` | 1.6-B Studio | Installation/Device 授权与 Membership 分开 | `AC-B01`, `AC-B10` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-AUTH-01` | 1.6-B Studio | 人员/设备/Tenant 有效性联合授权 Gate | `AC-B01`, `AC-B10`, `AC-B13` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-AUTH-02` | 1.6-B Studio | 首次登录/激活/首次授权必须在线 | `AC-B13` | 首次登录、首次激活、首次 Tenant 获取必须在线的单独场景待细化 | NOT_VERIFIED |
| `B-AUTH-03` | 1.6-B Studio | 8 小时是离线租约候选最大绝对期限，不是必须达到的离线服务承诺 | `AC-B08`, `AC-B13` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-AUTH-04` | 1.6-B Studio | 首发离线仅继续当前 Tenant，禁止离线切换 | `AC-B08` | 离线 Tenant/Operator 切换拒绝需要独立负向断言 | NOT_VERIFIED |
| `B-AUTH-05` | 1.6-B Studio | 撤权/到期阻断新 Task/Child 与其他受保护操作，现有执行安全收尾 | `AC-B07`, `AC-B13` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `B-AUTH-06` | 1.6-B Studio | 设备/人员失效或卸载不自动删客户数据 | `AC-B10`, `AC-B11` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `L3-M0-01` | L3 P1 | 历史事实不可改写，派生索引不替代 L1/L2 | `AC-L301`, `AC-L306` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `L3-M0-02` | L3 P1 | 归属维度与索引覆盖维度分离 | `AC-L303`, `AC-L306` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `L3-M0-03` | L3 P1 | Schema Migration 与 Historical Backfill 分离，按批准维护窗口进行回填 | `AC-L306` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `L3-M1-01` | L3 P1 | 同 Tenant 以兼容 FP-001 查询历史规划 | `AC-L301` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `L3-M2-01` | L3 P1 | 稳定、经确认输出建立 SHA256 精确身份 | `AC-L302` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `L3-M3-01` | L3 P1 | 向 Operator 展示历史证据与覆盖范围 | `AC-L303` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `L3-M3-02` | L3 P1 | Historical Policy 维持 OFF/OBSERVE/ADVISORY 独立语义，不默认 ENFORCE | `AC-L304`, `AC-L305` | 仍需从该需求的最小验收判据展开原子断言 | NOT_VERIFIED |
| `L3-M3-03` | L3 P1 | Operator 可人工查看、继续实验或在获准范围内复用 | `AC-L302`, `AC-L304` | 人工复用的素材授权、项目使用权、QC/Delivery 需补独立断言 | NOT_VERIFIED |

## 3. 场景到需求反向追踪（34 项）

| AC ID | 主场景 | 映射 Requirement ID | 预期判定 / Gate | 状态 |
|---|---|---|---|---|
| `AC-A01` | 好原片完成导入、Batch2 双 Child、技术检查与逐条人工 QC | `A-IMP-01`, `A-OPS-01`, `A-BAT-01`, `A-OUT-01`, `A-QC-01`, `A-QC-02` | 两条均合格且身份独立；不以进程完成替代 QC / A + RE 适用 Gate | NOT_RUN |
| `AC-A02` | 截断或损坏视频；正常 VFR 对照 | `A-IMP-01`, `A-IMP-02`, `A-IMP-04`, `A-REC-02` | 损坏拦截、VFR 不被无依据拒绝 / A | NOT_RUN |
| `AC-A03` | 通过检测后更换/修改源文件 | `A-IMP-03`, `A-IMP-04` | 旧验证结果不可无条件复用 / A | NOT_RUN |
| `AC-A04` | Batch2 一个 Child 失败 | `A-BAT-03`, `A-QC-03` | 保留合格 Child，整体不假称全部成功 / A | NOT_RUN |
| `AC-A05` | UNKNOWN/孤儿进程时重试 | `A-BAT-02`, `A-BAT-04`, `A-OUT-02` | 不允许危险重试或覆盖 / A | NOT_RUN |
| `AC-A06` | 技术合格但人工 QC 不通过 | `A-OUT-01`, `A-QC-01`, `A-QC-02` | 禁止合格交付 / A | NOT_RUN |
| `AC-A07` | 客户只接受两条但实际只有一条合格 | `A-QC-03` | 不可声称完整履约 / A | NOT_RUN |
| `AC-RE01` | Build/DEV RESET 面对真实 Runtime/Backup 路径 | `RE-01`, `RE-02`, `RE-09`, `RE-10` | 不破坏客户数据 / RE-G0～G2 | NOT_RUN |
| `AC-RE02` | 实际升级含 Schema 变化及恢复演练 | `RE-05`, `RE-06`, `RE-07`, `RE-09` | 已验证一致性备份和隔离恢复，否则 STOP / RE-G3/G4 | NOT_RUN |
| `AC-RE03` | 普通卸载和重新安装 | `RE-08` | 数据保留；授权另行核验 / RE-G3/G4 | NOT_RUN |
| `AC-RE04` | 候选制品欲安装菲律宾设备 | `RE-04`, `RE-09` | HOLD 未解除不得执行 / RE-G5 + 既有生产 Gate | NOT_RUN |
| `AC-B01` | 同设备两 Operator 和两 Tenant | `B-ID-01`, `B-ID-02`, `B-ID-03`, `B-CP-01`, `B-CP-03`, `B-AUTH-01` | Membership/Installation/Entitlement 三重约束有效 / B | NOT_RUN |
| `AC-B02` | Tenant A 旧请求返回，当前 B | `B-DB-01`, `B-DB-02`, `B-FILE-01`, `B-CACHE-01` | 不可污染 B 的数据库/缓存/界面 / B | NOT_RUN |
| `AC-B03` | Task 正运行/Queued/UNKNOWN 时切换 | `B-EXEC-01`, `B-SW-01`, `B-SW-02` | Barrier 拒绝，且不自动 Kill / B | NOT_RUN |
| `AC-B04` | 运行静止但仍有待人工 QC | `B-SW-04` | 允许授权切换，保留原业务状态 / B | NOT_RUN |
| `AC-B05` | 切换过程中目标 DB 不可用或应用崩溃 | `B-EXEC-01`, `B-SW-03`, `B-SW-05` | 可安全回原 Tenant 或 Locked，不混合上下文 / B | NOT_RUN |
| `AC-B06` | 1.5 无可信归属旧素材 | `B-LEG-01`, `B-CP-01` | 不自动归到当前 Tenant，不删库 / B + RE | NOT_RUN |
| `AC-B07` | 租约在 Batch2 运行中到期 | `B-AUTH-05` | 新执行准入停止；安全收尾；未授权不交付 / B | NOT_RUN |
| `AC-B08` | 离线 8h 上限到期、系统时间回退 | `B-AUTH-03`, `B-AUTH-04` | 不可重启/改时间自行续期 / B | NOT_RUN |
| `AC-L301` | Historical FP 命中 PLANNED/FAILED/RENDERED | `L3-M0-01`, `L3-M1-01` | 证据语义不混淆 / L3 | NOT_RUN |
| `AC-L302` | 相同 FP，不同 SHA256；相同 SHA256，跨 Tenant | `L3-M2-01`, `L3-M3-03` | 不混淆规划与字节重复；不跨 Tenant 泄露 / L3 | NOT_RUN |
| `AC-L303` | 历史索引未覆盖 / Output 已丢失 | `L3-M0-02`, `L3-M3-01` | No Match 不等于 Proven Novelty；保留原 Ledger 事实 / L3 | NOT_RUN |
| `AC-L304` | Historical 服务不可用但 Seed Gates 安全 | `L3-M3-02`, `L3-M3-03` | 明示不可用、可降级；权限或完整性异常必须阻断 / L3 | NOT_RUN |
| `AC-A08` | 不支持的编码与 AI 剧情分析失败对照 | `A-IMP-02` | 能区分技术不支持和语义分析错误，不能把后者误报媒体损坏 / A | NOT_RUN |
| `AC-A09` | 旧执行已安全终结后发起独立 Attempt | `A-BAT-02`, `A-BAT-04`, `A-OUT-02`, `A-REC-01`, `A-REC-02` | 新身份可追踪；原成功 Output 不覆盖；UNKNOWN 时拒绝 / A | NOT_RUN |
| `AC-RE05` | 同名不同字节的两份安装制品 | `RE-03` | 身份/SHA256/Manifest 区分且来源可追溯 / RE-G2 | NOT_RUN |
| `AC-RE06` | 仅有备份文件、没有成功恢复证据 | `RE-06`, `RE-07` | RE-G4 不得 PASS，真实升级阻断 / RE-G4 | NOT_RUN |
| `AC-B09` | 外部素材路径越界、链接重解析或内容在检查后变化 | `B-FILE-01`, `B-FILE-02` | 未获批准引用拒绝；获批引用不得读错 Tenant/素材版本 / B | NOT_RUN |
| `AC-B10` | 管理员无业务 Membership，尝试读取客户数据；复制设备配置 | `B-ID-02`, `B-CP-02`, `B-CP-03`, `B-AUTH-01`, `B-AUTH-06` | 拒绝越权业务读取和配置克隆授权 / B | NOT_RUN |
| `AC-B11` | 恢复 Tenant A 时 Tenant B 数据仍存在 | `B-DB-01`, `B-BACK-01`, `B-AUTH-06` | B 不受影响，失效授权不因恢复旧数据而恢复 / B + RE-G4 | NOT_RUN |
| `AC-B12` | 切换前存在未保存编辑及待 QC 记录 | `B-SW-04` | 编辑不静默丢失，QC/交付记录继续归属原 Tenant / B | NOT_RUN |
| `AC-B13` | 在线撤权、断网租约未过期与到期后的比较 | `B-AUTH-01`, `B-AUTH-02`, `B-AUTH-03`, `B-AUTH-05` | 已知撤权禁止新操作；断网承认到期前有限延迟；到期无新准入 / B | NOT_RUN |
| `AC-L305` | 历史 OFF/OBSERVE/ADVISORY 与 L2 并存 | `L3-M3-02` | L3 不暗中改变 L2 ENFORCE/Canary，也不默认硬阻断 / L3 | NOT_RUN |
| `AC-L306` | 历史 Backfill 中断、重入及 Output 缺失 | `L3-M0-01`, `L3-M0-02`, `L3-M0-03` | 不伪造重复记录、不删原 Ledger，覆盖状态可解释 / L3 | NOT_RUN |

## 4. 缺口与验收设计工作清单

现有 34 个 AC 场景是 **端到端基线**。下列事项需要补写原子断言、正反例与失败证据，但**不自动扩大冻结的产品功能范围**：

- `RE-09`：RE-G0/G1/G2/G3/G4/G5 各独立 Gate 的签字证据尚需逐项细化。
- `B-ID-01`：Customer 0..N Tenant、Workspace 1:1、Project 归属需要独立对象基数断言。
- `B-ID-02`：Project 非强 ACL 的负向访问与真实权限边界需独立断言。
- `B-DB-01`：每 Tenant 独立 SQLite 的物理隔离及旧连接生命周期需独立断言。
- `B-FILE-01`：临时文件、Output 和 Delivery 的跨租户隔离需独立验证。
- `B-EXEC-01`：Task/Child/Attempt 不可变 Tenant identity 的跨切换持久化断言需补齐。
- `B-CP-01`：管理员审核创建正式 Tenant 与失败 Provision 需独立正/负向断言。
- `B-AUTH-02`：首次登录、首次激活、首次 Tenant 获取必须在线的单独场景待细化。
- `B-AUTH-04`：离线 Tenant/Operator 切换拒绝需要独立负向断言。
- `L3-M3-03`：人工复用的素材授权、项目使用权、QC/Delivery 需补独立断言。
- `A-OPS-01`：人工选取/编辑有效参数的 UI/API 范围待明确。
- `A-REC-02`：人工补拍/替换后的再次 Gate 证据需补原子断言。

## 5. 测试执行与 Gate 责任

| 工作面 | 工程/测试验收重点 | Gate 继承约束 |
|---|---|---|
| 1.6-A Seed | 健康/损坏媒体、Batch2 Child 结果、Output Gate、Human QC、受控 Attempt | A 功能 PASS 不构成安装许可 |
| RE-0 | 真实路径隔离、制品唯一身份、备份恢复演练、卸载保留数据 | RE-G0～G5 分离；现有 HOLD 保留 |
| Studio 1.6-B | 授权、Tenant DB/文件/缓存隔离、Barrier、失败 Locked、离线租约 | B 必须保留 A 既有可靠性；不得越权执行 |
| L3 P1 | 历史证据、SHA256、覆盖诊断、Policy 降级、Backfill 安全 | 不自动阻塞 A/B，绝不放宽 Tenant 数据隔离 |

## 6. 下一步与冻结边界

1. Owner 已批准此验收规划的 Scenario/Requirement 映射及 12 组原子断言；未执行的工程证据仍待独立审查。
2. 在 Owner 独立授权后，依据最新工程 Handoff 和适用候选源码执行**只读工程证据调查**；不能以 Docs Worktree 的旧代码直接判断 RC2 现状。
3. 把 Test Case、环境、Candidate Commit、Artifact、Evidence URI、Reviewer 填回矩阵；未经证据不得出现 PASS。
4. PRD 与本矩阵均已完成产品范围/验收口径冻结；不授权测试或解除现存生产 HOLD。

---

## 7. R1：12 组关键原子验收断言（Owner 已批准）

以下条目是在 **59 条既有 Requirement 和 34 个既有 AC 场景之内**补写的正向、负向、失败证据要求。`AS-01`～`AS-12` 是**断言组编号，不是新需求编号或新增 E2E 场景**。它们不改变任何 D16 冻结合同，不授权运行测试，也不代表工程 PASS。所有断言状态均为 `NOT_RUN`。

### AS-01 · RE-09：六个 Release Gate 必须独立判定

- **映射：** `RE-09`；`AC-RE01/02/04/05/06`；`RE-G0`～`RE-G5`。
- **正向断言：** G0 给出只读路径/脚本清单；G1 给出受保护路径与破坏性操作边界；G2 给出隔离 Build + 不变制品 SHA256/Manifest；G3 给出 Fresh Install、适用 Upgrade、Uninstall 兼容结果；G4 给出隔离恢复实际成功证据；G5 绑定精确制品、环境、安装对象和 Owner 明确授权。
- **负向断言：** G4 无实际恢复证据时不能仅凭备份文件存在判 PASS；G0～G4 任何适用 Gate 未通过或原有生产 HOLD 未解除时，G5 不得宣称已批准菲律宾生产安装。
- **证据：** 每 Gate 的执行条件、候选 Commit/Artifact、审查人、结果与失败处理须分别记录；不得使用统一的“Release PASS”替代。

### AS-02 · B-ID-01：四类对象及基数的准确性

- **映射：** `B-ID-01`；`AC-B01`。
- **正向断言：** Customer 可以在正式开通 Tenant 前存在（0..N Tenant）；每个已开通 Tenant 具有唯一的逻辑 Workspace（1:1）；一个 Tenant 可以有多个 Project，且每个 Project 具备明确 Tenant 归属。
- **负向断言：** 不允许 Project 指向不相关 Tenant；不允许因为创建 Customer 而自动创建具备生产权限的 Tenant；不引入独立 Workspace IAM。
- **证据：** 对象关系示例、创建/读取负例、稳定身份与归属记录。

### AS-03 · B-ID-02：Project 不构成独立安全 ACL

- **映射：** `B-ID-02`；`AC-B01/10`。
- **正向断言：** 同一 Tenant 内的 Project 是业务组织边界；访问必须先通过 Tenant Membership 和设备授权。
- **负向断言：** 不得宣称 Project 筛选即实现团队保密隔离；如两个运营团队必须相互保密，须以不同 Tenant 承担强制隔离，而不是靠隐藏 Project 选择器。
- **证据：** 权限模型说明、通过/拒绝测试及 UI/API 访问一致性记录。

### AS-04 · B-DB-01：多 Tenant SQLite 与连接生命周期

- **映射：** `B-DB-01`、`B-DB-02`；`AC-B02/11`。
- **正向断言：** Tenant A、B 的业务 SQLite 文件和可信数据库上下文可区分；旧 A 请求的写入只可能落在 A 的授权数据空间；单 FastAPI 网关方向维持不变。
- **负向断言：** 禁止通过无保护的全局 `db_path` 切换使旧连接写 B；目标库不可访问、旧连接未安全收束时 Fail Closed，不发生跨 Tenant 混合事务。
- **证据：** 实际连接生命周期、并发/延迟请求的租户身份与数据库路径对应关系，数据库前后差异快照。兼容性先标 `NOT_VERIFIED`；触及 Frozen Architecture 必须先 ADR。

### AS-05 · B-FILE-01：全类型文件的归属保护

- **映射：** `B-FILE-01`；`AC-B02/09`。
- **正向断言：** 输入受管资产、临时渲染文件、Output、缩略图/缓存、Delivery 均关联明确 Tenant 与适用 Task/Project；两个 Tenant 使用同文件名时仍各自独立。
- **负向断言：** A 的操作不得读取、清理或覆盖 B 的文件；对路径重解析、外部引用、检查后内容变更必须采取阻断或重新检查，未获批准的外部引用路径应保持关闭。
- **证据：** 受保护目录/资产清单、路径解析结果、跨租户操作拒绝记录、文件前后哈希/清单。

### AS-06 · B-EXEC-01：Task/Child/Attempt 的身份不可变

- **映射：** `B-EXEC-01`；`AC-B03/05`。
- **正向断言：** Task 创建时固定 Tenant/Project 归属；Child 和新 Attempt 均可追溯其来源和产物；A→B→A 之后旧 A 的已完成记录仍属于 A。
- **负向断言：** 切换 Active Tenant 不能改变已有 Task/Child/Attempt 的归属；UNKNOWN、未终结资源不能通过新的 Tenant 上下文获得写入或重试资格。
- **证据：** 创建/切换/恢复前后身份快照、事件及 Output 归属记录，不能仅以 UI 显示作为证明。

### AS-07 · B-CP-01：正式 Tenant Provision 与失败恢复

- **映射：** `B-CP-01`；`AC-B01/06`。
- **正向断言：** 平台管理员明确批准后才能正式开通 Tenant；初始化与 Customer/Operator/Installation 授权保持可追溯关系；失败时可识别不完整状态。
- **负向断言：** 官网 Lead 或普通 Operator 不能跳过审批自助开通；中断的 Provision 不能自动清库、覆盖旧 Output 或认领 1.5 未验证归属的数据。
- **证据：** 审核记录、准入日志、模拟中断的保留清单和受控恢复判断。

### AS-08 · B-AUTH-02：三个首次动作必须在线

- **映射：** `B-AUTH-02`；`AC-B13`。
- **正向断言：** 首次 Operator 登录、首次 Installation 激活、首次获取目标 Tenant 授权，均要求独立的可信在线验证；成功授权与身份作用域绑定。
- **负向断言：** 断网、旧登录缓存或复制配置不能完成上述任一首次动作；授权失败不能因页面仍显示已登录而绕过本地业务 API 的拒绝。
- **证据：** 三个正例与三个断网负例的授权状态、API 响应、有效期和日志。

### AS-09 · B-AUTH-04：离线切换必须拒绝

- **映射：** `B-AUTH-04`；`AC-B08`。
- **正向断言：** 已签发、有效期内的离线租约仅在原 Operator + Installation + Active Tenant 范围内允许获批准的本地操作。
- **负向断言：** 离线尝试切换 Tenant 或 Operator，前端和直接 API 均须拒绝；重启、重新选择菜单或修改缓存不能变相切换；8 小时租约仅为可缩短的最长候选上限。
- **证据：** 断网切换请求、API 拒绝结果、有效租约原 Tenant 业务状态未损坏的记录。

### AS-10 · L3-M3-03：人工复用的授权与 QC/Delivery

- **映射：** `L3-M3-03`；`AC-L302/304`。
- **正向断言：** 查询到历史相同 FP 或 SHA256 时只提供证据/建议；Operator 选择复用前必须具备当前 Tenant、Project 的适用素材使用权与经确认的成品可用性、QC 和交付条件。
- **负向断言：** 同 SHA256 不构成跨 Tenant 使用授权；历史技术合格不自动替代当前交付所需人工 QC；Advisory 不得默认升级 Historical ENFORCE。
- **证据：** 历史来源、归属/授权审查、复用确认人、QC/Delivery 留痕与拒绝记录。

### AS-11 · A-OPS-01：人工编排支持范围

- **映射：** `A-OPS-01`；`AC-A01`。
- **正向断言：** 在实际 1.6-A 候选版本所声明的 UI/API 支持范围内，Operator 可以人工选择有效 Hook、Story 片段、Recipe 和参数，并获得明确的提交反馈。
- **负向断言：** 超出支持范围的输入必须提示或拒绝；不得把全自动 Story Mining、无人运营或未实现的编辑模式当成首发验收前提。
- **证据：** 已支持操作清单、有效/无效参数样本、界面与最终 Task 输入的一致性记录。

### AS-12 · A-REC-02：人工补救后的 Import Gate 重验

- **映射：** `A-REC-02`、`A-IMP-03/04`；`AC-A02/03/09`。
- **正向断言：** 损坏素材被拦截后，运营人工补拍/更换/重新导入；新素材完成技术检查并与实际执行使用版本匹配后才可恢复正常生产路径。
- **负向断言：** 不得沿用旧素材的 PASS 标记跳过重验；人工补救不得覆盖已有合格 Output 或在 UNKNOWN 旧执行未安全终结时启动危险重试。
- **证据：** 原始故障报告、新素材身份/校验结果、旧执行安全终结证据和新执行结果。

## 8. 本轮原子断言的验收规则

1. **范围锁：** `AS-01`～`AS-12` 仅细化既有合同的验证口径，**不新增 Requirement、AC 场景、软件模块或发行里程碑**。
2. **安全锁：** 若实现必须触及 1.5 Frozen Architecture，只能提出 ADR 候选并另行 Owner 审批；不能拿验收矩阵当工程授权。
3. **状态锁：** 当前 12 组均为 `NOT_RUN`，现存工程能力默认 `NOT_VERIFIED`；`HOLD` 独立于技术验收 PASS。
4. **准入锁：** 任何测试/工程审查仍需依据最新权威 Engineering Handoff 单独批准。特别不得解除 `PHILIPPINES_INSTALL = HOLD`、`LOCAL-P-R1 = FAIL/HOLD` 及其他未解除 Gate。
5. **Owner 冻结：** Product Owner 已批准 v0.2 内容，作为 v1.0 验收基线正式冻结。无需重审 59 项需求；断言仍需工程执行和证据证明。

## 9. Owner Approval & Freeze Record

- **Decision:** Product Owner 于 2026-11-07 明确批准 `ACCEPTANCE_MATRIX v0.2` 的内容。
- **Formal baseline:** `ACCEPTANCE_MATRIX.md v1.0 — FROZEN`。原 59 条 Requirement 追踪、34 个 AC 场景与 `AS-01`～`AS-12` 十二组原子断言内容保持不变；本次仅更新文档状态、审批语句和冻结记录。
- **Authority:** 验收合同冻结不等于工程 PASS；所有场景仍 `NOT_RUN`，工程能力仍 `NOT_VERIFIED`，工程审查/测试/修复/构建/发布权限仍 `NOT_GRANTED`。
- **Relationship:** `DECISIONS.md` 八项 FROZEN 决策和 `PRD.md v1.0 FROZEN` 仍是上位产品约束，当前矩阵不修改它们。
- **Production safety:** `PHILIPPINES_INSTALL = HOLD`、`LOCAL-P-R1 = FAIL/HOLD`、`ARCHITECTURE_EXCEPTION = BLOCKED`、`A1_ACTIVATION_BLOCKED = TRUE`、`A2 = NOT_APPROVED` 及其他尚未解除的 Production HOLD 继续有效。
