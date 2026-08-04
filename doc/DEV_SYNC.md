# ⚡ DopaMatrix 战术同步看板 (DEV_SYNC)

> **当前冲刺目标 (Sprint Goal)**: 跑通 V1.1 (Webhook 异步闭环) 与 V1.2 (多巴胺音频混音 UI) 的全链路测试。
> **最后同步时间**: 2026-03-24

---

## 📡 各战线 (AI 窗口) 状态概览

- 🟢 **[核心架构窗]** (当前进度)：已完成 BGM/SFX 的底层 SQLite 扩展与 FFmpeg `amix` 多轨延后混音重构。
- 🟡 **[网络通信窗 (v1.1)]** (当前进度)：Webhook 代码已写入，Ngrok 尚未联调测试。
- 🟡 **[前端增长突击窗]** (当前进度)：已下发“音频专属素材库”与“声音情绪下拉框”的重构指令，等待代码融合。

---

## 🛠️ 当前执行清单 (Active Tasks)

### 1. 底层引擎升级 (BGM & SFX 混音) - [已封板 Commit]
- [x] `models.py`: 扩展 `LocalAsset` 类型，新增 `emotion_tag` 字段。
- [x] `timeline.py`: 扩展 `AudioTrack` 支持 `audio_type` (bgm, sfx, tts)。
- [x] `compositor.py`: 重构 `_render_variant`，实现 BGM 降噪闪避与 `amix` 混音。
- [x] `assembler.py`: 增加基于 `emotion_tag` 的 LRU (最少使用优先) 抽卡逻辑。
- [x] 数据库迁移: 执行 `db_migrate_v1.py` 强行追加字段。

### 2. 前端 UI 升级 (听觉资产大盘) - [进行中]
- [ ] 侧边栏/顶部 Navbar: 全局品牌重命名`DopaMatrix`。
- [ ] `AssetLibrary`: 新增 [🎵 听觉资产] Tab，区分 BGM 与 SFX。
- [ ] `AudioAssetCard.vue`: 新增声波纹卡片，支持疲劳度显示与情绪打标 (如 `asmr`, `epic`)。
- [ ] `TaskSubmitBar.vue`: 新增“声音情绪”下拉框，并实现 JSON payload 的 `audio_scape` 正确拼接。

### 3. Webhook 与网络联调 - [待测试]
- [x] 后端 `main.py` / `services.py`: 写入任务完成后的 Webhook POST 触发逻辑。
- [ ] 本地测试: 使用 Ngrok 穿透本地端口，造一条带有 `asmr` 标签的 BGM 测试数据，触发一次完整的渲染任务。
- [ ] 接收验证: 确认 Webhook 接收端（如 TG Bot 或测试服务器）成功收到含 `file_hash` 的结案报告。

### 4. V1.1 桌面端安全架构与打包闭环 - [待确定 / 部分完成]
- [x] `run_matrix_factory.py`: 将底层渲染调度从多进程 (`ProcessPoolExecutor`) 降维为多线程 (`ThreadPoolExecutor`)，解决打包后 spawn 机制死锁。
- [x] `env_utils.py`: 实现 `get_ffmpeg_path` 嗅探器，解决 Tauri Sidecar 打包后 `bin/` 目录丢失问题。
- [x] `tts_node.py` 及所有节点: 彻底清剿 CLI 工具调用（如 `edge-tts`），改为纯 Python 内存级调用，消除 `[WinError 2]`。
- [x] `subprocess` 调用: 全局补全 `CREATE_NO_WINDOW` 标志，压制 Windows 渲染时的黑框弹窗闪烁。
- [x] `build_backend.py`: 融合 `clean_for_release.py`，实现发版前 output 清理与 SQLite 疲劳度自动重置。
- [x] `main.py`: 生命周期阶段注入 `.env` 物理自毁代码，防堵测试 API Key 泄漏。
- [ ] `database.py` / `routes_settings.py`: 建立 `app_settings` 表，打通大模型 API Key 本地存取接口。

### 5. 前端设置页 (BYOK 机制) - [待确定]
- [ ] `Settings.vue`: 新增用户自带密钥 (Bring Your Own Key) 配置面板，对接 `/api/v1/settings/llm`。

