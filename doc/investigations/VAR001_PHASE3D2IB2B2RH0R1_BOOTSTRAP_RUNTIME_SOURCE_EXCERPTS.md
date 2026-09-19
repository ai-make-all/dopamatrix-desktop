# VAR-001 Phase 3D-2I-B-2B-2R-H0-R1
# Bootstrap / Runtime-Root Source Evidence

## 1. Repository Baseline

Read-only baseline captured before the documentation corrections:

```text
branch: feature/var-001-variation-policy
HEAD: 61aed569b2e9c4eeba1f668c319ef6bdb0714fb9
commit: 61aed56 docs(v1.5): freeze release and Philippine field boundary
status:
?? doc/investigations/VAR001_PHASE3D2IB2B2RH0_RELEASE_HARDENING_ARCHITECTURE_FREEZE.md
?? doc/operations/DOPAMATRIX_V15_RUNTIME_CONFIG_SECRET_CONSTITUTION.md
```

No production source, tests, environment, service, or database was modified or executed. No secret value was read.

## 2. main.py Bootstrap Order

The module body performs frozen-mode CWD selection and dotenv loading before the normal application imports. It then imports the complete FastAPI graph before reaching the `__main__` block.

Current source, `main.py:14-55`:

```python
14: import asyncio
15: import os
16: import subprocess
17: import sys
18: from contextlib import asynccontextmanager
19: from typing import AsyncIterator
24: if getattr(sys, "frozen", False):
25:     os.chdir(os.path.dirname(sys.executable))
30: from src.utils.env_utils import load_env
31: load_env()
33: from fastapi import APIRouter, FastAPI
34: from fastapi.middleware.cors import CORSMiddleware
35: from fastapi.responses import JSONResponse
37: from pyngrok import ngrok
39: from src.core.logger import setup_logger, logger
40: from src.version import APPLICATION_VERSION
41: from src.api.database import engine, initialize_application_schema
42: from src.api.schemas import HealthResponse
43: from src.api import routes as task_routes
44: from src.api import routes_assets
45: from src.api import routes_dsl
46: from src.api import routes_history
47: from src.api.routes_history import tasks_router as tasks_today_router
48: from src.api import routes_matrix, routes_approval
49: from src.api import routes_gateway
50: from src.api import routes_media
51: from src.api import routes_video
52: from src.api import routes_reservation_diagnostics
53: from src.api import routes_ws
54: from src.api import settings_router
55: from src.api.ws_manager import manager as ws_manager
```

Logger setup also occurs at module scope (`main.py:57`):

```python
57: setup_logger()
```

The lifespan performs destructive/operational actions only when FastAPI enters lifespan, not merely when `main.py` is imported (`main.py:63-116`):

```python
63: @asynccontextmanager
64: async def lifespan(app: FastAPI) -> AsyncIterator[None]:
69:     if getattr(sys, "frozen", False):
70:         _env_path = os.path.join(os.path.dirname(sys.executable), ".env")
71:         if os.path.exists(_env_path):
73:                 os.remove(_env_path)
80:     initialize_application_schema(engine)
87:     ws_manager.set_event_loop(asyncio.get_running_loop())
93:     try:
95:         http_tunnel = await loop.run_in_executor(
96:             None, lambda: ngrok.connect(8000, bind_tls=True)
97:         )
99:         os.environ["PUBLIC_BASE_URL"] = _public_url
106:     yield
109:     if _public_url:
111:             ngrok.disconnect(_public_url)
112:             ngrok.kill()
```

FastAPI is constructed at module scope (`main.py:122-132`) and routers are included at `main.py:167-190`. The executable dispatch is only after all of that (`main.py:233-243`):

