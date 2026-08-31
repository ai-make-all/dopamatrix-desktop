import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from src.api import database, routes_dsl
from src.api.fingerprint_ledger import (
    LEDGER_SCHEMA_COMPONENT,
    LEDGER_SCHEMA_VERSION,
    FingerprintIdentity,
    FingerprintIdentityRecord,
    FingerprintLedgerCanonicalMismatch,
    FingerprintLedgerError,
    FingerprintLedgerRepository,
    FingerprintLedgerSchemaVersion,
    FingerprintOccurrence,
    FingerprintOccurrenceRecord,
    FingerprintReservation,
    ReservationAcquireStatus,
    ensure_fingerprint_ledger_schema,
)
from src.api.models import Base
from tests.test_var001_balanced_axis_coverage import (
    _SyntheticParser,
    _payload,
    _pools,
)


def _identity(**overrides):
    values = {
        "fingerprint_type": "main_visual_planning",
        "fingerprint_version": 1,
        "fingerprint_digest": "a" * 64,
        "digest_algorithm": "sha256",
        "source_hash_algorithm": "md5",
        "canonical_payload": '{"fingerprint_type":"main_visual_planning"}',
    }
    values.update(overrides)
    return FingerprintIdentityRecord(**values)


def _occurrence(lifecycle_event="PLANNED", **overrides):
    identity = _identity()
    values = {
        **identity.__dict__,
        "task_id": "task-a",
        "execution_id": "execution-a",
        "child_index": 0,
        "lifecycle_event": lifecycle_event,
        "provenance": "coordinator_authoritative_fp001",
    }
    values.update(overrides)
    return FingerprintOccurrenceRecord(**values)


def _engine(url="sqlite://"):
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    ensure_fingerprint_ledger_schema(engine)
    return engine


def _create_valid_v1_schema(engine):
    FingerprintLedgerSchemaVersion.__table__.create(bind=engine)
    FingerprintIdentity.__table__.create(bind=engine)
    FingerprintOccurrence.__table__.create(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            sqlite_insert(FingerprintLedgerSchemaVersion).values(
                component=LEDGER_SCHEMA_COMPONENT,
                schema_version=1,
                updated_at=datetime(2026, 1, 1),
            )
        )


def _create_malformed_reservation_schema(engine):
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE fingerprint_reservations ("
            "fingerprint_identity_id INTEGER NOT NULL PRIMARY KEY, "
            "owner_task_id VARCHAR(64) NOT NULL, owner_slot_index INTEGER NOT NULL, "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
            "expires_at DATETIME NOT NULL, confirmed_at DATETIME, "
            "execution_id VARCHAR(64), "
            "FOREIGN KEY(fingerprint_identity_id) "
            "REFERENCES fingerprint_identities(id) ON DELETE NO ACTION)"
        ))
        connection.execute(text(
            "CREATE INDEX ix_fingerprint_reservation_expires_at "
            "ON fingerprint_reservations (expires_at)"
        ))
        connection.execute(text(
            "CREATE INDEX ix_fingerprint_reservation_owner "
            "ON fingerprint_reservations (owner_task_id, owner_slot_index)"
        ))


