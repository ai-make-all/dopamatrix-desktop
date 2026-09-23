# VAR-001 Phase 3D-2I-B-2B-2R-H4-5
# RuntimePaths-Bound Backup Create / Verify Implementation

## 1. Phase Identity

H4-5 implements exactly the frozen packaged-operator commands:

```text
backend.exe operator [--json] backup create --tenant ID --destination ABSOLUTE_NEW_DIRECTORY
backend.exe operator [--json] backup verify --bundle ABSOLUTE_BUNDLE_DIRECTORY
```

The implementation and H4-5-R1 independent-review fixup, focused tests,
backup/H4 regression, and full backend regression pass. This is implementation
evidence for independent ChatGPT review, not a FINAL PASS.

## 2. Governing Documents

The implementation obeys root `AGENTS.md`, `.codex-local/handoffs.md`, H4-R0,
the H4-R0-R2 decision closure, the H4-4 Backup Namespace authority closure,
the targeted backup/restore and restore-alias audits/fix report, and the H4-4
implementation report. H0-H4-4 remain closed. H4-6 was not started.

## 3. Repository Baseline

- Branch: `feature/var-001-variation-policy`
- HEAD/origin: `03c67aaa06bea286f22dc5edf0fb0abd6969b80b`
- Immutable RC1: `5f534b180dd2ae9fa9212e6632a44746669d7e6f`
- Initial worktree: clean
- Initial index: empty

## 4. Pre-Change Source Audit

- `create_backup_bundle()` already provided SQLite online backup, snapshot-first
  TaskHistory catalog enumeration, full-file SHA-256, bounded asset-copy retry,
  sibling staging, staging verification, cleanup, and final publication.
- It defaulted `project_root="."`; the H4-5 adapter now always supplies the
  resolved `RuntimePaths.runtime_root` and exposes no project-root argument.
- Create used lexical `.absolute()` for a missing destination and final
  `os.replace`, leaving physical-alias and competing-final risks.
- `verify_backup_bundle()` already enforced format, member-path confinement,
  database/asset hashes, catalog locator/shape equality, and SQLite integrity.
  Its ordinary read-only SQLite connections could create WAL/SHM for a bundle
  DB and its top-level database import could initialize RuntimePaths.
- Existing Delivery reads either created `app_settings` or, in H4-4, rejected
  all sidecars. H4-5 needed a non-writing reader that sees current committed
  WAL data while a server is running.
- Both backup commands were registered placeholders before H4-5.

## 5. Exact Operator Grammar

Only the two commands in Section 1 became operational. There is no restore,
repair, force, overwrite, project-root, runtime-root, backup-root, tenant
override on verify, or other backup command. Global `--json` placement and the
H4-1A parser remain unchanged.

## 6. Exact Tenant Policy

Create reuses `validate_approved_tenant_identity()` from H4-4. Raw input must
already be canonical and must be exactly one of `ph-elv-0001`,
`ph-bty-0001`, or `ph-hwh-0001`. Sanitizer aliases, uppercase, whitespace,
unapproved sequences/verticals, reserved names, and path-like values fail with
exit 3 before RuntimePaths resolution or destination creation.

## 7. RuntimePaths Source Binding

`create_operator_backup()` selects `get_initialized_runtime_paths() or
resolve_runtime_paths()` and never calls `initialize_runtime_paths()`. It
requires the regular tenant DB at `RuntimePaths.tenant_database_path()` and
calls the accepted core with `project_root=RuntimePaths.runtime_root`.
A decoy CWD containing its own `data/` and `output/` was ignored.

## 8. No-Source-Creation Proof

A valid approved tenant with an absent runtime root/tenant DB returns
`OPERATOR_BACKUP_SOURCE_NOT_FOUND`, exit 5. The test proves no runtime root,
data directory, tenant DB, global DB, destination parent, final, or staging
entry is created. No tenant initializer or `get_tenant_engine()` is used.

## 9. No H4-3 Lock Proof

Neither create nor verify imports/acquires the H4-3 mutation barrier. An
independent process held the real OS-backed server barrier while create
completed and the published bundle verified successfully.

## 10. SQLite Online Backup Proof

The live source still uses a dedicated `sqlite3.Connection.backup()` from
`mode=ro`, with no checkpoint or journal-mode change and no filesystem copy of
DB/WAL/SHM. A concurrent committed writer ran during backup; the published DB
passed `integrity_check`, contained one valid committed snapshot state, and no
WAL/SHM member was copied.

