# VAR-001 Phase 3D-2I-B-2B-2R-H0
# V1.5 Release Hardening Architecture Freeze

## 1. Executive Result

The required hardening architecture is source-compatible and bounded. Packaged production can become completely NO-`.env` without migrating every environment value into SQLite or exposing 33 Seed controls in Settings.

Decisions:

- packaged configuration chain: database + versioned policy profile + DPAPI secret source, with no environment fallback;
- non-secret Seed authority: one atomically replaced, normalized applied-snapshot JSON row in global `app_settings`;
- secret authority: one new global `secure_settings` table protected with Windows DPAPI CurrentUser;
- policy authority: version-controlled `philippine-seed-v1` definition plus existing validators;
- runtime root: per-user `appdirs.user_data_dir("DopaMatrix", "DopaMatrixOrg")`;
- `APP_MODE_REMOVE_AS_LEGACY`;
- operator exposure: small packaged CLI, not dozens of Settings fields;
- Philippine default network exposure: Ngrok OFF;
- RC1 remains immutable; implementation requires a reviewed RC2.

Required answers:

| Question | Answer |
|---|---|
| Q1: completely NO-`.env`? | Yes, with explicit packaged/dev/test source modes and migrated consumers. |
| Q2: every env value in DB? | No. Build identity stays source/manifest; policy definitions stay version-controlled; obsolete values are removed; dev overrides remain dev-only. |
| Q3: every persisted value in UI? | No. Persistence is independent of UI exposure. |
| Q4: APP_MODE? | `APP_MODE_REMOVE_AS_LEGACY`. |
| Q5: Seed ownership? | Fixed rules in profile; all normalized effective non-secrets in snapshot; controlled fields in operational state; Assignment Secret in secure storage. |
| Q6: minimum DB schema? | Reuse `app_settings`; add only `secure_settings`. |
| Q7: reuse app_settings? | Yes, for non-secret machine settings and one applied-snapshot row. |
| Q8: DPAPI fit? | Yes on packaged Windows via CurrentUser and native `ctypes`; dev/test use explicit adapters. |
| Q9: manual field inputs? | Approved canonical tenant, approved generation, Delivery Root, Backup Root, and optional provider credentials; the Seed profile supplies all numeric values and generates the Assignment Secret locally. |
| Q10: restart? | Every applied Seed/profile/state change, secret rotation affecting rollout, product/network mode change, and runtime-source change. Delivery Root and LLM-key replacement may remain immediate. |

Final classification:

`VAR001_PHASE3D2IB2B2RH0_HARDENING_ARCHITECTURE_READY_FOR_IMPLEMENTATION`

## 2. Repository Baseline

| Fact | Value |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| HEAD | `61aed569b2e9c4eeba1f668c319ef6bdb0714fb9` |
| Commit | `61aed56 docs(v1.5): freeze release and Philippine field boundary` |
| Initial worktree | clean |
| RC1 tag/commit | `v1.5-phseed-rc1` / `5f534b180dd2ae9fa9212e6632a44746669d7e6f` |

The six required artifacts were read in full. Current source was inspected without reading `.env`, environment secret values, API-key values, or SQLite contents. No test, build, service, migration, or runtime mutation was performed.

## 3. Complete Environment Dependency Inventory

Static source inspection found 13 direct non-Seed `os.getenv`/`os.environ.get` reads and 33 Seed keys consumed through environment mappings: 46 active environment dependencies. No production Vue/Rust source explicitly reads `import.meta.env`, `process.env`, or `std::env`. `main.py` additionally writes process-local `PUBLIC_BASE_URL` after its unconditional Ngrok attempt.

Disposition vocabulary is `KEEP`, `MIGRATE`, `PROFILE`, `DEV_ONLY`, or `REMOVE`.

### Non-Seed and negative-audit entries

