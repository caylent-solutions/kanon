# Shell Completion

kanon supports tab-completion for bash and zsh via `kanon completion <shell>`.

## Bash version requirement

kanon's generated bash completion script requires **bash 4.0 or later**.
The macOS stock shell (`/bin/bash`, bash 3.2) is **not supported**. Install
a current bash via Homebrew (`brew install bash`) and source the completion
script from that shell.

## Quick start

```bash
# bash -- add to ~/.bashrc or ~/.bash_profile
eval "$(kanon completion bash)"

# zsh -- add to ~/.zshrc
eval "$(kanon completion zsh)"
```

After sourcing the script, Tab-completion is active for all kanon
subcommands and their dynamic arguments.

## Install paths

There are two ways to load the completion script:

### Auto-updating (recommended)

Source the completion output inline via `eval`. Every new shell session runs
`kanon completion <shell>` at startup, so the completion script is always
in sync with the installed kanon version.

```bash
# bash
eval "$(kanon completion bash)"

# zsh
eval "$(kanon completion zsh)"
```

This approach requires no maintenance after kanon upgrades.

### Static file (advanced)

Write the completion script to disk once and source it from a fixed path.
This avoids a subprocess call on each shell startup but means the file must
be refreshed manually after kanon upgrades.

```bash
# bash
kanon completion bash > ~/.local/share/bash-completion/completions/kanon

# zsh -- place the file on your $fpath
kanon completion zsh > ~/.zsh/completions/_kanon
```

When using the static approach, run `kanon doctor` after upgrading kanon.
The doctor command detects drift between the installed kanon version and
the content of the static file and emits a warning when they diverge.

## Update lifecycle

| Method | How completion stays current |
|--------|------------------------------|
| Auto-updating (`eval "$(kanon completion <shell>)"`) | Always current -- regenerated on each shell startup. |
| Static file | Must be refreshed manually after each kanon upgrade via `kanon completion <shell> > <path>`. `kanon doctor` warns when the static file is stale. |

## Dynamic completers

The completion script includes a preamble block that defines kanon-specific
shell helper functions. Each helper shells out to a corresponding
`kanon __complete_<name>` subcommand at Tab-press time.

### `_kanon_complete_catalog_entries`

Retrieves available catalog entry names from the local cache. Backed by
`kanon __complete_catalog_entries [<prefix>]`. On cache miss the helper
returns silently so the shell falls back to filename completion.

### `_kanon_complete_source_names_in_kanon`

Retrieves source names defined in the `.kanon` file for the current
project. Used for completing arguments to `kanon remove` and similar
subcommands that reference named dependency sources.

### `_kanon_complete_names_in_lockfile`

Retrieves names recorded in the lock file. Used for completing
lock-file-aware arguments.

### `_kanon_complete_catalog_versions`

Retrieves available versions for a catalog entry. Used when completing
`@<version>` suffixes on catalog entry arguments.

### `_kanon_complete_project_versions`

Retrieves available versions for a project URL. Used when completing
version arguments for project-URL-based entries.

### `_kanon_complete_cached_catalogs`

Retrieves locally cached catalog identifiers. Used when completing
`--catalog-source` arguments.

### `_kanon_complete_add_arg` (mid-token splitter)

Handles `kanon add foo@<TAB>` style completion by splitting on the `@`
separator. The current release calls `_kanon_complete_catalog_entries`
unconditionally; full `@`-splitting logic is added in a subsequent task.

## Cache environment variables

The following environment variables control cache and completion behaviour.
All variables must be set in the shell before sourcing the completion script
(or before any `kanon` invocation for the per-process settings).

