"""Task-local renewable Reservation lease infrastructure.

Lease TTL is a stale-owner detection horizon, not a render execution deadline.
This module owns no tenant selection and performs no planner integration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
import logging
import math
import os
import threading
from collections.abc import Callable, Mapping, Sequence

from sqlalchemy.exc import (
    DisconnectionError,
    InterfaceError,
    OperationalError,
    TimeoutError as SQLAlchemyTimeoutError,
)
from sqlalchemy.orm import Session

from .fingerprint_ledger import (
    FingerprintLedgerRepository,
    FingerprintReservationBatchRenewalError,
    ReservationRenewRequest,
    _normalize_reservation_datetime,
    _reservation_utcnow,
)


logger = logging.getLogger(__name__)

RESERVATION_LEASE_TTL_ENV = "RESERVATION_LEASE_TTL_SECONDS"
RESERVATION_HEARTBEAT_INTERVAL_ENV = "RESERVATION_HEARTBEAT_INTERVAL_SECONDS"

_INFRASTRUCTURE_ERRORS = (
    OperationalError,
    InterfaceError,
    DisconnectionError,
    SQLAlchemyTimeoutError,
)


class ReservationLeaseConfigurationError(ValueError):
    """Stable configuration failure for renewable Reservation leases."""


@dataclass(frozen=True)
class ReservationLeaseConfiguration:
    reservation_lease_ttl_seconds: float | None = None
    reservation_heartbeat_interval_seconds: float | None = None

    def __post_init__(self) -> None:
        ttl = self.reservation_lease_ttl_seconds
        interval = self.reservation_heartbeat_interval_seconds
        if ttl is None and interval is None:
            return
        if ttl is None or interval is None:
            raise ReservationLeaseConfigurationError(
                "RESERVATION_LEASE_CONFIGURATION_INCOMPLETE"
            )
        for name, value in (("TTL", ttl), ("HEARTBEAT_INTERVAL", interval)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ReservationLeaseConfigurationError(
                    f"RESERVATION_LEASE_{name}_INVALID"
                )
            if not math.isfinite(value) or value <= 0:
                raise ReservationLeaseConfigurationError(
                    f"RESERVATION_LEASE_{name}_INVALID"
                )
        if interval > ttl / 3:
            raise ReservationLeaseConfigurationError(
                "RESERVATION_LEASE_HEARTBEAT_INTERVAL_EXCEEDS_TTL_THIRD"
            )
        object.__setattr__(self, "reservation_lease_ttl_seconds", float(ttl))
        object.__setattr__(
            self,
            "reservation_heartbeat_interval_seconds",
            float(interval),
        )

    @property
    def configured(self) -> bool:
        return self.reservation_lease_ttl_seconds is not None

    def require_configured(self) -> "ReservationLeaseConfiguration":
        if not self.configured:
            raise ReservationLeaseConfigurationError(
                "RESERVATION_LEASE_CONFIGURATION_UNAVAILABLE"
            )
        return self


def load_reservation_lease_configuration(
    environ: Mapping[str, str] | None = None,
) -> ReservationLeaseConfiguration:
    """Read optional backend-only lease settings without creating defaults."""
    source = os.environ if environ is None else environ
    ttl_raw = source.get(RESERVATION_LEASE_TTL_ENV)
    interval_raw = source.get(RESERVATION_HEARTBEAT_INTERVAL_ENV)
    if ttl_raw is None and interval_raw is None:
        return ReservationLeaseConfiguration()
    try:
        ttl = float(ttl_raw) if ttl_raw is not None else None
        interval = float(interval_raw) if interval_raw is not None else None
    except (TypeError, ValueError) as exc:
        raise ReservationLeaseConfigurationError(
            "RESERVATION_LEASE_CONFIGURATION_VALUE_INVALID"
        ) from exc
    return ReservationLeaseConfiguration(ttl, interval)


class ReservationLeaseState(str, Enum):
    ACTIVE = "ACTIVE"
    LEASE_LOST = "LEASE_LOST"


class ReservationHeartbeatState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class ReservationLeaseBinding:
    fingerprint_identity_id: int
    owner_attempt_id: str
    owner_slot_index: int
    expires_at: datetime
    execution_id: str | None = None


class ReservationLeaseTrackerError(RuntimeError):
    """Stable task-local tracker contract failure."""


class ReservationLeaseTracker:
    """Renew a bounded task-owned Reservation set with isolated Sessions."""

    def __init__(
        self,
        *,
        owner_attempt_id: str,
        session_factory: Callable[[], Session],
        configuration: ReservationLeaseConfiguration,
        now: Callable[[], datetime] = _reservation_utcnow,
        heartbeat_wait: Callable[[float], bool] | None = None,
    ) -> None:
        self._owner_attempt_id = owner_attempt_id
        self._session_factory = session_factory
        self._configuration = configuration.require_configured()
        self._now = now
        self._state = ReservationLeaseState.ACTIVE
        self._heartbeat_state = ReservationHeartbeatState.NOT_STARTED
        self._bindings: dict[int, ReservationLeaseBinding] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._heartbeat_wait = heartbeat_wait or self._stop_event.wait
        self._thread: threading.Thread | None = None
        self._infrastructure_failure_count = 0
        self._infrastructure_warning_emitted = False
        self._terminal_failure_category: str | None = None

    @property
    def owner_attempt_id(self) -> str:
        """Return the owner-attempt identity stored in the legacy owner column."""
        return self._owner_attempt_id

    @property
    def state(self) -> ReservationLeaseState:
        with self._lock:
            return self._state

    @property
    def lease_lost(self) -> bool:
        with self._lock:
            return self._state is ReservationLeaseState.LEASE_LOST

    @property
    def heartbeat_state(self) -> ReservationHeartbeatState:
        with self._lock:
            return self._heartbeat_state

    @property
    def terminal_failure_category(self) -> str | None:
        with self._lock:
            return self._terminal_failure_category

    @property
    def infrastructure_failure_count(self) -> int:
        with self._lock:
            return self._infrastructure_failure_count

    def bindings(self) -> tuple[ReservationLeaseBinding, ...]:
        with self._lock:
            return tuple(self._bindings.values())

    def register_binding(
        self,
        *,
        fingerprint_identity_id: int,
        owner_slot_index: int,
        expires_at: datetime,
        execution_id: str | None = None,
    ) -> None:
        normalized_expiry = _normalize_reservation_datetime(expires_at)
        with self._lock:
            if (
                self._state is not ReservationLeaseState.ACTIVE
                or self._heartbeat_state in {
                    ReservationHeartbeatState.STOPPING,
                    ReservationHeartbeatState.STOPPED,
                }
            ):
                raise ReservationLeaseTrackerError(
                    "RESERVATION_LEASE_TRACKER_NOT_ACTIVE"
                )
            if fingerprint_identity_id in self._bindings:
                raise ReservationLeaseTrackerError(
                    "RESERVATION_LEASE_BINDING_ALREADY_REGISTERED"
                )
            self._bindings[fingerprint_identity_id] = ReservationLeaseBinding(
                fingerprint_identity_id=fingerprint_identity_id,
                owner_attempt_id=self._owner_attempt_id,
                owner_slot_index=owner_slot_index,
                expires_at=normalized_expiry,
                execution_id=execution_id,
            )

    def update_execution_binding(
        self,
        fingerprint_identity_id: int,
        execution_id: str,
    ) -> None:
        with self._lock:
            binding = self._bindings.get(fingerprint_identity_id)
            if binding is None:
                raise ReservationLeaseTrackerError(
                    "RESERVATION_LEASE_BINDING_NOT_REGISTERED"
                )
            expires_at = binding.expires_at
        self.update_committed_execution_bindings(
            ((fingerprint_identity_id, execution_id, expires_at),)
        )

    def update_committed_execution_bindings(
        self,
        updates: Sequence[tuple[int, str, datetime]],
    ) -> None:
        """Atomically apply post-commit execution bindings to local tracker state."""
        with self._lock:
            if (
                self._state is not ReservationLeaseState.ACTIVE
                or self._heartbeat_state in {
                    ReservationHeartbeatState.STOPPING,
                    ReservationHeartbeatState.STOPPED,
                }
            ):
                raise ReservationLeaseTrackerError(
                    "RESERVATION_LEASE_TRACKER_NOT_ACTIVE"
                )
            if len({identity_id for identity_id, _execution_id, _expiry in updates}) != len(updates):
                raise ReservationLeaseTrackerError(
                    "RESERVATION_LEASE_EXECUTION_UPDATE_DUPLICATE_IDENTITY"
                )
            replacements: dict[int, ReservationLeaseBinding] = {}
            for fingerprint_identity_id, execution_id, expires_at in updates:
                binding = self._bindings.get(fingerprint_identity_id)
                if binding is None:
                    raise ReservationLeaseTrackerError(
                        "RESERVATION_LEASE_BINDING_NOT_REGISTERED"
                    )
                if binding.execution_id not in (None, execution_id):
                    raise ReservationLeaseTrackerError(
                        "RESERVATION_LEASE_EXECUTION_REBIND_FORBIDDEN"
                    )
                replacements[fingerprint_identity_id] = replace(
                    binding,
                    execution_id=execution_id,
                    expires_at=_normalize_reservation_datetime(expires_at),
                )
            self._bindings.update(replacements)

    def fail_closed(self, category: str) -> None:
        """Make an integration failure observable as irreversible local authority loss."""
        with self._lock:
            self._mark_lease_lost_locked(category)

    def start(self) -> bool:
        with self._lock:
            if self._state is not ReservationLeaseState.ACTIVE:
                return False
            if not self._bindings:
                return False
            if self._heartbeat_state is ReservationHeartbeatState.RUNNING:
                return True
            if self._heartbeat_state is not ReservationHeartbeatState.NOT_STARTED:
                return False
            self._stop_event.clear()
            self._heartbeat_state = ReservationHeartbeatState.RUNNING
            self._thread = threading.Thread(
                target=self._heartbeat_loop,
                name="reservation-lease-heartbeat",
                daemon=True,
            )
            try:
                self._thread.start()
            except Exception as exc:
                self._mark_lease_lost_locked(type(exc).__name__)
                self._heartbeat_state = ReservationHeartbeatState.STOPPED
                raise
            return True

    def stop(self, *, join_timeout_seconds: float = 2.0) -> bool:
        self._stop_event.set()
        with self._lock:
            thread = self._thread
            if self._heartbeat_state is ReservationHeartbeatState.NOT_STARTED:
                self._heartbeat_state = ReservationHeartbeatState.STOPPED
            elif self._heartbeat_state is ReservationHeartbeatState.RUNNING:
                self._heartbeat_state = ReservationHeartbeatState.STOPPING
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, join_timeout_seconds))
        if thread is not None and thread.is_alive():
            return False
        with self._lock:
            self._heartbeat_state = ReservationHeartbeatState.STOPPED
        return True

    def run_renewal_cycle(self, *, now: datetime | None = None) -> bool:
        """Run one all-or-nothing cycle; exposed for deterministic coordination/tests."""
        try:
            with self._lock:
                if (
                    self._state is not ReservationLeaseState.ACTIVE
                    or self._heartbeat_state in {
                        ReservationHeartbeatState.STOPPING,
                        ReservationHeartbeatState.STOPPED,
                    }
                ):
                    return False
                if not self._bindings:
                    return True

                current_time = _normalize_reservation_datetime(now or self._now())
                ttl = self._configuration.reservation_lease_ttl_seconds
                assert ttl is not None
                next_expiry = current_time + timedelta(seconds=ttl)
                snapshot = tuple(self._bindings.values())
                requests = tuple(
                    ReservationRenewRequest(
                        fingerprint_identity_id=binding.fingerprint_identity_id,
                        owner_task_id=binding.owner_attempt_id,
                        owner_slot_index=binding.owner_slot_index,
                        expected_execution_id=binding.execution_id,
                    )
                    for binding in snapshot
                )

            with self._session_factory() as session:
                results = FingerprintLedgerRepository(session).renew_reservations(
                    requests,
                    now=current_time,
                    expires_at=next_expiry,
                )
                session.commit()

            with self._lock:
                if self._state is not ReservationLeaseState.ACTIVE:
                    return False
                for result in results:
                    binding = self._bindings[result.fingerprint_identity_id]
                    self._bindings[result.fingerprint_identity_id] = replace(
                        binding,
                        expires_at=_normalize_reservation_datetime(result.expires_at),
                    )
                return True
        except _INFRASTRUCTURE_ERRORS as exc:
            try:
                fresh_time = _normalize_reservation_datetime(self._now())
            except Exception as clock_exc:
                with self._lock:
                    self._mark_lease_lost_locked(type(clock_exc).__name__)
                raise
            with self._lock:
                self._infrastructure_failure_count += 1
                failure_time = max(current_time, fresh_time)
                earliest_expiry = min(
                    binding.expires_at for binding in self._bindings.values()
                )
                if failure_time >= earliest_expiry:
                    self._mark_lease_lost_locked(type(exc).__name__)
                elif not self._infrastructure_warning_emitted:
                    self._infrastructure_warning_emitted = True
                    try:
                        logger.warning(
                            "[RESERVATION_LEASE_RENEWAL_UNAVAILABLE] category=%s",
                            type(exc).__name__[:64],
                        )
                    except Exception:
                        pass
            return False
        except FingerprintReservationBatchRenewalError as exc:
            with self._lock:
                self._mark_lease_lost_locked(exc.result.status.value)
            return False
        except Exception as exc:
            with self._lock:
                self._mark_lease_lost_locked(type(exc).__name__)
            raise

    def _mark_lease_lost_locked(self, category: str | None = None) -> None:
        if self._state is ReservationLeaseState.ACTIVE:
            self._state = ReservationLeaseState.LEASE_LOST
            if category is not None:
                self._terminal_failure_category = category[:64]
            self._stop_event.set()

    def _heartbeat_loop(self) -> None:
        try:
            interval = self._configuration.reservation_heartbeat_interval_seconds
            assert interval is not None
            while not self._heartbeat_wait(interval):
                if not self.run_renewal_cycle():
                    if self.state is ReservationLeaseState.LEASE_LOST:
                        return
        except Exception as exc:
            with self._lock:
                self._mark_lease_lost_locked(type(exc).__name__)
            try:
                logger.error(
                    "[RESERVATION_LEASE_HEARTBEAT_FAILED] category=%s",
                    type(exc).__name__[:64],
                )
            except Exception:
                pass
        finally:
            with self._lock:
                if self._heartbeat_state is ReservationHeartbeatState.RUNNING:
                    self._mark_lease_lost_locked("HEARTBEAT_EXITED_UNEXPECTEDLY")
                self._heartbeat_state = ReservationHeartbeatState.STOPPED
