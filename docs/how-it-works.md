# How Kanon Works

Technical deep-dive into Kanon internals. For a high-level overview, see the [README](../README.md).

Kanon's `kanon_cli.repo` subsystem orchestrates dependencies across git repositories using a
manifest-driven sync. All repo operations are in-process Python API calls -- no external
binaries are invoked and no PATH lookups are performed.

## Package Structure

The `kanon_cli.repo` subsystem is structured as:

```
kanon_cli/
  repo/           # kanon repo subsystem
    __init__.py   # Public Python API: repo_init, repo_envsubst, repo_sync, repo_run
    main.py       # Core run_from_args() entry point
    subcmds/      # repo subcommands (init, sync, envsubst, ...)
    ...
  commands/
    install.py    # kanon install -- calls kanon_cli.repo Python API
    clean.py      # kanon clean
```

### Python API

`kanon_cli.repo` exposes a stable Python API used directly by `kanon_cli.core.install`:

- `repo_init(repo_dir, url, revision, manifest_path, repo_rev)` -- Initialize a repo checkout
- `repo_envsubst(repo_dir, env_vars)` -- Substitute environment variables in manifest XML files
- `repo_sync(repo_dir)` -- Clone and fetch all projects defined in the manifest
- `repo_run(argv, repo_dir=...)` -- General-purpose dispatcher for arbitrary repo subcommands
- `RepoCommandError` -- Exception raised when a repo command exits with a non-zero exit code

No external binaries are invoked and no PATH lookups are performed: every call is a direct
in-process Python API call.

## Bootstrap

The `kanon bootstrap` command scaffolds a new project by copying all files from a catalog entry package, including a pre-configured `.kanon`:

```bash
kanon bootstrap list      # List available catalog entry packages
kanon bootstrap kanon     # Copies .kanon, kanon-readme.md
```

Options:

- `--output-dir DIR` -- target directory for bootstrapped files (default: current directory)
- `--catalog-source SOURCE` -- remote catalog as `<git_url>@<ref>` where ref is a branch, tag, `latest` (resolves to highest semver tag), or a PEP 440 version constraint (e.g., `~=2.0.0`, `>=2.0.0,<3.0.0`). Overrides the `KANON_CATALOG_SOURCE` environment variable. When neither flag nor env var is set, the bundled catalog shipped with the CLI package is used.

The `.kanon` shipped with each catalog entry package is pre-configured by the catalog author. Users of the bundled catalog get example values; users of a remote catalog get values specific to their organization's manifest repository.

## Install Lifecycle

The `kanon install` command implements the install lifecycle. It is invoked via `kanon install` (auto-discovers the `.kanon` file by walking up the directory tree from the current directory) or `kanon install .kanon` (explicit path).

The command performs these steps:

1. **Parse `.kanon`** -- Reads configuration via the kanon parser module, auto-discovering sources from `KANON_SOURCE_<name>_URL` patterns
2. **Validate sources** -- Verifies all required variables present for each source (fail-fast if missing)
3. **Pre-sync marketplace setup** -- If `KANON_MARKETPLACE_INSTALL=true`: creates `CLAUDE_MARKETPLACES_DIR` and cleans its contents for a fresh sync
4. **For each source in alphabetical order:**
   - Creates `.kanon-data/sources/<name>/` directory
   - Calls `kanon_cli.repo.repo_init(source_dir, url, revision, manifest_path)` -- direct Python API call
   - Calls `kanon_cli.repo.repo_envsubst(source_dir, env_vars)` with `GITBASE` and `CLAUDE_MARKETPLACES_DIR` -- direct Python API call
   - Calls `kanon_cli.repo.repo_sync(source_dir)` -- aborts immediately on `RepoCommandError`
5. **Aggregate symlinks** -- For each `.kanon-data/sources/<name>/.packages/*`, creates a symlink in `.packages/`
6. **Collision detection** -- If two sources produce the same package name, fails fast with error identifying both sources
7. **Update `.gitignore`** -- Ensures `.packages/` and `.kanon-data/` entries are present
8. **Post-sync marketplace install** -- If `KANON_MARKETPLACE_INSTALL=true`: locates the `claude` binary, discovers marketplace entries and plugins, registers marketplaces, and installs plugins via the Claude Code CLI

## Clean Lifecycle

The `kanon clean` command implements the clean lifecycle. It is invoked via `kanon clean` (auto-discovers the `.kanon` file by walking up the directory tree from the current directory) or `kanon clean .kanon` (explicit path).

The command performs these steps in order:

1. **Parse `.kanon`** -- Reads configuration via the kanon parser module
2. **If `KANON_MARKETPLACE_INSTALL=true`:**
   - Uninstalls marketplace plugins via the Claude Code CLI (discovers entries, uninstalls each plugin, removes marketplace registrations)
   - Removes `CLAUDE_MARKETPLACES_DIR` entirely
3. **Remove `.packages/`** -- `shutil.rmtree` with `ignore_errors=True`
4. **Remove `.kanon-data/`** -- `shutil.rmtree` with `ignore_errors=True`

The order is critical: uninstalling plugins first ensures Claude Code's
registry is clean. Removing the marketplace directory before deleting
symlinks ensures the Kanon CLI can resolve marketplace paths during removal.
Deleting `.packages/` and `.kanon-data/` last avoids broken symlinks during uninstall.

## Symlinks via `<linkfile>`

Some packages contain assets (like checkstyle rules or config files) that IDEs or other tools expect at conventional paths in the project root. Rather than requiring consumers to reference `.packages/` directly, the manifest's `<linkfile>` element creates symlinks:

```xml
<project name="my-checkstyle" path=".packages/my-checkstyle"
         remote="origin" revision="refs/tags/1.0.0">
  <linkfile src="config/checkstyle/checkstyle.xml" dest="config/checkstyle/checkstyle.xml" />
  <linkfile src="config/checkstyle/suppressions.xml" dest="config/checkstyle/suppressions.xml" />
</project>
```

After `repo sync`, the project has `config/checkstyle/checkstyle.xml` as a symlink pointing into `.packages/`. This means:
- IDE settings (e.g., VS Code `java.checkstyle.configuration`) continue to reference `config/checkstyle/checkstyle.xml` -- no path changes needed
- The symlinked paths should be gitignored since they are regenerated by `kanon install`
