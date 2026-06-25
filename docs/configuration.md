# Configuration (.kanon)

## Global options

The following flags are accepted by every `kanon` command as global
options placed before the subcommand name
(e.g., `kanon --quiet install`):

| Flag          | Description                                  |
|---------------|----------------------------------------------|
| `--quiet`     | Suppress all output except errors. Sets the  |
|               | root logger to WARNING level.                |
| `--verbose`   | Enable debug-level output. Sets the root     |
|               | logger to DEBUG level.                       |
| `--no-color`  | Disable ANSI color output unconditionally.   |

### Mutual exclusion: --quiet and --verbose

`--quiet` and `--verbose` are mutually exclusive. Passing both flags
at the same time causes argparse to exit immediately with a non-zero
code and an error message on stderr. There is no fallback or silent
suppression -- this is a hard error per spec Section 7.

```bash
# ERROR: argument --verbose: not allowed with argument --quiet
kanon --quiet --verbose install .kanon
```

### Color output: --no-color and the NO\_COLOR environment variable

Color output is controlled by the following precedence chain
(highest wins):

1. `--no-color` flag -- always disables color when passed, regardless
   of the `NO_COLOR` environment variable or TTY state.
2. `NO_COLOR` environment variable -- when set to any non-empty value,
   disables color output following the <https://no-color.org>
   convention.
3. TTY auto-detection -- color is enabled by default when stdout is a
   TTY and neither of the above conditions applies.

```bash
# Disable color via flag (highest precedence)
kanon --no-color install .kanon

# Disable color via environment variable
NO_COLOR=1 kanon install .kanon

# --no-color wins even when NO_COLOR is empty
NO_COLOR= kanon --no-color install .kanon
```

The `.kanon` file is a shell-compatible KEY=VALUE configuration file
that drives the Kanon lifecycle.

## Format

```properties
# Comments start with #
KEY=VALUE
KEY_WITH_EXPANSION=${HOME}/.some-path
```

- Lines starting with `#` are comments
- Blank lines are ignored
- Lines without `=` are ignored
- Only the first `=` splits key from value (values may contain `=`)
- Trailing whitespace is trimmed

## Shell Variable Expansion

Values can reference environment variables using `${VAR}` syntax:

```properties
CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
```

If the referenced variable is not set in the environment, parsing
fails with a descriptive error.

## Placeholder Validation

`kanon install` scans the `.kanon` file for unresolved template
placeholders **before** running `repo envsubst`. Any value matching
the regex `<[A-Z_|]+>` is treated as an unfilled placeholder and
causes an immediate hard failure.

### What triggers the check

The pattern `<[A-Z_|]+>` matches angle-bracket-delimited tokens
containing only uppercase ASCII letters, underscores, and pipe
characters. Examples that trigger the check:

- `<YOUR_GIT_ORG_BASE_URL>`
- `<TRUE_OR_FALSE>`
- `<GITBASE|OTHER>`

Values written by `kanon add` in older releases sometimes contained
these literal strings as stand-in prompts that users were expected to
replace before running `kanon install`.

### Error format

When one or more placeholders are detected, `kanon install` exits
with a non-zero code and prints each finding to stderr:

```text
ERROR: .kanon contains unresolved placeholders
       -- resolve each before running kanon install
  Line 4: KANON_SOURCE_build_GITBASE=<YOUR_GIT_ORG_BASE_URL>
```

Each line reports the line number and the full `KEY=VALUE` line as it
appears in the `.kanon` file so the operator can locate it
immediately.

### Remediation

Three paths are available, listed in decreasing order of preference:

1. **Re-run `kanon add`** -- `kanon add` auto-derives the per-dependency
   `KANON_SOURCE_<alias>_GITBASE` from the catalog-source URL. Re-running
   `kanon add` overwrites the stale placeholder lines without manual
   editing.

2. **Set the corresponding environment variable** -- if the
   placeholder represents a value that should come from the
   environment, set the variable before invoking `kanon install`:

   ```bash
   export GITBASE=https://github.com/your-org
   kanon install .kanon
   ```

3. **Hand-edit `.kanon`** -- open the file and replace each
   placeholder with a concrete value:

   ```properties
   # Before (triggers error):
   KANON_SOURCE_build_GITBASE=<YOUR_GIT_ORG_BASE_URL>

   # After (valid):
   KANON_SOURCE_build_GITBASE=https://github.com/your-org
   ```

### Worked example

