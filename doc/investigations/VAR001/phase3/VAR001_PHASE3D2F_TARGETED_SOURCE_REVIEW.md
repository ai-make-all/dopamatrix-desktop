# VAR-001 Phase 3D-2F
# Targeted Rollout Readiness Source Review

Review mode: targeted source review, read-only except for this requested artifact.

Reviewed production scope:

- `src/api/database.py`
- `src/api/models.py`
- `src/api/public_task_admission.py`
- `src/api/routes.py`
- `src/api/routes_dsl.py`
- `src/api/routes_reservation_diagnostics.py`
- `src/api/reservation_rollout_readiness.py`

Supporting unchanged source was consulted only where required to prove the
request/default, tenant dependency, current lease validation, router
registration, and Ledger schema version.

No tests were run. No database was opened or mutated. No production source or
test source was modified. No commit, push, ENFORCE activation, or canary action
was performed.

## A. Baseline

Recorded before creating this review artifact:

```text
git branch --show-current
feature/var-001-variation-policy

git rev-parse HEAD
5f73335bb7447066d247532ac75828ec6067a274

git status --short
 M src/api/database.py
 M src/api/models.py
 M src/api/public_task_admission.py
 M src/api/routes.py
 M src/api/routes_dsl.py
 M src/api/routes_reservation_diagnostics.py
?? src/api/reservation_rollout_readiness.py
?? tests/test_var001_reservation_rollout_readiness.py
```

```text
git diff --stat
 src/api/database.py                       | 101 ++++++++++++++++++++++++++++
 src/api/models.py                         |  32 ++++++++-
 src/api/public_task_admission.py          |  30 +++++++++
 src/api/routes.py                         |   2 +
 src/api/routes_dsl.py                     |   2 +
 src/api/routes_reservation_diagnostics.py | 107 ++++++++++++++++++++++++++++++
 6 files changed, 273 insertions(+), 1 deletion(-)
```

`git diff --stat` does not list untracked files; the untracked production module
`src/api/reservation_rollout_readiness.py` was read completely and is reviewed
below.

```text
git diff --check
exit code: 0
warning: LF will be replaced by CRLF for public_task_admission.py
warning: LF will be replaced by CRLF for routes_reservation_diagnostics.py
```

The warnings are line-ending notices, not whitespace errors.

## B. VideoTask Metadata

The authoritative task cohort fields are defined together on `VideoTask` in
`src/api/models.py:30-75`:

```python
class VideoTask(Base):
    __tablename__ = "video_tasks"
    __table_args__ = (
        CheckConstraint(
            "reservation_conflict_mode IN ('OFF', 'ENFORCE')",
            name="ck_video_tasks_reservation_conflict_mode",
        ),
        CheckConstraint(
            "planning_policy IN ("
            "'legacy', 'exact_main_visual', 'exact_main_visual_balanced'"
            ")",
            name="ck_video_tasks_planning_policy",
        ),
        Index(
            "ix_video_tasks_rollout_readiness",
            "reservation_conflict_mode",
            "planning_policy",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    task_id = Column(String(64), unique=True, nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    batch_size = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="queued")
    reservation_conflict_mode = Column(
        String(16),
        nullable=False,
        default="OFF",
        server_default="OFF",
    )
    planning_policy = Column(
        String(64),
        nullable=False,
        default="legacy",
        server_default="legacy",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    finished_at = Column(DateTime(timezone=True), nullable=True)
```

Source conclusions:

- Both rollout metadata columns are `NOT NULL`.
- Historical/default mode is `OFF`; historical/default policy is `legacy`.
- Database constraints allow only `OFF | ENFORCE` and
  `legacy | exact_main_visual | exact_main_visual_balanced`.
- `task_id` is unique and non-null.
- `status` supplies authoritative lifecycle state.
- `created_at` supplies the authoritative configured-window cohort timestamp.
- The readiness index covers mode, policy, and cohort time.

Client authority identity is separately rejected by
`src/api/schemas.py:20-43,448-455`:

```python
_CLIENT_RESERVATION_AUTHORITY_FIELDS = frozenset(
    {
        "owner_attempt_id",
        "reservation_owner_attempt_id",
        "owner_task_id",
        "execution_id",
        "reservation_lease_ttl_seconds",
        "reservation_heartbeat_interval_seconds",
    }
)

class _ServerOwnedTaskRequest(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def reject_client_task_identity(cls, value):
        if isinstance(value, dict) and ({"session_id", "task_id"} & value.keys()):
            raise ValueError(CLIENT_TASK_ID_NOT_ALLOWED)
        return value

class RenderDSLRequest(_ServerOwnedTaskRequest):
    @model_validator(mode="before")
    @classmethod
    def reject_client_reservation_authority(cls, value):
        if isinstance(value, dict) and (
            _CLIENT_RESERVATION_AUTHORITY_FIELDS & value.keys()
        ):
            raise ValueError(CLIENT_RESERVATION_AUTHORITY_NOT_ALLOWED)
        return value
```

Mode and planning policy are validated submission policy selections. They are
not owner identity, execution identity, lease authority, confirmation
authority, or an idempotency key.

## C. Additive Schema

`initialize_application_schema()` calls the dedicated additive metadata helper
both before and after the generic evolver
(`src/api/database.py:208-307`):