## 11. Absolute Destination Validation

The adapter rejects blank, whitespace, NUL, relative, dot-relative,
drive-relative, malformed Windows, and reserved-device paths with exit 3. It
does not use CWD to rescue input. Only a raw absolute path proceeds.

## 12. Physical Canonicalization

Before destination-side creation, H4-5 checks the raw lexical target with
`lexists`, then uses `Path.resolve(strict=False)` to resolve junction/symlink
parents and normalize dot components. It verifies the nearest existing prefix
is a directory. The core also uses physical `resolve(strict=False)`.

## 13. Runtime-Tree Exclusion

Physical overlap is rejected in both directions against the whole runtime
root. This covers the tenant data directory, global DB, internal output,
logs, and any runtime child. Explicit tests reject the root, children,
internal-output children, ancestors, and real Windows junction aliases.

## 14. Delivery-Tree Exclusion

`read_current_delivery_root()` uses the existing `app_settings.delivery_root`
authority without creating a DB/table or writing SQL. A sidecar-free DB is read
immutable and its main-file size, nanosecond mtime, device, and inode plus
sidecar absence are verified before and after the closed connection. A complete
live WAL+SHM state uses `mode=ro` so current committed WAL data is visible.
Rollback-journal or incomplete WAL/SHM state fails closed. Configured Delivery
overlap is rejected in both directions, including a real junction alias.
Unconfigured Delivery imposes no extra path and creates none.

## 15. Final Destination No-Overwrite Design

Raw and physical final targets use `os.path.lexists`, covering files,
directories, links, junctions, and broken aliases. Publication now uses
`os.rename` on the Windows product platform rather than replacing semantics;
it rechecks immediately and maps a race winner to
`BACKUP_DESTINATION_ALREADY_EXISTS`. A fault test creates a competing final
with sentinel bytes after staging verification: the sentinel is preserved and
staging is removed.

## 16. Staging and Atomic Publication

The accepted same-parent sequence remains: validate, create unique sibling
staging, online snapshot, enumerate counts/catalog, copy authoritative assets,
write manifest, verify staging, then publish. Faults injected at snapshot,
catalog enumeration, asset copy, manifest write, staging verify, and final
publish all left final absent, removed only H4-5 staging, preserved source DB
and assets, and preserved unrelated siblings.

## 17. TaskHistory Catalog Authority

Only TaskHistory `output_assets` from the SQLite snapshot select assets under
`<runtime-root>/output/`. No whole-output scan was added. Orphan output and a
Delivery copy of a catalogued render were absent from the bundle.

## 18. Excluded Data Proof

Focused tests placed a synthetic global `dopamatrix.db` marker, another tenant
DB marker, orphan output, and Delivery-copy marker beside the source. None of
their names or bytes appeared in the bundle. The implementation does not back
up secure settings, Assignment Secret, credentials, logs, lock files, `.env`,
Ngrok state, Delivery copies, or L3 authority.

## 19. Full-File SHA-256 and Copy Consistency

The existing full-file SHA-256 and stat/copy+hash/fsync/restat/destination
verification remain unchanged with two bounded attempts. An injected source
asset mutation exhausted the retry, returned integrity exit 6, removed
staging, and left final unpublished.

## 20. Create Success Evidence

All three approved tenants created and independently verified synthetic
bundles with exact identity, one catalogued asset, and exact counts. Human
output is one bounded stdout line; JSON output is one schema-version-1 object.
No source DB absolute path is emitted.

## 21. Create Failure Evidence

Validated categories are: tenant/path policy exit 3; existing/protected state
exit 4; absent tenant source exit 5; core integrity/format/catalog failure exit
6; filesystem/SQLite/Delivery-setting subsystem exit 8; bounded unexpected
failure exit 9. No normal create path uses exit 7 because disposable staging
is cleaned.

## 22. Verify Standalone / No-Runtime Proof

A valid bundle was copied to an isolated location and the original runtime
tree removed. Verify succeeded while RuntimePaths initialization was patched
to fail. A fresh subprocess also patched both initialize and resolve seams;
`backup verify` succeeded and `src.api.database` was not imported.

## 23. Verify Read-Only Proof

Completed bundle snapshots use `mode=ro&immutable=1` for catalog, count, and
integrity reads. Before/after recursive names, sizes, mtimes, and SHA-256 were
identical for repeated success and representative failure. No tenant.db WAL,
SHM, or journal was created.

