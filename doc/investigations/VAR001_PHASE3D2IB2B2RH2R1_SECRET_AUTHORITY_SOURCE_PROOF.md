# VAR-001 Phase 3D-2I-B-2B-2R-H2-R1
# H2 Secret Authority Narrow Source Proof

## 1. Executive Result

The three requested authority questions were traced from current source without executing migrations or reading credentials:

- OpenAI startup conflict is fail-closed for later provider use. The provider does not depend on an in-memory migration flag: after the startup cache invalidation, its authoritative database read independently rejects any remaining legacy row.
- Legacy-only migration and explicit Settings replacement each perform secure write, same-connection decrypt verification, legacy deletion, and commit as one bounded SQLite transaction.
- Production packaged Pexels, Telegram, and Cloudflare construction cannot fall back to the corresponding process-environment secret. Environment compatibility exists only in the explicit `SOURCE_DEVELOPMENT` branch.

Two narrow follow-ups remain before H2 commit:

1. The conflict test exercises `read_openai_secret_for_use()` directly, but does not call the actual provider loader after a conflict: `CONFLICT_PROVIDER_TEST_GAP`.
2. Telegram embeds the bot token in its HTTP URL while three exception handlers log `str(exc)`. An `httpx` exception can include its request URL, so end-to-end Telegram error redaction is not source-proven: `TELEGRAM_EXCEPTION_URL_LOGGING_FOLLOWUP_REQUIRED`.

Final classification:

`VAR001_PHASE3D2IB2B2RH2R1_NARROW_FOLLOWUP_REQUIRED`

## 2. Repository / H2 Worktree Baseline

| Fact | Value |
|---|---|
| Branch | `feature/var-001-variation-policy` |
| HEAD | `e7bf00301e60f563f1b8deeb227b23145a109664` |
| HEAD subject | `e7bf003 feat(v1.5): establish runtime path and bootstrap foundation` |
| H2 state | Intentionally uncommitted |
| Initial `git diff --check` | PASS; informational LF-to-CRLF notices only |

The pre-existing H2 production, test, frontend, and implementation-report delta was preserved. No database, `.env`, credential, output, backup, or build artifact was opened or changed.

## 3. OpenAI Conflict Startup Path

Startup calls the migration only from FastAPI lifespan. `main.py:102-114`:

```python
initialize_application_schema(engine)
secret_migration = initialize_secret_storage()
invalidate_api_key_cache("openai_api_key")
if secret_migration in {
    OpenAISecretMigrationResult.ERROR,
    OpenAISecretMigrationResult.MIGRATION_CONFLICT,
}:
    logger.warning(
        "[SecretStore] OpenAI credential state=%s",
        secret_migration.value,
    )
```

`initialize_secret_storage()` selects the global RuntimePaths store and invokes the migration (`src/api/secret_store.py:487-494`):

```python
store = get_default_secret_store()
store.ensure_schema()
return migrate_legacy_openai_secret(store)
```

The conflicting values are compared at `src/api/secret_store.py:385-407`:

```python
with closing(store._connect()) as conn, conn:
    _create_app_settings_table(conn)
    _create_secure_settings_table(conn)
    legacy_value = _legacy_openai_value(conn)
    secure_row = store._read_row(conn, OPENAI_API_KEY)
    ...
    if secure_row is not None:
        secure_value = store._decrypt_row(secure_row)
        ...
        if secure_value != legacy_value:
            return OpenAISecretMigrationResult.MIGRATION_CONFLICT
```

Answers:

- Q1: `migrate_legacy_openai_secret()` detects the unequal legacy/secure values; `initialize_secret_storage()` returns the result to lifespan.
- Q2: both rows remain unchanged. The conflict branch performs no row write or deletion. Context exit closes the transaction normally, preserving `LEGACY_A` and `SECURE_B`.
- Startup does not persist a separate conflict flag. It logs only the enum and invalidates the provider cache.

## 4. OpenAI Conflict Provider Path

The request-time path is `OpenAIProvider.generate_script()` → `_load_api_key_from_db()` → `read_openai_secret_for_use()`.

