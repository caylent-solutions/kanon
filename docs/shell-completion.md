# Shell Completion

kanon supports tab-completion for bash and zsh via `kanon completion <shell>`.

## Preamble Overview

The generated completion script includes a preamble block that defines
kanon-specific shell helper functions used for dynamic argument lookup.
These helpers are sourced once when the completion script is loaded, and
invoked each time the user presses Tab on a supported argument position.

### How helpers work

Each helper shells out to a corresponding `kanon __complete_<name>`
subcommand to retrieve candidate lists at completion time. For example:

- `_kanon_complete_catalog_entries` -- retrieves available catalog entry
  names.
- `_kanon_complete_source_names_in_kanon` -- retrieves source names defined
  in `.kanon`.
- `_kanon_complete_names_in_lockfile` -- retrieves names recorded in the
  lock file.
- `_kanon_complete_catalog_versions` -- retrieves available catalog
  versions.
- `_kanon_complete_project_versions` -- retrieves available versions for a
  project URL.
- `_kanon_complete_cached_catalogs` -- retrieves locally cached catalog
  identifiers.

### Mid-token splitter

`_kanon_complete_add_arg` is the mid-token splitter helper used when
completing `kanon add foo@<TAB>` style arguments. The body shipped with
this release is a placeholder that calls `_kanon_complete_catalog_entries`
unconditionally. The full `@`-splitting logic is added in a subsequent
task.

### Controlling completion behaviour

Two environment variables control how preamble helpers behave at completion
time. See [Configuration](configuration.md) for the full reference.

| Variable                   | Default | Effect                                |
| -------------------------- | ------- | ------------------------------------- |
| `KANON_COMPLETION_ENABLED` | `1`     | Set to `0` to disable all lookups.    |
| `KANON_COMPLETION_TIMEOUT` | `2`     | Timeout (seconds) per subprocess.     |

### Quick start

```bash
# bash -- add to ~/.bashrc or ~/.bash_profile
eval "$(kanon completion bash)"

# zsh -- add to ~/.zshrc
eval "$(kanon completion zsh)"
```

After sourcing the script, Tab-completion is active for all kanon
subcommands and their dynamic arguments.

> The full operator guide, including fish support and troubleshooting steps,
> ships in a subsequent release.

## Cache layout

kanon maintains a local cache so that `__complete_*` subcommands can return
results from disk instead of re-fetching from git on every Tab press. The
cache root is controlled by `KANON_CACHE_DIR` (see
[Configuration](configuration.md#kanon_cache_dir) for the full precedence
chain).

```text
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
no access for group or others). All cache files are written with mode `0600`
(owner read/write only). Permissions are enforced via `os.chmod` after every
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

- **TTL:** `KANON_COMPLETION_CACHE_TTL` (default 300 s). A cached result
  whose `fetched_at.txt` is within the TTL is returned immediately;
  otherwise a background refresh is spawned (controlled by
  `KANON_COMPLETION_REFRESH_BG`).
- **Coalescing:** `accessed_at.txt` is updated at most once per
  `KANON_ACCESSED_AT_COALESCE_SEC` (default 60 s) to bound I/O under
  rapid Tab-pressing.
- **Pruning:** `kanon doctor --prune-cache` removes entries whose
  `accessed_at.txt` is older than `KANON_CACHE_PRUNE_AGE_DAYS`
  (default 30 d).

### Error log

Errors that occur inside `__complete_*` subcommands are written to
`completion-errors.log` (one line per error) in the format:

```text
<ISO-8601-UTC> <completer-name> <ErrorClass>: <message>
```

The log is append-only and never rotated automatically. Run
`kanon doctor --prune-cache` to truncate it. The path can be overridden via
`KANON_COMPLETION_LOG`.

## Dynamic completers

This section documents the individual `kanon __complete_*` subcommands that
back the shell helper functions described in the Preamble Overview.

### `__complete_catalog_entries`

**Subcommand:** `kanon __complete_catalog_entries [<prefix>]`

**Purpose:** Returns the list of catalog entry names available for
tab-completion. Entries are read from the local cache populated by prior
`kanon` invocations or explicit cache-warming commands.

**Source:** Entry names are sourced from `repo-specs/**/*-marketplace.xml`
files in the configured catalog repository. Each `<entry>` element name
in those XML files is eligible as a completion candidate.

**Cache file consulted:**
`${KANON_CACHE_DIR}/catalogs/<sha256>/index.txt`

where `<sha256>` is `sha256("<catalog-url>@<ref>")`. The file contains one
entry name per line with no surrounding whitespace.

**Prefix-match filtering:** When a `<prefix>` argument is supplied, only
entry names that begin with that prefix (case-sensitive) are written to
stdout. When no prefix is supplied all cached entry names are returned.

**Stdout / stderr contract:**

- On success: matching entry names, one per line, written to stdout.
  Exit code 0.
- On cache miss or any lookup failure: nothing written to stdout (silent
  on stdout). The error detail is appended to `completion-errors.log`
  and, if the shell session's stderr is a tty, a brief diagnostic line is
  written to stderr. Exit code 0 (failure-quiet on stdout,
  failure-loud on stderr).

This contract ensures that a stale or absent cache never injects garbage
into the completion menu -- the shell sees an empty candidate list and
falls back to filename completion rather than displaying an error.

**Disabling:** Set `KANON_COMPLETION_ENABLED=0` in the shell environment
to skip the subprocess call entirely. The helper function returns
immediately with no output, leaving completion to the static argument
list generated by the completion script.

```bash
# Disable dynamic catalog-entry completions for the current session
export KANON_COMPLETION_ENABLED=0
```