```python
122: app = FastAPI(
128:     version=APPLICATION_VERSION,
129:     lifespan=lifespan,
132: )
168: app.include_router(task_routes.router, prefix="/api/v1")
169: app.include_router(routes_assets.router, prefix="/api/v1")
170: app.include_router(routes_history.router, prefix="/api/v1")
172: app.include_router(routes_matrix.router, prefix="/api/v1")
175: app.include_router(routes_dsl.router, prefix="/api/v1")
180: app.include_router(routes_reservation_diagnostics.router, prefix="/api/v1")
184: app.include_router(settings_router.router, prefix="/api/v1")
233: if __name__ == "__main__":
234:     import uvicorn
236:     is_prod = getattr(sys, "frozen", False)
238:     if is_prod:
240:         uvicorn.run(app, host="127.0.0.1", port=8000, log_config=None)
243:         uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
```

**Q1. What executes before `backend.exe operator ...` could currently be dispatched?** The entire `main.py` module body: frozen CWD mutation, dotenv loading, FastAPI/Ngrok/logger/database/router imports, import-time effects of those modules, logger setup, FastAPI construction, route registration, and shutdown-route construction. Lifespan actions (schema initialization, `.env` deletion, Ngrok connection) do not run merely on import, but a dispatch placed in the existing `__main__` block would already be too late.

**Q2. Does importing `main.py` import `database.py` before CLI dispatch is possible?** Yes. `database` is imported at line 41; executable dispatch begins at line 233.

## 3. Database Import-Time Side Effects

`src/api/database.py:15-24` imports filesystem/SQLite/SQLAlchemy support:

```python
15: import json
16: import logging
17: import os
18: import sqlite3
19: import threading
21: from fastapi import Request
22: from sqlalchemy import Integer, String, create_engine, event, inspect as sa_inspect, text
23: from sqlalchemy.engine import Engine
24: from sqlalchemy.orm import sessionmaker, DeclarativeBase
```

It globally installs a connection listener at lines 46-55; the listener runs when a connection is opened.

The direct import-time mutations and bindings are (`src/api/database.py:66-84`):

```python
69: os.makedirs("data", exist_ok=True)
75: SETTINGS_DB_PATH = "dopamatrix.db"
78: engine = create_engine(
79:     f"sqlite:///./{SETTINGS_DB_PATH}",
80:     connect_args={"check_same_thread": False},
81: )
84: class Base(DeclarativeBase):
```

Schema initialization is a callable, not a module-scope call (`src/api/database.py:399-408`):

```python
399: def initialize_application_schema(engine) -> None:
401:     verify_video_task_identity_schema(engine)
402:     from .models import Base as ModelBase
404:     ModelBase.metadata.create_all(bind=engine)
405:     ensure_video_task_rollout_metadata_schema(engine)
406:     evolve_schema(engine)
407:     verify_video_task_identity_schema(engine)
408:     ensure_video_task_rollout_metadata_schema(engine)
```

Tenant engines are lazily initialized and cached (`src/api/database.py:414-459`):

```python
414: _tenant_engines: dict = {}
415: _engine_lock = threading.Lock()
437: def get_tenant_engine(tenant_id: str | None):
439:     safe_tenant_id = canonical_tenant_id(tenant_id)
441:     with _engine_lock:
442:         if safe_tenant_id not in _tenant_engines:
443:             db_path = f"sqlite:///./data/dopamatrix_{safe_tenant_id}.db"
444:             engine = create_engine(db_path, connect_args={"check_same_thread": False})
450:                 initialize_application_schema(engine)
451:                 from .fingerprint_ledger import ensure_fingerprint_ledger_schema
452:                 ensure_fingerprint_ledger_schema(engine)
457:             _tenant_engines[safe_tenant_id] = engine
459:         return _tenant_engines[safe_tenant_id]
```

Request routing invokes that lazy creation path (`src/api/database.py:432-434,465-474`):

```python
432: def request_tenant_id(request: Request) -> str:
434:     return canonical_tenant_id(request.headers.get("X-Local-User", "default"))
465: def get_db(request: Request):
470:     tenant_id = request_tenant_id(request)
471:     engine = get_tenant_engine(tenant_id)
472:     SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
474:     db.info["tenant_id"] = tenant_id
```

