from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from src.api.operator_backup import OperatorBackupOutcome
from src.api.operator_cli import run_operator_cli
from src.api.operator_seed import (
    OPERATOR_REASON_CODE_INVALID,
    OPERATOR_RUNTIME_MUTATION_BUSY,
    OPERATOR_SEED_BACKUP_TENANT_MISMATCH,
    OPERATOR_SEED_BPS_CHANGE_TOO_LARGE,
    OPERATOR_SEED_BPS_INVALID,
    OPERATOR_SEED_BREAKER_LATCHED,
    OPERATOR_SEED_COHORT_NOT_READY,
    OPERATOR_SEED_DELIVERY_NOT_CONFIGURED,
    OPERATOR_SEED_GENERATION_INVALID,
    OPERATOR_SEED_READINESS_NOT_READY,
    OPERATOR_SEED_SUBSYSTEM_FAILED,
    P3A_24H_ELIGIBILITY_NOT_PROVABLE,
    SeedSourceEvidence,
    _SeedFailure,
    _cohort_ready,
    _default_evidence_reader,
    execute_seed_transition,
    validate_operator_seed_generation,
    validate_reason_code,
)
from src.api.operator_tenant_provision import validate_approved_tenant_identity
from src.api.policy_profiles import (
    OPERATIONAL_SNAPSHOT_SETTING_KEY,
    PhilippineSeedStage,
    apply_philippine_seed_profile,
    load_applied_runtime_config_provider,
    parse_applied_operational_snapshot,
)
from src.api.reservation_lease import (
    RESERVATION_HEARTBEAT_INTERVAL_ENV,
    RESERVATION_LEASE_TTL_ENV,
)
from src.api.runtime_mutation import acquire_runtime_mutation_barrier
from src.api.runtime_paths import (
    LegacyRuntimeMigrationRequired,
    RuntimeMode,
    RuntimePaths,
    RuntimeRootUnavailable,
)
from src.api.secret_store import (
    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
    SecretStore,
)


TENANT = "ph-elv-0001"
GENERATION = "phseed-elv0001-bal-20260921-r1"
FIXED_TIME = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
FIXTURE_SECRET = "fixture-assignment-secret"
NEW_SECRET = "new-assignment-secret"

_BALANCED_BPS = "RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS"
_EXACT_BPS = "RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS"
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


def _paths(root: Path) -> RuntimePaths:
    runtime = root / "runtime"
    tenant_data = runtime / "data"
    output = runtime / "output"
    tenant_data.mkdir(parents=True)
    output.mkdir()
    paths = RuntimePaths(
        mode=RuntimeMode.TEST,
        runtime_root=runtime,
        settings_db_path=runtime / "dopamatrix.db",
        tenant_data_dir=tenant_data,
        internal_output_root=output,
    )
    with closing(
        sqlite3.connect(paths.tenant_database_path(TENANT))
    ) as connection, connection:
        connection.execute(
            "CREATE TABLE tenant_fixture (id INTEGER PRIMARY KEY);"
        )
    return paths


def _store(paths: RuntimePaths) -> SecretStore:
    return SecretStore(paths.settings_db_path, _IdentityProtector())


def _apply_fixture(
    paths: RuntimePaths,
    stage: PhilippineSeedStage,
    *,
    balanced_bps: int | None = None,
    kill_switch: bool | None = None,
    rollback_window: str = "7d",
) -> None:
    apply_philippine_seed_profile(
        _store(paths),
        tenant_id=TENANT,
        generation=GENERATION,
        stage=stage,
        balanced_basis_points=balanced_bps,
        kill_switch=kill_switch,
        rollback_window=rollback_window,
        audit_metadata={"fixture": "initial"},
        now=lambda: FIXED_TIME,
        secret_factory=lambda: FIXTURE_SECRET,
    )


def _healthy_evidence() -> SeedSourceEvidence:
    return SeedSourceEvidence(
        readiness_state="READY_FOR_CONTROLLED_CANARY",
        breaker_tripped=False,
        breaker_reason=None,
        metrics={
            "canaryTaskCount": 5,
            "diagnosticRunCoverageRate": 1.0,
            "planningObservationCoverageRate": 1.0,
            "terminalObservationCoverageRate": 1.0,
            "zeroPlanConflictRate": 0.0,
            "partialPlanRate": 0.0,
            "authorityLossRate": 0.0,
            "terminalPersistFailureRate": 0.0,
            "workerLeaseConfigFailureRate": 0.0,
            "cleanupWarningRate": 0.0,
        },
    )


def _valid_backup(tenant: str = TENANT) -> OperatorBackupOutcome:
    return OperatorBackupOutcome(
        "VALID",
        "backup is valid",
        {"tenant": tenant, "asset_count": 0, "counts": {}},
    )


