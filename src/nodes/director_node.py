"""
DirectorNode — Phase 9.2 全自动导演中枢（微管线 + 蓝图 Schema）

职责：
  - 单次 LLM 调用产出融合蓝图：视觉 timeline（DSL Beat 意向）与 script_data（TTS 消费）。
  - 解析层采用深度合并 + 可扩展键读取，未来追加 audio_effects / camera_moves 等
    无需改动核心编排，只需在 EXTENSION_KEYS 注册并消费。

WorkflowContext 契约（execute 路径）：
  读  context.assets["script"]、context.script_mode、context.target_languages、
      context.target_duration
  写  context.assets["script_data"]
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.logger import logger
from src.services.llm_provider import BaseLLMProvider, OpenAIProvider
from src.utils.prompt_loader import prompt_loader

# ── Schema Registry：契约说明（写入 Jinja，并供代码侧防呆参考）──────────────
BLUEPRINT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["timeline", "script_data"],
    "properties": {
        "timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "beat",
                    "role",
                    "address_mode",
                    "asset_hashes",
                    "semantic_tags",
                ],
            },
        },
        "script_data": {
            "type": "object",
            "required": ["scenes"],
            "properties": {
                "scenes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["duration", "visual_prompt", "narrations"],
                    },
                }
            },
        },
        "audio_effects": {"type": "array", "description": "预留：音效时间轴"},
        "camera_moves": {"type": "array", "description": "预留：运镜指令"},
    },
}

# Parser 层除 timeline / script_data 外，额外透传并入蓝图的扩展键（深合并根级）
EXTENSION_KEYS: tuple[str, ...] = ("audio_effects", "camera_moves")

_MODE_TEMPLATE: dict[str, str] = {
    "auto": "director_blueprint.jinja",
    "rewrite": "director_blueprint.jinja",
}


class DirectorNode(BaseNode):
    """
    导演节点：draft_blueprint 为同步战术板入口；execute 供 Workflow 混排复用。
    """

    def __init__(
        self,
        name: str = "DirectorNode",
        provider: Optional[BaseLLMProvider] = None,
    ):
        super().__init__(name)
        self._provider: BaseLLMProvider = provider or OpenAIProvider()

    # ── 微管线：Prompt → LLM → 扩展切面 ────────────────────────────────────

    def _build_core_prompt(
        self,
        mode: str,
        target_duration: int,
        langs: List[str],
        available_tags: Optional[List[str]] = None,
        user_hard_tags: Optional[List[str]] = None,
    ) -> str:
        if mode not in _MODE_TEMPLATE:
            logger.warning("[%s] unknown mode %r, fallback to auto", self.name, mode)
            mode = "auto"
        word_min = int(target_duration * 2.3)
        word_max = int(target_duration * 2.8)
        schema_json = json.dumps(BLUEPRINT_JSON_SCHEMA, ensure_ascii=False, indent=2)
        return prompt_loader.render_prompt(
            _MODE_TEMPLATE[mode],
            mode=mode,
            target_duration=target_duration,
            langs=langs,
            word_min=word_min,
            word_max=word_max,
            schema_json=schema_json,
            available_tags=available_tags or [],
            user_hard_tags=user_hard_tags or [],
        )

    def _execute_llm(self, user_prompt: str, system_prompt: str, *, temperature: float) -> dict:
        return self._provider.generate_script(
            user_prompt,
            system_prompt,
            temperature=temperature,
        )

    def _extend_blueprint_facets(self, blueprint: dict[str, Any]) -> dict[str, Any]:
        """
        预留扩展切面钩子：可在合并后对 audio_effects / camera_moves 做规范化。
        当前为恒等路径，保持骨架稳定。
        """
        return blueprint

    @staticmethod
    def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = dict(base)
        for key, val in incoming.items():
            if (
                key in out
                and isinstance(out[key], dict)
                and isinstance(val, dict)
            ):
                out[key] = DirectorNode._deep_merge(out[key], val)
            else:
                out[key] = val
        return out

    def _parse_llm_blueprint(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        自适应字典合并：保证 timeline / script_data 默认值，并根级并入扩展键。
        未来新增子模块时，只需把键加入 EXTENSION_KEYS（或依赖深合并自动保留未知键）。
        """
        seed: dict[str, Any] = {
            "timeline": [],
            "script_data": {"scenes": []},
        }
        merged = self._deep_merge(seed, raw)

        if not isinstance(merged.get("timeline"), list):
            merged["timeline"] = []
        sd = merged.get("script_data")
        if not isinstance(sd, dict):
            merged["script_data"] = {"scenes": []}
        elif not isinstance(sd.get("scenes"), list):
            merged["script_data"]["scenes"] = []

        scenes = merged["script_data"].get("scenes", [])
        if not scenes:
            raise ValueError(
                f"[{self.name}] LLM blueprint missing non-empty script_data.scenes."
            )
        if not merged["timeline"]:
            raise ValueError(
                f"[{self.name}] LLM blueprint missing non-empty timeline."
            )
        return self._extend_blueprint_facets(merged)

    def draft_blueprint(
        self,
        prompt: str,
        mode: str,
        duration: int,
        langs: List[str],
        *,
        available_tags: Optional[List[str]] = None,
        user_hard_tags: Optional[List[str]] = None,
        llm_temperature: float = 0.88,
    ) -> dict[str, Any]:
        """
        同步起草完整蓝图（战术板预览 / Worker 盲裂变）。

        available_tags: 素材库中真实存在的 Faceted Tags 列表；
                        若传入，将注入 Jinja 模板，强制 LLM 的
                        semantic_tags 只能从中挑选，杜绝幻觉。
        user_hard_tags: 前端剥离的硬约束标签，注入 Jinja 后作为绝对军令，
                        强制 LLM 在 timeline 中精确落位这些标签。

        Returns:
            dict: 至少含 timeline、script_data；可含 audio_effects、camera_moves 等扩展键。
        """
        if not prompt or not str(prompt).strip():
            raise ValueError(f"[{self.name}] prompt is empty.")
        if not langs:
            langs = ["en"]

        system_prompt = self._build_core_prompt(
            mode, duration, langs,
            available_tags or [],
            user_hard_tags or [],
        )
        raw = self._execute_llm(
            str(prompt).strip(),
            system_prompt,
            temperature=llm_temperature,
        )
        if not isinstance(raw, dict):
            raise ValueError(f"[{self.name}] LLM returned non-object JSON.")
        return self._parse_llm_blueprint(raw)

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        user_prompt: str = context.get_asset("script") or ""
        if not user_prompt.strip():
            self.log("Warning: context.assets['script'] is empty, skipping.")
            return context

        script_mode: str = getattr(context, "script_mode", "auto")
        target_duration: int = getattr(context, "target_duration", 15)
        target_languages: List[str] = getattr(context, "target_languages", ["en"])

        self.log(
            f"Director pipeline | mode={script_mode} | duration={target_duration}s "
            f"| langs={target_languages}"
        )
        bp = self.draft_blueprint(
            user_prompt,
            script_mode,
            target_duration,
            target_languages,
            llm_temperature=0.78,
        )
        context.set_asset("script_data", bp.get("script_data", {}))
        # 可选：供未来节点消费扩展切面
        for ek in EXTENSION_KEYS:
            if ek in bp:
                context.set_asset(ek, bp[ek])
        self.log('script_data written to Context.assets["script_data"]')
        return context
