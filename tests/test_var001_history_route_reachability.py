from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import routes as task_routes
from src.api.routes_history import tasks_router as tasks_today_router
from src.api.database import get_db
from src.api.models import Base, TaskHistory, VideoTask


class HistoryRouteReachabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._engines = {
            tenant_id: create_engine(
                "sqlite://",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            for tenant_id in ("route-tenant-a", "route-tenant-b")
        }
        cls._sessions = {
            tenant_id: sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=engine,
            )
            for tenant_id, engine in cls._engines.items()
        }
        for engine in cls._engines.values():
            Base.metadata.create_all(bind=engine)

        with cls._sessions["route-tenant-a"]() as db:
            history = TaskHistory(
                task_id="today-route-target",
                prompt="route reachability",
                batch_size=4,
                duration=12.5,
                output_assets=[],
                prompt_details=None,
                created_at=datetime.now(timezone.utc),
            )
            task = VideoTask(
                session_id="integer-route-target",
                prompt="dynamic route control",
                batch_size=1,
                status="completed",
            )
            db.add_all([history, task])
            db.commit()
            db.refresh(task)
            cls._integer_task_id = task.id

        def override_get_db(request: Request):
            tenant_id = request.headers.get("X-Local-User", "default")
            session_factory = cls._sessions.get(tenant_id)
            if session_factory is None:
                session_factory = cls._sessions["route-tenant-b"]
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

        cls.app = FastAPI()
        cls.app.include_router(tasks_today_router, prefix="/api/v1")
        cls.app.include_router(task_routes.router, prefix="/api/v1")
        cls.app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls.app.dependency_overrides.pop(get_db, None)
        for engine in cls._engines.values():
            engine.dispose()

    def test_today_static_route_is_reachable_and_tenant_scoped(self) -> None:
        response = self.client.get(
            "/api/v1/tasks/today",
            headers={"X-Local-User": "route-tenant-a"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("int_parsing", response.text)
        records = response.json()
        self.assertEqual([record["task_id"] for record in records], ["today-route-target"])

        isolated_response = self.client.get(
            "/api/v1/tasks/today",
            headers={"X-Local-User": "route-tenant-b"},
        )
        self.assertEqual(isolated_response.status_code, 200, isolated_response.text)
        self.assertEqual(isolated_response.json(), [])

    def test_production_registers_today_before_dynamic_task_route(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        today_registration = (
            'app.include_router(tasks_today_router, prefix="/api/v1")'
        )
        dynamic_registration = (
            'app.include_router(task_routes.router, prefix="/api/v1")'
        )

        self.assertLess(
            source.index(today_registration),
            source.index(dynamic_registration),
        )

    def test_integer_task_route_remains_reachable(self) -> None:
        response = self.client.get(
            f"/api/v1/tasks/{self._integer_task_id}",
            headers={"X-Local-User": "route-tenant-a"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], self._integer_task_id)
        self.assertEqual(response.json()["session_id"], "integer-route-target")


if __name__ == "__main__":
    unittest.main()