| Variable | Current consumer | Runtime/build/dev | Secret? | Current active? | Future layer | Production storage/source | Disposition |
|---|---|---|---|---|---|---|---|
| `PEXELS_API_KEY` | `asset_provider.PexelsProvider` | runtime, constructor | yes | yes when Pexels path is used | secret | DPAPI `secure_settings` | MIGRATE |
| `SHORT_LINK_BASE_URL` | `tracking_adapter.CloudflareKVAdapter` | runtime, module-created adapter | no | yes, defaulted | machine/integration | `app_settings` typed integration config | MIGRATE |
| `CF_ACCOUNT_ID` | `tracking_adapter.CloudflareKVAdapter` | runtime | no | yes when CF enabled | machine/integration | `app_settings` | MIGRATE |
| `CF_NAMESPACE_ID` | `tracking_adapter.CloudflareKVAdapter` | runtime | no | yes when CF enabled | machine/integration | `app_settings` | MIGRATE |
| `CF_API_TOKEN` | `tracking_adapter.CloudflareKVAdapter` | runtime | yes | token presence currently activates real writes | secret | DPAPI `secure_settings` plus explicit enable state | MIGRATE |
| `OPENAI_BASE_URL` | `llm_provider.OpenAIProvider` | runtime, provider construction | no | yes, optional | machine setting | `app_settings` LLM config | MIGRATE |
| `LLM_MODEL` | `llm_provider.OpenAIProvider` | runtime, provider construction | no | yes, defaulted | machine setting | `app_settings` LLM config | MIGRATE |
| `INTERNAL_OPS_CHAT_ID` | `reporting.NotificationRouter` | runtime, router construction | no | yes, optional | integration state | `app_settings` | MIGRATE |
| `CLIENT_REPORTING_CHAT_ID` | `reporting.NotificationRouter` | runtime, router construction | no | yes, optional | integration state | `app_settings` | MIGRATE |
| `TELEGRAM_BOT_TOKEN` | `TelegramAdapter` | runtime, adapter construction | yes | yes when messaging/reporting path constructs adapter | secret | DPAPI `secure_settings` | MIGRATE |
| `LLM_COST_PER_TOKEN` | `api.services` | runtime, module import | no | yes, defaulted | product policy | versioned service policy; dev override only | PROFILE |
| `TTS_COST_PER_SEC` | `api.services` | runtime, module import | no | yes, defaulted | product policy | versioned service policy; dev override only | PROFILE |
| `PUBLIC_BASE_URL` | `api.services`; written by `main.py` | runtime process-local | no | yes on legacy worker path | derived network state | loopback/request-aware URL; optional dev adapter | REMOVE |
| `APP_MODE` | none | none | no | no source match | obsolete | none | REMOVE |
| `OPENAI_API_KEY` | none as environment; current key is DB `openai_api_key` | none as env | yes | no env fallback | secret | DPAPI `secure_settings` | MIGRATE |
| `PEXELS_PER_PAGE` | docstring only; constructor parameter is authoritative | none as env | no | no read | obsolete doc claim | constructor/profile if ever needed | REMOVE |
| `NGROK_AUTHTOKEN` | no DopaMatrix source read; pyngrok may use its own external config | dev/network | yes | not an explicit app dependency | development only | developer process/config outside packaged chain | DEV_ONLY |
| host/port/debug variables | none; `127.0.0.1:8000` and dev reload are code paths | runtime/build | no | no reads | build/product profile | source/operator command contract | REMOVE |

### Seed environment entries (complete 33)

`Lease` = `reservation_lease.py`; `Readiness` = `reservation_rollout_readiness.py`; `Control` = `reservation_rollout_control.py`.

