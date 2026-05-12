# Kanon Lockfile Reference

## Overview

The kanon lockfile (`.kanon.lock`, written alongside the `.kanon` configuration file)
is a TOML file that captures the exact resolved state of every dependency declared in
a `.kanon` file at the moment `kanon install` last ran. It is machine-generated and
should be committed to source control so every subsequent `kanon install` produces
bit-for-bit identical results.

The lockfile schema version is embedded in the file and drives the migration policy.
This document describes schema version 1.

---

## Schema v1 Structure

A schema-v1 lockfile has the following top-level keys, followed by a `[catalog]` block
and zero or more `[[sources]]` entries.

```toml
schema_version = 1
generated_at   = "2026-01-15T12:34:56Z"
generator      = "kanon-cli/1.4.0"
kanon_hash     = "sha256:aabbcc..."    # sha256:<64 hex chars> of the .kanon source triples

[catalog]
source       = "https://example.com/manifest-repo.git@main"
url          = "https://example.com/manifest-repo.git"
revision_spec = "main"
resolved_ref = "refs/heads/main"
resolved_sha = "deadbeef..."          # SHA-1 or SHA-256

[[sources]]
name          = "build-tools"
url           = "https://example.com/build-tools.git"
revision_spec = "main"
resolved_ref  = "refs/heads/main"
resolved_sha  = "aabbccdd..."
path          = "repo-specs/build-tools/meta.xml"

[[sources.includes]]
name         = "ci-helpers"
path_in_repo = "repo-specs/ci/helpers.xml"
url          = "https://example.com/ci-helpers.git"
resolved_sha = "11223344..."

[[sources.includes.includes]]
name         = "shell-utils"
path_in_repo = "repo-specs/shell/utils.xml"
url          = "https://example.com/shell-utils.git"
resolved_sha = "aabbccdd..."

[[sources.projects]]
name          = "my-service"
url           = "https://github.com/example/my-service.git"
canonical_url = "https://github.com/example/my-service"
revision_spec = "==1.2.3"
resolved_ref  = "refs/tags/1.2.3"
resolved_sha  = "deadbeef..."
```

### Top-level fields

| Field           | Type   | Description | State branch that reads it |
|----------------|--------|-------------|---------------------------|
| `schema_version` | int  | Must be `1`. | All -- read first by `read_lockfile`. |
| `generated_at` | string | ISO-8601 UTC timestamp of when the lockfile was written. | Informational; not read by the state machine. |
| `generator`    | string | The `kanon-cli/<version>` string identifying the writer. | Informational; not read by the state machine. |
| `kanon_hash`   | string | `sha256:`-prefixed 71-character digest (`sha256:<64 lowercase hex chars>`) of the `KANON_SOURCE_*` triples declared in the `.kanon` file. | `LOCKFILE_CONSISTENT` / `LOCKFILE_HASH_MISMATCH`: compared to freshly-computed `kanon_hash(.kanon)` by `_classify_install_state`. See `docs/architecture.md`. |

### `[catalog]` block

| Field           | Type   | Description | State branch that reads it |
|----------------|--------|-------------|---------------------------|
| `source`        | string | The `<url>@<ref>` form identifying the catalog source. | `LOCKFILE_CONSISTENT` (fallback only): read by `_resolve_catalog_source` when CLI flag and `KANON_CATALOG_SOURCE` env var are both unset. Also: `LOCKFILE_SOURCE_MISMATCH` -- compared to CLI/env source; mismatch raises `CatalogSourceMismatchError`. See `docs/architecture.md`. |
| `url`           | string | The catalog repository URL (without the `@<ref>` suffix). | Written at lock time; not used by the state machine directly. |
| `revision_spec` | string | The revision spec used to locate the catalog (see Validation Rules). | Written at lock time; not used by the state machine directly. |
| `resolved_ref`  | string | The git ref resolved from `revision_spec`. | Written at lock time; not used by the state machine directly. |
| `resolved_sha`  | string | The exact commit SHA pinned for reproducibility. | Written at lock time; not used by the state machine directly (SHA reachability is checked by the resolver). |

### `[[sources]]` entries

Each `[[sources]]` block represents one source repository declared in the `.kanon` file.

