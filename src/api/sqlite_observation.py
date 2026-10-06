"""Shared read-only SQLite observation with fail-closed sidecar handling."""

from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


SQLITE_OBSERVATION_ABSENT = "SQLITE_OBSERVATION_ABSENT"
SQLITE_OBSERVATION_UNAVAILABLE = "SQLITE_OBSERVATION_UNAVAILABLE"
SQLITE_OBSERVATION_SIDECAR_UNSAFE = "SQLITE_OBSERVATION_SIDECAR_UNSAFE"
SQLITE_OBSERVATION_CHANGED_DURING_READ = (
    "SQLITE_OBSERVATION_CHANGED_DURING_READ"
)


class ReadonlySQLiteObservationError(RuntimeError):
    """A database cannot be observed under the reviewed read-only contract."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class _SQLiteFileObservation:
    size: int
    modified_ns: int
    device: int
    inode: int


def _observe_main_database(path: Path) -> _SQLiteFileObservation:
    try:
        metadata = path.stat()
    except FileNotFoundError as exc:
        raise ReadonlySQLiteObservationError(SQLITE_OBSERVATION_ABSENT) from exc
    except OSError as exc:
        raise ReadonlySQLiteObservationError(SQLITE_OBSERVATION_UNAVAILABLE) from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ReadonlySQLiteObservationError(SQLITE_OBSERVATION_UNAVAILABLE)
    return _SQLiteFileObservation(
        size=metadata.st_size,
        modified_ns=metadata.st_mtime_ns,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


def _sidecar_paths(path: Path) -> tuple[Path, Path, Path]:
    return (
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    )


def _sidecar_presence(path: Path) -> tuple[bool, bool, bool]:
    try:
        return tuple(os.path.lexists(item) for item in _sidecar_paths(path))
    except OSError as exc:
        raise ReadonlySQLiteObservationError(SQLITE_OBSERVATION_UNAVAILABLE) from exc


def _verify_sidecar_free_database(
    path: Path,
    expected_main: _SQLiteFileObservation,
) -> None:
    try:
        current_main = _observe_main_database(path)
        sidecar_appeared = any(_sidecar_presence(path))
    except ReadonlySQLiteObservationError as exc:
        raise ReadonlySQLiteObservationError(
            SQLITE_OBSERVATION_CHANGED_DURING_READ
        ) from exc
    if current_main != expected_main or sidecar_appeared:
        raise ReadonlySQLiteObservationError(SQLITE_OBSERVATION_CHANGED_DURING_READ)


@contextmanager
def open_readonly_sqlite(
    path: Path,
    *,
    timeout: float = 5.0,
) -> Iterator[sqlite3.Connection]:
    """Open one existing database without writes, repair, or stale WAL projection.

    Sidecar-free databases use immutable read-only mode so observation cannot
    create SQLite files. A complete WAL+SHM pair uses normal read-only mode so
    committed WAL state remains visible. Incomplete sidecars and rollback
    journals fail closed before SQLite is opened.
    """

    before = _observe_main_database(path)
    wal_exists, shm_exists, journal_exists = _sidecar_presence(path)
    if journal_exists or wal_exists != shm_exists:
        raise ReadonlySQLiteObservationError(SQLITE_OBSERVATION_SIDECAR_UNSAFE)

    query = "?mode=ro" if wal_exists else "?mode=ro&immutable=1"
    try:
        uri = path.resolve(strict=True).as_uri() + query
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        raise ReadonlySQLiteObservationError(SQLITE_OBSERVATION_UNAVAILABLE) from exc

    connection = sqlite3.connect(uri, uri=True, timeout=timeout)
    try:
        with closing(connection):
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON;")
            yield connection
    finally:
        if not wal_exists:
            _verify_sidecar_free_database(path, before)
