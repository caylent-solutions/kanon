# RPM (Repo Package Manager)

A standalone Python CLI for managing versioned DevOps automation packages via declarative manifests.

**License:** Apache 2.0

---

## Table of Contents

- [What is RPM?](#what-is-rpm)
  - [Use Cases](#use-cases)
- [Quick Start](#quick-start)
  - [Prerequisites](#prerequisites)
  - [Install the RPM CLI](#install-the-rpm-cli)
  - [Standalone Usage (No Task Runner Required)](#standalone-usage-no-task-runner-required)
  - [Usage with Task Runners (Optional)](#usage-with-task-runners-optional)
- [CLI Reference](#cli-reference)
  - [rpm bootstrap](#rpm-bootstrap)
  - [rpm configure](#rpm-configure)
  - [rpm clean](#rpm-clean)
  - [rpm validate xml](#rpm-validate-xml)
  - [rpm validate marketplace](#rpm-validate-marketplace)
- [.rpmenv Variable Reference](#rpmenv-variable-reference)
  - [Core Variables](#core-variables)
  - [Source Variables](#source-variables)
  - [Environment Variables](#environment-variables)
  - [Example .rpmenv](#example-rpmenv)
- [Architecture](#architecture)
  - [How It Works](#how-it-works)
  - [Directory Structure After Configure](#directory-structure-after-configure)
  - [Multi-Source Isolation](#multi-source-isolation)
  - [Environment Variable Portability (envsubst)](#environment-variable-portability-envsubst)
- [Creating a Manifest Repository](#creating-a-manifest-repository)
  - [Structure](#structure)
  - [remote.xml -- Git Remote Definition](#remotexml----git-remote-definition)
  - [packages.xml -- Package Declarations](#packagesxml----package-declarations)
  - [meta.xml -- Entry Point](#metaxml----entry-point)
  - [Include Chains for Hierarchy](#include-chains-for-hierarchy)
  - [Updating Package Versions](#updating-package-versions)
- [Creating Packages](#creating-packages)
  - [Package Structure](#package-structure)
  - [Versioning](#versioning)
  - [Registering a Package](#registering-a-package)
  - [Symlinks via linkfile](#symlinks-via-linkfile)
  - [Gradle Package Specifics](#gradle-package-specifics)
- [Creating Marketplace Packages](#creating-marketplace-packages)
  - [Marketplace Manifest Structure](#marketplace-manifest-structure)
  - [Key Requirements](#key-requirements)
  - [Cascading Hierarchy](#cascading-hierarchy)
  - [Validation](#validation)
- [Fork Features (PEP 440 Constraints)](#fork-features-pep-440-constraints)
  - [PEP 440 Version Constraints in Manifests](#pep-440-version-constraints-in-manifests)
  - [PEP 440 Version Resolution in .rpmenv](#pep-440-version-resolution-in-rpmenv)
  - [Absolute Linkfile Destinations](#absolute-linkfile-destinations)
- [Developer Setup](#developer-setup)
  - [Prerequisites](#prerequisites-1)
  - [Install from Source](#install-from-source)
  - [Set Up Git Hooks](#set-up-git-hooks)
  - [Run Tests](#run-tests)
  - [Build](#build)
  - [Project Structure](#project-structure)
  - [Contributing](#contributing)
  - [CI/CD Pipeline](#cicd-pipeline)
- [Documentation](#documentation)
- [License](#license)

---

## What is RPM?

RPM is a **DevOps Platform Dependency Manager** that brings version-controlled, reproducible automation to your projects through declarative manifests. RPM enables you to centralize, version, and share automation across your organization without replacing your existing tools.

**Solves a common problem:**
Organizations have quality automation scattered across teams -- build conventions, linting rules, security scanning, test frameworks, and local dev tooling that work well but are not widely adopted because they are hard to discover, version, test, and distribute. RPM enables you to package this automation and share it across projects in a tested, reproducible way.

**Fully customizable:**
- **Public or Private** -- Use public repositories or host everything privately within your organization
- **Your Infrastructure** -- Point to your own Git repositories and package sources
- **Your Standards** -- Define your own manifests, packages, and automation
- **Portable** -- Teams retain access to automation even after external partnerships end

**Core Purpose:**
- **Platform Dependency Management** -- Centralize and version your DevOps automation, dependencies, and standards
- **Flexible Overlay** -- Works alongside your preferred task runners (Make, npm, Gradle, Maven) and dependency managers
- **Team Standards** -- Share tested, versioned automation, tasks, and approaches across teams dynamically
- **Tool Agnostic** -- Adapts to your workflow, not the other way around

### Use Cases

**Unify Disparate Automation:**
Your organization has quality automation scattered across teams -- testing frameworks, linting configs, deployment scripts, security scans -- but they are not widely adopted because they are hard to find, version, and integrate. RPM lets you package this automation, version it, and make it available to all teams through simple manifests.

**Platform Engineering:**
Provide golden paths and paved roads to development teams. Package your organization's standards, policies, and automation as versioned dependencies that teams can pull into their projects.

**Multi-Project Consistency:**
Ensure the same testing, linting, security scanning, and deployment automation across projects without copy-pasting or manual synchronization.

---

## Quick Start

### Prerequisites

- Python 3.11+
- [pipx](https://pipx.pypa.io/) on PATH
- Git

### Install the RPM CLI

```bash
pipx install "git+https://github.com/caylent-solutions/rpm.git@0.1.0"
```

### Standalone Usage (No Task Runner Required)

RPM works directly from the command line. No task runner is needed.

**1. Bootstrap a project:**

```bash
rpm bootstrap make              # Generate .rpmenv and a Makefile wrapper
rpm bootstrap gradle            # Generate .rpmenv and Gradle wrapper files
rpm bootstrap list              # See all available runner templates
```

**2. Edit `.rpmenv`** and replace all `<PLACEHOLDER>` values with your project's configuration (manifest URLs, Git base URL, source definitions).

**3. Configure (sync all packages):**

```bash
rpm configure .rpmenv
```

This syncs all packages to `.packages/`, creates source workspaces in `.rpm/sources/`, and adds `.packages/` and `.rpm/` to `.gitignore`.

**4. Clean (full teardown):**

```bash
rpm clean .rpmenv
```

This removes all synced packages, RPM state directories, and optionally uninstalls marketplace plugins.

**Important:** All synced files in `.packages/` and `.rpm/` are ephemeral and should not be committed. Only commit your task runner bootstrap files and `.rpmenv` to your repository.

### Usage with Task Runners (Optional)

The `rpm bootstrap` command generates task runner wrappers that delegate to the CLI. These are optional conveniences -- the CLI works standalone.

**Make:**

```bash
make rpmConfigure    # Delegates to: rpm configure .rpmenv
make rpmClean        # Delegates to: rpm clean .rpmenv
```

**Gradle:**

```bash
./gradlew rpmConfigure    # Delegates to: rpm configure .rpmenv
./gradlew rpmClean        # Delegates to: rpm clean .rpmenv
```

Use `--output-dir DIR` to bootstrap into a different directory. Use `--catalog-source '<git_url>@<ref>'` or the `RPM_CATALOG_SOURCE` environment variable to fetch templates from a remote catalog repository (ref can be a branch, tag, or `latest` which resolves to the highest semver tag).

---

## CLI Reference

```bash
rpm --help                              # Top-level help
rpm --version                           # Show version
```

### rpm bootstrap

Scaffolds a new RPM project with task runner files and a `.rpmenv` template.

```bash
rpm bootstrap list                      # List available runner templates
rpm bootstrap make                      # Scaffold a Make project
rpm bootstrap gradle                    # Scaffold a Gradle project
rpm bootstrap gradle --output-dir proj  # Scaffold into proj/
rpm bootstrap make --catalog-source 'https://github.com/org/repo.git@main'
```

**Options:**

| Option | Description |
|---|---|
| `--output-dir DIR` | Target directory (default: current directory) |
| `--catalog-source SOURCE` | Remote catalog as `<git_url>@<ref>` (branch, tag, or `latest`). Overrides `RPM_CATALOG_SOURCE` env var. Default: bundled catalog. |

### rpm configure

Executes the full configure lifecycle.

```bash
rpm configure .rpmenv
```

**Steps performed:**

1. Checks prerequisites (pipx on PATH)
2. Resolves `REPO_REV` if fuzzy (PEP 440 version specifier)
3. Installs the repo tool via pipx
4. For each source (alphabetical order): `repo init` / `repo envsubst` / `repo sync`
5. Aggregates symlinks from `.rpm/sources/<name>/.packages/` into `.packages/`
6. Detects package name collisions across sources (fail-fast)
7. Updates `.gitignore`
8. If `RPM_MARKETPLACE_INSTALL=true`: runs marketplace install lifecycle

### rpm clean

Executes the full teardown lifecycle.

```bash
rpm clean .rpmenv
```

**Steps performed:**

1. If `RPM_MARKETPLACE_INSTALL=true`: uninstalls plugins, removes marketplace directory
2. Removes `.packages/` directory
3. Removes `.rpm/` directory

The order is critical: plugins are uninstalled before files are removed to ensure the registry is cleaned while paths are still resolvable.

### rpm validate xml

Validates all XML manifest files under `repo-specs/`.

```bash
rpm validate xml                        # Validate in current repo
rpm validate xml --repo-root /path      # Validate with explicit repo root
```

**Checks performed:**

- Well-formed XML
- Required attributes on `<project>` (name, path, remote, revision)
- Required attributes on `<remote>` (name, fetch)
- `<include>` references point to existing files

### rpm validate marketplace

Validates marketplace XML manifests under `repo-specs/`.

```bash
rpm validate marketplace                # Validate in current repo
rpm validate marketplace --repo-root /path
```

**Checks performed:**

- `<linkfile dest>` uses `${CLAUDE_MARKETPLACES_DIR}/` prefix
- Include chains are unbroken
- Project paths are unique across manifests
- Revision attributes follow valid formats (refs/tags, constraints, branches)

---

## .rpmenv Variable Reference

The `.rpmenv` file is a shell-compatible `KEY=VALUE` configuration file that drives the RPM lifecycle. Lines starting with `#` are comments. Values can reference environment variables using `${VAR}` syntax (e.g., `${HOME}/.claude-marketplaces`). Every `.rpmenv` variable can be overridden by an environment variable of the same name, enabling CI/CD pipelines to customize behavior without modifying the file.

### Core Variables

| Variable | Required | Purpose |
|---|---|---|
| `REPO_URL` | Yes | Git URL of the repo tool fork |
| `REPO_REV` | Yes | Repo tool version — branch, exact tag, or PEP 440 specifier (e.g. `~=1.0.0`) |
| `GITBASE` | Yes | Base Git URL for `repo envsubst` (e.g., `https://github.com/your-org/`) |
| `CLAUDE_MARKETPLACES_DIR` | Conditional | Directory for marketplace symlinks (required when `RPM_MARKETPLACE_INSTALL=true`) |
| `RPM_MARKETPLACE_INSTALL` | No | Boolean toggle for marketplace lifecycle (default: `false`) |

### Source Variables

Sources are auto-discovered from `RPM_SOURCE_<name>_URL` variable patterns and processed in alphabetical order by name. Each source requires three variables:

| Variable | Required | Purpose |
|---|---|---|
| `RPM_SOURCE_<name>_URL` | Yes | Git URL for the named source's manifest repository |
| `RPM_SOURCE_<name>_REVISION` | Yes | Branch, exact tag, or PEP 440 constraint (e.g. `refs/tags/~=1.1.0`) for the named source |
| `RPM_SOURCE_<name>_PATH` | Yes | Path to the entry-point manifest XML for the named source |

### Environment Variables

| Variable | Purpose |
|---|---|
| `RPM_CATALOG_SOURCE` | Remote catalog source for `rpm bootstrap` as `<git_url>@<ref>`. Overridden by `--catalog-source` flag. |

### Example .rpmenv

```properties
# Repo Tool (fork with envsubst support)
REPO_URL=https://github.com/your-org/git-repo.git
REPO_REV=v2.0.0

# Shared env vars for envsubst
GITBASE=https://github.com/your-org/
CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces

# Marketplace install toggle
RPM_MARKETPLACE_INSTALL=true

# Source: build -- build tooling packages
RPM_SOURCE_build_URL=https://github.com/your-org/rpm-manifests.git
RPM_SOURCE_build_REVISION=main
RPM_SOURCE_build_PATH=repo-specs/build/meta.xml

# Source: marketplaces -- plugin marketplaces
RPM_SOURCE_marketplaces_URL=https://github.com/your-org/rpm-manifests.git
RPM_SOURCE_marketplaces_REVISION=main
RPM_SOURCE_marketplaces_PATH=repo-specs/marketplaces/meta.xml
```

---

## Architecture

```text
                    ┌─────────────────────────┐
                    │     RPM CLI             │
                    │  (configure / clean /   │
                    │   bootstrap / validate) │
                    └───────────┬─────────────┘
                                │
               defines          │            uses
                                v
              ┌────────────────────────────────────────┐
              │       Manifest Repository              │
              │  - Top-level dependency manifests      │
              │  - Declares relationships between      │
              │    domain and automation repos         │
              └──────────────────┬─────────────────────┘
                                 │
        references               │                references
                                 │
             v                                       v
┌───────────────────────┐                ┌────────────────────────┐
│  Package Repositories │                │ Automation Repositories│
│ (build conventions,   │                │ (shared tasks,         │
│  linting, security)   │                │  validation, scanning) │
└────────────┬──────────┘                └───────────┬────────────┘
             │                                       │
             └───────────────────┬───────────────────┘
                                 │
                                 v
                   ┌────────────────────────────┐
                   │  Gerrit `repo` Tool Fork   │
                   │ (git-repo with envsubst +  │
                   │  PEP 440 constraints)      │
                   │ Executes manifests, syncs  │
                   │ repos, manages workspace   │
                   └────────────────────────────┘
```

### How It Works

RPM uses [a fork of the Gerrit `repo` tool](https://github.com/caylent-solutions/git-repo) (with `envsubst` support) to orchestrate dependencies across Git repositories. Manifests define what to clone, where to place it, and how to wire it together.

The configure lifecycle follows three steps per source:

1. **`repo init`** -- Clones the manifest repository. `${VARIABLE}` placeholders remain as-is in the XML.
2. **`repo envsubst`** -- Reads variables from `.rpmenv` (e.g., `GITBASE`) and replaces `${VARIABLE}` placeholders in all manifest XML files.
3. **`repo sync`** -- Clones packages using the now-resolved URLs into `.packages/`.

After all sources are synced, RPM aggregates their packages into a single `.packages/` directory using symlinks, giving consumers a unified view regardless of which source provided each package.

### Directory Structure After Configure

```text
project/
  .rpmenv                           # Configuration (committed)
  Makefile                          # Task runner (committed, optional)
  .rpm/                             # RPM state (gitignored)
    sources/
      build/                        # Isolated source workspace
        .repo/
        .packages/
          my-build-conventions/
      marketplaces/                 # Isolated source workspace
        .repo/
        .packages/
          my-marketplace-plugin/
  .packages/                        # Aggregated symlinks (gitignored)
    my-build-conventions -> ../.rpm/sources/build/.packages/my-build-conventions
    my-marketplace-plugin -> ../.rpm/sources/marketplaces/.packages/my-marketplace-plugin
```

### Multi-Source Isolation

Each source is initialized and synced in its own isolated directory under `.rpm/sources/<name>/`. Sources cannot interfere with each other -- each gets its own `repo init` / `repo sync` cycle. If two sources produce a package with the same name, RPM detects the collision and fails immediately with an actionable error message.

### Environment Variable Portability (envsubst)

The `envsubst` feature makes manifests portable across organizations. Instead of hard-coding Git URLs in manifest XML, you use `${GITBASE}` placeholders:

```xml
<!-- Portable -- resolved from .rpmenv at configure time -->
<remote name="origin" fetch="${GITBASE}"/>
```

Adopting RPM for a different organization means changing one line in `.rpmenv`:

```properties
GITBASE=https://github.com/your-company/
```

CI/CD pipelines can override this via environment variables without modifying `.rpmenv`:

```bash
GITBASE=https://git.internal.company.com/ rpm configure .rpmenv
```

For full documentation, see [docs/how-it-works.md](docs/how-it-works.md).

---

## Creating a Manifest Repository

A manifest repository contains `repo-specs/` with XML manifests that define what packages to sync, from which repositories, and at which versions. It uses the [git-repo manifest format](https://gerrit.googlesource.com/git-repo/+/HEAD/docs/manifest-format.md).

### Structure

```text
my-manifest-repo/
  repo-specs/
    git-connection/
      remote.xml             # Defines Git remotes with ${GITBASE} placeholders
    my-archetype/
      meta.xml               # Entry-point: includes remote.xml + packages.xml
      packages.xml           # Lists package repos with pinned versions
```

### remote.xml -- Git Remote Definition

Defines where packages are hosted using `${GITBASE}` for portability:

```xml
<manifest>
  <remote name="origin" fetch="${GITBASE}" />
  <default remote="origin" revision="refs/tags/1.0.0" />
</manifest>
```

### packages.xml -- Package Declarations

Lists each package repository, its local path, and the pinned version:

```xml
<manifest>
  <include name="repo-specs/git-connection/remote.xml" />

  <project name="my-build-conventions"
           path=".packages/my-build-conventions"
           remote="origin"
           revision="refs/tags/1.0.0" />

  <project name="my-lint-config"
           path=".packages/my-lint-config"
           remote="origin"
           revision="refs/tags/2.1.0" />
</manifest>
```

### meta.xml -- Entry Point

Combines all includes into a single entry point referenced by `.rpmenv`:

```xml
<manifest>
  <include name="repo-specs/my-archetype/packages.xml" />
</manifest>
```

### Include Chains for Hierarchy

Manifests can include other manifests via `<include>` tags, forming a hierarchy. This enables cascading configurations where common packages are defined once and specialized packages are layered on top:

```text
meta.xml
  └── packages.xml (leaf -- e.g., specific project type)
        └── packages.xml (framework level)
              └── packages.xml (language level)
                    └── packages.xml (common/base)
```

Each level includes its parent and adds its own package entries. The `repo` tool recursively resolves all includes, accumulating a unified set of packages.

### Updating Package Versions

1. Tag the package repository with the new semver version
2. Update the `revision` attribute in the corresponding `packages.xml`
3. Run `rpm validate xml` to verify manifests remain valid
4. Tag and push the manifest repository

Projects pick up the new versions on next `rpm configure .rpmenv`.

For more details, see [docs/contributing.md](docs/contributing.md).

---

## Creating Packages

A package is a Git repository containing automation scripts (Makefile targets, Gradle scripts, configuration files, etc.) tagged with semver versions. RPM syncs packages to `.packages/` where task runners can discover and apply them.

### Package Structure

```text
my-package/
  automation-script.gradle    # Or Makefile, shell script, config files, etc.
  config/                     # Optional: configuration files
  README.md                   # Package documentation
  CHANGELOG.md                # Version history
```

### Versioning

Use [semantic versioning](https://semver.org/) with Git tags:

- **MAJOR** -- Breaking changes (renamed tasks, removed config, changed behavior)
- **MINOR** -- New features (new tasks, new config options)
- **PATCH** -- Bug fixes (corrected config, fixed task behavior)

```bash
git tag -a 1.0.0 -m "Release 1.0.0"
git push origin 1.0.0
```

### Registering a Package

Add the package to a manifest's `packages.xml`:

```xml
<project name="my-package"
         path=".packages/my-package"
         remote="origin"
         revision="refs/tags/1.0.0" />
```

### Symlinks via linkfile

Some packages contain assets (configuration files, templates) that tools expect at conventional paths. The `<linkfile>` element creates symlinks from the package directory to the project root:

```xml
<project name="my-lint-config"
         path=".packages/my-lint-config"
         remote="origin"
         revision="refs/tags/1.0.0">
  <linkfile src="config/checkstyle/checkstyle.xml"
            dest="config/checkstyle/checkstyle.xml" />
</project>
```

After `repo sync`, the project has `config/checkstyle/checkstyle.xml` as a symlink pointing into `.packages/`. These symlinked paths should be gitignored since they are regenerated by `rpm configure`.

### Gradle Package Specifics

Gradle packages contain `.gradle` scripts that are auto-applied by the bootstrap script. Scripts access their own directory via:

```groovy
def PKG_DIR = project.ext.get('_rpmCurrentPkgDir')
```

If a package needs external Gradle plugins, declare them in `rpm-manifest.properties`:

```properties
buildscript.dependencies=org.some.group:some-plugin:1.2.3
```

---

## Creating Marketplace Packages

Marketplace packages use `<linkfile>` symlinks to expose plugins to Claude Code. They follow a cascading manifest hierarchy where each level includes its parent, enabling shared tools across project types while adding specialized plugins at each level.

### Marketplace Manifest Structure

```xml
<manifest>
  <!-- Include the parent level -->
  <include name="repo-specs/common/parent-level/claude-marketplaces.xml" />

  <!-- Add this level's marketplace project -->
  <project name="my-marketplace-packages"
           path=".packages/my-marketplace-dev-lint"
           remote="origin"
           revision="refs/tags/development/dev-lint/1.0.0">
    <linkfile src="development/dev-lint"
              dest="${CLAUDE_MARKETPLACES_DIR}/my-marketplace-dev-lint" />
  </project>
</manifest>
```

### Key Requirements

- All `<linkfile dest>` attributes must start with `${CLAUDE_MARKETPLACES_DIR}/`
- Each `<project path>` must be unique across all manifests
- The `RPM_MARKETPLACE_INSTALL` flag in `.rpmenv` must be set to `true`
- `CLAUDE_MARKETPLACES_DIR` must be defined in `.rpmenv`

### Cascading Hierarchy

```text
meta.xml
  └── claude-marketplaces.xml (leaf, e.g. specific CLI tool)
        └── claude-marketplaces.xml (framework)
              └── claude-marketplaces.xml (toolchain)
                    └── claude-marketplaces.xml (language)
                          └── claude-marketplaces.xml (category)
                                └── claude-marketplaces.xml (common/root)
```

Different project types (Python, Go, Node) share common tools (linting, CI/CD) while adding specialized marketplaces at their own level. Adding a new marketplace at any level automatically propagates to all descendants.

### Validation

```bash
rpm validate marketplace
```

This checks linkfile destination prefixes, include chain integrity, project path uniqueness, and revision format validity.

For full documentation, see [docs/claude-marketplaces-guide.md](docs/claude-marketplaces-guide.md).

---

## Fork Features (PEP 440 Constraints)

RPM uses a [fork of the Gerrit `repo` tool](https://github.com/caylent-solutions/git-repo) that adds two features beyond upstream:

### PEP 440 Version Constraints in Manifests

Standard `repo` requires `<project revision>` to be a branch, tag, or commit SHA. The fork accepts [PEP 440](https://peps.python.org/pep-0440/) version constraint syntax, resolving the best matching tag at sync time.

#### How It Works

The resolver splits the `revision` attribute at the last `/` into a tag-path prefix and a constraint. It filters available tags by that prefix, evaluates the constraint, and returns the highest matching version.

```text
revision="refs/tags/example/development/dev-lint/~=1.2.0"
         |------------- prefix ----------------| |- constraint -|

1. Filter tags starting with  refs/tags/example/development/dev-lint/
2. Parse version suffixes:    1.0.0, 1.2.0, 1.2.3, 1.3.0, 2.0.0
3. Evaluate ~=1.2.0:          1.2.0   1.2.3   (others excluded)
4. Return highest match:      refs/tags/example/development/dev-lint/1.2.3
```

#### Supported Constraint Types

| Operator | Syntax | Meaning |
|---|---|---|
| Patch-compatible | `~=1.2.0` | `>=1.2.0, <1.3.0` (any patch in 1.2.x) |
| Range | `>=1.0.0,<2.0.0` | Any version from 1.0.0 up to (not including) 2.0.0 |
| Wildcard | `*` | Any available version (selects the latest) |
| Exact | `==1.2.3` | Only version 1.2.3 |
| Minimum | `>=1.0.0` | 1.0.0 or higher |
| Exclusion | `!=1.0.1` | Any version except 1.0.1 |

#### XML Escaping

The `<` character must be escaped as `&lt;` in XML attribute values:

```xml
<project name="my-package"
         path=".packages/my-package"
         remote="origin"
         revision="refs/tags/my-package/>=1.0.0,&lt;2.0.0" />
```

### PEP 440 Version Resolution in .rpmenv

The CLI supports PEP 440 constraint syntax in both `REPO_REV` and `RPM_SOURCE_<name>_REVISION` in `.rpmenv`. Constraints are resolved against available git tags before being passed to the underlying tools.

#### Supported Operators

| Operator | Syntax | Meaning |
|---|---|---|
| Compatible release | `~=1.2.0` | `>=1.2.0, <1.3.0` |
| Range | `>=1.0.0,<2.0.0` | Any version in range |
| Exact | `==1.2.3` | Only 1.2.3 |
| Minimum | `>=1.0.0` | 1.0.0 or higher |
| Exclusion | `!=1.0.1` | Any version except 1.0.1 |
| Wildcard | `*` | Latest available |

Plain strings without PEP 440 operators pass through unchanged.

#### Prefixed Constraints (RPM_SOURCE_\<name\>_REVISION)

Source revisions support an optional `refs/tags/` prefix. This is recommended because the resolved value is passed to `repo init -b`, which accepts full ref paths:

```properties
# Resolves to refs/tags/1.1.2 — works directly with repo init -b
RPM_SOURCE_build_REVISION=refs/tags/~=1.1.0

# Namespaced — only considers tags under that path
RPM_SOURCE_build_REVISION=refs/tags/dev/python/my-lib/~=1.2.0

# Also supported — resolves against all tags
RPM_SOURCE_build_REVISION=~=1.1.0
```

For full details, see [docs/version-resolution.md](docs/version-resolution.md).

### Absolute Linkfile Destinations

Standard `repo` restricts `<linkfile dest>` to relative paths within the workspace. The fork accepts absolute paths after `envsubst` expansion, enabling marketplace symlinks to directories outside the project (e.g., `${CLAUDE_MARKETPLACES_DIR}/...`).

---

## Developer Setup

### Prerequisites

- Python 3.11+
- pipx

### Install from Source

```bash
make install-dev
```

### Set Up Git Hooks

```bash
make install-hooks
```

### Run Tests

```bash
make test          # All tests
make test-unit     # Unit tests only
make test-cov      # Tests with coverage report
```

### Build

```bash
make publish       # Clean, build, and check distribution
```

### Project Structure

```text
src/rpm_cli/
  cli.py              # Entry point
  commands/            # Subcommand implementations (bootstrap, configure, clean, validate)
  core/                # Core logic (configure, clean, rpmenv parsing, version resolution)
  catalog/             # Bundled catalog (fallback templates for rpm bootstrap)
tests/                 # Unit and functional tests
docs/                  # Configuration, lifecycle, version resolution documentation
pyproject.toml         # Package config (hatchling build, entry point: rpm)
```

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for commit conventions, PR process, and how the automated release pipeline works.

### CI/CD Pipeline

This project uses a fully automated SDLC pipeline:

1. **PR Validation** -- Lint, build, test (90% coverage), security scan on every PR
2. **Main Branch Validation** -- Full validation + CodeQL on merge to main
3. **Manual QA Approval** -- Human gate before release
4. **Automated Release** -- Semantic versioning from conventional commit prefixes, changelog generation, tagging
5. **PyPI Publishing** -- Automated publish via OIDC trusted publishing

PR titles must follow [Conventional Commits](https://www.conventionalcommits.org/) format (e.g., `feat: add feature`, `fix: resolve bug`) as they drive automatic version bumps.

---

## Documentation

- [How It Works](docs/how-it-works.md) -- Technical deep-dive into RPM internals
- [Setup Guide](docs/setup-guide.md) -- Step-by-step setup for new and existing projects
- [RPM Guide](docs/rpm-guide.md) -- Comprehensive guide for engineers new to this pattern
- [Multi-Source Guide](docs/multi-source-guide.md) -- Configuring multiple manifest sources
- [Claude Marketplaces Guide](docs/claude-marketplaces-guide.md) -- Marketplace architecture and plugin lifecycle
- [Pipeline Integration](docs/pipeline-integration.md) -- Using RPM tasks in CI/CD pipelines
- [Contributing](docs/contributing.md) -- How to create and maintain RPM packages and marketplaces
- [Version Resolution](docs/version-resolution.md) -- PEP 440 resolver details
- [Configuration](docs/configuration.md) -- .rpmenv format and variable expansion
- [Lifecycle](docs/lifecycle.md) -- Configure and clean lifecycle step-by-step

---

## License

Apache 2.0. See [LICENSE](LICENSE).
