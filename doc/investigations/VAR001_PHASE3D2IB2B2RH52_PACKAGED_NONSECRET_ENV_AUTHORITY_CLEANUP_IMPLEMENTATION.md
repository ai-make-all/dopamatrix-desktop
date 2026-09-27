# VAR-001 Phase 3D-2I-B-2B-2R-H5-2 Packaged Non-Secret Environment Authority Cleanup

## 1. Executive Result

H5-2 removed packaged-production process-environment authority for the nine frozen non-secret legacy keys without introducing a replacement configuration authority. Source-development compatibility remains explicit and H5-1/H4 behavior remains unchanged.

Implementation classification:

`VAR001_PHASE3D2IB2B2RH52_PACKAGED_NONSECRET_ENV_AUTHORITY_CLEANUP_IMPLEMENTATION_PASS`

This is implementation evidence for independent ChatGPT review, not an independent-review FINAL PASS.

## 2. Baseline and Authority

- Branch: `feature/var-001-variation-policy`
- HEAD: `a294b7f84ce6ac9987d01a3eb4eb5433ebe2449e`
- Origin: `a294b7f84ce6ac9987d01a3eb4eb5433ebe2449e`
- Immutable RC1: `5f534b180dd2ae9fa9212e6632a44746669d7e6f`
- Initial tracked worktree: clean
- Initial index: empty
- H5-R0 authority gate: `VAR001_PHASE3D2IB2B2RH5R0_NO_ENV_NETWORK_CONFIG_AUTHORITY_RECONNAISSANCE_PASS`
- H5-1 final gate: `VAR001_PHASE3D2IB2B2RH51_PACKAGED_NO_ENV_NETWORK_BOOTSTRAP_FINAL_PASS`
- H5-1 post-push gate: `VAR001_PHASE3D2IB2B2RH51_PACKAGED_NO_ENV_NETWORK_BOOTSTRAP_POST_PUSH_FINAL_PASS`

## 3. Exact Nine-Key Inventory

1. `LLM_COST_PER_TOKEN`
2. `TTS_COST_PER_SEC`
3. `OPENAI_BASE_URL`
4. `LLM_MODEL`
5. `INTERNAL_OPS_CHAT_ID`
6. `CLIENT_REPORTING_CHAT_ID`
7. `SHORT_LINK_BASE_URL`
8. `CF_ACCOUNT_ID`
9. `CF_NAMESPACE_ID`

No other environment authority was changed.

## 4. Production Changes

### 4.1 Cost rates

`src/api/services.py` now resolves import-time cost constants through `_resolve_cost_rates()`.

- Packaged/frozen ignores both cost environment values.
- Packaged defaults are exactly `0.000002` per LLM token and `0.000016` per TTS second.
- Source development retains the prior environment override adapter.
- No DB setting or new authority was added.

### 4.2 LLM endpoint and model

`src/services/llm_provider.py` now uses `_resolve_openai_base_url()` and `_resolve_llm_model()`.

- Existing explicit constructor arguments remain first authority.
- Packaged/frozen ignores `OPENAI_BASE_URL`; absence of an explicit value keeps SDK-default/no-override behavior (`None`).
- Packaged/frozen ignores `LLM_MODEL`; absence of an explicit value uses `gpt-4o-mini`.
- Source development retains both environment conveniences.
- OpenAI API-key loading and DPAPI/SecretStore behavior were not changed.

### 4.3 Reporting destinations

`src/services/reporting.py` now resolves chat destinations through `_resolve_reporting_chat_ids()`.

- Packaged/frozen ignores both chat-ID environment values and retains empty/disabled routing.
- Source development retains both environment conveniences.
- The no-destination log message is bounded and no longer directs packaged operators to environment configuration.
- Telegram token authority and error redaction were not changed.

### 4.4 Tracking adapter

`src/services/tracking_adapter.py` now resolves non-secret link/KV fields after reading the existing `RuntimeMode`.

- Explicit constructor arguments remain first authority.
- Packaged/frozen ignores all three tracking environment values.
- Packaged default short-link base remains `https://dopa.mx/t/`.
- Packaged account and namespace remain absent when not explicitly supplied.
- Existing `cloudflare_tracking_enabled` machine-setting behavior is unchanged.
- Cloudflare API token still loads from the existing SecretStore path in packaged mode.
- Source development retains the historical environment conveniences.

## 5. No New Authority

The change adds no:

- app_settings key;
- DB table or schema migration;
- operational snapshot field;
- SecretStore key;
- environment mode switch;
- configuration API;
- operator command.

DPAPI CurrentUser and all secret authorities are unchanged.

## 6. Focused Test Coverage

New module: `tests/test_var001_h5_nonsecret_env_authority.py`.

It proves:

