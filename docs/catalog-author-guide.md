# Catalog author guide

This guide describes how to write and maintain `*-marketplace.xml` files so that
`kanon catalog audit` reports no findings against your manifest repo.

## Marketplace XML structure

Every installable package in a manifest repo is described by one
`*-marketplace.xml` file under the `repo-specs/` directory.  The filename must
end in `-marketplace.xml` (e.g. `my-tool-marketplace.xml`).

Each file must contain exactly one `<catalog-metadata>` block:

```xml
<?xml version="1.0"?>
<package>
  <catalog-metadata>
    <name>my-tool</name>
    <display-name>My Tool</display-name>
    <description>A short prose description of what this package does.</description>
    <version>1.2.3</version>
    <type>plugin</type>
    <owner-name>Alice Example</owner-name>
    <owner-email>alice@example.com</owner-email>
    <keywords>infra,deploy,kubernetes</keywords>
  </catalog-metadata>
  <!-- ... other package elements ... -->
</package>
```

## Required fields

The following fields are **required**.  A missing or whitespace-only value causes
`kanon catalog audit --check metadata` to emit one ERROR finding per field and
exit with code 1.

| Field | Description | Example |
|-------|-------------|---------|
| `name` | Machine-readable package identifier.  Used as the source name in `.kanon` files and shell variable names.  Use lowercase letters, digits, and hyphens only. | `my-tool` |
| `display-name` | Human-readable label shown in `kanon list` output. | `My Tool` |
| `description` | Short (one or two sentence) prose description of what the package does and who should use it. | `Deploys Kubernetes manifests using Helm.` |
| `version` | Author-claimed version string.  Informational only; kanon does not validate it against semver or PEP-440.  Use a consistent scheme such as `MAJOR.MINOR.PATCH`. | `1.2.3` |

### Whitespace-only values are treated as missing

An element present in the XML but containing only whitespace is treated
identically to an absent element:

```xml
<!-- This is treated as missing -- produces an ERROR finding -->
<name>   </name>

<!-- Correct -->
<name>my-tool</name>
```

## Recommended fields

The following fields are **recommended**.  A missing field causes
`kanon catalog audit --check metadata` to emit one WARN finding per field.
WARN findings do not affect the exit code unless `--strict` is active.

| Field | Description | Example |
|-------|-------------|---------|
| `type` | Package type string.  Helps operators filter and understand the catalog. | `plugin`, `library`, `template` |
| `owner-name` | Primary owner display name.  Helps operators know who to contact. | `Alice Example` |
| `owner-email` | Primary owner contact address. | `alice@example.com` |
| `keywords` | Comma-separated keyword list for discoverability in `kanon list` searches. | `infra,deploy,kubernetes` |

## Structural rules

`kanon catalog audit --check metadata` also enforces the following structural
rules.  Violations produce ERROR findings.

### One `<catalog-metadata>` block per file

Each `*-marketplace.xml` file must contain exactly one `<catalog-metadata>` block.
Having zero or more than one block produces an ERROR:

```xml
<!-- ERROR: two <catalog-metadata> blocks -->
<package>
  <catalog-metadata>
    <name>tool-a</name>
    ...
  </catalog-metadata>
  <catalog-metadata>
    <name>tool-b</name>
    ...
  </catalog-metadata>
</package>

<!-- Correct: one block per file -->
<package>
  <catalog-metadata>
    <name>tool-a</name>
    ...
  </catalog-metadata>
</package>
```

### No duplicate child elements

Each child element within `<catalog-metadata>` must appear at most once.
Repeating a tag (even with different text) produces an ERROR:

```xml
<!-- ERROR: two <name> elements -->
<catalog-metadata>
  <name>my-tool</name>
  <name>my-tool-alias</name>
  ...
</catalog-metadata>

<!-- Correct: each tag appears once -->
<catalog-metadata>
  <name>my-tool</name>
  ...
</catalog-metadata>
```

## Source-name derivation and entry-name conventions

`kanon catalog audit --check source-name-derivation` enforces spec Section 3.5
soft-spot rule 2. Two independent findings can be raised per entry name.

### Normalisation rule

