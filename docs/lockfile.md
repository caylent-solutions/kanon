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

- The catalog source URL and revision used during resolution.
- The SHA-256 hash of the `.kanon` source triples (`kanon_hash`).
- The exact git ref and commit SHA for every source and transitive
  dependency in the dependency tree.

The lockfile schema version is embedded in the file and drives the
migration policy. See [Schema migration](#schema-migration).
This document describes schema version 1.

**Default lockfile path.** When `--kanon-file ./alt.kanon` is passed
to `kanon install`, the default lockfile path is `./alt.kanon.lock`
unless `--lock-file` or `KANON_LOCK_FILE` overrides it. See
[Default-lockfile path](#default-lockfile-path).

---

## Format reference

Schema version 1 uses TOML with four sections: top-level scalar fields,
a `[catalog]` block, and zero or more `[[sources]]` table-arrays each
of which may contain `[[sources.includes]]` and `[[sources.projects]]`
sub-tables.

### TOML schema

```toml
schema_version = 1
generated_at   = "2026-05-11T13:42:00Z"
generator      = "kanon-cli/1.4.0"
kanon_hash     = "sha256:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"

[catalog]
source        = "https://example.com/org/manifest-repo.git@==2.10.0"
url           = "https://example.com/org/manifest-repo.git"
revision_spec = "==2.10.0"
resolved_ref  = "refs/tags/2.10.0"
resolved_sha  = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

[[sources]]
name          = "package_a"
url           = "https://example.com/org/manifest-repo.git"
revision_spec = "==2.10.0"
resolved_ref  = "refs/tags/2.10.0"
resolved_sha  = "abc1234567890abcdef1234567890abcdef12345"
path          = "repo-specs/common/package-a/package-a-marketplace.xml"

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
  revision_spec = ">=1.0.0,<2.0.0"
  resolved_ref  = "refs/tags/1.4.2"
  resolved_sha  = "def4567890abcdef1234567890abcdef12345678"
```

### Top-level fields

**`schema_version`** (int) -- Must be `1`. Read first by `read_lockfile`
on every invocation path.

**`generated_at`** (string) -- ISO-8601 UTC timestamp when the lockfile
was written. Informational; not read by the state machine.

**`generator`** (string) -- `kanon-cli/<version>` string identifying the
writer. Informational; not read by the state machine.

**`kanon_hash`** (string) -- `sha256:`-prefixed 71-character digest
(`sha256:<64 lowercase hex chars>`) of the `KANON_SOURCE_*` triples
declared in the `.kanon` file. Pattern: `^sha256:[a-f0-9]{64}$`. Used
by `_classify_install_state` to detect `.kanon` drift. See
[kanon_hash](#kanon_hash).

### [catalog] block

**`source`** (string) -- `<url>@<ref>` form identifying the catalog
source. Used as a fallback when CLI flag and `KANON_CATALOG_SOURCE` are
both unset (`LOCKFILE_CONSISTENT` state). Also compared to the CLI/env
source when one is supplied; a mismatch raises `CatalogSourceMismatchError`.

**`url`** (string) -- Catalog repository URL without the `@<ref>` suffix.
Written at lock time; not used by the state machine directly.

**`revision_spec`** (string) -- Revision spec used to locate the catalog.
Written at lock time; not used by the state machine directly.

**`resolved_ref`** (string) -- Git ref resolved from `revision_spec`.
Written at lock time; not used by the state machine directly.

**`resolved_sha`** (string) -- Exact commit SHA pinned for
reproducibility. Must be 40 or 64 lowercase hex digits.

### [[sources]] entries

Each `[[sources]]` block represents one top-level source repository
declared in the `.kanon` file.

**`name`** (string) -- Source name matching the `KANON_SOURCE_<name>_*`
env-var key.

**`url`** (string) -- Source repository URL.

**`revision_spec`** (string) -- Revision spec for this source. Written
at lock time.

**`resolved_ref`** (string) -- Git ref resolved from `revision_spec`.
Written at lock time.

**`resolved_sha`** (string) -- Pinned commit SHA. Used to pin the clone
during `LOCKFILE_CONSISTENT` replay and to check SHA reachability in the
`LOCKFILE_UNREACHABLE` branch.

**`path`** (string) -- Path to the XML manifest file in this source repo.
Must not contain tab (`\t`), NUL (`\x00`), or newline (`\n`).

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

**`revision_spec`** (string) -- Revision spec for this project. Written
at lock time.

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
`[catalog]`, `[[sources]]`, `[[sources.includes]]`, and
`[[sources.projects]]` must match `^[a-f0-9]{40}$` (SHA-1) or
`^[a-f0-9]{64}$` (SHA-256). Uppercase hex is rejected.
Exception: `LockfileValidationError`. Remediation:
`kanon install --refresh-lock`.

**Rule 3: `revision_spec` format.** Accepted if it satisfies any one
of: (a) a valid PEP 440 `SpecifierSet` with optional monorepo path
prefix (e.g., `subpackage/==1.0.0`); (b) starts with `refs/`; or
(c) matches `^[a-zA-Z0-9_./+-]+$`.
Exception: `LockfileValidationError`.

**Rule 4: `canonical_url` consistency.** Every `[[sources.projects]]`
entry's `canonical_url` must equal `canonicalize_repo_url(url)`.
Exception: `LockfileValidationError`.

**Rule 5: path fields.** The `path` field on every `[[sources]]` entry
and the `path_in_repo` field on every `[[sources.includes]]` entry must
not contain `\x00` (NUL), `\n` (newline), or `\t` (tab).
Exception: `LockfileValidationError`.

---

## kanon_hash

`kanon_hash` is a deterministic SHA-256 digest stored in the lockfile
that covers only the `KANON_SOURCE_<name>_{URL,REVISION,PATH}` triples
declared in the `.kanon` file. It changes whenever a source URL,
revision, or path changes, and remains stable across all other edits.
`kanon install` and `kanon doctor` compare the `.kanon` file's current
hash to the lockfile's `kanon_hash` to detect consumer-side drift.

### Algorithm (spec Section 5.1)

1. Parse the `.kanon` file via `parse_kanonenv`.
2. Extract every `KANON_SOURCE_<name>_{URL,REVISION,PATH}` triple.
   Discard comments, blank lines, and all non-`KANON_SOURCE_*` keys
   (`GITBASE`, `CLAUDE_MARKETPLACES_DIR`, `KANON_MARKETPLACE_INSTALL`).
3. Sort triples by source name (lexicographic, case-sensitive). Within
   a source, `URL` precedes `REVISION` precedes `PATH`.
4. Serialize as bytes `name\turl\trevision\tpath\n` per source.
   If any of `name`, `url`, `revision`, or `path` contains a literal
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
- Changing `GITBASE`.
- Changing `CLAUDE_MARKETPLACES_DIR`.
- Changing `KANON_MARKETPLACE_INSTALL`.

### Hash-differs cases (hash DOES change)

The following changes to `.kanon` cause the hash to change, making the
existing lockfile stale:

- Changing any `REVISION` value for any source.
- Changing any `URL` value for any source.
- Changing any `PATH` value for any source.
- Changing a source name (the `<name>` token in `KANON_SOURCE_<name>_*`).
- Adding or removing a source.

### Tab-in-path rejection

If `url`, `revision`, or `path` for any source contains a literal tab
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

## [catalog].source vs kanon_hash

These two lockfile fields serve different consistency checks and are
independent of each other.

**`kanon_hash`** tracks content integrity of the `.kanon` source
declarations -- the set of repositories kanon resolves. It changes when
any `KANON_SOURCE_*` triple changes. It does NOT change when the catalog
source changes.

**`[catalog].source`** tracks provenance of the catalog repository used
to resolve version specs during `kanon install`. It changes only when
`--refresh-lock` is run with a different `--catalog-source` or
`KANON_CATALOG_SOURCE`. It does NOT change when source triples change.

`kanon_hash` detects consumer-side drift: the operator changed which
sources they declare in `.kanon`. `[catalog].source` detects
catalog-source switches: the operator changed which manifest repo they
point at. Both checks fire independently on every `kanon install` run.

- A `kanon_hash` mismatch means `.kanon` changed since the lockfile was
  written. Remediation: `kanon install --refresh-lock` (full) or
  `kanon install --refresh-lock-source <name>` (one source chain).
- A `[catalog].source` mismatch means the CLI or `KANON_CATALOG_SOURCE`
  env var points at a different catalog than the one recorded in the
  lockfile. This is a hard error (`CatalogSourceMismatchError`).
  Remediation: run `kanon install --refresh-lock` to rebuild the lockfile
  against the new catalog, or unset the override to reuse the lockfile's
  catalog source.

---

## Default-lockfile path

The lockfile path is derived from `--kanon-file` when neither
`--lock-file` nor `KANON_LOCK_FILE` is set.

### Derivation rule (spec Section 4.7)

`--kanon-file ./alt.kanon` yields `./alt.kanon.lock` as the default
lockfile path. More generally: the default lockfile path is
`<kanon-file-path>.lock`.

When `--kanon-file` is the default (`./.kanon`), the default lockfile
path is `./.kanon.lock`. Operators running parallel installs in the same
directory with different `--kanon-file` values therefore get distinct
lockfile paths by default.

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

# Non-default kanon file: alt.kanon -> alt.kanon.lock
kanon install --kanon-file ./alt.kanon

# Explicit lock file wins over derivation
kanon install --kanon-file ./alt.kanon --lock-file ./my.lock

# Env var wins over derivation (CLI flag absent)
KANON_LOCK_FILE=/tmp/shared.lock kanon install --kanon-file ./alt.kanon

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
constant (currently `1`). When `read_lockfile` encounters a lockfile
whose `schema_version` differs from `CURRENT_SCHEMA_VERSION`, it applies
one of three outcomes:

- `schema_version > CURRENT` -- Fatal error: kanon is too old to read
  this lockfile.
- `schema_version < CURRENT` -- Forward-only upgrade via the registered
  upgrader chain.
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

### Backward-compatible reads (forward-only migration)

If the lockfile was written by an older kanon
(`schema_version < CURRENT_SCHEMA_VERSION`), kanon walks a registered
upgrader chain. Each step applies one registered upgrader function to
transform the raw TOML dict from version N to version N+1. If any step
has no registered upgrader, the error is:

```text
no upgrade path from lockfile schema v<N> to v<current>;
this is a kanon bug; please report.
```

Because every schema bump must ship with an explicit upgrader, a missing
upgrader is a packaging defect in kanon, not an operator error.

### No silent rewrites

`read_lockfile` applies migration in memory and returns the upgraded
dataclass. It does NOT write back to disk. Only `kanon install
--refresh-lock` persists changes to disk, and only when the operator
explicitly requests it.

### Operator rebuild path

To rewrite an older lockfile at the current schema version:

```bash
kanon install --refresh-lock
```

This discards the existing lockfile and rebuilds it from scratch at
`CURRENT_SCHEMA_VERSION`. The `.kanon` file is never modified.

### v1 to v2 migration (placeholder)

Schema v2 has not yet been defined. When it ships, this section will
document the exact diff between schema v1 and v2 and the upgrader logic
that kanon applies automatically when it encounters a v1 lockfile at
runtime.

**Placeholder diff (illustrative only -- not yet finalised):**

```toml
# v1 lockfile fragment
schema_version = 1

# v2 lockfile fragment (hypothetical additions shown with + prefix)
schema_version = 2
# + audit_trail = "sha256:<hash>"   (new field tracking install history)
```

When the v2 upgrader runs, it:

1. Sets `schema_version = 2`.
2. Populates any new required fields with their migration-default values.
3. Returns the upgraded dataclass in memory without writing to disk.

The operator must then run `kanon install --refresh-lock` to persist the
upgraded lockfile on disk.

---

## Conflict resolution

### Lockfile-vs-CLI catalog-source mismatch

When `kanon install` is invoked with a `--catalog-source` CLI flag or
`KANON_CATALOG_SOURCE` env var that differs from the `[catalog].source`
value recorded in the lockfile, `kanon install` exits immediately with
`CatalogSourceMismatchError`:

```text
ERROR: Lockfile catalog source mismatch.
  Lockfile records: <lockfile-source>
  CLI/env supplies:  <cli-source>
  Remediation: run 'kanon install --refresh-lock' to rebuild the
  lockfile against the new catalog source.
```

This is a hard error. There is no silent override and no fallback to the
lockfile value when a CLI/env source is explicitly supplied.

### Lockfile-hash drift

When the `kanon_hash` computed from the current `.kanon` file differs
from the value recorded in the lockfile, `kanon install` exits with a
hard error:

```text
ERROR: .kanon has changed since the lockfile was written.
  Recorded kanon_hash: <old-hash>
  Current kanon_hash:  <new-hash>
  Remediation: run 'kanon install --refresh-lock' to rebuild the
  full lockfile, or 'kanon install --refresh-lock-source <name>'
  to refresh one source's chain.
```

`kanon install` never silently re-resolves when the lockfile is present;
explicit operator action is required.

### Branch drift

When a source's `revision_spec` is branch-shaped (e.g., `main`) and the
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

## Refresh flow

### --refresh-lock (full lockfile rebuild)

`kanon install --refresh-lock` discards the existing `.kanon.lock`
entirely, re-resolves every transitive version from scratch, and
overwrites `.kanon.lock` with the new resolved state.

Info-line emitted on success:

```text
lockfile rebuilt from .kanon (N sources, M projects)
```

**Catalog source requirement.** The lockfile fallback for the catalog
source is disabled on the `--refresh-lock` path. A catalog source must
be supplied via `--catalog-source` or `KANON_CATALOG_SOURCE`. If neither
is set, kanon exits with:

```text
ERROR: install requires a catalog source.
--refresh-lock requires a CLI or env-var catalog source; the
lockfile fallback is disabled on this path.
```

This constraint exists because the operator is explicitly rebuilding the
lockfile; silently reusing the stale catalog source stored in the old
lockfile would defeat the purpose of the rebuild.

Mutually exclusive with `--refresh-lock-source`.

### --refresh-lock-source \<name\> (single-source rebuild)

`kanon install --refresh-lock-source <name>` re-resolves exactly one
top-level source's full chain (the manifest XML at its current revision
and every transitive `<include>` reference) while preserving every other
top-level source's lockfile entries verbatim.

Info-line emitted on success:

```text
lockfile partially rebuilt: source <name>
(M projects refreshed; K projects preserved)
```

The `<name>` argument is resolved in two steps:

1. **Literal source key** -- compared directly to the
   `KANON_SOURCE_<name>_*` keys discovered in `.kanon`.
2. **Catalog entry name via `derive_source_name`** -- if no literal
   match is found, `<name>` is normalised (lowercase, hyphens replaced
   with underscores) and compared again. This allows passing the
   human-readable catalog entry name (e.g., `My-Tool`) when the source
   key is the normalised form (`my_tool`).

If neither step matches, `kanon install` exits with `UnknownSourceError`
listing known source names and the `derive_source_name` resolution that
was attempted.

**Catalog source requirement.** The lockfile fallback for the catalog
source is disabled on this path. You must supply a catalog source via
`--catalog-source` or `KANON_CATALOG_SOURCE`. The same error message as
`--refresh-lock` applies.

**What is modified.** Only the one `[[sources]]` entry for the named
source is rewritten in `.kanon.lock`. All other `[[sources]]` entries are
carried over verbatim. The `kanon_hash` field is updated to the freshly-
computed value over `.kanon`. The `[catalog]` block is preserved
unchanged.

Mutually exclusive with `--refresh-lock`.

---

## See also

- [docs/configuration.md](configuration.md) -- all environment variables,
  including `KANON_LOCK_FILE`, `KANON_KANON_FILE`, and
  `KANON_CATALOG_SOURCE`.
- [docs/architecture.md](architecture.md) -- install engine internals,
  lockfile-to-clone mapping, and the state machine that reads the
  lockfile.
- [docs/exit-codes.md](exit-codes.md) -- canonical exit-code table
  referenced by every `kanon` command.
- [docs/doctor.md](doctor.md) -- `kanon doctor` workspace health checks
  that read and validate the lockfile.
