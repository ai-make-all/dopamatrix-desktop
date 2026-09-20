# VAR-001 Phase 3D-2I-B-2B-2R-H2
# DPAPI Secret Store & Credential Migration Implementation Report

## 1. Executive Result

H2 implementation and regression execution are complete. DopaMatrix now has one global, fixed-key `secure_settings` store; Windows DPAPI CurrentUser protection; bounded secret-store/provider errors; verified OpenAI plaintext migration; configured-status-only Settings behavior; secure OpenAI provider authority; and packaged secure sources for Pexels, Telegram, and Cloudflare. Cloudflare packaged writes additionally require explicit non-secret enablement and complete configuration.

H2-R1 source review subsequently found a narrow Telegram exception-logging risk: because the bot token is embedded in the request URL, logging an `httpx` exception via `str(exc)` could disclose that URL. H2-R2 retained this historical finding and closed it with a fixed `TELEGRAM_REQUEST_FAILED` boundary, suppressed exception context, type-only upstream logging, and synthetic token-redaction regression coverage. H2-R2 also added direct OpenAI provider conflict and no-client-construction coverage.

The Assignment Secret is registered and can be stored securely, but Reservation rollout still consumes its existing environment mapping. No Seed profile, operational snapshot, Reservation source switch, operator command, or H3-H6 behavior was implemented.

Final classification:

`VAR001_PHASE3D2IB2B2RH2_DPAPI_SECRET_MIGRATION_PASS`

## 2. Repository Baseline

| Fact | Value |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| H2 starting HEAD | `e7bf00301e60f563f1b8deeb227b23145a109664` |
| Starting commit | `e7bf003 feat(v1.5): establish runtime path and bootstrap foundation` |
| Starting worktree | clean |
| RC1 tag target | `5f534b180dd2ae9fa9212e6632a44746669d7e6f` |

H1 was committed before H2. RC1 was neither moved nor modified.

## 3. H2 Scope

Implemented only the H2 secret-store, DPAPI, OpenAI migration/API/provider, optional credential-source, frontend status, tests, and evidence boundaries. No production database was opened by the test fixtures; all secret-store tests used isolated temporary global databases and synthetic values.

## 4. Secret Registry

The explicit registry contains exactly:

- `openai_api_key`;
- `reservation_rollout_assignment_secret`;
- `pexels_api_key`;
- `telegram_bot_token`;
- `cf_api_token`.

Unknown names fail with `SECRET_KEY_UNRECOGNIZED`. No arbitrary key API or DeepSeek-specific credential was added.

## 5. secure_settings Schema

The global RuntimePaths settings database owns the idempotent table:

```sql
secure_settings(
  key_name TEXT PRIMARY KEY,
  encryption_scheme TEXT NOT NULL,
  ciphertext BLOB NOT NULL,
  updated_at TEXT NOT NULL
)
```

Supported writes bind ciphertext through `sqlite3.Binary`. A real tenant initialization test proves the table exists in the isolated global DB and is absent from the initialized tenant DB.

## 6. Secret Store Architecture

`src/api/secret_store.py` separates a `SecretProtector` protocol from SQLite storage. `SecretStore` provides idempotent schema initialization and allowlisted `set_secret`, `get_secret`, `delete_secret`, and `get_status`. Status is limited to `PRESENT`, `ABSENT`, or `ERROR`. SQL is parameterized and every SQLite connection is explicitly closed after its transaction.

The default store always resolves `get_runtime_paths().settings_db_path`; there is no CWD, install-directory, or tenant-DB fallback.

## 7. DPAPI Implementation

`WindowsDpapiProtector` uses native `CryptProtectData` and `CryptUnprotectData` through the Python standard-library `ctypes` interface. It sets `CRYPTPROTECT_UI_FORBIDDEN`, uses CurrentUser scope, validates the stored versioned scheme `dpapi-current-user-v1`, and frees DPAPI output through `LocalFree`.

No optional entropy, plaintext master key, local key file, Machine-scope fallback, or pywin32 dependency was added. Tests use an injected deterministic fake except for one bounded real Windows round trip.

## 8. DPAPI Security Boundary

The design protects credentials from plaintext SQLite inspection, copied-database disclosure, and accidental packaging as plaintext. It does not claim protection from the same Windows user, administrators, privileged malware, compromised process memory, or a compromised application process.

Unknown schemes, corrupted data, unavailable platform protection, encrypt failures, and decrypt failures produce stable secret-independent errors. No error contains secret length, hash, prefix, suffix, ciphertext, or value.

## 9. OpenAI Legacy Migration

The lifespan invokes migration only after RuntimePaths and global application schema initialization. It never runs at module import and never relocates an executable-adjacent legacy root.

Covered cases:

| Case | Result |
|---|---|
| no legacy / no secure | `UNCONFIGURED` |
| legacy only | encrypt, persist, decrypt-verify, delete plaintext, `MIGRATED` |
| secure only | decrypt-validate, `SECURE_ONLY` |
| identical legacy + secure | verify, remove redundant plaintext |
| conflicting legacy + secure | preserve both, `MIGRATION_CONFLICT`, feature fail-closed |
| migration encryption failure | preserve legacy, `ERROR`, no plaintext authority fallback |
| corrupt secure value | `ERROR`, no legacy fallback |

Insert/verification/deletion occur in one SQLite transaction. Startup logs only the bounded result and invalidates the OpenAI provider cache. Optional OpenAI migration failure does not stop unrelated application or Reservation operation.

## 10. OpenAI Settings API

`POST /api/v1/settings/llm` validates a non-empty key, protects and writes it, decrypt-verifies it, deletes any legacy plaintext row in the same transaction, invalidates the provider cache, and returns only `{"status":"ok"}`. An explicit POST resolves a legacy conflict by replacing secure authority.

`GET /api/v1/settings/llm` returns only:

```json
{
  "is_configured": true,
  "secret_status": "PRESENT",
  "migration_required": false
}
```

It returns no key, mask, prefix, suffix, length, or hash. Errors use bounded messages such as `LLM_SECRET_SAVE_FAILED`.

## 11. Settings UI

The existing OpenAI card now consumes only `is_configured`, displays configured/not-configured state, and no longer holds or renders `llmMaskedKey`. Replacement input remains password-scoped and is cleared after save. No generic credential UI was added.

## 12. LLM Provider Integration

The OpenAI provider reads only DPAPI-backed `secure_settings` through the bounded cache. `OPENAI_API_KEY` has no environment fallback. Missing, conflicting, or corrupt authority fails with stable messages. Save and startup migration retain explicit cache invalidation.

Existing non-secret `OPENAI_BASE_URL` and `LLM_MODEL` development compatibility remains deferred; request/model semantics remain unchanged. Provider exceptions no longer echo SDK details or raw model output.

## 13. Assignment Secret H2 Boundary

`reservation_rollout_assignment_secret` is allowlisted and its secure set/get/delete/status capability is covered by focused tests. `src/api/reservation_rollout_control.py`, its environment key, HMAC input, assignment algorithm, and runtime authority were not modified.

`H2_ASSIGNMENT_SECRET_STORAGE_READY_NOT_WIRED = PASS`

## 14. Pexels Credential Migration

`PexelsProvider` resolves an absent explicit key through the centralized source. Packaged mode uses `secure_settings.pexels_api_key` and never the process environment. Source development may use `PEXELS_API_KEY`. Missing/corrupt packaged credentials fail only Pexels construction/action and do not affect local-asset workflows or startup.

## 15. Telegram Credential Migration

`TelegramAdapter` resolves an absent explicit token through the centralized source. Packaged mode uses `secure_settings.telegram_bot_token`; source development may use `TELEGRAM_BOT_TOKEN`. `NotificationRouter` treats missing/corrupt Telegram configuration as optional and disables only notification delivery. Gateway construction failures remain bounded to the optional request.

Chat IDs remain non-secret environment-backed configuration debt and were not moved in H2.

## 16. Cloudflare Credential / Enable Safety

Cloudflare adapter creation is now lazy at export use rather than router import. Packaged mode reads only `secure_settings.cf_api_token` and also requires:

- `app_settings.cloudflare_tracking_enabled` parsed true;
- account ID;
- namespace ID;
- token.

Token presence alone remains mock/safe-disabled. Missing or corrupt configuration does not prevent export; it retains the local fallback link behavior. Source development may use `CF_API_TOKEN`. Account ID, namespace ID, and base URL remain non-secret later-phase configuration debt.

## 17. Packaged vs Dev/Test Credential Sources

| Mode | Secret behavior |
|---|---|
| Packaged | secure store only; no secret environment fallback |
| Source development | explicit/injected value or allowed optional-integration environment adapter |
| Test | deterministic injected store/protector; no host environment unless explicitly patched by the test |

OpenAI is secure-store-only in every normal mode. Optional Pexels, Telegram, and Cloudflare retain source-development environment compatibility only.

## 18. Global vs Tenant DB Boundary

The secure store is initialized only against `RuntimePaths.settings_db_path`. Tenant ORM models, tenant schema evolution, Fingerprint Ledger V2, Reservation tables, and tenant engine initialization contain no `secure_settings` hook. Focused runtime verification confirms a provisioned test tenant does not receive the table.

## 19. Secret-Safe Error / Logging Audit

Secret-store and OpenAI-provider errors are fixed tokens, migration logs contain only enum status, and Cloudflare export fallback logs only exception class names. Tests assert synthetic values are absent from secret-store exception string/repr and Settings API failure responses.

