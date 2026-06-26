# kanon validate

Validate manifest XML files, catalog metadata, and lockfile consistency
without network access.

## Synopsis

```bash
kanon [--no-color] validate <target>
```

### Targets

```bash
kanon validate xml         [--repo-root <path>]
kanon validate marketplace [--repo-root <path>]
kanon validate metadata    [--repo-root <path>] [--format {text,json}]
kanon validate lockfile    [<kanonenv_path>] [--lock-file <path>]
```

## Description

`kanon validate` groups local validation commands that operate entirely without
network access. The `xml`, `marketplace`, and `metadata` targets validate a
manifest repository (catalog-author side); the `lockfile` target validates a
consumer project's `.kanon` / `.kanon.lock` pair. Each sub-subcommand targets a
different aspect.

## Sub-subcommands

### `kanon validate xml`

Validate all `*.xml` manifest files under `repo-specs/` for well-formedness,
required attributes, and include chain integrity.

**Checks:**

- XML is well-formed (parseable by defusedxml).
- `<project>` elements have required `name`, `path`, `remote`, and `revision`
  attributes.
- `<remote>` elements have required `name` and `fetch` attributes.
- `<include name="...">` attributes point to files that exist on disk.

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0` | All XML files are valid. |
| `1` | One or more validation errors found. |

**Options:**

| Option | Description |
|--------|-------------|
| `--repo-root <path>` | Repository root directory. Default: auto-detect via `git rev-parse --show-toplevel`. |

**Example:**

```bash
kanon validate xml
kanon validate xml --repo-root /path/to/repo
```

---

### `kanon validate marketplace`

Validate all `*-marketplace.xml` files under `repo-specs/` for marketplace
manifest correctness.

**Checks:**

- `<linkfile dest="...">` attributes use the `${CLAUDE_MARKETPLACES_DIR}/` prefix
  and are not absolute paths.
- Include chains are intact (all `<include name="...">` files exist).
- Project path values (`<project path="...">`) are unique across all marketplace
  files.
- Revision attributes (`<project revision="...">`) use one of the allowed
  pinnable formats: an exact deep-path tag `refs/tags/<path>/<pep440>`, a
  branch ref `refs/heads/<name>`, or a 40-hex commit SHA. The wildcard `*`,
  a bare branch name (e.g. `main` without the `refs/heads/` prefix), and
  version-range constraints (`>=X,<Y`, `~=`) are rejected. On install a tag
  or branch revision resolves to a content SHA pinned in `.kanon.lock`
  (`[[sources.content_pins]]`), so a branch revision does not pin a moving
  target.

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0` | All marketplace XML files are valid. |
| `1` | One or more validation errors found, or no `*-marketplace.xml` files found. |

**Options:**

| Option | Description |
|--------|-------------|
| `--repo-root <path>` | Repository root directory. Default: auto-detect via `git rev-parse --show-toplevel`. |

**Example:**

```bash
kanon validate marketplace
kanon validate marketplace --repo-root /path/to/repo
```

---

### `kanon validate metadata`

Check every catalog entry manifest (any `repo-specs/**/*.xml` file with a
`<catalog-metadata>` block) for in-repo catalog soft-spot violations (spec
Section 3.5 rules 1, 2, 3) without network access.

No git operations are performed. No `git ls-remote` calls. No cloning.

**Checks:**

- **Soft-spot 1 (metadata):** Required fields (`name`, `display-name`,
  `description`, `version`) are present and non-empty. No duplicate child
  elements within a `<catalog-metadata>` block. Exactly one `<catalog-metadata>`
  block per file. Missing recommended fields (`type`, `owner-name`, `owner-email`,
  `keywords`) produce WARN findings.
- **Soft-spot 2 (source-name derivation):** Entry name in `<catalog-metadata><name>`
  normalises cleanly via `derive_source_name` (WARN S001 when it differs) and uses
  only `[a-zA-Z0-9_-]` characters (WARN S002 for out-of-charset).
