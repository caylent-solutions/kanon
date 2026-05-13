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
   the default derived path `<kanon-file>.lock`) the locked value is used as
   the `current` column. The exact field read depends on the revision shape: for
   tag-pinned sources `resolved_ref` is used; for branch-pinned sources
   `resolved_sha` is used (a full commit SHA stored at lock time). When absent,
   `current` is live-resolved from the catalog or branch HEAD.
4. **Three columns computed per source** (semantics depend on revision shape):
   - For **tag-pinned** sources: `current` is the version extracted from the
     locked/live-resolved tag; `latest-matching-spec` is the highest tag ref
     satisfying the `REVISION` constraint; `latest-available` is the highest
     tag ref under the prefix ignoring the constraint.
   - For **branch-pinned** sources: all three columns display a 12-char
     truncated SHA. `latest-matching-spec` and `latest-available` both show the
     current branch HEAD SHA (they are equal -- there is no cross-branch notion).
     See the Branch-pinned sources subsection below.
   - For **SHA-pinned** sources: all three columns display the same 12-char
     truncated SHA of the pinned commit. See the SHA-pinned sources subsection
     below.
5. **`upgrade-type`** -- the value depends on revision shape:
   - Tag-pinned: one of `none`, `patch`, `minor`, `major`, or `prerelease`,
     derived by comparing `current` vs `latest-matching-spec` via
     `packaging.version.Version`.
   - Branch-pinned: `drift` when the locked SHA differs from the branch HEAD
     SHA; `none` otherwise.
   - SHA-pinned: always `none` (a pinned SHA cannot drift).
6. **Exit code** -- always 0. A future release will add `--fail-on-upgrade` to exit non-zero when upgrades are available.

#### Branch-pinned sources

A source's `REVISION` is **branch-pinned** when it is neither a PEP 440 version
specifier nor a full-length hex SHA (40 or 64 chars) nor a `refs/tags/...` ref.
Common branch shapes: `main`, `develop`, `release/v1`, `feature/foo`.

For branch-pinned sources:

- Both `latest-matching-spec` and `latest-available` display the current HEAD
  SHA of the branch, truncated to **exactly 12 hex characters** (the leading 12
  chars, matching git's short-SHA convention). The branch HEAD is resolved via
  `git ls-remote <url> refs/heads/<branch>`.
- `upgrade-type` is `drift` when the locked SHA in `.kanon.lock` differs from
  the branch HEAD SHA at command time.
- `upgrade-type` is `none` when the locked SHA equals the branch HEAD SHA, or
  when no lockfile is present (in that case `current` is filled by live-resolving
  the branch HEAD SHA, which equals the `latest-*` columns).
- There is no "latest available across all branches" notion. Both `latest-matching-spec`
  and `latest-available` always display the same 12-char HEAD SHA for the pinned
  branch. Operators who want cross-branch upgrade visibility should switch to
  tag-based pinning.

#### SHA-pinned sources

A source is **SHA-pinned** when its `REVISION` is a 40- or 64-character
hexadecimal commit SHA. A pinned SHA cannot drift -- the operator explicitly
pinned to that exact commit. All three of `current`, `latest-matching-spec`, and
`latest-available` display the same 12-char truncation of the pinned SHA.
`upgrade-type` is always `none`.

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
