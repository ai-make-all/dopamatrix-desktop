from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from src.api.operator_backup import OperatorBackupOutcome
from src.api.operator_cli import run_operator_cli
from src.api.operator_secret import (
    OPERATOR_ASSIGNMENT_SECRET_ROTATION_NO_CHANGE,
    OperatorSecretRotationOutcome,
    _default_connection,
    rotate_assignment_secret,
)
from src.api.operator_seed import (
    OPERATOR_RUNTIME_MUTATION_BUSY,
    OPERATOR_SEED_BACKUP_TENANT_MISMATCH,
    OPERATOR_SEED_GENERATION_INVALID,
    OPERATOR_SEED_SNAPSHOT_INTEGRITY_FAILED,
    OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
    OPERATOR_SEED_SUBSYSTEM_FAILED,
)
from src.api.policy_profiles import (
    ASSIGNMENT_SECRET_ENVIRONMENT_KEY,
    OPERATIONAL_SNAPSHOT_SETTING_KEY,
    PhilippineSeedStage,
    _write_snapshot_on_connection,
    apply_philippine_seed_profile,
    load_applied_runtime_config_provider,
    parse_applied_operational_snapshot,
)
from src.api.runtime_mutation import acquire_runtime_mutation_barrier
from src.api.runtime_paths import RuntimeMode, RuntimePaths
from src.api.secret_store import (
    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
    SecretDecryptionFailed,
    SecretStore,
)


TENANT = "ph-elv-0001"
GENERATION = "phseed-elv0001-bal-20260921-r1"
NEW_GENERATION = "phseed-elv0001-bal-20240103-r9"
THIRD_GENERATION = "phseed-elv0001-bal-20221231-r2"
FIXED_TIME = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
ROTATED_TIME = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
OLD_SECRET = "old-assignment-secret"
NEW_SECRET = "new-assignment-secret"

_BALANCED_BPS = "RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS"
_EXACT_BPS = "RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS"
_GENERATION = "RESERVATION_ROLLOUT_GENERATION"
_KILL = "RESERVATION_ROLLOUT_KILL_SWITCH"
_ROLLBACK_WINDOW = "RESERVATION_ROLLOUT_ROLLBACK_WINDOW"


class _IdentityProtector:
    scheme = "test-identity-v1"

    def protect(self, plaintext: bytes) -> bytes:
        return b"protected:" + plaintext

    def unprotect(self, ciphertext: bytes) -> bytes:
        prefix = b"protected:"
        if not ciphertext.startswith(prefix):
            raise ValueError("invalid test ciphertext")
        return ciphertext[len(prefix) :]


class _RejectNewSecretProtector(_IdentityProtector):
    def unprotect(self, ciphertext: bytes) -> bytes:
        plaintext = super().unprotect(ciphertext)
        if plaintext == NEW_SECRET.encode():
            raise SecretDecryptionFailed()
        return plaintext


class _BlankProtector(_IdentityProtector):
    def unprotect(self, ciphertext: bytes) -> bytes:
        del ciphertext
        return b""


class _ConnectionBoundOnlyStore(SecretStore):
    def _connect(self):
        raise AssertionError("rotation must use the caller-owned connection")


def _paths(root: Path) -> RuntimePaths:
    runtime = root / "runtime"
    tenant_data = runtime / "data"
    output = runtime / "output"
    tenant_data.mkdir(parents=True)
    output.mkdir()
    return RuntimePaths(
        mode=RuntimeMode.TEST,
        runtime_root=runtime,
        settings_db_path=runtime / "dopamatrix.db",
        tenant_data_dir=tenant_data,
        internal_output_root=output,
    )


def _store(
    paths: RuntimePaths,
    protector: _IdentityProtector | None = None,
) -> SecretStore:
    return SecretStore(paths.settings_db_path, protector or _IdentityProtector())


