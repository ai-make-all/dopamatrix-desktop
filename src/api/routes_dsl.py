"""
src/api/routes_dsl.py
——————————————————————————————————————————————————————————————————————
Story DSL 接口集  (Phase 4.1 → Phase 5.2)

端点
─────────────────────────────────────────────────────────────────────
  POST  /tasks/draft-blueprint 【Phase 9.2】战术板同步起草：
                             DirectorNode.draft_blueprint，返回融合 JSON
                            （timeline + script_data，供前端点亮）。

  POST  /tasks/enhance-prompt 【Phase 9.4】魔法扩写：
                             OpenAIProvider + prompt_enhance.jinja，
                             返回 enhanced_prompt（BYOK 兼容）。

  POST  /tasks/submit-dsl    【Phase 5.2 升级】全链路渲染入口：
                             DSL 解析 + 蓝图适配 + 后台渲染三合一。
                             接口立即返回 202（含 CompilationPlan 快照
                             + task_id），FFmpeg 渲染通过 BackgroundTasks
                             异步执行，进度由 WS 事件总线推送。

  POST  /tasks/render-dsl    【Phase 5.1】纯渲染触发端点：直接接收
                             RenderDSLRequest（含渲染配置字段），
                             与 submit-dsl 共用同一 render_worker。

内部工具函数
─────────────────────────────────────────────────────────────────────
  render_worker(plan, task_id, ...)   — 后台渲染主 Worker
  _run_compositor(compositor, ctx)    — 底层 FFmpeg 调用封装（异常日志）
"""

from __future__ import annotations

import hashlib
import heapq
import json
import logging
import os
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from itertools import product
from math import prod
from typing import Any, Callable, Optional, Sequence

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.exc import (
    DisconnectionError,
    InterfaceError,
    OperationalError,
    TimeoutError as SQLAlchemyTimeoutError,
)
from sqlalchemy.orm import Session, sessionmaker

from .database import (
    canonical_tenant_id,
    get_db,
    get_tenant_engine,
    request_tenant_id,
)
from .dsl_adapter import compile_plan_to_timeline
from src.api.ws_manager import manager as ws_manager
from .dsl_parser import (
    DSLParserNode,
    MainVisualCandidate,
    MainVisualSelectionMismatch,
    is_main_visual_asset_type,
    normalize_file_hash,
)
from .models import LocalAsset, TaskHistory
from .fingerprint_ledger import (
    LEDGER_DIGEST_ALGORITHM,
    FingerprintIdentityRecord,
    FingerprintLedgerError,
    FingerprintLedgerRepository,
    FingerprintOccurrenceRecord,
    HistoricalExactLookupResult,
)
from .historical_novelty_policy import (
    HistoricalDecisionAction,
    HistoricalEvidenceKind,
    HistoricalNoveltyPolicy,
    HistoricalNoveltyPolicyConfiguration,
    HistoricalPolicyMode,
    PreviewIntent,
)
from .planner_reservation import (
    PlannerReservationAuthorityLost,
    PlannerReservationBinding,
    PlannerReservationController,
    PlannerReservationDecision,
    PlannerReservationError,
    PlannerReservationExecutionBinding,
)
from .schemas import (
    CompilationPlan,
    CompilationPlanSummary,
    DSLBeatNode,
    DSLSubmitResponse,
    DraftBlueprintRequest,
    EnhancePromptRequest,
    RenderDSLAck,
    RenderDSLRequest,
    StoryDSLPayload,
)
from src.services.llm_provider import OpenAIProvider
from src.utils.prompt_loader import prompt_loader
from src.core.context import WorkflowContext
from src.core.logger import logger as fingerprint_logger
from src.nodes.compositor import FFmpegCompositorNode
from src.nodes.cover_node import CoverNode
from src.nodes.director_node import DirectorNode
from src.nodes.subtitle import SubtitleNode
from src.nodes.tts_node import TTSNode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["Story DSL"])


def _parse_plan_from_db(tenant_id: str, payload: StoryDSLPayload) -> CompilationPlan:
    """在 Worker 线程内打开租户库会话，执行 DSLParserNode。"""
    _tenant_engine = get_tenant_engine(tenant_id)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_tenant_engine)
    with _SessionLocal() as db:
        return DSLParserNode(db).parse_and_resolve(payload)


def _fetch_available_tags(tenant_id: str) -> list[str]:
    """
    从租户素材库查询所有 LocalAsset 的不重复标签列表。

    供 DirectorNode.draft_blueprint 注入 Jinja 模板，约束 LLM 的
    semantic_tags 只能从库内真实存在的标签中挑选，杜绝幻觉捏造。
    """
    _engine = get_tenant_engine(tenant_id)
    _Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    tag_set: set[str] = set()
    try:
        with _Session() as db:
            rows = (
                db.query(LocalAsset.tags)
                .filter(
                    LocalAsset.is_deleted.is_(False),
                    LocalAsset.tags.isnot(None),
                )
                .all()
            )
            for (tags,) in rows:
                if isinstance(tags, list):
                    tag_set.update(
                        t for t in tags if isinstance(t, str) and t.strip()
                    )
    except Exception:
        logger.warning(
            "[routes_dsl] _fetch_available_tags 查询失败，返回空标签库", exc_info=True
        )
    result = sorted(tag_set)
    logger.debug("[routes_dsl] _fetch_available_tags tenant=%s tags=%d", tenant_id, len(result))
    return result


def _is_blind_fission(payload: RenderDSLRequest) -> bool:
    """极速闭眼裂变：batch≥1 + 非空 prompt + 空 timeline。"""
    return (
        payload.batch_size >= 1
        and bool(payload.prompt and payload.prompt.strip())
        and len(payload.timeline) == 0
    )


def _authoritative_request_tenant(
    payload: RenderDSLRequest,
    request: Optional[Request],
) -> str:
    """Resolve one tenant authority and reject explicit split-tenant requests."""
    authoritative = (
        request_tenant_id(request)
        if request is not None
        else canonical_tenant_id(payload.tenant_id)
    )
    if (
        payload.tenant_id is not None
        and canonical_tenant_id(payload.tenant_id) != authoritative
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="TENANT_AUTHORITY_MISMATCH",
        )
    return authoritative


def _requests_exact_main_visual(payload: RenderDSLRequest) -> bool:
    """Return the explicit request policy; never infer it from mode or timeline."""
    return payload.variant_planning_policy == "exact_main_visual"


def _requests_exact_main_visual_balanced(payload: RenderDSLRequest) -> bool:
    """Return whether the request explicitly selects balanced exact planning."""
    return payload.variant_planning_policy == "exact_main_visual_balanced"


def _requests_authoritative_main_visual(payload: RenderDSLRequest) -> bool:
    """Return whether request-time preview setup is required by either exact policy."""
    return _requests_exact_main_visual(payload) or _requests_exact_main_visual_balanced(
        payload
    )


def _guard_pre_planner_policy(
    payload: RenderDSLRequest,
    *,
    flow: str,
    is_blind: bool = False,
) -> None:
    """Keep authoritative exact planning confined to populated submit-dsl requests."""
    if (
        payload.historical_novelty_mode != _HISTORICAL_MODE_OFF
        and not _requests_authoritative_main_visual(payload)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="HISTORICAL_NOVELTY_REQUIRES_AUTHORITATIVE_PLANNING",
        )
    if not _requests_authoritative_main_visual(payload):
        return
    policy_code = payload.variant_planning_policy.upper()
    if is_blind:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{policy_code}_UNSUPPORTED_FOR_BLIND: "
                "Blind planning is not implemented in INV-001 Phase 3A."
            ),
        )
    if flow == "submit_dsl":
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            f"{policy_code}_UNSUPPORTED_FOR_{flow.upper().replace('-', '_')}: "
            "this endpoint preserves its legacy planning semantics."
        ),
    )


@dataclass(frozen=True)
class _ChildExecution:
    """Internal identity envelope for one submitted render execution."""

    child_index: int
    execution_id: str
    file_sid: str


_MainVisualFingerprint = tuple[tuple[int, str, int, str], ...]

_MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE = "main_visual_planning"
_MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION = 1
_MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM = "md5"
_VARIANT_FINGERPRINT_EVENT = "VariantFingerprint"
_VARIANT_FINGERPRINT_PHASE = "authoritative_worker_start"
_MAX_LOGGED_FINGERPRINT_COMPONENTS = 32
_MAX_LOGGED_BEAT_IDENTITY_CHARS = 128
_MAX_LOGGED_SOURCE_HASH_CHARS = 128

_PLANNING_REQUEST_SATISFIED = "REQUEST_SATISFIED"
_PLANNING_TRUE_SPACE_EXHAUSTED = "TRUE_SPACE_EXHAUSTED"
_PLANNING_SEARCH_LIMIT_REACHED = "PLANNING_SEARCH_LIMIT_REACHED"
_PLANNING_RESERVATION_CONFLICT_EXHAUSTED = "RESERVATION_CONFLICT_EXHAUSTED"
_RESERVATION_AUTHORITY_LOST = "RESERVATION_AUTHORITY_LOST"
_RESERVATION_TERMINAL_PERSIST_FAILED = "RESERVATION_TERMINAL_PERSIST_FAILED"
_EXACT_MAIN_VISUAL_SEARCH_BUDGET = 4096

_COVERAGE_DIAGNOSTICS_TYPE = "balanced_axis_coverage"
_COVERAGE_DIAGNOSTICS_VERSION = 1
_BALANCED_VARIANT_PLANNING_POLICY = "exact_main_visual_balanced"
_BALANCED_COVERAGE_SUMMARY_EVENT = "BalancedCoverageSummary"
_COVERAGE_FIXED_BY_CAPACITY = "FIXED_BY_CAPACITY"
_COVERAGE_VARIABLE_BALANCED = "VARIABLE_BALANCED"
_COVERAGE_VARIABLE_TARGET_NOT_MET = "VARIABLE_TARGET_NOT_MET"

_HISTORICAL_NOVELTY_DIAGNOSTICS_TYPE = "historical_novelty"
_HISTORICAL_NOVELTY_DIAGNOSTICS_VERSION = 1
_HISTORICAL_NOVELTY_SUMMARY_EVENT = "HistoricalNoveltySummary"
_HISTORICAL_MODE_OFF = HistoricalPolicyMode.OFF.value
_HISTORICAL_MODE_OBSERVE = HistoricalPolicyMode.OBSERVE.value
_HISTORICAL_MODE_ADVISORY = HistoricalPolicyMode.ADVISORY.value


@dataclass(frozen=True)
class _CoverageHistogramEntryV1:
    normalized_file_hash: str
    asset_id: int
    count: int


@dataclass(frozen=True)
class _CoverageBeatDiagnosticsV1:
    beat_index: int
    beat_identity: str
    role: str
    pool_size: int
    selected_histogram: tuple[_CoverageHistogramEntryV1, ...]
    selected_count: int
    unique_used: int
    unused_count: int
    ideal_floor: Optional[int]
    ideal_ceil: Optional[int]
    max_min_gap: Optional[int]
    classification: Optional[str]


@dataclass(frozen=True)
class _CoverageRejectionCountsV1:
    materialization_mismatch_count: int
    invalid_plan_count: int
    duplicate_fingerprint_reject_count: int


@dataclass(frozen=True)
class _CoverageDiagnosticsV1:
    diagnostics_type: str
    version: int
    variant_planning_policy: str
    requested_count: int
    accepted_count: int
    candidate_space_size: int
    search_budget: int
    examined_count: int
    proposal_attempted_count: int
    termination_reason: str
    preview_seeded: bool
    preview_child_index: Optional[int]
    preview_fingerprint_digest: Optional[str]
    accepted_fingerprint_digests: tuple[str, ...]
    rejection_counts: _CoverageRejectionCountsV1
    beats: tuple[_CoverageBeatDiagnosticsV1, ...]


@dataclass(frozen=True)
class _HistoricalNoveltyDiagnosticsV1:
    diagnostics_type: str
    version: int
    historical_policy_mode: str
    policy_scope_type: str
    policy_scope_id: Optional[str]
    policy_window_kind: str
    policy_window_duration_seconds: Optional[int]
    history_complete_since: Optional[datetime]
    candidate_checks: int
    lookup_successes: int
    lookup_failures: int
    identity_matches: int
    historical_occurrence_matches: int
    identity_only_matches: int
    rendered_matches: int
    planned_only_matches: int
    failed_only_matches: int
    planned_and_failed_matches: int
    no_history_matches: int
    advisory_count: int
    reuse_intent_count: int
    actual_override_count: int
    historical_rejection_count: int
    reservation_conflict_count: int
    accepted_after_historical_check_count: int
    accepted_with_lookup_unknown_count: int
    preview_checked: bool
    preview_intent: str


@dataclass(frozen=True)
class _VariantPlanningResult:
    plans: tuple[CompilationPlan, ...]
    fingerprints: tuple[_MainVisualFingerprint, ...]
    examined_combinations: int
    candidate_space_size: int
    termination_reason: str
    warning_codes: tuple[str, ...]
    coverage_diagnostics: Optional[_CoverageDiagnosticsV1] = None
    historical_novelty_diagnostics: Optional[_HistoricalNoveltyDiagnosticsV1] = None
    reservation_bindings: tuple[PlannerReservationBinding, ...] = ()


@dataclass(frozen=True)
class _ChildWork:
    execution: _ChildExecution
    authoritative_plan: Optional[CompilationPlan] = None
    visual_fingerprint: Optional[_MainVisualFingerprint] = None


@dataclass(frozen=True)
class _MainVisualPlanningFingerprintContract:
    fingerprint_type: str
    fingerprint_version: int
    source_hash_algorithm: str
    fingerprint_digest: str
    components: _MainVisualFingerprint
    canonical_bytes: bytes