`src/services/llm_provider.py:24-35`:

```python
def _load_api_key_from_db(setting_key: str = "openai_api_key") -> str:
    if setting_key in _api_key_cache:
        return _api_key_cache[setting_key]
    ...
    try:
        result = read_openai_secret_for_use(get_default_secret_store()) or ""
    except (SecretStoreError, OSError) as exc:
        raise ValueError("LLM_SECRET_UNAVAILABLE") from exc
    _api_key_cache[setting_key] = result
    return result
```

`src/services/llm_provider.py:75-86` uses that loader before creating the OpenAI client:

```python
api_key = _load_api_key_from_db("openai_api_key")
if not api_key:
    raise ValueError("LLM_SECRET_NOT_CONFIGURED")
client = openai.OpenAI(api_key=api_key, base_url=self._base_url)
```

The database authority check is independent of the migration return value. `src/api/secret_store.py:449-463`:

```python
with closing(store._connect()) as conn, conn:
    _create_app_settings_table(conn)
    _create_secure_settings_table(conn)
    secure_row = store._read_row(conn, OPENAI_API_KEY)
    if secure_row is None:
        if _legacy_openai_value(conn) is not None:
            raise OpenAISecretMigrationConflict()
        return None
    secure_value = store._decrypt_row(secure_row)
    if _legacy_openai_value(conn) is not None:
        raise OpenAISecretMigrationConflict()
    return secure_value
```

Answers:

- Q3: `_load_api_key_from_db()` loads the credential, and `generate_script()` calls it immediately before client construction.
- Q4: yes. `read_openai_secret_for_use()` independently queries both tables and rejects the presence of any legacy OpenAI row while secure authority exists.
- Q5: no startup conflict state must be propagated. The persistent split-brain rows are the fail-closed signal. Lifespan additionally clears any pre-existing provider cache at `main.py:107`.
- Q6: in the stated startup-conflict scenario, no. Cache invalidation happens after migration returns, the first later provider load reaches the database check, and `OpenAISecretMigrationConflict` becomes stable `LLM_SECRET_UNAVAILABLE` before client construction.

Bounded caveat: the cache lookup at `llm_provider.py:26-27` intentionally avoids repeated DB reads. Unsupported out-of-band mutation of the SQLite tables after a successful credential has already been cached would not be observed until cache invalidation/restart. Supported startup and Settings replacement paths both invalidate the cache.

`OPENAI_CONFLICT_PROVIDER_FAIL_CLOSED_PROVEN`

## 5. Conflict Test Coverage

`tests/test_var001_dpapi_secret_store.py:246-256` verifies:

```python
self.assertEqual(
    migrate_legacy_openai_secret(self.store),
    OpenAISecretMigrationResult.MIGRATION_CONFLICT,
)
self.assertEqual(self.store.get_secret(OPENAI_API_KEY), "synthetic-secure")
self.assertEqual(legacy_value(self.db_path), "synthetic-legacy")
with self.assertRaises(OpenAISecretMigrationConflict):
    read_openai_secret_for_use(self.store)
```

This proves preservation plus the authoritative read helper's fail-closed result. It does not patch the provider's default store and call `_load_api_key_from_db()` or `OpenAIProvider.generate_script()` after the conflict; it also does not exercise the lifespan cache invalidation in this scenario.

`CONFLICT_PROVIDER_TEST_GAP`

The gap does not negate the source proof in Section 4, but it is a missing direct provider regression before commit.

## 6. Legacy Migration Transaction Boundary

The legacy-only path uses one connection created at `src/api/secret_store.py:388`. It does not call public `set_secret()` or `get_secret()`, both of which would open their own connections. Instead it passes the caller-owned connection to internal helpers:

```python
with closing(store._connect()) as conn, conn:
    ...
    store._set_on_connection(conn, OPENAI_API_KEY, legacy_value)
    conn.execute(
        "DELETE FROM app_settings WHERE key_name = ?;",
        (LEGACY_OPENAI_SETTING_KEY,),
    )
    return OpenAISecretMigrationResult.MIGRATED
```