def _apply_fixture(
    paths: RuntimePaths,
    stage: PhilippineSeedStage,
    *,
    generation: str = GENERATION,
    balanced_bps: int | None = None,
    kill_switch: bool = True,
    rollback_window: str = "7d",
) -> None:
    apply_philippine_seed_profile(
        _store(paths),
        tenant_id=TENANT,
        generation=generation,
        stage=stage,
        balanced_basis_points=balanced_bps,
        kill_switch=kill_switch,
        rollback_window=rollback_window,
        audit_metadata={"fixture": "initial"},
        now=lambda: FIXED_TIME,
        secret_factory=lambda: OLD_SECRET,
    )


def _valid_backup(tenant: str = TENANT) -> OperatorBackupOutcome:
    return OperatorBackupOutcome(
        "VALID",
        "backup is valid",
        {"tenant": tenant, "asset_count": 0, "counts": {}},
    )


def _invoke(
    paths: RuntimePaths,
    *,
    expected_generation: str = GENERATION,
    new_generation: str = NEW_GENERATION,
    tenant: str = TENANT,
    backup_bundle: str = "X:/backup",
    approval_ref: str = "CHANGE-ROTATE-1",
    backup_verifier=None,
    secret_factory=None,
    store_factory=None,
    paths_initializer=None,
    barrier_factory=None,
    connection_factory=None,
    now=None,
):
    arguments = {
        "paths_initializer": paths_initializer or (lambda: paths),
        "store_factory": store_factory
        or (lambda active_paths: _store(active_paths)),
        "backup_verifier": backup_verifier
        or (lambda bundle: _valid_backup()),
        "secret_factory": secret_factory or (lambda: NEW_SECRET),
        "now": now or (lambda: ROTATED_TIME),
    }
    if barrier_factory is not None:
        arguments["barrier_factory"] = barrier_factory
    if connection_factory is not None:
        arguments["connection_factory"] = connection_factory
    return rotate_assignment_secret(
        tenant,
        expected_generation,
        new_generation,
        backup_bundle,
        approval_ref,
        **arguments,
    )


def _database_rows(paths: RuntimePaths):
    with closing(sqlite3.connect(paths.settings_db_path)) as connection:
        snapshot = connection.execute(
            "SELECT key_value FROM app_settings WHERE key_name = ?;",
            (OPERATIONAL_SNAPSHOT_SETTING_KEY,),
        ).fetchone()
        secret = connection.execute(
            "SELECT encryption_scheme, ciphertext, updated_at "
            "FROM secure_settings WHERE key_name = ?;",
            (RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,),
        ).fetchone()
    return snapshot, secret


def _secret(paths: RuntimePaths) -> str | None:
    return _store(paths).get_secret(RESERVATION_ROLLOUT_ASSIGNMENT_SECRET)


def _snapshot(paths: RuntimePaths):
    assignment_secret = _secret(paths)
    assert assignment_secret is not None
    with closing(sqlite3.connect(paths.settings_db_path)) as connection:
        serialized = connection.execute(
            "SELECT key_value FROM app_settings WHERE key_name = ?;",
            (OPERATIONAL_SNAPSHOT_SETTING_KEY,),
        ).fetchone()[0]
    return parse_applied_operational_snapshot(
        serialized,
        assignment_secret=assignment_secret,
    )


