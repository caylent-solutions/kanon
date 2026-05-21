# kanon list, add, and remove

Operator-facing reference for three core dependency-management
commands: `kanon list`, `kanon add`, and `kanon remove`.

For first-time setup see
[docs/catalogs-explained.md](catalogs-explained.md)
(created by E8-F1-S1-T01).
For the canonical environment-variable table see
[docs/configuration.md](configuration.md).

---

## kanon list

Discover catalog entries available in a manifest repo.

### list -- Synopsis

```text
kanon list [--catalog-source <git-url>@<ref>]
           [<substring>]
           [--detail] [--tree] [--max-depth N]
           [--all-versions] [--limit N | --no-limit]
           [--since-version <spec>]
           [--regex <pattern>] [--match-fields <csv>]
           [--format {names,json}]
           [--no-filter-required]
           [--no-color]
```

### list -- How it works

`kanon list` clones the manifest repo identified by
`--catalog-source` (or `KANON_CATALOG_SOURCE`) and walks every
`repo-specs/**/*-marketplace.xml` file. One entry is emitted per
XML file whose `<catalog-metadata>` block contains the required
fields. Entry name = `<catalog-metadata><name>`.

The legacy `catalog/<name>/` directory inside a manifest repo is
ignored; `kanon list` reads only the XML manifests.

### list -- Default output

```text
$ kanon list \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
package-a
package-b
package-c
```

One entry name per line. Output is streamed line-by-line; large
manifest repos do not buffer the full result in memory. The output
is pipeable directly into `kanon add`.

### list -- Flags

| Flag | Default | Description |
| ---- | ------- | ----------- |
| `--detail` | off | Per-entry name, type, description, version. |
| `--tree` | off | Dependency tree per entry. Excl. --all-versions. |
| `--max-depth N` | unlimited | Cap tree depth. 0 = entry only. |
| `--all-versions` | off | Walk historical versions. Excl. --tree. |
| `--limit N` | `50` | Cap for --all-versions. |
| `--no-limit` | off | Remove --all-versions cap. |
| `--since-version spec` | none | Restrict --all-versions to PEP 440 spec. |
| `--format {names,json}` | `names` | Output format. Env: KANON_LIST_FORMAT. |
| `substr` (positional) | none | Filter entries by substring. |
| `--regex pattern` | none | Filter by regex on same four fields. |
| `--match-fields csv` | all | Narrow filter fields. Requires a filter. |
| `--no-filter-required` | off | Skip filter for --tree on large catalogs. |
| `--catalog-source url@ref` | env | Catalog source. Env: KANON_CATALOG_SOURCE |
| `--no-color` | auto | Disable color output. |

### list -- Mutually exclusive combinations

The following combinations are hard errors:

| Combination | Error |
| ----------------------------------------- | ------ |
| `--tree` + `--all-versions` | Hard error |
| `--match-fields` without filter | Hard error |

`--tree` + `--all-versions`:

```text
ERROR: --tree and --all-versions are mutually exclusive.
```

`--match-fields` without `<substring>` or `--regex`:

```text
ERROR: --match-fields requires a filter
(substring or --regex).
```

### list -- Output format examples

**`--format names` (default)**

```text
$ kanon list \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
package-a
package-b
package-c
```

**`--format json`**

```json
[
  {"name": "package-a"},
  {"name": "package-b"},
  {"name": "package-c"}
]
```

**`--detail --format json`**

```json
[
  {
    "name": "package-a",
    "display-name": "Package A",
    "description": "Example dependency",
    "version": "1.4.2",
    "type": "library"
  }
]
```

### list -- Streaming behaviour

The default `names` format streams one line at a time as each XML
file is read. No full in-memory buffering.

`--tree` requires a filter when the catalog has more entries than
`KANON_TREE_NO_FILTER_THRESHOLD` (default 20). Without a filter:

```text
ERROR: --tree requires a filter for catalogs with more than
20 entries. Provide a <substring>, --regex <pattern>,
--max-depth 0, or pass --no-filter-required to override.
```