`derive_source_name(entry_name)` transforms a `<name>` value into a
`KANON_SOURCE_<name>_*` shell variable token by:

1. Lowercasing the entire string.
2. Replacing every `-` (hyphen) with `_` (underscore).

No other transformation is applied. The function is deterministic and idempotent.

When the normalised form differs from the original entry name, `kanon catalog audit`
emits a **WARN** finding (S001) suggesting you rename the entry to the derived form.

Examples:

| Entry name | Derived form | Action |
|------------|--------------|--------|
| `Foo-Bar` | `foo_bar` | Rename to `foo_bar` |
| `foo-bar` | `foo_bar` | Rename to `foo_bar` |
| `MyTool` | `mytool` | Rename to `mytool` |
| `foo_bar` | `foo_bar` | No action needed |

### Allowed entry-name character set

Entry names SHOULD use only characters from `[a-zA-Z0-9_-]`. Characters outside
this set produce a **WARN** finding (S002) because they:

- May not survive shell quoting cleanly.
- Can cause unexpected behaviour in shell variable names derived from the entry name.
- Signal accidental whitespace, dots, or non-ASCII characters.

Common problematic characters and how to fix them:

| Character | Example | Fix |
|-----------|---------|-----|
| `.` (dot) | `foo.bar` | Use `foo_bar` |
| ` ` (space) | `my tool` | Use `my_tool` |
| Non-ASCII | `f\u00f3\u00f3` | Use ASCII equivalents, e.g. `foo` |

Note that hyphens (`-`) are within the allowed charset but cause normalisation drift
(S001), so using underscores directly (`_`) is preferred.

### Both findings are independent

An entry name can trigger both S001 and S002 simultaneously. For example, `Foo.Bar`:
- S001: `Foo.Bar` normalises to `foo.bar` (different from `Foo.Bar`) -- drift.
- S002: `Foo.Bar` contains `.` -- out-of-charset.

The recommended fix is to use a name like `foo_bar` which is already normalised and
uses only the allowed character set.

## Entry-name uniqueness

`kanon catalog audit --check entry-name-uniqueness` enforces spec Section 3.5
soft-spot rule 3. Every `<catalog-metadata><name>` value must be unique across
all `*-marketplace.xml` files in the manifest repo.

### The uniqueness rule

When two or more files share the same `<name>` value, `kanon install` cannot
tell which entry to use. The check emits one ERROR finding (U001) listing every
file that declares the colliding name.

```xml
<!-- ERROR: two files both declare name 'my-tool' -->

<!-- file: repo-specs/group-a/my-tool-marketplace.xml -->
<catalog-metadata>
  <name>my-tool</name>
  ...
</catalog-metadata>

<!-- file: repo-specs/group-b/my-tool-marketplace.xml -->
<catalog-metadata>
  <name>my-tool</name>
  ...
</catalog-metadata>
```

Fix: give each entry a distinct name (e.g. `my-tool-alpha` and `my-tool-beta`),
or remove the duplicate entry entirely.

### Case sensitivity

Entry-name uniqueness comparison is **case-sensitive**: `MyTool` and `mytool`
are treated as two distinct names by this check and do NOT collide here.

However, both names normalise to the same source name (`mytool`) via
`derive_source_name`. At install time, shell variable names derived from both
entries would be identical (`KANON_SOURCE_MYTOOL_URL`, etc.), producing a real
conflict.

The `source-name-derivation` check (S001) warns about this normalisation drift.
Authors who want case-insensitive uniqueness should rely on `--check
source-name-derivation` to surface these drift warnings in addition to
`--check entry-name-uniqueness`.

### Relationship to `source-name-derivation`

The two checks cover complementary scenarios:

| Scenario | Detected by |
|----------|-------------|
| `my-tool` declared in two files (exact match) | `entry-name-uniqueness` (U001 ERROR) |
| `My-Tool` and `my-tool` each in one file (case drift) | `source-name-derivation` (S001 WARN) |

Run both checks together (`--check all`) for complete coverage.

## Remote-URL discoverability (soft-spot rule 4)

`kanon catalog audit --check remote-url` enforces spec Section 3.5 soft-spot rule 4.
Every `<project remote="X">` in a marketplace XML must have a corresponding
`<remote name="X" fetch="...">` definition discoverable via the include chain.

