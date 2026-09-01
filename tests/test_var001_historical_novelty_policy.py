import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.fingerprint_ledger import (
    LEDGER_SCHEMA_VERSION,
    FingerprintIdentityRecord,
    FingerprintLedgerRepository,
    FingerprintReservation,
    HistoricalExactLookupResult,
    ReservationAcquireStatus,
    ReservationConfirmationStatus,
    ensure_fingerprint_ledger_schema,
)
from src.api.historical_novelty_policy import (
    HistoricalDecisionAction,
    HistoricalEvidenceKind,
    HistoricalNoveltyPolicy,
    HistoricalNoveltyPolicyConfiguration,
    HistoricalNoveltyPolicyConfigurationError,
    HistoricalPolicyMode,
    HistoricalPolicyScope,
    HistoricalPolicyWindow,
    HistoricalReuseIntent,
    HistoricalScopeType,
    HistoricalWindowKind,
    PreviewIntent,
    ReservationConflictAction,
    ReservationConflictMode,
)


def _facts(*, planned=0, rendered=0, failed=0, identity_exists=True):
    occurrence_count = planned + rendered + failed
    return HistoricalExactLookupResult(
        identity_exists=identity_exists,
        historical_match=occurrence_count > 0,
        fingerprint_identity_id=1 if identity_exists else None,
        historical_occurrence_count=occurrence_count,
        planned_count=planned,
        rendered_count=rendered,
        failed_count=failed,
        first_seen_at=None,
        last_seen_at=None,
        last_rendered_at=None,
    )


def _identity():
    return FingerprintIdentityRecord(
        fingerprint_type="main_visual_planning",
        fingerprint_version=1,
        fingerprint_digest="a" * 64,
        digest_algorithm="sha256",
        source_hash_algorithm="md5",
        canonical_payload='{"fingerprint_type":"main_visual_planning"}',
    )


class HistoricalNoveltyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = HistoricalNoveltyPolicy()

    def test_off_never_rejects_any_lifecycle_facts(self):
        configuration = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode.OFF,
        )
        for facts in (
            _facts(rendered=1),
            _facts(planned=1),
            _facts(failed=1),
            _facts(identity_exists=False),
        ):
            with self.subTest(facts=facts):
                decision = self.policy.evaluate(facts, configuration)
                self.assertEqual(decision.action, HistoricalDecisionAction.ALLOW)

    def test_observe_classifies_rendered_but_never_skips(self):
        decision = self.policy.evaluate(
            _facts(planned=1, rendered=1),
            HistoricalNoveltyPolicyConfiguration(
                historical_policy_mode=HistoricalPolicyMode.OBSERVE,
            ),
        )
        self.assertEqual(decision.evidence_kind, HistoricalEvidenceKind.RENDERED)
        self.assertEqual(decision.action, HistoricalDecisionAction.ALLOW)

    def test_advisory_only_marks_rendered_evidence(self):
        configuration = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode.ADVISORY,
        )
        expected = (
            (_facts(rendered=1), HistoricalDecisionAction.ALLOW_ADVISORY),
            (_facts(planned=1), HistoricalDecisionAction.ALLOW),
            (_facts(failed=1), HistoricalDecisionAction.ALLOW),
            (_facts(identity_exists=False), HistoricalDecisionAction.ALLOW),
        )
        for facts, action in expected:
            with self.subTest(facts=facts):
                self.assertEqual(
                    self.policy.evaluate(facts, configuration).action,
                    action,
                )

    def test_enforce_requires_explicit_available_scope(self):
        with self.assertRaisesRegex(
            HistoricalNoveltyPolicyConfigurationError,
            "HISTORICAL_NOVELTY_ENFORCE_SCOPE_UNAVAILABLE",
        ):
            HistoricalNoveltyPolicyConfiguration(
                historical_policy_mode=HistoricalPolicyMode.ENFORCE,
            )

        configuration = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode.ENFORCE,
            historical_scope=HistoricalPolicyScope(
                HistoricalScopeType.PROJECT,
                "project-1",
            ),
            historical_window=HistoricalPolicyWindow(
                kind=HistoricalWindowKind.ALL_TIME,
            ),
        )
        self.assertEqual(
            self.policy.evaluate(_facts(rendered=1), configuration).action,
            HistoricalDecisionAction.SKIP_HISTORICAL_MATCH,
        )

    def test_rendered_override_requires_reason_and_is_explicit(self):
        configuration = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode.ENFORCE,
            historical_scope=HistoricalPolicyScope(
                HistoricalScopeType.PROJECT,
                "project-1",
            ),
            historical_window=HistoricalPolicyWindow(
                kind=HistoricalWindowKind.ALL_TIME,
            ),
        )
        with self.assertRaisesRegex(
            HistoricalNoveltyPolicyConfigurationError,
            "HISTORICAL_NOVELTY_REUSE_REASON_REQUIRED",
        ):
            HistoricalReuseIntent(allow_historical_reuse=True)

        decision = self.policy.evaluate(
            _facts(rendered=1),
            configuration,
            reuse_intent=HistoricalReuseIntent(
                allow_historical_reuse=True,
                reuse_reason="approved localization reuse",
            ),
        )
        self.assertEqual(decision.action, HistoricalDecisionAction.ALLOW_OVERRIDE)

    def test_advisory_reuse_intent_is_not_counted_as_actual_override(self):
        decision = self.policy.evaluate(
            _facts(rendered=1),
            HistoricalNoveltyPolicyConfiguration(
                historical_policy_mode=HistoricalPolicyMode.ADVISORY,
            ),
            reuse_intent=HistoricalReuseIntent(
                allow_historical_reuse=True,
                reuse_reason="future explicit reuse",
            ),
        )
        self.assertEqual(decision.action, HistoricalDecisionAction.ALLOW_ADVISORY)

    def test_historical_and_reservation_modes_are_independent(self):
        advisory_with_reservation = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode.ADVISORY,
            reservation_conflict_mode=ReservationConflictMode.ENFORCE,
        )
        off_with_reservation = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode.OFF,
            reservation_conflict_mode=ReservationConflictMode.ENFORCE,
        )
        for configuration in (advisory_with_reservation, off_with_reservation):
            with self.subTest(configuration=configuration):
                self.assertEqual(
                    self.policy.evaluate_reservation_conflict(True, configuration),
                    ReservationConflictAction.SKIP_RESERVATION_CONFLICT,
                )
        self.assertEqual(
            self.policy.evaluate_reservation_conflict(
                True,
                HistoricalNoveltyPolicyConfiguration(
                    historical_policy_mode=HistoricalPolicyMode.ADVISORY,
                    reservation_conflict_mode=ReservationConflictMode.OFF,
                ),
            ),
            ReservationConflictAction.ALLOW,
        )

    def test_tenant_storage_does_not_resolve_unavailable_policy_scope(self):
        configuration = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode.ADVISORY,
            reservation_conflict_mode=ReservationConflictMode.ENFORCE,
        )
        self.assertEqual(
            configuration.historical_scope.scope_type,
            HistoricalScopeType.UNAVAILABLE,
        )
        self.assertIsNone(configuration.historical_scope.scope_id)

    def test_window_contract_defaults_to_unspecified(self):
        self.assertEqual(
            HistoricalPolicyWindow().kind,
            HistoricalWindowKind.UNSPECIFIED,
        )

    def test_enforce_requires_explicit_window_intent(self):
        scope = HistoricalPolicyScope(HistoricalScopeType.PROJECT, "project-1")
        with self.assertRaisesRegex(
            HistoricalNoveltyPolicyConfigurationError,
            "HISTORICAL_NOVELTY_ENFORCE_WINDOW_UNAVAILABLE",
        ):
            HistoricalNoveltyPolicyConfiguration(
                historical_policy_mode=HistoricalPolicyMode.ENFORCE,
                historical_scope=scope,
            )

        all_time = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode.ENFORCE,
            historical_scope=scope,
            historical_window=HistoricalPolicyWindow(
                kind=HistoricalWindowKind.ALL_TIME,
            ),
        )
        self.assertEqual(
            all_time.historical_window.kind,
            HistoricalWindowKind.ALL_TIME,
        )

        duration = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode.ENFORCE,
            historical_scope=scope,
            historical_window=HistoricalPolicyWindow(
                kind=HistoricalWindowKind.DURATION,
                duration_seconds=3600,
            ),
        )
        self.assertEqual(duration.historical_window.duration_seconds, 3600)

    def test_non_enforce_modes_allow_unspecified_window(self):
        for mode in (
            HistoricalPolicyMode.OFF,
            HistoricalPolicyMode.OBSERVE,
            HistoricalPolicyMode.ADVISORY,
        ):
            with self.subTest(mode=mode):
                configuration = HistoricalNoveltyPolicyConfiguration(
                    historical_policy_mode=mode,
                )
                self.assertEqual(
                    configuration.historical_window.kind,
                    HistoricalWindowKind.UNSPECIFIED,
                )

    def test_window_contract_rejects_invalid_combinations(self):
        for kind in (
            HistoricalWindowKind.UNSPECIFIED,
            HistoricalWindowKind.ALL_TIME,
        ):
            with self.subTest(kind=kind):
                with self.assertRaises(HistoricalNoveltyPolicyConfigurationError):
                    HistoricalPolicyWindow(kind=kind, duration_seconds=1)

        for duration_seconds in (None, 0, -1, True):
            with self.subTest(duration_seconds=duration_seconds):
                with self.assertRaises(HistoricalNoveltyPolicyConfigurationError):
                    HistoricalPolicyWindow(
                        kind=HistoricalWindowKind.DURATION,
                        duration_seconds=duration_seconds,
                    )

        window = HistoricalPolicyWindow(
            kind=HistoricalWindowKind.DURATION,
            duration_seconds=3600,
        )
        self.assertEqual(window.duration_seconds, 3600)

    def test_explicit_tenant_and_campaign_scopes_are_typed_contracts_only(self):
        tenant = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode.ENFORCE,
            historical_scope=HistoricalPolicyScope(
                HistoricalScopeType.TENANT,
                "tenant-1",
            ),
            historical_window=HistoricalPolicyWindow(
                kind=HistoricalWindowKind.ALL_TIME,
            ),
        )
        campaign = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode.ENFORCE,
            historical_scope=HistoricalPolicyScope(
                HistoricalScopeType.CAMPAIGN,
                "campaign-1",
            ),
            historical_window=HistoricalPolicyWindow(
                kind=HistoricalWindowKind.DURATION,
                duration_seconds=7200,
            )
        )
        self.assertEqual(tenant.historical_scope.scope_type, HistoricalScopeType.TENANT)
        self.assertEqual(
            campaign.historical_scope.scope_type,
            HistoricalScopeType.CAMPAIGN,
        )

    def test_preview_intents_are_explicit_and_distinct(self):
        self.assertNotEqual(
            PreviewIntent.AUTOMATIC_PREVIEW,
            PreviewIntent.OPERATOR_PINNED_PREVIEW,
        )
        self.assertNotEqual(
            PreviewIntent.UNSPECIFIED,
            PreviewIntent.AUTOMATIC_PREVIEW,
        )

    def test_policy_evaluation_does_not_call_ledger_repository(self):
        configuration = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode.ADVISORY,
        )
        with (
            patch.object(
                FingerprintLedgerRepository,
                "lookup_historical_exact",
                side_effect=AssertionError("policy attempted DB lookup"),
            ),
            patch.object(
                FingerprintLedgerRepository,
                "acquire_reservation",
                side_effect=AssertionError("policy attempted reservation acquire"),
            ),
        ):
            decision = self.policy.evaluate(_facts(rendered=1), configuration)
        self.assertEqual(decision.action, HistoricalDecisionAction.ALLOW_ADVISORY)


class ReservationConfirmationImmutabilityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
        )
        ensure_fingerprint_ledger_schema(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.now = datetime(2026, 9, 1, 8, 0, 0)

    def tearDown(self):
        self.engine.dispose()

    def _acquire(self, db, owner="task-a", slot=0, now=None):
        observed_at = now or self.now
        return FingerprintLedgerRepository(db).acquire_reservation(
            _identity(),
            owner_task_id=owner,
            owner_slot_index=slot,
            now=observed_at,
            expires_at=observed_at + timedelta(minutes=10),
        )

    def test_first_binding_retry_and_different_execution_are_immutable(self):
        with self.Session() as db:
            acquired = self._acquire(db)
            repository = FingerprintLedgerRepository(db)
            first_time = self.now + timedelta(seconds=1)
            self.assertEqual(
                repository.confirm_reservation_detailed(
                    acquired.fingerprint_identity_id,
                    owner_task_id="task-a",
                    owner_slot_index=0,
                    execution_id="EXEC-1",
                    now=first_time,
                ),
                ReservationConfirmationStatus.CONFIRMED,
            )
            db.commit()

            self.assertEqual(
                repository.confirm_reservation_detailed(
                    acquired.fingerprint_identity_id,
                    owner_task_id="task-a",
                    owner_slot_index=0,
                    execution_id="EXEC-1",
                    now=self.now + timedelta(seconds=2),
                ),
                ReservationConfirmationStatus.ALREADY_CONFIRMED,
            )
            self.assertEqual(
                repository.confirm_reservation_detailed(
                    acquired.fingerprint_identity_id,
                    owner_task_id="task-a",
                    owner_slot_index=0,
                    execution_id="EXEC-2",
                    now=self.now + timedelta(seconds=3),
                ),
                ReservationConfirmationStatus.EXECUTION_BINDING_CONFLICT,
            )
            db.commit()
            row = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
            self.assertEqual(row.execution_id, "EXEC-1")
            self.assertEqual(row.confirmed_at, first_time)
            self.assertEqual(row.updated_at, first_time)

    def test_compatibility_bool_accepts_exact_retry_but_rejects_rebind(self):
        with self.Session() as db:
            acquired = self._acquire(db)
            repository = FingerprintLedgerRepository(db)
            self.assertTrue(repository.confirm_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
                execution_id="EXEC-1",
                now=self.now + timedelta(seconds=1),
            ))
            self.assertTrue(repository.confirm_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
                execution_id="EXEC-1",
                now=self.now + timedelta(seconds=2),
            ))
            self.assertFalse(repository.confirm_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
                execution_id="EXEC-2",
                now=self.now + timedelta(seconds=3),
            ))

    def test_wrong_owner_and_exact_expiry_return_owner_or_expiry_conflict(self):
        with self.Session() as db:
            acquired = self._acquire(db)
            repository = FingerprintLedgerRepository(db)
            self.assertEqual(
                repository.confirm_reservation_detailed(
                    acquired.fingerprint_identity_id,
                    owner_task_id="task-b",
                    owner_slot_index=0,
                    execution_id="EXEC-1",
                    now=self.now + timedelta(seconds=1),
                ),
                ReservationConfirmationStatus.OWNER_OR_EXPIRY_CONFLICT,
            )
            self.assertEqual(
                repository.confirm_reservation_detailed(
                    acquired.fingerprint_identity_id,
                    owner_task_id="task-a",
                    owner_slot_index=0,
                    execution_id="EXEC-1",
                    now=self.now + timedelta(minutes=10),
                ),
                ReservationConfirmationStatus.OWNER_OR_EXPIRY_CONFLICT,
            )

    def test_taken_over_reservation_rejects_old_owner_confirmation(self):
        utc_plus_8 = timezone(timedelta(hours=8))
        with self.Session() as db:
            first = FingerprintLedgerRepository(db).acquire_reservation(
                _identity(),
                owner_task_id="task-a",
                owner_slot_index=0,
                now=datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc),
                expires_at=datetime(2026, 9, 1, 16, 1, tzinfo=utc_plus_8),
            )
            db.commit()

        with self.Session() as db:
            repository = FingerprintLedgerRepository(db)
            takeover = repository.acquire_reservation(
                _identity(),
                owner_task_id="task-b",
                owner_slot_index=1,
                now=datetime(2026, 9, 1, 8, 1, tzinfo=timezone.utc),
                expires_at=datetime(2026, 9, 1, 8, 11, tzinfo=timezone.utc),
            )
            self.assertEqual(takeover.status, ReservationAcquireStatus.ACQUIRED)
            self.assertEqual(
                repository.confirm_reservation_detailed(
                    first.fingerprint_identity_id,
                    owner_task_id="task-a",
                    owner_slot_index=0,
                    execution_id="EXEC-OLD",
                    now=datetime(2026, 9, 1, 8, 2, tzinfo=timezone.utc),
                ),
                ReservationConfirmationStatus.OWNER_OR_EXPIRY_CONFLICT,
            )
            row = db.get(FingerprintReservation, first.fingerprint_identity_id)
            self.assertEqual((row.owner_task_id, row.owner_slot_index), ("task-b", 1))
            self.assertIsNone(row.execution_id)

    def test_confirmation_hardening_keeps_ledger_schema_v2(self):
        self.assertEqual(LEDGER_SCHEMA_VERSION, 2)

    def test_two_sessions_atomically_bind_only_one_first_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tenant.db"
            engine = create_engine(
                f"sqlite:///{path}",
                connect_args={"check_same_thread": False, "timeout": 10},
            )
            ensure_fingerprint_ledger_schema(engine)
            Session = sessionmaker(bind=engine)
            now = datetime(2026, 9, 1, 8, 0, 0)
            with Session() as db:
                acquired = FingerprintLedgerRepository(db).acquire_reservation(
                    _identity(),
                    owner_task_id="task-a",
                    owner_slot_index=0,
                    now=now,
                    expires_at=now + timedelta(minutes=10),
                )
                db.commit()

            barrier = threading.Barrier(2)
            results = []
            failures = []
            result_lock = threading.Lock()

            def confirm(execution_id):
                try:
                    with Session() as db:
                        barrier.wait()
                        status = FingerprintLedgerRepository(
                            db
                        ).confirm_reservation_detailed(
                            acquired.fingerprint_identity_id,
                            owner_task_id="task-a",
                            owner_slot_index=0,
                            execution_id=execution_id,
                            now=now + timedelta(seconds=1),
                        )
                        db.commit()
                    with result_lock:
                        results.append((execution_id, status))
                except Exception as exc:
                    with result_lock:
                        failures.append(exc)

            threads = [
                threading.Thread(target=confirm, args=(execution_id,))
                for execution_id in ("EXEC-1", "EXEC-2")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertFalse(failures)
            self.assertEqual(
                sorted(status.value for _, status in results),
                sorted(
                    (
                        ReservationConfirmationStatus.CONFIRMED.value,
                        ReservationConfirmationStatus.EXECUTION_BINDING_CONFLICT.value,
                    )
                ),
            )
            with Session() as db:
                row = db.get(
                    FingerprintReservation,
                    acquired.fingerprint_identity_id,
                )
                self.assertIn(row.execution_id, {"EXEC-1", "EXEC-2"})
                self.assertIsNotNone(row.confirmed_at)
                confirmed_execution_ids = {
                    execution_id
                    for execution_id, status in results
                    if status is ReservationConfirmationStatus.CONFIRMED
                }
                self.assertEqual(confirmed_execution_ids, {row.execution_id})
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