```python
def ensure_video_task_rollout_metadata_schema(engine) -> None:
    """Add and verify immutable task-submission metadata without rebuilding."""
    inspector = sa_inspect(engine)
    if "video_tasks" not in inspector.get_table_names():
        raise TaskRolloutMetadataSchemaError(
            VIDEO_TASK_ROLLOUT_METADATA_SCHEMA_INVALID
        )

    columns = {
        column["name"]: column
        for column in inspector.get_columns("video_tasks")
    }
    additions = {
        "reservation_conflict_mode": (
            "TEXT NOT NULL DEFAULT 'OFF' "
            "CHECK (reservation_conflict_mode IN ('OFF', 'ENFORCE'))"
        ),
        "planning_policy": (
            "TEXT NOT NULL DEFAULT 'legacy' "
            "CHECK (planning_policy IN ("
            "'legacy', 'exact_main_visual', 'exact_main_visual_balanced'"
            "))"
        ),
    }
    with engine.begin() as conn:
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(
                    text(
                        f'ALTER TABLE "video_tasks" '
                        f'ADD COLUMN "{name}" {definition}'
                    )
                )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_video_tasks_rollout_readiness "
                "ON video_tasks "
                "(reservation_conflict_mode, planning_policy, created_at)"
            )
        )

    inspector = sa_inspect(engine)
    columns = {
        column["name"]: column
        for column in inspector.get_columns("video_tasks")
    }
    for name in additions:
        column = columns.get(name)
        if (
            column is None
            or column.get("nullable", True)
            or not isinstance(column["type"], String)
        ):
            raise TaskRolloutMetadataSchemaError(
                VIDEO_TASK_ROLLOUT_METADATA_SCHEMA_INVALID
            )

    indexes = {
        tuple(index.get("column_names") or ())
        for index in inspector.get_indexes("video_tasks")
    }
    if (
        "reservation_conflict_mode",
        "planning_policy",
        "created_at",
    ) not in indexes:
        raise TaskRolloutMetadataSchemaError(
            VIDEO_TASK_ROLLOUT_METADATA_SCHEMA_INVALID
        )

    with engine.connect() as conn:
        invalid = conn.execute(
            text(
                "SELECT 1 FROM video_tasks "
                "WHERE reservation_conflict_mode IS NULL "
                "OR reservation_conflict_mode NOT IN ('OFF', 'ENFORCE') "
                "OR planning_policy IS NULL "
                "OR planning_policy NOT IN ("
                "'legacy', 'exact_main_visual', "
                "'exact_main_visual_balanced'"
                ") LIMIT 1"
            )
        ).first()
    if invalid is not None:
        raise TaskRolloutMetadataSchemaError(
            VIDEO_TASK_ROLLOUT_METADATA_SCHEMA_INVALID
        )

def initialize_application_schema(engine) -> None:
    verify_video_task_identity_schema(engine)
    from .models import Base as ModelBase

    ModelBase.metadata.create_all(bind=engine)
    ensure_video_task_rollout_metadata_schema(engine)
    evolve_schema(engine)
    verify_video_task_identity_schema(engine)
    ensure_video_task_rollout_metadata_schema(engine)
```

For an existing B2/2E `video_tasks` table:

1. `create_all()` does not rebuild the existing table.
2. Missing columns are added with `ALTER TABLE ... ADD COLUMN`.
3. SQLite applies `DEFAULT 'OFF'` and `DEFAULT 'legacy'` to existing rows.
4. The checks make historical `ENFORCE` fabrication impossible during this
   addition: the mode default is explicitly `OFF`.
5. The helper verifies column presence, non-nullability, type, index, and all
   stored values; failure is raised as a stable schema error.

The reviewed diff contains no `DROP`, table rebuild, row deletion, Reservation
schema migration, or Ledger schema migration. Application-level `VideoTask`
columns do not create Ledger V3.

`VAR3D2F-RF-30 ADDITIVE_SCHEMA_CAN_FABRICATE_HISTORICAL_ENFORCE`: not found.

## D. Admission Atomicity

The complete authoritative insert transaction is in
`src/api/public_task_admission.py:82-109`:

```python
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
```

The complete admission/retry path is
`src/api/public_task_admission.py:112-140`:

```python
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
```

The DSL admission adapter persists normalized request values
(`src/api/routes_dsl.py:213-222`):

```python
def _admit_dsl_public_task(db: Session, payload: RenderDSLRequest) -> str:
    admission = admit_public_task(
        db.get_bind(),
        prompt=payload.prompt,
        batch_size=payload.batch_size,
        reservation_conflict_mode=payload.reservation_conflict_mode,
        planning_policy=payload.variant_planning_policy,
    )
    return admission.task_id
```

All three DSL public submission flows call this adapter before calling
`_dispatch_claimed_public_task()`:

- `submit_dsl`: admission at `routes_dsl.py:4442`, dispatch at `4443`.
- `submit_manual`: admission at `4550`, dispatch at `4551`.
- `render_dsl`: admission at `4686`, dispatch at `4687`.

The dispatch helper states and enforces the ordering
(`routes_dsl.py:225-239`):

```python
def _dispatch_claimed_public_task(...):
    """Make a worker reachable only after its durable task claim committed."""
    ...
    background_tasks.add_task(
        render_batch_worker,
        *worker_args,
        public_task_admitted=True,
        **worker_kwargs,
    )
```

There is one `VideoTask` construction and one commit. `task_id`, queued status,
Reservation mode, and planning policy are inserted together. There is no
post-commit metadata update.

**AUTHORITATIVE_TASK_METADATA_ATOMIC_ADMISSION_SOURCE_PROVEN: PASS**

### Generated task-ID retry

`_is_video_task_id_unique_violation()` recognizes only the exact
`video_tasks.task_id` uniqueness failure. `_claim_one()` rolls back the collided
attempt and returns zero. The next loop iteration generates another `task_id`
and calls `_claim_one()` with the same validated mode and policy arguments.
Therefore:

- no collided row commits;
- no stale metadata survives the rollback;
- the successful newly generated task row receives its metadata in its own
  single admission transaction.

`VAR3D2F-RF-19 TASK_METADATA_NOT_ATOMIC_WITH_ADMISSION`: not found.

## E. Legacy Task Metadata

Legacy `/tasks/submit` accepts `VideoTaskCreate`, whose source schema
(`src/api/schemas.py:69-119`) contains prompt/render fields but no Reservation
mode, readiness setting, lease setting, or planning-policy field.

The route supplies server-owned metadata explicitly before dispatch
(`src/api/routes.py:76-108`):

