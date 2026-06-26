# Lifecycle

## Install Lifecycle (`kanon install`)

```text
1. Parse .kanon, auto-discover sources from KANON_SOURCE_<alias>_URL patterns
2. Validate KANON_SOURCE_<alias>_* variables
3. If any source sets KANON_SOURCE_<alias>_MARKETPLACE=true:
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
8. If any source sets KANON_SOURCE_<alias>_MARKETPLACE=true:
   locate claude binary, discover marketplace entries and plugins,
   register marketplaces, install plugins via claude CLI
9. Reconcile marketplace ownership (per-source registered_marketplaces ledgers):
   auto-unregister any marketplace recorded in the previous lockfile
   that no current source registers (e.g. a source dropped from .kanon,
   or its KANON_SOURCE_<alias>_MARKETPLACE flag toggled off), then write
   the lockfile with each source's registered_marketplaces refreshed
```

All repo operations (init, envsubst, sync) are direct Python API calls into `kanon_cli.repo`.
No external binaries are invoked; no PATH lookups are performed.

Step 9 compares the union of every source's recorded
`registered_marketplaces` in the existing lockfile (`OLD`) against the
marketplaces attributed to the current sources this run (`NEW`). Any name
in `OLD` but not in `NEW` is an orphan and is unregistered from `~/.claude`
via `claude plugin marketplace remove`. Removal candidates come only from
the lockfile ledgers, so a marketplace kanon never recorded is never
touched. See
[docs/lockfile.md -- Marketplace ownership and pruning](lockfile.md#marketplace-ownership-and-pruning).

## Clean Lifecycle (`kanon clean`)

```text
1. Resolve .kanon symlinks (kanonenv_path.resolve())
2. Parse .kanon
3. If --orphans: prune orphaned-source marketplaces (see below), then continue
4. If a marketplace was registered (from .kanon.lock marketplace_registered,
   else any source's .kanon KANON_SOURCE_<alias>_MARKETPLACE flag):
   a. Uninstall marketplace plugins via claude CLI
   b. rm -rf CLAUDE_MARKETPLACES_DIR
5. rm -rf .packages/ (ignore_errors)
6. rm -rf .kanon-data/ (ignore_errors)
```

Steps execute in this specific order: uninstalling plugins first ensures
Claude Code's registry is clean. Removing marketplaces before deleting
symlinks ensures the CLI can resolve paths during removal.

### `kanon clean --orphans`

With `--orphans`, before the normal teardown kanon unregisters the
marketplaces of orphaned sources -- `[[sources]]` entries recorded in
`.kanon.lock` whose `name` no longer appears in the current `.kanon`
(removed via `kanon remove` but not yet reconciled by `kanon install`).
Each such marketplace is unregistered from `~/.claude` via
`claude plugin marketplace remove`. Removal candidates come only from the
orphaned sources' per-source `registered_marketplaces` ledgers, and a
marketplace also provided by a still-referenced source is retained, so the
keep-set and user-managed marketplaces are never touched. Plain
`kanon clean` (without `--orphans`) leaves this teardown path unchanged.
See
[docs/lockfile.md -- Marketplace ownership and pruning](lockfile.md#marketplace-ownership-and-pruning).

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