**Q3. Import-time result:** `database.py` creates the relative `data/` directory and constructs/binds the global SQLAlchemy Engine. `create_engine()` is lazy, so this module by itself does not prove a SQLite file or schema is created at import. SQLite connection/file/schema creation occurs when a connection or `initialize_application_schema()` is used. The broader `main.py` import graph has additional filesystem effects: `src/core/logger.py:26-27` creates the user log directory, and `src/api/routes_matrix.py:60-61` creates CWD-relative `output/exports` during import.

## 4. Runtime Path Assumptions

Current CWD-relative authorities include:

| Authority/use | Current evidence |
|---|---|
| global settings DB | `database.py:75-81` binds `dopamatrix.db` relative to CWD |
| tenant DBs | `database.py:443-444` binds `data/dopamatrix_<tenant>.db` relative to CWD |
| settings routes | `settings_router.py:24,44` imports the already-bound constant and opens it |
| Delivery settings | `delivery_output.py:14,58-65` imports the constant and opens it |
| LLM credential | `llm_provider.py:61-64` independently hard-codes `dopamatrix.db` |
| ZIP fallback | `routes_matrix.py:60-61` uses `os.getcwd()/output/exports` and creates it at import |
| render pipeline | `run_matrix_factory.py:221,251-252` uses/creates `output` and `output/clips` |
| nodes | `compositor.py:85,91`, `subtitle.py:411-412`, and TTS/asset defaults use relative `output` paths |
| backup default | `backup_restore.py:388-410` defaults `project_root="."`, then uses `<root>/data` and `<root>/output` |

Representative exact excerpts:

```python
# src/services/llm_provider.py:61-64
61:     db_path = "dopamatrix.db"
64:         conn = sqlite3.connect(db_path)

# src/api/routes_matrix.py:60-61
60: EXPORT_DIR = os.path.join(os.getcwd(), "output", "exports")
61: os.makedirs(EXPORT_DIR, exist_ok=True)

# run_matrix_factory.py:221,251-252
221:             TTSNode(output_dir="output"),
251:         os.makedirs("output", exist_ok=True)
252:         os.makedirs("output/clips", exist_ok=True)

# src/api/backup_restore.py:384-410
384: def create_backup_bundle(
388:     project_root: str | Path = ".",
391:     root = Path(project_root).resolve()
392:     canonical, source_database = _tenant_database_path(root, tenant_id)
409:             project_root=root,
410:             asset_root=root / "output",
```

**Q6.** These modules/functions currently assume a common CWD-selected project/runtime root. H1 must replace authority-bearing path construction with one explicit runtime-path object; merely changing CWD remains unsafe for an operator mode and leaves independently copied strings such as `llm_provider.py:61` unresolved.

## 5. env_utils

The full 116-line file was read. Current production behavior explicitly supports executable-adjacent dotenv and then ancestor search (`src/utils/env_utils.py:25-54`):

```python
25: def load_env() -> None:
42:     from dotenv import load_dotenv
44:     if getattr(sys, "frozen", False):
46:         exe_dir_env = Path(sys.executable).parent / ".env"
47:         if exe_dir_env.exists():
48:             load_dotenv(dotenv_path=exe_dir_env, override=False)
49:             return
51:         load_dotenv(override=False)
52:     else:
54:         load_dotenv(override=False)
```

FFmpeg resolution is independently frozen-aware (`src/utils/env_utils.py:91-116`): it checks executable-adjacent and `bin/` resources in frozen mode, then uses project-root/PATH fallbacks in development. H1 must preserve FFmpeg discovery while moving dotenv behind an explicit development-only adapter.

## 6. appdirs / Requirements Evidence

Logger source (`src/core/logger.py:22-27`):

```python
22: from appdirs import user_log_dir
23: from loguru import logger
26: LOG_DIR: str = user_log_dir("DopaMatrix", "DopaMatrixOrg")
27: os.makedirs(LOG_DIR, exist_ok=True)
```

Declared dependencies (`requirements.txt:15,32,38`):

```text
15: python-dotenv>=1.0.0
32: appdirs==1.4.4
38: pyinstaller>=6.21.0
```

**Q7.** Yes. `appdirs` is already an explicit runtime dependency. `platformdirs` is not declared. This conclusion is based on `requirements.txt`, not the installed environment.

## 7. Settings / LLM Dynamic Behavior

