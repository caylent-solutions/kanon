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
| `--strict` | Promotes warnings to errors for exit-code computation. Exits non-zero when any WARN-level finding is present. Prints a one-line summary to stderr naming the warning count. See [--strict flag](#--strict-flag). |
| `--no-color` | Suppress ANSI color codes in output. Inherited global flag from the top-level `kanon` parser. |

## Valid checks

### Selectable checks (`--check`)

The five soft-spot checks audited by `kanon catalog audit`:

| Check name | Description |
|------------|-------------|
| `metadata` | Verifies required fields (`name`, `display-name`, `description`, `version`) are present and non-empty in every catalog entry's XML metadata. |
| `source-name-derivation` | Verifies that each entry name in `<catalog-metadata><name>` is in its normalised form (lowercase, hyphens replaced with underscores) and uses only characters from `[a-zA-Z0-9_-]` (spec Section 3.5 soft-spot rule 2). |
| `entry-name-uniqueness` | Verifies that no two entries share the same `<catalog-metadata><name>` value across the entire catalog (soft-spot rule 3). Comparison is case-sensitive. |
| `remote-url` | Verifies that every `<project remote="X">` in each marketplace XML and its include chain can be resolved to a `<remote name="X" fetch="...">` definition using an HTTPS or SSH URL (spec Section 3.5 soft-spot rule 4; Section 3.6 HTTPS-by-default policy). |
| `tag-format` | Verifies that every git tag in the manifest repo has a canonical PEP 440 version as its last path component (soft-spot rule 5). |

Use `--check all` (or omit `--check`) to run all five checks.
Use a comma-separated list to run a subset, e.g. `--check metadata,tag-format`.

### Unconditional check (always runs)

One additional check runs on **every** `kanon catalog audit` invocation
regardless of the `--check` value. It cannot be selected or deselected:

| Check | Description |
|-------|-------------|
| Legacy `catalog/` directory | Detects the presence of a `catalog/<name>/` directory tree in the audit target (spec Section 4.8). This tree was created by the removed `kanon bootstrap` command and is unused by kanon >= 1.0.0. |

**Finding code:** `L001` (WARN).

**Finding message:**
```
WARN: [L001] Legacy catalog/ directory detected; this directory is unused by
kanon >= <version> and should be deleted; see docs/migration-to-add.md
```

where `<version>` is the running kanon CLI version.

**Exit code:** The legacy-directory WARN does not cause a non-zero exit code on
its own in default mode (exit 0). Under `--strict`, the WARN is treated as an
error and the exit code becomes 1 (spec Section 15).

See [docs/migration-to-add.md](../migration-to-add.md) for
migration instructions.

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

## --strict flag

The `--strict` flag promotes WARN-level findings to errors for the purposes of
exit-code computation. Findings are **not mutated**: the display always prints
`WARN:` prefixes for warnings, regardless of `--strict`. Only the exit code
changes.

### Exit-code rule

| Mode | Exit 0 | Exit 1 |
|------|--------|--------|
| Default (no `--strict`) | No ERROR findings | Any ERROR finding |
| `--strict` | No ERROR or WARN findings | Any ERROR or WARN finding |

### Strict-mode summary

When `--strict` is active AND at least one WARN finding exists, a one-line
summary is printed to **stderr** after all findings:

```
strict mode: <count> warning(s) treated as errors
```

where `<count>` is the number of WARN-level findings. This line is always
printed to stderr so it does not interfere with `--format json` stdout output.

The summary does NOT appear when:
- `--strict` is not passed.
- `--strict` is passed but zero WARN findings were produced.

### Example

```bash
# Run source-name-derivation against a fixture with only warnings:
kanon catalog audit --check source-name-derivation /path/to/manifest-repo
# -> exits 0 (warnings only; default mode)

kanon catalog audit --check source-name-derivation --strict /path/to/manifest-repo
# -> exits 1 (warnings promoted to errors)
# -> stderr: "strict mode: 3 warning(s) treated as errors"
```

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

## Source-name-derivation check (`--check source-name-derivation`)

The `source-name-derivation` check inspects every `*-marketplace.xml` file under
`repo-specs/` for spec Section 3.5 soft-spot rule 2 compliance.

For each file it reads `<catalog-metadata><name>` (the entry name) and applies two
independent checks:

### Normalisation drift (S001)

`derive_source_name(entry_name)` normalises an entry name by lowercasing it and
replacing every `-` with `_`. When the normalised form differs from the original
entry name, a **WARN** finding is produced naming both the original and the derived
form so the catalog author can decide whether to rename the entry.

Examples of entry names that trigger drift warnings:

| Entry name | Derived form | Reason |
|------------|--------------|--------|
| `Foo-Bar` | `foo_bar` | uppercase + hyphen |
| `foo-bar` | `foo_bar` | hyphen |
| `Foo` | `foo` | uppercase |

Entry names already in normalised form (e.g. `foo_bar`) produce zero drift findings.

### Out-of-charset (S002)

Entry names containing characters outside `[a-zA-Z0-9_-]` produce a **WARN** finding.
These characters are legal in XML but unusual; the warning helps authors spot
accidental whitespace, dots, or non-ASCII before they propagate into shell variable
names and `.kanon` files.

Examples of entry names that trigger charset warnings:

| Entry name | Bad character |
|------------|---------------|
| `foo.bar` | dot |
| `foo bar` | space |
| `f\u00f3\u00f3` | non-ASCII |

### Combining both checks

Both findings are independent. An entry name can produce both a drift warning and a
charset warning (e.g. `Foo.Bar` -- uppercase drift AND dot out-of-charset).

Entry name `foo.bar` produces only the S002 charset warning: `derive_source_name('foo.bar')`
returns `'foo.bar'` (no drift), but `.` is out-of-charset.

### Exit code behaviour

`kanon catalog audit --check source-name-derivation` exits **0** even when warnings
are present. All findings from this check are WARN-level; no ERROR findings are
produced. Under `--strict`, WARN findings are treated as errors and the exit
code becomes 1.

### Finding codes

| Code | Severity | Meaning |
|------|----------|---------|
| `S001` | WARN | Entry name differs from its normalised form (`derive_source_name` drift). |
| `S002` | WARN | Entry name contains characters outside `[a-zA-Z0-9_-]`. |

### Example output

```
WARN: [S001] /path/repo-specs/tool-marketplace.xml: entry name 'Foo-Bar' normalises to 'foo_bar' via derive_source_name. Consider renaming the entry to match the derived form to avoid surprises in shell variable names and .kanon files. -- Rename <name>Foo-Bar</name> to <name>foo_bar</name> in the <catalog-metadata> block.
WARN: [S002] /path/repo-specs/tool-marketplace.xml: entry name 'foo.bar' contains characters outside the recommended set [a-zA-Z0-9_-]. Characters outside this set may not survive shell quoting cleanly and can cause unexpected behaviour in shell variable names. -- Rename <name>foo.bar</name> to use only [a-zA-Z0-9_-] characters in the <catalog-metadata> block.
```

## Entry-name-uniqueness check (`--check entry-name-uniqueness`)

The `entry-name-uniqueness` check inspects every `*-marketplace.xml` file under
`repo-specs/` for spec Section 3.5 soft-spot rule 3 compliance.

It builds a mapping from `<catalog-metadata><name>` to the list of XML files that
declare that name. When two or more files share the same name, one ERROR finding
(U001) is emitted listing every offending file path.

### Collision semantics

- An entry name that appears in exactly one file produces no finding.
- An entry name that appears in N > 1 files produces **one** ERROR finding (not N),
  listing all N paths.
- Files that have no parseable `<name>` element are silently skipped -- their
  errors are reported by `--check metadata` (M001) and do not contribute to
  uniqueness collisions.

### Case sensitivity

Comparison is **case-sensitive**. `Foo` and `foo` are treated as distinct names
and do NOT collide under this check. If two names differ only in case (e.g.
`MyTool` and `mytool`), they normalise to the same source name at install time;
the `source-name-derivation` check (S001) will warn about normalisation drift
on the mixed-case variant.

### Exit code behaviour

`kanon catalog audit --check entry-name-uniqueness` exits **1** when any name
collision exists; exits **0** when all names are unique (or no XML files exist).

### Finding codes

| Code | Severity | Meaning |
|------|----------|---------|
| `U001` | ERROR | Entry name declared in more than one file. |

### Example output

```
ERROR: [U001] Entry name 'my-tool' is declared in 2 files: /path/repo-specs/tool-a-marketplace.xml, /path/repo-specs/tool-b-marketplace.xml. Entry names must be unique across every repo-specs/**/*-marketplace.xml file. -- Rename <name>my-tool</name> to a unique value in all but one of the listed files, or remove the duplicate catalog entries.
```

## Remote-URL check (`--check remote-url`)

The `remote-url` check inspects every `*-marketplace.xml` file under `repo-specs/`
for spec Section 3.5 soft-spot rule 4 compliance. For each file it:

1. Walks the `<include>` chain depth-first and collects all
   `<remote name="..." fetch="...">` definitions reachable from the file.
2. For each `<project remote="X">` in the marketplace XML, resolves `X` to
   its fetch URL by looking up the collected definitions.

### Finding codes

| Code | Severity | Meaning |
|------|----------|---------|
| `R001` | ERROR | `<project remote="X">` references a remote name that is not defined anywhere in the reachable include chain. |
| `R002` | ERROR | The resolved fetch URL uses a non-HTTPS/non-SSH scheme (e.g. `file://`, `http://`) and `KANON_ALLOW_INSECURE_REMOTES` is not set to `1`. |
| `R003` | ERROR | The resolved fetch URL contains a query string (`?`) or fragment (`#`); URL canonicalization is undefined for such values. |

### Unresolvable remote (R001)

When a `<project>` element references `remote="X"` but no `<remote name="X">` is
found anywhere in the marketplace XML or its transitive includes, a single R001
ERROR is emitted naming the `<project>` element, the XML file path, and the
unresolved remote name. The remediation points to `kanon validate marketplace`.

### HTTPS-by-default policy (R002)

By default, only `https://` and SSH URLs (`git@host:org/repo.git` or
`ssh://git@host/path`) are accepted as fetch URLs. Plain HTTP (`http://`),
`file://`, and any other schemes produce an R002 ERROR.

To allow insecure URLs (intended for local test fixtures only), set:

```bash
export KANON_ALLOW_INSECURE_REMOTES=1
```

When `KANON_ALLOW_INSECURE_REMOTES=1` is set, R002 findings are suppressed.
R001 and R003 findings are **never** suppressed by this variable.

### Query-string and fragment detection (R003)

A fetch URL containing a `?` (query string) or `#` (fragment) produces an R003
ERROR regardless of the scheme. URL canonicalization is undefined for such URLs
(spec Section 4.8, E1-F2-S1-T1). The remediation asks the author to remove the
query string or fragment from the `<remote>` element's `fetch` attribute.

### Include-chain resolution

The remote-url check uses a depth-first include walker to collect `<remote>`
definitions from the marketplace file and all files reachable via `<include>`
chains. This means:

- A `<remote>` defined in an included helper XML is visible to all marketplace
  files that include it (directly or transitively).
- Diamond includes (the same file reachable via two different paths) are visited
  only once. The first-visited definition wins when the same remote name appears
  in multiple files.
- Cycles in the include chain produce no findings (the walker is cycle-safe).

### Exit code behaviour

`kanon catalog audit --check remote-url` exits **1** when any R001, R002, or R003
finding is produced; exits **0** when no findings are produced.

### Example output

```
ERROR: [R001] /path/repo-specs/tool-marketplace.xml: <project name='my-project'> references remote='missing' but no <remote name='missing'> is defined anywhere in the reachable include chain. -- Add a <remote name="missing" fetch="<url>"/> element to the manifest or a file reachable via its <include> chain, or run 'kanon validate marketplace' to identify structural issues.
ERROR: [R002] /path/repo-specs/tool-marketplace.xml: <remote name='local'> has fetch URL 'file:///tmp/test-repos' which uses a non-HTTPS remote URL. Only HTTPS and SSH remote URLs are trusted by default (spec Section 3.6 HTTPS-by-default policy). -- Change the fetch URL to use https:// or ssh:// (or git@ shorthand), or set KANON_ALLOW_INSECURE_REMOTES=1 to allow insecure remotes (intended for tests and local fixtures only).
ERROR: [R003] /path/repo-specs/tool-marketplace.xml: <remote name='cdn'> has fetch URL 'https://example.com/mirrors?token=abc' which contains a query string or fragment. URL canonicalization is undefined for such URLs. -- Remove the query string or fragment from the fetch URL in <remote name='cdn' fetch="..."/>.
```

## Tag-format check (`--check tag-format`)

The `tag-format` check audits every git tag in the manifest repo to verify that
its last path component is a canonical PEP 440 version string (spec Section 3.5
soft-spot rule 5; Section 0.4; Section 4.0).

kanon's resolver (`version.py`) resolves version constraints against tag names by
parsing the last `/`-delimited path component via `packaging.version.Version`.
Tags whose last component either fails to parse OR whose normalized form differs
from the original are flagged as **unaddressable**: they are invisible to kanon's
constraint resolver and cannot be referenced by operators.

### Monorepo-style tags

Monorepo-prefixed tags such as `subpackage/1.0.0` are fully supported. Only the
last `/`-delimited component (`1.0.0`) is tested. A monorepo tag passes if its
last component is a valid canonical PEP 440 version.

Examples:

| Tag name | Last component | PEP 440 canonical? | Finding |
|----------|---------------|-------------------|---------|
| `1.0.0` | `1.0.0` | yes | none |
| `2026.4.1` | `2026.4.1` | yes | none |
| `subpackage/1.0.0` | `1.0.0` | yes | none |
| `subpackage/2.0.0` | `2.0.0` | yes | none |
| `v1.0.0` | `v1.0.0` | no (normalizes to `1.0.0`) | WARN T001 |
| `release-2024` | `release-2024` | no | WARN T001 |
| `subpackage/v1.0.0` | `v1.0.0` | no | WARN T001 |

### What "canonical PEP 440" means

A tag name component is canonical when it both parses as a `packaging.version.Version`
AND its string representation equals the normalized form. For example:

- `1.0.0` -- parses, normalized form is `1.0.0` (equal) -- canonical.
- `v1.0.0` -- parses (packaging normalizes it to `1.0.0`), but `str(Version("v1.0.0")) == "1.0.0"` differs from `v1.0.0` -- NOT canonical.
- `release-2024` -- does not parse as PEP 440 -- NOT canonical.

This distinction matters because git tag names are exact strings. An operator
writing `~=1.0.0` as a version constraint will never match the tag `v1.0.0`
directly via the git tag path.

### Cap behaviour

When the number of non-canonical tags exceeds `KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT`
(default: 50, overridable via the `KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT`
environment variable), only the first 50 per-tag WARN findings are emitted.
One additional WARN finding summarises the remaining count and directs the
author to run `kanon catalog audit --check tag-format` for the full list.

### Exit code behaviour

`kanon catalog audit --check tag-format` exits **0** even when WARN findings are
present. All findings from this check are WARN-level; no ERROR findings are
produced. Under `--strict`, WARN findings are treated as errors and the exit
code becomes 1.

Manifest repos with legitimate non-version tags (ops markers, release-prep tags)
still work; the warning surfaces unaddressability so authors can decide whether
to rename tags to canonical PEP 440 form.

### Finding codes

| Code | Severity | Meaning |
|------|----------|---------|
| `T001` | WARN | Tag's last path component is not a canonical PEP 440 version string; the tag is unaddressable by kanon's resolver. |

### Inventory workflow

Run this check to discover non-canonical tags in a manifest repo before
operators encounter resolver failures:

```bash
# Inventory non-PEP-440 tags in a local manifest repo
kanon catalog audit --check tag-format /path/to/manifest-repo

# Inventory a remote manifest repo
export KANON_CACHE_DIR=~/.kanon-cache
kanon catalog audit --check tag-format https://github.com/org/manifest-repo.git@main
```

### Example output

```
WARN: [T001] Tag 'v1.0.0' is unaddressable: the last path component 'v1.0.0' is not a valid PEP 440 version. kanon's resolver ignores tags whose last component does not parse as a PEP 440 version. -- Rename the tag so its last path component is a valid PEP 440 version (e.g. '1.0.0', '1.0.0a1'). See https://peps.python.org/pep-0440/ for PEP 440 version syntax.
WARN: [T001] Tag 'release-2024' is unaddressable: the last path component 'release-2024' is not a valid PEP 440 version. kanon's resolver ignores tags whose last component does not parse as a PEP 440 version. -- Rename the tag so its last path component is a valid PEP 440 version (e.g. '1.0.0', '1.0.0a1'). See https://peps.python.org/pep-0440/ for PEP 440 version syntax.
```

JSON equivalent:

```json
{
  "findings": [
    {
      "kind": "warn",
      "code": "T001",
      "message": "Tag 'v1.0.0' is unaddressable: the last path component 'v1.0.0' is not a valid PEP 440 version. kanon's resolver ignores tags whose last component does not parse as a PEP 440 version.",
      "remediation": "Rename the tag so its last path component is a valid PEP 440 version (e.g. '1.0.0', '1.0.0a1'). See https://peps.python.org/pep-0440/ for PEP 440 version syntax."
    }
  ]
}
```

### Environment variables for tag-format

| Variable | Default | Description |
|----------|---------|-------------|
| `KANON_CATALOG_AUDIT_TAG_REPORT_LIMIT` | `50` | Maximum number of per-tag WARN findings emitted per run. When more non-canonical tags exist, a single summary WARN names the remaining count. Must be a positive integer. |

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
Under `--strict`, WARN findings are treated as errors and the exit code becomes 1.

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
| `KANON_ALLOW_INSECURE_REMOTES` | (unset) | When set to `1`, suppresses R002 findings for non-HTTPS/SSH remote URLs. Any value other than `1` is treated as unset. Intended for local test fixtures only; do not set in production CI pipelines. R001 and R003 findings are never suppressed by this variable. |

## Related commands

- `kanon doctor` -- workspace health checks
- `kanon list` -- browse catalog entries
- `kanon add` -- add catalog entries to a `.kanon` file