```python
def submit_task(...):
    admission = admit_public_task(
        db.get_bind(),
        prompt=payload.prompt,
        batch_size=payload.batch_size,
        reservation_conflict_mode="OFF",
        planning_policy="legacy",
    )

    background_tasks.add_task(
        run_matrix_job,
        video_task_id=admission.video_task_id,
        task_id=admission.task_id,
        ...
    )
```

The durable legacy row is therefore always `OFF + legacy`; the legacy request
contract was not extended with Reservation or readiness controls.

## F. Metadata Immutability

Global production searches for:

- `VideoTask.reservation_conflict_mode`
- `VideoTask.planning_policy`
- assignments to `.reservation_conflict_mode` / `.planning_policy`
- `update(VideoTask)`
- all `VideoTask(...)` constructors

found:

1. the single constructor in `_claim_one()`;
2. cohort reads in `reservation_rollout_readiness.py`;
3. lifecycle updates in `transition_public_task_status()`;
4. legacy lifecycle status/cost updates in `services.py`.

The lifecycle update is limited to:

```python
update(VideoTask)
.where(
    VideoTask.task_id == task_id,
    VideoTask.status.in_(allowed_sources[target_status]),
)
.values(
    status=target_status,
    finished_at=...,
)
```

Legacy worker assignments modify status, finish time, and cost fields only.
No supported production path updates either rollout metadata column after
admission.

`VAR3D2F-RF-20 TASK_POLICY_METADATA_MUTABLE_AFTER_ADMISSION`: not found.

## G. Authoritative Cohort

The complete live cohort query is
`src/api/reservation_rollout_readiness.py:348-395`:

```python
end = now or datetime.now(timezone.utc)
if end.tzinfo is None:
    end = end.replace(tzinfo=timezone.utc)
start = end - _WINDOWS[configuration.evaluation_window]

rows = session.execute(
    select(
        VideoTask.status.label("task_status"),
        ReservationRunDiagnostic.id.label("diagnostic_id"),
        ReservationRunDiagnostic.planning_observed.label(
            "planning_observed"
        ),
        ReservationRunDiagnostic.reservation_conflict_count.label(
            "reservation_conflict_count"
        ),
        ReservationRunDiagnostic.had_reservation_conflict.label(
            "had_reservation_conflict"
        ),
        ReservationRunDiagnostic.zero_plan_conflict.label(
            "zero_plan_conflict"
        ),
        ReservationRunDiagnostic.partial_plan.label("partial_plan"),
        ReservationRunDiagnostic.authority_lost.label("authority_lost"),
        ReservationRunDiagnostic.terminal_persist_failed.label(
            "terminal_persist_failed"
        ),
        ReservationRunDiagnostic.worker_lease_config_failed.label(
            "worker_lease_config_failed"
        ),
        ReservationRunDiagnostic.cleanup_warning.label(
            "cleanup_warning"
        ),
        ReservationRunDiagnostic.terminal_status.label(
            "diagnostic_terminal_status"
        ),
    )
    .select_from(VideoTask)
    .outerjoin(
        ReservationRunDiagnostic,
        ReservationRunDiagnostic.task_id == VideoTask.task_id,
    )
    .where(
        VideoTask.reservation_conflict_mode == "ENFORCE",
        VideoTask.planning_policy == planning_policy,
        VideoTask.created_at >= start,
        VideoTask.created_at <= end,
    )
).all()
```

The query starts from `VideoTask`. Mode, policy, and window predicates are all
on the authoritative task table. `authoritative_count = len(rows)` is therefore
the count of authoritative `VideoTask` cohort rows, not a diagnostic table
count.

The selected session is already tenant-local (Section M). No global cohort is
computed.

## H. Diagnostic Intersection

The only diagnostics access is the LEFT JOIN inside the filtered authoritative
task query above. There is no second diagnostics query and no metric-specific
diagnostic scan.

The joined row reductions are
`src/api/reservation_rollout_readiness.py:397-424`:

```python
authoritative_count = len(rows)
diagnostic_count = sum(row.diagnostic_id is not None for row in rows)
planning_count = sum(bool(row.planning_observed) for row in rows)
authoritative_terminal_count = sum(
    row.task_status in _TERMINAL_STATUSES for row in rows
)
terminal_diagnostic_count = sum(
    row.task_status in _TERMINAL_STATUSES
    and row.diagnostic_terminal_status in _TERMINAL_STATUSES
    for row in rows
)
active_count = authoritative_count - authoritative_terminal_count
conflict_task_count = sum(
    bool(row.had_reservation_conflict) for row in rows
)
reservation_conflict_count = sum(
    int(row.reservation_conflict_count or 0) for row in rows
)
zero_plan_count = sum(bool(row.zero_plan_conflict) for row in rows)
partial_plan_count = sum(bool(row.partial_plan) for row in rows)
authority_loss_count = sum(bool(row.authority_lost) for row in rows)
terminal_failure_count = sum(
    bool(row.terminal_persist_failed) for row in rows
)
worker_config_count = sum(
    bool(row.worker_lease_config_failed) for row in rows
)
cleanup_count = sum(bool(row.cleanup_warning) for row in rows)
```

Every requested diagnostic numerator is reduced from this one joined row set:

- `diagnosticRunCount`
- `planningObservedTaskCount`
- `terminalDiagnosticTaskCount`
- `conflictTaskCount`
- `reservationConflictCount`
- `zeroPlanConflictCount`
- `partialPlanCount`
- `authorityLossCount`
- `terminalPersistFailureCount`
- `workerLeaseConfigFailureCount`
- `cleanupWarningCount`

An orphan diagnostic has no left-side `VideoTask` and cannot enter the row set.
A diagnostic belonging to an out-of-window, OFF, legacy, or other-policy task
cannot enter because its authoritative task fails the `VideoTask` predicates.
The diagnostic table's denormalized policy label is not used as authority; task
membership by `task_id` and authoritative `VideoTask.planning_policy` define
the selected cohort.

