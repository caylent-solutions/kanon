# How Kanon Works

Technical deep-dive into Kanon internals. For a high-level overview, see [Kanon Guide](kanon-guide.md).

Kanon supports multiple catalog entry packages. The sections below cover both the **Gradle bootstrap** (for Gradle/Spring Boot projects) and the **Python-based lifecycle** (for Make projects and multi-source configurations).

## Bootstrap

The `kanon bootstrap` command scaffolds a new project by copying all files from a catalog entry package, including a pre-configured `.kanon`:

```bash
kanon bootstrap list      # List available catalog entry packages
kanon bootstrap gradle    # Copies .kanon, kanon-bootstrap.gradle, build.gradle, kanon-readme.md
kanon bootstrap make      # Copies .kanon, Makefile, kanon-readme.md
kanon bootstrap kanon     # Copies .kanon, kanon-readme.md (no task runner files)
```

Options:

- `--output-dir DIR` — target directory for bootstrapped files (default: current directory)
- `--catalog-source SOURCE` — remote catalog as `<git_url>@<ref>` where ref is a branch, tag, or `latest` (resolves to highest semver tag). Overrides the `KANON_CATALOG_SOURCE` environment variable. When neither flag nor env var is set, the bundled catalog shipped with the CLI package is used.

The `.kanon` shipped with each catalog entry package is pre-configured by the catalog author. Users of the bundled catalog get example values; users of a remote catalog get values specific to their organization's manifest repository.

## Gradle Bootstrap Flow

The `kanon-bootstrap.gradle` script is the entry point for Gradle-based Kanon consumers. It performs two roles:

### Role 1: Package Auto-Discovery (at Gradle evaluation time)

When Gradle evaluates `build.gradle` and reaches `apply from: 'kanon-bootstrap.gradle'`, the bootstrap script:

1. Reads `.kanon` to get configuration (package directory, tool versions, URLs)
2. Checks if `.packages/` exists
3. If it does, iterates over each subdirectory in `.packages/`
4. For each package directory:
   - Sets `project.ext._rpmCurrentPkgDir` to the package's absolute path
   - Finds all `.gradle` files in the directory (sorted alphabetically)
   - Applies each `.gradle` file via `apply from:`

This means package scripts execute in the context of the project's build. They can apply plugins, configure tasks, add dependencies, and define new tasks — exactly as if the code were in `build.gradle` itself.

### Role 2: Package Sync (via `kanonInstall` task)

The `kanonInstall` Gradle task executes at runtime (not evaluation time). It delegates to the `kanon` CLI:

```groovy
task kanonInstall(type: Exec) {
    commandLine 'kanon', 'install', '.kanon'
}
```

The `kanon` CLI must be installed as a prerequisite (same as Make projects). The CLI handles the full multi-source lifecycle: repo init, envsubst, sync, symlink aggregation, and marketplace installation. See the Python-Based Install section below for the full step-by-step breakdown.

### Python-Based Install (Multi-Source)

The `kanon install` command implements the multi-source
install lifecycle. It is invoked via
`kanon install .kanon`.

The command performs these steps:

1. **Parse `.kanon`** — Reads configuration via the kanon parser module, auto-discovering sources from `KANON_SOURCE_<name>_URL` patterns
2. **Validate sources** — Verifies all required variables present for each source (fail-fast if missing)
3. **Pre-sync marketplace setup** — If `KANON_MARKETPLACE_INSTALL=true`: creates `CLAUDE_MARKETPLACES_DIR` and cleans its contents for a fresh sync
4. **For each source in alphabetical order:**
   - Creates `.kanon-data/sources/<name>/` directory
   - Runs `repo init -u <URL> -b <REVISION> -m <PATH>` in the source directory
   - Exports `GITBASE` and `CLAUDE_MARKETPLACES_DIR`, runs `repo envsubst`
   - Runs `repo sync` — aborts immediately on non-zero exit
5. **Aggregate symlinks** — For each `.kanon-data/sources/<name>/.packages/*`, creates a symlink in `.packages/`
6. **Collision detection** — If two sources produce the same package name, fails fast with error identifying both sources
7. **Update `.gitignore`** — Ensures `.packages/` and `.kanon-data/` entries are present
8. **Post-sync marketplace install** — If `KANON_MARKETPLACE_INSTALL=true`: locates the `claude` binary, discovers marketplace entries and plugins, registers marketplaces, and installs plugins via the Claude Code CLI