class FingerprintLedgerV2MigrationTests(unittest.TestCase):
    def test_valid_v1_migrates_to_v2_without_identity_or_occurrence_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tenant.db"
            engine = create_engine(f"sqlite:///{path}")
            _create_valid_v1_schema(engine)
            Session = sessionmaker(bind=engine)
            with Session() as db:
                FingerprintLedgerRepository(db).record_occurrence(_occurrence("RENDERED"))
                db.commit()

            ensure_fingerprint_ledger_schema(engine)
            self.assertIn(FingerprintReservation.__tablename__, inspect(engine).get_table_names())
            with Session() as db:
                version = db.get(FingerprintLedgerSchemaVersion, LEDGER_SCHEMA_COMPONENT)
                self.assertEqual(version.schema_version, LEDGER_SCHEMA_VERSION)
                self.assertEqual(db.scalar(select(func.count(FingerprintIdentity.id))), 1)
                self.assertEqual(db.scalar(select(func.count(FingerprintOccurrence.id))), 1)
            engine.dispose()

            reopened = create_engine(f"sqlite:///{path}")
            ensure_fingerprint_ledger_schema(reopened)
            with sessionmaker(bind=reopened)() as db:
                self.assertEqual(
                    db.get(FingerprintLedgerSchemaVersion, LEDGER_SCHEMA_COMPONENT).schema_version,
                    2,
                )
                self.assertEqual(db.scalar(select(func.count(FingerprintOccurrence.id))), 1)
            reopened.dispose()

    def test_v2_reservation_contract_is_reflected_and_global_base_excludes_it(self):
        engine = _engine()
        inspector = inspect(engine)
        columns = {item["name"]: item for item in inspector.get_columns(
            FingerprintReservation.__tablename__
        )}
        self.assertEqual(
            inspector.get_pk_constraint(FingerprintReservation.__tablename__)[
                "constrained_columns"
            ],
            ["fingerprint_identity_id"],
        )
        foreign_key = inspector.get_foreign_keys(FingerprintReservation.__tablename__)[0]
        self.assertEqual(foreign_key["referred_columns"], ["id"])
        self.assertEqual(foreign_key["options"]["ondelete"], "CASCADE")
        self.assertFalse(columns["confirmed_at"]["nullable"] is False)
        self.assertFalse(columns["execution_id"]["nullable"] is False)
        self.assertNotIn(FingerprintReservation.__tablename__, Base.metadata.tables)
        engine.dispose()

    def test_malformed_reservation_fails_before_v1_version_is_advanced(self):
        engine = create_engine("sqlite://")
        _create_valid_v1_schema(engine)
        _create_malformed_reservation_schema(engine)
        with self.assertRaisesRegex(
            FingerprintLedgerError,
            "FINGERPRINT_LEDGER_SCHEMA_INVALID",
        ):
            ensure_fingerprint_ledger_schema(engine)
        with sessionmaker(bind=engine)() as db:
            version = db.get(FingerprintLedgerSchemaVersion, LEDGER_SCHEMA_COMPONENT)
            self.assertEqual(version.schema_version, 1)
        engine.dispose()

    def test_actual_v1_to_v2_failure_does_not_poison_engine_cache(self):
        malformed_engine = create_engine("sqlite://")
        retry_engine = create_engine("sqlite://")
        _create_valid_v1_schema(malformed_engine)
        _create_malformed_reservation_schema(malformed_engine)
        engine_cache = {}
        try:
            with (
                patch.object(database, "_tenant_engines", engine_cache),
                patch.object(
                    database,
                    "create_engine",
                    side_effect=[malformed_engine, retry_engine],
                ),
            ):
                with self.assertRaises(FingerprintLedgerError):
                    database.get_tenant_engine("migration-retry")
                self.assertNotIn("migration-retry", engine_cache)

                initialized = database.get_tenant_engine("migration-retry")
                self.assertIs(initialized, retry_engine)
                self.assertIs(engine_cache["migration-retry"], retry_engine)
        finally:
            malformed_engine.dispose()
            retry_engine.dispose()


