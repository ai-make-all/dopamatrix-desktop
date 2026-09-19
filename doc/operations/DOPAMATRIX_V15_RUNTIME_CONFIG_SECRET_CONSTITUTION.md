# DopaMatrix V1.5
# Runtime Configuration and Secret Constitution

## 1. Purpose

This constitution freezes the packaged V1.5 runtime-configuration boundary. It changes where configuration comes from, not the meaning of Reservation, Readiness, Rollout, Task Identity, tenant isolation, Delivery, backup, or future L3.

The governing distinction is:

```text
definition != persisted state != secret storage != UI exposure
```

## 2. Production NO-.env Rule

Packaged/field DopaMatrix is completely NO-`.env`:

- no `.env` is bundled, copied, generated, searched, loaded, or deleted;
- no ancestor-directory dotenv fallback runs in frozen mode;
- no missing database or secure setting falls back to process environment;
- no Philippine handoff includes a production `.env` template;
- no installer, manifest, CLI argument, Markdown artifact, localStorage entry, or Vue state contains a real secret.

Source development may opt into process environment and local dotenv. Tests may inject deterministic mappings/providers. Those adapters are never in the packaged production fallback chain.

## 3. Configuration Layer Model

| Layer | Examples | Authority | Ordinary UI? |
|---|---|---|---|
| Build/release identity | version, tag, channel, architecture | source, build metadata, release manifest | no |
| Product profile | universal DopaMatrix product behavior | source-defined product profile | no |
| Machine/user settings | Delivery Root, LLM endpoint/model | global runtime DB | only when a normal operator genuinely chooses it |
| Operational policy definition | `philippine-seed-v1`, bounds and stage defaults | reviewed version-controlled profile | no raw-field UI |
| Operational state | active profile/version, tenant, generation, BPS, kill, allowlist, normalized snapshot | global runtime DB | field CLI; future restricted admin UI only |
| Secrets | provider credentials, Assignment Secret | DPAPI-protected `secure_settings` | secret-entry/status actions only |
| Development/test configuration | local overrides and fixtures | explicit dev/test adapter | not packaged |

## 4. Definition vs State

A policy definition answers what values, bounds, and transitions are approved. An applied runtime snapshot answers what one installation will run after its next controlled restart.

`philippine-seed-v1` is version-controlled. Applying it writes one normalized, complete, versioned snapshot. The snapshot may repeat profile-derived values for reproducibility, but this does not make those values individually operator-entered or individually editable.

## 5. Product Profile

V1.5 has one universal product profile. Content and UA are task-level `engine_type` choices, not installation identity. Product profile is release identity and is not a Settings-page dropdown.

The product profile and the operational profile are different authorities:

```text
product profile: DopaMatrix universal
operational profile: philippine-seed-v1
```

## 6. APP_MODE Decision

Decision: `APP_MODE_REMOVE_AS_LEGACY`.

Current production source contains no `APP_MODE` read or consumer. Vue submits `engine_type` per task, schemas carry it, and backend routes pass it into the task workflow. Both `content` and `ua` are already supported by one installation. `APP_MODE` must not be migrated into SQLite, a profile selector, or UI.

## 7. Machine Runtime Settings

Reuse global `app_settings` for non-secret machine choices such as Delivery Root and reviewed LLM endpoint/model settings. Values are validated and accessed through the runtime configuration provider rather than ad hoc SQL or environment reads.

Machine settings are independent of tenant logout. They are never stored in tenant databases. Settings that are implementation constants or obsolete variables are removed rather than persisted.

## 8. Operational Policy Profile

The named profile is `philippine-seed-v1`. It defines the frozen lease, Readiness, Rollout, rollback, safety, and transition contracts from the accepted Philippine policy. The existing configuration dataclasses and validators remain semantic authority.

Operators select/apply the profile; they do not transcribe its 32 non-secret fields. Profile edits require source review and a new profile version/release.

## 9. Applied Runtime Snapshot

