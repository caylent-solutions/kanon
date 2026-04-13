# Setup Guide

Step-by-step instructions for setting up Kanon in new and existing projects.

## Prerequisites

- Git
- Bash shell
- Python 3 (`command -v python3`)
- Internet access (to install the repo tool and clone packages)

**For all projects:** The `kanon` CLI tool must be installed first:

```bash
pipx install kanon-cli
```

The `kanon` CLI installs the repo tool automatically during `kanon install`. Both Gradle and Make bootstraps delegate to this CLI. See the [Kanon README](../README.md) for full CLI documentation.

## New Project Setup

### 1. Bootstrap Your Project

Use `kanon bootstrap` to copy catalog entry package files (including a pre-configured `.kanon`) into your project:

**For Gradle projects:**

```bash
kanon bootstrap gradle
```

**For Make projects:**

```bash
kanon bootstrap make
```

**For projects without a task runner:**

```bash
kanon bootstrap kanon
```

This copies all files from the catalog entry package into the target directory. The `.kanon` is pre-configured by the catalog author -- no placeholder editing required. Use `--output-dir` to specify a different target directory. Use `--catalog-source '<git_url>@<ref>'` or the `KANON_CATALOG_SOURCE` environment variable to fetch catalog entry packages from a remote catalog repo (ref can be a branch, tag, or `latest` which resolves to the highest semver tag).

### 2. Review `.kanon` (Optional)

The `.kanon` file is pre-configured from the catalog entry package. If you are using the bundled catalog, the `.kanon` contains example values. You may want to update the source URLs and paths to point to your organization's manifest repository.

If you are using a remote catalog (`--catalog-source` or `KANON_CATALOG_SOURCE`), the `.kanon` should already contain the correct values for your organization.

All `.kanon` values can be overridden by environment variables of the same name (useful for CI/CD pipelines).

### 3. Customize `build.gradle` (Gradle only)

Replace the template's project-specific section with your own. Kanon provides
plugins but does NOT manage dependency versions -- each project owns its version
pins and BOM imports. See
the [Kanon README](../README.md) for a detailed `build.gradle` example.

### 4. Run kanonInstall

**Gradle:**

```bash
./gradlew kanonInstall
```

**Make:**

```bash
make kanonInstall
```

**CLI directly:**

```bash
kanon install .kanon
```

### 5. Verify

```bash
./gradlew tasks       # Should show package-provided tasks
./gradlew build       # Should compile and run checks
```

## Existing Project Migration

For existing projects, follow the same steps above but adapt your existing build configuration to include Kanon's catalog entry files alongside your current setup.

## Troubleshooting

### `kanonInstall` fails with "python3 is not installed"

Python 3 must be available on PATH before running `kanonInstall`.

- **DevContainer:** Python is provided by the devcontainer Python feature.
- **CI/CD:** Add a Python installation step before running your build tool.
- **Local:** Install Python 3 via your system package manager.

### `kanonInstall` fails with "pipx is not installed"

pipx must be available on PATH to install the `kanon` CLI. Install it with `python3 -m pip install --user pipx && pipx ensurepath`.

### `kanonInstall` fails with "kanon: command not found"

The `kanon` CLI must be installed before running `kanonInstall`. Install it with `pipx install kanon-cli`.

### `repo envsubst` fails

Ensure `GITBASE` is set in `.kanon` and is a valid URL ending with `/`.

### `repo sync` fails with authentication errors

Ensure `git` can authenticate with the Git hosting provider for your package repositories (SSH keys or credential helper).

### Package scripts are not applied (Gradle only)

Ensure `.packages/` exists and contains package directories. Run `./gradlew kanonInstall` first.