class FingerprintReservationTests(unittest.TestCase):
    def setUp(self):
        self.engine = _engine()
        self.Session = sessionmaker(bind=self.engine)
        self.now = datetime(2026, 1, 1, 12, 0, 0)

    def tearDown(self):
        self.engine.dispose()

    def _acquire(self, db, owner="task-a", slot=0, now=None, expires_at=None):
        observed_at = now or self.now
        return FingerprintLedgerRepository(db).acquire_reservation(
            _identity(),
            owner_task_id=owner,
            owner_slot_index=slot,
            now=observed_at,
            expires_at=expires_at or observed_at + timedelta(minutes=1),
        )

    def test_non_utc_aware_acquire_persists_utc_naive_timestamps(self):
        utc_plus_8 = timezone(timedelta(hours=8))
        now = datetime(2026, 8, 31, 7, 0, tzinfo=timezone.utc)
        expires_at = datetime(2026, 8, 31, 16, 0, tzinfo=utc_plus_8)

        with self.Session() as db:
            acquired = self._acquire(db, now=now, expires_at=expires_at)
            db.commit()
            row = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
            self.assertEqual(row.created_at, datetime(2026, 8, 31, 7, 0))
            self.assertEqual(row.updated_at, datetime(2026, 8, 31, 7, 0))
            self.assertEqual(row.expires_at, datetime(2026, 8, 31, 8, 0))
            self.assertIsNone(row.created_at.tzinfo)
            self.assertIsNone(row.updated_at.tzinfo)
            self.assertIsNone(row.expires_at.tzinfo)

    def test_confirmation_compares_non_utc_offset_by_absolute_instant(self):
        utc_plus_8 = timezone(timedelta(hours=8))
        utc_plus_9 = timezone(timedelta(hours=9))
        now = datetime(2026, 8, 31, 15, 0, tzinfo=utc_plus_8)
        expires_at = datetime(2026, 8, 31, 16, 0, tzinfo=utc_plus_8)

        with self.Session() as db:
            acquired = self._acquire(db, now=now, expires_at=expires_at)
            repository = FingerprintLedgerRepository(db)
            self.assertTrue(repository.confirm_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
                execution_id="execution-a",
                now=datetime(2026, 8, 31, 16, 0, tzinfo=utc_plus_9),
            ))
            db.commit()
            row = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
            self.assertEqual(row.confirmed_at, datetime(2026, 8, 31, 7, 0))
            self.assertIsNone(row.confirmed_at.tzinfo)

    def test_exact_expiry_is_invalid_and_not_confirmable_across_offsets(self):
        utc_plus_8 = timezone(timedelta(hours=8))
        with self.Session() as db:
            with self.assertRaisesRegex(
                FingerprintLedgerError,
                "FINGERPRINT_RESERVATION_EXPIRY_INVALID",
            ):
                self._acquire(
                    db,
                    now=datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc),
                    expires_at=datetime(2026, 8, 31, 16, 0, tzinfo=utc_plus_8),
                )

            acquired = self._acquire(
                db,
                now=datetime(2026, 8, 31, 7, 0, tzinfo=timezone.utc),
                expires_at=datetime(2026, 8, 31, 16, 0, tzinfo=utc_plus_8),
            )
            self.assertFalse(FingerprintLedgerRepository(db).confirm_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
                execution_id="at-expiry",
                now=datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc),
            ))

    def test_expired_takeover_compares_absolute_instant_across_timezones(self):
        utc_plus_8 = timezone(timedelta(hours=8))
        utc_plus_9 = timezone(timedelta(hours=9))
        with self.Session() as db:
            first = self._acquire(
                db,
                now=datetime(2026, 8, 31, 7, 0, tzinfo=timezone.utc),
                expires_at=datetime(2026, 8, 31, 16, 0, tzinfo=utc_plus_8),
            )
            db.commit()

        with self.Session() as db:
            conflict = self._acquire(
                db,
                owner="task-b",
                now=datetime(2026, 8, 31, 16, 59, tzinfo=utc_plus_9),
                expires_at=datetime(2026, 8, 31, 18, 0, tzinfo=utc_plus_9),
            )
            self.assertEqual(conflict.status, ReservationAcquireStatus.CONFLICT)
            db.rollback()

        with self.Session() as db:
            takeover = self._acquire(
                db,
                owner="task-b",
                slot=1,
                now=datetime(2026, 8, 31, 17, 0, tzinfo=utc_plus_9),
                expires_at=datetime(2026, 8, 31, 18, 0, tzinfo=utc_plus_9),
            )
            db.commit()
            row = db.get(FingerprintReservation, first.fingerprint_identity_id)
            self.assertEqual(takeover.status, ReservationAcquireStatus.ACQUIRED)
            self.assertEqual((row.owner_task_id, row.owner_slot_index), ("task-b", 1))
            self.assertEqual(row.expires_at, datetime(2026, 8, 31, 9, 0))

    def test_mixed_aware_and_naive_inputs_share_utc_naive_contract(self):
        with self.Session() as db:
            acquired = self._acquire(
                db,
                now=datetime(2026, 8, 31, 7, 0, tzinfo=timezone.utc),
                expires_at=datetime(2026, 8, 31, 8, 0),
            )
            db.commit()
            row = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
            self.assertEqual(row.created_at, datetime(2026, 8, 31, 7, 0))
            self.assertEqual(row.expires_at, datetime(2026, 8, 31, 8, 0))

    def test_past_and_zero_length_requested_leases_remain_invalid(self):
        utc_plus_8 = timezone(timedelta(hours=8))
        now = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)
        for expires_at in (
            datetime(2026, 8, 31, 16, 0, tzinfo=utc_plus_8),
            datetime(2026, 8, 31, 15, 59, tzinfo=utc_plus_8),
        ):
            with self.subTest(expires_at=expires_at):
                with self.Session() as db:
                    with self.assertRaisesRegex(
                        FingerprintLedgerError,
                        "FINGERPRINT_RESERVATION_EXPIRY_INVALID",
                    ):
                        self._acquire(db, now=now, expires_at=expires_at)

    def test_same_owner_reacquires_idempotently_and_refreshes_lease(self):
        with self.Session() as db:
            first = self._acquire(db)
            db.commit()
        with self.Session() as db:
            second = self._acquire(
                db,
                now=self.now + timedelta(seconds=10),
                expires_at=self.now + timedelta(minutes=2),
            )
            db.commit()
            row = db.get(FingerprintReservation, first.fingerprint_identity_id)
            self.assertEqual(second.status, ReservationAcquireStatus.REACQUIRED)
            self.assertEqual(row.owner_task_id, "task-a")
            self.assertEqual(db.scalar(select(func.count(FingerprintReservation.fingerprint_identity_id))), 1)

    def test_different_owner_conflicts_with_unexpired_reservation(self):
        with self.Session() as db:
            first = self._acquire(db)
            db.commit()
        with self.Session() as db:
            conflict = self._acquire(
                db,
                owner="task-b",
                now=self.now + timedelta(seconds=1),
            )
            db.commit()
            row = db.get(FingerprintReservation, first.fingerprint_identity_id)
            self.assertEqual(conflict.status, ReservationAcquireStatus.CONFLICT)
            self.assertEqual(row.owner_task_id, "task-a")

    def test_expired_reservation_is_atomically_taken_over(self):
        with self.Session() as db:
            first = self._acquire(
                db,
                expires_at=self.now + timedelta(seconds=5),
            )
            db.commit()
        with self.Session() as db:
            takeover = self._acquire(
                db,
                owner="task-b",
                slot=1,
                now=self.now + timedelta(seconds=6),
            )
            db.commit()
            row = db.get(FingerprintReservation, first.fingerprint_identity_id)
            self.assertEqual(takeover.status, ReservationAcquireStatus.ACQUIRED)
            self.assertEqual((row.owner_task_id, row.owner_slot_index), ("task-b", 1))
            self.assertIsNone(row.confirmed_at)
            self.assertIsNone(row.execution_id)

    def test_release_is_owner_checked_and_idempotent(self):
        with self.Session() as db:
            acquired = self._acquire(db)
            repository = FingerprintLedgerRepository(db)
            self.assertFalse(repository.release_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-b",
                owner_slot_index=0,
            ))
            self.assertTrue(repository.release_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
            ))
            self.assertFalse(repository.release_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
            ))
            reacquired = self._acquire(db, owner="task-b")
            db.commit()
            self.assertEqual(reacquired.status, ReservationAcquireStatus.ACQUIRED)

    def test_confirmation_requires_current_owner_and_unexpired_lease(self):
        with self.Session() as db:
            acquired = self._acquire(
                db,
                expires_at=self.now + timedelta(seconds=5),
            )
            repository = FingerprintLedgerRepository(db)
            self.assertFalse(repository.confirm_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-b",
                owner_slot_index=0,
                execution_id="wrong",
                now=self.now + timedelta(seconds=1),
            ))
            self.assertTrue(repository.confirm_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
                execution_id="execution-a",
                now=self.now + timedelta(seconds=1),
            ))
            db.commit()
            row = db.get(FingerprintReservation, acquired.fingerprint_identity_id)
            self.assertEqual(row.execution_id, "execution-a")
            self.assertIsNotNone(row.confirmed_at)
            self.assertFalse(repository.confirm_reservation(
                acquired.fingerprint_identity_id,
                owner_task_id="task-a",
                owner_slot_index=0,
                execution_id="late",
                now=self.now + timedelta(seconds=6),
            ))

    def test_reservation_write_obeys_caller_transaction_rollback(self):
        with self.Session() as db:
            self._acquire(db)
            db.rollback()
        with self.Session() as db:
            self.assertEqual(db.scalar(select(func.count(FingerprintReservation.fingerprint_identity_id))), 0)