| Variable | Current consumer | Runtime/build/dev | Secret? | Current active? | Future layer | Production storage/source | Disposition |
|---|---|---|---|---|---|---|---|
| `RESERVATION_LEASE_TTL_SECONDS` | Lease | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_HEARTBEAT_INTERVAL_SECONDS` | Lease | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_READINESS_WINDOW` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MAXIMUM_PARTIAL_PLAN_RATE` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MAXIMUM_CLEANUP_WARNING_RATE` | Readiness | runtime evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_CONTROL_ENABLED` | Control | per assignment/status | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_GENERATION` | Control | per assignment/status | no | yes | operational state | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_TENANT_ALLOWLIST` | Control | per assignment/status | no | yes | operational state | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS` | Control | per assignment/status | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS` | Control | per assignment/status | no | yes | operational state | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_ASSIGNMENT_SECRET` | Control HMAC | per assignment | **yes** | yes | secret | DPAPI `secure_settings` | MIGRATE |
| `RESERVATION_ROLLOUT_KILL_SWITCH` | Control | per assignment/status | no | yes | operational state | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_WINDOW` | Control | per assignment/status | no | yes | policy/stage state | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS` | Control | status | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_DIAGNOSTIC_COVERAGE_RATE` | Control | breaker evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_PLANNING_COVERAGE_RATE` | Control | breaker evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_TERMINAL_COVERAGE_RATE` | Control | breaker evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | Control | breaker evaluation | no | yes | policy/stage state | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE` | Control | breaker evaluation | no | yes | policy/stage state | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE` | Control | breaker evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | Control | breaker evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE` | Control | breaker evaluation | no | yes | policy/snapshot | applied snapshot | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE` | Control | breaker evaluation | no | yes | policy/stage state | applied snapshot | PROFILE |

## 4. Configuration Classification Matrix

| Domain | Definition | Persisted state | Secret store | UI/CLI |
|---|---|---|---|---|
| Release version/tag/arch | build metadata | no | no | no UI |
| Universal product profile | source | identity only if useful | no | no UI |
| Delivery Root | validation contract | current path | no | ordinary Settings |
| LLM endpoint/model | supported machine defaults | selected endpoint/model | API key | ordinary Settings |
| Philippine Seed | `philippine-seed-v1` | complete applied snapshot | Assignment Secret | field CLI |
| Optional Pexels | integration definition | enabled/settings | API key | operator/admin only |
| Optional Telegram | integration definition | enabled/chat IDs | bot token | operator/admin only |
| Optional Cloudflare tracking | integration definition | enabled/account/namespace/base URL | API token | operator/admin only |
| Cost rates | release/service policy | no V1.5 runtime state | no | hidden |
| Ngrok | dev tool | no production state | dev credential outside package | no production UI |

## 5. APP_MODE Source Truth

There are zero `APP_MODE` matches in current production Python, Vue, Rust, or build source. There is no mode-specific packaging or backend branch controlled by it.

Current task semantics are explicit:

- Vue chooses `content` or `ua` in Workspace/DSL Orchestrator;
- request schemas carry `engine_type`;
- parser/routes pass `engine_type` through planning/rendering;
- asset `business_scopes` are per-asset metadata, not global deployment mode.

One desktop can run both task types. Decision: `APP_MODE_REMOVE_AS_LEGACY`. No DB migration, UI selector, product-profile toggle, or compatibility alias is warranted. Tests must prove removing legacy external `APP_MODE` has no behavioral effect.

## 6. Current OpenAI Settings Truth

Current source behavior:

- `POST /api/v1/settings/llm` trims a nonempty `api_key`, then performs `INSERT OR REPLACE` into global `dopamatrix.db`, table `app_settings`, key `openai_api_key`;
- `key_value` is plaintext;
- POST returns only `{"status": "ok"}` and invalidates `_api_key_cache["openai_api_key"]`;
- `GET /api/v1/settings/llm` reads plaintext and returns a first-five/last-four mask (or `****`) plus `is_configured`;
- `llm_provider` lazily reads the same row into a module dictionary; missing table/key becomes empty and provider raises `ValueError`;
- there is no `OPENAI_API_KEY` environment fallback;
- `OPENAI_BASE_URL` and `LLM_MODEL` are environment-backed non-secret provider settings;
- provider cache invalidation is precise; concurrent cache misses may duplicate a read but do not mutate the key;
- DeepSeek/Moonshot are only OpenAI-compatible endpoint examples. No DeepSeek-specific route/key/provider is active.

Target compatibility: retain POST input and success semantics, change storage to DPAPI, retain cache invalidation, and make GET return configured status only. SettingsView needs a small display update; no broad redesign.

## 7. Current Packaged .env Paths

`main.py` changes frozen CWD to the executable directory and calls `load_env()` before application imports. Frozen `load_env()` checks `<backend.exe-dir>/.env`, then invokes default ancestor search. Lifespan later deletes the executable-adjacent file after it has already been loaded. `api.services.run_matrix_job()` calls `load_env()` again. Tauri explicitly bundles `.env` as a resource.

This creates installer leakage, ancestor fallback, restart instability, and independent consumer coupling. Deletion after load is not zero trust.

## 8. Target NO-.env Architecture

Packaged mode neither imports nor invokes dotenv configuration behavior. Tauri removes `.env` from resources and builds successfully when the file does not exist. Frozen `env_utils` retains FFmpeg discovery but refuses dotenv search/load. `main.py` neither loads nor deletes `.env`; `api.services` removes its secondary load.

Production configuration is resolved only through `RuntimeConfigProvider`. Missing production state fails closed. Development can explicitly select dotenv/environment; tests inject deterministic sources.

No plaintext replacement file (`config.env`, JSON, YAML, TOML, or secrets file) is allowed.

## 9. Product Profile vs Operational Profile

The product profile is universal DopaMatrix and is release-defined. `APP_MODE` is removed.

The operational profile `philippine-seed-v1` defines Reservation rollout governance. It is selected by a field operator and can be applied to an approved tenant/generation. The two concepts do not share keys or UI.

## 10. Seed 33-Key Decomposition

All 33 current keys were source-verified: 2 lease + 13 Readiness + 18 Control. In the table, `P` means versioned policy definition, `S` means persisted applied snapshot, and `CC` means change-controlled. All changes require controlled restart. No row becomes an ordinary Settings control.

| Key | Current source | Secret? | Policy definition? | Applied snapshot? | Operator mutable? | Stage of mutation | Production authority | UI/CLI exposure | Restart required | Migration action |
|---|---|---:|---|---|---|---|---|---|---:|---|
| `RESERVATION_LEASE_TTL_SECONDS` | Lease | no | P, profile pair | S | CC profile only | P0 or approved lease change | snapshot | hidden profile/CLI action | yes | PROFILE |
| `RESERVATION_HEARTBEAT_INTERVAL_SECONDS` | Lease | no | P, profile pair | S | CC profile only | paired with TTL | snapshot | hidden profile/CLI action | yes | PROFILE |
| `RESERVATION_ROLLOUT_READINESS_WINDOW` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_AUTHORITATIVE_ENFORCE_TASKS` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVED_TASKS` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_CONFLICT_TASKS` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_DIAGNOSTIC_RUN_COVERAGE_RATE` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_PLANNING_OBSERVATION_COVERAGE_RATE` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_TERMINAL_OBSERVATION_COVERAGE_RATE` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_MAXIMUM_PARTIAL_PLAN_RATE` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_MAXIMUM_AUTHORITY_LOSS_RATE` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_MAXIMUM_WORKER_LEASE_CONFIG_FAILURE_RATE` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_MAXIMUM_CLEANUP_WARNING_RATE` | Readiness | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_CONTROL_ENABLED` | Control | no | P=true | S | no | Safe-Off apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_GENERATION` | Control | no | format/bounds | S | yes, CC | P0; incident/re-arm epoch | snapshot | field CLI | yes | PROFILE |
| `RESERVATION_ROLLOUT_TENANT_ALLOWLIST` | Control | no | one-tenant bounds | S | yes, CC | P0/tenant stagger | snapshot | field CLI | yes | PROFILE |
| `RESERVATION_ROLLOUT_EXACT_CANARY_BASIS_POINTS` | Control | no | P=0 | S | no in Seed | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_BALANCED_CANARY_BASIS_POINTS` | Control | no | bounds/defaults | S | yes, CC | P0=0, P3-W/reviews | snapshot | field CLI | yes | PROFILE |
| `RESERVATION_ROLLOUT_ASSIGNMENT_SECRET` | Control | **yes** | presence/rotation rule | memory only; persisted reference/status | rotation only | generated P0 if absent; explicit rotation | DPAPI secure setting | status/rotation CLI, never value | yes | MIGRATE |
| `RESERVATION_ROLLOUT_KILL_SWITCH` | Control | no | transition rules | S | yes | true P0-P2; false last P3; containment | snapshot | field CLI | yes | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_WINDOW` | Control | no | allowed transition | S | yes, CC | 7d initial; 24h only after eligibility | snapshot | named CLI transition | yes | PROFILE |
| `RESERVATION_ROLLOUT_MINIMUM_CANARY_TASKS` | Control | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_DIAGNOSTIC_COVERAGE_RATE` | Control | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_PLANNING_COVERAGE_RATE` | Control | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MINIMUM_TERMINAL_COVERAGE_RATE` | Control | no | P | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_ZERO_PLAN_CONFLICT_RATE` | Control | no | warm/active P values | S | guarded transition | P3-W 1.0 -> P3-A .30 | snapshot | named CLI transition | yes | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_PARTIAL_PLAN_RATE` | Control | no | warm/active P values | S | guarded transition | P3-W 1.0 -> P3-A .20 | snapshot | named CLI transition | yes | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_AUTHORITY_LOSS_RATE` | Control | no | P=0 | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_TERMINAL_PERSIST_FAILURE_RATE` | Control | no | P=0 | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_WORKER_CONFIG_FAILURE_RATE` | Control | no | P=0 | S | no | profile apply | snapshot | hidden | yes | PROFILE |
| `RESERVATION_ROLLOUT_ROLLBACK_MAXIMUM_CLEANUP_WARNING_RATE` | Control | no | warm/active P values | S | guarded transition | P3-W 1.0 -> P3-A .20 | snapshot | named CLI transition | yes | PROFILE |

This decomposition is why persistence does not require 33 Settings controls. Operators normally supply tenant and generation; named actions derive the rest.

## 11. Policy Definition vs Applied Snapshot

Concrete V1.5 design:

1. source defines immutable `philippine-seed-v1` profile versions and allowed transitions;
2. operator CLI selects the profile and supplies tenant/generation;
3. profile application materializes all 32 effective non-secret values into one canonical JSON snapshot;
4. snapshot is validated with current dataclasses/loaders and atomically replaced in `app_settings`;
5. Assignment Secret remains in `secure_settings`; only its presence/reference participates in snapshot validation;
6. startup reads once and constructs immutable typed process configuration;
7. runtime changes replace the complete snapshot and activate only after controlled restart.

No partial row set can become active, and profile evolution remains reviewable.

Any persisted stage label (`SAFE_OFF`, `P3_W`, `P3_A`, or a later reviewed label) is non-authoritative transition/audit metadata. Runtime rollout decisions must use the validated effective snapshot—generation, allowlist, Exact/Balanced BPS, kill switch, rollback window and thresholds, lease configuration, and Readiness configuration—not the label. Named transition commands derive and atomically write the effective values. Startup must validate any label against those values and fail closed on mismatch. This is a compatibility assertion, not a second rollout state machine.

## 12. Operational State Mapping

| State | Ownership | Mutation |
|---|---|---|
| active profile/version | applied snapshot | profile application only |
| canonical tenant allowlist | applied snapshot | tenant stagger/change control |
| rollout generation | applied snapshot | new governed epoch only |
| stage (`SAFE_OFF`, `P3_W`, `P3_A`, etc.) | optional non-authoritative transition/audit metadata | named transition; startup compatibility check only |
| Exact/Balanced BPS | applied snapshot | fixed/controlled transition |
| kill switch | applied snapshot | controlled operator action; CLI sufficient for V1.5 |
| lease profile | applied snapshot | approved paired profile change |
| breaker facts | existing tenant DB | unchanged; not copied into config snapshot |
| readiness/diagnostic evidence | existing tenant DB | unchanged; never configuration |

## 13. Secret Classification

| Current credential | Current authority | Target | Notes |
|---|---|---|---|
| OpenAI key | plaintext `app_settings` | `secure_settings/openai_api_key` | automatic verified legacy migration |
| Assignment Secret | process environment | `secure_settings/reservation_rollout_assignment_secret` | generated locally, status only |
| Pexels key | environment | `secure_settings/pexels_api_key` | optional integration |
| Telegram bot token | environment | `secure_settings/telegram_bot_token` | optional integration |
| Cloudflare API token | environment | `secure_settings/cf_api_token` | explicit integration enable, not token-presence activation |

Account IDs, namespace IDs, chat IDs, endpoints, models, and base URLs are non-secret DB settings. No active DeepSeek-specific credential exists. Ngrok credentials are development-only and must not enter the Philippine package.

## 14. DPAPI Feasibility

DPAPI CurrentUser is feasible for the Windows/Tauri/PyInstaller target. Python can invoke native `crypt32` using `ctypes`; no external daemon, network vault, or plaintext master key is required. PyInstaller can analyze/bundle the Python wrapper, and tests can substitute a deterministic in-memory cryptor.

Required implementation properties:

- BLOB ciphertext plus explicit encryption-scheme/version;
- same Windows account for operator CLI and application;
- zero secret metadata in logs/errors/status beyond PRESENT/ABSENT/ERROR;
- no silent Machine scope fallback;
- explicit handling of user-profile loss and corrupt ciphertext;
- exact decrypt round-trip tests on Windows.

DPAPI does not protect against the running user, administrators, privileged malware, or memory inspection.

## 15. Legacy OpenAI Migration

Choose automatic idempotent packaged-startup migration. It removes the need for an operator to handle plaintext and can preserve the only usable credential on failure.

Algorithm:

1. detect plaintext legacy row and secure row;
2. if secure row exists, decrypt-validate it and never overwrite it;
3. if both valid values conflict, preserve both, report bounded migration conflict, and require explicit resolution;
4. if no secure value exists, DPAPI-encrypt legacy bytes and insert;
5. decrypt and exact-compare in memory;
6. delete the legacy row only after successful verification, in a transactionally safe sequence;
7. invalidate/update provider cache;
8. never log value, length, hash, prefix, or suffix;
9. on failure retain plaintext legacy row and fail safely without `.env` fallback.

Fresh Philippine installations start with no OpenAI credential.

## 16. RuntimeConfigProvider Integration

Recommended minimal modules:

- `src/api/runtime_paths.py`: explicit packaged/dev/test roots;
- `src/api/secret_store.py`: `secure_settings`, DPAPI adapter, statuses, migration;
- `src/api/policy_profiles.py`: named immutable profile definitions and transitions;
- `src/api/runtime_config.py`: source adapters, canonical snapshot schema, immutable typed snapshot, existing-validator bridge;
- `src/api/operator_cli.py`: argument dispatch and offline operator commands.

`main.py` selects mode/root and dispatches operator commands before Uvicorn. Server startup initializes the global DB, performs bounded migrations, builds one immutable snapshot, and then mounts serving behavior. Reservation loaders retain their dataclasses/parsers but consume an injected mapping/snapshot instead of global `os.environ`.

Secrets use redacted wrapper types with `repr=False`; provider exceptions never interpolate a secret.

One provider boundary supports two lifecycles without conflating them:

- the **static operational snapshot** contains Seed/Reservation/Readiness/Rollout configuration and Assignment Secret participation, is loaded and validated at controlled startup, and is immutable for the backend process generation;
- **dynamic machine settings** such as Delivery Root and OpenAI credential may retain bounded read-through or explicit cache invalidation. LLM endpoint/model and optional integration configuration may use that lifecycle only where their implementation supplies an equally bounded mechanism.

Delivery Root is not part of the Seed snapshot. The existence of dynamic machine settings does not permit Seed rollout state to hot-reload; Seed changes still require complete atomic replacement plus controlled restart.

## 17. Packaged / Dev / Test Source Modes

| Mode | Configuration adapters | Dotenv | Host environment |
|---|---|---|---|
| packaged production | DB + profile + DPAPI | prohibited | prohibited as runtime fallback |
| source development | explicit environment adapter; optional dotenv | allowed | allowed by developer choice |
| test | deterministic mapping/fake secret source | normally absent | only when test explicitly supplies it |

Mode selection is deterministic from frozen/entry-point context, not an environment variable that production can accidentally inherit.

## 18. Runtime Data Root

Freeze packaged writable root as `appdirs.user_data_dir("DopaMatrix", "DopaMatrixOrg")`, conceptually `%LOCALAPPDATA%\DopaMatrixOrg\DopaMatrix\`:

```text
dopamatrix.db
data/dopamatrix_<tenant>.db
output/
```

Logs retain `user_log_dir`. FFmpeg, FFprobe, app executable, and backend sidecar remain installation resources. Development mode continues to use repository-relative roots.

An existing executable-adjacent runtime root must not be silently merged. H1 must either provide an explicit collision-checked, verified legacy-root migration command or fail with a bounded migration-required status. Split-brain databases are forbidden.

## 19. Field Operator Workflow

Conceptual packaged commands:

```text
backend.exe operator config status
backend.exe operator tenant provision --tenant ph-elv-0001
backend.exe operator seed-config apply-safe-off \
  --tenant ph-elv-0001 \
  --generation phseed-elv0001-bal-YYYYMMDD-rN
