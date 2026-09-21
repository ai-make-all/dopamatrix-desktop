# VAR-001 Phase 3D-2I-B-2B-2R-H4-R0-R2
# Packaged Operator CLI Contract Decision Closure

## 1. Purpose / Scope / Non-Goals

This document records the H4 packaged-operator contract decisions already made
by ChatGPT after independent review of H4-R0 and its H4-R0-R1 source bundle.
It is a decision closure, not an implementation report.

In scope:

- freeze the V1.5 packaged operator entry, command surface, output and exit
  behavior, non-mutating status rules, tenant scope, SAFE_OFF semantics,
  cross-process lock and transactional pre-state rules, evidence boundaries,
  secret rotation contract, and implementation-slice order;
- identify which R0 proposals are superseded by these decisions;
- define the only authorized next review unit: H4-1A.

Out of scope:

- no production, test, packaging, Tauri, runbook, database, or runtime change;
- no H4 command implementation or executable/build proof;
- no reopening of H0-H3 frozen architecture or closed phases;
- no H5 `.env`/Ngrok cleanup, H6 installer acceptance, AUTH-001, tenant
  registry, live restore, or second operator executable;
- no authorization to start H4-1A without a separate implementation task and
  its own ChatGPT gate.

## 2. Git Baseline

The baseline was verified before this report was created:

| Fact | Actual | Result |
|---|---|---|
| Branch | `feature/var-001-variation-policy` | MATCH |
| HEAD | `bc5840d80502a39e06afab4c172846a1412f1955` | MATCH |
| Local origin ref | `bc5840d80502a39e06afab4c172846a1412f1955` | MATCH |
| Immutable RC1 | `5f534b180dd2ae9fa9212e6632a44746669d7e6f` | MATCH |
| Git index | empty | MATCH |
| Initial status | only the untracked H4-R0 report | MATCH |
| R2 target | absent | SAFE TO CREATE |

No fetch, pull, branch, tag, index, commit, or remote mutation occurred.

## 3. Evidence Chain and SHA-256

The complete evidence chain was read before this closure was written:

1. `.codex-local/handoffs.md` — current local phase/state coordination;
2. `doc/investigations/VAR001_PHASE3D2IB2B2RH4R0_PACKAGED_OPERATOR_CLI_SOURCE_CONTRACT_AUDIT.md`;
3. `.codex-local/review/VAR001_PHASE3D2IB2B2RH4R0_FINAL_SOURCE_REVIEW_BUNDLE.md`.

Integrity values at entry:

| Artifact | SHA-256 | Result |
|---|---|---|
| H4-R0 audit report | `cf0241a521823a821630a4c615ebfbf58318671a83811742c0b0a326d9b77b75` | MATCH |
| H4-R0-R1 source bundle | `c776ce7ff350cf1ee54c2dd77596170976d3cd11eb069d8fb0445db77ef6c14f` | MATCH |

ChatGPT accepted:

`VAR001_PHASE3D2IB2B2RH4R0R1_FINAL_SOURCE_REVIEW_BUNDLE_FINAL_PASS`

The R1 bundle remains a locally ignored review artifact. It is not a tracked
product artifact and is not modified by this decision closure.

## 4. Accepted R1 Source Findings

The following findings are accepted as the factual source baseline:

1. The early `operator` seam is before the complete application graph.
2. Current `prepare_bootstrap()` creates the runtime root and tenant `data/`
   directory before recognizing the operator token.
3. No real packaged operator dispatcher currently exists.
4. Tracked `build_backend.py` invokes PyInstaller with `--windowed`.
5. `backend.spec` is not a HEAD blob. Its classification remains exactly:

   ```text
   HEAD_BLOB_STATUS = MISSING
   WORKTREE_ARTIFACT_STATUS = IGNORED_OR_GENERATED_SECONDARY_EVIDENCE
   ```

   It is not tracked build authority; tracked `build_backend.py` is.
6. Current source does not prove reliable packaged terminal stdout/stderr or
   shell-wait behavior.
7. The normal Tauri sidecar spawn contains no source-visible no-console flag.
   Other `CREATE_NO_WINDOW` uses apply to unrelated child commands.