### list -- Zero-match behaviour

When a filter returns zero entries, the command exits 0 with empty
stdout. A note is written to stderr:

```text
0 entries match filter
```

### list -- Empty manifest repo

When the manifest repo has zero `*-marketplace.xml` files, the
command exits 0 with empty stdout and a note to stderr:

```text
manifest repo contains 0 entries
```

### list -- `--all-versions` worked example

```text
$ kanon list --all-versions --limit 3 \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
package-a@2.10.0
package-a@2.9.1
package-a@2.9.0
package-b@1.5.0
package-b@1.4.0
package-b@1.3.0
```

`--format json` for the same invocation emits an array of
`{name, version, ref, sha}` objects:

```json
[
  {
    "name": "package-a",
    "version": "2.10.0",
    "ref": "refs/tags/2.10.0",
    "sha": "abc1234..."
  }
]
```

### list -- Error scenarios

#### list error 1 -- Missing catalog source

Reproducer:

```bash
kanon list
```

Expected message:

```text
ERROR: list requires a catalog source.
Provide one of:
  --catalog-source <git-url>@<ref>
  KANON_CATALOG_SOURCE=<git-url>@<ref>

The CLI flag takes precedence when both are set.
A catalog source identifies a manifest repo (a git repository
whose repo-specs/ directory exposes installable kanon
dependencies).
See docs/catalogs-explained.md for what a manifest repo is.
See docs/configuration.md for the full configuration reference.
```

#### list error 2 -- `--match-fields` without filter

Reproducer:

```bash
kanon list --match-fields name \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Expected message:

```text
ERROR: --match-fields requires a filter
(substring or --regex).
```

#### list error 3 -- `--tree` with `--all-versions`

Reproducer:

```bash
kanon list --tree --all-versions \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Expected message:

```text
ERROR: --tree and --all-versions are mutually exclusive.
```

---

## kanon add

Add one or more catalog entries to a `.kanon` file.

### add -- Synopsis

```text
kanon add [--catalog-source <git-url>@<ref>]
          <name>[@<spec>] [<name>[@<spec>] ...]
          [--kanon-file <path>]
          [--force]
          [--dry-run]
          [--no-color]
```

### add -- How it works

`kanon add` locates the named catalog entries in the resolved
manifest repo, derives a source name for each, and appends a
`KANON_SOURCE_<source-name>_{URL,REVISION,PATH}` triple to the
target `.kanon` file. If the file does not yet exist, it is
created with the standard header.

`kanon add` does **not** validate `<remote>` resolvability
(soft-spot 4) or tag-format PEP 440 compliance (soft-spot 5).
Those checks belong to `kanon catalog audit`. A successful
`kanon add` does not guarantee a successful install.

### add -- Argument shape

```text
<name>[@<spec>]
```

- `<name>` must match a `<catalog-metadata><name>` value in
  the resolved manifest repo.
- `@<spec>` is optional. Default: the highest PEP 440-valid git
  tag on the manifest repo (see "Default spec resolution").
- Multiple `<name>[@<spec>]` arguments may be supplied in one
  invocation.

### add -- Default spec resolution

When `@<spec>` is omitted, `kanon add` queries the manifest
repo for its highest PEP 440-valid git tag via
`git ls-remote --tags`. If zero PEP 440-valid tags exist:

```text
ERROR: manifest repo has no PEP 440-valid tags; pin to a
branch or SHA explicitly
(e.g., 'kanon add foo@main') or ask the catalog author to
publish a release tag.
```

### add -- Explicit spec forms

**PEP 440 constraint** -- `==1.4.2`, `~=1.2`, `>=1.0` --
Resolves to the highest matching tag via `_resolve_constraint_from_tags`.

**PEP 440 range** -- `>=1.0,<2.0` --
Must be shell-quoted. See "Shell quoting" below.

**Bare PEP 440 version** -- `1.4.2` --
Resolves to `refs/tags/1.4.2`.

**Branch name** -- `main` --
Passes through to git as-is. Git resolves to `refs/heads/main`.