`src/api/secret_store.py:300-331` performs protect, insert, same-connection read, and decrypt verification:

```python
ciphertext = self._protector.protect(value.encode("utf-8"))
conn.execute(
    "INSERT OR REPLACE INTO secure_settings "
    "(key_name, encryption_scheme, ciphertext, updated_at) "
    "VALUES (?, ?, ?, ?);",
    (...),
)
persisted = self._read_row(conn, key_name)
if persisted is None or self._decrypt_row(persisted) != value:
    raise SecretValueCorrupt()
```

The nested context order is significant: `conn` performs commit on normal exit or rollback on exceptional exit, then `closing(...)` closes it. A return from inside the block still runs both context exits.

Answers:

- Q1: yes, exactly one SQLite connection contains the claimed migration mutations.
- Q2: no; `_set_on_connection`, `_read_row`, and `_decrypt_row` do not connect.
- Q3: the explicit `conn` argument on `_set_on_connection()` and `_read_row()` is the caller-owned-connection mechanism.
- Q4: no. Deletion follows verified insertion on the same transaction and cannot commit independently.
- Q5: no. A delete failure exits exceptionally and rolls back the prior insert. Protect/insert/verification failure occurs before deletion and also rolls back.

`initialize_secret_storage()` does separately ensure the schema first; table creation is not claimed to be part of the credential-row migration transaction. Credential-row insertion/verification/deletion is one bounded transaction.

`OPENAI_MIGRATION_SINGLE_TRANSACTION_PROVEN`

## 7. Settings POST Transaction Boundary

The route calls `replace_openai_secret()` and invalidates cache only after that function returns. `src/api/settings_router.py:74-85`:

```python
try:
    replace_openai_secret(get_default_secret_store(), payload.api_key)
except (SecretStoreError, sqlite3.Error, OSError) as exc:
    raise HTTPException(..., detail="LLM_SECRET_SAVE_FAILED") from exc

invalidate_api_key_cache(_KEY_OPENAI)
return {"status": "ok"}
```

`src/api/secret_store.py:470-484` performs secure replacement, decrypt verification through `_set_on_connection()`, and legacy deletion on one connection:

```python
with closing(store._connect()) as conn, conn:
    _create_app_settings_table(conn)
    _create_secure_settings_table(conn)
    store._set_on_connection(conn, OPENAI_API_KEY, value)
    conn.execute(
        "DELETE FROM app_settings WHERE key_name = ?;",
        (LEGACY_OPENAI_SETTING_KEY,),
    )
```

The function returns only after context exit commits and closes. If protect, INSERT, decrypt verification, or DELETE fails, context exit rolls back the DB authority changes. Cache invalidation is deliberately after commit; it is an in-process cache action, not part of SQLite authority.

`OPENAI_POST_TRANSACTION_PROVEN`

## 8. Pexels Packaged Secret Source

Mode selection is not environment-controlled: `src/api/runtime_paths.py:58-61` maps `sys.frozen` to `PACKAGED`, otherwise `SOURCE_DEVELOPMENT`.

The centralized selector at `src/api/secret_store.py:497-517` reads an environment variable only inside the exact development branch:

```python
paths = get_runtime_paths()
if paths.mode is RuntimeMode.SOURCE_DEVELOPMENT:
    return (
        os.environ.get(development_environment_key)
        if development_environment_key
        else None
    )
active_store = store or get_default_secret_store()
return active_store.get_secret(key_name)
```

`PexelsProvider` calls it with the development key at `src/services/asset_provider.py:128-136`. The production construction at `src/nodes/asset_select.py:532-535` passes only `output_dir`, not a key:

```python
if provider is None:
    provider = PexelsProvider(output_dir=self._output_dir)
```

Therefore packaged production resolution reaches `secure_settings.pexels_api_key`; the named environment key is unreachable in packaged mode. Constructor key injection remains an explicit internal/test seam, not environment fallback.

`PEXELS_PACKAGED_NO_ENV_FALLBACK_PROVEN`