`VAR3D2F-RF-18 READINESS_DIAGNOSTIC_NUMERATOR_NOT_BOUND_TO_AUTHORITATIVE_COHORT`:
not found.

## I. Diagnostic Coverage

The shared zero-safe rate helper is:

```python
def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None
```

Diagnostic coverage is:

```python
diagnostic_coverage = _rate(diagnostic_count, authoritative_count)
```

Thus:

```text
diagnosticRunCoverageRate
= diagnosticRunCount / authoritativeEnforceTaskCount
```

When the authoritative denominator is zero, the result is `None`. A missing
diagnostic leaves the authoritative count unchanged and decreases the
numerator.

## J. Planning Coverage

Planning coverage is:

```python
planning_coverage = _rate(planning_count, authoritative_count)
```

Thus:

```text
planningObservationCoverageRate
= planningObservedTaskCount / authoritativeEnforceTaskCount
```

It does not divide by `diagnosticRunCount`. A missing diagnostic or missing
planning observation remains represented by the authoritative task in the
denominator.

## K. Terminal Coverage

Authoritative terminal membership is derived from task status:

```python
_TERMINAL_STATUSES = {"completed", "failed"}

authoritative_terminal_count = sum(
    row.task_status in _TERMINAL_STATUSES for row in rows
)
```

The terminal diagnostic numerator requires both sides:

```python
terminal_diagnostic_count = sum(
    row.task_status in _TERMINAL_STATUSES
    and row.diagnostic_terminal_status in _TERMINAL_STATUSES
    for row in rows
)
```

The rate is:

```python
terminal_coverage = _rate(
    terminal_diagnostic_count,
    authoritative_terminal_count,
)
```

Therefore a diagnostic terminal value on a nonterminal task does not count, and
a terminal task lacking a terminal diagnostic remains in the denominator.
Zero authoritative terminal tasks produce `None`.

## L. Policy Isolation

Public/operator readiness policies are allowlisted twice:

```python
ReservationRolloutPlanningPolicy = Literal[
    "exact_main_visual",
    "exact_main_visual_balanced",
]

_ALLOWED_POLICIES = {
    "exact_main_visual",
    "exact_main_visual_balanced",
}
```

The service rejects any other value and filters
`VideoTask.planning_policy == planning_policy`. Exact and Balanced therefore
produce separate authoritative cohorts. `legacy` cannot be evaluated. OFF
tasks cannot enter either policy cohort.

`VAR3D2F-RF-28 EXACT_BALANCED_COHORT_CONTAMINATION`: not found.

## M. Tenant Isolation

The readiness route takes `db: Session = Depends(get_db)`. The dependency
chain in `src/api/database.py:317-374` is:

```python
def canonical_tenant_id(tenant_id: str | None) -> str:
    raw_tenant_id = tenant_id or "default"
    safe_tenant_id = "".join(
        character
        for character in raw_tenant_id
        if character.isalnum() or character in ("_", "-")
    )
    return safe_tenant_id or "default"

def request_tenant_id(request: Request) -> str:
    return canonical_tenant_id(request.headers.get("X-Local-User", "default"))

def get_tenant_engine(tenant_id: str | None):
    safe_tenant_id = canonical_tenant_id(tenant_id)
    ...
    db_path = f"sqlite:///./data/dopamatrix_{safe_tenant_id}.db"
    engine = create_engine(db_path, connect_args={"check_same_thread": False})
    ...
    return _tenant_engines[safe_tenant_id]

def get_db(request: Request):
    tenant_id = request_tenant_id(request)
    engine = get_tenant_engine(tenant_id)
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    db = SessionLocal()
    db.info["tenant_id"] = tenant_id
    try:
        yield db
    finally:
        db.close()
```

The readiness service receives only this session. It does not import or use the
global application engine, choose a default database, accept a tenant body
field, or open another tenant engine. `VideoTask` and diagnostics are queried
through the same physical tenant session.

`VAR3D2F-RF-29 READINESS_CROSSES_TENANT_BOUNDARY`: not found.

## N. Readiness Configuration

The backend configuration semantic fields are declared without dataclass
defaults (`src/api/reservation_rollout_readiness.py:102-116`):

```python
@dataclass(frozen=True)
class ReservationRolloutReadinessConfiguration:
    evaluation_window: Literal["24h", "7d", "30d"]
    minimum_authoritative_enforce_tasks: int
    minimum_planning_observed_tasks: int
    minimum_conflict_tasks: int
    minimum_diagnostic_run_coverage_rate: float
    minimum_planning_observation_coverage_rate: float
    minimum_terminal_observation_coverage_rate: float
    maximum_zero_plan_conflict_rate: float
    maximum_partial_plan_rate: float
    maximum_authority_loss_rate: float
    maximum_terminal_persist_failure_rate: float
    maximum_worker_lease_config_failure_rate: float
    maximum_cleanup_warning_rate: float
```

The complete validation and parsing logic is:

```python
def __post_init__(self) -> None:
    if self.evaluation_window not in _WINDOWS:
        raise ReservationRolloutReadinessConfigurationError()

    count_fields = (
        "minimum_authoritative_enforce_tasks",
        "minimum_planning_observed_tasks",
        "minimum_conflict_tasks",
    )
    for name in count_fields:
        value = getattr(self, name)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise ReservationRolloutReadinessConfigurationError()

    rate_fields = (
        "minimum_diagnostic_run_coverage_rate",
        "minimum_planning_observation_coverage_rate",
        "minimum_terminal_observation_coverage_rate",
        "maximum_zero_plan_conflict_rate",
        "maximum_partial_plan_rate",
        "maximum_authority_loss_rate",
        "maximum_terminal_persist_failure_rate",
        "maximum_worker_lease_config_failure_rate",
        "maximum_cleanup_warning_rate",
    )
    for name in rate_fields:
        value = getattr(self, name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ReservationRolloutReadinessConfigurationError()
        object.__setattr__(self, name, float(value))

def _parse_nonnegative_integer(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ReservationRolloutReadinessConfigurationError() from None
    if parsed < 0:
        raise ReservationRolloutReadinessConfigurationError()
    return parsed

def _parse_rate(value: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ReservationRolloutReadinessConfigurationError() from None
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise ReservationRolloutReadinessConfigurationError()
    return parsed
```