The full `settings_router.py` file was read. It imports the database path by value (`settings_router.py:24`) and creates/commits `app_settings` on each connection (`settings_router.py:38-55`):

```python
24: from .database import SETTINGS_DB_PATH
38: @contextmanager
39: def _settings_conn() -> Generator[sqlite3.Connection, None, None]:
44:     conn = sqlite3.connect(SETTINGS_DB_PATH)
48:         conn.execute(
49:             "CREATE TABLE IF NOT EXISTS app_settings "
50:             "(key_name TEXT PRIMARY KEY, key_value TEXT);"
52:         conn.commit()
```

OpenAI key writes explicitly invalidate the cache (`settings_router.py:145-160`):

```python
146:         with _settings_conn() as conn:
147:             conn.execute(
148:                 "INSERT OR REPLACE INTO app_settings (key_name, key_value) VALUES (?, ?);",
151:             conn.commit()
160:     invalidate_api_key_cache(_KEY_OPENAI)
```

Delivery Root is read/saved through request-time helpers (`settings_router.py:165-205`; `delivery_output.py:69-101`). The delivery publication path calls `get_delivery_root()` when publishing (`delivery_output.py:219-240`), so it is genuinely read-through dynamic today.

The LLM provider has an explicit module cache and invalidation hook (`src/services/llm_provider.py:38-95`). The DB key is loaded lazily per cache miss at lines 41-78. Provider endpoint/model are captured when a provider is constructed (`llm_provider.py:151-164`):

```python
151:     def __init__(
153:         base_url: str | None = None,
154:         model: str | None = None,
163:         self._base_url = base_url or os.getenv("OPENAI_BASE_URL") or None
164:         self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
```

The route worker constructs a provider at `routes_dsl.py:4366`; director/script nodes also construct one when not injected. Thus endpoint/model can use a bounded dynamic provider lifecycle in H1/H2, but current source does not yet provide DB persistence or explicit invalidation for them.

**Q8.** Changing `database.SETTINGS_DB_PATH` after imports is not a safe solution. The global Engine URL has already been constructed (`database.py:78-81`), `settings_router.py:24` and `delivery_output.py:14` copied the name into their own module globals, and `llm_provider.py:61` has a separate hard-coded path. Runtime paths must be resolved before database and consumer-module initialization, then injected/referenced through one path authority.

**Q10.** Current source proves Delivery Root can remain dynamic through request/use-time reads and the OpenAI credential can remain dynamic through bounded cache invalidation. LLM endpoint/model are construction-time values and may be made dynamic only through a bounded provider-construction/cache contract. Optional integration settings can remain dynamic only where their future adapters provide equivalent bounded reads/invalidation. None belongs in or can hot-reload the immutable Seed operational snapshot.

## 8. Reservation Loader Injection Seams

Lease constants, validator, and mapping seam (`src/api/reservation_lease.py:37-114`):

```python
37: RESERVATION_LEASE_TTL_ENV = "RESERVATION_LEASE_TTL_SECONDS"
38: RESERVATION_HEARTBEAT_INTERVAL_ENV = "RESERVATION_HEARTBEAT_INTERVAL_SECONDS"
52: @dataclass(frozen=True)
53: class ReservationLeaseConfiguration:
75:         if interval > ttl / 3:
98: def load_reservation_lease_configuration(
99:     environ: Mapping[str, str] | None = None,
100: ) -> ReservationLeaseConfiguration:
102:     source = os.environ if environ is None else environ
114:     return ReservationLeaseConfiguration(ttl, interval)
```

Readiness defines its complete 13-key mapping at `reservation_rollout_readiness.py:54-92`; its frozen dataclass validator is at lines 102-156. The loader retains all-or-none behavior and accepts a mapping (`reservation_rollout_readiness.py:179-238`):

