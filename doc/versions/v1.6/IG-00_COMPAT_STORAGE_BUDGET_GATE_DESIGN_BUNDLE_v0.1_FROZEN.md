# DopaMatrix 1.6-A
# IG-00 COMPAT + STORAGE + BUDGET Gate Design Bundle v0.1
## FROZEN — Owner-Approved Design Record

**Document status:** `OWNER_APPROVED / FROZEN`  
**Decision:** `IG-00-COMPAT-STORAGE-BUDGET-DESIGN-FREEZE v0.1`  
**Approved baseline:** `IG-00_COMPAT_STORAGE_BUDGET_GATE_DESIGN_BUNDLE_v0.1_FOR_OWNER_REVIEW.md`  
**Prior baseline:** `IG-00_COMPAT_STORAGE_BUDGET_GATE_DESIGN_BUNDLE_v0.1_R1`  
**Finalization mode:** `DOCUMENT_ONLY / NO_NEW_SOURCE_AUDIT`  
**Finalization date:** `2026-11-18` (Asia/Shanghai; execution clock: 2026-11-18 06:05:34 UTC)  
**Owner approval of this Design Freeze:** `APPROVED`  
**Decision effect:** `DESIGN FREEZE EFFECTIVE`  
**Implementation authority:** `NOT_GRANTED`

> 本文是经 Product Owner 明确批准的 Frozen Design Record，不构成工程实施授权。
>
> Owner Statement：“批准 IG-00-COMPAT-STORAGE-BUDGET-DESIGN-FREEZE v0.1，保留所有未关闭 Gate 与未授权工程边界。”
>
> 本次仅使设计冻结生效，不授权工程实施、测试、Native Process、真实媒体、SQLite/DDL、Build、Install、Production、Git Commit/Push 或 Release。

本文仅依据上述 Owner 明确批准，将已通过 Owner Review 的设计整理为 Frozen Design Record，不新增工程方案，不重新执行 AUD-01/AUD-03，不重新审计 Frozen Architecture 或 Closed Phases。所有源码、Git、哈希及历史测试引用均继承原 Bundle，不是本次 Finalization 的新核验结果。

冻结范围仅为 COMPAT、STORAGE、BUDGET、SEED ALLOWLIST 的设计、已批准边界、未验证项的记录及其处理边界、后续 Gate 顺序、Candidate File Scope 和明确的 NOT_AUTHORIZED 边界。冻结未验证项不等于将其验证为通过；冻结候选文件范围不等于文件已存在或获准创建。

---

## 1. Executive Summary and Frozen Design Scope

本次 Owner 已批准有条件的最小 Design Contract 冻结；这不是工程完成、运行资格或发布结论。所有条件与未授权边界继续生效。

| 设计域 | 本文收口范围 | 未闭合条件 | 当前实施授权 |
|---|---|---|---|
| COMPAT | 现有 Main Runner 的可选、有界、双通道 Observer；窄 Q 逻辑复用边界 | Windows 读取兼容、完整观察、故障与旧调用回归；G1 独立阻断 | `NOT_GRANTED` |
| STORAGE | 每 Tenant SQLite 内独立资格记录；身份、Generation、事务、Readiness 和恢复边界 | Schema Preparation、可信授权上下文、Restore barrier、回滚验收 | `NOT_GRANTED` |
| BUDGET | 已冻结的分阶段测量框架、指标与判定口径 | 正式数值未建立；Native 测量前置条件未满足 | `NOT_GRANTED` |
| SEED ALLOWLIST | 静态入口清单、Backend Gate 要求、实际 SOP 未知边界 | 菲律宾实际 SOP、后端限制、健康正向路径验证 | `NOT_GRANTED` |

辅助 PROFILE 域保留 S0-E 与 S0-OPS 的区分，不新增支持格式承诺。

本文证据标签含义：

- `EXISTING_FACT`：继承 R1 的限定静态或历史证据，不表示本次运行核验。
- `DESIGN_PROPOSAL_READY`：原 Bundle 的设计就绪标签；本文已获设计冻结批准，但该标签不表示工程实施、测试或运行资格通过。
- `EVIDENCE_REQUIRED`：需要后续独立授权的证据。
- `OWNER_OR_ADR_GATE_REQUIRED`：不能由本次文档整理关闭的审批依赖。
- `NOT_VERIFIED`：未证实，不得升级为 PASS。

---

## 2. Inherited Frozen Authority and Non-Authorization

### 2.1 Inherited decisions — unchanged

必须继承且不得修改、重解释或重新设计：

- D16-001～D16-006，包括 D16-004-A/B/C。
- AUD-03-D1-D2 v1.0。
- IG-00 Owner Decision Packet v0.1，OD-01～OD-04。
- IG-00 DD2 v0.1，DD2-01～DD2-05。
- IG-00 AUTH-ACK Owner Resolution。
- AUTH-ACK-01A Owner Gap Resolution v0.1。
- Frozen Architecture、Closed Phases 及所有未解除的工程/生产 HOLD。

AUTH-ACK 的两项选择必须分别表述：

```text
AUTH-ACK-01 = Option B
  Consume an existing trusted authorization authority.
  No second Membership Authority or temporary local issuer.

AUTH-ACK-01A = Option C Gap Resolution
  No reusable source found in the reviewed RC2 scope.
  External authority status remains UNKNOWN.
  This does not amend AUTH-ACK-01 Option B.
```

同时继承 AUTH-ACK-02 在线授权边界、AUTH-ACK-03 官方 Tauri 客户端仅为未来 Recover Credential Producer 候选的限制。客户端能力不等于服务端授权。

### 2.2 Preserved blocked state

