"""
ScriptGenNode — Phase 3: 文案生成节点

职责：
  接收用户对短视频的自然语言描述，调用 LLM 生成结构化分镜脚本，
  将结果写入 WorkflowContext.assets["script_data"]，供后续节点消费。

脚本 JSON 格式规范（scene 数组）：
  {
    "scenes": [
      {
        "duration": 5,
        "visual_prompt": "Low-angle shot of a car driving on a bumpy road...",
        "narrations": {
          "en": "Built to last, mile after mile.",
          "ar": "مصنوع ليدوم، ميلاً بعد ميل."
        }
      },
      ...
    ]
  }

System Prompt 来源：
  所有提示词均以 Jinja2 模板文件存放于 src/prompts/，由 PromptLoader 动态加载渲染。
  节点本身零硬编码，新增语言或调整措辞只需编辑对应 .jinja 文件。

  script_auto.jinja   — 模式 A：AI 从零智能创作分镜脚本
  script_rewrite.jinja — 模式 B：基准文案防查重矩阵洗稿
"""

import json
from typing import List, Optional

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.logger import logger
from src.services.llm_provider import BaseLLMProvider, OpenAIProvider
from src.utils.prompt_loader import prompt_loader


# 模式 → 模板文件名映射表（新增模式只需在此注册）
_MODE_TEMPLATE: dict[str, str] = {
    "auto":    "script_auto.jinja",
    "rewrite": "script_rewrite.jinja",
}

_DEFAULT_LANGUAGES: List[str] = ["en"]


# ---------------------------------------------------------------------------
# ScriptGenNode
# ---------------------------------------------------------------------------

class ScriptGenNode(BaseNode):
    """
    文案生成节点。

    期望 Context 中存在：
        context.assets["script"]: str
            用户对短视频的自然语言描述（What to make）

    执行后写入 Context：
        context.assets["script_data"]: dict
            解析后的分镜脚本 JSON（格式见模块文档）

    可选 Context 属性（均有安全 fallback）：
        context.script_mode:      str        — 'auto' | 'rewrite'，默认 'auto'
        context.batch_size:       int        — 矩阵变体数量，默认 1
        context.target_duration:  int        — 目标时长（秒），默认 15
        context.target_languages: List[str]  — 目标语种列表，默认 ["en"]

    依赖注入：
        可通过构造器传入任意 BaseLLMProvider 实现，默认使用 OpenAIProvider。
        这让单元测试可以注入 Mock Provider，无需真实 API 调用。
    """

    def __init__(
        self,
        name: str = "ScriptGenNode",
        provider: Optional[BaseLLMProvider] = None,
    ):
        """
        Args:
            name:     节点名称（用于日志）
            provider: LLM 服务适配器实例；为 None 时自动创建 OpenAIProvider（读取环境变量）
        """
        super().__init__(name)
        self._provider: BaseLLMProvider = provider or OpenAIProvider()

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        """
        执行文案生成流程：
          1. 从 Context 取出用户提示词及运行参数
          2. 根据 script_mode 选择对应 Jinja2 模板并渲染 System Prompt
          3. 调用 LLM Provider 生成结构化 JSON
          4. 验证 JSON 包含必要字段
          5. 将结果写入 Context.assets["script_data"]
        """
        user_prompt: str = context.get_asset("script") or ""

        if not user_prompt.strip():
            self.log("Warning: context.assets['script'] is empty, skipping.")
            return context

        # ── 从 Context 读取运行参数（全部带安全 fallback）──────────────────────
        script_mode:      str        = getattr(context, "script_mode",      "auto")
        batch_size:       int        = getattr(context, "batch_size",        1)
        target_duration:  int        = getattr(context, "target_duration",   15)
        target_languages: List[str]  = getattr(context, "target_languages",  _DEFAULT_LANGUAGES)

        # 防御：未知模式兜底到 auto
        if script_mode not in _MODE_TEMPLATE:
            self.log(f"Warning: unknown script_mode '{script_mode}', falling back to 'auto'.")
            script_mode = "auto"

        word_min = int(target_duration * 2.3)
        word_max = int(target_duration * 2.8)

        self.log(f"Calling LLM provider [{type(self._provider).__name__}]...")
        self.log(
            f"script_mode={script_mode} | batch_size={batch_size} "
            f"| duration={target_duration}s | langs={target_languages} "
            f"| word_range=[{word_min}, {word_max}]"
        )
        self.log(f"User prompt: {user_prompt[:80]}{'...' if len(user_prompt) > 80 else ''}")

        # ── 渲染 System Prompt（Jinja2 模板 → 纯文本）──────────────────────────
        template_name = _MODE_TEMPLATE[script_mode]
        effective_system_prompt: str = prompt_loader.render_prompt(
            template_name,
            target_languages=target_languages,
            batch_size=batch_size,
            target_duration=target_duration,
            word_min=word_min,
            word_max=word_max,
        )

        # ── 调用 LLM ────────────────────────────────────────────────────────────
        result: dict = self._provider.generate_script(
            prompt=user_prompt,
            system_prompt=effective_system_prompt,
        )

        # ── 基础结构校验 ─────────────────────────────────────────────────────────
        if "scenes" not in result or not isinstance(result["scenes"], list):
            raise ValueError(
                f"[{self.name}] LLM response missing required 'scenes' list.\n"
                f"Got: {json.dumps(result, ensure_ascii=False)}"
            )

        scene_count    = len(result["scenes"])
        total_duration = sum(s.get("duration", 0) for s in result["scenes"])
        self.log(
            f"Script generated: {scene_count} scenes, "
            f"estimated total duration: {total_duration}s"
        )

        # ── 写入 Context ─────────────────────────────────────────────────────────
        context.set_asset("script_data", result)
        self.log('script_data written to Context.assets["script_data"]')

        return context
