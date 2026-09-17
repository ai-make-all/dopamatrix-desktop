# VAR-001 V1.5 Tenant Delivery Output
# Post-Commit Source Excerpts

Role: read-only source excerpt collection. No code, tests, DB, services,
or git writes besides this file. No new architecture proposal.

Accepted prior direction: Two-Root. This file only proves **where**
delivery publication may attach relative to authoritative terminal
commit / TaskHistory truth.

Labels: **SOURCE FACT** unless marked otherwise.

## 1. Executive Result

`render_worker` can return `outcome=succeeded` with `file_path` /
`cover_path` **before** Reservation fence, TaskHistory INSERT, and the
coordinator wipe that discards non-authoritative outputs.

Durable catalog truth is committed in the coordinator, not the child.

**SAFE_DELIVERY_PUBLICATION_POINT:**

`src/api/routes_dsl.py` `_render_batch_worker_impl`
after successful TaskHistory/ledger terminal persist
(`history_persisted is True`)
and after the authority-loss / terminal-persist wipe branch
(lines 3828–3862)
and **before** `ws_manager.broadcast_sync` (lines 3905–3909)

Publication at that point must be **best-effort** (cannot raise into
the WS / `VideoTask` status path).

**POST_AUTHORITATIVE_COMMIT_PROVEN**

**ZIP_DOWNLOAD_TENANT_HEADER_COMPATIBILITY:**
`INCOMPATIBLE_WITH_CURRENT_DIRECT_DOWNLOAD`

**GLOBAL_DELIVERY_ROOT_SETTINGS_API_PATTERN:**
`NARROW_EXTENSION_FEASIBLE`

## 2. Question A — DSL Child Result Flow

### `_ChildResult` envelope

```2431:2448:src/api/routes_dsl.py
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
```

### `render_worker` knows

- `task_id`, `tenant_id`, `execution_id`, `child_index`, `file_sid`
- compositor `render_ok`
- in-memory `collected_assets` with `file_path` / `cover_path`

It sets `ws_terminal_managed_by_coordinator = True` and does **not**
emit the public terminal event.

```2778:2799:src/api/routes_dsl.py
        context = WorkflowContext(
            task_id=task_id,
            aspect_ratio=aspect_ratio,
            target_duration=target_duration,
            tenant_id=tenant_id,
            batch_size=batch_size,
            test_language=test_language,
        )
        context.set_asset("timeline", timeline)

        # ── 3. 显式 child execution identity ───────────────────────────
        # context.task_id keeps shared task/UI/WS identity; execution/file
        # execution_id and file_sid are distinct from public task identity.
        context.config["execution_id"] = execution_id
        context.config["file_sid"] = resolved_file_sid
        context.config["child_index"] = child_index
        context.config["enable_tts"] = enable_tts
        context.config["enable_subtitles"] = enable_subtitles
        # render_worker is always a child execution.  The submitted-task
        # terminal event belongs exclusively to render_batch_worker.
        context.config["ws_terminal_managed_by_coordinator"] = True
        os.makedirs("output", exist_ok=True)
```

### Internal render success, assets, returns

```2914:3020:src/api/routes_dsl.py
        # ── 5b. 引擎点火 ───────────────────────────────────────────────
        render_ok = _run_compositor(FFmpegCompositorNode(), context)

        # ── 5c. 封面抽帧（Phase 9.8.2）─────────────────────────────────
        # CoverNode 为非关键路径：失败只记录日志，不回滚渲染结果。
        if render_ok:
            ...
            _cover_path: str = context.get_asset("cover_path") or ""
            ...
        else:
            _cover_path = ""

        ...
        if render_ok:
            for _variant_assets in context.variants.values():
                _fp = _variant_assets.get("final_video", "")
                if _fp and os.path.exists(_fp):
                    ...
                    collected_assets.append({
                        "file_path": _fp,
                        "file_hash": _h.hexdigest(),
                        "cover_path": _cover_path,
                        **_social_fields,
                    })

        ...
        if render_ok and collected_assets:
            return _result("succeeded")
        if not render_ok:
            return _result("failed", "RENDER_FAILED", "compositor did not complete")
        return _result("failed", "NO_FINAL_OUTPUT", "render produced no final output")
```