| Field           | Type           | Description | State branch that reads it |
|----------------|----------------|-------------|---------------------------|
| `name`          | string         | Source name (matches the `KANON_SOURCE_<name>_URL` env-var key). | `LOCKFILE_UNREACHABLE`: named in the `LockfileUnreachableShaError` message. |
| `url`           | string         | Source repository URL. | `LOCKFILE_UNREACHABLE`: included as `remote_url` in the `LockfileUnreachableShaError` message. |
| `revision_spec` | string         | The revision spec for this source. | Written at lock time; not read back by the state machine. |
| `resolved_ref`  | string         | The git ref resolved from `revision_spec`. | Written at lock time; not read back by the state machine. |
| `resolved_sha`  | string         | Pinned commit SHA. | `LOCKFILE_CONSISTENT`: used by the resolver to pin the clone at the recorded SHA (ignoring newer tags). `LOCKFILE_UNREACHABLE`: if the resolver cannot verify the SHA, raises `LockfileUnreachableShaError`. |
| `path`          | string         | Path to the XML file in this source repo. | `LOCKFILE_CONSISTENT`: passed to `repo init -m <path>`. |
| `includes`      | list           | Zero or more `[[sources.includes]]` entries (recursive, unbounded depth). | `LOCKFILE_CONSISTENT`: walked transitively by the resolver. |
| `projects`      | list           | Zero or more `[[sources.projects]]` entries. | `LOCKFILE_CONSISTENT`: each project is cloned at `resolved_sha`. |

### `[[sources.includes]]` entries

Include entries are recursive: each entry may have its own `includes` list.

| Field           | Type   | Description | State branch that reads it |
|----------------|--------|-------------|---------------------------|
| `name`          | string | Display name of the included file. | Informational; surfaced in error messages. |
| `path_in_repo`  | string | Repo-relative path to the included XML file. | `LOCKFILE_CONSISTENT`: used to locate the included XML during `repo init`. |
| `url`           | string | URL of the repository providing this include. | `LOCKFILE_CONSISTENT`: used as the source URL for this include's clone. |
| `resolved_sha`  | string | Pinned commit SHA for reproducibility. | `LOCKFILE_CONSISTENT`: pins the include's clone; `LOCKFILE_UNREACHABLE` if the SHA is no longer reachable. |
| `includes`      | list   | Nested includes (may be empty or absent). | `LOCKFILE_CONSISTENT`: walked recursively. |

### `[[sources.projects]]` entries

| Field           | Type   | Description | State branch that reads it |
|----------------|--------|-------------|---------------------------|
| `name`          | string | Project name. | Informational; surfaced in error messages. |
| `url`           | string | Raw project URL (as declared in the catalog XML). | `LOCKFILE_CONSISTENT`: used as the remote for cloning this project. |
| `canonical_url` | string | Canonical form of `url` (see Validation Rules). | Conflict detection (future `LOCKFILE_URL_CONFLICT` state, T5). |
| `revision_spec` | string | Revision spec for this project. | Written at lock time; not read back by the state machine. |
| `resolved_ref`  | string | Resolved git ref. | `LOCKFILE_CONSISTENT`: passed to `repo sync` to check out the project at this ref. |
| `resolved_sha`  | string | Pinned commit SHA. | `LOCKFILE_CONSISTENT`: pins the project clone at this SHA via repo sync. Note: project SHAs are not individually verified by the LOCKFILE_UNREACHABLE check; only top-level source SHAs are checked via _check_sha_reachable(). Project SHA errors surface as repo sync failures. |

---

## Validation Rules

When `read_lockfile` parses a lockfile, it applies the following validation rules.
Any violation raises a specific exception with a message that names the offending
field path and value, and suggests a remediation step.

### Rule 1a: `kanon_hash` must be a `sha256:`-prefixed digest

The top-level `kanon_hash` field must match the pattern `^sha256:[a-f0-9]{64}$`
(71 characters total: the 7-character prefix `sha256:` followed by 64 lowercase hex chars).

- The `sha256:` prefix is required; a bare 64-character hex string is rejected.
- Uppercase hex characters after the prefix are rejected.
- Any length other than 71 total characters is rejected.

**Exception:** `LockfileValidationError` -- message includes the field path
(`kanon_hash`) and the bad value.

**Remediation:** Regenerate the lockfile with `kanon install --refresh-lock` to obtain a correctly
formatted `kanon_hash`.

### Rule 1b: `resolved_sha` must be 40 or 64 lowercase hex digits

Every `resolved_sha` field (in `[catalog]`, in every `[[sources]]` entry, in every
`[[sources.includes]]` entry, and in every `[[sources.projects]]` entry) must match
the pattern `^[a-f0-9]{40}$` (SHA-1) OR `^[a-f0-9]{64}$` (SHA-256).