| Field | Environment key | Source line(s) |
|---|---|---|
| `evaluation_window` | `RESERVATION_ROLLOUT_READINESS_WINDOW` | 55 |
| `minimum_authoritative_enforce_tasks` | `RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS` | 56-58 |
| `minimum_planning_observed_tasks` | `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS` | 59-61 |
| `minimum_conflict_tasks` | `RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS` | 62-64 |
| `minimum_diagnostic_run_coverage_rate` | `RESERVATION_ROLLOUT_MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE` | 65-67 |
| `minimum_planning_observation_coverage_rate` | `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE` | 68-70 |
| `minimum_terminal_observation_coverage_rate` | `RESERVATION_ROLLOUT_MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE` | 71-73 |
| `maximum_zero_plan_conflict_rate` | `RESERVATION_ROLLOUT_MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | 74-76 |
| `maximum_partial_plan_rate` | `RESERVATION_ROLLOUT_MAXIMUM_PARTIAL_PLAN_RATE` | 77-79 |
| `maximum_authority_loss_rate` | `RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE` | 80-82 |
| `maximum_terminal_persist_failure_rate` | `RESERVATION_ROLLOUT_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | 83-85 |
| `maximum_worker_lease_config_failure_rate` | `RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE` | 86-88 |
| `maximum_cleanup_warning_rate` | `RESERVATION_ROLLOUT_MAXIMUM_CLEANUP_WARNING_RATE` | 89-91 |

```python
179: def load_reservation_rollout_readiness_configuration(
180:     environ: Mapping[str, str] | None = None,
181: ) -> ReservationRolloutReadinessConfiguration | None:
183:     source = os.environ if environ is None else environ
189:     if not present:
190:         return None
191:     if present != set(_ENVIRONMENT_KEYS):
192:         raise ReservationRolloutReadinessConfigurationError()
200:     return ReservationRolloutReadinessConfiguration(
```

Rollout Control defines its complete 18-key mapping at `reservation_rollout_control.py:74-119`; the dataclass validates generation, tenant authority, secret presence, BPS/counts/rates at lines 197-286. Its loader also accepts a mapping without changing semantics (`reservation_rollout_control.py:338-404`):

| Field | Environment key | Source line(s) |
|---|---|---|
| `enabled` | `RESERVATION_ROLLOUT_CONTROL_ENABLED` | 75 |
| `rollout_generation` | `RESERVATION_ROLLOUT_GENERATION` | 76 |
| `tenant_allowlist` | `RESERVATION_ROLLOUT_TENANT_ALLOWLIST` | 77 |
| `exact_main_visual_canary_basis_points` | `RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS` | 78-80 |
| `exact_main_visual_balanced_canary_basis_points` | `RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS` | 81-83 |
| `assignment_secret` | `RESERVATION_ROLLOUT_ASSIGNMENT_SECRET` | 84 |
| `kill_switch` | `RESERVATION_ROLLOUT_KILL_SWITCH` | 85 |
| `rollback_evaluation_window` | `RESERVATION_ROLLOUT_ROLLBACK_WINDOW` | 86-88 |
| `minimum_canary_task_count` | `RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS` | 89-91 |
| `minimum_diagnostic_run_coverage_rate` | `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_DIAGNOSTIC_COVERAGE_RATE` | 92-94 |
| `minimum_planning_observation_coverage_rate` | `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_PLANNING_COVERAGE_RATE` | 95-97 |
| `minimum_terminal_observation_coverage_rate` | `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_TERMINAL_COVERAGE_RATE` | 98-100 |
| `maximum_zero_plan_conflict_rate` | `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | 101-103 |
| `maximum_partial_plan_rate` | `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE` | 104-106 |
| `maximum_authority_loss_rate` | `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE` | 107-109 |
| `maximum_terminal_persist_failure_rate` | `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | 110-112 |
| `maximum_worker_lease_config_failure_rate` | `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE` | 113-115 |
| `maximum_cleanup_warning_rate` | `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE` | 116-118 |

```python
338: def load_reservation_rollout_control_configuration(
339:     environ: Mapping[str, str] | None = None,
340: ) -> ReservationRolloutControlConfiguration | None:
342:     source = os.environ if environ is None else environ
348:     if not present:
349:         return None
350:     if present != set(_ENVIRONMENT_KEYS):
351:         raise ReservationRolloutControlConfigurationError()
359:     return ReservationRolloutControlConfiguration(
```

