# Kanon Lockfile Reference

## Overview

The kanon lockfile (`KANON_LOCK_FILE`, default derived from `--kanon-file`) is a TOML
file that captures the exact resolved state of every dependency declared in a `.kanon`
file at the moment `kanon lock` was last run. It is machine-generated and should be
committed to source control so every subsequent `kanon install` produces bit-for-bit
identical results.

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
kanon_hash     = "aabbcc..."          # SHA-1 or SHA-256 of the .kanon file

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

| Field           | Type   | Description |
|----------------|--------|-------------|
| `schema_version` | int  | Must be `1`. |
| `generated_at` | string | ISO-8601 UTC timestamp of when the lockfile was written. |
| `generator`    | string | The `kanon-cli/<version>` string identifying the writer. |
| `kanon_hash`   | string | SHA-1 or SHA-256 hex digest of the `.kanon` file that produced this lockfile. |

### `[catalog]` block

| Field           | Type   | Description |
|----------------|--------|-------------|
| `source`        | string | The `<url>@<ref>` form identifying the catalog source. |
| `url`           | string | The catalog repository URL (without the `@<ref>` suffix). |
| `revision_spec` | string | The revision spec used to locate the catalog (see Validation Rules). |
| `resolved_ref`  | string | The git ref resolved from `revision_spec`. |
| `resolved_sha`  | string | The exact commit SHA pinned for reproducibility. |

### `[[sources]]` entries

Each `[[sources]]` block represents one source repository declared in the `.kanon` file.

| Field           | Type           | Description |
|----------------|----------------|-------------|
| `name`          | string         | Source name (matches the `KANON_SOURCE_<name>_URL` env-var key). |
| `url`           | string         | Source repository URL. |
| `revision_spec` | string         | The revision spec for this source. |
| `resolved_ref`  | string         | The git ref resolved from `revision_spec`. |
| `resolved_sha`  | string         | Pinned commit SHA. |
| `path`          | string         | Path to the XML file in this source repo. |
| `includes`      | list           | Zero or more `[[sources.includes]]` entries (recursive, unbounded depth). |
| `projects`      | list           | Zero or more `[[sources.projects]]` entries. |

### `[[sources.includes]]` entries

Include entries are recursive: each entry may have its own `includes` list.

| Field           | Type   | Description |
|----------------|--------|-------------|
| `name`          | string | Display name of the included file. |
| `path_in_repo`  | string | Repo-relative path to the included XML file. |
| `url`           | string | URL of the repository providing this include. |
| `resolved_sha`  | string | Pinned commit SHA for reproducibility. |
| `includes`      | list   | Nested includes (may be empty or absent). |

### `[[sources.projects]]` entries

| Field           | Type   | Description |
|----------------|--------|-------------|
| `name`          | string | Project name. |
| `url`           | string | Raw project URL (as declared in the catalog XML). |
| `canonical_url` | string | Canonical form of `url` (see Validation Rules). |
| `revision_spec` | string | Revision spec for this project. |
| `resolved_ref`  | string | Resolved git ref. |
| `resolved_sha`  | string | Pinned commit SHA. |

---

## Validation Rules

When `read_lockfile` parses a lockfile, it applies the following validation rules.
Any violation raises a specific exception with a message that names the offending
field path and value, and suggests a remediation step.

### Rule 1: `resolved_sha` must be 40 or 64 lowercase hex digits

Every `resolved_sha` field (at the top level as `kanon_hash`, in `[catalog]`, in every
`[[sources]]` entry, in every `[[sources.includes]]` entry, and in every
`[[sources.projects]]` entry) must match the pattern `^[a-f0-9]{40}$` (SHA-1) OR
`^[a-f0-9]{64}$` (SHA-256).

- Uppercase hex characters are rejected (`A-F` are not accepted).
- Mixed-case values are rejected.
- Any non-hex character is rejected.
- Lengths other than 40 or 64 are rejected.

**Exception:** `LockfileValidationError` -- message includes the field path (e.g.
`sources[0].projects[2].resolved_sha`) and the bad value.

**Remediation:** Regenerate the lockfile with `kanon lock` to obtain a fresh SHA.

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
`kanon lock`.

### Rule 3: `canonical_url` must equal `canonicalize_repo_url(url)`

Every `[[sources.projects]]` entry's `canonical_url` field is compared to the result
of applying the URL canonicalisation function to the entry's `url` field. Canonicalisation
(spec Section 4.0) normalises the scheme to `https://`, lowercases the host, strips
user-info, strips a trailing `/`, strips a trailing `.git`, and preserves the port.

**Exception:** `LockfileValidationError` -- message includes both the recorded
`canonical_url` and the computed value so the operator can see the mismatch.

**Remediation:** Regenerate the lockfile with `kanon lock` to update the
`canonical_url` field.

### Rule 4: `path` and `path_in_repo` must not contain NUL, newline, or tab

The `path` field on every `[[sources]]` entry and the `path_in_repo` field on every
`[[sources.includes]]` entry must not contain:
- `\x00` (NUL, U+0000)
- `\n` (newline, U+000A)
- `\t` (tab, U+0009)

**Exception:** `LockfileValidationError` -- message names the bad character by
codepoint (e.g. `U+0000 (NUL)`) and the field path.

**Remediation:** Correct the path value in your `.kanon` file and re-run `kanon lock`.

### Rule 5: `schema_version` must be 1

Any `schema_version` value other than `1` raises `LockfileSchemaError` (a distinct
exception class from `LockfileValidationError`). This allows the T2 migration policy
to dispatch on the schema version and apply the appropriate upgrade path.

**Exception:** `LockfileSchemaError` with message
`"lockfile schema v<N> not supported by this kanon version"`.

**Remediation:** Upgrade `kanon-cli` to a version that supports the lockfile's schema
version, or downgrade the lockfile by re-running `kanon lock` with a supported version.

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
| `KANON_LOCK_FILE` | Override the lockfile path. When set, kanon reads and writes the lockfile at this path instead of the default derived from `--kanon-file`. The `--lock-file` CLI flag takes precedence when both are set. |

---

## Worked Example

The following is a complete schema-v1 lockfile matching the structure from spec Section 5.

```toml
schema_version = 1
generated_at   = "2026-01-15T12:34:56Z"
generator      = "kanon-cli/1.4.0"
kanon_hash     = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"

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
- `kanon_hash` is the SHA-1 of the `.kanon` file that produced this lockfile.
- `catalog.resolved_sha` pins the catalog repo at a specific commit.
- `sources[0].resolved_sha` pins the `platform-tools` source at a specific commit.
- `sources[0].projects[0].canonical_url` is the result of canonicalising
  `https://github.com/example-org/build-service.git` (strips the `.git` suffix).