H2-R1 corrected the broader conclusion: Telegram constructs API URLs containing the bot token (`telegram_adapter.py:72-79`), while Telegram/reporting/gateway exception handlers interpolate `str(exc)` into logs (`telegram_adapter.py:188-189`, `reporting.py:132-133`, `routes_gateway.py:158-163`). An `httpx` exception may include its request URL. Therefore end-to-end Telegram error redaction is not source-proven and requires a narrow follow-up; no secret value was read or emitted during the review.

### H2-R2 closure

`TelegramAdapter._post()` now catches the complete `httpx.HTTPError` transport/status hierarchy and raises the fixed `TelegramRequestFailed("TELEGRAM_REQUEST_FAILED")` from `None`. Raw request, response, URL, and chained HTTP exception text cannot cross the adapter boundary. Adapter file-resolution, reporting delivery, and gateway outbound logs now record only fixed text and exception class names rather than `str(exc)`.

The synthetic regression injects an `httpx.ConnectError` whose message and request URL both contain a fake token. It proves the token is absent from the stable exception string, exception repr, formatted traceback, adapter logs, reporting logs, gateway logs, and gateway public response. A mocked successful Telegram request still works, and existing missing-secret, packaged-source, source-development, and optional-failure isolation tests remain green.

The OpenAI conflict regression now creates unequal legacy/secure rows, obtains `MIGRATION_CONFLICT`, clears cache exactly as lifespan does, calls the actual provider loader and `generate_script()`, receives only `LLM_SECRET_UNAVAILABLE`, proves neither credential appears in exception string/repr, and proves `openai.OpenAI` is never constructed.

The plaintext audit found no new secret write to `app_settings`, files, CLI arguments, frontend persistence, or logs. The legacy OpenAI row can remain only in the explicitly preserved conflict/error states.

## 20. Tests Added / Updated

Added `tests/test_var001_dpapi_secret_store.py` with 31 tests covering:

- schema/registry/CRUD/status;
- BLOB storage and raw-SQLite plaintext absence;
- scheme/corruption/error redaction;
- global/tenant boundary;
- all OpenAI migration cases;
- Settings GET/POST and cache invalidation;
- provider secure authority and no OpenAI env fallback;
- packaged/dev optional credential sources;
- Cloudflare explicit enablement;
- Assignment Secret capability;
- real Windows DPAPI.
- Telegram token-bearing transport exception redaction across adapter, reporting, gateway, traceback, and public response;
- OpenAI split-brain rejection through the actual provider loader with no client construction.

Updated `tests/test_matrix_export.py` only for the new lazy tracking-adapter seam.

## 21. Real Windows DPAPI Result

PASS. A synthetic non-production byte value was protected under CurrentUser, ciphertext differed from plaintext, exact bytes were recovered, one-bit corruption failed with `SECRET_DECRYPTION_FAILED`, and an unknown stored scheme failed closed. No synthetic value was printed.

## 22. Focused Test Results

| Suite | Result |
|---|---:|
| H2 focused final | 31/31 PASS |
| H2 + H1 + matrix final affected rerun | 48/48 PASS, 3 subtests PASS |
| Matrix/export isolated | 3/3 PASS |
| H1 focused isolated | 14/14 PASS, 3 subtests PASS |
| Required authority regression aggregate | 378 PASS, 1 skipped, 163 subtests PASS |

The first focused run exposed unclosed Windows SQLite handles because `sqlite3.Connection` transaction contexts do not close the connection. Implementation and fixture helpers were corrected to close after transaction completion; the repeated focused runs then passed without lock residue.

## 23. Full Regression Result

Final command:

```text
.\venv_build\Scripts\python.exe -m pytest tests -q
```

H2-R2 final result: `582 passed, 1 skipped, 217 subtests passed, 0 failures, 0 errors` in `137.99s`. The four-test increase is the bounded R2 coverage. The skip is the existing POSIX-only filesystem case. The 120 warnings are existing deprecation/compatibility warnings and did not fail the run.

## 24. Frontend Validation

`web_ui/package.json` defines `npm run build` as the correct Vite build command. Neither `node` nor `npm` is available in the current environment, so no toolchain was installed or changed:

`FRONTEND_BUILD_TOOLCHAIN_UNAVAILABLE`

Bounded static validation confirms `SettingsView.vue` no longer references `llmMaskedKey`/`masked_key`, reads only `is_configured`, does not persist a returned credential, and remains aligned with the backend response contract.

## 25. Remaining Environment Dependency Audit

- `OPENAI_API_KEY`: no production environment read or fallback.
- `PEXELS_API_KEY`: source-development adapter only; packaged uses secure storage.
- `TELEGRAM_BOT_TOKEN`: source-development adapter only; packaged uses secure storage.
- `CF_API_TOKEN`: source-development adapter only; packaged uses secure storage plus explicit enablement.
- `RESERVATION_ROLLOUT_ASSIGNMENT_SECRET`: deliberately remains the current Reservation environment authority until H3.