Persist one normalized JSON snapshot in `app_settings`, under a schema-versioned key such as `operational_runtime_snapshot_v1`. The payload includes:

- snapshot schema version and profile name/version;
- applied UTC timestamp and safe change-control metadata;
- tenant allowlist, generation, optional transition/audit stage label, Exact/Balanced BPS, kill switch;
- the complete normalized lease, Readiness, and rollback configuration;
- a secret reference/status, never secret plaintext or ciphertext copied into the JSON.

Replacing this single row inside one SQLite transaction provides all-or-none non-secret application. The same transaction may insert a newly encrypted Assignment Secret into `secure_settings`. The backend accepts only a known profile/version and a complete snapshot that passes existing validators.

`stage`, including labels such as `SAFE_OFF`, `P3_W`, and `P3_A`, is non-authoritative transition/audit metadata. Runtime rollout behavior must never branch on that label alone. Runtime authority is the complete validated effective configuration: generation, allowlist, Exact/Balanced BPS, kill switch, rollback window and thresholds, lease configuration, and Readiness configuration. Named transition commands calculate and atomically write those effective values. If a label is persisted, startup validates that it is compatible with the effective snapshot and fails closed on mismatch. The label does not create a second rollout state machine.

## 10. Secret Settings

Create one global table:

```text
secure_settings(
  key_name TEXT PRIMARY KEY,
  encryption_scheme TEXT NOT NULL,
  ciphertext BLOB NOT NULL,
  updated_at TEXT NOT NULL
)
```

Minimum current registry:

| Key | Disposition |
|---|---|
| `openai_api_key` | secure setting |
| `reservation_rollout_assignment_secret` | secure setting |
| `pexels_api_key` | secure setting when Pexels is enabled |
| `telegram_bot_token` | secure setting when Telegram is enabled |
| `cf_api_token` | secure setting when Cloudflare tracking is enabled |

`deepseek_api_key` is not an active current credential; add it only with a real provider implementation. Chat IDs, account IDs, namespaces, URLs, models, and Delivery Root are non-secret settings, though some remain operationally sensitive.

## 11. Windows DPAPI Contract

Packaged Windows V1.5 uses DPAPI `CurrentUser`. Native `CryptProtectData`/`CryptUnprotectData` is available through Python `ctypes`, so no network service or plaintext key file is required and PyInstaller can bundle the wrapper.

Ciphertext is bound to the Windows user profile. The application may use stable application-purpose entropy, but must not describe it as an independent cryptographic secret. Decrypted values exist only for the shortest necessary in-process use and are excluded from repr, logs, errors, responses, and diagnostics.

Loss of the Windows profile makes secrets unrecoverable. Assignment Secret regeneration is an explicit rotation requiring kill containment, a new rollout generation, approval, and controlled restart because it changes HMAC assignment.

## 12. OpenAI / LLM Secret Contract

`POST /api/v1/settings/llm` receives the key, encrypts it with DPAPI, writes `secure_settings`, commits, and invalidates the provider cache. It never returns the value.

`GET /api/v1/settings/llm` returns only `is_configured`/`configured` status. It no longer returns even a prefix/suffix mask. The existing Settings card and request shape can remain; the frontend removes masked-key display.

Provider base URL and model are non-secret machine settings. OpenAI-compatible branding does not imply that a separate DeepSeek credential exists today.

## 13. Seed Runtime Configuration

The 33-key source contract is retained semantically:

- 2 lease values;
- 13 Readiness values;
- 18 Rollout values;
- exactly 32 non-secret values and 1 Assignment Secret.

All 32 normalized non-secret effective values are present in the applied snapshot for reproducibility. Profile-fixed values are hidden definition fields. Generation, allowlist, Balanced BPS, kill switch, rollback stage thresholds/window, and approved lease-profile selection are controlled operational state. The secret is resolved from `secure_settings` into an in-memory secret-safe snapshot only.

## 14. Assignment Secret Contract

