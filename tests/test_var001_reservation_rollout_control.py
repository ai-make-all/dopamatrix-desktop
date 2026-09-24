import inspect as python_inspect
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.api import (
    database,
    reservation_rollout_control as control,
    routes_dsl,
    routes_reservation_diagnostics as diagnostics_routes,
)
from src.api.database import initialize_application_schema
from src.api.models import (
    ReservationRolloutBreaker,
    ReservationRunDiagnostic,
    VideoTask,
)
from src.api.public_task_admission import (
    PublicTaskAdmissionError,
    PublicTaskReservationModeDecision,
    admit_public_task,
    transition_public_task_status,
)
from src.api.reservation_lease import ReservationLeaseConfiguration
from src.api.reservation_rollout_control import (
    RESERVATION_ROLLOUT_CONTROL_CONFIGURATION_INVALID,
    ReservationRolloutControlConfiguration,
    ReservationRolloutControlConfigurationError,
    deterministic_rollout_bucket,
    load_reservation_rollout_control_configuration,
    reservation_rollout_status,
    resolve_omitted_reservation_mode,
)
from src.api.schemas import RenderDSLRequest
from tests.test_var001_clean_task_identity import _beat, _plan


_VALID_CONTROL_ENVIRONMENT = {
    "RESERVATION_ROLLOUT_CONTROL_ENABLED": "true",
    "RESERVATION_ROLLOUT_GENERATION": "canary-g1",
    "RESERVATION_ROLLOUT_TENANT_ALLOWLIST": "tenant-a,tenant-b",
    "RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS": "1000",
    "RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS": "0",
    "RESERVATION_ROLLOUT_ASSIGNMENT_SECRET": "backend-only-test-secret",
    "RESERVATION_ROLLOUT_KILL_SWITCH": "false",
    "RESERVATION_ROLLOUT_ROLLBACK_WINDOW": "24h",
    "RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS": "2",
    "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_DIAGNOSTIC_COVERAGE_RATE": "0.9",
    "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_PLANNING_COVERAGE_RATE": "0.9",
    "RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_TERMINAL_COVERAGE_RATE": "0.9",
    "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE": "0.1",
    "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE": "0.1",
    "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE": "0.1",
    "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE": "0.1",
    "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE": "0.1",
    "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE": "0.1",
}


class _Background:
    def __init__(self):
        self.tasks = []

    def add_task(self, function, *args, **kwargs):
        self.tasks.append(
            SimpleNamespace(func=function, args=args, kwargs=kwargs)
        )


class ReservationRolloutControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.engines = []
        self.now = datetime.now(timezone.utc)
        self.engine, self.Session = self._database("tenant-a.db")
        self.lease = ReservationLeaseConfiguration(30, 5)

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
        self.engines.append(engine)
        return engine, sessionmaker(bind=engine, expire_on_commit=False)

    def _weak_rollout_database(self, name):
        """Build the additive pre-2G path whose generation column has no CHECK."""
        path = Path(self.temporary.name) / name
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE video_tasks ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "task_id VARCHAR(64) NOT NULL, "
                "prompt TEXT NOT NULL, "
                "batch_size INTEGER NOT NULL DEFAULT 1, "
                "status VARCHAR(20) NOT NULL DEFAULT 'queued', "
                "reservation_conflict_mode TEXT NOT NULL DEFAULT 'OFF', "
                "planning_policy TEXT NOT NULL DEFAULT 'legacy', "
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
            connection.commit()
        finally:
            connection.close()
        engine = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        self.engines.append(engine)
        initialize_application_schema(engine)
        return engine, sessionmaker(bind=engine, expire_on_commit=False)

    def _insert_direct_canary(self, engine, *, task_id, generation):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO video_tasks ("
                    "task_id, prompt, batch_size, status, "
                    "reservation_conflict_mode, planning_policy, "
                    "reservation_mode_source, rollout_generation, "
                    "rollout_bucket, rollout_canary_basis_points, created_at"
                    ") VALUES ("
                    ":task_id, 'direct canary', 1, 'queued', "
                    "'ENFORCE', 'exact_main_visual', 'ROLLOUT_CANARY', "
                    ":generation, 0, 10000, :created_at)"
                ),
                {
                    "task_id": task_id,
                    "generation": generation,
                    "created_at": self.now,
                },
            )

    def _configuration(self, **overrides):
        values = {
            "enabled": True,
            "rollout_generation": "canary-g1",
            "tenant_allowlist": frozenset({"tenant-a"}),
            "exact_main_visual_canary_basis_points": 10000,
            "exact_main_visual_balanced_canary_basis_points": 0,
            "assignment_secret": "backend-only-test-secret",
            "kill_switch": False,
            "rollback_evaluation_window": "24h",
            "minimum_canary_task_count": 2,
            "minimum_diagnostic_run_coverage_rate": 0,
            "minimum_planning_observation_coverage_rate": 0,
            "minimum_terminal_observation_coverage_rate": 0,
            "maximum_zero_plan_conflict_rate": 1,
            "maximum_partial_plan_rate": 1,
            "maximum_authority_loss_rate": 1,
            "maximum_terminal_persist_failure_rate": 1,
            "maximum_worker_lease_config_failure_rate": 1,
            "maximum_cleanup_warning_rate": 1,
        }
        values.update(overrides)
        return ReservationRolloutControlConfiguration(**values)

    @contextmanager
    def _control(
        self,
        configuration,
        *,
        readiness_state="READY_FOR_CONTROLLED_CANARY",
        lease=None,
    ):
        with (
            patch.object(
                control,
                "load_reservation_rollout_control_configuration",
                return_value=configuration,
            ),
            patch.object(
                control,
                "reservation_rollout_readiness",
                return_value={"state": readiness_state},
            ),
            patch.object(
                control,
                "load_reservation_lease_configuration",
                return_value=self.lease if lease is None else lease,
            ),
        ):
            yield

    def _payload(self, **overrides):
        values = {
            "engine_type": "content",
            "timeline": [_beat()],
            "prompt": "controlled canary",
            "variant_planning_policy": "exact_main_visual",
        }
        values.update(overrides)
        return RenderDSLRequest(**values)

    def _admit_payload(
        self,
        payload,
        *,
        tenant_id="tenant-a",
        Session=None,
    ):
        SessionLocal = Session or self.Session
        with SessionLocal() as session:
            session.info["tenant_id"] = tenant_id
            return routes_dsl._admit_dsl_public_task_admission(
                session,
                payload,
                tenant_id=tenant_id,
            )

    def _admit_canary(
        self,
        *,
        engine=None,
        Session=None,
        policy="exact_main_visual",
        generation="canary-g1",
        status="completed",
        created_at=None,
    ):
        tenant_engine = engine or self.engine
        SessionLocal = Session or self.Session
        admission = admit_public_task(
            tenant_engine,
            prompt="canary evidence",
            batch_size=1,
            reservation_conflict_mode="ENFORCE",
            planning_policy=policy,
            reservation_mode_source="ROLLOUT_CANARY",
            rollout_generation=generation,
            rollout_bucket=0,
            rollout_canary_basis_points=10000,
        )
        with SessionLocal() as session:
            session.execute(
                update(VideoTask)
                .where(VideoTask.task_id == admission.task_id)
                .values(
                    status=status,
                    created_at=created_at
                    or self.now - timedelta(minutes=5),
                    finished_at=(
                        self.now
                        if status in {"completed", "failed"}
                        else None
                    ),
                )
            )
            session.commit()
        return admission.task_id

    def _admit_explicit(
        self,
        *,
        engine=None,
        Session=None,
        policy="exact_main_visual",
        status="completed",
    ):
        tenant_engine = engine or self.engine
        SessionLocal = Session or self.Session
        admission = admit_public_task(
            tenant_engine,
            prompt="explicit evidence",
            batch_size=1,
            reservation_conflict_mode="ENFORCE",
            planning_policy=policy,
            reservation_mode_source="EXPLICIT_ENFORCE",
        )
        with SessionLocal() as session:
            session.execute(
                update(VideoTask)
                .where(VideoTask.task_id == admission.task_id)
                .values(
                    status=status,
                    created_at=self.now - timedelta(minutes=5),
                    finished_at=self.now,
                )
            )
            session.commit()
        return admission.task_id

    def _diagnostic(
        self,
        task_id,
        *,
        Session=None,
        planning=True,
        terminal_status="completed",
        zero_plan=False,
        partial_plan=False,
        authority_lost=False,
        terminal_persist_failed=False,
        worker_lease_config_failed=False,
        cleanup_warning=False,
    ):
        SessionLocal = Session or self.Session
        with SessionLocal() as session:
            session.add(
                ReservationRunDiagnostic(
                    task_id=task_id,
                    planning_policy="exact_main_visual",
                    requested_count=2 if partial_plan else 1,
                    planning_observed=planning,
                    planned_count=(
                        None
                        if not planning
                        else 0 if zero_plan else 1
                    ),
                    succeeded_count=0,
                    failed_count=0,
                    reservation_conflict_count=0,
                    had_reservation_conflict=False,
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

    def _breaker(self, Session=None, generation="canary-g1"):
        SessionLocal = Session or self.Session
        with SessionLocal() as session:
            return session.scalar(
                select(ReservationRolloutBreaker).where(
                    ReservationRolloutBreaker.planning_policy
                    == "exact_main_visual",
                    ReservationRolloutBreaker.rollout_generation
                    == generation,
                )
            )

    def test_backend_configuration_is_all_or_none_without_numeric_defaults(self):
        self.assertIsNone(load_reservation_rollout_control_configuration({}))
        loaded = load_reservation_rollout_control_configuration(
            _VALID_CONTROL_ENVIRONMENT
        )
        self.assertTrue(loaded.enabled)
        self.assertEqual(loaded.rollout_generation, "canary-g1")
        self.assertEqual(
            loaded.tenant_allowlist,
            frozenset({"tenant-a", "tenant-b"}),
        )
        self.assertEqual(loaded.canary_basis_points("exact_main_visual"), 1000)
        self.assertEqual(
            loaded.canary_basis_points("exact_main_visual_balanced"),
            0,
        )
        self.assertNotIn(
            "backend-only-test-secret",
            repr(loaded),
        )
        for window in ("1h", "24h", "7d"):
            environment = dict(_VALID_CONTROL_ENVIRONMENT)
            environment["RESERVATION_ROLLOUT_ROLLBACK_WINDOW"] = window
            self.assertEqual(
                load_reservation_rollout_control_configuration(
                    environment
                ).rollback_evaluation_window,
                window,
            )

        invalid_environments = [
            {"RESERVATION_ROLLOUT_CONTROL_ENABLED": "true"}
        ]
        for key, value in (
            ("RESERVATION_ROLLOUT_CONTROL_ENABLED", "yes"),
            ("RESERVATION_ROLLOUT_GENERATION", "../secret"),
            ("RESERVATION_ROLLOUT_TENANT_ALLOWLIST", "tenant a"),
            ("RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS", "10001"),
            ("RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS", "-1"),
            ("RESERVATION_ROLLOUT_ASSIGNMENT_SECRET", ""),
            ("RESERVATION_ROLLOUT_ROLLBACK_WINDOW", "30d"),
            ("RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS", "0"),
            (
                "RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE",
                "NaN",
            ),
        ):
            invalid = dict(_VALID_CONTROL_ENVIRONMENT)
            invalid[key] = value
            invalid_environments.append(invalid)
        for environment in invalid_environments:
            with self.subTest(environment=environment), self.assertRaises(
                ReservationRolloutControlConfigurationError
            ) as caught:
                load_reservation_rollout_control_configuration(environment)
            self.assertEqual(
                str(caught.exception),
                RESERVATION_ROLLOUT_CONTROL_CONFIGURATION_INVALID,
            )

    def test_clients_have_no_rollout_controls(self):
        request_fields = RenderDSLRequest.model_fields
        for field in (
            "rollout_generation",
            "canary_basis_points",
            "assignment_secret",
            "rollout_bucket",
            "breaker_reset",
            "rollout_kill_switch",
        ):
            self.assertNotIn(field, request_fields)
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self._payload(**{field: "client-value"})
        with self.assertRaises(ValidationError):
            self._payload(reservation_conflict_mode="AUTO")

    def test_omission_and_explicit_off_are_distinct_and_only_omission_promotes(self):
        omitted = self._payload()
        explicit_off = self._payload(reservation_conflict_mode="OFF")
        self.assertNotIn(
            "reservation_conflict_mode",
            omitted.model_fields_set,
        )
        self.assertIn(
            "reservation_conflict_mode",
            explicit_off.model_fields_set,
        )
        configuration = self._configuration()
        with self._control(configuration):
            omitted_admission = self._admit_payload(omitted)
        with patch.object(
            routes_dsl,
            "resolve_omitted_reservation_mode",
            side_effect=AssertionError("explicit OFF entered rollout"),
        ):
            explicit_admission = self._admit_payload(explicit_off)

        self.assertEqual(
            (
                omitted_admission.reservation_conflict_mode,
                omitted_admission.reservation_mode_source,
            ),
            ("ENFORCE", "ROLLOUT_CANARY"),
        )
        self.assertEqual(
            (
                explicit_admission.reservation_conflict_mode,
                explicit_admission.reservation_mode_source,
                explicit_admission.rollout_generation,
                explicit_admission.rollout_bucket,
            ),
            ("OFF", "EXPLICIT_OFF", None, None),
        )

    def test_fastapi_request_parsing_preserves_omission_explicitness(self):
        app = FastAPI()
        app.include_router(routes_dsl.router, prefix="/api/v1")

        def override_db():
            with self.Session() as session:
                session.info["tenant_id"] = "tenant-a"
                yield session

        app.dependency_overrides[database.get_db] = override_db
        client = TestClient(app)
        omitted_body = self._payload().model_dump(
            mode="json",
            exclude_unset=True,
        )
        explicit_body = self._payload(
            reservation_conflict_mode="OFF"
        ).model_dump(mode="json", exclude_unset=True)
        parser = Mock()
        parser.parse_and_resolve.return_value = _plan()
        with (
            self._control(self._configuration()),
            patch.object(routes_dsl, "DSLParserNode", return_value=parser),
            patch.object(routes_dsl, "_dispatch_claimed_public_task"),
        ):
            omitted_response = client.post(
                "/api/v1/tasks/submit-dsl",
                json=omitted_body,
                headers={"X-Local-User": "tenant-a"},
            )
            explicit_response = client.post(
                "/api/v1/tasks/submit-dsl",
                json=explicit_body,
                headers={"X-Local-User": "tenant-a"},
            )
            with patch.object(
                control,
                "_find_breaker",
                side_effect=RuntimeError("private rollout query failure"),
            ):
                failed_control_response = client.post(
                    "/api/v1/tasks/submit-dsl",
                    json=omitted_body,
                    headers={"X-Local-User": "tenant-a"},
                )
        self.assertEqual(omitted_response.status_code, 202)
        self.assertEqual(explicit_response.status_code, 202)
        self.assertEqual(failed_control_response.status_code, 202)
        with self.Session() as session:
            omitted_task = session.scalar(
                select(VideoTask).where(
                    VideoTask.task_id
                    == omitted_response.json()["task_id"]
                )
            )
            explicit_task = session.scalar(
                select(VideoTask).where(
                    VideoTask.task_id
                    == explicit_response.json()["task_id"]
                )
            )
            failed_control_task = session.scalar(
                select(VideoTask).where(
                    VideoTask.task_id
                    == failed_control_response.json()["task_id"]
                )
            )
        self.assertEqual(
            omitted_task.reservation_mode_source,
            "ROLLOUT_CANARY",
        )
        self.assertEqual(
            explicit_task.reservation_mode_source,
            "EXPLICIT_OFF",
        )
        self.assertEqual(
            (
                failed_control_task.reservation_conflict_mode,
                failed_control_task.reservation_mode_source,
            ),
            ("OFF", "DEFAULT_OFF"),
        )

    def test_explicit_enforce_preserves_b2_and_bypasses_rollout(self):
        explicit = self._payload(reservation_conflict_mode="ENFORCE")
        killed = self._configuration(kill_switch=True)
        with (
            self._control(killed),
            patch.object(
                routes_dsl,
                "resolve_omitted_reservation_mode",
                side_effect=AssertionError("explicit ENFORCE entered rollout"),
            ),
        ):
            admission = self._admit_payload(explicit)
        self.assertEqual(admission.reservation_conflict_mode, "ENFORCE")
        self.assertEqual(
            admission.reservation_mode_source,
            "EXPLICIT_ENFORCE",
        )

        with patch.object(
            routes_dsl,
            "load_reservation_lease_configuration",
            return_value=ReservationLeaseConfiguration(),
        ), self.assertRaises(HTTPException) as caught:
            routes_dsl._preflight_public_reservation_policy(explicit)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(
            caught.exception.detail,
            "RESERVATION_LEASE_CONFIGURATION_REQUIRED",
        )

    def test_tenant_policy_allowlists_and_kill_switch(self):
        configuration = self._configuration(
            tenant_allowlist=frozenset({"tenant-a"}),
            exact_main_visual_canary_basis_points=10000,
            exact_main_visual_balanced_canary_basis_points=0,
        )
        with self._control(configuration):
            tenant_a = self._admit_payload(self._payload())
            tenant_b = self._admit_payload(
                self._payload(),
                tenant_id="tenant-b",
            )
            balanced = self._admit_payload(
                self._payload(
                    variant_planning_policy=(
                        "exact_main_visual_balanced"
                    )
                )
            )
            legacy = self._admit_payload(
                self._payload(variant_planning_policy="legacy")
            )
        self.assertEqual(tenant_a.reservation_mode_source, "ROLLOUT_CANARY")
        for admission in (tenant_b, balanced, legacy):
            self.assertEqual(admission.reservation_conflict_mode, "OFF")
            self.assertEqual(admission.reservation_mode_source, "DEFAULT_OFF")

        killed = self._configuration(kill_switch=True)
        with self._control(killed):
            omitted = self._admit_payload(self._payload())
        self.assertEqual(omitted.reservation_conflict_mode, "OFF")
        self.assertEqual(omitted.reservation_mode_source, "DEFAULT_OFF")

    def test_initial_not_ready_does_not_latch_and_same_generation_can_start(self):
        configuration = self._configuration()
        with (
            self._control(
                configuration,
                readiness_state="INSUFFICIENT_EVIDENCE",
            ),
            patch.object(
                control,
                "deterministic_rollout_bucket",
            ) as assignment,
        ):
            blocked = self._admit_payload(self._payload())
        self.assertEqual(blocked.reservation_conflict_mode, "OFF")
        assignment.assert_not_called()
        self.assertIsNone(self._breaker())

        with self._control(configuration):
            started = self._admit_payload(self._payload())
        self.assertEqual(started.reservation_mode_source, "ROLLOUT_CANARY")
        self.assertIsNone(self._breaker())

    def test_deterministic_bucket_is_stable_and_exact(self):
        inputs = {
            "assignment_secret": "known-secret",
            "canonical_tenant": "tenant-a",
            "planning_policy": "exact_main_visual",
            "task_id": "00000000-0000-4000-8000-000000000123",
            "rollout_generation": "generation-7",
        }
        first = deterministic_rollout_bucket(**inputs)
        self.assertEqual(first, 1190)
        for _ in range(10):
            self.assertEqual(
                deterministic_rollout_bucket(**inputs),
                first,
            )
        root = Path(__file__).resolve().parents[1]
        script = (
            "from src.api.reservation_rollout_control import "
            "deterministic_rollout_bucket as bucket;"
            "print(bucket("
            "assignment_secret='known-secret',"
            "canonical_tenant='tenant-a',"
            "planning_policy='exact_main_visual',"
            "task_id='00000000-0000-4000-8000-000000000123',"
            "rollout_generation='generation-7'))"
        )
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = "random"
        cross_process = subprocess.check_output(
            [sys.executable, "-c", script],
            cwd=root,
            env=environment,
            text=True,
        ).strip()
        self.assertEqual(cross_process, "1190")
        self.assertNotIn("hash(", python_inspect.getsource(
            deterministic_rollout_bucket
        ))

    def test_basis_point_boundaries_use_exact_bucket_rule(self):
        zero = self._configuration(
            exact_main_visual_canary_basis_points=0
        )
        with (
            self._control(zero),
            patch.object(
                control,
                "deterministic_rollout_bucket",
            ) as assignment,
        ):
            decision = resolve_omitted_reservation_mode(
                self.engine,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                task_id=str(uuid.uuid4()),
            )
        self.assertEqual(decision.reservation_conflict_mode, "OFF")
        assignment.assert_not_called()

        full = self._configuration(
            exact_main_visual_canary_basis_points=10000
        )
        with (
            self._control(full),
            patch.object(
                control,
                "deterministic_rollout_bucket",
                return_value=9999,
            ),
        ):
            selected = resolve_omitted_reservation_mode(
                self.engine,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                task_id=str(uuid.uuid4()),
            )
        self.assertEqual(selected.reservation_mode_source, "ROLLOUT_CANARY")

        intermediate = self._configuration(
            exact_main_visual_canary_basis_points=1000
        )
        for bucket, expected in ((999, "ROLLOUT_CANARY"), (1000, "DEFAULT_OFF")):
            with (
                self.subTest(bucket=bucket),
                self._control(intermediate),
                patch.object(
                    control,
                    "deterministic_rollout_bucket",
                    return_value=bucket,
                ),
            ):
                decision = resolve_omitted_reservation_mode(
                    self.engine,
                    canonical_tenant="tenant-a",
                    planning_policy="exact_main_visual",
                    task_id=str(uuid.uuid4()),
                )
            self.assertEqual(decision.reservation_mode_source, expected)

    def test_atomic_metadata_and_uuid_collision_recompute_assignment(self):
        collision = "00000000-0000-4000-8000-000000000001"
        replacement = "00000000-0000-4000-8000-000000000002"
        admit_public_task(
            self.engine,
            prompt="existing",
            batch_size=1,
            task_id_factory=lambda: collision,
        )
        seen = []

        def resolver(task_id):
            seen.append(task_id)
            bucket = deterministic_rollout_bucket(
                assignment_secret="known-secret",
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                task_id=task_id,
                rollout_generation="canary-g1",
            )
            return PublicTaskReservationModeDecision(
                reservation_conflict_mode="ENFORCE",
                reservation_mode_source="ROLLOUT_CANARY",
                rollout_generation="canary-g1",
                rollout_bucket=bucket,
                rollout_canary_basis_points=10000,
            )

        generated = iter((collision, replacement))
        admission = admit_public_task(
            self.engine,
            prompt="replacement",
            batch_size=1,
            reservation_conflict_mode="OFF",
            planning_policy="exact_main_visual",
            reservation_mode_source="DEFAULT_OFF",
            reservation_mode_resolver=resolver,
            task_id_factory=lambda: next(generated),
        )
        self.assertEqual(seen, [collision, replacement])
        self.assertEqual(admission.task_id, replacement)
        expected_bucket = deterministic_rollout_bucket(
            assignment_secret="known-secret",
            canonical_tenant="tenant-a",
            planning_policy="exact_main_visual",
            task_id=replacement,
            rollout_generation="canary-g1",
        )
        with self.Session() as session:
            existing = session.scalar(
                select(VideoTask).where(VideoTask.task_id == collision)
            )
            persisted = session.scalar(
                select(VideoTask).where(VideoTask.task_id == replacement)
            )
            count = session.query(VideoTask).count()
        self.assertEqual(count, 2)
        self.assertEqual(existing.reservation_mode_source, "DEFAULT_OFF")
        self.assertEqual(
            (
                persisted.status,
                persisted.reservation_conflict_mode,
                persisted.planning_policy,
                persisted.reservation_mode_source,
                persisted.rollout_generation,
                persisted.rollout_bucket,
                persisted.rollout_canary_basis_points,
            ),
            (
                "queued",
                "ENFORCE",
                "exact_main_visual",
                "ROLLOUT_CANARY",
                "canary-g1",
                expected_bucket,
                10000,
            ),
        )

    def test_inconsistent_rollout_metadata_is_rejected_before_insert(self):
        invalid = (
            {
                "reservation_conflict_mode": "ENFORCE",
                "reservation_mode_source": "ROLLOUT_CANARY",
            },
            {
                "reservation_conflict_mode": "OFF",
                "reservation_mode_source": "EXPLICIT_OFF",
                "rollout_generation": "canary-g1",
            },
            {
                "reservation_conflict_mode": "OFF",
                "reservation_mode_source": "EXPLICIT_ENFORCE",
            },
        )
        for metadata in invalid:
            with self.subTest(metadata=metadata), self.assertRaises(
                PublicTaskAdmissionError
            ):
                admit_public_task(
                    self.engine,
                    prompt="invalid rollout metadata",
                    batch_size=1,
                    planning_policy="exact_main_visual",
                    **metadata,
                )
        with self.Session() as session:
            self.assertEqual(session.query(VideoTask).count(), 0)

    def test_application_admission_accepts_complete_generation_domain(self):
        valid_generations = (
            "generation-1",
            "generation_1",
            "generation.1",
            "ABC_xyz-123",
        )
        for generation in valid_generations:
            with self.subTest(generation=generation):
                admission = admit_public_task(
                    self.engine,
                    prompt="valid generation",
                    batch_size=1,
                    reservation_conflict_mode="ENFORCE",
                    planning_policy="exact_main_visual",
                    reservation_mode_source="ROLLOUT_CANARY",
                    rollout_generation=generation,
                    rollout_bucket=0,
                    rollout_canary_basis_points=10000,
                )
                self.assertEqual(admission.rollout_generation, generation)
        with self.Session() as session:
            persisted = session.scalars(select(VideoTask)).all()
        self.assertEqual(
            [row.rollout_generation for row in persisted],
            list(valid_generations),
        )

    def test_application_admission_rejects_unsafe_generation_characters(self):
        invalid_generations = (
            "generation 1",
            "generation/1",
            "../generation",
            "generation:1",
            r"generation\1",
            "generation\n1",
            "generation\t1",
            "generation@1",
        )
        for generation in invalid_generations:
            with self.subTest(generation=repr(generation)), self.assertRaises(
                PublicTaskAdmissionError
            ):
                admit_public_task(
                    self.engine,
                    prompt="invalid generation",
                    batch_size=1,
                    reservation_conflict_mode="ENFORCE",
                    planning_policy="exact_main_visual",
                    reservation_mode_source="ROLLOUT_CANARY",
                    rollout_generation=generation,
                    rollout_bucket=0,
                    rollout_canary_basis_points=10000,
                )
        with self.Session() as session:
            self.assertEqual(session.query(VideoTask).count(), 0)

    def test_application_admission_rejects_overlong_generation(self):
        with self.assertRaises(PublicTaskAdmissionError):
            admit_public_task(
                self.engine,
                prompt="overlong generation",
                batch_size=1,
                reservation_conflict_mode="ENFORCE",
                planning_policy="exact_main_visual",
                reservation_mode_source="ROLLOUT_CANARY",
                rollout_generation="g" * 65,
                rollout_bucket=0,
                rollout_canary_basis_points=10000,
            )
        with self.Session() as session:
            self.assertEqual(session.query(VideoTask).count(), 0)

    def test_fresh_schema_enforces_complete_generation_domain(self):
        valid_generations = (
            "generation-1",
            "generation_1",
            "generation.1",
            "ABC_xyz-123",
        )
        invalid_generations = (
            "generation 1",
            "generation/1",
            "../generation",
            "generation:1",
            r"generation\1",
            "generation\n1",
            "generation\t1",
            "generation@1",
            "g" * 65,
        )
        for index, generation in enumerate(valid_generations):
            self._insert_direct_canary(
                self.engine,
                task_id=f"fresh-valid-generation-{index}",
                generation=generation,
            )
        for index, generation in enumerate(invalid_generations):
            with self.subTest(generation=repr(generation)), self.assertRaises(
                IntegrityError
            ):
                self._insert_direct_canary(
                    self.engine,
                    task_id=f"fresh-invalid-generation-{index}",
                    generation=generation,
                )
        with self.Session() as session:
            generations = session.scalars(
                select(VideoTask.rollout_generation)
            ).all()
        self.assertCountEqual(generations, valid_generations)

    def test_existing_database_startup_rejects_invalid_generation_domain(self):
        for name, generation in (
            ("existing-overlong.db", "g" * 65),
            ("existing-unsafe.db", "generation/1"),
        ):
            with self.subTest(generation=repr(generation)):
                engine, _Session = self._weak_rollout_database(name)
                self._insert_direct_canary(
                    engine,
                    task_id=f"invalid-{name}",
                    generation=generation,
                )
                with self.assertRaises(
                    database.TaskRolloutMetadataSchemaError
                ):
                    initialize_application_schema(engine)

    def test_existing_database_startup_accepts_valid_generation(self):
        engine, SessionLocal = self._weak_rollout_database(
            "existing-valid.db"
        )
        self._insert_direct_canary(
            engine,
            task_id="existing-valid-generation",
            generation="generation-7",
        )
        initialize_application_schema(engine)
        with SessionLocal() as session:
            row = session.scalar(
                select(VideoTask).where(
                    VideoTask.task_id == "existing-valid-generation"
                )
            )
        self.assertEqual(row.rollout_generation, "generation-7")

    def test_rollout_config_and_task_generation_contracts_are_aligned(self):
        valid_generations = (
            "generation-1",
            "generation_1",
            "generation.1",
            "ABC_xyz-123",
        )
        invalid_generations = (
            "",
            "generation 1",
            "generation/1",
            "../generation",
            "generation:1",
            r"generation\1",
            "generation\n1",
            "generation\t1",
            "generation@1",
            "g" * 65,
        )
        for generation in valid_generations:
            with self.subTest(valid=generation):
                configuration = self._configuration(
                    rollout_generation=generation
                )
                admission = admit_public_task(
                    self.engine,
                    prompt="aligned valid generation",
                    batch_size=1,
                    reservation_conflict_mode="ENFORCE",
                    planning_policy="exact_main_visual",
                    reservation_mode_source="ROLLOUT_CANARY",
                    rollout_generation=generation,
                    rollout_bucket=0,
                    rollout_canary_basis_points=10000,
                )
                self.assertEqual(
                    admission.rollout_generation,
                    configuration.rollout_generation,
                )
        for generation in invalid_generations:
            with self.subTest(invalid=repr(generation)):
                with self.assertRaises(
                    ReservationRolloutControlConfigurationError
                ):
                    self._configuration(rollout_generation=generation)
                with self.assertRaises(PublicTaskAdmissionError):
                    admit_public_task(
                        self.engine,
                        prompt="aligned invalid generation",
                        batch_size=1,
                        reservation_conflict_mode="ENFORCE",
                        planning_policy="exact_main_visual",
                        reservation_mode_source="ROLLOUT_CANARY",
                        rollout_generation=generation,
                        rollout_bucket=0,
                        rollout_canary_basis_points=10000,
                    )

    def test_additive_schema_backfills_pre2g_without_canary_fabrication(self):
        path = Path(self.temporary.name) / "pre-2g.db"
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE video_tasks ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "task_id VARCHAR(64) NOT NULL, "
                "prompt TEXT NOT NULL, "
                "batch_size INTEGER NOT NULL DEFAULT 1, "
                "status VARCHAR(20) NOT NULL DEFAULT 'queued', "
                "reservation_conflict_mode TEXT NOT NULL DEFAULT 'OFF', "
                "planning_policy TEXT NOT NULL DEFAULT 'legacy', "
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
            for task_id, mode, policy in (
                ("old-off", "OFF", "legacy"),
                ("old-enforce", "ENFORCE", "exact_main_visual"),
            ):
                connection.execute(
                    "INSERT INTO video_tasks "
                    "(task_id, prompt, batch_size, status, "
                    "reservation_conflict_mode, planning_policy, created_at) "
                    "VALUES (?, 'old', 1, 'completed', ?, ?, ?)",
                    (task_id, mode, policy, self.now.isoformat()),
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
        for name in (
            "reservation_mode_source",
            "rollout_generation",
            "rollout_bucket",
            "rollout_canary_basis_points",
        ):
            self.assertIn(name, columns)
        indexes = {
            tuple(index.get("column_names") or ())
            for index in inspector.get_indexes("video_tasks")
        }
        self.assertIn(
            (
                "reservation_mode_source",
                "planning_policy",
                "rollout_generation",
                "created_at",
            ),
            indexes,
        )
        self.assertIn(
            "reservation_rollout_breakers",
            inspector.get_table_names(),
        )
        SessionLocal = sessionmaker(bind=engine)
        with SessionLocal() as session:
            rows = {
                row.task_id: row
                for row in session.scalars(select(VideoTask)).all()
            }
        self.assertEqual(rows["old-off"].reservation_mode_source, "DEFAULT_OFF")
        self.assertEqual(
            rows["old-enforce"].reservation_mode_source,
            "EXPLICIT_ENFORCE",
        )
        for row in rows.values():
            self.assertIsNone(row.rollout_generation)
            self.assertIsNone(row.rollout_bucket)

    def test_route_dispatches_effective_canary_mode_after_atomic_admission(self):
        payload = self._payload()
        background = _Background()
        parser = Mock()
        parser.parse_and_resolve.return_value = _plan()
        request = Mock(headers={"X-Local-User": "tenant-a"})
        with (
            self._control(self._configuration()),
            self.Session() as session,
            patch.object(routes_dsl, "DSLParserNode", return_value=parser),
        ):
            response = routes_dsl.submit_dsl(
                payload,
                background,
                db=session,
                request=request,
            )
        self.assertEqual(len(background.tasks), 1)
        self.assertEqual(
            background.tasks[0].kwargs["reservation_conflict_mode"],
            "ENFORCE",
        )
        with self.Session() as session:
            task = session.scalar(
                select(VideoTask).where(
                    VideoTask.task_id == response.task_id
                )
            )
        self.assertEqual(task.status, "queued")
        self.assertEqual(task.reservation_mode_source, "ROLLOUT_CANARY")
        self.assertEqual(task.reservation_conflict_mode, "ENFORCE")

    def test_quality_guards_trip_independently(self):
        for field, expected_reason in (
            ("zero_plan", "ZERO_PLAN_CONFLICT_RATE_EXCEEDED"),
            ("partial_plan", "PARTIAL_PLAN_RATE_EXCEEDED"),
        ):
            engine, SessionLocal = self._database(f"quality-{field}.db")
            task_id = self._admit_canary(
                engine=engine,
                Session=SessionLocal,
            )
            self._diagnostic(
                task_id,
                Session=SessionLocal,
                **{field: True},
            )
            configuration = self._configuration(
                minimum_diagnostic_run_coverage_rate=1,
                minimum_planning_observation_coverage_rate=1,
                minimum_terminal_observation_coverage_rate=1,
                maximum_zero_plan_conflict_rate=0,
                maximum_partial_plan_rate=0,
            )
            with self.subTest(field=field), self._control(configuration):
                decision = resolve_omitted_reservation_mode(
                    engine,
                    canonical_tenant="tenant-a",
                    planning_policy="exact_main_visual",
                    task_id=str(uuid.uuid4()),
                )
            self.assertEqual(decision.reservation_conflict_mode, "OFF")
            breaker = self._breaker(
                Session=SessionLocal,
                generation=configuration.rollout_generation,
            )
            self.assertEqual(breaker.reason_code, expected_reason)

    def test_safety_guards_trip_independently(self):
        cases = (
            ("authority_lost", "AUTHORITY_LOSS_RATE_EXCEEDED"),
            (
                "terminal_persist_failed",
                "TERMINAL_PERSIST_FAILURE_RATE_EXCEEDED",
            ),
            (
                "worker_lease_config_failed",
                "WORKER_LEASE_CONFIG_FAILURE_RATE_EXCEEDED",
            ),
            ("cleanup_warning", "CLEANUP_WARNING_RATE_EXCEEDED"),
        )
        for field, expected_reason in cases:
            engine, SessionLocal = self._database(f"safety-{field}.db")
            task_id = self._admit_canary(
                engine=engine,
                Session=SessionLocal,
            )
            self._diagnostic(
                task_id,
                Session=SessionLocal,
                **{field: True},
            )
            configuration = self._configuration(
                minimum_diagnostic_run_coverage_rate=1,
                minimum_planning_observation_coverage_rate=1,
                minimum_terminal_observation_coverage_rate=1,
                maximum_authority_loss_rate=0,
                maximum_terminal_persist_failure_rate=0,
                maximum_worker_lease_config_failure_rate=0,
                maximum_cleanup_warning_rate=0,
            )
            with self.subTest(field=field), self._control(configuration):
                decision = resolve_omitted_reservation_mode(
                    engine,
                    canonical_tenant="tenant-a",
                    planning_policy="exact_main_visual",
                    task_id=str(uuid.uuid4()),
                )
            self.assertEqual(decision.reservation_conflict_mode, "OFF")
            breaker = self._breaker(Session=SessionLocal)
            self.assertEqual(breaker.reason_code, expected_reason)

    def test_completeness_guards_trip_independently_during_warmup(self):
        cases = (
            (
                "diagnostic",
                "DIAGNOSTIC_RUN_COVERAGE_BELOW_MINIMUM",
            ),
            (
                "planning",
                "PLANNING_OBSERVATION_COVERAGE_BELOW_MINIMUM",
            ),
            (
                "terminal",
                "TERMINAL_OBSERVATION_COVERAGE_BELOW_MINIMUM",
            ),
        )
        for missing, expected_reason in cases:
            engine, SessionLocal = self._database(
                f"coverage-{missing}.db"
            )
            task_id = self._admit_canary(
                engine=engine,
                Session=SessionLocal,
            )
            if missing == "planning":
                self._diagnostic(
                    task_id,
                    Session=SessionLocal,
                    planning=False,
                )
            elif missing == "terminal":
                self._diagnostic(
                    task_id,
                    Session=SessionLocal,
                    terminal_status=None,
                )
            configuration = self._configuration(
                minimum_canary_task_count=10,
                minimum_diagnostic_run_coverage_rate=1,
                minimum_planning_observation_coverage_rate=1,
                minimum_terminal_observation_coverage_rate=1,
            )
            with self.subTest(missing=missing), self._control(configuration):
                decision = resolve_omitted_reservation_mode(
                    engine,
                    canonical_tenant="tenant-a",
                    planning_policy="exact_main_visual",
                    task_id=str(uuid.uuid4()),
                )
            self.assertEqual(decision.reservation_conflict_mode, "OFF")
            breaker = self._breaker(Session=SessionLocal)
            self.assertEqual(breaker.reason_code, expected_reason)

    def test_readiness_loss_after_canary_latches_breaker(self):
        task_id = self._admit_canary()
        self._diagnostic(task_id)
        configuration = self._configuration()
        with self._control(
            configuration,
            readiness_state="BLOCKED",
        ):
            decision = resolve_omitted_reservation_mode(
                self.engine,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                task_id=str(uuid.uuid4()),
            )
        self.assertEqual(decision.reservation_conflict_mode, "OFF")
        self.assertEqual(self._breaker().reason_code, "READINESS_LOST")

        old_engine, OldSession = self._database("old-canary-readiness.db")
        old_task = self._admit_canary(
            engine=old_engine,
            Session=OldSession,
            created_at=self.now - timedelta(days=2),
        )
        self._diagnostic(old_task, Session=OldSession)
        with self._control(
            configuration,
            readiness_state="BLOCKED",
        ):
            out_of_window = resolve_omitted_reservation_mode(
                old_engine,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                task_id=str(uuid.uuid4()),
            )
        self.assertEqual(out_of_window.reservation_conflict_mode, "OFF")
        self.assertEqual(
            self._breaker(Session=OldSession).reason_code,
            "READINESS_LOST",
        )

    def test_breaker_latches_survives_restart_and_generation_rearms(self):
        task_id = self._admit_canary()
        self._diagnostic(task_id, authority_lost=True)
        strict = self._configuration(maximum_authority_loss_rate=0)
        with self._control(strict):
            first = resolve_omitted_reservation_mode(
                self.engine,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                task_id=str(uuid.uuid4()),
            )
        self.assertEqual(first.reservation_conflict_mode, "OFF")
        self.assertIsNotNone(self._breaker())

        repaired = self._configuration(maximum_authority_loss_rate=1)
        with self._control(repaired):
            latched = resolve_omitted_reservation_mode(
                self.engine,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                task_id=str(uuid.uuid4()),
            )
        self.assertEqual(latched.reservation_conflict_mode, "OFF")

        path = self.engine.url.database
        self.engine.dispose()
        reopened = create_engine(
            f"sqlite:///{Path(path).as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        initialize_application_schema(reopened)
        self.engines.append(reopened)
        with self._control(repaired):
            after_restart = resolve_omitted_reservation_mode(
                reopened,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                task_id=str(uuid.uuid4()),
            )
        self.assertEqual(after_restart.reservation_conflict_mode, "OFF")

        generation_two = self._configuration(
            rollout_generation="canary-g2"
        )
        with self._control(generation_two):
            rearmed = resolve_omitted_reservation_mode(
                reopened,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                task_id=str(uuid.uuid4()),
            )
        self.assertEqual(rearmed.reservation_mode_source, "ROLLOUT_CANARY")
        ReopenedSession = sessionmaker(bind=reopened)
        with ReopenedSession() as session:
            generations = set(
                session.scalars(
                    select(ReservationRolloutBreaker.rollout_generation)
                ).all()
            )
        self.assertEqual(generations, {"canary-g1"})

    def test_breaker_write_and_control_query_failures_fail_safe_off(self):
        task_id = self._admit_canary()
        self._diagnostic(task_id, authority_lost=True)
        strict = self._configuration(maximum_authority_loss_rate=0)
        with (
            self._control(strict),
            patch.object(control, "_trip_breaker", return_value=False),
        ):
            write_failed = resolve_omitted_reservation_mode(
                self.engine,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                task_id=str(uuid.uuid4()),
            )
        self.assertEqual(write_failed.reservation_conflict_mode, "OFF")

        broken_session = Mock()
        broken_session.execute.side_effect = RuntimeError("write failed")
        self.assertFalse(
            control._trip_breaker(
                broken_session,
                planning_policy="exact_main_visual",
                rollout_generation="canary-g1",
                reason_code="READINESS_LOST",
            )
        )
        broken_session.rollback.assert_called_once()

        clean_engine, CleanSession = self._database("query-failure.db")
        with (
            self._control(self._configuration()),
            patch.object(
                control,
                "_find_breaker",
                side_effect=RuntimeError("private database detail"),
            ),
            patch.object(
                control.logger,
                "warning",
                side_effect=RuntimeError("logging unavailable"),
            ),
        ):
            query_failed = self._admit_payload(
                self._payload(),
                Session=CleanSession,
            )
        self.assertEqual(query_failed.reservation_conflict_mode, "OFF")

    def test_absent_invalid_or_unavailable_control_never_breaks_admission(self):
        for effect in (
            None,
            ReservationRolloutControlConfigurationError(),
        ):
            loader = (
                {"return_value": None}
                if effect is None
                else {"side_effect": effect}
            )
            with (
                self.subTest(effect=type(effect).__name__),
                patch.object(
                    control,
                    "load_reservation_rollout_control_configuration",
                    **loader,
                ),
            ):
                admission = self._admit_payload(self._payload())
            self.assertEqual(admission.reservation_conflict_mode, "OFF")
            self.assertEqual(admission.reservation_mode_source, "DEFAULT_OFF")
        with patch.object(
            routes_dsl,
            "resolve_omitted_reservation_mode",
            side_effect=RuntimeError("unexpected resolver failure"),
        ):
            admission = self._admit_payload(self._payload())
        self.assertEqual(admission.reservation_conflict_mode, "OFF")
        self.assertEqual(admission.reservation_mode_source, "DEFAULT_OFF")

    def test_canary_preflight_failure_falls_back_off_but_explicit_errors(self):
        unconfigured = ReservationLeaseConfiguration()
        with self._control(
            self._configuration(),
            lease=unconfigured,
        ):
            admission = self._admit_payload(self._payload())
        self.assertEqual(admission.reservation_conflict_mode, "OFF")
        self.assertEqual(admission.reservation_mode_source, "DEFAULT_OFF")

        explicit = self._payload(reservation_conflict_mode="ENFORCE")
        with patch.object(
            routes_dsl,
            "load_reservation_lease_configuration",
            return_value=unconfigured,
        ), self.assertRaises(HTTPException):
            routes_dsl._preflight_public_reservation_policy(explicit)

    def test_canary_cohort_excludes_explicit_enforce_and_other_generations(self):
        explicit = self._admit_explicit()
        self._diagnostic(explicit, authority_lost=True)
        old_generation = self._admit_canary(generation="canary-old")
        self._diagnostic(old_generation, authority_lost=True)
        outside_window = self._admit_canary(
            created_at=self.now - timedelta(days=2)
        )
        self._diagnostic(outside_window, authority_lost=True)
        balanced = self._admit_canary(
            policy="exact_main_visual_balanced"
        )
        current = self._admit_canary()
        self._diagnostic(current)
        configuration = self._configuration()
        with self.Session() as session:
            metrics = control._canary_metrics(
                session,
                planning_policy="exact_main_visual",
                configuration=configuration,
                now=self.now,
            )
        self.assertEqual(metrics["canaryTaskCount"], 1)
        self.assertEqual(metrics["authorityLossRate"], 0)
        self.assertNotEqual(balanced, current)

    def test_breaker_trip_is_idempotent_under_concurrency(self):
        def trip():
            with self.Session() as session:
                return control._trip_breaker(
                    session,
                    planning_policy="exact_main_visual",
                    rollout_generation="canary-g1",
                    reason_code="READINESS_LOST",
                )

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: trip(), range(8)))
        self.assertEqual(results, [True] * 8)
        with self.Session() as session:
            rows = session.scalars(
                select(ReservationRolloutBreaker)
            ).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].reason_code, "READINESS_LOST")

    def test_canary_failure_and_breaker_do_not_mutate_or_cancel_admitted_task(self):
        task_id = self._admit_canary(status="queued")
        transition_public_task_status(
            self.engine,
            task_id=task_id,
            target_status="processing",
        )
        with self.Session() as session:
            session.add(
                ReservationRolloutBreaker(
                    planning_policy="exact_main_visual",
                    rollout_generation="canary-g1",
                    reason_code="AUTHORITY_LOSS_RATE_EXCEEDED",
                )
            )
            session.commit()
        with self._control(self._configuration()):
            future = resolve_omitted_reservation_mode(
                self.engine,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                task_id=str(uuid.uuid4()),
            )
        self.assertEqual(future.reservation_conflict_mode, "OFF")
        with self.Session() as session:
            running = session.scalar(
                select(VideoTask).where(VideoTask.task_id == task_id)
            )
        self.assertEqual(
            (
                running.status,
                running.reservation_conflict_mode,
                running.reservation_mode_source,
            ),
            ("processing", "ENFORCE", "ROLLOUT_CANARY"),
        )

        transition_public_task_status(
            self.engine,
            task_id=task_id,
            target_status="failed",
        )
        with self.Session() as session:
            failed = session.scalar(
                select(VideoTask).where(VideoTask.task_id == task_id)
            )
        self.assertEqual(failed.reservation_conflict_mode, "ENFORCE")
        self.assertEqual(failed.reservation_mode_source, "ROLLOUT_CANARY")

    def test_breaker_is_tenant_local(self):
        engine_b, SessionB = self._database("tenant-b.db")
        with self.Session() as session:
            session.add(
                ReservationRolloutBreaker(
                    planning_policy="exact_main_visual",
                    rollout_generation="canary-g1",
                    reason_code="READINESS_LOST",
                )
            )
            session.commit()
        configuration = self._configuration(
            tenant_allowlist=frozenset({"tenant-a", "tenant-b"})
        )
        with self._control(configuration):
            tenant_a = resolve_omitted_reservation_mode(
                self.engine,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                task_id=str(uuid.uuid4()),
            )
            tenant_b = resolve_omitted_reservation_mode(
                engine_b,
                canonical_tenant="tenant-b",
                planning_policy="exact_main_visual",
                task_id=str(uuid.uuid4()),
            )
        self.assertEqual(tenant_a.reservation_conflict_mode, "OFF")
        self.assertEqual(tenant_b.reservation_mode_source, "ROLLOUT_CANARY")
        with SessionB() as session:
            self.assertEqual(
                session.query(ReservationRolloutBreaker).count(),
                0,
            )

    def test_tenant_canonicalization_matches_platform_file_identity(self):
        mixed = database.canonical_tenant_id("Tenant-A")
        lower = database.canonical_tenant_id("tenant-a")
        self.assertEqual(mixed, os.path.normcase("Tenant-A"))
        if os.path.normcase("Tenant-A") == os.path.normcase("tenant-a"):
            self.assertEqual(mixed, lower)

    def test_rollout_status_states_and_warmup(self):
        with self.Session() as session:
            disabled = reservation_rollout_status(
                session,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                configuration=None,
                now=self.now,
            )
        self.assertEqual(disabled["state"], "DISABLED")

        cases = (
            (
                self._configuration(enabled=False),
                "tenant-a",
                "DISABLED",
            ),
            (
                self._configuration(kill_switch=True),
                "tenant-a",
                "KILL_SWITCHED",
            ),
            (
                self._configuration(),
                "tenant-b",
                "NOT_ELIGIBLE",
            ),
        )
        for configuration, tenant, expected in cases:
            with (
                self.subTest(expected=expected),
                self._control(configuration),
                self.Session() as session,
            ):
                result = reservation_rollout_status(
                    session,
                    canonical_tenant=tenant,
                    planning_policy="exact_main_visual",
                    configuration=configuration,
                    now=self.now,
                )
            self.assertEqual(result["state"], expected)

        first = self._admit_canary()
        self._diagnostic(first)
        configuration = self._configuration(minimum_canary_task_count=2)
        with self._control(configuration), self.Session() as session:
            warming = reservation_rollout_status(
                session,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                configuration=configuration,
                now=self.now,
            )
        self.assertEqual(warming["state"], "WARMING_UP")

        second = self._admit_canary()
        self._diagnostic(second)
        with self._control(configuration), self.Session() as session:
            active = reservation_rollout_status(
                session,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                configuration=configuration,
                now=self.now,
            )
        self.assertEqual(active["state"], "CANARY_ACTIVE")

        with self.Session() as session:
            session.add(
                ReservationRolloutBreaker(
                    planning_policy="exact_main_visual",
                    rollout_generation="canary-g1",
                    reason_code="READINESS_LOST",
                )
            )
            session.commit()
        with self._control(configuration), self.Session() as session:
            rolled_back = reservation_rollout_status(
                session,
                canonical_tenant="tenant-a",
                planning_policy="exact_main_visual",
                configuration=configuration,
                now=self.now,
            )
        self.assertEqual(rolled_back["state"], "AUTO_ROLLED_BACK")
        self.assertTrue(rolled_back["breakerTripped"])

    def test_rollout_status_api_is_get_only_tenant_scoped_and_private(self):
        configuration = self._configuration(
            assignment_secret="must-never-appear"
        )
        app = FastAPI()
        app.include_router(
            diagnostics_routes.router,
            prefix="/api/v1",
        )

        def override_db():
            with self.Session() as session:
                session.info["tenant_id"] = "tenant-a"
                yield session

        app.dependency_overrides[database.get_db] = override_db
        client = TestClient(app)
        with (
            patch.object(
                diagnostics_routes,
                "load_reservation_rollout_control_configuration",
                return_value=configuration,
            ),
            patch.object(
                control,
                "reservation_rollout_readiness",
                return_value={"state": "READY_FOR_CONTROLLED_CANARY"},
            ),
        ):
            response = client.get(
                "/api/v1/diagnostics/reservation/rollout-status",
                params={"planning_policy": "exact_main_visual"},
                headers={"X-Local-User": "tenant-a"},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "WARMING_UP")
        self.assertEqual(body["rolloutGeneration"], "canary-g1")
        serialized = json.dumps(body)
        for forbidden in (
            "must-never-appear",
            "task_id",
            "owner_attempt",
            "execution_id",
            "fingerprint",
            "sqlite",
            "SELECT ",
            "assignment",
            "digest",
            "bucket",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(
            client.get(
                "/api/v1/diagnostics/reservation/rollout-status"
            ).status_code,
            422,
        )
        self.assertEqual(
            client.post(
                "/api/v1/diagnostics/reservation/rollout-status",
                params={"planning_policy": "exact_main_visual"},
            ).status_code,
            405,
        )
        with patch.object(
            diagnostics_routes,
            "load_reservation_rollout_control_configuration",
            side_effect=ReservationRolloutControlConfigurationError(),
        ):
            invalid = client.get(
                "/api/v1/diagnostics/reservation/rollout-status",
                params={"planning_policy": "exact_main_visual"},
            )
        self.assertEqual(invalid.status_code, 503)
        self.assertEqual(
            invalid.json()["detail"],
            RESERVATION_ROLLOUT_CONTROL_CONFIGURATION_INVALID,
        )
        with self.Session() as session:
            self.assertEqual(
                session.query(ReservationRolloutBreaker).count(),
                0,
            )

    def test_no_automatic_ramp_up_or_rollout_authority_coupling(self):
        configuration = self._configuration(
            exact_main_visual_canary_basis_points=1000
        )
        with (
            self._control(configuration),
            patch.object(
                control,
                "deterministic_rollout_bucket",
                return_value=0,
            ),
        ):
            decisions = [
                resolve_omitted_reservation_mode(
                    self.engine,
                    canonical_tenant="tenant-a",
                    planning_policy="exact_main_visual",
                    task_id=str(uuid.uuid4()),
                )
                for _ in range(20)
            ]
        self.assertTrue(
            all(
                decision.rollout_canary_basis_points == 1000
                for decision in decisions
            )
        )
        self.assertEqual(
            configuration.exact_main_visual_canary_basis_points,
            1000,
        )

        root = Path(__file__).resolve().parents[1] / "src" / "api"
        authority_files = (
            "planner_reservation.py",
            "fingerprint_ledger.py",
            "reservation_lease.py",
        )
        forbidden = (
            "reservation_rollout_control",
            "reservation_mode_source",
            "rollout_generation",
            "rollout_bucket",
            "rollout_canary_basis_points",
            "ReservationRolloutBreaker",
        )
        for name in authority_files:
            source = (root / name).read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, source, (name, token))

        readiness_importers = []
        for path in root.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "reservation_rollout_readiness import" in source:
                readiness_importers.append(path.name)
        self.assertEqual(
            set(readiness_importers),
            {
                "operator_seed.py",
                "policy_profiles.py",
                "reservation_rollout_control.py",
                "routes_reservation_diagnostics.py",
            },
        )


if __name__ == "__main__":
    unittest.main()
