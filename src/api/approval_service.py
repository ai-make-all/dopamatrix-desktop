from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .approval_types import REVIEW_TARGET_STATUSES, VariantStatus
from .models import TaskHistory, VariantApproval, VariantStatusAudit


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _status_value(value: VariantStatus | str | None) -> str | None:
    if value is None:
        return None
    return value.value if isinstance(value, VariantStatus) else str(value)


def _extract_social_meta(record: TaskHistory) -> dict:
    if not record.prompt_details:
        return {}
    try:
        details = (
            json.loads(record.prompt_details)
            if isinstance(record.prompt_details, str)
            else record.prompt_details
        )
        return (details or {}).get("meta", {}) or {}
    except (json.JSONDecodeError, AttributeError, TypeError):
        return {}


def _normalize_hashes(hashes: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in hashes if value and value.strip()))


def _stage_file(path_value: str, staged: list[tuple[Path, Path]]) -> bool:
    if not path_value:
        return False
    source = Path(path_value)
    if not source.is_file():
        return False
    tombstone = source.with_name(f".{source.name}.deleted-{uuid.uuid4().hex}")
    os.replace(source, tombstone)
    staged.append((source, tombstone))
    return True


def _restore_staged_files(staged: list[tuple[Path, Path]]) -> None:
    for source, tombstone in reversed(staged):
        if tombstone.exists():
            os.replace(tombstone, source)


def ensure_pending_variant_records(db: Session) -> int:
    """Backfill PENDING rows for rendered history assets not yet in the state table."""
    existing_keys = {
        (row.task_id, row.asset_hash)
        for row in db.query(VariantApproval.task_id, VariantApproval.asset_hash).all()
    }
    created = 0
    now = _now()

    for record in db.query(TaskHistory).all():
        meta = _extract_social_meta(record)
        for asset in record.output_assets or []:
            asset_hash = asset.get("hash") or asset.get("file_hash")
            if not asset_hash or (record.task_id, asset_hash) in existing_keys:
                continue
            db.add(
                VariantApproval(
                    task_id=record.task_id,
                    asset_hash=asset_hash,
                    file_path=asset.get("path") or asset.get("file_path", ""),
                    cover_path=asset.get("cover_path", ""),
                    status=VariantStatus.PENDING,
                    social_title=asset.get("social_title") or meta.get("social_title"),
                    social_caption=asset.get("social_caption") or meta.get("social_caption"),
                    social_hashtags=asset.get("social_hashtags") or meta.get("social_hashtags"),
                    human_drive=meta.get("human_drive"),
                    emotional_tag=meta.get("emotional_tag"),
                    operator="system",
                    created_at=now,
                    updated_at=now,
                )
            )
            existing_keys.add((record.task_id, asset_hash))
            created += 1

    if created:
        db.commit()
    return created


