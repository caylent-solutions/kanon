# Kanon Architecture: Install Engine Internals

## Overview

This document describes the internals of the `kanon install` engine -- the
embedded repo-fork install pipeline, the lockfile state machine, the directory
layout under the install workspace, and the error-propagation contract.

For operator-facing usage, see `docs/lifecycle.md`. For the lockfile schema,
see `docs/lockfile.md`. For configuration, see `docs/configuration.md`.

---

## Embedded Repo Fork

Kanon bundles a fork of the `repo` tool (Google repo) under
`src/kanon_cli/repo/`. No external `repo` binary is required -- the fork is
part of the kanon wheel and is invoked via the Python API in
`src/kanon_cli/core/install.py`.

**Why kanon does not use an external repo tool.** The bundled fork allows kanon
to pin a specific, tested version of repo and avoid incompatibilities between
the upstream tool's rolling releases and kanon's expectations. The fork is
treated as a vendored dependency; it is NOT modified by kanon feature work and
is carved out from mypy and bandit scopes per `CLAUDE.md`.

---

## Install Workspace Directory Layout

After `kanon install` completes, the project directory contains:

```
<project-root>/
  .kanon                    # operator-authored config file
  .kanon.lock               # generated lockfile (commit this)
  .kanon-data/
    .kanon-install.lock     # fcntl exclusive lock (harmless if stale)
    sources/
      <source-name>/        # one directory per top-level source
        .repo/              # managed by the embedded repo fork
        ...                 # cloned project directories
        .packages/          # per-source package symlinks
  .packages/                # top-level aggregated package symlinks
  .gitignore                # updated by kanon install (idempotent)
```

The `.kanon-data/sources/<name>/.packages/` directories are populated by
`repo sync`. The top-level `.packages/` directory is populated by
`aggregate_symlinks` in `core/install.py`, which creates symlinks from each
per-source `.packages/*` entry to the top-level directory.

Operators MUST treat the `.kanon-data/` directory layout as opaque. Use the
lockfile as the source of truth for which clones exist. If the directory
becomes inconsistent (e.g. after a SIGTERM mid-clone), run
`kanon clean --orphans` to prune and recover.

---

## Install Engine Steps (spec Section 4.7.1)

The engine is implemented in `core/install.py::_run_install` (inner) and
`core/install.py::install` (outer, acquires the concurrency lock). Steps:

1. **Classify lockfile state.** Call `_classify_install_state(kanon_path, lockfile_path)` to determine which of the five state-machine rows applies.
2. **Resolve catalog source.** Call `_resolve_catalog_source(...)` to determine the effective catalog source following the three-tier precedence rule. `MissingCatalogSourceError` is raised unconditionally when all three sources are unset.
3. **Resolve top-level sources.** Parse `.kanon` triples via `parse_kanonenv`. In the `LOCKFILE_ABSENT` state, resolve each source URL and revision to a concrete git ref + SHA via `git ls-remote`. In the `LOCKFILE_CONSISTENT` state, skip fresh resolution and replay the pinned SHAs from the lockfile instead (one git ls-remote call per source to verify SHA reachability; no version re-resolution via the catalog).
4. **Create per-source workspaces** under `.kanon-data/sources/<source-name>/`. Fail fast with `OSError` if any directory cannot be created.
5. **`repo init`** per source -- `repo init -u <url> -b <resolved-revision> -m <manifest-path>` via `kanon_cli.repo.repo_init`. Raises `RepoCommandError` on non-zero exit.
6. **`repo envsubst`** -- expands `${GITBASE}` and `${CLAUDE_MARKETPLACES_DIR}` references inside the manifest XML.
7. **`repo sync`** per source -- clones each `<project>` at the resolved SHA. Walks `<include>` chains transitively.
8. **Aggregate symlinks** into `.packages/` via `aggregate_symlinks`. Raises `ValueError` on package name collision.
9. **Update `.gitignore`** with `.packages/` and `.kanon-data/` (idempotent append).
10. **Emit info-line.** Call `_emit_install_state(state, sources, projects)` to print the spec's verbatim status line (after aggregate symlinks so the project count is known).
11. **Marketplace install** (gated on `KANON_MARKETPLACE_INSTALL=true`; runs in `LOCKFILE_ABSENT` and `LOCKFILE_CONSISTENT` states only -- hard-error states exit before reaching this step): clean and populate `CLAUDE_MARKETPLACES_DIR`, then run `install_marketplace_plugins`.
12. **Write `.kanon.lock`** atomically (write-temp-then-rename) via `write_lockfile`. Runs only in the `LOCKFILE_ABSENT` state (the lockfile is generated for the first time). In the `LOCKFILE_CONSISTENT` state the lockfile is authoritative and is **not** rewritten. Hard-error states (`LOCKFILE_HASH_MISMATCH`, `LOCKFILE_UNREACHABLE`, `LOCKFILE_SOURCE_MISMATCH`) raise before reaching this step.

---

