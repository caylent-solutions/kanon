# Configuration (.kanon)

## Global options

The following flags are accepted by every `kanon` command as global options placed
before the subcommand name (e.g., `kanon --quiet install`):

| Flag | Description |
|------|-------------|
| `--quiet` | Suppress all output except errors. Sets the root logger to WARNING level. |
| `--verbose` | Enable debug-level output. Sets the root logger to DEBUG level. |
| `--no-color` | Disable ANSI color output unconditionally. |

### Mutual exclusion: --quiet and --verbose

`--quiet` and `--verbose` are mutually exclusive. Passing both flags at the same
time causes argparse to exit immediately with a non-zero code and an error message
on stderr. There is no fallback or silent suppression -- this is a hard error per
spec Section 7.

```bash
# ERROR: argument --verbose: not allowed with argument --quiet
kanon --quiet --verbose install .kanon
```

### Color output: --no-color and the NO_COLOR environment variable

Color output is controlled by the following precedence chain (highest wins):

1. `--no-color` flag -- always disables color when passed, regardless of the
   `NO_COLOR` environment variable or TTY state.
2. `NO_COLOR` environment variable -- when set to any non-empty value, disables
   color output following the https://no-color.org convention.
3. TTY auto-detection -- color is enabled by default when stdout is a TTY and
   neither of the above conditions applies.

```bash
# Disable color via flag (highest precedence)
kanon --no-color install .kanon

# Disable color via environment variable
NO_COLOR=1 kanon install .kanon

# --no-color wins even when NO_COLOR is empty
NO_COLOR= kanon --no-color install .kanon
```

The `.kanon` file is a shell-compatible KEY=VALUE configuration file that drives the Kanon lifecycle.

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

If the referenced variable is not set in the environment, parsing fails with a descriptive error.

## Environment Variable Overrides

Every `.kanon` variable can be overridden by an environment variable of the same name. This enables CI/CD pipelines to customize behavior without modifying the file.

Additionally, the following environment variables control internal timeouts and path overrides:

| Variable | Default | Description |
|----------|---------|-------------|
| `KANON_GIT_LS_REMOTE_TIMEOUT` | `30` | Timeout in seconds for `git ls-remote` calls used by SHA reachability checks and ref resolution in the install engine. |
| `KANON_LOCK_FILE` | _(derived)_ | Override the lock file path. When set to a non-empty value, kanon reads and writes the lock file at this path instead of the default derived from `--kanon-file` (i.e. `<kanon-file-path>.lock`). The `--lock-file` CLI flag takes precedence when both are set. An empty-string value is treated as unset. See `docs/lockfile.md` for the full precedence chain. |
| `KANON_ALLOW_INSECURE_REMOTES` | _(unset)_ | When set to exactly `1`, disables the insecure-remote-URL security check in `kanon install`. All remote URL schemes (HTTP, `file://`, `git://`, etc.) are accepted without error. Any value other than `1` is treated as unset. See the security note below. |

### KANON_ALLOW_INSECURE_REMOTES -- security rationale

kanon enforces a trust model (spec Section 3.6) that requires all `<remote>` fetch URLs in
resolved manifests to use HTTPS or SSH. Plain HTTP, `file://`, `git://`, and other unencrypted
schemes are rejected by default because they expose dependency resolution to network-level
interception and tampering.

**Allowed unconditionally:**
- `https://...` -- encrypted, authenticated.
- `git@host:org/repo.git` -- SCP-style SSH shorthand; encrypted, key-authenticated.
- `ssh://...` -- explicit SSH protocol; encrypted, key-authenticated.

**Rejected by default (allowed only with `KANON_ALLOW_INSECURE_REMOTES=1`):**
- `http://...` -- unencrypted; traffic can be intercepted and modified in transit.
- `file://...` -- local filesystem path; no network-level guarantees, and a path that
  is valid in one environment may resolve to something different in another.
- Any other scheme (`git://`, `ftp://`, custom schemes, or empty URL).