- Uppercase hex characters are rejected (`A-F` are not accepted).
- Mixed-case values are rejected.
- Any non-hex character is rejected.
- Lengths other than 40 or 64 are rejected.

**Exception:** `LockfileValidationError` -- message includes the field path (e.g.
`sources[0].projects[2].resolved_sha`) and the bad value.

**Remediation:** Regenerate the lockfile with `kanon install --refresh-lock` to obtain a fresh SHA.

### Rule 2: `revision_spec` must satisfy one of three accept rules

A `revision_spec` value is accepted if it satisfies **any one** of:

1. **PEP 440 SpecifierSet** -- parses as a `packaging.specifiers.SpecifierSet`
   (e.g. `==1.0.0`, `~=2.0.0`, `>=1.0,<2.0`). An optional monorepo path prefix
   of the form `subpackage/` may precede the specifier; the prefix is stripped
   before PEP 440 parsing (e.g. `subpackage/==1.0.0` is accepted).

2. **Git ref** -- starts with `refs/` (e.g. `refs/heads/main`,
   `refs/tags/v1.0.0`). No further parsing is performed.

3. **Branch-name charset** -- matches the regex `^[a-zA-Z0-9_./+-]+$`
   (e.g. `main`, `feature-branch`, `release/1.0`).

**Exception:** `LockfileValidationError` -- message includes the field path and the
rejected value, and lists all three accept rules.

**Remediation:** Update the `revision_spec` in your `.kanon` file and re-run
`kanon install --refresh-lock`.

### Rule 3: `canonical_url` must equal `canonicalize_repo_url(url)`

Every `[[sources.projects]]` entry's `canonical_url` field is compared to the result
of applying the URL canonicalisation function to the entry's `url` field. Canonicalisation
(spec Section 4.0) normalises the scheme to `https://`, lowercases the host, strips
user-info, strips a trailing `/`, strips a trailing `.git`, and preserves the port.

**Exception:** `LockfileValidationError` -- message includes both the recorded
`canonical_url` and the computed value so the operator can see the mismatch.

**Remediation:** Regenerate the lockfile with `kanon install --refresh-lock` to update the
`canonical_url` field.

### Rule 4: `path` and `path_in_repo` must not contain NUL, newline, or tab

The `path` field on every `[[sources]]` entry and the `path_in_repo` field on every
`[[sources.includes]]` entry must not contain:
- `\x00` (NUL, U+0000)
- `\n` (newline, U+000A)
- `\t` (tab, U+0009)

**Exception:** `LockfileValidationError` -- message names the bad character by
codepoint (e.g. `U+0000 (NUL)`) and the field path.

**Remediation:** Correct the path value in your `.kanon` file and re-run `kanon install --refresh-lock`.

### Rule 5: `schema_version` -- migration policy

`schema_version` is validated against `CURRENT_SCHEMA_VERSION` (currently `1`).
Three cases are handled:

**Forward-incompatible** (`schema_version > CURRENT_SCHEMA_VERSION`): raises
`LockfileSchemaError` with message:
`"lockfile schema v<N> written by newer kanon; upgrade kanon-cli."`

This is a fatal error; kanon cannot safely parse a format it has never seen.

**Backward-incompatible** (`schema_version < CURRENT_SCHEMA_VERSION`): looks up a
registered upgrader chain from the file's version to `CURRENT_SCHEMA_VERSION`. If
a chain exists, each upgrader is applied in sequence and the upgraded `Lockfile` is
returned. If no chain exists, raises `LockfileSchemaError` with message:
`"no upgrade path from lockfile schema v<N> to v<current>; this is a kanon bug; please report."`

The "kanon bug" framing is intentional: the spec mandates that every released schema
bump ships with an explicit upgrader; a missing upgrader is a packaging defect, not an
operator error.

**Current schema** (`schema_version == CURRENT_SCHEMA_VERSION`): parsed and validated
directly with no migration applied.

**Exception class:** `LockfileSchemaError` (distinct from `LockfileValidationError`)
so callers can dispatch on schema errors separately from field validation errors.

---

## Schema Migration Policy

### Overview

Every kanon release ships with a single `CURRENT_SCHEMA_VERSION` constant (currently
`1`). When `read_lockfile` encounters a lockfile whose `schema_version` differs from
`CURRENT_SCHEMA_VERSION`, it applies one of three outcomes:

| Condition | Outcome |
|-----------|---------|
| `schema_version > CURRENT_SCHEMA_VERSION` | Fatal error -- kanon is too old |
| `schema_version < CURRENT_SCHEMA_VERSION` | Upgrade via registered chain |
| `schema_version == CURRENT_SCHEMA_VERSION` | Parse directly -- no migration |

