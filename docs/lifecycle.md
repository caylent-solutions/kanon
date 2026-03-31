# Lifecycle

## Configure Lifecycle (`rpm configure`)

```text
1. Parse .rpmenv, auto-discover sources from RPM_SOURCE_<name>_URL patterns
2. Validate RPM_SOURCE_<name>_* variables
3. Check pipx on PATH (fail-fast)
4. Install repo tool:
   - If REPO_URL and REPO_REV both set (git override):
     resolve REPO_REV (PEP 440), pipx install --force "git+URL@REV"
   - If both omitted (default): check pipx list for rpm-git-repo,
     install from PyPI if not present
   - If only one set: fail-fast with error
6. If RPM_MARKETPLACE_INSTALL=true:
   mkdir -p CLAUDE_MARKETPLACES_DIR, clean contents
7. For each source in alphabetical order:
   a. mkdir -p .rpm/sources/<name>/
   b. repo init -u URL -b REVISION -m PATH --no-repo-verify [--repo-rev REV]
   c. GITBASE=... CLAUDE_MARKETPLACES_DIR=... repo envsubst
   d. repo sync (fail-fast on non-zero)
8. Aggregate: symlink .rpm/sources/<name>/.packages/* -> .packages/
9. Collision check: fail-fast if duplicate package names
10. Update .gitignore with .packages/ and .rpm/
11. If RPM_MARKETPLACE_INSTALL=true:
    locate claude binary, discover marketplace entries and plugins,
    register marketplaces, install plugins via claude CLI
```

## Clean Lifecycle (`rpm clean`)

```text
1. Parse .rpmenv
2. If RPM_MARKETPLACE_INSTALL=true:
   a. Uninstall marketplace plugins via claude CLI
   b. rm -rf CLAUDE_MARKETPLACES_DIR
3. rm -rf .packages/ (ignore_errors)
4. rm -rf .rpm/ (ignore_errors)
```

Steps execute in this specific order: uninstalling plugins first ensures
Claude Code's registry is clean. Removing marketplaces before deleting
symlinks ensures the CLI can resolve paths during removal.

## Directory Structure After Configure

```text
project/
  .rpmenv                           # Configuration (committed)
  Makefile                          # Catalog entry file (committed)
  .rpm/                             # RPM state (gitignored)
    sources/
      build/                        # Source workspace
        .packages/
          rpm-python-lint/
      marketplaces/                 # Source workspace
        .packages/
          rpm-claude-marketplaces-example-dev-lint/
  .packages/                        # Aggregated symlinks (gitignored)
    rpm-python-lint -> ../.rpm/sources/build/.packages/rpm-python-lint
    rpm-claude-marketplaces-example-dev-lint -> ../.rpm/sources/marketplaces/.packages/...
```