Current runtime calls omit the mapping and therefore read `os.environ`: route preflight `routes_dsl.py:425`; worker revalidation `routes_dsl.py:4148`; readiness lease check `reservation_rollout_readiness.py:329`; rollout decision `reservation_rollout_control.py:660,699,740`; rollout status `reservation_rollout_control.py:854`; diagnostics `routes_reservation_diagnostics.py:192,242`.

**Q9.** Yes. All three loaders already accept `Mapping[str, str] | None`, select the mapping verbatim when supplied, and route through the same dataclass/parser validators. H1/H3 can build an adapter-produced string mapping from the static snapshot without weakening all-or-none or validation semantics. Runtime call sites must stop omitting that mapping in packaged mode.

## 9. Tauri Sidecar Startup

Packaged startup is unconditional inside Tauri setup (`web_ui/src-tauri/src/lib.rs:63-101`):

```rust
63: #[cfg_attr(mobile, tauri::mobile_entry_point)]
64: pub fn run() {
65:     tauri::Builder::default()
70:         .setup(|app| {
81:             if !cfg!(debug_assertions) {
82:                 use tauri_plugin_shell::ShellExt;
83:                 let sidecar_command = app
84:                     .shell()
85:                     .sidecar("backend")
87:                 let (mut rx, child) = sidecar_command
88:                     .spawn()
92:                 tauri::async_runtime::spawn(async move {
93:                     let _keep_alive = child;
94:                     while let Some(_event) = rx.recv().await {}
95:                 });
```

No sidecar argument or working directory is specified in this source. Process ownership is retained by the async task; application exit sends the HTTP shutdown and then uses Windows `taskkill` (`lib.rs:105-142`). H1 cannot treat a source-unstated inherited CWD as runtime-root authority.

Tauri configuration (`web_ui/src-tauri/tauri.conf.json:3-4,27-38`):

```json
3:   "productName": "DopaMatrix",
4:   "version": "1.5.0-rc1",
27:   "bundle": {
28:     "active": true,
29:     "targets": "all",
30:     "externalBin": ["bin/backend"],
31:     "resources": ["bin/ffmpeg.exe", "bin/ffprobe.exe", ".env"],
32:     "icon": [
```

The `.env` resource is current source truth and remains an H5 removal requirement; R1 does not modify it.

## 10. Build Backend Startup Assumptions

`build_backend.py` is not a pure build. Its current `build()` kills processes, clears caches, mutates runtime data, invokes PyInstaller against `main.py`, then copies/removes the resulting sidecar (`build_backend.py:185-232`):

```python
185: def build():
188:     kill_backend_processes()
193:     clean_build_cache()
196:     prepare_release_data()
199:     subprocess.run(
201:             "pyinstaller",
203:             "--onefile",
204:             "--windowed",
205:             "--name", "backend",
206:             "main.py",
219:     dest_dir = os.path.join("web_ui", "src-tauri", "bin")
228:     move_with_retry(src_path, dest_path)
```

Destructive operations are explicit: `clean_build_cache()` removes `build/`, `dist/`, root `*.spec`, and `backend-*` sidecars (`build_backend.py:61-94`). `prepare_release_data()` deletes CWD/project `output/` contents and mutates the project-root `dopamatrix.db` (`build_backend.py:97-150`):

```python
102:     output_dir = os.path.join(root, "output")
105:         if os.path.isdir(output_dir):
106:             for name in os.listdir(output_dir):
110:                         os.remove(path)
112:                         shutil.rmtree(path)
120:     db_path = os.path.join(root, "dopamatrix.db")
127:         conn = sqlite3.connect(db_path)
133:             cursor.execute("DELETE FROM task_history;")
135:             cursor.execute("UPDATE local_assets_inventory SET usage_count = 0;")
```

The PyInstaller entry remains `main.py`, so the earliest safe dispatcher must be reachable from that entry (or the build entry must be changed in the later hardening phase).

## 11. Earliest Safe Operator CLI Dispatch Point

