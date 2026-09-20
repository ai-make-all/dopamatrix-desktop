from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine

from src.api.policy_profiles import (
    ASSIGNMENT_SECRET_ENVIRONMENT_KEY,
    OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE,
    OPERATIONAL_PROFILE_APPLICATION_FAILED,
    OPERATIONAL_PROFILE_POLICY_VIOLATION,
    OPERATIONAL_SNAPSHOT_INVALID,
    OPERATIONAL_SNAPSHOT_KEYSET_INVALID,
    OPERATIONAL_SNAPSHOT_MISSING,
    OPERATIONAL_SNAPSHOT_SETTING_KEY,
    OPERATIONAL_SNAPSHOT_STAGE_MISMATCH,
    PHILIPPINE_SEED_PROFILE_NAME,
    PHILIPPINE_SEED_PROFILE_VERSION,
    SEED_NON_SECRET_ENVIRONMENT_KEYS,
    SEED_RUNTIME_ENVIRONMENT_KEYS,
    SEED_SECRET_ENVIRONMENT_KEYS,
    OperationalProfileApplicationError,
    OperationalProfileError,
    OperationalProfilePolicyError,
    OperationalSnapshotError,
    PhilippineSeedStage,
    apply_philippine_seed_profile,
    build_applied_operational_snapshot,
    canonical_snapshot_json,
    load_applied_runtime_config_provider,
    materialize_philippine_seed_profile,
    parse_applied_operational_snapshot,
    validate_philippine_seed_effective_values,
)
from src.api.reservation_lease import load_reservation_lease_configuration
from src.api.reservation_rollout_control import (
    load_reservation_rollout_control_configuration,
    resolve_omitted_reservation_mode,
)
from src.api.reservation_rollout_readiness import (
    load_reservation_rollout_readiness_configuration,
)
from src.api.runtime_config import (
    StaticOperationalStatus,
    reservation_runtime_mapping,
    temporary_runtime_config_provider,
)
from src.api.runtime_paths import temporary_test_runtime_paths
from src.api.secret_store import (
    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
    SecretDecryptionFailed,
    SecretEncryptionFailed,
    SecretStatus,
    SecretStore,
)


FIXED_TIME = datetime(2026, 9, 20, 8, 30, tzinfo=timezone.utc)
TENANT = "ph-elv-0001"
GENERATION = "phseed-elv0001-bal-20260920-r1"
SYNTHETIC_SECRET = "synthetic-assignment-secret-H3-only"


class FakeProtector:
    scheme = "h3-test-protector-v1"

    def protect(self, plaintext: bytes) -> bytes:
        return b"H3" + bytes(value ^ 0xA7 for value in plaintext)

    def unprotect(self, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(b"H3"):
            raise SecretDecryptionFailed()
        return bytes(value ^ 0xA7 for value in ciphertext[2:])


class FailingProtector(FakeProtector):
    def protect(self, plaintext: bytes) -> bytes:
        raise SecretEncryptionFailed()


class SeedSnapshotTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "dopamatrix.db"
        self.store = SecretStore(self.db_path, FakeProtector())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def apply(self, **overrides):
        arguments = {
            "tenant_id": TENANT,
            "generation": GENERATION,
            "stage": PhilippineSeedStage.SAFE_OFF,
            "audit_metadata": {"operator": "synthetic-test"},
            "now": lambda: FIXED_TIME,
            "secret_factory": lambda: SYNTHETIC_SECRET,
        }
        arguments.update(overrides)
        return apply_philippine_seed_profile(self.store, **arguments)

    def snapshot_text(self) -> str | None:
        if not self.db_path.exists():
            return None
        with closing(sqlite3.connect(self.db_path)) as conn:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings';"
            ).fetchone()
            if table is None:
                return None
            row = conn.execute(
                "SELECT key_value FROM app_settings WHERE key_name = ?;",
                (OPERATIONAL_SNAPSHOT_SETTING_KEY,),
            ).fetchone()
        return None if row is None else row[0]