### Python-Based Clean (Full Teardown)

The `kanon clean` command implements the clean
lifecycle. It is invoked via
`kanon clean .kanon`.

The command performs these steps in order:

1. **Parse `.kanon`** — Reads configuration via the kanon parser module
2. **If `KANON_MARKETPLACE_INSTALL=true`:**
   - Uninstalls marketplace plugins via the Claude Code CLI (discovers entries, uninstalls each plugin, removes marketplace registrations)
   - Removes `CLAUDE_MARKETPLACES_DIR` entirely
3. **Remove `.packages/`** — `shutil.rmtree` with `ignore_errors=True`
4. **Remove `.kanon-data/`** — `shutil.rmtree` with `ignore_errors=True`

The order is critical: uninstalling plugins first ensures Claude Code's
registry is clean. Removing the marketplace directory before deleting
symlinks ensures the Kanon CLI can resolve marketplace paths during removal.
Deleting `.packages/` and `.kanon-data/` last avoids broken symlinks during uninstall.

## Symlinks via `<linkfile>`

Some packages contain assets (like checkstyle rules or config files) that IDEs or other tools expect at conventional paths in the project root. Rather than requiring consumers to reference `.packages/` directly, the manifest's `<linkfile>` element creates symlinks:

```xml
<project name="my-gradle-checkstyle" path=".packages/my-gradle-checkstyle"
         remote="origin" revision="refs/tags/1.0.0">
  <linkfile src="config/checkstyle/checkstyle.xml" dest="config/checkstyle/checkstyle.xml" />
  <linkfile src="config/checkstyle/suppressions.xml" dest="config/checkstyle/suppressions.xml" />
</project>
```

After `repo sync`, the project has `config/checkstyle/checkstyle.xml` as a symlink pointing into `.packages/`. This means:
- IDE settings (e.g., VS Code `java.checkstyle.configuration`) continue to reference `config/checkstyle/checkstyle.xml` — no path changes needed
- The symlinked paths should be gitignored since they are regenerated by `kanonInstall`
- Gradle package scripts still use `PKG_DIR` to reference assets directly (they don't use the symlinks)

## External Plugin Resolution

Some Kanon packages need external Gradle plugins that are not part of Gradle's core. For example:
- A Spring Boot package needs `org.springframework.boot` and `io.spring.dependency-management`
- A SonarQube package needs `org.sonarqube`
- A security package needs `org.owasp.dependencycheck`

These plugins must be on the build classpath **before** `apply from: 'kanon-bootstrap.gradle'` executes (because the package scripts use `apply plugin:`). The project's `build.gradle` handles this with a `buildscript {}` block that reads `rpm-manifest.properties` from each package:

```groovy
buildscript {
    repositories {
        mavenCentral()
        gradlePluginPortal()
    }
    def packagesDir = file('.packages')
    if (packagesDir.exists()) {
        packagesDir.eachDir { pkg ->
            def manifest = file("${pkg}/rpm-manifest.properties")
            if (manifest.exists()) {
                def props = new Properties()
                manifest.withInputStream { props.load(it) }
                props.getProperty('buildscript.dependencies', '').split(',')
                    .findAll { it.trim() }
                    .each { dep -> dependencies { classpath dep.trim() } }
            }
        }
    }
}
```

Core Gradle plugins (java, checkstyle, jacoco) need no `buildscript` entry.

## Package Script Context

Each `.gradle` script applied by the bootstrap has access to:

- `project` — The Gradle project object (same as in `build.gradle`)
- `project.ext._rpmCurrentPkgDir` — Absolute path to the package directory, so scripts can reference their own config files, templates, etc.

Example from the checkstyle package:
```groovy
def PKG_DIR = project.ext.get('_rpmCurrentPkgDir')

apply plugin: 'checkstyle'
checkstyle {
    configFile = file("${PKG_DIR}/config/checkstyle/checkstyle.xml")
    configProperties['config_loc'] = "${PKG_DIR}/config/checkstyle"
}
```

## Environment Variable Override

`.kanon` values can be overridden by environment variables. The bootstrap script checks `System.getenv()` first, then falls back to the `.kanon` property:

```groovy
def kanonProp = { String key ->
    System.getenv(key) ?: kanonEnv.getProperty(key)
}
```

This enables CI/CD pipelines to override values (e.g., `GITBASE`, `REPO_MANIFESTS_REVISION`) without modifying `.kanon`.
