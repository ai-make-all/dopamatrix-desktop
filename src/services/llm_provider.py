"""LLM provider abstraction with DPAPI-backed OpenAI credential authority."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

import openai

from src.api.secret_store import (
    SecretStoreError,
    get_default_secret_store,
    read_openai_secret_for_use,
)


# The cache intentionally contains only in-process plaintext needed by the
# provider. It is never represented in API status or logs and is explicitly
# invalidated after Settings replacement.
_api_key_cache: dict[str, str] = {}


def _load_api_key_from_db(setting_key: str = "openai_api_key") -> str:
    """Load the recognized secure key through the bounded provider cache."""
    if setting_key in _api_key_cache:
        return _api_key_cache[setting_key]
    if setting_key != "openai_api_key":
        raise ValueError("LLM_SECRET_KEY_UNSUPPORTED")
    try:
        result = read_openai_secret_for_use(get_default_secret_store()) or ""
    except (SecretStoreError, OSError) as exc:
        raise ValueError("LLM_SECRET_UNAVAILABLE") from exc
    _api_key_cache[setting_key] = result
    return result


def invalidate_api_key_cache(setting_key: str | None = None) -> None:
    """Invalidate one provider credential or the complete bounded cache."""
    if setting_key is not None:
        _api_key_cache.pop(setting_key, None)
    else:
        _api_key_cache.clear()


class BaseLLMProvider(ABC):
    @abstractmethod
    def generate_script(
        self,
        prompt: str,
        system_prompt: str,
        *,
        temperature: float | None = None,
    ) -> dict:
        """Generate a structured script."""
        raise NotImplementedError


class OpenAIProvider(BaseLLMProvider):
    """OpenAI/compatible chat-completions provider.

    The API key is resolved from ``secure_settings`` at request time (through
    the bounded cache). Non-secret endpoint/model development compatibility
    remains environment-backed until its later configuration phase.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self._base_url = base_url or os.getenv("OPENAI_BASE_URL") or None
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")

    def generate_script(
        self,
        prompt: str,
        system_prompt: str,
        *,
        temperature: float | None = None,
    ) -> dict:
        api_key = _load_api_key_from_db("openai_api_key")
        if not api_key:
            raise ValueError("LLM_SECRET_NOT_CONFIGURED")

        client = openai.OpenAI(api_key=api_key, base_url=self._base_url)
        requested_temperature = 0.7 if temperature is None else float(temperature)
        try:
            response = client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=requested_temperature,
            )
        except openai.OpenAIError as exc:
            # SDK failures are intentionally reduced to a stable message so a
            # provider exception cannot echo request headers or credentials.
            raise RuntimeError("OPENAI_PROVIDER_REQUEST_FAILED") from exc

        raw = response.choices[0].message.content or ""
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            # Do not echo model output through an exception/log path.
            raise RuntimeError("OPENAI_PROVIDER_RESPONSE_INVALID") from exc
