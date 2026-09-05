import inspect as python_inspect
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select, update
from sqlalchemy.orm import sessionmaker

from src.api import (
    database,
    reservation_rollout_readiness as rollout,
    routes_dsl,
    routes_reservation_diagnostics as diagnostics_routes,
)
from src.api.database import initialize_application_schema
from src.api.fingerprint_ledger import (
    FingerprintReservation,
    LEDGER_SCHEMA_VERSION,
    ensure_fingerprint_ledger_schema,
)
from src.api.models import ReservationRunDiagnostic, VideoTask
from src.api.public_task_admission import (
    PublicTaskAdmissionError,
    admit_public_task,
    transition_public_task_status,
)
from src.api.reservation_lease import ReservationLeaseConfiguration
from src.api.reservation_rollout_readiness import (
    RESERVATION_ROLLOUT_READINESS_CONFIGURATION_INVALID,
    RESERVATION_ROLLOUT_READINESS_UNAVAILABLE,
    ReservationRolloutReadinessConfiguration,
    ReservationRolloutReadinessConfigurationError,
    load_reservation_rollout_readiness_configuration,
    reservation_rollout_readiness,
)
from src.api.routes_reservation_diagnostics import (
    ReservationRolloutReadinessResponse,
    get_reservation_rollout_readiness,
)
from src.api.schemas import RenderDSLRequest
from tests.test_var001_clean_task_identity import _beat, _plan


_VALID_ENVIRONMENT = {
    "RESERVATION_ROLLOUT_READINESS_WINDOW": "24h",
    "RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS": "2",
    "RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS": "2",
    "RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS": "1",
    "RESERVATION_ROLLOUT_MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE": "1",
    "RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE": "1",
    "RESERVATION_ROLLOUT_MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE": "1",
    "RESERVATION_ROLLOUT_MAXIMUM_ZERO_PLAN_CONFLICT_RATE": "0",
    "RESERVATION_ROLLOUT_MAXIMUM_PARTIAL_PLAN_RATE": "0",
    "RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE": "0",
    "RESERVATION_ROLLOUT_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE": "0",
    "RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE": "0",
    "RESERVATION_ROLLOUT_MAXIMUM_CLEANUP_WARNING_RATE": "0",
}


class _Background:
    def __init__(self):
        self.tasks = []

    def add_task(self, function, *args, **kwargs):
        self.tasks.append(
            SimpleNamespace(func=function, args=args, kwargs=kwargs)
        )


class ReservationRolloutReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.engines = []
        self.now = datetime.now(timezone.utc)
        self.engine, self.Session = self._database("tenant-a.db")

    def tearDown(self):
        for engine in reversed(self.engines):
            engine.dispose()
        self.temporary.cleanup()

    def _database(self, name):
        path = Path(self.temporary.name) / name
        engine = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        initialize_application_schema(engine)
        ensure_fingerprint_ledger_schema(engine)
        self.engines.append(engine)
        return engine, sessionmaker(bind=engine, expire_on_commit=False)

    def _configuration(self, **overrides):
        values = {
            "evaluation_window": "24h",
            "minimum_authoritative_enforce_tasks": 2,
            "minimum_planning_observed_tasks": 2,
            "minimum_conflict_tasks": 1,
            "minimum_diagnostic_run_coverage_rate": 1.0,
            "minimum_planning_observation_coverage_rate": 1.0,
            "minimum_terminal_observation_coverage_rate": 1.0,
            "maximum_zero_plan_conflict_rate": 0.0,
            "maximum_partial_plan_rate": 0.0,
            "maximum_authority_loss_rate": 0.0,
            "maximum_terminal_persist_failure_rate": 0.0,
            "maximum_worker_lease_config_failure_rate": 0.0,
            "maximum_cleanup_warning_rate": 0.0,
        }
        values.update(overrides)
        return ReservationRolloutReadinessConfiguration(**values)

    def _admit(
        self,
        *,
        policy="exact_main_visual",
        mode="ENFORCE",
        status="completed",
        engine=None,
        Session=None,
        created_at=None,
    ):
        tenant_engine = engine or self.engine
        TenantSession = Session or self.Session
        admission = admit_public_task(
            tenant_engine,
            prompt="rollout evidence",
            batch_size=1,
            reservation_conflict_mode=mode,
            planning_policy=policy,
        )
        with TenantSession() as session:
            session.execute(
                update(VideoTask)
                .where(VideoTask.task_id == admission.task_id)
                .values(
                    status=status,
                    created_at=(
                        created_at
                        if created_at is not None
                        else self.now - timedelta(minutes=5)
                    ),
                    finished_at=(
                        self.now if status in {"completed", "failed"} else None
                    ),
                )
            )
            session.commit()
        return admission.task_id

    def _diagnostic(
        self,
        task_id,
        *,
        policy="exact_main_visual",
        planning=True,
        terminal_status="completed",
        conflict=False,
        zero_plan=False,
        partial_plan=False,
        authority_lost=False,
        terminal_persist_failed=False,
        worker_lease_config_failed=False,
        cleanup_warning=False,
        Session=None,
    ):
        TenantSession = Session or self.Session
        requested_count = 2 if partial_plan else 1
        planned_count = (
            None
            if not planning
            else 0 if zero_plan else 1
        )
        conflict_count = 1 if conflict or zero_plan else 0
        with TenantSession() as session:
            session.add(
                ReservationRunDiagnostic(
                    task_id=task_id,
                    planning_policy=policy,
                    requested_count=requested_count,
                    planning_observed=planning,
                    planned_count=planned_count,
                    succeeded_count=(
                        None if terminal_status is None else 0
                    ),
                    failed_count=(
                        None
                        if terminal_status is None
                        else 1 if terminal_status == "failed" else 0
                    ),
                    reservation_conflict_count=conflict_count,
                    had_reservation_conflict=conflict_count > 0,
                    zero_plan_conflict=zero_plan,
                    partial_plan=partial_plan,
                    authority_lost=authority_lost,
                    terminal_persist_failed=terminal_persist_failed,
                    worker_lease_config_failed=worker_lease_config_failed,
                    cleanup_warning=cleanup_warning,
                    terminal_status=terminal_status,
                    started_at=self.now - timedelta(minutes=5),
                    finished_at=(
                        self.now if terminal_status is not None else None
                    ),
                )
            )
            session.commit()

    def _evaluate(
        self,
        configuration,
        *,
        policy="exact_main_visual",
        Session=None,
        lease_ready=True,
    ):
        TenantSession = Session or self.Session
        lease = (
            ReservationLeaseConfiguration(0.9, 0.15)
            if lease_ready
            else ReservationLeaseConfiguration()
        )
        with (
            TenantSession() as session,
            patch.object(
                rollout,
                "load_reservation_lease_configuration",
                return_value=lease,
            ),
        ):
            return reservation_rollout_readiness(
                session,
                planning_policy=policy,
                configuration=configuration,
                now=self.now,
            )

    def _seed_ready(
        self,
        *,
        policy="exact_main_visual",
        engine=None,
        Session=None,
    ):
        for _ in range(2):
            task_id = self._admit(
                policy=policy,
                engine=engine,
                Session=Session,
            )
            self._diagnostic(
                task_id,
                policy=policy,
                conflict=True,
                Session=Session,
            )

    @staticmethod
    def _gate_map(result):
        return {gate["code"]: gate for gate in result["gates"]}

    def test_backend_configuration_is_all_or_nothing_and_validated(self):
        self.assertIsNone(
            load_reservation_rollout_readiness_configuration({})
        )
        configuration = load_reservation_rollout_readiness_configuration(
            _VALID_ENVIRONMENT
        )
        self.assertEqual(configuration.evaluation_window, "24h")
        self.assertEqual(configuration.minimum_authoritative_enforce_tasks, 2)
        for window in ("24h", "7d", "30d"):
            environment = dict(_VALID_ENVIRONMENT)
            environment["RESERVATION_ROLLOUT_READINESS_WINDOW"] = window
            loaded = load_reservation_rollout_readiness_configuration(
                environment
            )
            self.assertEqual(loaded.evaluation_window, window)

        invalid_environments = []
        invalid_environments.append(
            {"RESERVATION_ROLLOUT_READINESS_WINDOW": "24h"}
        )
        for key, value in (
            ("RESERVATION_ROLLOUT_READINESS_WINDOW", "1h"),
            (
                "RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS",
                "-1",
            ),
            (
                "RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE",
                "NaN",
            ),
            (
                "RESERVATION_ROLLOUT_MAXIMUM_CLEANUP_WARNING_RATE",
                "1.01",
            ),
        ):
            environment = dict(_VALID_ENVIRONMENT)
            environment[key] = value
            invalid_environments.append(environment)

        for environment in invalid_environments:
            with self.subTest(environment=environment), self.assertRaises(
                ReservationRolloutReadinessConfigurationError
            ) as caught:
                load_reservation_rollout_readiness_configuration(environment)
            self.assertEqual(
                str(caught.exception),
                RESERVATION_ROLLOUT_READINESS_CONFIGURATION_INVALID,
            )

    def test_configured_windows_use_authoritative_task_created_at_cohort(self):
        for age in (
            timedelta(hours=12),
            timedelta(days=2),
            timedelta(days=10),
            timedelta(days=31),
        ):
            task_id = self._admit(created_at=self.now - age)
            self._diagnostic(task_id, conflict=True)

        expected_counts = {
            "24h": 1,
            "7d": 2,
            "30d": 3,
        }
        for window, expected_count in expected_counts.items():
            with self.subTest(window=window):
                result = self._evaluate(
                    self._configuration(
                        evaluation_window=window,
                        minimum_authoritative_enforce_tasks=0,
                        minimum_planning_observed_tasks=0,
                        minimum_conflict_tasks=0,
                        minimum_diagnostic_run_coverage_rate=0,
                        minimum_planning_observation_coverage_rate=0,
                        minimum_terminal_observation_coverage_rate=0,
                        maximum_zero_plan_conflict_rate=1,
                        maximum_partial_plan_rate=1,
                        maximum_authority_loss_rate=1,
                        maximum_terminal_persist_failure_rate=1,
                        maximum_worker_lease_config_failure_rate=1,
                        maximum_cleanup_warning_rate=1,
                    )
                )
                self.assertEqual(
                    result["authoritativeEnforceTaskCount"],
                    expected_count,
                )

    def test_admission_persists_normalized_authoritative_task_metadata(self):
        payloads = (
            RenderDSLRequest(
                engine_type="content",
                timeline=[],
                prompt="exact enforce",
                variant_planning_policy="exact_main_visual",
                reservation_conflict_mode="ENFORCE",
            ),
            RenderDSLRequest(
                engine_type="content",
                timeline=[],
                prompt="balanced enforce",
                variant_planning_policy="exact_main_visual_balanced",
                reservation_conflict_mode="ENFORCE",
            ),
            RenderDSLRequest(
                engine_type="content",
                timeline=[],
                prompt="exact off",
                variant_planning_policy="exact_main_visual",
            ),
        )
        with self.Session() as session:
            task_ids = [
                routes_dsl._admit_dsl_public_task(session, payload)
                for payload in payloads
            ]
        legacy = admit_public_task(
            self.engine,
            prompt="legacy",
            batch_size=1,
            reservation_conflict_mode="OFF",
            planning_policy="legacy",
        )

        with self.Session() as session:
            rows = {
                row.task_id: row
                for row in session.scalars(select(VideoTask)).all()
            }
        self.assertEqual(
            (
                rows[task_ids[0]].reservation_conflict_mode,
                rows[task_ids[0]].planning_policy,
            ),
            ("ENFORCE", "exact_main_visual"),
        )
        self.assertEqual(
            (
                rows[task_ids[1]].reservation_conflict_mode,
                rows[task_ids[1]].planning_policy,
            ),
            ("ENFORCE", "exact_main_visual_balanced"),
        )
        self.assertEqual(
            (
                rows[task_ids[2]].reservation_conflict_mode,
                rows[task_ids[2]].planning_policy,
            ),
            ("OFF", "exact_main_visual"),
        )
        self.assertEqual(
            (
                rows[legacy.task_id].reservation_conflict_mode,
                rows[legacy.task_id].planning_policy,
            ),
            ("OFF", "legacy"),
        )

        transition_public_task_status(
            self.engine,
            task_id=task_ids[0],
            target_status="processing",
        )
        transition_public_task_status(
            self.engine,
            task_id=task_ids[0],
            target_status="failed",
        )
        with self.Session() as session:
            transitioned = session.scalar(
                select(VideoTask).where(VideoTask.task_id == task_ids[0])
            )
        self.assertEqual(
            (
                transitioned.reservation_conflict_mode,
                transitioned.planning_policy,
            ),
            ("ENFORCE", "exact_main_visual"),
        )

        with self.assertRaises(ValidationError):
            RenderDSLRequest(
                engine_type="content",
                timeline=[],
                variant_planning_policy="exact_main_visual",
                reservation_conflict_mode="READY",
            )
        with self.assertRaises(PublicTaskAdmissionError):
            admit_public_task(
                self.engine,
                prompt="invalid",
                batch_size=1,
                reservation_conflict_mode="ENFORCE",
                planning_policy="legacy",
            )
        ignored_threshold = RenderDSLRequest(
            engine_type="content",
            timeline=[],
            minimum_authoritative_enforce_tasks=0,
        )
        self.assertNotIn(
            "minimum_authoritative_enforce_tasks",
            ignored_threshold.model_dump(),
        )

    def test_existing_schema_evolves_additively_without_enforce_fabrication(self):
        path = Path(self.temporary.name) / "pre-2f.db"
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE video_tasks ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "task_id VARCHAR(64) NOT NULL, "
                "prompt TEXT NOT NULL, "
                "batch_size INTEGER NOT NULL DEFAULT 1, "
                "status VARCHAR(20) NOT NULL DEFAULT 'queued', "
                "created_at DATETIME NOT NULL, "
                "finished_at DATETIME, "
                "llm_tokens_used INTEGER, "
                "tts_duration_seconds REAL, "
                "estimated_cost_usd REAL)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX ix_video_tasks_task_id "
                "ON video_tasks (task_id)"
            )
            connection.execute(
                "INSERT INTO video_tasks "
                "(task_id, prompt, batch_size, status, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "pre-2f-task",
                    "existing",
                    1,
                    "completed",
                    self.now.isoformat(),
                ),
            )
            connection.commit()
        finally:
            connection.close()

        engine = create_engine(f"sqlite:///{path.as_posix()}")
        self.engines.append(engine)
        initialize_application_schema(engine)
        inspector = inspect(engine)
        columns = {
            column["name"]: column
            for column in inspector.get_columns("video_tasks")
        }
        self.assertFalse(columns["reservation_conflict_mode"]["nullable"])
        self.assertFalse(columns["planning_policy"]["nullable"])
        indexes = {
            tuple(index.get("column_names") or ())
            for index in inspector.get_indexes("video_tasks")
        }
        self.assertIn(
            (
                "reservation_conflict_mode",
                "planning_policy",
                "created_at",
            ),
            indexes,
        )
        SessionLocal = sessionmaker(bind=engine)
        with SessionLocal() as session:
            row = session.scalar(
                select(VideoTask).where(VideoTask.task_id == "pre-2f-task")
            )
        self.assertEqual(row.reservation_conflict_mode, "OFF")
        self.assertEqual(row.planning_policy, "legacy")
        self.assertEqual(row.prompt, "existing")
        self.assertEqual(LEDGER_SCHEMA_VERSION, 2)

    def test_not_configured_is_safe_and_invalid_config_is_bounded(self):
        session = Mock()
        result = reservation_rollout_readiness(
            session,
            planning_policy="exact_main_visual",
            configuration=None,
        )
        self.assertEqual(result["state"], "NOT_CONFIGURED")
        self.assertEqual(result["recommendation"], "KEEP_EXPLICIT_ONLY")
        self.assertIsNone(result["evaluationWindow"])
        self.assertEqual(result["gates"], [])
        session.execute.assert_not_called()

        with patch.object(
            diagnostics_routes,
            "load_reservation_rollout_readiness_configuration",
            return_value=None,
        ):
            response = get_reservation_rollout_readiness(
                planning_policy="exact_main_visual",
                db=session,
            )
        self.assertEqual(response.state, "NOT_CONFIGURED")

        with (
            patch.object(
                diagnostics_routes,
                "load_reservation_rollout_readiness_configuration",
                side_effect=ReservationRolloutReadinessConfigurationError(),
            ),
            self.assertRaises(HTTPException) as caught,
        ):
            get_reservation_rollout_readiness(
                planning_policy="exact_main_visual",
                db=session,
            )
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(
            caught.exception.detail,
            RESERVATION_ROLLOUT_READINESS_CONFIGURATION_INVALID,
        )

    def test_authoritative_denominator_exposes_all_observation_loss(self):
        exact_tasks = [self._admit() for _ in range(3)]
        self._diagnostic(exact_tasks[0], conflict=True)
        self._diagnostic(
            exact_tasks[1],
            planning=False,
            terminal_status=None,
        )

        balanced = self._admit(policy="exact_main_visual_balanced")
        self._diagnostic(
            balanced,
            policy="exact_main_visual_balanced",
            conflict=True,
        )
        off = self._admit(mode="OFF")
        legacy = self._admit(policy="legacy", mode="OFF")
        self.assertNotEqual(off, legacy)

        configuration = self._configuration(
            minimum_authoritative_enforce_tasks=3,
            minimum_planning_observed_tasks=3,
            maximum_zero_plan_conflict_rate=1,
            maximum_partial_plan_rate=1,
            maximum_authority_loss_rate=1,
            maximum_terminal_persist_failure_rate=1,
            maximum_worker_lease_config_failure_rate=1,
            maximum_cleanup_warning_rate=1,
        )
        exact = self._evaluate(configuration)
        self.assertEqual(exact["authoritativeEnforceTaskCount"], 3)
        self.assertEqual(exact["diagnosticRunCount"], 2)
        self.assertEqual(exact["diagnosticRunCoverageRate"], 2 / 3)
        self.assertEqual(exact["planningObservedTaskCount"], 1)
        self.assertEqual(exact["planningObservationCoverageRate"], 1 / 3)
        self.assertEqual(exact["authoritativeTerminalTaskCount"], 3)
        self.assertEqual(exact["terminalDiagnosticTaskCount"], 1)
        self.assertEqual(exact["terminalObservationCoverageRate"], 1 / 3)
        self.assertEqual(exact["state"], "INSUFFICIENT_EVIDENCE")
        gates = self._gate_map(exact)
        for code in (
            "MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE",
            "MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE",
            "MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE",
        ):
            self.assertEqual(gates[code]["status"], "FAIL")

        balanced_result = self._evaluate(
            self._configuration(
                minimum_authoritative_enforce_tasks=1,
                minimum_planning_observed_tasks=1,
            ),
            policy="exact_main_visual_balanced",
        )
        self.assertEqual(
            balanced_result["authoritativeEnforceTaskCount"],
            1,
        )

    def test_insufficient_sample_and_conflict_evidence_are_not_blockers(self):
        for _ in range(2):
            task_id = self._admit()
            self._diagnostic(task_id)
        result = self._evaluate(
            self._configuration(
                minimum_authoritative_enforce_tasks=3,
                minimum_planning_observed_tasks=2,
                minimum_conflict_tasks=1,
                maximum_zero_plan_conflict_rate=1,
                maximum_partial_plan_rate=1,
                maximum_authority_loss_rate=1,
                maximum_terminal_persist_failure_rate=1,
                maximum_worker_lease_config_failure_rate=1,
                maximum_cleanup_warning_rate=1,
            )
        )
        self.assertEqual(result["state"], "INSUFFICIENT_EVIDENCE")
        gates = self._gate_map(result)
        self.assertEqual(
            gates["MINIMUM_AUTHORITATIVE_ENFORCE_TASKS"]["status"],
            "FAIL",
        )
        self.assertEqual(gates["MINIMUM_CONFLICT_TASKS"]["status"], "FAIL")

    def test_high_conflict_rate_and_active_task_are_informational(self):
        self._seed_ready()
        active = self._admit(status="processing")
        self._diagnostic(
            active,
            conflict=True,
            terminal_status=None,
        )
        result = self._evaluate(
            self._configuration(
                minimum_authoritative_enforce_tasks=3,
                minimum_planning_observed_tasks=3,
            )
        )
        self.assertEqual(result["conflictTaskRate"], 1.0)
        self.assertEqual(result["activeTaskCount"], 1)
        self.assertEqual(result["state"], "READY_FOR_CONTROLLED_CANARY")
        self.assertEqual(
            result["recommendation"],
            "ELIGIBLE_FOR_CONTROLLED_DEFAULT_ON_CANARY",
        )
        self.assertNotIn(
            "MAXIMUM_CONFLICT_TASK_RATE",
            self._gate_map(result),
        )

    def test_quality_and_authority_safety_rates_block_explicitly(self):
        scenarios = (
            (
                "MAXIMUM_ZERO_PLAN_CONFLICT_RATE",
                {
                    "status": "failed",
                    "conflict": True,
                    "zero_plan": True,
                },
            ),
            (
                "MAXIMUM_PARTIAL_PLAN_RATE",
                {"partial_plan": True},
            ),
            (
                "MAXIMUM_AUTHORITY_LOSS_RATE",
                {"status": "failed", "authority_lost": True},
            ),
            (
                "MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE",
                {"status": "failed", "terminal_persist_failed": True},
            ),
            (
                "MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE",
                {
                    "status": "failed",
                    "planning": False,
                    "worker_lease_config_failed": True,
                },
            ),
            (
                "MAXIMUM_CLEANUP_WARNING_RATE",
                {"cleanup_warning": True},
            ),
        )
        for index, (expected_gate, values) in enumerate(scenarios):
            with self.subTest(expected_gate=expected_gate):
                _engine, ScenarioSession = self._database(
                    f"guard-{index}.db"
                )
                diagnostic_values = dict(values)
                status = diagnostic_values.pop("status", "completed")
                task_id = self._admit(
                    status=status,
                    engine=_engine,
                    Session=ScenarioSession,
                )
                self._diagnostic(
                    task_id,
                    Session=ScenarioSession,
                    **diagnostic_values,
                )

                result = self._evaluate(
                    self._configuration(
                        minimum_authoritative_enforce_tasks=1,
                        minimum_planning_observed_tasks=0,
                        minimum_conflict_tasks=0,
                        minimum_planning_observation_coverage_rate=0,
                    ),
                    Session=ScenarioSession,
                )
                gates = self._gate_map(result)
                self.assertEqual(result["state"], "BLOCKED")
                self.assertEqual(gates[expected_gate]["status"], "FAIL")
                self.assertGreater(gates[expected_gate]["observed"], 0)

    def test_current_lease_configuration_is_a_strong_blocker(self):
        self._seed_ready()
        result = self._evaluate(
            self._configuration(),
            lease_ready=False,
        )
        self.assertFalse(result["leaseConfigurationReady"])
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(
            self._gate_map(result)["CURRENT_LEASE_CONFIGURATION_READY"][
                "status"
            ],
            "FAIL",
        )

    def test_exact_and_balanced_readiness_are_independent(self):
        self._seed_ready(policy="exact_main_visual")
        balanced_zero = self._admit(
            policy="exact_main_visual_balanced",
            status="failed",
        )
        self._diagnostic(
            balanced_zero,
            policy="exact_main_visual_balanced",
            conflict=True,
            zero_plan=True,
            terminal_status="failed",
        )
        balanced_clean = self._admit(
            policy="exact_main_visual_balanced"
        )
        self._diagnostic(
            balanced_clean,
            policy="exact_main_visual_balanced",
            conflict=True,
        )

        configuration = self._configuration()
        exact = self._evaluate(configuration)
        balanced = self._evaluate(
            configuration,
            policy="exact_main_visual_balanced",
        )
        self.assertEqual(exact["authoritativeEnforceTaskCount"], 2)
        self.assertEqual(balanced["authoritativeEnforceTaskCount"], 2)
        self.assertEqual(exact["state"], "READY_FOR_CONTROLLED_CANARY")
        self.assertEqual(balanced["state"], "BLOCKED")
        self.assertEqual(exact["zeroPlanConflictCount"], 0)
        self.assertEqual(balanced["zeroPlanConflictCount"], 1)

    def test_readiness_is_physically_tenant_isolated(self):
        engine_b, SessionB = self._database("tenant-b.db")
        self._seed_ready()
        self._seed_ready(engine=engine_b, Session=SessionB)
        with SessionB() as session:
            task = session.scalar(
                select(VideoTask).where(
                    VideoTask.reservation_conflict_mode == "ENFORCE"
                )
            )
            diagnostic = session.scalar(
                select(ReservationRunDiagnostic).where(
                    ReservationRunDiagnostic.task_id == task.task_id
                )
            )
            task.status = "failed"
            diagnostic.authority_lost = True
            diagnostic.terminal_status = "failed"
            session.commit()

        configuration = self._configuration()
        tenant_engines = {
            "tenant-a": self.engine,
            "tenant-b": engine_b,
        }
        app = FastAPI()
        app.include_router(
            diagnostics_routes.router,
            prefix="/api/v1",
        )
        lease = ReservationLeaseConfiguration(0.9, 0.15)
        with (
            patch.object(
                database,
                "get_tenant_engine",
                side_effect=lambda tenant_id: tenant_engines[tenant_id],
            ),
            patch.object(
                diagnostics_routes,
                "load_reservation_rollout_readiness_configuration",
                return_value=configuration,
            ),
            patch.object(
                rollout,
                "load_reservation_lease_configuration",
                return_value=lease,
            ),
            TestClient(app) as client,
        ):
            tenant_a = client.get(
                "/api/v1/diagnostics/reservation/readiness",
                params={"planning_policy": "exact_main_visual"},
                headers={"X-Local-User": "tenant-a"},
            )
            tenant_b = client.get(
                "/api/v1/diagnostics/reservation/readiness",
                params={"planning_policy": "exact_main_visual"},
                headers={"X-Local-User": "tenant-b"},
            )
        self.assertEqual(tenant_a.status_code, 200, tenant_a.text)
        self.assertEqual(tenant_b.status_code, 200, tenant_b.text)
        tenant_a_payload = tenant_a.json()
        tenant_b_payload = tenant_b.json()
        self.assertEqual(
            tenant_a_payload["state"],
            "READY_FOR_CONTROLLED_CANARY",
        )
        self.assertEqual(tenant_b_payload["state"], "BLOCKED")
        self.assertEqual(tenant_a_payload["authorityLossCount"], 0)
        self.assertEqual(tenant_b_payload["authorityLossCount"], 1)

    def test_zero_denominator_rates_are_unknown_and_never_ready(self):
        result = self._evaluate(
            self._configuration(
                minimum_authoritative_enforce_tasks=0,
                minimum_planning_observed_tasks=0,
                minimum_conflict_tasks=0,
                minimum_diagnostic_run_coverage_rate=0,
                minimum_planning_observation_coverage_rate=0,
                minimum_terminal_observation_coverage_rate=0,
                maximum_zero_plan_conflict_rate=1,
                maximum_partial_plan_rate=1,
                maximum_authority_loss_rate=1,
                maximum_terminal_persist_failure_rate=1,
                maximum_worker_lease_config_failure_rate=1,
                maximum_cleanup_warning_rate=1,
            )
        )
        self.assertEqual(result["state"], "INSUFFICIENT_EVIDENCE")
        for field in (
            "diagnosticRunCoverageRate",
            "planningObservationCoverageRate",
            "terminalObservationCoverageRate",
            "conflictTaskRate",
            "zeroPlanConflictRate",
            "partialPlanRate",
            "authorityLossRate",
            "terminalPersistFailureRate",
            "workerLeaseConfigFailureRate",
            "cleanupWarningRate",
        ):
            self.assertIsNone(result[field])
        self.assertTrue(
            any(gate["status"] == "UNKNOWN" for gate in result["gates"])
        )
        gates = self._gate_map(result)
        for code in (
            "MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE",
            "MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE",
            "MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE",
            "MAXIMUM_ZERO_PLAN_CONFLICT_RATE",
            "MAXIMUM_PARTIAL_PLAN_RATE",
            "MAXIMUM_AUTHORITY_LOSS_RATE",
            "MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE",
            "MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE",
            "MAXIMUM_CLEANUP_WARNING_RATE",
        ):
            self.assertEqual(gates[code]["status"], "UNKNOWN")

    def test_ready_result_cannot_activate_an_omitted_off_request(self):
        self._seed_ready()
        ready = self._evaluate(self._configuration())
        self.assertEqual(ready["state"], "READY_FOR_CONTROLLED_CANARY")

        payload = RenderDSLRequest(
            engine_type="content",
            timeline=[_beat()],
            prompt="default remains off",
            variant_planning_policy="exact_main_visual",
        )
        self.assertEqual(payload.reservation_conflict_mode, "OFF")
        background = _Background()
        parser = Mock()
        parser.parse_and_resolve.return_value = _plan()
        request = Mock(headers={"X-Local-User": "tenant-a"})
        with (
            self.Session() as session,
            patch.object(routes_dsl, "DSLParserNode", return_value=parser),
        ):
            response = routes_dsl.submit_dsl(
                payload,
                background,
                db=session,
                request=request,
            )
        task_id = response.task_id
        self.assertEqual(len(background.tasks), 1)
        dispatched = background.tasks[0]
        self.assertEqual(
            dispatched.kwargs["reservation_conflict_mode"],
            "OFF",
        )

        def implementation(*args, **kwargs):
            kwargs["_terminal_target_callback"]("completed")
            return {"taskId": args[1], "status": "completed"}

        with (
            patch.object(
                routes_dsl,
                "get_tenant_engine",
                return_value=self.engine,
            ),
            patch.object(
                routes_dsl,
                "_render_batch_worker_impl",
                side_effect=implementation,
            ),
            patch.object(routes_dsl, "PlannerReservationController") as controller,
            patch.object(rollout, "reservation_rollout_readiness") as lookup,
        ):
            terminal = dispatched.func(
                *dispatched.args,
                **dispatched.kwargs,
            )
        self.assertEqual(terminal["status"], "completed")
        controller.assert_not_called()
        lookup.assert_not_called()
        with self.Session() as session:
            task = session.scalar(
                select(VideoTask).where(VideoTask.task_id == task_id)
            )
            reservation_count = session.query(FingerprintReservation).count()
            diagnostic = session.scalar(
                select(ReservationRunDiagnostic).where(
                    ReservationRunDiagnostic.task_id == task_id
                )
            )
        self.assertEqual(task.reservation_conflict_mode, "OFF")
        self.assertEqual(task.status, "completed")
        self.assertEqual(reservation_count, 0)
        self.assertIsNone(diagnostic)

    def test_readiness_api_is_get_only_private_and_fails_safely(self):
        self._seed_ready()
        configuration = self._configuration()
        lease = ReservationLeaseConfiguration(0.9, 0.15)
        with (
            self.Session() as session,
            patch.object(
                diagnostics_routes,
                "load_reservation_rollout_readiness_configuration",
                return_value=configuration,
            ),
            patch.object(
                rollout,
                "load_reservation_lease_configuration",
                return_value=lease,
            ),
        ):
            response = get_reservation_rollout_readiness(
                planning_policy="exact_main_visual",
                db=session,
            )
        serialized = response.model_dump(by_alias=True, mode="json")
        self.assertEqual(
            serialized["state"],
            "READY_FOR_CONTROLLED_CANARY",
        )
        self.assertEqual(
            set(
                next(
                    route
                    for route in diagnostics_routes.router.routes
                    if route.path.endswith("/readiness")
                ).methods
            ),
            {"GET"},
        )
        signature = python_inspect.signature(
            get_reservation_rollout_readiness
        )
        self.assertEqual(
            set(signature.parameters),
            {"planning_policy", "db"},
        )
        forbidden = (
            "task_id",
            "owner_attempt",
            "execution_id",
            "fingerprint",
            "prompt",
            "sqlite",
            "select ",
            "reservation_rollout_readiness_window",
            "lease_timestamp",
        )
        lowered = json.dumps(serialized).lower()
        for token in forbidden:
            self.assertNotIn(token, lowered)

        db = Mock()
        with (
            patch.object(
                diagnostics_routes,
                "load_reservation_rollout_readiness_configuration",
                return_value=configuration,
            ),
            patch.object(
                diagnostics_routes,
                "reservation_rollout_readiness",
                side_effect=RuntimeError(
                    "sqlite:///private.db SELECT task_id"
                ),
            ),
            self.assertRaises(HTTPException) as caught,
        ):
            get_reservation_rollout_readiness(
                planning_policy="exact_main_visual",
                db=db,
            )
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(
            caught.exception.detail,
            RESERVATION_ROLLOUT_READINESS_UNAVAILABLE,
        )
        self.assertNotIn("private", str(caught.exception.detail).lower())


if __name__ == "__main__":
    unittest.main()
