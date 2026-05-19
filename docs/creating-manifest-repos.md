# Creating a Manifest Repository

How to create and maintain a manifest repository that serves as a catalog
of packages for kanon consumers.

## What a manifest repo is

A **manifest repo** is a git repository whose `repo-specs/` directory
holds XML manifest files whose names match `*-marketplace.xml`. The git
URL (with an optional `@<ref>`) of this repository is exactly what a
consumer passes to `--catalog-source` or sets in `KANON_CATALOG_SOURCE`.

The manifest repo IS the catalog. There is no separate catalog directory;
every catalog entry lives in a single `*-marketplace.xml` file under
`repo-specs/`. Each XML file is identified by its `<catalog-metadata>`
block. The `<catalog-metadata><name>` child is the **entry name** -- the
identifier consumers pass to `kanon add <name>`.

Key terminology (canonical form from spec Section 1.1):

- **manifest repo** -- the git repository itself; synonymous with
  "catalog repo".
- **catalog source** -- a `<git-url>@<ref>` string pointing at a
  manifest repo at a specific revision.
- **catalog entry** -- one `*-marketplace.xml` file inside the manifest
  repo; identified by `<catalog-metadata><name>`.
- **entry name** -- the value of `<catalog-metadata><name>`; must be
  unique across the manifest repo.
- **source name** -- the `<source-name>` token in
  `KANON_SOURCE_<source-name>_*` triples in a `.kanon` file; derived
  from the entry name by normalization (always lowercase, always replace
  `-` with `_`).

## Repository layout

```text
my-manifest-repo/
+-- repo-specs/
|   +-- git-connection/
|   |   +-- remote.xml              # Shared remote definitions
|   +-- common/
|       +-- my-archetype/
|           +-- build-meta.xml      # Entry-point manifest
|           +-- packages.xml        # Package declarations
|           +-- my-archetype-marketplace.xml  # Catalog entry XML
+-- README.md
```

