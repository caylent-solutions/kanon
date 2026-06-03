# Catalog author guide

This guide covers `kanon catalog audit` end-to-end and the workflow for
authors who maintain a manifest repository (a catalog).

## Audience

This document is for **catalog authors** -- people who own and maintain a
manifest repository that exposes installable kanon dependencies to other
teams.

Consumer-facing usage (how to discover and add entries from a catalog) is
documented in [docs/catalogs-explained.md](catalogs-explained.md) and
[docs/list-and-add.md](list-and-add.md).

If you are starting a new manifest repository from scratch, read
[docs/creating-manifest-repos.md](creating-manifest-repos.md) first,
then return here to learn how `kanon catalog audit` fits into your
workflow.

## kanon catalog audit

`kanon catalog audit` inspects a manifest repo for the five catalog
soft-spot violations and reports findings on stdout.

### Synopsis

```text
kanon catalog audit [<path-or-url>] [--check <names>] [--strict]
                    [--format {text,json}]
```

`<path-or-url>` accepts:

- A **local directory** path whose root contains `repo-specs/`
  (e.g. `.` or `/home/user/my-manifest-repo`).
- A **remote catalog source** in `<git_url>@<ref>` form
  (e.g. `https://example.com/org/manifest-repo.git@main`).
  Requires `KANON_CACHE_DIR` to be set.

When `<path-or-url>` is omitted the command defaults to `.`.

### Flags