| Variable | Default | Effect |
|----------|---------|--------|
| `KANON_CACHE_DIR` | `$XDG_CACHE_HOME/kanon` or `~/.cache/kanon` | Root directory for all kanon cache files. Controls where completion index files, version lists, and error logs are written. |
| `KANON_COMPLETION_CACHE_TTL` | `300` | Cache time-to-live in seconds. Entries whose `fetched_at.txt` is within this window are returned immediately; older entries trigger a background refresh. |
| `KANON_COMPLETION_TIMEOUT` | `2` | Timeout in seconds for each inline subprocess call during a cache-miss fetch. |
| `KANON_COMPLETION_REFRESH_BG` | `1` | Set to `0` to disable background refresh. When disabled, stale cache entries are returned without spawning a child refresh process. |
| `KANON_COMPLETION_ENABLED` | `1` | Set to `0` to disable all dynamic completion lookups entirely. The completion script still provides static subcommand and flag completion; only dynamic argument lookups (catalog entries, source names, etc.) are skipped. |
| `KANON_ACCESSED_AT_COALESCE_SEC` | `60` | Coalescing window in seconds for `accessed_at.txt` updates. Limits I/O under rapid Tab-pressing by suppressing redundant writes within this window. |
| `KANON_COMPLETION_LOG` | `${KANON_CACHE_DIR}/completion-errors.log` | Path to the append-only error log written by `__complete_*` subcommands. Override to redirect completion-time errors to a custom path. |

## Troubleshooting

### Stale cache

If completion results are outdated after adding new entries to a catalog,
the cache has not yet refreshed. Options:

1. Wait for the background refresh to complete (triggered on the next
   Tab-press after the TTL expires).
2. Force an immediate refresh by running `kanon doctor --refresh-completion-cache`.
3. Prune the entire cache with `kanon doctor --prune-cache` and let it
   rebuild on the next Tab-press.

### Log file location

Errors that occur inside `__complete_*` subcommands are written to the
completion error log. The default path is:

```
${KANON_CACHE_DIR}/completion-errors.log
```

Override the path via `KANON_COMPLETION_LOG`. The log is append-only and
is never rotated automatically. Truncate or remove it manually, or run
`kanon doctor --prune-cache` to clear it along with the rest of the cache.

Format of each log line:

```
<ISO-8601-UTC> <completer-name> <ErrorClass>: <message>
```

### Disabling dynamic completion

Set `KANON_COMPLETION_ENABLED=0` to disable all dynamic argument lookups
for the current shell session:

```bash
export KANON_COMPLETION_ENABLED=0
```

Static subcommand and flag completion (subcommand names, option strings)
remain active. Only the dynamic completers that shell out to
`kanon __complete_*` are suppressed.

### Completion timeout

If Tab-presses feel slow on a cache miss, reduce `KANON_COMPLETION_TIMEOUT`
(default `2` seconds):

```bash
export KANON_COMPLETION_TIMEOUT=1
```

Or disable inline fetches entirely with `KANON_COMPLETION_ENABLED=0` and
rely on cached results only.

## Updating snapshots

The CI pipeline verifies that the completion scripts have not changed
unexpectedly using snapshot fixture files committed to the repository
(`tests/fixtures/completion/expected-bash.sh` and `expected-zsh.sh`).

After intentionally changing the completion output (e.g. adding a new
subcommand or flag), regenerate both fixtures in one step:

```bash
make update-completion-snapshots
```

Then commit the updated fixture files alongside the code change.

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

Each cache entry directory contains a `fetched_at.txt` file holding an
integer epoch-seconds timestamp.  The `classify()` function in
`kanon_cli.completions.cache` evaluates that timestamp against the
current time and the configured TTL to produce one of three `Freshness`
values:

| Freshness | Condition | Action |
|-----------|-----------|--------|
| `FRESH`   | `now - fetched_at <= TTL`, OR `fetched_at > now` (clock skew) | Return cached entries immediately. |
| `STALE`   | `now - fetched_at > TTL` (file present and parseable) | Return stale entries; fork background refresh when `KANON_COMPLETION_REFRESH_BG=1`. |
| `MISSING` | File absent, empty, non-integer content, or negative value | Perform inline fetch bounded by `KANON_COMPLETION_TIMEOUT`. |

**Staleness rules (spec Section 11.4):**

- `fetched_at.txt` absent on disk -- `MISSING`.
- Content not parseable as an integer -- `MISSING`.
- Parsed value < 0 -- `MISSING` (negative epoch is invalid).
- `fetched_at > now` (clock skew -- future timestamp) -- `FRESH`.
  The spec is explicit: a future timestamp must be treated as fresh so
  that a misconfigured or drifting system clock does not force a
  continuous refetch storm.
