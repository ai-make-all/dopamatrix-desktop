"""
src/utils/prompt_loader.py
——————————————————————————
基于 Jinja2 的 LLM System Prompt 模板加载器。

设计原则：
  - 极简单例：模块加载时创建唯一的 `prompt_loader` 实例，调用方直接 import 使用。
  - 物理解耦：所有提示词以 .jinja 文件存放于 src/prompts/，节点代码零硬编码。
  - trim_blocks + lstrip_blocks：自动清理模板控制标签产生的多余空行与缩进，
    使渲染输出保持整洁，避免向 LLM 传入意外的空白符噪声。

用法：
    from src.utils.prompt_loader import prompt_loader

    rendered = prompt_loader.render_prompt(
        "script_auto.jinja",
        target_languages=["en", "ar", "zh"],
        target_duration=15,
        word_min=34,
        word_max=42,
    )
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound


# src/prompts/ 相对于本文件（src/utils/prompt_loader.py）的绝对路径
_PROMPTS_DIR: Path = Path(__file__).resolve().parent.parent / "prompts"


class PromptLoader:
    """
    Jinja2 模板加载器单例。

    通过 `FileSystemLoader` 挂载 src/prompts/ 目录，
    支持按文件名动态加载并渲染任意 .jinja 提示词模板。
    """

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(_PROMPTS_DIR)),
            trim_blocks=True,       # 自动去除块标签（{% %}）后的首个换行
            lstrip_blocks=True,     # 自动去除块标签所在行的行首空白
            keep_trailing_newline=True,
        )

    def render_prompt(self, template_name: str, **kwargs) -> str:
        """
        渲染指定的 Jinja2 提示词模板。

        Args:
            template_name: 模板文件名（相对于 src/prompts/），如 "script_auto.jinja"
            **kwargs:       传入模板的上下文变量

        Returns:
            渲染后的纯文本字符串，可直接作为 LLM system_prompt 使用

        Raises:
            FileNotFoundError: 模板文件不存在时抛出，附带完整路径提示
        """
        try:
            template = self._env.get_template(template_name)
        except TemplateNotFound:
            raise FileNotFoundError(
                f"[PromptLoader] 模板文件未找到: {_PROMPTS_DIR / template_name}\n"
                f"请确认 src/prompts/{template_name} 文件存在。"
            )
        return template.render(**kwargs)


# 模块级单例 —— 调用方只需 `from src.utils.prompt_loader import prompt_loader`
prompt_loader = PromptLoader()
