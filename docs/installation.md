# kanon install

Operator-facing reference for `kanon install` -- the command that
resolves and installs dependencies declared in `.kanon` using
the catalog source.

For the canonical environment-variable table see
[docs/configuration.md](configuration.md).
For lifecycle details see [docs/lifecycle.md](lifecycle.md).

---

## Synopsis

```text
kanon install [--catalog-source <git-url>@<ref>]
              [--refresh-lock | --refresh-lock-source <name>]
              [--strict-lock] [--strict-drift]
              [--lock-file <path>]
              [<kanonenv_path>]
```

## How it works

`kanon install` reads the `.kanon` file, resolves the effective
catalog source (see [Catalog source precedence](#catalog-source-precedence)
below), clones the manifest repo, fetches all declared sources, and
writes the aggregated packages into `.packages/`.

On first run -- or when `--refresh-lock` is passed -- the lockfile
`.kanon.lock` is written. Subsequent runs in a consistent state
install directly from the lockfile without re-cloning the catalog.

## Catalog source precedence

`kanon install` needs to know which manifest repo (catalog) to use.
The effective catalog source is resolved by
`_resolve_catalog_source` following this four-layer precedence chain
(highest priority first):

1. `--catalog-source <git-url>@<ref>` -- the CLI flag. Always wins
   when provided. Example:
   `kanon install --catalog-source https://example.com/org/catalog.git@main`

2. `KANON_CATALOG_SOURCE` environment variable. Wins when the CLI
   flag is absent. Example:
   `KANON_CATALOG_SOURCE=https://example.com/org/catalog.git@main kanon install`

3. `[catalog].source` from `.kanon.lock` -- the lockfile's recorded
   catalog source. This fallback applies **only** in the
   `LOCKFILE_CONSISTENT` state and **only** when neither the CLI flag
   nor the env var is set. It is disabled on `--refresh-lock` and
   `--refresh-lock-source` paths because those paths are explicitly
   rebuilding the lockfile and must receive a fresh source from the
   operator.

4. `[catalog]` block inside the `.kanon` file -- written automatically
   by `kanon add` when the `.kanon` file is first created. Applies
   when the block is present and the three higher-priority layers all
   return no value. See [.kanon catalog block format](#kanon-catalog-block-format)
   below.

When all four layers return no value, `kanon install` exits with a
non-zero code and the canonical error:

```text
ERROR: install requires a catalog source.
Provide one of:
  --catalog-source <git-url>@<ref>
  KANON_CATALOG_SOURCE=<git-url>@<ref>  # set as env var, then re-run
```

## One-step workflow after kanon add

`kanon add` writes the `[catalog]` block to the `.kanon` file when
the file is first created. This means subsequent bare `kanon install`
invocations succeed without the operator having to re-pass
`--catalog-source`:

```bash
# First use: declare the catalog source explicitly.
kanon add my-entry --catalog-source https://example.com/org/catalog.git@main

# .kanon now contains a [catalog] block recording the catalog source.
# All subsequent installs in this project can omit the flag.
kanon install
```

The `[catalog]` block recorded by `kanon add` is the fourth-priority
fallback. If the env var or a consistent lockfile is also present,
those take precedence over the block.

## Hand-edited .kanon files

If you author a `.kanon` file by hand without adding a `[catalog]`
block, bare `kanon install` will still raise the missing-source
diagnostic above. The fix is to either:

- Pass `--catalog-source <url>@<ref>` on the command line (or set
  `KANON_CATALOG_SOURCE`), or
- Add the `[catalog]` block to your hand-written `.kanon` file
  (see format below).

## .kanon catalog block format

`kanon add` writes the following INI-style block at the top of a
freshly-created `.kanon` file:

```properties
[catalog]
KANON_CATALOG_SOURCE=<git-url>@<ref>
```

For example:

```properties
[catalog]
KANON_CATALOG_SOURCE=https://example.com/org/manifest-repo.git@main
```

The `[catalog]` header must appear on its own line (no leading or
trailing whitespace). The `KANON_CATALOG_SOURCE=` key-value line must
immediately follow (blank lines between them are not allowed and
produce a `CatalogBlockParseError`). The value must be non-empty.

A hand-written `.kanon` that includes this block gains the same
auto-derive behaviour as one created by `kanon add`.

## Flags

| Flag | Description |
|------|-------------|
| `--catalog-source <git-url>@<ref>` | Override or supply the catalog source. Wins over env var, lockfile, and `.kanon` block. |
| `--refresh-lock` | Rebuild the full lockfile from `.kanon`. Requires `--catalog-source` or `KANON_CATALOG_SOURCE`; the lockfile fallback is disabled on this path. |
| `--refresh-lock-source <name>` | Rebuild the lockfile entry for a single named source. Same catalog-source requirement as `--refresh-lock`. |
| `--strict-lock` | Promote orphaned lock entries to a hard error instead of pruning them (see [Orphaned lockfile entries](#orphaned-lockfile-entries)). |
| `--strict-drift` | Promote branch drift (a locked SHA differing from the branch's current tip) to a hard error instead of reusing the locked SHA. |
| `--lock-file <path>` | Path to the lock file (default: `<kanon-file>.lock`; env `KANON_LOCK_FILE`). |

## Orphaned lockfile entries

An orphaned lockfile entry is a `[[sources]]` row in `.kanon.lock` whose
`name` no longer has a matching `KANON_SOURCE_<name>_URL` triple in `.kanon`.
This happens when a source is removed from `.kanon` (for example, via
`kanon remove`) but the lockfile has not yet been updated to reflect that
removal.

### Default behaviour: auto-prune

By default, `kanon install` detects orphaned lockfile entries, removes them
from the in-memory lockfile, and emits one INFO line per orphan:

```text
pruned orphaned lock entry: <name>
```

For example, if a source named `alpha` was removed from `.kanon` and
`.kanon.lock` still contains its entry, running `kanon install` produces:

```text
pruned orphaned lock entry: alpha
```

The lockfile is then rewritten without the orphaned entry and installation
continues normally. No operator intervention is required.

### Opt-in error path: --strict-lock

If you want `kanon install` to fail loudly instead of silently pruning
orphaned entries, pass `--strict-lock`:

```bash
kanon install --strict-lock
```

With `--strict-lock`, the command exits non-zero and enumerates every
orphaned source by name so you can decide intentionally. For options to
resolve the error, see
[docs/troubleshooting.md -- 15. Strict-lock Orphan Errors](troubleshooting.md#15-strict-lock-orphan-errors).

### Worked example

Suppose your `.kanon` file originally declares a source named `my-lib`, and
`kanon add` has already been run so `.kanon.lock` contains the corresponding
entry. You then remove the source:

```bash
kanon remove my-lib
```

The next bare `kanon install` automatically reconciles the lockfile:

```text
pruned orphaned lock entry: my-lib
```

Installation then completes with the remaining declared sources.

## See also

- [docs/lockfile.md](lockfile.md) -- lockfile format and lifecycle.
- [docs/list-and-add.md](list-and-add.md) -- `kanon list`, `kanon add`, and `kanon remove`.
- [docs/configuration.md](configuration.md) -- full environment-variable reference.
- [docs/catalogs-explained.md](catalogs-explained.md) -- what a manifest repo is and how to find one.
