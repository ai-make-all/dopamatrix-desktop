"""Crash-releasing runtime mutation barrier and checked SQLite transactions."""

from __future__ import annotations

import atexit
import errno
import os
import sqlite3
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Generic, Iterator, TypeVar

from .runtime_paths import RuntimePaths


RUNTIME_MUTATION_LOCK_FILENAME = "dopamatrix-runtime-mutation.lock"


if os.name == "nt":  # pragma: no cover - platform-selected import
    import msvcrt as _windows_locking

    _posix_locking = None
else:  # pragma: no cover - exercised on POSIX only
    import fcntl as _posix_locking

    _windows_locking = None


class RuntimeMutationBarrierError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("RUNTIME_MUTATION_BARRIER_ERROR")


class RuntimeMutationBarrierBusy(RuntimeMutationBarrierError):
    def __init__(self) -> None:
        RuntimeError.__init__(self, "RUNTIME_MUTATION_BARRIER_BUSY")


class MutationTransactionError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("MUTATION_TRANSACTION_ERROR")


class MutationTransactionStateError(MutationTransactionError):
    def __init__(self) -> None:
        RuntimeError.__init__(self, "MUTATION_TRANSACTION_ALREADY_ACTIVE")


class MutationPrestateMismatch(RuntimeError):
    def __init__(self) -> None:
        super().__init__("MUTATION_PRESTATE_MISMATCH")


def runtime_mutation_lock_path(paths: RuntimePaths) -> Path:
    return paths.runtime_root / RUNTIME_MUTATION_LOCK_FILENAME


def _open_stable_lock_file(path: Path) -> BinaryIO:
    try:
        root = path.parent.stat()
    except OSError:
        raise RuntimeMutationBarrierError() from None
    if not stat.S_ISDIR(root.st_mode):
        raise RuntimeMutationBarrierError()

    handle: BinaryIO | None = None
    for _attempt in range(3):
        try:
            handle = path.open("x+b", buffering=0)
            break
        except FileExistsError:
            try:
                handle = path.open("r+b", buffering=0)
                break
            except FileNotFoundError:
                continue
            except OSError:
                raise RuntimeMutationBarrierError() from None
        except OSError:
            raise RuntimeMutationBarrierError() from None
    if handle is None:
        raise RuntimeMutationBarrierError()

    try:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("lock target is not a regular file")
        if metadata.st_size < 1:
            handle.seek(0)
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        return handle
    except OSError:
        handle.close()
        raise RuntimeMutationBarrierError() from None


def _is_expected_contention(exc: OSError) -> bool:
    return exc.errno in {errno.EACCES, errno.EAGAIN}


def _acquire_platform_lock(handle: BinaryIO) -> None:
    handle.seek(0)
    try:
        if os.name == "nt":
            assert _windows_locking is not None
            _windows_locking.locking(
                handle.fileno(),
                _windows_locking.LK_NBLCK,
                1,
            )
        else:  # pragma: no cover - exercised on POSIX only
            assert _posix_locking is not None
            _posix_locking.flock(
                handle.fileno(),
                _posix_locking.LOCK_EX | _posix_locking.LOCK_NB,
            )
    except OSError as exc:
        if _is_expected_contention(exc):
            raise RuntimeMutationBarrierBusy() from None
        raise RuntimeMutationBarrierError() from None


def _release_platform_lock(handle: BinaryIO) -> None:
    handle.seek(0)
    try:
        if os.name == "nt":
            assert _windows_locking is not None
            _windows_locking.locking(
                handle.fileno(),
                _windows_locking.LK_UNLCK,
                1,
            )
        else:  # pragma: no cover - exercised on POSIX only
            assert _posix_locking is not None
            _posix_locking.flock(handle.fileno(), _posix_locking.LOCK_UN)
    except OSError:
        raise RuntimeMutationBarrierError() from None


class RuntimeMutationBarrier:
    """One owned OS lock whose open handle defines the lock lifetime."""

    def __init__(self, lock_path: Path, handle: BinaryIO) -> None:
        self._lock_path = lock_path
        self._handle: BinaryIO | None = handle

    @classmethod
    def acquire(cls, paths: RuntimePaths) -> "RuntimeMutationBarrier":
        lock_path = runtime_mutation_lock_path(paths)
        handle = _open_stable_lock_file(lock_path)
        try:
            _acquire_platform_lock(handle)
        except BaseException:
            handle.close()
            raise
        return cls(lock_path, handle)

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    @property
    def is_owned(self) -> bool:
        return self._handle is not None

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            _release_platform_lock(handle)
        finally:
            handle.close()

    def __enter__(self) -> "RuntimeMutationBarrier":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


def acquire_runtime_mutation_barrier(paths: RuntimePaths) -> RuntimeMutationBarrier:
    """Acquire the reusable future mutating-operator barrier non-blockingly."""
    return RuntimeMutationBarrier.acquire(paths)


_server_barrier_guard = threading.RLock()
_server_barrier: RuntimeMutationBarrier | None = None


def acquire_server_runtime_mutation_barrier(
    paths: RuntimePaths,
) -> RuntimeMutationBarrier:
    """Acquire or return the one process-owned normal-server barrier."""
    global _server_barrier
    expected_path = runtime_mutation_lock_path(paths)
    with _server_barrier_guard:
        if _server_barrier is not None:
            if (
                not _server_barrier.is_owned
                or _server_barrier.lock_path != expected_path
            ):
                raise RuntimeMutationBarrierError()
            return _server_barrier
        _server_barrier = acquire_runtime_mutation_barrier(paths)
        return _server_barrier


def release_server_runtime_mutation_barrier() -> None:
    """Release the normal-server barrier without deleting its stable file."""
    global _server_barrier
    with _server_barrier_guard:
        barrier = _server_barrier
        _server_barrier = None
    if barrier is not None:
        barrier.release()


atexit.register(release_server_runtime_mutation_barrier)


PrestateT = TypeVar("PrestateT")


@dataclass(frozen=True)
class CheckedImmediateTransaction(Generic[PrestateT]):
    connection: sqlite3.Connection = field(repr=False)
    prestate: PrestateT


def _rollback_checked_transaction(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        return
    try:
        connection.rollback()
    except sqlite3.Error:
        raise MutationTransactionError() from None


@contextmanager
def checked_immediate_transaction(
    connection: sqlite3.Connection,
    *,
    reread_prestate: Callable[[sqlite3.Connection], PrestateT],
    validate_prestate: Callable[[sqlite3.Connection, PrestateT], None],
) -> Iterator[CheckedImmediateTransaction[PrestateT]]:
    """Reread and validate authoritative state inside one caller connection."""
    if connection.in_transaction:
        raise MutationTransactionStateError()

    try:
        connection.execute("BEGIN IMMEDIATE;")
    except sqlite3.Error:
        raise MutationTransactionError() from None

    try:
        prestate = reread_prestate(connection)
        validate_prestate(connection, prestate)
        yield CheckedImmediateTransaction(
            connection=connection,
            prestate=prestate,
        )
        connection.commit()
    except sqlite3.Error:
        _rollback_checked_transaction(connection)
        raise MutationTransactionError() from None
    except BaseException:
        _rollback_checked_transaction(connection)
        raise