## 9. Telegram Packaged Secret Source

`TelegramAdapter` uses the same centralized selector (`src/services/messaging/adapters/telegram_adapter.py:58-67`):

```python
self._token = bot_token or load_runtime_secret(
    TELEGRAM_BOT_TOKEN,
    development_environment_key="TELEGRAM_BOT_TOKEN",
) or ""
```

Production construction does not inject a token:

- `src/services/reporting.py:56-62`: `self.adapter = TelegramAdapter()`.
- `src/services/messaging/adapters/__init__.py:14-18`: the gateway registry stores the class.
- `src/api/routes_gateway.py:103-108`: the gateway calls `adapter_class()` with no arguments.

Consequently packaged production resolution reaches `secure_settings.telegram_bot_token`, not `os.getenv`/`os.environ`. Explicit constructor injection remains a deliberate internal/test seam.

`TELEGRAM_PACKAGED_NO_ENV_FALLBACK_PROVEN`

## 10. Cloudflare Packaged Secret Source

The packaged branch is explicit at `src/services/tracking_adapter.py:58-88`:

```python
mode = get_runtime_paths().mode
...
if mode is RuntimeMode.PACKAGED:
    self._enabled = _is_enabled(
        _read_machine_setting(_ENABLE_SETTING) if enabled is None else enabled
    )
    try:
        self._api_token = api_token or (
            load_runtime_secret(CF_API_TOKEN) if self._enabled else None
        )
    except (SecretStoreError, OSError):
        self._api_token = None
elif mode is RuntimeMode.SOURCE_DEVELOPMENT:
    self._api_token = api_token or load_runtime_secret(
        CF_API_TOKEN,
        development_environment_key="CF_API_TOKEN",
    )
```

The only production factory, `src/api/routes_matrix.py:56-59`, calls `CloudflareKVAdapter()` without an injected token. Thus packaged production cannot reach the development environment adapter for `CF_API_TOKEN`. `CF_ACCOUNT_ID`, `CF_NAMESPACE_ID`, and `SHORT_LINK_BASE_URL` remain non-secret configuration and are outside the token-source assertion.

`CLOUDFLARE_PACKAGED_NO_ENV_FALLBACK_PROVEN`

## 11. Cloudflare Explicit Enablement

In packaged mode, the enable bit comes from global non-secret `app_settings.cloudflare_tracking_enabled` unless explicitly injected. The adapter computes real-write eligibility at `src/services/tracking_adapter.py:90-95`:

```python
self._mock_mode = not bool(
    self._enabled
    and self._api_token
    and self._account_id
    and self._namespace_id
)
```

Token presence alone therefore cannot activate real writes. All four elements must be truthy: explicit enable, token, account, and namespace.

When disabled or missing configuration, `generate_short_link()` returns a local generated link without calling Cloudflare (`tracking_adapter.py:99-109`). A secure-store read error is caught and produces `_api_token = None` (`tracking_adapter.py:69-74`), which also selects mock mode. If an enabled real write later fails, `_generate_resilient_short_link()` catches it and returns a fallback (`src/api/routes_matrix.py:259-268`):

```python
try:
    return adapter.generate_short_link(long_url, asset_hash or "")
except Exception as exc:
    logger.warning(
        "[Delivery Hub] short-link fallback error=%s",
        type(exc).__name__,
    )
    return _fallback_short_link(asset_hash, adapter)
```

Thus missing/error paths remain local/mock and do not prevent export.

`CLOUDFLARE_EXPLICIT_ENABLE_SOURCE_PROVEN`

## 12. Secret-Safe Source Audit

Source-safe areas:

- `SecretStoreError` subclasses expose fixed codes only (`secret_store.py:59-100`).
- DPAPI and SQLite failures are chained behind fixed public messages; plaintext and ciphertext are not formatted (`secret_store.py:273-287`, `300-331`).
- Settings POST emits only `LLM_SECRET_SAVE_FAILED` (`settings_router.py:76-82`).
- OpenAI provider errors are stable and do not echo SDK exception text (`llm_provider.py:98-108`).
- Cloudflare write logging emits only variant prefix and exception class (`tracking_adapter.py:130-136`, `routes_matrix.py:263-267`).
- Searches found no masked secret prefix/suffix API output and no ciphertext formatting.