Failure returns also exist earlier (`PLAN_MISSING`, `MAIN_VISUAL_MISSING`,
`CHILD_EXCEPTION`, etc.). `_result()` copies `collected_assets` as-is.

### What `render_worker` does **not** know

**SOURCE FACT:** it does not call TaskHistory persist, Reservation
fence, ledger `RENDERED`/`FAILED` terminal write, `VideoTask` terminal
status, Reservation `abort`/release, or the coordinator wipe of
`all_assets` after authority loss / terminal persist failure.

Physical files under `output/` may already exist while later
coordinator truth is `failed` with empty assets.

## 3. Question B — Batch Coordinator Authority Flow

Order inside `_render_batch_worker_impl` after children return
(all **SOURCE FACT**):

### 1. Child aggregation

```3596:3697:src/api/routes_dsl.py
    child_results: list[_ChildResult] = []
    def _execute_child(work: _ChildWork) -> _ChildResult:
        ...
            result = render_worker(...)
            ...
            return result
    ...
    child_results.sort(key=lambda result: result.child_index)
    ...
    successful_results = [result for result in child_results if result.succeeded]
    all_assets = [
        dict(asset)
        for result in successful_results
        for asset in result.assets
    ]
    succeeded_count = len(successful_results)
```

Pre-child `require_active()` may already set `reservation_authority_lost`
and skip work (3646–3653, 3661–3666).

### 2–4. Ledger records, then fenced terminal OR OFF history persist

```3717:3815:src/api/routes_dsl.py
    terminal_ledger_records: tuple[FingerprintOccurrenceRecord, ...] = ()
    try:
        terminal_ledger_records = tuple(
            _fingerprint_ledger_occurrence_record(
                ...,
                "RENDERED" if result.succeeded else "FAILED",
            )
            for result in child_results
            if (result.child_index, result.execution_id) in authoritative_work_by_identity
        )
    except Exception as exc:
        ...
        if reservation_controller is not None:
            reservation_terminal_persist_failed = True
    ...
    if reservation_controller is not None and reservation_execution_bindings:
        ...
                history_persisted = _persist_reservation_authoritative_terminal(...)
                terminal_ledger_persisted = True
            except PlannerReservationAuthorityLost:
                reservation_authority_lost = True
                ...
            except Exception:
                reservation_terminal_persist_failed = True
                ...
        reservation_controller.abort()
    elif reservation_controller is not None:
        reservation_controller.abort()
    elif succeeded_count:
        try:
            terminal_ledger_persisted = _persist_task_history(...)
            history_persisted = True
        except Exception:
            warning_codes.append("HISTORY_PERSIST_FAILED")
            ...  # 保留渲染结果
```

ENFORCE writer (TaskHistory only if `succeeded_count`):

```3280:3309:src/api/routes_dsl.py
    def _write_terminal(session: Session) -> None:
        _record_fingerprint_ledger_records(session, terminal_ledger_records)
        _apply_fatigue_updates(...)
        if succeeded_count:
            session.add(
                _build_task_history_record(...)
            )

    reservation_controller.run_fenced_terminal_transaction(
        execution_bindings,
        _write_terminal,
    )
```

Fence = **one** DB transaction (renew + writer + `session.commit()`):

```356:384:src/api/planner_reservation.py
    def run_fenced_terminal_transaction(...):
        """Renew/fence all confirmed bindings and run writes in one transaction."""
        self.require_active()
        ...
        with self._session_factory() as session:
            try:
                _begin_sqlite_outer_transaction(session)
                FingerprintLedgerRepository(session).renew_reservations(...)
                writer(session)
                session.commit()
            except FingerprintReservationBatchRenewalError as exc:
                session.rollback()
                ...
                raise PlannerReservationAuthorityLost(...)
            except Exception:
                session.rollback()
                raise
```

OFF history persist is a **different** session/commit (TaskHistory add +
optional nested ledger; outer `db.commit()`):