### 6. 发版与协同基建 - [待确定]
- [x] `.github/ISSUE_TEMPLATE`: 建立中英双语 Bug Report 模板，规范化跨国团队测试反馈。
- [x] `CHANGELOG.md`: 确立语义化版本记录规范。
- [ ] `tauri.conf.json`: 配置 GitHub Releases 节点，打通 OTA (Over-The-Air) 静默热更新全链路。

### 6. 智能素材库与打标基建 (Smart DAM)
- [ ] `SQLite`: 表结构升级，新增 `shot_type`, `scene`, `emotion_trigger`, `decision_flow_stage` 等语义字段。(待确定)
- [ ] `AssetSelectNode`: 引入 Hook/Body 物理隔离抓取逻辑，以及安全查重裂变数学公式拦截。(待确定)
- [ ] 桌面端 UI: 素材“疲劳度血条”可视化，以及 Hook 身份专属设置按钮。(待确定)
- [ ] 桌面端 UI: 素材库新增“✨ AI 变异车间”弹窗入口，预留 API 接口。(待确定)

### 7. 测试优先与音画对齐重构 (Test-First & Audio-Driven)
- [ ] 前端 UI: 将 Prompt 中的时长提示废除，改为 `[短平快]`, `[标准]`, `[深度]` 专属下拉框。(待确定)
- [ ] `ScriptGenNode`: 注入底层 Prompt，强制大模型按所选下拉框精准控制单词数量。(待确定)
- [ ] `CompositorNode / AssemblyNode`: 废除 1变3 渲染，引入首发测试语言 (Test-Language) 参数，仅挂载单一语音与字幕。(待确定)
- [ ] `CompositorNode`: 强制以音频轨（TTS）时长作为 `-shortest` 截断基准，实现音画绝对对齐结束。(待确定)

### 8. 桌面端体验与单体架构剥离 (Desktop UX & Monorepo)
- [ ] 耗时预估: 后端实现 $E = \lceil B/C \rceil \times D \times k$ 算法接口，前端提交流程增加拦截预估弹窗。(待确定)
- [ ] 目录重构: 将原 `web_ui` 改造成 Tauri 的多包结构 (`clients/content-desktop` 与 `clients/ua-desktop`)，实现品牌隔离。(待确定)
- [ ] 本地隔离: 增加基于 JWT/Token 动态初始化专属 SQLite db 文件的登录逻辑，实现数据硬隔离。(待确定)

### 9. 移动端极速投喂闭环 (Telegram Bot 专线)
- [ ] Node.js Bot: 实现视频接收与本地 `POST /tasks/submit` API 连通。(待确定)
- [ ] Webhook 承接: 完善 Bot 接收 Python 引擎 Webhook 回调，原生发送回 TG 聊天框。(待确定)
- [ ] PLG 漏斗: 增加日均 5 条生成上限拦截，植入引流至桌面版/官网的 Magic Link 卡片。(待确定)
- [ ] 高阶指令: 增加 `/abtest --hooks 3` 等快速裂变快捷键，迎合买量手习惯。(待确定)

### 10. 落地页与官网引流 (Landing Page)
- [ ] 框架搭建: 使用 Nuxt 3 + Tailwind CSS 初始化代码库，并部署至 Cloudflare Pages。(待确定)
- [ ] 页面设计: 面向 UA 游戏买量市场，撰写高转化率 Hero Section 营销文案。(待确定)
- [ ] 数据基建: 嵌入 PostHog 代码，实现 A/B 测试、屏幕录制与线索漏斗埋点。(待确定)
- [ ] 动态收集: FastAPI 端新增 `POST /api/leads` 路由，捕获官网提交的意向线索并推送到内部 TG 监控群。(待确定)

### 11. 游戏买量专属管线 (UA Engine: Fake Gameplay) - [规划中]
- [ ] 数据库扩容: `local_assets_inventory` 表的 `asset_type` 新增 `sprite_webm` (透明序列帧) 和 `vfx_overlay` (透明特效) 枚举值。
- [ ] `compositor.py` 重构: 升级 `overlay` 滤镜的编译逻辑，支持接受 `{count: N, area: [x1, y1, x2, y2]}` 参数，实现单个透明素材在指定区域内的批量随机散布与复制。
- [ ] 前端测试 UI (UA-Desktop): 在工作台中新增“伪实机实验区”，允许上传 1 张底图 + 1 个透明小人，测试输入数量生成矩阵军队的功能。

