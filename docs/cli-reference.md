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

### `kanon bootstrap`

Scaffold a new Kanon project with catalog entry package files.

The `--catalog-source` flag on this command is registered by
`add_catalog_source_arg` from `kanon_cli.core.cli_args`.

```
kanon bootstrap [--output-dir OUTPUT_DIR] [--catalog-source <git-url>@<ref>] package
```
