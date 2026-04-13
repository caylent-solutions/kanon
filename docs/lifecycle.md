# Lifecycle

## Install Lifecycle (`kanon install`)

```text
1. Parse .kanon, auto-discover sources from KANON_SOURCE_<name>_URL patterns
2. Validate KANON_SOURCE_<name>_* variables
3. Check pipx on PATH (fail-fast)
4. Install repo tool:
   - If REPO_URL and REPO_REV both set (git override):
     resolve REPO_REV (PEP 440), pipx install --force "git+URL@REV"
   - If both omitted (default): check pipx list for rpm-git-repo,
     install from PyPI if not present
   - If only one set: fail-fast with error
6. If KANON_MARKETPLACE_INSTALL=true:
   mkdir -p CLAUDE_MARKETPLACES_DIR, clean contents
7. For each source in alphabetical order:
   a. mkdir -p .kanon-data/sources/<name>/
   b. repo init -u URL -b REVISION -m PATH --no-repo-verify [--repo-rev REV]
   c. GITBASE=... CLAUDE_MARKETPLACES_DIR=... repo envsubst
   d. repo sync (fail-fast on non-zero)
8. Aggregate: symlink .kanon-data/sources/<name>/.packages/* -> .packages/
9. Collision check: fail-fast if duplicate package names
10. Update .gitignore with .packages/ and .kanon-data/
11. If KANON_MARKETPLACE_INSTALL=true:
    locate claude binary, discover marketplace entries and plugins,
    register marketplaces, install plugins via claude CLI
```

## Clean Lifecycle (`kanon clean`)

```text
1. Parse .kanon
2. If KANON_MARKETPLACE_INSTALL=true:
   a. Uninstall marketplace plugins via claude CLI
   b. rm -rf CLAUDE_MARKETPLACES_DIR
3. rm -rf .packages/ (ignore_errors)
4. rm -rf .kanon-data/ (ignore_errors)
```

Steps execute in this specific order: uninstalling plugins first ensures
Claude Code's registry is clean. Removing marketplaces before deleting
symlinks ensures the CLI can resolve paths during removal.

## Directory Structure After Install

```text
project/
  .kanon                                # Configuration (committed)
  Makefile                              # Catalog entry file (committed)
  .kanon-data/                          # Kanon state (gitignored)
    sources/
      build/                            # Source workspace
        .packages/
          kanon-python-lint/
      marketplaces/                     # Source workspace
        .packages/
          kanon-claude-marketplaces-example-dev-lint/
  .packages/                            # Aggregated symlinks (gitignored)
    kanon-python-lint -> ../.kanon-data/sources/build/.packages/kanon-python-lint
    kanon-claude-marketplaces-example-dev-lint -> ../.kanon-data/sources/marketplaces/.packages/...
```