```text
EXTERNAL_CONTROL_PLANE = UNKNOWN
TRUSTED_AUTHORIZATION_SOURCE = NOT_VERIFIED
ACK = FAIL_CLOSED
RECOVER = UNAVAILABLE
AUTH-ACK-01B = NOT_ENTERED

G1_UNKNOWN_CUSTODY = BLOCKED
PHILIPPINES_INSTALL = HOLD
PRODUCTION_HOLD = UNCHANGED
```

不能将“在已审 RC2 范围未找到可复用来源”写成“外部权威不存在”。不能设计假定 Issuer 的 Adapter，也不能创建第二套 IAM、Issuer 或 Membership Authority。

### 2.3 Prohibited execution — unchanged

当前仍禁止：

- 工程源码、测试、配置及冻结合同修改。
- Native Test、Helper 或媒体进程执行。
- Real Media Execution 或真实客户素材访问。
- SQLite DDL、Migration、Database Mutation 或真实数据库访问。
- Build、Package、Installer、Install。
- Production Data Operation 或菲律宾设备操作。
- Git Stage、Commit、Push、Tag、Merge 或分支/Worktree 变更。
- Release、IG-01-A/IG-02-B 实施以及 AUTH-ACK-01B。

本次只允许生成本文和配套 Freeze Record，不授权其他文件变更；原 FOR_OWNER_REVIEW 文档及 Change Summary 原样保留。

---

## 3. Repository and Evidence Baseline

### 3.1 Inherited repository readback

下表是原 Bundle 的已记录读回，不是本次重新检查：

| 项目 | Main | Candidate Q |
|---|---|---|
| Branch | `fix/rc2-final-render-reliability` | `fix/rc2-source-media-integrity-p0` |
| HEAD | `6fb87450a6b06aaf8f32a0636990f47dcf9ba62e` | `7a7cf489c650bc7dfdb7f1c88a7d40c070cffb76` |
| Tracked Worktree | CLEAN | CLEAN |
| Index | EMPTY | EMPTY |
| Untracked | 仅 `doc/versions/v1.6/DECISIONS.md` | 无 |

原 Bundle 最终十二项 Git 只读查询 Native Exit 均为 0。本次没有重新执行 Git 查询，不对随后环境变化作新证明。

Handoff：`.codex-local/handoffs.md`，53,243 bytes，SHA256：

`2EF1725619E0319D7158DD79F1B8C32575BEB41FEEAD2D21CD5D26B3FA23FA22`

Main AGENTS SHA256：

`1513CB2B78E22850697D4F75809E77E7125EF4DE485747E1E11B32CA53ED7645`

Handoff 内 Main `72b7b0f...` 是较早历史快照。原 Bundle 按任务指定及实际 Git 读回确认 Main `6fb8745...`，不能将该维护源码身份视为历史 Candidate P 已认证制品，不能继承 Candidate P/Q 的发布资格。

### 3.2 Reference roots

- `M/`：`E:/dopaworkspace/dopamatrix-desktop/`。
- `Q/`：Main 下 `.codex-local/worktrees/source-media-integrity-q0/`。
- `D/`：`E:/dopaworkspace/dopamatrix-v1.6-docs/doc/versions/v1.6/`。
- `R/`：Main 下 `.codex-local/review/v1.5.0-rc2-source-media-integrity-q1a/`。

### 3.3 Product evidence references

| 文档 | 已有相关位置 |
|---|---|
| `D/DECISIONS.md` | D16-001～006 各冻结合同 |
| `D/PRD.md` | 需求 53–65；冻结记录 250–255 |
| `D/ACCEPTANCE_MATRIX.md` | 21–36、236–257 |
| `D/AUD-03-D1_SEED_IMPORT_GATE_CONTRACT.md` | Layer C/Q 20–40；PROFILE 88–105；IG-T 210–233；冻结 253–257 |
| `D/IG-00_OWNER_DECISION_PACKET_v0.1_FROZEN.md` | COMPAT 44–78；STORAGE 82–128；BUDGET 202–298 |
| `D/DopaMatrix_1.6_IG-00-DD2_OWNER_RESOLUTION_PACKET_v0.1_FROZEN.md` | COMPAT 33–50；Restore/Schema 105–140 |
| `D/AUTH-ACK-01A_OWNER_GAP_RESOLUTION_v0.1_OWNER_APPROVED.md` | 选择及含义 20–70；阻断 72–95；恢复条件 117–155 |

AUTH-ACK-01A Gap Resolution 已记录大小 11,492 bytes，SHA256：

`C0096494B85219A6B76838367A9D951023F94F8D1446AD24C055189312B6D333`

原 Bundle 对选定源码、AGENTS、Handoff、参考副本及七份 Docs Authority 文件共 22 条哈希记录的最终复核一致。该范围不是整仓库全量审计，本次不扩大或重做。

---

## 4. PROFILE — S0-E versus S0-OPS

### 4.1 Static and historical facts

| 输入类别 | 已有证据 | 资格限制 |
|---|---|---|
| MP4/H.264 | Main UI 接受扩展名；Q 有完整逐帧遍历、流选择、计数核对和历史合成正向样例 | `HISTORICAL_TEST_ONLY`，不是 S0-OPS |
| MOV/H.264 | Main UI 接受 `.mov`；Q Binding 限定 MOV/MP4 demuxer 家族 | 代表性 MOV 兼容性 `EVIDENCE_REQUIRED` |
| HEVC/H.265 | 扩展名与合法 Codec 名称不能证明支持 | `NOT_VERIFIED`，不能将不支持写成损坏 |
| VFR | Q 历史无 B-frame VFR 合成样例有正向证据 | 不得据此认证实际手机范围 |
| B-frame | Q 历史 H.264 B-frame 合成样例有正向证据 | 仅有限历史证据 |
| VFR+B-frame | 一个历史合成样例完整遍历后因声明时长/解码包络差异保持 UNVERIFIED | 不 blanket reject，也不忽略证据差异 |

源码锚点：

