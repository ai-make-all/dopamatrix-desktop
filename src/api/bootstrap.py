"""Bootstrap-safe invocation decisions before importing the application graph."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .runtime_paths import RuntimeMode, RuntimePaths, initialize_runtime_paths


@dataclass(frozen=True)
class BootstrapDecision:
    runtime_paths: RuntimePaths
    operator_requested: bool


def is_operator_invocation(argv: Sequence[str] | None = None) -> bool:
    """Recognize the exact operator entry without resolving or creating paths."""
    arguments = tuple(sys.argv if argv is None else argv)
    return len(arguments) > 1 and arguments[1] == "operator"


def prepare_bootstrap(argv: Sequence[str] | None = None) -> BootstrapDecision:
    """Initialize the normal server bootstrap after early operator dispatch."""
    arguments = tuple(sys.argv if argv is None else argv)
    paths = initialize_runtime_paths()
    return BootstrapDecision(
        runtime_paths=paths,
        operator_requested=is_operator_invocation(arguments),
    )


def apply_server_compatibility_cwd(decision: BootstrapDecision) -> None:
    """Retain install-resource lookup temporarily; never use CWD as authority."""
    if decision.runtime_paths.mode is RuntimeMode.PACKAGED:
        # H1 keeps legacy non-authoritative resource behavior. Database and
        # output authority already use absolute RuntimePaths.
        import os

        os.chdir(Path(sys.executable).resolve().parent)