class OperatorSecretRotationSuccessTests(unittest.TestCase):
    def _assert_rotation(
        self,
        stage: PhilippineSeedStage,
        *,
        balanced_bps: int | None,
        rollback_window: str,
    ):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                stage,
                balanced_bps=balanced_bps,
                rollback_window=rollback_window,
            )
            before = _snapshot(paths)
            result = _invoke(paths)
            self.assertEqual((result.exit_code, result.status), (0, "ROTATED"))
            self.assertIsNone(result.error_code)
            self.assertEqual(
                dict(result.data),
                {
                    "tenant": TENANT,
                    "old_generation": GENERATION,
                    "new_generation": NEW_GENERATION,
                    "kill_switch": True,
                    "assignment_secret_status": "PRESENT",
                    "restart_required": True,
                },
            )
            after = _snapshot(paths)
            expected_values = dict(before.effective_values)
            expected_values[_GENERATION] = NEW_GENERATION
            self.assertEqual(dict(after.effective_values), expected_values)
            self.assertEqual(len(after.effective_values), 32)
            self.assertEqual(after.stage, before.stage)
            self.assertEqual(after.tenant_allowlist, before.tenant_allowlist)
            self.assertEqual(after.generation, NEW_GENERATION)
            self.assertEqual(after.effective_values[_KILL], "true")
            self.assertEqual(after.applied_at_utc, ROTATED_TIME.isoformat())
            self.assertEqual(
                dict(after.audit_metadata),
                {
                    "operator_command": "secret.assignment.rotate",
                    "approval_ref": "CHANGE-ROTATE-1",
                },
            )
            self.assertEqual(_secret(paths), NEW_SECRET)
            emitted = result.message + json.dumps(dict(result.data))
            for forbidden in (OLD_SECRET, NEW_SECRET, "protected:"):
                self.assertNotIn(forbidden, emitted)
            return before, after

    def test_safe_off_rotation_preserves_complete_contained_family(self):
        before, after = self._assert_rotation(
            PhilippineSeedStage.SAFE_OFF,
            balanced_bps=None,
            rollback_window="7d",
        )
        self.assertEqual(after.effective_values[_BALANCED_BPS], "0")
        self.assertEqual(after.effective_values[_EXACT_BPS], "0")
        self.assertEqual(after.effective_values[_ROLLBACK_WINDOW], "7d")
        self.assertEqual(after.stage, before.stage)

    def test_p3w_rotation_preserves_complete_contained_family(self):
        before, after = self._assert_rotation(
            PhilippineSeedStage.P3_W,
            balanced_bps=3250,
            rollback_window="7d",
        )
        self.assertEqual(after.effective_values[_BALANCED_BPS], "3250")
        self.assertEqual(after.effective_values[_ROLLBACK_WINDOW], "7d")
        self.assertEqual(after.stage, before.stage)

    def test_p3a_7d_rotation_preserves_complete_active_family(self):
        before, after = self._assert_rotation(
            PhilippineSeedStage.P3_A,
            balanced_bps=3500,
            rollback_window="7d",
        )
        self.assertEqual(after.effective_values[_BALANCED_BPS], "3500")
        self.assertEqual(after.effective_values[_ROLLBACK_WINDOW], "7d")
        self.assertEqual(after.stage, before.stage)

    def test_p3a_24h_rotation_preserves_containment_and_provider_immutability(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_A,
                balanced_bps=3750,
                rollback_window="24h",
            )
            loaded = load_applied_runtime_config_provider(paths, _store(paths))
            before = _snapshot(paths)
            result = _invoke(paths)
            self.assertEqual((result.exit_code, result.status), (0, "ROTATED"))
            after = _snapshot(paths)
            expected_values = dict(before.effective_values)
            expected_values[_GENERATION] = NEW_GENERATION
            self.assertEqual(dict(after.effective_values), expected_values)
            self.assertEqual(after.stage, PhilippineSeedStage.P3_A)
            self.assertEqual(after.effective_values[_ROLLBACK_WINDOW], "24h")
            self.assertEqual(after.effective_values[_KILL], "true")
            self.assertEqual(after.effective_values[_BALANCED_BPS], "3750")
            self.assertEqual(
                loaded.static_operational_mapping[_GENERATION],
                GENERATION,
            )
            self.assertEqual(
                loaded.static_operational_mapping[ASSIGNMENT_SECRET_ENVIRONMENT_KEY],
                OLD_SECRET,
            )
            reloaded = load_applied_runtime_config_provider(paths, _store(paths))
            self.assertEqual(
                reloaded.static_operational_mapping[_GENERATION],
                NEW_GENERATION,
            )
            self.assertEqual(
                reloaded.static_operational_mapping[
                    ASSIGNMENT_SECRET_ENVIRONMENT_KEY
                ],
                NEW_SECRET,
            )

    def test_rotation_uses_only_the_caller_owned_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
            )
            result = _invoke(
                paths,
                store_factory=lambda active_paths: _ConnectionBoundOnlyStore(
                    active_paths.settings_db_path,
                    _IdentityProtector(),
                ),
            )
            self.assertEqual((result.exit_code, result.status), (0, "ROTATED"))