The complete loader is:

```python
def load_reservation_rollout_readiness_configuration(
    environ: Mapping[str, str] | None = None,
) -> ReservationRolloutReadinessConfiguration | None:
    """Load one all-or-nothing backend policy without numeric defaults."""
    source = os.environ if environ is None else environ
    present = {
        field
        for field, environment_key in _ENVIRONMENT_KEYS.items()
        if environment_key in source
    }
    if not present:
        return None
    if present != set(_ENVIRONMENT_KEYS):
        raise ReservationRolloutReadinessConfigurationError()

    def raw(field: str) -> str:
        value = source[_ENVIRONMENT_KEYS[field]]
        if not isinstance(value, str):
            raise ReservationRolloutReadinessConfigurationError()
        return value

    return ReservationRolloutReadinessConfiguration(
        evaluation_window=raw("evaluation_window"),
        minimum_authoritative_enforce_tasks=_parse_nonnegative_integer(
            raw("minimum_authoritative_enforce_tasks")
        ),
        minimum_planning_observed_tasks=_parse_nonnegative_integer(
            raw("minimum_planning_observed_tasks")
        ),
        minimum_conflict_tasks=_parse_nonnegative_integer(
            raw("minimum_conflict_tasks")
        ),
        minimum_diagnostic_run_coverage_rate=_parse_rate(
            raw("minimum_diagnostic_run_coverage_rate")
        ),
        minimum_planning_observation_coverage_rate=_parse_rate(
            raw("minimum_planning_observation_coverage_rate")
        ),
        minimum_terminal_observation_coverage_rate=_parse_rate(
            raw("minimum_terminal_observation_coverage_rate")
        ),
        maximum_zero_plan_conflict_rate=_parse_rate(
            raw("maximum_zero_plan_conflict_rate")
        ),
        maximum_partial_plan_rate=_parse_rate(
            raw("maximum_partial_plan_rate")
        ),
        maximum_authority_loss_rate=_parse_rate(
            raw("maximum_authority_loss_rate")
        ),
        maximum_terminal_persist_failure_rate=_parse_rate(
            raw("maximum_terminal_persist_failure_rate")
        ),
        maximum_worker_lease_config_failure_rate=_parse_rate(
            raw("maximum_worker_lease_config_failure_rate")
        ),
        maximum_cleanup_warning_rate=_parse_rate(
            raw("maximum_cleanup_warning_rate")
        ),
    )
```

All thirteen fields are present or configuration is invalid. All fields absent
returns `None`. Counts are nonnegative integers. Rates reject booleans,
non-numbers, NaN, infinity, negatives, and values above one. The window map is
limited to `24h`, `7d`, and `30d`.

No public request or query supplies this mapping. It is loaded from backend
environment state inside the readiness route.

## O. Current Lease Gate

Readiness validates current lease configuration directly
(`reservation_rollout_readiness.py:327-332`):

```python
def _current_lease_configuration_ready() -> bool:
    try:
        load_reservation_lease_configuration().require_configured()
        return True
    except ReservationLeaseConfigurationError:
        return False
```

The existing lease configuration source validates finite positive values and
the heartbeat-to-TTL relationship. Missing configuration causes
`require_configured()` to raise its stable configuration error.

The result becomes a required SAFETY gate:

```python
_gate(
    "CURRENT_LEASE_CONFIGURATION_READY",
    "SAFETY",
    "PASS" if lease_ready else "FAIL",
    lease_ready,
    True,
)
```

Any false lease result is a SAFETY `FAIL`, so the state logic selects
`BLOCKED` before considering insufficient evidence. Historical metrics cannot
override it. Only a boolean readiness result is returned; TTL, heartbeat,
timestamps, and raw lease values are not exposed.

`VAR3D2F-RF-23 CURRENT_LEASE_FAILURE_CAN_BE_OVERRIDDEN`: not found.

## P. Metric Definitions

Exact formulas in `reservation_rollout_readiness.py:426-441`:

```python
diagnostic_coverage = _rate(diagnostic_count, authoritative_count)
planning_coverage = _rate(planning_count, authoritative_count)
terminal_coverage = _rate(
    terminal_diagnostic_count,
    authoritative_terminal_count,
)
conflict_rate = _rate(conflict_task_count, planning_count)
zero_plan_rate = _rate(zero_plan_count, planning_count)
partial_plan_rate = _rate(partial_plan_count, planning_count)
authority_loss_rate = _rate(authority_loss_count, authoritative_count)
terminal_failure_rate = _rate(
    terminal_failure_count,
    authoritative_count,
)
worker_config_rate = _rate(worker_config_count, authoritative_count)
cleanup_rate = _rate(cleanup_count, authoritative_count)
```

Denominators:

| Response rate | Denominator |
|---|---|
| `diagnosticRunCoverageRate` | authoritative ENFORCE task count |
| `planningObservationCoverageRate` | authoritative ENFORCE task count |
| `terminalObservationCoverageRate` | authoritative terminal task count |
| `conflictTaskRate` | planning-observed task count |
| `zeroPlanConflictRate` | planning-observed task count |
| `partialPlanRate` | planning-observed task count |
| `authorityLossRate` | authoritative ENFORCE task count |
| `terminalPersistFailureRate` | authoritative ENFORCE task count |
| `workerLeaseConfigFailureRate` | authoritative ENFORCE task count |
| `cleanupWarningRate` | authoritative ENFORCE task count |

No required readiness safety/completeness rate accidentally uses
`diagnosticRunCount` as its denominator.