## 24. Verify Failure Matrix

Focused cases cover missing/relative bundle, missing/invalid manifest, wrong
format/application version/tenant/DB path, missing DB, DB size/hash/corruption,
asset-count/count mismatch, missing/size/hash asset, traversal/absolute member,
duplicate member, locator mismatch, catalog-shape mismatch, and manifest/
snapshot catalog mismatch. All integrity/format cases return exit 6 without
bundle mutation or RuntimePaths. Unknown unreferenced extra files remain
tolerated and non-authoritative, preserving format behavior.

## 25. Exact Error / Exit Mapping

| Condition | Symbol | Exit |
|---|---|---:|
| invalid tenant | `OPERATOR_TENANT_INVALID` | 3 |
| invalid absolute path | `OPERATOR_BACKUP_PATH_INVALID` | 3 |
| protected overlap | `OPERATOR_BACKUP_DESTINATION_PROTECTED` | 3 |
| destination exists/race | `BACKUP_DESTINATION_ALREADY_EXISTS` | 4 |
| source tenant missing | `OPERATOR_BACKUP_SOURCE_NOT_FOUND` | 5 |
| bundle missing | `OPERATOR_BACKUP_BUNDLE_NOT_FOUND` | 5 |
| core format/path/hash/catalog/integrity | existing `BACKUP_*` code | 6 |
| filesystem/SQLite/Delivery read | `OPERATOR_BACKUP_SUBSYSTEM_FAILED` | 8 |
| Runtime Root unavailable/initialization conflict | `OPERATOR_BACKUP_SUBSYSTEM_FAILED` | 8 |
| legacy runtime migration required | `LEGACY_RUNTIME_MIGRATION_REQUIRED` | 4 |
| bounded unexpected | `OPERATOR_BACKUP_INTERNAL_FAILED` | 9 |

## 26. Human / JSON Output Evidence

Human success uses stdout only and failure stderr only. JSON success/failure
uses exactly one UTF-8 object on stdout, empty stderr, schema version 1, exact
command, bounded status/error, and approved facts only. Focused tests cover
success and exits 3, 4, 5, 6, and 8.

## 27. H4-6 / H4-7 Placeholder Proof

`seed apply-safe-off`, `prearm-p3w`, `activate`, `kill`,
`set-balanced-bps`, `transition-p3a`, and `secret assignment rotate` remain
`OPERATOR_COMMAND_NOT_IMPLEMENTED`. No restore command is exposed.

## 28. Existing Backup / Restore Regression

Command:

```text
.\venv_build\Scripts\python.exe -m pytest tests/test_var001_v15_backup_restore.py -q
```

Result: `22 passed, 1 skipped, 8 subtests passed`. The skip is the POSIX-only
symlink branch on Windows. Restore remains source-compatible.

## 29. H4-2 / H4-3 / H4-4 Regression

The six-file H4 status/mutation/provision/CLI/bootstrap/packaged-console run
returned `89 passed, 138 subtests passed`, zero failures/errors.

## 30. Focused and Broad Regression Results

- H4-5 focused: `23 passed, 1 skipped, 61 subtests passed`; the skip is the
  POSIX-only symlink branch while real Windows junction cases executed.
- H2/H3/Delivery/Ledger/Reservation/Task/execution-isolation selection:
  `348 passed, 177 subtests passed`.

## 31. Full Pytest

```text
.\venv_build\Scripts\python.exe -m pytest tests -q
```

Authoritative final result: `703 passed, 2 skipped, 436 subtests passed`, zero
failures/errors. The two skips are the complementary POSIX symlink tests on
Windows. Warnings are existing framework/deprecation warnings.

## 32. Complete Changed-File Inventory

- `src/api/operator_cli.py` - lazy backup create/verify dispatch.
- `src/api/operator_backup.py` - new bounded H4-5 adapter.
- `src/api/backup_restore.py` - physical destination, no-overwrite publish,
  immutable snapshot verify, count equality, and verify import-boundary fixes.
- `src/api/delivery_output.py` - current non-writing Delivery-root reader and
  lazy tenant canonicalizer import.
- `tests/test_var001_operator_backup.py` - new focused H4-5 suite.
- four existing H4 test modules - placeholder inventories narrowed only for
  the now-implemented backup commands.
- this implementation report.
- ignored H4-5 final review bundle (not tracked/staged).

## 33. Forbidden-Scope Audit

