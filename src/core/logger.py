"""
src/core/logger.py
——————————————————
DopaMatrix 生产级日志系统。

设计要点：
  - 按日期自动滚动（rotation="00:00"），保留最近 7 天
  - diagnose=False：禁止在异常回溯中打印局部变量值，防止生产环境泄露敏感数据
  - backtrace=True：保留完整调用链，便于定位崩溃现场
  - LOG_DIR 通过 appdirs.user_log_dir 定位系统标准日志路径，跨平台可靠

日志目录（示例）：
  Windows : C:/Users/<user>/AppData/Local/DopaMatrixOrg/DopaMatrix/Logs/
  macOS   : ~/Library/Logs/DopaMatrix/
  Linux   : ~/.cache/DopaMatrix/log/
"""

import os
import sys
import time  # noqa: F401 — 供调用方通过 from src.core.logger import time 使用

from appdirs import user_log_dir
from loguru import logger

# ── 全局日志目录 ─────────────────────────────────────────────────
LOG_DIR: str = user_log_dir("DopaMatrix", "DopaMatrixOrg")
os.makedirs(LOG_DIR, exist_ok=True)


def setup_logger() -> None:
    """
    初始化全局 Loguru 日志配置，应在应用入口处调用一次。

    输出策略：
      1. 控制台（stdout）：INFO 及以上，用于开发/调试即时查看
      2. 文件（按日滚动）：INFO 及以上，保留 7 天，含完整回溯但不含局部变量
    """
    logger.remove()
    # 防御性编程：在 --windowed 模式下，sys.stdout 为 None，跳过控制台绑定
    if sys.stdout is not None:
      logger.add(
          sys.stdout,
          level="INFO",
          colorize=True,
          format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
      )

    logger.add(
        os.path.join(LOG_DIR, "dopamatrix_{time:YYYY-MM-DD}.log"),
        rotation="00:00",
        retention="7 days",
        level="INFO",
        encoding="utf-8",
        backtrace=True,
        diagnose=False,  # 安全要求：禁止在日志中记录局部变量，防止密钥/Token 泄露
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    )
