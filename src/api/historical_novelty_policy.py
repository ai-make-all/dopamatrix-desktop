"""Pure Historical Novelty policy contracts.

This module deliberately contains no database access.  Tenant-local Ledger storage,
historical fact retrieval, and Reservation mutation remain repository concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fingerprint_ledger import HistoricalExactLookupResult


class HistoricalNoveltyPolicyError(ValueError):
    """Base error for an invalid policy contract or factual input."""


class HistoricalNoveltyPolicyConfigurationError(HistoricalNoveltyPolicyError):
    """Raised when a policy configuration would imply unsafe semantics."""


class HistoricalPolicyMode(str, Enum):
    OFF = "OFF"
    OBSERVE = "OBSERVE"
    ADVISORY = "ADVISORY"
    ENFORCE = "ENFORCE"


class ReservationConflictMode(str, Enum):
    OFF = "OFF"
    ENFORCE = "ENFORCE"


class HistoricalScopeType(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    TENANT = "TENANT"
    PROJECT = "PROJECT"
    CAMPAIGN = "CAMPAIGN"


class HistoricalWindowKind(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    ALL_TIME = "ALL_TIME"
    DURATION = "DURATION"


class HistoricalEvidenceKind(str, Enum):
    NONE = "NONE"
    RENDERED = "RENDERED"
    PLANNED_ONLY = "PLANNED_ONLY"
    FAILED_ONLY = "FAILED_ONLY"
    PLANNED_AND_FAILED = "PLANNED_AND_FAILED"


class HistoricalDecisionAction(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_ADVISORY = "ALLOW_ADVISORY"
    ALLOW_OVERRIDE = "ALLOW_OVERRIDE"
    SKIP_HISTORICAL_MATCH = "SKIP_HISTORICAL_MATCH"


class ReservationConflictAction(str, Enum):
    ALLOW = "ALLOW"
    SKIP_RESERVATION_CONFLICT = "SKIP_RESERVATION_CONFLICT"


class PreviewIntent(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    AUTOMATIC_PREVIEW = "AUTOMATIC_PREVIEW"
    OPERATOR_PINNED_PREVIEW = "OPERATOR_PINNED_PREVIEW"


@dataclass(frozen=True)
class HistoricalPolicyScope:
    scope_type: HistoricalScopeType = HistoricalScopeType.UNAVAILABLE
    scope_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope_type, HistoricalScopeType):
            raise HistoricalNoveltyPolicyConfigurationError(
                "HISTORICAL_NOVELTY_SCOPE_TYPE_INVALID"
            )
        normalized_scope_id = self.scope_id.strip() if self.scope_id is not None else None
        if self.scope_type is HistoricalScopeType.UNAVAILABLE:
            if normalized_scope_id:
                raise HistoricalNoveltyPolicyConfigurationError(
                    "HISTORICAL_NOVELTY_SCOPE_UNAVAILABLE_HAS_ID"
                )
            object.__setattr__(self, "scope_id", None)
            return
        if not normalized_scope_id:
            raise HistoricalNoveltyPolicyConfigurationError(
                "HISTORICAL_NOVELTY_SCOPE_ID_REQUIRED"
            )
        object.__setattr__(self, "scope_id", normalized_scope_id)


@dataclass(frozen=True)
class HistoricalPolicyWindow:
    kind: HistoricalWindowKind = HistoricalWindowKind.UNSPECIFIED
    duration_seconds: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, HistoricalWindowKind):
            raise HistoricalNoveltyPolicyConfigurationError(
                "HISTORICAL_NOVELTY_WINDOW_KIND_INVALID"
            )
        if self.kind is HistoricalWindowKind.UNSPECIFIED:
            if self.duration_seconds is not None:
                raise HistoricalNoveltyPolicyConfigurationError(
                    "HISTORICAL_NOVELTY_UNSPECIFIED_DURATION_UNEXPECTED"
                )
            return
        if self.kind is HistoricalWindowKind.ALL_TIME:
            if self.duration_seconds is not None:
                raise HistoricalNoveltyPolicyConfigurationError(
                    "HISTORICAL_NOVELTY_ALL_TIME_DURATION_UNEXPECTED"
                )
            return
        if type(self.duration_seconds) is not int or self.duration_seconds <= 0:
            raise HistoricalNoveltyPolicyConfigurationError(
                "HISTORICAL_NOVELTY_DURATION_INVALID"
            )


@dataclass(frozen=True)
class HistoricalReuseIntent:
    allow_historical_reuse: bool = False
    reuse_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.allow_historical_reuse) is not bool:
            raise HistoricalNoveltyPolicyConfigurationError(
                "HISTORICAL_NOVELTY_REUSE_FLAG_INVALID"
            )
        normalized_reason = (
            self.reuse_reason.strip() if self.reuse_reason is not None else None
        )
        if self.allow_historical_reuse and not normalized_reason:
            raise HistoricalNoveltyPolicyConfigurationError(
                "HISTORICAL_NOVELTY_REUSE_REASON_REQUIRED"
            )
        if not self.allow_historical_reuse and normalized_reason:
            raise HistoricalNoveltyPolicyConfigurationError(
                "HISTORICAL_NOVELTY_REUSE_REASON_WITHOUT_OVERRIDE"
            )
        object.__setattr__(self, "reuse_reason", normalized_reason)


@dataclass(frozen=True)
class HistoricalNoveltyPolicyConfiguration:
    historical_policy_mode: HistoricalPolicyMode = HistoricalPolicyMode.OFF
    reservation_conflict_mode: ReservationConflictMode = ReservationConflictMode.OFF
    historical_scope: HistoricalPolicyScope = field(default_factory=HistoricalPolicyScope)
    historical_window: HistoricalPolicyWindow = field(default_factory=HistoricalPolicyWindow)

    def __post_init__(self) -> None:
        if not isinstance(self.historical_policy_mode, HistoricalPolicyMode):
            raise HistoricalNoveltyPolicyConfigurationError(
                "HISTORICAL_NOVELTY_MODE_INVALID"
            )
        if not isinstance(self.reservation_conflict_mode, ReservationConflictMode):
            raise HistoricalNoveltyPolicyConfigurationError(
                "RESERVATION_CONFLICT_MODE_INVALID"
            )
        if not isinstance(self.historical_scope, HistoricalPolicyScope):
            raise HistoricalNoveltyPolicyConfigurationError(
                "HISTORICAL_NOVELTY_SCOPE_INVALID"
            )
        if not isinstance(self.historical_window, HistoricalPolicyWindow):
            raise HistoricalNoveltyPolicyConfigurationError(
                "HISTORICAL_NOVELTY_WINDOW_INVALID"
            )
        if (
            self.historical_policy_mode is HistoricalPolicyMode.ENFORCE
            and self.historical_scope.scope_type is HistoricalScopeType.UNAVAILABLE
        ):
            raise HistoricalNoveltyPolicyConfigurationError(
                "HISTORICAL_NOVELTY_ENFORCE_SCOPE_UNAVAILABLE"
            )
        if (
            self.historical_policy_mode is HistoricalPolicyMode.ENFORCE
            and self.historical_window.kind is HistoricalWindowKind.UNSPECIFIED
        ):
            raise HistoricalNoveltyPolicyConfigurationError(
                "HISTORICAL_NOVELTY_ENFORCE_WINDOW_UNAVAILABLE"
            )


@dataclass(frozen=True)
class HistoricalNoveltyDecision:
    action: HistoricalDecisionAction
    evidence_kind: HistoricalEvidenceKind
    identity_exists: bool
    historical_occurrence_count: int
    planned_count: int
    rendered_count: int
    failed_count: int
    history_complete_since: datetime | None = None


class HistoricalNoveltyPolicy:
    """Evaluate already-retrieved Ledger facts without SQL or side effects."""

    @staticmethod
    def _classify_evidence(
        facts: HistoricalExactLookupResult,
    ) -> HistoricalEvidenceKind:
        counts = (
            facts.historical_occurrence_count,
            facts.planned_count,
            facts.rendered_count,
            facts.failed_count,
        )
        if any(type(count) is not int or count < 0 for count in counts):
            raise HistoricalNoveltyPolicyError("HISTORICAL_NOVELTY_FACTS_INVALID")
        lifecycle_count = facts.planned_count + facts.rendered_count + facts.failed_count
        if (
            lifecycle_count != facts.historical_occurrence_count
            or facts.historical_match != (facts.historical_occurrence_count > 0)
            or (not facts.identity_exists and facts.historical_occurrence_count > 0)
        ):
            raise HistoricalNoveltyPolicyError("HISTORICAL_NOVELTY_FACTS_INVALID")
        if facts.rendered_count > 0:
            return HistoricalEvidenceKind.RENDERED
        if facts.planned_count > 0 and facts.failed_count > 0:
            return HistoricalEvidenceKind.PLANNED_AND_FAILED
        if facts.planned_count > 0:
            return HistoricalEvidenceKind.PLANNED_ONLY
        if facts.failed_count > 0:
            return HistoricalEvidenceKind.FAILED_ONLY
        return HistoricalEvidenceKind.NONE

    def evaluate(
        self,
        facts: HistoricalExactLookupResult,
        configuration: HistoricalNoveltyPolicyConfiguration,
        *,
        reuse_intent: HistoricalReuseIntent | None = None,
        history_complete_since: datetime | None = None,
    ) -> HistoricalNoveltyDecision:
        evidence_kind = self._classify_evidence(facts)
        intent = reuse_intent or HistoricalReuseIntent()

        if configuration.historical_policy_mode in {
            HistoricalPolicyMode.OFF,
            HistoricalPolicyMode.OBSERVE,
        }:
            action = HistoricalDecisionAction.ALLOW
        elif evidence_kind is not HistoricalEvidenceKind.RENDERED:
            action = HistoricalDecisionAction.ALLOW
        elif intent.allow_historical_reuse:
            action = HistoricalDecisionAction.ALLOW_OVERRIDE
        elif configuration.historical_policy_mode is HistoricalPolicyMode.ADVISORY:
            action = HistoricalDecisionAction.ALLOW_ADVISORY
        else:
            action = HistoricalDecisionAction.SKIP_HISTORICAL_MATCH

        return HistoricalNoveltyDecision(
            action=action,
            evidence_kind=evidence_kind,
            identity_exists=facts.identity_exists,
            historical_occurrence_count=facts.historical_occurrence_count,
            planned_count=facts.planned_count,
            rendered_count=facts.rendered_count,
            failed_count=facts.failed_count,
            history_complete_since=history_complete_since,
        )

    @staticmethod
    def evaluate_reservation_conflict(
        conflict: bool,
        configuration: HistoricalNoveltyPolicyConfiguration,
    ) -> ReservationConflictAction:
        if (
            conflict
            and configuration.reservation_conflict_mode
            is ReservationConflictMode.ENFORCE
        ):
            return ReservationConflictAction.SKIP_RESERVATION_CONFLICT
        return ReservationConflictAction.ALLOW