class SeedInventoryAndProfileTests(SeedSnapshotTestCase):
    def test_source_inventory_is_exactly_32_non_secret_plus_one_secret(self):
        self.assertEqual(len(SEED_NON_SECRET_ENVIRONMENT_KEYS), 32)
        self.assertEqual(
            SEED_SECRET_ENVIRONMENT_KEYS,
            {ASSIGNMENT_SECRET_ENVIRONMENT_KEY},
        )
        self.assertEqual(len(SEED_RUNTIME_ENVIRONMENT_KEYS), 33)
        self.assertNotIn(
            ASSIGNMENT_SECRET_ENVIRONMENT_KEY,
            SEED_NON_SECRET_ENVIRONMENT_KEYS,
        )

    def test_safe_off_profile_matches_frozen_policy_and_existing_loaders(self):
        values = materialize_philippine_seed_profile(
            tenant_id=TENANT,
            generation=GENERATION,
            stage=PhilippineSeedStage.SAFE_OFF,
        )
        self.assertEqual(set(values), set(SEED_NON_SECRET_ENVIRONMENT_KEYS))
        self.assertEqual(values["RESERVATION_LEASE_TTL_SECONDS"], "180")
        self.assertEqual(values["RESERVATION_HEARTBEAT_INTERVAL_SECONDS"], "45")
        self.assertEqual(values["RESERVATION_ROLLOUT_READINESS_WINDOW"], "7d")
        self.assertEqual(
            values["RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS"],
            "10",
        )
        self.assertEqual(
            values["RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS"],
            "10",
        )
        self.assertEqual(
            values["RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS"],
            "0",
        )
        self.assertEqual(
            values["RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS"],
            "0",
        )
        self.assertEqual(values["RESERVATION_ROLLOUT_KILL_SWITCH"], "true")
        self.assertNotEqual(values["RESERVATION_LEASE_TTL_SECONDS"], "30")

        control_values = dict(values)
        control_values[ASSIGNMENT_SECRET_ENVIRONMENT_KEY] = SYNTHETIC_SECRET
        self.assertTrue(load_reservation_lease_configuration(values).configured)
        self.assertIsNotNone(
            load_reservation_rollout_readiness_configuration(values)
        )
        self.assertIsNotNone(
            load_reservation_rollout_control_configuration(control_values)
        )

    def test_approved_lease_and_stage_materializations(self):
        alternate = materialize_philippine_seed_profile(
            tenant_id=TENANT,
            generation=GENERATION,
            stage=PhilippineSeedStage.SAFE_OFF,
            lease_profile=(300, 60),
        )
        self.assertEqual(alternate["RESERVATION_LEASE_TTL_SECONDS"], "300")
        p3w = materialize_philippine_seed_profile(
            tenant_id=TENANT,
            generation=GENERATION,
            stage=PhilippineSeedStage.P3_W,
        )
        self.assertEqual(
            p3w["RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS"], "3000"
        )
        self.assertEqual(
            p3w["RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE"],
            "1.0",
        )
        p3a = materialize_philippine_seed_profile(
            tenant_id=TENANT,
            generation=GENERATION,
            stage=PhilippineSeedStage.P3_A,
            balanced_basis_points=4000,
            rollback_window="24h",
        )
        self.assertEqual(
            p3a["RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE"],
            "0.20",
        )

    def test_unapproved_inputs_and_policy_drift_fail(self):
        invalid_arguments = (
            {"lease_profile": (120, 30)},
            {"stage": PhilippineSeedStage.SAFE_OFF, "balanced_basis_points": 1000},
            {"stage": PhilippineSeedStage.P3_W, "balanced_basis_points": 999},
            {"stage": PhilippineSeedStage.P3_A, "balanced_basis_points": 4001},
            {"tenant_id": "PH-ELV-0001"},
            {"generation": "../generation"},
        )
        for changes in invalid_arguments:
            arguments = {
                "tenant_id": TENANT,
                "generation": GENERATION,
                "stage": PhilippineSeedStage.SAFE_OFF,
            }
            arguments.update(changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(
                OperationalProfilePolicyError,
                OPERATIONAL_PROFILE_POLICY_VIOLATION,
            ):
                materialize_philippine_seed_profile(**arguments)

        base = dict(
            materialize_philippine_seed_profile(
                tenant_id=TENANT,
                generation=GENERATION,
                stage=PhilippineSeedStage.SAFE_OFF,
            )
        )
        for key, value in (
            ("RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS", "1"),
            ("RESERVATION_ROLLOUT_MAXIMUM_PARTIAL_PLAN_RATE", "0.21"),
            ("RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE", "0.01"),
        ):
            drifted = dict(base)
            drifted[key] = value
            with self.subTest(key=key), self.assertRaises(
                OperationalProfileError
            ):
                validate_philippine_seed_effective_values(
                    drifted,
                    stage=PhilippineSeedStage.SAFE_OFF,
                    assignment_secret=SYNTHETIC_SECRET,
                )

    def test_noncanonical_lease_snapshot_values_fail_closed(self):
        legal_values = dict(
            materialize_philippine_seed_profile(
                tenant_id=TENANT,
                generation=GENERATION,
                stage=PhilippineSeedStage.SAFE_OFF,
            )
        )
        invalid_pairs = (
            ("180.9", "45.1"),
            ("300.9", "60.1"),
            ("180.0", "45.0"),
            ("0300", "060"),
        )
        for ttl, heartbeat in invalid_pairs:
            drifted = dict(legal_values)
            drifted["RESERVATION_LEASE_TTL_SECONDS"] = ttl
            drifted["RESERVATION_HEARTBEAT_INTERVAL_SECONDS"] = heartbeat
            with self.subTest(ttl=ttl, heartbeat=heartbeat), self.assertRaisesRegex(
                OperationalProfilePolicyError,
                OPERATIONAL_PROFILE_POLICY_VIOLATION,
            ):
                validate_philippine_seed_effective_values(
                    drifted,
                    stage=PhilippineSeedStage.SAFE_OFF,
                    assignment_secret=SYNTHETIC_SECRET,
                )

        for ttl, heartbeat in (("180", "45"), ("300", "60")):
            approved = dict(legal_values)
            approved["RESERVATION_LEASE_TTL_SECONDS"] = ttl
            approved["RESERVATION_HEARTBEAT_INTERVAL_SECONDS"] = heartbeat
            with self.subTest(approved_ttl=ttl, approved_heartbeat=heartbeat):
                validate_philippine_seed_effective_values(
                    approved,
                    stage=PhilippineSeedStage.SAFE_OFF,
                    assignment_secret=SYNTHETIC_SECRET,
                )

        self.apply()
        payload = json.loads(self.snapshot_text())
        payload["effective_values"]["RESERVATION_LEASE_TTL_SECONDS"] = "180.9"
        payload["effective_values"][
            "RESERVATION_HEARTBEAT_INTERVAL_SECONDS"
        ] = "45.1"
        invalid_serialized = canonical_snapshot_json(payload)
        self.assertEqual(
            invalid_serialized,
            canonical_snapshot_json(json.loads(invalid_serialized)),
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE app_settings SET key_value = ? WHERE key_name = ?;",
                (invalid_serialized, OPERATIONAL_SNAPSHOT_SETTING_KEY),
            )

        environment_fallback = dict(legal_values)
        environment_fallback[ASSIGNMENT_SECRET_ENVIRONMENT_KEY] = (
            "synthetic-environment-assignment-secret"
        )
        with temporary_test_runtime_paths(self.root / "runtime-invalid-lease") as paths:
            with patch.dict(os.environ, environment_fallback, clear=False):
                provider = load_applied_runtime_config_provider(paths, self.store)
                with temporary_runtime_config_provider(provider):
                    active_mapping = reservation_runtime_mapping()

        self.assertEqual(
            provider.static_operational_status,
            StaticOperationalStatus.SAFE_OFF_INVALID,
        )
        self.assertEqual(
            provider.static_operational_error_code,
            OPERATIONAL_PROFILE_POLICY_VIOLATION,
        )
        self.assertEqual(dict(provider.static_operational_mapping), {})
        self.assertEqual(dict(active_mapping), {})
        self.assertEqual(self.snapshot_text(), invalid_serialized)


class SnapshotSchemaTests(SeedSnapshotTestCase):
    def make_snapshot(self, stage=PhilippineSeedStage.SAFE_OFF):
        values = materialize_philippine_seed_profile(
            tenant_id=TENANT,
            generation=GENERATION,
            stage=stage,
        )
        return build_applied_operational_snapshot(
            effective_values=values,
            stage=stage,
            applied_at=FIXED_TIME,
            audit_metadata={"operator": "synthetic-test", "reason": "test"},
            assignment_secret=SYNTHETIC_SECRET,
        )

    def test_canonical_json_is_deterministic_and_contains_no_secret(self):
        first = self.make_snapshot().canonical_json()
        second = self.make_snapshot().canonical_json()
        self.assertEqual(first, second)
        self.assertEqual(first, canonical_snapshot_json(json.loads(first)))
        self.assertNotIn(SYNTHETIC_SECRET, first)
        self.assertNotIn("ciphertext", first)
        parsed = parse_applied_operational_snapshot(
            first,
            assignment_secret=SYNTHETIC_SECRET,
        )
        self.assertEqual(parsed.profile_name, PHILIPPINE_SEED_PROFILE_NAME)
        self.assertEqual(parsed.profile_version, PHILIPPINE_SEED_PROFILE_VERSION)

    def test_partial_extra_duplicate_corrupt_and_wrong_type_are_rejected(self):
        payload = self.make_snapshot().to_payload()
        cases = []
        partial = json.loads(json.dumps(payload))
        partial["effective_values"].pop(next(iter(partial["effective_values"])))
        cases.append(canonical_snapshot_json(partial))
        extra = json.loads(json.dumps(payload))
        extra["effective_values"]["RESERVATION_UNKNOWN"] = "value"
        cases.append(canonical_snapshot_json(extra))
        wrong_type = json.loads(json.dumps(payload))
        wrong_type["effective_values"]["RESERVATION_LEASE_TTL_SECONDS"] = 180
        cases.append(canonical_snapshot_json(wrong_type))
        cases.extend(("{", "[]"))
        for serialized in cases:
            with self.subTest(serialized=serialized[:32]), self.assertRaises(
                OperationalSnapshotError
            ):
                parse_applied_operational_snapshot(
                    serialized,
                    assignment_secret=SYNTHETIC_SECRET,
                )

        canonical = self.make_snapshot().canonical_json()
        duplicate = canonical[:-1] + ',"schema_version":1}'
        with self.assertRaisesRegex(
            OperationalSnapshotError,
            OPERATIONAL_SNAPSHOT_KEYSET_INVALID,
        ):
            parse_applied_operational_snapshot(
                duplicate,
                assignment_secret=SYNTHETIC_SECRET,
            )

    def test_unknown_schema_profile_version_and_noncanonical_json_fail(self):
        payload = self.make_snapshot().to_payload()
        mutations = (
            ("schema_version", 2),
            ("profile_name", "other-profile"),
            ("profile_version", "2.0"),
        )
        for key, value in mutations:
            changed = dict(payload)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(
                OperationalSnapshotError
            ):
                parse_applied_operational_snapshot(
                    canonical_snapshot_json(changed),
                    assignment_secret=SYNTHETIC_SECRET,
                )
        with self.assertRaisesRegex(
            OperationalSnapshotError,
            OPERATIONAL_SNAPSHOT_INVALID,
        ):
            parse_applied_operational_snapshot(
                json.dumps(payload, indent=2),
                assignment_secret=SYNTHETIC_SECRET,
            )

    def test_stage_is_compatibility_metadata_not_runtime_authority(self):
        payload = self.make_snapshot().to_payload()
        payload["stage"] = PhilippineSeedStage.P3_A.value
        with self.assertRaisesRegex(
            OperationalSnapshotError,
            OPERATIONAL_SNAPSHOT_STAGE_MISMATCH,
        ):
            parse_applied_operational_snapshot(
                canonical_snapshot_json(payload),
                assignment_secret=SYNTHETIC_SECRET,
            )
        snapshot = self.make_snapshot()
        self.assertNotIn("stage", snapshot.effective_values)


class AtomicApplicationTests(SeedSnapshotTestCase):
    def test_absent_secret_and_snapshot_commit_together_in_one_row(self):
        result = self.apply()
        self.assertTrue(result.assignment_secret_created)
        self.assertEqual(result.assignment_secret_status, SecretStatus.PRESENT)
        self.assertEqual(
            self.store.get_secret(RESERVATION_ROLLOUT_ASSIGNMENT_SECRET),
            SYNTHETIC_SECRET,
        )
        serialized = self.snapshot_text()
        self.assertIsNotNone(serialized)
        self.assertNotIn(SYNTHETIC_SECRET, serialized)
        with closing(sqlite3.connect(self.db_path)) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM app_settings WHERE key_name = ?;",
                (OPERATIONAL_SNAPSHOT_SETTING_KEY,),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_snapshot_failure_rolls_back_new_secret(self):
        with patch(
            "src.api.policy_profiles._write_snapshot_on_connection",
            side_effect=sqlite3.OperationalError("synthetic write failure"),
        ):
            with self.assertRaisesRegex(
                OperationalProfileApplicationError,
                OPERATIONAL_PROFILE_APPLICATION_FAILED,
            ):
                self.apply()
        self.assertIsNone(
            self.store.get_secret(RESERVATION_ROLLOUT_ASSIGNMENT_SECRET)
        )
        self.assertIsNone(self.snapshot_text())

    def test_secret_failure_rolls_back_snapshot(self):
        failing = SecretStore(self.db_path, FailingProtector())
        with self.assertRaisesRegex(
            OperationalProfileApplicationError,
            OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE,
        ):
            apply_philippine_seed_profile(
                failing,
                tenant_id=TENANT,
                generation=GENERATION,
                stage=PhilippineSeedStage.SAFE_OFF,
                now=lambda: FIXED_TIME,
                secret_factory=lambda: SYNTHETIC_SECRET,
            )
        self.assertIsNone(self.snapshot_text())

    def test_existing_secret_is_reused_and_reapply_does_not_rotate(self):
        existing = "synthetic-existing-assignment-secret"
        self.store.set_secret(RESERVATION_ROLLOUT_ASSIGNMENT_SECRET, existing)
        first = self.apply(secret_factory=lambda: "must-not-be-used")
        first_text = self.snapshot_text()
        second = self.apply(secret_factory=lambda: "must-not-be-used-either")
        self.assertFalse(first.assignment_secret_created)
        self.assertFalse(second.assignment_secret_created)
        self.assertEqual(
            self.store.get_secret(RESERVATION_ROLLOUT_ASSIGNMENT_SECRET),
            existing,
        )
        self.assertEqual(first_text, self.snapshot_text())

    def test_corrupt_existing_secret_fails_without_replacement(self):
        self.store.ensure_schema()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO secure_settings VALUES (?, ?, ?, ?);",
                (
                    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
                    FakeProtector.scheme,
                    sqlite3.Binary(b"broken"),
                    "now",
                ),
            )
        with self.assertRaisesRegex(
            OperationalProfileApplicationError,
            OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE,
        ):
            self.apply(secret_factory=lambda: "must-not-replace")
        self.assertIsNone(self.snapshot_text())


