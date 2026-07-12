import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.approval_service import batch_update_variant_status
from src.api.approval_types import VariantStatus
from src.api.models import Base, TaskHistory, VariantApproval, VariantStatusAudit
from src.api.routes_approval import get_approval_list


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_batch_update_audits_syncs_history_and_deletes_file(db, tmp_path):
    video_path = tmp_path / "variant.mp4"
    video_path.write_bytes(b"video")
    asset_hash = "hash-approval-1"
    history = TaskHistory(
        task_id="task-1",
        prompt="test",
        batch_size=1,
        duration=1.0,
        output_assets=[{"path": str(video_path), "hash": asset_hash}],
        prompt_details=json.dumps(
            {"meta": {"social_title": "Title", "social_hashtags": "#tag"}}
        ),
    )
    db.add(history)
    db.commit()

    result = batch_update_variant_status(
        db,
        [asset_hash],
        VariantStatus.APPROVED,
        operator="alice",
    )

    approval = db.query(VariantApproval).one()
    assert result["updated_count"] == 1
    assert approval.status == VariantStatus.APPROVED
    assert approval.operator == "alice"
    assert db.query(VariantStatusAudit).count() == 1
    db.refresh(history)
    assert history.output_assets[0]["status"] == "APPROVED"

    batch_update_variant_status(
        db,
        [asset_hash],
        VariantStatus.DELETED,
        operator="alice",
    )

    db.refresh(approval)
    assert approval.status == VariantStatus.DELETED
    assert not video_path.exists()
    assert db.query(VariantStatusAudit).count() == 2


def test_processing_variant_blocks_entire_batch(db, tmp_path):
    asset_hash = "hash-processing-1"
    video_path = tmp_path / "processing.mp4"
    video_path.write_bytes(b"video")
    db.add(
        VariantApproval(
            task_id="task-processing",
            asset_hash=asset_hash,
            file_path=str(video_path),
            status=VariantStatus.PROCESSING,
            operator="renderer",
        )
    )
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        batch_update_variant_status(
            db,
            [asset_hash],
            VariantStatus.APPROVED,
            operator="alice",
        )

    assert exc_info.value.status_code == 409
    approval = db.query(VariantApproval).one()
    assert approval.status == VariantStatus.PROCESSING


def test_approval_list_filters_terminal_and_processing_statuses(db):
    for index, variant_status in enumerate(VariantStatus):
        db.add(
            VariantApproval(
                task_id=f"task-{index}",
                asset_hash=f"hash-{index}",
                file_path=f"video-{index}.mp4",
                status=variant_status,
                operator="tester",
            )
        )
    db.commit()

    all_rows = get_approval_list(status_filter="ALL", db=db)
    assert {row["status"] for row in all_rows} == {"PENDING", "APPROVED"}

    rejected_rows = get_approval_list(status_filter="REJECTED", db=db)
    assert [row["status"] for row in rejected_rows] == ["REJECTED"]
    assert all(
        row["status"] not in {"DELETED", "PROCESSING"}
        for row in all_rows + rejected_rows
    )
