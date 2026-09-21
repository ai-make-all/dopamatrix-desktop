"""Explicit mutable-runtime path authority for source, packaged, and tests."""

from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator

from appdirs import user_data_dir


class RuntimeMode(str, Enum):
    PACKAGED = "PACKAGED"
    SOURCE_DEVELOPMENT = "SOURCE_DEVELOPMENT"
    TEST = "TEST"


class RuntimePathsError(RuntimeError):
    """Base class for stable runtime-path initialization failures."""


class RuntimePathsInitializationConflict(RuntimePathsError):
    def __init__(self) -> None:
        super().__init__("RUNTIME_PATHS_INITIALIZATION_CONFLICT")


class RuntimeRootUnavailable(RuntimePathsError):
    def __init__(self) -> None:
        super().__init__("RUNTIME_ROOT_UNAVAILABLE")


class LegacyRuntimeMigrationRequired(RuntimePathsError):
    def __init__(self) -> None:
        super().__init__("LEGACY_RUNTIME_MIGRATION_REQUIRED")


@dataclass(frozen=True)
class RuntimePaths:
    mode: RuntimeMode
    runtime_root: Path
    settings_db_path: Path
    tenant_data_dir: Path
    internal_output_root: Path

    def tenant_database_path(self, canonical_tenant: str) -> Path:
        return self.tenant_data_dir / f"dopamatrix_{canonical_tenant}.db"


_runtime_paths: RuntimePaths | None = None
_runtime_paths_lock = threading.RLock()


def detect_runtime_mode(*, frozen: bool | None = None) -> RuntimeMode:
    """Select packaged/source mode without environment-variable authority."""
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    return RuntimeMode.PACKAGED if is_frozen else RuntimeMode.SOURCE_DEVELOPMENT


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _packaged_install_root() -> Path:
    return Path(sys.executable).resolve().parent


def _has_meaningful_legacy_state(install_root: Path) -> bool:
    """Detect mutable legacy state, ignoring empty dirs and bundled resources."""
    try:
        if (install_root / "dopamatrix.db").is_file():
            return True

        data_dir = install_root / "data"
        if data_dir.is_dir() and any(
            path.is_file()
            for pattern in (
                "dopamatrix_*.db",
                "dopamatrix_*.db-wal",
                "dopamatrix_*.db-shm",
            )
            for path in data_dir.glob(pattern)
        ):
            return True

        output_dir = install_root / "output"
        return output_dir.is_dir() and next(output_dir.iterdir(), None) is not None
    except OSError as exc:
        # An unreadable packaged install root cannot be safely classified.
        raise LegacyRuntimeMigrationRequired() from exc


def resolve_runtime_paths(
    *,
    mode: RuntimeMode | None = None,
    runtime_root: str | os.PathLike[str] | None = None,
    source_root: str | os.PathLike[str] | None = None,
    packaged_install_root: str | os.PathLike[str] | None = None,
    user_data_dir_factory: Callable[[str, str], str] = user_data_dir,
    check_legacy: bool = True,
) -> RuntimePaths:
    """Resolve paths without creating, copying, deleting, or migrating state."""
    selected_mode = mode or detect_runtime_mode()
    if selected_mode is RuntimeMode.PACKAGED:
        selected_root = Path(
            runtime_root
            if runtime_root is not None
            else user_data_dir_factory("DopaMatrix", "DopaMatrixOrg")
        )
        install_root = Path(
            packaged_install_root
            if packaged_install_root is not None
            else _packaged_install_root()
        ).resolve(strict=False)
    elif selected_mode is RuntimeMode.SOURCE_DEVELOPMENT:
        selected_root = Path(
            runtime_root
            if runtime_root is not None
            else (source_root if source_root is not None else _source_root())
        )
        install_root = None
    elif selected_mode is RuntimeMode.TEST:
        if runtime_root is None:
            raise RuntimeRootUnavailable()
        selected_root = Path(runtime_root)
        install_root = None
    else:  # pragma: no cover - Enum exhaustiveness guard
        raise RuntimeRootUnavailable()

    root = selected_root.expanduser().resolve(strict=False)
    if not root.is_absolute():
        raise RuntimeRootUnavailable()

    if (
        selected_mode is RuntimeMode.PACKAGED
        and check_legacy
        and install_root is not None
        and install_root != root
        and _has_meaningful_legacy_state(install_root)
    ):
        raise LegacyRuntimeMigrationRequired()

    return RuntimePaths(
        mode=selected_mode,
        runtime_root=root,
        settings_db_path=root / "dopamatrix.db",
        tenant_data_dir=root / "data",
        internal_output_root=root / "output",
    )


def _prepare_runtime_directories(paths: RuntimePaths) -> None:
    try:
        paths.runtime_root.mkdir(parents=True, exist_ok=True)
        paths.tenant_data_dir.mkdir(parents=True, exist_ok=True)
        if not paths.runtime_root.is_dir() or not paths.tenant_data_dir.is_dir():
            raise OSError("runtime path is not a directory")
        if not os.access(paths.runtime_root, os.W_OK):
            raise OSError("runtime root is not writable")
    except OSError as exc:
        raise RuntimeRootUnavailable() from exc


def initialize_runtime_paths(
    *,
    mode: RuntimeMode | None = None,
    runtime_root: str | os.PathLike[str] | None = None,
    source_root: str | os.PathLike[str] | None = None,
    packaged_install_root: str | os.PathLike[str] | None = None,
    user_data_dir_factory: Callable[[str, str], str] = user_data_dir,
    check_legacy: bool = True,
) -> RuntimePaths:
    """Initialize one process-wide path authority, idempotently for one value."""
    candidate = resolve_runtime_paths(
        mode=mode,
        runtime_root=runtime_root,
        source_root=source_root,
        packaged_install_root=packaged_install_root,
        user_data_dir_factory=user_data_dir_factory,
        check_legacy=check_legacy,
    )
    global _runtime_paths
    with _runtime_paths_lock:
        if _runtime_paths is not None:
            if _runtime_paths != candidate:
                raise RuntimePathsInitializationConflict()
            return _runtime_paths
        _prepare_runtime_directories(candidate)
        _runtime_paths = candidate
        return candidate


def get_runtime_paths() -> RuntimePaths:
    """Return the initialized authority; direct source imports initialize safely."""
    with _runtime_paths_lock:
        current = _runtime_paths
    return current if current is not None else initialize_runtime_paths()


def get_initialized_runtime_paths() -> RuntimePaths | None:
    """Return the installed authority without initializing or creating paths."""
    with _runtime_paths_lock:
        return _runtime_paths


@contextmanager
def temporary_test_runtime_paths(
    runtime_root: str | os.PathLike[str],
) -> Iterator[RuntimePaths]:
    """Explicit test-only override that restores the prior process authority."""
    candidate = resolve_runtime_paths(mode=RuntimeMode.TEST, runtime_root=runtime_root)
    _prepare_runtime_directories(candidate)
    global _runtime_paths
    with _runtime_paths_lock:
        previous = _runtime_paths
        _runtime_paths = candidate
    try:
        yield candidate
    finally:
        with _runtime_paths_lock:
            if _runtime_paths is not candidate:
                raise RuntimePathsInitializationConflict()
            _runtime_paths = previous