Given a `.kanon` file with the following content at line 4:

```properties
# .kanon
KANON_SOURCE_build_URL=${KANON_SOURCE_build_GITBASE}/build.git
KANON_SOURCE_build_REF=main
KANON_SOURCE_build_PATH=repo-specs/meta.xml
KANON_SOURCE_build_GITBASE=<YOUR_GIT_ORG_BASE_URL>
```

Running `kanon install .kanon` before resolving the placeholder
produces:

```text
ERROR: .kanon contains unresolved placeholders
       -- resolve each before running kanon install
  Line 5: KANON_SOURCE_build_GITBASE=<YOUR_GIT_ORG_BASE_URL>
```

After correcting the line:

```properties
KANON_SOURCE_build_GITBASE=https://github.com/your-org
```

`kanon install .kanon` proceeds normally.

## Environment Variable Reference

The sections below group every environment variable by function.
Each entry shows the variable name, its default, and a description.
Cross-references:

- Shell completion cache layout:
  [docs/shell-completion.md](shell-completion.md)
- Lockfile precedence and format:
  [docs/lockfile.md](lockfile.md)
- Git authentication setup:
  [docs/git-auth-setup.md](git-auth-setup.md)

---

### Catalog source

**No default catalog source.** Post-bootstrap-deprecation, the
bundled fallback catalog has been removed. One of `--catalog-source`
or `KANON_CATALOG_SOURCES` is required for catalog-requiring commands.
There is no rc-file mechanism; configuration is explicit via CLI flag
or environment variable only.

**`KANON_CATALOG_SOURCES`** (default: unset) -- One or more catalog
repositories, each in `url[@ref]` form, given as a newline-delimited
list (one entry per line). Specifies the catalog repositories used by
catalog-requiring commands. A command that resolves a catalog uses the
single configured entry; `--catalog-source` overrides it.

```bash
export KANON_CATALOG_SOURCES=\
  https://github.com/example-org/kanon-catalog.git@main
kanon search
```

**Precedence (highest to lowest):**

1. `--catalog-source` CLI flag
2. `KANON_CATALOG_SOURCES` environment variable

These are the only two layers. There is no lockfile or `.kanon`
fallback: the schema-v4 lockfile carries no catalog block, and `.kanon`
records no catalog source.

When neither source is set, a catalog-requiring command (`kanon search`,
`kanon add`, `kanon outdated`, `kanon why`, `kanon catalog audit`) exits
with a hard error and remediation text. See
[docs/catalogs-explained.md](catalogs-explained.md) for details.

**`kanon install` is hermetic.** Install never reads a catalog source: it
does not accept `--catalog-source`, and a populated `KANON_CATALOG_SOURCES`
is ignored. Install is driven solely by the committed `.kanon` and
`.kanon.lock`, so it neither resolves nor records a catalog source and
never raises a catalog-source mismatch.

See [docs/architecture.md](architecture.md) for the full precedence
logic.

**Shell-profile leakage warning.** If `KANON_CATALOG_SOURCES` is set
in a shell profile (e.g., `~/.bashrc`, `~/.zshrc`, `~/.profile`),
it leaks into every shell session including unrelated workspaces.
A catalog source set for project A silently applies to project B
if both are opened in the same shell. To avoid cross-workspace
contamination, set `KANON_CATALOG_SOURCES` in workspace-specific
tooling (e.g., a `.envrc` loaded by direnv) rather than in shell
profiles. Alternatively, always pass `--catalog-source` explicitly
on the command line.

---

### Resolver behavior

These variables control how the resolver fetches, resolves, and
validates dependency information.

**`KANON_RESOLVE_TIMEOUT`** (default: `30`) -- Timeout in seconds for
each `git ls-remote` call in `kanon install`, `kanon outdated`,
`kanon why`, and `kanon doctor`. Bounded per call; not a global wall
clock. Defined in `src/kanon_cli/constants.py`.

**`KANON_KANON_FILE`** (default: `./.kanon`) -- Default `.kanon` file
path. It supplies the default target for `kanon add` / `kanon remove`
writes and the default `--kanon-file` value for the commands that accept
that flag (`kanon add`, `kanon remove`, `kanon doctor`). On `kanon install`
and `kanon validate lockfile` the `.kanon` path is given as a positional
argument (these commands do not expose a `--kanon-file` flag). The
`--kanon-file` CLI flag takes precedence over this variable when both are
set.