## Lockfile State Machine (spec Section 4.7)

Every `kanon install` invocation runs through the five-row state matrix below.
The state is determined by `_classify_install_state(kanon_path, lockfile_path)`
which returns an `InstallClassification` NamedTuple containing `state`, `computed_hash`, and `lockfile` fields.

### State Matrix

| State | Condition | Behaviour | Error class | Remediation |
|-------|-----------|-----------|-------------|-------------|
| `LOCKFILE_ABSENT` | `.kanon.lock` does not exist | Resolve every transitive version fresh. Install. Write `.kanon.lock` capturing resolved SHAs + catalog source + `kanon_hash`. Emit info-line: `"lockfile rebuilt from .kanon (N sources, M projects)"`. | -- | -- |
| `LOCKFILE_CONSISTENT` | `.kanon.lock` exists AND `kanon_hash` in lockfile matches freshly-computed `kanon_hash(.kanon)` | Install EXACTLY the SHAs in the lockfile. Do NOT re-resolve. Ignore newer tags. Emit info-line: `"installing from lockfile (N sources, M projects)"`. Catalog source MAY be read from `lockfile.[catalog].source` when no CLI/env source is set. | -- | -- |
| `LOCKFILE_HASH_MISMATCH` | `.kanon.lock` exists but `kanon_hash` does not match | Hard error. | `KanonHashMismatchError` | `kanon install --refresh-lock` or `--refresh-lock-source <name>` |
| `LOCKFILE_UNREACHABLE` | Resolver discovers a lockfile SHA is no longer reachable on remote | Hard error. Names the source, SHA, and remote URL. | `LockfileUnreachableShaError` | `kanon install --refresh-lock-source <name>` |
| `LOCKFILE_SOURCE_MISMATCH` | `lockfile.[catalog].source` differs from CLI/env catalog source (when CLI/env is set) | Hard error. Names both values. The lockfile is authoritative. | `CatalogSourceMismatchError` | `kanon install --refresh-lock` |
| `REFRESH_LOCK` | Operator passed `--refresh-lock` | Short-circuit: ignore lockfile state entirely. Resolve every transitive version fresh. Overwrite `.kanon.lock`. Emit info-line: `"lockfile rebuilt from .kanon (N sources, M projects)"`. Lockfile catalog-source fallback is DISABLED on this path. | -- | Requires CLI or env-var catalog source. |
| `REFRESH_LOCK_SOURCE` | Operator passed `--refresh-lock-source <name>` | Short-circuit: re-resolve exactly the named source's chain while preserving every other lockfile entry verbatim. Emit info-line: `"lockfile partially rebuilt: source <name> (M projects refreshed; K projects preserved)"`. Lockfile catalog-source fallback is DISABLED on this path. `<name>` is resolved by literal KANON_SOURCE key first, then via `derive_source_name`. Raises `UnknownSourceError` if neither matches. | `UnknownSourceError` | Requires CLI or env-var catalog source; use a known source name or catalog entry name. |

### State Classification Logic

`_classify_install_state` returns an `InstallClassification(state, computed_hash, lockfile)`
NamedTuple -- not a bare `InstallState` enum -- so the caller receives the pre-computed
hash and parsed lockfile without needing to recompute them.

```
_classify_install_state(kanon_path, lockfile_path, refresh_lock=False) -> InstallClassification:
  if refresh_lock:
    return InstallClassification(REFRESH_LOCK, computed_hash=None, lockfile=None)
  if lockfile_path does not exist:
    return InstallClassification(LOCKFILE_ABSENT, computed_hash=None, lockfile=None)
  lockfile = read_lockfile(lockfile_path)
  computed_hash = kanon_hash(kanon_path)
  if computed_hash == lockfile.kanon_hash:
    return InstallClassification(LOCKFILE_CONSISTENT, computed_hash, lockfile)
  return InstallClassification(LOCKFILE_HASH_MISMATCH, computed_hash, lockfile)
```

The `LOCKFILE_UNREACHABLE` and `LOCKFILE_SOURCE_MISMATCH` states are detected
later in the pipeline (during resolver output analysis and catalog-source
validation) and are surfaced as exceptions rather than `InstallState` values.

The `REFRESH_LOCK` state is triggered by the `--refresh-lock` CLI flag
(`refresh_lock=True` kwarg). It short-circuits the normal hash comparison,
returning `REFRESH_LOCK` regardless of lockfile presence or hash state. The
`computed_hash` and `lockfile` fields are `None` in this state (the lockfile is
ignored entirely). The `--refresh-lock` flag is mutually exclusive with
`--refresh-lock-source` at the argparse level.

The `REFRESH_LOCK_SOURCE` state is triggered by the `--refresh-lock-source <name>`
CLI flag (`refresh_lock_source=<name>` kwarg). The existing lockfile is read for
the partial merge: all other sources' entries are preserved verbatim. The name is
resolved in two steps -- literal KANON_SOURCE key match first, then via
`derive_source_name` normalisation. Raises `UnknownSourceError` if neither step
matches. The `--refresh-lock-source` flag is mutually exclusive with `--refresh-lock`.

