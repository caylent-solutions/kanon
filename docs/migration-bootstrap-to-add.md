# Migration: `kanon bootstrap` to `kanon add` / `kanon list`

This guide is the central reference for operators moving from the
deprecated `kanon bootstrap` command to `kanon add` and `kanon list`.
Every WARN line emitted by the bootstrap shim links here.

---

## Why this changed

`kanon bootstrap` was the original setup command. It read template
files from a `catalog/<name>/` directory inside the manifest repo (or
from a bundled `src/kanon_cli/catalog/` inside the kanon wheel itself)
and copied them into `--output-dir`.

This model had two problems:

1. **Bundled catalog fallback.** The kanon wheel shipped a bundled
   `src/kanon_cli/catalog/` directory so that `kanon bootstrap` could
   run without a `--catalog-source`. This created an implicit, opaque
   default that was easy to misconfigure and hard to audit.

2. **Template directory coupling.** Projects accumulated a
   `catalog/<name>/` directory committed alongside the project source.
   kanon >= 1.0.0 reads all configuration from the root `.kanon` file;
   the `catalog/` directory is unused and must not exist.

**Forced migration at the CI / script boundary.** Any `kanon bootstrap`
invocation (other than `--help`) now exits with status 3
(`EXIT_CODE_DEPRECATED`) and prints a WARN to stderr naming the exact
replacement command WITHOUT performing any work. Scripts that call
`kanon bootstrap` will fail immediately, forcing operators to update
their pipelines rather than silently running stale tooling.

See [docs/exit-codes.md](exit-codes.md) for the full exit-code table.

---

## Command translations

| Deprecated command | Replacement command |
| ------------------ | ------------------- |
| `kanon bootstrap <name>` | `kanon add <name>` |
| `kanon bootstrap list` | `kanon list` |

See [docs/list-and-add.md](list-and-add.md) for the full reference
for `kanon add` and `kanon list`.

---

## Flag translations

The following table maps every `kanon bootstrap` flag to its
`kanon add` / `kanon list` equivalent (spec Section 4.9):

| Bootstrap flag | `kanon add` equivalent | `kanon list` equivalent |
| -------------- | ---------------------- | ----------------------- |
| `<package>` positional | `<name>` positional | n/a |
| `--catalog-source <v>` | `--catalog-source <v>` | `--catalog-source <v>` |
| `--output-dir <v>` | no equivalent | no equivalent |

**`<package>` positional.** Identical semantics: the catalog entry
name. When the positional is `list`, the bootstrap shim routes to the
`kanon list` replacement.

**`--catalog-source`.** Identical in all three commands. The canonical
flag definition now lives in `core/cli_args.py`; every command imports
it from there.

**`--output-dir`.** There is no direct equivalent in `kanon add`. The
install artifacts (`.packages/` and `.kanon-data/`) land beside `.kanon`
by default; setting `KANON_WORKSPACE_DIR` relocates them to that directory
instead (the directory is created if absent; an unwritable value causes a
non-zero exit with an actionable message and no silent fallback to cwd).
`kanon clean` resolves the same directory so it removes exactly what
`kanon install` wrote. `--output-dir` has no equivalent in `kanon list`
either. When `--output-dir` appears in a deprecated `kanon bootstrap`
invocation, the WARN body includes a `Note:` line explaining this.

See [docs/configuration.md](configuration.md) for `KANON_CATALOG_SOURCE`.

---

## The exit-3 contract

`kanon bootstrap` exits **3** (`EXIT_CODE_DEPRECATED`) on every
non-`--help` invocation. The shim:

- Prints a WARN to stderr naming the exact replacement command.
- Exits with status 3.
- Performs **no work** -- it does not read the manifest repo, does not
  parse catalog metadata, and does not touch the filesystem.
- Does **not delegate** to the replacement command. The operator must
  copy-paste and run the suggested command explicitly.

`kanon bootstrap --help` is the only invocation that exits 0. Help
output is prepended with a `DEPRECATED:` notice for discoverability.

Example WARN (package, no flags):

```text
WARN: 'kanon bootstrap kanon' is deprecated. Run instead:
    kanon add kanon
See docs/migration-bootstrap-to-add.md.
```

