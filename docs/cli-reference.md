# kanon CLI Reference

This document is the canonical reference for kanon's command-line flags, shared
argument factories, and environment variables that control CLI behaviour.

## Shared Argument Factories

### `kanon_cli.core.cli_args`

The module `src/kanon_cli/core/cli_args.py` provides reusable argparse argument
factories. Every command that requires a given flag MUST register it via the
corresponding factory rather than inlining `parser.add_argument(...)`.

This ensures consistent metavar, help text, default resolution, and env-var
coupling across all sub-commands.

#### `add_catalog_source_arg(parser)`

Adds the `--catalog-source` flag to `parser`.

```
--catalog-source <git-url>@<ref>
```

- **dest**: `catalog_source`
- **metavar**: `<git-url>@<ref>`
- **env var**: `KANON_CATALOG_SOURCE` (constant `CATALOG_ENV_VAR` in
  `kanon_cli.constants`)
- **precedence**: CLI flag wins over env var; env var wins over built-in default
  (`None`), per spec Section 4 header.

**Usage for contributors authoring a new command:**

```python
from kanon_cli.core.cli_args import add_catalog_source_arg

def register(subparsers) -> None:
    parser = subparsers.add_parser("my-command", ...)
    add_catalog_source_arg(parser)
    parser.set_defaults(func=_run)
```

Do NOT inline `parser.add_argument("--catalog-source", ...)` -- use the factory
so that future changes to metavar, help text, or default logic propagate
automatically to every sub-command.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `KANON_CATALOG_SOURCE` | Remote catalog as `<git_url>@<ref>`. Sets the default for every command that accepts `--catalog-source`. | (none) |

## Commands

### `kanon outdated`

Compare installed sources against the catalog and report which are behind.

Reads the `.kanon` file, resolves the catalog, and emits one row per
`KANON_SOURCE_<name>_*` block containing:

```
name | current | latest-matching-spec | latest-available | upgrade-type
```

**Behaviour (spec Section 4.4):**

1. **Catalog required** -- `--catalog-source` or `KANON_CATALOG_SOURCE` must be
   set. When neither is present the command exits non-zero with
   `ERROR: no catalog source configured` and a remediation pointer.
2. **`.kanon` required** -- the file at `--kanon-file` (default `./.kanon`) must
   exist. When absent the command exits non-zero naming the missing path.
3. **Lockfile optional** -- when `.kanon.lock` is present (at `--lock-file` or
   the default derived path `<kanon-file>.lock`) its `resolved_ref` is used as
   the `current` column. When absent `current` is live-resolved from the catalog.
4. **Three columns computed per source:**
   - `current` -- locked ref or live-resolved ref (version extracted from the tag).
   - `latest-matching-spec` -- highest ref satisfying the source's `REVISION` constraint.
   - `latest-available` -- highest ref under the prefix ignoring the constraint.
5. **`upgrade-type`** -- one of `none`, `patch`, `minor`, `major`, or `prerelease`,
   derived by comparing `current` vs `latest-matching-spec` via `packaging.version.Version`.
6. **Exit code** -- always 0. A future release will add `--fail-on-upgrade` to exit non-zero when upgrades are available.

**Flags:**

```
kanon outdated [--catalog-source <git-url>@<ref>]
               [--kanon-file <path>]
               [--lock-file <path>]
               [--format {table}]
```

| Flag | Env var | Default | Description |
|------|---------|---------|-------------|
| `--catalog-source` | `KANON_CATALOG_SOURCE` | (none) | Manifest repo as `<git_url>@<ref>`. Required. |
| `--kanon-file` | `KANON_KANON_FILE` | `./.kanon` | Path to the `.kanon` file. |
| `--lock-file` | `KANON_LOCK_FILE` | `<kanon-file>.lock` | Path to the lockfile. Optional; derived from `--kanon-file` when absent. |
| `--format` | `KANON_OUTDATED_FORMAT` | `table` | Output format. Only `table` supported in this release. |

**Example:**

```bash
kanon outdated \
  --catalog-source https://github.com/my-org/manifest-repo.git@main \
  --kanon-file ./.kanon \
  --lock-file ./.kanon.lock
```

### `kanon bootstrap`

Scaffold a new Kanon project with catalog entry package files.

The `--catalog-source` flag on this command is registered by
`add_catalog_source_arg` from `kanon_cli.core.cli_args`.

```
kanon bootstrap [--output-dir OUTPUT_DIR] [--catalog-source <git-url>@<ref>] package
```