def _invoke(
    paths: RuntimePaths,
    command: str,
    *,
    tenant: str = TENANT,
    generation: str = GENERATION,
    approval_ref: str | None = "CHANGE-1",
    reason_code: str | None = None,
    lease_profile: str | None = None,
    balanced_basis_points: int | None = None,
    rollback_window: str | None = None,
    backup_bundle: str | None = None,
    backup_verifier=None,
    delivery_reader=None,
    evidence_reader=None,
    now=None,
    secret_factory=None,
    barrier_factory=None,
):
    keyword_arguments = {
        "approval_ref": approval_ref,
        "reason_code": reason_code,
        "lease_profile": lease_profile,
        "balanced_basis_points": balanced_basis_points,
        "rollback_window": rollback_window,
        "backup_bundle": backup_bundle,
        "paths_initializer": lambda: paths,
        "store_factory": lambda active_paths: _store(active_paths),
        "backup_verifier": backup_verifier or (lambda bundle: _valid_backup()),
        "delivery_reader": delivery_reader
        or (lambda active_paths: str(paths.runtime_root / "delivery")),
        "evidence_reader": evidence_reader
        or (lambda active_paths, target, snapshot, secret: _healthy_evidence()),
        "now": now or (lambda: FIXED_TIME),
        "secret_factory": secret_factory or (lambda: NEW_SECRET),
    }
    if barrier_factory is not None:
        keyword_arguments["barrier_factory"] = barrier_factory
    return execute_seed_transition(
        command,
        tenant,
        generation,
        **keyword_arguments,
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


def _snapshot(paths: RuntimePaths):
    store = _store(paths)
    assignment_secret = store.get_secret(RESERVATION_ROLLOUT_ASSIGNMENT_SECRET)
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


class OperatorGenerationAndReasonValidationTests(unittest.TestCase):
    def test_exact_generation_is_accepted_for_each_tenant_and_revision(self):
        cases = (
            ("ph-elv-0001", "phseed-elv0001-bal-20260921-r1"),
            ("ph-bty-0001", "phseed-bty0001-bal-20260921-r2"),
            ("ph-hwh-0001", "phseed-hwh0001-bal-20200101-r1"),
        )
        for tenant, generation in cases:
            with self.subTest(tenant=tenant, generation=generation):
                identity = validate_approved_tenant_identity(tenant)
                self.assertEqual(
                    validate_operator_seed_generation(generation, identity),
                    generation,
                )

    def test_cross_tenant_malformed_date_and_revision_are_rejected(self):
        identity = validate_approved_tenant_identity(TENANT)
        invalid = (
            "phseed-bty0001-bal-20260921-r1",
            "PHSEED-elv0001-bal-20260921-r1",
            "phseed-elv0001-BAL-20260921-r1",
            "phseed-elv0001-bal-20260230-r1",
            "phseed-elv0001-bal-20260921-r0",
            "phseed-elv0001-bal-20260921-r-1",
            "phseed-elv0001-bal-20260921-r01",
        )
        for generation in invalid:
            with self.subTest(generation=generation):
                with self.assertRaises(_SeedFailure) as raised:
                    validate_operator_seed_generation(generation, identity)
                self.assertEqual(
                    raised.exception.error_code,
                    OPERATOR_SEED_GENERATION_INVALID,
                )
                self.assertEqual(raised.exception.exit_code, 3)

    def test_reason_code_has_dedicated_bounded_control_safe_contract(self):
        invalid = ("", " \t ", "X" * 257, "INCIDENT\n42", "\x00")
        for reason in invalid:
            with self.subTest(reason=repr(reason)):
                with self.assertRaises(_SeedFailure) as raised:
                    validate_reason_code(reason)
                self.assertEqual(
                    raised.exception.error_code,
                    OPERATOR_REASON_CODE_INVALID,
                )
                self.assertEqual(raised.exception.exit_code, 3)
        accepted = "INCIDENT-42 operator-safe containment"
        self.assertEqual(validate_reason_code(accepted), accepted)

    def test_invalid_generation_and_reason_fail_before_runtime_initialization(self):
        initializer = Mock(side_effect=AssertionError("must not initialize"))
        generation = execute_seed_transition(
            "apply-safe-off",
            TENANT,
            "phseed-elv0001-bal-20260230-r1",
            approval_ref="CHANGE-1",
            paths_initializer=initializer,
        )
        reason = execute_seed_transition(
            "kill",
            TENANT,
            GENERATION,
            reason_code="bad\nreason",
            paths_initializer=initializer,
        )
        self.assertEqual(
            (generation.exit_code, generation.error_code),
            (3, OPERATOR_SEED_GENERATION_INVALID),
        )
        self.assertEqual(
            (reason.exit_code, reason.error_code),
            (3, OPERATOR_REASON_CODE_INVALID),
        )
        initializer.assert_not_called()


class OperatorSeedTransitionTests(unittest.TestCase):
    def test_apply_safe_off_creates_complete_snapshot_and_secret_then_noops(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            first = _invoke(paths, "apply-safe-off")
            self.assertEqual((first.exit_code, first.status), (0, "APPLIED"))
            self.assertTrue(first.data["restart_required"])
            snapshot = _snapshot(paths)
            self.assertEqual(snapshot.stage, PhilippineSeedStage.SAFE_OFF)
            self.assertEqual(snapshot.tenant_allowlist, (TENANT,))
            self.assertEqual(snapshot.generation, GENERATION)
            self.assertEqual(snapshot.effective_values[_BALANCED_BPS], "0")
            self.assertEqual(snapshot.effective_values[_EXACT_BPS], "0")
            self.assertEqual(snapshot.effective_values[_KILL], "true")
            self.assertEqual(
                _store(paths).get_secret(
                    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET
                ),
                NEW_SECRET,
            )
            before = _database_rows(paths)
            second = _invoke(
                paths,
                "apply-safe-off",
                secret_factory=Mock(
                    side_effect=AssertionError("must not create a secret")
                ),
            )
            self.assertEqual(
                (second.exit_code, second.status),
                (0, "ALREADY_APPLIED"),
            )
            self.assertFalse(second.data["restart_required"])
            self.assertEqual(_database_rows(paths), before)

    def test_initial_safe_off_reuses_valid_existing_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            store = _store(paths)
            store.set_secret(
                RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
                FIXTURE_SECRET,
            )
            result = _invoke(
                paths,
                "apply-safe-off",
                secret_factory=Mock(
                    side_effect=AssertionError("must reuse existing secret")
                ),
            )
            self.assertEqual((result.exit_code, result.status), (0, "APPLIED"))
            self.assertEqual(
                store.get_secret(RESERVATION_ROLLOUT_ASSIGNMENT_SECRET),
                FIXTURE_SECRET,
            )

    def test_prearm_builds_fixed_contained_p3w_and_preserves_secret_and_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(paths, PhilippineSeedStage.SAFE_OFF)
            secret_before = _store(paths).get_secret(
                RESERVATION_ROLLOUT_ASSIGNMENT_SECRET
            )
            result = _invoke(
                paths,
                "prearm-p3w",
                backup_bundle=str(paths.runtime_root / "backup"),
            )
            self.assertEqual((result.exit_code, result.status), (0, "PREARMED"))
            snapshot = _snapshot(paths)
            self.assertEqual(snapshot.stage, PhilippineSeedStage.P3_W)
            self.assertEqual(snapshot.effective_values[_BALANCED_BPS], "3000")
            self.assertEqual(snapshot.effective_values[_EXACT_BPS], "0")
            self.assertEqual(snapshot.effective_values[_KILL], "true")
            self.assertEqual(
                snapshot.effective_values[RESERVATION_LEASE_TTL_ENV],
                "180",
            )
            self.assertEqual(
                snapshot.effective_values[RESERVATION_HEARTBEAT_INTERVAL_ENV],
                "45",
            )
            self.assertEqual(
                _store(paths).get_secret(
                    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET
                ),
                secret_before,
            )

    def test_activate_changes_only_kill_and_loaded_provider_stays_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=True,
            )
            before = _snapshot(paths)
            loaded = load_applied_runtime_config_provider(paths, _store(paths))
            result = _invoke(
                paths,
                "activate",
                backup_bundle=str(paths.runtime_root / "backup"),
            )
            self.assertEqual((result.exit_code, result.status), (0, "ACTIVATED"))
            after = _snapshot(paths)
            changed = {
                key
                for key in before.effective_values
                if before.effective_values[key] != after.effective_values[key]
            }
            self.assertEqual(changed, {_KILL})
            self.assertEqual(
                loaded.static_operational_mapping[_KILL],
                "true",
            )
            reloaded = load_applied_runtime_config_provider(paths, _store(paths))
            self.assertEqual(
                reloaded.static_operational_mapping[_KILL],
                "false",
            )
            self.assertTrue(result.data["restart_required"])

    def test_activate_rejects_p3a_24h_contained_and_active_without_writes(self):
        for killed in (True, False):
            with self.subTest(kill_switch=killed), tempfile.TemporaryDirectory() as directory:
                paths = _paths(Path(directory))
                _apply_fixture(
                    paths,
                    PhilippineSeedStage.P3_A,
                    balanced_bps=3000,
                    kill_switch=killed,
                    rollback_window="24h",
                )
                before = _database_rows(paths)
                result = _invoke(
                    paths,
                    "activate",
                    backup_bundle=str(paths.runtime_root / "backup"),
                )
                self.assertEqual(
                    (result.exit_code, result.error_code),
                    (4, P3A_24H_ELIGIBILITY_NOT_PROVABLE),
                )
                self.assertEqual(result.status, "ERROR")
                self.assertNotEqual(result.status, "ALREADY_ACTIVE")
                self.assertEqual(_database_rows(paths), before)

    def test_activate_preserves_p3a_7d_enablement_and_active_noop(self):
        for killed, expected in (
            (True, "ACTIVATED"),
            (False, "ALREADY_ACTIVE"),
        ):
            with self.subTest(kill_switch=killed), tempfile.TemporaryDirectory() as directory:
                paths = _paths(Path(directory))
                _apply_fixture(
                    paths,
                    PhilippineSeedStage.P3_A,
                    balanced_bps=3000,
                    kill_switch=killed,
                    rollback_window="7d",
                )
                before = _snapshot(paths)
                result = _invoke(
                    paths,
                    "activate",
                    backup_bundle=str(paths.runtime_root / "backup"),
                )
                self.assertEqual((result.exit_code, result.status), (0, expected))
                after = _snapshot(paths)
                self.assertEqual(after.stage, PhilippineSeedStage.P3_A)
                self.assertEqual(after.effective_values[_ROLLBACK_WINDOW], "7d")
                changed = {
                    key
                    for key in before.effective_values
                    if before.effective_values[key] != after.effective_values[key]
                }
                self.assertEqual(changed, ({_KILL} if killed else set()))

    def test_activate_p3a_24h_backup_failure_precedes_state_failure(self):
        cases = (
            (
                Mock(return_value=_valid_backup("ph-bty-0001")),
                OPERATOR_SEED_BACKUP_TENANT_MISMATCH,
            ),
            (
                Mock(
                    return_value=OperatorBackupOutcome(
                        "ERROR",
                        "invalid",
                        {},
                        6,
                        "OPERATOR_BACKUP_INTEGRITY_FAILED",
                    )
                ),
                "OPERATOR_BACKUP_INTEGRITY_FAILED",
            ),
        )
        for verifier, expected_error in cases:
            with (
                self.subTest(error=expected_error),
                tempfile.TemporaryDirectory() as directory,
            ):
                paths = _paths(Path(directory))
                _apply_fixture(
                    paths,
                    PhilippineSeedStage.P3_A,
                    balanced_bps=3000,
                    kill_switch=True,
                    rollback_window="24h",
                )
                before = _database_rows(paths)
                bundle = str(paths.runtime_root / "backup")
                result = _invoke(
                    paths,
                    "activate",
                    backup_bundle=bundle,
                    backup_verifier=verifier,
                    evidence_reader=Mock(
                        side_effect=AssertionError(
                            "backup failure must precede state evidence"
                        )
                    ),
                )
                self.assertEqual(result.error_code, expected_error)
                verifier.assert_called_once_with(bundle)
                self.assertEqual(_database_rows(paths), before)

    def test_kill_changes_only_kill_and_does_not_echo_reason_or_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=False,
            )
            before = _snapshot(paths)
            secret_before = _store(paths).get_secret(
                RESERVATION_ROLLOUT_ASSIGNMENT_SECRET
            )
            reason = "INCIDENT-SAFE-METADATA"
            result = _invoke(
                paths,
                "kill",
                approval_ref=None,
                reason_code=reason,
            )
            self.assertEqual((result.exit_code, result.status), (0, "CONTAINED"))
            after = _snapshot(paths)
            changed = {
                key
                for key in before.effective_values
                if before.effective_values[key] != after.effective_values[key]
            }
            self.assertEqual(changed, {_KILL})
            self.assertEqual(after.audit_metadata["reason_code"], reason)
            secret_after = _store(paths).get_secret(
                RESERVATION_ROLLOUT_ASSIGNMENT_SECRET
            )
            self.assertEqual(secret_after, secret_before)
            emitted = result.message + json.dumps(dict(result.data))
            self.assertNotIn(reason, emitted)
            self.assertNotIn(FIXTURE_SECRET, emitted)

    def test_kill_contains_p3a_24h_and_preserves_every_other_value(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_A,
                balanced_bps=3500,
                kill_switch=False,
                rollback_window="24h",
            )
            before = _snapshot(paths)
            secret_row_before = _database_rows(paths)[1]
            result = _invoke(
                paths,
                "kill",
                approval_ref=None,
                reason_code="INCIDENT",
            )
            self.assertEqual((result.exit_code, result.status), (0, "CONTAINED"))
            after = _snapshot(paths)
            self.assertEqual(after.stage, PhilippineSeedStage.P3_A)
            self.assertEqual(after.tenant_allowlist, before.tenant_allowlist)
            self.assertEqual(after.generation, before.generation)
            self.assertEqual(after.effective_values[_ROLLBACK_WINDOW], "24h")
            changed = {
                key
                for key in before.effective_values
                if before.effective_values[key] != after.effective_values[key]
            }
            self.assertEqual(changed, {_KILL})
            self.assertEqual(after.effective_values[_KILL], "true")
            self.assertEqual(_database_rows(paths)[1], secret_row_before)

    def test_balanced_bps_changes_only_requested_field_under_containment(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=True,
            )
            before = _snapshot(paths)
            result = _invoke(
                paths,
                "set-balanced-bps",
                balanced_basis_points=4000,
                backup_bundle=str(paths.runtime_root / "backup"),
                delivery_reader=Mock(
                    side_effect=AssertionError("Delivery is not a BPS gate")
                ),
                evidence_reader=Mock(
                    side_effect=AssertionError("evidence is not a BPS gate")
                ),
            )
            self.assertEqual(
                (result.exit_code, result.status),
                (0, "BALANCED_BPS_SET"),
            )
            after = _snapshot(paths)
            changed = {
                key
                for key in before.effective_values
                if before.effective_values[key] != after.effective_values[key]
            }
            self.assertEqual(changed, {_BALANCED_BPS})
            self.assertEqual(after.effective_values[_BALANCED_BPS], "4000")

    def test_balanced_bps_bounds_delta_and_containment_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=True,
            )
            invalid = _invoke(
                paths,
                "set-balanced-bps",
                balanced_basis_points=999,
                backup_bundle=str(paths.runtime_root / "backup"),
            )
            excessive = _invoke(
                paths,
                "set-balanced-bps",
                balanced_basis_points=1000,
                backup_bundle=str(paths.runtime_root / "backup"),
            )
            self.assertEqual(invalid.error_code, OPERATOR_SEED_BPS_INVALID)
            self.assertEqual(
                excessive.error_code,
                OPERATOR_SEED_BPS_CHANGE_TOO_LARGE,
            )

        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=False,
            )
            active = _invoke(
                paths,
                "set-balanced-bps",
                balanced_basis_points=4000,
                backup_bundle=str(paths.runtime_root / "backup"),
            )
            self.assertEqual(active.exit_code, 4)

    def test_transition_p3a_preserves_identity_bps_exact_lease_kill_and_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3500,
                kill_switch=True,
            )
            before = _snapshot(paths)
            secret_before = _store(paths).get_secret(
                RESERVATION_ROLLOUT_ASSIGNMENT_SECRET
            )
            result = _invoke(
                paths,
                "transition-p3a",
                rollback_window="7d",
                backup_bundle=str(paths.runtime_root / "backup"),
                delivery_reader=Mock(
                    side_effect=AssertionError("Delivery is not a P3-A gate")
                ),
            )
            self.assertEqual(
                (result.exit_code, result.status),
                (0, "TRANSITIONED"),
            )
            after = _snapshot(paths)
            self.assertEqual(after.stage, PhilippineSeedStage.P3_A)
            self.assertEqual(after.tenant_allowlist, before.tenant_allowlist)
            self.assertEqual(after.generation, before.generation)
            for key in (
                _BALANCED_BPS,
                _EXACT_BPS,
                _KILL,
                _ROLLBACK_WINDOW,
                RESERVATION_LEASE_TTL_ENV,
                RESERVATION_HEARTBEAT_INTERVAL_ENV,
                "RESERVATION_ROLLOUT_READINESS_WINDOW",
                "RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS",
                "RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS",
            ):
                self.assertEqual(
                    after.effective_values[key],
                    before.effective_values[key],
                    key,
                )
            self.assertEqual(
                _store(paths).get_secret(
                    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET
                ),
                secret_before,
            )

    def test_four_authority_closure_noops_verify_evidence_and_write_nothing(self):
        cases = (
            (
                "prearm-p3w",
                PhilippineSeedStage.P3_W,
                3000,
                True,
                "ALREADY_PREARMED",
                True,
                True,
            ),
            (
                "activate",
                PhilippineSeedStage.P3_W,
                3000,
                False,
                "ALREADY_ACTIVE",
                True,
                True,
            ),
            (
                "set-balanced-bps",
                PhilippineSeedStage.P3_W,
                3000,
                True,
                "ALREADY_SET",
                False,
                False,
            ),
            (
                "transition-p3a",
                PhilippineSeedStage.P3_A,
                3000,
                True,
                "ALREADY_TRANSITIONED",
                True,
                False,
            ),
        )
        for command, stage, bps, killed, expected, evidence, delivery in cases:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                paths = _paths(Path(directory))
                _apply_fixture(
                    paths,
                    stage,
                    balanced_bps=bps,
                    kill_switch=killed,
                )
                before = _database_rows(paths)
                backup_calls: list[str] = []
                evidence_calls: list[str] = []
                delivery_calls: list[str] = []

                def verify(bundle: str):
                    backup_calls.append(bundle)
                    return _valid_backup()

                def read_evidence(active_paths, target, snapshot, secret):
                    evidence_calls.append(target)
                    return _healthy_evidence()

                def read_delivery(active_paths):
                    delivery_calls.append("called")
                    return str(paths.runtime_root / "delivery")

                result = _invoke(
                    paths,
                    command,
                    balanced_basis_points=(bps if command == "set-balanced-bps" else None),
                    rollback_window=("7d" if command == "transition-p3a" else None),
                    backup_bundle=str(paths.runtime_root / "backup"),
                    backup_verifier=verify,
                    evidence_reader=read_evidence,
                    delivery_reader=read_delivery,
                )
                self.assertEqual((result.exit_code, result.status), (0, expected))
                self.assertFalse(result.data["restart_required"])
                self.assertEqual(backup_calls, [str(paths.runtime_root / "backup")])
                self.assertEqual(len(evidence_calls), int(evidence))
                self.assertEqual(len(delivery_calls), int(delivery))
                self.assertEqual(_database_rows(paths), before)

    def test_kill_already_contained_is_no_write_without_external_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_A,
                balanced_bps=3000,
                kill_switch=True,
            )
            before = _database_rows(paths)
            result = _invoke(
                paths,
                "kill",
                approval_ref=None,
                reason_code="INCIDENT",
                backup_verifier=Mock(
                    side_effect=AssertionError("kill has no backup gate")
                ),
                delivery_reader=Mock(
                    side_effect=AssertionError("kill has no Delivery gate")
                ),
                evidence_reader=Mock(
                    side_effect=AssertionError("kill has no evidence gate")
                ),
            )
            self.assertEqual(
                (result.exit_code, result.status),
                (0, "ALREADY_CONTAINED"),
            )
            self.assertEqual(_database_rows(paths), before)

    def test_stage_generation_and_missing_snapshot_preconditions_fail_closed(self):
        stage_cases = (
            ("prearm-p3w", PhilippineSeedStage.P3_A, True),
            ("activate", PhilippineSeedStage.SAFE_OFF, True),
            ("kill", PhilippineSeedStage.SAFE_OFF, True),
            ("transition-p3a", PhilippineSeedStage.P3_W, False),
        )
        for command, stage, killed in stage_cases:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                paths = _paths(Path(directory))
                _apply_fixture(
                    paths,
                    stage,
                    balanced_bps=(
                        None if stage is PhilippineSeedStage.SAFE_OFF else 3000
                    ),
                    kill_switch=killed,
                )
                before = _database_rows(paths)
                result = _invoke(
                    paths,
                    command,
                    approval_ref=(None if command == "kill" else "CHANGE-1"),
                    reason_code=("INCIDENT" if command == "kill" else None),
                    rollback_window=(
                        "7d" if command == "transition-p3a" else None
                    ),
                    backup_bundle=(
                        None
                        if command == "kill"
                        else str(paths.runtime_root / "backup")
                    ),
                )
                self.assertEqual(result.exit_code, 4)
                self.assertEqual(_database_rows(paths), before)

        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            missing = _invoke(
                paths,
                "kill",
                approval_ref=None,
                reason_code="INCIDENT",
            )
            self.assertEqual(missing.exit_code, 4)

        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=True,
            )
            mismatch = _invoke(
                paths,
                "kill",
                generation="phseed-elv0001-bal-20260921-r2",
                approval_ref=None,
                reason_code="INCIDENT",
            )
            self.assertEqual(mismatch.exit_code, 4)