### 12. V2V 视觉重绘与跨国本地化基建 (Global V2V Pipeline) - [规划中]
- [ ] **资产库扩容**: 在 SQLite 的 `local_assets_inventory` 表中，增加 `is_curated_master` (布尔值) 字段，用于严格区分官方优质底模与普通用户上传的视频。
- [ ] **云端 API 契约设计**: 撰写与远端 ComfyUI GPU 集群通信的 `POST /api/v1/v2v/redraw` OpenAPI 文档，明确输入底模 ID、目标人种/画风枚举值。
- [ ] **桌面端 UI (跨国本地化面板)**: 在“矩阵工厂”中规划新增“🌍 跨国本地化”功能区。UI 逻辑设计为：锁定仅允许从“优质底模库”中勾选源视频，并提供对应的画风下拉框。

### 13. Prompt 架构解耦 (Prompt Engineering Decoupling) - [进行中]
- [ ] 依赖管理: `requirements.txt` 中新增 `Jinja2`。
- [ ] 资产隔离: 新建 `src/prompts/` 目录，创建 `script_auto.jinja` 与 `script_rewrite.jinja`。
- [ ] 逻辑重构: 剥离 `script_gen.py` 中的长文本硬编码，引入 Jinja2 `Environment` 渲染模板。
- [ ] 动态多语言支持: 将原先写死的 `"en"` 和 `"ar"` 替换为读取 `context.target_languages` 的循环渲染逻辑。

### 14. 桌面端监测与激活基建 (Telemetry & Engagement) - [V2.0 规划中]
- [ ] **云端中枢建库**: 筹备云端 PostgreSQL，建立 `users` 与 `device_logs` 表，支持 `last_login_at` 留痕。
- [ ] **心跳与遥测 API**: 开发云端 `POST /api/telemetry/ping` 接口，接收 Tauri 桌面端定时发送的版本与在线状态。
- [ ] **前端配额引擎 (Quota UI)**: 在 Vue 3 顶栏新增“算力积分/电池”进度条。每日首次登录请求云端重置，耗尽后弹出付费或引流弹窗。
- [ ] **云端强推网关 (In-App Push)**: 实现基于 JSON 的轻量级云控配置下发，支持强制弹窗通告、红点提示。
- [ ] **强制升级屏障 (Force Update)**: 结合 Tauri 的 Updater 机制，若检测到本地版本低于云端 `min_required_version`，强制进入升级锁定页。

### 15. 长视频智能切片管线 (Smart Clipping Pipeline) - [规划中]
- [ ] **底层 DSL 升级**: 扩展 `Timeline` 和 `ClipItem` 数据结构，新增 `trim_start` (float) 和 `trim_end` (float) 属性。
- [ ] **FFmpeg 滤镜适配**: 修改 `FFmpegCompositorNode`，确保在拼接含 `trim` 参数的片段时，正确注入 `-ss` 和 `-to` 指令，并解决切割后的音画同步（PTS 重置）问题。
- [ ] **端侧特征提取器 (AssetShredderNode)**: 新增前置处理节点，实现长视频输入后自动执行 `fps=1` 抽帧与 16kHz 音频剥离。
- [ ] **云端审片 API 契约**: 规划 `POST /api/v1/semantic/analyze_video` 云端接口，定义传入图片序列与音频，返回高光时间戳 JSON 的 OpenAPI Schema。

### 16. ACG 叙事与互动影游管线 (ACG Narrative Pipeline) - [规划中]
- [ ] **语义解析器分化**: 在 `src/domains/ua/` 目录下，独立设计 `NarrativeParserNode.py`，专门处理带台词对白的超长上下文视频切片。
- [ ] **悬念截断算法**: 在 `FFmpegCompositorNode` 中增强 `trim` 功能，支持接收由 LLM 计算出的 `cliffhanger_timestamp`，并在该帧后强行注入 3 秒的静态 CTA 画面缓冲。
- [ ] **H5 播放器外壳基建**: 开发一个极简的 Vue/Vanilla JS 模板，作为 `InteractiveExportNode` 打包互动影游时的前端运行时底座。