**Full git ref** -- `refs/tags/v1.0.0` --
Passes through unchanged.

**Raw SHA (40 or 64 hex)** -- `abc123...` --
Passes through unchanged; git resolves to the commit.

For the complete resolution rules see
`docs/version-resolution.md`.

### add -- Shell quoting for PEP 440 specs

PEP 440 range specifiers contain `>` and `<`, which the shell
interprets as redirection operators. Always quote the full
`<name>@<spec>` argument:

```bash
# Single quotes (recommended) -- quote the full <name>@<spec> argument
kanon add 'package-a@>=1.0,<2.0' \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main

# Single quotes work for any range style, e.g. ~=
kanon add 'package-a@~=1.2' \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Do NOT omit the quotes: `package-a@>=1.0,<2.0` passed without quotes causes the
shell to treat `>=` as a redirect operator, breaking the command silently.

Failing to quote a range spec causes the shell to redirect
stderr before kanon runs. kanon emits a friendly error when it
detects the resulting empty argument, but the shell-level
redirection may still create or truncate files in the working
directory.

### add -- Source-name derivation

The source name written into the `.kanon` triple is derived from
the entry name by a deterministic one-way normalization
(spec Section 1.1):

1. Lowercase the entry name.
2. Replace every `-` with `_`.

This normalization is applied unconditionally. The same input
always yields the same output.

Examples:

| Entry name | Derived source name |
| ---------- | ------------------- |
| `package-a` | `package_a` |
| `Package-A` | `package_a` |
| `MyTool` | `mytool` |
| `my-cool-lib` | `my_cool_lib` |

Worked example: `Package-A` normalizes to `package_a`.

The normalized source name appears in the
`KANON_SOURCE_<name>_*` triple keys. `kanon add` always writes
the normalized form verbatim.

### add -- File creation

When the target `.kanon` file does not exist, `kanon add`
creates it with the standard header before appending the source
triples:

```bash
GITBASE=<YOUR_GIT_ORG_BASE_URL>
CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
KANON_MARKETPLACE_INSTALL=<true|false>
```

### add -- Written triples

For each added entry, `kanon add` appends:

```bash
KANON_SOURCE_<source_name>_URL=<manifest_repo_url>
KANON_SOURCE_<source_name>_REVISION=<resolved_spec>
KANON_SOURCE_<source_name>_PATH=<path_to_marketplace_xml>
```

Output confirms every triple written:

```text
Wrote KANON_SOURCE_package_a_URL, _REVISION, _PATH to ./.kanon
```

### add -- Flags

| Flag | Default | Description |
| ---- | ------- | ----------- |
| `--kanon-file path` | `./.kanon` | Target file. Env: KANON_KANON_FILE. |
| `--force` | off | Overwrite existing block; collision is error without. |
| `--dry-run` | off | Print diff without modifying any file. Exit 0. |
| `--catalog-source url@ref` | env | Catalog source. Env: KANON_CATALOG_SOURCE |
| `--no-color` | auto | Disable color output. |

### add -- `--dry-run` semantics

With `--dry-run`, `kanon add` prints the diff that would be
written to the target file and exits 0 without modifying any
file:

```text
--- ./.kanon (existing)
+++ ./.kanon (proposed)
@@ ...
+KANON_SOURCE_package_a_URL=\
+  https://example.com/org/manifest-repo.git
+KANON_SOURCE_package_a_REVISION===1.4.2
+KANON_SOURCE_package_a_PATH=\
+  repo-specs/package-a/package-a-marketplace.xml
```

### add -- Collision behaviour

#### add -- Cross-entry collision in the same invocation

When two entries in the same `kanon add` invocation normalize to
the same source name, the command exits with a hard error before
touching the file:

```text
ERROR: source-name collision within this invocation:
both 'package-a' and 'Package-A' normalize to source name
'package_a'. Remove one of the requested entries.
```

#### add -- Destination-file collision

When the target `.kanon` file already contains a source block
for the same source name:

```text
ERROR: source-name 'package_a' already mapped to
https://example.com/org/manifest-repo.git
(revision ==1.3.0); requested mapping is
https://example.com/org/manifest-repo.git
(revision ==1.4.2).
Use --force to overwrite, or 'kanon remove package_a' first.
```

With `--force`, the existing block is replaced.

### add -- Error scenarios

#### add error 1 -- Unquoted PEP 440 range

Reproducer: run the `add` command with the spec argument unquoted, e.g.
`package-a@>=1.0,<2.0` passed without surrounding single quotes. The shell
treats `>=` as a redirect operator and the spec is never received by kanon.

Expected message (shell creates an empty redirection target):

```text
ERROR: received an empty spec argument. PEP 440 range
specifiers contain > and < which the shell treats as
redirection. Quote the argument:
kanon add 'package-a@>=1.0,<2.0'
```

#### add error 2 -- Missing catalog source

Reproducer:

```bash
kanon add package-a
```

Expected message:

```text
ERROR: add requires a catalog source.
Provide one of:
  --catalog-source <git-url>@<ref>
  KANON_CATALOG_SOURCE=<git-url>@<ref>