- `M/web_ui/src/utils/assetConfig.js:ASSET_REGISTRY:18–23`。
- `M/web_ui/src/views/AssetsView.vue:文件选择/Import处理:154–205`。
- `M/src/api/routes_assets.py:compute_md5/import_asset:34–97`。
- `Q/src/services/source_media_integrity.py:DecodeEvidenceObserver.__call__:255–299`。
- 同文件：`LocalFFprobeAdapter._scan_frames:648–687`；`_census_prepared:760–830`。

历史证据：`R/CANDIDATE_Q1A_REAL_DECODER_ADAPTER_IMPLEMENTATION.md:91–123`。Q1-A 历史 Commit 为 `633c24b437624a7570274b20b3ea4f0c4d65e843`，见 `R/CANDIDATE_Q1A_CONTROLLED_LOCAL_COMMIT_REVIEW.md:35–48`。历史报告 66 passed / 21 subtests passed 不构成当前 Main PASS，也不自动认证包含后续变更的整个 Q。

### 4.2 Design objective and boundary

继承 D2：S0-E 从 MP4/H.264 实验起步，MOV/H.264 独立样例，HEVC 另行调查；VFR/B-frame 不能仅因存在而拒绝。可选音频不等于音频质量认证。

S0-OPS 必须独立绑定代表性素材、实际工具/安装包、受测阈值及运营补救 SOP。完整可解码的已剪短文件仍可能只满足技术检查，不能推导创意内容完整。

依据：`D/AUD-03-D1_SEED_IMPORT_GATE_CONTRACT.md:§4:88–105`。

### 4.3 Tools and unresolved evidence

原 Bundle 只读确认的 Main 工具文件：

| 文件 | Bytes | SHA256 |
|---|---:|---|
| `web_ui/src-tauri/bin/ffmpeg.exe` | 99,264,000 | `5AF82A0D4FE2B9EAE211B967332EA97EDFC51C6B328CA35B827E73EAC560DC0D` |
| `web_ui/src-tauri/bin/ffprobe.exe` | 99,066,368 | `192A1D6899059765AC8C39764FC3148D4E6049955956DC2029F81F4BD6A8972D` |

`M/web_ui/src-tauri/tauri.conf.json:bundle:30–31` 声明资源，但不能证明实际安装包包含正确文件或运行时选中了它们。Main 开发态 locator 可回退 PATH；Q Adapter 要求绝对路径且存在。依据：`M/src/utils/env_utils.py:get_ffmpeg_path:49–108`；`Q/src/services/source_media_integrity.py:LocalFFprobeAdapter._tool:520–527`。

仍缺：明确授权的菲律宾代表性原片、拍摄/导出来源、实际容器/Codec/Profile/位深/像素格式/旋转/时间基、短长片/大文件、VFR/B-frame/Edit List 组合，以及实际打包环境证据。

**后续 Gate：**受控分阶段资格确认；`S0-OPS = NOT_VERIFIED`。本文件不授权素材访问、工具执行或格式支持实现。

---

## 5. COMPAT Design Contract

### 5.1 Current static facts

Main Runner 已有同一 Popen 的双 Reader、Timeout/Cancel、既有 terminate/kill/wait、有限日志 tail 和 stdout progress callback；没有等价的双通道完整 Observer、有界观察队列、原始读取预算、累计观察预算及完整生命周期 Receipt。

`stdout_events = queue.Queue()` 未指定容量；有限日志 tail 不等于完整证据流有界，逐行迭代也不能证明任意无换行输出的原始缓冲区上限。

源码：`M/src/nodes/compositor.py:_run_bounded_media_process:322–407、409–490`；`_MediaProcessResult:68–73`；`_stop_and_reap_process:299–320`。

Q 最小候选复用单元：

| 单元 | 既有能力 | 不得推导 |
|---|---|---|
| `DecodeEvidenceObserver` | 有界数值状态、诊断与时间字段检查 | 资源回收已证明 |
| `evaluate_decode_evidence` | 组合完整扫描、观察、退出码、诊断、身份变化 | 不可信 attestations 已变可信 |
| `_compact_record/_scan_frames` | 明确流、Frame/Footer 数量核对 | 所有工具版本语法均兼容 |
| Binding/Freshness | SHA、工具/Policy、Stream census、使用重读 | 已是 Tenant 持久化 Proof |
| Q Observer Runner 分支 | 非阻塞队列、溢出标记、有限投递、继续 drain | 可原样复制替代 DD2 原始字节读取合同 |

锚点：`Q/src/services/source_media_integrity.py:238–372、648–687、711–731`；`Q/src/services/source_media_admission.py:BatchValidationSession.assert_fresh:312–333`；`Q/src/nodes/compositor.py:_run_bounded_media_process:391–412`。

Q 当前带长度的文本 `readline(limit+1)` 优于无界读行，但不等于 DD2-01 已冻结的固定原始字节分块、增量解码及原始字节预算。

### 5.2 Design objective

继承 OD-01 / DD2-01：仅在现有 Main Runner 增加向后兼容的 opt-in Observer；不创建第二套 Media Runner。

**Interface Sketch / Design Notation only；不是现有 API Contract，不是文件级 Implementation Authority。**

```python
_run_bounded_media_process(
    command,
    *,
    context,
    process_kind,
    timeout_seconds,
    started_stage=None,
    exited_stage=None,
    on_stdout_line=None,
    stream_observer=None,
    observation_limits=None,
) -> _MediaProcessResult
```

最小事件设计包含 channel、通道内 sequence、有界文本、原始字节数及解码字符数。预算维度包括原始读取块、记录组装 bytes/chars、Queue、累计原始字节/UTF-8 文本字节/字符/记录及投递批次。正式数值均为 `NOT_ESTABLISHED`。

原始字节、解码字符、UTF-8 文本字节是不同计量，不能互相冒充。

