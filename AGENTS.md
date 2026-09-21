# DopaMatrix Codex Project Rules

This file contains repository-level, long-lived rules for Codex and other coding agents working on DopaMatrix.

It is intentionally limited to durable engineering constraints. Current phase status, Git anchors, closed phases, and Immediate Next Action belong in the rolling `handoffs.md`, not here.

---

## 1. Authority and Scope

- Treat the repository-root `AGENTS.md` as a persistent engineering rule set.
- Treat the current `handoffs.md` as the authoritative rolling project-state entry when a task explicitly references it.
- Treat task-specific Codex instructions as the authority for the current implementation slice.
- Do not reopen frozen architecture or closed phases unless the current task explicitly authorizes it or new failing evidence requires reopening.
- Do not expand scope beyond the explicitly authorized implementation slice.

If instructions conflict, stop and report the conflict instead of guessing.

---

## 2. Git Safety Rule

Unless the current task explicitly authorizes Git mutation:

- do not run `git add`;
- do not commit;
- do not push;
- do not create, move, delete, or recreate tags;
- do not switch branches;
- do not overwrite unrelated work.

Before implementation work, verify the expected branch, HEAD, worktree state, and index state when the task provides expected anchors.

If the tracked worktree is unexpectedly dirty, stop and report the unexpected paths before editing.

Ignored local review evidence under `.codex-local/` must not be staged unless a task explicitly says otherwise.

---

## 3. Build Toolchain Rule

Any task that invokes Node, npm, frontend build, Vite build, Tauri build, packaging, installer build, or another Node-dependent build step MUST verify the effective Node/npm executable path and version before starting the build.

Run:

```powershell
where.exe node
where.exe npm
node -v
npm -v
```

Authoritative Node installation for this development machine:

```text
C:\Users\chenp\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.22_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v22.23.1-win-x64
```

Current expected versions:

```text
Node: v22.23.1
npm:  10.9.8
```

The first effective `node` and `npm` executables MUST resolve to the authoritative WinGet Node installation above.

Do NOT fall back to browser-bundled, application-bundled, embedded, incidental, or otherwise unrelated Node runtimes, including runtimes found under paths such as:

- `secoresdk`;
- `360se6`;
- browser component directories;
- application component directories.

If the effective Node/npm toolchain does not match the authoritative installation:

```text
BUILD_TOOLCHAIN_MISMATCH
```

STOP BEFORE BUILD.

Do not search for and silently substitute another Node installation.
Do not install, upgrade, downgrade, remove, or modify Node/npm without explicit authorization.

This preflight is required only for tasks that actually invoke a Node/npm-dependent build. It is not required for Python-only tests, documentation-only work, source-only analysis, or Git-only tasks.

---

## 4. Build Toolchain Provenance Rule

For release, packaging, Tauri, installer, or other build evidence, record:

- effective executable paths;
- Node version;
- npm version;
- project-local Tauri CLI version when applicable;
- Python version when applicable;
- PyInstaller version when applicable;
- Rust and Cargo versions when applicable;
- the exact build command.

A build performed with an incidental, browser-bundled, application-bundled, or otherwise unauthorized toolchain does not qualify as authoritative release evidence.

When a toolchain version is intentionally upgraded in the future, update this file in a separate reviewed change rather than silently accepting a newly discovered executable.

---

## 5. Dependency Mutation Rule

Do not run dependency-mutating commands merely to make a build pass unless the current task explicitly authorizes dependency changes.

Examples include:

```text
npm install
npm update
npm audit fix
cargo update
pip install
pip install --upgrade
```

Do not modify:

- `package.json`;
- `package-lock.json`;
- `Cargo.toml`;
- `Cargo.lock`;
- Python dependency lock/requirements files;

unless dependency changes are explicitly in scope.

Prefer the repository's existing locked dependencies and project-local tooling.

If an expected dependency/tool is missing, report the missing prerequisite instead of silently installing or upgrading it.

---

## 6. Isolated Packaging / Release-Build Rule

Packaging or release-build workflows that can delete files, kill processes, mutate databases, reset output, or generate large build artifacts MUST use an isolated disposable worktree or staging directory when the task requires such execution.

Do not run a known-destructive release preparation directly in the primary development worktree.

Before any build step capable of terminating processes:

- inspect the relevant running processes;
- do not terminate unrelated user/developer processes;
- stop if safe isolation cannot be established.

Build/runtime artifacts must not be copied back into the primary worktree unless the task explicitly requires a tracked artifact.

---

## 7. Primary Worktree Contamination Rule

After isolated build, packaging, or runtime smoke work, verify the primary worktree.

Look for unintended changes or artifacts such as:

- `build/`;
- `dist/`;
- generated `*.spec`;
- Tauri `target/`;
- generated sidecar binaries;
- runtime databases;
- WAL/SHM files;
- runtime logs;
- output media;
- `.env` changes;
- backup artifacts.

Only task-authorized source, test, and evidence/report changes may remain.

Do not delete pre-existing user/project data while cleaning test artifacts.

---

## 8. Evidence Rule

A Codex PASS or implementation summary is not the final project gate when the task assigns ChatGPT as independent reviewer.

For implementation slices, return the evidence requested by the task, typically including:

- changed-file inventory;
- exact test commands;
- exact pass/skip/fail/error counts;
- relevant runtime/build proof;
- `git diff --stat`;
- `git status --short`;
- ignored review-bundle proof when required.

Do not claim an independent ChatGPT FINAL PASS.

---

## 9. Source and Secret Safety

Do not print, log, expose, or place into review evidence:

- API keys;
- auth tokens;
- Assignment Secret values;
- secret hashes/prefixes/suffixes;
- DPAPI ciphertext;
- secret-derived intermediates;
- credentials from `.env` or operating-system secure storage.

Do not inspect secret values unless a task explicitly and safely requires it.

---

## 10. Minimal-Change Rule

Prefer the smallest change that satisfies the accepted contract.

Do not use a bounded implementation task as an opportunity to:

- refactor unrelated code;
- clean unrelated configuration;
- upgrade dependencies;
- redesign architecture;
- implement later phases;
- fix unrelated UI or release issues.

If a required fix would cross the current phase boundary, stop and report the blocker for independent review.

---

## 11. Windows Build Environment Rule

For Windows-specific build or runtime proof:

- use real PowerShell/cmd behavior when the contract requires it;
- do not substitute source inference for a required packaged-runtime proof;
- do not use an incidental Node runtime simply because it is discoverable;
- prefer machine-auditable evidence over visual-only observations when proving process/window behavior.

---

## 12. Long-Lived Rule Maintenance

Keep this file limited to durable repository-level rules.

Do NOT put the following here:

- current phase;
- current HEAD;
- current origin commit;
- current release blocker list;
- Immediate Next Action;
- temporary investigation findings.

Those belong in `handoffs.md` or phase-specific investigation/report artifacts.

Changes to this file should be deliberate, reviewed, and committed separately when practical.