`VAR3D2F-RF-21 READINESS_RATE_USES_WRONG_DENOMINATOR`: not found.

## Q. Conflict Evidence

Conflict task count has exactly one gate:

```python
_minimum_gate(
    "MINIMUM_CONFLICT_TASKS",
    conflict_task_count,
    configuration.minimum_conflict_tasks,
)
```

`conflictTaskRate` is calculated and returned as context but is not passed to
`_maximum_gate()` or any other gate. Global gate search found no maximum
conflict threshold. Therefore a high conflict rate cannot independently
produce `BLOCKED`; conflict count is benefit/evidence only.

## R. Gate Evaluation

The complete generic gate implementation is
`reservation_rollout_readiness.py:245-285`:

```python
def _gate(
    code: str,
    category: Literal["EVIDENCE", "QUALITY", "SAFETY"],
    status: Literal["PASS", "FAIL", "UNKNOWN"],
    observed: int | float | bool | None,
    threshold: int | float | bool,
) -> dict[str, Any]:
    return {
        "code": code,
        "category": category,
        "status": status,
        "observed": observed,
        "threshold": threshold,
    }

def _minimum_gate(
    code: str,
    observed: int | float | None,
    threshold: int | float,
) -> dict[str, Any]:
    status = (
        "UNKNOWN"
        if observed is None
        else "PASS" if observed >= threshold else "FAIL"
    )
    return _gate(code, "EVIDENCE", status, observed, threshold)

def _maximum_gate(
    code: str,
    category: Literal["QUALITY", "SAFETY"],
    observed: float | None,
    threshold: float,
) -> dict[str, Any]:
    status = (
        "UNKNOWN"
        if observed is None
        else "PASS" if observed <= threshold else "FAIL"
    )
    return _gate(code, category, status, observed, threshold)
```

The complete required gate set is:

```python
gates = [
    _minimum_gate(
        "MINIMUM_AUTHORITATIVE_ENFORCE_TASKS",
        authoritative_count,
        configuration.minimum_authoritative_enforce_tasks,
    ),
    _minimum_gate(
        "MINIMUM_PLANNING_OBSERVED_TASKS",
        planning_count,
        configuration.minimum_planning_observed_tasks,
    ),
    _minimum_gate(
        "MINIMUM_CONFLICT_TASKS",
        conflict_task_count,
        configuration.minimum_conflict_tasks,
    ),
    _minimum_gate(
        "MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE",
        diagnostic_coverage,
        configuration.minimum_diagnostic_run_coverage_rate,
    ),
    _minimum_gate(
        "MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE",
        planning_coverage,
        configuration.minimum_planning_observation_coverage_rate,
    ),
    _minimum_gate(
        "MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE",
        terminal_coverage,
        configuration.minimum_terminal_observation_coverage_rate,
    ),
    _maximum_gate(
        "MAXIMUM_ZERO_PLAN_CONFLICT_RATE",
        "QUALITY",
        zero_plan_rate,
        configuration.maximum_zero_plan_conflict_rate,
    ),
    _maximum_gate(
        "MAXIMUM_PARTIAL_PLAN_RATE",
        "QUALITY",
        partial_plan_rate,
        configuration.maximum_partial_plan_rate,
    ),
    _maximum_gate(
        "MAXIMUM_AUTHORITY_LOSS_RATE",
        "SAFETY",
        authority_loss_rate,
        configuration.maximum_authority_loss_rate,
    ),
    _maximum_gate(
        "MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE",
        "SAFETY",
        terminal_failure_rate,
        configuration.maximum_terminal_persist_failure_rate,
    ),
    _maximum_gate(
        "MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE",
        "SAFETY",
        worker_config_rate,
        configuration.maximum_worker_lease_config_failure_rate,
    ),
    _maximum_gate(
        "MAXIMUM_CLEANUP_WARNING_RATE",
        "SAFETY",
        cleanup_rate,
        configuration.maximum_cleanup_warning_rate,
    ),
    _gate(
        "CURRENT_LEASE_CONFIGURATION_READY",
        "SAFETY",
        "PASS" if lease_ready else "FAIL",
        lease_ready,
        True,
    ),
]
```

Each result has exactly `code`, `category`, `status`, `observed`, and
`threshold`. No task identity enters a gate.

## S. UNKNOWN Semantics

`_rate()` returns `None` for a zero denominator. Both `_minimum_gate()` and
`_maximum_gate()` map `observed is None` to `UNKNOWN`, never `PASS`.

Overall:

- an UNKNOWN EVIDENCE rate contributes to `incomplete_evidence` and yields
  `INSUFFICIENT_EVIDENCE` unless a stronger failure exists;
- an UNKNOWN QUALITY or SAFETY rate also contributes to
  `incomplete_evidence` and yields `INSUFFICIENT_EVIDENCE` unless an actual
  QUALITY/SAFETY `FAIL` yields `BLOCKED`;
- the current lease gate itself is always boolean PASS/FAIL;
- any UNKNOWN gate prevents the all-PASS condition required for READY.

`VAR3D2F-RF-22 UNKNOWN_REQUIRED_GATE_CAN_REACH_READY`: not found.

## T. State Precedence

Configuration absence is handled before time calculation, lease validation, or
the evidence query:

```python
if configuration is None:
    return _not_configured_result(planning_policy)
```

The complete configured-state decision is:

```python
blocking_failure = any(
    gate["category"] in {"QUALITY", "SAFETY"}
    and gate["status"] == "FAIL"
    for gate in gates
)
incomplete_evidence = any(
    gate["status"] != "PASS" for gate in gates
)
state: ReservationRolloutReadinessState
if blocking_failure:
    state = "BLOCKED"
elif incomplete_evidence:
    state = "INSUFFICIENT_EVIDENCE"
else:
    state = "READY_FOR_CONTROLLED_CANARY"
```

Deterministic precedence:

1. config absent -> `NOT_CONFIGURED`;
2. current lease false -> SAFETY FAIL -> `BLOCKED`;
3. any actual QUALITY/SAFETY FAIL -> `BLOCKED`;
4. any EVIDENCE FAIL or any required UNKNOWN -> `INSUFFICIENT_EVIDENCE`;
5. no non-PASS gate -> `READY_FOR_CONTROLLED_CANARY`.

## U. Active Task Semantics

The authoritative terminal count uses only `VideoTask.status in
{completed, failed}`. Active count is its complement within the authoritative
cohort:

```python
active_count = authoritative_count - authoritative_terminal_count
```

No gate consumes `active_count`; it is only returned as `activeTaskCount`.
There is no stale threshold and no `activeTaskCount > 0` blocker.

## V. Default OFF

The exact public request definition remains
`src/api/schemas.py:419-446`:

```python
variant_planning_policy: Literal[
    "legacy",
    "exact_main_visual",
    "exact_main_visual_balanced",
] = Field(default="legacy", ...)

reservation_conflict_mode: Literal["OFF", "ENFORCE"] = Field(
    default="OFF",
    ...
)
```

No readiness module is imported by `schemas.py`. Ordinary request
normalization cannot call readiness or transform omitted OFF into ENFORCE.

## W. No Auto Activation

Global source search for:

- `reservation_rollout_readiness`
- `ReservationRolloutReadiness`
- `READY_FOR_CONTROLLED_CANARY`
- `ELIGIBLE_FOR_CONTROLLED_DEFAULT_ON_CANARY`

found production references only in:

1. `src/api/reservation_rollout_readiness.py` — config, calculation, advisory
   state, and response dictionary;
2. `src/api/routes_reservation_diagnostics.py` — readiness response schema and
   GET endpoint;
3. `src/api/models.py` / `src/api/database.py` only through the word
   `readiness` in the task query index name.

No references exist in `routes_dsl.py`, `public_task_admission.py`,
`planner_reservation.py`, `fingerprint_ledger.py`, planner selection,
confirmation, terminal fencing, lifecycle transitions, or worker mode
normalization.

There is no assignment from readiness state/recommendation to
`reservation_conflict_mode`.

**READINESS_STATE_NON_AUTHORITATIVE_SOURCE_PROVEN: PASS**

`VAR3D2F-RF-25 READINESS_STATE_USED_TO_AUTO_ACTIVATE_ENFORCE`: not found.

## X. Readiness API

The complete route is `src/api/routes_reservation_diagnostics.py:137-180`:

```python
@router.get("/readiness", response_model=ReservationRolloutReadinessResponse)
def get_reservation_rollout_readiness(
    planning_policy: Literal[
        "exact_main_visual",
        "exact_main_visual_balanced",
    ] = Query(...),
    db: Session = Depends(get_db),
) -> ReservationRolloutReadinessResponse:
    """Return advisory tenant/policy evidence without changing runtime mode."""
    try:
        configuration = load_reservation_rollout_readiness_configuration()
        return ReservationRolloutReadinessResponse.model_validate(
            reservation_rollout_readiness(
                db,
                planning_policy=planning_policy,
                configuration=configuration,
            )
        )
    except ReservationRolloutReadinessConfigurationError as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(
            "[RESERVATION_ROLLOUT_READINESS_CONFIG_FAILED] category=%s",
            type(exc).__name__[:64],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=RESERVATION_ROLLOUT_READINESS_CONFIGURATION_INVALID,
        ) from exc
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(
            "[RESERVATION_ROLLOUT_READINESS_QUERY_FAILED] category=%s",
            type(exc).__name__[:64],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=RESERVATION_ROLLOUT_READINESS_UNAVAILABLE,
        ) from exc
```

The router prefix is `/diagnostics/reservation`; `main.py:185` registers that
router under `/api/v1`. The resulting endpoint is:

```text
GET /api/v1/diagnostics/reservation/readiness
```

Source proof:

- GET only;
- required `planning_policy`;
- only Exact or Balanced;
- no body;
- no tenant body/query field;
- no client window;
- no client thresholds;
- tenant-authoritative `Depends(get_db)`.

## Y. NOT_CONFIGURED

When every rollout config key is absent, the loader returns `None`. The service
returns before lease validation and before `session.execute()`.

The exact state/recommendation fields are:

```python
{
    "planningPolicy": planning_policy,
    "state": "NOT_CONFIGURED",
    "recommendation": "KEEP_EXPLICIT_ONLY",
    "evaluationWindow": None,
    "from": None,
    "to": None,
    "leaseConfigurationReady": None,
    ...
    "gates": [],
}
```

All unevaluated metric fields are `None`. Absence does not raise and therefore
does not become HTTP 503.

## Z. Invalid Configuration

Any partial key set, invalid window, negative/noninteger count, nonnumeric rate,
NaN, infinity, negative rate, or rate above one raises only:

```text
RESERVATION_ROLLOUT_READINESS_CONFIGURATION_INVALID
```

The route maps the configuration exception to HTTP 503 with that stable detail.
It logs only the exception class name. It does not serialize the raw
environment key, raw value, or configuration string.

## AA. Query Failure

Any unexpected service/query failure is rolled back defensively and mapped to:

```text
RESERVATION_ROLLOUT_READINESS_UNAVAILABLE
```

The route logs only:

```python
type(exc).__name__[:64]
```

No SQL text, database path, tenant path, or raw exception message enters the
HTTP detail. Readiness is referenced by no render route, so this error path
cannot affect ordinary rendering.

## AB. READY Conditions

`READY_FOR_CONTROLLED_CANARY` is selected only in the final `else` after:

- no QUALITY or SAFETY gate has status FAIL; and
- `any(gate["status"] != "PASS" for gate in gates)` is false.

The latter means every configured evidence, completeness, quality, safety, and
current-lease gate is exactly PASS. A missing metric creates `None`, then
UNKNOWN, then incomplete evidence. Missing diagnostics lower completeness.
Invalid lease creates a SAFETY FAIL. None can reach READY.