**Override:** Set `KANON_ALLOW_INSECURE_REMOTES=1` to disable the check. The override is
intentionally narrow: only the exact string `1` enables it. Values such as `true`, `yes`,
`on`, or `0` do NOT enable the override and leave the policy enforced.

```bash
# Default: HTTP remote rejected
kanon install .kanon  # exits 1 if any <remote> uses http://

# Override: HTTP remote accepted
KANON_ALLOW_INSECURE_REMOTES=1 kanon install .kanon
```

The check also runs on the lockfile-consistent replay path: even if a lockfile was
recorded with an HTTP URL, `kanon install` rejects it. This defends against a malicious
or tampered lockfile injecting an insecure remote for a subsequent install. See
`docs/lockfile.md` for details on how replay enforcement works.

## Multi-Source Groups

Sources are auto-discovered from `KANON_SOURCE_<name>_URL` variable patterns and processed in alphabetical order by name:

```properties
KANON_SOURCE_build_URL=https://github.com/org/build-repo.git
KANON_SOURCE_build_REVISION=main
KANON_SOURCE_build_PATH=repo-specs/meta.xml

KANON_SOURCE_marketplaces_URL=https://github.com/org/mp-repo.git
KANON_SOURCE_marketplaces_REVISION=main
KANON_SOURCE_marketplaces_PATH=repo-specs/marketplaces.xml
```

Each source requires `_URL`, `_REVISION`, and `_PATH` suffixed variables.

## KANON_CATALOG_SOURCE Environment Variable

The `KANON_CATALOG_SOURCE` environment variable specifies the catalog repository
used by `kanon install` to resolve version specs. It follows the `<url>@<ref>` form:

```bash
export KANON_CATALOG_SOURCE=https://github.com/example-org/kanon-catalog.git@main
kanon install .kanon
```

**Precedence (highest to lowest):**

1. `--catalog-source` CLI flag (**pending**: not yet registered on `kanon install`;
   see task E1-F4-S1-T1. Currently only `KANON_CATALOG_SOURCE` and lockfile fallback
   are active.)
2. `KANON_CATALOG_SOURCE` environment variable
3. `lockfile.[catalog].source` (fallback -- applies only in the `LOCKFILE_CONSISTENT`
   state and only when both the CLI flag and env var are unset)

When none of the three sources is set and the lockfile fallback is not applicable,
`kanon install` raises `MissingCatalogSourceError` with remediation text. See the
catalog source configuration section above for details on how to configure a catalog.

When the CLI flag or env var is set and differs from the lockfile's recorded
`[catalog].source`, `kanon install` raises `CatalogSourceMismatchError`. The lockfile
is authoritative; run `kanon install --refresh-lock` to intentionally change catalogs.

See `docs/architecture.md` for the full precedence and mismatch-detection logic.

## KANON_MARKETPLACE_INSTALL Toggle

When `KANON_MARKETPLACE_INSTALL=true`:

- `kanon install` creates and cleans `CLAUDE_MARKETPLACES_DIR`, then runs the install script post-sync
- `kanon clean` runs the uninstall script and removes `CLAUDE_MARKETPLACES_DIR`

When `false` (default), marketplace lifecycle is skipped entirely.

## KANON_OUTDATED_FORMAT

Controls the output format of the `kanon outdated` command.

| Variable | Default | Description |
|----------|---------|-------------|
| `KANON_OUTDATED_FORMAT` | `table` | Output format for `kanon outdated`. Currently only `table` is supported. Additional formats will be added in a future release. |

**Precedence:** `--format` CLI flag wins over `KANON_OUTDATED_FORMAT` env var; the env var wins over
the built-in default (`table`).

```bash
# Use the default table format
kanon outdated --catalog-source file:///catalog@HEAD

# Override via environment variable (only table supported in this release)
KANON_OUTDATED_FORMAT=table kanon outdated --catalog-source file:///catalog@HEAD

# Override via CLI flag (takes precedence over env var)
kanon outdated --format table --catalog-source file:///catalog@HEAD
```

