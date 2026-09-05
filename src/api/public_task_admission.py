"""Tenant-local admission and lifecycle state for server-owned task IDs.

Admission is committed before worker dispatch. The ``video_tasks.task_id``
UNIQUE constraint is the physical collision authority; UUID collisions are
retried internally and never exposed as a client duplicate contract.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import Engine, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import VideoTask
from .task_identity import PUBLIC_TASK_ID_GENERATION_COLLISION, new_task_id


PUBLIC_TASK_ADMISSION_STATE_INVALID = "PUBLIC_TASK_ADMISSION_STATE_INVALID"
PUBLIC_TASK_ROLLOUT_METADATA_INVALID = "PUBLIC_TASK_ROLLOUT_METADATA_INVALID"
PUBLIC_TASK_RESERVATION_CONFLICT_MODES = frozenset({"OFF", "ENFORCE"})
PUBLIC_TASK_PLANNING_POLICIES = frozenset(
    {"legacy", "exact_main_visual", "exact_main_visual_balanced"}
)
_SERVER_ID_CLAIM_ATTEMPTS = 4


class PublicTaskAdmissionError(RuntimeError):
    """Base error for public task admission and lifecycle state."""


class PublicTaskAdmissionStateError(PublicTaskAdmissionError):
    """An admitted task row is missing or has an invalid lifecycle state."""

    def __init__(self) -> None:
        super().__init__(PUBLIC_TASK_ADMISSION_STATE_INVALID)


@dataclass(frozen=True)
class PublicTaskAdmission:
    task_id: str
    video_task_id: int


def _session_factory(bind: Engine) -> Callable[[], Session]:
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=bind,
        expire_on_commit=False,
    )


def _is_video_task_id_unique_violation(exc: IntegrityError) -> bool:
    """Recognize only SQLite's exact server task-ID unique violation."""
    return (
        isinstance(exc.orig, sqlite3.IntegrityError)
        and str(exc.orig) == "UNIQUE constraint failed: video_tasks.task_id"
    )


def _validate_rollout_metadata(
    reservation_conflict_mode: str,
    planning_policy: str,
) -> None:
    """Reject metadata that cannot describe a validated public submission."""
    if (
        reservation_conflict_mode not in PUBLIC_TASK_RESERVATION_CONFLICT_MODES
        or planning_policy not in PUBLIC_TASK_PLANNING_POLICIES
        or (
            reservation_conflict_mode == "ENFORCE"
            and planning_policy == "legacy"
        )
    ):
        raise PublicTaskAdmissionError(PUBLIC_TASK_ROLLOUT_METADATA_INVALID)


def _claim_one(
    bind: Engine,
    *,
    task_id: str,
    prompt: str,
    batch_size: int,
    reservation_conflict_mode: str,
    planning_policy: str,
) -> int:
    SessionLocal = _session_factory(bind)
    with SessionLocal() as session:
        task = VideoTask(
            task_id=task_id,
            prompt=prompt,
            batch_size=batch_size,
            status="queued",
            reservation_conflict_mode=reservation_conflict_mode,
            planning_policy=planning_policy,
        )
        session.add(task)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            if _is_video_task_id_unique_violation(exc):
                return 0
            raise
        return int(task.id)


def admit_public_task(
    bind: Engine,
    *,
    prompt: str | None,
    batch_size: int,
    reservation_conflict_mode: str = "OFF",
    planning_policy: str = "legacy",
    task_id_factory: Callable[[], str] | None = None,
) -> PublicTaskAdmission:
    """Generate and durably admit one public task before worker dispatch."""
    _validate_rollout_metadata(reservation_conflict_mode, planning_policy)
    generator = task_id_factory or new_task_id
    for _ in range(_SERVER_ID_CLAIM_ATTEMPTS):
        task_id = generator()
        video_task_id = _claim_one(
            bind,
            task_id=task_id,
            prompt=prompt or "",
            batch_size=batch_size,
            reservation_conflict_mode=reservation_conflict_mode,
            planning_policy=planning_policy,
        )
        if video_task_id:
            return PublicTaskAdmission(
                task_id=task_id,
                video_task_id=video_task_id,
            )

    raise PublicTaskAdmissionError(PUBLIC_TASK_ID_GENERATION_COLLISION)


def transition_public_task_status(
    bind: Engine,
    *,
    task_id: str,
    target_status: str,
) -> None:
    """Commit one truthful lifecycle transition in a short tenant session."""
    allowed_sources = {
        "processing": {"queued"},
        "completed": {"processing"},
        "failed": {"queued", "processing"},
    }
    if target_status not in allowed_sources:
        raise PublicTaskAdmissionStateError()

    SessionLocal = _session_factory(bind)
    with SessionLocal() as session:
        result = session.execute(
            update(VideoTask)
            .where(
                VideoTask.task_id == task_id,
                VideoTask.status.in_(allowed_sources[target_status]),
            )
            .values(
                status=target_status,
                finished_at=(
                    datetime.now(timezone.utc)
                    if target_status in {"completed", "failed"}
                    else None
                ),
            )
        )
        if result.rowcount != 1:
            session.rollback()
            raise PublicTaskAdmissionStateError()
        session.commit()
