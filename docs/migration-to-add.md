# Migration: `kanon bootstrap` to `kanon add` / `kanon list`

This guide is the central reference for operators moving away from the
removed `kanon bootstrap` command to `kanon add`, `kanon list`, and
`kanon install`. The deprecation message that every `kanon bootstrap`
invocation prints links here.

---

## Why this changed

`kanon bootstrap` was the original setup command. It read template
files from a `catalog/<name>/` directory inside the manifest repo (or
from a bundled catalog inside the kanon wheel itself) and copied them
into an output directory.

This model had two problems:

1. **Bundled catalog fallback.** The kanon wheel shipped a bundled
   catalog directory so that `kanon bootstrap` could run without a
   `--catalog-source`. This created an implicit, opaque default that
   was easy to misconfigure and hard to audit.

2. **Template directory coupling.** Projects accumulated a
   `catalog/<name>/` directory committed alongside the project source.
   kanon now reads all configuration from the root `.kanon` file; the
   `catalog/` directory is unused and must not exist.

`kanon bootstrap` was **removed in a major release** (a breaking
change). It no longer performs any work. The command name is retained
only as a uniform deprecation shim so that operators get a clear,
actionable message instead of an "unknown command" error.

**Forced migration at the CI / script boundary.** Every `kanon
bootstrap` invocation now exits with status `3`
(`EXIT_CODE_DEPRECATED`) and prints a deprecation message to stderr
naming the closest replacement command WITHOUT performing any work.
Scripts that call `kanon bootstrap` fail immediately, forcing operators
to update their pipelines rather than silently running stale tooling.

See [docs/exit-codes.md](exit-codes.md) for the full exit-code table.

---

## Command translations

| Removed command | Replacement command |
| --------------- | ------------------- |
| `kanon bootstrap <entry>` | `kanon add <entry> --catalog-source <git-url>@<ref>` |
| `kanon bootstrap list` | `kanon list --catalog-source <git-url>@<ref>` |

After adding entries, run `kanon install` to fetch them.

See [docs/list-and-add.md](list-and-add.md) for the full reference for
`kanon add` and `kanon list`, and
[docs/configuration.md](configuration.md) for `KANON_CATALOG_SOURCE`.

---

## No bootstrap flags remain

`kanon bootstrap` no longer accepts any flags. There is nothing to
translate per-flag: every argument and every flag is swallowed and
routed to the same deprecation message. This includes:

- `--help` / `-h` (no exit-0 help; see "The exit-3 contract" below)
- the former `--output-dir` and `--catalog-source` flags
- any unknown flag (for example `--marketplace-install`)
- the `list` positional and any other positional

The catalog source for the replacement commands is supplied with
`--catalog-source <git-url>@<ref>` or the `KANON_CATALOG_SOURCE`
environment variable. The canonical `--catalog-source` flag definition
lives in `core/cli_args.py`; `kanon list`, `kanon add`, and the other
catalog-aware commands import it from there.

The replacement install artifacts (`.packages/` and `.kanon-data/`)
land beside `.kanon` by default; setting `KANON_WORKSPACE_DIR` relocates
them to that directory instead (the directory is created if absent; an
unwritable value causes a non-zero exit with an actionable message and
no silent fallback to cwd). `kanon clean` resolves the same directory so
it removes exactly what `kanon install` wrote.

See [docs/configuration.md](configuration.md) for `KANON_CATALOG_SOURCE`
and `KANON_WORKSPACE_DIR`.

---

## The exit-3 contract

`kanon bootstrap` exits **3** (`EXIT_CODE_DEPRECATED`) on **every**
invocation -- any args, any flags, including `--help`/`-h`, unknown
flags, `kanon bootstrap list`, and bare `kanon bootstrap`. There is no
invocation that exits `0` and no argparse "unrecognized arguments"
error. The shim:

- Prints the deprecation message to stderr.
- Exits with status `3`.
- Performs **no work** -- it does not read the manifest repo, does not
  parse catalog metadata, and does not touch the filesystem.
- Does **not delegate** to the replacement command. The operator must
  copy the suggested command and run it explicitly.

The message has a per-invocation "CLOSEST REPLACEMENT FOR WHAT YOU RAN"
line derived from what was typed:

- `kanon bootstrap list` -> `kanon list --catalog-source <git-url>@<ref>`
- any other entry `<x>` (and the no-argument case) ->
  `kanon add <entry> --catalog-source <git-url>@<ref>`