The field operator does not type or receive the Assignment Secret. `apply-safe-off` generates it locally with a CSPRNG only when absent, DPAPI-encrypts it, and preserves an existing valid setting. Status is exactly `PRESENT`, `ABSENT`, or `ERROR`.

The value, length, hash, prefix, suffix, HMAC intermediate, and ciphertext are never printed. Rotation is a separate guarded action and is never an incidental profile re-apply.

## 15. RuntimeConfigProvider

One `RuntimeConfigProvider` separates consumers from storage while exposing two deliberately different lifecycles:

1. **Static operational snapshot.** Seed, Reservation, Readiness, Rollout, and Assignment Secret participation are loaded and validated during controlled backend startup. The resulting typed configuration is immutable for that backend process generation. Changes activate only after a controlled restart.
2. **Dynamic machine settings.** Delivery Root, OpenAI credential, and—where the implementing source supports bounded reads or cache invalidation—LLM endpoint/model and optional integration settings may use bounded read-through or explicit cache invalidation. They are not members of the immutable Seed policy snapshot.

The provider therefore:

- selects packaged, source-development, or test source mode explicitly;
- loads build identity, machine settings, policy definition, applied snapshot, and secrets;
- creates an immutable typed process configuration for the static operational snapshot;
- validates complete groups through existing lease/Readiness/Rollout validators;
- prevents secret-bearing fields from repr/log/error output;
- fails closed on missing, partial, unknown, corrupt, or version-incompatible configuration.

Consumers receive typed configuration or an adapter-produced mapping. They do not independently query environment, SQLite, policy source, or DPAPI.

Delivery Root remains a dynamic machine setting, not Seed authority. Dynamic machine-setting support does not authorize hot reload of Seed rollout state.

## 16. Packaged / Dev / Test Modes

| Mode | Sources | Fallback rule |
|---|---|---|
| Packaged production | `DatabaseRuntimeConfigSource` + `PolicyProfileSource` + `SecureSecretSource` | no environment/dotenv fallback |
| Source development | explicit `EnvironmentConfigSource`; optional dotenv adapter | allowed only when explicitly selected |
| Test | deterministic injected `TestConfigSource` | no host-environment dependence unless the test requests it |

Frozen status alone selects the secure production chain. A missing packaged setting is an error or safe-disabled feature, never an invitation to search ancestor files.

## 17. Runtime Data Root

Packaged mutable state lives under:

```text
appdirs.user_data_dir("DopaMatrix", "DopaMatrixOrg")
  dopamatrix.db
  data/
    dopamatrix_<canonical-tenant>.db
  output/
```

Logs remain under the existing per-user log root. Binaries, FFmpeg, FFprobe, and installer resources remain immutable and separate. Source development retains repository-relative roots through an explicit development path adapter. Packaged startup must fail before serving if the user-data root cannot be created or validated.

## 18. Controlled Restart

Seed changes are written and validated transactionally while work is drained, then activated only by controlled backend restart. Startup creates one immutable static operational `RuntimeConfigSnapshot`; Readiness, Rollout, and summary are re-queried after restart.

V1.5 does not introduce live Seed-policy mutation during active tasks. Delivery Root and an LLM key may retain their existing immediate Settings behavior, and bounded dynamic handling may be added for LLM endpoint/model or optional integration configuration, when those values do not alter a running task's authoritative Seed policy snapshot.

## 19. Field Operator Configuration

The packaged backend hosts an operator mode before Uvicorn startup, for example:

```text
backend.exe operator config status
backend.exe operator seed-config apply-safe-off \
  --tenant ph-elv-0001 \
  --generation phseed-elv0001-bal-YYYYMMDD-rN
backend.exe operator secret status
```

`apply-safe-off` selects `philippine-seed-v1`, validates the approved tenant/generation, writes the complete normalized snapshot, sets Exact/Balanced to `0/0`, kill to `true`, allowlist to exactly the tenant, creates the Assignment Secret if absent, and commits atomically. It never starts Uvicorn or prints a secret.

