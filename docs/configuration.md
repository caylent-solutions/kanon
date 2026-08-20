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
fallback: the schema-v5 lockfile carries no catalog block, and `.kanon`
records no catalog source.

**Optional `@ref` and default-branch resolution.** The `@ref` portion of a
catalog source is optional (`url[@ref]`). When a catalog source is given
without `@ref`, `kanon add` and `kanon search` resolve a default branch and
print a yellow `WARNING` naming the branch and suggesting you pin `@<ref>` to
silence it. The branch is chosen by this precedence (highest to lowest):

1. An inline `@ref` on the source (when present, no default-branch resolution
   happens).
2. The `--catalog-default-branch <name>` CLI flag (available on `kanon add`
   and `kanon search`).
3. The `KANON_CATALOG_DEFAULT_BRANCH` environment variable (default: `main`).
4. The literal value `auto`, which resolves the remote's `HEAD` symref via
   `git ls-remote --symref`.

**`KANON_CATALOG_DEFAULT_BRANCH`** (default: `main`) -- The default branch
used by `kanon add` / `kanon search` when a catalog source omits `@ref` and
no `--catalog-default-branch` flag is passed. Set it to `auto` to resolve the
remote's `HEAD` symref instead of assuming `main`.

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

**`KANON_SYNC_JOBS`** (default: unset) -- Upper bound on how many worker
processes `repo sync` fans out to during `kanon install`. This is a **cap**: it
can lower fan-out, never raise it.

`repo sync` resolves two independent job counts, and their defaults differ:
network fetch defaults to **1**, local checkout to `min(cpu_count, 8)`. kanon
caps each against its own default and passes them separately, so
`KANON_SYNC_JOBS=64` leaves network fetch at 1 rather than raising it to 64. The
cap also takes precedence over a manifest's `<default sync-j>`: an operator
bounding fan-out on their own machine should not be overridden by a value a
remote manifest chose.

Set it to `1` to run the sync in a single process. That is what the test suite
pins, because many concurrent `kanon install` processes each building their own
worker pool contend for the same POSIX semaphores and can wedge.

When unset, kanon passes no job arguments at all and `repo sync` resolves its own
defaults, clipped by a limit derived from `RLIMIT_NOFILE`.

Must be a positive integer; any other value aborts with exit 1. It is validated
at CLI entry, before any command does work, so a bad value cannot abort an
install part-way with a half-built workspace on disk. Defined in
`src/kanon_cli/constants.py`.

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

**`KANON_HOME`** (default: `~/.kanon-home`) -- Single root directory that
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
3. `~/.kanon-home` -- default when the env var is unset and no flag is given.

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

### Absolute manifest destinations

**`CLAUDE_MARKETPLACES_DIR`** -- unlike every other setting on this page, this is
not an environment variable kanon reads from your shell. It is a line in the
`.kanon` file itself. `kanon add` inserts
`CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces` as the first non-comment
line the first time you add a marketplace entry, never overwrites a value you
have changed, and prunes the line when the last marketplace entry is removed. The
`${HOME}` in it is expanded at install time. A `.kanon` declaring a marketplace
source with no such line fails the install.

**`KANON_ALLOWED_ABS_ROOTS`** (default: unset) -- extra roots an absolute
`<linkfile dest>` or `<copyfile dest>` may resolve under, separated by the
platform path separator (`:` on POSIX). A manifest is fetched from a remote
repository, so an absolute destination is confined rather than trusted; see
[Security model](security-model.md). Entries must be absolute paths, and an empty
entry or a relative one aborts with a non-zero exit.

**Permitted-root resolution order (highest wins):**

1. `--allow-abs-root <path>` global CLI flag, repeatable (when supplied). When
   given, `KANON_ALLOWED_ABS_ROOTS` is ignored for that invocation.
2. `KANON_ALLOWED_ABS_ROOTS` environment variable (when non-empty).
3. No extra roots -- the default.

Two roots are **always** permitted and cannot be removed by either mechanism: the
consumer project root (the directory holding `.kanon`) and the resolved
`CLAUDE_MARKETPLACES_DIR`. The setting can therefore only widen the boundary,
never narrow it below the project being installed into. Nothing is added to
`.kanon`, and existing `.kanon` files need no change.

A destination outside every permitted root aborts the install, naming the
destination, the roots, and how to widen them -- there is no prompt, so kanon
stays usable in CI, containers, and cron.

