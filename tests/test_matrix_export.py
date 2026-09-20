import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import routes_matrix
from src.api.approval_types import VariantStatus
from src.api.models import Base, TaskHistory, VariantApproval


class MatrixExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temporary.name)
        self.delivery_root = self.temp_root / "delivery"
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

        self.approved_path = self.temp_root / "approved.mp4"
        self.approved_path.write_bytes(b"approved-video")
        pending_path = self.temp_root / "pending.mp4"
        pending_path.write_bytes(b"pending-video")
        self.session.add_all(
            [
                TaskHistory(
                    task_id="task-approved",
                    prompt="approved prompt",
                    batch_size=1,
                    duration=1.0,
                    output_assets=[
                        {"path": str(self.approved_path), "hash": "hash-approved"}
                    ],
                ),
                VariantApproval(
                    task_id="task-approved",
                    asset_hash="hash-approved",
                    file_path=str(self.approved_path),
                    status=VariantStatus.APPROVED,
                    social_title="Approved title",
                    social_caption="Watch {TRACKING_LINK}",
                    social_hashtags="#approved",
                    emotional_tag="Joy",
                    operator="tester",
                ),
                VariantApproval(
                    task_id="task-pending",
                    asset_hash="hash-pending",
                    file_path=str(pending_path),
                    status=VariantStatus.PENDING,
                    operator="tester",
                ),
            ]
        )
        self.session.commit()

        self.generated_hashes = []

        def fake_short_link(_long_url, asset_hash):
            self.generated_hashes.append(asset_hash)
            return f"https://short.test/{asset_hash}"

        self.patches = [
            patch.object(routes_matrix, "get_tenant_engine", return_value=self.engine),
            patch.object(
                routes_matrix,
                "get_delivery_root",
                return_value=str(self.delivery_root.resolve()),
            ),
            patch.object(
                routes_matrix,
                "_create_tracking_adapter",
                return_value=type(
                    "FakeTrackingAdapter",
                    (),
                    {
                        "base_url": "https://short.test/",
                        "generate_short_link": staticmethod(fake_short_link),
                    },
                )(),
            ),
        ]
        for item in self.patches:
            item.start()
        app = FastAPI()
        app.include_router(routes_matrix.router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.session.close()
        self.engine.dispose()
        self.temporary.cleanup()

    def test_export_requires_hashes(self):
        response = self.client.post(
            "/matrix/export",
            json={"hashes": []},
            headers={"X-Local-User": "tenant-a"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "无有效变体 hashes")

    def test_async_export_packages_only_requested_approved_hashes(self):
        response = self.client.post(
            "/matrix/export",
            json={
                "hashes": [
                    "hash-approved",
                    "hash-pending",
                    "hash-approved",
                    "hash-missing",
                ]
            },
            headers={"X-Local-User": "tenant-a"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "processing")
        filename = response.json()["filename"]

        status_response = self.client.get(
            "/matrix/export/status",
            params={"filename": filename},
            headers={"X-Local-User": "tenant-a"},
        )
        self.assertEqual(status_response.json()["status"], "ready")
        self.assertIn("/api/v1/matrix/export/download", status_response.json()["download_url"])

        download = self.client.get(
            "/matrix/export/download",
            params={"filename": filename},
            headers={"X-Local-User": "tenant-a"},
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(self.generated_hashes, ["hash-approved"])
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            names = archive.namelist()
            video_names = [name for name in names if name.startswith("videos/")]
            self.assertEqual(len(video_names), 1)
            self.assertEqual(archive.read(video_names[0]), b"approved-video")
            csv_name = next(name for name in names if name.endswith(".csv"))
            rows = list(
                csv.reader(
                    io.StringIO(archive.read(csv_name).decode("utf-8-sig"))
                )
            )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], video_names[0].removeprefix("videos/"))
        self.assertEqual(rows[1][1], "Approved title")
        self.assertEqual(rows[1][2], "Watch https://short.test/hash-approved")

        approval = (
            self.session.query(VariantApproval)
            .filter(VariantApproval.asset_hash == "hash-approved")
            .one()
        )
        self.session.refresh(approval)
        first_exported_at = approval.exported_at
        self.assertEqual(approval.tracking_link, "https://short.test/hash-approved")
        self.assertIsNotNone(first_exported_at)

        second = self.client.post(
            "/matrix/export",
            json={"hashes": ["hash-approved"]},
            headers={"X-Local-User": "tenant-a"},
        )
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second.json()["filename"], filename)
        self.assertEqual(self.generated_hashes, ["hash-approved"])
        self.session.refresh(approval)
        self.assertEqual(approval.exported_at, first_exported_at)

    def test_other_tenant_cannot_observe_or_download_export(self):
        response = self.client.post(
            "/matrix/export",
            json={"hashes": ["hash-approved"]},
            headers={"X-Local-User": "tenant-a"},
        )
        filename = response.json()["filename"]
        for endpoint in ("/matrix/export/status", "/matrix/export/download"):
            denied = self.client.get(
                endpoint,
                params={"filename": filename},
                headers={"X-Local-User": "tenant-b"},
            )
            self.assertEqual(denied.status_code, 404)


if __name__ == "__main__":
    unittest.main()
