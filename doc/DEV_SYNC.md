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
- [ ] 侧边栏/顶部 Navbar: 全局品牌重命名 `ClipFlow` -> `DopaMatrix`。
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