### 5.3 Reader and delivery boundary

```text
各通道唯一 Reader
 → 固定上限原始字节分块
 → 增量 UTF-8 解码
 → 追加前检查记录预算
 → 有界非阻塞入队
 → Runner 控制线程有限批次投递
 → 数值证据汇总
```

- 只保证各通道内部顺序，不承诺 stdout/stderr 全局时间顺序。
- 无 Observer 时保留原 Render/progress 调用、返回与异常合同。
- 初始 Adapter 不使用 progress；同时使用 Observer/progress 的组合不能未经验证默认为兼容。
- Callback 必须是受审查的非阻塞聚合器；有限批次不能中断一个已阻塞的 Callback。

### 5.4 Failure contract

| 条件 | 观察语义 | 资源边界 |
|---|---|---|
| Queue Full | 不可逆 incomplete，停止投递 | 可读时有界 drain/discard，走既有 teardown |
| 超长无换行记录 | 不继续累积，不认证截断记录 | 停止证据投递；不凭丢失记录声明完整 |
| Reader 异常 | EOF 未确认、non-PASS | 不伪造 EOF，不解决 G1 |
| Callback 异常 | opt-in typed observation failure | 已识别 Cleanup Failure 保留优先级 |
| Timeout/Cancel | 既有错误语义 | 不改 terminate/kill/wait |
| Native 非零 | 保留真实 returncode | 不变为健康 PASS |
| 未观察 Close/Handle | UNKNOWN / NOT_PROVEN | Observer 成功不能补齐 |

继承 DD2-01 的 Typed exception A，不重新选择结果对象方案。依据：`D/DopaMatrix_1.6_IG-00-DD2_OWNER_RESOLUTION_PACKET_v0.1_FROZEN.md:33–50`；Q 路径 `src/nodes/compositor.py:385–467、506–546`。

### 5.5 Unverified items, next Gate and authority

仍需独立审查/测试：Windows binary-pipe 兼容、零/无换行/异常 UTF-8、两通道溢出、Callback 失败、EOF、Timeout/Cancel、旧调用回归。

不新增 Native Owner，不增加 Process Handle Close，不改变 terminate/kill/wait、Task/Child/Attempt/Terminal，不把 `VALIDATED_COMPLETE` 当生产 Receipt。必要修正如跨越上述边界：`OWNER_OR_ADR_GATE_REQUIRED`，停止对应分支。

**当前实施授权：`NOT_GRANTED`。Native 测量仍受 G1 前置条件阻断。**

---

## 6. STORAGE Design Contract

### 6.1 Current static facts

| 能力 | 已有锚点 | 限制 |
|---|---|---|
| LocalAsset | `M/src/api/models.py:LocalAsset:266–290` | ID/MD5/Path/删除标志/manifest，不是当前资格 Head/Generation |
| Tenant DB | `runtime_paths.py:RuntimePaths.tenant_database_path:42–51`；`database.py:get_db:509–522` | Session 绑定不等于 Actor/Membership 授权 |
| 初始化 | `database.py:initialize_application_schema:412–421` | create_all/evolve_schema 不是资格 Readiness |
| Schema 演进 | `database.py:evolve_schema:141–185` | 失败记录后继续，不能证明资格存储就绪 |
| Backup | `backup_restore.py:_sqlite_online_backup:183–195` | 一致性快照不是当前有效资格 |
| 数据版本 | `backup_restore.py:create_backup_bundle:457–473` | Backup/Application Version 不是资格 Schema/Policy Version |
| Restore | `backup_restore.py:restore_backup_to_staging:690–747` | 有隔离目标/完整性核对，未证明资格恢复 barrier |

### 6.2 Design objective and settled storage direction

继承 OD-02：每 Tenant 独立 SQLite 内建立独立的小型资格记录。不重新选择存储架构，不将完整 Proof 优先塞入 LocalAsset.manifest，不建立 L3。

| 已比较方向 | 保留的设计判断 |
|---|---|
| LocalAsset 最小字段扩展 | 可复用 Tenant 数据边界，但不作为完整 Operation/Generation/Proof 主存储 |
| Tenant 独立 Proof Record | 同库短事务、独立状态/版本/Generation；继承已冻结推荐方向 |
| Server-owned Manifest | 另有 Tenant namespace、双写一致性、Backup/Restore 负担，不新增为资格 Authority |

依据：`D/IG-00_OWNER_DECISION_PACKET_v0.1_FROZEN.md:82–128`。

### 6.3 Qualification data and authorization boundary

最小设计字段组：

```text
Tenant + asset_id + source_revision + generation
proof_id + operation_id
SHA256 + actual size + selected stream
profile/policy/checker version + tool identity
status + bounded evidence summary + diagnostics reference
timestamps + ACK receipt binding
```

> 未来 Tenant 必须来自经批准、可验证的服务端授权上下文；不得信任 Body 自报 Tenant；当前实际授权来源仍为 UNKNOWN / NOT_VERIFIED。

这不是当前 Main 已具备该授权上下文的声明，不新增 IAM、Issuer、Membership Authority 或实现方案。

同 Tenant 内约束 Operation 唯一、Asset/Generation 唯一及一个当前 Head。长解码在 SQLite 写事务外；建立 Generation、使旧 Head 失效、条件提交使用短事务。旧结果须匹配当前 Head/Revision/Generation，不能覆盖新资格。

`source_revision` 只覆盖应用已知修改，不能替代实际字节 Freshness；相同 SHA 不授予跨 Tenant 复用权。

### 6.4 Status and activation boundary

`NOT_EVALUATED / PENDING / PENDING_ACK / REJECTED / UNVERIFIED / UNSUPPORTED_PROFILE` 均不是正常 Seed 资格。只有当前、授权、完成必要确认且 Fresh 的 PASS 才是候选资格。