### 17. SwaS 商业闭环开发 (SwaS Business Loop) - [高优先级]
- [ ] **TG Webhook 汇报端 (Wizard of Oz)**: 实现本地渲染任务完成后，向指定 TG UserID 发送包含视频预览与生产报告的自动化消息。
- [ ] **桌面端多工作区路由**: 重构 Tauri 后台 API，支持根据 `X-Local-User` 请求头自动挂载对应的客户端数据库，实现“一键切客户”。
- [ ] **TG 转化客服雏形**: 调研 RAG 框架（如 LangChain），用于为 TG Bot 挂载商家的自定义 PDF/Doc 知识库，开启 AI 客服内测。

### 18. 消息中枢与行动卡片基建 (Notification Engine) - [规划中]
- [ ] **数据结构统一定义**: 设计 `EventMessage` Pydantic 模型，包含 `level` (info/warn/error), `category` (system/insight/task), `action_url` 等字段。
- [ ] **Tauri 前端状态机增强**: 在 `App.vue` 或全局 Store 中添加 `Presence` 监听。当窗口失去焦点超 5 分钟，向云端上报 `is_away=true` 状态。
- [ ] **决策卡片组件封装**: 开发 `<ActionableProposalCard />` Vue 组件，用于在 Dashboard 接收并渲染 AI 推送的节假日生产计划，并绑定审批回传接口。

### 19. 转化承接与聚合收件箱 (Unified Social Inbox) - [规划中]
- [ ] **工单状态机基建**: 在云端 PostgreSQL 设计 `social_tickets` 表，包含平台来源、账号归属、意图打标与三级状态字段。
- [ ] **防关联 RPA 探针**: 在 Tauri 后台实验集成对 AdsPower / Dolphin Anty 的 Local API 控制脚本，尝试自动抓取指定网页的评论区 DOM 树。
- [ ] **Tauri UI - 聚合收件箱**: 开发专门的 Vue 组件页，左侧聚合来自全矩阵的未读消息，右侧提供带有 AI 话术推荐的聊天框。
- [ ] **一键甩单接口 (TG Escalation)**: 编写 `POST /api/v1/tickets/{id}/escalate` 接口，接收 Tauri 传来的代运营备注，并触发 Telegraf 向对应的商家 TG 账号发送 Actionable 报警卡片。
- [ ] **统一消息基建 (Messaging Gateway)**: 在 `src/services/messaging/` 目录下定义 `UniversalMessage` Pydantic 模型与 `BaseIMAdapter` 抽象基类。
- [ ] **开发 Telegram 适配器**: 作为第一个 MVP 实现类，编写 `TelegramAdapter`，打通与 Telegraf 接收端的标准化 JSON 通信。预留 `WhatsAppAdapter` 与 `ViberAdapter` 的目录桩。

### 20. 双引擎 DSL 解析器开发 (DSLParserNode) - [高优先级]
- [ ] **语义标签体系**: 确立 Content（叙事）与 UA（心理触发）两套独立的 X 轴逻辑节点标签。
- [ ] **Node 重构**: 在 `DSLParserNode` 中实现基于 `script_mode` 的逻辑路由，能够根据“挫败感”指令自动编排 Problem -> Failure 序列。

### 21. 互动影游极限打包管线 (FMV Export Pipeline) - [高优先级]
- [ ] **时间轴缝合器**: 实现 `TimelineMergerNode`，完成视频物理拼接与时间戳 Map 的自动导出。
- [ ] **极简 H5 模板**: 编写纯 Vanilla JS 的播放器壳，验证 `currentTime` 跳跃分支的流畅度。
- [ ] **体积压测**: 验证 3-5 个分支的短视频压缩至 Base64 后，是否能稳定通过 5MB 红线。

### 22. 游戏 UA 导流视频优化 (UA Guiding Video) - [进行中]
- [ ] **情绪调用增强**: 结合 NeuroFlow，针对游戏买量的导流视频部分，在 Hook 阶段强制注入高冲突、高反差的视觉标签素材。

### 23. ACG 互动影游与短剧管线 (Interactive FMV Pipeline) - [高优先级规划]
- [ ] **FFmpeg 分支缝合器**: 开发 `TimelineMergerNode`，接收包含分支逻辑的 JSON，将多个视频切片无损缝合为单轨视频，并输出各分支的精准时间戳区间 (Timestamps Map)。
- [ ] **互动壳生成器 (H5 Wrapper)**: 使用原生 JS 编写一个轻量级播放器模板，能读取前置节点输出的 Timestamps Map，实现点击按钮跳转对应视频帧的交互。
- [ ] **体积极限压缩测试**: 测试 WebM 超低码率参数与 Base64 转换器，确保 3 个 10 秒分支视频压包后总体积 < 5MB。
- [ ] **SenseVoice 桌面端集成探针**: 验证 `SenseVoice-Small` 转 ONNX 格式后的包体积与 CPU 推理速度。编写独立的 `LocalAudioParserNode`，能够接收本地 MP3，输出包含 `start_time, end_time, text, emotion` 的标准化 JSON 数组。

