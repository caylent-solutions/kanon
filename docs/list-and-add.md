# kanon search, add, and remove

Operator-facing reference for three core dependency-management
commands: `kanon search`, `kanon add`, and `kanon remove`.

For first-time setup see
[docs/catalogs-explained.md](catalogs-explained.md)
(created by E8-F1-S1-T01).
For the canonical environment-variable table see
[docs/configuration.md](configuration.md).

---

## kanon search

Discover catalog entries available in a manifest repo.

### list -- Synopsis

```text
kanon search [--catalog-source <git-url>@<ref>]
           [<substring>]
           [--detail] [--tree] [--max-depth N]
           [-A | --all] [--limit N | --no-limit]
           [--since-version <spec>]
           [--regex <pattern>] [--match-fields <csv>]
           [--format {names,json}]
           [--no-filter-required]
           [--no-color]
```

### list -- How it works

`kanon search` clones the manifest repo identified by
`--catalog-source` (or `KANON_CATALOG_SOURCES`) and walks every
`repo-specs/**/*.xml` file. One entry is emitted per XML file whose
`<catalog-metadata>` block contains the required fields (the filename is
unrestricted -- the `-marketplace.xml` suffix is a convention, not a
requirement). Entry name = `<catalog-metadata><name>`.

The legacy `catalog/<name>/` directory inside a manifest repo is
ignored; `kanon search` reads only the XML manifests.

### list -- Default output

```text
$ kanon search \
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
| `--tree` | off | Dependency tree per entry. Excl. -A/--all. |
| `--max-depth N` | unlimited | Cap tree depth. 0 = entry only. |
| `-A`, `--all` | off | Walk historical versions. Excl. --tree. |
| `--limit N` | `50` | Cap for -A/--all. |
| `--no-limit` | off | Remove -A/--all cap. |
| `--since-version spec` | none | Restrict -A/--all to PEP 440 spec. |
| `--format {names,json}` | `names` | Output format. Env: KANON_LIST_FORMAT. |
| `substr` (positional) | none | Filter entries by substring. |
| `--regex pattern` | none | Filter by regex on same four fields. |
| `--match-fields csv` | all | Narrow filter fields. Requires a filter. |
| `--no-filter-required` | off | Skip filter for --tree on large catalogs. |
| `--catalog-source url[@ref]` | env | Catalog source; `@ref` optional. Env: KANON_CATALOG_SOURCES |
| `--catalog-default-branch name` | env | Branch used when the catalog source omits `@ref`. Env: KANON_CATALOG_DEFAULT_BRANCH (default `main`; `auto` = remote HEAD). |
| `--no-color` | auto | Disable color output. |

### list -- Mutually exclusive combinations

The following combinations are hard errors:

| Combination | Error |
| ----------------------------------------- | ------ |
| `--tree` + `-A`/`--all` | Hard error |
| `--match-fields` without filter | Hard error |

`--tree` + `-A`/`--all`:

```text
ERROR: --tree and -A/--all are mutually exclusive. Use --tree for dependency tree rendering, or -A/--all to list all available versions. These flags cannot be combined.
```

`--match-fields` without `<substring>` or `--regex`:

```text
ERROR: --match-fields requires a filter. Supply a positional <substring> or --regex <pattern> together with --match-fields.
```

### list -- Output format examples

**`--format names` (default)**

```text
$ kanon search \
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

When the manifest repo exposes zero installable catalog entries (no
`repo-specs/**/*.xml` file carries a complete `<catalog-metadata>`
block), the command exits 0 with empty stdout and a note to stderr:

```text
manifest repo contains 0 entries
```

### list -- `-A`/`--all` worked example

```text
$ kanon search -A --limit 3 \
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
kanon search
```

Expected message:

```text
ERROR: search requires a catalog source.
Provide one of:
  --catalog-source <git-url>@<ref>       # e.g. --catalog-source https://example.com/org/manifest-repo.git@main
  KANON_CATALOG_SOURCES=<git-url>@<ref>  # set as env var (one entry per line), then re-run

The CLI flag takes precedence when both are set.
A catalog source identifies a manifest repo (a git repository whose
repo-specs/ directory exposes installable kanon dependencies).
See docs/catalogs-explained.md for what a manifest repo is and how to find one.
See docs/configuration.md for the full configuration reference.
```

