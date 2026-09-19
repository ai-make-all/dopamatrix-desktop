"""H1 lifecycle boundary for static operational and dynamic machine settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping

from .runtime_paths import RuntimePaths


DynamicMachineSettingReader = Callable[[str], str | None]


@dataclass(frozen=True)
class RuntimeConfigProvider:
    """Keep static process configuration separate from dynamic machine reads.

    H1 does not migrate Seed configuration or secrets. It only establishes the
    provider shape that later phases can populate without changing lifecycle
    semantics.
    """

    paths: RuntimePaths
    _static_operational_mapping: Mapping[str, str] = field(repr=False)
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
        dynamic_machine_setting_reader: DynamicMachineSettingReader | None = None,
    ) -> "RuntimeConfigProvider":
        snapshot = MappingProxyType(dict(static_operational_mapping))
        return cls(paths, snapshot, dynamic_machine_setting_reader)

    @property
    def static_operational_mapping(self) -> Mapping[str, str]:
        return self._static_operational_mapping

    def read_dynamic_machine_setting(self, key: str) -> str | None:
        if self._dynamic_machine_setting_reader is None:
            return None
        return self._dynamic_machine_setting_reader(key)