Non-secret Cloudflare account/namespace/base URL, Telegram chat IDs, OpenAI base/model, dotenv compatibility, and other H5 configuration debt remain. This report does not claim Production NO-`.env` completion.

## 26. Scope Check

No Reservation, HMAC, Readiness, Rollout, Canary, planner, Task Identity, owner-attempt, execution identity, Historical, Coverage, Fingerprint Ledger, tenant schema, backup, Delivery authority, Seed profile, snapshot, operator command, Tauri resource, build script, version, tag, or dependency declaration was changed.

## 27. Git Diff

Production changes are limited to the global secret store, startup migration hook, OpenAI settings/provider, optional credential consumers, Cloudflare lazy construction, Telegram R2 error boundary, and the existing Settings card. Tests add the focused H2/R2 suite and adjust only the matrix tracking test seam. Documentation preserves the H2 report, historical R1 proof, and R2 closure artifact.

`git diff --check`: PASS; line-ending conversion notices are informational.

Tracked-file `git diff --stat`:

```text
11 files changed, 274 insertions(+), 365 deletions(-)
```

Git does not include the five untracked additions in this statistic: this report, the R1 and R2 evidence artifacts, `src/api/secret_store.py`, and `tests/test_var001_dpapi_secret_store.py`.

## 28. Git Status

```text
 M main.py
 M src/api/routes_gateway.py
 M src/api/routes_matrix.py
 M src/api/settings_router.py
 M src/services/asset_provider.py
 M src/services/llm_provider.py
 M src/services/messaging/adapters/telegram_adapter.py
 M src/services/reporting.py
 M src/services/tracking_adapter.py
 M tests/test_matrix_export.py
 M web_ui/src/views/SettingsView.vue
?? doc/investigations/VAR001_PHASE3D2IB2B2RH2R1_SECRET_AUTHORITY_SOURCE_PROOF.md
?? doc/investigations/VAR001_PHASE3D2IB2B2RH2R2_SECRET_ERROR_CLOSURE.md
?? doc/investigations/VAR001_PHASE3D2IB2B2RH2_DPAPI_SECRET_CREDENTIAL_MIGRATION_IMPLEMENTATION.md
?? src/api/secret_store.py
?? tests/test_var001_dpapi_secret_store.py
```

No `.env`, SQLite DB, tenant DB, output media, Delivery media, backup bundle, real credential, build/installer artifact, dependency file, or secret test artifact is present in the delta.

## 29. Deferred H3-H6 Work

- H3: Philippine Seed profile, atomic applied snapshot, Reservation mapping/Assignment Secret consumer switch.
- H4: packaged operator secret/status/provision/backup commands.
- H5: complete packaged NO-`.env`, Tauri resource removal, Ngrok/network/configuration cleanup.
- H6: isolated release build and artifact security acceptance.

## 30. Final Classification

Proof markers:

- `H2_SECURE_SETTINGS_GLOBAL_ONLY_PROVEN = PASS`
- `H2_DPAPI_CURRENT_USER_PROVEN = PASS`
- `H2_NO_PLAINTEXT_SECRET_AT_REST_PROVEN = PASS`
- `H2_SECRET_ERROR_REDACTION_PROVEN = PASS`
- `H2_OPENAI_LEGACY_MIGRATION_PROVEN = PASS`
- `H2_OPENAI_SECURE_AUTHORITY_PROVEN = PASS`
- `H2_OPENAI_GET_NO_SECRET_DERIVATIVE_PROVEN = PASS`
- `H2_OPENAI_CACHE_INVALIDATION_PRESERVED = PASS`
- `H2_PEXELS_PACKAGED_SECURE_SOURCE_PROVEN = PASS`
- `H2_TELEGRAM_PACKAGED_SECURE_SOURCE_PROVEN = PASS`
- `H2_CLOUDFLARE_PACKAGED_SECURE_SOURCE_PROVEN = PASS`
- `H2_CLOUDFLARE_EXPLICIT_ENABLE_PROVEN = PASS`
- `H2_OPTIONAL_SECRET_FAILURE_ISOLATED = PASS`
- `H2_ASSIGNMENT_SECRET_STORAGE_READY_NOT_WIRED = PASS`
- `H2_RESERVATION_AUTHORITY_UNCHANGED = PASS`
- `H2_H1_RUNTIME_PATH_AUTHORITY_PRESERVED = PASS`
- `H2_NO_SEED_PROFILE_IMPLEMENTED_EARLY = PASS`
- `H2_PRODUCTION_NO_ENV_NOT_FALSELY_CLAIMED = PASS`

`VAR001_PHASE3D2IB2B2RH2_DPAPI_SECRET_MIGRATION_PASS`
