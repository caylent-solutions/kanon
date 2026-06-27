# URL Canonicalization

kanon normalizes git repository URLs to a single canonical form so that two
spellings of the same repository (HTTPS, SSH, SCP shorthand, with or without
`.git`, with or without a trailing slash) are always treated as identical.

Reference: spec `kanon-list-add-lock-features-spec.md` Section 4.0 "Repo URL
canonicalization".

## API

```python
from kanon_cli.core.url import canonicalize_repo_url

canonical: str = canonicalize_repo_url(url)
```

`canonicalize_repo_url` is a pure function. It performs no I/O, writes no
logs, and has no module-level state.

## Transformation Rules

The following rules are applied in order to every input URL:

| # | Rule | Example input | Example output |
|---|------|---------------|----------------|
| 1 | Empty or whitespace-only input raises `ValueError`. | `""` | raises |
| 2 | Query strings raise `ValueError`. | `https://h/r?ref=v1` | raises |
| 3 | Fragments raise `ValueError`. | `https://h/r#L42` | raises |
| 4 | User-info (`user@`) is stripped from the authority. | `https://user@h/r` | `https://h/r` |
| 5 | Host is lowercased; path case is preserved verbatim. | `https://GitHub.com/Org/Repo` | `https://github.com/Org/Repo` |
| 6 | Exactly one trailing `/` is stripped from the path. | `https://h/r/` | `https://h/r` |
| 7 | Exactly one trailing `.git` suffix is stripped after the slash strip. | `https://h/r.git/` | `https://h/r` |
| 8 | The output scheme is always `https://`. | `git@h:r` | `https://h/r` |
| 9 | Port is preserved when present. | `https://h:8443/r` | `https://h:8443/r` |

## Accepted Input Shapes

- `https://[user@]host[:port]/path` -- standard HTTPS
- `ssh://[user@]host[:port]/path` -- explicit SSH
- `[user@]host:path` -- SCP shorthand (no scheme prefix; `:` is the path
  separator)

## Worked Equivalence-Set Example

All six of the following spellings refer to the same repository and produce
the same canonical string:

| Input URL | Canonical form |
|-----------|----------------|
| `https://github.com/caylent-solutions/kanon` | `https://github.com/caylent-solutions/kanon` |
| `https://github.com/caylent-solutions/kanon.git` | `https://github.com/caylent-solutions/kanon` |
| `https://github.com/caylent-solutions/kanon.git/` | `https://github.com/caylent-solutions/kanon` |
| `git@github.com:caylent-solutions/kanon.git` | `https://github.com/caylent-solutions/kanon` |
| `ssh://git@github.com/caylent-solutions/kanon.git` | `https://github.com/caylent-solutions/kanon` |
| `https://user@github.com/caylent-solutions/kanon.git` | `https://github.com/caylent-solutions/kanon` |

Python assertion:

```python
from kanon_cli.core.url import canonicalize_repo_url

urls = [
    "https://github.com/caylent-solutions/kanon",
    "https://github.com/caylent-solutions/kanon.git",
    "https://github.com/caylent-solutions/kanon.git/",
    "git@github.com:caylent-solutions/kanon.git",
    "ssh://git@github.com/caylent-solutions/kanon.git",
    "https://user@github.com/caylent-solutions/kanon.git",
]

canonical_forms = {canonicalize_repo_url(u) for u in urls}
assert len(canonical_forms) == 1
assert "https://github.com/caylent-solutions/kanon" in canonical_forms
```

## Error Messages

Error messages follow the spec Section 4 shape:

```text
ERROR: <one-line summary>
  Input: '<offending input>'
  <remediation>
```

## Consumers

The following kanon features use `canonicalize_repo_url` for URL matching:

- **Lockfile `canonical_url` field** (spec Section 5) -- every entry in the
  lockfile stores the canonical form of the dependency URL.
- **`kanon why` URL matching** (spec Section 4.5) -- the query URL is
  canonicalized before comparison against lockfile entries.
- **`kanon outdated` URL matching** -- canonical URLs are used to correlate
  lockfile entries with upstream versions.
