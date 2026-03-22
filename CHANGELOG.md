# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-03-21

### Added
- 实现了 Tauri + FastAPI 的独立 Sidecar 打包架构
- 增加了 `build_backend.py` 自动化环境清理与数据库重置流水线

### Changed
- 将矩阵渲染底层从多进程 (`ProcessPoolExecutor`) 升级为多线程 (`ThreadPoolExecutor`)，大幅降低内存占用
- 重构了 FFmpeg 与 TTS 的物理路径嗅探逻辑，实现无环境变量纯净执行

### Fixed
- 彻底修复了 Windows 下多进程导致的黑框弹窗问题
- 修复了打包后环境变量读取报错导致大模型无法调用的问题