The recommendation mapping is advisory only:

```python
recommendation = (
    "ELIGIBLE_FOR_CONTROLLED_DEFAULT_ON_CANARY"
    if state == "READY_FOR_CONTROLLED_CANARY"
    else "KEEP_EXPLICIT_ONLY"
)
```

No runtime mode change follows this mapping.

## AC. Privacy

Complete readiness response schema
(`routes_reservation_diagnostics.py:58-109`):

```text
planningPolicy
state
recommendation
evaluationWindow
from
to
leaseConfigurationReady
authoritativeEnforceTaskCount
diagnosticRunCount
diagnosticRunCoverageRate
planningObservedTaskCount
planningObservationCoverageRate
authoritativeTerminalTaskCount
terminalDiagnosticTaskCount
terminalObservationCoverageRate
conflictTaskCount
conflictTaskRate
reservationConflictCount
zeroPlanConflictCount
zeroPlanConflictRate
partialPlanCount
partialPlanRate
authorityLossCount
authorityLossRate
terminalPersistFailureCount
terminalPersistFailureRate
workerLeaseConfigFailureCount
workerLeaseConfigFailureRate
cleanupWarningCount
cleanupWarningRate
activeTaskCount
gates[]
  code
  category
  status
  observed
  threshold
```

The query does not select `VideoTask.task_id`, prompt, owner attempt,
execution identity, fingerprint, SQL, path, or lease timestamp into result
rows. The schema has no fields for them. Environment names/raw values are not
included. Safe normalized threshold numbers appear only as gate thresholds.

`VAR3D2F-RF-26 READINESS_RESPONSE_PRIVACY_LEAK`: not found.

## AD. Readiness Non-Persistence

Global source search found:

- no readiness ORM model;
- no readiness table name;
- no snapshot model/table;
- no `session.add`, `session.commit`, `insert`, `update`, or `delete` in
  `reservation_rollout_readiness.py`.

The decision is computed live from:

1. tenant-local `VideoTask`;
2. tenant-local `ReservationRunDiagnostic`;
3. backend rollout configuration;
4. current backend Reservation lease configuration.

Only a response dictionary is produced.

## AE. Authority Non-Dependence

Production references to the readiness module/state/result are confined to the
readiness service and diagnostics route. No authority module imports them.

Specifically absent from readiness consumers:

- candidate planner;
- `PlannerReservationController`;
- Reservation acquire/renew/confirm/release;
- PLANNED persistence;
- terminal fencing;
- TaskHistory;
- Ledger;
- `VideoTask` lifecycle transitions;
- public render result;
- request mode normalization;
- worker dispatch mode decisions.

`VAR3D2F-RF-24 READINESS_CONFIG_AFFECTS_RENDER_PATH`: not found.

## AF. Production Threshold Audit

Global source search for numeric assignments/defaults to readiness
`minimum_*` and `maximum_*` fields found none.

The dataclass has no threshold defaults. The loader requires operator-provided
values for every threshold when configured. The only production numeric values
in the module are:

- allowlisted window durations needed to interpret `24h`, `7d`, and `30d`;
- the mathematical rate bounds zero and one;
- the boolean lease gate threshold `True`.

None is a chosen production rollout threshold.

`VAR3D2F-RF-27 PRODUCTION_READINESS_THRESHOLD_HARDCODED`: not found.

## AG. Ledger V2

`src/api/fingerprint_ledger.py:30` remains:

```python
LEDGER_SCHEMA_VERSION = 2
```

The reviewed production diff does not modify `fingerprint_ledger.py`,
Reservation tables, or Ledger migration logic. The new columns belong to the
application `video_tasks` table and do not constitute Ledger V3.

## AH. Findings

Source-proven review results:

| Finding | Result | Source conclusion |
|---|---|---|
| VAR3D2F-RF-18 | Not found | Every diagnostic numerator is reduced from the LEFT JOIN row set rooted in the filtered authoritative `VideoTask` cohort. |
| VAR3D2F-RF-19 | Not found | ID, queued state, mode, and policy share one `VideoTask` insert and commit before dispatch. |
| VAR3D2F-RF-20 | Not found | No supported production write mutates task mode/policy after admission. |
| VAR3D2F-RF-21 | Not found | Completeness/safety denominators are authoritative; planning-quality rates use planning-observed count. |
| VAR3D2F-RF-22 | Not found | None becomes UNKNOWN; every non-PASS gate prevents READY. |
| VAR3D2F-RF-23 | Not found | Current lease failure is a SAFETY FAIL and has blocking precedence. |
| VAR3D2F-RF-24 | Not found | Rollout config loader is reachable only from the readiness GET route. |
| VAR3D2F-RF-25 | Not found | Readiness state/recommendation has no render or mode consumer. |
| VAR3D2F-RF-26 | Not found | Response schema contains aggregates and normalized gate data only. |
| VAR3D2F-RF-27 | Not found | No production rollout threshold default exists. |
| VAR3D2F-RF-28 | Not found | Authoritative task policy predicate separates Exact and Balanced; legacy is rejected. |
| VAR3D2F-RF-29 | Not found | Route session is selected from the authoritative tenant header and no other engine is queried. |
| VAR3D2F-RF-30 | Not found | Existing task rows receive OFF/legacy through additive NOT NULL defaults. |

Required source markers:

- `AUTHORITATIVE_TASK_METADATA_ATOMIC_ADMISSION_SOURCE_PROVEN`: PASS
- `READINESS_STATE_NON_AUTHORITATIVE_SOURCE_PROVEN`: PASS

Final source-review verdict: the Phase 3D-2F readiness layer is read-only,
tenant/policy scoped, based on an authoritative task denominator, conservative
about missing/unknown evidence, blocked by current lease misconfiguration, and
incapable of changing public Reservation mode.

PHASE3D2F_TARGETED_SOURCE_REVIEW_CLEAN