继承 OD-03 Two-Phase Activation；ACK 不能代替技术证据、资源责任、持久化或 Source Freshness。当前授权来源未证明，因此 ACK 不能激活 PASS，Recover 不可用。不增加 Task Terminal State，不重做 ACK/CAS 协议设计。

### 6.5 Mutation consistency

| 操作 | 已有源码 | 设计要求 |
|---|---|---|
| Import/同 MD5 Revival | `routes_assets.py:import_asset:63–91` | 路径/版本变化撤销旧资格，不继承 PASS |
| Trash | `trash_asset:243–252` | 同事务使资格不可选及旧 Operation 失效 |
| Restore | `restore_asset:255–265` | 当前源重验/新 Generation，不只清除删除标志 |
| Purge | `purge_asset:268–277` | 明确 FK/墓碑/迟到 ACK；不自动清理素材 |
| DB Restore | `backup_restore.py:690–747` | 恢复前 non-ready，旧 PASS 不自动有效 |

### 6.6 Schema, restore and rollback boundary

继承 DD2-04/05：

- 独立、明确授权的离线 Schema Preparation；不借旧 create_all/evolve_schema 自动放行。
- 运行时 Readiness 检查缺表、未知版本、初始化失败或恢复 guard 失败时，拒绝资格及 Seed Admission，不重建客户数据。
- 历史 1.5 无 Proof 资产保持 NOT_EVALUATED，不自动回填 PASS，不重写 MD5/path。
- 不因二进制回滚自动删除资格表；Binary Rollback 不等于 Data Rollback。
- 恢复 SQLite 内的 Epoch 会随备份回退；必须证明可跨 DB Restore 和中断存活的可信 barrier/anchor。
- 未证明 barrier 时 Seed 受控 Restore 保持阻断。不声称检测任意外部 DB 替换或 DB+Anchor 同时回滚，不默认新增全局 DB、DPAPI Key 或备份系统。

依据：`D/DopaMatrix_1.6_IG-00-DD2_OWNER_RESOLUTION_PACKET_v0.1_FROZEN.md:105–140`。

### 6.7 Unverified items, next Gate and authority

Schema Preparation 入口、Readiness、FK/Purge、恢复 barrier、升级/回滚及授权上下文仍为 `NOT_VERIFIED / OWNER_OR_ADR_GATE_REQUIRED`。

**当前实施及 DDL 授权：`NOT_GRANTED`。设计方向不授权创建表、文件、CLI 或 Startup hook。**

```text
Schema Preparation = NOT_AUTHORIZED
DDL = NOT_AUTHORIZED
Migration = NOT_AUTHORIZED
Database Mutation = NOT_AUTHORIZED
```

---

## 7. BUDGET Design Contract

### 7.1 Current static facts

Main 有 Render/Probe 超时、轮询、Grace 和日志 tail 常量，见 `M/src/nodes/compositor.py:模块常量:27–35`。Q 有显式 provisional 预算结构，见 `Q/src/services/source_media_integrity.py:DecoderBudget:375–400`、`Q/src/services/source_media_admission.py:SessionLimits:90–109`。

这些不是 Seed Import 正式阈值，日志 tail 也不是累计观察上限。不得将原常量、历史 Fixture 值或经验值转写为正式资格数值。

### 7.2 Design objective and measurement dimensions

| 维度 | 后续需要的测量证据 |
|---|---|
| File size / duration | 实际 Bytes、声明时长、完整解码时间包络、输入组合 |
| Wall / decode time | Hash、Tool Hash、Metadata、Census、Full Decode、最终身份检查分阶段耗时 |
| CPU / memory | Backend/子进程 CPU、峰值 RSS、队列和记录缓冲峰值 |
| Timeout / cancellation | 触发、实际退出、Wait/Reap、Reader/EOF/Pipe/Handle 状态 |
| Concurrency | 同时扫描、排队、重复请求、无关 API 延迟 |
| stdout / stderr | 原始字节、字符、UTF-8 文本字节、记录数、最大记录、队列峰值/丢失 |
| Healthy positive path | 健康源在合格预算内完成，不通过永久拒绝制造 PASS |
| Classification | 损坏漏检、健康误拒、未知/不支持误分类 |

测量覆盖完整验证成本，不只覆盖 FFprobe 循环。Popen 创建及同步 OS 文件读不能被轮询预算声明为硬截止；轮询式体积检查不是 OS 配额。不得复用 Task pool 大小充当验证并发资格。

### 7.3 Staged plan — unchanged

| 阶段 | 设计内容 | 独立 Gate |
|---|---|---|
| Stage 0 Synthetic Design Preparation | 样例矩阵、指标、结果格式、失败判据；不生成 Fixture | 本文仅设计，不执行 |
| Stage 1 Isolated Synthetic Native Testing | 实际 Runner/Reader/观察/Timeout/Cleanup | 独立 Native 授权及 G1 前置条件；当前 BLOCKED |
| Stage 2 Packaged Environment Qualification | 实际包工具身份、语法、路径、资源 | 独立 Build/Package/Runtime 授权 |
| Stage 3 Representative Philippine Media | 获授权实际手机素材及误拒/漏检 | 素材范围与使用授权 |
| Philippines Device Qualification | 目标设备资源与运营闭环 | 独立设备授权；不等于安装批准 |

依据：`D/IG-00_OWNER_DECISION_PACKET_v0.1_FROZEN.md:202–298`。

### 7.4 Formal thresholds — not established

本次只冻结测量方法，不冻结未经测量的正式数字阈值。

```text
File Size Threshold = NOT_ESTABLISHED
Duration Threshold = NOT_ESTABLISHED
CPU Threshold = NOT_ESTABLISHED
Memory Threshold = NOT_ESTABLISHED
Concurrency Threshold = NOT_ESTABLISHED
Timeout Threshold = NOT_ESTABLISHED
Observation Output Threshold = NOT_ESTABLISHED
```

