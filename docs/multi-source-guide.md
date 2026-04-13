# Multi-Source Kanon Bootstrap Guide

This guide documents how Kanon supports multiple manifest sources,
enabling teams to compose packages from different repositories
and organizations.

---

## Named Source Format (.kanon)

Kanon auto-discovers sources from `KANON_SOURCE_<name>_URL` variable patterns in `.kanon`.
Each source is defined by a set of three variables following the
`KANON_SOURCE_<name>_<property>` naming convention:

| Suffix | Purpose |
|---|---|
| `_URL` | Git repository URL for the manifest source |
| `_REVISION` | Branch name, exact tag ref, or PEP 440 version constraint |
| `_PATH` | Path to the entry-point manifest XML within the repository |

Sources are processed in alphabetical order by name.

See the [.kanon variable reference](../README.md#kanon-variable-reference)
for the full variable table.

### Source Naming Convention

The `<name>` in `KANON_SOURCE_<name>_URL` is a free-form identifier — Kanon
extracts it by stripping the `KANON_SOURCE_` prefix and the `_URL` suffix,
treating everything in between as the source name. The name has no semantic
meaning to the CLI; it is purely organizational.

**The CLI treats all sources identically.** Every source goes through the
same processing pipeline: `repo init` → `repo envsubst` → `repo sync`.
The source name does not influence how the CLI processes it. What a source
delivers is determined entirely by its **manifest content**.

A source delivers build packages when its manifest contains `<project>`
entries that clone package repositories into `.packages/`. A source
delivers marketplace plugins when its manifest contains `<project>` entries
with `<linkfile>` elements that create symlinks into
`${CLAUDE_MARKETPLACES_DIR}`. It is the symlink destination — not the
source name — that causes the synced content to be recognized as a
marketplace plugin. When `KANON_MARKETPLACE_INSTALL=true`, the CLI scans the
entire `${CLAUDE_MARKETPLACES_DIR}` directory after all sources have synced
and installs every plugin found there, regardless of which source created
the symlink.

### Recommended Naming Convention

Choose source names that describe what the source provides. This makes
`.kanon` files self-documenting for humans and AI agents without needing
to inspect the manifest XML content. Common prefixes include:

| Prefix | Purpose |
|---|---|
| `build` | Build tooling packages (linting, formatting, conventions) |
| `marketplaces` | Claude Code marketplace plugins |
| `pipelines` | CI/CD pipeline packages |
| `runners` | Task runner packages |
| `tf-deploy-templates` | Terraform deployment templates |
| `sonarqube-config` | SonarQube configuration packages |

These prefixes are conventions, not requirements. Any descriptive name
that communicates the source's purpose to your team is appropriate.

When multiple sources serve the same concern, append a hyphenated qualifier
to distinguish them (e.g., `build-core`, `build-infra`,
`marketplaces-core`, `marketplaces-team`, `pipelines-ci`, `pipelines-cd`).

**Use hyphens to create descriptive, multi-word source names.** Hyphens
keep the three-field structure (`KANON_SOURCE_` + `<name>` + `_SUFFIX`)
visually unambiguous:

```text
KANON_SOURCE_<name>_URL
     ^1         ^2    ^3

Field 1: KANON_SOURCE_   (fixed prefix)
Field 2: <name>          (free-form identifier — use hyphens for multi-word names)
Field 3: _URL            (fixed suffix: _URL, _REVISION, or _PATH)
```

**Single source per concern:**

```properties
KANON_SOURCE_build_URL=...
KANON_SOURCE_marketplaces_URL=...
KANON_SOURCE_pipelines_URL=...
```

**Multiple sources per concern — hyphenate the name:**

```properties
KANON_SOURCE_build-core_URL=...
KANON_SOURCE_build-infra_URL=...
KANON_SOURCE_marketplaces-core_URL=...
KANON_SOURCE_marketplaces-team_URL=...
KANON_SOURCE_pipelines-ci_URL=...
KANON_SOURCE_pipelines-cd_URL=...
```

There is no limit on the number of sources. The CLI discovers all
`KANON_SOURCE_<name>_URL` keys, extracts each `<name>`, and processes
them in alphabetical order.

> **Note:** Underscores within the name (e.g., `KANON_SOURCE_build_core_URL`)
> also work — the parser strips only the known prefix and suffix. However,
> hyphens are recommended because they visually distinguish the source name
> from the surrounding underscore-delimited fields.

### Example: Single Build and Marketplace Source

```properties
# Sources are auto-discovered from KANON_SOURCE_<name>_URL patterns.
# No explicit source list is needed — names are extracted from _URL keys
# and processed in alphabetical order.

# Build tools source — pinned to exact tag
KANON_SOURCE_build_URL=https://github.com/org/kanon-build-tools.git
KANON_SOURCE_build_REVISION=refs/tags/2.0.0
KANON_SOURCE_build_PATH=repo-specs/build-meta.xml

# Marketplace source — compatible release constraint (>=1.1.0, <1.2.0)
KANON_SOURCE_marketplaces_URL=https://github.com/org/kanon-marketplace.git
KANON_SOURCE_marketplaces_REVISION=refs/tags/~=1.1.0
KANON_SOURCE_marketplaces_PATH=repo-specs/common/plugins/plugins-marketplace.xml

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
KANON_SOURCE_build-core_URL=https://github.com/org/kanon-build-core.git
KANON_SOURCE_build-core_REVISION=refs/tags/~=2.0.0
KANON_SOURCE_build-core_PATH=repo-specs/build-meta.xml

KANON_SOURCE_build-infra_URL=https://github.com/org/kanon-build-infra.git
KANON_SOURCE_build-infra_REVISION=refs/tags/>=1.0.0,<2.0.0
KANON_SOURCE_build-infra_PATH=repo-specs/build-meta.xml

KANON_SOURCE_build-security_URL=https://github.com/org/kanon-build-security.git
KANON_SOURCE_build-security_REVISION=refs/tags/~=1.4.0
KANON_SOURCE_build-security_PATH=repo-specs/build-meta.xml

# Marketplace sources — each provides Claude Code plugins
KANON_SOURCE_marketplaces-core_URL=https://github.com/org/kanon-marketplace-core.git
KANON_SOURCE_marketplaces-core_REVISION=main
KANON_SOURCE_marketplaces-core_PATH=repo-specs/common/core/core-marketplace.xml

KANON_SOURCE_marketplaces-team_URL=https://github.com/org/kanon-marketplace-team.git
KANON_SOURCE_marketplaces-team_REVISION=main
KANON_SOURCE_marketplaces-team_PATH=repo-specs/common/team/team-marketplace.xml

# Global variables available to all sources
GITBASE=https://github.com/org/
CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
KANON_MARKETPLACE_INSTALL=true
```

Processing order (alphabetical): `build-core` → `build-infra` →
`build-security` → `marketplaces-core` → `marketplaces-team`.

`KANON_SOURCE_<name>_REVISION` accepts a branch name, an exact tag ref, or a PEP 440 constraint. When a constraint is used, the CLI resolves it against available tags before passing the result to `repo init -b`. Using the `refs/tags/` prefix is recommended — it scopes resolution to tags and produces a full ref path compatible with `repo init`. See [version-resolution.md](version-resolution.md) for all supported operators and syntax.

Sources are auto-discovered from `KANON_SOURCE_<name>_URL` variable patterns
and processed in alphabetical order by name. Environment variables override
`.kanon` file values, allowing the same configuration to work across environments.

---

## Source Isolation

Each source is initialized and synced in its own isolated directory
under `.kanon-data/sources/<name>/`. This prevents sources from interfering
with each other.

### Directory Structure

Each source name becomes a directory under `.kanon-data/sources/`:

```text
.kanon-data/
└── sources/
    ├── build-core/               # From KANON_SOURCE_build-core_*
    │   ├── .repo/
    │   └── .packages/
    │       └── kanon-build-conventions/
    ├── build-infra/              # From KANON_SOURCE_build-infra_*
    │   ├── .repo/
    │   └── .packages/
    │       └── kanon-terraform-modules/
    ├── marketplaces-core/        # From KANON_SOURCE_marketplaces-core_*
    │   ├── .repo/
    │   └── .packages/
    │       └── kanon-claude-marketplaces-example-dev-lint/
    └── marketplaces-team/        # From KANON_SOURCE_marketplaces-team_*
        ├── .repo/
        └── .packages/
            └── kanon-claude-marketplaces-team-tools/
```

### Why Isolation Matters

- Each source gets its own `repo init` / `repo sync` cycle
- Sources cannot overwrite each other's `.repo/` metadata
- Failures in one source do not corrupt another source's state
- Sources can use different manifest URLs, revisions, and paths

---

## Symlink Aggregation

After all sources are synced, Kanon aggregates their packages into
a single top-level `.packages/` directory using symlinks. This gives
consumers a unified view of all packages regardless of which source
provided them.

### Aggregation Process

1. For each source in alphabetical order, scan `.kanon-data/sources/<name>/.packages/`
2. For each package directory found, create a symlink in the top-level `.packages/`
3. The symlink points from `.packages/<pkg-name>` to `.kanon-data/sources/<name>/.packages/<pkg-name>`

### Result

```text
.packages/                                         # Unified view (symlinks)
├── kanon-build-conventions          -> .kanon-data/sources/build-core/.packages/kanon-build-conventions
├── kanon-terraform-modules          -> .kanon-data/sources/build-infra/.packages/kanon-terraform-modules
├── kanon-claude-marketplaces-example-dev-lint -> .kanon-data/sources/marketplaces-core/.packages/kanon-claude-marketplaces-example-dev-lint
└── kanon-claude-marketplaces-team-tools      -> .kanon-data/sources/marketplaces-team/.packages/kanon-claude-marketplaces-team-tools
```

Consumers reference packages from `.packages/` without needing to know
which source provided them.

---

## Collision Detection

When two sources produce a package with the same name, Kanon detects the
collision and fails immediately with an actionable error message.

### How It Works

During symlink aggregation, Kanon tracks which source provided each
package name. If a package name already exists from a previous source,
aggregation aborts with an error identifying both the conflicting
sources and the duplicate package name.

### Example Error

```text
Error: Package collision for 'kanon-shared-utils':
  provided by source 'build-core' and source 'build-infra'
```

### Resolution

- Rename one of the conflicting packages in its manifest
- Remove the duplicate from one source
- Remove the `KANON_SOURCE_<name>_*` variables for the source with the unwanted duplicate

Collision detection runs after all sources are synced, ensuring that
the error is caught before any consumer code runs.