The constant `KANON_OUTDATED_FORMAT` (env var name) and `KANON_OUTDATED_FORMAT_DEFAULT` (default
value `"table"`) are both defined in `src/kanon_cli/constants.py`.

## KANON_WHY_FORMAT

Controls the output format of the `kanon why` command.

| Variable | Default | Description |
|----------|---------|-------------|
| `KANON_WHY_FORMAT` | `text` | Output format for `kanon why`. Supported values: `text` (human-readable arrow-separated chains) and `json` (machine-readable JSON array). |

**Precedence:** `--format` CLI flag wins over `KANON_WHY_FORMAT` env var; the env var wins over
the built-in default (`text`).

```bash
# Use the default text format
kanon why https://github.com/org/myproject

# Select JSON format via environment variable
KANON_WHY_FORMAT=json kanon why https://github.com/org/myproject

# Override via CLI flag (takes precedence over env var)
kanon why https://github.com/org/myproject --format json
```

The constant `KANON_WHY_FORMAT` (env var name) and `KANON_WHY_FORMAT_DEFAULT` (default
value `"text"`) are both defined in `src/kanon_cli/constants.py`.

## KANON_WHY_JSON_INDENT

Controls the JSON indentation level used by `json.dumps` when `kanon why --format json` is
selected.

| Variable | Default | Description |
|----------|---------|-------------|
| `KANON_WHY_JSON_INDENT` | `2` | Number of spaces per indentation level in JSON output from `kanon why --format json`. |

This variable is optional. When unset, the default value of `2` is used. The value must be a
non-negative integer (>= 0) parseable by Python `int()`. Setting the value to `0` produces
newline-only formatting without indentation, which is valid JSON but difficult to read; a value
of `1` or greater is recommended for human-readable output.

```bash
# Use the default indentation of 2 spaces
kanon why https://github.com/org/myproject --format json

# Use 4-space indentation
KANON_WHY_JSON_INDENT=4 kanon why https://github.com/org/myproject --format json
```

The constant `KANON_WHY_JSON_INDENT` (default `2`) is defined in `src/kanon_cli/constants.py`.

## KANON_WHY_SUGGEST_MAX_DISTANCE

Controls the maximum Levenshtein edit distance for closest-match suggestions when `kanon why`
cannot find the requested argument in the resolved dependency tree.

| Variable | Default | Description |
|----------|---------|-------------|
| `KANON_WHY_SUGGEST_MAX_DISTANCE` | `3` | Maximum edit distance (insertions, deletions, substitutions) for a candidate to appear in the suggestion list on not-found. |

Only candidates whose Levenshtein distance to the argument is less than or equal to this value
are eligible. The candidate universe is the union of all source names, XML manifest paths, and
canonical project URLs in the resolved tree.

This variable is optional. When unset, the default value of `3` is used. The value must be a
non-negative integer parseable by Python `int()`; a non-integer value causes an error at startup.

```bash
# Use the default threshold of 3
kanon why fooo

# Narrow the suggestion window to distance 1 only
KANON_WHY_SUGGEST_MAX_DISTANCE=1 kanon why fooo

# Disable suggestions entirely (threshold 0 means only exact matches are eligible)
KANON_WHY_SUGGEST_MAX_DISTANCE=0 kanon why fooo
```

The constant `KANON_WHY_SUGGEST_MAX_DISTANCE` (default `3`) is defined in
`src/kanon_cli/constants.py`.

## KANON_WHY_SUGGEST_TOP_N

Controls the maximum number of closest-match suggestions shown when `kanon why` cannot find
the requested argument in the resolved dependency tree.

| Variable | Default | Description |
|----------|---------|-------------|
| `KANON_WHY_SUGGEST_TOP_N` | `3` | Maximum number of candidates to display in the suggestion list on not-found. Results are sorted ascending by edit distance, with ties broken lexicographically. |