def batch_update_variant_status(
    db: Session,
    hashes: Iterable[str],
    target_status: VariantStatus,
    operator: str,
) -> dict:
    normalized_hashes = _normalize_hashes(hashes)
    if not normalized_hashes:
        return {
            "message": "success",
            "updated_count": 0,
            "target_status": target_status,
            "updated_hashes": [],
            "missing_hashes": [],
            "missing_files": [],
            "cleanup_errors": [],
        }
    if target_status not in REVIEW_TARGET_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"审核接口不允许将状态更新为 {target_status.value}",
        )

    requested = set(normalized_hashes)
    approvals = (
        db.query(VariantApproval)
        .filter(VariantApproval.asset_hash.in_(normalized_hashes))
        .all()
    )
    approval_by_key = {(row.task_id, row.asset_hash): row for row in approvals}

    histories = db.query(TaskHistory).all()
    history_assets: dict[tuple[str, str], tuple[TaskHistory, dict]] = {}
    histories_to_sync: dict[int, TaskHistory] = {}

    for record in histories:
        for asset in record.output_assets or []:
            asset_hash = asset.get("hash") or asset.get("file_hash")
            if asset_hash in requested:
                history_assets[(record.task_id, asset_hash)] = (record, asset)

    found_hashes = {row.asset_hash for row in approvals}
    found_hashes.update(asset_hash for _, asset_hash in history_assets)
    missing_hashes = [value for value in normalized_hashes if value not in found_hashes]
    if missing_hashes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "部分视频 hash 不存在，批量操作未执行",
                "missing_hashes": missing_hashes,
            },
        )

    for key, (record, asset) in history_assets.items():
        if key in approval_by_key:
            continue
        meta = _extract_social_meta(record)
        approval = VariantApproval(
            task_id=record.task_id,
            asset_hash=key[1],
            file_path=asset.get("path") or asset.get("file_path", ""),
            cover_path=asset.get("cover_path", ""),
            status=VariantStatus.PENDING,
            social_title=asset.get("social_title") or meta.get("social_title"),
            social_caption=asset.get("social_caption") or meta.get("social_caption"),
            social_hashtags=asset.get("social_hashtags") or meta.get("social_hashtags"),
            human_drive=meta.get("human_drive"),
            emotional_tag=meta.get("emotional_tag"),
            operator="system",
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(approval)
        approvals.append(approval)
        approval_by_key[key] = approval

    blocked = [
        row.asset_hash
        for row in approvals
        if _status_value(row.status) == VariantStatus.PROCESSING.value
    ]
    if blocked:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "PROCESSING 状态不可执行审核操作，批量操作未执行",
                "blocked_hashes": sorted(set(blocked)),
            },
        )

    invalid_terminal = [
        row.asset_hash
        for row in approvals
        if _status_value(row.status) == VariantStatus.DELETED.value
        and target_status != VariantStatus.DELETED
    ]
    if invalid_terminal:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "DELETED 是终态，不允许恢复，批量操作未执行",
                "blocked_hashes": sorted(set(invalid_terminal)),
            },
        )

    staged_files: list[tuple[Path, Path]] = []
    missing_files: list[str] = []
    now = _now()

    try:
        if target_status == VariantStatus.DELETED:
            seen_paths: set[str] = set()
            for row in approvals:
                for path_value in (row.file_path, row.cover_path):
                    if not path_value or path_value in seen_paths:
                        continue
                    seen_paths.add(path_value)
                    if not _stage_file(path_value, staged_files):
                        missing_files.append(path_value)

        for row in approvals:
            previous = _status_value(row.status)
            if previous != target_status.value:
                db.add(
                    VariantStatusAudit(
                        task_id=row.task_id,
                        asset_hash=row.asset_hash,
                        from_status=previous,
                        to_status=target_status.value,
                        operator=operator,
                        created_at=now,
                    )
                )
            row.status = target_status
            row.updated_at = now
            row.operator = operator

        for (task_id, asset_hash), (record, _) in history_assets.items():
            assets = [dict(asset) for asset in (record.output_assets or [])]
            changed = False
            for asset in assets:
                current_hash = asset.get("hash") or asset.get("file_hash")
                if current_hash == asset_hash:
                    asset["status"] = target_status.value
                    asset["updated_at"] = now.isoformat()
                    asset["operator"] = operator
                    changed = True
            if changed:
                record.output_assets = assets
                histories_to_sync[record.id] = record

        db.commit()
    except Exception:
        db.rollback()
        _restore_staged_files(staged_files)
        raise

    cleanup_errors: list[str] = []
    for _, tombstone in staged_files:
        try:
            tombstone.unlink(missing_ok=True)
        except OSError as exc:
            cleanup_errors.append(f"{tombstone}: {exc}")

    return {
        "message": "success",
        "updated_count": len(approvals),
        "target_status": target_status,
        "updated_hashes": normalized_hashes,
        "missing_hashes": [],
        "missing_files": missing_files,
        "cleanup_errors": cleanup_errors,
    }
