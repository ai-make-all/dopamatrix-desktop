"""Runtime configuration lifecycle boundaries.

The static operational mapping is installed once for a backend process and is
the Seed/Reservation plus startup-loaded LLM authority in packaged mode.
Dynamic machine settings deliberately retain their separate read-through
lifecycle.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterator, Mapping
from urllib.parse import urlsplit

from .runtime_paths import RuntimeMode, RuntimePaths, get_runtime_paths


DynamicMachineSettingReader = Callable[[str], str | None]

OPENAI_BASE_URL_SETTING_KEY = "openai_base_url"
LLM_MODEL_SETTING_KEY = "llm_model"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
LLM_PROVIDER_NAME = "OpenAI / Compatible API"


class LlmOperationalSettingsError(ValueError):
    """A non-secret LLM operational setting is invalid."""


@dataclass(frozen=True)
class LlmOperationalSettings:
    openai_base_url: str | None
    llm_model: str


def normalize_openai_base_url(value: str | None) -> str:
    """Normalize an optional absolute HTTP(S) provider URL."""
    normalized = "" if value is None else value.strip()
    if not normalized:
        return ""
    if any(character.isspace() for character in normalized):
        raise LlmOperationalSettingsError("OPENAI_BASE_URL_INVALID")
    try:
        parsed = urlsplit(normalized)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise LlmOperationalSettingsError("OPENAI_BASE_URL_INVALID") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise LlmOperationalSettingsError("OPENAI_BASE_URL_INVALID")
    return normalized


def normalize_llm_model(value: str | None) -> str:
    """Normalize an optional provider model name; blank selects the default."""
    return "" if value is None else value.strip()


def _read_llm_operational_mapping(
    connection: sqlite3.Connection,
) -> dict[str, str]:
    rows = connection.execute(
        "SELECT key_name, key_value FROM app_settings WHERE key_name IN (?, ?);",
        (OPENAI_BASE_URL_SETTING_KEY, LLM_MODEL_SETTING_KEY),
    ).fetchall()
    persisted = {str(row[0]): "" if row[1] is None else str(row[1]) for row in rows}
    base_url = normalize_openai_base_url(
        persisted.get(OPENAI_BASE_URL_SETTING_KEY)
    )
    model = normalize_llm_model(persisted.get(LLM_MODEL_SETTING_KEY))
    mapping: dict[str, str] = {}
    if base_url:
        mapping[OPENAI_BASE_URL_SETTING_KEY] = base_url
    if model:
        mapping[LLM_MODEL_SETTING_KEY] = model
    return mapping


def read_llm_operational_settings(
    database_path: str | os.PathLike[str] | Path,
) -> LlmOperationalSettings:
    """Read non-secret provider settings from the existing global settings DB."""
    with closing(sqlite3.connect(Path(database_path))) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS app_settings "
            "(key_name TEXT PRIMARY KEY, key_value TEXT);"
        )
        mapping = _read_llm_operational_mapping(connection)
    return LlmOperationalSettings(
        openai_base_url=mapping.get(OPENAI_BASE_URL_SETTING_KEY),
        llm_model=mapping.get(LLM_MODEL_SETTING_KEY, DEFAULT_LLM_MODEL),
    )


def save_llm_operational_settings(
    database_path: str | os.PathLike[str] | Path,
    *,
    openai_base_url: str | None,
    llm_model: str | None,
) -> LlmOperationalSettings:
    """Atomically persist validated LLM settings; blank values remove rows."""
    base_url = normalize_openai_base_url(openai_base_url)
    model = normalize_llm_model(llm_model)
    with closing(sqlite3.connect(Path(database_path))) as connection, connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS app_settings "
            "(key_name TEXT PRIMARY KEY, key_value TEXT);"
        )
        for key, value in (
            (OPENAI_BASE_URL_SETTING_KEY, base_url),
            (LLM_MODEL_SETTING_KEY, model),
        ):
            if value:
                connection.execute(
                    "INSERT OR REPLACE INTO app_settings (key_name, key_value) "
                    "VALUES (?, ?);",
                    (key, value),
                )
            else:
                connection.execute(
                    "DELETE FROM app_settings WHERE key_name = ?;",
                    (key,),
                )
    return LlmOperationalSettings(
        openai_base_url=base_url or None,
        llm_model=model or DEFAULT_LLM_MODEL,
    )


class StaticOperationalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SAFE_OFF_MISSING = "SAFE_OFF_MISSING"
    SAFE_OFF_INVALID = "SAFE_OFF_INVALID"


class RuntimeConfigProviderError(RuntimeError):
    """Stable provider lifecycle error."""


class RuntimeConfigProviderInitializationConflict(RuntimeConfigProviderError):
    def __init__(self) -> None:
        super().__init__("RUNTIME_CONFIG_PROVIDER_INITIALIZATION_CONFLICT")


@dataclass(frozen=True)
class RuntimeConfigProvider:
    """Keep static process configuration separate from dynamic machine reads.

    Seed configuration and startup-loaded non-secret provider settings share
    one immutable mapping without sharing persistence schemas with secrets.
    """

    paths: RuntimePaths
    _static_operational_mapping: Mapping[str, str] = field(repr=False)
    static_operational_status: StaticOperationalStatus = (
        StaticOperationalStatus.ACTIVE
    )
    static_operational_error_code: str | None = None
    _dynamic_machine_setting_reader: DynamicMachineSettingReader | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @classmethod
    def create(
        cls,
        *,
        paths: RuntimePaths,
        static_operational_mapping: Mapping[str, str],
        static_operational_status: StaticOperationalStatus = (
            StaticOperationalStatus.ACTIVE
        ),
        static_operational_error_code: str | None = None,
        dynamic_machine_setting_reader: DynamicMachineSettingReader | None = None,
    ) -> "RuntimeConfigProvider":
        snapshot = MappingProxyType(dict(static_operational_mapping))
        return cls(
            paths,
            snapshot,
            static_operational_status,
            static_operational_error_code,
            dynamic_machine_setting_reader,
        )

    @property
    def static_operational_mapping(self) -> Mapping[str, str]:
        return self._static_operational_mapping

    def read_dynamic_machine_setting(self, key: str) -> str | None:
        if self._dynamic_machine_setting_reader is None:
            return None
        return self._dynamic_machine_setting_reader(key)


_runtime_config_provider: RuntimeConfigProvider | None = None
_runtime_config_provider_lock = threading.RLock()
_EMPTY_MAPPING: Mapping[str, str] = MappingProxyType({})


def install_runtime_config_provider(
    provider: RuntimeConfigProvider,
) -> RuntimeConfigProvider:
    """Install one immutable process-generation provider.

    Reinstalling the same value is idempotent.  A different value requires a
    controlled process restart and therefore fails closed.
    """
    global _runtime_config_provider
    with _runtime_config_provider_lock:
        if _runtime_config_provider is not None:
            if _runtime_config_provider != provider:
                raise RuntimeConfigProviderInitializationConflict()
            return _runtime_config_provider
        _runtime_config_provider = provider
        return provider


def get_runtime_config_provider() -> RuntimeConfigProvider | None:
    with _runtime_config_provider_lock:
        return _runtime_config_provider


def reservation_runtime_mapping() -> Mapping[str, str]:
    """Return the explicit configuration source for Reservation consumers.

    Source development retains its bounded environment compatibility.  Test
    and packaged modes never fall back to the host environment.
    """
    paths = get_runtime_paths()
    if paths.mode is RuntimeMode.SOURCE_DEVELOPMENT:
        return os.environ
    provider = get_runtime_config_provider()
    if provider is None or provider.paths != paths:
        return _EMPTY_MAPPING
    return provider.static_operational_mapping


@contextmanager
def temporary_runtime_config_provider(
    provider: RuntimeConfigProvider,
) -> Iterator[RuntimeConfigProvider]:
    """Test-only scoped provider override that cannot reconfigure production."""
    if provider.paths.mode is not RuntimeMode.TEST:
        raise RuntimeConfigProviderInitializationConflict()
    global _runtime_config_provider
    with _runtime_config_provider_lock:
        previous = _runtime_config_provider
        _runtime_config_provider = provider
    try:
        yield provider
    finally:
        with _runtime_config_provider_lock:
            if _runtime_config_provider is not provider:
                raise RuntimeConfigProviderInitializationConflict()
            _runtime_config_provider = previous
