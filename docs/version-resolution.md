# Version Resolution

The `kanon` CLI resolves PEP 440 version specifiers against git tags using
`git ls-remote`. This applies to `KANON_SOURCE_<name>_REVISION` values in
`.kanon` and to `--catalog-source` revision arguments.

---

## Implementation

Version constraint logic is consolidated in `kanon_cli.version`, which is
the canonical implementation. All constraint detection and resolution routes
through the two public functions in that module:

- `kanon_cli.version.is_version_constraint(rev_spec)` -- returns `True`
  when the last path component of `rev_spec` contains a PEP 440 constraint
  operator
- `kanon_cli.version.resolve_version(url, rev_spec)` -- fetches tags via
  `git ls-remote` and returns the highest tag satisfying the constraint

The `kanon_cli.repo.version_constraints` module at
`kanon_cli/repo/version_constraints.py` delegates to `kanon_cli.version`
rather than maintaining its own independent implementation. Specifically:

- `repo/version_constraints.is_version_constraint` delegates to
  `kanon_cli.version.is_version_constraint`
- `repo/version_constraints.resolve_version_constraint` delegates to
  `kanon_cli.version._resolve_constraint_from_tags`, converting `ValueError`
  to `ManifestInvalidRevisionError` as required by the repo module's error
  contract

This delegation ensures there is a single consolidated implementation of
PEP 440 constraint logic throughout `kanon-cli`.

---

## How It Works

1. If `rev_spec` contains no PEP 440 operators, it is returned as-is
   (branch/tag passthrough)
2. If `rev_spec` contains a PEP 440 constraint:
   - Splits on the last `/` to separate the tag-path prefix from the
     constraint
   - Runs `git ls-remote --tags <url>` to list all available tags
   - Filters tags by prefix (when a prefix is present)
   - Parses version suffixes with `packaging.version.Version`
   - Evaluates with `packaging.specifiers.SpecifierSet`
   - Returns the full ref path of the highest matching tag
     (e.g. `refs/tags/1.1.2`)
3. Fails fast if no match is found

---

## Prefixed vs Bare Constraints

Constraints can be written with or without a `refs/tags/` prefix. The prefix
controls which tags are considered and ensures the returned value is a full
ref path usable directly with `repo init -b`.

### Prefixed (recommended)

```properties
KANON_SOURCE_build_REVISION=refs/tags/~=1.1.0
```

Resolves against all tags under `refs/tags/`. Returns the full ref,
e.g. `refs/tags/1.1.2`.

### Namespaced prefix

```properties
KANON_SOURCE_build_REVISION=refs/tags/dev/python/my-lib/~=1.2.0
```

Filters to tags under `refs/tags/dev/python/my-lib/` only. Returns
e.g. `refs/tags/dev/python/my-lib/1.2.7`.

### Bare (no prefix)

```properties
KANON_SOURCE_build_REVISION=~=1.1.0
```

Resolves against all available tags. Returns the full ref,
e.g. `refs/tags/1.1.2`.

---

## Supported Operators

| Operator | Syntax | Meaning | Example Match |
| --- | --- | --- | --- |
| Compatible release | `~=1.2.0` | `>=1.2.0, <1.3.0` | `1.2.7` |
| Range | `>=1.0.0,<2.0.0` | Any version in range | `1.5.2` |
| Exact | `==1.2.3` | Only 1.2.3 | `1.2.3` |
| Minimum | `>=1.0.0` | 1.0.0 or higher | `3.0.0` |
| Less than | `<2.0.0` | Below 2.0.0 | `1.9.9` |
| Less than or equal | `<=2.0.0` | 2.0.0 or below | `2.0.0` |
| Exclusion | `!=1.0.1` | Any except 1.0.1 | `1.0.0`, `1.0.2` |
| Wildcard | `*` | Latest available | highest tag |

