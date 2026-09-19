"""Bootstrap-safe invocation decision before importing the application graph."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .runtime_paths import RuntimeMode, RuntimePaths, initialize_runtime_paths


OPERATOR_COMMANDS_NOT_IMPLEMENTED_H1 = "OPERATOR_COMMANDS_NOT_IMPLEMENTED_H1"


@dataclass(frozen=True)
class BootstrapDecision:
    runtime_paths: RuntimePaths
    operator_requested: bool


def prepare_bootstrap(argv: Sequence[str] | None = None) -> BootstrapDecision:
    """Resolve path authority, then recognize the future operator namespace."""
    arguments = tuple(sys.argv if argv is None else argv)
    paths = initialize_runtime_paths()
    return BootstrapDecision(
        runtime_paths=paths,
        operator_requested=len(arguments) > 1 and arguments[1] == "operator",
    )


def apply_server_compatibility_cwd(decision: BootstrapDecision) -> None:
    """Retain install-resource lookup temporarily; never use CWD as authority."""
    if decision.runtime_paths.mode is RuntimeMode.PACKAGED:
        # H1 keeps legacy non-authoritative resource behavior. Database and
        # output authority already use absolute RuntimePaths.
        import os

        os.chdir(Path(sys.executable).resolve().parent)


def operator_placeholder_exit_code() -> int:
    print(OPERATOR_COMMANDS_NOT_IMPLEMENTED_H1, file=sys.stderr)
    return 2