Bounded finding:

`TelegramAdapter._api_url()` embeds the secret in the URL (`telegram_adapter.py:72-79`):

```python
def _api_url(self, method: str) -> str:
    return _TG_API_BASE.format(token=self._token, method=method)
...
resp = await client.post(url, json=payload)
```

Network exceptions are not sanitized inside `_post()`. They can flow to handlers that log their string form:

- `telegram_adapter.py:188-189`: `logger.warning(... {exc})`
- `reporting.py:132-133`: `logger.error(... {exc})`
- `routes_gateway.py:158-163`: `logger.error(... {exc})`

Because an `httpx` exception may include the request URL, these paths can disclose the bot token. No credential was read and no network call was made during this audit.

`H2_SECRET_SAFE_SOURCE_AUDIT_FAIL — TELEGRAM_EXCEPTION_URL_LOGGING_FOLLOWUP_REQUIRED`

## 13. Findings Requiring Correction

### H2R1-F-01 — Conflict provider regression gap

Source proves provider fail-closed behavior, but the focused conflict test stops at the authority helper. Add a narrow test that:

1. creates unequal legacy and secure rows;
2. runs migration and verifies `MIGRATION_CONFLICT`;
3. invalidates the provider cache as lifespan does;
4. calls `_load_api_key_from_db()` (or provider construction/use at the existing seam);
5. proves stable `LLM_SECRET_UNAVAILABLE` and no OpenAI client construction.

### H2R1-F-02 — Telegram tokenized-URL exception logging

Sanitize exceptions at the Telegram adapter boundary so callers receive a fixed error that cannot contain the tokenized request URL. Logging in adapter/reporting/gateway must use fixed error codes or exception class names, not `str(exc)` from token-bearing HTTP operations. Add a synthetic test whose exception text contains the tokenized URL and prove logs/public responses exclude the token.

This is a secret-safe error-path defect, not a secure-store, transaction, packaged-source, Reservation, or rollout-authority defect.

## 14. Scope Check

The review did not modify production source, tests, databases, `.env`, process environment, credentials, services, output, backups, build artifacts, Reservation, rollout, or H3-H6 behavior. The only corrections are this evidence artifact and a factual qualification in the existing H2 implementation report.

No tests were run, as required by the read-only source-review scope.

## 15. Git Status

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
?? doc/investigations/VAR001_PHASE3D2IB2B2RH2_DPAPI_SECRET_CREDENTIAL_MIGRATION_IMPLEMENTATION.md
?? src/api/secret_store.py
?? tests/test_var001_dpapi_secret_store.py
```

The new R1 document and the factual correction inside the existing untracked H2 report are the only R1 documentation changes; all pre-existing H2 implementation/test changes remain preserved. No production or test source was changed by R1.

## 16. Final Classification

Authority/transaction proofs:

- `OPENAI_CONFLICT_PROVIDER_FAIL_CLOSED_PROVEN`
- `OPENAI_MIGRATION_SINGLE_TRANSACTION_PROVEN`
- `OPENAI_POST_TRANSACTION_PROVEN`
- `PEXELS_PACKAGED_NO_ENV_FALLBACK_PROVEN`
- `TELEGRAM_PACKAGED_NO_ENV_FALLBACK_PROVEN`
- `CLOUDFLARE_PACKAGED_NO_ENV_FALLBACK_PROVEN`
- `CLOUDFLARE_EXPLICIT_ENABLE_SOURCE_PROVEN`

Follow-up findings:

- `CONFLICT_PROVIDER_TEST_GAP`
- `H2_SECRET_SAFE_SOURCE_AUDIT_FAIL — TELEGRAM_EXCEPTION_URL_LOGGING_FOLLOWUP_REQUIRED`

`VAR001_PHASE3D2IB2B2RH2R1_NARROW_FOLLOWUP_REQUIRED`
