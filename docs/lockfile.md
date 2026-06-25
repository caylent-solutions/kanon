# Kanon Lockfile Reference (`.kanon.lock`)

Operator-facing reference for the `.kanon.lock` file: its format,
`kanon_hash` semantics, schema migration policy, conflict resolution,
and refresh flow.

For the canonical environment-variable table see
[docs/configuration.md](configuration.md).
For install-engine internals see
[docs/architecture.md](architecture.md).
For exit codes see
[docs/exit-codes.md](exit-codes.md).
For workspace health checks see
[docs/doctor.md](doctor.md).

---

## What .kanon.lock is

`.kanon.lock` is a TOML file that captures the exact resolved state of
every dependency declared in a `.kanon` file at the moment
`kanon install` last ran successfully. It is machine-generated and must
be committed to source control so that every subsequent `kanon install`
produces bit-for-bit identical results without re-resolving tags or
branches.

The lockfile records:

- The SHA-256 hash of the alias-keyed `.kanon` source declarations
  (`kanon_hash`).
- The exact git ref and commit SHA for every source and transitive
  dependency in the dependency tree, keyed by the source alias.

The schema-v4 lockfile carries no catalog block: `kanon install` is
hermetic and neither resolves nor records a catalog source. See
[Hermetic install](#hermetic-install).

The lockfile schema version is embedded in the file and drives the
migration policy. See [Schema migration](#schema-migration).
This document describes schema version 4, the format shipped with
kanon 3.0.0.

**Default lockfile path.** When `kanon install ./alt.kanon` is run, the
default lockfile path is `./alt.kanon.lock` unless `--lock-file` or
`KANON_LOCK_FILE` overrides it. See
[Default-lockfile path](#default-lockfile-path).

---

## Format reference

Schema version 4 uses TOML with three kinds of content: top-level scalar
fields and zero or more `[[sources]]` table-arrays (each keyed by alias),
each of which may contain `[[sources.includes]]` and `[[sources.projects]]`
sub-tables. There is no `[catalog]` block.

### TOML schema

```toml
schema_version         = 4
generated_at           = "2026-05-11T13:42:00Z"
generator              = "kanon-cli/3.0.0"
kanon_hash             = "sha256:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
marketplace_registered = true
marketplace_dir        = "/home/user/.claude-marketplaces"

[[sources]]
alias         = "package_a"
name          = "package-a"
url           = "https://example.com/org/manifest-repo.git"
ref_spec      = "==2.10.0"
resolved_ref  = "refs/tags/2.10.0"
resolved_sha  = "abc1234567890abcdef1234567890abcdef12345"
path          = "repo-specs/common/package-a/package-a-marketplace.xml"
registered_marketplaces = ["package-a-marketplace"]

  [[sources.includes]]
  name         = "git-connection/remote"
  path_in_repo = "repo-specs/git-connection/remote.xml"
  url          = "https://example.com/org/manifest-repo.git"
  resolved_sha = "abc1234567890abcdef1234567890abcdef12345"

    [[sources.includes.includes]]
    name         = "git-connection/transitive"
    path_in_repo = "repo-specs/git-connection/transitive.xml"
    url          = "https://example.com/org/manifest-repo.git"
    resolved_sha = "abc1234567890abcdef1234567890abcdef12345"

  [[sources.projects]]
  name          = "vendor/example-package"
  url           = "https://example.com/vendor/example-package.git"
  canonical_url = "https://example.com/vendor/example-package"
  ref_spec      = ">=1.0.0,<2.0.0"
  resolved_ref  = "refs/tags/1.4.2"
  resolved_sha  = "def4567890abcdef1234567890abcdef12345678"
```

### Top-level fields

**`schema_version`** (int) -- Must be `4`. Read first by `read_lockfile`
on every invocation path. An older lockfile (`1`, `2`, or `3`) is a hard
fail-fast: schema v4 is a breaking major and there is no automatic
upgrade. See [Schema migration](#schema-migration).

**`generated_at`** (string) -- ISO-8601 UTC timestamp when the lockfile
was written. Informational; not read by the state machine.

**`generator`** (string) -- `kanon-cli/<version>` string identifying the
writer. Informational; not read by the state machine.

**`kanon_hash`** (string) -- `sha256:`-prefixed 71-character digest
(`sha256:<64 lowercase hex chars>`) of the alias-keyed `KANON_SOURCE_*`
source declarations in the `.kanon` file. Pattern: `^sha256:[a-f0-9]{64}$`.
Used by `_classify_install_state` to detect `.kanon` drift. See
[kanon_hash](#kanon_hash).

**`marketplace_registered`** (bool, schema v2+) -- `true` when the last
`kanon install` registered a marketplace plugin. `kanon clean` reads this
field to decide whether to uninstall marketplace plugins and remove the
marketplace directory. Defaults to `false`. (Per-dependency marketplace
ownership is tracked in the per-source `registered_marketplaces` ledger;
see the [source entries](#sources-entries) section.)

**`marketplace_dir`** (string, schema v2+) -- The `CLAUDE_MARKETPLACES_DIR`
path used at install time. Non-empty only when `marketplace_registered`
is `true`; `kanon clean` removes this directory during teardown. Defaults
to the empty string.

### [[sources]] entries

Each `[[sources]]` block represents one top-level source repository
declared in the `.kanon` file. Entries are keyed by alias (schema v4): the
`alias` field is the lock key and is written first.

**`alias`** (string) -- The local alias the source is keyed by, matching
the `<alias>` in the `KANON_SOURCE_<alias>_*` declarations in `.kanon`.
The alias keys the entry and is written first.

**`name`** (string) -- The catalog entry name for the source.

**`url`** (string) -- Source repository URL.

**`ref_spec`** (string) -- Version / ref constraint for this source (the
v4 rename of the former `revision_spec`): a PEP 440 specifier, the `*`
wildcard, a `refs/...` ref, or a branch name. Written at lock time.

**`resolved_ref`** (string) -- Git ref resolved from `ref_spec`.
Written at lock time.

**`resolved_sha`** (string) -- Pinned commit SHA. Used to pin the clone
during `LOCKFILE_CONSISTENT` replay and to check SHA reachability in the
`LOCKFILE_UNREACHABLE` branch.

**`path`** (string) -- Path to the XML manifest file in this source repo.
Must not contain tab (`\t`), NUL (`\x00`), or newline (`\n`).

**`registered_marketplaces`** (list of strings, schema v3) -- The sorted
set of marketplace names this source registered during the last
`kanon install`. Written sorted for deterministic, byte-stable output;
defaults to `[]` for sources that registered no marketplace (or when
marketplace install is disabled). This per-source ledger is the authority
for marketplace ownership: `kanon clean --orphans` and the `kanon install`
auto-prune (see [Marketplace ownership and pruning](#marketplace-ownership-and-pruning))
consult it to attribute and unregister the marketplaces of a removed
source, and never enumerate `~/.claude` to remove by exclusion -- so a
marketplace kanon never recorded can never be unregistered.

**`includes`** (list) -- Zero or more `[[sources.includes]]` entries,
recursive, unbounded depth.

**`projects`** (list) -- Zero or more `[[sources.projects]]` entries.

### [[sources.includes]] entries

Include entries are recursive: each entry may have its own `includes`
list. Entries are written in DFS pre-order (the traversal order of
`_walk_includes` in `core/include_walker.py`). Diamond shapes (two paths
to the same XML file) are deduplicated: the shared file appears exactly
once at its first-walked position.

**`name`** (string) -- Display name of the included file. Surfaced in
error messages.

**`path_in_repo`** (string) -- Repo-relative path to the included XML
file. Must not contain tab, NUL, or newline.

**`url`** (string) -- URL of the manifest repository that owns this
include.

**`resolved_sha`** (string) -- Pinned commit SHA for reproducibility.

**`includes`** (list) -- Nested includes (may be empty or absent).

### [[sources.projects]] entries

**`name`** (string) -- Project name. Surfaced in error messages.

**`url`** (string) -- Raw project URL as declared in the catalog XML.

**`canonical_url`** (string) -- Canonical form of `url` (output of
`canonicalize_repo_url`). Used for conflict detection: two entries
sharing a canonical URL but pinning different SHAs trigger a
`CanonicalUrlConflictError`.

**`ref_spec`** (string) -- Version / ref constraint for this project (the
v4 rename of the former `revision_spec`). Written at lock time.

**`resolved_ref`** (string) -- Resolved git ref. Used during
`LOCKFILE_CONSISTENT` replay.

**`resolved_sha`** (string) -- Pinned commit SHA. Used to pin the project
clone via repo sync.

### Validation rules

`read_lockfile` enforces the following rules. Any violation raises a
specific exception naming the offending field and value, and suggesting
a remediation step.

**Rule 1: `kanon_hash` format.** Must match `^sha256:[a-f0-9]{64}$`
(71 characters total). A bare 64-character hex string, uppercase hex,
or any other length is rejected. Exception: `LockfileValidationError`.
Remediation: `kanon install --refresh-lock`.

**Rule 2: `resolved_sha` format.** Every `resolved_sha` field in
`[[sources]]`, `[[sources.includes]]`, and `[[sources.projects]]` must
match `^[a-f0-9]{40}$` (SHA-1) or `^[a-f0-9]{64}$` (SHA-256). Uppercase
hex is rejected. Exception: `LockfileValidationError`. Remediation:
`kanon install --refresh-lock`.

**Rule 3: `ref_spec` format.** Accepted if it satisfies any one
of: (a) a valid PEP 440 `SpecifierSet` with optional monorepo path
prefix (e.g., `subpackage/==1.0.0`); (b) the bare wildcard `*`
("any version", written verbatim by `add`/`install`); (c) starts with
`refs/`; or (d) matches `^[a-zA-Z0-9_./+-]+$`.
Exception: `LockfileValidationError`.

**Rule 4: `canonical_url` consistency.** Every `[[sources.projects]]`
entry's `canonical_url` must equal `canonicalize_repo_url(url)`.
Exception: `LockfileValidationError`.

**Rule 5: path fields.** The `path` field on every `[[sources]]` entry
and the `path_in_repo` field on every `[[sources.includes]]` entry must
not contain `\x00` (NUL), `\n` (newline), or `\t` (tab).
Exception: `LockfileValidationError`.

**Rule 6: `registered_marketplaces` shape.** When present on a
`[[sources]]` entry, `registered_marketplaces` must be a list whose every
element is a string. A non-list value, or a list containing a non-string
element, is rejected; malformed entries are never silently coerced or
dropped. Exception: `LockfileValidationError`. Remediation:
`kanon install`.

---

## kanon_hash

`kanon_hash` is a deterministic SHA-256 digest stored in the lockfile
that covers only the alias-keyed `KANON_SOURCE_<alias>_{URL,REF,PATH}`
declarations in the `.kanon` file. It changes whenever a source URL,
ref, or path changes, and remains stable across all other edits.
`kanon install` and `kanon doctor` compare the `.kanon` file's current
hash to the lockfile's `kanon_hash` to detect consumer-side drift.

### Algorithm (spec Section 5.1)

1. Parse the `.kanon` file via `parse_kanonenv`.
2. Extract every source's `{URL, REF, PATH}` keyed by alias. Discard
   comments, blank lines, declaration order, the per-source `_NAME` and
   `_GITBASE` keys, the per-dependency `KANON_SOURCE_<alias>_MARKETPLACE`
   flag, and the `CLAUDE_MARKETPLACES_DIR` workspace key.
3. Sort sources by alias (lexicographic, case-sensitive).
4. Serialize as bytes `alias\turl\tref\tpath\n` per source.
   If any of `alias`, `url`, `ref`, or `path` contains a literal
   tab (`\t`, U+0009), NUL byte (`\x00`, U+0000), or newline
   (`\n`, U+000A), a `KanonHashError` is raised naming the source, the
   field, and the offending codepoint. This is a hard error; there is
   no sanitisation or fallback.
5. SHA-256 the serialized bytes.
6. Return `sha256:<64 lowercase hex chars>` -- 71 characters total.

### Hash-equivalent cases (hash does NOT change)

The following changes to `.kanon` do NOT change `kanon_hash`:

- Re-ordering source blocks.
- Adding, removing, or changing comments.
- Adding or removing blank lines.
- Changing any `KANON_SOURCE_<alias>_GITBASE` value.
- Changing any `KANON_SOURCE_<alias>_NAME` value.
- Changing `CLAUDE_MARKETPLACES_DIR`.
- Toggling any `KANON_SOURCE_<alias>_MARKETPLACE` flag.

### Hash-differs cases (hash DOES change)

The following changes to `.kanon` cause the hash to change, making the
existing lockfile stale:

- Changing any `_REF` value for any source.
- Changing any `_URL` value for any source.
- Changing any `_PATH` value for any source.
- Changing a source alias (the `<alias>` token in `KANON_SOURCE_<alias>_*`).
- Adding or removing a source.

### Tab-in-path rejection

If `url`, `ref`, or `path` for any source contains a literal tab
character (U+0009), NUL byte (U+0000), or newline (U+000A), the hash
function raises `KanonHashError` naming the source, field, and offending
codepoint. `kanon install` propagates this as a hard error and exits with
a non-zero code. There is no sanitisation and no fallback.

The same character set is rejected in `path` and `path_in_repo` fields
by lockfile validation Rule 5.

### Implementation reference

```python
from pathlib import Path
from kanon_cli.core.kanon_hash import kanon_hash, KanonHashError

digest = kanon_hash(Path(".kanon"))  # returns "sha256:<64 hex chars>"
```

The function is pure: given identical `.kanon` content it returns
identical output. It does not touch the filesystem beyond reading the
`kanon_path` argument and makes no network calls.

---

## Hermetic install

`kanon install` is hermetic (spec Section 4.3 / FR-14). The schema-v4
lockfile carries no catalog block, so install neither resolves nor records
a catalog source: it is driven solely by the committed `.kanon` and
`.kanon.lock`.

- `kanon install` does not accept `--catalog-source`.
- A populated `KANON_CATALOG_SOURCES` environment variable has no effect on
  install (it is ignored, never read).
- There is no catalog-source mismatch check on install, and no lockfile or
  `.kanon` catalog-source fallback.

Catalog-requiring commands (`kanon search`, `kanon add`, `kanon outdated`,
`kanon why`, `kanon catalog audit`) still resolve a catalog source from
`--catalog-source` or `KANON_CATALOG_SOURCES`; see
[docs/configuration.md](configuration.md#catalog-source).

`kanon_hash` is therefore the single consumer-side drift signal install
and `kanon doctor` consult: it tracks the content integrity of the
alias-keyed `.kanon` source declarations and changes whenever a source
`URL`, `REF`, or `PATH` changes.

A `kanon_hash` mismatch means `.kanon` changed since the lockfile was
written. Plain `kanon install` reconciles the change automatically (see
[Install reconcile model](#install-reconcile-model)); under `--strict-lock`
a non-removal drift is a hard error, and `kanon install --refresh-lock`
(full) or `kanon install --refresh-lock-source <name>` (one source chain)
force a rebuild.

---

## Default-lockfile path

The lockfile path is derived from the `.kanon` path when neither
`--lock-file` nor `KANON_LOCK_FILE` is set. On `kanon install` the `.kanon`
path is the positional `kanonenv_path` argument (default `./.kanon`).

### Derivation rule (spec Section 4.7)

A `.kanon` path of `./alt.kanon` yields `./alt.kanon.lock` as the default
lockfile path. More generally: the default lockfile path is
`<kanon-file-path>.lock`.

When the `.kanon` path is the default (`./.kanon`), the default lockfile
path is `./.kanon.lock`. Operators running parallel installs in the same
directory with different `.kanon` paths therefore get distinct lockfile
paths by default.

Explicit `--lock-file` always wins.

### Precedence chain

The three-tier precedence (highest wins):

1. `--lock-file PATH` CLI flag -- always wins when supplied.
2. `KANON_LOCK_FILE` environment variable -- wins over derivation when
   the CLI flag is absent. An empty-string value is treated as unset
   and falls through to derivation.
3. `<kanon-file-path>.lock` derivation -- the default when neither of
   the above is set.

### Examples

```bash
# Default: .kanon -> .kanon.lock
kanon install

# Non-default kanon file (positional): alt.kanon -> alt.kanon.lock
kanon install ./alt.kanon

# Explicit lock file wins over derivation
kanon install ./alt.kanon --lock-file ./my.lock

# Env var wins over derivation (CLI flag absent)
KANON_LOCK_FILE=/tmp/shared.lock kanon install ./alt.kanon

# CLI flag wins over env var
KANON_LOCK_FILE=/tmp/env.lock kanon install --lock-file ./explicit.lock
```

### Environment variable

**`KANON_LOCK_FILE`** -- Override the lockfile path. When set to a
non-empty value, kanon reads and writes the lockfile at this path instead
of the derived `<kanon-file-path>.lock`. The `--lock-file` CLI flag
takes precedence when both are set. An empty-string value is treated as
unset and falls through to derivation.

---

## Schema migration

### Policy overview (spec Section 5.2)

Every kanon release ships with a single `CURRENT_SCHEMA_VERSION`
constant (`4` in kanon 3.0.0). When `read_lockfile` encounters a lockfile
whose `schema_version` differs from `CURRENT_SCHEMA_VERSION`, it applies
one of three outcomes:

- `schema_version > CURRENT` -- Fatal error: kanon is too old to read
  this lockfile.
- `schema_version < CURRENT` -- Fatal error: schema v4 is a breaking
  major with no automatic upgrade. The lockfile must be regenerated.
- `schema_version == CURRENT` -- Parse directly; no migration applied.

### Forward-incompatible reads

If the lockfile was written by a newer kanon
(`schema_version > CURRENT_SCHEMA_VERSION`), `read_lockfile` raises
`LockfileSchemaError`:

```text
lockfile schema v<N> written by newer kanon; upgrade kanon-cli.
```

This is a fatal error. kanon cannot safely parse a format it has never
seen. There is no fallback and no silent downgrade.

Remediation: upgrade `kanon-cli` to a version that supports schema v`N`,
or rebuild the lockfile by running `kanon install --refresh-lock` with a
supported kanon version.

### Older lockfiles hard-fail (no auto-upgrade)

Schema v4 (kanon 3.0.0, spec Section 13 FLAG-C) is a breaking major:
source entries are now keyed by alias, the per-entry version-constraint
field was renamed to `ref_spec`, and the global `[catalog]` block was
removed. There is **no** silent or automatic upgrade from any older
schema. When `read_lockfile` encounters a v1, v2, or v3 lockfile
(`schema_version < CURRENT_SCHEMA_VERSION`), it raises `LockfileSchemaError`
and fails fast with an actionable message:

```text
ERROR: lockfile schema v<N> is incompatible with this kanon version (schema v4).
  Path: <lockfile-path>
  Schema v4 is a breaking change: source entries are now keyed by alias,
  the per-entry version-constraint field was renamed to 'ref_spec', and the
  global [catalog] block was removed.
  There is no automatic upgrade from schema v<N>.
  Remediation: regenerate the lockfile by running 'kanon add' to refresh the
  alias-keyed declarations, then 'kanon install' to rewrite the lock at schema v4.
```

There is no in-memory migration and no upgrader chain. The only path
forward is to regenerate the lockfile.

### Operator regenerate path

To replace an older (v1/v2/v3) lockfile with a v4 lockfile:

```bash
# Refresh the alias-keyed .kanon declarations, then rewrite the lock at v4
kanon add <entry>[@<spec>] ...
kanon install
```

`kanon install` writes the lock at `CURRENT_SCHEMA_VERSION` on success.
For an explicit full rebuild of an already-v4 lock, use
`kanon install --refresh-lock`.

### Schema changelog (v1 to v4)

- **v1** -- original schema (`[catalog]`, `[[sources]]`, `kanon_hash`).
- **v2** -- added the top-level `marketplace_registered` (bool) and
  `marketplace_dir` (string) fields, recording whether install registered
  a marketplace plugin and which directory it used.
- **v3** -- added the per-source `registered_marketplaces` (list of
  strings) ledger to each `[[sources]]` entry.
- **v4** (kanon 3.0.0) -- the breaking major. Each `[[sources]]` entry is
  re-keyed by `alias` and carries the per-entry fields `alias, name, url,
  ref_spec, resolved_ref, resolved_sha, path`; the per-entry
  version-constraint field was renamed from `revision_spec` to `ref_spec`
  on every source and project entry. The global `[catalog]` block was
  removed: the lock no longer serialises or parses a `[catalog]` inline
  table. v1/v2/v3 lockfiles hard-fail on read (see above).

### Marketplace ownership and pruning

The per-source `registered_marketplaces` ledgers (schema v3+) drive two
related cleanup behaviours. Both draw removal candidates ONLY from the
ledgers -- the marketplace names kanon itself recorded -- so user-managed
or keep-set marketplaces (which were never written to any ledger) are
never unregistered.

**`kanon install` auto-prune.** When install rebuilds the marketplace set,
it computes `OLD` (the union of every source's recorded
`registered_marketplaces` in the existing lockfile) and `NEW` (the union
of the marketplaces attributed to the current sources this run). Any name
in `OLD` but not in `NEW` is an orphan -- a marketplace whose source was
removed from `.kanon`, or whose per-dependency
`KANON_SOURCE_<alias>_MARKETPLACE` flag was turned off -- and is
unregistered from `~/.claude` via `claude plugin marketplace remove`
(idempotent). Disabling a dependency's marketplace flag therefore prunes
exactly what that dependency previously registered. The lockfile is then
rewritten with each source's ledger refreshed to what it registered this
run.

**`kanon clean --orphans`.** Before the normal teardown, this unregisters
the marketplaces of orphaned sources -- `[[sources]]` entries recorded in
`.kanon.lock` whose alias no longer appears in the current `.kanon`
(removed via `kanon remove` but not yet reconciled by `kanon install`). A
marketplace also provided by a still-referenced source is retained
(subtracted from the prune set). Plain `kanon clean` (without `--orphans`)
performs the full teardown unchanged and does not consult the ledgers.

---

## Conflict resolution

`kanon install` is hermetic and does not read a catalog source, so there
is no catalog-source mismatch check (see [Hermetic install](#hermetic-install)).
The conflict conditions below are all detected from the committed `.kanon`
and `.kanon.lock` alone.

### Lockfile-hash drift

When the `kanon_hash` computed from the current `.kanon` file differs
from the value recorded in the lockfile, the behaviour follows the
npm-like model described under [Install reconcile model](#install-reconcile-model):

- **Plain `kanon install` reconciles** (the `npm install` analogue).
  Removed sources (orphans) are pruned, newly-added and changed-spec
  sources are resolved fresh, unchanged sources preserve their locked
  SHA, and the lockfile is rebuilt and written **once at the end on
  success only**. No error is raised for ordinary edits to `.kanon`.

- **`kanon install --strict-lock` errors on the drift** (the `npm ci`
  analogue) and **never mutates the lockfile**. A pure-removal drift
  raises `OrphanedLockEntryError` (naming each orphan); any other drift
  (a newly-added source, or a changed ref spec) raises
  `KanonHashMismatchError`:

```text
ERROR: .kanon has been modified since the lockfile was written.
  Lockfile kanon_hash : <old-hash>
  Current  kanon_hash : <new-hash>
  Remediation: run 'kanon install --refresh-lock' to rebuild the entire
  lockfile, or 'kanon install --refresh-lock-source <name>' to re-resolve
  one source chain while preserving all other lockfile entries.
```

`--strict-lock` is the gate to use in CI when the lockfile must be
treated as authoritative and any drift should fail the pipeline.

### Branch drift

When a source's `ref_spec` is branch-shaped (e.g., `main`) and the
branch's current tip on the remote differs from the `resolved_sha` in
the lockfile, the default behaviour is:

- Reuse the locked SHA. The branch tip change is ignored.
- Emit an info-level notice to stdout per drifted source:

```text
branch drift: <source>: <branch> tip <new-sha> differs from
locked <old-sha>; reusing locked SHA
```

With `--strict-drift`, branch drift is a hard error
(`BranchDriftError`). To accept the new branch tip, run
`kanon install --refresh-lock-source <source>`.

### Unreachable locked SHA

If a `resolved_sha` recorded in the lockfile is no longer reachable on
the remote, `kanon install` exits with `LockfileUnreachableShaError`.
This is a hard error.

### Transitive canonical-URL conflict

When two or more `[[sources.projects]]` entries resolve to the same
canonical URL but pin different commit SHAs, `kanon install` exits with
`CanonicalUrlConflictError`. This check runs both during fresh resolution
and during `LOCKFILE_CONSISTENT` replay.

---

## Install reconcile model

`kanon install` treats `.kanon` and `.kanon.lock` the way `npm` treats
`package.json` and `package-lock.json`.

### Plain `kanon install` -- reconcile (`npm install`)

When `.kanon` is unchanged since the lockfile was written
(`LOCKFILE_CONSISTENT`), plain install replays every locked SHA verbatim
and does not touch the remote or the lockfile.

When `.kanon` has changed (the `kanon_hash` differs), plain install
**reconciles** the lockfile to the new `.kanon`:

- **Prune** sources removed from `.kanon` (orphaned lock entries); one
  `pruned orphaned lock entry: <name>` info-line is emitted per orphan.
- **Resolve fresh** any source that is new, or whose `.kanon` ref
  spec differs from the locked `ref_spec`.
- **Replay** (preserve the locked SHA) every source still present in
  `.kanon` with an unchanged ref spec.
- **Rebuild and write** the lockfile **once at the end, on success
  only**, recording the new `kanon_hash`. If the install fails part-way,
  the old lockfile is left untouched.

Info-line emitted on success:

```text
lockfile reconciled with .kanon (N sources, M projects)
```

This means the common edit-then-install loop -- `kanon add`/`kanon
remove` followed by `kanon install` -- "just works" without any flag,
including the case where one source is removed and another added in the
same edit.

### `kanon install --strict-lock` -- error on drift (`npm ci`)

`--strict-lock` makes the lockfile authoritative. Any drift between
`.kanon` and the lockfile is a hard error and the lockfile is **never**
mutated:

- A pure-removal drift raises `OrphanedLockEntryError` listing each
  orphan.
- Any other drift (addition or changed ref spec) raises
  `KanonHashMismatchError` (see [Lockfile-hash drift](#lockfile-hash-drift)).

Use `--strict-lock` in CI to fail fast when a build's `.kanon` has
drifted from its committed lockfile.

### `kanon install --refresh-lock` -- force rebuild

`--refresh-lock` discards the lockfile and rebuilds it from scratch (see
[Refresh flow](#refresh-flow)).

---

## Refresh flow

### --refresh-lock (full lockfile rebuild)

`kanon install --refresh-lock` discards the existing `.kanon.lock`
entirely, re-resolves every transitive version from scratch, and
overwrites `.kanon.lock` with the new resolved state.

Info-line emitted on success:

```text
lockfile rebuilt from .kanon (N sources, M projects)
```

`kanon install` is hermetic on every path, including `--refresh-lock`: it
re-resolves against the committed `.kanon` source declarations and does
not accept or read a catalog source. There is no catalog-source
requirement and no catalog-source fallback.

Mutually exclusive with `--refresh-lock-source`.

### --refresh-lock-source \<name\> (single-source rebuild)

`kanon install --refresh-lock-source <name>` re-resolves exactly one
top-level source's full chain (the manifest XML at its current ref
and every transitive `<include>` reference) while preserving every other
top-level source's lockfile entries verbatim.

Info-line emitted on success:

```text
lockfile partially rebuilt: source <name>
(M projects refreshed; K projects preserved)
```

The `<name>` argument is resolved in two steps:

1. **Literal source key** -- compared directly to the source aliases
   (the `<alias>` in `KANON_SOURCE_<alias>_*`) discovered in `.kanon`.
2. **Catalog entry name via `derive_source_name`** -- if no literal
   match is found, `<name>` is normalised (lowercase, hyphens replaced
   with underscores) and compared again. This allows passing the
   human-readable catalog entry name (e.g., `My-Tool`) when the source
   alias is the normalised form (`my_tool`).

If neither step matches, `kanon install` exits with `UnknownSourceError`
listing known source names and the `derive_source_name` resolution that
was attempted.

This path is hermetic as well: no catalog source is accepted or read.

**What is modified.** Only the one `[[sources]]` entry for the named
source is rewritten in `.kanon.lock`. All other `[[sources]]` entries are
carried over verbatim. The `kanon_hash` field is updated to the freshly-
computed value over `.kanon`.

Mutually exclusive with `--refresh-lock`.

---

## Revision forms

The `KANON_SOURCE_<alias>_REF` entry in a `.kanon` file (and the
corresponding `ref_spec` field in the lockfile) may be recorded in
several forms. `kanon outdated` recognises and handles all four.

### Supported revision forms

- **PEP 440 version** (e.g., `1.0.0`, `==2.3.1`, `>=1.0.0,<2.0.0`) --
  a bare version or constraint specifier without any `refs/` prefix.
  `kanon outdated` compares the resolved version against available tags
  using PEP 440 ordering to determine the upgrade type.

- **Tag ref** (`refs/tags/X.Y.Z`) -- a fully-qualified tag reference
  written by `kanon add`. `kanon outdated` strips the `refs/tags/`
  prefix and then treats the remainder as a PEP 440 version for
  upgrade-type classification.

- **Branch ref** (`refs/heads/<branch>`) -- a fully-qualified branch
  reference pointing to a branch in the source repository. After
  stripping the prefix, the bare branch name is used for display and
  drift detection.

- **Remote-tracking ref** (`refs/remotes/origin/<branch>`) -- a
  fully-qualified remote-tracking reference. After stripping the
  prefix, the bare branch name is used for display and drift detection.

### Prefix-stripping semantics

When `kanon outdated` reads a `_REF` value that starts with one of the
three recognized git ref prefixes, it strips the prefix before
classifying the bare remainder. The prefixes are checked in the
following order (longest-first to avoid partial matches):

1. `refs/remotes/origin/`
2. `refs/heads/`
3. `refs/tags/`

After stripping, the bare string is classified:

- If the bare string is a valid PEP 440 version, the revision is
  classified as `version` and upgrade-type computation proceeds with
  standard PEP 440 comparison against available tags.
- If the matched prefix was `refs/heads/` or `refs/remotes/origin/`,
  the revision is classified as `branch` regardless of the bare string's
  content.

A `refs/tags/` bare remainder that is not a valid PEP 440 version raises
a hard parse error; `kanon outdated` exits immediately with a non-zero
code and an error message naming the malformed revision.

### Branch-shaped revision display

When a `_REF` value is stored as a fully-qualified branch ref
(`refs/heads/<branch>` or `refs/remotes/origin/<branch>`), `kanon
outdated` applies the following display rules (spec D5):

- The `current`, `latest-matching-spec`, and `latest-available` columns
  all show the **bare branch name** (the portion after the prefix),
  not a SHA truncation.
- The `upgrade-type` column shows `drift` when the locked commit SHA
  differs from the current branch HEAD, or `none` when the locked SHA
  matches the HEAD or no lockfile is present.

### Example `.kanon` entries

```bash
# Tag-shaped ref -- written by `kanon add` when resolving a versioned entry
KANON_SOURCE_foo_REF=refs/tags/1.0.0

# Branch-shaped ref -- written by `kanon add` when targeting a branch
KANON_SOURCE_bar_REF=refs/heads/main
```

Both forms are accepted by `kanon install`, `kanon outdated`, and
`kanon doctor`. The prefix is stripped internally; operators see the
bare version or branch name in all `kanon outdated` output columns.

---

## See also

- [docs/configuration.md](configuration.md) -- all environment variables,
  including `KANON_LOCK_FILE`, `KANON_KANON_FILE`, `KANON_HOME`, and
  `KANON_CATALOG_SOURCES`.
- [docs/architecture.md](architecture.md) -- install engine internals,
  lockfile-to-clone mapping, and the state machine that reads the
  lockfile.
- [docs/exit-codes.md](exit-codes.md) -- canonical exit-code table
  referenced by every `kanon` command.
- [docs/doctor.md](doctor.md) -- `kanon doctor` workspace health checks
  that read and validate the lockfile.