**`KANON_LIST_FORMAT`** (default: `names`) -- Default output format
for `kanon search`. Supported values: `names`, `json`. Overridden by
`--format` CLI flag.

**`KANON_LIST_LIMIT`** (default: `50`) -- Default cap on the number
of entries returned by `kanon search -A`. Overridden by
`--limit N` / `--no-limit` CLI flags.

**`KANON_TREE_NO_FILTER_THRESHOLD`** (default: `20`) -- Entry count
above which `kanon search --tree` requires a filter argument. Without a
filter, `kanon search --tree` exits with an error suggesting `--regex`,
`<substring>`, or `--max-depth 0`. Override with
`--no-filter-required`.

**`KANON_OUTDATED_FORMAT`** (default: `table`) -- Default output
format for `kanon outdated`. Currently only `table` is supported.
Overridden by `--format` CLI flag.

**`KANON_WHY_FORMAT`** (default: `text`) -- Default output format for
`kanon why`. Supported values: `text` (human-readable arrow-separated
chains) and `json` (machine-readable JSON array). Overridden by
`--format` CLI flag.

**`KANON_WHY_JSON_INDENT`** (default: `2`) -- Number of spaces per
indentation level in JSON output from `kanon why --format json`. Must
be a non-negative integer parseable by Python `int()`.

**`KANON_WHY_SUGGEST_MAX_DISTANCE`** (default: `3`) -- Maximum
Levenshtein edit distance for closest-match suggestions when
`kanon why` cannot find the requested argument. Must be a
non-negative integer.

**`KANON_WHY_SUGGEST_TOP_N`** (default: `3`) -- Maximum number of
closest-match suggestions displayed on not-found. Results are sorted
ascending by edit distance, ties broken lexicographically. Must be a
non-negative integer.

**`KANON_ALLOW_INSECURE_REMOTES`** (default: unset) -- When set to
exactly `1`, disables the insecure-remote URL security check in
`kanon install`. All remote URL schemes (HTTP, `file://`, `git://`,
etc.) are accepted without error. Any value other than `1` is treated
as unset. See the security rationale below.

#### KANON\_ALLOW\_INSECURE\_REMOTES -- security rationale

kanon enforces a trust model (spec Section 3.6) that requires all
`<remote>` fetch URLs in resolved manifests to use HTTPS or SSH. Plain
HTTP, `file://`, `git://`, and other unencrypted schemes are rejected
by default because they expose dependency resolution to network-level
interception and tampering.

**Allowed unconditionally:**

- `https://...` -- encrypted, authenticated.
- `git@host:org/repo.git` -- SCP-style SSH; encrypted, key-authed.
- `ssh://...` -- explicit SSH; encrypted, key-authenticated.

**Rejected by default (allowed only with `KANON_ALLOW_INSECURE_REMOTES=1`):**

- `http://...` -- unencrypted; interceptable in transit.
- `file://...` -- local path; no network-level guarantees.
- Any other scheme (`git://`, `ftp://`, custom schemes, empty URL).

**Override:** Set `KANON_ALLOW_INSECURE_REMOTES=1` to disable the
check. Only the exact string `1` enables it. Values such as `true`,
`yes`, `on`, or `0` do NOT enable the override.

```bash
# Default: HTTP remote rejected
kanon install .kanon  # exits 1 if any <remote> uses http://

# Override: HTTP remote accepted
KANON_ALLOW_INSECURE_REMOTES=1 kanon install .kanon
```

The check also runs on the lockfile-consistent replay path: even if a
lockfile was recorded with an HTTP URL, `kanon install` rejects it.
See [docs/lockfile.md](lockfile.md) for details on replay enforcement.

---

### File paths

These variables control where kanon reads and writes its key files.

**`KANON_LOCK_FILE`** (default: derived) -- Override the lock file
path. When set to a non-empty value, kanon reads and writes the lock
file at this path instead of the default derived from `--kanon-file`
(i.e. `<kanon-file-path>.lock`). The `--lock-file` CLI flag takes
precedence when both are set. An empty-string value is treated as
unset. See [docs/lockfile.md](lockfile.md) for the full precedence
chain.

**Lock file resolution order (highest wins):**

1. `--lock-file` CLI flag
2. `KANON_LOCK_FILE` environment variable
3. Default derived from `--kanon-file`: `./.kanon` becomes
   `./.kanon.lock`; `./alt.kanon` becomes `./alt.kanon.lock`.