class SeedTransitionRegressionTests(SeedSnapshotTestCase):
    _KILL_KEY = "RESERVATION_ROLLOUT_KILL_SWITCH"
    _BALANCED_BPS_KEY = (
        "RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS"
    )

    def read_snapshot(self):
        assignment_secret = self.store.get_secret(
            RESERVATION_ROLLOUT_ASSIGNMENT_SECRET
        )
        serialized = self.snapshot_text()
        self.assertIsNotNone(assignment_secret)
        self.assertIsNotNone(serialized)
        snapshot = parse_applied_operational_snapshot(
            serialized,
            assignment_secret=assignment_secret,
        )
        return snapshot, serialized, assignment_secret

    def assert_only_effective_key_changed(
        self,
        before,
        after,
        changed_key,
    ):
        before_values = dict(before.effective_values)
        after_values = dict(after.effective_values)
        self.assertNotEqual(before_values[changed_key], after_values[changed_key])
        before_values.pop(changed_key)
        after_values.pop(changed_key)
        self.assertEqual(before_values, after_values)

    def assert_omitted_mode_is_default_off(self, runtime_name):
        with temporary_test_runtime_paths(self.root / runtime_name) as paths:
            provider = load_applied_runtime_config_provider(paths, self.store)
            engine = create_engine("sqlite:///:memory:")
            try:
                with temporary_runtime_config_provider(provider):
                    decision = resolve_omitted_reservation_mode(
                        engine,
                        canonical_tenant=TENANT,
                        planning_policy="exact_main_visual_balanced",
                        task_id="synthetic-h3r2-task",
                    )
            finally:
                engine.dispose()
        self.assertEqual(
            provider.static_operational_status,
            StaticOperationalStatus.ACTIVE,
        )
        self.assertEqual(decision.reservation_conflict_mode, "OFF")
        self.assertEqual(decision.reservation_mode_source, "DEFAULT_OFF")

    def test_p2_prearm_is_complete_but_stage_does_not_activate_canary(self):
        result = self.apply(
            stage=PhilippineSeedStage.P3_W,
            balanced_basis_points=3000,
            kill_switch=True,
            rollback_window="7d",
        )
        snapshot, serialized, assignment_secret = self.read_snapshot()
        values = snapshot.effective_values

        self.assertEqual(result.stage, PhilippineSeedStage.P3_W)
        self.assertEqual(snapshot.stage, PhilippineSeedStage.P3_W)
        self.assertEqual(snapshot.generation, GENERATION)
        self.assertEqual(snapshot.tenant_allowlist, (TENANT,))
        self.assertEqual(values[self._BALANCED_BPS_KEY], "3000")
        self.assertEqual(
            values["RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS"],
            "0",
        )
        self.assertEqual(values[self._KILL_KEY], "true")
        self.assertEqual(values["RESERVATION_ROLLOUT_ROLLBACK_WINDOW"], "7d")
        self.assertEqual(
            values["RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE"],
            "1.0",
        )
        self.assertEqual(
            values["RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE"],
            "1.0",
        )
        self.assertEqual(
            values["RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE"],
            "1.0",
        )
        self.assertFalse(assignment_secret in serialized)
        self.assertNotIn("stage", values)
        self.assert_omitted_mode_is_default_off("runtime-prearm")

    def test_disable_kill_last_preserves_prearm_state_until_restart(self):
        self.apply(
            stage=PhilippineSeedStage.P3_W,
            balanced_basis_points=3000,
            kill_switch=True,
        )
        before, _, assignment_secret_before = self.read_snapshot()

        with temporary_test_runtime_paths(self.root / "runtime-activation") as paths:
            current_provider = load_applied_runtime_config_provider(paths, self.store)
            current_mapping = dict(current_provider.static_operational_mapping)
            result = self.apply(
                stage=PhilippineSeedStage.P3_W,
                balanced_basis_points=3000,
                kill_switch=False,
            )
            self.assertEqual(
                dict(current_provider.static_operational_mapping),
                current_mapping,
            )
            restarted_provider = load_applied_runtime_config_provider(
                paths,
                self.store,
            )

        after, serialized, assignment_secret_after = self.read_snapshot()
        self.assertFalse(result.assignment_secret_created)
        self.assertEqual(before.stage, after.stage)
        self.assertEqual(before.generation, after.generation)
        self.assertEqual(before.tenant_allowlist, after.tenant_allowlist)
        self.assert_only_effective_key_changed(before, after, self._KILL_KEY)
        self.assertEqual(before.effective_values[self._KILL_KEY], "true")
        self.assertEqual(after.effective_values[self._KILL_KEY], "false")
        self.assertTrue(assignment_secret_before == assignment_secret_after)
        self.assertFalse(assignment_secret_after in serialized)
        self.assertEqual(current_mapping[self._KILL_KEY], "true")
        self.assertEqual(
            restarted_provider.static_operational_mapping[self._KILL_KEY],
            "false",
        )
        self.assertEqual(
            restarted_provider.static_operational_mapping[self._BALANCED_BPS_KEY],
            "3000",
        )

    def test_p3w_kill_containment_preserves_authoritative_state(self):
        self.apply(
            stage=PhilippineSeedStage.P3_W,
            balanced_basis_points=3000,
            kill_switch=False,
        )
        before, _, assignment_secret_before = self.read_snapshot()
        result = self.apply(
            stage=PhilippineSeedStage.P3_W,
            balanced_basis_points=3000,
            kill_switch=True,
        )
        after, serialized, assignment_secret_after = self.read_snapshot()

        self.assertFalse(result.assignment_secret_created)
        self.assertEqual(before.stage, after.stage)
        self.assertEqual(before.generation, GENERATION)
        self.assertEqual(after.generation, GENERATION)
        self.assertEqual(before.tenant_allowlist, after.tenant_allowlist)
        self.assert_only_effective_key_changed(before, after, self._KILL_KEY)
        self.assertEqual(after.effective_values[self._BALANCED_BPS_KEY], "3000")
        self.assertTrue(assignment_secret_before == assignment_secret_after)
        self.assertFalse(assignment_secret_after in serialized)
        self.assert_omitted_mode_is_default_off("runtime-p3w-kill")

    def test_p3a_kill_containment_preserves_tightened_policy(self):
        arguments = {
            "stage": PhilippineSeedStage.P3_A,
            "balanced_basis_points": 2500,
            "rollback_window": "24h",
        }
        self.apply(**arguments, kill_switch=False)
        before, _, assignment_secret_before = self.read_snapshot()
        result = self.apply(**arguments, kill_switch=True)
        after, serialized, assignment_secret_after = self.read_snapshot()

        self.assertFalse(result.assignment_secret_created)
        self.assertEqual(before.stage, PhilippineSeedStage.P3_A)
        self.assertEqual(after.stage, PhilippineSeedStage.P3_A)
        self.assertEqual(before.generation, GENERATION)
        self.assertEqual(after.generation, GENERATION)
        self.assert_only_effective_key_changed(before, after, self._KILL_KEY)
        self.assertEqual(after.effective_values[self._BALANCED_BPS_KEY], "2500")
        self.assertEqual(
            after.effective_values[
                "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE"
            ],
            "0.30",
        )
        self.assertEqual(
            after.effective_values[
                "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE"
            ],
            "0.20",
        )
        self.assertEqual(
            after.effective_values[
                "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE"
            ],
            "0.20",
        )
        self.assertEqual(
            after.effective_values[
                "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE"
            ],
            "0",
        )
        self.assertEqual(
            after.effective_values[
                "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_DIAGNOSTIC_COVERAGE_RATE"
            ],
            "1.0",
        )
        self.assertTrue(assignment_secret_before == assignment_secret_after)
        self.assertFalse(assignment_secret_after in serialized)

    def test_p3a_governed_bps_change_preserves_all_other_authority(self):
        arguments = {
            "stage": PhilippineSeedStage.P3_A,
            "kill_switch": True,
            "rollback_window": "7d",
        }
        self.apply(**arguments, balanced_basis_points=1500)
        before, _, assignment_secret_before = self.read_snapshot()
        result = self.apply(**arguments, balanced_basis_points=3500)
        after, serialized, assignment_secret_after = self.read_snapshot()

        self.assertFalse(result.assignment_secret_created)
        self.assertEqual(before.stage, after.stage)
        self.assertEqual(before.generation, GENERATION)
        self.assertEqual(after.generation, GENERATION)
        self.assertEqual(before.tenant_allowlist, after.tenant_allowlist)
        self.assert_only_effective_key_changed(
            before,
            after,
            self._BALANCED_BPS_KEY,
        )
        self.assertEqual(before.effective_values[self._BALANCED_BPS_KEY], "1500")
        self.assertEqual(after.effective_values[self._BALANCED_BPS_KEY], "3500")
        self.assertEqual(after.effective_values[self._KILL_KEY], "true")
        self.assertEqual(
            after.effective_values[
                "RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS"
            ],
            "0",
        )
        self.assertTrue(assignment_secret_before == assignment_secret_after)
        self.assertFalse(assignment_secret_after in serialized)


