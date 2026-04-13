# Version Resolution

The `kanon` CLI resolves PEP 440 version specifiers against git tags using `git ls-remote`. This applies to both `REPO_REV` and `KANON_SOURCE_<name>_REVISION` values in `.kanon`.

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

Plain strings without PEP 440 operators are returned unchanged:

| Input | Returns |
|---|---|
| `main` | `main` |
| `refs/tags/1.1.2` | `refs/tags/1.1.2` |
| `v1.0.0` | `v1.0.0` |
| `feat/my-feature` | `feat/my-feature` |

---

## Where Resolution Applies

### REPO_REV (git override only)

When both `REPO_URL` and `REPO_REV` are set in `.kanon`, resolves the repo tool version before `pipx install --force`. When both are omitted, the repo tool is installed from PyPI and this resolution does not apply.

```properties
REPO_REV=~=1.0.0
```

### KANON_SOURCE_\<name\>_REVISION

Resolves the manifest repository revision before `repo init -b`. The resolved value must be a ref usable by `repo init`, so using the `refs/tags/` prefix is recommended:

```properties
KANON_SOURCE_build_REVISION=refs/tags/~=1.1.0
KANON_SOURCE_marketplaces_REVISION=refs/tags/>=1.0.0,<2.0.0
```

---

## Error Cases

- No tags found for the URL → fail with error
- No tags under the specified prefix → fail with error
- No parseable version tags → fail with error
- No tags matching the specifier → fail with available versions listed
- Invalid constraint syntax → fail with error
- `git ls-remote` failure → fail with stderr