- `now - fetched_at <= TTL` -- `FRESH`.
- `now - fetched_at > TTL` -- `STALE`.

**TTL:** `KANON_COMPLETION_CACHE_TTL` (default 300 s). A cached result
  whose `fetched_at.txt` is within the TTL is returned immediately;
  otherwise a background refresh is spawned (controlled by
  `KANON_COMPLETION_REFRESH_BG`).

**Background refresh (STALE path):**

When the cache is STALE, `fork_background_refresh()` in
`kanon_cli.completions.cache` is called with a refresh callable.

- The stale entries are returned to the shell immediately (the
  completer does not block).
- A child process is forked via `os.fork()`:
  1. `os.setsid()` detaches the child from the controlling terminal.
  2. stdin and stdout are redirected to `/dev/null` so the child
     cannot write to the operator's terminal.
  3. stderr is redirected to `completion-errors.log` (append mode)
     so any refresh-time errors are captured.
  4. The refresh function is called; on success the child exits 0.
  5. On any exception, the error is logged via `log_completion_error`
     and the child exits non-zero.
- The parent process returns immediately and does not call
  `os.waitpid`; the child is fully detached.

**Opt-out:** Set `KANON_COMPLETION_REFRESH_BG=0` to disable background
refresh entirely.  In that mode, a STALE cache is still returned
immediately but no child process is forked to update it.  A subsequent
Tab-press will again return the stale data until the cache is refreshed
by an inline fetch (cache-miss path) or until the operator runs
`kanon doctor --prune-cache`.

- **Coalescing:** `accessed_at.txt` is updated at most once per
  `KANON_ACCESSED_AT_COALESCE_SEC` (default 60 s) to bound I/O under
  rapid Tab-pressing. The coalescing rule is: `accessed_at.txt` is
  rewritten only when `now - prior_value >= KANON_ACCESSED_AT_COALESCE_SEC`.
  If the file is missing or contains non-integer content it is treated
  as a first-touch and written unconditionally. If `prior_value > now`
  (clock skew), the file is rewritten to `now` to force-forward the
  timestamp. The `maybe_update_accessed_at(path, now, coalesce_window_seconds)`
  function in `kanon_cli.completions.cache` implements this rule and
  returns True when the file was written, False when the write was
  suppressed.
- **Pruning:** `kanon doctor --prune-cache` removes entries whose
  `accessed_at.txt` is older than `KANON_CACHE_PRUNE_AGE_DAYS`
  (default 30 d).

### Sanitization

Before any entry is written to a cache file by `write_entries`, it is
passed through the output sanitizer (`kanon_cli.completions.sanitize`).
The sanitizer rejects any entry that contains a forbidden character.
Rejected entries are dropped from the file AND logged to
`completion-errors.log` (see "Error log" below).

Forbidden character classes (per spec Section 11.3 and Section 3.6
trust model):

| Class | Characters / range | Rejection reason |
|-------|--------------------|-----------------|
| NUL | `\x00` (ASCII NUL) | `contains NUL` |
| Newline / carriage return | `\n` (0x0a), `\r` (0x0d) | `contains newline` |
| Shell metacharacters | `\|`, `&`, `;`, `<`, `>`, `(`, `)`, `{`, `}`, `$`, `` ` ``, `\`, `"`, `'` | `contains shell metacharacter '<c>'` |
| Other control characters | Any character below 0x20 not listed above | `contains control char 0xNN` |

The closed set of shell metacharacters is defined in
`kanon_cli.constants.SHELL_METACHARS` (a `frozenset[str]`).

Entries that survive all checks are written verbatim, one per line.
The sanitizer makes a single O(n) pass over each entry's characters
and stops on the first forbidden character, so filtering cost is
linear in total input size.

### Error log

Errors that occur inside `__complete_*` subcommands are written to
`completion-errors.log` (one line per error) in the format:

```text
<ISO-8601-UTC> <completer-name> <ErrorClass>: <message>
```

The log is append-only and never rotated automatically. Run
`kanon doctor --prune-cache` to truncate it. The path can be overridden via
`KANON_COMPLETION_LOG`.

## Dynamic completers (detailed reference)

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
