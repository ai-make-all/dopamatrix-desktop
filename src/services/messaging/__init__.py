"""
src/services/messaging/__init__.py
——————————————————————————————————
Omnichannel Messaging Gateway 包入口。

对外暴露核心契约，业务层只需 from src.services.messaging import UniversalMessage。
"""

from .contract import UniversalMessage, UniversalResponse, BaseIMAdapter, MessageType

__all__ = ["UniversalMessage", "UniversalResponse", "BaseIMAdapter", "MessageType"]