The same executable may expose tenant provision and backup/verify modes, provided argument dispatch happens before normal application imports/startup side effects.

## 20. UI Exposure Rules

| Domain | V1.5 exposure |
|---|---|
| OpenAI key | `ORDINARY_SETTINGS_UI`, write + configured status only |
| Delivery Root | `ORDINARY_SETTINGS_UI` |
| APP_MODE | `NO_UI`; remove |
| Seed profile | `FIELD_OPERATOR_CLI` |
| Generation | `FIELD_OPERATOR_CLI` |
| Kill switch | `FIELD_OPERATOR_CLI`; future restricted admin UI optional |
| Basis points | `FIELD_OPERATOR_CLI`; future restricted admin UI optional |
| Readiness thresholds | `HIDDEN_PROFILE_DEFINITION` |
| Rollback thresholds | `HIDDEN_PROFILE_DEFINITION`, with named guarded stage transition |
| Assignment Secret | `NO_UI`; status/rotation operator commands only |
| Lease TTL/heartbeat | `HIDDEN_PROFILE_DEFINITION`; approved profile selection through CLI |

Persistence never implies ordinary UI exposure.

## 21. Legacy Migration

In packaged startup, perform one idempotent OpenAI migration after the global DB and DPAPI source are ready:

1. inspect the legacy `app_settings.openai_api_key` row without logging metadata;
2. inspect `secure_settings.openai_api_key`;
3. if a valid secure value exists, never overwrite it; a conflicting legacy value is preserved and reported as a bounded conflict;
4. otherwise encrypt and persist the legacy value;
5. decrypt and compare exact bytes in memory;
6. only after successful verification delete the plaintext row in the same controlled migration flow;
7. invalidate the LLM cache;
8. on any failure retain the only usable plaintext row and fail the migration safely, with no dotenv fallback.

This automatic bounded migration is preferable to requiring a field operator to handle plaintext. Legacy install-root database relocation is a separate explicit, verified runtime-data migration and must not create split-brain roots.

## 22. Failure Semantics

- DPAPI encrypt/decrypt failure: no plaintext fallback; secret status `ERROR`; affected feature fails closed.
- Missing/corrupt secret: no value disclosure; Seed canary remains OFF; provider request fails safely.
- Missing/partial/unknown/version-mismatched operational snapshot: reject activation and remain/return SAFE-OFF.
- Runtime-root or global-DB failure: do not start the server or operator mutation.
- Atomic profile transaction failure: rollback snapshot and newly inserted secret together.
- Legacy migration failure: preserve legacy credential; never delete the sole usable copy.
- Optional integration configuration failure: disable that integration without weakening render/Reservation authority.

## 23. Release / Handoff Contract

Remove `.env` from Tauri resources. A release build must succeed with no `web_ui/src-tauri/.env` and final artifact scanning must prove there is no `.env`, `config.env`, `runtime.env`, `settings.json`/YAML/TOML secret substitute, or plaintext secret file.

Replace the prior “safe field `.env` template” handoff item with:

- Field Runtime Configuration Procedure;
- Philippine Seed Safe-Off Profile identity/version;
- packaged operator CLI instructions;
- local secret generation/status procedure.

## 24. Security Boundary

DPAPI protects against plaintext database inspection, copied-database disclosure, installer secret leakage, and casual disk browsing. It does not protect against the same authorized Windows user while the application is running, privileged local malware, system administrators, process-memory inspection, or a compromised application process.

Runtime status, logs, errors, API responses, diagnostics, manifests, and operator evidence expose presence/state only. Local network exposure remains loopback by default; Ngrok is off in Philippine V1.5.

## 25. Non-Goals

This constitution does not implement AUTH-001, cloud secret management, multi-machine secret portability, automatic rollout ramp, live configuration hot reload, a full operations console, new Reservation semantics, a new tenant authority, or a plaintext configuration-file replacement for `.env`.