| 正式阈值 | 状态 |
|---|---|
| File size limit | `NOT_ESTABLISHED` |
| Duration limit | `NOT_ESTABLISHED` |
| CPU limit | `NOT_ESTABLISHED` |
| Memory limit | `NOT_ESTABLISHED` |
| Concurrency limit | `NOT_ESTABLISHED` |
| stdout / stderr / combined observation limits | `NOT_ESTABLISHED` |
| Per-file / process / total timeout thresholds | `NOT_ESTABLISHED` |
| API latency acceptance limit | `NOT_ESTABLISHED` |

必须经过后续独立授权的受控测量，再由 Owner 批准；本文件不填入任何具体正式数值。

### 7.5 Unverified items, next Gate and authority

目标环境性能、健康正向预算、故障清理及实际包行为均未建立资格。Stage 1 必须先满足既有 Native Custody 授权条件，不能绕过 G1。

**当前测试、测量、媒体及设备执行授权：`NOT_GRANTED`。**

---

## 8. SEED ALLOWLIST Design Contract

### 8.1 Terminology and current static facts

`STATIC_ENTRY_CONFIRMED` 仅表示静态代码入口存在，不代表 Runtime Qualification、Seed Qualification 或 Production PASS；不得改写为 Runtime Qualified、Seed Qualified 或 Production PASS。

```text
S0-E != S0-OPS
S0-OPS / Philippines SOP / Actual Device Qualification = NOT_VERIFIED
Philippines Install / Production = HOLD
```

| 入口 | 继承源码证据 | 状态 | 现有边界及设计处置 |
|---|---|---|---|
| DAM UI Import | `M/web_ui/src/views/AssetsView.vue:154–205` | `STATIC_ENTRY_CONFIRMED` | UI 扩展名后提交路径；未来必须 Backend IG-01 |
| Direct Import API | `M/src/api/routes_assets.py:import_asset:42–97` | `STATIC_ENTRY_CONFIRMED` | 同一 MD5 注册函数，无完整视频资格；与 UI 同 Gate |
| Revival | 同文件 `63–77` | `STATIC_ENTRY_CONFIRMED` | 更新路径/元数据并复活；重验并撤销旧资格 |
| Trash Restore | `restore_asset:255–265` | `STATIC_ENTRY_CONFIRMED` | 当前恢复删除标志；不得继承 PASS |
| DSL / Manual | `routes_dsl.py:submit_dsl:4437–4461`；`submit_manual:4618–4655` | `STATIC_ENTRY_CONFIRMED` | 有 Tenant/规划检查，未建立 D2 持久资格；注册资产+IG-02 才可候选启用 |
| Pinned Hash | `dsl_parser.py:_load_locked_hash_assets:248–292` | `STATIC_ENTRY_CONFIRMED` | Hash/未删除查询不是健康证明；同 IG-02 |
| Directory Pool | `asset_select.py:execute:298–314`；`asset_provider.py:get_clips_for_duration:375–407` | `STATIC_ENTRY_CONFIRMED` | DB 无结果可 fallback；Seed 禁用或另行完整 Gate，不静默 fallback |
| Legacy API | `src/api/routes.py:submit_task:76–104` | `STATIC_ENTRY_CONFIRMED` | 准入后调度 run_matrix_job；未覆盖入口不进 Seed Allowlist |
| CLI | `run_factory.py:build_pipeline:103–145`；`run_matrix_factory.py:_run_single_matrix:224–238` | `STATIC_ENTRY_CONFIRMED` | 直接 Pipeline/Pool，不作为正常 Seed 入口 |

补充证据边界：

- `M/src/api/routes_assets.py:get_assets:137–165` 的正常列表主要按未删除等业务条件，不是资格 PASS。
- `M/src/nodes/asset_select.py:_scan_user_asset_dir:104–108` 当前返回 None，附近旧扩展名/大小常量不能被当作当前 Import 限制。
- `Q/src/api/routes_dsl.py:render_worker:2920–2945` 的 Source Admission 在 Worker Context 建立后、TTS 前，不是 Import Gate，也不代替 Task 接受前 IG-02。
- 任意 pinned-path API 未确认，不虚构端点。

### 8.2 Design objective and boundary

继承 D2：候选正常路径为 Backend 合格 DAM Import/Revival → 注册资产 DSL/Manual → IG-02 Task Admission 与 Actual-use Freshness。

前端限制不能替代 Backend Enforcement。未覆盖 Legacy/Pool/CLI 的 Seed 限制必须准确限定获批 Seed 范围，不能全局删除 1.5 Legacy 行为。

IG-01-A 完成不代表 IG-02-B 完成。任何未合格源不能通过直接 API、Hash、旧记录、Restore/Revival 或缓存绕过。

### 8.3 Unverified items, next Gate and authority

菲律宾实际操作入口/SOP、路由限制、旧客户端行为和健康正向工作流仍为 `NOT_VERIFIED / EVIDENCE_REQUIRED`。没有真实 SOP 证据，不推断运营人员实际走哪一路。

后续须分别批准精确 Seed 范围、Backend 执行及验收。不能因本文件存在就启用/禁用任何路由。

**当前路由修改、IG-01-A/IG-02-B 实施及运营变更授权：`NOT_GRANTED`。**

---

## 9. Integrated Design and Dependency Contract

```text
明确且安全的输入范围
 → 现有 Main Runner 的 opt-in bounded Observer
 → 窄 Q evaluator / selected-stream Adapter
 → 技术证据与资源状态分别判断
 → Tenant 独立资格 Operation / Proof Record
 → 当前授权未证明：non-PASS，ACK Fail Closed
```