8. No reusable crash-releasing server/operator cross-process lock exists.
9. No snapshot revision or compare-and-swap helper exists.
10. Existing status helpers can create a SQLite database and/or table.
11. The tenant initializer uses a permissive sanitizer rather than enforcing
    the complete production tenant-identity constitution.
12. Ordinary profile apply is not Assignment Secret rotation.
13. Tenant backup excludes the global DB, DPAPI secrets, and the Assignment
    Secret; Delivery copies are not backup authority.
14. Future handler inclusion and terminal behavior require real packaged
    build/runtime smoke evidence.

No statement in this section promotes `backend.spec` to tracked authority.

## 5. Supersession Rule

- R0 SOURCE-PROVEN facts that R1 verified remain valid, subject to R1's exact
  qualification of `backend.spec` and future built-artifact behavior.
- R0 proposed command syntax, unresolved choices, exit-code suggestions, and
  slice recommendations are superseded wherever they differ from this R2.
- This R2 does not modify H0-H3 Frozen Architecture, H1 bootstrap/runtime
  authority, H2 secret authority, or H3 applied-snapshot semantics.
- This R2 does not authorize production implementation.
- The next possible implementation unit is H4-1A only. H4-1B or any later
  slice may not begin before its predecessor is implemented, tested, reported,
  and independently gated.

## 6. Frozen Single-Binary Entry

The V1.5 product entry is frozen as one packaged backend binary:

```text
backend.exe operator ...
```

No second operator product entry or independent operator executable is
authorized.

The same packaged binary has two mutually exclusive invocation modes:

- no `operator` token: normal Tauri server-sidecar mode;
- `operator` token: CLI dispatch before the complete application graph, then
  deterministic process exit.

CLI mode must prove all of the following using a real Windows packaged build:

- the invoking PowerShell/cmd process waits for completion;
- stdout and stderr are available under the contracts in Section 8;
- the shell can read the exact process exit code;
- FastAPI, Uvicorn, routers, and the database application graph do not start;
- help and usage paths create no runtime directory, DB, or table.

Normal Tauri server launch must separately prove:

- no visible console window;
- no operator arguments;
- unchanged server startup and lifecycle behavior.

Current `--windowed` behavior is not accepted as proof of both modes. R2 does
not freeze a specific Windows console technique. H4-1B must choose and prove
the technique through isolated real packaged smoke. If new evidence proves the
single-binary contract infeasible, implementation stops and returns to
ChatGPT; it must not silently introduce a second binary.

## 7. Frozen Command Tree

Global grammar:

```text
backend.exe operator [--json] <namespace> <command> [arguments]
```

`--json` is an operator-global option and appears before the namespace. Every
final H4 command supports human output by default and the same global JSON
mode.

Frozen minimum commands:

```text
backend.exe operator [--json] config status

backend.exe operator [--json] tenant provision \
  --tenant ID \
  --approval-ref REF

backend.exe operator [--json] seed status \
  --tenant ID

backend.exe operator [--json] seed apply-safe-off \
  --tenant ID \
  --generation G \
  --approval-ref REF \
  [--lease-profile 180-45|300-60]

backend.exe operator [--json] seed prearm-p3w \
  --tenant ID \
  --generation G \
  --backup-bundle PATH \
  --approval-ref REF

backend.exe operator [--json] seed activate \
  --tenant ID \
  --generation G \
  --backup-bundle PATH \
  --approval-ref REF

backend.exe operator [--json] seed kill \
  --tenant ID \
  --generation G \
  --reason-code CODE

backend.exe operator [--json] seed set-balanced-bps \
  --tenant ID \
  --generation G \
  --bps N \
  --backup-bundle PATH \
  --approval-ref REF

backend.exe operator [--json] seed transition-p3a \
  --tenant ID \
  --generation G \
  --rollback-window 7d|24h \
  --backup-bundle PATH \
  --approval-ref REF

backend.exe operator [--json] secret assignment status

backend.exe operator [--json] secret assignment rotate \
  --tenant ID \
  --expected-generation G \
  --new-generation G2 \
  --backup-bundle PATH \
  --approval-ref REF

backend.exe operator [--json] backup create \
  --tenant ID \
  --destination ABSOLUTE_NEW_DIRECTORY

backend.exe operator [--json] backup verify \
  --bundle ABSOLUTE_BUNDLE_DIRECTORY
```

