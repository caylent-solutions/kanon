# Kanon Architecture: Install Engine Internals

This document describes the internals of the `kanon install` engine for
**kanon contributors** and **advanced operators** who want to understand what
happens during `kanon install`.

For operator-facing usage see `docs/lifecycle.md`.
For the lockfile schema see [`docs/lockfile.md`](lockfile.md).
For configuration see [`docs/configuration.md`](configuration.md).
For the security model see [`docs/security-model.md`](security-model.md).

---

## Audience

This document is written for two audiences:

- **Kanon contributors** working on the install engine, lockfile state machine,
  or the embedded repo-fork carve-out (`src/kanon_cli/repo/`).
- **Advanced operators** who need to understand the exact directory layout
  produced by `kanon install`, the lockfile-to-clone mapping, the retry
  policy, and the error-propagation contract so they can diagnose failures
  without opening the source code.

Operators who only need day-to-day usage guidance should read
[`docs/lifecycle.md`](lifecycle.md) instead.

---

## Embedded repo-fork install engine

Kanon vendors a fork of Google's `repo` tool at `src/kanon_cli/repo/`.

### Vendored carve-out

The fork is shipped as part of the kanon wheel. No external `repo` binary is
required or used. The vendored path is a declared scope carve-out in
`CLAUDE.md`: mypy and bandit do not check `src/kanon_cli/repo/`. This
carve-out is a scope demarcation, not a bypass annotation; it must not be
extended to any other path.

Operators never invoke `repo` directly. The CLI entry points are
`kanon install`, `kanon add`, and `kanon remove`. The embedded fork is an
implementation detail.

### Call sequence

For each source listed in the resolved lockfile, `core/install.py` calls the
fork in three steps:

1. **`repo_init`** -- initialises a repo workspace inside
   `.kanon-data/sources/<name>/` using the manifest XML URL and the resolved
   revision. Raises `RepoCommandError` on non-zero exit.

2. **`repo_envsubst`** -- expands `${GITBASE}` and `${CLAUDE_MARKETPLACES_DIR}`
   variable references inside the manifest XML before sync.

3. **`repo_sync`** -- clones every `<project>` referenced by the manifest XML
   at the locked SHA. Walks `<include>` chains transitively. Raises
   `RepoCommandError` on non-zero exit.

All three functions are defined in `src/kanon_cli/repo/` and are called
exclusively from `core/install.py::_run_install`.

---

## Directory layout

After `kanon install` completes, the project directory contains the following
layout. Operators must treat `.kanon-data/` as opaque; use `.kanon.lock` as
the source of truth for which clones exist.

```text
<project-root>/
  .kanon                        # operator-authored config file
  .kanon.lock                   # generated lockfile (commit this)
  .gitignore                    # auto-updated by kanon install (idempotent)
  .kanon-data/
    .kanon-install.lock         # flock-managed concurrency lock
    sources/
      <source-name>/            # one directory per top-level source
        .repo/                  # managed by the embedded repo fork
        <project-dir>/          # cloned project directories
        .packages/              # per-source package symlinks
  .packages/                    # aggregated symlinks (operator-facing)
```

Key paths:

- **`.kanon-data/sources/<name>/`** -- per-source workspace holding the
  manifest XML, transitive includes, and repo state. One directory per
  top-level source declared in `.kanon`.
- **`.kanon-data/.kanon-install.lock`** -- `fcntl.flock(LOCK_EX)` file.
  All workspace-mutating commands acquire this lock before any filesystem
  mutation. A stale lock left by a killed process is harmless; the next
  invocation reopens and re-acquires it.
- **`.packages/`** -- aggregated symlinks pointing into the per-source
  `.packages/*` entries. This is the only directory operators need to
  reference in downstream tooling.
- **`.gitignore`** -- `kanon install` appends `.packages/` and
  `.kanon-data/` (idempotent; no duplicate entries are written).

If the `.kanon-data/` directory layout becomes inconsistent (for example after
a SIGTERM mid-clone), run `kanon clean` to prune and recover.

---

## Lockfile-to-clone mapping

For each `[[sources]]` entry in `.kanon.lock`, the install engine:

1. Reads the locked SHA from `lockfile.sources[n].resolved_sha`.
2. Creates `.kanon-data/sources/<name>/` if it does not exist.
3. Calls `repo_init` with the manifest URL and the locked SHA, initialising
   a repo workspace inside `.kanon-data/sources/<name>/`.
4. Calls `repo_sync` to clone every `<project>` referenced by the manifest
   XML at exactly the locked SHA. Transitive `<include>` chains are walked
   fully.
5. Symlinks from `.kanon-data/sources/<name>/.packages/*` are aggregated
   into the top-level `.packages/` directory by `aggregate_symlinks` in
   `core/install.py`. A `ValueError` is raised immediately on package name
   collision.

In the `LOCKFILE_CONSISTENT` state (hash unchanged), locked SHAs are
replayed verbatim from the lockfile. No version re-resolution via the
catalog occurs. One `git ls-remote` call per source verifies SHA
reachability; if a SHA is no longer reachable a `LockfileUnreachableShaError`
is raised naming the source, SHA, and remote URL.

In the `LOCKFILE_ABSENT` state, each source URL and revision is resolved to
a concrete git ref and SHA via `git ls-remote` before `repo_init` is called.
The resulting SHAs are written to `.kanon.lock` atomically at the end of the
install step (write-temp-then-rename).

