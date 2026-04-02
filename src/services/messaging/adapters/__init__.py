"""
src/services/messaging/adapters/__init__.py
————————————————————————————————————————————
适配器注册表 (Adapter Registry)

网关路由通过此字典动态实例化适配器，实现「零硬编码」的平台扩展。

新增渠道三步走：
  1. 新建 <platform>_adapter.py，实现 BaseIMAdapter
  2. 在此注册表添加一行映射
  3. 完成 —— 路由层、业务层零改动
"""

from .telegram_adapter import TelegramAdapter

# platform slug → Adapter 类（未实例化）
ADAPTER_REGISTRY: dict = {
    "telegram": TelegramAdapter,
    # "whatsapp":   WhatsAppAdapter,   # 下一个战场
    # "wechat":     WeChatWorkAdapter,
    # "sms":        TwilioSMSAdapter,
}

__all__ = ["ADAPTER_REGISTRY", "TelegramAdapter"]