The following are explicitly absent from H4:

- `--tenant-code` and `--verified-backup`;
- generic `set KEY=VALUE`, raw snapshot import, generic generation edit, or
  arbitrary tenant-allowlist editing;
- a secret-value argument, `--force`, automatic ramp, or live restore.

`--backup-bundle` always means that the command itself performs a complete
verification at execution time and validates bundle tenant identity. A folder
name or historical operator statement that a backup was verified is not
authority.

## 8. Output and JSON Contract

Human mode:

- success output goes only to stdout;
- failure output goes only to stderr;
- no traceback, raw exception, secret-derived material, or unbounded message;
- every result uses a stable symbolic status/error code.

JSON mode:

- both success and failure write exactly one UTF-8 JSON object to stdout;
- stderr remains empty;
- no banner, log line, traceback, or mixed multi-line output is permitted;
- `schema_version` is exactly `1`;
- the object contains at least `schema_version`, `command`, `status`,
  `error_code`, and `data`;
- successful `error_code` is `null`;
- `data` contains only explicitly approved non-sensitive fields.

Help and usage:

| Invocation | Exit |
|---|---:|
| `backend.exe operator --help` | 0 |
| valid namespace/command `--help` | 0 |
| bare `operator` | 2 |
| unknown namespace or command | 2 |
| invalid arguments | 2 |

Every help/usage path has zero runtime-filesystem mutation.

## 9. Exit-Code Contract

| Exit | Frozen category |
|---:|---|
| 0 | success, including successful observation of ABSENT/NOT_INITIALIZED |
| 2 | usage |
| 3 | validation or frozen-policy violation |
| 4 | state, precondition, or concurrency failure |
| 5 | required tenant, bundle, or resource not found |
| 6 | integrity or verification failure |
| 7 | preserved partial mutation requiring human review |
| 8 | platform, storage, DPAPI, filesystem, or SQLite subsystem failure |
| 9 | bounded unexpected internal failure |

Additional mappings:

- `config status` with no DB/snapshot exits 0 and projects
  `NOT_INITIALIZED` or `SAFE_OFF_MISSING`;
- Assignment Secret status with no DB/table/row exits 0 and projects `ABSENT`;
- unreadable or corrupt state is not ABSENT and maps to 6 or 8;
- `seed status` for an absent tenant exits 5;
- every failure carries a stable symbolic error code.

## 10. Strict Non-Mutating Status Contract

All help, usage, and status paths are strictly non-mutating.

Required bootstrap behavior:

- do not call `initialize_runtime_paths()` before operator recognition;
- help and usage need not resolve runtime paths at all;
- status uses `resolve_runtime_paths()` or an equivalent no-write resolver.

Prohibited status effects:

- no `mkdir`;
- no SQLite file or table creation;
- no lazy tenant provisioning;
- no RuntimeConfigProvider install or mutation;
- no log file written under the runtime root.

SQLite status procedure:

1. test whether the database file exists;
2. open an existing file through a read-only SQLite URI;
3. query `sqlite_master` before querying a table;
4. optionally test DPAPI decryptability only for an existing secret row;
5. project an absent DB/table/row as a valid non-error state.

## 11. Tenant Provision Contract

H4 V1.5 tenant provisioning is restricted to exactly:

- `ph-elv-0001`;
- `ph-bty-0001`;
- `ph-hwh-0001`.

Allowlist membership does not replace validation. Before any mutation the
command must also enforce:

- the production tenant regex;
- lowercase ASCII and raw input exactly equal to canonical identity;
- sequence range `0001..9999`;
- reserved namespace and approved vertical rules;
- case-normalized DB, WAL, and SHM filename collision checks;
- Delivery namespace, backup namespace, and known partial-allocation checks;
- backend/server quiescence and acquisition of the shared operator mutation
  lock.

After initialization it independently verifies SQLite integrity, application
schema, Ledger V2, reopen behavior, and zero business rows. It creates no fake
task, asset, Reservation, readiness, or rollout evidence.

Tenant short code is deterministically derived from the approved canonical ID.
It is not accepted as an argument, DB selector, or second identity authority.