Cross-reference: [`docs/lockfile.md`](lockfile.md) describes the lockfile
TOML schema and the `kanon_hash` field in detail.

---

## Retry policy

`git ls-remote` calls inside the embedded repo fork
(`src/kanon_cli/repo/project.py::_run_ls_remote_with_retry`) are retried up
to `KANON_GIT_RETRY_COUNT` times (default 3). The delay before each retry
uses exponential backoff: `delay = KANON_GIT_RETRY_DELAY * (2 ** (attempt -
1))`, where `KANON_GIT_RETRY_DELAY` (default 1 second) is the base delay.
Attempt 1 waits the base delay; attempt 2 waits twice that; attempt 3 waits
four times that.

`KANON_GIT_RETRY_DELAY` is the **only** sleep-based wait in non-vendored
kanon code. The vendored fork at `src/kanon_cli/repo/` also contains a
separate exponential-backoff sleep inside `retry_fetches` (controlled by
`KANON_MAX_RETRY_SLEEP_SEC` and `KANON_RETRY_JITTER_PERCENT`), but that code
is inside the vendored carve-out and is not part of the kanon source
surface. Every other synchronization mechanism in non-vendored kanon code
uses readiness detection or event-driven callbacks.

**Authentication-error bypass.** When the `git ls-remote` stderr output
matches any pattern in `GIT_AUTH_ERROR_PATTERNS` (defined in
`src/kanon_cli/constants.py`), the retry loop exits immediately and the
error is surfaced without further attempts. Retrying an auth failure would
only produce identical failures and waste time.

`repo_init` and `repo_sync` calls from `core/install.py` are single-shot
and are not retried by this mechanism.

Both `KANON_GIT_RETRY_COUNT` and `KANON_GIT_RETRY_DELAY` are read at call
time from the environment; their defaults are defined in
`src/kanon_cli/constants.py` (`GIT_RETRY_COUNT_DEFAULT` and
`GIT_RETRY_DELAY_DEFAULT`).

---

## Error propagation

Every git stderr line produced by the embedded engine is surfaced verbatim
to the operator's terminal with a prefix identifying the source name, for
example:

```text
[source: my-org-packages] error: Repository not found.
[source: my-org-packages] fatal: Could not read from remote repository.
```

The full error-propagation contract:

- `install` (outer): acquires the concurrency lock via
  `kanon_workspace_lock`; raises `OSError` if `.kanon-data/` cannot be
  created.
- `_run_install` (inner): propagates all exceptions from sub-steps without
  catching and discarding. Callers see the original exception type.
- Library code in `core/install.py` never calls `sys.exit()`. Only CLI
  command handlers in `src/kanon_cli/commands/` or `cli.py` exit.
- Every error path produces a clear, actionable message sent to stderr. No
  silent failures, no swallowed exceptions.

Hard-error states (`LOCKFILE_UNREACHABLE`, `LOCKFILE_SOURCE_MISMATCH`)
raise typed exception subclasses of `InstallError(Exception)` before any
filesystem mutation occurs. A `kanon_hash` mismatch is NOT a hard error
on plain install: it derives the `RECONCILE` state and reconciles
`.kanon` against the lockfile npm-style (prune orphans, resolve
added/changed sources, replay unchanged ones, write the rebuilt lock once
on success). Under `--strict-lock` the mismatch is a hard error
(`OrphanedLockEntryError` for a pure removal, otherwise
`KanonHashMismatchError`) and the lockfile is never mutated. Each
exception renders in the spec's standard three-line shape:

```text
ERROR: <one-line summary>
<context lines wrapped at 80 columns>
Remediation: <operator next step>
```

Cross-reference: [`docs/security-model.md`](security-model.md) describes
which errors are never silenced for security reasons.

---

## Why kanon doesn't use an external repo tool

Kanon vendors the `repo` fork rather than depending on the system `repo`
binary for the following reasons:

1. **Deterministic install behaviour.** A vendored fork is pinned to a
   specific, tested revision. Upstream `repo` has a rolling release model;
   depending on the system binary would expose kanon to unexpected breakage
   from operator-controlled upgrades.

2. **No external binary dependency.** Operators do not need to install or
   manage a separate `repo` tool. The kanon wheel is self-contained. This
   simplifies CI pipelines and reduces the operator's setup burden.

3. **Controlled error reporting.** The fork exposes a Python API
   (`repo_init`, `repo_envsubst`, `repo_sync`) that allows kanon to capture
   stderr verbatim and prefix it with the source name before surfacing it to
   the operator. A subprocess call to an external binary would make this
   structured forwarding harder.

4. **No provider-specific tooling.** Per spec Section 3.6, kanon never calls
   provider HTTP APIs (`api.github.com`, `gitlab.com/api`, etc.) and never
   shells out to provider CLIs (`gh`, `glab`, `bb`, `tea`). All git
   interaction is via the `git` binary only. Vendoring `repo` keeps this
   boundary clean; there is no temptation to use provider-specific
   extensions bundled with third-party repo tools.

---

## See also

- [`docs/lockfile.md`](lockfile.md) -- lockfile TOML schema, `kanon_hash`
  field, and the five-row install state matrix.
- [`docs/configuration.md`](configuration.md) -- all environment variables,
  including `KANON_CATALOG_SOURCE` and `KANON_GIT_LS_REMOTE_TIMEOUT`.
- [`docs/security-model.md`](security-model.md) -- the no-provider-API rule,
  the no-credentials-caching rule, and the auth-error pattern list.