#### list error 2 -- `--match-fields` without filter

Reproducer:

```bash
kanon search --match-fields name \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Expected message:

```text
ERROR: --match-fields requires a filter. Supply a positional <substring> or --regex <pattern> together with --match-fields.
```

#### list error 3 -- `--tree` with `-A`/`--all`

Reproducer:

```bash
kanon search --tree -A \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Expected message:

```text
ERROR: --tree and -A/--all are mutually exclusive. Use --tree for dependency tree rendering, or -A/--all to list all available versions. These flags cannot be combined.
```

---

## kanon add

Add one or more catalog entries to a `.kanon` file.

### add -- Synopsis

```text
kanon add [--catalog-source <git-url>@<ref>]
          <name>[@<spec>] [<name>[@<spec>] ...]
          [--as <alias>]
          [--kanon-file <path>]
          [--force]
          [--dry-run]
          [--marketplace-install | --no-marketplace-install]
```

### add -- How it works

`kanon add` locates the named catalog entries in the resolved
manifest repo, derives a local alias for each, and appends an
alias-keyed `KANON_SOURCE_<alias>_{URL,REF,PATH,NAME}` block to the
target `.kanon` file. It then resolves the entry's manifest (its
`<include>` chain plus embedded remotes) and appends one optional
`KANON_SOURCE_<alias>_<VAR>` env-var line per `${VAR}` placeholder the
entry's `<project>` depends on -- the `GITBASE` var auto-derived from
the source URL, every other var name written empty -- and no env-var
line at all when the manifest references no `${VAR}`. A
`KANON_SOURCE_<alias>_MARKETPLACE=true` line is added for marketplace-type
entries. If the file does not yet exist, it is created; no global header
is written -- each per-dependency block carries its own optional env-var
lines, and there is no global `[catalog]` block or
`KANON_MARKETPLACE_INSTALL` header (both removed in 3.0.0).

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

| Entry name | Derived alias |
| ---------- | ------------- |
| `package-a` | `package_a` |
| `Package-A` | `package_a` |
| `MyTool` | `mytool` |
| `my-cool-lib` | `my_cool_lib` |

Worked example: `Package-A` normalizes to `package_a`.

The normalized alias appears in the `KANON_SOURCE_<alias>_*` block
keys. `kanon add` writes the normalized form verbatim, unless
`--as <alias>` overrides it or a cross-source collision triggers a
deterministic auto-suffix.

### add -- File creation

When the target `.kanon` file does not exist, `kanon add` creates
it and writes the alias-keyed source block(s) directly. **No global
header is written** in 3.0.0: there is no `[catalog]` block, no
global `GITBASE=` line, and no `KANON_MARKETPLACE_INSTALL=` line.
Any per-org base is recorded per dependency in
`KANON_SOURCE_<alias>_GITBASE`, derived automatically from the
catalog-source URL -- but only when the entry's manifest actually
references `${GITBASE}` (see the env-var block below).

### add -- Written block

For each added entry, `kanon add` appends an alias-keyed structural block:

```bash
KANON_SOURCE_<alias>_URL=<manifest_repo_url>
KANON_SOURCE_<alias>_REF=<resolved_spec>
KANON_SOURCE_<alias>_PATH=<path_to_marketplace_xml>
KANON_SOURCE_<alias>_NAME=<manifest_name>
```

It then appends one optional env-var line per `${VAR}` placeholder the
entry's manifest references (resolved through the entry's `<include>`
chain and the `<remote>` its `<project>` depends on). The var named
exactly `GITBASE` is auto-derived from the catalog-source URL; every
other var name is written empty for you to fill in:

```bash
KANON_SOURCE_<alias>_GITBASE=<derived_org_base>   # only if the manifest uses ${GITBASE}
KANON_SOURCE_<alias>_<OTHER_VAR>=                 # only if the manifest uses ${OTHER_VAR}
```

An entry whose manifest references no `${VAR}` gets no env-var line. For
a marketplace-type entry (or when `--marketplace-install` is passed), a
trailing `_MARKETPLACE` line is appended:

```bash
KANON_SOURCE_<alias>_MARKETPLACE=true
```

Output confirms the structural keys written (full key names, in canonical
suffix order):

