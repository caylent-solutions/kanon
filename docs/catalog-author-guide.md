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

## Related documentation

- `docs/cli/catalog-audit.md` -- full CLI reference for `kanon catalog audit`
- `docs/creating-packages.md` -- end-to-end guide to creating a new package
- `docs/creating-manifest-repos.md` -- guide to setting up a manifest repo