```bash
# Allow a manifest to deliver into a shared tooling directory
export KANON_ALLOWED_ABS_ROOTS=/opt/org-tooling

# Or per-invocation, overriding the env var; repeat for several roots
kanon --allow-abs-root /opt/org-tooling --allow-abs-root /srv/shared install
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

`kanon install`, `kanon add`, `kanon remove`, `kanon marketplace`, and
`kanon doctor --refresh-completion-cache` use an exclusive file lock
(`fcntl.flock(LOCK_EX)`) on a `.kanon-install.lock` to serialize concurrent
invocations against the same `.kanon` file. The lock lives in the shared
`KANON_HOME` store under `${KANON_HOME}/store/.locks/<address>/`, keyed by a
hash of the resolved `.kanon` path, so concurrent edits to the same file
serialize while the project directory stays clean: the working directory holds
only `.kanon` (and `.kanon.lock` after the first install), never a
`.kanon-data/` lock directory. The kernel releases the lock on process exit
(graceful or crash); a leftover `.kanon-install.lock` file on disk is harmless.

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
never blocks a command on failure. When an upgrade is available the banner
is yellow with the current (installed) version in red and the latest
version in green. When a check is attempted but the network is unreachable,
a red `no internet access -- could not check for updates` notice is printed
to stderr at most once per cache window.

**`KANON_SKIP_UPDATE_CHECK`** (default: unset) -- When set to exactly `1`,
the PyPI update-available check is skipped entirely. The global
`--no-update-check` flag has the same effect for a single invocation.

```bash
# Skip the update check for one run
kanon --no-update-check install .kanon

# Skip it for the whole session
export KANON_SKIP_UPDATE_CHECK=1
```

**`KANON_UPDATE_CHECK_TTL`** (default: `10800`) -- Seconds the cached
"latest version" result is considered fresh before the next check refetches
it (default 3 hours). Must be a positive integer.

**`KANON_UPDATE_CONNECT_TIMEOUT`** (default: `2`) -- Connect timeout in
seconds for the PyPI request. Must be a positive integer.

**`KANON_UPDATE_READ_TIMEOUT`** (default: `3`) -- Read timeout in seconds
for the PyPI request. Must be a positive integer.

**`KANON_UPDATE_BODY_SIZE_CAP`** (default: `204800`) -- Maximum number of
response bytes read from the PyPI JSON endpoint. Must be a positive
integer.

---

### Usage telemetry

kanon emits one anonymised-by-design usage event per command to the Caylent
telemetry collector so the maintainers can understand which commands and
package sources are used. Telemetry is **on by default**, runs **silently**
and **non-blocking** in a detached background process, and **never** blocks,
delays, or fails your command. It serialises only an explicit allowlist of
kanon-computed fields and never raw argv, credentials, keys, tokens, env-var
values, or file contents; every URL is credential-stripped before it is sent.
See [docs/privacy.md](privacy.md) for the exact fields collected, the reason
for each, and the transit/at-rest encryption.

**`KANON_TELEMETRY_DISABLED`** (default: unset) -- The single opt-out. Set to
a truthy value (`1`, `true`, `yes`, or `on`) to disable telemetry entirely.
There is no disable flag; this env var is the only off switch.

```bash
# Turn telemetry off for the whole session
export KANON_TELEMETRY_DISABLED=1
```

**`KANON_TELEMETRY_ENDPOINT`** (default:
`https://collector.platform.solutions.caylent.com/v1/logs`) -- The collector
endpoint. Must be an `https://` URL. The global `--telemetry-endpoint <url>`
flag overrides this for a single invocation.

**`KANON_TELEMETRY_DEBUG`** (default: unset) -- When truthy, prints the exact
JSON that would be sent to stderr (still non-blocking). Equivalent to the
global `--telemetry-debug` flag. Use it to inspect precisely what an event
contains.

```bash
# See exactly what an event contains without changing send behaviour
kanon --telemetry-debug install .kanon
```

**`KANON_TELEMETRY_CONNECT_TIMEOUT`** (default: `2`) /
**`KANON_TELEMETRY_READ_TIMEOUT`** (default: `3`) -- Connect / read timeouts
in seconds for the background POST. Must be positive integers.

**`KANON_TELEMETRY_MAX_BODY_BYTES`** (default: `4194304`) /
**`KANON_TELEMETRY_GRAPH_SIZE_CAP`** (default: `3145728`) -- The maximum
serialised body size and the install-graph size cap. When an install graph
exceeds the cap it is dropped in favour of the flattened installed-packages
summary with `install_graph_truncated: true`, so the fact that packages were
installed is never lost. Must be positive integers.

**`KANON_TELEMETRY_GIT_TIMEOUT`** (default: `3`) -- Per-command timeout in
seconds for the read-only `git` probes used to collect credential-stripped
repository provenance. Must be a positive integer.

**`KANON_TELEMETRY_LOG`** (default: `${KANON_HOME}/cache/telemetry-errors.log`)
-- Path to the append-only background telemetry error log.

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

### Auto-managed `CLAUDE_MARKETPLACES_DIR` header

The global `CLAUDE_MARKETPLACES_DIR` header is auto-managed alongside the
per-dependency marketplace flags, so the canonical
`kanon add <claude-marketplace> ; kanon install` workflow needs no manual
edit:

- `kanon add` of a `claude-marketplace` entry and `kanon marketplace enable`
  insert `CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces` once, as the
  first non-comment line, when it is absent.
- `kanon remove` and `kanon marketplace disable` prune the line once the last
  `KANON_SOURCE_<alias>_MARKETPLACE=true` dependency is gone; it is re-added
  automatically on the next add or enable.
- A hand-set custom value is preserved (never duplicated, never clobbered);
  set the line by hand only to override the directory.

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