class _HistoricalObservationOutcome(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


def _exact_main_visual_fingerprint(
    plan: CompilationPlan,
) -> _MainVisualFingerprint:
    """Validate and fingerprint the ordered layer-0 main visual sequence."""
    if not plan.beats:
        raise ValueError("MAIN_VISUAL_PLAN_INVALID: plan has no Beats")

    fingerprint: list[tuple[int, str, int, str]] = []
    for beat_index, beat in enumerate(plan.beats):
        main_layers = [layer for layer in beat.layers if layer.layer_index == 0]
        if len(main_layers) != 1:
            raise ValueError(
                "MAIN_VISUAL_PLAN_INVALID: Beat "
                f"{beat.beat!r} has {len(main_layers)} layer-0 assets"
            )
        main_layer = main_layers[0]
        if not is_main_visual_asset_type(main_layer.asset_type):
            raise ValueError(
                "MAIN_VISUAL_PLAN_INVALID: Beat "
                f"{beat.beat!r} layer 0 is not a main-X asset"
            )
        normalized_hash = normalize_file_hash(main_layer.file_hash)
        if not normalized_hash:
            raise ValueError(
                f"MAIN_VISUAL_PLAN_INVALID: Beat {beat.beat!r} has no stable file_hash"
            )
        beat_identity = str(beat.beat).strip()
        if not beat_identity:
            raise ValueError("MAIN_VISUAL_PLAN_INVALID: Beat identity is empty")
        fingerprint.append((beat_index, beat_identity, 0, normalized_hash))

    return tuple(fingerprint)


def _main_visual_planning_canonical_payload(
    fingerprint: _MainVisualFingerprint,
) -> dict[str, Any]:
    """Return the canonical logical payload for a validated INV fingerprint."""
    return {
        "fingerprint_type": _MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE,
        "fingerprint_version": _MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION,
        "source_hash_algorithm": _MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM,
        "beats": [
            {
                "beat_index": beat_index,
                "beat_identity": beat_identity,
                "layer_index": layer_index,
                "normalized_file_hash": normalized_file_hash,
            }
            for beat_index, beat_identity, layer_index, normalized_file_hash
            in fingerprint
        ],
    }


def _main_visual_planning_canonical_bytes(
    fingerprint: _MainVisualFingerprint,
) -> bytes:
    """Serialize a validated INV fingerprint as deterministic UTF-8 JSON."""
    payload = _main_visual_planning_canonical_payload(fingerprint)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _main_visual_planning_fingerprint_contract(
    fingerprint: _MainVisualFingerprint,
) -> _MainVisualPlanningFingerprintContract:
    """Build the additive versioned digest contract for a validated INV tuple."""
    canonical_bytes = _main_visual_planning_canonical_bytes(fingerprint)
    return _MainVisualPlanningFingerprintContract(
        fingerprint_type=_MAIN_VISUAL_PLANNING_FINGERPRINT_TYPE,
        fingerprint_version=_MAIN_VISUAL_PLANNING_FINGERPRINT_VERSION,
        source_hash_algorithm=_MAIN_VISUAL_PLANNING_SOURCE_HASH_ALGORITHM,
        fingerprint_digest=hashlib.sha256(canonical_bytes).hexdigest(),
        components=fingerprint,
        canonical_bytes=canonical_bytes,
    )


def _main_visual_fingerprint_identity_record(
    fingerprint: _MainVisualFingerprint,
) -> FingerprintIdentityRecord:
    """Adapt the one authoritative FP-001 contract to Ledger identity input."""
    contract = _main_visual_planning_fingerprint_contract(fingerprint)
    return FingerprintIdentityRecord(
        fingerprint_type=contract.fingerprint_type,
        fingerprint_version=contract.fingerprint_version,
        fingerprint_digest=contract.fingerprint_digest,
        digest_algorithm=LEDGER_DIGEST_ALGORITHM,
        source_hash_algorithm=contract.source_hash_algorithm,
        canonical_payload=contract.canonical_bytes.decode("utf-8"),
    )


_HistoricalExactLookup = Callable[
    [FingerprintIdentityRecord],
    HistoricalExactLookupResult,
]
_HistoricalSessionFactory = Callable[[], Session]
_HISTORICAL_LOOKUP_INFRASTRUCTURE_ERRORS = (
    OperationalError,
    InterfaceError,
    DisconnectionError,
    SQLAlchemyTimeoutError,
)


class _HistoricalNoveltyObserver:
    """Observe accepted-eligible FP-001 candidates without affecting selection."""

    def __init__(
        self,
        lookup_historical_exact: _HistoricalExactLookup,
        historical_policy_mode: str,
    ):
        if historical_policy_mode not in {
            _HISTORICAL_MODE_OBSERVE,
            _HISTORICAL_MODE_ADVISORY,
        }:
            raise ValueError("HISTORICAL_NOVELTY_RUNTIME_MODE_UNSUPPORTED")
        self._lookup_historical_exact = lookup_historical_exact
        self._configuration = HistoricalNoveltyPolicyConfiguration(
            historical_policy_mode=HistoricalPolicyMode(historical_policy_mode),
        )
        self._policy = HistoricalNoveltyPolicy()
        self._warning_emitted = False
        self.candidate_checks = 0
        self.lookup_successes = 0
        self.lookup_failures = 0
        self.identity_matches = 0
        self.historical_occurrence_matches = 0
        self.identity_only_matches = 0
        self.rendered_matches = 0
        self.planned_only_matches = 0
        self.failed_only_matches = 0
        self.planned_and_failed_matches = 0
        self.no_history_matches = 0
        self.advisory_count = 0
        self.reservation_conflict_count = 0
        self.accepted_after_historical_check_count = 0
        self.accepted_with_lookup_unknown_count = 0
        self.preview_checked = False
        self.preview_intent = PreviewIntent.UNSPECIFIED

    def observe(
        self,
        fingerprint: _MainVisualFingerprint,
        *,
        is_preview: bool = False,
        preview_intent: PreviewIntent = PreviewIntent.UNSPECIFIED,
    ) -> _HistoricalObservationOutcome:
        """Record candidate facts, deferring acceptance counters to the planner."""
        if not isinstance(preview_intent, PreviewIntent):
            raise ValueError("HISTORICAL_NOVELTY_PREVIEW_INTENT_INVALID")
        self.candidate_checks += 1
        if is_preview:
            self.preview_checked = True
            self.preview_intent = preview_intent

        identity_record = _main_visual_fingerprint_identity_record(fingerprint)
        try:
            facts = self._lookup_historical_exact(identity_record)
        except FingerprintLedgerError:
            raise
        except _HISTORICAL_LOOKUP_INFRASTRUCTURE_ERRORS as exc:
            self.lookup_failures += 1
            if not self._warning_emitted:
                self._warning_emitted = True
                try:
                    fingerprint_logger.warning(
                        "[HISTORICAL_NOVELTY_LOOKUP_FAILED] "
                        f"mode={self._configuration.historical_policy_mode.value} "
                        "category=database_read_unavailable "
                        f"error={type(exc).__name__[:64]}"
                    )
                except Exception:
                    pass
            return _HistoricalObservationOutcome.UNKNOWN

        decision = self._policy.evaluate(facts, self._configuration)
        self.lookup_successes += 1
        if facts.identity_exists:
            self.identity_matches += 1
        if facts.historical_match:
            self.historical_occurrence_matches += 1
        elif facts.identity_exists:
            self.identity_only_matches += 1

        evidence_counters = {
            HistoricalEvidenceKind.RENDERED: "rendered_matches",
            HistoricalEvidenceKind.PLANNED_ONLY: "planned_only_matches",
            HistoricalEvidenceKind.FAILED_ONLY: "failed_only_matches",
            HistoricalEvidenceKind.PLANNED_AND_FAILED: "planned_and_failed_matches",
        }
        counter_name = evidence_counters.get(decision.evidence_kind)
        if counter_name is not None:
            setattr(self, counter_name, getattr(self, counter_name) + 1)
        elif not facts.identity_exists:
            self.no_history_matches += 1
        if decision.action is HistoricalDecisionAction.ALLOW_ADVISORY:
            self.advisory_count += 1
        return _HistoricalObservationOutcome.KNOWN

    def mark_accepted(self, outcome: _HistoricalObservationOutcome) -> None:
        if outcome is _HistoricalObservationOutcome.KNOWN:
            self.accepted_after_historical_check_count += 1
        elif outcome is _HistoricalObservationOutcome.UNKNOWN:
            self.accepted_with_lookup_unknown_count += 1
        else:
            raise ValueError("HISTORICAL_NOVELTY_OBSERVATION_OUTCOME_INVALID")

    def mark_reservation_conflict(self) -> None:
        self.reservation_conflict_count += 1

    def diagnostics(self) -> _HistoricalNoveltyDiagnosticsV1:
        return _HistoricalNoveltyDiagnosticsV1(
            diagnostics_type=_HISTORICAL_NOVELTY_DIAGNOSTICS_TYPE,
            version=_HISTORICAL_NOVELTY_DIAGNOSTICS_VERSION,
            historical_policy_mode=self._configuration.historical_policy_mode.value,
            policy_scope_type=self._configuration.historical_scope.scope_type.value,
            policy_scope_id=self._configuration.historical_scope.scope_id,
            policy_window_kind=self._configuration.historical_window.kind.value,
            policy_window_duration_seconds=(
                self._configuration.historical_window.duration_seconds
            ),
            history_complete_since=None,
            candidate_checks=self.candidate_checks,
            lookup_successes=self.lookup_successes,
            lookup_failures=self.lookup_failures,
            identity_matches=self.identity_matches,
            historical_occurrence_matches=self.historical_occurrence_matches,
            identity_only_matches=self.identity_only_matches,
            rendered_matches=self.rendered_matches,
            planned_only_matches=self.planned_only_matches,
            failed_only_matches=self.failed_only_matches,
            planned_and_failed_matches=self.planned_and_failed_matches,
            no_history_matches=self.no_history_matches,
            advisory_count=self.advisory_count,
            reuse_intent_count=0,
            actual_override_count=0,
            historical_rejection_count=0,
            reservation_conflict_count=self.reservation_conflict_count,
            accepted_after_historical_check_count=(
                self.accepted_after_historical_check_count
            ),
            accepted_with_lookup_unknown_count=(
                self.accepted_with_lookup_unknown_count
            ),
            preview_checked=self.preview_checked,
            preview_intent=self.preview_intent.value,
        )


def _lookup_historical_exact_in_new_session(
    historical_session_factory: _HistoricalSessionFactory,
    identity_record: FingerprintIdentityRecord,
) -> HistoricalExactLookupResult:
    """Read Ledger facts in one short-lived tenant-bound Session."""
    with historical_session_factory() as historical_db:
        return FingerprintLedgerRepository(historical_db).lookup_historical_exact(
            identity_record
        )


def _historical_novelty_observer(
    historical_session_factory: _HistoricalSessionFactory,
    historical_policy_mode: str,
) -> Optional[_HistoricalNoveltyObserver]:
    """Create no observer and perform no Ledger read when runtime mode is OFF."""
    if historical_policy_mode == _HISTORICAL_MODE_OFF:
        return None
    return _HistoricalNoveltyObserver(
        lambda identity_record: _lookup_historical_exact_in_new_session(
            historical_session_factory,
            identity_record,
        ),
        historical_policy_mode,
    )


def _historical_novelty_diagnostics_v1_payload(
    diagnostics: _HistoricalNoveltyDiagnosticsV1,
) -> dict[str, Any]:
    """Validate and serialize the bounded HistoricalNoveltyDiagnosticsV1 contract."""
    if (
        diagnostics.diagnostics_type != _HISTORICAL_NOVELTY_DIAGNOSTICS_TYPE
        or diagnostics.version != _HISTORICAL_NOVELTY_DIAGNOSTICS_VERSION
        or diagnostics.historical_policy_mode
        not in {_HISTORICAL_MODE_OBSERVE, _HISTORICAL_MODE_ADVISORY}
        or diagnostics.policy_scope_type != "UNAVAILABLE"
        or diagnostics.policy_scope_id is not None
        or diagnostics.policy_window_kind != "UNSPECIFIED"
        or diagnostics.policy_window_duration_seconds is not None
        or diagnostics.history_complete_since is not None
    ):
        raise ValueError("HISTORICAL_NOVELTY_DIAGNOSTICS_IDENTITY_MISMATCH")
    counters = (
        diagnostics.candidate_checks,
        diagnostics.lookup_successes,
        diagnostics.lookup_failures,
        diagnostics.identity_matches,
        diagnostics.historical_occurrence_matches,
        diagnostics.identity_only_matches,
        diagnostics.rendered_matches,
        diagnostics.planned_only_matches,
        diagnostics.failed_only_matches,
        diagnostics.planned_and_failed_matches,
        diagnostics.no_history_matches,
        diagnostics.advisory_count,
        diagnostics.reuse_intent_count,
        diagnostics.actual_override_count,
        diagnostics.historical_rejection_count,
        diagnostics.reservation_conflict_count,
        diagnostics.accepted_after_historical_check_count,
        diagnostics.accepted_with_lookup_unknown_count,
    )
    if any(type(value) is not int or value < 0 for value in counters):
        raise ValueError("HISTORICAL_NOVELTY_DIAGNOSTICS_COUNTER_INVALID")
    classified_successes = (
        diagnostics.rendered_matches
        + diagnostics.planned_only_matches
        + diagnostics.failed_only_matches
        + diagnostics.planned_and_failed_matches
        + diagnostics.identity_only_matches
        + diagnostics.no_history_matches
    )
    if (
        diagnostics.candidate_checks
        != diagnostics.lookup_successes + diagnostics.lookup_failures
        or diagnostics.lookup_successes != classified_successes
        or diagnostics.identity_matches
        != diagnostics.historical_occurrence_matches
        + diagnostics.identity_only_matches
        or diagnostics.accepted_after_historical_check_count
        > diagnostics.lookup_successes
        or diagnostics.accepted_with_lookup_unknown_count
        > diagnostics.lookup_failures
        or diagnostics.candidate_checks
        != diagnostics.accepted_after_historical_check_count
        + diagnostics.accepted_with_lookup_unknown_count
        + diagnostics.reservation_conflict_count
        or diagnostics.advisory_count > diagnostics.rendered_matches
        or diagnostics.reuse_intent_count != 0
        or diagnostics.actual_override_count != 0
        or diagnostics.historical_rejection_count != 0
    ):
        raise ValueError("HISTORICAL_NOVELTY_DIAGNOSTICS_COUNTER_MISMATCH")
    if diagnostics.preview_checked:
        if diagnostics.preview_intent not in {
            intent.value for intent in PreviewIntent
        }:
            raise ValueError("HISTORICAL_NOVELTY_DIAGNOSTICS_PREVIEW_MISMATCH")
    elif diagnostics.preview_intent != PreviewIntent.UNSPECIFIED.value:
        raise ValueError("HISTORICAL_NOVELTY_DIAGNOSTICS_PREVIEW_MISMATCH")

    payload = {
        "type": diagnostics.diagnostics_type,
        "version": diagnostics.version,
        "historical_policy_mode": diagnostics.historical_policy_mode,
        "policy_scope_type": diagnostics.policy_scope_type,
        "policy_scope_id": diagnostics.policy_scope_id,
        "policy_window_kind": diagnostics.policy_window_kind,
        "policy_window_duration_seconds": diagnostics.policy_window_duration_seconds,
        "history_complete_since": None,
        "candidate_checks": diagnostics.candidate_checks,
        "lookup_successes": diagnostics.lookup_successes,
        "lookup_failures": diagnostics.lookup_failures,
        "identity_matches": diagnostics.identity_matches,
        "historical_occurrence_matches": diagnostics.historical_occurrence_matches,
        "identity_only_matches": diagnostics.identity_only_matches,
        "rendered_matches": diagnostics.rendered_matches,
        "planned_only_matches": diagnostics.planned_only_matches,
        "failed_only_matches": diagnostics.failed_only_matches,
        "planned_and_failed_matches": diagnostics.planned_and_failed_matches,
        "no_history_matches": diagnostics.no_history_matches,
        "advisory_count": diagnostics.advisory_count,
        "reuse_intent_count": diagnostics.reuse_intent_count,
        "actual_override_count": diagnostics.actual_override_count,
        "historical_rejection_count": diagnostics.historical_rejection_count,
        "reservation_conflict_count": diagnostics.reservation_conflict_count,
        "accepted_after_historical_check_count": (
            diagnostics.accepted_after_historical_check_count
        ),
        "accepted_with_lookup_unknown_count": (
            diagnostics.accepted_with_lookup_unknown_count
        ),
        "preview_checked": diagnostics.preview_checked,
        "preview_intent": diagnostics.preview_intent,
    }
    json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return payload


def _validated_historical_novelty_diagnostics_payload(
    diagnostics: _HistoricalNoveltyDiagnosticsV1,
    planning_result: _VariantPlanningResult,
    historical_policy_mode: str,
) -> dict[str, Any]:
    payload = _historical_novelty_diagnostics_v1_payload(diagnostics)
    if (
        diagnostics.historical_policy_mode != historical_policy_mode
        or diagnostics.candidate_checks
        != len(planning_result.plans) + diagnostics.reservation_conflict_count
        or diagnostics.accepted_after_historical_check_count
        + diagnostics.accepted_with_lookup_unknown_count
        != len(planning_result.plans)
    ):
        raise ValueError("HISTORICAL_NOVELTY_COORDINATOR_CONTRACT_MISMATCH")
    return payload


def _emit_historical_novelty_summary(
    task_id: str,
    diagnostics_payload: dict[str, Any],
) -> None:
    """Emit one bounded task-level summary without affecting product execution."""
    try:
        fingerprint_logger.info(
            "[HistoricalNoveltySummary] "
            + json.dumps(
                {
                    "event": _HISTORICAL_NOVELTY_SUMMARY_EVENT,
                    "task_id": task_id,
                    "historical_novelty_diagnostics": diagnostics_payload,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    except Exception:
        pass


_FINGERPRINT_LEDGER_PROVENANCE = "coordinator_authoritative_fp001"


def _fingerprint_ledger_occurrence_record(
    work: _ChildWork,
    task_id: str,
    lifecycle_event: str,
) -> FingerprintOccurrenceRecord:
    """Build durable Ledger input only from a coordinator-approved FP-001 tuple."""
    if work.visual_fingerprint is None:
        raise ValueError("FINGERPRINT_LEDGER_AUTHORITATIVE_FINGERPRINT_MISSING")
    contract = _main_visual_planning_fingerprint_contract(work.visual_fingerprint)
    return FingerprintOccurrenceRecord(
        fingerprint_type=contract.fingerprint_type,
        fingerprint_version=contract.fingerprint_version,
        fingerprint_digest=contract.fingerprint_digest,
        digest_algorithm=LEDGER_DIGEST_ALGORITHM,
        source_hash_algorithm=contract.source_hash_algorithm,
        canonical_payload=contract.canonical_bytes.decode("utf-8"),
        task_id=task_id,
        execution_id=work.execution.execution_id,
        child_index=work.execution.child_index,
        lifecycle_event=lifecycle_event,
        provenance=_FINGERPRINT_LEDGER_PROVENANCE,
    )


def _record_fingerprint_ledger_records(
    db: Session,
    records: Sequence[FingerprintOccurrenceRecord],
) -> int:
    """Record shadow occurrences in a caller-owned tenant transaction."""
    return FingerprintLedgerRepository(db).record_occurrences(records)


def _record_fingerprint_ledger_records_safely(
    tenant_id: str,
    records: Sequence[FingerprintOccurrenceRecord],
    *,
    phase: str,
) -> bool:
    """Commit shadow records without allowing Ledger faults into product flow."""
    if not records:
        return True
    try:
        ledger_engine = get_tenant_engine(tenant_id)
        LedgerSession = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=ledger_engine,
        )
        with LedgerSession() as db:
            _record_fingerprint_ledger_records(db, records)
            db.commit()
        return True
    except Exception as exc:
        try:
            fingerprint_logger.warning(
                "[FINGERPRINT_LEDGER_SHADOW_WRITE_FAILED] "
                f"phase={phase[:32]} task_id={records[0].task_id[:64]} "
                f"count={len(records)} error={type(exc).__name__[:64]} "
                f"detail={str(exc)[:128]}"
            )
        except Exception:
            pass
        return False


def _coverage_diagnostics_v1_payload(
    diagnostics: _CoverageDiagnosticsV1,
) -> dict[str, Any]:
    """Serialize CoverageDiagnosticsV1 without leaking internal representations."""
    return {
        "type": diagnostics.diagnostics_type,
        "version": diagnostics.version,
        "variant_planning_policy": diagnostics.variant_planning_policy,
        "requested_count": diagnostics.requested_count,
        "accepted_count": diagnostics.accepted_count,
        "candidate_space_size": diagnostics.candidate_space_size,
        "search_budget": diagnostics.search_budget,
        "examined_count": diagnostics.examined_count,
        "proposal_attempted_count": diagnostics.proposal_attempted_count,
        "termination_reason": diagnostics.termination_reason,
        "preview_seeded": diagnostics.preview_seeded,
        "preview_child_index": diagnostics.preview_child_index,
        "preview_fingerprint_digest": diagnostics.preview_fingerprint_digest,
        "accepted_fingerprint_digests": list(
            diagnostics.accepted_fingerprint_digests
        ),
        "rejection_counts": {
            "materialization_mismatch_count": (
                diagnostics.rejection_counts.materialization_mismatch_count
            ),
            "invalid_plan_count": diagnostics.rejection_counts.invalid_plan_count,
            "duplicate_fingerprint_reject_count": (
                diagnostics.rejection_counts.duplicate_fingerprint_reject_count
            ),
        },
        "beats": [
            {
                "beat_index": beat.beat_index,
                "beat_identity": beat.beat_identity,
                "role": beat.role,
                "pool_size": beat.pool_size,
                "selected_histogram": [
                    {
                        "normalized_file_hash": entry.normalized_file_hash,
                        "asset_id": entry.asset_id,
                        "count": entry.count,
                    }
                    for entry in beat.selected_histogram
                ],
                "selected_count": beat.selected_count,
                "unique_used": beat.unique_used,
                "unused_count": beat.unused_count,
                "ideal_floor": beat.ideal_floor,
                "ideal_ceil": beat.ideal_ceil,
                "max_min_gap": beat.max_min_gap,
                "classification": beat.classification,
            }
            for beat in diagnostics.beats
        ],
    }


def _build_coverage_diagnostics_v1(
    dsl_payload: StoryDSLPayload,
    candidate_pools: Sequence[Sequence[MainVisualCandidate]],
    coverage: Sequence[dict[str, int]],
    accepted_fingerprints: Sequence[_MainVisualFingerprint],
    *,
    requested_count: int,
    candidate_space_size: int,
    search_budget: int,
    examined_count: int,
    proposal_attempted_count: int,
    termination_reason: str,
    preview_seeded: bool,
    materialization_mismatch_count: int,
    invalid_plan_count: int,
    duplicate_fingerprint_reject_count: int,
    reservation_conflict_count: int = 0,
    preview_examined: Optional[bool] = None,
    preview_reservation_conflicted: bool = False,
) -> _CoverageDiagnosticsV1:
    """Freeze authoritative completed balanced-planner coverage as V1 diagnostics."""
    beat_count = len(dsl_payload.timeline)
    if len(candidate_pools) != beat_count or len(coverage) != beat_count:
        raise ValueError("COVERAGE_DIAGNOSTICS_BEAT_COUNT_MISMATCH")
    if any(
        value < 0
        for value in (
            requested_count,
            candidate_space_size,
            search_budget,
            examined_count,
            proposal_attempted_count,
            materialization_mismatch_count,
            invalid_plan_count,
            duplicate_fingerprint_reject_count,
            reservation_conflict_count,
        )
    ):
        raise ValueError("COVERAGE_DIAGNOSTICS_NEGATIVE_COUNTER")

    expected_space_size = (
        prod(len(pool) for pool in candidate_pools)
        if candidate_pools and all(candidate_pools)
        else 0
    )
    if candidate_space_size != expected_space_size:
        raise ValueError("COVERAGE_DIAGNOSTICS_CANDIDATE_SPACE_MISMATCH")

    accepted_count = len(accepted_fingerprints)
    preview_count = 1 if preview_seeded else 0
    preview_examined_count = (
        preview_count if preview_examined is None else int(preview_examined)
    )
    if preview_count > accepted_count:
        raise ValueError("COVERAGE_DIAGNOSTICS_PREVIEW_STATE_INVALID")
    if preview_reservation_conflicted and (
        not preview_examined_count or preview_seeded or reservation_conflict_count < 1
    ):
        raise ValueError("COVERAGE_DIAGNOSTICS_PREVIEW_STATE_INVALID")
    if examined_count != proposal_attempted_count + preview_examined_count:
        raise ValueError("COVERAGE_DIAGNOSTICS_EXAMINED_PARTITION_INVALID")
    non_preview_accepted_count = accepted_count - preview_count
    normal_reservation_conflict_count = (
        reservation_conflict_count - int(preview_reservation_conflicted)
    )
    if proposal_attempted_count != (
        non_preview_accepted_count
        + materialization_mismatch_count
        + invalid_plan_count
        + duplicate_fingerprint_reject_count
        + normal_reservation_conflict_count
    ):
        raise ValueError("COVERAGE_DIAGNOSTICS_PROPOSAL_PARTITION_INVALID")

    normalized_pools: list[tuple[tuple[str, MainVisualCandidate], ...]] = []
    for beat_index, pool in enumerate(candidate_pools):
        normalized_pool: list[tuple[str, MainVisualCandidate]] = []
        seen_hashes: set[str] = set()
        for candidate in pool:
            normalized_hash = normalize_file_hash(candidate.file_hash)
            if not normalized_hash:
                raise ValueError(
                    "COVERAGE_DIAGNOSTICS_CANDIDATE_IDENTITY_INVALID: "
                    f"Beat {beat_index}"
                )
            if normalized_hash in seen_hashes:
                continue
            seen_hashes.add(normalized_hash)
            normalized_pool.append((normalized_hash, candidate))
        normalized_pools.append(tuple(normalized_pool))

    authoritative_counts = [
        {normalized_hash: 0 for normalized_hash, _candidate in pool}
        for pool in normalized_pools
    ]
    for fingerprint in accepted_fingerprints:
        if len(fingerprint) != beat_count:
            raise ValueError("COVERAGE_DIAGNOSTICS_FINGERPRINT_BEAT_COUNT_MISMATCH")
        for expected_index, component in enumerate(fingerprint):
            beat_index, beat_identity, layer_index, normalized_file_hash = component
            expected_identity = str(dsl_payload.timeline[expected_index].beat).strip()
            if (
                beat_index != expected_index
                or beat_identity != expected_identity
                or layer_index != 0
            ):
                raise ValueError("COVERAGE_DIAGNOSTICS_FINGERPRINT_ORDER_MISMATCH")
            if normalized_file_hash not in authoritative_counts[beat_index]:
                raise ValueError("COVERAGE_DIAGNOSTICS_SELECTED_HASH_OUTSIDE_POOL")
            authoritative_counts[beat_index][normalized_file_hash] += 1

    beat_diagnostics: list[_CoverageBeatDiagnosticsV1] = []
    for beat_index, (node, normalized_pool, axis_coverage) in enumerate(
        zip(dsl_payload.timeline, normalized_pools, coverage)
    ):
        pool_hashes = tuple(normalized_hash for normalized_hash, _ in normalized_pool)
        if tuple(axis_coverage) != pool_hashes:
            raise ValueError("COVERAGE_DIAGNOSTICS_COVERAGE_POOL_MISMATCH")
        if any(type(count) is not int or count < 0 for count in axis_coverage.values()):
            raise ValueError("COVERAGE_DIAGNOSTICS_COVERAGE_COUNT_INVALID")
        if axis_coverage != authoritative_counts[beat_index]:
            raise ValueError("COVERAGE_DIAGNOSTICS_COVERAGE_AUTHORITY_MISMATCH")

        full_counts = [axis_coverage[normalized_hash] for normalized_hash in pool_hashes]
        pool_size = len(normalized_pool)
        selected_count = sum(full_counts)
        if pool_size and selected_count != accepted_count:
            raise ValueError("COVERAGE_DIAGNOSTICS_SELECTED_COUNT_MISMATCH")
        if not pool_size and selected_count != 0:
            raise ValueError("COVERAGE_DIAGNOSTICS_EMPTY_POOL_HAS_SELECTIONS")

        selected_histogram = tuple(
            _CoverageHistogramEntryV1(
                normalized_file_hash=normalized_hash,
                asset_id=candidate.asset_id,
                count=axis_coverage[normalized_hash],
            )
            for normalized_hash, candidate in normalized_pool
            if axis_coverage[normalized_hash] > 0
        )
        unique_used = len(selected_histogram)
        unused_count = pool_size - unique_used
        if unique_used > pool_size or unused_count < 0:
            raise ValueError("COVERAGE_DIAGNOSTICS_UNIQUE_COUNT_INVALID")

        if pool_size == 0:
            ideal_floor = None
            ideal_ceil = None
            max_min_gap = None
            classification = None
        else:
            ideal_floor, remainder = divmod(accepted_count, pool_size)
            ideal_ceil = ideal_floor if remainder == 0 else ideal_floor + 1
            max_min_gap = max(full_counts) - min(full_counts)
            target_counts = sorted(
                [ideal_ceil] * remainder
                + [ideal_floor] * (pool_size - remainder)
            )
            target_met = (
                len(full_counts) == pool_size
                and all(type(count) is int and count >= 0 for count in full_counts)
                and sum(full_counts) == accepted_count
                and sorted(full_counts) == target_counts
            )
            if pool_size == 1:
                classification = _COVERAGE_FIXED_BY_CAPACITY
            elif target_met:
                classification = _COVERAGE_VARIABLE_BALANCED
            else:
                classification = _COVERAGE_VARIABLE_TARGET_NOT_MET

        beat_diagnostics.append(
            _CoverageBeatDiagnosticsV1(
                beat_index=beat_index,
                beat_identity=str(node.beat),
                role=str(node.role),
                pool_size=pool_size,
                selected_histogram=selected_histogram,
                selected_count=selected_count,
                unique_used=unique_used,
                unused_count=unused_count,
                ideal_floor=ideal_floor,
                ideal_ceil=ideal_ceil,
                max_min_gap=max_min_gap,
                classification=classification,
            )
        )

    accepted_digests = tuple(
        _main_visual_planning_fingerprint_contract(fingerprint).fingerprint_digest
        for fingerprint in accepted_fingerprints
    )
    if len(accepted_digests) != accepted_count:
        raise ValueError("COVERAGE_DIAGNOSTICS_DIGEST_COUNT_MISMATCH")
    preview_digest = accepted_digests[0] if preview_seeded else None
    diagnostics = _CoverageDiagnosticsV1(
        diagnostics_type=_COVERAGE_DIAGNOSTICS_TYPE,
        version=_COVERAGE_DIAGNOSTICS_VERSION,
        variant_planning_policy=_BALANCED_VARIANT_PLANNING_POLICY,
        requested_count=requested_count,
        accepted_count=accepted_count,
        candidate_space_size=candidate_space_size,
        search_budget=search_budget,
        examined_count=examined_count,
        proposal_attempted_count=proposal_attempted_count,
        termination_reason=termination_reason,
        preview_seeded=preview_seeded,
        preview_child_index=0 if preview_seeded else None,
        preview_fingerprint_digest=preview_digest,
        accepted_fingerprint_digests=accepted_digests,
        rejection_counts=_CoverageRejectionCountsV1(
            materialization_mismatch_count=materialization_mismatch_count,
            invalid_plan_count=invalid_plan_count,
            duplicate_fingerprint_reject_count=duplicate_fingerprint_reject_count,
        ),
        beats=tuple(beat_diagnostics),
    )
    json.dumps(
        _coverage_diagnostics_v1_payload(diagnostics),
        ensure_ascii=False,
        allow_nan=False,
    )
    return diagnostics


def _validated_coverage_diagnostics_payload(
    diagnostics: _CoverageDiagnosticsV1,
    planning_result: _VariantPlanningResult,
    computed_fingerprints: Sequence[_MainVisualFingerprint],
) -> dict[str, Any]:
    """Validate the balanced diagnostics against coordinator-approved truth."""
    if (
        diagnostics.diagnostics_type != _COVERAGE_DIAGNOSTICS_TYPE
        or diagnostics.version != _COVERAGE_DIAGNOSTICS_VERSION
        or diagnostics.variant_planning_policy
        != _BALANCED_VARIANT_PLANNING_POLICY
    ):
        raise ValueError("COVERAGE_DIAGNOSTICS_COORDINATOR_CONTRACT_MISMATCH")
    accepted_count = len(computed_fingerprints)
    if (
        diagnostics.accepted_count != accepted_count
        or len(planning_result.plans) != accepted_count
        or len(planning_result.fingerprints) != accepted_count
        or diagnostics.examined_count != planning_result.examined_combinations
        or diagnostics.candidate_space_size != planning_result.candidate_space_size
        or diagnostics.termination_reason != planning_result.termination_reason
    ):
        raise ValueError("COVERAGE_DIAGNOSTICS_COORDINATOR_COUNT_MISMATCH")
    coordinator_digests = tuple(
        _main_visual_planning_fingerprint_contract(fingerprint).fingerprint_digest
        for fingerprint in computed_fingerprints
    )
    if diagnostics.accepted_fingerprint_digests != coordinator_digests:
        raise ValueError("COVERAGE_DIAGNOSTICS_COORDINATOR_DIGEST_MISMATCH")
    payload = _coverage_diagnostics_v1_payload(diagnostics)
    json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return payload


def _emit_balanced_coverage_summary(
    task_id: str,
    coverage_diagnostics: dict[str, Any],
) -> None:
    """Emit one best-effort batch coverage event through the project Loguru sink."""
    try:
        event_json = json.dumps(
            {
                "event": _BALANCED_COVERAGE_SUMMARY_EVENT,
                "task_id": task_id,
                "coverage_diagnostics": coverage_diagnostics,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        fingerprint_logger.info(f"[BalancedCoverageSummary] {event_json}")
    except Exception:
        pass


def _bounded_fingerprint_log_string(
    value: object,
    max_chars: int,
) -> tuple[str, bool]:
    """Return a deterministic presentation-only string and truncation state."""
    text = str(value)
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _main_visual_planning_log_components(
    plan: CompilationPlan,
    fingerprint: _MainVisualFingerprint,
    *,
    max_components: int = _MAX_LOGGED_FINGERPRINT_COMPONENTS,
) -> tuple[list[dict[str, Any]], bool, bool]:
    """Build bounded diagnostics from the authoritative plan and fingerprint."""
    if len(plan.beats) != len(fingerprint):
        raise ValueError("FINGERPRINT_OBSERVABILITY_BEAT_COUNT_MISMATCH")

    components: list[dict[str, Any]] = []
    component_fields_truncated = False
    for beat, component in zip(plan.beats[:max_components], fingerprint[:max_components]):
        main_layers = [layer for layer in beat.layers if layer.layer_index == 0]
        if len(main_layers) != 1:
            raise ValueError("FINGERPRINT_OBSERVABILITY_MAIN_LAYER_INVALID")
        beat_index, beat_identity, _layer_index, normalized_file_hash = component
        displayed_beat_identity, beat_identity_truncated = (
            _bounded_fingerprint_log_string(
                beat_identity,
                _MAX_LOGGED_BEAT_IDENTITY_CHARS,
            )
        )
        displayed_file_hash, file_hash_truncated = _bounded_fingerprint_log_string(
            normalized_file_hash,
            _MAX_LOGGED_SOURCE_HASH_CHARS,
        )
        component_fields_truncated = (
            component_fields_truncated
            or beat_identity_truncated
            or file_hash_truncated
        )
        components.append(
            {
                "beat_index": beat_index,
                "beat_identity": displayed_beat_identity,
                "asset_id": main_layers[0].asset_id,
                "normalized_file_hash": displayed_file_hash,
            }
        )
    return (
        components,
        len(fingerprint) > max_components,
        component_fields_truncated,
    )


def _variant_fingerprint_event_payload(
    plan: CompilationPlan,
    *,
    planner_fingerprint: Optional[_MainVisualFingerprint],
    task_id: str,
    execution_id: str,
    child_index: int,
    file_sid: str,
) -> dict[str, Any]:
    """Build the authoritative child-entry fingerprint observability event."""
    worker_fingerprint = _exact_main_visual_fingerprint(plan)
    contract = _main_visual_planning_fingerprint_contract(worker_fingerprint)
    (
        components,
        components_truncated,
        component_fields_truncated,
    ) = _main_visual_planning_log_components(plan, worker_fingerprint)
    planner_fingerprint_match = (
        None
        if planner_fingerprint is None
        else planner_fingerprint == worker_fingerprint
    )
    return {
        "event": _VARIANT_FINGERPRINT_EVENT,
        "phase": _VARIANT_FINGERPRINT_PHASE,
        "task_id": task_id,
        "execution_id": execution_id,
        "child_index": child_index,
        "file_sid": file_sid,
        "fingerprint_type": contract.fingerprint_type,
        "fingerprint_version": contract.fingerprint_version,
        "source_hash_algorithm": contract.source_hash_algorithm,
        "fingerprint_digest": contract.fingerprint_digest,
        "beat_count": len(worker_fingerprint),
        "planner_fingerprint_match": planner_fingerprint_match,
        "components": components,
        "components_truncated": components_truncated,
        "component_fields_truncated": component_fields_truncated,
    }


def _fingerprint_observability_warning(
    diagnostic: str,
    *,
    task_id: str,
    execution_id: str,
    child_index: int,
    file_sid: str,
    detail: str,
) -> None:
    """Emit a bounded diagnostic without allowing logging to affect rendering."""
    try:
        fingerprint_logger.warning(
            f"[VariantFingerprint] diagnostic={diagnostic} task_id={task_id} "
            f"execution_id={execution_id} child_index={child_index} "
            f"file_sid={file_sid} detail={str(detail)[:300]}"
        )
    except Exception:
        pass


def _emit_authoritative_variant_fingerprint(
    plan: CompilationPlan,
    *,
    planner_fingerprint: Optional[_MainVisualFingerprint],
    task_id: str,
    execution_id: str,
    child_index: int,
    file_sid: str,
) -> None:
    """Emit one non-blocking authoritative VariantFingerprint INFO event."""
    try:
        event = _variant_fingerprint_event_payload(
            plan,
            planner_fingerprint=planner_fingerprint,
            task_id=task_id,
            execution_id=execution_id,
            child_index=child_index,
            file_sid=file_sid,
        )
        if event["planner_fingerprint_match"] is None:
            _fingerprint_observability_warning(
                "FINGERPRINT_OBSERVABILITY_MISSING",
                task_id=task_id,
                execution_id=execution_id,
                child_index=child_index,
                file_sid=file_sid,
                detail="planner-provided fingerprint is missing",
            )
        elif not event["planner_fingerprint_match"]:
            _fingerprint_observability_warning(
                "FINGERPRINT_OBSERVABILITY_MISMATCH",
                task_id=task_id,
                execution_id=execution_id,
                child_index=child_index,
                file_sid=file_sid,
                detail="planner fingerprint differs from authoritative worker plan",
            )
        event_json = json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        fingerprint_logger.info(f"[VariantFingerprint] {event_json}")
    except Exception as exc:
        _fingerprint_observability_warning(
            "FINGERPRINT_OBSERVABILITY_FAILED",
            task_id=task_id,
            execution_id=execution_id,
            child_index=child_index,
            file_sid=file_sid,
            detail=f"{type(exc).__name__}: {exc}",
        )


def _selection_key(
    selections: Sequence[MainVisualCandidate],
) -> tuple[tuple[int, str], ...]:
    return tuple((selection.asset_id, selection.file_hash) for selection in selections)


def _preview_selection(
    preview_plan: Optional[CompilationPlan],
    dsl_payload: StoryDSLPayload,
    candidate_pools: Sequence[Sequence[MainVisualCandidate]],
) -> Optional[tuple[MainVisualCandidate, ...]]:
    """Map a preview plan back to the current resolver-valid candidate space."""
    if preview_plan is None or len(preview_plan.beats) != len(dsl_payload.timeline):
        return None
    try:
        _exact_main_visual_fingerprint(preview_plan)
    except ValueError:
        return None

    selections: list[MainVisualCandidate] = []
    for beat_index, (beat, node, pool) in enumerate(
        zip(preview_plan.beats, dsl_payload.timeline, candidate_pools)
    ):
        if beat.beat != node.beat:
            return None
        main_layer = next(layer for layer in beat.layers if layer.layer_index == 0)
        normalized_hash = normalize_file_hash(main_layer.file_hash)
        match = next(
            (
                candidate
                for candidate in pool
                if candidate.asset_id == main_layer.asset_id
                and candidate.file_hash == normalized_hash
            ),
            None,
        )
        if match is None:
            logger.info(
                "[variant_planner] preview seed stale/invalid beat_index=%d beat=%s",
                beat_index,
                node.beat,
            )
            return None
        selections.append(match)
    return tuple(selections)


def _acquire_planner_candidate_reservation(
    reservation_controller: Optional[PlannerReservationController],
    fingerprint: _MainVisualFingerprint,
    *,
    prospective_slot: int,
) -> bool:
    if reservation_controller is None:
        return True
    outcome = reservation_controller.acquire_candidate(
        _main_visual_fingerprint_identity_record(fingerprint),
        prospective_slot=prospective_slot,
    )
    if outcome.decision is PlannerReservationDecision.CONFLICT:
        return False
    if outcome.decision is not PlannerReservationDecision.OWNED:
        raise ValueError("PLANNER_RESERVATION_DECISION_INVALID")
    reservation_controller.require_active()
    return True


def _planning_termination(
    *,
    accepted_count: int,
    requested_count: int,
    examined_count: int,
    candidate_space_size: int,
    unresolved_unique_reservation_blocked_count: int,
) -> tuple[str, list[str]]:
    if accepted_count >= requested_count:
        return _PLANNING_REQUEST_SATISFIED, []
    if examined_count >= candidate_space_size:
        if (
            unresolved_unique_reservation_blocked_count > 0
            and accepted_count + unresolved_unique_reservation_blocked_count
            >= requested_count
        ):
            return (
                _PLANNING_RESERVATION_CONFLICT_EXHAUSTED,
                [_PLANNING_RESERVATION_CONFLICT_EXHAUSTED],
            )
        return _PLANNING_TRUE_SPACE_EXHAUSTED, ["INSUFFICIENT_UNIQUE_CAPACITY"]
    return _PLANNING_SEARCH_LIMIT_REACHED, [_PLANNING_SEARCH_LIMIT_REACHED]


def _attach_planner_reservation_bindings(
    result: _VariantPlanningResult,
    reservation_controller: Optional[PlannerReservationController],
) -> _VariantPlanningResult:
    if reservation_controller is None:
        return result
    bindings = reservation_controller.bindings
    if len(bindings) != len(result.plans):
        raise ValueError("PLANNER_RESERVATION_BINDING_COUNT_MISMATCH")
    for slot, (binding, fingerprint) in enumerate(zip(bindings, result.fingerprints)):
        contract = _main_visual_planning_fingerprint_contract(fingerprint)
        if (
            binding.owner_task_id != reservation_controller.owner_task_id
            or binding.owner_slot_index != slot
            or binding.fingerprint_type != contract.fingerprint_type
            or binding.fingerprint_version != contract.fingerprint_version
            or binding.fingerprint_digest != contract.fingerprint_digest
        ):
            raise ValueError("PLANNER_RESERVATION_BINDING_ALIGNMENT_MISMATCH")
    return replace(result, reservation_bindings=bindings)


def _plan_exact_main_visual_variants_impl(
    parser: DSLParserNode,
    dsl_payload: StoryDSLPayload,
    requested_count: int,
    *,
    preview_plan: Optional[CompilationPlan] = None,
    search_budget: int = _EXACT_MAIN_VISUAL_SEARCH_BUDGET,
    historical_observer: Optional[_HistoricalNoveltyObserver] = None,
    preview_intent: PreviewIntent = PreviewIntent.UNSPECIFIED,
    reservation_controller: Optional[PlannerReservationController] = None,
) -> _VariantPlanningResult:
    """Lazily enumerate finite resolver-valid main-X combinations."""
    if requested_count < 1:
        raise ValueError("requested_count must be at least 1")
    if search_budget < 1:
        raise ValueError("search_budget must be at least 1")

    candidate_pools = parser.discover_main_visual_candidates(dsl_payload)
    if len(candidate_pools) != len(dsl_payload.timeline):
        raise ValueError(
            "PLANNER_CANDIDATE_CONTRACT_INVALID: candidate pool count "
            "does not match Beat count"
        )
    candidate_space_size = (
        prod(len(pool) for pool in candidate_pools)
        if candidate_pools and all(candidate_pools)
        else 0
    )
    accepted_plans: list[CompilationPlan] = []
    accepted_fingerprints: list[_MainVisualFingerprint] = []
    used_fingerprints: set[_MainVisualFingerprint] = set()
    reservation_conflicted_fingerprints: set[_MainVisualFingerprint] = set()
    examined_keys: set[tuple[tuple[int, str], ...]] = set()
    selection_mismatch_seen = False

    preview_selections = _preview_selection(
        preview_plan,
        dsl_payload,
        candidate_pools,
    )
    if preview_selections is not None and candidate_space_size:
        preview_key = _selection_key(preview_selections)
        preview_fingerprint = _exact_main_visual_fingerprint(preview_plan)
        examined_keys.add(preview_key)
        historical_outcome = None
        if historical_observer is not None:
            historical_outcome = historical_observer.observe(
                preview_fingerprint,
                is_preview=True,
                preview_intent=preview_intent,
            )
        if _acquire_planner_candidate_reservation(
            reservation_controller,
            preview_fingerprint,
            prospective_slot=len(accepted_plans),
        ):
            accepted_plans.append(preview_plan)
            accepted_fingerprints.append(preview_fingerprint)
            used_fingerprints.add(preview_fingerprint)
            reservation_conflicted_fingerprints.discard(preview_fingerprint)
            if historical_observer is not None:
                historical_observer.mark_accepted(historical_outcome)
        else:
            reservation_conflicted_fingerprints.add(preview_fingerprint)
            if historical_observer is not None:
                historical_observer.mark_reservation_conflict()

    if len(accepted_plans) < requested_count and candidate_space_size:
        for combination in product(*candidate_pools):
            combination_key = _selection_key(combination)
            if combination_key in examined_keys:
                continue
            if len(examined_keys) >= search_budget:
                break
            examined_keys.add(combination_key)
            try:
                materialized = parser.materialize_with_main_selections(
                    dsl_payload,
                    combination,
                )
                fingerprint = _exact_main_visual_fingerprint(materialized)
                selected_hashes = tuple(candidate.file_hash for candidate in combination)
                materialized_hashes = tuple(row[3] for row in fingerprint)
                if selected_hashes != materialized_hashes:
                    raise MainVisualSelectionMismatch(
                        "PLANNER_SELECTION_MISMATCH: selected and materialized hashes differ"
                    )
            except MainVisualSelectionMismatch:
                selection_mismatch_seen = True
                logger.exception(
                    "[variant_planner] explicit selection materialization mismatch"
                )
                continue
            except ValueError:
                logger.warning(
                    "[variant_planner] rejected invalid materialized main-visual plan",
                    exc_info=True,
                )
                continue

            if fingerprint in used_fingerprints:
                continue
            historical_outcome = None
            if historical_observer is not None:
                historical_outcome = historical_observer.observe(fingerprint)
            if not _acquire_planner_candidate_reservation(
                reservation_controller,
                fingerprint,
                prospective_slot=len(accepted_plans),
            ):
                reservation_conflicted_fingerprints.add(fingerprint)
                if historical_observer is not None:
                    historical_observer.mark_reservation_conflict()
                continue
            accepted_plans.append(materialized)
            accepted_fingerprints.append(fingerprint)
            used_fingerprints.add(fingerprint)
            reservation_conflicted_fingerprints.discard(fingerprint)
            if historical_observer is not None:
                historical_observer.mark_accepted(historical_outcome)
            if len(accepted_plans) >= requested_count:
                break

    termination_reason, warning_codes = _planning_termination(
        accepted_count=len(accepted_plans),
        requested_count=requested_count,
        examined_count=len(examined_keys),
        candidate_space_size=candidate_space_size,
        unresolved_unique_reservation_blocked_count=len(
            reservation_conflicted_fingerprints
        ),
    )
    if selection_mismatch_seen:
        warning_codes.append("PLANNER_SELECTION_MISMATCH")

    return _VariantPlanningResult(
        plans=tuple(accepted_plans),
        fingerprints=tuple(accepted_fingerprints),
        examined_combinations=len(examined_keys),
        candidate_space_size=candidate_space_size,
        termination_reason=termination_reason,
        warning_codes=tuple(warning_codes),
        historical_novelty_diagnostics=(
            historical_observer.diagnostics()
            if historical_observer is not None
            else None
        ),
    )


def _plan_exact_main_visual_variants(
    parser: DSLParserNode,
    dsl_payload: StoryDSLPayload,
    requested_count: int,
    *,
    preview_plan: Optional[CompilationPlan] = None,
    search_budget: int = _EXACT_MAIN_VISUAL_SEARCH_BUDGET,
    historical_observer: Optional[_HistoricalNoveltyObserver] = None,
    preview_intent: PreviewIntent = PreviewIntent.UNSPECIFIED,
    reservation_controller: Optional[PlannerReservationController] = None,
) -> _VariantPlanningResult:
    try:
        result = _plan_exact_main_visual_variants_impl(
            parser,
            dsl_payload,
            requested_count,
            preview_plan=preview_plan,
            search_budget=search_budget,
            historical_observer=historical_observer,
            preview_intent=preview_intent,
            reservation_controller=reservation_controller,
        )
        return _attach_planner_reservation_bindings(
            result,
            reservation_controller,
        )
    except Exception:
        if reservation_controller is not None:
            reservation_controller.abort()
        raise


@dataclass(frozen=True)
class _BalancedCandidateWindowEntry:
    """One lightweight Cartesian proposal for balanced planning."""

    selections: tuple[MainVisualCandidate, ...]
    selection_key: tuple[tuple[int, str], ...]
    cartesian_ordinal: int


def _selection_from_cartesian_ordinal(
    candidate_pools: Sequence[Sequence[MainVisualCandidate]],
    ordinal: int,
) -> tuple[MainVisualCandidate, ...]:
    """Decode a rightmost-fastest flat Cartesian ordinal without materializing it."""
    if not candidate_pools or any(not pool for pool in candidate_pools):
        raise ValueError("candidate pools must be non-empty")

    candidate_space_size = prod(len(pool) for pool in candidate_pools)
    if ordinal < 0 or ordinal >= candidate_space_size:
        raise ValueError("Cartesian ordinal is outside candidate space")

    remaining = ordinal
    candidate_indexes = [0] * len(candidate_pools)
    for beat_index in range(len(candidate_pools) - 1, -1, -1):
        remaining, candidate_indexes[beat_index] = divmod(
            remaining,
            len(candidate_pools[beat_index]),
        )
    return tuple(
        candidate_pools[beat_index][candidate_index]
        for beat_index, candidate_index in enumerate(candidate_indexes)
    )


def _stratified_cartesian_ordinals(
    candidate_space_size: int,
    sample_count: int,
) -> tuple[int, ...]:
    """Return deterministic evenly spaced ordinals spanning the full space."""
    if candidate_space_size < 0:
        raise ValueError("candidate_space_size must be non-negative")
    if sample_count < 0:
        raise ValueError("sample_count must be non-negative")
    if candidate_space_size == 0 or sample_count == 0:
        return ()
    if sample_count >= candidate_space_size:
        return tuple(range(candidate_space_size))
    if sample_count == 1:
        return (0,)
    return tuple(
        sample_index * (candidate_space_size - 1) // (sample_count - 1)
        for sample_index in range(sample_count)
    )


def _balanced_candidate_window(
    candidate_pools: Sequence[Sequence[MainVisualCandidate]],
    candidate_space_size: int,
    max_entries: int,
    *,
    excluded_keys: set[tuple[tuple[int, str], ...]],
) -> tuple[_BalancedCandidateWindowEntry, ...]:
    """Build a bounded lightweight full-space or stratified proposal window."""
    if max_entries <= 0 or candidate_space_size <= 0:
        return ()

    remaining_space_size = max(candidate_space_size - len(excluded_keys), 0)
    if remaining_space_size <= max_entries:
        ordinals: Sequence[int] = range(candidate_space_size)
    else:
        sample_count = min(
            candidate_space_size,
            max_entries + len(excluded_keys),
        )
        ordinals = _stratified_cartesian_ordinals(
            candidate_space_size,
            sample_count,
        )

    entries: list[_BalancedCandidateWindowEntry] = []
    seen_keys = set(excluded_keys)
    for ordinal in ordinals:
        selections = _selection_from_cartesian_ordinal(candidate_pools, ordinal)
        selection_key = _selection_key(selections)
        if selection_key in seen_keys:
            continue
        seen_keys.add(selection_key)
        entries.append(
            _BalancedCandidateWindowEntry(
                selections=selections,
                selection_key=selection_key,
                cartesian_ordinal=ordinal,
            )
        )
        if len(entries) >= max_entries:
            break
    return tuple(entries)


def _initial_main_visual_coverage(
    candidate_pools: Sequence[Sequence[MainVisualCandidate]],
) -> list[dict[str, int]]:
    """Initialize per-Beat normalized source-hash counters, including zeros."""
    return [
        {
            normalize_file_hash(candidate.file_hash): 0
            for candidate in pool
        }
        for pool in candidate_pools
    ]


def _projected_main_visual_coverage_score(
    entry: _BalancedCandidateWindowEntry,
    coverage: Sequence[dict[str, int]],
) -> tuple[
    int,
    int,
    float,
    int,
    tuple[tuple[int, str], ...],
]:
    """Score one proposal by projected equal-weight per-Beat coverage fairness."""
    if len(entry.selections) != len(coverage):
        raise ValueError("coverage axis count does not match candidate selection")

    axis_gaps: list[int] = []
    axis_mses: list[float] = []
    for beat_index, (candidate, axis_coverage) in enumerate(
        zip(entry.selections, coverage)
    ):
        if len(axis_coverage) <= 1:
            continue
        candidate_hash = normalize_file_hash(candidate.file_hash)
        if candidate_hash not in axis_coverage:
            raise ValueError(
                f"coverage candidate is not present in Beat {beat_index} pool"
            )
        projected_counts = list(axis_coverage.values())
        candidate_position = tuple(axis_coverage).index(candidate_hash)
        projected_counts[candidate_position] += 1
        axis_gap = max(projected_counts) - min(projected_counts)
        target = sum(projected_counts) / len(projected_counts)
        axis_mse = sum(
            (count - target) ** 2 for count in projected_counts
        ) / len(projected_counts)
        axis_gaps.append(axis_gap)
        axis_mses.append(axis_mse)

    return (
        max(axis_gaps, default=0),
        sum(axis_gaps),
        sum(axis_mses),
        entry.cartesian_ordinal,
        entry.selection_key,
    )


def _update_main_visual_coverage(
    coverage: Sequence[dict[str, int]],
    fingerprint: _MainVisualFingerprint,
) -> None:
    """Update coverage from one already accepted authoritative fingerprint."""
    if len(fingerprint) != len(coverage):
        raise ValueError("accepted fingerprint Beat count does not match coverage")
    for beat_index, _beat_identity, _layer_index, normalized_file_hash in fingerprint:
        if beat_index < 0 or beat_index >= len(coverage):
            raise ValueError("accepted fingerprint Beat index is outside coverage")
        if normalized_file_hash not in coverage[beat_index]:
            raise ValueError("accepted fingerprint hash is outside candidate pool")
        coverage[beat_index][normalized_file_hash] += 1


def _plan_exact_main_visual_balanced_variants_impl(
    parser: DSLParserNode,
    dsl_payload: StoryDSLPayload,
    requested_count: int,
    *,
    preview_plan: Optional[CompilationPlan] = None,
    search_budget: int = _EXACT_MAIN_VISUAL_SEARCH_BUDGET,
    historical_observer: Optional[_HistoricalNoveltyObserver] = None,
    preview_intent: PreviewIntent = PreviewIntent.UNSPECIFIED,
    reservation_controller: Optional[PlannerReservationController] = None,
) -> _VariantPlanningResult:
    """Select exact unique plans through a bounded greedy coverage window."""
    if requested_count < 1:
        raise ValueError("requested_count must be at least 1")
    if search_budget < 1:
        raise ValueError("search_budget must be at least 1")

    candidate_pools = parser.discover_main_visual_candidates(dsl_payload)
    if len(candidate_pools) != len(dsl_payload.timeline):
        raise ValueError(
            "PLANNER_CANDIDATE_CONTRACT_INVALID: candidate pool count "
            "does not match Beat count"
        )
    candidate_space_size = (
        prod(len(pool) for pool in candidate_pools)
        if candidate_pools and all(candidate_pools)
        else 0
    )
    accepted_plans: list[CompilationPlan] = []
    accepted_fingerprints: list[_MainVisualFingerprint] = []
    used_fingerprints: set[_MainVisualFingerprint] = set()
    reservation_conflicted_fingerprints: set[_MainVisualFingerprint] = set()
    examined_keys: set[tuple[tuple[int, str], ...]] = set()
    selection_mismatch_seen = False
    coverage = _initial_main_visual_coverage(candidate_pools)
    preview_seeded = False
    preview_reservation_conflicted = False
    proposal_attempted_count = 0
    materialization_mismatch_count = 0
    invalid_plan_count = 0
    duplicate_fingerprint_reject_count = 0

    preview_selections = _preview_selection(
        preview_plan,
        dsl_payload,
        candidate_pools,
    )
    if preview_selections is not None and candidate_space_size:
        preview_key = _selection_key(preview_selections)
        preview_fingerprint = _exact_main_visual_fingerprint(preview_plan)
        examined_keys.add(preview_key)
        historical_outcome = None
        if historical_observer is not None:
            historical_outcome = historical_observer.observe(
                preview_fingerprint,
                is_preview=True,
                preview_intent=preview_intent,
            )
        if _acquire_planner_candidate_reservation(
            reservation_controller,
            preview_fingerprint,
            prospective_slot=len(accepted_plans),
        ):
            accepted_plans.append(preview_plan)
            accepted_fingerprints.append(preview_fingerprint)
            used_fingerprints.add(preview_fingerprint)
            reservation_conflicted_fingerprints.discard(preview_fingerprint)
            _update_main_visual_coverage(coverage, preview_fingerprint)
            preview_seeded = True
            if historical_observer is not None:
                historical_observer.mark_accepted(historical_outcome)
        else:
            reservation_conflicted_fingerprints.add(preview_fingerprint)
            preview_reservation_conflicted = True
            if historical_observer is not None:
                historical_observer.mark_reservation_conflict()

    window = _balanced_candidate_window(
        candidate_pools,
        candidate_space_size,
        search_budget - len(examined_keys),
        excluded_keys=examined_keys,
    )

    while (
        len(accepted_plans) < requested_count
        and len(examined_keys) < search_budget
    ):
        remaining_entries = [
            entry for entry in window if entry.selection_key not in examined_keys
        ]
        if not remaining_entries:
            break

        scored_entries = [
            (_projected_main_visual_coverage_score(entry, coverage), entry)
            for entry in remaining_entries
        ]
        heapq.heapify(scored_entries)
        accepted_this_round = False

        while scored_entries and len(examined_keys) < search_budget:
            _score, proposal = heapq.heappop(scored_entries)
            examined_keys.add(proposal.selection_key)
            proposal_attempted_count += 1
            try:
                materialized = parser.materialize_with_main_selections(
                    dsl_payload,
                    proposal.selections,
                )
                fingerprint = _exact_main_visual_fingerprint(materialized)
                selected_hashes = tuple(
                    candidate.file_hash for candidate in proposal.selections
                )
                materialized_hashes = tuple(row[3] for row in fingerprint)
                if selected_hashes != materialized_hashes:
                    raise MainVisualSelectionMismatch(
                        "PLANNER_SELECTION_MISMATCH: selected and materialized hashes differ"
                    )
            except MainVisualSelectionMismatch:
                selection_mismatch_seen = True
                materialization_mismatch_count += 1
                logger.exception(
                    "[variant_planner] explicit balanced selection materialization mismatch"
                )
                continue
            except ValueError:
                invalid_plan_count += 1
                logger.warning(
                    "[variant_planner] rejected invalid balanced main-visual plan",
                    exc_info=True,
                )
                continue

            if fingerprint in used_fingerprints:
                duplicate_fingerprint_reject_count += 1
                continue
            historical_outcome = None
            if historical_observer is not None:
                historical_outcome = historical_observer.observe(fingerprint)
            if not _acquire_planner_candidate_reservation(
                reservation_controller,
                fingerprint,
                prospective_slot=len(accepted_plans),
            ):
                reservation_conflicted_fingerprints.add(fingerprint)
                if historical_observer is not None:
                    historical_observer.mark_reservation_conflict()
                continue
            accepted_plans.append(materialized)
            accepted_fingerprints.append(fingerprint)
            used_fingerprints.add(fingerprint)
            reservation_conflicted_fingerprints.discard(fingerprint)
            _update_main_visual_coverage(coverage, fingerprint)
            if historical_observer is not None:
                historical_observer.mark_accepted(historical_outcome)
            accepted_this_round = True
            break

        if not accepted_this_round:
            break

    termination_reason, warning_codes = _planning_termination(
        accepted_count=len(accepted_plans),
        requested_count=requested_count,
        examined_count=len(examined_keys),
        candidate_space_size=candidate_space_size,
        unresolved_unique_reservation_blocked_count=len(
            reservation_conflicted_fingerprints
        ),
    )
    if selection_mismatch_seen:
        warning_codes.append("PLANNER_SELECTION_MISMATCH")

    coverage_diagnostics = _build_coverage_diagnostics_v1(
        dsl_payload,
        candidate_pools,
        coverage,
        accepted_fingerprints,
        requested_count=requested_count,
        candidate_space_size=candidate_space_size,
        search_budget=search_budget,
        examined_count=len(examined_keys),
        proposal_attempted_count=proposal_attempted_count,
        termination_reason=termination_reason,
        preview_seeded=preview_seeded,
        materialization_mismatch_count=materialization_mismatch_count,
        invalid_plan_count=invalid_plan_count,
        duplicate_fingerprint_reject_count=duplicate_fingerprint_reject_count,
        reservation_conflict_count=(
            reservation_controller.conflict_count
            if reservation_controller is not None
            else 0
        ),
        preview_examined=(preview_selections is not None and bool(candidate_space_size)),
        preview_reservation_conflicted=preview_reservation_conflicted,
    )

    return _VariantPlanningResult(
        plans=tuple(accepted_plans),
        fingerprints=tuple(accepted_fingerprints),
        examined_combinations=len(examined_keys),
        candidate_space_size=candidate_space_size,
        termination_reason=termination_reason,
        warning_codes=tuple(warning_codes),
        coverage_diagnostics=coverage_diagnostics,
        historical_novelty_diagnostics=(
            historical_observer.diagnostics()
            if historical_observer is not None
            else None
        ),
    )


def _plan_exact_main_visual_balanced_variants(
    parser: DSLParserNode,
    dsl_payload: StoryDSLPayload,
    requested_count: int,
    *,
    preview_plan: Optional[CompilationPlan] = None,
    search_budget: int = _EXACT_MAIN_VISUAL_SEARCH_BUDGET,
    historical_observer: Optional[_HistoricalNoveltyObserver] = None,
    preview_intent: PreviewIntent = PreviewIntent.UNSPECIFIED,
    reservation_controller: Optional[PlannerReservationController] = None,
) -> _VariantPlanningResult:
    try:
        result = _plan_exact_main_visual_balanced_variants_impl(
            parser,
            dsl_payload,
            requested_count,
            preview_plan=preview_plan,
            search_budget=search_budget,
            historical_observer=historical_observer,
            preview_intent=preview_intent,
            reservation_controller=reservation_controller,
        )
        return _attach_planner_reservation_bindings(
            result,
            reservation_controller,
        )
    except Exception:
        if reservation_controller is not None:
            reservation_controller.abort()
        raise


def _plan_exact_main_visual_variants_from_db(
    tenant_id: str,
    dsl_payload: StoryDSLPayload,
    requested_count: int,
    *,
    preview_plan: Optional[CompilationPlan] = None,
    historical_novelty_mode: str = _HISTORICAL_MODE_OFF,
    preview_intent: PreviewIntent = PreviewIntent.UNSPECIFIED,
    reservation_controller: Optional[PlannerReservationController] = None,
) -> _VariantPlanningResult:
    """Run discovery and materialization inside one tenant DB session."""
    tenant_engine = get_tenant_engine(tenant_id)
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=tenant_engine,
    )
    with SessionLocal() as db:
        historical_observer = _historical_novelty_observer(
            SessionLocal,
            historical_novelty_mode,
        )
        if historical_observer is None and reservation_controller is None:
            return _plan_exact_main_visual_variants(
                DSLParserNode(db),
                dsl_payload,
                requested_count,
                preview_plan=preview_plan,
            )
        return _plan_exact_main_visual_variants(
            DSLParserNode(db),
            dsl_payload,
            requested_count,
            preview_plan=preview_plan,
            historical_observer=historical_observer,
            preview_intent=preview_intent,
            reservation_controller=reservation_controller,
        )


def _plan_exact_main_visual_balanced_variants_from_db(
    tenant_id: str,
    dsl_payload: StoryDSLPayload,
    requested_count: int,
    *,
    preview_plan: Optional[CompilationPlan] = None,
    historical_novelty_mode: str = _HISTORICAL_MODE_OFF,
    preview_intent: PreviewIntent = PreviewIntent.UNSPECIFIED,
    reservation_controller: Optional[PlannerReservationController] = None,
) -> _VariantPlanningResult:
    """Run balanced discovery and materialization inside one tenant DB session."""
    tenant_engine = get_tenant_engine(tenant_id)
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=tenant_engine,
    )
    with SessionLocal() as db:
        historical_observer = _historical_novelty_observer(
            SessionLocal,
            historical_novelty_mode,
        )
        if historical_observer is None and reservation_controller is None:
            return _plan_exact_main_visual_balanced_variants(
                DSLParserNode(db),
                dsl_payload,
                requested_count,
                preview_plan=preview_plan,
            )
        return _plan_exact_main_visual_balanced_variants(
            DSLParserNode(db),
            dsl_payload,
            requested_count,
            preview_plan=preview_plan,
            historical_observer=historical_observer,
            preview_intent=preview_intent,
            reservation_controller=reservation_controller,
        )


@dataclass(frozen=True)
class _ChildResult:
    """Internal result envelope returned by one child render execution."""

    child_index: int
    execution_id: str
    file_sid: str
    outcome: str
    assets: list[dict]
    elapsed: float
    error_code: Optional[str]
    error_message: Optional[str]
    prompt_details: dict[str, Any]
    fatigue_asset_ids: tuple[int, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.outcome == "succeeded" and bool(self.assets)


def _create_child_executions(task_id: str, child_count: int) -> list[_ChildExecution]:
    """Create child identities while keeping ``task_id`` as the batch identity."""
    if child_count < 1:
        raise ValueError("child_count must be at least 1")

    children: list[_ChildExecution] = []
    used_execution_ids: set[str] = set()
    used_file_sids: set[str] = set()

    for child_index in range(child_count):
        for _attempt in range(100):
            execution_uuid = uuid.uuid4()
            execution_id = str(execution_uuid)
            file_sid = execution_uuid.hex[:8]
            if (
                execution_id != task_id
                and execution_id not in used_execution_ids
                and file_sid not in used_file_sids
            ):
                break
        else:
            raise RuntimeError("unable to allocate a unique child execution identity")

        used_execution_ids.add(execution_id)
        used_file_sids.add(file_sid)
        children.append(
            _ChildExecution(
                child_index=child_index,
                execution_id=execution_id,
                file_sid=file_sid,
            )
        )

    return children


def _validate_child_execution(
    *,
    task_id: str,
    execution_id: str,
    file_sid: Optional[str],
    child_index: int,
) -> str:
    """Validate the explicit child identity contract at worker entry."""
    if child_index < 0:
        raise ValueError("child_index must be non-negative")
    if not execution_id or execution_id == task_id:
        raise ValueError("execution_id must be present and differ from task_id")

    try:
        execution_uuid = uuid.UUID(execution_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("execution_id must be a full UUID") from exc

    expected_file_sid = execution_uuid.hex[:8]
    if file_sid != expected_file_sid:
        raise ValueError("file_sid must be derived from execution_id")
    return expected_file_sid


def _child_prompt_details(
    dsl_payload: Optional[StoryDSLPayload],
    working_plan: Optional[CompilationPlan],
) -> dict[str, Any]:
    """Capture the legacy history fields from execution-local worker state."""
    meta: Optional[dict[str, Any]] = None
    if dsl_payload is not None and dsl_payload.meta is not None:
        meta = dsl_payload.meta.model_dump()

    return {
        "meta": meta,
        "timeline": [
            beat.model_dump()
            for beat in (working_plan.beats if working_plan is not None else [])
        ],
    }


def _plan_fatigue_asset_ids(
    plan: Optional[CompilationPlan],
) -> tuple[int, ...]:
    if plan is None:
        return ()
    return tuple(
        sorted(
            {
                layer.asset_id
                for beat in plan.beats
                for layer in beat.layers
                if layer.asset_id
            }
        )
    )


def _apply_fatigue_updates(
    db: Session,
    fatigue_counts: Counter[int],
    *,
    used_at: datetime,
) -> int:
    if not fatigue_counts:
        return 0
    assets = (
        db.query(LocalAsset)
        .filter(
            LocalAsset.id.in_(tuple(fatigue_counts)),
            LocalAsset.is_deleted.is_(False),
        )
        .all()
    )
    for asset in assets:
        asset.usage_count = (asset.usage_count or 0) + fatigue_counts[asset.id]
        asset.last_used_at = used_at
    return len(assets)


# ================================================================== #
# 后台渲染 Worker  (Phase 5.2)                                        #
# ================================================================== #

def render_worker(
    plan: Optional[CompilationPlan],
    task_id: str,
    aspect_ratio: str = "9:16",
    target_duration: int = 15,
    tenant_id: str = "default",
    prompt: Optional[str] = None,
    batch_size: int = 1,
    test_language: str = "en",
    file_sid: Optional[str] = None,
    *,
    execution_id: str,
    child_index: int,
    blind_dsl: bool = False,
    engine_type: str = "content",
    director_mode: str = "auto",
    dsl_payload: Optional[StoryDSLPayload] = None,
    plan_is_authoritative: bool = False,
    visual_fingerprint: Optional[_MainVisualFingerprint] = None,
    enable_tts: bool = True,
    enable_subtitles: bool = True,
    defer_fatigue_write: bool = False,
) -> _ChildResult:
    """
    后台渲染主 Worker（Phase 9.11.2 单轨线性架构）。

    blind_dsl=True 时在本线程内由 DirectorNode 生成含 script_text 的 timeline，
    再经 DSLParserNode 编译为 CompilationPlan；各矩阵子线程独立调用大模型，
    利用采样随机性产生差异化文案与打标。

    单轨线性架构要点：
      - 每个 Beat 的 script_text 直接驱动 TTS，不再依赖独立 script_data 根节点。
      - context.assets["tts_script"] = {lang: "聚合全文"} 作为 TTSNode 的唯一入口。
      - 无 Beat 台词时（纯积木模式），DirectorNode 兜底生成后同样写入 tts_script。

    纯积木模式（prompt 为空）：注入 default 变体，仅合流 BGM/SFX。
    """
    resolved_file_sid = _validate_child_execution(
        task_id=task_id,
        execution_id=execution_id,
        file_sid=file_sid,
        child_index=child_index,
    )
    logger.info(
        "[render_worker] child 开始 task_id=%s execution_id=%s child_index=%d "
        "file_sid=%s aspect=%s duration=%ds tenant=%s mode=%s",
        task_id, execution_id, child_index, resolved_file_sid,
        aspect_ratio, target_duration, tenant_id,
        "hybrid" if prompt else "dsl-only",
    )

    collected_assets: list[dict] = []
    fatigue_asset_ids: tuple[int, ...] = ()
    _start_time: float = time.time()
    working_plan: Optional[CompilationPlan] = plan

    def _result(
        outcome: str,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> _ChildResult:
        return _ChildResult(
            child_index=child_index,
            execution_id=execution_id,
            file_sid=resolved_file_sid,
            outcome=outcome,
            assets=[dict(asset) for asset in collected_assets],
            elapsed=round(time.time() - _start_time, 3),
            error_code=error_code,
            error_message=(error_message[:500] if error_message else None),
            prompt_details=_child_prompt_details(dsl_payload, working_plan),
            fatigue_asset_ids=fatigue_asset_ids,
        )

    try:
        if blind_dsl:
            if not prompt or not str(prompt).strip():
                logger.error(
                    "[render_worker] blind_dsl 需要非空 prompt，task_id=%s", task_id,
                )
                return _result("failed", "BLIND_PROMPT_MISSING", "blind_dsl requires prompt")
            langs = [test_language] if test_language else ["en"]
            director = DirectorNode()

            # 注入可用标签菜单（防幻觉）：从租户库实时抽取真实存在的 Faceted Tags
            _available_tags = _fetch_available_tags(tenant_id)
            logger.info(
                "[render_worker] task_id=%s 标签菜单注入：%d 个可用标签供 LLM 约束",
                task_id, len(_available_tags),
            )

            bp = director.draft_blueprint(
                str(prompt).strip(),
                director_mode,
                target_duration,
                langs,
                available_tags=_available_tags,
                llm_temperature=0.92,
            )
            # 单轨模式：script_text 已内聚于各 Beat，无需独立 script_data 根节点
            logger.info(
                "[render_worker] task_id=%s 单轨闭眼裂变：DirectorNode 生成含 script_text 的 timeline",
                task_id,
            )

            beat_nodes: list[DSLBeatNode] = []
            for i, row in enumerate(bp.get("timeline") or []):
                if not isinstance(row, dict):
                    continue
                try:
                    beat_nodes.append(DSLBeatNode.model_validate(row))
                except Exception:
                    logger.warning(
                        "[render_worker] task_id=%s timeline[%d] 非法，跳过: %r",
                        task_id, i, row,
                    )
            if not beat_nodes:
                logger.error(
                    "[render_worker] task_id=%s blind_dsl 无有效 Beat，终止。", task_id,
                )
                return _result("failed", "BLIND_TIMELINE_EMPTY", "blind_dsl produced no beats")

            dsl_payload = StoryDSLPayload(
                engine_type=engine_type,
                timeline=beat_nodes,
                meta=bp.get("meta") or None,
            )
            working_plan = _parse_plan_from_db(tenant_id, dsl_payload)
            logger.info(
                "[render_worker] task_id=%s blind_dsl 解析 resolved=%d/%d unresolved=%s",
                task_id,
                working_plan.summary.resolved_beats,
                working_plan.summary.total_beats,
                working_plan.unresolved_beats or "[]",
            )
            if working_plan.summary.resolved_beats == 0:
                logger.error(
                    "[render_worker] task_id=%s blind_dsl 无可渲染 Beat：%s",
                    task_id,
                    working_plan.unresolved_beats,
                )
                return _result("failed", "PLAN_UNRESOLVED", "blind_dsl resolved no beats")
        else:
            if plan_is_authoritative:
                if plan is None:
                    logger.error(
                        "[render_worker] task_id=%s authoritative plan missing", task_id,
                    )
                    return _result(
                        "failed",
                        "AUTHORITATIVE_PLAN_MISSING",
                        "authoritative child requires CompilationPlan",
                    )
                # Exact-policy children retain raw DSL for script/meta only.
                # Their accepted visual plan must never be silently re-resolved.
                working_plan = plan
                _emit_authoritative_variant_fingerprint(
                    working_plan,
                    planner_fingerprint=visual_fingerprint,
                    task_id=task_id,
                    execution_id=execution_id,
                    child_index=child_index,
                    file_sid=resolved_file_sid,
                )
            elif dsl_payload is not None:
                # 动态运行时寻址：Worker 线程内独立重新执行资产抽卡，
                # 确保批量并发时各子任务命中不同素材（_score_candidates + random.choice）
                working_plan = _parse_plan_from_db(tenant_id, dsl_payload)
                logger.info(
                    "[render_worker] task_id=%s 动态寻址完成 resolved=%d/%d",
                    task_id,
                    working_plan.summary.resolved_beats,
                    working_plan.summary.total_beats,
                )
                if working_plan.summary.resolved_beats == 0:
                    logger.error(
                        "[render_worker] task_id=%s 动态寻址无可渲染 Beat，终止。", task_id,
                    )
                    return _result("failed", "PLAN_UNRESOLVED", "DSL resolved no beats")
            elif plan is not None:
                working_plan = plan
            else:
                logger.error(
                    "[render_worker] task_id=%s 缺少 CompilationPlan 或 StoryDSLPayload（非 blind_dsl）",
                    task_id,
                )
                return _result("failed", "PLAN_MISSING", "no CompilationPlan or DSL payload")

        # ── 1. CompilationPlan → Timeline ─────────────────────────────
        assert working_plan is not None, "working_plan must be resolved before this point"
        timeline = compile_plan_to_timeline(
            working_plan, target_duration=target_duration,
        )

        if not timeline.tracks:
            logger.error(
                "[render_worker] task_id=%s Timeline 主视频轨为空，终止渲染。",
                task_id,
            )
            return _result(
                "failed",
                "TIMELINE_EMPTY",
                "main video timeline is empty",
            )

        # ── 2. 初始化 WorkflowContext，将 Timeline 注入数据总线 ─────────
        context = WorkflowContext(
            session_id=task_id,
            aspect_ratio=aspect_ratio,
            target_duration=target_duration,
            tenant_id=tenant_id,
            batch_size=batch_size,
            test_language=test_language,
        )
        context.set_asset("timeline", timeline)

        # ── 3. 显式 child execution identity ───────────────────────────
        # context.session_id 保持 shared task/UI/WS identity；写路径与短输出名
        # 分别使用 execution_id / file_sid，不再复用语义含混的 config session_id。
        context.config["execution_id"] = execution_id
        context.config["file_sid"] = resolved_file_sid
        context.config["child_index"] = child_index
        context.config["enable_tts"] = enable_tts
        context.config["enable_subtitles"] = enable_subtitles
        # render_worker is always a child execution.  The submitted-task
        # terminal event belongs exclusively to render_batch_worker.
        context.config["ws_terminal_managed_by_coordinator"] = True
        os.makedirs("output", exist_ok=True)

        # ── 4. 动态模态路由 ────────────────────────────────────────────
        if prompt:
            logger.info(
                "[render_worker] task_id=%s 混合编排：单轨台词 → TTS → Subtitle → Compositor",
                task_id,
            )

            # 单轨原位提取：从 dsl_payload.timeline 各 Beat 的 script_text 聚合
            _active_payload = dsl_payload
            _beat_texts = [
                b.script_text.strip()
                for b in (_active_payload.timeline if _active_payload else [])
                if b.script_text and b.script_text.strip()
            ]

            if _beat_texts:
                _tts_lang = test_language or "en"
                context.set_asset("tts_script", {_tts_lang: "\n".join(_beat_texts)})
                logger.info(
                    "[render_worker] task_id=%s 单轨模式：聚合 %d 个 Beat script_text "
                    "→ tts_script[%s] len=%d",
                    task_id, len(_beat_texts), _tts_lang,
                    sum(len(t) for t in _beat_texts),
                )
            else:
                # 无 Beat 台词 → DirectorNode 兜底生成（写入 context.assets["tts_script"]）
                logger.info(
                    "[render_worker] task_id=%s Beat 无 script_text，导演节点兜底生成台词",
                    task_id,
                )
                context.set_asset("script", prompt)
                DirectorNode().execute(context)

            # TTSNode 读取 tts_script，将 MP3 + VTT 写入 context.variants[lang]
            if enable_tts:
                TTSNode().execute(context)
            else:
                logger.info(
                    "[render_worker] task_id=%s enable_tts=False，跳过 TTS 播音节点，"
                    "仅保留 BGM 音轨",
                    task_id,
                )

            # ── TranslationBridge（内联）：从 tts_script + Beat 时长计算字幕时间轴 ──
            if enable_subtitles:
                tts_script: dict = context.get_asset("tts_script") or {}
                _translations: dict = {
                    lang: text
                    for lang, text in tts_script.items()
                    if text and str(text).strip()
                }
                # Beat 时长累加；若 LLM 未提供 duration，回退至 target_duration
                _beats_for_dur = _active_payload.timeline if _active_payload else []
                _total_duration = sum(
                    float(b.duration) for b in _beats_for_dur if b.duration
                )
                if _total_duration <= 0:
                    _total_duration = float(target_duration)

                context.config["translations"] = _translations
                context.config["subtitle_start"] = 0.0
                context.config["subtitle_end"] = _total_duration
                logger.debug(
                    "[render_worker] task_id=%s TranslationBridge: langs=%s subtitle_end=%.1fs",
                    task_id,
                    list(_translations.keys()),
                    _total_duration,
                )
                SubtitleNode().execute(context)
            else:
                logger.info(
                    "[render_worker] task_id=%s enable_subtitles=False，跳过字幕烧录节点",
                    task_id,
                )

            # 确认字幕文件已注入 context
            target_lang = getattr(context, "test_language", "en") or "en"
            _subtitle_ass = (context.variants.get(target_lang) or {}).get("subtitle_ass", "")
            if _subtitle_ass:
                logger.debug(
                    "[render_worker] task_id=%s 字幕文件已写入 context: lang=%s path=%s",
                    task_id, target_lang, _subtitle_ass,
                )
            else:
                logger.warning(
                    "[render_worker] task_id=%s SubtitleNode 未生成字幕（lang=%s），"
                    "Compositor 将跳过字幕轨道。",
                    task_id, target_lang,
                )
        else:
            logger.info("[render_worker] task_id=%s 纯积木模式：注入 default 变体触发 BGM/SFX 混音", task_id)
            # ADR-1 延后混音：无 TTS 时手动注入 default 变体，
            # 驱动 compositor._render_variant 进入 BGM/SFX 合流阶段。
            context.variants = {"default": {}}

        # ── 5. 渲染前安检（Pre-flight Check）────────────────────────────
        # 统计有效主视频层（layer_index == 0）数量；归零则熔断，绝不下发 FFmpeg。
        _valid_main_clips = sum(
            1
            for _beat in (working_plan.beats if working_plan else [])
            if _beat.resolved and any(lyr.layer_index == 0 for lyr in _beat.layers)
        )
        if _valid_main_clips == 0:
            logger.error(
                "❌ 任务 %s 缺乏主视觉素材，触发安全熔断！引擎拦截渲染，不调用 FFmpeg。",
                task_id,
            )
            return _result(
                "failed",
                "MAIN_VISUAL_MISSING",
                "no valid layer-0 main visual clips",
            )

        # ── 5b. 引擎点火 ───────────────────────────────────────────────
        render_ok = _run_compositor(FFmpegCompositorNode(), context)

        # ── 5c. 封面抽帧（Phase 9.8.2）─────────────────────────────────
        # CoverNode 为非关键路径：失败只记录日志，不回滚渲染结果。
        if render_ok:
            logger.info(
                "[render_worker] task_id=%s 渲染完成，启动 CoverNode 封面抽帧...",
                task_id,
            )
            cover_ok = _run_cover_node(CoverNode(), context)
            _cover_path: str = context.get_asset("cover_path") or ""
            if cover_ok:
                logger.info(
                    "[render_worker] task_id=%s CoverNode ✅ 封面生成成功: %s",
                    task_id, _cover_path,
                )
            else:
                logger.warning(
                    "[render_worker] task_id=%s CoverNode ⚠️ 封面抽帧失败，"
                    "前端将显示缺省占位块。",
                    task_id,
                )
        else:
            _cover_path = ""

        # ── 6. 收集输出资产 ─────────────────────────────────────────────
        # 提取社交元数据，随资产一并写入 WS payload，前端无需二次 API 请求即可渲染 HUD
        _social_fields: dict = {}
        if dsl_payload is not None and dsl_payload.meta is not None:
            try:
                _meta_dump = dsl_payload.meta.model_dump()
                _social_fields = {
                    k: _meta_dump[k]
                    for k in ("social_title", "social_caption", "social_hashtags")
                    if _meta_dump.get(k)
                }
            except Exception:
                pass

        if render_ok:
            for _variant_assets in context.variants.values():
                _fp = _variant_assets.get("final_video", "")
                if _fp and os.path.exists(_fp):
                    _h = hashlib.md5()
                    try:
                        with open(_fp, "rb") as _f:
                            _h.update(_f.read(65536))
                    except OSError:
                        _h.update(_fp.encode())
                    collected_assets.append({
                        "file_path": _fp,
                        "file_hash": _h.hexdigest(),
                        "cover_path": _cover_path,  # ← CoverNode 执行完毕后才填入，时序正确
                        **_social_fields,
                    })

        # ── 6b. 疲劳值回写 ────────────────────────────────────────────────
        if render_ok and working_plan:
            fatigue_asset_ids = _plan_fatigue_asset_ids(working_plan)

        if render_ok and working_plan and not defer_fatigue_write:
            try:
                used_asset_ids: set[int] = set()
                for beat in working_plan.beats:
                    for layer in beat.layers:
                        if layer.asset_id:
                            used_asset_ids.add(layer.asset_id)

                if used_asset_ids:
                    _tenant_engine = get_tenant_engine(tenant_id)
                    _SessionLocal = sessionmaker(
                        autocommit=False, autoflush=False, bind=_tenant_engine
                    )
                    with _SessionLocal() as db:
                        now = datetime.utcnow()
                        assets = (
                            db.query(LocalAsset)
                            .filter(
                                LocalAsset.id.in_(used_asset_ids),
                                LocalAsset.is_deleted.is_(False),
                            )
                            .all()
                        )
                        for asset in assets:
                            asset.usage_count = (asset.usage_count or 0) + 1  # type: ignore[assignment]
                            asset.last_used_at = now  # type: ignore[assignment]
                        db.commit()
                    logger.info(
                        "[render_worker] task_id=%s 疲劳值回写成功，共刷新 %d 个弹药资产。",
                        task_id, len(assets),
                    )
                else:
                    logger.debug(
                        "[render_worker] task_id=%s plan.beats 中无 asset_id，跳过疲劳值回写。",
                        task_id,
                    )
            except Exception:
                logger.exception(
                    "[render_worker] task_id=%s 疲劳值回写失败，请排查事务。", task_id
                )

        if render_ok and collected_assets:
            return _result("succeeded")
        if not render_ok:
            return _result("failed", "RENDER_FAILED", "compositor did not complete")
        return _result("failed", "NO_FINAL_OUTPUT", "render produced no final output")

    except Exception as exc:
        logger.exception(
            "[render_worker] child 异常 task_id=%s execution_id=%s "
            "child_index=%d file_sid=%s",
            task_id, execution_id, child_index, resolved_file_sid,
        )
        return _result("failed", "CHILD_EXCEPTION", str(exc))
    finally:
        logger.info(
            "[render_worker] child 结束 task_id=%s execution_id=%s "
            "child_index=%d file_sid=%s assets=%d elapsed=%.1fs",
            task_id, execution_id, child_index, resolved_file_sid,
            len(collected_assets), time.time() - _start_time,
        )


def _failed_child_result(
    child: _ChildExecution,
    error_code: str,
    error_message: str,
    elapsed: float = 0.0,
) -> _ChildResult:
    return _ChildResult(
        child_index=child.child_index,
        execution_id=child.execution_id,
        file_sid=child.file_sid,
        outcome="failed",
        assets=[],
        elapsed=round(elapsed, 3),
        error_code=error_code,
        error_message=error_message[:500],
        prompt_details={"meta": None, "timeline": []},
    )


def _build_task_history_record(
    *,
    task_id: str,
    prompt: Optional[str],
    batch_size: int,
    elapsed: float,
    child_results: list[_ChildResult],
    output_assets: list[dict],
    warning_codes: list[str],
    coverage_diagnostics: Optional[dict[str, Any]] = None,
    historical_novelty_diagnostics: Optional[dict[str, Any]] = None,
) -> TaskHistory:
    first_success = next(result for result in child_results if result.succeeded)
    legacy_details = first_success.prompt_details
    planning_summary: dict[str, Any] = {
        "requested_count": batch_size,
        "planned_count": len(child_results),
        "succeeded_count": sum(result.succeeded for result in child_results),
        "failed_count": sum(not result.succeeded for result in child_results),
        "warning_codes": list(warning_codes),
    }
    if coverage_diagnostics is not None:
        planning_summary["coverage_diagnostics"] = coverage_diagnostics
    if historical_novelty_diagnostics is not None:
        planning_summary["historical_novelty_diagnostics"] = (
            historical_novelty_diagnostics
        )
    prompt_details: dict[str, Any] = {
        "meta": legacy_details.get("meta"),
        "timeline": legacy_details.get("timeline") or [],
        "planning_summary": planning_summary,
        "children": [
            {
                "child_index": result.child_index,
                "execution_id": result.execution_id,
                "file_sid": result.file_sid,
                "outcome": "succeeded" if result.succeeded else "failed",
                "elapsed": result.elapsed,
                "error_code": result.error_code,
                "output_assets": [dict(asset) for asset in result.assets],
                "timeline": result.prompt_details.get("timeline") or [],
            }
            for result in child_results
        ],
    }
    return TaskHistory(
        task_id=task_id,
        prompt=prompt or "",
        batch_size=batch_size,
        duration=round(elapsed, 1),
        output_assets=output_assets,
        prompt_details=json.dumps(prompt_details, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )


def _persist_task_history(
    *,
    task_id: str,
    tenant_id: str,
    prompt: Optional[str],
    batch_size: int,
    elapsed: float,
    child_results: list[_ChildResult],
    output_assets: list[dict],
    warning_codes: list[str],
    coverage_diagnostics: Optional[dict[str, Any]] = None,
    historical_novelty_diagnostics: Optional[dict[str, Any]] = None,
    ledger_terminal_records: Sequence[FingerprintOccurrenceRecord] = (),
) -> bool:
    """Persist the single completed-result row owned by the coordinator."""
    history_record = _build_task_history_record(
        task_id=task_id,
        prompt=prompt,
        batch_size=batch_size,
        elapsed=elapsed,
        child_results=child_results,
        output_assets=output_assets,
        warning_codes=warning_codes,
        coverage_diagnostics=coverage_diagnostics,
        historical_novelty_diagnostics=historical_novelty_diagnostics,
    )
    history_engine = get_tenant_engine(tenant_id)
    HistorySession = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=history_engine,
    )
    with HistorySession() as db:
        db.add(history_record)
        ledger_persisted = True
        if ledger_terminal_records:
            db.flush()
            try:
                with db.begin_nested():
                    _record_fingerprint_ledger_records(
                        db,
                        ledger_terminal_records,
                    )
            except Exception as exc:
                ledger_persisted = False
                try:
                    fingerprint_logger.warning(
                        "[FINGERPRINT_LEDGER_SHADOW_WRITE_FAILED] "
                        f"phase=terminal_history task_id={task_id[:64]} "
                        f"count={len(ledger_terminal_records)} "
                        f"error={type(exc).__name__[:64]} detail={str(exc)[:128]}"
                    )
                except Exception:
                    pass
        db.commit()
    return ledger_persisted


def _reservation_execution_bindings(
    *,
    task_id: str,
    planning_result: _VariantPlanningResult,
    computed_fingerprints: Sequence[_MainVisualFingerprint],
    child_work: Sequence[_ChildWork],
    reservation_controller: PlannerReservationController,
) -> tuple[PlannerReservationExecutionBinding, ...]:
    """Validate the authoritative plan/FP/slot/execution handoff."""
    controller_bindings = reservation_controller.bindings
    result_bindings = planning_result.reservation_bindings
    expected_count = len(planning_result.plans)
    if (
        reservation_controller.owner_task_id != task_id
        or len(computed_fingerprints) != expected_count
        or len(controller_bindings) != expected_count
        or len(result_bindings) != expected_count
        or len(child_work) != expected_count
        or controller_bindings != result_bindings
    ):
        raise PlannerReservationError(
            "PLANNER_RESERVATION_COORDINATOR_BINDING_COUNT_MISMATCH"
        )

    execution_bindings: list[PlannerReservationExecutionBinding] = []
    for slot, (binding, fingerprint, work) in enumerate(
        zip(controller_bindings, computed_fingerprints, child_work)
    ):
        contract = _main_visual_planning_fingerprint_contract(fingerprint)
        if (
            binding.owner_task_id != task_id
            or binding.owner_slot_index != slot
            or work.execution.child_index != slot
            or work.authoritative_plan != planning_result.plans[slot]
            or work.visual_fingerprint != fingerprint
            or binding.fingerprint_type != contract.fingerprint_type
            or binding.fingerprint_version != contract.fingerprint_version
            or binding.fingerprint_digest != contract.fingerprint_digest
        ):
            raise PlannerReservationError(
                "PLANNER_RESERVATION_COORDINATOR_BINDING_ALIGNMENT_MISMATCH"
            )
        execution_bindings.append(
            PlannerReservationExecutionBinding(
                fingerprint_identity_id=binding.fingerprint_identity_id,
                owner_task_id=task_id,
                owner_slot_index=slot,
                execution_id=work.execution.execution_id,
            )
        )
    return tuple(execution_bindings)


def _persist_reservation_authoritative_terminal(
    *,
    reservation_controller: PlannerReservationController,
    execution_bindings: Sequence[PlannerReservationExecutionBinding],
    terminal_ledger_records: Sequence[FingerprintOccurrenceRecord],
    task_id: str,
    prompt: Optional[str],
    batch_size: int,
    elapsed: float,
    child_results: list[_ChildResult],
    output_assets: list[dict],
    warning_codes: list[str],
    coverage_diagnostics: Optional[dict[str, Any]],
    historical_novelty_diagnostics: Optional[dict[str, Any]],
) -> bool:
    """Fence every binding and commit all authoritative terminal side effects."""
    if (
        len(execution_bindings) != len(child_results)
        or len(terminal_ledger_records) != len(child_results)
    ):
        raise PlannerReservationError(
            "PLANNER_RESERVATION_TERMINAL_RESULT_COUNT_MISMATCH"
        )
    expected_by_execution = {
        (binding.owner_slot_index, binding.execution_id): binding
        for binding in execution_bindings
    }
    if len(expected_by_execution) != len(execution_bindings):
        raise PlannerReservationError(
            "PLANNER_RESERVATION_TERMINAL_EXECUTION_IDENTITY_DUPLICATE"
        )
    for result, record in zip(child_results, terminal_ledger_records):
        key = (result.child_index, result.execution_id)
        binding = expected_by_execution.get(key)
        if (
            binding is None
            or record.task_id != binding.owner_task_id
            or record.child_index != binding.owner_slot_index
            or record.execution_id != binding.execution_id
            or record.lifecycle_event
            != ("RENDERED" if result.succeeded else "FAILED")
        ):
            raise PlannerReservationError(
                "PLANNER_RESERVATION_TERMINAL_RESULT_ALIGNMENT_MISMATCH"
            )
    succeeded_count = sum(result.succeeded for result in child_results)
    fatigue_counts: Counter[int] = Counter(
        asset_id
        for result in child_results
        if result.succeeded
        for asset_id in result.fatigue_asset_ids
    )

    def _write_terminal(session: Session) -> None:
        _record_fingerprint_ledger_records(session, terminal_ledger_records)
        _apply_fatigue_updates(
            session,
            fatigue_counts,
            used_at=datetime.utcnow(),
        )
        # Preserve the existing zero-success TaskHistory limitation.
        if succeeded_count:
            session.add(
                _build_task_history_record(
                    task_id=task_id,
                    prompt=prompt,
                    batch_size=batch_size,
                    elapsed=elapsed,
                    child_results=child_results,
                    output_assets=output_assets,
                    warning_codes=warning_codes,
                    coverage_diagnostics=coverage_diagnostics,
                    historical_novelty_diagnostics=(
                        historical_novelty_diagnostics
                    ),
                )
            )

    reservation_controller.run_fenced_terminal_transaction(
        execution_bindings,
        _write_terminal,
    )
    return bool(succeeded_count)


def render_batch_worker(
    dsl_payload: Optional[StoryDSLPayload],
    task_id: str,
    aspect_ratio: str = "9:16",
    target_duration: int = 15,
    tenant_id: str = "default",
    prompt: Optional[str] = None,
    batch_size: int = 1,
    test_language: str = "en",
    *,
    blind_dsl: bool = False,
    engine_type: str = "content",
    director_mode: str = "auto",
    enable_tts: bool = True,
    enable_subtitles: bool = True,
    resolved_plan: Optional[CompilationPlan] = None,
    variant_planning_policy: str = "legacy",
    historical_novelty_mode: str = _HISTORICAL_MODE_OFF,
    preview_intent: PreviewIntent = PreviewIntent.UNSPECIFIED,
    reservation_controller: Optional[PlannerReservationController] = None,
) -> dict[str, Any]:
    """
    批量矩阵渲染 Worker（Phase 5.9）。

    所有 batch size 都经过本 coordinator。每个 child 仅返回 execution-local
    result；本函数稳定聚合、写入一条 TaskHistory，并发送唯一 terminal WS。
    """
    batch_start = time.time()
    logger.info(
        "[render_batch_worker] 批量渲染启动 task_id=%s batch=%d",
        task_id, batch_size,
    )

    planning_warning_codes: list[str] = []
    coverage_diagnostics_payload: Optional[dict[str, Any]] = None
    historical_novelty_diagnostics_payload: Optional[dict[str, Any]] = None
    child_work: list[_ChildWork] = []
    planned_ledger_records: tuple[FingerprintOccurrenceRecord, ...] = ()
    reservation_execution_bindings: tuple[
        PlannerReservationExecutionBinding, ...
    ] = ()
    reservation_authority_lost = False
    reservation_terminal_persist_failed = False

    if reservation_controller is not None:
        if reservation_controller.owner_task_id != task_id:
            reservation_controller.abort()
            raise PlannerReservationError(
                "PLANNER_RESERVATION_WORKER_OWNER_MISMATCH"
            )
        if variant_planning_policy not in {
            "exact_main_visual",
            "exact_main_visual_balanced",
        }:
            reservation_controller.abort()
            raise PlannerReservationError(
                "PLANNER_RESERVATION_AUTHORITATIVE_POLICY_REQUIRED"
            )
    planning_function = None
    if variant_planning_policy == "exact_main_visual":
        planning_function = _plan_exact_main_visual_variants_from_db
    elif variant_planning_policy == "exact_main_visual_balanced":
        planning_function = _plan_exact_main_visual_balanced_variants_from_db

    if planning_function is not None:
        if blind_dsl or dsl_payload is None:
            logger.error(
                "[render_batch_worker] authoritative planning received unsupported/missing "
                "DSL task_id=%s policy=%s blind=%s",
                task_id,
                variant_planning_policy,
                blind_dsl,
            )
            planning_warning_codes.append("VARIANT_PLANNING_FAILED")
        else:
            staged_coverage_diagnostics_payload: Optional[dict[str, Any]] = None
            staged_historical_novelty_diagnostics_payload: Optional[
                dict[str, Any]
            ] = None
            try:
                planning_kwargs: dict[str, Any] = {
                    "preview_plan": resolved_plan,
                }
                if reservation_controller is not None:
                    planning_kwargs["reservation_controller"] = (
                        reservation_controller
                    )
                if historical_novelty_mode != _HISTORICAL_MODE_OFF:
                    planning_kwargs.update({
                        "historical_novelty_mode": historical_novelty_mode,
                        "preview_intent": preview_intent,
                    })
                planning_result = planning_function(
                    tenant_id,
                    dsl_payload,
                    batch_size,
                    **planning_kwargs,
                )
                computed_fingerprints = tuple(
                    _exact_main_visual_fingerprint(plan)
                    for plan in planning_result.plans
                )
                if (
                    computed_fingerprints != planning_result.fingerprints
                    or len(set(computed_fingerprints)) != len(computed_fingerprints)
                ):
                    raise ValueError(
                        "PLANNER_RESULT_INVALID: authoritative plans/fingerprints mismatch"
                    )
                if variant_planning_policy == _BALANCED_VARIANT_PLANNING_POLICY:
                    if planning_result.coverage_diagnostics is None:
                        raise ValueError("COVERAGE_DIAGNOSTICS_MISSING")
                    staged_coverage_diagnostics_payload = (
                        _validated_coverage_diagnostics_payload(
                            planning_result.coverage_diagnostics,
                            planning_result,
                            computed_fingerprints,
                        )
                    )
                    _emit_balanced_coverage_summary(
                        task_id,
                        staged_coverage_diagnostics_payload,
                    )
                elif planning_result.coverage_diagnostics is not None:
                    raise ValueError("COVERAGE_DIAGNOSTICS_UNEXPECTED_FOR_EXACT_POLICY")
                if historical_novelty_mode == _HISTORICAL_MODE_OFF:
                    if planning_result.historical_novelty_diagnostics is not None:
                        raise ValueError(
                            "HISTORICAL_NOVELTY_DIAGNOSTICS_UNEXPECTED_FOR_OFF"
                        )
                else:
                    if planning_result.historical_novelty_diagnostics is None:
                        raise ValueError("HISTORICAL_NOVELTY_DIAGNOSTICS_MISSING")
                    staged_historical_novelty_diagnostics_payload = (
                        _validated_historical_novelty_diagnostics_payload(
                            planning_result.historical_novelty_diagnostics,
                            planning_result,
                            historical_novelty_mode,
                        )
                    )
                    _emit_historical_novelty_summary(
                        task_id,
                        staged_historical_novelty_diagnostics_payload,
                    )
                planning_warning_codes.extend(planning_result.warning_codes)
                identities = (
                    _create_child_executions(task_id, len(planning_result.plans))
                    if planning_result.plans
                    else []
                )
                staged_child_work = [
                    _ChildWork(
                        execution=identity,
                        authoritative_plan=plan,
                        visual_fingerprint=fingerprint,
                    )
                    for identity, plan, fingerprint in zip(
                        identities,
                        planning_result.plans,
                        computed_fingerprints,
                    )
                ]
                if reservation_controller is not None:
                    reservation_execution_bindings = (
                        _reservation_execution_bindings(
                            task_id=task_id,
                            planning_result=planning_result,
                            computed_fingerprints=computed_fingerprints,
                            child_work=staged_child_work,
                            reservation_controller=reservation_controller,
                        )
                    )
                    planned_ledger_records = tuple(
                        _fingerprint_ledger_occurrence_record(
                            work,
                            task_id,
                            "PLANNED",
                        )
                        for work in staged_child_work
                    )
                    reservation_controller.confirm_and_record_planned(
                        reservation_execution_bindings,
                        planned_ledger_records,
                    )
                    reservation_controller.require_active()
                child_work = staged_child_work
                logger.info(
                    "[render_batch_worker] authoritative planning task_id=%s policy=%s "
                    "requested=%d planned=%d examined=%d space=%d reason=%s warnings=%s",
                    task_id,
                    variant_planning_policy,
                    batch_size,
                    len(child_work),
                    planning_result.examined_combinations,
                    planning_result.candidate_space_size,
                    planning_result.termination_reason,
                    planning_warning_codes,
                )
            except PlannerReservationAuthorityLost:
                reservation_authority_lost = True
                logger.exception(
                    "[render_batch_worker] Reservation authority lost before child "
                    "start task_id=%s policy=%s",
                    task_id,
                    variant_planning_policy,
                )
                planning_warning_codes.append(_RESERVATION_AUTHORITY_LOST)
                if reservation_controller is not None:
                    reservation_controller.abort()
            except Exception:
                logger.exception(
                    "[render_batch_worker] authoritative planning failed task_id=%s "
                    "policy=%s",
                    task_id,
                    variant_planning_policy,
                )
                planning_warning_codes.append("VARIANT_PLANNING_FAILED")
                if reservation_controller is not None:
                    reservation_controller.abort()
            else:
                coverage_diagnostics_payload = staged_coverage_diagnostics_payload
                historical_novelty_diagnostics_payload = (
                    staged_historical_novelty_diagnostics_payload
                )
    elif variant_planning_policy == "legacy":
        child_work = [
            _ChildWork(execution=child)
            for child in _create_child_executions(task_id, batch_size)
        ]
    else:
        logger.error(
            "[render_batch_worker] unsupported variant planning policy task_id=%s policy=%s",
            task_id,
            variant_planning_policy,
        )
        planning_warning_codes.append("VARIANT_PLANNING_FAILED")

    if (
        reservation_controller is None
        and child_work
        and all(work.visual_fingerprint is not None for work in child_work)
    ):
        try:
            planned_ledger_records = tuple(
                _fingerprint_ledger_occurrence_record(work, task_id, "PLANNED")
                for work in child_work
            )
            _record_fingerprint_ledger_records_safely(
                tenant_id,
                planned_ledger_records,
                phase="planned",
            )
        except Exception as exc:
            planned_ledger_records = ()
            try:
                fingerprint_logger.warning(
                    "[FINGERPRINT_LEDGER_SHADOW_WRITE_FAILED] "
                    f"phase=planned_build task_id={task_id[:64]} "
                    f"count={len(child_work)} error={type(exc).__name__[:64]}"
                )
            except Exception:
                pass

    child_results: list[_ChildResult] = []

    def _execute_child(work: _ChildWork) -> _ChildResult:
        child = work.execution
        child_start = time.time()
        try:
            result = render_worker(
                (
                    work.authoritative_plan
                    if work.authoritative_plan is not None
                    else (None if blind_dsl else resolved_plan)
                ),
                task_id,
                aspect_ratio, target_duration, tenant_id,
                prompt, batch_size, test_language,
                child.file_sid,
                execution_id=child.execution_id,
                child_index=child.child_index,
                blind_dsl=blind_dsl,
                engine_type=engine_type,
                director_mode=director_mode,
                dsl_payload=None if blind_dsl else dsl_payload,
                plan_is_authoritative=work.authoritative_plan is not None,
                visual_fingerprint=work.visual_fingerprint,
                enable_tts=enable_tts,
                enable_subtitles=enable_subtitles,
                defer_fatigue_write=reservation_controller is not None,
            )
            if not isinstance(result, _ChildResult):
                raise TypeError("render_worker must return _ChildResult")
            if (
                result.child_index != child.child_index
                or result.execution_id != child.execution_id
                or result.file_sid != child.file_sid
            ):
                raise ValueError("render_worker returned mismatched child identity")
            return result
        except Exception as exc:
            logger.exception(
                "[render_batch_worker] child 异常 task_id=%s execution_id=%s "
                "child_index=%d file_sid=%s",
                task_id, child.execution_id, child.child_index, child.file_sid,
            )
            return _failed_child_result(
                child,
                "CHILD_EXCEPTION",
                str(exc),
                time.time() - child_start,
            )

    if reservation_controller is not None and child_work:
        try:
            reservation_controller.require_active()
        except PlannerReservationAuthorityLost:
            reservation_authority_lost = True
            child_work = []
            if _RESERVATION_AUTHORITY_LOST not in planning_warning_codes:
                planning_warning_codes.append(_RESERVATION_AUTHORITY_LOST)

    if len(child_work) == 1:
        child_results.append(_execute_child(child_work[0]))
    elif len(child_work) > 1:
        with ThreadPoolExecutor(max_workers=len(child_work)) as pool:
            future_map = {}
            for work in child_work:
                if reservation_controller is not None:
                    try:
                        reservation_controller.require_active()
                    except PlannerReservationAuthorityLost:
                        reservation_authority_lost = True
                        break
                future_map[pool.submit(_execute_child, work)] = work.execution
            for future in as_completed(future_map):
                child = future_map[future]
                try:
                    child_results.append(future.result())
                except Exception as exc:
                    logger.exception(
                        "[render_batch_worker] future 收口异常 task_id=%s execution_id=%s "
                        "child_index=%d file_sid=%s",
                        task_id, child.execution_id, child.child_index, child.file_sid,
                    )
                    child_results.append(
                        _failed_child_result(child, "CHILD_FUTURE_FAILED", str(exc))
                    )

    child_results.sort(key=lambda result: result.child_index)
    for result in child_results:
        log_method = logger.info if result.succeeded else logger.warning
        log_method(
            "[render_batch_worker] child 收口 task_id=%s execution_id=%s "
            "child_index=%d file_sid=%s outcome=%s assets=%d error_code=%s",
            task_id, result.execution_id, result.child_index, result.file_sid,
            "succeeded" if result.succeeded else "failed",
            len(result.assets), result.error_code,
        )
    successful_results = [result for result in child_results if result.succeeded]
    all_assets = [
        dict(asset)
        for result in successful_results
        for asset in result.assets
    ]
    succeeded_count = len(successful_results)
    failed_count = len(child_results) - succeeded_count
    planned_count = (
        len(reservation_execution_bindings)
        if reservation_controller is not None
        else len(child_results)
    )
    partial = succeeded_count > 0 and (
        failed_count > 0 or planned_count < batch_size
    )
    warning_codes = list(dict.fromkeys(planning_warning_codes))
    if failed_count and "CHILD_EXECUTION_FAILED" not in warning_codes:
        warning_codes.append("CHILD_EXECUTION_FAILED")

    authoritative_work_by_identity = {
        (work.execution.child_index, work.execution.execution_id): work
        for work in child_work
        if work.visual_fingerprint is not None
    }
    terminal_ledger_records: tuple[FingerprintOccurrenceRecord, ...] = ()
    try:
        terminal_ledger_records = tuple(
            _fingerprint_ledger_occurrence_record(
                authoritative_work_by_identity[(result.child_index, result.execution_id)],
                task_id,
                "RENDERED" if result.succeeded else "FAILED",
            )
            for result in child_results
            if (result.child_index, result.execution_id) in authoritative_work_by_identity
        )
    except Exception as exc:
        terminal_ledger_records = ()
        if reservation_controller is not None:
            reservation_terminal_persist_failed = True
        try:
            fingerprint_logger.warning(
                "[FINGERPRINT_LEDGER_SHADOW_WRITE_FAILED] "
                f"phase=terminal_build task_id={task_id[:64]} "
                f"count={len(child_results)} error={type(exc).__name__[:64]}"
            )
        except Exception:
            pass

    history_persisted = False
    terminal_ledger_persisted = not terminal_ledger_records
    elapsed = time.time() - batch_start
    if reservation_controller is not None and reservation_execution_bindings:
        if reservation_authority_lost:
            terminal_ledger_persisted = False
        elif reservation_terminal_persist_failed:
            terminal_ledger_persisted = False
        else:
            try:
                history_persisted = _persist_reservation_authoritative_terminal(
                    reservation_controller=reservation_controller,
                    execution_bindings=reservation_execution_bindings,
                    terminal_ledger_records=terminal_ledger_records,
                    task_id=task_id,
                    prompt=prompt,
                    batch_size=batch_size,
                    elapsed=elapsed,
                    child_results=child_results,
                    output_assets=all_assets,
                    warning_codes=warning_codes,
                    coverage_diagnostics=coverage_diagnostics_payload,
                    historical_novelty_diagnostics=(
                        historical_novelty_diagnostics_payload
                    ),
                )
                terminal_ledger_persisted = True
            except PlannerReservationAuthorityLost:
                reservation_authority_lost = True
                terminal_ledger_persisted = False
                logger.exception(
                    "[render_batch_worker] Reservation terminal authority lost "
                    "task_id=%s",
                    task_id,
                )
            except Exception:
                reservation_terminal_persist_failed = True
                terminal_ledger_persisted = False
                logger.exception(
                    "[render_batch_worker] Reservation terminal transaction failed "
                    "task_id=%s",
                    task_id,
                )
        reservation_controller.abort()
    elif reservation_controller is not None:
        # No accepted bindings still has an owned controller lifecycle to quiesce.
        reservation_controller.abort()
    elif succeeded_count:
        try:
            terminal_ledger_persisted = _persist_task_history(
                task_id=task_id,
                tenant_id=tenant_id,
                prompt=prompt,
                batch_size=batch_size,
                elapsed=elapsed,
                child_results=child_results,
                output_assets=all_assets,
                warning_codes=warning_codes,
                coverage_diagnostics=coverage_diagnostics_payload,
                historical_novelty_diagnostics=(
                    historical_novelty_diagnostics_payload
                ),
                ledger_terminal_records=terminal_ledger_records,
            )
            history_persisted = True
            logger.info(
                "[render_batch_worker] 历史记录写入成功 task_id=%s outputs=%d",
                task_id, len(all_assets),
            )
        except Exception:
            warning_codes.append("HISTORY_PERSIST_FAILED")
            logger.exception(
                "[render_batch_worker] 历史记录写入失败 task_id=%s；保留渲染结果",
                task_id,
            )

    if (
        reservation_controller is None
        and terminal_ledger_records
        and not terminal_ledger_persisted
    ):
        _record_fingerprint_ledger_records_safely(
            tenant_id,
            terminal_ledger_records,
            phase="terminal_fallback",
        )

    if reservation_authority_lost:
        warning_codes = list(dict.fromkeys(
            [*warning_codes, _RESERVATION_AUTHORITY_LOST]
        ))
        all_assets = []
        history_persisted = False
        final_status = "failed"
        terminal_error_code = _RESERVATION_AUTHORITY_LOST
        terminal_succeeded_count = 0
        terminal_failed_count = planned_count
        partial = False
    elif reservation_terminal_persist_failed:
        warning_codes = list(dict.fromkeys(
            [*warning_codes, _RESERVATION_TERMINAL_PERSIST_FAILED]
        ))
        all_assets = []
        history_persisted = False
        final_status = "failed"
        terminal_error_code = _RESERVATION_TERMINAL_PERSIST_FAILED
        terminal_succeeded_count = 0
        terminal_failed_count = planned_count
        partial = False
    else:
        final_status = "completed" if succeeded_count else "failed"
        terminal_error_code = None
        terminal_succeeded_count = succeeded_count
        terminal_failed_count = failed_count
    terminal_payload: dict[str, Any] = {
        "taskId": task_id,
        "status": final_status,
        "generation_mode": director_mode,
        "partial": partial,
        "requestedCount": batch_size,
        "plannedCount": planned_count,
        "succeededCount": terminal_succeeded_count,
        "failedCount": terminal_failed_count,
        "historyPersisted": history_persisted,
        "warningCodes": warning_codes,
    }
    if terminal_error_code is not None:
        terminal_payload["errorCode"] = terminal_error_code
    if all_assets:
        terminal_payload["assets"] = all_assets
    if coverage_diagnostics_payload is not None:
        terminal_payload["coverageDiagnostics"] = coverage_diagnostics_payload

    try:
        ws_manager.broadcast_sync(
            {"type": "WS_UPDATE", "payload": terminal_payload},
            user_id=tenant_id,
        )
        logger.info(
            "[render_batch_worker] task_id=%s status=%s partial=%s "
            "succeeded=%d failed=%d assets=%d history_persisted=%s",
            task_id, final_status, partial,
            terminal_succeeded_count, terminal_failed_count,
            len(all_assets), history_persisted,
        )
    except Exception:
        logger.exception(
            "[render_batch_worker] WS 广播失败 task_id=%s", task_id,
        )

    return terminal_payload


def _run_compositor(
    compositor: FFmpegCompositorNode,
    context: WorkflowContext,
) -> bool:
    """
    FFmpegCompositorNode 调用封装层。

    独立为函数的目的：BackgroundTasks 线程内的未捕获异常会被 Starlette
    静默丢弃，此处显式捕获并记录完整栈帧，保证渲染失败时有迹可查。

    Returns:
        True  — FFmpeg 渲染成功落盘；
        False — 渲染期间抛出异常，已记录完整栈帧。
    """
    try:
        compositor.execute(context)
        return True
    except Exception:
        logger.exception(
            "[_run_compositor] FFmpeg 渲染失败 task_id=%s execution_id=%s "
            "child_index=%s file_sid=%s",
            context.session_id,
            context.config.get("execution_id"),
            context.config.get("child_index"),
            context.config.get("file_sid"),
        )
        return False


def _run_cover_node(cover: CoverNode, context: WorkflowContext) -> bool:
    """
    CoverNode 调用封装层（Phase 9.8.2）。

    封面抽帧为非关键路径——失败不阻断渲染主流程，仅记录日志。
    Returns:
        True  — 封面 JPEG 已生成并写入 context.assets["cover_path"]；
        False — 抽帧失败，context 不含 cover_path（前端降级显示占位）。
    """
    try:
        cover.execute(context)
        return bool(context.get_asset("cover_path"))
    except Exception:
        logger.exception(
            "[_run_cover_node] CoverNode 异常（不阻断主流程） task_id=%s "
            "execution_id=%s child_index=%s file_sid=%s",
            context.session_id,
            context.config.get("execution_id"),
            context.config.get("child_index"),
            context.config.get("file_sid"),
        )
        return False


# ================================================================== #
# POST /tasks/draft-blueprint  — 战术板同步蓝图  (Phase 9.2)         #
# ================================================================== #


@router.post(
    "/draft-blueprint",
    status_code=status.HTTP_200_OK,
    summary="导演同步起草蓝图（timeline + script_data）",
    description=(
        "同步调用 DirectorNode.draft_blueprint，返回单次 LLM 融合结构：\n"
        "视觉 timeline（DSL Beat 意向）与 script_data（TTS 台词轨），"
        "供战术板预览与微调后再走 submit-dsl。"
    ),
)
def draft_blueprint_endpoint(
    body: DraftBlueprintRequest,
    request: Request,
) -> dict[str, Any]:
    # 如果前端没有提供可用标签，从租户库自动查询并注入（防幻觉菜单供给）
    available_tags: list[str] = list(body.available_tags or [])
    if not available_tags:
        _tenant_id = request_tenant_id(request)
        available_tags = _fetch_available_tags(_tenant_id)
        logger.info(
            "[routes_dsl] draft-blueprint 自动注入标签菜单：%d 个可用标签（tenant=%s）",
            len(available_tags), _tenant_id,
        )

    return DirectorNode().draft_blueprint(
        body.prompt,
        body.mode,
        body.duration,
        body.langs,
        available_tags=available_tags,
        user_hard_tags=body.user_hard_tags,
    )


# ================================================================== #
# POST /tasks/enhance-prompt  — 魔法扩写  (Phase 9.4)                  #
# ================================================================== #


@router.post(
    "/enhance-prompt",
    status_code=status.HTTP_200_OK,
    summary="魔法扩写与自动打标",
    description=(
        "将用户极简短句扩写为生动视频提示词，并从可用标签库中挑选 "
        "1~3 个 `@标签` 追加在文末。复用 OpenAIProvider（BYOK）与 JSON 契约。"
    ),
)
def enhance_prompt_endpoint(body: EnhancePromptRequest) -> dict[str, str]:
    system_prompt = prompt_loader.render_prompt(
        "prompt_enhance.jinja",
        available_tags=body.available_tags,
    )
    provider = OpenAIProvider()
    try:
        result = provider.generate_script(
            prompt=body.prompt.strip(),
            system_prompt=system_prompt,
            temperature=0.7,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        logger.exception("[routes_dsl] enhance-prompt LLM 调用失败")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    enhanced = result.get("enhanced_prompt") if isinstance(result, dict) else None
    if not enhanced or not str(enhanced).strip():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM 返回缺少 enhanced_prompt 字段或内容为空。",
        )
    return {"enhanced_prompt": str(enhanced).strip()}


# ================================================================== #
# POST /tasks/submit-dsl  — 全链路渲染入口  (Phase 5.2 升级)         #
# ================================================================== #

@router.post(
    "/submit-dsl",
    response_model=DSLSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Story DSL 全链路渲染（三合一）",
    description=(
        "接收 Story DSL Payload，一次调用完成：\n\n"
        "1. **DSL 解析**：执行双轨寻址（locked / smart），返回完整 CompilationPlan 蓝图\n"
        "2. **蓝图适配**：将 CompilationPlan → Timeline / Track / Clip 对象树\n"
        "3. **后台渲染**：通过 `BackgroundTasks` 异步触发 FFmpegCompositorNode\n\n"
        "接口立即返回 **202 Accepted**，响应体包含：\n"
        "- 完整的 `CompilationPlan` 蓝图（供前端核对寻址结果）\n"
        "- `task_id`：submitted task / batch UUID，同步作为 WS `taskId`\n"
        "- 每个 child 使用内部 `execution_id`，并以其派生的 `file_sid` 作为输出文件名后缀\n"
        "- `render_status: \"rendering\"`\n\n"
        "渲染进度通过 **WebSocket 事件总线**（`WS_UPDATE`）实时推送。\n\n"
        "**容错策略**：若所有 Beat 均寻址失败，返回 `422` 并给出具体原因，"
        "不会下发无效的渲染任务。"
    ),
)
def submit_dsl(
    payload: RenderDSLRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    request: Request = None,
) -> DSLSubmitResponse:
    """
    Story DSL 三合一端点：解析 + 适配 + 后台渲染。

    同步部分（毫秒级，不阻塞响应）：
      1. 校验 payload（Pydantic 自动完成）
      2. DSLParserNode 执行双轨寻址 → CompilationPlan
      3. 前置校验：resolved_beats > 0
      4. 生成 task_id（UUID），注册 render_worker 至 BackgroundTasks
      5. 立即返回 202 + DSLSubmitResponse

    异步部分（BackgroundTasks 线程）：
      6. render_worker: compile_plan_to_timeline → WorkflowContext
      7. FFmpegCompositorNode.execute → FFmpeg 子进程渲染
      8. WS 事件总线推送 running / progress / completed / failed
    """
    tenant_id = _authoritative_request_tenant(payload, request)
    is_blind = _is_blind_fission(payload)
    _guard_pre_planner_policy(
        payload,
        flow="submit_dsl",
        is_blind=is_blind,
    )

    logger.info(
        "[routes_dsl] submit-dsl 请求 engine=%s beats=%d blind=%s aspect=%s duration=%ds",
        payload.engine_type,
        len(payload.timeline),
        is_blind,
        payload.aspect_ratio,
        payload.target_duration,
    )

    if not is_blind and not payload.timeline:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="timeline 不能为空，请至少提供一个 Beat 节点。",
        )

    plan: Optional[CompilationPlan] = None

    if is_blind:
        plan = CompilationPlan(
            engine_type=payload.engine_type,
            beats=[],
            unresolved_beats=[],
            summary=CompilationPlanSummary(
                total_beats=0,
                resolved_beats=0,
                unresolved_beats=0,
            ),
        )
        logger.info("[routes_dsl] 极速闭眼裂变：timeline 留空，DSL 解析推迟至 Worker 线程。")
    else:
        # ── Step 1: DSL 解析 → CompilationPlan ───────────────────────────
        try:
            dsl_payload = StoryDSLPayload(
                engine_type=payload.engine_type,
                timeline=payload.timeline,
                meta=payload.meta,
                user_hard_tags=payload.user_hard_tags,
            )
            parser = DSLParserNode(db)
            plan = parser.parse_and_resolve(dsl_payload)
        except Exception as exc:
            logger.exception("[routes_dsl] DSLParserNode 内部异常")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"DSL 解析引擎内部错误：{exc}",
            ) from exc

        logger.info(
            "[routes_dsl] 蓝图解析完成 resolved=%d/%d unresolved=%s",
            plan.summary.resolved_beats,
            plan.summary.total_beats,
            plan.unresolved_beats or "[]",
        )

        # ── Step 2: 前置校验 — 至少有一个可渲染的主视频 Beat ───────────────
        if plan.summary.resolved_beats == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "所有 Beat 寻址失败，无可渲染素材。"
                    f"未解析的 Beats：{plan.unresolved_beats}"
                ),
            )

    assert plan is not None

    # ── Step 3: 生成唯一 task_id，按 batch_size 选择 worker ──────────────
    task_id    = payload.session_id or str(uuid.uuid4())
    batch_size = payload.batch_size

    # 原始 DSL Payload（未执行寻址），下发给 Worker 实现运行时动态抽卡
    dsl_payload_for_worker: Optional[StoryDSLPayload] = None if is_blind else StoryDSLPayload(
        engine_type=payload.engine_type,
        timeline=payload.timeline,
        meta=payload.meta,
        user_hard_tags=payload.user_hard_tags,
    )

    _worker_kw: dict[str, Any] = {
        "blind_dsl": is_blind,
        "engine_type": payload.engine_type,
        "director_mode": payload.mode,
        "enable_tts": payload.enable_tts,
        "enable_subtitles": payload.enable_subtitles,
        "variant_planning_policy": payload.variant_planning_policy,
        "historical_novelty_mode": payload.historical_novelty_mode,
    }
    if _requests_authoritative_main_visual(payload):
        # Request-time preview is only a validated seed; the coordinator still
        # owns bounded batch planning before any child identity is allocated.
        _worker_kw["resolved_plan"] = plan
        _worker_kw["preview_intent"] = PreviewIntent.AUTOMATIC_PREVIEW

    background_tasks.add_task(
        render_batch_worker,
        dsl_payload_for_worker,
        task_id,
        payload.aspect_ratio, payload.target_duration, tenant_id,
        payload.prompt, batch_size, payload.test_language,
        **_worker_kw,
    )

    logger.info(
        "[routes_dsl] 渲染任务已下发 task_id=%s batch=%d blind=%s resolved=%d/%d",
        task_id, batch_size, is_blind,
        plan.summary.resolved_beats,
        plan.summary.total_beats,
    )

    # ── Step 4: 返回 CompilationPlan 快照 + 任务元数据 ─────────────────
    return DSLSubmitResponse(
        **plan.model_dump(),
        task_id=task_id,
        task_ids=[task_id],
        render_status="rendering",
        message=(
            f"渲染任务已下发（task_id={task_id[:8]}…，batch={batch_size}，"
            f"blind_dsl={is_blind}），全部完成后由事件总线推送含所有资产的 completed 事件。"
        ),
    )


# ================================================================== #
# POST /tasks/render-dsl  — 纯渲染触发端点  (Phase 5.1，保持不变)    #
# ================================================================== #

# ================================================================== #
# POST /tasks/submit-manual  - pure manual DSL submit endpoint
# ================================================================== #

@router.post(
    "/submit-manual",
    response_model=DSLSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Story DSL 手工编排渲染入口",
    description=(
        "接收前端手工编排好的 RenderDSLRequest，直接通过 DSLParserNode "
        "解析 CompilationPlan 并下发后台渲染。该端点不执行 blind fission "
        "判断，也不依赖 DirectorNode。"
    ),
)
def submit_manual(
    payload: RenderDSLRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    request: Request = None,
) -> DSLSubmitResponse:
    tenant_id = _authoritative_request_tenant(payload, request)
    _guard_pre_planner_policy(payload, flow="submit_manual")
    logger.info(
        "[routes_dsl] submit-manual request engine=%s beats=%d aspect=%s duration=%ds",
        payload.engine_type,
        len(payload.timeline),
        payload.aspect_ratio,
        payload.target_duration,
    )

    if not payload.timeline:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="timeline cannot be empty for manual submit.",
        )

    try:
        dsl_payload = StoryDSLPayload(
            engine_type=payload.engine_type,
            timeline=payload.timeline,
            meta=payload.meta,
            user_hard_tags=payload.user_hard_tags,
        )
        parser = DSLParserNode(db)
        plan = parser.parse_and_resolve(dsl_payload)
    except Exception as exc:
        logger.exception("[routes_dsl] submit-manual DSLParserNode failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DSL parser failed: {exc}",
        ) from exc

    if plan.summary.resolved_beats == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No renderable beats were resolved. "
                f"Unresolved beats: {plan.unresolved_beats}"
            ),
        )

    task_id = payload.session_id or str(uuid.uuid4())
    batch_size = payload.batch_size
    worker_kwargs: dict[str, Any] = {
        "blind_dsl": False,
        "engine_type": payload.engine_type,
        "director_mode": payload.mode,
        "enable_tts": payload.enable_tts,
        "enable_subtitles": payload.enable_subtitles,
    }

    background_tasks.add_task(
        render_batch_worker,
        dsl_payload,
        task_id,
        payload.aspect_ratio, payload.target_duration, tenant_id,
        None, batch_size, payload.test_language,
        **{**worker_kwargs, "resolved_plan": plan},
    )

    logger.info(
        "[routes_dsl] submit-manual dispatched task_id=%s batch=%d resolved=%d/%d",
        task_id,
        batch_size,
        plan.summary.resolved_beats,
        plan.summary.total_beats,
    )

    return DSLSubmitResponse(
        **plan.model_dump(),
        task_id=task_id,
        task_ids=[task_id],
        render_status="rendering",
        message=(
            f"Manual render task dispatched (task_id={task_id[:8]}, "
            f"batch={batch_size})."
        ),
    )