### 24. 游戏 UA 情绪导流视频管线 (Emotional UA Hooks) - [规划中]
- [ ] **破绽截断算法 (`trim` 升级)**: 强化 FFmpeg 节点的 `trim` 功能，支持大模型计算出的“悬念截断时间戳”，并在该帧后强行注入 2-3 秒的动态 CTA 贴纸与音效。

### 25. Playable H5 换皮引擎基建 (Playable Reskin Pipeline) - [暂缓 / Backlog]
- [ ] **模板一号工程**: 使用 Phaser.js 或 Cocos Creator 开发第一个“参数化”打样工程（如：画线救狗）。确保怪物贴图、主角贴图可在不改动代码的情况下被物理替换。
- [ ] **单文件打包脚本**: 编写 Node.js 脚本，实现将构建出的 HTML、JS、CSS 以及图片资源（转 Base64）强行合并为一个独立的 `index.html`。
- [ ] **参数化注入 API**: 开发云端 `POST /api/v1/playable/build` 接口，接收客户的图片 zip 包和配置 JSON，驱动无头引擎编译并返回下载链接。

### 26. 多模态特征融合节点 (MultimodalFusionNode) - [规划中]
- [ ] **数据结构统一定义**: 升级 `ClipItem` 和 `Timeline` 结构，支持同时携带 `vision_emotion` 和 `audio_emotion` 及各自的 `confidence` 分数。
- [ ] **融合算法实现**: 编写 `fuse_emotions(audio_event, vision_event, domain)` 核心函数，严格落地四层仲裁机制。
- [ ] **反差标签处理逻辑**: 在 `AssetSelectNode` 的抽卡逻辑中，针对携带 `extreme_contrast` 标签的切片赋予 S 级抽卡权重。
- [ ] **云端仲裁 API 契约**: 规划 `POST /api/v1/semantic/arbitrate` 接口，接收本地发来的 `{text, keyframe_base64}`，返回 NeuroFlow 的终极情绪打标。

### 27. 视频基因舱与单片重铸管线 (Video DNA Hub) - [规划中]
- [ ] **渲染伴生清单 (Manifest Export)**: 修改 `CompositorNode` 的输出逻辑，在生成 MP4 的同时，将 `Timeline` 数据结构剥离为扁平化的 `VideoManifest` JSON 并持久化到 SQLite。
- [ ] **重铸 API 端点**: 开发 `POST /api/v1/engine/mutate-video`，接收 `{video_id, block_index, prompt}`，实现对指定区块的重新执行与极速 `concat` 缝合。
- [ ] **Tauri 三栏式 UI 验证**: 前端开发“视频详情页”组件。完成左侧带 ROI 的播放器、中间基于 JSON 渲染的卡片堆叠（DNA Recipe），以及右侧的 Copilot 对话框 UI 打样。
- [ ] **卡片与播放器联动**: 实现点击中栏的 Hook/Body 卡片，左侧播放器自动 `seek` 到 JSON 中对应的 `start` 时间戳并高亮该区块。

### 28. [储备] 图文矩阵与 Monorepo 前端拆分 (Graphic & Monorepo Prep)
- [ ] **目录重构**: 将现有的 Vue 前端工程重构为 Monorepo 结构。分离出 `clients/content-desktop` 与 `clients/ua-desktop` 两个独立外壳，共享 `src/core` 基建。
- [ ] **Tauri 配置隔离**: 为两个 Client 分别配置独立的 `tauri.conf.json`（设定不同的 `productName` 和 `identifier`，实现分别打包出两款独立 .exe 软件）。
- [ ] **路由命名空间分割**: 在 FastAPI 的 `routes.py` 中，建立 `/api/v1/content/` 和 `/api/v1/ua/` 的命名空间路由树。
- [ ] **双核调度池基建**: 在 `services.py` 中引入独立的 `GraphicExecutor` 线程池，为后续接入 Playwright 预留无阻塞的异步执行队列。
- [ ] **数据模型扩容**: 修改全局数据库模型，在任务表和资产表中新增 `task_type` 字段（视频/图文），并在 UI 的历史记录页通过 Icon 兼容混合展示。