**`--check <names>`**
Comma-separated list of check names to run, or `all` (default).
Cannot mix `all` with individual names.
See [--check semantics](#--check-semantics).

**`--strict`**
Promotes WARN-level findings to errors for exit-code purposes.
Exits non-zero when any WARN finding is present.
Prints a summary to stderr naming the warning count.
Findings are never mutated; `WARN:` prefixes still appear in output.

**`--format {text,json}`**
Output format. Default: `text`.
Also controlled by `KANON_CATALOG_AUDIT_FORMAT`.

### --check semantics

The five selectable check names are:

| Check name | Rule |
| ---------- | ---- |
| `metadata` | Rule 1 -- metadata completeness |
| `source-name-derivation` | Rule 2 -- entry-name normalisation |
| `entry-name-uniqueness` | Rule 3 -- name uniqueness |
| `remote-url` | Rule 4 -- remote resolvability |
| `tag-format` | Rule 5 -- PEP 440 compliance |

Use `--check all` (or omit `--check`) to run all five checks.

Use a comma-separated list to run a subset:

```bash
# Run only rules 1 and 5
kanon catalog audit --check metadata,tag-format
```

`all` cannot be combined with individual names. The following invocation
is rejected:

```bash
# ERROR: 'all' cannot be combined with other --check values.
kanon catalog audit --check all,metadata
```

### Exit codes

| Exit code | Meaning |
| --------- | ------- |
| `0` | No ERROR findings (WARN findings ignored unless `--strict`). |
| `1` | One or more ERROR findings, or a fatal error occurred. |
| `2` | Argument-parsing error (bad `--check` value, etc.). |

### Remote audit

To audit a remote manifest repo, set `KANON_CACHE_DIR` and supply the
source in `<git_url>@<ref>` form:

```bash
export KANON_CACHE_DIR=~/.kanon-cache
kanon catalog audit https://example.com/org/manifest-repo.git@main
```

The repository is cloned into a cache subdirectory keyed by a SHA-256
of the canonicalized URL and ref. Cached clones are reused for the
duration of `KANON_CATALOG_AUDIT_CACHE_TTL_SECONDS` (default: 3600 s).

## The five soft-spot rules

Soft-spot rules are quality checks that `kanon catalog audit` enforces.
Each rule targets a different category of catalog author mistake. The
sections below name each rule, describe what the check looks for, show
the emitted finding message, and give the catalog-author fix.

### Rule 1 -- catalog-metadata completeness

**What it looks for:**
The check reads every `*-marketplace.xml` file under `repo-specs/` and
inspects the `<catalog-metadata>` block for:

1. Missing or whitespace-only **required** fields -- produces one ERROR
   (M001) per missing field.
2. Missing **recommended** fields -- produces one WARN (M002) per absent
   field.
3. Duplicate child elements inside `<catalog-metadata>` (e.g. two
   `<name>` elements) -- produces an ERROR (M006).
4. More than one `<catalog-metadata>` block in a single file -- produces
   an ERROR (M005).

Required fields (absence = ERROR):

| Field | Description |
| ----- | ----------- |
| `name` | Machine-readable package identifier. |
| `display-name` | Human-readable label shown in `kanon list` output. |
| `description` | Short prose description of the package. |
| `version` | Author-claimed version string (informational). |

Recommended fields (absence = WARN):

| Field | Description |
| ----- | ----------- |
| `type` | Package type string (e.g. `plugin`, `library`). |
| `owner-name` | Primary owner display name. |
| `owner-email` | Primary owner contact address. |
| `keywords` | Comma-separated keyword list for discoverability. |

**Emitted message:**

```text
ERROR: [M001] /path/tool-marketplace.xml: required <catalog-metadata>
field <description> is missing or contains only whitespace. Add a
non-empty <description> element to the <catalog-metadata> block.

WARN: [M002] /path/tool-marketplace.xml: recommended <catalog-metadata>
field <owner-email> is absent. Consider adding <owner-email> to improve
catalog discoverability.

ERROR: [M006] /path/tool-marketplace.xml: duplicate <name> element
inside <catalog-metadata>; each child tag must appear at most once.
Remove the extra <name> element.

ERROR: [M005] /path/tool-marketplace.xml: 2 <catalog-metadata> blocks
found; exactly one is required. Remove the extra <catalog-metadata>
elements.
```

**How to fix it:**

Add the missing required fields to the `<catalog-metadata>` block and
ensure each `*-marketplace.xml` file contains exactly one such block
with no repeated child elements:

```xml
<?xml version="1.0"?>
<package>
  <catalog-metadata>
    <name>my-tool</name>
    <display-name>My Tool</display-name>
    <description>Deploys Kubernetes manifests using Helm.</description>
    <version>1.2.3</version>
    <type>plugin</type>
    <owner-name>Alice Example</owner-name>
    <owner-email>alice@example.com</owner-email>
    <keywords>infra,deploy,kubernetes</keywords>
  </catalog-metadata>
</package>
```

Run `kanon catalog audit --check metadata .` to confirm zero findings.

### Rule 2 -- source-name derivation

**What it looks for:**
Every `<catalog-metadata><name>` value (the entry name) is normalised
to a shell-variable token by `derive_source_name`:

1. Lowercase the entire string.
2. Replace every `-` (hyphen) with `_` (underscore).

No other transformation is applied.

Two independent findings can be raised per entry name:

- **S001 (WARN):** the normalised form differs from the original entry
  name -- normalisation drift.
- **S002 (WARN):** the entry name contains characters outside
  `[a-zA-Z0-9_-]` (accidental whitespace, dots, non-ASCII, etc.).

Worked example:

| Entry name | Derived form | Drift? | Out-of-charset? |
| ---------- | ------------ | ------ | --------------- |
| `Foo-Bar` | `foo_bar` | yes (S001) | no |
| `foo-bar` | `foo_bar` | yes (S001) | no |
| `foo.bar` | `foo.bar` | no | yes (S002, `.`) |
| `Foo.Bar` | `foo.bar` | yes (S001) | yes (S002, `.`) |
| `foo_bar` | `foo_bar` | no | no |

`Foo-Bar` normalises to `foo_bar` (S001 drift); `Foo.Bar` triggers both
S001 (drift) and S002 (dot out-of-charset).

**Emitted message:**

```text
WARN: [S001] /path/tool-marketplace.xml: entry name 'Foo-Bar' normalises
to 'foo_bar' via derive_source_name. Consider renaming the entry to match
the derived form to avoid surprises in shell variable names and .kanon
files. -- Rename <name>Foo-Bar</name> to <name>foo_bar</name> in the
<catalog-metadata> block.

WARN: [S002] /path/tool-marketplace.xml: entry name 'foo.bar' contains
characters outside the recommended set [a-zA-Z0-9_-]. -- Rename
<name>foo.bar</name> to use only [a-zA-Z0-9_-] characters.
```

**How to fix it:**

Rename the `<name>` value to its fully-normalised form: lowercase and
underscores only. Using `foo_bar` instead of `Foo-Bar` satisfies both
S001 (already normalised) and S002 (only allowed characters).

### Rule 3 -- entry-name uniqueness

**What it looks for:**
Every `<catalog-metadata><name>` value must be unique across all
`*-marketplace.xml` files in the manifest repo. When two or more files
declare the same name, `kanon install` cannot resolve the ambiguity.
The check emits one ERROR (U001) per colliding name, listing every XML
path that declares it.

Comparison is **case-sensitive**: `MyTool` and `mytool` are distinct
names under this check. However, both normalise to `mytool` via
`derive_source_name`, which causes a real conflict at install time.
Run `--check source-name-derivation` alongside this check to catch
case-drift collisions.

**Emitted message:**

```text
ERROR: [U001] Entry name 'my-tool' is declared in 2 files:
/path/repo-specs/group-a/my-tool-marketplace.xml,
/path/repo-specs/group-b/my-tool-marketplace.xml. Entry names must be
unique across every repo-specs/**/*-marketplace.xml file. -- Rename
<name>my-tool</name> to a unique value in all but one of the listed
files, or remove the duplicate catalog entries.
```

**How to fix it:**

Give each entry a distinct name (e.g. `my-tool-alpha` and
`my-tool-beta`), or remove the duplicate entry entirely. Run
`--check entry-name-uniqueness .` after renaming to confirm the ERROR
is gone.

### Rule 4 -- remote-URL resolvability

**What it looks for:**
For every `<project remote="X">` element in each marketplace XML, the
check walks the transitive `<include>` chain and looks for a
`<remote name="X" fetch="...">` definition. The walk is depth-first and
cycle-safe; diamond includes are visited only once.

Three findings can be raised:

- **R001 (ERROR):** no `<remote name="X">` found anywhere in the
  reachable include chain.
- **R002 (ERROR):** the resolved fetch URL uses a non-HTTPS/non-SSH
  scheme (e.g. `http://`, `file://`) and
  `KANON_ALLOW_INSECURE_REMOTES` is not `1`.
- **R003 (ERROR):** the resolved fetch URL contains a query string (`?`)
  or fragment (`#`); URL canonicalization is undefined for such values.

The check re-runs `kanon validate marketplace` against each remote
source as part of verifying resolvability.

**Emitted message:**

```text
ERROR: [R001] /path/tool-marketplace.xml: <project name='my-project'>
references remote='missing' but no <remote name='missing'> is defined
anywhere in the reachable include chain.

ERROR: [R002] /path/tool-marketplace.xml: <remote name='local'> has
fetch URL 'file:///tmp/test' which uses a non-HTTPS remote URL.

ERROR: [R003] /path/tool-marketplace.xml: <remote name='cdn'> has fetch
URL 'https://example.com/mirrors?token=abc' which contains a query
string or fragment.
```

**How to fix it:**

For R001: add a `<remote name="X" fetch="..."/>` element to the
marketplace XML or to a helper file reachable via an `<include>` chain.

For R002: change the fetch URL to `https://` or `ssh://` (or the
`git@host:org/repo.git` shorthand). To allow insecure remotes in local
test fixtures only, set `KANON_ALLOW_INSECURE_REMOTES=1`.

For R003: remove the query string or fragment from the `fetch` attribute
in the `<remote>` element.

### Rule 5 -- PEP 440 tag-name compliance

**What it looks for:**
kanon's version resolver parses the last `/`-delimited path component of
every git tag via `packaging.version.Version`. A tag is **addressable**
(reachable by version constraints like `~=1.0.0`) only when its last
path component is a canonical PEP 440 string -- meaning it both parses
successfully AND `str(Version(component)) == component`.

Tags that fail either condition are silently skipped by the resolver.

Examples:

| Tag | Addressable? | Reason |
| --- | ------------ | ------ |
| `1.0.0` | yes | Canonical PEP 440 |
| `subpackage/1.0.0` | yes | Last component `1.0.0` is canonical |
| `v1.0.0` | no | Normalises to `1.0.0`; not canonical |
| `release-2024` | no | Does not parse as PEP 440 |

**This rule is warning-only (WARN, not ERROR).**
The check exits 0 even when non-canonical tags are present. Manifest
repos commonly contain non-version tags such as ops markers and
release-prep tags (e.g. `release-candidate/1.1.0-rc1`); these tags are
intentionally ignored by the resolver and continue to function for other
git operations. Emitting a warning rather than an error means those repos
are not blocked by the audit.

**Emitted message:**

```text
WARN: [T001] Tag 'v1.0.0' is unaddressable: the last path component
'v1.0.0' is not a valid PEP 440 version. -- Rename the tag so its last
path component is a valid PEP 440 version (e.g. '1.0.0', '1.0.0a1').
```

**How to fix it:**

Rename the tag so its last path component is a canonical PEP 440 string.
For example, rename `v1.0.0` to `1.0.0`, or rename `subpackage/v1.0.0`
to `subpackage/1.0.0`. Use `--check tag-format` to inventory all
non-canonical tags before operators encounter resolver failures.

## Testing your manifest repo

Run the following seven steps to verify a manifest repo end-to-end
before publishing a release. The steps assume a scratch clone at
`./scratch`:

1. **Clone to a scratch directory:**

   ```bash
   git clone https://example.com/org/manifest-repo.git ./scratch
   ```

2. **Full catalog audit (strict mode):**

   ```bash
   kanon catalog audit ./scratch --strict
   ```

   Exits non-zero on any ERROR or WARN finding.

3. **Validate XML structure:**

   ```bash
   kanon validate xml --repo-root ./scratch
   ```

4. **Validate marketplace manifests:**

   ```bash
   kanon validate marketplace --repo-root ./scratch
   ```

5. **Validate metadata soft-spots:**

   ```bash
   kanon validate metadata --repo-root ./scratch
   ```

6. **List catalog entries via scratch source:**

   ```bash
   export KANON_CACHE_DIR=~/.kanon-cache
   kanon list --catalog-source ./scratch@main
   ```

7. **Add a catalog entry and install:**

   ```bash
   kanon add <entry-name> \
     --catalog-source https://example.com/org/manifest-repo.git@main
   kanon install
   ```

   Verify `kanon install` exits zero and the expected packages are
   placed under `.packages/`.

## See also

- [docs/creating-manifest-repos.md](creating-manifest-repos.md) --
  full guide to setting up a manifest repository from scratch,
  including repo structure, the `<catalog-metadata>` contract, and
  tag/versioning rules.
- [docs/list-and-add.md](list-and-add.md) --
  consumer-side reference for `kanon list`, `kanon add`, and
  `kanon remove`.
- [docs/catalogs-explained.md](catalogs-explained.md) --
  conceptual overview of how kanon catalogs work, aimed at first-time
  consumers.
- [docs/cli/catalog-audit.md](cli/catalog-audit.md) --
  full CLI reference for `kanon catalog audit`, including all finding
  codes, output formats, and environment variables.
- Spec Section 3.5 -- soft-spot rules 1-5 (normative source).
- Spec Section 4.8 -- `kanon catalog audit` command specification.