@router.post(
    "/render-dsl",
    response_model=RenderDSLAck,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Story DSL 渲染触发（纯渲染，无蓝图快照）",
    description=(
        "接收带渲染配置的 DSL Payload，仅下发渲染任务并返回轻量 Ack。\n\n"
        "与 `submit-dsl` 的区别：响应体不含 CompilationPlan 蓝图快照，"
        "适用于前端已完成 Dry-run 核对、只需触发渲染的场景。\n\n"
        "渲染进度同样通过 **WebSocket 事件总线**（`WS_UPDATE`）实时推送。"
    ),
)
def render_dsl(
    payload: RenderDSLRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    request: Request = None,
) -> RenderDSLAck:
    """
    Story DSL 纯渲染触发端点（共用 render_worker，与 submit-dsl 渲染逻辑一致）。
    """
    tenant_id = _authoritative_request_tenant(payload, request)
    is_blind = _is_blind_fission(payload)
    _guard_pre_planner_policy(
        payload,
        flow="render_dsl",
        is_blind=is_blind,
    )

    logger.info(
        "[routes_dsl] render-dsl 请求 engine=%s beats=%d blind=%s aspect=%s duration=%ds",
        payload.engine_type,
        len(payload.timeline),
        is_blind,
        payload.aspect_ratio,
        payload.target_duration,
    )

    if not is_blind and not payload.timeline:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="timeline 不能为空，请至少提供一个 Beat 节点。",
        )

    plan: Optional[CompilationPlan] = None

    if is_blind:
        plan = CompilationPlan(
            engine_type=payload.engine_type,
            beats=[],
            unresolved_beats=[],
            summary=CompilationPlanSummary(
                total_beats=0,
                resolved_beats=0,
                unresolved_beats=0,
            ),
        )
    else:
        try:
            dsl_payload = StoryDSLPayload(
                engine_type=payload.engine_type,
                timeline=payload.timeline,
                meta=payload.meta,
                user_hard_tags=payload.user_hard_tags,
            )
            parser = DSLParserNode(db)
            plan = parser.parse_and_resolve(dsl_payload)
        except Exception as exc:
            logger.exception("[routes_dsl] DSLParserNode 内部异常")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"DSL 解析引擎内部错误：{exc}",
            ) from exc

        if plan.summary.resolved_beats == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "所有 Beat 寻址失败，无可渲染素材。"
                    f"未解析的 Beats：{plan.unresolved_beats}"
                ),
            )

    assert plan is not None

    task_id    = payload.session_id or str(uuid.uuid4())
    batch_size = payload.batch_size

    # 原始 DSL Payload（未执行寻址），下发给 Worker 实现运行时动态抽卡
    dsl_payload_for_worker: Optional[StoryDSLPayload] = None if is_blind else StoryDSLPayload(
        engine_type=payload.engine_type,
        timeline=payload.timeline,
        meta=payload.meta,
        user_hard_tags=payload.user_hard_tags,
    )

    _worker_kw: dict[str, Any] = {
        "blind_dsl": is_blind,
        "engine_type": payload.engine_type,
        "director_mode": payload.mode,
        "enable_tts": payload.enable_tts,
        "enable_subtitles": payload.enable_subtitles,
    }

    background_tasks.add_task(
        render_batch_worker,
        dsl_payload_for_worker,
        task_id,
        payload.aspect_ratio, payload.target_duration, tenant_id,
        payload.prompt, batch_size, payload.test_language,
        **_worker_kw,
    )

    logger.info(
        "[routes_dsl] render-dsl 渲染已下发 task_id=%s batch=%d blind=%s resolved=%d/%d",
        task_id, batch_size, is_blind,
        plan.summary.resolved_beats,
        plan.summary.total_beats,
    )

    return RenderDSLAck(
        session_id=task_id,
        status="processing",
        message=(
            f"渲染任务已下发（batch={batch_size}，blind_dsl={is_blind}），"
            "请通过 WebSocket 事件总线监听进度。"
        ),
    )
