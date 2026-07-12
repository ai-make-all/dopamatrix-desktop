import csv
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.approval_types import VariantStatus
from src.api.database import get_db
from src.api.models import Base, TaskHistory, VariantApproval
from src.api import routes_history, routes_matrix


@pytest.fixture()
def export_client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    approved_path = tmp_path / "approved.mp4"
    approved_path.write_bytes(b"approved-video")
    pending_path = tmp_path / "pending.mp4"
    pending_path.write_bytes(b"pending-video")

    session.add_all(
        [
            TaskHistory(
                task_id="task-approved",
                prompt="approved prompt",
                batch_size=1,
                duration=1.0,
                output_assets=[
                    {
                        "path": str(approved_path),
                        "hash": "hash-approved",
                    }
                ],
            ),
            VariantApproval(
                task_id="task-approved",
                asset_hash="hash-approved",
                file_path=str(approved_path),
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
    session.commit()

    generated_hashes = []

    def fake_short_link(long_url, asset_hash):
        generated_hashes.append(asset_hash)
        return f"https://short.test/{asset_hash}"

    monkeypatch.setattr(
        routes_matrix._tracking_adapter,
        "generate_short_link",
        fake_short_link,
    )

    app = FastAPI()
    app.include_router(routes_matrix.router)
    app.include_router(routes_history.router)
    app.dependency_overrides[get_db] = lambda: session

    try:
        yield TestClient(app), generated_hashes, session
    finally:
        session.close()


def test_export_requires_hashes(export_client):
    client, _, _ = export_client

    response = client.post("/matrix/export", json={"hashes": []})

    assert response.status_code == 400
    assert response.json()["detail"] == "No hashes provided"


def test_export_only_packages_requested_approved_hashes(export_client):
    client, generated_hashes, session = export_client

    response = client.post(
        "/matrix/export",
        json={
            "hashes": [
                "hash-approved",
                "hash-pending",
                "hash-approved",
                "hash-missing",
            ]
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert generated_hashes == ["hash-approved"]

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        video_names = [name for name in names if name.startswith("videos/")]
        assert len(video_names) == 1
        assert archive.read(video_names[0]) == b"approved-video"

        csv_name = next(name for name in names if name.endswith(".csv"))
        csv_text = archive.read(csv_name).decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(csv_text)))

    assert len(rows) == 2
    assert rows[1][0] == video_names[0].removeprefix("videos/")
    assert rows[1][1] == "Approved title"
    assert rows[1][2] == "Watch https://short.test/hash-approved"

    approval = (
        session.query(VariantApproval)
        .filter(VariantApproval.asset_hash == "hash-approved")
        .one()
    )
    first_exported_at = approval.exported_at
    assert approval.tracking_link == "https://short.test/hash-approved"
    assert first_exported_at is not None

    second_response = client.post(
        "/matrix/export",
        json={"hashes": ["hash-approved"]},
    )

    assert second_response.status_code == 200
    assert generated_hashes == ["hash-approved"]
    session.refresh(approval)
    assert approval.tracking_link == "https://short.test/hash-approved"
    assert approval.exported_at == first_exported_at

    history_response = client.get("/history/")
    assert history_response.status_code == 200
    exported_asset = history_response.json()[0]["output_assets"][0]
    assert exported_asset["tracking_link"] == "https://short.test/hash-approved"
    assert exported_asset["exported_at"] is not None
