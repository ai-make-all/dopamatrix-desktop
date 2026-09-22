"""H4-3 crash-releasing lock and checked transaction regressions."""

from __future__ import annotations

import io
import json
import os
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from src.api.operator_cli import (
    OPERATOR_COMMAND_NOT_IMPLEMENTED,
    OperatorExitCode,
    run_operator_cli,
)
from src.api.operator_status import observe_operator_status
from src.api.policy_profiles import (
    OPERATIONAL_SNAPSHOT_SETTING_KEY,
    PhilippineSeedStage,
    build_applied_operational_snapshot,
    materialize_philippine_seed_profile,
    parse_applied_operational_snapshot,
)
from src.api.runtime_mutation import (
    RUNTIME_MUTATION_LOCK_FILENAME,
    MutationPrestateMismatch,
    MutationTransactionStateError,
    RuntimeMutationBarrierBusy,
    RuntimeMutationBarrierError,
    acquire_runtime_mutation_barrier,
    acquire_server_runtime_mutation_barrier,
    checked_immediate_transaction,
    release_server_runtime_mutation_barrier,
)
from src.api.runtime_paths import RuntimeMode, resolve_runtime_paths


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
TENANT = "ph-elv-0001"
GENERATION = "phseed-elv0001-bal-20260921-r1"
SYNTHETIC_SECRET = "synthetic-h4-3-assignment-secret"


def _runtime_paths(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    return resolve_runtime_paths(mode=RuntimeMode.TEST, runtime_root=root)


def _subprocess_environment() -> dict[str, str]:
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(REPOSITORY_ROOT)
        if not existing
        else os.pathsep.join((str(REPOSITORY_ROOT), existing))
    )
    return environment