class FingerprintReservationConcurrencyTests(unittest.TestCase):
    def test_two_sessions_atomically_claim_same_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tenant.db"
            engine = _engine(f"sqlite:///{path}")
            Session = sessionmaker(bind=engine)
            barrier = threading.Barrier(2)
            results = []
            failures = []
            result_lock = threading.Lock()
            now = datetime(2026, 1, 1, 12, 0, 0)

            def claim(owner):
                try:
                    with Session() as db:
                        barrier.wait()
                        result = FingerprintLedgerRepository(db).acquire_reservation(
                            _identity(),
                            owner_task_id=owner,
                            owner_slot_index=0,
                            now=now,
                            expires_at=now + timedelta(minutes=1),
                        )
                        db.commit()
                    with result_lock:
                        results.append(result.status)
                except Exception as exc:
                    with result_lock:
                        failures.append(exc)

            threads = [threading.Thread(target=claim, args=(owner,)) for owner in ("a", "b")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)

            self.assertFalse(failures)
            self.assertEqual(
                sorted(status.value for status in results),
                [ReservationAcquireStatus.ACQUIRED.value, ReservationAcquireStatus.CONFLICT.value],
            )
            with Session() as db:
                rows = db.scalars(select(FingerprintReservation)).all()
                self.assertEqual(len(rows), 1)
                self.assertIn(rows[0].owner_task_id, {"a", "b"})
            engine.dispose()