This variable is optional. When unset, the default value of `3` is used. The value must be a
non-negative integer parseable by Python `int()`; a non-integer value causes an error at startup.

```bash
# Use the default cap of 3 suggestions
kanon why fooo

# Show only the single closest match
KANON_WHY_SUGGEST_TOP_N=1 kanon why fooo

# Show up to 5 suggestions
KANON_WHY_SUGGEST_TOP_N=5 kanon why fooo
```

The constant `KANON_WHY_SUGGEST_TOP_N` (default `3`) is defined in
`src/kanon_cli/constants.py`.

## Doctor Cache Management

The `kanon doctor` command supports two optional cache-management flags:
`--refresh-completion-cache` (subcheck 8) and `--prune-cache` (subcheck 10).
The following environment variables control their behaviour.

### KANON_CACHE_PRUNE_AGE_DAYS

| Variable | Default | Description |
|----------|---------|-------------|
| `KANON_CACHE_PRUNE_AGE_DAYS` | `30` | Files under `${KANON_CACHE_DIR}` whose last-access time is older than this many days are removed by `kanon doctor --prune-cache`. Must be a positive integer. |

This variable is optional. When unset, the default value of `30` is used. Values of 0 or below
are rejected with a clear error at startup.

```bash
# Use the default 30-day threshold
kanon doctor --prune-cache

# Prune files not accessed in the last 7 days
KANON_CACHE_PRUNE_AGE_DAYS=7 kanon doctor --prune-cache
```

The constant `KANON_CACHE_PRUNE_AGE_DAYS` (default `30`) is defined in `src/kanon_cli/constants.py`.

### KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH

| Variable | Default | Description |
|----------|---------|-------------|
| `KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH` | `4` | Maximum directory depth below the current working directory that `kanon doctor --prune-cache` searches for stale `.kanon-data/.kanon-install.lock` files. Bounds filesystem traversal to prevent wandering the entire filesystem in a misconfigured workspace. Must be a positive integer. |

This variable is optional. When unset, the default value of `4` is used. Values of 0 or below
are rejected with a clear error at startup.

```bash
# Use the default depth of 4
kanon doctor --prune-cache

# Restrict scan to 2 levels deep
KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH=2 kanon doctor --prune-cache
```

The constant `KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH` (default `4`) is defined in `src/kanon_cli/constants.py`.

### KANON_DOCTOR_STALE_LOCK_AGE_HOURS

| Variable | Default | Description |
|----------|---------|-------------|
| `KANON_DOCTOR_STALE_LOCK_AGE_HOURS` | `1` | Minimum age in hours for a `.kanon-data/.kanon-install.lock` file to be considered stale by `kanon doctor --prune-cache`. Stale locks are reported as advisory findings only -- doctor never deletes them. Must be a positive integer. |

`fcntl.flock` self-cleans on process exit, so a leftover lock file is harmless. The advisory
finding is informational: it tells the operator that a lock file is older than expected and
may correspond to a crashed install. No action is required unless the operator suspects a
genuine issue.

```bash
# Use the default 1-hour threshold
kanon doctor --prune-cache

# Treat locks older than 4 hours as stale
KANON_DOCTOR_STALE_LOCK_AGE_HOURS=4 kanon doctor --prune-cache
```

The constant `KANON_DOCTOR_STALE_LOCK_AGE_HOURS` (default `1`) is defined in `src/kanon_cli/constants.py`.

## kanon repo Subcommand

The `kanon repo` subcommand exposes kanon's repo subsystem for direct manifest operations, allowing direct
invocation of any `repo` subcommand (such as `init`, `sync`, `version`, `help`) without requiring
a separate `repo` installation.

### KANON_REPO_DIR

| Variable | Default | Description |
|----------|---------|-------------|
| `KANON_REPO_DIR` | `.repo` | Path to the `.repo` working directory used by `kanon repo` |

This variable controls where `kanon repo` looks for (or creates) the `.repo` directory. It
corresponds to the `--repo-dir` flag on the `kanon repo` subcommand.

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
