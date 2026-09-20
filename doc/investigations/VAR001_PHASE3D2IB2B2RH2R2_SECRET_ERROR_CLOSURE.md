# VAR-001 Phase 3D-2I-B-2B-2R-H2-R2
# Telegram Secret-Safe Error Closure and OpenAI Provider Conflict Regression Closure

## 1. Executive Result

H2-R2 closed both narrow findings from H2-R1 without changing secret-store architecture, OpenAI conflict semantics, packaged credential authority, Reservation, or later-phase behavior.

- Telegram token-bearing `httpx` exceptions are converted at the adapter boundary into fixed `TELEGRAM_REQUEST_FAILED` errors with suppressed chained context.
- Telegram adapter, reporting, and gateway outbound logging no longer formats exception text that could contain a tokenized URL.
- A synthetic token-bearing transport exception is absent from exception string, repr, formatted traceback, all affected logs, and the gateway public response.
- OpenAI unequal legacy/secure state is now exercised through the actual provider loader and provider use; it fails with `LLM_SECRET_UNAVAILABLE` before `openai.OpenAI` construction.
- Focused, affected, H1, static, and full pytest gates pass.

`VAR001_PHASE3D2IB2B2RH2R2_SECRET_ERROR_CLOSURE_PASS`

## 2. H2-R1 Findings

H2-R1 preserved the proven H2 authority conclusions and identified:

- F-01: `CONFLICT_PROVIDER_TEST_GAP` — the authority helper was tested directly, but the provider loader and client-construction boundary were not.
- F-02: `TELEGRAM_EXCEPTION_URL_LOGGING_FOLLOWUP_REQUIRED` — Telegram puts the bot token in request URLs, and raw exception text could reach adapter/reporting/gateway logs.

The historical R1 artifact remains unchanged. R2 changes only the bounded Telegram error path, focused tests, the H2 implementation report, and this closure report.

## 3. Telegram Tokenized-URL Risk

Telegram API URLs necessarily have the form:

```text
https://api.telegram.org/bot<TOKEN>/<METHOD>
```

`httpx.RequestError` and `httpx.HTTPStatusError` may retain the request/response and render the request URL in their text or traceback. Therefore raw `httpx.HTTPError` objects are treated as secret-bearing even if the immediate error message does not visibly contain the token.

The prior `_post()` allowed errors from `client.post()` to escape. Upstream `str(exc)` logging could then expose the tokenized URL.

## 4. Telegram Error Boundary Correction

`src/services/messaging/adapters/telegram_adapter.py` now defines a stable `TelegramRequestFailed` error with exactly:

```text
TELEGRAM_REQUEST_FAILED
```

`_post()` encloses both request execution and `response.raise_for_status()`:

```python
try:
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
except httpx.HTTPError:
    raise TelegramRequestFailed() from None
```

This covers the `httpx` transport/status hierarchy used by the request and prevents the raw request, response, URL, and normal traceback context from escaping. It does not catch unrelated programming errors.

Successful response parsing and the existing Telegram application-level `ok` contract remain unchanged.

## 5. Upstream Logging Correction

Three source boundaries were hardened:

- Telegram file-resolution warning logs only `type(exc).__name__`.
- `NotificationRouter.dispatch()` logs fixed delivery context and `type(exc).__name__`.
- Gateway outbound delivery logs fixed mode/platform/chat context and `type(exc).__name__`.

The gateway still acknowledges optional outbound failure without exposing error text in its public response. Missing/corrupt Telegram configuration remains isolated to the optional integration.

## 6. Telegram Redaction Regression

The focused suite creates a synthetic token, embeds it in the exact Telegram request URL, and injects an `httpx.ConnectError` whose own message also contains that URL.

Assertions prove the synthetic token is absent from:

- `str(TelegramRequestFailed)`;
- `repr(TelegramRequestFailed)`;
- the formatted exception traceback;
- adapter warning/error logs;
- reporting logs even when an injected adapter raises token-bearing text;
- gateway outbound logs even when an injected adapter raises token-bearing text;
- the gateway HTTP response.

The test also proves `__suppress_context__` is true. No Telegram network request is made.

A separate mocked-200 test proves the normal Telegram success path remains functional. Existing tests retain missing-secret isolation, packaged secure-store selection, and source-development compatibility.

## 7. OpenAI Provider Conflict Regression

The new regression:

1. writes synthetic secure value B;
2. writes a different synthetic legacy value A;
3. runs migration and receives `MIGRATION_CONFLICT`;
4. invalidates the provider cache with the same key used by lifespan;
5. calls `_load_api_key_from_db()`;
6. calls `OpenAIProvider.generate_script()`;
7. receives only `LLM_SECRET_UNAVAILABLE` from both provider-level paths;
8. proves neither A nor B appears in exception string or repr.

The test preserves both rows and does not modify the proven migration algorithm.

`H2R2_OPENAI_CONFLICT_PROVIDER_REGRESSION_PROVEN = PASS`

## 8. Client Construction Proof