正常候选资格必须同时满足：完整技术证据、当前源字节/流/版本绑定、真实 Tenant/调用方授权、Schema/Proof 持久化及当前 Generation、必要资源正向证据，以及经授权的两阶段确认。

任一条件不能被其他条件替代。Q ValidationRecord、日志 PASS、HTTP 成功、Observer 成功均不是生产资格或 Custody Receipt。

IG-01 Import/Revival Eligibility 与 IG-02 Task Admission/Actual-use Freshness 是独立 Gate。方案不含新 IAM、新 Native Owner、新媒体 Runner、后台验证框架、全 Q 合并或历史回填。

---

## 10. Candidate File Scope — No File-Level Authority

以下仅为未来审批候选，不是本文件授权修改/创建的文件清单。

| 切片 | 未来候选范围 | 限制 |
|---|---|---|
| COMPAT | `src/nodes/compositor.py`；独立 Observer 隔离测试 | opt-in、旧调用回归；不改 Native Owner |
| Q narrow adaptation | `src/services/source_media_integrity.py` | **未来 Main 候选文件，可能由 Q-derived narrow logic 提取/重构；该文件当前存在于 Q 证据范围不等于 Main 已存在，也不构成创建或修改授权。** 相应测试也仅为未来候选。 |
| STORAGE | `src/api/import_qualification.py`；必要 database.py Readiness 接线及隔离测试 | **future candidate new file / not currently authorized / not existing-by-assumption**；不得假定 Main 已有该文件。DDL/Preparation 另批，避免自动加入旧 create_all。 |
| 后续 IG-01 | `routes_assets.py`、`schemas.py`、`AssetsView.vue` | 不授权本轮实施 |
| 后续 IG-02 | `dsl_parser.py`、`routes_dsl.py` 的准确准入/使用边界 | 不借机修改 Child/Terminal |
| Schema/Restore | Preparation 入口、Startup hook、Backup/Restore 接线 | 精确范围另批，不自动扩展 CLI/RuntimePaths/全局存储 |

```text
src/services/source_media_integrity.py = Future Main Candidate
Q file exists != Main file exists != Implementation authorized
src/api/import_qualification.py = Future Candidate New File
```

不能为文件最少而把 Schema、HTTP、Decoder、Native Custody 混成新框架。最终实施文件清单必须随独立切片批准；本次冻结的是候选范围，不是文件级实施授权。

---

## 11. Frozen Contract Impact and Acceptance Traceability

| 合同 | 本文保持的边界 |
|---|---|
| D16-001 | 单 Task/Batch2、无自动失败重提、全部 HOLD；不将完整 Control Plane 建设混入本轮 |
| D16-002 | 1.5 数据保护，Schema/Restore/回滚独立验收，无真实目录清理/迁移 |
| D16-003 | 健康正向、坏素材阻断、错误分类、人工替换后重验 |
| D16-004-A/B | Tenant 强制隔离，相同 Path/SHA 不产生跨 Tenant 权限 |
| D16-004-C | 不新增切换期间后台验证或 Quiescence 声明 |
| D16-005 | 不建立第二套 Authority；Header/CORS/Tauri 身份不替代授权 |
| D16-006 | 资格记录不是 L3，不改历史事实、不自动回填 |
| OD-01～04 / DD2-01～05 | 全部选择与条件保持，不重新设计 |
| AUTH-ACK | 01=Option B；01A=Option C Gap Resolution；不进入 01B |
| G1 | UNKNOWN custody BLOCKED；Observer 不能关闭该 Gate |

原证据锚点：`D/DECISIONS.md:D16-001:39–93`；`D16-002:175–208、249–291`；`D16-003:461–473`；`D16-004-A:727–739`；`D16-004-B:947–1007、1070–1096`；`D16-004-C:1197–1245`；`D16-005:1506–1524`；`D16-006:1846–1877、1995–2019`。

| 设计域 | 既有追溯，不新增需求 |
|---|---|
| PROFILE / COMPAT / BUDGET | A-IMP-01/02；AC-A01/A02/A08；IG-T01～06/T15 |
| STORAGE / Freshness | A-IMP-03/04；AC-A03；IG-T08/09/13 |
| ALLOWLIST | IG-T10/T12 |
| Human replacement | A-REC-02；AS-12；IG-T11/T16 |

依据：`D/PRD.md:53–65`；`D/ACCEPTANCE_MATRIX.md:21–36、236–248`；`D/AUD-03-D1_SEED_IMPORT_GATE_CONTRACT.md:210–233`。测试未在本次执行，设计审阅不改变冻结验收基线。

---

## 12. Unresolved Dependencies and Subsequent Gates

| 依赖 | 状态 | 受影响范围 |
|---|---|---|
| 实际授权来源、可信验证材料及消费合同 | `EVIDENCE_REQUIRED / NOT_VERIFIED` | ACK/Recover/PASS 激活 |
| G1 UNKNOWN custody | `BLOCKED` | Native 测量及依赖该安全结论的接线 |
| 原始字节读取/完整两通道观察兼容 | `NOT_VERIFIED` | Main COMPAT 资格 |
| Schema Preparation / Readiness | `OWNER_OR_ADR_GATE_REQUIRED` | 资格持久化 |
| Restore barrier 跨恢复/中断存活 | `NOT_VERIFIED` | Seed Restore 恢复资格 |
| MOV/HEVC/手机实际组合及 S0-OPS | `EVIDENCE_REQUIRED` | 正式格式支持 |
| 正式资源阈值 | `NOT_ESTABLISHED` | BUDGET 资格 |
| 实际安装包工具/语法/路径 | `NOT_VERIFIED` | Packaged Runtime |
| 菲律宾 SOP/目标设备/Backend Allowlist | `NOT_VERIFIED` | 最终 Seed 运营资格 |

仍需 Owner 处理的原有事项，不新增决策：

