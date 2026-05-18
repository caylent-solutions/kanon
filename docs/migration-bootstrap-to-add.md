# Migration: `kanon bootstrap` to `kanon add` / `kanon list`

## Overview

The `kanon bootstrap` command created an initial `.kanon` file and populated
a `catalog/<name>/` directory tree inside the project. This command was
removed in kanon 1.0.0. Projects that still contain a `catalog/` directory
have leftover artefacts from the old workflow.

`kanon catalog audit` detects the presence of this legacy directory and emits
a WARN finding:

```
WARN: [L001] Legacy catalog/ directory detected; this directory is unused by
kanon >= <version> and should be deleted; see docs/migration-bootstrap-to-add.md
```

This document explains what to do when you see that warning.

## What changed

| Old workflow (`kanon bootstrap`) | New workflow |
|----------------------------------|--------------|
| `kanon bootstrap` created a `.kanon` file and a `catalog/<name>/` tree. | Edit `.kanon` directly, then run `kanon add` to append entries. |
| Source data lived under `catalog/<name>/.kanon`. | Source data lives in `.kanon` at the project root. |
| The `catalog/` directory was committed to the project repo. | No `catalog/` directory is needed. |

## Migration steps

### 1. Verify the `.kanon` file is complete

The current `.kanon` file should contain all the `KANON_SOURCE_*` lines that
were previously spread across individual `catalog/<name>/.kanon` files.

If your project was migrated automatically, all source definitions are already
in the root `.kanon` file. You can verify by running:

```bash
kanon list
```

This command reads from the catalog source (not from `catalog/`) and shows
available entries.

### 2. Remove the legacy `catalog/` directory

Once you have confirmed the `.kanon` file is complete, remove the old tree:

```bash
rm -rf catalog/
git rm -r catalog/
git commit -m "chore: remove legacy kanon bootstrap catalog/ directory"
```

### 3. Confirm the warning is gone

Run the audit again to confirm no legacy-directory finding appears:

```bash
kanon catalog audit .
```

The `WARN: [L001]` finding should no longer appear.

## Adding new catalog entries

Use `kanon add` instead of the old bootstrap flow:

```bash
# Add a catalog entry by name (requires a catalog source)
kanon add <entry-name>

# List available entries in the catalog
kanon list
```

See `kanon add --help` and `kanon list --help` for full usage.

## Related commands

- `kanon catalog audit` -- audit a manifest repo for soft-spot violations
  (includes the unconditional legacy-directory check)
- `kanon add` -- add a catalog entry to the `.kanon` file
- `kanon list` -- list available catalog entries

## Background

The `catalog/<name>/` directory was created by `kanon bootstrap` to mirror
the upstream catalog layout inside each project. kanon >= 1.0.0 reads all
source configuration from the root `.kanon` file and no longer references
the `catalog/` directory. The directory is safe to delete once your `.kanon`
file is complete.

During the deprecation window (kanon 1.x), the presence of a non-empty
`catalog/` directory produces a WARN-level finding and does not block
operation. A future release (per spec Section 15) will promote this warning
to an error.
