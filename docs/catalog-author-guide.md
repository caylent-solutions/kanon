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
```

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

## Related documentation

- `docs/cli/catalog-audit.md` -- full CLI reference for `kanon catalog audit`
- `docs/creating-packages.md` -- end-to-end guide to creating a new package
- `docs/creating-manifest-repos.md` -- guide to setting up a manifest repo