class StartupActivationTests(SeedSnapshotTestCase):
    def test_valid_snapshot_activates_complete_static_mapping(self):
        self.apply()
        with temporary_test_runtime_paths(self.root / "runtime") as paths:
            provider = load_applied_runtime_config_provider(paths, self.store)
        self.assertEqual(
            provider.static_operational_status,
            StaticOperationalStatus.ACTIVE,
        )
        self.assertEqual(len(provider.static_operational_mapping), 33)
        self.assertEqual(
            provider.static_operational_mapping[
                ASSIGNMENT_SECRET_ENVIRONMENT_KEY
            ],
            SYNTHETIC_SECRET,
        )
        control = load_reservation_rollout_control_configuration(
            provider.static_operational_mapping
        )
        self.assertIsNotNone(control)
        self.assertNotIn(SYNTHETIC_SECRET, repr(provider))

    def test_missing_snapshot_is_safe_off_and_ignores_dangerous_environment(self):
        dangerous = {
            "RESERVATION_ROLLOUT_CONTROL_ENABLED": "true",
            "RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS": "10000",
            ASSIGNMENT_SECRET_ENVIRONMENT_KEY: "environment-must-not-win",
        }
        with temporary_test_runtime_paths(self.root / "runtime") as paths:
            provider = load_applied_runtime_config_provider(paths, self.store)
            with (
                temporary_runtime_config_provider(provider),
                patch.dict(os.environ, dangerous, clear=False),
            ):
                active = reservation_runtime_mapping()
                self.assertEqual(dict(active), {})
                self.assertIsNone(
                    load_reservation_rollout_control_configuration(active)
                )
        self.assertEqual(
            provider.static_operational_status,
            StaticOperationalStatus.SAFE_OFF_MISSING,
        )
        self.assertEqual(
            provider.static_operational_error_code,
            OPERATIONAL_SNAPSHOT_MISSING,
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            secure_table = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='secure_settings';"
            ).fetchone()
        self.assertIsNone(secure_table)

    def test_invalid_snapshot_and_missing_secret_are_safe_off(self):
        self.apply()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE app_settings SET key_value = ? WHERE key_name = ?;",
                ("{", OPERATIONAL_SNAPSHOT_SETTING_KEY),
            )
        with temporary_test_runtime_paths(self.root / "runtime") as paths:
            invalid = load_applied_runtime_config_provider(paths, self.store)
        self.assertEqual(
            invalid.static_operational_status,
            StaticOperationalStatus.SAFE_OFF_INVALID,
        )
        self.assertEqual(dict(invalid.static_operational_mapping), {})

        self.apply()
        self.store.delete_secret(RESERVATION_ROLLOUT_ASSIGNMENT_SECRET)
        with temporary_test_runtime_paths(self.root / "runtime-2") as paths:
            missing_secret = load_applied_runtime_config_provider(paths, self.store)
        self.assertEqual(
            missing_secret.static_operational_status,
            StaticOperationalStatus.SAFE_OFF_INVALID,
        )
        self.assertEqual(
            missing_secret.static_operational_error_code,
            OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE,
        )

        self.apply()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE secure_settings SET ciphertext = ? WHERE key_name = ?;",
                (
                    sqlite3.Binary(b"broken"),
                    RESERVATION_ROLLOUT_ASSIGNMENT_SECRET,
                ),
            )
        with temporary_test_runtime_paths(self.root / "runtime-3") as paths:
            corrupt_secret = load_applied_runtime_config_provider(
                paths,
                self.store,
            )
        self.assertEqual(
            corrupt_secret.static_operational_status,
            StaticOperationalStatus.SAFE_OFF_INVALID,
        )
        self.assertEqual(
            corrupt_secret.static_operational_error_code,
            OPERATIONAL_ASSIGNMENT_SECRET_UNAVAILABLE,
        )

    def test_process_snapshot_is_immutable_until_new_provider_load(self):
        self.apply()
        with temporary_test_runtime_paths(self.root / "runtime") as paths:
            current = load_applied_runtime_config_provider(paths, self.store)
            old_mapping = dict(current.static_operational_mapping)
            self.apply(
                stage=PhilippineSeedStage.P3_W,
                balanced_basis_points=3000,
                kill_switch=False,
            )
            self.assertEqual(dict(current.static_operational_mapping), old_mapping)
            restarted = load_applied_runtime_config_provider(paths, self.store)
        self.assertEqual(
            current.static_operational_mapping[
                "RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS"
            ],
            "0",
        )
        self.assertEqual(
            restarted.static_operational_mapping[
                "RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS"
            ],
            "3000",
        )


if __name__ == "__main__":
    unittest.main()
