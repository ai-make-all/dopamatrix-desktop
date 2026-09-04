"""Internal planner Reservation coordination.

This module owns no tenant resolution and has no public request activation.
Callers must supply an authoritative tenant-bound Session factory and explicit
lease configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import logging
import threading
from collections.abc import Callable

from sqlalchemy.orm import Session

from .fingerprint_ledger import (
    FingerprintIdentityRecord,
    FingerprintLedgerRepository,
    ReservationAcquireStatus,
    _normalize_reservation_datetime,
    _reservation_utcnow,
)
from .reservation_lease import (
    ReservationLeaseConfiguration,
    ReservationLeaseState,
    ReservationLeaseTracker,
)


logger = logging.getLogger(__name__)


class PlannerReservationError(RuntimeError):
    """Stable hard failure for enforcement-critical Reservation coordination."""


class PlannerReservationDecision(str, Enum):
    OWNED = "OWNED"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class PlannerReservationBinding:
    fingerprint_identity_id: int
    fingerprint_type: str
    fingerprint_version: int
    fingerprint_digest: str
    owner_task_id: str
    owner_slot_index: int
    committed_expires_at: datetime


@dataclass(frozen=True)
class PlannerReservationAcquireOutcome:
    decision: PlannerReservationDecision
    binding: PlannerReservationBinding | None = None


class PlannerReservationController:
    """Own committed planner leases and their task-local heartbeat."""

    def __init__(
        self,
        *,
        owner_task_id: str,
        session_factory: Callable[[], Session],
        configuration: ReservationLeaseConfiguration,
        now: Callable[[], datetime] = _reservation_utcnow,
        tracker: ReservationLeaseTracker | None = None,
        cleanup_join_timeout_seconds: float = 2.0,
    ) -> None:
        self._owner_task_id = owner_task_id
        self._session_factory = session_factory
        self._configuration = configuration.require_configured()
        self._now = now
        self._tracker = tracker or ReservationLeaseTracker(
            owner_task_id=owner_task_id,
            session_factory=session_factory,
            configuration=configuration,
            now=now,
        )
        self._cleanup_join_timeout_seconds = cleanup_join_timeout_seconds
        self._bindings: list[PlannerReservationBinding] = []
        self._conflict_count = 0
        self._cleanup_warning_emitted = False
        self._lock = threading.RLock()

    @property
    def owner_task_id(self) -> str:
        return self._owner_task_id

    @property
    def tracker(self) -> ReservationLeaseTracker:
        return self._tracker

    @property
    def conflict_count(self) -> int:
        with self._lock:
            return self._conflict_count

    @property
    def bindings(self) -> tuple[PlannerReservationBinding, ...]:
        with self._lock:
            return tuple(self._bindings)

    def require_active(self) -> None:
        if self._tracker.state is not ReservationLeaseState.ACTIVE:
            raise PlannerReservationError("PLANNER_RESERVATION_AUTHORITY_LOST")

    def acquire_candidate(
        self,
        identity_record: FingerprintIdentityRecord,
        *,
        prospective_slot: int,
    ) -> PlannerReservationAcquireOutcome:
        """Commit ownership before returning an accepted-eligible outcome."""
        self.require_active()
        with self._lock:
            if prospective_slot != len(self._bindings):
                raise PlannerReservationError(
                    "PLANNER_RESERVATION_SLOT_ALIGNMENT_INVALID"
                )

        current_time = _normalize_reservation_datetime(self._now())
        ttl = self._configuration.reservation_lease_ttl_seconds
        assert ttl is not None
        requested_expiry = current_time + timedelta(seconds=ttl)
        with self._session_factory() as session:
            result = FingerprintLedgerRepository(session).acquire_reservation(
                identity_record,
                owner_task_id=self._owner_task_id,
                owner_slot_index=prospective_slot,
                now=current_time,
                expires_at=requested_expiry,
            )
            session.commit()

        if result.status is ReservationAcquireStatus.CONFLICT:
            with self._lock:
                self._conflict_count += 1
            return PlannerReservationAcquireOutcome(
                decision=PlannerReservationDecision.CONFLICT,
            )
        if result.status not in {
            ReservationAcquireStatus.ACQUIRED,
            ReservationAcquireStatus.REACQUIRED,
        }:
            raise PlannerReservationError(
                "PLANNER_RESERVATION_ACQUIRE_RESULT_INVALID"
            )
        if result.expires_at is None:
            raise PlannerReservationError(
                "PLANNER_RESERVATION_COMMITTED_EXPIRY_MISSING"
            )

        binding = PlannerReservationBinding(
            fingerprint_identity_id=result.fingerprint_identity_id,
            fingerprint_type=identity_record.fingerprint_type,
            fingerprint_version=identity_record.fingerprint_version,
            fingerprint_digest=identity_record.fingerprint_digest,
            owner_task_id=self._owner_task_id,
            owner_slot_index=prospective_slot,
            committed_expires_at=_normalize_reservation_datetime(result.expires_at),
        )
        with self._lock:
            self._bindings.append(binding)
        try:
            self._tracker.register_binding(
                fingerprint_identity_id=binding.fingerprint_identity_id,
                owner_slot_index=binding.owner_slot_index,
                expires_at=binding.committed_expires_at,
            )
            if not self._tracker.start():
                raise PlannerReservationError(
                    "PLANNER_RESERVATION_HEARTBEAT_START_FAILED"
                )
            self.require_active()
        except Exception:
            self.abort()
            raise
        return PlannerReservationAcquireOutcome(
            decision=PlannerReservationDecision.OWNED,
            binding=binding,
        )

    def abort(self) -> bool:
        """Stop heartbeat and owner-safely release; never hide caller failure."""
        try:
            quiesced = self._tracker.stop(
                join_timeout_seconds=self._cleanup_join_timeout_seconds
            )
        except Exception as exc:
            self._warn_cleanup(type(exc).__name__)
            return False
        if not quiesced:
            self._warn_cleanup("HEARTBEAT_NOT_QUIESCED")
            return False

        with self._lock:
            bindings = tuple(self._bindings)
        if not bindings:
            return True
        try:
            with self._session_factory() as session:
                repository = FingerprintLedgerRepository(session)
                for binding in bindings:
                    repository.release_reservation(
                        binding.fingerprint_identity_id,
                        owner_task_id=binding.owner_task_id,
                        owner_slot_index=binding.owner_slot_index,
                    )
                session.commit()
        except Exception as exc:
            self._warn_cleanup(type(exc).__name__)
            return False
        with self._lock:
            self._bindings.clear()
        return True

    def _warn_cleanup(self, category: str) -> None:
        with self._lock:
            if self._cleanup_warning_emitted:
                return
            self._cleanup_warning_emitted = True
        try:
            logger.warning(
                "[PLANNER_RESERVATION_CLEANUP_INCOMPLETE] category=%s",
                category[:64],
            )
        except Exception:
            pass