The regression patches `llm_provider.openai.OpenAI` and asserts it is never called. The conflict is rejected by `read_openai_secret_for_use()` through `_load_api_key_from_db()` before any client receives secure value B.

No OpenAI network request is made.

`H2R2_OPENAI_CONFLICT_NO_CLIENT_CONSTRUCTION_PROVEN = PASS`

## 9. Secret-Safe Source Search

Post-fix searches covered `str(exc)`, `repr(exc)`, logger/exception interpolation, `request.url`, `_TG_API_BASE`, bot-token formatting, `api_key`, and `token` across changed H2/Telegram paths.

Classifications:

- `_TG_API_BASE` and file-download URL formatting remain necessary internal Telegram protocol construction; neither is logged by the corrected paths.
- Telegram outbound HTTP errors are caught before leaving `_post()`.
- Telegram file-resolution, reporting, and gateway outbound logging use exception class names only.
- Remaining gateway `str(exc)` sites concern inbound JSON decoding, stable adapter-construction errors, inbound payload parsing, or dispatcher execution; the tokenized outbound Telegram HTTP exception cannot reach them.
- Settings Delivery Root `str(exc)` is unrelated non-secret validation.
- OpenAI keys remain process-memory inputs to the provider and are not formatted or logged.

No unresolved Telegram token-bearing exception logging/public-response path remains.

## 10. Focused Test Results

| Test command/suite | Result |
|---|---:|
| `pytest tests/test_var001_dpapi_secret_store.py -q` | 31 passed, 2 warnings |
| H2 + matrix/export + H1 combined | 48 passed, 3 subtests passed, 2 warnings |
| `pytest tests/test_matrix_export.py -q` | 3 passed, 1 warning |
| `pytest tests/test_var001_runtime_paths_bootstrap.py -q` | 14 passed, 3 subtests passed |
| `py_compile` for every changed/new Python module | PASS |

The H2 focused baseline increased from 27 to 31 tests: one OpenAI provider-conflict regression and three Telegram error/success/upstream-boundary regressions.

## 11. Full Regression Result

Command:

```text
.\venv_build\Scripts\python.exe -m pytest tests -q
```

Result:

```text
582 passed, 1 skipped, 217 subtests passed, 120 warnings
0 failures, 0 errors
137.99s
```

The skip and warnings are the existing platform/deprecation/compatibility results. No R2 regression was observed.

## 12. Scope Check

R2 production changes are limited to:

- `src/services/messaging/adapters/telegram_adapter.py`;
- `src/services/reporting.py`;
- `src/api/routes_gateway.py`.

R2 test changes are limited to `tests/test_var001_dpapi_secret_store.py`. Documentation changes are this artifact and the required H2 report closure update.

No change was made to DPAPI, `secure_settings`, OpenAI migration semantics, packaged source selection, Pexels, Cloudflare authority, Reservation, Assignment Secret authority, Seed profile, Readiness, Rollout, HMAC, Canary, RuntimePaths, Tauri, `.env`, Ngrok, build scripts, version, or tag.

## 13. Git Diff

Final `git diff --check`: PASS. LF-to-CRLF notices are informational only.

Tracked-file `git diff --stat`:

```text
11 files changed, 274 insertions(+), 365 deletions(-)
```

This statistic covers the complete tracked H2/R2 delta and excludes the five untracked additions listed below.

## 14. Git Status

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

No `.env`, SQLite DB, tenant DB, output, backup, real credential, secret artifact, or build/installer artifact appears in the delta.

## 15. Final Classification

- `H2R2_TELEGRAM_HTTP_EXCEPTION_SANITIZED = PASS`
- `H2R2_TELEGRAM_TOKEN_NOT_IN_EXCEPTION_STRING = PASS`
- `H2R2_TELEGRAM_TOKEN_NOT_IN_EXCEPTION_REPR = PASS`
- `H2R2_TELEGRAM_TOKEN_NOT_IN_LOGS = PASS`
- `H2R2_TELEGRAM_PUBLIC_ERROR_REDACTED = PASS`
- `H2R2_TELEGRAM_OPTIONAL_FAILURE_ISOLATED = PASS`
- `H2R2_OPENAI_CONFLICT_PROVIDER_REGRESSION_PROVEN = PASS`
- `H2R2_OPENAI_CONFLICT_NO_CLIENT_CONSTRUCTION_PROVEN = PASS`
- `H2R2_OPENAI_CONFLICT_NO_SECRET_OUTPUT_PROVEN = PASS`
- `H2R2_PACKAGED_SECRET_AUTHORITIES_UNCHANGED = PASS`
- `H2R2_RESERVATION_AUTHORITY_UNCHANGED = PASS`
- `H2R2_NO_H3_H6_SCOPE_CREEP = PASS`

H2 final classification restored after all gates passed:

`VAR001_PHASE3D2IB2B2RH2_DPAPI_SECRET_MIGRATION_PASS`

R2 final classification:

`VAR001_PHASE3D2IB2B2RH2R2_SECRET_ERROR_CLOSURE_PASS`