### Forward-incompatible reads

If the lockfile was written by a newer kanon (i.e. `schema_version > CURRENT_SCHEMA_VERSION`),
`read_lockfile` raises `LockfileSchemaError`:

```
lockfile schema v<N> written by newer kanon; upgrade kanon-cli.
```

There is no fallback; the format is unknown and cannot be parsed safely.

**Remediation:** Upgrade `kanon-cli` to a version that supports schema v`<N>`, or
rebuild the lockfile with a supported kanon by running `kanon install --refresh-lock`.

### Backward-compatible reads (per-version upgrader chain)

If the lockfile was written by an older kanon (i.e. `schema_version < CURRENT_SCHEMA_VERSION`),
kanon walks an upgrader chain: for each step from `N` to `N+1`, a registered upgrader
function transforms the raw TOML dict. If any step has no registered upgrader, the error is:

```
no upgrade path from lockfile schema v<N> to v<current>; this is a kanon bug; please report.
```

Because the spec requires every schema bump to ship with an explicit upgrader, a missing
upgrader is a packaging defect in kanon, not an operator error.

### v1 -> v2 placeholder example (spec Section 5.2)

When schema v2 ships, the migration module will contain one new registry entry:

```python
from kanon_cli.core.lockfile import _register_upgrader

def _upgrade_v1_to_v2(data: dict) -> dict:
    """Upgrade a schema v1 lockfile dict to schema v2."""
    upgraded = dict(data)
    upgraded["schema_version"] = 2
    # Example: v2 adds a required "lock_generated_by" field.
    upgraded.setdefault("lock_generated_by", upgraded.get("generator", "unknown"))
    return upgraded

_register_upgrader(1, 2, _upgrade_v1_to_v2)
```

No other code changes are needed for the migration to function; `_dispatch_migration`
walks the chain automatically.

### Operator rebuild path

Operators who want to rewrite an older lockfile at the current schema can run:

```
kanon install --refresh-lock
```

This discards the existing lockfile and rebuilds it from scratch at `CURRENT_SCHEMA_VERSION`.
It is the canonical path for intentional lockfile regeneration. See `E3-F3-S1-T2` for
the implementation of this flag.

**kanon never silently rewrites lockfiles.** A `read_lockfile` call that applies an
upgrade returns the upgraded dataclass in memory but does NOT write back to disk.
Only `kanon install --refresh-lock` persists changes.

---

## Atomicity Contract

`write_lockfile` implements the atomic write contract from spec Section 4.7.1:

1. A temporary file is created in the same directory as the destination path,
   using a `.tmp.<pid>.<rand>` suffix to prevent collisions between concurrent writers.
2. The serialised TOML bytes are written to the temp file.
3. The temp file's file descriptor is flushed and `fsync`-ed to ensure durability.
4. `os.replace` renames the temp file over the destination path in a single kernel call.
   A reader observing the destination path sees either the prior full content or the new
   full content, never a truncated intermediate state.

---

## Environment Variables

| Variable          | Description |
|------------------|-------------|
| `KANON_LOCK_FILE` | Override the lockfile path. When set, kanon reads and writes the lockfile at this path instead of the default derived from `--kanon-file`. The `--lock-file` CLI flag takes precedence when both are set. **Note:** this environment variable is planned for a future release and is not yet active in the current implementation. |

---

## Worked Example

The following is a complete schema-v1 lockfile matching the structure from spec Section 5.

```toml
schema_version = 1
generated_at   = "2026-01-15T12:34:56Z"
generator      = "kanon-cli/1.4.0"
kanon_hash     = "sha256:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"

[catalog]
source        = "https://github.com/example-org/kanon-catalog.git@main"
url           = "https://github.com/example-org/kanon-catalog.git"
revision_spec = "main"
resolved_ref  = "refs/heads/main"
resolved_sha  = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

[[sources]]
name          = "platform-tools"
url           = "https://github.com/example-org/platform-tools.git"
revision_spec = "main"
resolved_ref  = "refs/heads/main"
resolved_sha  = "1234567890abcdef1234567890abcdef12345678"
path          = "repo-specs/platform-tools/meta.xml"

[[sources.includes]]
name         = "ci-helpers"
path_in_repo = "repo-specs/platform-tools/ci/helpers.xml"
url          = "https://github.com/example-org/platform-tools.git"
resolved_sha = "1234567890abcdef1234567890abcdef12345678"

[[sources.projects]]
name          = "build-service"
url           = "https://github.com/example-org/build-service.git"
canonical_url = "https://github.com/example-org/build-service"
revision_spec = "==2.3.1"
resolved_ref  = "refs/tags/2.3.1"
resolved_sha  = "abcdef1234567890abcdef1234567890abcdef12"
```