class FingerprintHistoricalLookupTests(unittest.TestCase):
    def setUp(self):
        self.engine = _engine()
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_no_match_is_read_only_and_does_not_create_identity(self):
        with self.Session() as db:
            result = FingerprintLedgerRepository(db).lookup_historical_exact(_identity())
            self.assertFalse(result.identity_exists)
            self.assertFalse(result.historical_match)
            self.assertEqual(result.historical_occurrence_count, 0)
            self.assertEqual(db.scalar(select(func.count(FingerprintIdentity.id))), 0)

    def test_rendered_history_returns_separate_counts_and_timestamps(self):
        first = datetime(2026, 1, 1, 12, 0, 0)
        rendered = first + timedelta(seconds=5)
        with self.Session() as db:
            identity = FingerprintLedgerRepository(db).ensure_identity(_identity())
            db.add_all([
                FingerprintOccurrence(
                    fingerprint_identity_id=identity.id,
                    task_id="task-a",
                    execution_id="planned-a",
                    child_index=0,
                    lifecycle_event="PLANNED",
                    occurred_at=first,
                    provenance="test",
                ),
                FingerprintOccurrence(
                    fingerprint_identity_id=identity.id,
                    task_id="task-a",
                    execution_id="rendered-a",
                    child_index=0,
                    lifecycle_event="RENDERED",
                    occurred_at=rendered,
                    provenance="test",
                ),
            ])
            db.commit()
            result = FingerprintLedgerRepository(db).lookup_historical_exact(_identity())
            self.assertTrue(result.identity_exists)
            self.assertTrue(result.historical_match)
            self.assertEqual(
                (result.planned_count, result.rendered_count, result.failed_count),
                (1, 1, 0),
            )
            self.assertEqual(result.first_seen_at, first)
            self.assertEqual(result.last_seen_at, rendered)
            self.assertEqual(result.last_rendered_at, rendered)

    def test_mixed_history_aggregates_lifecycle_facts(self):
        records = [
            _occurrence("PLANNED", execution_id="p1"),
            _occurrence("PLANNED", task_id="task-b", execution_id="p2", child_index=1),
            _occurrence("RENDERED", execution_id="r1"),
            _occurrence("FAILED", task_id="task-c", execution_id="f1", child_index=2),
        ]
        with self.Session() as db:
            FingerprintLedgerRepository(db).record_occurrences(records)
            db.commit()
            result = FingerprintLedgerRepository(db).lookup_historical_exact(_identity())
            self.assertEqual(result.historical_occurrence_count, 4)
            self.assertEqual(
                (result.planned_count, result.rendered_count, result.failed_count),
                (2, 1, 1),
            )

    def test_lookup_revalidates_canonical_metadata(self):
        with self.Session() as db:
            FingerprintLedgerRepository(db).ensure_identity(_identity())
            db.commit()
            with self.assertRaises(FingerprintLedgerCanonicalMismatch):
                FingerprintLedgerRepository(db).lookup_historical_exact(
                    _identity(canonical_payload='{"different":true}')
                )
            for field, value in (
                ("digest_algorithm", "other"),
                ("source_hash_algorithm", "other"),
            ):
                with self.subTest(field=field):
                    with self.assertRaisesRegex(
                        FingerprintLedgerError,
                        "FINGERPRINT_LEDGER_IDENTITY_METADATA_MISMATCH",
                    ):
                        FingerprintLedgerRepository(db).lookup_historical_exact(
                            _identity(**{field: value})
                        )

    def test_reservation_only_identity_is_not_historical_match(self):
        now = datetime(2026, 1, 1, 12, 0, 0)
        with self.Session() as db:
            FingerprintLedgerRepository(db).acquire_reservation(
                _identity(),
                owner_task_id="task-a",
                owner_slot_index=0,
                now=now,
                expires_at=now + timedelta(minutes=1),
            )
            db.commit()
            result = FingerprintLedgerRepository(db).lookup_historical_exact(_identity())
            self.assertTrue(result.identity_exists)
            self.assertFalse(result.historical_match)
            self.assertEqual(result.historical_occurrence_count, 0)

    def test_tenant_history_and_reservations_are_physically_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            engines = [
                _engine(f"sqlite:///{Path(directory) / name}")
                for name in ("tenant-a.db", "tenant-b.db")
            ]
            now = datetime(2026, 1, 1, 12, 0, 0)
            with sessionmaker(bind=engines[0])() as db:
                repository = FingerprintLedgerRepository(db)
                repository.record_occurrence(_occurrence("RENDERED"))
                repository.acquire_reservation(
                    _identity(), owner_task_id="a", owner_slot_index=0,
                    now=now, expires_at=now + timedelta(minutes=1),
                )
                db.commit()
            with sessionmaker(bind=engines[1])() as db:
                repository = FingerprintLedgerRepository(db)
                self.assertFalse(repository.lookup_historical_exact(_identity()).historical_match)
                acquired = repository.acquire_reservation(
                    _identity(), owner_task_id="b", owner_slot_index=0,
                    now=now, expires_at=now + timedelta(minutes=1),
                )
                db.commit()
                self.assertEqual(acquired.status, ReservationAcquireStatus.ACQUIRED)
            for engine in engines:
                engine.dispose()


