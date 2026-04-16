# Lifecycle

## Install Lifecycle (`kanon install`)

```text
1. Parse .kanon, auto-discover sources from KANON_SOURCE_<name>_URL patterns
2. Validate KANON_SOURCE_<name>_* variables
3. If KANON_MARKETPLACE_INSTALL=true:
   mkdir -p CLAUDE_MARKETPLACES_DIR, clean contents
4. For each source in alphabetical order:
   a. mkdir -p .kanon-data/sources/<name>/
   b. kanon_cli.repo.repo_init(source_dir, url, revision, manifest_path)
      -- direct Python API call, no subprocess
   c. kanon_cli.repo.repo_envsubst(source_dir, {GITBASE, CLAUDE_MARKETPLACES_DIR})
      -- direct Python API call, no subprocess
   d. kanon_cli.repo.repo_sync(source_dir)
      -- direct Python API call, fail-fast on RepoCommandError
5. Aggregate: symlink .kanon-data/sources/<name>/.packages/* -> .packages/
6. Collision check: fail-fast if duplicate package names
7. Update .gitignore with .packages/ and .kanon-data/
8. If KANON_MARKETPLACE_INSTALL=true:
   locate claude binary, discover marketplace entries and plugins,
   register marketplaces, install plugins via claude CLI
```

All repo operations (init, envsubst, sync) are direct Python API calls into `kanon_cli.repo`.
No external binaries are invoked; no PATH lookups are performed.

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
