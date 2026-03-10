# 🧠 ClipFlow Ecosystem Architecture & Context
> **版本**: v1.0 MVP 终极封板 | **核心定位**: 跨国视频矩阵增长引擎 (智链 AI)
> **目标市场**: 
> 1. 实体出海下沉市场 (东南亚/中东汽修、建材等高频实体 B 端)
> 2. 数字内容买量大军 (广州出海游戏、互动影游、短剧/漫剧 UA 团队)

## 1. 宏观三层架构模型 (The 3-Tier Ecosystem)
生态严格遵循物理隔离与 PLG (产品驱动增长) 商业逻辑：
1. **触角层 (C/小 B 端 Agile Bots - 当前阶段重点)**: 
   - **载体**: Telegram Bot & Discord Bot。
   - **技术栈**: Node.js + Telegraf (TG) / Discord.js。
   - **职责**: 作为极速摄入素材的“移动工作站”和 PLG 漏斗入口。接收游戏实机录屏或车间实拍 -> 组装参数 -> 发送给后端引擎 -> 接收 Webhook 异步推送成片 -> 引导高频消耗用户“升级获取企业桌面端主机”。
2. **执行层 (B 端 Tauri 桌面端 + FastAPI 引擎)**: 
   - **定位**: 沉浸式矩阵工厂，承载重度工业化渲染。
   - **状态**: v1.0 已封板。采用双视图架构（ROI 商业落地首屏 + AI Feed 异步工作台）。
   - **引擎特性**: 纯异步后台队列，基于 FFmpeg `[v0][v1]` 槽位模型，天然适配游戏/漫剧界面的“底层画面+UI图层”解耦叠加。
3. **大脑层 (MatrixBrain GrowthOS - v2.0 规划)**: 
   - 云端中枢。跨账号矩阵自动排期、全网投流分发与数据回流。

## 2. 核心技术红线与契约 (Hard Constraints)
1. **🔴 测试语言优先 (Test-First 管线)**: 引擎单次任务仅生成【1个 Master 纯净母带】+【1个 Test_Language (如 en) 最终变体】。跨语言扩展依赖跑通买量数据后的二次挂载。
2. **🔴 降维极速渲染**: 默认短视频分辨率为 720x1280，底层开启 `-preset superfast -threads 0`，确保单条素材 1-2 分钟极速出片。
3. **🔴 Y 轴双轨解耦**: 透明图层强制拆分为 `local_logo_dir` (如：品牌水印/常驻UI) 和 `local_sticker_dir` (如：爆衣特效/互动选择按钮/促销贴纸)，确保视觉空间不冲突。
4. **🔴 纯异步非阻塞通信**: 所有前端界面与 Bot 必须通过轮询或 Webhook 获取结果，禁止 HTTP 长连接阻塞等待。