**`KANON_HOME`** (default: `~/.kanon`) -- Single root directory that
subsumes the former per-user cache-dir override and the former
per-workspace artifact-dir override. The cache subtree lives at
`${KANON_HOME}/cache/` and the store subtree at `${KANON_HOME}/store/`.
An unwritable resolved home fails fast with an actionable message
(no silent relocation). Owner-private modes `0700` / `0600` still apply
to cache files. See
[Shell Completion -- Cache layout](shell-completion.md#cache-layout).

**`KANON_HOME` resolution order (highest wins):**

1. `--home` / `--store-dir <path>` global CLI flag (when supplied).
2. `KANON_HOME` environment variable (when non-empty).
3. `~/.kanon` -- default when the env var is unset and no flag is given.

The `--home` (alias `--store-dir`) flag is a global option accepted on
every command; when supplied it overrides `KANON_HOME` for that
invocation.

```bash
# Store cache and artifacts under a non-default home
export KANON_HOME=/tmp/my-kanon-home

# Or per-invocation, overriding the env var and the default
kanon --home /tmp/my-kanon-home install
```

---

### Lockfile

These variables control lockfile-related behaviour. See
[docs/lockfile.md](lockfile.md) for the full lockfile reference
including format, semantics, schema migration, and conflict
resolution.

**`KANON_GIT_LS_REMOTE_TIMEOUT`** (default: `30`) -- Timeout in
seconds for `git ls-remote` calls used by SHA reachability checks and
ref resolution in the install engine. Defined in
`src/kanon_cli/constants.py`.

The `KANON_RESOLVE_TIMEOUT` variable (documented under
[Resolver behavior](#resolver-behavior)) also governs `git ls-remote`
calls during lockfile resolution.

---

### Concurrency

`kanon install`, `kanon add`, `kanon remove`, and
`kanon doctor --refresh-completion-cache` use an exclusive file lock
(`fcntl.flock(LOCK_EX)`) on `.kanon-data/.kanon-install.lock` to
serialize concurrent invocations within the same workspace. The
kernel releases the lock on process exit (graceful or crash); a
leftover `.kanon-install.lock` file on disk is harmless.

The following variables control how `kanon doctor --prune-cache`
handles stale lock files and cache entries.

**`KANON_CACHE_PRUNE_AGE_DAYS`** (default: `30`) -- Files under
`${KANON_HOME}/cache` whose last-access time is older than this many
days are removed by `kanon doctor --prune-cache`. Reports what was
pruned. Must be a positive integer. Values of 0 or below are rejected
with a clear error at startup.

**`KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH`** (default: `4`) --
Maximum directory depth below the current working directory that
`kanon doctor --prune-cache` searches for stale
`.kanon-data/.kanon-install.lock` files. Bounds filesystem traversal
to prevent wandering the entire filesystem in a misconfigured
workspace. Must be a positive integer.

**`KANON_DOCTOR_STALE_LOCK_AGE_HOURS`** (default: `1`) -- Minimum
age in hours for a `.kanon-data/.kanon-install.lock` file to be
considered stale by `kanon doctor --prune-cache`. Stale locks are
reported as advisory findings only -- doctor never deletes them.
`fcntl.flock` self-cleans on process exit, so a leftover file is
harmless. Must be a positive integer.

```bash
# Use the default 30-day threshold
kanon doctor --prune-cache

# Prune files not accessed in the last 7 days
KANON_CACHE_PRUNE_AGE_DAYS=7 kanon doctor --prune-cache

# Restrict stale-lock scan to 2 levels deep
KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH=2 kanon doctor --prune-cache

# Treat locks older than 4 hours as stale
KANON_DOCTOR_STALE_LOCK_AGE_HOURS=4 kanon doctor --prune-cache
```

---

### Completion cache

These variables control the shell-completion cache. See
[docs/shell-completion.md](shell-completion.md) for the full cache
layout and lifecycle description.

**`KANON_COMPLETION_ENABLED`** (default: `1`) -- When set to `0`,
all shell completion helpers return an empty candidate list
immediately without invoking the `kanon` subprocess. Set to `0` to
disable dynamic completion lookups globally (for example in
restricted environments or when completion latency is a concern). Any
value other than `0` is treated as enabled.

```bash
# Disable all kanon completion lookups
export KANON_COMPLETION_ENABLED=0

# Re-enable (default behaviour)
export KANON_COMPLETION_ENABLED=1
```

**`KANON_COMPLETION_TIMEOUT`** (default: `2`) -- Timeout in seconds
applied to each `kanon __complete_*` subprocess call made by the
shell completion preamble helpers. When `timeout`(1) is available on
`$PATH`, it wraps the subprocess call with this value. When
`timeout`(1) is not available, kanon's own internal subprocess
timeout (also bounded by this variable) applies. Must be a positive
integer.

```bash
# Use a 5-second timeout for completion lookups
export KANON_COMPLETION_TIMEOUT=5

# Use the default 2-second timeout
unset KANON_COMPLETION_TIMEOUT
```

**`KANON_COMPLETION_REFRESH_BG`** (default: `1`) -- When set to `1`,
a background subprocess is spawned after a stale-but-present cache
read to refresh the cache asynchronously. Set to `0` to disable
background refresh (completions then become stale until the TTL
expires and the next Tab press triggers a synchronous fetch).

```bash
# Disable background refresh
export KANON_COMPLETION_REFRESH_BG=0
```

**`KANON_COMPLETION_CACHE_TTL`** (default: `300`) -- Cache
time-to-live in seconds. A cached completion result whose
`fetched_at.txt` is within this age is returned immediately without a
remote fetch. When the age exceeds the TTL, a background refresh is
spawned (if `KANON_COMPLETION_REFRESH_BG=1`).

```bash
# Extend TTL to 10 minutes
export KANON_COMPLETION_CACHE_TTL=600
```

**`KANON_ACCESSED_AT_COALESCE_SEC`** (default: `60`) -- Coalescing
window in seconds for `accessed_at.txt` updates. A read that occurs
within this many seconds of the last `accessed_at` write does not
rewrite the file. This bounds I/O during rapid tab-pressing without
losing access-time tracking for cache pruning.

```bash
# Coalesce accessed_at writes within a 5-minute window
export KANON_ACCESSED_AT_COALESCE_SEC=300
```

**`KANON_COMPLETION_LOG`** (default: `${KANON_HOME}/cache/completion-errors.log`)
-- Path to the append-only completion-errors log. When unset, errors
are written to `completion-errors.log` directly under
`${KANON_HOME}/cache`. The file is created with mode `0600` and its
parent directory with mode `0700`.

```bash
# Redirect completion errors to a custom path
export KANON_COMPLETION_LOG=/var/log/kanon-completion-errors.log
```

**`KANON_COMPLETION_ERRORS_REPORT_LIMIT`** (default: `5`) -- Maximum
number of completion error lines surfaced by `kanon doctor` (subcheck
7). Must be a positive integer.

---

### Update check

kanon performs a best-effort PyPI check for a newer `kanon-cli` release
and prints an upgrade hint when one is available. The check is cached and
never blocks a command on failure.

**`KANON_SKIP_UPDATE_CHECK`** (default: unset) -- When set to exactly `1`,
the PyPI update-available check is skipped entirely. The global
`--no-update-check` flag has the same effect for a single invocation.

```bash
# Skip the update check for one run
kanon --no-update-check install .kanon

# Skip it for the whole session
export KANON_SKIP_UPDATE_CHECK=1
```

**`KANON_UPDATE_CHECK_TTL`** (default: `86400`) -- Seconds the cached
"latest version" result is considered fresh before the next check refetches
it. Must be a positive integer.

**`KANON_UPDATE_CONNECT_TIMEOUT`** (default: `2`) -- Connect timeout in
seconds for the PyPI request. Must be a positive integer.

**`KANON_UPDATE_READ_TIMEOUT`** (default: `3`) -- Read timeout in seconds
for the PyPI request. Must be a positive integer.

**`KANON_UPDATE_BODY_SIZE_CAP`** (default: `204800`) -- Maximum number of
response bytes read from the PyPI JSON endpoint. Must be a positive
integer.

---

### Retry policy

kanon retries `git ls-remote` calls on transient errors. Auth-failure
patterns skip retries immediately; see
[docs/git-auth-setup.md](git-auth-setup.md) for authentication
configuration. The auth-error patterns (`GIT_AUTH_ERROR_PATTERNS`) are
internal constants, not environment variables.

**`KANON_GIT_RETRY_COUNT`** (default: `3`) -- Number of
`git ls-remote` retry attempts on transient errors. Auth-error
patterns (e.g., "Authentication", "Permission denied") skip retries
regardless of this value. Must be a non-negative integer. Defined in
`src/kanon_cli/constants.py`.

**`KANON_GIT_RETRY_DELAY`** (default: `1`) -- Seconds to wait
between `git ls-remote` retry attempts. Must be a non-negative
integer. Defined in `src/kanon_cli/constants.py`.

```bash
# Increase retry attempts for unreliable networks
KANON_GIT_RETRY_COUNT=5 kanon install .kanon

# Increase wait between retries
KANON_GIT_RETRY_DELAY=3 kanon install .kanon
```

---

## Multi-Source Groups

Sources are alias-keyed: each is auto-discovered from a
`KANON_SOURCE_<alias>_URL` variable and processed in alphabetical order
by alias. Each source block carries the required structural suffixes
`_{URL,REF,PATH,NAME}`, plus an open, optional set of per-dependency
env-var suffixes (`KANON_SOURCE_<alias>_<VAR>`) used to resolve `${VAR}`
placeholders in that source's manifest at install time:

```properties
KANON_SOURCE_build_URL=${KANON_SOURCE_build_GITBASE}/build-repo.git
KANON_SOURCE_build_REF=main
KANON_SOURCE_build_PATH=repo-specs/meta.xml
KANON_SOURCE_build_NAME=build
KANON_SOURCE_build_GITBASE=https://github.com/org

KANON_SOURCE_marketplaces_URL=${KANON_SOURCE_marketplaces_GITBASE}/mp-repo.git
KANON_SOURCE_marketplaces_REF=main
KANON_SOURCE_marketplaces_PATH=repo-specs/marketplaces.xml
KANON_SOURCE_marketplaces_NAME=marketplaces
KANON_SOURCE_marketplaces_GITBASE=https://github.com/org
```

Each source requires the `_URL`, `_REF`, `_PATH`, and `_NAME` suffixed
variables. The per-dependency env-var suffixes (`_GITBASE` above, or any
other `${VAR}` name) are OPTIONAL and open-ended: `kanon add` writes one
line per `${VAR}` the entry's manifest actually references (the `GITBASE`
var is auto-derived from the source URL; every other var name is written
empty for you to fill in), and writes none when the manifest references no
`${VAR}`. At install time each declared var is injected into that source's
manifest substitution; an unresolved `${VAR}` after substitution fails the
install fast, naming the `KANON_SOURCE_<alias>_<VAR>` key to set.

---

## Per-dependency marketplace install flag

There is no global marketplace-install toggle. Marketplace install is a
per-dependency setting stored in `.kanon` as
`KANON_SOURCE_<alias>_MARKETPLACE=true`. Absence of the line is the
canonical "disabled" state; kanon never writes `=false` itself.

When `KANON_SOURCE_<alias>_MARKETPLACE=true` for a dependency:

- `kanon install` registers that dependency's marketplace plugin under
  `CLAUDE_MARKETPLACES_DIR` and records the registration in the
  per-source `registered_marketplaces` ledger in `.kanon.lock`.
- `kanon clean` unregisters the plugins kanon recorded and removes the
  marketplace directory it used.

Manage the flag with the `kanon marketplace` subcommand, which edits only
`.kanon` (it never touches `.kanon.lock` and performs no re-resolution):

```bash
# Enable marketplace install for one dependency (writes =true)
kanon marketplace enable <alias>

# Disable it (removes the =true line)
kanon marketplace disable <alias>

# Show each dependency, its catalog <type>, and its effective setting
kanon marketplace status
kanon marketplace status --all
```

See [docs/lockfile.md](lockfile.md#marketplace-ownership-and-pruning) for
how the per-source ledger drives marketplace pruning.

---

## kanon repo Subcommand

The `kanon repo` subcommand exposes kanon's repo subsystem for direct
manifest operations, allowing direct invocation of any `repo`
subcommand (such as `init`, `sync`, `version`, `help`) without
requiring a separate `repo` installation.

### KANON\_REPO\_DIR

**`KANON_REPO_DIR`** (default: `.repo`) -- Path to the `.repo`
working directory used by `kanon repo`. Corresponds to the
`--repo-dir` flag on the `kanon repo` subcommand.

### Usage

```bash
# Initialize a manifest repository
kanon repo init -u <url> -b <branch> -m <manifest>

# Sync all projects
kanon repo sync --jobs=4

# Show the status of checked-out projects
kanon repo status

# Use a custom .repo directory
KANON_REPO_DIR=/path/to/workspace/.repo kanon repo status

# Equivalent via flag
kanon repo --repo-dir /path/to/workspace/.repo status
```
