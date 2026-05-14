# kanon catalog audit

Audit a manifest repo for catalog soft-spot violations.

## Synopsis

```
kanon [--no-color] catalog audit [<dir-or-source>] [--check <subset>]
                                  [--format {text,json}] [--strict]
```

## Description

`kanon catalog audit` inspects a manifest repo (a git repository whose
`repo-specs/` directory exposes installable kanon dependencies) for common
quality issues known as "soft-spots". The command iterates each requested
check, collects findings, and reports them on stdout.

The audit target may be a local directory or a remote git repository URL.

## Arguments

| Argument | Description |
|----------|-------------|
| `<dir-or-source>` | Path to a local manifest repo directory (must contain `repo-specs/`), or a remote `<git_url>@<ref>` catalog source. Defaults to `.` (current working directory). |

## Options

| Option | Description |
|--------|-------------|
| `--check <subset>` | Comma-separated list of checks to run, or `all` (default). Cannot mix `all` with individual check names. See [Valid checks](#valid-checks). |
| `--format {text,json}` | Output format. Default: `text`. Env: `KANON_CATALOG_AUDIT_FORMAT`. |
| `--strict` | Promotes warnings to errors when enabled; exits non-zero when any WARN-level finding is present. Currently parsed but not yet active. |
| `--no-color` | Suppress ANSI color codes in output. Inherited global flag from the top-level `kanon` parser. |

## Valid checks

The five soft-spot checks audited by `kanon catalog audit`:

| Check name | Description |
|------------|-------------|
| `metadata` | Verifies required fields (`name`, `display-name`, `description`, `version`) are present and non-empty in every catalog entry's XML metadata. |
| `source-name-derivation` | Verifies that the source name derived from the entry URL matches the declared name (soft-spot rule 2). |
| `entry-name-uniqueness` | Verifies that no two entries share the same derived source name within the catalog (soft-spot rule 3). |
| `remote-url` | Verifies that every entry's `source_url` uses a permitted scheme (HTTPS by default; see `docs/configuration.md` for `KANON_ALLOW_INSECURE_REMOTES`). |
| `tag-format` | Verifies that all tags referenced by catalog entries are PEP 440-compliant version strings (soft-spot rule 5). |

Use `--check all` (or omit `--check`) to run all five checks.
Use a comma-separated list to run a subset, e.g. `--check metadata,tag-format`.

## Output formats

### text (default)

One finding per line, prefixed with `ERROR:`, `WARN:`, or `INFO:`:

```
ERROR: [M001] /path/repo-specs/tool-marketplace.xml: required <catalog-metadata> field <description> is missing or contains only whitespace. Add a non-empty <description> element to the <catalog-metadata> block.
WARN: [M002] /path/repo-specs/tool-marketplace.xml: recommended <catalog-metadata> field <owner-email> is absent. Consider adding <owner-email> to improve catalog discoverability.
```

### json

A single JSON object `{"findings": [...]}` written to stdout:

```json
{
  "findings": [
    {
      "kind": "error",
      "code": "M001",
      "message": "/path/repo-specs/tool-marketplace.xml: required <catalog-metadata> field <description> is missing or contains only whitespace. Add a non-empty <description> element to the <catalog-metadata> block.",
      "remediation": ""
    }
  ]
}
```

An empty audit produces `{"findings": []}`.

## Cache layout

When `<dir-or-source>` is a remote `<git_url>@<ref>` source, the repository is
cloned into:

```
${KANON_CACHE_DIR}/catalog-audit/<sha256(canonicalized_url@ref)>/
```

The SHA-256 key is computed over the canonicalized URL and ref, ensuring SSH and
HTTPS variants of the same repository map to the same cache entry.

Cached clones are reused without re-cloning when their filesystem mtime is within
`KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS` seconds of the current time (default:
3600 seconds / 1 hour). Set the environment variable to override:

```bash
export KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS=7200
```

The cache root directory is created with mode `0700` (owner-only access) per
spec Section 3.6 (trust model / credential isolation).

`KANON_CACHE_DIR` must be set to use a remote audit target. If unset, `kanon
catalog audit` exits with an error when a remote source is supplied.

## Metadata check (`--check metadata`)

The `metadata` check inspects every `*-marketplace.xml` file under `repo-specs/` for
spec Section 3.5 soft-spot rule 1 compliance.

### Required fields

The following fields MUST be present and non-empty in the `<catalog-metadata>` block.
A missing or whitespace-only value produces one **ERROR** finding per field:

| Field | Description |
|-------|-------------|
| `name` | Machine-readable package identifier. |
| `display-name` | Human-readable label shown in `kanon list` output. |
| `description` | Short prose description of the package. |
| `version` | Author-claimed version string (informational; not validated against semver/PEP-440). |

### Recommended fields

The following fields SHOULD be present. A missing field produces one **WARN** finding per field:

| Field | Description |
|-------|-------------|
| `type` | Package type string (e.g. `plugin`, `library`). |
| `owner-name` | Primary owner display name. |
| `owner-email` | Primary owner contact address. |
| `keywords` | Comma-separated keyword list for discoverability. |

### Structural rules

| Condition | Finding |
|-----------|---------|
| Duplicate child element (e.g. two `<name>` elements) within one `<catalog-metadata>` block | ERROR -- names the duplicated tag |
| More than one `<catalog-metadata>` block in the file | ERROR -- names the count found |
| Malformed XML (parse failure) | ERROR -- names the parse error |
| Zero `<catalog-metadata>` blocks | ERROR |

### Exit code behaviour

`kanon catalog audit --check metadata` exits **1** when any ERROR-level finding is
present (missing required field, duplicate child, multiple blocks, or malformed XML).
It exits **0** when only WARN-level findings are present (missing recommended fields).
The `--strict` flag (T8) will promote WARNs to ERRORs and is not yet active.

### Example output

```
ERROR: [M001] /path/repo-specs/tool-marketplace.xml: required <catalog-metadata> field <name> is missing or contains only whitespace. Add a non-empty <name> element to the <catalog-metadata> block.
WARN: [M002] /path/repo-specs/tool-marketplace.xml: recommended <catalog-metadata> field <owner-email> is absent. Consider adding <owner-email> to improve catalog discoverability.
ERROR: [M006] /path/repo-specs/tool-marketplace.xml: duplicate <name> element inside <catalog-metadata>; each child tag must appear at most once. Remove the extra <name> element.
ERROR: [M005] /path/repo-specs/tool-marketplace.xml: 2 <catalog-metadata> blocks found; exactly one is required. Remove the extra <catalog-metadata> elements.
```

JSON equivalent:

```json
{
  "findings": [
    {
      "kind": "error",
      "code": "M001",
      "message": "/path/repo-specs/tool-marketplace.xml: required <catalog-metadata> field <name> is missing or contains only whitespace. Add a non-empty <name> element to the <catalog-metadata> block.",
      "remediation": ""
    }
  ]
}
```

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Audit completed. No ERROR-level findings produced by any selected check. WARN-level findings do not affect the exit code (unless `--strict` is active). |
| `1` | One or more ERROR-level findings produced, OR a fatal error occurred (missing audit target path, clone failure, missing repo-specs/ directory, or invalid environment variable configuration). |
| `2` | Argument parsing error (invalid `--check` value, etc.). |

## Error messages

Error messages follow the standard kanon shape:

```
ERROR: <one-line summary>
[optional context lines, wrapped at 80 cols]
[remediation line when applicable]
```

### Common errors

- `ERROR: --check requires a non-empty value. Valid values: all, ...`
  Cause: `--check ''` was passed.
  Fix: provide a valid check name or omit `--check` to use the default (`all`).

- `ERROR: 'all' cannot be combined with other --check values. Use '--check all' alone to run every check, or list individual check names without 'all'.`
  Cause: `--check all,metadata` was passed.
  Fix: use `--check all` alone, or list individual check names without `all`.

- `ERROR: Unknown --check value(s): nonsense. Valid values: all, entry-name-uniqueness, metadata, remote-url, source-name-derivation, tag-format.`
  Cause: an invalid check name was passed.
  Fix: use one of the five valid check names listed above.

- `ERROR: Audit target path does not exist: /path/to/missing`
  Cause: the supplied path does not exist on disk.
  Fix: verify the path or supply a valid `<git_url>@<ref>` source.

- `ERROR: Audit target '/path' does not contain a 'repo-specs/' directory.`
  Cause: the supplied directory is not a manifest repo.
  Fix: point `kanon catalog audit` at the root of a manifest repo.

- `ERROR: KANON_CACHE_DIR must be set to use a remote audit target. Set the environment variable to a writable directory path.`
  Cause: a remote source was supplied but `KANON_CACHE_DIR` is not set.
  Fix: `export KANON_CACHE_DIR=/path/to/cache` and re-run.

- `ERROR: Failed to clone audit target <url>@<ref>:`
  Cause: git clone returned a non-zero exit code when attempting to clone the remote audit target.
  Fix: verify the URL is accessible, the ref exists in the remote repository, network connectivity is available, and git authentication is configured (SSH keys or credential helper).

- `ERROR: Empty ref in audit source: '<source>'. Expected '<git_url>@<ref>'.`
  Cause: a remote source was supplied in `<git_url>@<ref>` form but the ref
  portion after the last `@` is empty (e.g. `https://github.com/org/repo.git@`).
  Fix: append a valid ref such as a branch name, tag, or full commit SHA after
  the `@` (e.g. `https://github.com/org/repo.git@main`).

- `ERROR: KANON_CATALOG_AUDIT_FORMAT has invalid value '<val>'. Valid values: text, json.`
  Cause: the `KANON_CATALOG_AUDIT_FORMAT` environment variable is set to a value
  other than `text` or `json`.
  Fix: `export KANON_CATALOG_AUDIT_FORMAT=text` or
  `export KANON_CATALOG_AUDIT_FORMAT=json`, then re-run.

## Examples

```bash
# Audit the current directory (must contain repo-specs/)
kanon catalog audit

# Audit an explicit local path
kanon catalog audit /path/to/manifest-repo

# Audit a remote repo (requires KANON_CACHE_DIR)
export KANON_CACHE_DIR=~/.kanon-cache
kanon catalog audit https://github.com/org/manifest-repo.git@main

# Run only metadata and tag-format checks
kanon catalog audit --check metadata,tag-format

# Output findings as JSON
kanon catalog audit --format json

# Promote warnings to errors (non-zero exit on any WARN finding)
kanon catalog audit --strict

# Combine: JSON output on a remote target, only metadata check
kanon catalog audit https://github.com/org/repo.git@v1.0.0 \
  --check metadata --format json
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KANON_CATALOG_AUDIT_FORMAT` | `text` | Default output format. CLI `--format` takes precedence. |
| `KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS` | `3600` | Cache TTL in seconds for remote clones. Must be a positive integer. |
| `KANON_CACHE_DIR` | (unset) | Root cache directory. Required for remote audit targets. |

## Related commands

- `kanon doctor` -- workspace health checks
- `kanon list` -- browse catalog entries
- `kanon add` -- add catalog entries to a `.kanon` file