```3139:3168:src/api/routes_dsl.py
    with HistorySession() as db:
        db.add(history_record)
        ledger_persisted = True
        if ledger_terminal_records:
            db.flush()
            try:
                with db.begin_nested():
                    _record_fingerprint_ledger_records(...)
            except Exception as exc:
                ledger_persisted = False
                ...
        db.commit()
    return ledger_persisted
```

### 5. Reservation release — **separate** commit after terminal persist

```463:495:src/api/planner_reservation.py
    def abort(self) -> bool:
        """Stop heartbeat and owner-safely release; never hide caller failure."""
        ...
            with self._session_factory() as session:
                ...
                    repository.release_reservation(...)
                session.commit()
```

`abort()` does not delete TaskHistory. Cleanup failure only warns.

### 6. Wipe non-authoritative outputs, then WS

```3828:3921:src/api/routes_dsl.py
    if reservation_authority_lost:
        ...
        all_assets = []
        history_persisted = False
        final_status = "failed"
        ...
    elif reservation_terminal_persist_failed:
        ...
        all_assets = []
        history_persisted = False
        final_status = "failed"
        ...
    else:
        final_status = "completed" if succeeded_count else "failed"
        ...
    if _terminal_target_callback is not None:
        _terminal_target_callback(final_status)
    terminal_payload: dict[str, Any] = {
        ...
        "historyPersisted": history_persisted,
        ...
    }
    if all_assets:
        terminal_payload["assets"] = all_assets
    ...
        ws_manager.broadcast_sync(
            {"type": "WS_UPDATE", "payload": terminal_payload},
            user_id=tenant_id,
        )
```

### 7. `VideoTask` status — **after** impl (including WS) returns

```4204:4210:src/api/routes_dsl.py
    _best_effort_public_task_terminal_transition(
        admission_engine,
        task_id=task_id,
        target_status=terminal_target,
        phase="terminal",
    )
    return terminal_payload
```

```259:294:src/api/public_task_admission.py
def transition_public_task_status(...):
    """Commit one truthful lifecycle transition in a short tenant session."""
    ...
        session.commit()
```

Docstring: persist operational task state **without replacing worker
truth/errors**. Failure is logged; it does not rewrite TaskHistory.

### First durable-authoritative point

**SOURCE FACT:** outputs are catalog-durable only after:

- ENFORCE: `run_fenced_terminal_transaction` `session.commit()` succeeds
  (ledger terminal + optional TaskHistory in that same txn), **and**
  the wipe branch does not run (`reservation_authority_lost` /
  `reservation_terminal_persist_failed` false).
- OFF: `_persist_task_history` `db.commit()` succeeds
  (`history_persisted = True`).

Before that, child success can still be rejected (authority loss /
fence failure / persist exception → wipe `all_assets`, `failed`).

OFF `HISTORY_PERSIST_FAILED` still sets `final_status=completed` and
keeps `all_assets` in WS **without** TaskHistory. That is **not**
catalog-authoritative.

## 4. Question C — Hook options (no design)

| Hook | Location | Stale non-auth output to delivery? | Delivery failure roll back auth success? | task_id | tenant_id | final/cover |
|---|---|---|---|---|---|---|
| **A** `render_worker` after `render_ok` | 2915–3017 | **YES** — later wipe / failed terminal | **DEPENDS** — uncaught copy fails child (`_result failed`); TaskHistory not written yet | YES | YES | YES (in-memory) |
| **B** coordinator before terminal persist | ~3692–3740 | **YES** — persist/authority can still fail and wipe | **DEPENDS** — uncaught would skip persist/WS | YES | YES | YES (`all_assets`) |
| **C** immediately after successful authoritative DB commit | after 3767 / 3805, and after 3828–3862 so wipe cannot still apply | **NO** if gated on `history_persisted` and not wiped | **DEPENDS** — uncaught **would skip WS and VideoTask completed** even though TaskHistory committed | YES | YES | YES (`all_assets`) |
| **D** after terminal WS | after 3905–3909, still inside impl | **NO** if same gate as C | **DEPENDS** — uncaught skips impl return → wrapper may `failed` VideoTask after WS already sent completed | YES | YES | YES |