Example WARN (package, with `--catalog-source`):

```text
WARN: 'kanon bootstrap kanon' is deprecated. Run instead:
    kanon add kanon \
      --catalog-source \
      https://example.com/org/manifest-repo.git@main
See docs/migration-bootstrap-to-add.md.
```

Example WARN (`bootstrap list`, with `--catalog-source`):

```text
WARN: 'kanon bootstrap list' is deprecated. Run instead:
    kanon list \
      --catalog-source \
      https://example.com/org/manifest-repo.git@main
See docs/migration-bootstrap-to-add.md.
```

Example WARN (package, `--output-dir` has no equivalent):

```text
WARN: 'kanon bootstrap kanon' is deprecated. Run instead:
    kanon add kanon
See docs/migration-bootstrap-to-add.md.
Note: --output-dir has no direct equivalent in 'kanon add'; \
the install workspace is the current directory or \
KANON_WORKSPACE_DIR if set.
```

See [docs/exit-codes.md](exit-codes.md) for the canonical exit-code
reference.

---

## How manifest repos changed

**Before (legacy model):**

- A manifest repo contained a `catalog/<name>/` directory for each
  catalog entry. This directory held pre-baked `.kanon` snippets and
  per-entry READMEs consumed by `kanon bootstrap`.
- `kanon bootstrap <name>` read from `catalog/<name>/` and copied
  files into the project's working directory.

**After (current model):**

- Every catalog-entry definition lives in a single
  `*-marketplace.xml` file under `repo-specs/`, identified by its
  `<catalog-metadata>` block.
- There is no `catalog/<name>/` directory. Catalog authors removed
  the legacy directory as part of this deprecation.
- Consumers see the same entries via `kanon list`. No migration step
  is required for consumers beyond updating their `kanon bootstrap`
  invocations.

`kanon catalog audit` detects the presence of a legacy
`catalog/<name>/` directory and emits a WARN-level finding.

See [docs/catalogs-explained.md](catalogs-explained.md) for a full
explanation of the manifest-repo model.

---

## How the kanon wheel changed

The bundled `src/kanon_cli/catalog/` directory has been **removed**
from the kanon wheel.

**Consequences for operators:**

- The third-tier "bundled fallback" in `resolve_catalog_dir()` no
  longer exists. There is no implicit default catalog source.
- Operators MUST supply a catalog source via `--catalog-source` or
  the `KANON_CATALOG_SOURCE` environment variable for every `kanon
  list`, `kanon add`, `kanon outdated`, `kanon why`, and
  `kanon catalog audit` invocation.
- Missing both `--catalog-source` and `KANON_CATALOG_SOURCE` is a
  hard error with a clear, actionable message. There is no fallback.
- For `kanon install` and `kanon doctor`, the lockfile's
  `[catalog].source` field is used as a fallback when present and
  consistent (re-resolution paths still require CLI/env).

See [docs/configuration.md](configuration.md) for the full
`KANON_CATALOG_SOURCE` reference.

---

## Migration timeline

| Event | Version |
| ----- | ------- |
| `kanon bootstrap` becomes a deprecation shim (exit 3, WARN) | 1.0.0 |
| Bundled `src/kanon_cli/catalog/` removed from wheel | 1.0.0 |
| Legacy `catalog/<name>/` audit warning added | 1.0.0 |
| Hard removal of `kanon bootstrap` shim | TBD |

The hard-removal release is a separate future decision. During the
deprecation window (kanon 1.x), all `kanon bootstrap` invocations
other than `--help` exit 3 immediately.

---

## See also

- [docs/list-and-add.md](list-and-add.md) -- replacement commands
  `kanon add` and `kanon list`
- [docs/catalogs-explained.md](catalogs-explained.md) -- what a
  manifest repo is and how catalog entries are structured
- [docs/exit-codes.md](exit-codes.md) -- canonical exit-code table,
  including exit 3 (`EXIT_CODE_DEPRECATED`)
- [docs/configuration.md](configuration.md) -- `KANON_CATALOG_SOURCE`
  and other environment variables
