"""
DirectorNode — Phase 9.11.2 单轨线性一体化导演中枢

职责：
  - 单次 LLM 调用产出单轨融合蓝图：timeline 中每个 Beat 直接内聚 script_text。
  - 彻底废弃独立 script_data 根节点，实现台词（灵魂）与资产图层（肉体）空间绑定。
  - 解析层采用深度合并 + 可扩展键读取，未来追加 audio_effects / camera_moves 等
    无需改动核心编排，只需在 EXTENSION_KEYS 注册并消费。

WorkflowContext 契约（execute 路径）：
  读  context.assets["script"]、context.script_mode、context.target_languages、
      context.target_duration
  写  context.assets["tts_script"]   → {lang: "聚合全文"} 供 TTSNode 消费
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from src.core.base_node import BaseNode
from src.core.context import WorkflowContext
from src.core.logger import logger
from src.services.llm_provider import BaseLLMProvider, OpenAIProvider
from src.utils.prompt_loader import prompt_loader

# ── Schema Registry：单轨线性一体化契约（Phase 9.11.2）─────────────────────────
BLUEPRINT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["meta", "timeline"],
    "properties": {
        "meta": {
            "type": "object",
            "description": "全局社交媒体投放文案（Phase 9.12 归因管线）",
            "required": ["social_title", "social_caption", "social_hashtags", "human_drive", "emotional_tag"],
            "properties": {
                "social_title": {
                    "type": "string",
                    "description": "极具网感、带 Emoji 的短标题（≤20字）",
                },
                "social_caption": {
                    "type": "string",
                    "description": "情绪化描述文案，结尾必须包含占位符 {TRACKING_LINK}",
                },
                "social_hashtags": {
                    "type": "string",
                    "description": "3–5 个高流量话题标签，空格分隔",
                },
                "human_drive": {
                    "type": "string",
                    "description": "核心利用的人性本能/七宗罪，单选",
                },
                "emotional_tag": {
                    "type": "string",
                    "description": "情绪微标：纯英文驼峰或纯中文，2–4字/≤15字母，禁止空格标点",
                },
            },
        },
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
                    "script_text",
                    "visual_script",
                    "emotion",
                    "tts_params",
                    "duration",
                ],
                "properties": {
                    "beat":          {"type": "string"},
                    "role":          {"type": "string"},
                    "address_mode":  {"type": "string", "enum": ["smart", "locked"]},
                    "asset_hashes":  {"type": "array",  "items": {"type": "string"}},
                    "semantic_tags": {"type": "array",  "items": {"type": "string"}},
                    "script_text":   {"type": "string", "description": "该分镜的高光口播台词"},
                    "visual_script": {"type": "string", "description": "该分镜的画面动作描写、视觉特效与人物状态"},
                    "emotion": {
                        "type": "string",
                        "enum": ["焦虑", "愤怒", "扎心", "悬疑", "震惊", "渴望", "极度渴望", "专业", "舒缓", "解压"],
                        "description": "该分镜唯一核心情绪标签，必须从神经营销学情绪分类库中选择。",
                    },
                    "tts_params": {
                        "type": "string",
                        "enum": ["fast, high-pitch", "medium, heavy-stress", "slow, calm, low-pitch"],
                        "description": "匹配 emotion 所属象限的 TTS 语速/语调特征。",
                    },
                    "duration":      {"type": "number", "description": "该分镜预估时长（秒）"},
                },
            },
        },
        "audio_effects": {"type": "array", "description": "预留：音效时间轴"},
        "camera_moves":  {"type": "array", "description": "预留：运镜指令"},
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
        自适应字典合并：保证 timeline 默认值，并根级并入扩展键。
        单轨线性架构（Phase 9.11.2）：每个 Beat 必须含 script_text，无需 script_data 根节点。
        """
        seed: dict[str, Any] = {"meta": {}, "timeline": []}
        merged = self._deep_merge(seed, raw)

        if not isinstance(merged.get("timeline"), list) or not merged["timeline"]:
            raise ValueError(
                f"[{self.name}] LLM blueprint missing non-empty timeline."
            )

        # 防呆：过滤掉缺少 script_text 的 beat，并记录警告
        valid_beats = []
        for i, beat in enumerate(merged["timeline"]):
            if not isinstance(beat, dict):
                logger.warning("[%s] timeline[%d] 非对象，跳过: %r", self.name, i, beat)
                continue
            if not beat.get("script_text", "").strip():
                logger.warning(
                    "[%s] timeline[%d] beat=%r 缺少 script_text，已补充占位符",
                    self.name, i, beat.get("beat"),
                )
                beat["script_text"] = ""
            beat["visual_script"] = beat.get("visual_script") or ""
            beat["emotion"] = beat.get("emotion") or ""
            valid_beats.append(beat)

        if not valid_beats:
            raise ValueError(f"[{self.name}] LLM blueprint has no valid beats after filtering.")

        merged["timeline"] = valid_beats
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
            dict: 至少含 timeline（每个 Beat 内聚 script_text + duration）；
                  可含 audio_effects、camera_moves 等扩展键。
                  单轨线性架构（Phase 9.11.2）：不再返回独立 script_data 根节点。
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
        target_lang: str = (target_languages[0] if target_languages else None) or "en"

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

        # 单轨聚合：从 Beat 原位提取 script_text → tts_script[lang]
        beat_texts = [
            beat.get("script_text", "").strip()
            for beat in bp.get("timeline", [])
            if beat.get("script_text", "").strip()
        ]
        if beat_texts:
            context.set_asset("tts_script", {target_lang: "\n".join(beat_texts)})
            self.log(
                f"tts_script[{target_lang!r}] written to Context: "
                f"{len(beat_texts)} beats, {sum(len(t) for t in beat_texts)} chars"
            )
        else:
            self.log("Warning: no non-empty script_text found in timeline beats.")

        # 可选：供未来节点消费扩展切面
        for ek in EXTENSION_KEYS:
            if ek in bp:
                context.set_asset(ek, bp[ek])
        return context