def _start_lock_holder(root: Path) -> subprocess.Popen[str]:
    source = f"""
import sys
from src.api.runtime_mutation import acquire_runtime_mutation_barrier
from src.api.runtime_paths import RuntimeMode, resolve_runtime_paths
paths = resolve_runtime_paths(mode=RuntimeMode.TEST, runtime_root={str(root)!r})
barrier = acquire_runtime_mutation_barrier(paths)
print('LOCKED', flush=True)
sys.stdin.readline()
barrier.release()
print('RELEASED', flush=True)
"""
    process = subprocess.Popen(
        [str(PYTHON), "-c", source],
        cwd=REPOSITORY_ROOT,
        env=_subprocess_environment(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    ready = process.stdout.readline().strip()
    if ready != "LOCKED":
        stderr = "" if process.stderr is None else process.stderr.read()
        process.kill()
        process.wait(timeout=10)
        raise AssertionError(f"lock holder failed: {ready!r} {stderr!r}")
    return process


def _finish_lock_holder(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        assert process.stdin is not None
        process.stdin.write("release\n")
        process.stdin.flush()
    stdout, stderr = process.communicate(timeout=10)
    if process.returncode != 0 or stderr:
        raise AssertionError(
            f"lock holder exit={process.returncode} stdout={stdout!r} stderr={stderr!r}"
        )


def _independent_lock_probe(root: Path) -> subprocess.CompletedProcess[str]:
    source = f"""
from src.api.runtime_mutation import (
    RuntimeMutationBarrierBusy,
    acquire_runtime_mutation_barrier,
)
from src.api.runtime_paths import RuntimeMode, resolve_runtime_paths
paths = resolve_runtime_paths(mode=RuntimeMode.TEST, runtime_root={str(root)!r})
try:
    barrier = acquire_runtime_mutation_barrier(paths)
except RuntimeMutationBarrierBusy:
    print('BUSY')
    raise SystemExit(4)
else:
    print('ACQUIRED')
    barrier.release()
"""
    return subprocess.run(
        [str(PYTHON), "-c", source],
        cwd=REPOSITORY_ROOT,
        env=_subprocess_environment(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


class RuntimeMutationBarrierTests(unittest.TestCase):
    def tearDown(self) -> None:
        release_server_runtime_mutation_barrier()

    def test_first_acquire_release_and_stale_file_are_authority_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _runtime_paths(Path(directory) / "runtime")
            lock_path = paths.runtime_root / RUNTIME_MUTATION_LOCK_FILENAME

            barrier = acquire_runtime_mutation_barrier(paths)
            try:
                self.assertTrue(barrier.is_owned)
                self.assertTrue(lock_path.is_file())
                self.assertEqual(lock_path.stat().st_size, 1)
            finally:
                barrier.release()

            self.assertTrue(lock_path.is_file())
            self.assertEqual(lock_path.read_bytes(), b"\0")
            reacquired = acquire_runtime_mutation_barrier(paths)
            reacquired.release()
            self.assertEqual(lock_path.read_bytes(), b"\0")

    def test_repeated_acquisition_keeps_stable_one_byte_file(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _runtime_paths(Path(directory) / "runtime")
            lock_path = paths.runtime_root / RUNTIME_MUTATION_LOCK_FILENAME
            for _ in range(8):
                with acquire_runtime_mutation_barrier(paths):
                    self.assertEqual(lock_path.stat().st_size, 1)
            self.assertEqual(lock_path.stat().st_size, 1)
            self.assertEqual(lock_path.read_bytes(), b"\0")

    def test_missing_runtime_root_is_stable_subsystem_error(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = resolve_runtime_paths(
                mode=RuntimeMode.TEST,
                runtime_root=Path(directory) / "missing",
            )
            with self.assertRaisesRegex(
                RuntimeMutationBarrierError,
                "^RUNTIME_MUTATION_BARRIER_ERROR$",
            ):
                acquire_runtime_mutation_barrier(paths)

    def test_second_process_contention_is_prompt_and_clean_release_reacquires(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            paths = _runtime_paths(root)
            holder = _start_lock_holder(root)
            try:
                started = time.monotonic()
                with self.assertRaisesRegex(
                    RuntimeMutationBarrierBusy,
                    "^RUNTIME_MUTATION_BARRIER_BUSY$",
                ):
                    acquire_runtime_mutation_barrier(paths)
                self.assertLess(time.monotonic() - started, 2.0)
                self.assertTrue(
                    (root / RUNTIME_MUTATION_LOCK_FILENAME).is_file()
                )
            finally:
                _finish_lock_holder(holder)

            probe = _independent_lock_probe(root)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(probe.stdout.strip(), "ACQUIRED")

    @unittest.skipUnless(os.name == "nt", "authoritative msvcrt proof requires Windows")
    def test_windows_process_crash_releases_os_lock_without_file_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            paths = _runtime_paths(root)
            lock_path = root / RUNTIME_MUTATION_LOCK_FILENAME
            lock_path.write_bytes(b"\0")
            before = lock_path.read_bytes()
            holder = _start_lock_holder(root)
            try:
                with self.assertRaises(RuntimeMutationBarrierBusy):
                    acquire_runtime_mutation_barrier(paths)
                holder.kill()
                holder.communicate(timeout=10)
                self.assertTrue(lock_path.is_file())
                acquired = acquire_runtime_mutation_barrier(paths)
                acquired.release()
                self.assertEqual(lock_path.read_bytes(), before)
            finally:
                if holder.poll() is None:
                    holder.kill()
                    holder.wait(timeout=10)

    def test_platform_adapter_source_is_conditional_and_nonblocking(self):
        source = (REPOSITORY_ROOT / "src/api/runtime_mutation.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('if os.name == "nt"', source)
        self.assertIn("import msvcrt as _windows_locking", source)
        self.assertIn("_windows_locking.LK_NBLCK", source)
        self.assertIn("_windows_locking.LK_UNLCK", source)
        self.assertIn("import fcntl as _posix_locking", source)
        self.assertIn("_posix_locking.LOCK_EX | _posix_locking.LOCK_NB", source)
        self.assertIn("_posix_locking.LOCK_UN", source)

    def test_fake_server_lifetime_and_exception_release_same_barrier(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            paths = _runtime_paths(root)

            def fake_server(raise_failure: bool = False) -> None:
                acquire_server_runtime_mutation_barrier(paths)
                try:
                    probe = _independent_lock_probe(root)
                    self.assertEqual(probe.returncode, 4, probe.stderr)
                    self.assertEqual(probe.stdout.strip(), "BUSY")
                    if raise_failure:
                        raise RuntimeError("synthetic-startup-failure")
                finally:
                    release_server_runtime_mutation_barrier()

            fake_server()
            self.assertEqual(_independent_lock_probe(root).returncode, 0)
            with self.assertRaisesRegex(RuntimeError, "synthetic-startup-failure"):
                fake_server(raise_failure=True)
            self.assertEqual(_independent_lock_probe(root).returncode, 0)

    def test_main_contention_exits_four_before_application_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            paths = _runtime_paths(root)
            holder = acquire_runtime_mutation_barrier(paths)
            source = f"""
import json, runpy, sys
from unittest.mock import patch
from src.api.bootstrap import BootstrapDecision
from src.api.runtime_paths import RuntimeMode, resolve_runtime_paths
paths = resolve_runtime_paths(mode=RuntimeMode.TEST, runtime_root={str(root)!r})
sys.argv = [{str(REPOSITORY_ROOT / 'main.py')!r}]
exit_code = None
with patch('src.api.bootstrap.prepare_bootstrap', return_value=BootstrapDecision(paths, False)):
    try:
        runpy.run_path({str(REPOSITORY_ROOT / 'main.py')!r}, run_name='__main__')
    except SystemExit as exc:
        exit_code = exc.code
print(json.dumps({{
    'exit_code': exit_code,
    'fastapi': 'fastapi' in sys.modules,
    'database': 'src.api.database' in sys.modules,
    'routes': 'src.api.routes_dsl' in sys.modules,
    'uvicorn': 'uvicorn' in sys.modules,
    'ngrok': 'pyngrok' in sys.modules,
}}))
"""
            try:
                result = subprocess.run(
                    [str(PYTHON), "-c", source],
                    cwd=REPOSITORY_ROOT,
                    env=_subprocess_environment(),
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
            finally:
                holder.release()
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(observed["exit_code"], 4)
        for module in ("fastapi", "database", "routes", "uvicorn", "ngrok"):
            self.assertFalse(observed[module], module)
        self.assertEqual(
            result.stderr,
            "RUNTIME_MUTATION_BARRIER_BUSY: another backend or mutation is active\n",
        )

    def test_main_lifespan_startup_exception_releases_server_barrier(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            _runtime_paths(root)
            source = f"""
import asyncio, json, sys
from contextlib import asynccontextmanager
from unittest.mock import patch
import appdirs, dotenv
from src.api.bootstrap import BootstrapDecision
from src.api.runtime_mutation import acquire_runtime_mutation_barrier
from src.api.runtime_paths import RuntimeMode, initialize_runtime_paths
appdirs.user_log_dir = lambda *args, **kwargs: {str(root / 'logs')!r}
dotenv.load_dotenv = lambda *args, **kwargs: False
paths = initialize_runtime_paths(mode=RuntimeMode.TEST, runtime_root={str(root)!r})
sys.argv = ['main-lifespan-probe']
with patch('src.api.bootstrap.prepare_bootstrap', return_value=BootstrapDecision(paths, False)):
    import main
@asynccontextmanager
async def failing_lifespan(_app):
    raise RuntimeError('synthetic-startup-failure')
    yield
main._application_lifespan = failing_lifespan
async def exercise():
    try:
        async with main.lifespan(main.app):
            pass
    except RuntimeError as exc:
        return str(exc)
failure = asyncio.run(exercise())
barrier = acquire_runtime_mutation_barrier(paths)
barrier.release()
print(json.dumps({{'failure': failure, 'reacquired': True}}))
"""
            result = subprocess.run(
                [str(PYTHON), "-c", source],
                cwd=REPOSITORY_ROOT,
                env=_subprocess_environment(),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(
            observed,
            {"failure": "synthetic-startup-failure", "reacquired": True},
        )

    def test_status_remains_lock_free_while_barrier_is_owned(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _runtime_paths(Path(directory) / "runtime")
            with acquire_runtime_mutation_barrier(paths):
                config = observe_operator_status(("config", "status"), paths=paths)
                secret = observe_operator_status(
                    ("secret", "assignment", "status"), paths=paths
                )
                seed = observe_operator_status(
                    ("seed", "status"), tenant_id=TENANT, paths=paths
                )
            self.assertEqual((config.exit_code, config.status), (0, "NOT_INITIALIZED"))
            self.assertEqual((secret.exit_code, secret.status), (0, "ABSENT"))
            self.assertEqual(seed.exit_code, OperatorExitCode.NOT_FOUND)
            self.assertNotEqual(seed.error_code, "RUNTIME_MUTATION_BARRIER_BUSY")

    def test_all_future_mutation_and_backup_commands_remain_placeholders(self):
        commands = (
            ("tenant", "provision", "--tenant", TENANT, "--approval-ref", "A-1"),
            (
                "seed", "apply-safe-off", "--tenant", TENANT,
                "--generation", GENERATION, "--approval-ref", "A-1",
            ),
            (
                "seed", "prearm-p3w", "--tenant", TENANT,
                "--generation", GENERATION, "--backup-bundle", "X:/backup",
                "--approval-ref", "A-1",
            ),
            (
                "seed", "activate", "--tenant", TENANT, "--generation", GENERATION,
                "--backup-bundle", "X:/backup", "--approval-ref", "A-1",
            ),
            (
                "seed", "kill", "--tenant", TENANT, "--generation", GENERATION,
                "--reason-code", "INCIDENT",
            ),
            (
                "seed", "set-balanced-bps", "--tenant", TENANT,
                "--generation", GENERATION, "--bps", "3000",
                "--backup-bundle", "X:/backup", "--approval-ref", "A-1",
            ),
            (
                "seed", "transition-p3a", "--tenant", TENANT,
                "--generation", GENERATION, "--rollback-window", "7d",
                "--backup-bundle", "X:/backup", "--approval-ref", "A-1",
            ),
            (
                "secret", "assignment", "rotate", "--tenant", TENANT,
                "--expected-generation", GENERATION,
                "--new-generation", "phseed-elv0001-bal-20260921-r2",
                "--backup-bundle", "X:/backup", "--approval-ref", "A-1",
            ),
            (
                "backup", "create", "--tenant", TENANT,
                "--destination", "X:/new-backup",
            ),
            ("backup", "verify", "--bundle", "X:/backup"),
        )
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            os.chdir(directory)
            try:
                for command in commands:
                    with self.subTest(command=command):
                        stdout = io.StringIO()
                        stderr = io.StringIO()
                        code = run_operator_cli(
                            command, stdout=stdout, stderr=stderr
                        )
                        self.assertEqual(code, OperatorExitCode.STATE)
                        self.assertEqual(stdout.getvalue(), "")
                        self.assertTrue(
                            stderr.getvalue().startswith(
                                f"{OPERATOR_COMMAND_NOT_IMPLEMENTED}:"
                            )
                        )
                self.assertFalse(
                    (Path(directory) / RUNTIME_MUTATION_LOCK_FILENAME).exists()
                )
            finally:
                os.chdir(previous)


class CheckedImmediateTransactionTests(unittest.TestCase):
    def _database(self, root: Path) -> Path:
        path = root / "fixture.db"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "CREATE TABLE state (id INTEGER PRIMARY KEY, value TEXT NOT NULL);"
            )
            connection.execute("INSERT INTO state (id, value) VALUES (1, 'A');")
            connection.commit()
        return path

    @staticmethod
    def _read(connection: sqlite3.Connection) -> str:
        row = connection.execute("SELECT value FROM state WHERE id = 1;").fetchone()
        assert row is not None
        return str(row[0])

    def test_begin_reread_validate_write_and_single_commit_use_same_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._database(Path(directory))
            connection = sqlite3.connect(path)
            statements: list[str] = []
            identities: list[int] = []
            connection.set_trace_callback(statements.append)

            def reread(conn: sqlite3.Connection) -> str:
                identities.append(id(conn))
                return self._read(conn)

            def validate(conn: sqlite3.Connection, value: str) -> None:
                identities.append(id(conn))
                self.assertEqual(value, "A")

            with checked_immediate_transaction(
                connection,
                reread_prestate=reread,
                validate_prestate=validate,
            ) as transaction:
                identities.append(id(transaction.connection))
                self.assertEqual(transaction.prestate, "A")
                self.assertTrue(connection.in_transaction)
                transaction.connection.execute(
                    "UPDATE state SET value = 'B' WHERE id = 1;"
                )

            normalized = [statement.strip().upper() for statement in statements]
            begin_index = normalized.index("BEGIN IMMEDIATE;")
            select_index = next(
                index for index, statement in enumerate(normalized) if statement.startswith("SELECT")
            )
            self.assertLess(begin_index, select_index)
            self.assertEqual(normalized.count("COMMIT"), 1)
            self.assertEqual(set(identities), {id(connection)})
            self.assertFalse(connection.in_transaction)
            self.assertEqual(self._read(connection), "B")
            connection.close()

    def test_stale_expected_prestate_rejects_before_write_and_preserves_new_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._database(Path(directory))
            expected = "A"
            with closing(sqlite3.connect(path)) as updater:
                updater.execute("UPDATE state SET value = 'B' WHERE id = 1;")
                updater.commit()
            connection = sqlite3.connect(path)
            write_reached = False

            def validate(_connection: sqlite3.Connection, current: str) -> None:
                if current != expected:
                    raise MutationPrestateMismatch()

            with self.assertRaisesRegex(
                MutationPrestateMismatch, "^MUTATION_PRESTATE_MISMATCH$"
            ):
                with checked_immediate_transaction(
                    connection,
                    reread_prestate=self._read,
                    validate_prestate=validate,
                ) as transaction:
                    write_reached = True
                    transaction.connection.execute(
                        "UPDATE state SET value = 'C' WHERE id = 1;"
                    )
            self.assertFalse(write_reached)
            self.assertFalse(connection.in_transaction)
            self.assertEqual(self._read(connection), "B")
            connection.close()

    def test_validation_and_mutation_failures_rollback_and_leave_connection_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._database(Path(directory))
            connection = sqlite3.connect(path)

            def reject(_connection: sqlite3.Connection, _value: str) -> None:
                raise MutationPrestateMismatch()

            with self.assertRaises(MutationPrestateMismatch):
                with checked_immediate_transaction(
                    connection,
                    reread_prestate=self._read,
                    validate_prestate=reject,
                ):
                    self.fail("validation failure must not yield write authority")
            self.assertEqual(self._read(connection), "A")

            with self.assertRaisesRegex(RuntimeError, "synthetic-mutation-failure"):
                with checked_immediate_transaction(
                    connection,
                    reread_prestate=self._read,
                    validate_prestate=lambda _conn, value: self.assertEqual(value, "A"),
                ) as transaction:
                    transaction.connection.execute(
                        "UPDATE state SET value = 'B' WHERE id = 1;"
                    )
                    raise RuntimeError("synthetic-mutation-failure")
            self.assertFalse(connection.in_transaction)
            self.assertEqual(self._read(connection), "A")
            self.assertEqual(connection.execute("SELECT 1;").fetchone(), (1,))
            connection.close()

    def test_second_writer_is_busy_until_checked_transaction_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._database(Path(directory))
            first = sqlite3.connect(path)
            second = sqlite3.connect(path, timeout=0.05)
            with checked_immediate_transaction(
                first,
                reread_prestate=self._read,
                validate_prestate=lambda _conn, value: self.assertEqual(value, "A"),
            ):
                started = time.monotonic()
                with self.assertRaises(sqlite3.OperationalError):
                    second.execute("BEGIN IMMEDIATE;")
                self.assertLess(time.monotonic() - started, 1.0)
            second.execute("BEGIN IMMEDIATE;")
            second.execute("UPDATE state SET value = 'B' WHERE id = 1;")
            second.commit()
            self.assertEqual(self._read(first), "B")
            first.close()
            second.close()

    def test_existing_caller_transaction_is_not_hijacked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._database(Path(directory))
            connection = sqlite3.connect(path)
            connection.execute("UPDATE state SET value = 'CALLER' WHERE id = 1;")
            with self.assertRaisesRegex(
                MutationTransactionStateError,
                "^MUTATION_TRANSACTION_ALREADY_ACTIVE$",
            ):
                with checked_immediate_transaction(
                    connection,
                    reread_prestate=self._read,
                    validate_prestate=lambda _conn, _value: None,
                ):
                    self.fail("an existing transaction must not be entered")
            self.assertTrue(connection.in_transaction)
            self.assertEqual(self._read(connection), "CALLER")
            connection.rollback()
            self.assertEqual(self._read(connection), "A")
            connection.close()

    def test_foundation_adds_no_revision_version_etag_or_cas_column(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._database(Path(directory))
            connection = sqlite3.connect(path)
            before = tuple(connection.execute("PRAGMA table_info(state);").fetchall())
            with checked_immediate_transaction(
                connection,
                reread_prestate=self._read,
                validate_prestate=lambda _conn, value: self.assertEqual(value, "A"),
            ):
                pass
            after = tuple(connection.execute("PRAGMA table_info(state);").fetchall())
            self.assertEqual(after, before)
            column_names = {row[1].lower() for row in after}
            self.assertTrue(
                column_names.isdisjoint({"revision", "version", "etag", "cas"})
            )
            connection.close()

    def test_canonical_h3_snapshot_is_reread_inside_transaction_and_stale_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.db"
            values_a = materialize_philippine_seed_profile(
                tenant_id=TENANT,
                generation=GENERATION,
                stage=PhilippineSeedStage.P3_W,
                balanced_basis_points=3000,
                kill_switch=True,
            )
            values_b = materialize_philippine_seed_profile(
                tenant_id=TENANT,
                generation=GENERATION,
                stage=PhilippineSeedStage.P3_W,
                balanced_basis_points=3000,
                kill_switch=False,
            )
            snapshot_a = build_applied_operational_snapshot(
                effective_values=values_a,
                stage=PhilippineSeedStage.P3_W,
                applied_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
                audit_metadata={"operator": "synthetic-h4-3"},
                assignment_secret=SYNTHETIC_SECRET,
            )
            snapshot_b = build_applied_operational_snapshot(
                effective_values=values_b,
                stage=PhilippineSeedStage.P3_W,
                applied_at=datetime(2026, 9, 21, 0, 1, tzinfo=timezone.utc),
                audit_metadata={"operator": "synthetic-h4-3"},
                assignment_secret=SYNTHETIC_SECRET,
            )
            with closing(sqlite3.connect(path)) as setup:
                setup.execute(
                    "CREATE TABLE app_settings "
                    "(key_name TEXT PRIMARY KEY, key_value TEXT NOT NULL);"
                )
                setup.execute(
                    "INSERT INTO app_settings (key_name, key_value) VALUES (?, ?);",
                    (OPERATIONAL_SNAPSHOT_SETTING_KEY, snapshot_a.canonical_json()),
                )
                setup.commit()
            expected_canonical = snapshot_a.canonical_json()
            with closing(sqlite3.connect(path)) as updater:
                updater.execute(
                    "UPDATE app_settings SET key_value = ? WHERE key_name = ?;",
                    (snapshot_b.canonical_json(), OPERATIONAL_SNAPSHOT_SETTING_KEY),
                )
                updater.commit()

            connection = sqlite3.connect(path)
            business_write_reached = False

            def reread(conn: sqlite3.Connection):
                row = conn.execute(
                    "SELECT key_value FROM app_settings WHERE key_name = ?;",
                    (OPERATIONAL_SNAPSHOT_SETTING_KEY,),
                ).fetchone()
                assert row is not None
                return parse_applied_operational_snapshot(
                    row[0], assignment_secret=SYNTHETIC_SECRET
                )

            def validate(_conn: sqlite3.Connection, current) -> None:
                if current.canonical_json() != expected_canonical:
                    raise MutationPrestateMismatch()

            with self.assertRaises(MutationPrestateMismatch):
                with checked_immediate_transaction(
                    connection,
                    reread_prestate=reread,
                    validate_prestate=validate,
                ):
                    business_write_reached = True
            self.assertFalse(business_write_reached)
            row = connection.execute(
                "SELECT key_value FROM app_settings WHERE key_name = ?;",
                (OPERATIONAL_SNAPSHOT_SETTING_KEY,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], snapshot_b.canonical_json())
            connection.close()


if __name__ == "__main__":
    unittest.main()