```text
Wrote KANON_SOURCE_package_a_URL, KANON_SOURCE_package_a_REF, KANON_SOURCE_package_a_PATH, KANON_SOURCE_package_a_NAME to ./.kanon
```

A `--force` overwrite of an existing alias prints `Overwrote ... in ./.kanon`.

### add -- Lockfile interaction

`kanon add` only edits `.kanon`; it does not resolve or write the
lockfile. The next plain `kanon install` reconciles the new source into
the lockfile (resolving it fresh while preserving the locked SHAs of
unchanged sources), so the `kanon add` then `kanon install` loop "just
works" without any flag -- including when an `add` and a `remove` happen
between two installs. See
[docs/lockfile.md -- Install reconcile model](lockfile.md#install-reconcile-model).

### add -- Flags

| Flag | Default | Description |
| ---- | ------- | ----------- |
| `--catalog-source url[@ref]` | env | Catalog source; `@ref` optional. Env: KANON_CATALOG_SOURCES. |
| `--catalog-default-branch name` | env | Branch used when the catalog source omits `@ref`. Env: KANON_CATALOG_DEFAULT_BRANCH (default `main`; `auto` = remote HEAD). |
| `--as alias` | auto | Override the auto-computed local alias (single entry only). Charset `[A-Za-z0-9_]`, no `__` run. |
| `--kanon-file path` | `./.kanon` | Target file. Env: KANON_KANON_FILE. |
| `--force` | off | Re-add an existing alias (same source@ref): overwrite the block and re-pin its lock entry. Without it, a re-add is a hard error. |
| `--dry-run` | off | Print diff without modifying any file. Exit 0. |
| `--marketplace-install` | auto | Force `KANON_SOURCE_<alias>_MARKETPLACE=true` (errors if the entry is not a `claude-marketplace` type). Excl. `--no-marketplace-install`. |
| `--no-marketplace-install` | auto | Force the `_MARKETPLACE` line to be omitted. Excl. `--marketplace-install`. |

### add -- `--dry-run` semantics

With `--dry-run`, `kanon add` prints the diff that would be
written to the target file and exits 0 without modifying any
file:

```text
--- ./.kanon (existing)
+++ ./.kanon (proposed)
@@ ...
+KANON_SOURCE_package_a_URL=https://example.com/org/manifest-repo.git
+KANON_SOURCE_package_a_REF===1.4.2
+KANON_SOURCE_package_a_PATH=repo-specs/package-a/package-a-marketplace.xml
+KANON_SOURCE_package_a_NAME=package-a
+KANON_SOURCE_package_a_GITBASE=https://example.com/org
```

The trailing `_GITBASE` line appears only because this entry's manifest
references `${GITBASE}`; an entry with fully-literal remotes shows only the
four structural lines.

When a `--force` overwrite replaces an existing block, the diff also
shows the removed lines with a `-` prefix.

### add -- Collision behaviour

Alias collisions are classified into three cases:

#### add -- Within-request collision (hard error)

When two entries in the same `kanon add` invocation normalize to the
same alias, the command exits with a hard error before touching the
file. See "add error 4 -- Within-request alias collision" below.

#### add -- Cross-source collision (auto-suffixed, never an error)

When the requested entry's manifest name sanitizes to an alias already
mapped to a **different** source, the alias is auto-suffixed
deterministically and the add succeeds -- with or without `--force`. Use
`--as <alias>` to choose an explicit alias instead.

#### add -- Same-alias re-add (hard error without `--force`)

When the target `.kanon` already maps the alias to the **same**
source@ref, `kanon add` treats it as a re-add and exits with a hard
error (showing a diff and a remediation hint) unless `--force` is passed.
See "add error 5 -- Re-adding an existing alias without `--force`" below.
With `--force`, the existing block is overwritten and its lock entry is
re-pinned.

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
  --catalog-source <git-url>@<ref>       # e.g. --catalog-source https://example.com/org/manifest-repo.git@main
  KANON_CATALOG_SOURCES=<git-url>@<ref>  # set as env var (one entry per line), then re-run

The CLI flag takes precedence when both are set.
A catalog source identifies a manifest repo (a git repository whose
repo-specs/ directory exposes installable kanon dependencies).
See docs/catalogs-explained.md for what a manifest repo is and how to find one.
See docs/configuration.md for the full configuration reference.
```

#### add error 3 -- Zero PEP 440 tags and no `@<spec>`

Reproducer (manifest repo has no PEP 440-valid tags):

```bash
kanon add package-a \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Expected message (the example tag is always `foo@main`, regardless of the
requested entry name):

```text
ERROR: manifest repo has no PEP 440-valid tags; pin to a branch or SHA explicitly (e.g., 'kanon add foo@main') or ask the catalog author to publish a release tag.
```

#### add error 4 -- Within-request alias collision

When two entries in the same invocation normalize to the same alias:

```bash
kanon add package-a Package-A \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Expected message:

```text
ERROR: within-request collision: 'package-a' and 'Package-A' both normalise to source name 'package_a'.
Remove duplicate entries from your command arguments.
```

> A *cross-source* collision (two different sources whose manifest names
> sanitize to the same alias) is NOT an error -- it is auto-suffixed
> deterministically, with or without `--force`. Only a within-request
> duplicate and a same-alias re-add (below) are errors.

#### add error 5 -- Re-adding an existing alias without `--force`

Reproducer (when alias `package_a` already maps to the same source@ref):

```bash
kanon add 'package-a@==1.5.0' \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Expected message (the diff lines show the existing block followed by a
remediation hint):

```text
ERROR: source alias 'package_a' is already mapped to https://example.com/org/manifest-repo.git/repo-specs/package-a/package-a-marketplace.xml (ref ==1.4.2); this is a re-add of an existing package.
-KANON_SOURCE_package_a_URL=https://example.com/org/manifest-repo.git
-KANON_SOURCE_package_a_REF===1.4.2
-KANON_SOURCE_package_a_PATH=repo-specs/package-a/package-a-marketplace.xml
+KANON_SOURCE_package_a_URL=https://example.com/org/manifest-repo.git
+KANON_SOURCE_package_a_REF===1.5.0
+KANON_SOURCE_package_a_PATH=repo-specs/package-a/package-a-marketplace.xml
Use --force to overwrite and re-pin its lock entry, or 'kanon remove package_a' first.
```

With `--force`, the existing block is overwritten and its lock entry is
re-pinned (the dependency's `_NAME` is preserved).

#### add error 6 -- Entry with manifest integrity issues

Reproducer (the entry's manifest XML has integrity issues):

```bash
kanon add broken-entry \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main
```

Expected message (one preceding `ERROR:` line per offending XML path,
followed by the summary):

```text
ERROR: manifest repo `https://example.com/org/manifest-repo.git@main` has integrity issues in the following XML paths: repo-specs/broken-entry/broken-entry-marketplace.xml
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

### remove -- Alias or entry name

`kanon remove` accepts **either** the alias (the `<alias>` token in
`KANON_SOURCE_<alias>_*` keys) or the original entry name. Both forms
are normalized via the same derivation rule (lowercase + replace `-`
with `_`).

Worked example:

```bash
# Both remove the same alias block:
kanon remove package-a   # entry name
kanon remove package_a   # alias (normalized form)
```

### remove -- Behaviour

1. Read the `.kanon` file. Fail-fast if the file is missing.
2. For each `<name>`, normalize to the alias and locate every line of
   that alias' block: the structural keys
   `KANON_SOURCE_<normalized>_{URL,REF,PATH,NAME}=...`, plus any optional
   per-dependency env-var line (e.g. `_GITBASE`) and the optional
   `_MARKETPLACE` flag. These lines may be non-contiguous in hand-written
   `.kanon` files. They are removed wherever they appear, preserving the
   order of remaining content.
3. **Atomicity:** all requested aliases are validated first. Presence is
   judged by the required STRUCTURAL keys only. If ANY requested alias is
   missing a required structural key (fewer than 4 present), the command
   exits non-zero and the file is NOT modified -- either every requested
   removal succeeds or nothing changes. The error is:
   `source 'X' (normalized form 'Y') not fully present in
   .kanon; found <n> of 4 expected KANON_SOURCE_<Y>_* keys`.
4. Comments adjacent to removed keys are not removed
   automatically; all other content is preserved byte-for-byte
   except for the removed block lines.

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

### remove -- Non-contiguous block handling

The alias' block lines -- `KANON_SOURCE_<alias>_{URL,REF,PATH,NAME}` plus
any optional env-var (e.g. `_GITBASE`) and `_MARKETPLACE` line -- are
removed wherever they appear in the file, even if they are not adjacent.
All other content (including interleaved comments and other keys) is
preserved in its original order.

### remove -- Flags

| Flag | Default | Description |
| ---- | ------- | ----------- |
| `--kanon-file path` | `./.kanon` | Target file. Env: KANON_KANON_FILE. |
| `--force` | off | Silently skip aliases not fully present (clean up partially-orphaned entries). Known aliases are still removed atomically. |
| `--dry-run` | off | Print the lines that would be removed (each with a `-` prefix); makes no on-disk change. Exit 0. |

### remove -- `--dry-run` semantics

With `--dry-run`, `kanon remove` prints what would be removed
and exits 0 without modifying any file:

```text
-KANON_SOURCE_package_a_URL=https://example.com/org/manifest-repo.git
-KANON_SOURCE_package_a_REF===1.4.2
-KANON_SOURCE_package_a_PATH=repo-specs/package-a/package-a-marketplace.xml
-KANON_SOURCE_package_a_NAME=package-a
-KANON_SOURCE_package_a_GITBASE=https://example.com/org
```

The `_GITBASE` line is shown here because this block declared it; a block
with no optional env-var line removes only its four structural lines.

### remove -- Lockfile interaction

If `.kanon.lock` exists and references the removed source, the
next `kanon install` detects the orphan and reconciles by
default: it prunes the orphan, replays the surviving sources,
and rewrites the lockfile (the `npm install` model). With
`--strict-lock` on `kanon install`, the orphan is a hard error
and the lockfile is not mutated (the `npm ci` model). See
[docs/lockfile.md -- Install reconcile model](lockfile.md#install-reconcile-model).

If the removed source had registered a marketplace (recorded in its
per-source `registered_marketplaces` ledger), the next `kanon install`
also auto-unregisters that marketplace from `~/.claude` as part of the
reconcile -- unless another still-referenced source provides the same
marketplace, in which case it is retained. To prune the orphaned
marketplace explicitly without a reinstall, run `kanon clean --orphans`.
See
[docs/lockfile.md -- Marketplace ownership and pruning](lockfile.md#marketplace-ownership-and-pruning).

### remove -- Error scenarios

#### remove error 1 -- Unknown alias without `--force`

Reproducer:

```bash
kanon remove nonexistent-entry
```

Expected message:

```text
ERROR: source alias 'nonexistent-entry' (normalized form 'nonexistent_entry') not fully present in .kanon; found 0 of 5 expected KANON_SOURCE_nonexistent_entry_* keys
```

Pass `--force` to silently skip aliases that are not fully present.

#### remove error 2 -- Missing `.kanon` file

Reproducer:

```bash
kanon remove package-a
```

Expected message (when no `.kanon` exists):

```text
ERROR: no .kanon file at .kanon; nothing to remove
```

---

## Environment variables

The following environment variables affect `kanon search`,
`kanon add`, and `kanon remove`. For the full configuration
reference see [docs/configuration.md](configuration.md).

**`KANON_CATALOG_SOURCES`** -- `search`, `add`

Catalog source as `<git-url>@<ref>`. CLI flag
`--catalog-source` takes precedence when both are set.

**`KANON_LIST_FORMAT`** -- `search`

Default output format (`names` or `json`). Overridden by
`--format`.

**`KANON_LIST_LIMIT`** -- `search`

Default `-A`/`--all` cap. Default value: `50`. Overridden
by `--limit` or `--no-limit`.

**`KANON_TREE_NO_FILTER_THRESHOLD`** -- `search`

Entry count above which `--tree` requires a filter. Default:
`20`.

**`KANON_KANON_FILE`** -- `add`, `remove`

Default target file path. Default: `./.kanon`. Overridden by
`--kanon-file`.

**`NO_COLOR`** -- all commands

When set to any non-empty value, disables color output.

**`KANON_GIT_RETRY_COUNT`** -- `search`, `add`

Number of `git ls-remote` retries on transient errors.
Default: `3`.

**`KANON_GIT_RETRY_DELAY`** -- `search`, `add`

Seconds between `git ls-remote` retries. Default: `1`.
