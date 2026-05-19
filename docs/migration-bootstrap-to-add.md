# Migration: `kanon bootstrap` to `kanon add` / `kanon list`

## Why `kanon bootstrap` is deprecated

`kanon bootstrap` was the original command for setting up a catalog entry inside a
project. It copied files from the upstream catalog into a `catalog/<name>/` directory
tree committed alongside the project source, and wrote a `.kanon` manifest file.

This model had two problems:

1. **Bundled catalog fallback.** The kanon wheel shipped a bundled
   `src/kanon_cli/catalog/` directory so that `kanon bootstrap` could run without a
   `--catalog-source`. This created an implicit, opaque default that was easy to
   misconfigure and hard to audit.

2. **Template directory coupling.** Projects accumulated a `catalog/<name>/` directory
   that served as a runtime data source. kanon >= 1.0.0 reads all source configuration
   from the root `.kanon` file; the `catalog/` directory is unused and should not exist.

The replacement workflow -- `kanon add` / `kanon list` -- is explicit about the catalog
source (required via `--catalog-source` or `KANON_CATALOG_SOURCE`), writes only to the
`.kanon` manifest file, and leaves no per-entry directory tree behind.

**Forced migration at the CI / script boundary.** Any `kanon bootstrap` invocation
(other than `--help`) now prints a WARN to stderr naming the exact replacement command
and exits with status 3 (`EXIT_CODE_DEPRECATED`) WITHOUT performing any work. Scripts
that call `kanon bootstrap` will fail immediately, which forces operators to update their
pipelines rather than silently running stale tooling.

## Flag translation table

The following table maps `kanon bootstrap` flags to their `kanon add` / `kanon list`
equivalents (spec Section 4.9):

| Bootstrap flag | `kanon add` equivalent | `kanon list` equivalent | Notes |
|---|---|---|---|
| `<package>` positional | `<name>` positional | (n/a -- `bootstrap list` triggers `kanon list`) | identical semantics |
| `--catalog-source <v>` | `--catalog-source <v>` | `--catalog-source <v>` | identical |
| `--output-dir <v>` | (no equivalent) | (no equivalent) | See notes below |

**`--output-dir` notes.**

- For `kanon add`: `--output-dir has no direct equivalent in 'kanon add'; the install
  workspace is the current directory or KANON_WORKSPACE_DIR if set.`
- For `kanon list`: `--output-dir has no equivalent in 'kanon list'.`

**`kanon bootstrap list` flag set.** Only `--catalog-source` is meaningful for the
list sub-command. Any other flag (today, only `--output-dir` exists) triggers a
`Note:` notice appended to the WARN body.

## Worked translation examples

The deprecation shim prints a verbatim WARN to stderr with the translated replacement
command. These examples show what the WARN body looks like in each case.

### 1. Package with no flags

```
kanon bootstrap kanon
```

WARN emitted to stderr:

```
WARN: 'kanon bootstrap kanon' is deprecated. Run instead:
    kanon add kanon
See docs/migration-bootstrap-to-add.md.
```

Run instead: `kanon add kanon`

### 2. Package with `--catalog-source`

```
kanon bootstrap kanon --catalog-source https://example.com/x.git@main
```

WARN emitted to stderr:

```
WARN: 'kanon bootstrap kanon' is deprecated. Run instead:
    kanon add kanon --catalog-source https://example.com/x.git@main
See docs/migration-bootstrap-to-add.md.
```

Run instead: `kanon add kanon --catalog-source https://example.com/x.git@main`

### 3. Package with `--output-dir` (no equivalent)

```
kanon bootstrap kanon --output-dir ./scratch
```

WARN emitted to stderr:

```
WARN: 'kanon bootstrap kanon' is deprecated. Run instead:
    kanon add kanon
See docs/migration-bootstrap-to-add.md.
Note: --output-dir has no direct equivalent in 'kanon add'; the install workspace is the current directory or KANON_WORKSPACE_DIR if set.
```

Run instead: `kanon add kanon` (choose your working directory before running).

### 4. List with `--catalog-source`

```
kanon bootstrap list --catalog-source https://example.com/x.git@main
```

WARN emitted to stderr:

```
WARN: 'kanon bootstrap list' is deprecated. Run instead:
    kanon list --catalog-source https://example.com/x.git@main
See docs/migration-bootstrap-to-add.md.
```

Run instead: `kanon list --catalog-source https://example.com/x.git@main`

### 5. List with `--output-dir` (no equivalent)

```
kanon bootstrap list --output-dir ./scratch
```

WARN emitted to stderr:

```
WARN: 'kanon bootstrap list' is deprecated. Run instead:
    kanon list
See docs/migration-bootstrap-to-add.md.
Note: --output-dir has no equivalent in 'kanon list'.
```

Run instead: `kanon list`

## What changed

| Old workflow (`kanon bootstrap`) | New workflow |
|----------------------------------|--------------|
| `kanon bootstrap` created a `.kanon` file and a `catalog/<name>/` tree. | Edit `.kanon` directly, then run `kanon add` to append entries. |
| Source data lived under `catalog/<name>/.kanon`. | Source data lives in `.kanon` at the project root. |
| The `catalog/` directory was committed to the project repo. | No `catalog/` directory is needed. |
| A bundled `src/kanon_cli/catalog/` in the wheel provided a default source. | No bundled catalog exists. `--catalog-source` or `KANON_CATALOG_SOURCE` is required. |

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
