# kanon install

Operator-facing reference for `kanon install` -- the command that
resolves and installs the dependencies declared in `.kanon` and pins
them in `.kanon.lock`.

For the canonical environment-variable table see
[docs/configuration.md](configuration.md).
For lifecycle details see [docs/lifecycle.md](lifecycle.md).

---

## Synopsis

```text
kanon install [--refresh-lock | --refresh-lock-source <name>]
              [--strict-lock] [--strict-drift]
              [--lock-file <path>]
              [<kanonenv_path>]
```

## How it works

`kanon install` is **hermetic** (spec Section 4.3 / FR-14): it reads
only the committed `.kanon` file and its `.kanon.lock`, fetches every
declared source, resolves the transitive include/project graph, and
publishes the result into the shared `KANON_HOME` store. It does **not**
resolve or record a catalog source: the `--catalog-source` flag is not
accepted (passing it exits non-zero), and a populated
`KANON_CATALOG_SOURCES` environment variable is ignored, not read.

A catalog source is needed only by the discovery commands (`kanon
search`, `kanon add`, `kanon outdated`, `kanon why`, `kanon catalog
audit`). You supply it there; `kanon add` writes the resolved,
alias-keyed `KANON_SOURCE_<alias>_*` blocks into `.kanon`, and from then
on `kanon install` works from those blocks with no catalog source.

On first run -- or when `--refresh-lock` is passed -- the lockfile
`.kanon.lock` is written at schema v4. Subsequent runs in a consistent
state install directly from the lockfile without re-resolving.

## The reconcile model

`kanon install` follows an npm-like reconcile model:

- **Lockfile consistent** (`.kanon.lock` present and its `kanon_hash`
  matches `.kanon`): replay the pinned SHAs verbatim. No re-resolution.
- **Lockfile drifted** (`.kanon.lock` present but `kanon_hash` differs,
  e.g. after editing `.kanon`): by default, reconcile -- prune orphaned
  entries, resolve added/changed sources fresh, replay unchanged ones,
  and rewrite the lock once on success. With `--strict-lock` this drift
  is a hard error instead (npm-ci style).
- **No lockfile**: resolve everything from `.kanon` and write
  `.kanon.lock`.

To re-resolve from scratch, pass `--refresh-lock`. To re-resolve exactly
one top-level source while preserving every other lockfile entry, pass
`--refresh-lock-source <name>`.

## Where artifacts live

`kanon install` publishes fetched data into the shared `KANON_HOME`
store, content-addressed and deduped across projects:

- The store root resolves with precedence `--home` / `--store-dir`
  flag > `KANON_HOME` environment variable > the default `~/.kanon`.
- The store directory is created if absent. If it cannot be created or is
  not writable, `kanon install` exits non-zero with an actionable
  message naming the path and the `KANON_HOME` variable -- there is no
  silent fallback.
- `kanon clean` resolves the same store root, so it removes exactly what
  `kanon install` wrote.

The legacy per-project `.packages/` / `.kanon-data/` locations and their
`KANON_WORKSPACE_DIR` / `KANON_CACHE_DIR` environment variables were
removed; the shared `KANON_HOME` store subsumes them.

## Flags

| Flag | Description |
|------|-------------|
| `--refresh-lock` | Ignore the existing lockfile, re-resolve every transitive version from scratch against the committed `.kanon`, and overwrite `.kanon.lock`. |
| `--refresh-lock-source <name>` | Re-resolve exactly one top-level source's full chain while preserving every other source's lockfile entries verbatim. `<name>` may be the `KANON_SOURCE_<name>` alias or a catalog entry name. |
| `--strict-lock` | Promote orphaned lock entries (and a `kanon_hash` drift) to a hard error instead of reconciling them (see [Orphaned lockfile entries](#orphaned-lockfile-entries)). |
| `--strict-drift` | Promote branch drift (a locked SHA differing from the branch's current tip) to a hard error instead of reusing the locked SHA. |
| `--lock-file <path>` | Path to the lock file (default: `<kanon-file>.lock`; env `KANON_LOCK_FILE`). |

`kanon install` accepts no `--catalog-source` flag: it is hermetic.

## Orphaned lockfile entries

An orphaned lockfile entry is a `[[sources]]` row in `.kanon.lock` whose
alias no longer has a matching `KANON_SOURCE_<alias>_URL` block in
`.kanon`. This happens when a source is removed from `.kanon` (for
example, via `kanon remove`) but the lockfile has not yet been updated to
reflect that removal.

### Default behaviour: auto-prune

By default, `kanon install` detects orphaned lockfile entries, removes them
from the in-memory lockfile, and emits one INFO line per orphan:

```text
pruned orphaned lock entry: <alias>
```

For example, if a source aliased `alpha` was removed from `.kanon` and
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

Suppose your `.kanon` file originally declares a source aliased `my_lib`, and
`kanon add` has already been run so `.kanon.lock` contains the corresponding
entry. You then remove the source:

```bash
kanon remove my_lib
```

The next bare `kanon install` automatically reconciles the lockfile:

```text
pruned orphaned lock entry: my_lib
```

Installation then completes with the remaining declared sources.

## See also

- [docs/lockfile.md](lockfile.md) -- lockfile format and lifecycle.
- [docs/list-and-add.md](list-and-add.md) -- `kanon search`, `kanon add`, and `kanon remove`.
- [docs/configuration.md](configuration.md) -- full environment-variable reference.
- [docs/catalogs-explained.md](catalogs-explained.md) -- what a manifest repo is and how to find one.