## 3. 核心 API 负载与 Webhook 回调契约 (API & Callback Contract)
**提交载荷 (POST /api/v1/tasks/submit)**:
```json
{
  "prompt": "生成一个15秒的赛博朋克风射击游戏买量视频，突出十连抽必中SSR...",
  "batch_size": 1,
  "test_language": "en", 
  "aspect_ratio": "9:16",
  "local_asset_dir": "绝对路径 (X轴，实机录屏/实拍)",
  "local_logo_dir": "绝对路径 (Y轴右上角，品牌Logo，可选)",
  "local_sticker_dir": "绝对路径 (Y轴居中，十连抽/互动UI贴图，可选)"
}

**即时响应 (202 Accepted)**:
```json
{
  "task_id": 123,
  "session_id": "uuid-v4",
  "status": "queued",
  "message": "任务已提交至后台矩阵工厂，请通过 GET /tasks/{task_id} 轮询进度。"
}
```

**终态轮询 (GET /api/v1/tasks/{task_id})**:
```json
{
  "task_id": 123,
  "status": "completed",
  "test_language": "en",
  "assets": [
    {
      "language": "en",
      "file_path": "/output/final_en_123.mp4",
      "file_hash": "md5-hash",
      "perceptual_hash": "phash-hash",
      "duration_seconds": 15.0,
      "tts_duration_seconds": 12.5,
      "llm_tokens_used": 450,
      "estimated_cost_usd": 0.012
    }
  ],
  "estimated_cost_usd": 0.012,
  "created_at": "2026-03-10T10:00:00",
  "finished_at": "2026-03-10T10:01:30"
}
```

**Webhook 回调 (POST {WEBHOOK_URL})**:
```json
{
  "event": "task_completed",
  "task_id": 123,
  "session_id": "uuid-v4",
  "status": "completed",
  "test_language": "en",
  "cost_usd": 0.012,
  "timestamp": "2026-03-10T10:01:30",
  "assets": {
    "master_video": "/outputs/master_123.mp4",
    "final_variant": "/outputs/final_en_123.mp4",
    "anti_dup_md5": "ea2aaf285df9bc..."
  }
}
```

## 4. 核心组件职责与数据流 (Component Responsibilities & Data Flow)
1. **Bot (Node.js)**:
   - **摄入**: 接收用户上传的视频/图片 (Telegram `document`/`photo`)。
   - **组装**: 提取文件名/用户输入作为 `prompt`，读取本地目录作为 `local_asset_dir`。
   - **提交**: 调用 FastAPI `POST /api/v1/tasks/submit`。
   - **响应**: 接收 202 响应 -> 立即回复用户“任务已提交，请稍后查看”。
   - **轮询**: 定时轮询 `GET /api/v1/tasks/{task_id}`，直到 `status === "completed"`。
   - **推送**: 收到成片后，通过 Webhook 将结果推送给 MatrixBrain (v2.0)。

2. **FastAPI Backend (Python)**:
   - **提交**: 接收任务 -> 存入 `video_tasks` 表 (status: `queued`) -> 立即返回 202。
   - **调度**: 启动后台 `run_matrix_factory` 进程池。
   - **执行**: 内部调用 `ScriptGenNode` -> `TTSNode` -> `VideoFactoryNode`。
   - **状态**: 过程中定期更新 `video_tasks` (status: `processing`)。
   - **完成**: 任务结束 -> 存入 `video_assets` -> 更新 `video_tasks` (status: `completed`, `finished_at`, `estimated_cost_usd`)。
   - **通知**: 发射 Webhook 到 `WEBHOOK_URL`。

3. **MatrixBrain (v2.0)**:
   - **接收**: 监听 Webhook，聚合多任务数据。
   - **排期**: 自动生成多账号/多语言的生产计划。
   - **分发**: 调用 FastAPI 提交任务，并跟踪进度。
   - **回流**: 收集各渠道的点击/转化数据，反向优化 `prompt` 和 `sticker` 策略。

## 5. 关键技术契约与边界 (Key Technical Contracts & Boundaries)
1. **文件路径契约**:
   - Bot 提交 `local_asset_dir` 时，必须是绝对路径。
   - FastAPI 接收后，在 `run_matrix_factory` 中使用 `Path(local_asset_dir).resolve()` 确保绝对路径。
   - 所有本地文件路径在数据库中存储为绝对路径，前端仅展示相对路径或可点击 URL。

2. **异步通信契约**:
   - **提交**: 永不阻塞，立即返回 202。
   - **轮询**: 客户端每 2-3 秒轮询一次，直到 200 且 `status === "completed"`。
   - **Webhook**: 任务终态后异步发送，不阻塞 FastAPI 主线程。

3. **成本与语言契约**:
   - **成本**: 仅在 `VideoFactoryNode` 中计算 `estimated_cost_usd`，累加到任务总成本。
   - **语言**: 每次任务仅生成 `test_language` 的最终变体，Master 母带不含语言特定元素。

4. **文件命名契约**:
   - **Master**: `master_{hash}.mp4` (纯净母带)。
   - **Test**: `final_{test_language}_{hash}.mp4` (带 TTS 和贴纸的最终成品)。
   - **透明图层**: `logo_{hash}.png` (右上角), `sticker_{hash}.png` (居中)。

## 6. 扩展性契约 (Scalability Contracts)
1. **多语言扩展 (v2.0)**:
   - 仅需在 `VideoFactoryNode` 中增加 `test_language` 循环，复用 Master 母带。
   - 数据库 `video_assets` 增加 `language` 字段。

2. **多账号矩阵 (v2.0)**:
   - MatrixBrain 负责管理多账号的 `session_id` 和 `webhook_url`。
   - FastAPI 任务记录中包含 `session_id`，用于区分不同账号的矩阵任务。

3. **投流数据回流 (v2.0)**:
   - MatrixBrain 收集各平台广告后台数据。
   - 通过 API 更新 `video_assets` 中的 `ctr`, `cvr`, `roi` 等字段。
   - 建立“数据驱动的 prompt 优化”闭环。

## 7. 部署与运行契约 (Deployment & Runtime Contracts)
1. **Bot 部署**: Node.js 运行在用户本地或云服务器，通过 HTTP/S 调用 FastAPI。
2. **FastAPI 部署**: 运行在云服务器，监听 `0.0.0.0:8000`，数据库为 PostgreSQL。
3. **MatrixBrain 部署**: v2.0 独立服务，监听 Webhook，管理多账号任务。
4. **文件存储**: 所有视频/图片存储在云存储（如 MinIO/S3），数据库仅存储路径和元数据。

## 8. 总结 (Summary)
ClipFlow v1.0 MVP 封板已完成三层架构的**触角层**（Bot）与**执行层**（Tauri + FastAPI）的完整闭环，并为 v2.0 的 **MatrixBrain** 预留了清晰的扩展契约。核心红线（测试语言优先、降维极速渲染、Y轴双轨解耦、纯异步通信）已固化在代码中，确保生态在商业化初期即可快速迭代、快速出片、快速验证买量效果。

---

**免责声明**: 本文档描述的是 v1.0 MVP 终极封板后的架构与上下文，所有 API 负载、Webhook 回调及组件职责均已固化，后续 v2.0 扩展将严格遵循本契约进行。

---

**版本信息**:
- **版本**: v1.0 MVP 终极封板
- **核心定位**: 跨国视频矩阵增长引擎 (智链 AI)
- **目标市场**: 实体出海下沉市场 + 数字内容买