General grammar-based provisioning and a persistent tenant registry are not
part of H4 V1.5. A partial tenant DB is never deleted, overwritten, or retried
automatically. It is preserved and returns exit 7 for human review.

## 12. SAFE_OFF Initial / Idempotent Contract

`seed apply-safe-off` is permitted only when:

1. no applied snapshot exists; or
2. the existing snapshot is already an exact idempotent target with:
   - the same tenant;
   - the same generation;
   - the same approved Lease profile;
   - stage `SAFE_OFF`;
   - Balanced BPS `0`;
   - Exact BPS `0`;
   - kill switch `true`;
   - the identical complete policy family.

Case 2 returns `ALREADY_APPLIED` without rewriting the snapshot, timestamp,
audit metadata, or Assignment Secret. It does not generate or rotate a secret.

Any existing but different snapshot fails with exit 4. H4 does not add generic
rebaseline, tenant switch, generation replacement, or force overwrite.

## 13. Cross-Process Lock Contract

One dedicated lock file under the runtime root is used as the shared runtime
mutation barrier. Lock authority is the operating system's held file lock, not
the path's existence.

Frozen mechanics:

1. Windows uses Python standard-library `msvcrt.locking` with a non-blocking
   byte-range lock.
2. Source-development/POSIX tests use an adapter based on `fcntl.flock`.
3. The owning process keeps the locked file handle open.
4. Process exit or crash releases the OS lock.
5. The lock file may remain present indefinitely; deletion is not unlock or
   stale-lock recovery.
6. A normal server holds the same exclusive runtime mutation barrier from
   startup through shutdown.
7. Every Seed, Assignment Secret, and tenant mutation requires that exclusive
   barrier.
8. A second server or concurrent mutating operator that cannot lock exits 4.
9. Status and backup verify do not acquire the mutation lock.
10. Backup create may coexist with the server and continues to use SQLite
    online backup and the accepted backup consistency mechanism.

PID-file-only, lock-file-existence, delete-to-unlock, and last-writer-wins
schemes are prohibited.

## 14. Transactional Pre-State / CAS Contract

H4 does not add a snapshot-schema revision column.

After acquiring the process lock, every operational mutation uses a caller-
owned global SQLite connection and one `BEGIN IMMEDIATE` transaction. Inside
that same transaction it:

1. rereads the current canonical snapshot;
2. verifies tenant, generation, stage metadata compatibility, kill, BPS, and
   every command-specific complete pre-state condition;
3. performs the write only when the pre-state exactly matches.

The precondition check and snapshot write must not cross transaction
boundaries. An implementation may not check outside the transaction and then
call a separate ordinary-apply transaction.

Assignment Secret rotation writes the new secret and new-generation contained
snapshot through that same transaction. Both commit or both roll back. No
last-writer-wins or PID-file-only substitute is accepted.

## 15. Evidence / Approval / Backup Semantics

`--approval-ref` is an external change-ticket or approval-record reference. It
is not application authentication, authorization, or proof that approval is
genuine.

The value must be non-empty, bounded, control-character-free, contain no
secret, and be safe for approved audit metadata and output.

Readiness, breaker, Delivery, and applied-snapshot state are read from current
canonical sources. Command-line booleans cannot assert that these gates passed.

Every `--backup-bundle` input is fully verified during the command and must
match the target tenant. H4 does not add an approval or evidence database.

The following remain external runbook/change-control responsibilities:

- proof that a required restart was performed;
- staffed-block approval;
- human cohort review and risk decision.

The CLI enforces only source-provable state and evidence boundaries and never
claims to prove those human decisions.

## 16. Assignment Secret Rotation Contract

Assignment Secret rotation remains a separate high-risk command. Ordinary
profile apply must not rotate it, and no operator supplies, receives, or reads
the value. A new value is generated locally through a CSPRNG.

Rotation preconditions are all mandatory:

- a valid current snapshot;
- kill-switch containment (`kill=true`);
- exact expected-generation match;
- a different, valid new generation;
- the same tenant;
- a fully verified, tenant-matching `--backup-bundle`;
- a valid external `--approval-ref`;
- server quiescence and the exclusive runtime mutation lock.