class OperatorSecretRotationPreconditionTests(unittest.TestCase):
    def test_active_p3_states_fail_without_secret_generation_or_writes(self):
        cases = (
            (PhilippineSeedStage.P3_W, "7d"),
            (PhilippineSeedStage.P3_A, "7d"),
            (PhilippineSeedStage.P3_A, "24h"),
        )
        for stage, window in cases:
            with self.subTest(stage=stage, window=window), tempfile.TemporaryDirectory() as directory:
                paths = _paths(Path(directory))
                _apply_fixture(
                    paths,
                    stage,
                    balanced_bps=3000,
                    kill_switch=False,
                    rollback_window=window,
                )
                before = _database_rows(paths)
                factory = Mock(return_value=NEW_SECRET)
                result = _invoke(paths, secret_factory=factory)
                self.assertEqual(
                    (result.exit_code, result.error_code),
                    (4, OPERATOR_SEED_SNAPSHOT_STATE_INVALID),
                )
                factory.assert_not_called()
                self.assertEqual(_database_rows(paths), before)

    def test_generation_inputs_are_strictly_tenant_bound_and_well_formed(self):
        cases = (
            (
                "phseed-bty0001-bal-20260921-r1",
                NEW_GENERATION,
            ),
            (
                GENERATION,
                "phseed-bty0001-bal-20260921-r2",
            ),
            ("bad-generation", NEW_GENERATION),
            (GENERATION, "phseed-elv0001-bal-20260230-r2"),
        )
        for expected, new in cases:
            with self.subTest(expected=expected, new=new), tempfile.TemporaryDirectory() as directory:
                paths = _paths(Path(directory))
                initializer = Mock(side_effect=AssertionError("runtime must not initialize"))
                verifier = Mock(side_effect=AssertionError("backup must not verify"))
                result = _invoke(
                    paths,
                    expected_generation=expected,
                    new_generation=new,
                    paths_initializer=initializer,
                    backup_verifier=verifier,
                )
                self.assertEqual(
                    (result.exit_code, result.error_code),
                    (3, OPERATOR_SEED_GENERATION_INVALID),
                )
                initializer.assert_not_called()
                verifier.assert_not_called()

    def test_same_generation_is_rejected_before_backup_or_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            verifier = Mock(side_effect=AssertionError("backup must not verify"))
            initializer = Mock(side_effect=AssertionError("runtime must not initialize"))
            result = _invoke(
                paths,
                new_generation=GENERATION,
                backup_verifier=verifier,
                paths_initializer=initializer,
            )
            self.assertEqual(
                (result.exit_code, result.error_code),
                (4, OPERATOR_SEED_SNAPSHOT_STATE_INVALID),
            )
            verifier.assert_not_called()
            initializer.assert_not_called()

    def test_authoritative_generation_mismatch_fails_before_secret_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
            )
            before = _database_rows(paths)
            factory = Mock(return_value=NEW_SECRET)
            result = _invoke(
                paths,
                expected_generation=THIRD_GENERATION,
                new_generation=NEW_GENERATION,
                secret_factory=factory,
            )
            self.assertEqual(
                (result.exit_code, result.error_code),
                (4, OPERATOR_SEED_SNAPSHOT_STATE_INVALID),
            )
            factory.assert_not_called()
            self.assertEqual(_database_rows(paths), before)

    def test_nonsequential_historical_new_generation_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
            )
            result = _invoke(paths, new_generation=NEW_GENERATION)
            self.assertEqual((result.exit_code, result.status), (0, "ROTATED"))
            self.assertEqual(_snapshot(paths).generation, NEW_GENERATION)

    def test_same_generated_secret_fails_with_stable_code_and_zero_write(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
            )
            before = _database_rows(paths)
            result = _invoke(
                paths,
                secret_factory=lambda: OLD_SECRET,
            )
            self.assertEqual(
                (result.exit_code, result.error_code),
                (4, OPERATOR_ASSIGNMENT_SECRET_ROTATION_NO_CHANGE),
            )
            self.assertEqual(_database_rows(paths), before)
            self.assertNotIn(OLD_SECRET, result.message)

    def test_repeat_rotation_fails_stale_expected_without_generating_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
            )
            verifier = Mock(side_effect=lambda bundle: _valid_backup())
            first = _invoke(paths, backup_verifier=verifier)
            self.assertEqual((first.exit_code, first.status), (0, "ROTATED"))
            self.assertEqual(verifier.call_count, 1)
            before_second = _database_rows(paths)
            second_factory = Mock(return_value="third-secret")
            second = _invoke(
                paths,
                backup_verifier=verifier,
                secret_factory=second_factory,
            )
            self.assertEqual(
                (second.exit_code, second.error_code),
                (4, OPERATOR_SEED_SNAPSHOT_STATE_INVALID),
            )
            self.assertEqual(verifier.call_count, 2)
            self.assertNotEqual(second.status, "ALREADY_ROTATED")
            second_factory.assert_not_called()
            self.assertEqual(_database_rows(paths), before_second)

    def test_backup_failures_precede_runtime_and_authoritative_state(self):
        cases = (
            OperatorBackupOutcome(
                "ERROR",
                "missing",
                {},
                5,
                "OPERATOR_BACKUP_BUNDLE_NOT_FOUND",
            ),
            OperatorBackupOutcome(
                "ERROR",
                "corrupt",
                {},
                6,
                "OPERATOR_BACKUP_INTEGRITY_FAILED",
            ),
            _valid_backup("ph-bty-0001"),
        )
        for outcome in cases:
            with self.subTest(status=outcome.status, tenant=outcome.data.get("tenant")):
                paths = Mock(spec=RuntimePaths)
                verifier = Mock(return_value=outcome)
                initializer = Mock(side_effect=AssertionError("runtime must not initialize"))
                result = rotate_assignment_secret(
                    TENANT,
                    GENERATION,
                    NEW_GENERATION,
                    "X:/backup",
                    "CHANGE-1",
                    backup_verifier=verifier,
                    paths_initializer=initializer,
                )
                expected = (
                    OPERATOR_SEED_BACKUP_TENANT_MISMATCH
                    if outcome.error_code is None
                    else outcome.error_code
                )
                self.assertEqual(result.error_code, expected)
                verifier.assert_called_once_with("X:/backup")
                initializer.assert_not_called()