- **Soft-spot 3 (entry-name uniqueness):** No two `*-marketplace.xml` files share
  the same `<catalog-metadata><name>` value (ERROR U001 on collision).

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0` | No ERROR-level findings. WARN-level findings do not affect the exit code. |
| `1` | One or more ERROR-level findings produced, or a fatal error (missing `--repo-root` directory). |

**Options:**

| Option | Description |
|--------|-------------|
| `--repo-root <path>` | Repository root directory. Default: auto-detect via `git rev-parse --show-toplevel`. |
| `--format {text,json}` | Output format. Default: `text`. |

**Output formats:**

`text` (default): one finding per line with `ERROR:`, `WARN:`, or `INFO:` prefix:

```text
ERROR: [M001] /path/repo-specs/tool-marketplace.xml: required <catalog-metadata> field <name> is missing or contains only whitespace.
WARN: [S001] /path/repo-specs/tool-marketplace.xml: entry name 'Foo-Bar' normalises to 'foo_bar' via derive_source_name.
ERROR: [U001] Entry name 'my-tool' is declared in 2 files: /path/a.xml, /path/b.xml.
```

`json`: a single JSON object `{"findings": [...]}` written to stdout:

```json
{
  "findings": [
    {
      "kind": "error",
      "code": "M001",
      "message": "...",
      "remediation": ""
    }
  ]
}
```

An empty audit produces `{"findings": []}`.

**What this command does NOT check:**

- Soft-spot 4 (`<remote>` resolvability via `git ls-remote`).
- Soft-spot 5 (PEP 440 tag-name compliance via `git ls-remote --tags`).

Use `kanon catalog audit` for those checks.

**Note on soft-spot 5 and `<project>`-referenced tags:**

`kanon catalog audit --check tag-format` covers ALL tags in the manifest repo,
including tags referenced by `<project revision="..."/>` elements. Spec section 0.4
describes a check that warns on every `<project>` tag whose last path component is
not a valid PEP 440 version; this is satisfied by the existing `--check tag-format`
implementation (soft-spot rule 5, spec section 3.5) because the manifest repo's
`git ls-remote --tags` output already includes those tags. No separate
`--check project-tag-format` surface exists or is needed.

Resolution recorded: `(a) R3 == R89 / soft-spot 5; no new check required.`

**Example:**

```bash
# Check the current directory (must contain repo-specs/)
kanon validate metadata

# Check an explicit path
kanon validate metadata --repo-root /path/to/manifest-repo

# Output findings as JSON
kanon validate metadata --format json

# Validate before pushing changes to a manifest repo
kanon validate metadata --repo-root . && echo "No errors -- safe to push"
```

---

### `kanon validate lockfile`

Check that a consumer project's `.kanon` declarations agree with its
`.kanon.lock` entries, without network access. This is the same consistency
check `kanon install` runs implicitly before it resolves (spec Section 4.5 /
FR-24), exposed as a standalone command for CI and pre-commit use. The same
drift this command flags now also makes the default `kanon install` fail
fast (exit 1) before resolving, without mutating the lock; reconcile it with
`kanon install --reconcile` or rebuild with `kanon install --refresh-lock`.

**Checks:**

- **Alias uniqueness:** every source alias declared in `.kanon` (the
  `<alias>` in `KANON_SOURCE_<alias>_*`) is unique.
- **Alias-set parity:** the set of aliases in `.kanon.lock` equals the set of
  aliases declared in `.kanon`. An alias present in only one file is reported
  (added in `.kanon` but missing from the lock, or orphaned in the lock but
  removed from `.kanon`).
- **Ref-spec parity:** each `.kanon.lock` entry's `ref_spec` matches the
  revision declared for that alias in `.kanon`.

No git operations are performed. No `git ls-remote` calls. No cloning.

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0` | `.kanon` and `.kanon.lock` are consistent. |
| Non-zero | A drift was found (duplicate alias, alias-set mismatch, or ref-spec mismatch); an actionable message names the offending alias(es) and the remediation (`kanon install --reconcile`, or `kanon install --refresh-lock` to rebuild). |

**Arguments and options:**

| Argument / Option | Description |
|-------------------|-------------|
| `<kanonenv_path>` (positional) | Path to the `.kanon` file. Default: auto-discover from the current directory. |
| `--lock-file <path>` | Path to the lock file. Default: `<kanon-file>.lock` derived from the `.kanon` path. The `KANON_LOCK_FILE` environment variable is consulted when this flag is absent; the CLI flag takes precedence when both are set. |

**Example:**

```bash
# Validate the auto-discovered .kanon / .kanon.lock pair
kanon validate lockfile

# Explicit .kanon path
kanon validate lockfile .kanon

# Explicit lock-file path
kanon validate lockfile --lock-file /path/to/.kanon.lock
```

See [docs/lockfile.md](../lockfile.md) for the lockfile format and the
consistency rules this command enforces.

---

## Relationship to `kanon catalog audit`

`kanon validate` and `kanon catalog audit` share the same underlying check
functions and produce findings in the same format. The key difference is scope:

| Feature | `kanon validate metadata` | `kanon catalog audit` |
|---------|--------------------------|----------------------|
| Soft-spot 1 (metadata) | Yes | Yes |
| Soft-spot 2 (source-name derivation) | Yes | Yes |
| Soft-spot 3 (entry-name uniqueness) | Yes | Yes |
| Soft-spot 4 (remote-URL resolvability) | No | Yes |
| Soft-spot 5 (PEP 440 tag-name compliance) | No | Yes |
| Remote git sources (`<git_url>@<ref>`) | No | Yes |
| Network access | None | Yes (for remote sources) |
| `--strict` mode | No | Yes (parsed; not yet active) |
| `--check <subset>` | No (runs all three in-repo checks) | Yes |

Use `kanon validate metadata` in fast local pre-push hooks where network
access is undesirable. Use `kanon catalog audit` for comprehensive audits
against remote or cached manifest repos.

## Related commands

- `kanon catalog audit` -- full soft-spot audit including remote checks
- `kanon doctor` -- workspace health checks
- `kanon search` -- browse catalog entries