HOOK C/D require a **non-raising** wrapper to answer rollback **NO**.
That is a placement constraint, not an implementation.

HOOK A is **too early** (source-proven).

## 5. Question D — Transaction boundaries

**MULTIPLE COMMITS**, not one global transaction.

| Step | Session / commit | Role |
|---|---|---|
| Child fatigue (OFF; `defer_fatigue_write=False`) | `render_worker` `db.commit()` | DAM usage; not terminal catalog |
| ENFORCE terminal | **one** fenced txn: renew + ledger RENDERED/FAILED + fatigue + TaskHistory INSERT | **catalog + lease fence truth** |
| ENFORCE `abort()` | **separate** commit: release reservations | cleanup, not catalog unwrite |
| OFF `_persist_task_history` | **one** outer `db.commit()`; ledger nested savepoint may fail while history still commits | **OFF catalog truth** |
| Diagnostic callbacks | best-effort separate writes | not catalog |
| `VideoTask` processing / completed / failed | **separate** `transition_public_task_status` commit | operational lifecycle |

**Authoritative terminal catalog truth (current source):**

- ENFORCE: fenced `session.commit()` in `run_fenced_terminal_transaction`
- OFF: `db.commit()` in `_persist_task_history` when it does not throw

`VideoTask` is **not** that catalog truth.

## 6. Question E — TaskHistory vs terminal WebSocket

**SOURCE FACT:** TaskHistory commit happens **before**
`ws_manager.broadcast_sync`.

ENFORCE/OFF persist: 3750–3815  
Wipe / `final_status`: 3828–3862  
WS: 3905–3909  
`VideoTask` completed/failed: **after** impl return, 4204–4208

Delivery must not be stronger than TaskHistory. Attaching after
`history_persisted` and after the wipe branch, before or after WS,
matches existing truth **if** copy cannot raise.

Attaching after WS does not make delivery stronger than TaskHistory;
it only follows UI notify. Uncaught exception after WS can still
desync `VideoTask` vs WS.

## 7. Question F — ZIP serving / frontend

### Backend

```54:55:src/api/routes_matrix.py
EXPORT_DIR = os.path.join(os.getcwd(), "output", "exports")
os.makedirs(EXPORT_DIR, exist_ok=True)
```

```206:210:src/api/routes_matrix.py
def _safe_export_filename(filename: str) -> str:
    safe_name = os.path.basename(filename or "")
    if not safe_name.startswith("dopamatrix_delivery_") or not safe_name.endswith(".zip"):
        raise HTTPException(...)
    return safe_name
```

POST uses `X-Local-User` for **DB engine only**; filename is
`dopamatrix_delivery_{int(time.time())}.zip`; zip path is `EXPORT_DIR`.

```373:384:src/api/routes_matrix.py
    filename = f"dopamatrix_delivery_{int(time.time())}.zip"
    tenant_id = request.headers.get("X-Local-User", "default") or "default"
    bg_tasks.add_task(
        background_build_zip,
        requested_hashes,
        tenant_id,
        filename,
        ...
    )
    return {"status": "processing", "filename": filename}
```

Status: **no** `Request` / tenant. Lookup by filename in shared
`EXPORT_DIR`.

```387:398:src/api/routes_matrix.py
async def check_export_status(filename: str) -> dict:
    ...
    if os.path.exists(zip_path):
        return {
            "status": "ready",
            "download_url": f"/exports/{safe_filename}",
            "local_path": os.path.abspath(zip_path),
        }
```

```144:145:main.py
os.makedirs(os.path.join("output", "exports"), exist_ok=True)
app.mount("/exports", StaticFiles(directory=os.path.join("output", "exports")), name="exports")
```

StaticFiles has **no** tenant header check.

### Frontend

Initiate (axios → default `X-Local-User` from login):

