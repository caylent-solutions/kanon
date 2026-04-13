# Configuration (.kanon)

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

Every `.kanon` variable can be overridden by an environment variable of the same name. This enables CI/CD pipelines to customize behavior without modifying the file:

```bash
REPO_REV=v3.0.0 kanon install .kanon
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

## KANON_MARKETPLACE_INSTALL Toggle

When `KANON_MARKETPLACE_INSTALL=true`:

- `kanon install` creates and cleans `CLAUDE_MARKETPLACES_DIR`, then runs the install script post-sync
- `kanon clean` runs the uninstall script and removes `CLAUDE_MARKETPLACES_DIR`

When `false` (default), marketplace lifecycle is skipped entirely.
