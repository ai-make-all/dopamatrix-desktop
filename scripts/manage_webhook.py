#!/usr/bin/env python3
"""
scripts/manage_webhook.py
——————————————————————————————————————————————————————————————
ClipFlow — Telegram Webhook 运维指挥官

用途：注册、查询、解绑 ClipFlow FastAPI 网关与 Telegram Bot 之间的 Webhook 通道。
依赖：httpx（已在项目主依赖中，无需额外安装）、python-dotenv（可选，自动加载 .env）

使用方式
────────
  # 注册 Webhook（将 ngrok 公网地址接管到本地网关）
  python scripts/manage_webhook.py set --url https://xxxx.ngrok-free.app/api/v1/webhook/telegram/receive

  # 查询当前 Webhook 状态（排障神器）
  python scripts/manage_webhook.py info

  # 解绑 Webhook（切回长轮询模式，或废弃 Bot 时使用）
  python scripts/manage_webhook.py delete

  # 指定 Bot Token（覆盖环境变量，适用于多 Bot 场景）
  python scripts/manage_webhook.py info --token 123456:ABC-your-other-bot-token

环境变量
────────
  TELEGRAM_BOT_TOKEN  Bot Token，也可通过 --token 参数显式传入
  项目根目录的 .env 文件会被自动加载（若存在）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

# ------------------------------------------------------------------ #
# 自动加载项目根目录 .env（仅供本脚本独立运行时使用）                    #
# ------------------------------------------------------------------ #
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

def _load_dotenv(env_path: Path) -> None:
    """极简 .env 加载器，无需安装 python-dotenv。"""
    if not env_path.is_file():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

_load_dotenv(_ENV_FILE)


# ------------------------------------------------------------------ #
# Telegram Bot API 工具                                                #
# ------------------------------------------------------------------ #
TG_API = "https://api.telegram.org/bot{token}/{method}"


def _build_url(token: str, method: str) -> str:
    return TG_API.format(token=token, method=method)


def _call(token: str, method: str, payload: dict[str, Any] | None = None) -> dict:
    """
    向 Telegram Bot API 发送请求并返回结果。

    GET  → payload 为 None
    POST → payload 非空
    """
    url = _build_url(token, method)
    try:
        with httpx.Client(timeout=15.0) as client:
            if payload is not None:
                resp = client.post(url, json=payload)
            else:
                resp = client.get(url)
        resp.raise_for_status()
    except httpx.TimeoutException:
        _die(f"[✗] 请求超时（15s），请检查网络连接或 Token 是否有效。\n    URL: {url}")
    except httpx.HTTPStatusError as exc:
        _die(f"[✗] HTTP 错误 {exc.response.status_code}: {exc.response.text}")

    data: dict = resp.json()
    if not data.get("ok"):
        _die(
            f"[✗] Telegram API 返回错误:\n"
            f"    error_code  : {data.get('error_code')}\n"
            f"    description : {data.get('description')}"
        )
    return data.get("result", {})


# ------------------------------------------------------------------ #
# 三大核心命令                                                          #
# ------------------------------------------------------------------ #

def cmd_set(token: str, url: str, secret_token: str | None) -> None:
    """
    向 Telegram 注册 Webhook 地址。

    Args:
        token        : Bot Token
        url          : 公网可访问的 Webhook 接收地址（必须 HTTPS）
        secret_token : 可选安全令牌，TG 会在每个请求头 X-Telegram-Bot-Api-Secret-Token
                       中携带，网关可用于验证来源合法性
    """
    if not url.startswith("https://"):
        _warn("[!] 警告：Telegram 要求 Webhook URL 必须使用 HTTPS。")
        _warn(f"    当前 URL: {url}")
        _warn("    如果是本地开发环境，请确保已开启内网穿透（如 ngrok）。")

    payload: dict[str, Any] = {
        "url"             : url,
        "allowed_updates" : ["message", "callback_query", "inline_query"],
        "drop_pending_updates": False,
    }
    if secret_token:
        payload["secret_token"] = secret_token

    print(f"\n[→] 正在向 Telegram 注册 Webhook...")
    print(f"    Bot Token : ...{token[-8:]}")
    print(f"    目标 URL  : {url}")
    if secret_token:
        print(f"    Secret    : ****{secret_token[-4:]}")

    result = _call(token, "setWebhook", payload)

    print("\n[✓] Webhook 注册成功！")
    if isinstance(result, bool) and result:
        print("    Telegram 已确认接收该 Webhook 地址。")
    else:
        print(f"    响应: {result}")

    print("\n[→] 验证注册结果：")
    cmd_info(token, brief=True)


def cmd_info(token: str, brief: bool = False) -> None:
    """
    查询当前 Webhook 状态（排障神器）。

    打印内容：
      - 当前注册的 Webhook URL
      - 待处理消息积压数量（pending_update_count）
      - 最近一次错误信息及发生时间
      - TG 服务器证书状态
    """
    if not brief:
        print(f"\n[→] 正在查询 Webhook 状态...")
        print(f"    Bot Token : ...{token[-8:]}\n")

    result = _call(token, "getWebhookInfo")

    webhook_url       = result.get("url", "")
    pending_count     = result.get("pending_update_count", 0)
    last_error_date   = result.get("last_error_date")
    last_error_msg    = result.get("last_error_message", "")
    max_conns         = result.get("max_connections", 40)
    allowed_updates   = result.get("allowed_updates", [])
    has_custom_cert   = result.get("has_custom_certificate", False)
    ip_address        = result.get("ip_address", "")

    # ---- 状态展示 --------------------------------------------------- #
    sep = "─" * 55
    print(sep)
    print("  📡  Telegram Webhook 状态报告")
    print(sep)

    if webhook_url:
        print(f"  URL            : {webhook_url}")
        _status_tag("  注册状态", "ACTIVE ✓", "green")
    else:
        print(f"  URL            : （未注册）")
        _status_tag("  注册状态", "INACTIVE ✗", "red")

    print(f"  IP 地址        : {ip_address or '—'}")
    print(f"  最大并发连接    : {max_conns}")
    print(f"  监听 Update 类型: {', '.join(allowed_updates) or '全部'}")
    print(f"  自定义证书      : {'是' if has_custom_cert else '否'}")

    # 积压消息数量：黄色警告 / 红色告警
    if pending_count == 0:
        _status_tag("  积压消息数量", f"{pending_count}  （队列健康）", "green")
    elif pending_count < 100:
        _status_tag("  积压消息数量", f"{pending_count}  ⚠ 轻微积压", "yellow")
    else:
        _status_tag("  积压消息数量", f"{pending_count}  ✗ 严重积压！请检查网关！", "red")

    # 最近错误
    if last_error_date:
        import datetime
        error_time = datetime.datetime.fromtimestamp(last_error_date).strftime("%Y-%m-%d %H:%M:%S")
        _status_tag("  最近错误时间", error_time, "red")
        _status_tag("  最近错误信息", last_error_msg, "red")
    else:
        _status_tag("  最近错误", "无  （运行正常）", "green")

    print(sep)


def cmd_delete(token: str, drop_pending: bool) -> None:
    """
    解绑当前 Webhook，Bot 将回到长轮询（getUpdates）可用状态。

    Args:
        drop_pending : True 则同时丢弃积压的未处理消息，适合切换测试环境时使用
    """
    print(f"\n[→] 正在解绑 Webhook...")
    print(f"    Bot Token      : ...{token[-8:]}")
    print(f"    丢弃积压消息   : {'是' if drop_pending else '否'}")

    result = _call(token, "deleteWebhook", {"drop_pending_updates": drop_pending})

    print("\n[✓] Webhook 已成功解绑！")
    print("    Bot 现在处于「长轮询就绪」状态，可通过 getUpdates 接收消息。")
    if drop_pending:
        print("    所有积压消息已一并清除。")


# ------------------------------------------------------------------ #
# 终端彩色辅助（Windows ANSI 兼容）                                    #
# ------------------------------------------------------------------ #
_COLORS = {
    "green" : "\033[92m",
    "yellow": "\033[93m",
    "red"   : "\033[91m",
    "reset" : "\033[0m",
    "bold"  : "\033[1m",
}

def _colorize(text: str, color: str) -> str:
    """Windows 10+ 支持 ANSI，低版本直接返回原文。"""
    if sys.platform == "win32":
        # 启用 Windows ANSI 模式
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    return f"{_COLORS.get(color, '')}{text}{_COLORS['reset']}"

def _status_tag(label: str, value: str, color: str) -> None:
    print(f"{label:<18}: {_colorize(value, color)}")

def _warn(msg: str) -> None:
    print(_colorize(msg, "yellow"), file=sys.stderr)

def _die(msg: str) -> None:
    print(_colorize(msg, "red"), file=sys.stderr)
    sys.exit(1)


# ------------------------------------------------------------------ #
# CLI 入口                                                             #
# ------------------------------------------------------------------ #

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage_webhook",
        description=(
            "ClipFlow — Telegram Webhook 运维指挥官\n"
            "管理 FastAPI 全渠道网关与 Telegram Bot 之间的 Webhook 通道。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例
────
  # 注册 Webhook（ngrok 内网穿透场景）
  python scripts/manage_webhook.py set --url https://xxxx.ngrok-free.app/api/v1/webhook/telegram/receive

  # 注册并附带安全令牌（生产推荐）
  python scripts/manage_webhook.py set --url https://your.domain.com/api/v1/webhook/telegram/receive --secret MY_SECRET

  # 查询当前状态（排障）
  python scripts/manage_webhook.py info

  # 解绑 Webhook 并清空积压消息（切回本地轮询测试）
  python scripts/manage_webhook.py delete --drop-pending
        """,
    )

    parser.add_argument(
        "--token", "-t",
        metavar="BOT_TOKEN",
        default=None,
        help="Bot Token（默认读取环境变量 TELEGRAM_BOT_TOKEN）",
    )

    subparsers = parser.add_subparsers(dest="action", metavar="ACTION", required=True)

    # ---- set -------------------------------------------------------- #
    p_set = subparsers.add_parser(
        "set",
        help="注册 Webhook 地址到 Telegram",
        description="将指定 HTTPS URL 注册为 Bot 的 Webhook 接收端点。",
    )
    p_set.add_argument(
        "--url", "-u",
        required=True,
        metavar="GATEWAY_URL",
        help="公网可访问的 Webhook 接收地址（必须 HTTPS），如 https://xxxx.ngrok-free.app/api/v1/webhook/telegram/receive",
    )
    p_set.add_argument(
        "--secret", "-s",
        metavar="SECRET_TOKEN",
        default=None,
        help="可选安全令牌，TG 将在请求头 X-Telegram-Bot-Api-Secret-Token 中携带，供网关校验来源",
    )

    # ---- info ------------------------------------------------------- #
    subparsers.add_parser(
        "info",
        help="查询当前 Webhook 状态（URL / 积压量 / 最近错误）",
        description="调用 getWebhookInfo，打印完整的 Webhook 健康报告。",
    )

    # ---- delete ----------------------------------------------------- #
    p_del = subparsers.add_parser(
        "delete",
        help="解绑 Webhook，Bot 恢复长轮询可用状态",
        description="调用 deleteWebhook，解除当前注册的 Webhook 绑定。",
    )
    p_del.add_argument(
        "--drop-pending",
        action="store_true",
        default=False,
        help="同时丢弃积压的未处理消息（切换测试环境时推荐开启）",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # ---- 解析 Token ------------------------------------------------- #
    token: str = args.token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        _die(
            "[✗] Bot Token 未配置！\n"
            "    请在 .env 文件中设置 TELEGRAM_BOT_TOKEN=<your_token>，\n"
            "    或通过 --token 参数显式传入。"
        )

    # 基础格式校验（Token 格式：数字:字母数字串）
    if ":" not in token or len(token) < 20:
        _warn(f"[!] Bot Token 格式疑似有误，请确认：{token[:10]}...")

    # ---- 分发命令 --------------------------------------------------- #
    if args.action == "set":
        cmd_set(token, args.url, args.secret)

    elif args.action == "info":
        cmd_info(token)

    elif args.action == "delete":
        cmd_delete(token, args.drop_pending)


if __name__ == "__main__":
    main()