The rest of the message is identical for every invocation.

Example (`kanon bootstrap kanon`, or any non-`list` entry):

```text
DEPRECATED: `kanon bootstrap` was removed in a major release (a breaking change).
This command no longer performs any work and exits non-zero.

WHY IT CHANGED
The catalog model changed. A manifest repo no longer has a separate
catalog/<name>/ location, and the kanon wheel no longer bundles a catalog.
The catalog is now the manifest repo itself: each XML manifest under
repo-specs/ that carries a <catalog-metadata> block is a catalog entry,
identified by its <catalog-metadata><name>. (A marketplace is one kind of
entry; other manifest types live under repo-specs/ too.)

MANAGE KANON DEPENDENCIES INSTEAD
  search    kanon list --catalog-source <git-url>@<ref>
            (narrow with a <substring>, --regex, or --match-fields)
  add       kanon add <entry> --catalog-source <git-url>@<ref>
            (writes the entry into .kanon, creating .kanon for you if absent)
  install   kanon install

CLOSEST REPLACEMENT FOR WHAT YOU RAN
  kanon add kanon --catalog-source <git-url>@<ref>

RELATED COMMANDS
  list  add  remove  install  clean  outdated  why  doctor  validate
  catalog  completion        (run `kanon <command> --help` for details)

See docs/migration-to-add.md.
```

Example (`kanon bootstrap list`): identical to the above except the
"CLOSEST REPLACEMENT FOR WHAT YOU RAN" line reads:

```text
CLOSEST REPLACEMENT FOR WHAT YOU RAN
  kanon list --catalog-source <git-url>@<ref>
```

`kanon bootstrap --help`, `kanon bootstrap --marketplace-install`, and
bare `kanon bootstrap` all print the same message and exit `3`; the
"CLOSEST REPLACEMENT" line falls back to
`kanon add <entry> --catalog-source <git-url>@<ref>`.

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

- A manifest repo no longer has a separate `catalog/<name>/` location.
  The manifest repo **is** the catalog: each XML manifest under
  `repo-specs/` that carries a `<catalog-metadata>` block is a catalog
  entry, identified by its `<catalog-metadata><name>`. (A marketplace
  is one kind of entry; other manifest types live under `repo-specs/`
  too.)
- There is no `catalog/<name>/` directory. Catalog authors removed the
  legacy directory as part of this change.
- Consumers see the same entries via `kanon list`. No migration step is
  required for consumers beyond replacing their `kanon bootstrap`
  invocations with `kanon list` / `kanon add` / `kanon install`.

`kanon catalog audit` detects the presence of a legacy
`catalog/<name>/` directory and emits a WARN-level finding.

See [docs/catalogs-explained.md](catalogs-explained.md) for a full
explanation of the manifest-repo model.

---

## How the kanon wheel changed

The bundled catalog directory has been **removed** from the kanon
wheel.

**Consequences for operators:**

- There is no implicit default catalog source. The third-tier "bundled
  fallback" in catalog resolution no longer exists.
- Operators MUST supply a catalog source via `--catalog-source` or the
  `KANON_CATALOG_SOURCE` environment variable for every `kanon list`,
  `kanon add`, `kanon outdated`, `kanon why`, and `kanon catalog audit`
  invocation.
- Missing both `--catalog-source` and `KANON_CATALOG_SOURCE` is a hard
  error with a clear, actionable message. There is no fallback.
- For `kanon install` and `kanon doctor`, the lockfile's
  `[catalog].source` field is used as a fallback when present and
  consistent (re-resolution paths still require CLI/env).

See [docs/configuration.md](configuration.md) for the full
`KANON_CATALOG_SOURCE` reference.

---

## Migration timeline

| Event | Release |
| ----- | ------- |
| Bundled catalog removed from the kanon wheel | major release (breaking change) |
| Legacy `catalog/<name>/` audit warning added | same major release |
| `kanon bootstrap` removed; replaced by a uniform deprecation shim (exit 3) | same major release |
| Removal of the `kanon bootstrap` name from the CLI entirely | TBD |

The shim retains the `bootstrap` name only so the deprecation message
can be shown. Removing the name from the CLI entirely is a separate
future decision. Until then, every `kanon bootstrap` invocation exits
`3` immediately.

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
