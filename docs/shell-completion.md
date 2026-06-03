# Shell Completion

kanon supports tab-completion for bash and zsh via
`kanon completion <shell>`. The generated script provides static
completions for all subcommands and flags, plus dynamic completions
for catalog entry names, versions, and other live data fetched
through a TTL-cached local mirror.

## Install

### Bash version requirement

kanon's generated bash completion script requires **bash 4.0 or
later**. The macOS stock shell (`/bin/bash`, bash 3.2) is **not
supported**. Install a current bash via Homebrew
(`brew install bash`) and source the completion script from that
shell.

### Auto-updating install (recommended)

Source the completion output inline via `eval`. Every new shell
session runs `kanon completion <shell>` at startup, so the completion
script is always in sync with the installed kanon version.

```bash
# bash -- add to ~/.bashrc or ~/.bash_profile
eval "$(kanon completion bash)"

# zsh -- add to ~/.zshrc
eval "$(kanon completion zsh)"
```

After sourcing the script, tab-completion is active for all kanon
subcommands and their arguments. This approach requires no maintenance
after kanon upgrades.

### Static file install (advanced)

Write the completion script to disk once and source it from a fixed
path. This avoids a subprocess call on each shell startup, but the
file must be refreshed manually after kanon upgrades.

```bash
# bash -- system-wide completions directory
kanon completion bash \
  > ~/.local/share/bash-completion/completions/kanon

# zsh -- place the file on your $fpath
mkdir -p ~/.zsh/completions
kanon completion zsh > ~/.zsh/completions/_kanon
```

