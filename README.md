# 🧬 DopaMatrix (Formerly ClipFlow)

> **Next-Gen AI Infrastructure for UA & Content**
> Powered by **NeuroFlow™** Affective Computing Engine

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-Core_Engine-ff69b4.svg)](https://ffmpeg.org/)
[![Status](https://img.shields.io/badge/Status-V1.2_Active_Development-success.svg)]()

## 🌌 概览 (Overview)

**DopaMatrix** 是全球首个面向互动买量 (Playable Ads) 与高并发内容矩阵的 AI 基础设施。我们不剪辑视频，我们**工程化制造“情绪触发器”**。

通过底层的 **NeuroFlow™** 神经营销大模型与极速 DAG 渲染工作流，我们将枯燥的实录素材，裂变为包含 [挫败感]、[好奇心] 与 [权力幻想] 的多巴胺视觉矩阵，彻底打破 Meta/TikTok 的算法黑盒。

---

## 🏛️ 核心架构 (Core Architecture)

本项目采用 **“单核双擎 (Single Core, Dual Engines)”** 的 Monorepo 架构理念：

* **`src/core/` (渲染底座)**：极其纯粹的 DAG 工作流引擎与 FFmpeg 槽位渲染器。**严禁在此处混入任何业务逻辑。**
* **`src/domains/` (业务中枢)**：
    * `ua/`：面向游戏发行的互动买量逻辑（情绪触发 DSL、Hook 生成）。
    * `content/`：面向实体商家的生活叙事逻辑（多语言母带、防封裂变）。
* **`clients/` (前端外壳)**：基于 Tauri + Vue 3 / Nuxt 3 构建的独立客户端与落地页。

---

## ⚠️ 品牌与架构升级过渡指南 (v1.2+)

> **🚨 DO NOT MASS-RENAME INTERNAL MODULES!**

本项目已正式从临时内部代号 `ClipFlow` 升级为商业化主品牌 **`DopaMatrix`**。
为了保证现有矩阵渲染引擎的稳定，避免引发灾难性的 Python 包导入错误，代码库更名将采用**“自外向内，分层替换”**的原则。所有开发者（及 AI 代码助手）请严格遵守以下红线：

### 1. 表现层与前端外壳 (The Shell) —— 【全面启用新品牌】
* **规范**：对外展示的产品名一律为 `DopaMatrix`，底层驱动大模型一律称为 `NeuroFlow™`。
* **执行**：
  * Nuxt 官网落地页、文案、Logos 全部使用新品牌。
  * Tauri 桌面端的应用名称、打包产物 (`.exe` / `.dmg`) 修改为 `DopaMatrix UA` 或 `DopaMatrix Content`。
  * FastAPI 的启动日志、Swagger UI 标题 (`app = FastAPI(title="DopaMatrix API")`) 进行更新。

### 2. 数据库与配置层 (The Bridge) —— 【平滑过渡】
* **规范**：暂时保留现有物理文件名，在配置逻辑中解耦。
* **执行**：
  * 现有的 `.env` 环境变量键名、SQLite 物理文件名（如 `clipflow.db`）**暂时不动**，避免现有环境丢失数据。
  * 后续通过环境变量映射，平滑迁移到 `dopamatrix.db`。

### 3. 底层渲染引擎 (The Core) —— 【绝对静止，严禁重命名】
* **规范**：**绝对不要**在 IDE 里对根目录的 `ClipFlow` 文件夹或深层 Python 模块进行“全局查找替换”。
* **执行**：
  * 现有的 Python 绝对路径导入（例如 `from src.core.engine import ...`）保持原样。
  * 现有的核心类名（如 `WorkflowEngine`, `FFmpegCompositorNode`）保持不变（它们本质上是无业务属性的纯净基建）。
  * **重构计划**：内部 Python 命名空间的彻底重命名，将被推迟到后期的 `refactor/dopamatrix-core` 专属分支中统一进行，严禁在开发业务功能时夹带修改。

---

## 🚀 极速启动 (Quick Start)

### 1. 环境依赖 (Prerequisites)
* Python 3.10+
* Node.js 18+ (用于前端开发)
* **FFmpeg (⚠️ 极度重要：Tauri Sidecar 边车模式)**：
  * **开发环境**：系统全局环境变量中需配置 FFmpeg 以便本地调试。
  * **生产打包 (To B 客户交付)**：系统全局环境的 FFmpeg **不会**被打包进独立安装包中。必须将纯净版的 `ffmpeg.exe` 和 `ffprobe.exe` 拷贝至前端工程的 Tauri 边车目录（例如：`clients/ua-desktop/src-tauri/bin/` 或过渡期的 `web_ui/src-tauri/bin/`），通过 Tauri 的 Sidecar 机制随安装包一并分发，实现客户机“开箱即用”。

### 2. 后端引擎初始化
```bash
# 1. 激活虚拟环境 (确保已创建)
source venv/bin/activate  # Windows 用户使用: venv\Scripts\activate

# 2. 安装核心依赖
pip install -r requirements.txt