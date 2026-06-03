"""
LLM 服务适配器 — 抽象基类 + OpenAI/兼容接口实现

设计原则：基于依赖倒置（DIP），所有上层节点只依赖 BaseLLMProvider 接口，
底层换模型（DeepSeek / Gemini / 本地 Ollama 等）只需新增子类，
无需改动任何上层业务逻辑。

【BYOK 安全架构 + 字典缓存】：
  API Key 采用"多键字典懒加载缓存"模式：
    - 模块级字典 _api_key_cache[setting_key] 存储各模型的 Key 缓存。
    - 首次请求某模型时查询 SQLite，结果写入字典；后续请求直接命中，零 I/O。
    - invalidate_api_key_cache(key) 精准清除指定模型缓存；传 None 则清空全部。
  新增 Provider（如 DeepSeekProvider）只需调用
  _load_api_key_from_db('deepseek_api_key')，无需改动任何其他逻辑。
  未配置则抛出 ValueError，由 Worker 层捕获并记录。

【关键防坑配置】：
  - base_url 通过 OPENAI_BASE_URL 环境变量注入，支持代理/中转地址
  - 未配置时 SDK 自动使用官方默认地址
  - response_format={"type": "json_object"} 强制 JSON 输出，彻底规避 LLM 输出格式不稳定问题
"""

import json
import os
import sqlite3
from abc import ABC, abstractmethod

import openai


# ---------------------------------------------------------------------------
# 多键字典懒加载缓存：支持多模型独立缓存与精准失效
# ---------------------------------------------------------------------------

# key   → setting_key（如 'openai_api_key'、'deepseek_api_key'）
# value → 对应的 API Key 字符串（"" 表示已查库但未配置）
# 键不存在 → 尚未加载，需穿透查库
_api_key_cache: dict[str, str] = {}


def _load_api_key_from_db(setting_key: str = "openai_api_key") -> str:
    """
    带字典缓存的多模型 API Key 加载器。

    命中路径（热路径）：setting_key 已在字典中，直接返回，零 I/O。
    冷路径（首次 / 缓存失效后）：查询 dopamatrix.db，结果写入字典后返回。

    Args:
        setting_key: app_settings 表中的键名，默认 'openai_api_key'。
                     新增模型时（如 DeepSeek）传入对应键名即可，无需修改本函数。

    Returns:
        API Key 字符串；未配置时返回空字符串。

    并发安全性：Python GIL 保证字典读写的原子性，
    极端情况下多线程同时穿透缓存只会多查一次库，不会产生竞态错误。
    """
    if setting_key in _api_key_cache:
        return _api_key_cache[setting_key]

    db_path = "dopamatrix.db"
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT key_value FROM app_settings WHERE key_name = ?;",
            (setting_key,),
        ).fetchone()
        result = row[0] if (row and row[0]) else ""
    except sqlite3.OperationalError:
        # app_settings 表尚未创建（首次启动），视为未配置
        result = ""
    finally:
        if conn is not None:
            conn.close()

    _api_key_cache[setting_key] = result
    return result


def invalidate_api_key_cache(setting_key: str | None = None) -> None:
    """
    使字典缓存失效。

    Args:
        setting_key: 指定要清除的模型键名（如 'openai_api_key'）。
                     传 None 则清空所有模型的缓存（安全兜底）。

    应在用户通过设置页面更新 API Key 后立即调用，
    确保下一次 LLM 请求重新从数据库加载最新配置。
    """
    if setting_key is not None:
        _api_key_cache.pop(setting_key, None)
    else:
        _api_key_cache.clear()


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------

class BaseLLMProvider(ABC):
    """
    所有 LLM 服务适配器必须实现的接口。
    上层节点（如 ScriptGenNode）只依赖该抽象类，与具体模型完全解耦。
    """

    @abstractmethod
    def generate_script(
        self,
        prompt: str,
        system_prompt: str,
        *,
        temperature: float | None = None,
    ) -> dict:
        """
        向 LLM 发送请求并返回结构化结果。

        Args:
            prompt:        用户指令（Human Turn）
            system_prompt: 系统提示词（角色 + 输出格式约束）
            temperature:   采样温度；None 时由实现类使用默认值（通常为 0.7）。

        Returns:
            解析后的 Python dict（LLM 返回的 JSON 内容）

        Raises:
            ValueError:   未配置 API Key 时抛出（业务异常，由 Worker 捕获）
            RuntimeError: API 调用失败或返回内容无法解析为 JSON 时抛出
        """
        pass


# ---------------------------------------------------------------------------
# OpenAI / 兼容接口实现（DeepSeek、Moonshot、通义千问等）
# ---------------------------------------------------------------------------

class OpenAIProvider(BaseLLMProvider):
    """
    基于 OpenAI Python SDK 的 Provider。

    通过 base_url 可无缝切换至任何兼容 OpenAI Chat Completions API 的服务：
      - DeepSeek:  OPENAI_BASE_URL=https://api.deepseek.com/v1
      - Moonshot:  OPENAI_BASE_URL=https://api.moonshot.cn/v1
      - 本地代理:  OPENAI_BASE_URL=http://localhost:8000/v1

    API Key 在每次请求时实时从 SQLite app_settings 表读取（BYOK 架构），
    不在构造期缓存，不依赖环境变量。
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ):
        """
        Args:
            base_url: 自定义接入地址，默认从 OPENAI_BASE_URL 环境变量读取；
                      若均未配置，SDK 使用 OpenAI 官方默认地址。
            model:    模型名称，默认从 LLM_MODEL 环境变量读取，兜底 gpt-4o-mini。
        """
        # base_url 仍允许通过环境变量配置（非敏感信息，无安全风险）
        self._base_url = base_url or os.getenv("OPENAI_BASE_URL") or None
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")

    def generate_script(
        self,
        prompt: str,
        system_prompt: str,
        *,
        temperature: float | None = None,
    ) -> dict:
        """
        每次调用前从字典缓存（冷路径穿透 SQLite）读取 openai_api_key，
        构造临时客户端发起请求。

        未来新增 DeepSeekProvider 时，只需将此处改为：
          _load_api_key_from_db('deepseek_api_key')
        即可复用同一套缓存与失效机制。

        Raises:
            ValueError:   未在设置页面配置 API Key
            RuntimeError: API 调用异常 或 返回内容非合法 JSON
        """
        api_key = _load_api_key_from_db("openai_api_key")
        if not api_key:
            raise ValueError(
                "尚未配置大模型 API Key，请先前往设置页面进行配置。"
            )

        # 每次构造新客户端，确保使用数据库中的最新 Key
        client = openai.OpenAI(api_key=api_key, base_url=self._base_url)

        temp = 0.7 if temperature is None else float(temperature)
        try:
            response = client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": prompt},
                ],
                temperature=temp,
            )
        except openai.OpenAIError as e:
            raise RuntimeError(f"[OpenAIProvider] API call failed: {e}") from e

        raw = response.choices[0].message.content or ""

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"[OpenAIProvider] Failed to parse LLM response as JSON.\n"
                f"Raw content:\n{raw}\n"
                f"Error: {e}"
            ) from e
