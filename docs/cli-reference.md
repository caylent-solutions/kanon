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

Explain why a transitive project, XML manifest include, or catalog source is in the
resolved dependency tree.

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
3. **Argument matching -- all three categories are evaluated before deciding (no short-circuit):**

   **(a) `<project>` repo URL (most common).**
   The argument is attempted through `core/url.py::canonicalize_repo_url`. When
   canonicalization succeeds, the canonical form is matched against every `<project>`
   node's stored canonical URL. SCP shorthand (`git@github.com:org/repo.git`),
   `https://`, `ssh://`, trailing `.git`, and trailing `/` are all normalised before
   comparison.

   **(b) Transitive XML manifest path.**
   The argument is matched by exact string equality against every `<include>` node's
   `path_in_repo` value (e.g., `repo-specs/git-connection/remote.xml`). Partial paths
   do NOT match -- the full manifest-relative path is required.

   **(c) Top-level source name.**
   The argument is normalized via `derive_source_name()` (lowercase, replace `-` with
   `_`) and compared against the normalized set of `KANON_SOURCE_<name>_*` tokens from
   the `.kanon` file. This makes matching case- and separator-insensitive: argument
   `Foo-Bar` matches source token `FOO_BAR` because both normalize to `foo_bar`.

4. **Ambiguity detection (spec Section 4.5 step 3).**
   If the argument matches in two or more categories, the command exits non-zero with
   an error listing every matching interpretation (category name + matched value):

   ```
   ERROR: argument 'Repo-Specs-Foo' is ambiguous -- matches multiple categories:
   XML manifest path 'Repo-Specs-Foo'; source name 'REPO_SPECS_FOO'.
   Pass the argument in its canonical form to disambiguate ...
   ```

   This condition is "extremely unlikely but possible with `file://` test fixtures"
   (spec Section 4.5 step 3) -- for example, when a `file://` URL happens to equal
   an XML manifest path stored in the lockfile.

5. For every chain in the tree passing through the matched node, print one line:

   ```
   <top-source> -> <include-path>@<sha> -> ... -> <project>@<sha>
   ```

6. **Not-found with closest-match suggestion (spec Section 4.5 step 5).**
   If the argument is not found across all three categories, the command exits non-zero
   with a closest-match suggestion list drawn from the union of all source names, XML
   manifest paths, and project URLs in the resolved tree.

   Candidates are ranked by Levenshtein edit distance (insertions, deletions,
   substitutions -- no transpositions) to the argument. Only candidates with distance
   `<= KANON_WHY_SUGGEST_MAX_DISTANCE` (default 3) are eligible. Results are sorted
   ascending by `(distance, value)` and capped to `KANON_WHY_SUGGEST_TOP_N` (default 3).

   When at least one candidate is within the threshold:

   ```
   ERROR: fooo not found in resolved tree
   Did you mean one of:
     foo
     repo-specs/foo/foo.xml
   ```

   When no candidate is within the threshold:

   ```
   ERROR: xyzzy not found in resolved tree
   No close matches found.
   ```

**Flags:**

| Flag | Env var | Default | Description |
|------|---------|---------|-------------|
| `<project-url-or-name>` (positional) | -- | required | Project URL, XML manifest path, or source name to look up. |
| `--catalog-source` | `KANON_CATALOG_SOURCE` | -- | Catalog source as `<git-url>@<ref>`. Required only when `.kanon.lock` is absent. |
| `--kanon-file` | `KANON_KANON_FILE` | `./.kanon` | Path to the `.kanon` file. |
| `--lock-file` | `KANON_LOCK_FILE` | `<kanon-file>.lock` | Path to the `.kanon.lock` file. |
| `--format` | `KANON_WHY_FORMAT` | `text` | Output format: `text` (default) or `json`. See JSON shape below. |

**JSON output shape (`--format json`):**

When `--format json` is selected, stdout receives a well-formed JSON array. Each
element of the outer array is one chain (a list of node objects). Nodes are ordered
top-level source first, leaf project last -- the same order as the text format:

```json
[
  [
    {"kind": "source",  "name": "<source-name>", "ref": null,          "sha": "<40-char-hex>", "url": "<catalog-url>"},
    {"kind": "include", "name": "<manifest-name>","ref": "<xml-path>",  "sha": "<40-char-hex>", "url": null},
    {"kind": "project", "name": "<project-name>", "ref": null,          "sha": "<40-char-hex>", "url": "<canonical-url>"}
  ]
]
```

Field semantics:

- **`kind`** -- one of `"source"`, `"include"`, `"project"`.
- **`name`** -- human-readable identifier (source token, XML manifest name, or project name).
- **`ref`** -- for `include` nodes: the `path_in_repo` value (e.g. `"repo-specs/bar.xml"`);
  `null` for `source` and `project` nodes.
- **`sha`** -- full 40-character hex commit SHA (never truncated).
- **`url`** -- for `project` nodes, the value is `node.canonical_url` (canonicalized via
  `canonicalize_repo_url`). For `source` nodes, the value is `node.url` (raw URL as stored in
  the lockfile). For `include` nodes, the value is `null` (XML manifest paths have no standalone
  URL).

Indent depth is controlled by `KANON_WHY_JSON_INDENT` (default `2`). Only the success-path
chain output is JSON-encoded. Ambiguity and not-found errors always emit plain-text to stderr
regardless of `--format`.

**Examples:**

```sh
# Find all chains reaching a project by https:// URL
kanon why https://github.com/org/myproject \
  --kanon-file ./.kanon \
  --lock-file ./.kanon.lock

# SCP shorthand and https:// forms are canonicalized -- both match the same project
kanon why git@github.com:org/myproject.git \
  --kanon-file ./.kanon

# Look up chains that pass through a specific XML manifest path
kanon why repo-specs/git-connection/remote.xml \
  --kanon-file ./.kanon \
  --lock-file ./.kanon.lock

# Look up all chains starting from a named source (case- and separator-insensitive)
kanon why my-source \
  --kanon-file ./.kanon \
  --lock-file ./.kanon.lock

# Disambiguate an ambiguous argument by using the full canonical project URL
kanon why https://github.com/org/myproject \
  --kanon-file ./.kanon \
  --lock-file ./.kanon.lock

# Emit JSON output and pipe to jq for processing
kanon why https://github.com/org/myproject --format json | jq '.[0] | length'
```

### `kanon bootstrap`

Scaffold a new Kanon project with catalog entry package files.

The `--catalog-source` flag on this command is registered by
`add_catalog_source_arg` from `kanon_cli.core.cli_args`.

```
kanon bootstrap [--output-dir OUTPUT_DIR] [--catalog-source <git-url>@<ref>] package
```