class OperatorSeedEvidenceGateTests(unittest.TestCase):
    def _noop_fixture(self, paths: RuntimePaths, command: str) -> None:
        if command == "prearm-p3w":
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=True,
            )
        elif command == "activate":
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=False,
            )
        elif command == "set-balanced-bps":
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=True,
            )
        else:
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_A,
                balanced_bps=3000,
                kill_switch=True,
            )

    def test_corrupt_or_wrong_tenant_backup_precedes_every_backup_noop(self):
        commands = (
            "prearm-p3w",
            "activate",
            "set-balanced-bps",
            "transition-p3a",
        )
        verifiers = (
            (
                lambda bundle: _valid_backup("ph-bty-0001"),
                OPERATOR_SEED_BACKUP_TENANT_MISMATCH,
            ),
            (
                lambda bundle: OperatorBackupOutcome(
                    "ERROR",
                    "invalid",
                    {},
                    6,
                    "OPERATOR_BACKUP_INTEGRITY_FAILED",
                ),
                "OPERATOR_BACKUP_INTEGRITY_FAILED",
            ),
        )
        for command in commands:
            for verifier, error_code in verifiers:
                with (
                    self.subTest(command=command, error=error_code),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    paths = _paths(Path(directory))
                    self._noop_fixture(paths, command)
                    before = _database_rows(paths)
                    result = _invoke(
                        paths,
                        command,
                        balanced_basis_points=(
                            3000 if command == "set-balanced-bps" else None
                        ),
                        rollback_window=(
                            "7d" if command == "transition-p3a" else None
                        ),
                        backup_bundle=str(paths.runtime_root / "backup"),
                        backup_verifier=verifier,
                        evidence_reader=Mock(
                            side_effect=AssertionError(
                                "backup must fail before evidence"
                            )
                        ),
                    )
                    self.assertEqual(result.error_code, error_code)
                    self.assertNotIn("ALREADY", result.status)
                    self.assertEqual(_database_rows(paths), before)

    def test_readiness_breaker_delivery_and_cohort_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.SAFE_OFF,
            )
            missing_delivery = _invoke(
                paths,
                "prearm-p3w",
                backup_bundle=str(paths.runtime_root / "backup"),
                delivery_reader=lambda active_paths: "",
            )
            self.assertEqual(
                missing_delivery.error_code,
                OPERATOR_SEED_DELIVERY_NOT_CONFIGURED,
            )

            not_ready = _invoke(
                paths,
                "prearm-p3w",
                backup_bundle=str(paths.runtime_root / "backup"),
                evidence_reader=lambda *args: SeedSourceEvidence(
                    "NOT_READY", False, None, {}
                ),
            )
            self.assertEqual(
                not_ready.error_code,
                OPERATOR_SEED_READINESS_NOT_READY,
            )

            breaker = _invoke(
                paths,
                "prearm-p3w",
                backup_bundle=str(paths.runtime_root / "backup"),
                evidence_reader=lambda *args: SeedSourceEvidence(
                    "READY_FOR_CONTROLLED_CANARY",
                    True,
                    "LATCHED",
                    _healthy_evidence().metrics,
                ),
            )
            self.assertEqual(
                breaker.error_code,
                OPERATOR_SEED_BREAKER_LATCHED,
            )

        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=True,
            )
            unhealthy = dict(_healthy_evidence().metrics)
            unhealthy["canaryTaskCount"] = 4
            cohort = _invoke(
                paths,
                "transition-p3a",
                rollback_window="7d",
                backup_bundle=str(paths.runtime_root / "backup"),
                evidence_reader=lambda *args: SeedSourceEvidence(
                    "READY_FOR_CONTROLLED_CANARY",
                    False,
                    None,
                    unhealthy,
                ),
            )
            self.assertEqual(cohort.error_code, OPERATOR_SEED_COHORT_NOT_READY)

    def test_cohort_ready_rejects_bool_nonfinite_and_coercible_wrong_types(self):
        valid = dict(_healthy_evidence().metrics)
        self.assertTrue(_cohort_ready(valid))

        integer_rates = {
            key: int(value)
            for key, value in valid.items()
        }
        self.assertTrue(_cohort_ready(integer_rates))
        count_as_float = dict(valid)
        count_as_float["canaryTaskCount"] = 5.0
        self.assertFalse(_cohort_ready(count_as_float))

        invalid_values = (
            True,
            False,
            "1.0",
            "5",
            "not-a-number",
            float("nan"),
            float("inf"),
            float("-inf"),
            None,
            Decimal("1.0"),
        )
        for key in valid:
            for invalid in invalid_values:
                with self.subTest(key=key, invalid=repr(invalid)):
                    metrics = dict(valid)
                    metrics[key] = invalid
                    self.assertFalse(_cohort_ready(metrics))

            with self.subTest(key=key, invalid="missing"):
                metrics = dict(valid)
                del metrics[key]
                self.assertFalse(_cohort_ready(metrics))

    def test_24h_is_verified_then_fails_closed_without_any_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=True,
            )
            before = _database_rows(paths)
            verifier = Mock(return_value=_valid_backup())
            initializer = Mock(
                side_effect=AssertionError("24h must not enter mutation")
            )
            result = execute_seed_transition(
                "transition-p3a",
                TENANT,
                GENERATION,
                approval_ref="APPROVAL-DOES-NOT-PROVE-ELIGIBILITY",
                rollback_window="24h",
                backup_bundle=str(paths.runtime_root / "backup"),
                backup_verifier=verifier,
                paths_initializer=initializer,
                evidence_reader=Mock(
                    return_value=_healthy_evidence()
                ),
            )
            self.assertEqual(
                (result.exit_code, result.error_code),
                (4, P3A_24H_ELIGIBILITY_NOT_PROVABLE),
            )
            verifier.assert_called_once_with(str(paths.runtime_root / "backup"))
            initializer.assert_not_called()
            self.assertEqual(_database_rows(paths), before)

    def test_default_evidence_reader_calls_direct_readiness_and_breaker_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=True,
            )
            snapshot = _snapshot(paths)
            assignment_secret = _store(paths).get_secret(
                RESERVATION_ROLLOUT_ASSIGNMENT_SECRET
            )
            assert assignment_secret is not None
            readiness = Mock(
                return_value={"state": "READY_FOR_CONTROLLED_CANARY"}
            )
            rollout = Mock(
                return_value={
                    "breakerTripped": False,
                    "breakerReason": None,
                    **dict(_healthy_evidence().metrics),
                }
            )
            with (
                patch(
                    "src.api.operator_seed.reservation_rollout_readiness",
                    readiness,
                ),
                patch(
                    "src.api.operator_seed.reservation_rollout_status",
                    rollout,
                ),
            ):
                observed = _default_evidence_reader(
                    paths,
                    TENANT,
                    snapshot,
                    assignment_secret,
                )
            self.assertEqual(
                observed.readiness_state,
                "READY_FOR_CONTROLLED_CANARY",
            )
            self.assertFalse(observed.breaker_tripped)
            readiness.assert_called_once()
            rollout.assert_called_once()
            readiness_mapping = readiness.call_args.kwargs["runtime_mapping"]
            rollout_mapping = rollout.call_args.kwargs["runtime_mapping"]
            self.assertIs(readiness_mapping, rollout_mapping)
            self.assertEqual(
                readiness.call_args.kwargs["now"],
                rollout.call_args.kwargs["now"],
            )
            self.assertEqual(
                readiness_mapping[
                    "RESERVATION_ROLLOUT_ASSIGNMENT_SECRET"
                ],
                assignment_secret,
            )