- clean subprocess import under `sys.frozen=True` ignores cost env values;
- clean subprocess import in source development preserves cost env values;
- packaged LLM endpoint/model env values are ignored;
- LLM explicit constructor arguments win;
- packaged default model is `gpt-4o-mini`;
- packaged reporting chat IDs stay absent;
- packaged tracking ignores base/account/namespace env values;
- packaged tracking preserves explicit arguments;
- packaged Cloudflare enablement is still read from `cloudflare_tracking_enabled`;
- packaged Cloudflare token uses `load_runtime_secret(CF_API_TOKEN)` rather than env;
- source-development conveniences remain for all nine keys.

Command:

```text
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_h5_nonsecret_env_authority.py -q
```

Result:

```text
9 passed, 1 warning, 0 failures/errors
```

## 7. H5-1 Regression

Command:

```text
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_h5_no_env_network_bootstrap.py -q
```

Result:

```text
6 passed, 1 warning, 0 failures/errors
```

Packaged no-dotenv, Tauri no-`.env` resource, packaged Ngrok-off, packaged `PUBLIC_BASE_URL` isolation, and local `127.0.0.1:8000` authority remain intact.

## 8. Relevant Regression

Final command used a fresh external basetemp and included the new H5-2 module, H5-1, the required DPAPI/Seed/RuntimePaths/mutation/operator suites, and direct consumers `test_var001_clean_task_identity.py` and `test_matrix_export.py`.

Result:

```text
178 passed, 97 subtests passed, 4 warnings, 0 failures/errors
```

## 9. Full Backend Regression

Command:

```text
.\venv_build\Scripts\python.exe -m pytest tests -q --basetemp <fresh-external-temp>
```

Final result after the last production edit:

```text
777 passed, 2 skipped, 580 subtests passed, 120 warnings
0 failures, 0 errors
```

## 10. Static Validation

`py_compile` covered all four changed production modules and the new test module.

```text
py-compile-exit=0
git diff --check: exit 0
```

The LF-to-CRLF messages emitted by Git were informational; `git diff --check` returned zero.

## 11. Final Nine-Key Source Scan

Every remaining occurrence was classified as follows:

| Key(s) | Production occurrence classification | Test occurrence classification |
|---|---|---|
| `LLM_COST_PER_TOKEN`, `TTS_COST_PER_SEC` | `SOURCE_DEVELOPMENT_ONLY` reader after packaged early return; fixed default constants are not env authority | `TEST_ONLY` synthetic values |
| `OPENAI_BASE_URL`, `LLM_MODEL` | `SOURCE_DEVELOPMENT_ONLY` reader after packaged early return; default-model constant is fixed packaged authority | `TEST_ONLY` synthetic values |
| `INTERNAL_OPS_CHAT_ID`, `CLIENT_REPORTING_CHAT_ID` | `SOURCE_DEVELOPMENT_ONLY` reader after packaged early return; remaining prose references are `COMMENT/DOC` | `TEST_ONLY` synthetic values |
| `SHORT_LINK_BASE_URL`, `CF_ACCOUNT_ID`, `CF_NAMESPACE_ID` | `SOURCE_DEVELOPMENT_ONLY` reader in the explicit `RuntimeMode.SOURCE_DEVELOPMENT` branch | `TEST_ONLY` synthetic values |

Packaged-production process-env readers for all nine keys: `NONE`.

## 12. Changed Files

Production:

- `src/api/services.py`
- `src/services/llm_provider.py`
- `src/services/reporting.py`
- `src/services/tracking_adapter.py`

Tests:

- `tests/test_var001_h5_nonsecret_env_authority.py`

Evidence:

- `doc/investigations/VAR001_PHASE3D2IB2B2RH52_PACKAGED_NONSECRET_ENV_AUTHORITY_CLEANUP_IMPLEMENTATION.md`
- `.codex-local/review/VAR001_PHASE3D2IB2B2RH52_PACKAGED_NONSECRET_ENV_AUTHORITY_CLEANUP_FINAL_SOURCE_REVIEW_BUNDLE.md` (ignored)

## 13. Scope Confirmation

- H5-1 source/config and report were not modified.
- H4 code, reports, runbooks, and contracts were not modified.
- SecretStore, RuntimePaths, operational snapshot, and app_settings schemas were not modified.
- No packaging/build/install/dependency operation ran.
- H5-3 was not started.
- H6 was not started.
- No staging, commit, push, or tag operation ran.

## 14. Final Classification

`VAR001_PHASE3D2IB2B2RH52_PACKAGED_NONSECRET_ENV_AUTHORITY_CLEANUP_IMPLEMENTATION_PASS`

Independent ChatGPT review is required before H5-2 FINAL PASS or any H5-3 work.
