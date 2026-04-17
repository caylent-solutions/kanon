# Kanon -- Standalone Catalog Entry Package

Getting started with Kanon using the CLI directly. This is the simplest setup -- you get a `.kanon` configuration file and invoke `kanon install` and `kanon clean` directly.

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) -- Python package installer
- Git

The Kanon CLI is already installed (it just ran `kanon bootstrap` to create this file).

> **SSH Users:** Kanon uses HTTPS Git URLs internally. If you authenticate with GitHub via SSH, configure Git to rewrite HTTPS URLs to SSH globally:
>
> ```bash
> git config --global url."git@github.com:".insteadOf "https://github.com/"
> ```
>
> The `--global` flag is required -- `--local` will not work because Kanon uses the `repo` tool under the hood, which operates in its own working directories with their own local Git configuration. For other Git hosts, adjust the URL accordingly (e.g., `git@gitlab.com:` for GitLab).

---

## Setup

### 1. Install (sync all packages)

Edit `.kanon` to set `GITBASE`, `KANON_MARKETPLACE_INSTALL`, and your source variables, then run install:

```bash
kanon install .kanon
```

This syncs all packages to `.packages/`, creates source workspaces in `.kanon-data/sources/`, and updates `.gitignore`.

### 2. Verify

```bash
ls .packages/
```

After install, `.packages/` contains symlinks to all synced packages.

---

## Usage

**Install (sync packages):**

```bash
kanon install .kanon
```

**Clean (full teardown):**

```bash
kanon clean .kanon
```

**Validate manifests:**

```bash
kanon validate xml
kanon validate marketplace
```

---

## `.kanon` Variable Reference

### Core Variables

| Variable | Required | Purpose |
|---|---|---|
| `GITBASE` | Yes | Base Git URL for your organization (e.g., `https://github.com/your-org/`). Used by `repo envsubst` to resolve `${GITBASE}` placeholders in manifest XML files. |
| `CLAUDE_MARKETPLACES_DIR` | Conditional | Directory for marketplace plugin symlinks. Required when `KANON_MARKETPLACE_INSTALL=true`. Typically `${HOME}/.claude-marketplaces`. |
| `KANON_MARKETPLACE_INSTALL` | No | Set to `true` to enable the marketplace plugin install/uninstall lifecycle during install and clean. Default: `false`. When `false`, marketplace-related operations are skipped entirely. |

### Source Variables

Sources are auto-discovered from `KANON_SOURCE_<name>_URL` patterns and processed in alphabetical order by name. Each source requires three variables:

| Variable | Required | Purpose |
|---|---|---|
| `KANON_SOURCE_<name>_URL` | Yes | Git URL of the manifest repository for this source. |
| `KANON_SOURCE_<name>_REVISION` | Yes | Branch, tag, or PEP 440 constraint to track for this source's manifest repository. |
| `KANON_SOURCE_<name>_PATH` | Yes | Path to the entry-point manifest XML file within the manifest repository (e.g., `repo-specs/build/meta.xml`). |

You can define multiple sources. Add new source blocks in `.kanon` as needed.

---

## How It Works

The Kanon CLI reads `.kanon` and for each source:

1. `repo init` -- Clones the manifest repository
2. `repo envsubst` -- Resolves `${VARIABLE}` placeholders in manifest XML
3. `repo sync` -- Syncs packages into `.kanon-data/sources/<name>/.packages/`

After all sources are synced, Kanon aggregates their packages into `.packages/` using symlinks, giving a unified view regardless of which source provided each package.

**Committed files:** `.kanon`, `kanon-readme.md`

**Ephemeral files (gitignored):** `.packages/`, `.kanon-data/`

---

## When to Use This Package

Use the `kanon` catalog entry package when:

- Your project uses a build tool not directly supported by Kanon's catalog (npm, Maven, Bazel, etc.)
- You prefer to invoke the Kanon CLI directly from scripts or CI/CD pipelines
- You want the simplest possible setup with no wrapper files

You can integrate Kanon with any build tool by wrapping `kanon install .kanon` and `kanon clean .kanon` in your task runner of choice.

---

## Adding Sources

Add source blocks in `.kanon`:

```properties
KANON_SOURCE_tools_URL=https://github.com/your-org/tools-manifests.git
KANON_SOURCE_tools_REVISION=main
KANON_SOURCE_tools_PATH=repo-specs/tools/meta.xml
```

---

## Marketplace Plugins (Optional)

To enable Claude Code marketplace plugins, set in `.kanon`:

```properties
KANON_MARKETPLACE_INSTALL=true
CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
```

Then add a marketplace source and re-run `kanon install .kanon`. When `KANON_MARKETPLACE_INSTALL` is `false` (the default), the marketplace lifecycle is skipped entirely -- no plugins are installed or uninstalled.

---

## Troubleshooting

- **`kanon: command not found`** -- Reinstall the Kanon CLI: `uv tool install kanon-cli`
- **`kanon install` fails with ".kanon not found"** -- Pass the path: `kanon install .kanon`
- **`repo envsubst` fails** -- Ensure `GITBASE` is set in `.kanon` and is a valid URL ending with `/`
- **Authentication errors during sync** -- If you use SSH for Git auth, ensure the HTTPS-to-SSH rewrite is configured globally: `git config --global url."git@github.com:".insteadOf "https://github.com/"`. If you use HTTPS, ensure your credential helper is configured.