```441:448:web_ui/src/views/ApprovalView.vue
    const exportUrl = `${store.API_BASE}/api/v1/matrix/export`
    const { data } = await axios.post(exportUrl, { hashes: hashesToExport })
    ...
    store.startGlobalExportPolling(data.filename, hashesToExport.length)
```

Poll (axios → **has** `X-Local-User`):

```107:118:web_ui/src/stores/appStore.js
        const res = await axios.get(`${API_BASE}/api/v1/matrix/export/status`, {
          params: { filename },
        })
        if (res.data.status === 'ready') {
          ...
            downloadUrl: `${API_BASE}${res.data.download_url}`,
            localPath: res.data.local_path,
```

Download / open:

```53:109:web_ui/src/App.vue
async function triggerDownload(notification) {
  ...
  if (localPath) {
    ...
      await invoke('show_in_folder', { path: localPath })
      return
    ...
      await openPath(folderPath)
      return
  ...
  fallbackWebDownload(notification.downloadUrl)
}

function fallbackWebDownload(url) {
  ...
  const link = document.createElement('a')
  link.href = url
  link.target = '_blank'
  ...
  link.click()
}
```

**Does the browser download send `X-Local-User`?**

- POST export / GET status via axios: **YES** (`axios.defaults.headers.common['X-Local-User']` in `appStore.js` `handleLogin` / `initAuth`).
- Tauri `show_in_folder` / `openPath(localPath)`: **N/A** (filesystem, not HTTP).
- HTTP fallback `<a href="{API_BASE}/exports/{filename}">`: **NO**. Navigation cannot attach `X-Local-User`. Current `/exports` StaticFiles would ignore it even if sent.

## 8. Question G — Settings API pattern

`src/api/settings_router.py` is LLM-only. Global `dopamatrix.db`
`app_settings(key_name PRIMARY KEY, key_value TEXT)`.

- GET `/api/v1/settings/llm` — SELECT by `_KEY_OPENAI`
- POST `/api/v1/settings/llm` — `INSERT OR REPLACE` then `conn.commit()`
- **No PATCH**

No tenant on these routes.

Output directory UI (not this API):

```47:57:web_ui/src/views/SettingsView.vue
async function pickGlobalOutputFolder() {
  ...
      store.setGlobalOutputDir(selected)
```

```214:218:web_ui/src/stores/appStore.js
  const globalOutputDir = ref(localStorage.getItem('dopamatrix_output_dir') || '')
  function setGlobalOutputDir(path) {
    globalOutputDir.value = path
    localStorage.setItem('dopamatrix_output_dir', path)
  }
```

Logout removes `dopamatrix_output_dir`.

**SOURCE FACT:** a second `key_name` (Delivery Root) using the same
GET/POST + `INSERT OR REPLACE` table is a narrow extension of this
file. No generic settings framework exists or is required.

## 9. Mini-conclusion

**SAFE_DELIVERY_PUBLICATION_POINT:**

`src/api/routes_dsl.py` / `_render_batch_worker_impl`
after ENFORCE `run_fenced_terminal_transaction` commit **or** OFF
`_persist_task_history` commit with `history_persisted is True`,
after wipe branch 3828–3862,
before `ws_manager.broadcast_sync`,
non-raising best-effort only.

**POST_AUTHORITATIVE_COMMIT_PROVEN**

(`RENDER_WORKER_SAFE_PROVEN` is false. `SOURCE_AMBIGUOUS` is false.)

**ZIP_DOWNLOAD_TENANT_HEADER_COMPATIBILITY:**
`INCOMPATIBLE_WITH_CURRENT_DIRECT_DOWNLOAD`

**GLOBAL_DELIVERY_ROOT_SETTINGS_API_PATTERN:**
`NARROW_EXTENSION_FEASIBLE`

## 10. Git Status

```text
git branch --show-current
feature/var-001-variation-policy

git rev-parse HEAD
73982e4073455a8e542015c25cd9e20e397dd078

git status --short
?? doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_TARGETED_AUDIT.md
?? doc/investigations/VAR001_V15_TENANT_DELIVERY_OUTPUT_POSTCOMMIT_SOURCE_EXCERPTS.md
```

No production files changed. No commit. No push.
