# Shell Completion

kanon supports tab-completion for bash and zsh via `kanon completion <shell>`.

## Preamble Overview

The generated completion script includes a preamble block that defines kanon-specific
shell helper functions used for dynamic argument lookup. These helpers are sourced once
when the completion script is loaded, and invoked each time the user presses Tab on a
supported argument position.

### How helpers work

Each helper shells out to a corresponding `kanon __complete_<name>` subcommand to
retrieve candidate lists at completion time. For example:

- `_kanon_complete_catalog_entries` -- retrieves available catalog entry names.
- `_kanon_complete_source_names_in_kanon` -- retrieves source names defined in `.kanon`.
- `_kanon_complete_names_in_lockfile` -- retrieves names recorded in the lock file.
- `_kanon_complete_catalog_versions` -- retrieves available catalog versions.
- `_kanon_complete_project_versions` -- retrieves available versions for a project URL.
- `_kanon_complete_cached_catalogs` -- retrieves locally cached catalog identifiers.

### Mid-token splitter

`_kanon_complete_add_arg` is the mid-token splitter helper used when completing
`kanon add foo@<TAB>` style arguments. The body shipped with this release is a
placeholder that calls `_kanon_complete_catalog_entries` unconditionally. The full
`@`-splitting logic is added in a subsequent task.

### Controlling completion behaviour

Two environment variables control how preamble helpers behave at completion time.
See [Configuration](configuration.md) for the full reference.

| Variable | Default | Effect |
|---|---|---|
| `KANON_COMPLETION_ENABLED` | `1` | Set to `0` to disable all completion lookups globally. |
| `KANON_COMPLETION_TIMEOUT` | `2` | Timeout in seconds for each `kanon __complete_*` subprocess call. |

### Quick start

```bash
# bash -- add to ~/.bashrc or ~/.bash_profile
eval "$(kanon completion bash)"

# zsh -- add to ~/.zshrc
eval "$(kanon completion zsh)"
```

After sourcing the script, Tab-completion is active for all kanon subcommands and
their dynamic arguments.

> The full operator guide, including fish support and troubleshooting steps,
> ships in a subsequent release.

## Cache layout

kanon maintains a local cache so that `__complete_*` subcommands can return
results from disk instead of re-fetching from git on every Tab press.  The
cache root is controlled by `KANON_CACHE_DIR` (see
[Configuration](configuration.md#kanon_cache_dir) for the full precedence
chain).

```
${KANON_CACHE_DIR}/
  catalogs/
    <sha256-of-catalog-url@ref>/
      index.txt          -- one catalog entry name per line
      tags.txt           -- one PEP 440-valid tag or branch per line
      fetched_at.txt     -- Unix epoch seconds of last remote fetch
      accessed_at.txt    -- Unix epoch seconds of last read (coalesced)
      origin.txt         -- "<url>@<ref>" sidecar for __complete_cached_catalogs
  projects/
    <sha256-of-canonical-project-repo-url>/
      tags.txt           -- one PEP 440-valid tag or branch per line
      fetched_at.txt     -- Unix epoch seconds of last remote fetch
      accessed_at.txt    -- Unix epoch seconds of last read (coalesced)
      origin.txt         -- canonical "<repo-url>"
  completion-errors.log  -- append-only log of completion-time errors
```

### File and directory permissions

All cache directories are created with mode `0700` (owner read/write/execute,
no access for group or others).  All cache files are written with mode `0600`
(owner read/write only).  Permissions are enforced via `os.chmod` after every
`mkdir` and file write, so the process umask cannot weaken them.

This implements the user-private cache requirement from spec Section 3.6
(trust model -- "Cache files are user-private").

### Entry key derivation

Cache subdirectory names are the SHA-256 hex digest of the lookup key:

- Catalog entry: `sha256("<url>@<ref>")`
- Project: `sha256("<canonical-repo-url>")`

The digest is deterministic, so the same URL and ref always map to the
same on-disk directory regardless of the calling process.

### Cache lifecycle

- **TTL:** `KANON_COMPLETION_CACHE_TTL` (default 300 s).  A cached result
  whose `fetched_at.txt` is within the TTL is returned immediately; otherwise
  a background refresh is spawned (controlled by `KANON_COMPLETION_REFRESH_BG`).
- **Coalescing:** `accessed_at.txt` is updated at most once per
  `KANON_ACCESSED_AT_COALESCE_SEC` (default 60 s) to bound I/O under rapid
  Tab-pressing.
- **Pruning:** `kanon doctor --prune-cache` removes entries whose
  `accessed_at.txt` is older than `KANON_CACHE_PRUNE_AGE_DAYS` (default 30 d).

### Error log

Errors that occur inside `__complete_*` subcommands are written to
`completion-errors.log` (one line per error) in the format:

```
<ISO-8601-UTC> <completer-name> <ErrorClass>: <message>
```

The log is append-only and never rotated automatically.  Run
`kanon doctor --prune-cache` to truncate it.  The path can be overridden via
`KANON_COMPLETION_LOG`.