### 29. [储备] 情緒彈药库基建 (Meme Hub Prep)
- [ ] **数据库扩容**: 在 SQLite 多租户模型 的结果表和资产表中，新增支持存储表情包 URL、表情包 ID 和情緒标签的模型。
- [ ] **本地发送日志库**: 在 SQLite 中新建文件 `dopamatrix_Team_A_memes_log.db`，专门存储Team A 的表情包发送历史和本地Likes 数，为云端遥测（Telemetry）上报做准备。
- [ ] **Pillow 字体描边节点**: 开发一个专门处理表情包静态图合成的 Python 类（基于 Pillow库），重点实现魔性字体的自动排版和描边。
- [ ] **FFmpeg 表情包 GIF 切片逻辑**: 利用本地现有的 FFmpeg 命令，开发专门处理把 3 秒内的视频切片转换为GIF并叠加字幕的简单节点路由。

### 30. Gemma 4 云端大脑换芯工程 - [紧急/高优先级]
- [ ] **环境搭建**: 在云端 GrowthOS 节点完成 vLLM 部署环境配置，预下载 Gemma-4-31B-Dense 权重文件。
- [ ] **API 适配层开发**: 编写 Python 包装器，将 Gemma 4 的输出适配为现有的 `VideoTaskCreate` 接口规范。
- [ ] **DeerFlow 管道对接**: 开发数据回流脚本，将 DeerFlow 抓取的 TikTok 评论数据格式化后实时推送到云端大模型的上下文窗口（256K 模式）。
- [ ] **Function Calling 注册**: 在 `src/api/agent_tools/` 中定义 `RenderVideo` 和 `GenerateMeme` 的 JSON Schema，供 Gemma 4 直接调遣。
- [ ] **CrewAI 代码清理**: 从依赖库中移除 CrewAI 相关的试验性代码，简化工程结构。

### 31. AI 伴侣桌面端 (Tauri) 基建攻坚战 - [高优先级]
- [ ] **Airi 手术拆除**：Fork `airi` 开源库，彻底剥离原有的 Transformers.js, ONNX Runtime 等沉重本地 AI 模块。
- [ ] **音频扳机开发**：在 Rust 层实现 15 秒极低功耗 Rolling Buffer（视频缓存），并对接麦克风输入接口。
- [ ] **P2P 分发模块**：调研并集成基于 Rust 的 libtorrent 或 WebTorrent 协议，实现模型文件的分块校验与局域网极速传输。
- [ ] **双轨制 UI 实装**：开发“多巴胺”积分与法币（USD）的双轨制钱包界面，以及战后的“高光多巴胺结算卡片”（Loot Box 交互），规避频繁授权的打扰。

### 32. 全自动图文底模生成 MVP (Auto-Templating Graphic MVP) - [规划中]
- [ ] **大模型 Prompt 工程**: 编写并测试专门针对 Gemma 4 的 `System Prompt`，要求其根据输入的图片，严格输出带有固定 `id` 占位符（如 `dm-text-1`, `dm-img-1`）的单文件 HTML/CSS 代码。
- [ ] **底模数据库扩容**: 修改 SQLite/PostgreSQL 中资产表的 `asset_type`，新增枚举值 `html_template`。字段直接存储大模型生成的 HTML 文本字符串。
- [ ] **Playwright 渲染沙盒**: 升级 `services.py` 中的 `GraphicExecutor`。在启动无头浏览器上下文时，强制挂载沙盒参数，确保安全渲染 AI 生成的代码。
- [ ] **C 端接口对接**: 开放 `/api/v1/memes/templates/latest` 路由，让“嘴强鸭”客户端能够实时拉取并展示最近 1 小时内由 AI 自动撰写并生成出来的最新互动图文梗模板。
- [ ] **[架构共识]**: 确认图文引擎与视频引擎共用 `DSLParserNode`。
- [ ] **[逻辑隔离]**: 开发 `PathResolver` 模块，根据任务类型强制分流至不同的本地物理文件夹。
- [ ] **[渲染联调]**: 准备在图文轨道试行“代码积木”，直接注入 HTML 字符串进行渲染测试。