All constraints follow [PEP 440](https://peps.python.org/pep-0440/) via the
`packaging` library.

---

## Branch/Tag Passthrough

Plain strings without PEP 440 operators are returned unchanged, with one
exception: **bare PEP 440 version values** (any string accepted by
`packaging.version.Version` that contains no `/`) are normalized to
`refs/tags/<value>` so that `repo init -b <value>` resolves the version
as a tag rather than a branch.

This widens the previous narrow acceptance set (digits and dots only) to
cover all PEP 440 version shapes per spec Section 4.0 rule 3:

| Input | Returns | Notes |
| --- | --- | --- |
| `main` | `main` | not a PEP 440 version |
| `refs/tags/1.1.2` | `refs/tags/1.1.2` | already prefixed (contains `/`) |
| `feat/my-feature` | `feat/my-feature` | contains `/` |
| `subpackage/1.0.0` | `subpackage/1.0.0` | contains `/` |
| `1.0.0` | `refs/tags/1.0.0` | plain semver |
| `2.5` | `refs/tags/2.5` | two-part semver |
| `1` | `refs/tags/1` | single-digit PEP 440 version |
| `v1.0.0` | `refs/tags/v1.0.0` | v-prefixed PEP 440 version |
| `1.0.0a1` | `refs/tags/1.0.0a1` | PEP 440 prerelease |
| `1.0.0b3` | `refs/tags/1.0.0b3` | PEP 440 beta prerelease |
| `1.0.0rc2` | `refs/tags/1.0.0rc2` | PEP 440 release candidate |
| `1.0.0+local.build` | `refs/tags/1.0.0+local.build` | PEP 440 local version |
| `2026.4.1` | `refs/tags/2026.4.1` | calendar version |
| `1!2.0.0` | `refs/tags/1!2.0.0` | PEP 440 epoch |
| `1.0.0.post1` | `refs/tags/1.0.0.post1` | PEP 440 post-release |
| `1.0.0.dev0` | `refs/tags/1.0.0.dev0` | PEP 440 dev-release |

**Pass-through rule:** any input that (a) contains `/` OR (b) fails
`packaging.version.Version` parsing is returned unchanged. Branch names
such as `main`, `develop`, and hex SHAs all fail PEP 440 parsing and
pass through unmodified.

---

## Where Resolution Applies

### KANON_SOURCE_\<name\>_REVISION

Resolves the manifest repository revision before `repo init -b`. The
resolved value must be a ref usable by `repo init`, so using the
`refs/tags/` prefix is recommended:

```properties
KANON_SOURCE_build_REVISION=refs/tags/~=1.1.0
KANON_SOURCE_marketplaces_REVISION=refs/tags/>=1.0.0,<2.0.0
```

### KANON_CATALOG_SOURCE / --catalog-source

Resolves the catalog repository version before `git clone --branch`.
Supports the same constraint syntax as other revision fields:

```bash
# Pin to current major, allow minor/patch updates
export KANON_CATALOG_SOURCE='https://github.com/org/repo.git@>=2.0.0,<3.0.0'

# Compatible release (>=2.0.0, <2.1.0)
kanon bootstrap <entry> --catalog-source \
  'https://github.com/org/repo.git@~=2.0.0'

# Exact version
kanon bootstrap <entry> --catalog-source \
  'https://github.com/org/repo.git@==2.2.0'
```

The `latest` keyword is shorthand for `*` (wildcard), resolving to the
highest semver tag.

Plain branch names and exact tags pass through without resolution:

```bash
# These do not trigger constraint resolution
export KANON_CATALOG_SOURCE='https://github.com/org/repo.git@main'
export KANON_CATALOG_SOURCE='https://github.com/org/repo.git@2.2.0'
```

---

## Error Cases

- No tags found for the URL -- fail with error
- No tags under the specified prefix -- fail with a narrow error:

  ```text
  No tags found under prefix '<prefix>' for the given revision
  ```

- No parseable version tags -- two variants apply (see below):
  - **Zero candidates under prefix** (prefix has no tags at all): narrow
    message preserved as-is.
  - **Non-PEP-440 candidates** (tags exist under prefix but none parse as
    PEP 440): loud error (see below).
- No tags matching the specifier -- fail with available versions listed
- Invalid constraint syntax -- fail with error
- `git ls-remote` failure -- fail with stderr

---

## Loud Error: Non-PEP-440 Tags Under Prefix

When candidate tags exist under the requested prefix but none of their last
path components parse as a valid PEP 440 version (spec Section 0.4, Section
13 decision 14), the resolver raises a `ValueError` with the following
multi-line format:

```text
ERROR: No PEP 440-parseable version tags found under '<prefix>'.
Skipped <N> tag(s) whose last path component is not a valid PEP 440 version:
  - <tag_name_1>
  - <tag_name_2>
  ... (showing first 10 of <N>)
Run 'kanon catalog audit --check tag-format' against the manifest repo
to identify every non-PEP-440 tag, then ask the catalog author to rename
them to PEP 440 form (e.g., 'release-1.0.0' -> '1.0.0').
```

Key details:

- The `... (showing first 10 of <N>)` suffix is only present when more than
  10 tags are skipped.
- The bullet list is sorted deterministically (lexicographic) regardless of
  input order.
- The remediation pointer always names `kanon catalog audit --check
  tag-format`.

**When this fires:** the prefix matched at least one tag, but every matched
tag has a last path component that `packaging.version.Version` rejects
(e.g., `release-1.0.0`, `release-2024`, `nightly-build`).

**When the narrow message fires instead:** the prefix matched zero tags --
there are simply no tags under that namespace at all. In this case the
original narrow message is preserved:
`No tags found under prefix '<prefix>' for the given revision`.

The formatting logic is encapsulated in the private helper
`_format_zero_pep440_tags_error(prefix, skipped)` in `kanon_cli.version`,
which accepts the display prefix string and the full list of skipped tag
refs.

---

## Resolver Precedence

The resolver applies rules in the following priority order (first match
wins). These rules apply uniformly across `kanon add`, `kanon install`,
`kanon outdated`, and any completer that resolves a `@<spec>` token
(spec Section 4.0).

| Priority | Rule |
| --- | --- |
| 1 | **PEP 440 constraint** |
| 2 | **Full git ref** |
| 3 | **Bare PEP 440 version** |
| 4 | **Raw git SHA** |
| 5 | **Pass-through to git** |

Rule conditions and actions:

- **Rule 1 (PEP 440 constraint)** -- Fires when the last `/`-delimited path
  component starts with a PEP 440 operator (`==`, `~=`, `>=`, `<=`, `>`,
  `<`, `!=`, `===`), equals `*`, equals `latest`, or is a comma-separated
  range with operators. Action: resolves via `_resolve_constraint_from_tags`
  -- filter tags by the prefix (if any), parse each tag's last path
  component as `packaging.version.Version`, evaluate `SpecifierSet`, return
  the full ref of the highest-matching tag
  (e.g. `refs/tags/subpackage/1.0.0`).
- **Rule 2 (Full git ref)** -- Fires when `rev_spec` starts with `refs/`
  (e.g. `refs/tags/x`, `refs/heads/x`). Action: passes through to git
  unchanged.
- **Rule 3 (Bare PEP 440 version)** -- Fires when `rev_spec` is a valid
  `packaging.version.Version` literal AND contains no `/`. Action:
  normalizes to `refs/tags/<spec>`.
- **Rule 4 (Raw git SHA)** -- Fires when `rev_spec` is a 40-char or 64-char
  lowercase hex string AND contains no `/`. Action: passes through to git
  as-is.
- **Rule 5 (Pass-through to git)** -- Fires for anything else (contains `/`
  but not a constraint, or a non-PEP-440 bare value). Action: passes through
  to git unchanged; git resolves following its standard ref priority
  (`refs/heads/<spec>`, then `refs/tags/<spec>`, then other matches).

**No fallback between rules.** If a rule fires and the underlying git
operation fails (tag not found, branch not found, SHA not reachable), kanon
errors immediately. It does NOT silently try the next rule.

**No `--ref-kind` flag.** To disambiguate -- e.g., a branch named with
PEP 440-looking digits like `1.0.0` vs a same-named tag -- use the explicit
`refs/heads/<name>` or `refs/tags/<name>` form (rule 2).

For the full resolution-kind edge-case table see
[Branch/Tag Passthrough](#branchtag-passthrough).

---

## `@` Parsing Rule

Catalog-source strings and `kanon add` arguments use the form
`<name>[@<spec>]` where `<spec>` is resolved using the
[Resolver Precedence](#resolver-precedence) rules above.

**Split rule:** split on the **last** `@` character.

This handles SSH URLs that contain `@` in their user-info prefix:

```text
git@host:org/repo.git@main
```

Splits into:

- URL: `git@host:org/repo.git`
- Ref: `main`

The split is implemented in `_parse_catalog_source` (see
[docs/list-and-add.md](list-and-add.md) for the `--catalog-source`
reference and shell-quoting examples for PEP 440 range specs).

A catalog-source string with no `@` is a hard error:

```text
ERROR: missing ref; use '<url>@<ref>' form
```

---

## Monorepo Prefix Support

PEP 440 constraint specs may include an arbitrary path prefix before the
constraint operator. The prefix is used to filter tags to the matching
namespace before resolving the constraint.

Examples:

| Rev spec | Prefix | Constraint |
| --- | --- | --- |
| `subpackage/==1.0.0` | `subpackage` | `==1.0.0` |
| `dev/python/lib/~=1.2` | `dev/python/lib` | `~=1.2` |
| `~=1.2.0` | (none) | `~=1.2.0` |

The resolved ref follows the pattern `refs/tags/<prefix>/<highest-match>`;
for bare constraints (no prefix) the pattern is `refs/tags/<highest-match>`.
For example, `subpackage/==1.0.0` resolves to `refs/tags/subpackage/1.0.0`,
and `dev/python/lib/~=1.2` resolves to
`refs/tags/dev/python/lib/<highest-1.2.x>` (e.g. `refs/tags/dev/python/lib/1.2.7`).

Resolution via `_resolve_constraint_from_tags`:

1. Splits the spec on the last `/`; the part after the last `/` is tested
   for a PEP 440 operator. If found, the part before the last `/` is the
   prefix.
2. Filters `git ls-remote --tags` output to refs whose path starts with
   `refs/tags/<prefix>/`.
3. Parses the last path component of each remaining ref as
   `packaging.version.Version`.
4. Evaluates `SpecifierSet` against the parsed versions; returns the full
   ref of the highest-matching tag.

**Edge cases:**

- If the prefix matches at least one tag but none of those tags have
  PEP 440-parseable last path components, the resolver raises the loud
  non-PEP-440 error (see
  [Loud Error: Non-PEP-440 Tags Under Prefix](#loud-error-non-pep-440-tags-under-prefix)).
- If the prefix matches zero tags, the narrow error fires:
  `No tags found under prefix '<prefix>' for the given revision`.
- A bare constraint with no prefix (e.g. `~=1.2.0`) filters across all
  available tags.

For the `refs/tags/`-prefixed form (`refs/tags/dev/python/my-lib/~=1.2.0`)
see [Prefixed vs Bare Constraints](#prefixed-vs-bare-constraints).

---

## Bare PEP 440 Widening

Rule 3 of the [Resolver Precedence](#resolver-precedence) table normalizes
any input that `packaging.version.Version` accepts (AND which contains no
`/`) to `refs/tags/<spec>`.

This widens the previous narrow acceptance set (digits and dots, matching
`^\d+(?:\.\d+){1,2}$` only) to the full PEP 440 grammar. All six additional
shapes are now accepted:

| Shape | Example input | Resolved to |
| --- | --- | --- |
| Prerelease (`a`/`b`/`rc` suffix) | `1.0.0a1` | `refs/tags/1.0.0a1` |
| Local version (`+` segment) | `1.0+local` | `refs/tags/1.0+local` |
| Calendar version | `2026.4.1` | `refs/tags/2026.4.1` |
| Epoch (`<epoch>!<release>`) | `1!2.0.0` | `refs/tags/1!2.0.0` |
| Post-release (`.postN` suffix) | `1.0.0.post1` | `refs/tags/1.0.0.post1` |
| Dev-release (`.devN` suffix) | `1.0.0.dev0` | `refs/tags/1.0.0.dev0` |

**Pass-through rule:** any input that (a) contains `/` OR (b) fails
`packaging.version.Version` parsing is returned unchanged. Strings such as
`main`, `develop`, `v1.0.0`, and hex SHAs all fail PEP 440 parsing and pass
through unmodified (rule 5 or rule 4).

See [Branch/Tag Passthrough](#branchtag-passthrough) for the full edge-case
table.

---

## Non-PEP-440 Tag Names

Tag names whose last path component is not a canonical PEP 440 version
string -- such as `v1.0.0`, `release-2024`, `nightly-build`, or
`ops-marker` -- are **unaddressable via `kanon add` / install resolution.**

Specifically:

- A bare input like `v1.0.0` fails `packaging.version.Version` parsing (the
  `v` prefix is rejected by canonical PEP 440) and passes through to git as
  rule 5 (branch name pass-through). If no branch named `v1.0.0` exists,
  git fails. The tag is not reached.
- A PEP 440 constraint like `>=1.0.0` against a repo whose only tags are
  `v1.0.0`, `v1.0.1`, `v2.0.0` finds zero parseable candidates and raises
  the loud non-PEP-440 error.

**To address a literal non-PEP-440 tag**, use the explicit full-ref form
(rule 2): `refs/tags/v1.0.0`. This bypasses PEP 440 parsing and passes the
ref directly to git.

**For catalog authors** -- to ensure your manifest repo is addressable via
constraint resolution, all tags must have PEP 440-canonical last path
components. Rename non-canonical tags (e.g. `v1.0.0` -> `1.0.0`). See
[docs/catalog-author-guide.md](catalog-author-guide.md) for the
`kanon catalog audit --check tag-format` workflow and remediation steps.

**For operators** -- if you encounter the zero-PEP-440-tags error at install
time, see [docs/troubleshooting.md](troubleshooting.md) for the
zero-PEP-440-tags scenario and workarounds (branch pin, explicit
`refs/tags/<name>` form, or escalating to the catalog author to rename
tags).

For additional context see [docs/configuration.md](configuration.md) for
`KANON_CATALOG_SOURCE` and related environment variables.

---

## Proactive Inventory: `kanon catalog audit --check tag-format`

The loud error above fires at install/resolve time -- after an operator has
already hit a resolver failure. To discover non-PEP-440 tags **before**
operators encounter failures, catalog authors should run:

```bash
kanon catalog audit --check tag-format /path/to/manifest-repo
```

This check reads every git tag from the manifest repo (via
`git ls-remote --tags`) and emits one WARN finding (code `T001`) for each
tag whose last path component is not a canonical PEP 440 version string. It
exits 0 even when warnings are present.

The recommended workflow for catalog authors:

1. **Before tagging a new release**, run
   `kanon catalog audit --check tag-format .` on the manifest repo to
   confirm all existing tags are PEP 440 canonical.
2. **When tagging**, use canonical PEP 440 form (`1.0.0`, `2.10.1`) rather
   than v-prefixed forms (`v1.0.0`) or free-form names (`release-2024`).
3. **For monorepo-style tags**, the last path component must be canonical:
   `mylib/1.0.0` (correct) vs. `mylib/v1.0.0` (produces T001 WARN).

See `docs/cli/catalog-audit.md` and `docs/catalog-author-guide.md` for
details on the `tag-format` check, finding codes, and remediation steps.