When using the static approach, run `kanon doctor` after upgrading
kanon. The doctor command detects drift between the installed kanon
version and the content of the static file and emits a warning when
they diverge. See [Update lifecycle](#update-lifecycle) below.

## Update lifecycle

For the **auto-updating** method (`eval "$(kanon completion <shell>)"`
in your rc file), the completion script is regenerated on each shell
startup and is always current. No maintenance is required after a
kanon upgrade.

For the **static file** method, the on-disk script must be
regenerated manually after each kanon upgrade:

```bash
kanon completion bash > ~/.local/share/bash-completion/completions/kanon
# or
kanon completion zsh > ~/.zsh/completions/_kanon
```

**When to regenerate:**

- After running `pipx upgrade kanon-cli` or any other upgrade method.
- After installing kanon in a new environment.
- When `kanon doctor` emits a completion-script staleness warning.

**How staleness is detected:**

`kanon doctor` compares the hash of the on-disk static file against a
fresh invocation of `kanon completion <shell>`. When they differ, the
doctor output includes a warning under check 9 ("Completion script
staleness"). Run `kanon completion <shell> > <path>` to refresh, or
switch to the auto-updating `eval` approach to eliminate this
maintenance step. See [kanon doctor](doctor.md) for the full list of
health checks.

## Dynamic completers

The completion script includes a preamble block that defines
kanon-specific shell helper functions. Each helper calls a
corresponding `kanon __complete_<name>` hidden subcommand at
tab-press time. The subcommand writes candidates to stdout (one per
line); the shell function hands them to the shell completion machinery.

All completers are failure-quiet on stdout (return an empty list on
error) and failure-loud on stderr (append a structured error line to
`${KANON_CACHE_DIR}/completion-errors.log`). This keeps the shell UX
non-blocking while ensuring errors are captured for `kanon doctor` to
surface.

### `__complete_catalog_entries`

**Shell helper:** `_kanon_complete_catalog_entries`

Retrieves available catalog entry names from the local cache.
Reads `${KANON_CACHE_DIR}/catalogs/<sha256>/index.txt`, where the
sha256 is derived from `"<catalog-url>@<ref>"`. On cache miss, the
command performs an inline network fetch bounded by
`KANON_COMPLETION_TIMEOUT` before returning results.

Used for completing the `<name>[@<spec>]` positional argument of
`kanon add`. (`kanon bootstrap` was removed and accepts no arguments; see
[docs/migration-bootstrap-to-add.md](migration-bootstrap-to-add.md).)

### `__complete_source_names_in_kanon`

**Shell helper:** `_kanon_complete_source_names_in_kanon`

Retrieves source names defined in the `.kanon` file for the current
project. Reads `${KANON_KANON_FILE:-./.kanon}` and emits one
normalized source name per line (parsed from `KANON_SOURCE_<name>_URL`
keys).

Used for completing arguments to `kanon remove` and
`kanon install --refresh-lock-source`. Note: normalization is
one-way -- the original entry name is not recoverable from the source
name. Tab-completion is suggest-only.

### `__complete_names_in_lockfile`

**Shell helper:** `_kanon_complete_names_in_lockfile`

Retrieves names recorded in the lockfile. Resolves the lockfile path
using the three-tier precedence chain:

1. `${KANON_LOCK_FILE}` -- explicit lockfile path override.
2. `${KANON_KANON_FILE}.lock` -- derived from the kanon file env var.
3. `./.kanon.lock` -- default path in the current directory.

Emits, one per line (sorted, deduplicated):
- Every top-level source name.
- Every transitive include `path_in_repo` value (recursive through
  nested includes).
- Every project URL.

Used for completing the `<name-or-url>` positional argument of
`kanon why`.

### `__complete_catalog_versions`

**Shell helper:** `_kanon_complete_catalog_versions`

Retrieves available versions for a catalog entry. Calls
`git ls-remote --tags --heads` against the manifest repo, filters
results to PEP 440-valid tags and branches, and returns them one per
line (deduped). Results are cached in
`${KANON_CACHE_DIR}/catalogs/<sha256>/tags.txt`.

Used when completing `@<version>` suffixes on `kanon add` arguments.

### `__complete_project_versions`

**Shell helper:** `_kanon_complete_project_versions`

Retrieves available versions for a project repository URL. Takes
two positional arguments: the project repo URL (first) and the
current completion prefix (second). Calls
`git ls-remote --tags --heads <repo-url>`, filters to PEP 440-valid
tags and branches, and returns them one per line (deduped, sorted).
Results are cached in
`${KANON_CACHE_DIR}/projects/<sha256>/tags.txt`.

**URL canonicalization:** Before computing the cache key, the raw
repo URL is canonicalized via the internal `canonicalize_repo_url`
helper (spec Section 4.0). Two URL shapes that resolve to the same
canonical URL share the same cache entry. For example,
`https://example.com/org/proj.git` and
`git@example.com:org/proj.git` both canonicalize to
`https://example.com/org/proj` and therefore hash to the same
`projects/<sha256>/tags.txt` file. The original (non-canonical) URL
is passed to `git ls-remote` so the transport (SSH, HTTPS, file,
etc.) is preserved. A malformed URL that cannot be canonicalized
produces empty stdout and a structured log entry.

Used when completing the `<spec>` portion of `kanon add foo@<TAB>`.

### `__complete_cached_catalogs`

**Shell helper:** `_kanon_complete_cached_catalogs`

Retrieves locally cached catalog identifiers. Enumerates
`${KANON_CACHE_DIR}/catalogs/*/` directories and reads the
`origin.txt` sidecar from each sha-named entry. Emits one
`<url>@<ref>` string per line, sorted lexicographically, filtered
by the current completion prefix.

The completer never recurses into subdirectories of
`catalogs/<sha>/`; it reads `origin.txt` from each sha directory
only.

- **Empty or missing `catalogs/`** -- returns empty stdout without
  writing a log entry (first-run or empty cache is not an error).
- **Malformed `origin.txt`** (empty file or no `@` separator) --
  the entry is skipped and a structured log entry naming the
  offending sha directory is appended to `completion-errors.log`.

Used when completing the `--catalog-source <url>@<ref>` flag for
`kanon list`, `kanon add`, `kanon outdated`, and related commands.

### Mid-token splitting

The `_kanon_complete_add_arg` shell helper drives `kanon add <name>[@<spec>]`
completion. It applies the LAST-`@` split rule (spec Section 4.0) to the
current completion token and routes to the appropriate completer.

**LAST-`@` split rule.** The token is split at the LAST `@` character. The
portion before the last `@` is the entry name; the portion after is the spec
prefix. Examples:

| Token | Entry name | Spec prefix |
|-------|------------|-------------|
| `foo` | `foo` | (no `@` present) |
| `foo@` | `foo` | `""` |
| `foo@1` | `foo` | `1` |
| `foo@bar@baz` | `foo@bar` | `baz` |
| `@1.0.0` | `""` | `1.0.0` |

**Routing table.** After the split:

| Condition | Action |
|-----------|--------|
| No `@` in token | Call `_kanon_complete_catalog_entries <token>` |
| `@` present AND resolver returns a URL | Call `_kanon_complete_project_versions <repo-url> <spec>` |
| `@` present AND resolver fails (unknown entry or disabled) | Emit empty; no error output |

**Entry-name to repo-URL resolution.** When `@` is detected, the shell helper
shells out to `kanon __resolve_entry_to_repo_url <name>` to obtain the
catalog source URL for that entry. The subcommand consults the local
completion cache (populated by `kanon __complete_catalog_entries`) and returns
the catalog git URL on stdout, or exits non-zero if the entry is not cached.
If the subcommand exits non-zero or returns an empty URL, the splitter emits
no candidates for the spec portion.

**`KANON_COMPLETION_ENABLED=0`.** When completion is disabled, the splitter
returns immediately without shelling out to `__resolve_entry_to_repo_url`.
The COMPREPLY / compadd list is left empty.

## Cache and environment variables

The following environment variables control cache and completion
behaviour. All variables must be set in the shell before sourcing the
completion script (or before any `kanon` invocation for
per-process settings).

See [Configuration](configuration.md) for the full environment
variable reference table.

**`KANON_CACHE_DIR`** -- Root directory for all kanon cache files.
Controls where completion index files, version lists, and error logs
are written. Defaults to `${XDG_CACHE_HOME:-~/.cache}/kanon`.
Override to place the cache on a faster or larger volume.

**`KANON_COMPLETION_CACHE_TTL`** (default `300`) -- Cache
time-to-live in seconds. Entries whose `fetched_at.txt` is within
this window are returned immediately. Older entries trigger a
background refresh when `KANON_COMPLETION_REFRESH_BG=1`.

**`KANON_COMPLETION_TIMEOUT`** (default `2`) -- Timeout in seconds
for each inline subprocess call during a cache-miss fetch. Increase
on slow networks; decrease if tab-presses feel sluggish.

**`KANON_COMPLETION_REFRESH_BG`** (default `1`) -- When `1`, a stale
cache entry is returned immediately while a child process refreshes
it in the background. Set to `0` to suppress background refreshes;
stale data is then returned until an inline refresh occurs.

**`KANON_COMPLETION_ENABLED`** (default `1`) -- Set to `0` to disable
all dynamic argument lookups. Static subcommand and flag completion
remains active; only dynamic completers (`kanon __complete_*`) are
suppressed.

**`KANON_ACCESSED_AT_COALESCE_SEC`** (default `60`) -- Coalescing
window in seconds for `accessed_at.txt` updates. Limits I/O under
rapid tab-pressing by suppressing redundant writes within this window.

**`KANON_COMPLETION_LOG`** (default
`${KANON_CACHE_DIR}/completion-errors.log`) -- Path to the
append-only error log written by `__complete_*` subcommands. Override
to redirect completion-time errors to a custom path.

### Cache layout

```text
${KANON_CACHE_DIR}/
  catalogs/
    <sha256-of-catalog-url@ref>/
      index.txt      -- one catalog entry name per line
      tags.txt       -- one PEP 440-valid tag or branch per line
      fetched_at.txt -- Unix epoch seconds of last remote fetch
      accessed_at.txt -- Unix epoch seconds of last read
      origin.txt     -- "<url>@<ref>" sidecar
  projects/
    <sha256-of-canonical-project-repo-url>/
      tags.txt       -- one PEP 440-valid tag or branch per line
      fetched_at.txt -- Unix epoch seconds of last remote fetch
      accessed_at.txt -- Unix epoch seconds of last read
      origin.txt     -- canonical "<repo-url>"
  completion-errors.log -- append-only error log
```

All cache directories are created with mode `0700`; all cache files
are written with mode `0600`. The process umask cannot weaken these
permissions.

## Troubleshooting

### Stale cache

If completion results are outdated after adding new entries to a
catalog, the cache has not yet refreshed.

1. Wait for the background refresh to complete (triggered on the next
   tab-press after the TTL expires).
2. Force an immediate refresh:

   ```bash
   kanon doctor --refresh-completion-cache
   ```

3. Prune the entire cache and let it rebuild:

   ```bash
   kanon doctor --prune-cache
   ```

### Refreshing the completion cache without a workspace

`kanon doctor --refresh-completion-cache` and
`kanon doctor --prune-cache` operate on `KANON_CACHE_DIR` globally
and do NOT require a `.kanon` workspace to be present in the current
directory. Both flags inspect and modify only the cache directory;
they never read or write `.kanon` or `.kanon.lock`. This means they
can be invoked from any directory -- including `$HOME` or a
freshly-created empty directory -- with no project context.

Example: refresh the completion cache from `$HOME` (no `.kanon`
present):

```bash
cd ~
kanon doctor --refresh-completion-cache
# exit 0; output similar to:
# [ok] Completion cache refreshed (KANON_CACHE_DIR=~/.cache/kanon)
```

Example: prune the entire cache from any directory:

```bash
kanon doctor --prune-cache
# exit 0; output similar to:
# [ok] Cache pruned (KANON_CACHE_DIR=~/.cache/kanon)
```

Override the cache directory via `KANON_CACHE_DIR` to target a
non-default location:

```bash
KANON_CACHE_DIR=/tmp/my-kanon-cache kanon doctor --refresh-completion-cache
```

See [docs/installation.md](installation.md) for the broader
completion-installation context and initial setup instructions.

### Log file location

Errors that occur inside `__complete_*` subcommands are written to
the completion error log. The default path is:

```text
${KANON_CACHE_DIR}/completion-errors.log
```

Override the path via `KANON_COMPLETION_LOG`. The log is append-only
and is never rotated automatically. Truncate or remove it manually,
or run `kanon doctor --prune-cache` to clear it along with the rest
of the cache.

Each log line follows this format:

```text
<ISO-8601-UTC> <completer-name> <ErrorClass>: <message>
```

Use `kanon doctor` to surface the most recent completion errors in a
human-readable summary.

### Disabling dynamic completion

Set `KANON_COMPLETION_ENABLED=0` to disable all dynamic argument
lookups for the current shell session:

```bash
export KANON_COMPLETION_ENABLED=0
```

Static subcommand and flag completion (subcommand names, option
strings) remain active. Only the dynamic completers that shell out to
`kanon __complete_*` are suppressed.

### Completion feels slow on cache miss

Reduce `KANON_COMPLETION_TIMEOUT` (default `2` seconds) to make
cache-miss fetches fail faster:

```bash
export KANON_COMPLETION_TIMEOUT=1
```

Or disable inline fetches entirely with `KANON_COMPLETION_ENABLED=0`
and rely on cached results only.

## See also

- [Configuration](configuration.md) -- full environment variable
  reference table, including all `KANON_COMPLETION_*` and
  `KANON_CACHE_*` variables.
- [kanon doctor](doctor.md) -- health checks including completion
  script staleness detection (`--refresh-completion-cache`,
  `--prune-cache`).
- [Troubleshooting](troubleshooting.md) -- general troubleshooting
  guide for kanon.