class OperatorSecretRotationIntegrityAndAtomicityTests(unittest.TestCase):
    def test_default_connection_requires_existing_database_without_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing.db"
            with self.assertRaises((OSError, sqlite3.Error)):
                _default_connection(database)
            for suffix in ("", "-wal", "-shm", "-journal"):
                self.assertFalse(Path(str(database) + suffix).exists())

    def test_disappearance_after_is_file_does_not_recreate_database(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
            )
            original_bytes = paths.settings_db_path.read_bytes()
            renamed = paths.settings_db_path.with_name("original-dopamatrix.db")
            factory = Mock(return_value=NEW_SECRET)

            def disappear_before_open(database: Path) -> sqlite3.Connection:
                self.assertTrue(database.is_file())
                database.replace(renamed)
                return _default_connection(database)

            result = _invoke(
                paths,
                connection_factory=disappear_before_open,
                secret_factory=factory,
            )
            self.assertEqual(
                (result.exit_code, result.error_code),
                (8, OPERATOR_SEED_SUBSYSTEM_FAILED),
            )
            factory.assert_not_called()
            self.assertTrue(renamed.is_file())
            self.assertEqual(renamed.read_bytes(), original_bytes)
            for suffix in ("", "-wal", "-shm", "-journal"):
                self.assertFalse(
                    Path(str(paths.settings_db_path) + suffix).exists()
                )

    def test_missing_corrupt_or_blank_current_secret_fails_before_generation(self):
        for case in ("missing", "corrupt", "blank"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                paths = _paths(Path(directory))
                _apply_fixture(
                    paths,
                    PhilippineSeedStage.P3_W,
                    balanced_bps=3000,
                )
                with closing(sqlite3.connect(paths.settings_db_path)) as connection, connection:
                    if case == "missing":
                        connection.execute(
                            "DELETE FROM secure_settings WHERE key_name = ?;",
                            (RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,),
                        )
                    elif case == "corrupt":
                        connection.execute(
                            "UPDATE secure_settings SET ciphertext = ? "
                            "WHERE key_name = ?;",
                            (
                                sqlite3.Binary(b"corrupt"),
                                RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
                            ),
                        )
                before = _database_rows(paths)
                factory = Mock(return_value=NEW_SECRET)
                store_factory = None
                if case == "blank":
                    store_factory = lambda active_paths: _store(
                        active_paths,
                        _BlankProtector(),
                    )
                result = _invoke(
                    paths,
                    secret_factory=factory,
                    store_factory=store_factory,
                )
                self.assertIn(result.exit_code, {6, 8})
                self.assertIn(
                    result.error_code,
                    {
                        OPERATOR_SEED_SNAPSHOT_INTEGRITY_FAILED,
                        OPERATOR_SEED_SUBSYSTEM_FAILED,
                    },
                )
                factory.assert_not_called()
                self.assertEqual(_database_rows(paths), before)

    def test_invalid_snapshot_fails_before_secret_generation_or_write(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
            )
            with closing(sqlite3.connect(paths.settings_db_path)) as connection, connection:
                connection.execute(
                    "UPDATE app_settings SET key_value = ? WHERE key_name = ?;",
                    ("not-json", OPERATIONAL_SNAPSHOT_SETTING_KEY),
                )
            before = _database_rows(paths)
            factory = Mock(return_value=NEW_SECRET)
            result = _invoke(paths, secret_factory=factory)
            self.assertEqual(
                (result.exit_code, result.error_code),
                (6, OPERATOR_SEED_SNAPSHOT_INTEGRITY_FAILED),
            )
            factory.assert_not_called()
            self.assertEqual(_database_rows(paths), before)

    def test_new_secret_decrypt_verification_failure_rolls_back_both_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
            )
            before = _database_rows(paths)
            result = _invoke(
                paths,
                store_factory=lambda active_paths: _store(
                    active_paths,
                    _RejectNewSecretProtector(),
                ),
            )
            self.assertEqual(
                (result.exit_code, result.error_code),
                (8, OPERATOR_SEED_SUBSYSTEM_FAILED),
            )
            self.assertEqual(_database_rows(paths), before)
            self.assertEqual(_secret(paths), OLD_SECRET)

    def test_failure_after_secret_write_rolls_back_secret_and_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
            )
            before = _database_rows(paths)
            with patch(
                "src.api.operator_secret._write_snapshot_on_connection",
                side_effect=sqlite3.OperationalError("synthetic write failure"),
            ):
                result = _invoke(paths)
            self.assertEqual(
                (result.exit_code, result.error_code),
                (8, OPERATOR_SEED_SUBSYSTEM_FAILED),
            )
            self.assertEqual(_database_rows(paths), before)
            self.assertEqual(_secret(paths), OLD_SECRET)

    def test_authoritative_reread_rejects_changed_prestate(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
            )

            @contextmanager
            def change_before_checked_read(active_paths):
                with acquire_runtime_mutation_barrier(active_paths):
                    _apply_fixture(
                        paths,
                        PhilippineSeedStage.P3_W,
                        generation=THIRD_GENERATION,
                        balanced_bps=3000,
                    )
                    yield

            factory = Mock(return_value=NEW_SECRET)
            result = _invoke(
                paths,
                barrier_factory=change_before_checked_read,
                secret_factory=factory,
            )
            self.assertEqual(
                (result.exit_code, result.error_code),
                (4, OPERATOR_SEED_SNAPSHOT_STATE_INVALID),
            )
            factory.assert_not_called()
            self.assertEqual(_snapshot(paths).generation, THIRD_GENERATION)
            self.assertEqual(_secret(paths), OLD_SECRET)

    def test_mutation_barrier_contention_is_stable_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
            )
            before = _database_rows(paths)
            with acquire_runtime_mutation_barrier(paths):
                result = _invoke(paths)
            self.assertEqual(
                (result.exit_code, result.error_code),
                (4, OPERATOR_RUNTIME_MUTATION_BUSY),
            )
            self.assertEqual(_database_rows(paths), before)


