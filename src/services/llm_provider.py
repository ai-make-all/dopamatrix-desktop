"""
LLM 服务适配器 — 抽象基类 + OpenAI/兼容接口实现

设计原则：基于依赖倒置（DIP），所有上层节点只依赖 BaseLLMProvider 接口，
底层换模型（DeepSeek / Gemini / 本地 Ollama 等）只需新增子类，
无需改动任何上层业务逻辑。

【关键防坑配置】：
  - base_url 通过 OPENAI_BASE_URL 注入，支持代理/中转地址（DeepSeek 等兼容 OpenAI 格式的服务）
  - 未配置时 SDK 自动使用官方默认地址
  - response_format={"type": "json_object"} 强制 JSON 输出，彻底规避 LLM 输出格式不稳定问题
"""

import os
import json
from abc import ABC, abstractmethod

import openai


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------

class BaseLLMProvider(ABC):
    """
    所有 LLM 服务适配器必须实现的接口。
    上层节点（如 ScriptGenNode）只依赖该抽象类，与具体模型完全解耦。
    """

    @abstractmethod
    def generate_script(self, prompt: str, system_prompt: str) -> dict:
        """
        向 LLM 发送请求并返回结构化结果。

        Args:
            prompt:        用户指令（Human Turn）
            system_prompt: 系统提示词（角色 + 输出格式约束）

        Returns:
            解析后的 Python dict（LLM 返回的 JSON 内容）

        Raises:
            RuntimeError: 当 API 调用失败或返回内容无法解析为 JSON 时抛出
        """
        pass


# ---------------------------------------------------------------------------
# OpenAI / 兼容接口实现（DeepSeek、Moonshot、通义千问等）
# ---------------------------------------------------------------------------

class OpenAIProvider(BaseLLMProvider):
    """
    基于 OpenAI Python SDK 的 Provider。

    通过传入 base_url，可无缝切换至任何兼容 OpenAI Chat Completions API 的服务，
    例如：
      - DeepSeek:  OPENAI_BASE_URL=https://api.deepseek.com/v1
      - Moonshot:  OPENAI_BASE_URL=https://api.moonshot.cn/v1
      - 本地代理:  OPENAI_BASE_URL=http://localhost:8000/v1

    关键配置（均从环境变量读取，不硬编码敏感信息）：
      OPENAI_API_KEY    — 必填，API 密钥
      OPENAI_BASE_URL   — 选填，自定义接入地址；留空则走 SDK 默认 OpenAI 官方地址
      LLM_MODEL         — 选填，模型名称，默认 gpt-4o-mini
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        """
        Args:
            api_key:  API Key，默认从 OPENAI_API_KEY 环境变量读取
            base_url: 接入地址，默认从 OPENAI_BASE_URL 环境变量读取；
                      若均未配置，SDK 使用 OpenAI 官方默认地址
            model:    模型名称，默认从 LLM_MODEL 环境变量读取，兜底 gpt-4o-mini
        """
        resolved_api_key  = api_key  or os.getenv("OPENAI_API_KEY")
        resolved_base_url = base_url or os.getenv("OPENAI_BASE_URL") or None  # 空字符串转 None
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")

        # 构造客户端：base_url=None 时 SDK 自动忽略，走官方默认地址
        self._client = openai.OpenAI(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
        )

    def generate_script(self, prompt: str, system_prompt: str) -> dict:
        """
        调用 Chat Completions API，强制 JSON 输出，返回解析后的 dict。

        强制 JSON 输出方案：
          response_format={"type": "json_object"}
          同时在 system_prompt 中明确要求 JSON，双重保险。

        Raises:
            RuntimeError: API 调用异常 或 返回内容非合法 JSON
        """
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.7,
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
