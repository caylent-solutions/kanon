# Setup Guide

Step-by-step instructions for setting up Kanon in new and existing projects.

## Prerequisites

- Git
- Bash shell
- Python 3.11+
- Internet access (to clone package repositories)

**For all projects:** The `kanon` CLI tool must be installed first.

For end-user / production use (isolated CLI from PyPI):

```bash
pipx install kanon-cli
```

For local development on the kanon-cli repository itself, install it
in editable mode against the local source tree:

```bash
pip install -e .
```

(`pipx` keeps the CLI isolated in its own venv. Install it with
`python3 -m pip install --user pipx && pipx ensurepath` if it is not
already on your PATH. Editable mode is documented for kanon
contributors; see `CONTRIBUTING.md`.)

The `kanon repo` subsystem (`kanon repo init`, `kanon repo sync`, etc.)
is part of the `kanon` CLI. See the [Kanon README](../README.md) for
full CLI documentation.

## New Project Setup

### 1. Add Catalog Entries to Your Project

> **Note:** `kanon bootstrap` was removed in a major release (a breaking
> change). It performs no work and exits 3 on every invocation. Use the
> commands below instead. See
> [docs/migration-to-add.md](migration-to-add.md).

Search the catalog and add an entry to your `.kanon` with `kanon search` and
`kanon add`. A catalog source is required, supplied via `--catalog-source
'<git_url>@<ref>'` or the `KANON_CATALOG_SOURCES` environment variable (ref can
be a branch, tag, `latest`, or a PEP 440 version constraint such as
`>=2.0.0,<3.0.0`):

```bash
kanon search --catalog-source '<git_url>@<ref>'        # search the catalog
kanon add kanon --catalog-source '<git_url>@<ref>'   # add an entry to .kanon
```

`kanon add` writes the entry into `.kanon`, creating `.kanon` for you if it does
not yet exist.

### 2. Review `.kanon` (Optional)

The `.kanon` file is populated by `kanon add` with values from your
organization's catalog entry. You may want to review the source URLs and paths
before installing.

All `.kanon` values can be overridden by environment variables of the same name (useful for CI/CD pipelines).

### 3. Run kanon install

```bash
kanon install
```

### 4. Verify

Confirm that `.packages/` was created and contains the expected package directories. Check that any symlinks defined in the manifest are present in your project root.

## Existing Project Migration

For existing projects, follow the same steps above but adapt your existing build configuration to include Kanon's catalog entry files alongside your current setup.

## Troubleshooting

### `kanon: command not found`

The `kanon` CLI must be installed before running any `kanon` command.
Install it with `pipx install kanon-cli` (production) or `pip install -e .`
(local development on this repository). The `kanon repo` subsystem is part of
the `kanon` CLI -- there is no separate tool to install.

### `kanon repo envsubst` fails

Ensure `GITBASE` is set in `.kanon` and is a valid URL ending with `/`.

### `kanon repo sync` fails with authentication errors

Ensure `git` can authenticate with the Git hosting provider for your package repositories (SSH keys or credential helper).
