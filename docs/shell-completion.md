# Shell Completion

kanon supports tab-completion for bash and zsh via `kanon completion <shell>`.

## Preamble Overview

The generated completion script includes a preamble block that defines kanon-specific
shell helper functions used for dynamic argument lookup. These helpers are sourced once
when the completion script is loaded, and invoked each time the user presses Tab on a
supported argument position.

### How helpers work

Each helper shells out to a corresponding `kanon __complete_<name>` subcommand to
retrieve candidate lists at completion time. For example:

- `_kanon_complete_catalog_entries` -- retrieves available catalog entry names.
- `_kanon_complete_source_names_in_kanon` -- retrieves source names defined in `.kanon`.
- `_kanon_complete_names_in_lockfile` -- retrieves names recorded in the lock file.
- `_kanon_complete_catalog_versions` -- retrieves available catalog versions.
- `_kanon_complete_project_versions` -- retrieves available versions for a project URL.
- `_kanon_complete_cached_catalogs` -- retrieves locally cached catalog identifiers.

### Mid-token splitter

`_kanon_complete_add_arg` is the mid-token splitter helper used when completing
`kanon add foo@<TAB>` style arguments. The body shipped with this release is a
placeholder that calls `_kanon_complete_catalog_entries` unconditionally. The full
`@`-splitting logic is added in a subsequent task.

### Controlling completion behaviour

Two environment variables control how preamble helpers behave at completion time.
See [Configuration](configuration.md) for the full reference.

| Variable | Default | Effect |
|---|---|---|
| `KANON_COMPLETION_ENABLED` | `1` | Set to `0` to disable all completion lookups globally. |
| `KANON_COMPLETION_TIMEOUT` | `2` | Timeout in seconds for each `kanon __complete_*` subprocess call. |

### Quick start

```bash
# bash -- add to ~/.bashrc or ~/.bash_profile
eval "$(kanon completion bash)"

# zsh -- add to ~/.zshrc
eval "$(kanon completion zsh)"
```

After sourcing the script, Tab-completion is active for all kanon subcommands and
their dynamic arguments.

> The full operator guide, including fish support and troubleshooting steps,
> ships in a subsequent release.
