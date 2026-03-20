# RPM -- Standalone Catalog Entry Package

Getting started with RPM using the CLI directly. This is the simplest setup -- you get a `.rpmenv` configuration file and invoke `rpm configure` and `rpm clean` directly.

---

## Prerequisites

- Git

The RPM CLI is already installed (it just ran `rpm bootstrap` to create this file).

---

## Setup

### 1. Configure (sync all packages)

Edit `.rpmenv` to set `GITBASE`, `RPM_MARKETPLACE_INSTALL`, and your source variables, then run configure:

```bash
rpm configure .rpmenv
```

This syncs all packages to `.packages/`, creates source workspaces in `.rpm/sources/`, and updates `.gitignore`.

### 2. Verify

```bash
ls .packages/
```

After configure, `.packages/` contains symlinks to all synced packages.

---

## Usage

**Configure (sync packages):**

```bash
rpm configure .rpmenv
```

**Clean (full teardown):**

```bash
rpm clean .rpmenv
```

**Validate manifests:**

```bash
rpm validate xml
rpm validate marketplace
```

---

## `.rpmenv` Variable Reference

### Core Variables

| Variable | Required | Purpose |
|---|---|---|
| `REPO_URL` | Yes | Git URL of the [rpm-git-repo](https://github.com/caylent-solutions/rpm-git-repo) tool. Must be `https://github.com/caylent-solutions/rpm-git-repo.git` -- no other repo tool or fork is supported. Used by `rpm configure` to install the repo tool via pipx. |
| `REPO_REV` | Yes | rpm-git-repo version. Currently use `feat/initial-rpm-git-repo` (the only available branch). Once published to PyPI, use a tagged release or PEP 440 specifier (e.g., `~=2.0.0`, `>=2.0.0,<3.0.0`, `*`). |
| `GITBASE` | Yes | Base Git URL for your organization (e.g., `https://github.com/your-org/`). Used by `repo envsubst` to resolve `${GITBASE}` placeholders in manifest XML files. |
| `CLAUDE_MARKETPLACES_DIR` | Conditional | Directory for marketplace plugin symlinks. Required when `RPM_MARKETPLACE_INSTALL=true`. Typically `${HOME}/.claude-marketplaces`. |
| `RPM_MARKETPLACE_INSTALL` | No | Set to `true` to enable the marketplace plugin install/uninstall lifecycle during configure and clean. Default: `false`. When `false`, marketplace-related operations are skipped entirely. |

### Source Variables

Sources are auto-discovered from `RPM_SOURCE_<name>_URL` patterns and processed in alphabetical order by name. Each source requires three variables:

| Variable | Required | Purpose |
|---|---|---|
| `RPM_SOURCE_<name>_URL` | Yes | Git URL of the manifest repository for this source. |
| `RPM_SOURCE_<name>_REVISION` | Yes | Branch, tag, or PEP 440 constraint to track for this source's manifest repository. |
| `RPM_SOURCE_<name>_PATH` | Yes | Path to the entry-point manifest XML file within the manifest repository (e.g., `repo-specs/build/meta.xml`). |

You can define multiple sources. Add new source blocks in `.rpmenv` as needed.

---

## How It Works

The RPM CLI reads `.rpmenv` and for each source:

1. `repo init` -- Clones the manifest repository
2. `repo envsubst` -- Resolves `${VARIABLE}` placeholders in manifest XML
3. `repo sync` -- Syncs packages into `.rpm/sources/<name>/.packages/`

After all sources are synced, RPM aggregates their packages into `.packages/` using symlinks, giving a unified view regardless of which source provided each package.

**Committed files:** `.rpmenv`, `rpm-readme.md`

**Ephemeral files (gitignored):** `.packages/`, `.rpm/`

---

## When to Use This Package

Use the `rpm` catalog entry package when:

- Your project uses a build tool not directly supported by RPM's catalog (npm, Maven, Bazel, etc.)
- You prefer to invoke the RPM CLI directly from scripts or CI/CD pipelines
- You want the simplest possible setup with no wrapper files

You can integrate RPM with any build tool by wrapping `rpm configure .rpmenv` and `rpm clean .rpmenv` in your task runner of choice.

---

## Adding Sources

Add source blocks in `.rpmenv`:

```properties
RPM_SOURCE_tools_URL=https://github.com/your-org/tools-manifests.git
RPM_SOURCE_tools_REVISION=main
RPM_SOURCE_tools_PATH=repo-specs/tools/meta.xml
```

---

## Marketplace Plugins (Optional)

To enable Claude Code marketplace plugins, set in `.rpmenv`:

```properties
RPM_MARKETPLACE_INSTALL=true
CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
```

Then add a marketplace source and re-run `rpm configure .rpmenv`. When `RPM_MARKETPLACE_INSTALL` is `false` (the default), the marketplace lifecycle is skipped entirely -- no plugins are installed or uninstalled.

---

## Troubleshooting

- **`rpm: command not found`** -- Reinstall the RPM CLI: `pipx install rpm-cli`
- **`rpm configure` fails with ".rpmenv not found"** -- Pass the path: `rpm configure .rpmenv`
- **`repo envsubst` fails** -- Ensure `GITBASE` is set in `.rpmenv` and is a valid URL ending with `/`
- **Authentication errors during sync** -- Ensure `git` can authenticate with your Git hosting provider (SSH keys or credential helper)
