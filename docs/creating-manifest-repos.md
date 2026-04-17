# Creating a Manifest Repository

How to create a top-level manifest repository that orchestrates Kanon packages.

## What is a Manifest Repository?

A manifest repository is a Git repository that contains XML manifest files defining which packages to sync, from which repositories, at which versions. It acts as the central registry for an organization's automation packages.

The Kanon CLI reads `.kanon` configurations that point to manifest files in these repositories. When `kanon install` runs, kanon clones and syncs packages according to the manifest definitions.

## Repository Structure

```text
my-manifest-repo/
├── repo-specs/
│   ├── git-connection/
│   │   └── remote.xml              # Shared remote definitions
│   └── common/
│       └── <archetype>/
│           └── development/
│               └── <language>/
│                   └── <toolchain>/
│                       ├── build-meta.xml          # Entry-point manifest
│                       ├── packages.xml            # Package declarations
│                       └── <name>-marketplace.xml   # Optional: marketplace packages
├── catalog/                         # Optional: catalog entry packages for kanon bootstrap
│   └── kanon/
│       ├── .kanon                   # Pre-configured for this catalog entry
│       └── kanon-readme.md
├── examples/                        # Optional: example bootstrapped projects
└── README.md
```

## Remote Definitions (remote.xml)

The `remote.xml` file defines Git remotes that manifests reference. It uses `${VARIABLE}` placeholders resolved by `repo envsubst` at sync time:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin"
          fetch="${GITBASE}" />

  <default revision="main"
           remote="origin"
           sync-j="4" />
</manifest>
```

The `GITBASE` variable comes from `.kanon` and defines the base URL for all package repositories.

## Package Manifests (packages.xml)

Package manifests declare which repositories to clone and where to place them:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <include name="repo-specs/git-connection/remote.xml" />

  <project name="my-build-conventions"
           path=".packages/my-build-conventions"
           remote="origin"
           revision="refs/tags/1.0.0">
  </project>

  <project name="my-linting-rules"
           path=".packages/my-linting-rules"
           remote="origin"
           revision="refs/tags/2.1.0">
  </project>
</manifest>
```

Key attributes:

- `name` — repository name (appended to the remote's `fetch` URL)
- `path` — local directory where the repo is cloned (always under `.packages/`)
- `remote` — name of the remote defined in `remote.xml`
- `revision` — Git ref to checkout (tag, branch, or PEP 440 constraint)

> **Platform path separator note (Bug 17):** Manifest `path`, `src`, and `dest`
> attribute values use forward slashes (`/`) as path separators regardless of
> the host operating system. Some internal path operations in the sync engine
> use `os.sep` or `pathlib`, which may produce backslashes on Windows. If you
> encounter path-related issues on Windows, use `pathlib.Path` or
> `os.path.join()` in any custom tooling that processes manifest paths rather
> than hard-coding `/` separators.

## Entry-Point Manifests (meta.xml / build-meta.xml)

An entry-point manifest ties everything together with `<include>` tags:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <include name="repo-specs/common/my-archetype/packages.xml" />
  <include name="repo-specs/common/my-archetype/my-archetype-marketplace.xml" />
</manifest>
```

This is the file referenced by `KANON_SOURCE_<name>_PATH` in `.kanon`.

## Cascading Manifest Hierarchy (Optional)

Manifests support cascading inheritance through `<include>` chains. This is optional but useful for organizations with many project archetypes that share common packages.

Each level in the hierarchy includes its parent:

```text
meta.xml (entry point)
  └── packages.xml (leaf — e.g., microservice)
        └── packages.xml (framework — e.g., spring-boot)
              └── packages.xml (language — e.g., java)
                    └── packages.xml (common — shared across all)
```

A leaf manifest includes its parent, which includes its parent, forming a chain. Packages defined at any level are available to all descendants.

This hierarchy is not required — a flat structure with a single `packages.xml` works for simple setups.

## Providing a Remote Catalog

A manifest repository can also serve as a remote catalog for `kanon bootstrap`. Place catalog entry packages in a `catalog/` directory at the repository root:

```text
catalog/
└── kanon/
    ├── .kanon
    └── kanon-readme.md
```

Each catalog entry package directory includes a pre-configured `.kanon` with source URLs and paths pointing to manifests in the repository, plus a `kanon-readme.md` with getting-started instructions. The `kanon` entry provides `.kanon` and the readme only.

When users bootstrap with your catalog, they get a fully configured `.kanon` and can run `kanon install` immediately without editing placeholders.

Users can then bootstrap projects using your catalog:

```bash
kanon bootstrap kanon --catalog-source 'https://github.com/org/my-manifest-repo.git@>=2.0.0,<3.0.0'
```

Or via environment variable:

```bash
export KANON_CATALOG_SOURCE='https://github.com/org/my-manifest-repo.git@>=2.0.0,<3.0.0'
kanon bootstrap kanon
```

## Versioning

Manifest repositories should use [semantic versioning](https://semver.org/) for git tags:

- **MAJOR** -- breaking changes (renamed manifests, removed packages, changed directory structure)
- **MINOR** -- new features (new catalog entries, new packages, new manifest archetypes)
- **PATCH** -- bug fixes (corrected manifest paths, fixed XML attributes)

Consumers should pin `KANON_CATALOG_SOURCE` to a major version range to allow automatic pickup of minor and patch releases while preventing unexpected breaking changes:

```bash
# Recommended: pin to current major version
export KANON_CATALOG_SOURCE='https://github.com/org/my-manifest-repo.git@>=2.0.0,<3.0.0'
```

The `@<ref>` portion accepts a branch, tag, `latest` (highest semver tag), or any PEP 440 constraint.

## Connecting to .kanon

The `.kanon` file in a consumer project points to your manifest repository:

```properties
KANON_SOURCE_build_URL=https://github.com/org/my-manifest-repo.git
KANON_SOURCE_build_REVISION=v1.0.0
KANON_SOURCE_build_PATH=repo-specs/common/my-archetype/build-meta.xml
```

Multiple sources can reference different manifest repositories, enabling teams to compose packages from multiple organizations.

See the [multi-source guide](multi-source-guide.md) for details on multi-source configurations.