Every `*-marketplace.xml` under `repo-specs/` is a catalog entry. There
is no `catalog/` directory in a current manifest repo. If you are
migrating a repo that still has one, see
[Migrating away from catalog/\<name\>/](#migrating-away-from-catalogname)
below.

## Catalog entry contract

Each `*-marketplace.xml` file MUST contain exactly one `<catalog-metadata>`
block. The following fields are enforced by `kanon validate metadata` and
`kanon catalog audit`:

**REQUIRED fields** (missing any of these is an error):

- `name` -- unique entry name across the manifest repo.
- `display-name` -- human-readable display label.
- `description` -- plain-text description of the entry.
- `version` -- author-claimed version string (informational only; not
  used for resolution -- actual versioning uses git refs/tags on the
  manifest repo).

**RECOMMENDED fields** (missing any of these is a warning):

- `type` -- entry type classification.
- `owner-name` -- maintainer's name.
- `owner-email` -- maintainer's contact address.
- `keywords` -- space-separated search terms.

Example `<catalog-metadata>` block:

```xml
<catalog-metadata>
  <name>my-python-lib</name>
  <display-name>My Python Library</display-name>
  <description>
    A reusable Python library for internal tooling.
  </description>
  <version>1.2.0</version>
  <type>library</type>
  <owner-name>Platform Team</owner-name>
  <owner-email>platform@example.com</owner-email>
  <keywords>python library utilities</keywords>
</catalog-metadata>
```

**Additional rules enforced by `kanon catalog audit`:**

1. **Source-name normalization** -- the source name written into
   `.kanon` by `kanon add` is derived from the entry name by:
   lowercasing the input AND replacing every `-` with `_`. This
   normalization is deterministic and one-way. Example:
   `My-Python-Lib` normalizes to `my_python_lib`.
2. **Entry-name uniqueness** -- `<catalog-metadata><name>` MUST be
   unique across every `*-marketplace.xml` in the manifest repo.
   Collisions are a hard error.
3. **`<remote>` resolvability** -- every `<remote>` element referenced
   in the entry's XML chain MUST be reachable via the `<include>` graph
   rooted at that XML file.
4. **PEP 440 tag-name compliance** -- tag names whose last path
   component is not a valid PEP 440 version are flagged with a warning
   (not an error). See [Tag publishing](#tag-publishing).

## Tag publishing

Kanon's resolver identifies versions from git tags on the manifest repo.
Tags MUST be PEP 440 compliant in their last path component to be
addressable by kanon consumers. For monorepo layouts a path prefix is
allowed; kanon strips everything up to and including the final `/` before
parsing the version.

**Valid tag names:**

| Tag | Note |
| --- | ---- |
| `1.0.0` | simple release |
| `2.1.3rc2` | release candidate |
| `subpackage/1.0.0` | monorepo path prefix |
| `dev/python/lib/2.1.3` | deeper monorepo prefix |

**Counter-examples (produce a warning from `kanon catalog audit`):**

| Tag | Why it is warned about |
| --- | ---------------------- |
| `v1.0.0` | leading `v` is not PEP 440 |
| `release-2024` | not a version number |
| `prod-deploy-2026-04-01` | date-based, not PEP 440 |

Tags that do not pass PEP 440 parsing are silently skipped by the
resolver. Consumers who need to pin to a non-PEP-440 ref must use an
explicit branch name or full `refs/tags/<name>` notation. The warning
from `kanon catalog audit` is not a build error; it exists to alert
catalog authors before consumers hit silent resolution failures.

To publish a release:

```bash
git tag 1.0.0
git push origin 1.0.0
```

## Migrating away from catalog/\<name\>/

Older manifest repos contained a `catalog/` directory tree where each
subdirectory held a pre-baked `.kanon` template and an optional
`kanon-readme.md` (or `README.md`) for `kanon bootstrap`. This layout
is no longer used. `kanon list`, `kanon add`, and `kanon catalog audit`
read ONLY the `*-marketplace.xml` files in `repo-specs/`; the `catalog/`
directory is ignored.

To migrate a manifest repo that still has a `catalog/` directory:

1. **Copy author documentation into `<description>`.** For each entry,
   open `catalog/<name>/README.md` or `catalog/<name>/kanon-readme.md`
   (whichever exists) and paste the relevant content verbatim into the
   corresponding `*-marketplace.xml`'s `<catalog-metadata><description>`
   element. Truncation is a human-review decision; the XML parser accepts
   multi-line text content in `<description>`.

2. **Verify required metadata fields.** Run:

   ```bash
   kanon catalog audit . --check metadata
   ```

   Fix every error reported before proceeding. Warnings about
   recommended fields are advisory.

3. **Delete the legacy `catalog/` directory tree.**

   ```bash
   git rm -r catalog/
   git commit -m "Remove legacy catalog/ directory (use repo-specs/**/*-marketplace.xml)"
   ```

4. **Verify `kanon list` returns every expected entry.**

   ```bash
   kanon list --catalog-source https://example.com/org/manifest-repo.git@main
   ```

   The output should list every entry name you expect. If an entry is
   missing, check that its XML file has a valid `<catalog-metadata><name>`
   and passes `kanon validate metadata`.

## Testing your manifest repo

Run the following eight steps in order before publishing a new release
of your manifest repo:

1. Run the full catalog audit in strict mode:

   ```bash
   kanon catalog audit . --strict
   ```

2. Validate all XML is well-formed:

   ```bash
   kanon validate xml
   ```

3. Validate all marketplace XML files:

   ```bash
   kanon validate marketplace
   ```

4. Validate all catalog metadata:

   ```bash
   kanon validate metadata
   ```

5. Clone the repo to a scratch directory:

   ```bash
   git clone https://example.com/org/manifest-repo.git ./scratch
   ```

6. List all entries using the scratch clone:

   ```bash
   kanon list --catalog-source ./scratch@main
   ```

7. Add one entry end-to-end using the scratch clone:

   ```bash
   kanon add <one-entry> --catalog-source ./scratch@main
   ```

8. Run install to confirm the resolved `.kanon` is valid:

   ```bash
   kanon install
   ```

All eight steps must exit zero before the release tag is pushed.

## See also

- [docs/catalog-author-guide.md](catalog-author-guide.md) -- detailed
  guide for authors writing `*-marketplace.xml` catalog entries.
- [docs/catalogs-explained.md](catalogs-explained.md) -- what a manifest
  repo is and how to find one as a consumer.
- [docs/list-and-add.md](list-and-add.md) -- reference for `kanon list`
  and `kanon add` from the consumer perspective.
- [docs/lockfile.md](lockfile.md) -- the `.kanon.lock` file format and
  how resolved catalog sources are recorded.