### How remote resolution works

The check performs a depth-first walk of every `<include>` chain reachable from
the marketplace XML and collects all `<remote name="..." fetch="...">` definitions.
For each `<project remote="X">`:

1. If no `<remote name="X">` is found anywhere in the reachable chain =>
   **R001 ERROR** (unresolvable remote).
2. If the resolved fetch URL contains a `?` or `#` => **R003 ERROR** (query string
   or fragment in URL; canonicalization undefined).
3. If the resolved fetch URL uses a non-HTTPS/SSH scheme and
   `KANON_ALLOW_INSECURE_REMOTES` is not `1` => **R002 ERROR** (insecure URL).

### Allowed URL schemes

| Scheme | Status | Notes |
|--------|--------|-------|
| `https://` | Accepted | Always trusted. |
| `git@host:org/repo.git` | Accepted | SSH SCP shorthand; treated as HTTPS-equivalent. |
| `ssh://git@host/path` | Accepted | Explicit SSH; treated as HTTPS-equivalent. |
| `http://` | Rejected by default | Allowed with `KANON_ALLOW_INSECURE_REMOTES=1`. |
| `file://` | Rejected by default | Allowed with `KANON_ALLOW_INSECURE_REMOTES=1`. |
| `https://...?query` | Always rejected | R003: query strings are not allowed. |
| `https://...#frag` | Always rejected | R003: fragments are not allowed. |

### Example: remote defined in a helper include

A common pattern is to declare shared `<remote>` definitions in a helper XML that
multiple marketplace files include:

```xml
<!-- repo-specs/helpers/remotes.xml -->
<?xml version="1.0"?>
<manifest>
  <remote name="origin" fetch="https://github.com/my-org" />
</manifest>
```

```xml
<!-- repo-specs/my-tool-marketplace.xml -->
<?xml version="1.0"?>
<manifest>
  <catalog-metadata>
    <name>my-tool</name>
    ...
  </catalog-metadata>
  <include name="repo-specs/helpers/remotes.xml" />
  <project name="my-tool" remote="origin" path="src/my-tool" />
</manifest>
```

The check resolves `remote="origin"` to `https://github.com/my-org` via the
include, accepts the HTTPS URL, and produces zero findings.

### Finding codes

| Code | Severity | Meaning |
|------|----------|---------|
| `R001` | ERROR | `<project remote="X">` has no matching `<remote name="X">` in the include chain. |
| `R002` | ERROR | Resolved fetch URL uses a non-HTTPS/SSH scheme without opt-out. |
| `R003` | ERROR | Resolved fetch URL contains a query string or fragment. |

## Tag naming: PEP 440 compliance (soft-spot rule 5)

kanon's version resolver reads git tags from the manifest repo and resolves
operator version constraints (e.g. `~=1.0.0`) against them.  For a tag to be
addressable by the resolver, its last `/`-delimited path component must be a
**canonical PEP 440 version string**.

A canonical PEP 440 version string is one where:

1. `packaging.version.Version(component)` parses without raising `InvalidVersion`, AND
2. The string representation of the parsed version equals the original component
   (i.e. `str(Version(component)) == component`).

Tags that fail either condition are silently skipped by the resolver.  Operators
writing version constraints like `~=1.0.0` will not find such tags, which leads
to confusing "no version found" errors.

### Canonical vs. non-canonical tag examples

| Tag name | Addressable? | Reason |
|----------|-------------|--------|
| `1.0.0` | yes | Canonical PEP 440 |
| `2026.4.1` | yes | Calendar version, canonical PEP 440 |
| `subpackage/1.0.0` | yes | Monorepo prefix; last component `1.0.0` is canonical |
| `v1.0.0` | no | `packaging` normalizes `v1.0.0` to `1.0.0`; non-canonical |
| `release-2024` | no | Does not parse as PEP 440 |
| `subpackage/v1.0.0` | no | Last component `v1.0.0` is non-canonical |

### Inventory non-PEP-440 tags with the audit check