1. 授权分支仅在 Owner 提供可识别上游权威证据或另行授权 ADR 后重新考虑；不假定存在/不存在，不建立本地 Issuer。依据 Gap Resolution 117–155。
2. Schema Preparation/Restore barrier 的维护入口、可信性、失败恢复及独立验收范围。
3. G1 条件满足后，分阶段测量、工具、素材和设备的精确授权；依据测量另批阈值。

原顺序的 Owner Review 与明确 Design Freeze 批准步骤现已完成；后续仍须分别处理既有前置 Gate 与精确授权，不自动启动任何后续动作。设计批准本身不开放 Native Test、DDL 或实施。未满足 G1 不启动 Stage 1；未满足授权边界不激活 PASS。

### Frozen open-gate ledger

| Gate | Frozen Status |
|---|---|
| G1 UNKNOWN custody | `BLOCKED` |
| External Control Plane | `UNKNOWN` |
| Trusted Authorization Source | `NOT_VERIFIED` |
| ACK | `FAIL_CLOSED` |
| Recover | `UNAVAILABLE` |
| AUTH-ACK-01B | `NOT_ENTERED` |
| COMPAT Runtime Qualification | `NOT_VERIFIED` |
| Schema / Restore Barrier | `NOT_VERIFIED / NOT_AUTHORIZED` |
| Resource Thresholds | `NOT_ESTABLISHED` |
| S0-OPS | `NOT_VERIFIED` |
| Philippines SOP / Actual Device Qualification | `NOT_VERIFIED` |
| Philippines Install | `HOLD` |
| Production | `HOLD` |

---

## 13. Owner Approval, Effect and Stop Record

**Decision:** `IG-00-COMPAT-STORAGE-BUDGET-DESIGN-FREEZE v0.1`  
**Owner Decision:** `APPROVED`  
**Finalization Date:** `2026-11-18` (Asia/Shanghai)

**Owner Statement:**

> 批准 IG-00-COMPAT-STORAGE-BUDGET-DESIGN-FREEZE v0.1，保留所有未关闭 Gate 与未授权工程边界。

**Decision Effect:** `DESIGN FREEZE EFFECTIVE`  
**Implementation Authorization:** `NOT GRANTED`

Owner 批准仅使设计冻结生效，不制造任何新的技术证明或执行权限，不修改此前 D16、D2、OD、DD2 或 AUTH-ACK 决策。

```text
DOCUMENT_STATUS = OWNER_APPROVED / FROZEN
DESIGN_FREEZE_APPROVAL = APPROVED
DESIGN_FREEZE_EFFECTIVE = TRUE
Decision Effect = DESIGN FREEZE EFFECTIVE
Implementation Authorization = NOT GRANTED

ENGINEERING_IMPLEMENTATION = NOT_AUTHORIZED
IMPLEMENTATION_AUTHORITY = NOT_GRANTED
NATIVE_TEST = NOT_AUTHORIZED
NATIVE_PROCESS_EXECUTION = NOT_AUTHORIZED
REAL_MEDIA_EXECUTION = NOT_AUTHORIZED
DATABASE_ACCESS = NOT_AUTHORIZED
SCHEMA_PREPARATION = NOT_AUTHORIZED
DDL = NOT_AUTHORIZED
MIGRATION = NOT_AUTHORIZED
DATABASE_MUTATION = NOT_AUTHORIZED
BUILD = NOT_AUTHORIZED
INSTALL = NOT_AUTHORIZED
PRODUCTION_DATA = NOT_AUTHORIZED
EXTERNAL_SERVICE_ACCESS = NOT_AUTHORIZED
GIT_STAGE = NOT_AUTHORIZED
GIT_COMMIT = NOT_AUTHORIZED
GIT_PUSH = NOT_AUTHORIZED
TAG = NOT_AUTHORIZED
RELEASE = NOT_AUTHORIZED

AUTH-ACK-01 = Option B
AUTH-ACK-01A = Option C Gap Resolution
EXTERNAL_CONTROL_PLANE = UNKNOWN
TRUSTED_AUTHORIZATION_SOURCE = NOT_VERIFIED
ACK = FAIL_CLOSED
RECOVER = UNAVAILABLE
AUTH-ACK-01B = NOT_ENTERED

G1_UNKNOWN_CUSTODY = BLOCKED
S0-OPS = NOT_VERIFIED
PHILIPPINES_SOP = NOT_VERIFIED
ACTUAL_DEVICE_QUALIFICATION = NOT_VERIFIED
PHILIPPINES_INSTALL = HOLD
PRODUCTION = HOLD
PRODUCTION_HOLD = UNCHANGED
```

本次仅读取此前已批准的 FOR_OWNER_REVIEW 文档并整理两份指定文档，未读取新工程范围，未重跑 Audit，未修改工程源码、测试、配置、Handoff、AGENTS、DECISIONS、PRD、D16、DD2 或 AUTH-ACK Owner Resolution。未运行测试、Native Helper、媒体进程或应用，未访问真实媒体、客户素材、SQLite、外部服务或 Credential/Secret，未执行 DDL/Migration、Build、Install、Git mutation 或 Production 操作。文档读取命令不是 Native Test 或业务进程实验。

唯一输出：

1. `IG-00_COMPAT_STORAGE_BUDGET_GATE_DESIGN_BUNDLE_v0.1_FROZEN.md`
2. `IG-00_COMPAT_STORAGE_BUDGET_GATE_DESIGN_BUNDLE_v0.1_FREEZE_RECORD.md`

不创建新的 Owner Decision Packet，不进入 AUTH-ACK-01B、IG-01-A 或 IG-02-B。此前 FOR_OWNER_REVIEW 文档与 Change Summary 不修改。

**STOP — Design Freeze 已按 Owner 明确批准记录生效；等待 Product Owner Review，不自动启动任何工程、测试或发布任务。**
