# Kanon (Kanon Package Manager)

A standalone Python CLI for managing versioned DevOps automation packages
via declarative manifests.

**License:** Apache 2.0

---

## Table of Contents

- [Platform support](#platform-support)
- [Quick Start: Find and Add Dependencies](#quick-start-find-and-add-dependencies)
- [Tab Completion](#tab-completion)
- [Subcommands](#subcommands)
- [Git Authentication](#git-authentication)
- [Migration from kanon bootstrap](#migration-from-kanon-bootstrap)
- [What is Kanon?](#what-is-kanon)
  - [Fully customizable](#fully-customizable)
  - [Core Purpose](#core-purpose)
- [Use Cases](#use-cases)
  - [Unify Disparate Automation](#unify-disparate-automation)
  - [Platform Engineering](#platform-engineering)
  - [Multi-Project Consistency](#multi-project-consistency)
- [Quick Start](#quick-start)
  - [Prerequisites](#prerequisites)
  - [Install the Kanon CLI](#install-the-kanon-cli)
  - [Standalone Usage (No Task Runner Required)](#standalone-usage-no-task-runner-required)
  - [Integrating with Task Runners (Optional)](#integrating-with-task-runners-optional)
- [CLI Reference](#cli-reference)
  - [kanon search](#kanon-search)
  - [kanon add](#kanon-add)
  - [kanon remove](#kanon-remove)
  - [kanon install](#kanon-install)
  - [kanon clean](#kanon-clean)
  - [kanon outdated](#kanon-outdated)
  - [kanon why](#kanon-why)
  - [kanon doctor](#kanon-doctor)
  - [kanon validate](#kanon-validate)
  - [kanon catalog audit](#kanon-catalog-audit)
  - [kanon repo](#kanon-repo)
  - [kanon completion](#kanon-completion)
  - [kanon bootstrap (removed in 3.0.0)](#kanon-bootstrap-removed-in-300)
- [.kanon Variable Reference](#kanon-variable-reference)
  - [Core Variables](#core-variables)
  - [Source Variables](#source-variables)
  - [Environment Variables](#environment-variables)
  - [Example .kanon](#example-kanon)
- [Architecture](#architecture)
  - [How It Works](#how-it-works)
  - [Directory Structure After Install](#directory-structure-after-install)
  - [Multi-Source Isolation](#multi-source-isolation)
  - [Environment Variable Portability (envsubst)](#environment-variable-portability-envsubst)
- [Creating a Manifest Repository](#creating-a-manifest-repository)
  - [Structure](#structure)
  - [Catalog entry](#catalog-entry)
  - [remote.xml -- Git Remote Definition](#remotexml----git-remote-definition)
  - [packages.xml -- Package Declarations](#packagesxml----package-declarations)
  - [Entry-point manifest](#entry-point-manifest)
  - [Include Chains for Hierarchy](#include-chains-for-hierarchy)
  - [Updating Package Versions](#updating-package-versions)
- [Creating Packages](#creating-packages)
  - [Package Structure](#package-structure)
  - [Versioning](#versioning)
  - [Registering a Package](#registering-a-package)
  - [Symlinks via linkfile](#symlinks-via-linkfile)
- [Creating Marketplace Packages](#creating-marketplace-packages)
  - [Marketplace Manifest Structure](#marketplace-manifest-structure)
  - [Key Requirements](#key-requirements)
  - [Cascading Includes](#cascading-includes)
  - [Validation](#validation)
- [Manifest Features (PEP 440 Constraints)](#manifest-features-pep-440-constraints)
  - [PEP 440 Version Constraints in Manifests](#pep-440-version-constraints-in-manifests)
  - [PEP 440 Version Resolution in .kanon](#pep-440-version-resolution-in-kanon)
  - [Absolute Linkfile Destinations](#absolute-linkfile-destinations)
- [SSH Authentication Setup](#ssh-authentication-setup)
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

## Platform support

Kanon runs on macOS and Linux. **Windows is not currently supported
(planned).** Native Windows support is on the roadmap but not yet
available; in the meantime, run kanon under WSL2 (Windows Subsystem for
Linux), where the Linux instructions throughout this documentation apply
unchanged.

The shell-completion docs describe a cross-platform PowerShell Core
(`pwsh`) completer that also runs on macOS and Linux; see
[docs/shell-completion.md](docs/shell-completion.md). PowerShell Core
support is not a claim of native Windows support.

---

## Quick Start: Find and Add Dependencies

The following five-step workflow shows how to discover, inspect, add, and
install a dependency from a remote manifest catalog -- using the placeholder
URL `https://example.com/org/manifest-repo.git@main` throughout.

**Step 1: Discover available packages.**

```bash
kanon search --catalog-source 'https://example.com/org/manifest-repo.git@main'
```

Lists every package declared in the remote catalog so you can see what is
available.

**Step 2: Inspect a package.**

```bash
kanon search my-package \
  --catalog-source 'https://example.com/org/manifest-repo.git@main' \
  --detail
```

Shows the full metadata for `my-package` -- version history, description,
and source URL.

**Step 3: Add the package at a pinned version.**

```bash
kanon add 'my-package@==1.2.3' \
  --catalog-source 'https://example.com/org/manifest-repo.git@main'
```

Writes `my-package@==1.2.3` into your `.kanon` manifest file. The `==`
prefix pins to an exact version; PEP 440 range constraints (e.g., `~=1.2.0`,
`>=1.0.0,<2.0.0`) are also accepted.

**Step 4: Install (first run writes `.kanon.lock`).**

```bash
kanon install
```

`kanon install` is hermetic: it resolves the declared packages from the
committed `.kanon` (it does not re-read the catalog), clones them into the
shared `KANON_HOME` store under `.kanon-data/sources/`, aggregates symlinks
under `.packages/` in that store, and writes `.kanon.lock` with exact
resolved versions so every subsequent install is reproducible.

**Step 5: Commit both `.kanon` and `.kanon.lock`.**

```bash
git add .kanon .kanon.lock
git commit -m "feat: add my-package 1.2.3"
```

Committing both files ensures the entire team installs the same resolved
package versions. The synced artifacts live in the shared `KANON_HOME`
store (`~/.kanon` by default), never in your project, so there is nothing
package-related to commit beyond `.kanon` and `.kanon.lock`.

---

## Tab Completion

Kanon ships built-in shell completion for bash, zsh, and PowerShell Core
(`pwsh`) via the `kanon completion <shell>` subcommand. Run
`eval "$(kanon completion bash)"` (or `zsh`) once in your shell session, or
add it to your shell RC file, to enable tab-completion of subcommand names,
flags, and catalog entries. For PowerShell, pipe
`kanon completion powershell` into `Out-String | Invoke-Expression`. For
persistent installation and advanced options, see
[docs/shell-completion.md](docs/shell-completion.md).

---

## Subcommands

| Subcommand | Summary | Doc |
| --- | --- | --- |
| `kanon search` | List packages available in a catalog or show detail for one | [docs/list-and-add.md](docs/list-and-add.md) |
| `kanon add` | Add a package (with optional version constraint) to `.kanon` | [docs/list-and-add.md](docs/list-and-add.md) |
| `kanon remove` | Remove a package from `.kanon` | [docs/list-and-add.md](docs/list-and-add.md) |
| `kanon outdated` | Show packages in `.kanon` that have newer versions available | [docs/outdated-and-why.md](docs/outdated-and-why.md) |
| `kanon why` | Explain why a specific package version was resolved | [docs/outdated-and-why.md](docs/outdated-and-why.md) |
| `kanon install` | Resolve, clone, and symlink all packages; writes `.kanon.lock` | [docs/lockfile.md](docs/lockfile.md) |
| `kanon doctor` | Diagnose the local Kanon installation and report problems | [docs/doctor.md](docs/doctor.md) |
| `kanon catalog audit` | Audit a catalog for missing or malformed entries | [docs/catalog-author-guide.md](docs/catalog-author-guide.md) |
| `kanon validate xml` | Validate XML manifests under `repo-specs/` | [docs/repo/manifest-format.md](docs/repo/manifest-format.md) |
| `kanon validate marketplace` | Validate marketplace XML manifests under `repo-specs/` | [docs/repo/manifest-format.md](docs/repo/manifest-format.md) |
| `kanon validate metadata` | Validate catalog entry metadata | [docs/catalog-author-guide.md](docs/catalog-author-guide.md) |
| `kanon clean` | Remove synced packages and Kanon state (`--orphans` also prunes unreferenced marketplaces) | [docs/lifecycle.md](docs/lifecycle.md) |
| `kanon repo` | Low-level manifest-driven repo sync subsystem | [docs/repo/README.md](docs/repo/README.md) |
| `kanon marketplace` | Manage the per-dependency Claude marketplace install flag in `.kanon` (`enable` / `disable` / `status`) | [docs/configuration.md](docs/configuration.md) |
| `kanon completion` | Emit a shell completion script for bash, zsh, or powershell | [docs/shell-completion.md](docs/shell-completion.md) |
| `kanon bootstrap` | **removed in 3.0.0** -- not a registered subcommand (argparse `invalid choice`, exit 2); use `kanon search` / `kanon add` instead | [docs/migration-to-add.md](docs/migration-to-add.md) |

---

## Git Authentication

Kanon uses the `git` binary for all remote operations and never prompts for
credentials or caches them itself -- authentication is delegated entirely to
the operator's git client (SSH keys, credential helpers, `GIT_TOKEN`, etc.).
For setup instructions covering SSH key forwarding, HTTPS token helpers, and
URL rewriting for private Git hosts, see
[docs/git-auth-setup.md](docs/git-auth-setup.md).

---

## Migration from kanon bootstrap

The `kanon bootstrap` subcommand was removed in kanon 3.0.0 (a breaking
change) -- it is no longer a registered subcommand, so `kanon bootstrap`
exits non-zero with an argparse `invalid choice` error. Its
catalog-discovery and project-scaffolding responsibilities have been
replaced by `kanon search` (discover and inspect packages) and `kanon add`
(add a pinned dependency to `.kanon`). If your workflow currently uses
`kanon bootstrap <entry>`, the
[docs/migration-to-add.md](docs/migration-to-add.md)
guide walks through the equivalent `kanon search` + `kanon add` + `kanon
install` steps and explains the lockfile model that replaces hand-editing
`.kanon`.

---

## What is Kanon?

Kanon is a **DevOps Platform Dependency Manager** that brings
version-controlled, reproducible automation to your projects through
declarative manifests. Kanon enables you to centralize, version, and share
automation across your organization without replacing your existing tools.

**Solves a common problem:** Organizations have quality automation and operational knowledge scattered across teams -- build conventions, linting rules, security scanning, test frameworks, local dev tooling, and shared markdown documentation that work well but are not widely adopted because they are hard to discover, version, test, and distribute. Kanon enables you to package this automation and share it across projects in a tested, reproducible way.

### Fully customizable

- **Public or Private** -- Use public repositories or host everything privately within your organization
- **Your Infrastructure** -- Point to your own Git repositories and package sources
- **Your Standards** -- Define your own manifests, packages, and automation
- **Portable** -- Teams retain access to automation even after external partnerships end

### Core Purpose

- **Platform Dependency Management** -- Centralize and version your DevOps automation, shared knowledge, dependencies, and standards
- **Flexible Overlay** -- Works alongside your preferred build tools and dependency managers, or standalone with no task runner at all
- **Team Standards** -- Share tested, versioned automation, tasks, and approaches across teams dynamically
- **Tool Agnostic** -- Adapts to your workflow, not the other way around

## Use Cases

### Unify Disparate Automation

Your organization has quality automation scattered across teams -- testing frameworks, linting configs, deployment scripts, security scans -- but they are not widely adopted because they are hard to find, version, and integrate. Kanon lets you package this automation, version it, and make it available to all teams through simple manifests.

### Platform Engineering

Provide golden paths and paved roads to development teams. Package your organization's standards, policies, automation, and shared operational knowledge as versioned dependencies that teams can pull into their projects.

This can include CI/CD workflows, security policies, deployment automation, coding standards, architecture guidance, operational runbooks, and shared markdown knowledge bases used by both developers and AI coding agents.

### Multi-Project Consistency

Ensure the same testing, linting, security scanning, and deployment automation across projects without copy-pasting or manual synchronization.

---

## Quick Start

### Prerequisites

- Python 3.11+
- [pipx](https://pipx.pypa.io/) on PATH
  (`python3 -m pip install --user pipx && pipx ensurepath`)
- Git
- If authenticating with Git via SSH, see
  [SSH Authentication Setup](#ssh-authentication-setup)

### Install the Kanon CLI

`kanon-cli` is published to [PyPI](https://pypi.org/project/kanon-cli/). The
recommended install method depends on the use case:

**Production / general use** -- isolated CLI install via pipx:

```bash
pipx install kanon-cli
```

**Local development on this repository** -- editable install into the
project's virtualenv:

```bash
pip install -e .
```

(Editable mode lets local source edits take effect immediately without
reinstalling. CI uses `pip install kanon-cli` for ephemeral runners; see
`docs/pipeline-integration.md`.)

### Standalone Usage (No Task Runner Required)

Kanon works directly from the command line. No task runner is needed. The
workflow is declarative: you discover entries in a remote catalog, add the
ones you want to `.kanon`, install them, and (optionally) clean up. Every
command that resolves a catalog needs a catalog source -- either the
`--catalog-source <url>@<ref>` flag or the `KANON_CATALOG_SOURCES`
environment variable.

```bash
# Set once in your shell rc file -- pin to the current major version
export KANON_CATALOG_SOURCES='https://github.com/your-org/your-catalog-repo.git@>=2.0.0,<3.0.0'
```

**1. Discover entries in the catalog:**

```bash
kanon search                   # all entry names, one per line
kanon search --detail          # human-readable record per entry
kanon search my-tool --detail  # narrow to entries matching a substring
```

`kanon search` reads the catalog entry manifests (any `repo-specs/**/*.xml`
file with a `<catalog-metadata>` block) in the manifest repo and prints one
catalog entry name per line.

**2. Add entries to `.kanon`:**

```bash
kanon add my-tool                       # pin to the highest available version
kanon add 'my-tool@>=1.0.0,<2.0.0'      # pin with a PEP 440 constraint
kanon add my-tool --marketplace-install # also enable the marketplace lifecycle
```

`kanon add` resolves each entry against the catalog and writes the
alias-keyed `KANON_SOURCE_<alias>_{URL,REF,PATH,NAME}` block into
`.kanon` (plus one optional `KANON_SOURCE_<alias>_<VAR>` env-var line per
`${VAR}` the entry's manifest references -- `GITBASE` auto-derived, others
empty -- and a `_MARKETPLACE=true` line for marketplace entries),
creating the file when it does not yet exist. There is no global header.

**3. Install (sync all packages, write `.kanon.lock`):**

```bash
kanon install
```

`kanon install` is hermetic: it reads only the committed `.kanon` and
`.kanon.lock` (it does not accept `--catalog-source` and ignores
`KANON_CATALOG_SOURCES`). It reconciles `.kanon` against `.kanon.lock`,
runs the repo init/envsubst/sync lifecycle for every source, aggregates
packages into `.packages/` via symlinks under the shared `KANON_HOME`
store, creates source workspaces under `.kanon-data/sources/` in that
store, and writes `.kanon.lock` with the exact resolved SHAs.

**4. Clean (full teardown):**

```bash
kanon clean              # remove .packages/, .kanon-data/, marketplace dir
kanon clean --orphans    # also prune kanon-owned marketplaces no longer referenced
```

`kanon clean` removes this project's synced packages and Kanon state from
the shared `KANON_HOME` store, prunes the content-addressed entries it no
longer references, and (for any source with
`KANON_SOURCE_<alias>_MARKETPLACE=true`) uninstalls marketplace plugins.

**Important:** All synced artifacts live in the shared `KANON_HOME` store
and are never committed. Commit only `.kanon` and `.kanon.lock` to your
repository.

The `@<ref>` portion of a catalog source accepts a branch name, a tag, the
special value `latest` (which resolves to the highest PEP 440 tag), or a PEP
440 version constraint (e.g., `~=2.0.0`, `>=2.0.0,<3.0.0`). Version
constraints are resolved against the repository's git tags via
`git ls-remote`. The manifest repo IS the catalog: every `repo-specs/**/*.xml`
file carrying a `<catalog-metadata>` block is one catalog entry (the
`-marketplace.xml` suffix is a convention, not a requirement). There is no
separate `catalog/` directory.

Manifest repositories should use [semantic versioning](https://semver.org/)
for git tags. Pinning to a major version range (e.g., `>=2.0.0,<3.0.0`)
allows automatic pickup of minor and patch releases while preventing
unexpected breaking changes.

### Integrating with Task Runners (Optional)

Kanon works standalone via `kanon install` and `kanon clean`. You can wrap
these commands in any build tool or task runner by creating targets that
delegate to the CLI.

### Tab Completion

Kanon ships with built-in shell completion for bash, zsh, and PowerShell
Core (`pwsh`) via the `kanon completion <shell>` subcommand. The generated
script enables tab-completion of subcommand names and flags in your shell
session.

**Quick setup:**

```bash
# bash -- add to ~/.bashrc or source once in your current session
eval "$(kanon completion bash)"

# zsh -- add to ~/.zshrc
eval "$(kanon completion zsh)"
```

```powershell
# PowerShell -- add to your $PROFILE
kanon completion powershell | Out-String | Invoke-Expression
```

For persistent installation and advanced options (system-wide install,
oh-my-zsh), see `docs/shell-completion.md`.

---

## CLI Reference

```bash
kanon --help                              # Top-level help
kanon --version                           # Show version
```

Run `kanon <command> --help` for the full option list of any command. The
sections below summarise each command. A catalog source (the
`--catalog-source <url>@<ref>` flag or a single `KANON_CATALOG_SOURCES`
entry) is required by `search`, `add`, `outdated`, `why`, and
`catalog audit`. `install` is hermetic: it reads only `.kanon` and
`.kanon.lock`, does not accept `--catalog-source`, and has no lock
`[catalog]` fallback.

### kanon search

Discovers catalog entries. Prints one entry name per line to stdout, sorted
lexicographically, by reading the catalog entry manifests (any
`repo-specs/**/*.xml` file carrying a `<catalog-metadata>` block) in the
catalog source.

```bash
kanon search                       # all entry names
kanon search foo                   # substring filter (name/desc/keywords)
kanon search --regex '^foo'        # regex filter
kanon search --detail              # human-readable record per entry
kanon search --format json         # structured JSON array
kanon search --tree                # three-layer ASCII dependency tree
kanon search -A                    # walk historical tagged versions
```

Key options: `--format {names,json}`, `--detail`, `--tree` (with
`--max-depth N`, `--no-filter-required`), `-A`/`--all` (with `--limit N`,
`--no-limit`, `--since-version <spec>`), `--regex <pattern>`,
`--match-fields <csv>`. A positional `<substring>` and `--regex` are mutually
exclusive; `--format json` is incompatible with `--tree`.

### kanon add

Resolves catalog entries from the catalog source and appends the alias-keyed
`KANON_SOURCE_<alias>_{URL,REF,PATH,NAME}` block to `.kanon` (plus one optional
`KANON_SOURCE_<alias>_<VAR>` env-var line per `${VAR}` the entry's manifest
references and a `_MARKETPLACE=true` line for marketplace entries), creating the
file when absent. There is no global header.

```bash
kanon add my-tool                       # pin to highest PEP 440 tag
kanon add 'my-tool@>=1.0.0,<2.0.0'      # pin with a PEP 440 constraint
kanon add my-tool --marketplace-install # enable the marketplace lifecycle
kanon add my-tool --dry-run             # print the diff without writing
```

Each entry is `<name>` or `<name>@<spec>` (PEP 440 constraint). Key options:
`--as <alias>` (override the auto-computed alias), `--kanon-file <path>`
(default `./.kanon`, env `KANON_KANON_FILE`), `--force` (overwrite an existing
block), `--dry-run`, and the mutually-exclusive `--marketplace-install` /
`--no-marketplace-install` (force the added dependency's marketplace flag,
overriding the auto-detected `<catalog-metadata><type>`).

### kanon remove

Removes the alias-keyed `KANON_SOURCE_<alias>_*` block (the structural `_URL`,
`_REF`, `_PATH`, `_NAME`, plus any optional per-dependency env-var line such as
`_GITBASE` and the optional `_MARKETPLACE`) for one or more entries from
`.kanon`.

```bash
kanon remove my-tool                      # canonical source OR entry name
kanon remove my-tool --dry-run            # preview removed lines
kanon remove my-tool --force              # skip not-fully-present sources
```

Each `<name>` may be the canonical source alias (e.g. `foo_bar`) or the
original entry name (e.g. `Foo-Bar`); both normalise to the same keys.
Removal is atomic: if any requested name is not fully present (fewer than
the expected number of block keys) and `--force` is not set, the command
exits non-zero and the file is unchanged.

### kanon install

Executes the full install lifecycle and reconciles `.kanon` against
`.kanon.lock`.

```bash
kanon install                     # auto-discover .kanon by walking up from cwd
kanon install .kanon              # explicit path to .kanon file
kanon install --reconcile         # opt in to prune/re-resolve when .kanon and .kanon.lock drift
kanon install --strict-lock       # error when an orphaned lock entry survives a hash match
kanon install --strict-drift      # error when a branch source has drifted
kanon install --refresh-lock      # re-resolve every transitive version from scratch
kanon install --refresh-lock-source NAME  # re-resolve one source's chain only
```

**Behavior:**

- Parses `.kanon`, then runs the repo init/envsubst/sync lifecycle for each
  source (alphabetical order).
- Aggregates packages into `.packages/` via symlinks under the shared
  `KANON_HOME` store; detects cross-source name collisions (fail-fast). When
  the store lives inside a git repo, writes a `.gitignore` safety net into
  the store root.
- Reconciles against `.kanon.lock` like `npm ci`: a plain `install` fails fast
  (exit 1) without mutating the lock when `.kanon` and `.kanon.lock` have
  drifted (a source added, removed, or with a changed ref). `--reconcile` opts
  in to the lenient prune-and-re-resolve (prune orphaned entries, re-resolve
  added/changed sources, replay unchanged ones, rewrite the lock on success).
  `--strict-lock` additionally rejects an orphaned lock entry that survives a
  `kanon_hash` match. Branch drift (a locked SHA differing from the branch's
  current tip) reuses the locked SHA with an info-line; `--strict-drift`
  promotes that to an error.
- **Marketplace prune:** when a source is removed from `.kanon` and the lock is
  rebuilt (via `--reconcile`, `--refresh-lock`, or `kanon clean --orphans`),
  the marketplaces that source registered are unregistered.
- For any source with `KANON_SOURCE_<alias>_MARKETPLACE=true`: runs the
  marketplace install lifecycle.

`--refresh-lock` and `--refresh-lock-source NAME` re-resolve transitive
versions from the committed `.kanon` declarations. They do not take or
require a catalog source: `kanon install` is hermetic on every path.

### kanon clean

Executes the full teardown lifecycle.

```bash
kanon clean                       # auto-discover .kanon by walking up from cwd
kanon clean .kanon                # explicit path to .kanon file
kanon clean --orphans             # also unregister orphaned marketplaces
```

**Behavior:**

1. For any source with `KANON_SOURCE_<alias>_MARKETPLACE=true`: uninstalls
   plugins and removes the marketplace directory.
2. Removes the `.packages/` and `.kanon-data/` directories and prunes this
   project's content-addressed entries from the shared `KANON_HOME` store.

With `--orphans`, before the normal teardown kanon also unregisters any
kanon-owned marketplaces recorded in `.kanon.lock` that are no longer
referenced by `.kanon`, pruning them from `~/.claude`.

### kanon outdated

Compares each source in `.kanon` against the catalog and emits a table of
`name | current | latest-matching-spec | latest-available | upgrade-type`.

```bash
kanon outdated                    # table output, always exits 0
kanon outdated --format json      # JSON array, one object per source
kanon outdated --fail-on-upgrade  # exit 1 when any source has an upgrade (CI gate)
```

The `current` column comes from `.kanon.lock` when present, or is
live-resolved against the catalog when absent. Key options:
`--fail-on-upgrade`, `--format {table,json}`, `--kanon-file`, `--lock-file`.

### kanon why

Explains why a transitive dependency is in the tree. Reads `.kanon`, resolves
the full dependency tree (from `.kanon.lock` when present, else live-resolves
against the catalog), and prints every chain reaching the requested node.

```bash
kanon why my-project              # by source name, repo URL, or XML path
kanon why https://example.com/org/project.git
kanon why remote                  # a transitive include, by its name
kanon why --format json my-project
```

The argument is matched four ways: a `<project>` repo URL (canonicalized), a
transitive XML manifest path (exact-string equality), a top-level source name,
or a transitive include name (the last two normalized via `derive_source_name`).
When a single logical node is reached by many chains -- for example a transitive
include pulled in by several sources -- every chain is printed; an error is
raised only when the argument matches two or more distinct interpretations. A
catalog source is required only on the live-resolve path (when `.kanon.lock` is
absent).

### kanon doctor

Diagnoses `.kanon` / `.kanon.lock` health against the current project
directory.

```bash
kanon doctor                            # run all health checks
kanon doctor --strict-drift             # promote branch-drift findings to errors
kanon doctor --refresh-completion-cache # invalidate the shell completion cache
kanon doctor --prune-cache              # prune stale cache files (age-based)
```

Reports findings including `.kanon`/`.kanon.lock` consistency (via
`kanon_hash`), hand-edit detection, orphaned lock entries, branch drift,
dangling-SHA detection, a `NO_SOURCES` finding for a zero-source `.kanon`, and
a remote-reachability sanity check (warning only). See
[docs/doctor.md](docs/doctor.md) for the full subcheck reference.

### kanon validate

Validates manifest XML files. Subcommands:

```bash
kanon validate xml          # well-formedness, attributes, include chains
kanon validate marketplace  # linkfile dest, includes, uniqueness, tag format
kanon validate metadata     # catalog-metadata soft-spots (no network access)
kanon validate lockfile     # .kanon <-> .kanon.lock consistency
```

- **`validate xml`** -- checks well-formed XML, required attributes on
  `<project>` and `<remote>`, and that `<include>` names point to existing
  files.
- **`validate marketplace`** -- checks `<linkfile dest>` attributes, include
  chain integrity, project path uniqueness, and revision tag format.
- **`validate metadata`** -- checks the `<catalog-metadata>` blocks for
  required/recommended fields, source-name derivation, and entry-name
  uniqueness, without cloning or calling git. Supports `--format {text,json}`.
- **`validate lockfile`** -- checks that the `.kanon` declarations agree with
  the `.kanon.lock` entries (alias uniqueness, alias-set parity, ref-spec
  parity) -- the same check `kanon install` runs implicitly. Accepts a
  `<kanonenv_path>` and `--lock-file PATH`.

The `xml`, `marketplace`, and `metadata` subcommands accept
`--repo-root REPO_ROOT` (default: auto-detect via `git rev-parse`).

### kanon catalog audit

Audits a manifest repo against the catalog standards contract (the five
soft-spot rules).

```bash
kanon catalog audit                       # audit the current directory
kanon catalog audit ./scratch --strict    # promote warnings to errors
kanon catalog audit https://example.com/org/repo.git@main  # audit a remote source
kanon catalog audit --check metadata,tag-format            # run a subset of checks
```

`<dir-or-source>` is a local directory (must contain `repo-specs/`) or a
remote `<git_url>@<ref>` source; defaults to `.`. Options: `--check <subset>`
(valid values: `all`, `entry-name-uniqueness`, `metadata`, `remote-url`,
`source-name-derivation`, `tag-format`), `--format {text,json}`, `--strict`.
See [docs/catalog-author-guide.md](docs/catalog-author-guide.md).

### kanon repo

Catalog-author / low-level subcommand: runs kanon's `repo` dispatcher.
All trailing arguments after `kanon repo` are forwarded verbatim to it.

```bash
kanon repo init -u <url> -b <branch> -m <manifest>
kanon repo sync --jobs=4
kanon repo help
```

`--repo-dir REPO_DIR` sets the `.repo` directory (default: `${KANON_REPO_DIR}`
or `.repo`). See [docs/repo/README.md](docs/repo/README.md).

### kanon completion

Emits the shell completion script for kanon to stdout.

```bash
kanon completion bash > /etc/bash_completion.d/kanon
kanon completion zsh  > "${fpath[1]}/_kanon"
kanon completion powershell | Out-String | Invoke-Expression
```

Target shell choices: `bash`, `zsh`, `powershell` (PowerShell Core / `pwsh`).
`cmd.exe` has no programmable tab-completion and is not a supported target.
See [docs/shell-completion.md](docs/shell-completion.md).

### kanon bootstrap (removed in 3.0.0)

`kanon bootstrap` was removed in kanon 3.0.0 (a breaking change). There is
**no compatibility shim**: `bootstrap` is no longer a registered subcommand,
so `kanon bootstrap` (with any args or flags) exits non-zero with an argparse
`invalid choice: 'bootstrap'` error that lists the valid subcommands. The
catalog model changed: a manifest repo no longer has a separate
`catalog/<name>/` location and the kanon wheel no longer bundles a catalog.
Use `kanon search` to discover entries and `kanon add` to add them. See
[docs/migration-to-add.md](docs/migration-to-add.md).

---

## .kanon Variable Reference

The `.kanon` file is a shell-compatible `KEY=VALUE` configuration file that
drives the Kanon lifecycle. Lines starting with `#` are comments. Values can
reference environment variables using `${VAR}` syntax (e.g.,
`${HOME}/.claude-marketplaces`). Every `.kanon` variable can be overridden
by an environment variable of the same name, enabling CI/CD pipelines to
customize behavior without modifying the file.

### Core Variables

There is no required global header. The only global variable kanon reads is:

**`CLAUDE_MARKETPLACES_DIR`** (Auto-managed)
Directory for marketplace symlinks. Auto-added (as
`CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces`) by `kanon add` of a
`claude-marketplace` entry and by `kanon marketplace enable`, and pruned by
`kanon remove` / `kanon marketplace disable` once the last
`KANON_SOURCE_<alias>_MARKETPLACE=true` dependency is gone. Hand-set the line
only to override the directory; a custom value is preserved and never clobbered.

### Source Variables

Sources are auto-discovered from `KANON_SOURCE_<alias>_URL` variable patterns
and processed in alphabetical order by alias. Each source carries the
following alias-keyed variables:

**`KANON_SOURCE_<alias>_URL`** (Required)
Git URL for the source's manifest repository.

**`KANON_SOURCE_<alias>_REF`** (Required)
Branch, exact tag, or PEP 440 constraint (e.g. `refs/tags/~=1.1.0`) for the
source.

**`KANON_SOURCE_<alias>_PATH`** (Required)
Path to the entry-point manifest XML for the source.

**`KANON_SOURCE_<alias>_NAME`** (Required)
The original catalog entry name (the pre-normalization manifest name).

**`KANON_SOURCE_<alias>_<VAR>`** (Optional, open-ended)
Per-dependency env vars used to resolve `${VAR}` placeholders in this source's
manifest at install time. `kanon add` writes one line per `${VAR}` the entry's
manifest actually references: the var named exactly `GITBASE` is auto-derived
from the source URL (e.g. `KANON_SOURCE_<alias>_GITBASE=https://github.com/your-org`,
replacing the removed global `GITBASE` header), and every other var name is
written empty for you to fill in. An entry whose manifest references no `${VAR}`
gets no env-var line. At install time each declared var is injected into that
source's manifest substitution; if a `${VAR}` remains unresolved, install fails
fast naming the `KANON_SOURCE_<alias>_<VAR>` key to set.

**`KANON_SOURCE_<alias>_MARKETPLACE`** (Optional)
Per-source marketplace toggle. Set to `true` to enable the marketplace
lifecycle for this source; absence means `false` (kanon never writes
`=false`). Written by `kanon add --marketplace-install`; manage it with
`kanon marketplace enable` / `disable` / `status`.

### Environment Variables

**`KANON_CATALOG_SOURCES`**
Newline-delimited list of remote catalog sources, each as `url[@ref]` where
ref is a branch, tag, `latest`, or PEP 440 constraint (e.g.,
`>=2.0.0,<3.0.0`). Commands that resolve a catalog use the single configured
entry, or the `--catalog-source` flag overrides it. A catalog source is
**required** by `kanon search`, `kanon add`, `kanon outdated`, `kanon why`,
and `kanon catalog audit`. `kanon install` is hermetic: it reads only
`.kanon` and `.kanon.lock` and does not consult a catalog source.

**`KANON_HOME`**
Root of the shared kanon store and caches (default `~/.kanon`). The
`--home` / `--store-dir <path>` global flag overrides it for a single
invocation; precedence is flag > `KANON_HOME` > `~/.kanon`. Replaces the
removed `KANON_WORKSPACE_DIR` / `KANON_CACHE_DIR` variables. Synced artifacts
and the per-`.kanon` workspace lock both live under `${KANON_HOME}/store/`,
so the project directory holds only `.kanon` (plus `.kanon.lock` after the
first install) and never a `.kanon-data/` lock directory.

**`KANON_SKIP_UPDATE_CHECK`**
Set to `1` to skip the PyPI update-available check (equivalent to the
`--no-update-check` global flag).

See [docs/configuration.md](docs/configuration.md) for the full
environment-variable reference.

### Example .kanon

```properties
# Auto-added by `kanon add` of a claude-marketplace entry / `kanon marketplace
# enable`; pruned on the last `kanon remove` / `kanon marketplace disable`.
# Hand-set it only to override the directory.
CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces

# Source: build -- build tooling packages.
# The _GITBASE line below is present only because this source's manifest
# references ${GITBASE}; a manifest with fully-literal remotes has no env-var line.
KANON_SOURCE_build_URL=https://github.com/your-org/kanon-manifests.git
KANON_SOURCE_build_REF=main
KANON_SOURCE_build_PATH=repo-specs/build/meta.xml
KANON_SOURCE_build_NAME=build
KANON_SOURCE_build_GITBASE=https://github.com/your-org

# Source: marketplaces -- plugin marketplaces (per-source marketplace toggle)
KANON_SOURCE_marketplaces_URL=https://github.com/your-org/kanon-manifests.git
KANON_SOURCE_marketplaces_REF=main
KANON_SOURCE_marketplaces_PATH=repo-specs/marketplaces/meta.xml
KANON_SOURCE_marketplaces_NAME=marketplaces
KANON_SOURCE_marketplaces_GITBASE=https://github.com/your-org
KANON_SOURCE_marketplaces_MARKETPLACE=true
```

---

## Architecture

```text
                    ┌─────────────────────────┐
                    │     Kanon CLI           │
                    │ (search / add / install/│
                    │   clean / validate)     │
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
                   │   kanon repo subsystem     │
                   │ (manifest-driven sync with │
                   │  envsubst + PEP 440)       │
                   │ Executes manifests, syncs  │
                   │ repos, manages workspace   │
                   └────────────────────────────┘
```

### How It Works

Kanon's `kanon repo` subsystem orchestrates dependencies across Git
repositories via XML manifests. Manifests define what to clone, where to
place it, and how to wire it together.

The install lifecycle follows three steps per source:

1. **`kanon repo init`** -- Clones the manifest repository. `${VARIABLE}`
   placeholders remain as-is in the XML.
2. **`kanon repo envsubst`** -- Reads variables from `.kanon` (e.g.,
   `GITBASE`) and replaces `${VARIABLE}` placeholders in all manifest XML
   files.
3. **`kanon repo sync`** -- Clones packages using the now-resolved URLs into
   `.packages/`.

After all sources are synced, Kanon aggregates their packages into a single
`.packages/` directory using symlinks, giving consumers a unified view
regardless of which source provided each package.

### Directory Structure After Install

Fetched artifacts live in the shared `KANON_HOME` store
(`$KANON_HOME`, default `~/.kanon`), content-addressed and deduped across
projects. Only `.kanon` and `.kanon.lock` live in (and are committed to)
the project itself:

```text
project/
  .kanon                            # Configuration (committed)
  .kanon.lock                       # Resolved SHAs (committed)

$KANON_HOME/                        # Shared store (default ~/.kanon; not in the repo)
  store/
    .kanon-data/
      sources/
        build/                      # Isolated source workspace
          .repo/
          .packages/
            my-build-conventions/
        marketplaces/               # Isolated source workspace
          .repo/
          .packages/
            my-marketplace-plugin/
    .packages/                      # Aggregated symlinks
      my-build-conventions -> \
        ../.kanon-data/sources/build/.packages/my-build-conventions
      my-marketplace-plugin -> \
        ../.kanon-data/sources/marketplaces/.packages/my-marketplace-plugin
```

Relocate the store for a single invocation with `--home` / `--store-dir`,
or persistently with the `KANON_HOME` environment variable. When the store
happens to live inside a git repository, `kanon install` writes a
`.gitignore` safety net into the store root so fetched artifacts are never
committed.

### Multi-Source Isolation

Each source is initialized and synced in its own isolated directory under
`.kanon-data/sources/<name>/`. Sources cannot interfere with each other --
each gets its own `kanon repo init` / `kanon repo sync` cycle. If two sources
produce a package with the same name, Kanon detects the collision and fails
immediately with an actionable error message.

### Environment Variable Portability (envsubst)

The `envsubst` feature makes manifests portable across organizations. Instead
of hard-coding Git URLs in manifest XML, you use `${GITBASE}` placeholders:

```xml
<!-- Portable -- resolved from .kanon at install time -->
<remote name="origin" fetch="${GITBASE}"/>
```

Each dependency carries its own org base in `KANON_SOURCE_<alias>_GITBASE`,
which is exported as `${GITBASE}` while that source's manifests are
processed. Adopting Kanon for a different organization means pointing a
dependency at a different base:

```properties
KANON_SOURCE_my_dep_GITBASE=https://github.com/your-company
```

CI/CD pipelines can override a dependency's base via environment variables
without modifying `.kanon` (environment variables take precedence over
`.kanon` file values):

```bash
KANON_SOURCE_my_dep_GITBASE=https://git.internal.company.com kanon install
```

For full documentation, see [docs/how-it-works.md](docs/how-it-works.md).

---

## Creating a Manifest Repository

A manifest repository contains `repo-specs/` with XML manifests that define
what packages to sync, from which repositories, and at which versions. **The
manifest repo IS the catalog** -- there is no separate `catalog/` directory.
Each catalog entry is a single `*.xml` file under `repo-specs/` (any
filename) that carries a nested `<catalog-metadata>` block; the
`<catalog-metadata><name>` child is the entry name consumers pass to
`kanon add <name>`. See
[docs/creating-manifest-repos.md](docs/creating-manifest-repos.md) for the
full catalog-author guide and
[docs/repo/manifest-format.md](docs/repo/manifest-format.md) for the
underlying XML schema.

### Structure

```text
my-manifest-repo/
  repo-specs/
    git-connection/
      remote.xml             # Git remotes with ${GITBASE} placeholders
    my-archetype/
      my-archetype-marketplace.xml  # Catalog entry (carries <catalog-metadata>)
      packages.xml           # Package repos with pinned versions
```

### Catalog entry

Each catalog entry is an XML file under `repo-specs/` (any filename)
containing exactly one nested `<catalog-metadata>` block. Required fields are `name`,
`display-name`, `description`, and `version`; recommended fields are `type`,
`owner-name`, `owner-email`, and `keywords` (comma-separated). The legacy
flat-attribute scheme (metadata as XML attributes) is rejected.

```xml
<package>
  <catalog-metadata>
    <name>my-archetype</name>
    <display-name>My Archetype</display-name>
    <description>Build conventions and lint config for service repos.</description>
    <version>1.0.0</version>
    <type>library</type>
    <owner-name>Platform Team</owner-name>
    <owner-email>platform@example.com</owner-email>
    <keywords>build,lint,conventions</keywords>
  </catalog-metadata>
  <include name="repo-specs/my-archetype/packages.xml" />
</package>
```

`kanon validate metadata` and `kanon catalog audit` enforce the
`<catalog-metadata>` contract.

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

### Entry-point manifest

The `*-marketplace.xml` catalog entry is the entry point referenced by the
`KANON_SOURCE_<name>_PATH` value that `kanon add` writes into `.kanon`. It
pulls in the package declarations via `<include>`:

```xml
<package>
  <catalog-metadata>
    <!-- ... required + recommended fields ... -->
  </catalog-metadata>
  <include name="repo-specs/my-archetype/packages.xml" />
</package>
```

### Include Chains for Hierarchy

Manifests can include other manifests via `<include>` tags, forming a
hierarchy. This enables cascading configurations where common packages are
defined once and specialized packages are layered on top:

```text
my-archetype-marketplace.xml
  └── packages.xml (leaf -- e.g., specific project type)
        └── packages.xml (framework level)
              └── packages.xml (language level)
                    └── packages.xml (common/base)
```

Each level includes its parent and adds its own package entries. The
`kanon repo` subsystem recursively resolves all includes, accumulating a
unified set of packages.

### Updating Package Versions

1. Tag the package repository with the new semver version
2. Update the `revision` attribute in the corresponding `packages.xml`
3. Run `kanon validate xml` to verify manifests remain valid
4. Tag and push the manifest repository

Projects pick up the new versions on next `kanon install`.

For more details, see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Creating Packages

A package is a Git repository containing automation scripts (configuration
files, shell scripts, etc.) tagged with semver versions. Kanon syncs packages
to `.packages/` where build tools can discover and apply them.

### Package Structure

```text
my-package/
  automation-script.sh        # Shell scripts, config files, etc.
  config/                     # Optional: configuration files
  README.md                   # Package documentation
  CHANGELOG.md                # Version history
```

### Versioning

Use [semantic versioning](https://semver.org/) with Git tags:

- **MAJOR** -- Breaking changes (renamed tasks, removed config, changed
  behavior)
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

Some packages contain assets (configuration files, templates) that tools
expect at conventional paths. The `<linkfile>` element creates symlinks from
the package directory to the project root:

```xml
<project name="my-lint-config"
         path=".packages/my-lint-config"
         remote="origin"
         revision="refs/tags/1.0.0">
  <linkfile src="config/checkstyle/checkstyle.xml"
            dest="config/checkstyle/checkstyle.xml" />
</project>
```

After `kanon repo sync`, the project has `config/checkstyle/checkstyle.xml`
as a symlink pointing into `.packages/`. These symlinked paths should be
gitignored since they are regenerated by `kanon install`.

---

## Creating Marketplace Packages

Marketplace packages use `<linkfile>` symlinks to expose plugins to Claude
Code. They follow a cascading manifest hierarchy where each level includes
its parent, enabling shared tools across project types while adding
specialized plugins at each level.

### Marketplace Manifest Structure

```xml
<manifest>
  <!-- Include shared remote definitions -->
  <include name="repo-specs/git-connection/remote.xml" />

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

- All `<linkfile dest>` attributes must start with
  `${CLAUDE_MARKETPLACES_DIR}/`
- Each `<project path>` must be unique across all manifests
- The per-source `KANON_SOURCE_<alias>_MARKETPLACE` flag in `.kanon` must be
  set to `true` for the marketplace source
- `CLAUDE_MARKETPLACES_DIR` must be present in `.kanon` (auto-added by
  `kanon add` / `kanon marketplace enable`; hand-set only to override the dir)

### Naming Convention

Marketplace manifest files must be named `*-marketplace.xml` (e.g.,
`claude-history-marketplace.xml`,
`immutable-audit-trail-marketplace.xml`).
The `kanon validate marketplace` command discovers files matching this
pattern under `repo-specs/`.

### Cascading Includes

Manifests support cascading `<include>` chains where each level includes its
parent. This enables shared remote definitions, common project entries, and
layered composition across project types. Currently marketplace manifests use
a flat structure (each manifest includes `remote.xml` directly), but
cascading hierarchies are fully supported when needed.

### Validation

```bash
kanon validate marketplace
```

This checks linkfile destination prefixes, include chain integrity, project
path uniqueness, and revision format validity.

For full documentation, see
[docs/claude-marketplaces-guide.md](docs/claude-marketplaces-guide.md).

---

## Manifest Features (PEP 440 Constraints)

Kanon adds the following capabilities to manifest-driven sync:

### PEP 440 Version Constraints in Manifests

`<project revision>` accepts [PEP 440](https://peps.python.org/pep-0440/)
version constraint syntax in addition to a branch, tag, or commit SHA.
Constraints resolve to the best matching tag at sync time.

#### How It Works

The resolver splits the `revision` attribute at the last `/` into a tag-path
prefix and a constraint. It filters available tags by that prefix, evaluates
the constraint, and returns the highest matching version.

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
| --- | --- | --- |
| Patch-compatible | `~=1.2.0` | `>=1.2.0, <1.3.0` (any patch in 1.2.x) |
| Range | `>=1.0.0,<2.0.0` | Any version up to (not including) 2.0.0 |
| Wildcard | `*` | Any available version (selects the latest) |
| Exact | `==1.2.3` | Only version 1.2.3 |
| Minimum | `>=1.0.0` | 1.0.0 or higher |
| Exclusion | `!=1.0.1` | Any version except 1.0.1 |

#### XML Escaping

Certain characters are reserved in XML and must be escaped inside
attribute values. The most common case is `<` in range constraints:

| Character | Escape | When required |
| --- | --- | --- |
| `<` | `&lt;` | Always (reserved XML character) |
| `&` | `&amp;` | Always (reserved XML character) |
| `"` | `&quot;` | Inside `"` delimited attributes |
| `'` | `&apos;` | Inside `'` delimited attributes |
| `>` | `&gt;` | Optional (`>` also valid in attributes) |

Example with range constraint:

```xml
<project name="my-package"
         path=".packages/my-package"
         remote="origin"
         revision="refs/tags/my-package/>=1.0.0,&lt;2.0.0" />
```

### PEP 440 Version Resolution in .kanon

The CLI supports PEP 440 constraint syntax in `KANON_SOURCE_<alias>_REF`
entries in `.kanon`. Constraints are resolved against available git tags
before being passed to the sync engine.

#### Supported Operators

| Operator | Syntax | Meaning |
| --- | --- | --- |
| Compatible release | `~=1.2.0` | `>=1.2.0, <1.3.0` |
| Range | `>=1.0.0,<2.0.0` | Any version in range |
| Exact | `==1.2.3` | Only 1.2.3 |
| Minimum | `>=1.0.0` | 1.0.0 or higher |
| Exclusion | `!=1.0.1` | Any version except 1.0.1 |
| Wildcard | `*` | Latest available |

Plain strings without PEP 440 operators pass through unchanged.

#### Prefixed Constraints (KANON_SOURCE_\<alias\>_REF)

Source refs support an optional `refs/tags/` prefix. This is recommended
because the resolved value is passed to `kanon repo init -b`, which accepts
full ref paths:

```properties
# Resolves to refs/tags/1.1.2 -- works directly with kanon repo init -b
KANON_SOURCE_build_REF=refs/tags/~=1.1.0

# Namespaced -- only considers tags under that path
KANON_SOURCE_build_REF=refs/tags/dev/python/my-lib/~=1.2.0

# Also supported -- resolves against all tags
KANON_SOURCE_build_REF=~=1.1.0
```

For full details, see [docs/version-resolution.md](docs/version-resolution.md).

### Absolute Linkfile Destinations

`<linkfile dest>` accepts absolute paths after `envsubst` expansion, enabling
marketplace symlinks to directories outside the project (e.g.,
`${CLAUDE_MARKETPLACES_DIR}/...`).

---

## SSH Authentication Setup

Kanon uses HTTPS Git URLs internally. If you authenticate with GitHub via SSH
instead of HTTPS tokens, configure Git to rewrite HTTPS URLs to SSH globally:

```bash
git config --global url."git@github.com:".insteadOf "https://github.com/"
```

This tells Git to use SSH for all `github.com` requests, which Kanon's
`git clone`, `git ls-remote`, and `kanon repo` commands will then use
automatically.

**Note:** The `--global` flag is required. Using `--local` will not work
because `kanon repo` operates in its own working directories with their own
local Git configuration.

For other Git hosts, adjust the URL accordingly:

```bash
git config --global url."git@gitlab.com:".insteadOf "https://gitlab.com/"
git config --global \
  url."git@bitbucket.org:".insteadOf "https://bitbucket.org/"
```

To verify the configuration:

```bash
git config --global --get-regexp url
```

---

## Developer Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

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
make test              # All tests with coverage
make test-unit         # Unit tests only
make test-integration  # Integration tests (modules end-to-end)
make test-functional   # Functional tests (CLI via subprocess)
make test-scenarios    # End-to-end scenario tests
make test-cov          # Tests with coverage report
```

### Build

```bash
make publish       # Clean, build, and check distribution
```

### Project Structure

```text
src/kanon_cli/
  cli.py              # Entry point
  commands/           # Subcommand implementations
  core/               # Core logic (install, clean, kanon parsing, lockfile)
  completions/        # Shell-completion generators
  utils/              # Shared helpers
  repo/               # kanon repo subsystem (manifest sync, PEP 440)
tests/                # Unit and functional tests
docs/                 # Configuration, lifecycle, version resolution docs
pyproject.toml        # Package config (hatchling, entry point: kanon)
```

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for commit conventions, PR process,
and how the automated release pipeline works.

### CI/CD Pipeline

This project uses a fully automated SDLC pipeline:

1. **PR Validation** -- Lint, build, test (90% coverage), security scan on
   every PR
2. **Main Branch Validation** -- Full validation + CodeQL on merge to main
3. **Manual QA Approval** -- Human gate before release
4. **Automated Release** -- Semantic versioning from conventional commit
   prefixes, changelog generation, tagging
5. **PyPI Publishing** -- Automated publish via OIDC trusted publishing

PR titles must follow
[Conventional Commits](https://www.conventionalcommits.org/) format
(e.g., `feat: add feature`, `fix: resolve bug`) as they drive automatic
version bumps.

---

## Documentation

- [How It Works](docs/how-it-works.md) -- Technical deep-dive into Kanon
  internals
- [Setup Guide](docs/setup-guide.md) -- Step-by-step setup for new and
  existing projects
- [Configuration](docs/configuration.md) -- `.kanon` format and variable
  expansion
- [Lifecycle](docs/lifecycle.md) -- Install and clean lifecycle step-by-step
- [Multi-Source Guide](docs/multi-source-guide.md) -- Configuring multiple
  manifest sources
- [Version Resolution](docs/version-resolution.md) -- PEP 440 resolver
  details
- [Creating Manifest Repos](docs/creating-manifest-repos.md) -- Authoring
  manifest repositories
- [Creating Packages](docs/creating-packages.md) -- Authoring individual
  package repositories
- [Claude Marketplaces Guide](docs/claude-marketplaces-guide.md) --
  Marketplace architecture and plugin lifecycle
- [Pipeline Integration](docs/pipeline-integration.md) -- Using Kanon tasks
  in CI/CD pipelines
- [Integration Testing](docs/integration-testing.md) -- End-to-end CLI test
  plan
- [kanon repo reference](docs/repo/README.md) -- Manifest format, `.repo/`
  layout, hooks, smart sync, Python support (Windows is not currently
  supported; see [Platform support](#platform-support) and use WSL2)
- [Contributing](CONTRIBUTING.md) -- How to create and maintain Kanon
  packages and marketplaces

---

## License

Apache 2.0. See [LICENSE](LICENSE).