class OperatorSeedAtomicityAndRuntimeTests(unittest.TestCase):
    def test_authoritative_in_transaction_reread_rejects_changed_prestate(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=False,
            )

            @contextmanager
            def change_before_checked_read(active_paths):
                with acquire_runtime_mutation_barrier(active_paths):
                    _apply_fixture(
                        paths,
                        PhilippineSeedStage.SAFE_OFF,
                    )
                    yield

            result = _invoke(
                paths,
                "kill",
                approval_ref=None,
                reason_code="INCIDENT",
                barrier_factory=change_before_checked_read,
            )
            self.assertEqual(result.exit_code, 4)
            observed = _snapshot(paths)
            self.assertEqual(observed.stage, PhilippineSeedStage.SAFE_OFF)
            self.assertEqual(observed.effective_values[_KILL], "true")

    def test_failure_after_secret_write_rolls_back_snapshot_secret_and_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            result = _invoke(
                paths,
                "apply-safe-off",
                now=Mock(side_effect=RuntimeError("synthetic failure")),
            )
            self.assertEqual(result.exit_code, 9)
            with closing(
                sqlite3.connect(paths.settings_db_path)
            ) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table';"
                    )
                }
            self.assertNotIn("app_settings", tables)
            self.assertNotIn("secure_settings", tables)

    def test_mutation_barrier_contention_is_stable_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _paths(Path(directory))
            _apply_fixture(
                paths,
                PhilippineSeedStage.P3_W,
                balanced_bps=3000,
                kill_switch=False,
            )
            before = _database_rows(paths)
            with acquire_runtime_mutation_barrier(paths):
                result = _invoke(
                    paths,
                    "kill",
                    approval_ref=None,
                    reason_code="INCIDENT",
                )
            self.assertEqual(
                (result.exit_code, result.error_code),
                (4, OPERATOR_RUNTIME_MUTATION_BUSY),
            )
            self.assertEqual(_database_rows(paths), before)

    def test_known_runtimepath_failures_do_not_reach_exit_9(self):
        cases = (
            (RuntimeRootUnavailable(), 8, OPERATOR_SEED_SUBSYSTEM_FAILED),
            (
                LegacyRuntimeMigrationRequired(),
                4,
                "LEGACY_RUNTIME_MIGRATION_REQUIRED",
            ),
        )
        for exception, expected_exit, expected_error in cases:
            with self.subTest(exception=type(exception).__name__):
                result = execute_seed_transition(
                    "apply-safe-off",
                    TENANT,
                    GENERATION,
                    approval_ref="CHANGE-1",
                    paths_initializer=Mock(side_effect=exception),
                )
                self.assertEqual(
                    (result.exit_code, result.error_code),
                    (expected_exit, expected_error),
                )