The CLI flag takes precedence when both are set.
A catalog source identifies a manifest repo (a git repository
whose repo-specs/ directory exposes installable kanon
dependencies).
See docs/catalogs-explained.md for what a manifest repo is.
See docs/configuration.md for the full configuration reference.
```

#### add error 3 -- Zero PEP 440 tags and no `@<spec>`

Reproducer (manifest repo has no PEP 440-valid tags):

```bash
kanon add package-a \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Expected message:

```text
ERROR: manifest repo has no PEP 440-valid tags; pin to a
branch or SHA explicitly
(e.g., 'kanon add package-a@main') or ask the catalog author
to publish a release tag.
```

#### add error 4 -- Cross-entry source-name collision

Reproducer:

```bash
kanon add package-a Package-A \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Expected message:

```text
ERROR: source-name collision within this invocation:
both 'package-a' and 'Package-A' normalize to source name
'package_a'. Remove one of the requested entries.
```

#### add error 5 -- Destination-file collision without `--force`

Reproducer (when `package_a` already exists in `.kanon`):

```bash
kanon add 'package-a@==1.5.0' \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Expected message:

```text
ERROR: source-name 'package_a' already mapped to
https://example.com/org/manifest-repo.git
(revision ==1.4.2); requested mapping is
https://example.com/org/manifest-repo.git
(revision ==1.5.0).
Use --force to overwrite, or 'kanon remove package_a' first.
```

#### add error 6 -- Entry missing required `<catalog-metadata>` fields

Reproducer (entry is missing required fields in the catalog):

```bash
kanon add broken-entry \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Expected message:

```text
ERROR: manifest repo
https://example.com/org/manifest-repo.git@main
has integrity issues (1); the catalog author must fix these
via 'kanon catalog audit'. Affected entries: broken-entry
```

---

## kanon remove

Remove one or more named source blocks from a `.kanon` file.

### remove -- Synopsis

```text
kanon remove [--kanon-file <path>]
             <name> [<name> ...]
             [--force]
             [--dry-run]
             [--no-color]
