"""Runtime configuration lifecycle boundaries.

The static operational mapping is installed once for a backend process and is
the only Seed/Reservation authority in packaged mode.  Dynamic machine
settings deliberately retain their separate read-through lifecycle.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Callable, Iterator, Mapping

from .runtime_paths import RuntimeMode, RuntimePaths, get_runtime_paths


DynamicMachineSettingReader = Callable[[str], str | None]


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

    H1 does not migrate Seed configuration or secrets. It only establishes the
    provider shape that later phases can populate without changing lifecycle
    semantics.
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