Inside one global SQLite transaction the command:

1. writes and decrypt-verifies the new secret;
2. builds a new-generation contained snapshot;
3. preserves tenant, stage-compatible metadata, BPS, Lease, Readiness, and
   rollback family;
4. preserves `kill=true`;
5. canonical-validates the resulting snapshot;
6. commits both writes or rolls both back.

Success requires a controlled restart. Approved output is limited to:

- `ROTATED`;
- tenant;
- old and new generation;
- `kill=true`;
- secret status `PRESENT`;
- restart-required status.

The command never emits the secret value, length, hash, prefix, suffix,
ciphertext, or HMAC intermediate. Tenant backup contains neither the global DB
nor a secret. `--backup-bundle` is an operational checkpoint, not secret
recovery. H4 implements no secret export, import, reveal, or recovery.

## 17. Deferred Scope

The following remain explicitly outside H4:

- a general tenant registry or arbitrary tenant provisioning;
- generic rebaseline, tenant switch, or general incident generation edit;
- packaged restore-to-staging or live restore;
- Assignment Secret recovery, export, import, or reveal;
- H5 production NO-`.env` and Ngrok/network/config cleanup;
- H6 final installer acceptance;
- a second operator binary.

## 18. Frozen H4 Slice Order

### H4-1A — Bootstrap-safe dispatcher and output contract

- implement operator/help/usage parsing, global `--json`, stable output/error/
  exit helpers, and zero-filesystem-mutation help/usage;
- add source-level focused tests;
- do not modify DB/status/tenant/Seed/secret/backup behavior;
- do not perform a packaged build.

### H4-1B — Same-binary packaged console/Tauri proof

- prove the same backend binary's operator shell-wait/stdout/stderr/exit
  behavior;
- prove normal Tauri server startup has no visible console and no regression;
- use an isolated temporary worktree/build environment;
- do not run the currently destructive build preparation directly in the
  developer worktree.

### H4-2 — Strict non-mutating status

Implement the Section 10 projections and absence behavior without any runtime
filesystem or schema mutation.

### H4-3 — Crash-releasing lock and transactional pre-state/CAS

Implement Sections 13-14 before any higher-level mutating command.

### H4-4 — Three-ID-only packaged tenant provisioning

Implement only the approved identities and the complete Section 11 barrier,
verification, and partial-failure semantics.

### H4-5 — RuntimePaths-bound packaged backup create/verify

Expose the accepted backup/verify core through the frozen packaged commands,
with tenant and destination safety and no authority expansion.

### H4-6 — SAFE_OFF and named Seed transitions

Implement initial/idempotent SAFE_OFF, P3-W pre-arm/activate/kill, governed BPS
change, and P3-A transition under the frozen pre-state/evidence contracts.

### H4-7 — Atomic contained new-generation Assignment Secret rotation

Implement only the independent Section 16 command and transaction.

### H4-8 — Full packaged smoke and Runbook/Execution Pack synchronization

Prove the completed packaged command surface and then synchronize operational
documentation. This slice does not absorb H5 or H6.

Every slice requires its own Codex implementation, focused tests, relevant
regressions, evidence report, and independent ChatGPT review/gate. A later
slice does not start before its predecessor passes its gate.

## 19. Files Changed

This R2 creates exactly one tracked-candidate documentation artifact:

```text
doc/investigations/VAR001_PHASE3D2IB2B2RH4R0R2_OPERATOR_CLI_CONTRACT_DECISION_CLOSURE.md
```

Production code: 0 changes. Tests: 0. Packaging/Tauri: 0. Runbooks: 0.
Handoff: 0. H4-R0 report: 0. H4-R0-R1 review bundle: 0. Existing reports: 0.
Git index, branch, tag, commit, and remote: unchanged.

## 20. Final Classification

The H4 contract decisions are closed for implementation slicing, but no H4
production implementation is authorized by this document. The next review
unit is H4-1A only.

```text
VAR001_PHASE3D2IB2B2RH4R0R2_OPERATOR_CLI_CONTRACT_DECISION_CLOSURE_COMPLETE
VAR001_PHASE3D2IB2B2RH4R0_FINAL_GATE_REVIEW_REQUIRED
```