class OperatorSeedCliTests(unittest.TestCase):
    def _invoke(self, *arguments: str):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run_operator_cli(arguments, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_parser_accepts_24h_and_dispatches_it_unchanged(self):
        from src.api.operator_seed import OperatorSeedOutcome

        outcome = OperatorSeedOutcome(
            "ERROR",
            "P3-A 24-hour eligibility is not machine-provable",
            {},
            4,
            P3A_24H_ELIGIBILITY_NOT_PROVABLE,
        )
        with patch(
            "src.api.operator_seed.execute_seed_transition",
            return_value=outcome,
        ) as execute:
            code, stdout, stderr = self._invoke(
                "--json",
                "seed",
                "transition-p3a",
                "--tenant",
                TENANT,
                "--generation",
                GENERATION,
                "--rollback-window",
                "24h",
                "--backup-bundle",
                "X:/backup",
                "--approval-ref",
                "CHANGE-1",
            )
        self.assertEqual(code, 4)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(
            payload["error_code"],
            P3A_24H_ELIGIBILITY_NOT_PROVABLE,
        )
        self.assertEqual(execute.call_args.kwargs["rollback_window"], "24h")

    def test_six_seed_commands_dispatch_and_preserve_one_stream_contract(self):
        from src.api.operator_seed import OperatorSeedOutcome

        commands = (
            (
                "apply-safe-off",
                "--approval-ref",
                "CHANGE-1",
            ),
            (
                "prearm-p3w",
                "--backup-bundle",
                "X:/backup",
                "--approval-ref",
                "CHANGE-1",
            ),
            (
                "activate",
                "--backup-bundle",
                "X:/backup",
                "--approval-ref",
                "CHANGE-1",
            ),
            ("kill", "--reason-code", "INCIDENT"),
            (
                "set-balanced-bps",
                "--bps",
                "3000",
                "--backup-bundle",
                "X:/backup",
                "--approval-ref",
                "CHANGE-1",
            ),
            (
                "transition-p3a",
                "--rollback-window",
                "7d",
                "--backup-bundle",
                "X:/backup",
                "--approval-ref",
                "CHANGE-1",
            ),
        )
        for command, *options in commands:
            with self.subTest(command=command):
                outcome = OperatorSeedOutcome(
                    "DONE",
                    "completed",
                    {"restart_required": True},
                )
                with patch(
                    "src.api.operator_seed.execute_seed_transition",
                    return_value=outcome,
                ) as execute:
                    code, stdout, stderr = self._invoke(
                        "seed",
                        command,
                        "--tenant",
                        TENANT,
                        "--generation",
                        GENERATION,
                        *options,
                    )
                self.assertEqual(code, 0)
                self.assertEqual(stdout, "completed\n")
                self.assertEqual(stderr, "")
                self.assertEqual(execute.call_args.args[:3], (
                    command,
                    TENANT,
                    GENERATION,
                ))


if __name__ == "__main__":
    unittest.main()