```

### remove -- Source name or entry name

`kanon remove` accepts **either** the source name (the
`<source-name>` token in `KANON_SOURCE_<source-name>_*`
triples) or the original entry name. Both forms are normalized
via the same derivation rule (lowercase + replace `-` with `_`).

Worked example:

```bash
# Both remove the same triple block:
kanon remove package-a   # entry name
kanon remove package_a   # source name (normalized form)
```

### remove -- Behaviour

1. Read the `.kanon` file. Fail-fast if the file is missing.
2. For each `<name>`, normalize to the source name and locate
   every line matching
   `KANON_SOURCE_<normalized>_{URL,REVISION,PATH}=...`.
   These three lines may be non-contiguous in hand-written
   `.kanon` files. All three are removed wherever they appear,
   preserving the order of remaining content.
3. If fewer than three matching lines are found, hard error:
   `source 'X' (normalized form 'Y') not fully present in
   .kanon; found <n> of 3 expected KANON_SOURCE_<Y>_* keys`.
4. Comments adjacent to removed keys are not removed
   automatically; all other content is preserved byte-for-byte
   except for the three removed lines.

### remove -- Line-ending preservation

`kanon remove` writes the file back with these rules:

| Condition | Behaviour |
| --------- | --------- |
| LF only | LF preserved throughout |
| CRLF only | CRLF preserved throughout |
| Mixed LF and CRLF | Normalized to LF; warning to stderr |
| Trailing newline | File ends with exactly one `\n` |
| 3 or more consecutive blank lines | Collapsed to 2 |

Mixed line-ending warning:

```text
WARNING: mixed line endings detected; normalizing to LF
```

### remove -- Non-contiguous triple handling

The three `KANON_SOURCE_<name>_{URL,REVISION,PATH}` lines are
removed wherever they appear in the file, even if they are not
adjacent. All other content (including interleaved comments and
other keys) is preserved in its original order.

### remove -- Flags

| Flag | Default | Description |
| ---- | ------- | ----------- |
| `--kanon-file path` | `./.kanon` | Target file. |
| `--force` | off | Allow removal of unknown source names. |
| `--dry-run` | off | Print diff without modifying any file. |
| `--no-color` | auto | Disable color output. |

### remove -- `--dry-run` semantics

With `--dry-run`, `kanon remove` prints what would be removed
and exits 0 without modifying any file:

```text
--- ./.kanon (existing)
+++ ./.kanon (proposed)
@@ ...
-KANON_SOURCE_package_a_URL=\
-  https://example.com/org/manifest-repo.git
-KANON_SOURCE_package_a_REVISION===1.4.2
-KANON_SOURCE_package_a_PATH=\
-  repo-specs/package-a/package-a-marketplace.xml
```

### remove -- Lockfile interaction

If `.kanon.lock` exists and references the removed source, the
next `kanon install` detects the orphan and prunes it by
default. With `--strict-lock` on `kanon install`, the orphan
is a hard error.

### remove -- Error scenarios

#### remove error 1 -- Unknown source name without `--force`

Reproducer:

```bash
kanon remove nonexistent-entry
```

Expected message:

```text
ERROR: source 'nonexistent-entry'
(normalized form 'nonexistent_entry') not fully present in
.kanon; found 0 of 3 expected
KANON_SOURCE_nonexistent_entry_* keys. Use --force to
remove partial or unknown entries.
```

#### remove error 2 -- Missing `.kanon` file

Reproducer:

```bash
kanon remove package-a
```

Expected message (when no `.kanon` exists):

```text
ERROR: .kanon not found in current directory. Run 'kanon add'
to create a kanon workspace.
```

---

## Environment variables

The following environment variables affect `kanon list`,
`kanon add`, and `kanon remove`. For the full configuration
reference see [docs/configuration.md](configuration.md).

**`KANON_CATALOG_SOURCE`** -- `list`, `add`

Catalog source as `<git-url>@<ref>`. CLI flag
`--catalog-source` takes precedence when both are set.

**`KANON_LIST_FORMAT`** -- `list`

Default output format (`names` or `json`). Overridden by
`--format`.

**`KANON_LIST_LIMIT`** -- `list`

Default `--all-versions` cap. Default value: `50`. Overridden
by `--limit` or `--no-limit`.

**`KANON_TREE_NO_FILTER_THRESHOLD`** -- `list`

Entry count above which `--tree` requires a filter. Default:
`20`.

**`KANON_KANON_FILE`** -- `add`, `remove`

Default target file path. Default: `./.kanon`. Overridden by
`--kanon-file`.

**`NO_COLOR`** -- all commands

When set to any non-empty value, disables color output.

**`KANON_GIT_RETRY_COUNT`** -- `list`, `add`

Number of `git ls-remote` retries on transient errors.
Default: `3`.

**`KANON_GIT_RETRY_DELAY`** -- `list`, `add`

Seconds between `git ls-remote` retries. Default: `1`.