In this example:
- `kanon_hash` is the SHA-256 digest of the `.kanon` source triples that produced this lockfile (see below).
- `catalog.resolved_sha` pins the catalog repo at a specific commit.
- `sources[0].resolved_sha` pins the `platform-tools` source at a specific commit.
- `sources[0].projects[0].canonical_url` is the result of canonicalising
  `https://github.com/example-org/build-service.git` (strips the `.git` suffix).

---

## `kanon_hash` -- Lockfile Consistency Hash

### Purpose

The `kanon_hash` field in the lockfile (see top-level fields above) is a deterministic
SHA-256 digest that covers only the `KANON_SOURCE_<name>_{URL,REVISION,PATH}` triples
declared in the `.kanon` file. It changes whenever a source URL, revision, or path
changes, and remains stable across comment edits, blank-line additions, declaration
reordering, and workspace-environment changes. This makes it safe to use as a
cache key and as a freshness check for `kanon install`.

The `kanon_hash` covers ONLY the `.kanon` source triples and is independent of
the `[catalog].source` field. A change to the catalog source does not change
`kanon_hash`; a change to any `KANON_SOURCE_*` triple does.

### Algorithm (spec Section 5.1)

1. Parse the `.kanon` file via `parse_kanonenv`.
2. Extract every `KANON_SOURCE_<name>_{URL,REVISION,PATH}` triple. Discard
   comments, blank lines, and all non-`KANON_SOURCE_*` keys (specifically
   `GITBASE`, `CLAUDE_MARKETPLACES_DIR`, and `KANON_MARKETPLACE_INSTALL`).
3. Sort triples by source name (lexicographic, case-sensitive); within a
   source, `URL` precedes `REVISION` precedes `PATH`.
4. Serialise as bytes `name\turl\trevision\tpath\n` per source. If any of
   `name`, `url`, `revision`, or `path` contains a literal tab (`\t`, U+0009),
   NUL byte (`\x00`, U+0000), or newline (`\n`, U+000A), a `KanonHashError`
   is raised naming the source, the field, and the offending codepoint. This
   is a hard error -- there is no sanitisation or fallback.
5. SHA-256 the serialised bytes.
6. Return `f"sha256:{digest.hexdigest()}"` -- 71 characters total (7-char
   prefix `sha256:` plus 64 lowercase hex characters).

### Properties

| Property | Effect on hash |
|----------|---------------|
| Re-order source blocks | No change |
| Add, remove, or change comments | No change |
| Add or remove blank lines | No change |
| Change any `REVISION` value | Hash changes |
| Change any `URL` value | Hash changes |
| Change any `PATH` value | Hash changes |
| Change a source name | Hash changes |
| Change `GITBASE` | No change |
| Change `CLAUDE_MARKETPLACES_DIR` | No change |
| Change `KANON_MARKETPLACE_INSTALL` | No change |
| URL contains literal tab (`\t`) | Raises `KanonHashError` |
| PATH contains literal newline (`\n`) | Raises `KanonHashError` |
| REVISION contains literal NUL (`\x00`) | Raises `KanonHashError` |

### Relationship to `[catalog].source`

`kanon_hash` and `[catalog].source` are independent checks:

- `kanon_hash` tracks changes to the `.kanon` source declarations (the set
  of repositories kanon resolves). It does NOT track the catalog used to
  resolve version specs.
- `[catalog].source` records the catalog repository URL and ref used during
  `kanon install --refresh-lock`. It does NOT track source declaration changes.

A lockfile is stale if either `kanon_hash` differs from the current `.kanon`
triples OR the resolved catalog SHA differs from the pinned value. Both are
checked independently during `kanon install`.

### Implementation

`kanon_hash` is implemented in `src/kanon_cli/core/kanon_hash.py`:

```python
from pathlib import Path
from kanon_cli.core.kanon_hash import kanon_hash, KanonHashError

digest = kanon_hash(Path(".kanon"))  # returns "sha256:<64 hex chars>"
```

The function is pure: given identical `.kanon` content it returns identical
output. It does not touch the filesystem outside reading the `kanon_path`
argument and makes no network calls.
