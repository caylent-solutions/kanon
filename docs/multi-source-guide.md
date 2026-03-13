# Multi-Source RPM Bootstrap Guide

This guide documents how RPM supports multiple manifest sources,
enabling teams to compose packages from different repositories
and organizations.

---

## Named Source Format (.rpmenv)

RPM auto-discovers sources from `RPM_SOURCE_<name>_URL` variable patterns in `.rpmenv`.
Each source is defined by a set of three variables following the
`RPM_SOURCE_<name>_<property>` naming convention:

| Suffix | Purpose |
|---|---|
| `_URL` | Git repository URL for the manifest source |
| `_REVISION` | Branch name, exact tag ref, or PEP 440 version constraint |
| `_PATH` | Path to the entry-point manifest XML within the repository |

Sources are processed in alphabetical order by name.

See the [.rpmenv variable reference](../README.md#rpmenv-variable-reference)
for the full variable table.

### Source Naming Convention

The `<name>` in `RPM_SOURCE_<name>_URL` is a free-form identifier — RPM
extracts it by stripping the `RPM_SOURCE_` prefix and the `_URL` suffix,
treating everything in between as the source name. The name has no semantic
meaning to the CLI; it is purely organizational.

**Use hyphens to create descriptive, multi-word source names.** Hyphens
keep the three-field structure (`RPM_SOURCE_` + `<name>` + `_SUFFIX`)
visually unambiguous:

```text
RPM_SOURCE_<name>_URL
     ^1       ^2    ^3

Field 1: RPM_SOURCE_     (fixed prefix)
Field 2: <name>          (free-form identifier — use hyphens for multi-word names)
Field 3: _URL            (fixed suffix: _URL, _REVISION, or _PATH)
```

**Single source per concern:**

```properties
RPM_SOURCE_build_URL=...
RPM_SOURCE_marketplaces_URL=...
```

**Multiple sources per concern — hyphenate the name:**

```properties
RPM_SOURCE_build-core_URL=...
RPM_SOURCE_build-infra_URL=...
RPM_SOURCE_marketplaces-core_URL=...
RPM_SOURCE_marketplaces-team_URL=...
```

There is no limit on the number of sources. The CLI discovers all
`RPM_SOURCE_<name>_URL` keys, extracts each `<name>`, and processes
them in alphabetical order.

> **Note:** Underscores within the name (e.g., `RPM_SOURCE_build_core_URL`)
> also work — the parser strips only the known prefix and suffix. However,
> hyphens are recommended because they visually distinguish the source name
> from the surrounding underscore-delimited fields.

### Example: Single Build and Marketplace Source

```properties
# Sources are auto-discovered from RPM_SOURCE_<name>_URL patterns.
# No explicit source list is needed — names are extracted from _URL keys
# and processed in alphabetical order.

# Build tools source — pinned to exact tag
RPM_SOURCE_build_URL=https://github.com/org/rpm-build-tools.git
RPM_SOURCE_build_REVISION=refs/tags/2.0.0
RPM_SOURCE_build_PATH=repo-specs/build-meta.xml

# Marketplace source — compatible release constraint (>=1.1.0, <1.2.0)
RPM_SOURCE_marketplaces_URL=https://github.com/org/rpm-marketplace.git
RPM_SOURCE_marketplaces_REVISION=refs/tags/~=1.1.0
RPM_SOURCE_marketplaces_PATH=repo-specs/claude-marketplaces.xml

# Global variables available to all sources
GITBASE=https://github.com/org/
CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
```

### Example: Multiple Build and Marketplace Sources

When a project needs packages from several repositories, add additional
sources with hyphenated names. Each source gets its own isolated workspace
and all packages are aggregated into a unified `.packages/` directory.

```properties
# Build sources — each points to a different manifest repository
RPM_SOURCE_build-core_URL=https://github.com/org/rpm-build-core.git
RPM_SOURCE_build-core_REVISION=refs/tags/~=2.0.0
RPM_SOURCE_build-core_PATH=repo-specs/build-meta.xml

RPM_SOURCE_build-infra_URL=https://github.com/org/rpm-build-infra.git
RPM_SOURCE_build-infra_REVISION=refs/tags/>=1.0.0,<2.0.0
RPM_SOURCE_build-infra_PATH=repo-specs/build-meta.xml

RPM_SOURCE_build-security_URL=https://github.com/org/rpm-build-security.git
RPM_SOURCE_build-security_REVISION=refs/tags/~=1.4.0
RPM_SOURCE_build-security_PATH=repo-specs/build-meta.xml

# Marketplace sources — each provides Claude Code plugins
RPM_SOURCE_marketplaces-core_URL=https://github.com/org/rpm-marketplace-core.git
RPM_SOURCE_marketplaces-core_REVISION=main
RPM_SOURCE_marketplaces-core_PATH=repo-specs/claude-marketplaces.xml

RPM_SOURCE_marketplaces-team_URL=https://github.com/org/rpm-marketplace-team.git
RPM_SOURCE_marketplaces-team_REVISION=main
RPM_SOURCE_marketplaces-team_PATH=repo-specs/claude-marketplaces.xml

# Global variables available to all sources
GITBASE=https://github.com/org/
CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
RPM_MARKETPLACE_INSTALL=true
```

Processing order (alphabetical): `build-core` → `build-infra` →
`build-security` → `marketplaces-core` → `marketplaces-team`.

`RPM_SOURCE_<name>_REVISION` accepts a branch name, an exact tag ref, or a PEP 440 constraint. When a constraint is used, the CLI resolves it against available tags before passing the result to `repo init -b`. Using the `refs/tags/` prefix is recommended — it scopes resolution to tags and produces a full ref path compatible with `repo init`. See [version-resolution.md](version-resolution.md) for all supported operators and syntax.

Sources are auto-discovered from `RPM_SOURCE_<name>_URL` variable patterns
and processed in alphabetical order by name. Environment variables override
`.rpmenv` file values, allowing the same configuration to work across environments.

---

## Source Isolation

Each source is initialized and synced in its own isolated directory
under `.rpm/sources/<name>/`. This prevents sources from interfering
with each other.

### Directory Structure

Each source name becomes a directory under `.rpm/sources/`:

```text
.rpm/
└── sources/
    ├── build-core/               # From RPM_SOURCE_build-core_*
    │   ├── .repo/
    │   └── .packages/
    │       └── rpm-build-conventions/
    ├── build-infra/              # From RPM_SOURCE_build-infra_*
    │   ├── .repo/
    │   └── .packages/
    │       └── rpm-terraform-modules/
    ├── marketplaces-core/        # From RPM_SOURCE_marketplaces-core_*
    │   ├── .repo/
    │   └── .packages/
    │       └── rpm-claude-marketplaces-example-dev-lint/
    └── marketplaces-team/        # From RPM_SOURCE_marketplaces-team_*
        ├── .repo/
        └── .packages/
            └── rpm-claude-marketplaces-team-tools/
```

### Why Isolation Matters

- Each source gets its own `repo init` / `repo sync` cycle
- Sources cannot overwrite each other's `.repo/` metadata
- Failures in one source do not corrupt another source's state
- Sources can use different manifest URLs, revisions, and paths

---

## Symlink Aggregation

After all sources are synced, RPM aggregates their packages into
a single top-level `.packages/` directory using symlinks. This gives
consumers a unified view of all packages regardless of which source
provided them.

### Aggregation Process

1. For each source in alphabetical order, scan `.rpm/sources/<name>/.packages/`
2. For each package directory found, create a symlink in the top-level `.packages/`
3. The symlink points from `.packages/<pkg-name>` to `.rpm/sources/<name>/.packages/<pkg-name>`

### Result

```text
.packages/                                         # Unified view (symlinks)
├── rpm-build-conventions          -> .rpm/sources/build-core/.packages/rpm-build-conventions
├── rpm-terraform-modules          -> .rpm/sources/build-infra/.packages/rpm-terraform-modules
├── rpm-claude-marketplaces-example-dev-lint -> .rpm/sources/marketplaces-core/.packages/rpm-claude-marketplaces-example-dev-lint
└── rpm-claude-marketplaces-team-tools      -> .rpm/sources/marketplaces-team/.packages/rpm-claude-marketplaces-team-tools
```

Consumers reference packages from `.packages/` without needing to know
which source provided them.

---

## Collision Detection

When two sources produce a package with the same name, RPM detects the
collision and fails immediately with an actionable error message.

### How It Works

During symlink aggregation, RPM tracks which source provided each
package name. If a package name already exists from a previous source,
aggregation aborts with an error identifying both the conflicting
sources and the duplicate package name.

### Example Error

```text
Error: Package collision for 'rpm-shared-utils':
  provided by source 'build-core' and source 'build-infra'
```

### Resolution

- Rename one of the conflicting packages in its manifest
- Remove the duplicate from one source
- Remove the `RPM_SOURCE_<name>_*` variables for the source with the unwanted duplicate

Collision detection runs after all sources are synced, ensuring that
the error is caught before any consumer code runs.
