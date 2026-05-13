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
| `KANON_OUTDATED_JSON_INDENT` | Controls JSON indentation (number of spaces) used by `kanon outdated --format json`. | `2` |

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
6. **Exit code** -- always 0 by default, matching the convention of `pip list --outdated`,
   `npm outdated`, and `cargo outdated` (spec Section 0.2). Pass `--fail-on-upgrade` to exit 1
   when ANY source has an available upgrade (i.e. any row whose `upgrade-type` is not `none`).
   This is the CI-gate use case: a workflow runs `kanon outdated --fail-on-upgrade` and the
   build fails when any source is upgradable, prompting the operator to refresh the lockfile.
   The row content (column values) is identical whether or not the flag is set; only the exit
   code differs.

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
               [--format {table,json}]
               [--fail-on-upgrade]
```

| Flag | Env var | Default | Description |
|------|---------|---------|-------------|
| `--catalog-source` | `KANON_CATALOG_SOURCE` | (none) | Manifest repo as `<git_url>@<ref>`. Required. |
| `--kanon-file` | `KANON_KANON_FILE` | `./.kanon` | Path to the `.kanon` file. |
| `--lock-file` | `KANON_LOCK_FILE` | `<kanon-file>.lock` | Path to the lockfile. Optional; derived from `--kanon-file` when absent. |
| `--format` | `KANON_OUTDATED_FORMAT` | `table` | Output format: `table` (default) or `json`. The CLI flag takes precedence over the env var. |
| `--fail-on-upgrade` | (none) | off | Exit 1 when any source has an available upgrade (`upgrade-type != none`). Default is always exit 0 -- parity with `pip list --outdated`, `npm outdated`, `cargo outdated` (spec Section 0.2). Use this flag in CI pipelines to gate on lockfile freshness. |

#### JSON output format (`--format json`)

When `--format json` is selected (or `KANON_OUTDATED_FORMAT=json` is set), the command emits
a top-level JSON array to stdout. Each element represents one source from the `.kanon` file
and contains exactly five keys matching the table column headers:

```json
[
  {
    "name": "<source-name>",
    "current": "<sha-or-tag-or-ref>",
    "latest-matching-spec": "<sha-or-tag-or-ref>",
    "latest-available": "<sha-or-tag-or-ref>",
    "upgrade-type": "none|patch|minor|major|prerelease|drift"
  }
]
```

Notes:

- Key names use hyphens (matching the table column headers) for parity with human-readable
  output.
- The JSON is pretty-printed with 2 spaces of indentation (configurable via the
  `KANON_OUTDATED_JSON_INDENT` environment variable). A trailing newline is appended for
  POSIX-tool friendliness.
- For branch-pinned and SHA-pinned sources, the `current`, `latest-matching-spec`, and
  `latest-available` fields contain the 12-character truncated SHA (consistent with table
  output).
- `--fail-on-upgrade` exit-code logic is independent of format selection: the same source
  data produces the same exit code regardless of whether `table` or `json` is chosen.

**Example (two sources: one tag-pinned, one branch-pinned):**

```json
[
  {
    "name": "FOO",
    "current": "1.0.0",
    "latest-matching-spec": "1.0.1",
    "latest-available": "1.1.0",
    "upgrade-type": "patch"
  },
  {
    "name": "MYLIB",
    "current": "abc123456789",
    "latest-matching-spec": "def012345678",
    "latest-available": "def012345678",
    "upgrade-type": "drift"
  }
]
```

**Example:**

```bash
kanon outdated \
  --catalog-source https://github.com/my-org/manifest-repo.git@main \
  --kanon-file ./.kanon \
  --lock-file ./.kanon.lock

kanon outdated \
  --catalog-source https://github.com/my-org/manifest-repo.git@main \
  --format json | jq '.[] | select(.["upgrade-type"] != "none")'
```

### `kanon why`

Explain why a transitive project is in the resolved dependency tree.

Reads the `.kanon` file and resolves the full dependency tree. When a `.kanon.lock`
file is present, the tree is built from lockfile entries (no network calls needed --
every node already has its resolved SHA).

> **Note:** Live-resolution (when no `.kanon.lock` is present) is not yet implemented.
> Running `kanon why` without a lockfile exits with:
> `ERROR: Live-resolution is not yet implemented. Run kanon install to generate a lockfile.`
> Run `kanon install` first to generate `.kanon.lock`, then use `kanon why`.

**Behaviour (spec Section 4.5):**

1. Read the `.kanon` file at `--kanon-file` (default `./.kanon`; env `KANON_KANON_FILE`).
2. Resolve the full dependency tree:
   - If `.kanon.lock` exists (at `--lock-file` or its derived default), read the tree
     from the lockfile -- every node carries its resolved SHA. No `git ls-remote` calls.
   - Otherwise, live-resolution is not yet implemented. Exit with a clear error message
     directing the user to run `kanon install`.
3. Locate all `<project>` nodes whose canonicalized URL equals the canonicalized argument
   (via `core/url.py::canonicalize_repo_url`). SCP shorthand, `https://`, `ssh://`,
   trailing `.git`, and trailing `/` are all normalised before comparison.
4. For every chain in the tree ending at the requested project, print one line:

   ```
   <top-source> -> <include-path>@<sha> -> ... -> <project>@<sha>
   ```

5. If the argument is not found in the resolved tree, the command exits non-zero with:
   `ERROR: <arg> not found in resolved tree`

**Flags:**

| Flag | Env var | Default | Description |
|------|---------|---------|-------------|
| `<project-url>` (positional) | -- | required | Project URL to look up. |
| `--catalog-source` | `KANON_CATALOG_SOURCE` | -- | Catalog source as `<git-url>@<ref>`. Required only when `.kanon.lock` is absent. |
| `--kanon-file` | `KANON_KANON_FILE` | `./.kanon` | Path to the `.kanon` file. |
| `--lock-file` | `KANON_LOCK_FILE` | `<kanon-file>.lock` | Path to the `.kanon.lock` file. |
| `--format` | `KANON_WHY_FORMAT` | `text` | Output format: `text` (default). JSON output is added in a later task. |

**Examples:**

```sh
# Find all chains reaching a project by https:// URL
kanon why https://github.com/org/myproject \
  --kanon-file ./.kanon \
  --lock-file ./.kanon.lock

# SCP shorthand and https:// forms are canonicalized -- both match the same project
kanon why git@github.com:org/myproject.git \
  --kanon-file ./.kanon
```

### `kanon bootstrap`

Scaffold a new Kanon project with catalog entry package files.

The `--catalog-source` flag on this command is registered by
`add_catalog_source_arg` from `kanon_cli.core.cli_args`.

```
kanon bootstrap [--output-dir OUTPUT_DIR] [--catalog-source <git-url>@<ref>] package
```