---

## Catalog-Source Precedence (spec Section 4 header)

`_resolve_catalog_source` implements the three-tier precedence rule:

1. **`--catalog-source` CLI flag** -- highest priority. Passed as `cli_arg`.
   **Note:** `--catalog-source` is not yet registered on the `kanon install`
   subcommand (pending task E1-F4-S1-T1). Currently only `KANON_CATALOG_SOURCE`
   and the lockfile fallback are active for `kanon install`.
2. **`KANON_CATALOG_SOURCE` env var** -- second priority. Passed as `env_value`.
3. **`lockfile.[catalog].source`** -- lockfile fallback. Applies ONLY in the
   `LOCKFILE_CONSISTENT` state and ONLY when both CLI flag and env var are
   unset. This is the documented exception to the NO-FALLBACK rule.

**Special case: `REFRESH_LOCK` state.** When `install_state == REFRESH_LOCK`
(i.e. `--refresh-lock` was passed), the lockfile fallback (tier 3) is DISABLED.
The operator MUST supply a catalog source via CLI or env var. If neither is set,
`MissingCatalogSourceError` is raised with the refresh-specific remediation text:
`"--refresh-lock requires a CLI or env-var catalog source; the lockfile fallback
is disabled on this path."` This constraint prevents silent reuse of a stale
catalog source when the operator is explicitly rebuilding the lockfile.

When CLI/env is set and differs from the lockfile's recorded source, a
`CatalogSourceMismatchError` is raised (the lockfile is authoritative; the
operator must explicitly refresh to change catalogs).

When all three sources are unset (or the lockfile fallback is inapplicable),
`MissingCatalogSourceError` is raised with the spec's canonical error text.
See `docs/configuration.md` for how to configure a catalog source.

---

## Exception Classes

All install-state hard errors inherit from `InstallError(Exception)`:

| Exception class | Raised when | Key fields |
|-----------------|-------------|------------|
| `KanonHashMismatchError` | `.kanon` has been modified since the lockfile was written (`LOCKFILE_HASH_MISMATCH` state). | `lockfile_hash`, `computed_hash` |
| `LockfileUnreachableShaError` | A lockfile SHA is no longer reachable on the remote (`LOCKFILE_UNREACHABLE` state). | `source_name`, `sha`, `remote_url` |
| `CatalogSourceMismatchError` | CLI/env catalog source differs from lockfile's `[catalog].source` (`LOCKFILE_SOURCE_MISMATCH` state). | `lockfile_source`, `cli_env_source` |
| `MissingCatalogSourceError` | No catalog source is available from CLI, env, or lockfile fallback. | `command` |
| `UnknownSourceError` | `--refresh-lock-source <name>` does not match any known source by direct lookup or `derive_source_name`. | `name`, `known_names` |

Each exception's `__str__` renders in the spec's standard three-line error
shape: `ERROR: <one-line summary>`, optional context lines (wrapped at 80
columns), and a remediation line.

---

## Retry Policy

`git ls-remote` calls inside the embedded repo fork
(`src/kanon_cli/repo/project.py::_run_ls_remote_with_retry`) are retried up
to `KANON_GIT_RETRY_COUNT` times (default 3) with a delay of
`KANON_GIT_RETRY_DELAY` seconds (default 1) between attempts. Authentication
errors are not retried. `repo init` and `repo sync` calls from
`core/install.py` are single-shot and not retried via this mechanism.

---

## Concurrency Serialization

`install` acquires an exclusive `fcntl.flock(LOCK_EX)` on
`.kanon-data/.kanon-install.lock` before performing any filesystem mutations.
This serializes concurrent `kanon install` invocations on the same project
directory. The lock is released automatically on process exit; a stale lock
file left by a killed process is harmless.

---

## Atomicity Contract

Writes to the lockfile use a write-temp-then-rename pattern (see
`core/lockfile.py::write_lockfile` and `docs/lockfile.md` for details). A
SIGTERM mid-install leaves either the prior lockfile or the new lockfile,
never a partial file.

Per-project clones (which touch many files in `.kanon-data/sources/<name>/`)
are NOT atomic in aggregate. A SIGTERM during a `repo sync` may leave a
partially-cloned project directory. Use `kanon clean --orphans` to recover.

---

## Error-Propagation Contract

- `install` (outer): acquires the concurrency lock; raises `OSError` if the
  `.kanon-data/` directory cannot be created.
- `_run_install` (inner): propagates all exceptions from sub-steps without
  catching and discarding. Callers see the original exception type.
- Library code (all functions in `core/install.py`) NEVER calls `sys.exit()`.
  Only CLI command handlers in `src/kanon_cli/commands/` or `cli.py` exit.
- Every error path produces a clear, actionable message sent to stderr. No
  silent failures, no swallowed exceptions.