backend.exe operator secret status
backend.exe operator backup ...
backend.exe operator backup verify ...
```

One executable can safely host these modes if argument dispatch precedes Uvicorn, Ngrok, router imports, global Engine construction, and normal application side effects.

Manual field inputs are limited to:

- approved Canonical Tenant ID;
- approved rollout Generation;
- Delivery Root;
- Backup Root/destination at backup time;
- optional OpenAI and enabled-integration credentials entered through secure flows.

The Assignment Secret is generated locally if absent and never displayed. Lease/readiness/rollback/BPS Safe-Off defaults come from the profile.

## 20. UI Exposure Matrix

| Domain | Classification | Reason |
|---|---|---|
| OpenAI API Key | `ORDINARY_SETTINGS_UI` | normal provider credential; write/status only |
| Delivery Root | `ORDINARY_SETTINGS_UI` | operator-selected machine path |
| APP_MODE | `NO_UI` | remove as legacy |
| Seed Profile | `FIELD_OPERATOR_CLI` | governed operation, not creative setting |
| Generation | `FIELD_OPERATOR_CLI` | governed epoch |
| Kill Switch | `FIELD_OPERATOR_CLI`; `ADMIN_ONLY_FUTURE_UI` optional | operational safety state |
| Basis Points | `FIELD_OPERATOR_CLI`; `ADMIN_ONLY_FUTURE_UI` optional | controlled exposure |
| Readiness thresholds | `HIDDEN_PROFILE_DEFINITION` | frozen reviewed policy |
| Rollback thresholds | `HIDDEN_PROFILE_DEFINITION` plus named stage action | prevents raw unsafe edits |
| Assignment Secret | `NO_UI` | status/explicit rotation only |
| Lease TTL/heartbeat | `HIDDEN_PROFILE_DEFINITION` plus approved profile CLI | indivisible safety pair |
| LLM base URL/model | ordinary/advanced LLM Settings | normal machine provider choice |
| Pexels/Telegram/Cloudflare integration config | operator/admin only | optional operational integrations |

## 21. Ngrok / Other Runtime Dependencies

- **Ngrok:** remove unconditional startup. Philippine packaged default is OFF. Keep only an explicit development adapter or a separately approved controlled machine setting; no production `.env` dependency.
- **Telegram:** optional integration group. Token in DPAPI; chat IDs in DB; missing/partial config disables messaging without failing rendering.
- **Cloudflare tracking:** optional explicit enable group. Token presence alone must not activate real writes. Token in DPAPI; account/namespace/base URL in DB; group validates all-or-none.
- **Pexels:** key in DPAPI when the external provider is enabled; local asset mode remains independent.
- **OpenAI-compatible LLM:** key in DPAPI; model/base URL in DB.
- **Cost rates:** release/service policy, not normal field UI.
- **Port/host/debug:** no current environment reads; packaged remains loopback `127.0.0.1:8000`, dev reload is development behavior.
- **PUBLIC_BASE_URL:** remove environment mutation from packaged field mode; derive local URLs or use request-aware routing.

## 22. Policy / Runbook Migration Impact

Active operator documents requiring terminology/workflow updates after implementation:

- Philippine Seed Canary Runbook: replace backend environment keys and `.env` restart instructions with Runtime Configuration Keys, applied snapshot, operator CLI, secure settings, and controlled restart;
- Philippine Seed Execution Pack: replace Environment Manifest/apply procedure with profile/snapshot status and named transitions; numeric policy remains unchanged;
- Release Field Boundary: remove “safe field environment template” and “complete Seed environment”; substitute runtime-configuration procedure/profile/secret-generation artifacts;
- 2B-2A assembly report: record supersession of environment-based execution wording.

Historical investigation/source-review artifacts remain immutable evidence; later reports may mark them superseded rather than rewrite their historical truth. Backup and Tenant Identity constitutions require only packaged-command cross-reference updates, not authority changes.

## 23. Source File Impact Map

| File/component | Impact | Required behavior |
|---|---|---|
| `web_ui/src-tauri/tauri.conf.json` | MUST_CHANGE | remove `.env` resource; build without it |
| `main.py` | MUST_CHANGE | runtime root/mode bootstrap, operator dispatch, no frozen dotenv/delete, Ngrok off by default |
| `src/utils/env_utils.py` | MUST_CHANGE | FFmpeg discovery retained; dotenv dev-only, never frozen |
| `src/api/database.py` | MUST_CHANGE | explicit runtime paths for global/tenant DB; secure table initialization hook |
| `src/api/settings_router.py` | MUST_CHANGE | DPAPI OpenAI storage; configured-only GET |
| `src/services/llm_provider.py` | MUST_CHANGE | provider snapshot/secure source; no production env reads; cache contract |
| `src/api/reservation_lease.py` | MUST_CHANGE | injected snapshot mapping; validator semantics unchanged |
| `src/api/reservation_rollout_readiness.py` | MUST_CHANGE | injected snapshot mapping; all-or-none semantics unchanged |
| `src/api/reservation_rollout_control.py` | MUST_CHANGE | injected snapshot + secure Assignment Secret; HMAC/rollout semantics unchanged |
| `src/services/asset_provider.py` | MUST_CHANGE | secure Pexels credential source |
| `src/services/tracking_adapter.py` | MUST_CHANGE | typed integration config and secure token; explicit enable |
| `src/services/reporting.py` / Telegram adapter | MUST_CHANGE | typed integration config and secure token |
| `src/api/services.py` | MUST_CHANGE | remove dotenv call and env cost/base URL reads |
| `web_ui/src/views/SettingsView.vue` | MUST_CHANGE | configured-only LLM status; no masked key |
| `web_ui/src/stores/appStore.js` | NO_CHANGE for Seed | Delivery API remains; no Seed controls/local secrets |
| `src/api/models.py` | NO_CHANGE | secure/control-plane tables belong to global DB, not tenant ORM |
| `build_backend.py` | MUST_CHANGE | deterministic isolated build; no runtime-data mutation; no `.env` assumption |
| packaged operator entry | MUST_CHANGE/new | command dispatch before server/import side effects |
| `requirements.txt` | NO_CHANGE if native `ctypes` DPAPI | avoid unnecessary pywin32 runtime dependency |
| tests | MUST_CHANGE/new | source modes, migration, DPAPI, profile atomicity, artifact NO-`.env` |

New minimal boundaries: `runtime_paths.py`, `secret_store.py`, `policy_profiles.py`, `runtime_config.py`, and `operator_cli.py`. Avoid a generic settings framework.

## 24. Test / Acceptance Requirements

Future acceptance must prove:

- Tauri build and packaged startup succeed with no `.env`; installer scan contains no plaintext config/secret file; frozen code does not search/delete ancestor `.env`;
- user-data root owns global DB, tenant DB, and internal output while binaries remain separate;
- source-development dotenv and deterministic test injection remain usable but cannot leak into packaged mode;
- OpenAI Settings save encrypts, GET returns configured status only, DB contains no plaintext, cache invalidates, legacy migration succeeds, and failed migration preserves legacy truth;
- DPAPI round trip works under the packaged Windows user; copied DB does not reveal plaintext; corruption is bounded/fail-closed;
- Assignment Secret is CSPRNG-generated locally, preserved, never printed, and rotation requires controlled new-generation workflow;
- `apply-safe-off` needs only tenant/generation, writes a complete atomic snapshot, leaves Exact/Balanced `0/0` and kill `true`, and rejects partial/unknown/version-mismatched profiles;
- controlled restart recreates the same effective snapshot and existing validators accept it;
- APP_MODE removal does not change per-task `engine_type` content/UA paths;
- Ngrok is absent/off in normal packaged startup;
- tenant provisioning and backup commands run without Uvicorn or creative/Reservation traffic;
- L1/L2 authority, readiness, rollout, breaker, Task Identity, Delivery, and backup regressions remain unchanged.

## 25. Risks / Open Questions

Bounded implementation questions, not architecture blockers:

1. define the explicit legacy executable-adjacent data migration/rollback evidence before H1 ships;
2. select the exact stable JSON canonicalization/schema-version strategy for the snapshot;
3. confirm whether optional Pexels/Telegram/Cloudflare integrations are shipped enabled-capable or explicitly disabled for the first Philippine release;
4. choose final configured-status response field compatibility (`is_configured` can be retained);
5. ensure CLI and desktop always run as the same Windows user for DPAPI CurrentUser;
6. define recovery when the Windows profile is lost—provider secrets are re-entered, Assignment Secret rotation requires kill + new generation;
7. installer NSIS/MSI and broader Tauri capability hardening remain separate release blockers from H0 configuration architecture.

There is no need to revise the core profile/secret/provider architecture before implementation.

## 26. Implementation Phases

1. **H1 — Runtime paths and provider foundation:** explicit packaged/dev/test modes, per-user root, immutable snapshot types, global DB path, explicit legacy-root detection/migration, no consumer semantic changes.
2. **H2 — Secret store and credentials:** `secure_settings`, DPAPI, OpenAI migration/API/cache, then Pexels/Telegram/Cloudflare secret adapters.
3. **H3 — Operational profile and snapshot:** `philippine-seed-v1`, atomic apply/validation, existing lease/readiness/control validators, controlled transitions.
4. **H4 — Packaged operator CLI:** pre-Uvicorn dispatch, tenant provision, config/status/apply-safe-off, secret status/rotation, backup/verify.
5. **H5 — Remove packaged dotenv and exposure debt:** Tauri resource removal, frozen dotenv prohibition, Ngrok default-off, PUBLIC_BASE_URL cleanup, visible version/release surfaces, operator-doc terminology sync.
6. **H6 — Clean isolated build and security acceptance:** corrected immutable RC2, artifact inventory, NO-`.env`/DB/media scan, DPAPI/runtime-root/CLI acceptance, checksums and handoff manifest.

Each phase preserves current policy meanings and runs focused plus authority regressions. AUTH-001 remains outside this sequence.

## 27. Scope Check

This audit changed no Python, Vue, Rust, Tauri config, build script, test, package file, `.env`, process environment, SQLite, service, tenant, Delivery Root, or backup. It did not read any secret value. It created only the two authorized H0 documents and did not commit or push.

## 28. Git Status

Initial worktree was clean. Expected final delta:

```text
?? doc/investigations/VAR001_PHASE3D2IB2B2RH0_RELEASE_HARDENING_ARCHITECTURE_FREEZE.md
?? doc/operations/DOPAMATRIX_V15_RUNTIME_CONFIG_SECRET_CONSTITUTION.md
```

## 29. Final Classification

The architecture is source-compatible, keeps configuration definition separate from state and UI, preserves all accepted authority semantics, and has a bounded implementation path.

`VAR001_PHASE3D2IB2B2RH0_HARDENING_ARCHITECTURE_READY_FOR_IMPLEMENTATION`