PASS: no persisted Backup Root, no `app_settings.backup_root`, no RuntimePaths
backup field, no historical path authority, no operator project/runtime/root
override, no arbitrary tenant/lazy provision, no global DB/secret/Delivery
backup, no output scan, no mutation lock, no server shutdown, no WAL/SHM copy,
no checkpoint/journal-mode mutation, no overwrite/alias bypass/unverified
publish/staging debris, no restore/repair/live restore, no format revision, no
H4-6/H4-7/H5/H6, no Tauri/Rust/build/dependency/AGENTS/handoff/RC1 mutation.

## 34. H4-5-R1 Independent Review Fixup

Independent review reproduced a stale-read window in the sidecar-free Delivery
reader. The pre-R1 `mode=ro&immutable=1` branch checked only whether a sidecar
existed after the query. It did not prove that the main `dopamatrix.db` was the
same file in the same state, and the missing-`app_settings` branch returned
before even that sidecar check. A concurrent update/checkpoint could therefore
leave no sidecar and allow an old Delivery Root, or a stable-looking empty
value, to escape into backup destination protection.

The deterministic regression connection mutates the real sidecar-free database
at the immutable connection's close boundary. One case replaces the Delivery
value and grows the main DB; another begins without `app_settings` and creates
the table/value in that exact window. Both now raise exactly
`DELIVERY_SETTINGS_CHANGED_DURING_READ`; neither can return the immutable
reader's stale result.

The selected fix applies the accepted H4-2 observation principle only to the
sidecar-free branch:

1. stat the regular main DB and retain `st_size`, `st_mtime_ns`, `st_dev`, and
   `st_ino`;
2. prove WAL, SHM, and rollback journal are absent;
3. open `mode=ro&immutable=1`, set `query_only=ON`, and retain the row locally;
4. close SQLite without an early return for missing table or row;
5. restat the regular main DB and re-prove all three sidecars absent;
6. require exact observation equality or fail with
   `DELIVERY_SETTINGS_CHANGED_DURING_READ`;
7. only then normalize and return the row, or return empty for stable absence.

The complete pre-existing WAL+SHM branch remains `mode=ro` with
`query_only=ON`; it still sees current committed WAL state and performs no
immutable open, checkpoint, journal-mode change, sidecar deletion, or H4-3
lock. Its regression remained green.

The create adapter now catches `LegacyRuntimeMigrationRequired` before the
`RuntimePathsError` base. Legacy migration is a bounded precondition/state
result (`LEGACY_RUNTIME_MIGRATION_REQUIRED`, exit 4). Other known RuntimePaths
failures, including `RuntimeRootUnavailable` and
`RuntimePathsInitializationConflict`, are bounded subsystem results
(`OPERATOR_BACKUP_SUBSYSTEM_FAILED`, exit 8). Messages are fixed, contain no raw
path, emit no traceback, and no known RuntimePaths failure reaches exit 9.

Superseding H4-5-R1 validation:

- focused backup + Delivery:
  `53 passed, 1 skipped, 74 subtests passed`, zero failures/errors;
- required backup/H4 regression:
  `111 passed, 1 skipped, 146 subtests passed`, zero failures/errors;
- full backend authoritative retry:
  `709 passed, 2 skipped, 436 subtests passed`, zero failures/errors;
- the first full attempt had `707 passed, 2 skipped, 2 setup errors` because
  Pytest could not scan its pre-existing default `%TEMP%\pytest-of-chenp`
  directory (`WinError 5`); the identical suite reran with a fresh isolated
  temporary root, cleaned it, and produced the authoritative clean result;
- all changed/new Python files: `py_compile` exit 0;
- `git diff --check`: exit 0.

These counts supersede Sections 28-31 for H4-5-R1.

## 35. Final Git Evidence and Declarations

`py_compile` passes for every changed/new Python module. `git diff --check`
exits 0; line-ending notices are informational. The Git index remains empty.
The final raw Git evidence and complete source/test diffs are preserved in the
ignored review bundle.

```text
NO COMMIT PERFORMED
NO PUSH PERFORMED
H4_6_NOT_STARTED
NO_PACKAGED_REBUILD_PERFORMED
```

Final Codex classification:

```text
VAR001_PHASE3D2IB2B2RH45_RUNTIMEPATHS_BACKUP_CREATE_VERIFY_IMPLEMENTATION_PASS
```

Independent ChatGPT review remains required before commit, push, or H4-6.
