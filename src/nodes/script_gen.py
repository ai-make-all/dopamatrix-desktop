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
"""

import json
from typing import Optional

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.services.llm_provider import BaseLLMProvider, OpenAIProvider


# ---------------------------------------------------------------------------
# 系统提示词（决定 LLM 的角色与输出格式，是脚本质量的基石）
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
你是一位专注于出海短视频的资深编导，精通东南亚、中东等新兴市场的内容偏好与平台算法。
你的任务是根据用户的需求，生成一份专业、结构化的短视频分镜脚本。

【输出格式要求】
你必须且只能返回一个合法的 JSON 对象，格式如下：
{
  "scenes": [
    {
      "duration": <整数，该分镜的预估时长，单位：秒>,
      "visual_prompt": "<英文画面提示词，描述镜头内容、角度、氛围，供视频生成 AI 使用>",
      "narrations": {
        "en": "<英文旁白文案>",
        "ar": "<阿拉伯语旁白文案>"
      }
    }
  ]
}

【创作原则】
1. scenes 数量要合理，覆盖完整叙事弧（吸引→痛点→解决→行动号召）
2. visual_prompt 要写实、具体，避免抽象词汇，突出产品核心卖点
3. narrations 中英文和阿拉伯语均需情感饱满、口语化、贴近当地文化
4. duration 之和应接近用户要求的总时长
5. 不要在 JSON 外输出任何额外文字、注释或 Markdown 格式
"""


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
          1. 从 Context 取出用户提示词
          2. 调用 LLM Provider 生成结构化 JSON
          3. 验证 JSON 包含必要字段
          4. 将结果写入 Context.assets["script_data"]
        """
        user_prompt: str = context.get_asset("script") or ""

        if not user_prompt.strip():
            self.log("Warning: context.assets['script'] is empty, skipping.")
            return context

        self.log(f"Calling LLM provider [{type(self._provider).__name__}]...")
        self.log(f"User prompt: {user_prompt[:80]}{'...' if len(user_prompt) > 80 else ''}")

        # --- 调用 LLM ---
        result: dict = self._provider.generate_script(
            prompt=user_prompt,
            system_prompt=_SYSTEM_PROMPT,
        )

        # --- 基础结构校验 ---
        if "scenes" not in result or not isinstance(result["scenes"], list):
            raise ValueError(
                f"[{self.name}] LLM response missing required 'scenes' list.\n"
                f"Got: {json.dumps(result, ensure_ascii=False)}"
            )

        scene_count = len(result["scenes"])
        total_duration = sum(s.get("duration", 0) for s in result["scenes"])
        self.log(
            f"Script generated: {scene_count} scenes, "
            f"estimated total duration: {total_duration}s"
        )

        # --- 写入 Context ---
        context.set_asset("script_data", result)
        self.log("script_data written to Context.assets[\"script_data\"]")

        return context