Use `kanon catalog audit --check tag-format` to inventory all non-canonical tags
before operators encounter resolver failures.  This is the recommended discovery
tool for non-PEP-440 tags in a manifest repo:

```bash
# Inventory non-canonical tags in a local manifest repo
kanon catalog audit --check tag-format /path/to/manifest-repo

# Inventory a remote manifest repo
export KANON_CACHE_DIR=~/.kanon-cache
kanon catalog audit --check tag-format https://github.com/org/manifest-repo.git@main
```

The check exits **0** even when warnings are present -- non-canonical tags are a
WARN finding (code `T001`), not an error.  Manifest repos with legitimate
non-version tags (ops markers, release-prep tags) continue to work; the warning
helps authors decide whether to rename tags to canonical PEP 440 form.

## Running the audit locally

To check your manifest repo before pushing:

```bash
# Audit the current directory (must contain repo-specs/)
kanon catalog audit --check metadata .

# Audit only the metadata check, show output as JSON
kanon catalog audit --check metadata --format json .

# Audit a remote repo
export KANON_CACHE_DIR=~/.kanon-cache
kanon catalog audit --check metadata https://github.com/org/manifest-repo.git@main

# Inventory non-PEP-440 tags (recommended before releasing new catalog versions)
kanon catalog audit --check tag-format .
```

## Validate before pushing (fast local check)

`kanon validate metadata` runs the same in-repo soft-spot checks (rules 1, 2, 3)
as `kanon catalog audit --check metadata,source-name-derivation,entry-name-uniqueness`
but without any network access or git operations. Use it in a pre-push hook or
a local dev loop where speed matters:

```bash
# Check soft-spots 1, 2, and 3 with no network access
kanon validate metadata --repo-root .

# Exit early on first error (shell short-circuit)
kanon validate metadata --repo-root . && echo "All checks passed -- safe to push"

# JSON output for CI log parsing
kanon validate metadata --repo-root . --format json | jq '.findings | length'
```

### Recommended pre-push workflow

1. **Fast local check:** Run `kanon validate metadata --repo-root .` before every
   `git push`. This catches metadata errors, source-name drift, and name collisions
   without touching the network.
2. **Full audit:** Run `kanon catalog audit .` (or against a remote source) in CI
   to cover soft-spots 4 and 5 (remote-URL resolvability and PEP 440 tag-name
   compliance), which require git operations.

Both commands share the same findings schema (`{"findings": [...]}` for JSON
output, one finding per line for text output) and the same exit code semantics
(exit 0 for no errors, exit 1 for any ERROR finding).

Exit code 0 means no ERROR findings (WARN findings may still appear on stdout).
Exit code 1 means at least one ERROR finding was produced.

## Finding codes

| Code | Severity | Meaning |
|------|----------|---------|
| `M001` | ERROR | Required field missing or whitespace-only. |
| `M002` | WARN | Recommended field absent. |
| `M003` | ERROR | Malformed XML -- file could not be parsed. |
| `M004` | ERROR | Zero `<catalog-metadata>` blocks found. |
| `M005` | ERROR | More than one `<catalog-metadata>` block found. |
| `M006` | ERROR | Duplicate child element within `<catalog-metadata>`. |
| `S001` | WARN | Entry name differs from its normalised form (source-name derivation drift). |
| `S002` | WARN | Entry name contains characters outside `[a-zA-Z0-9_-]`. |
| `U001` | ERROR | Entry name declared in more than one file (entry-name uniqueness collision). |
| `R001` | ERROR | `<project remote="X">` has no matching `<remote name="X">` in the include chain. |
| `R002` | ERROR | Resolved fetch URL uses a non-HTTPS/SSH scheme without `KANON_ALLOW_INSECURE_REMOTES=1`. |
| `R003` | ERROR | Resolved fetch URL contains a query string or fragment. |
| `T001` | WARN | Tag's last path component is not a canonical PEP 440 version string; the tag is unaddressable by kanon's resolver. |

## Related documentation

- `docs/cli/catalog-audit.md` -- full CLI reference for `kanon catalog audit`
- `docs/creating-packages.md` -- end-to-end guide to creating a new package
- `docs/creating-manifest-repos.md` -- guide to setting up a manifest repo