class OperatorSecretRotationCliTests(unittest.TestCase):
    @staticmethod
    def _invoke_cli(*arguments: str):
        stdout = io.StringIO()
        stderr = io.StringIO()
        exit_code = run_operator_cli(arguments, stdout=stdout, stderr=stderr)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_human_and_json_success_use_bounded_redacted_result(self):
        outcome = OperatorSecretRotationOutcome(
            "ROTATED",
            "ROTATED: restart_required=true",
            {
                "tenant": TENANT,
                "old_generation": GENERATION,
                "new_generation": NEW_GENERATION,
                "kill_switch": True,
                "assignment_secret_status": "PRESENT",
                "restart_required": True,
            },
        )
        arguments = (
            "secret",
            "assignment",
            "rotate",
            "--tenant",
            TENANT,
            "--expected-generation",
            GENERATION,
            "--new-generation",
            NEW_GENERATION,
            "--backup-bundle",
            "X:/backup",
            "--approval-ref",
            "CHANGE-1",
        )
        with patch(
            "src.api.operator_secret.rotate_assignment_secret",
            return_value=outcome,
        ) as rotate:
            code, stdout, stderr = self._invoke_cli(*arguments)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(stdout, "ROTATED: restart_required=true\n")

            code, stdout, stderr = self._invoke_cli("--json", *arguments)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["command"], "secret assignment rotate")
            self.assertEqual(payload["status"], "ROTATED")
            self.assertIsNone(payload["error_code"])
            self.assertEqual(payload["data"], dict(outcome.data))

        self.assertEqual(rotate.call_count, 2)
        emitted = stdout + stderr + json.dumps(payload)
        for forbidden in (OLD_SECRET, NEW_SECRET, "ciphertext", "secret_hash"):
            self.assertNotIn(forbidden, emitted)

    def test_cli_dispatch_preserves_exact_argument_order(self):
        outcome = OperatorSecretRotationOutcome(
            "ERROR",
            "synthetic state failure",
            {},
            4,
            OPERATOR_SEED_SNAPSHOT_STATE_INVALID,
        )
        with patch(
            "src.api.operator_secret.rotate_assignment_secret",
            return_value=outcome,
        ) as rotate:
            code, stdout, stderr = self._invoke_cli(
                "secret",
                "assignment",
                "rotate",
                "--approval-ref",
                "CHANGE-1",
                "--backup-bundle",
                "X:/backup",
                "--new-generation",
                NEW_GENERATION,
                "--expected-generation",
                GENERATION,
                "--tenant",
                TENANT,
            )
        self.assertEqual(code, 4)
        self.assertEqual(stdout, "")
        self.assertEqual(
            stderr,
            f"{OPERATOR_SEED_SNAPSHOT_STATE_INVALID}: synthetic state failure\n",
        )
        rotate.assert_called_once_with(
            TENANT,
            GENERATION,
            NEW_GENERATION,
            "X:/backup",
            "CHANGE-1",
        )


if __name__ == "__main__":
    unittest.main()
