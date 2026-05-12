# Version Resolution

The `kanon` CLI resolves PEP 440 version specifiers against git tags using `git ls-remote`. This
applies to `KANON_SOURCE_<name>_REVISION` values in `.kanon` and to `--catalog-source` revision
arguments.

---

## Implementation

Version constraint logic is consolidated in `kanon_cli.version`, which is the canonical
implementation. All constraint detection and resolution routes through the two public functions
in that module:

- `kanon_cli.version.is_version_constraint(rev_spec)` -- returns `True` when the last path
  component of `rev_spec` contains a PEP 440 constraint operator
- `kanon_cli.version.resolve_version(url, rev_spec)` -- fetches tags via `git ls-remote` and
  returns the highest tag satisfying the constraint

The `kanon_cli.repo.version_constraints` module at `kanon_cli/repo/version_constraints.py`
delegates to `kanon_cli.version` rather than maintaining its own independent implementation.
Specifically:

- `repo/version_constraints.is_version_constraint` delegates to
  `kanon_cli.version.is_version_constraint`
- `repo/version_constraints.resolve_version_constraint` delegates to
  `kanon_cli.version._resolve_constraint_from_tags`, converting `ValueError` to
  `ManifestInvalidRevisionError` as required by the repo module's error contract

This delegation ensures there is a single consolidated implementation of PEP 440 constraint
logic throughout `kanon-cli`.

---

## How It Works

1. If `rev_spec` contains no PEP 440 operators, it is returned as-is (branch/tag passthrough)
2. If `rev_spec` contains a PEP 440 constraint:
   - Splits on the last `/` to separate the tag-path prefix from the constraint
   - Runs `git ls-remote --tags <url>` to list all available tags
   - Filters tags by prefix (when a prefix is present)
   - Parses version suffixes with `packaging.version.Version`
   - Evaluates with `packaging.specifiers.SpecifierSet`
   - Returns the full ref path of the highest matching tag (e.g. `refs/tags/1.1.2`)
3. Fails fast if no match is found

---

## Prefixed vs Bare Constraints

Constraints can be written with or without a `refs/tags/` prefix. The prefix controls which tags are considered and ensures the returned value is a full ref path usable directly with `repo init -b`.

### Prefixed (recommended)

```properties
KANON_SOURCE_build_REVISION=refs/tags/~=1.1.0
```

Resolves against all tags under `refs/tags/`. Returns the full ref, e.g. `refs/tags/1.1.2`.

### Namespaced prefix

```properties
KANON_SOURCE_build_REVISION=refs/tags/dev/python/my-lib/~=1.2.0
```

Filters to tags under `refs/tags/dev/python/my-lib/` only. Returns e.g. `refs/tags/dev/python/my-lib/1.2.7`.

### Bare (no prefix)

```properties
KANON_SOURCE_build_REVISION=~=1.1.0
```

Resolves against all available tags. Returns the full ref, e.g. `refs/tags/1.1.2`.

---

## Supported Operators

| Operator | Syntax | Meaning | Example Match |
|---|---|---|---|
| Compatible release | `~=1.2.0` | `>=1.2.0, <1.3.0` | `1.2.7` |
| Range | `>=1.0.0,<2.0.0` | Any version in range | `1.5.2` |
| Exact | `==1.2.3` | Only 1.2.3 | `1.2.3` |
| Minimum | `>=1.0.0` | 1.0.0 or higher | `3.0.0` |
| Less than | `<2.0.0` | Below 2.0.0 | `1.9.9` |
| Less than or equal | `<=2.0.0` | 2.0.0 or below | `2.0.0` |
| Exclusion | `!=1.0.1` | Any except 1.0.1 | `1.0.0`, `1.0.2` |
| Wildcard | `*` | Latest available | highest tag |

All constraints follow [PEP 440](https://peps.python.org/pep-0440/) via the `packaging` library.

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
|---|---|---|
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

Resolves the manifest repository revision before `repo init -b`. The resolved value must be a ref usable by `repo init`, so using the `refs/tags/` prefix is recommended:

```properties
KANON_SOURCE_build_REVISION=refs/tags/~=1.1.0
KANON_SOURCE_marketplaces_REVISION=refs/tags/>=1.0.0,<2.0.0
```

### KANON_CATALOG_SOURCE / --catalog-source

Resolves the catalog repository version before `git clone --branch`. Supports the same constraint syntax as other revision fields:

```bash
# Pin to current major, allow minor/patch updates
export KANON_CATALOG_SOURCE='https://github.com/org/repo.git@>=2.0.0,<3.0.0'

# Compatible release (>=2.0.0, <2.1.0)
kanon bootstrap <entry> --catalog-source 'https://github.com/org/repo.git@~=2.0.0'

# Exact version
kanon bootstrap <entry> --catalog-source 'https://github.com/org/repo.git@==2.2.0'
```

The `latest` keyword is shorthand for `*` (wildcard), resolving to the highest semver tag.

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
  ```
  No tags found under prefix '<prefix>' for the given revision
  ```
- No parseable version tags -- two variants apply (see below):
  - **Zero candidates under prefix** (prefix has no tags at all): narrow message preserved as-is.
  - **Non-PEP-440 candidates** (tags exist under prefix but none parse as PEP 440): loud error (see below).
- No tags matching the specifier -- fail with available versions listed
- Invalid constraint syntax -- fail with error
- `git ls-remote` failure -- fail with stderr

---

## Loud Error: Non-PEP-440 Tags Under Prefix

When candidate tags exist under the requested prefix but none of their last path
components parse as a valid PEP 440 version (spec Section 0.4, Section 13 decision 14),
the resolver raises a `ValueError` with the following multi-line format:

```
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

- The `... (showing first 10 of <N>)` suffix is only present when more than 10 tags are skipped.
- The bullet list is sorted deterministically (lexicographic) regardless of input order.
- The remediation pointer always names `kanon catalog audit --check tag-format`.

**When this fires:** the prefix matched at least one tag, but every matched tag has a
last path component that `packaging.version.Version` rejects (e.g., `release-1.0.0`,
`release-2024`, `nightly-build`).

**When the narrow message fires instead:** the prefix matched zero tags -- there are
simply no tags under that namespace at all. In this case the original narrow message
is preserved: `No tags found under prefix '<prefix>' for the given revision`.

The formatting logic is encapsulated in the private helper
`_format_zero_pep440_tags_error(prefix, skipped)` in `kanon_cli.version`, which
accepts the display prefix string and the full list of skipped tag refs.