**Q4. What is the earliest safe bootstrap seam?** It is a stdlib-only bootstrap before `main.py:24` and before importing `env_utils`, logger, database, FastAPI, Ngrok, or any router. It must:

1. identify packaged/source/test mode deterministically;
2. resolve and validate the runtime root;
3. parse only enough arguments to distinguish `operator` from server mode;
4. dispatch an operator command by importing only its bounded dependencies, or import/build the normal server graph for server mode.

Current code has no such seam: `if __name__ == "__main__"` is at line 233 after the entire application graph. A bounded bootstrap refactor is therefore required.

**Q5. Can operator CLI dispatch occur before importing the normal FastAPI application graph?** Not in current source. After the bounded entry refactor, yes: operator dispatch can and must occur before importing the normal application graph.

## 12. Earliest Safe Runtime Root Selection Point

Runtime-root selection must precede `src.api.database` import and every module that copies/constructs path state. Concretely it must occur before current `main.py:24-31`, because frozen `chdir` and dotenv are themselves legacy root/config actions, and certainly before:

- `src/core/logger` import (`main.py:39`), although logs may retain their independent appdirs root;
- `src.api.database` import (`main.py:41`);
- route imports (`main.py:43-54`), especially `routes_matrix.py:60-61`;
- settings/Delivery/LLM modules that copy or hard-code the global DB path.

The runtime-root result must be explicit path data, not a late mutation of `SETTINGS_DB_PATH` and not an assumption about the Tauri sidecar CWD.

## 13. H1 Implementation Constraints

1. Add a minimal entry/bootstrap boundary; do not import `main.py` merely to dispatch operator mode.
2. Resolve packaged/dev/test mode and root with stdlib/appdirs before importing database or routers.
3. Keep packaged mutable roots explicit: global DB, tenant `data/`, and authoritative `output/` under the selected user-data root.
4. Preserve the existing per-user log root; prevent logger import from preceding operator dispatch unless the CLI deliberately initializes logging.
5. Replace copied/hard-coded DB path consumers (`settings_router`, Delivery, LLM) with the same runtime-path authority.
6. Remove import-time `output/exports` creation or defer it until the selected runtime root is known.
7. Do not use `chdir` as the authoritative dependency-injection mechanism. Development compatibility may use an explicit repository-root adapter.
8. Keep Reservation dataclasses, parsers, all-or-none behavior, and authority semantics; pass their already-supported mapping argument.
9. Keep one provider boundary but separate the immutable static Seed snapshot from bounded dynamic machine settings.
10. Treat stage labels as audit/transition metadata and validate compatibility; runtime behavior uses effective values only.
11. Tauri currently supplies no args/CWD contract; H1 must not depend on an implicit launch directory.
12. Preserve FFmpeg resource lookup while removing packaged dotenv behavior in its designated phase.
13. Do not run or reuse the current destructive `prepare_release_data()` in a normal developer worktree.

## 14. Scope Check

R1 changes only the two existing H0 documents and this new evidence artifact. It changes no Python, Vue, Rust, Tauri configuration, requirements, build script, tests, `.env`, process environment, SQLite, runtime service, Delivery Root, or backup state. No test, build, backend, or task was run.

## 15. Git Status

The final status is recorded after document validation. The expected delta is exactly:

```text
?? doc/investigations/VAR001_PHASE3D2IB2B2RH0_RELEASE_HARDENING_ARCHITECTURE_FREEZE.md
?? doc/investigations/VAR001_PHASE3D2IB2B2RH0R1_BOOTSTRAP_RUNTIME_SOURCE_EXCERPTS.md
?? doc/operations/DOPAMATRIX_V15_RUNTIME_CONFIG_SECRET_CONSTITUTION.md
```

## 16. Final Evidence Classification

The H0 architecture remains implementable. The current source does not yet have a safe pre-import CLI/runtime-root seam: `main.py` imports database and the full application graph before its executable dispatch block. This is a bounded bootstrap ordering problem, not a contradiction in the frozen provider, secret, runtime-root, or rollout architecture.

`VAR001_PHASE3D2IB2B2RH0R1_BOOTSTRAP_REFACTOR_REQUIRED`
