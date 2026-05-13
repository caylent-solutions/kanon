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

```bash
KANON_SOURCE_build_REVISION=refs/tags/~=2.0.0 kanon install .kanon
```

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