class FingerprintLedgerNoEnforcementTests(unittest.TestCase):
    def test_history_and_active_reservation_do_not_change_balanced_selection(self):
        pools = _pools(4, 2)
        payload = _payload(pools)
        before = routes_dsl._plan_exact_main_visual_balanced_variants(
            _SyntheticParser(pools), payload, 4
        )
        contract = routes_dsl._main_visual_planning_fingerprint_contract(
            before.fingerprints[0]
        )
        identity_record = _identity(
            fingerprint_digest=contract.fingerprint_digest,
            canonical_payload=contract.canonical_bytes.decode("utf-8"),
        )
        engine = _engine()
        now = datetime(2026, 1, 1, 12, 0, 0)
        with sessionmaker(bind=engine)() as db:
            repository = FingerprintLedgerRepository(db)
            repository.record_occurrence(FingerprintOccurrenceRecord(
                **identity_record.__dict__,
                task_id="historical",
                execution_id="historical-render",
                child_index=0,
                lifecycle_event="RENDERED",
                provenance="test",
            ))
            repository.acquire_reservation(
                identity_record,
                owner_task_id="active-owner",
                owner_slot_index=0,
                now=now,
                expires_at=now + timedelta(minutes=1),
            )
            db.commit()

        after = routes_dsl._plan_exact_main_visual_balanced_variants(
            _SyntheticParser(pools), payload, 4
        )
        self.assertEqual(before.plans, after.plans)
        self.assertEqual(before.fingerprints, after.fingerprints)
        self.assertEqual(before.coverage_diagnostics, after.coverage_diagnostics)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
