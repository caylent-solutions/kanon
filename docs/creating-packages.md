# Creating Packages

How to create automation packages that Kanon manifest repositories can reference.

## What is a Package?

A Kanon package is a Git repository containing automation scripts, configuration files, or tooling that gets synced into a consumer project's `.packages/` directory. Packages are versioned with Git tags and referenced by manifest XML files.

## Package Structure

A package repository can contain any combination of automation artifacts:

```text
my-package/
├── <concern>.gradle           # Gradle script with tasks/config
├── Makefile                   # Make targets
├── rpm-manifest.properties    # Optional: external Gradle plugin dependencies
├── config/                    # Optional: configuration files (checkstyle, etc.)
├── README.md                  # Package documentation
└── CHANGELOG.md               # Version history
```

The package structure depends on the task runner ecosystem:

- **Gradle packages** — contain `.gradle` scripts that are auto-applied by `kanon-bootstrap.gradle`
- **Make packages** — contain `Makefile` files that are auto-included by the bootstrap `Makefile`
- **Generic packages** — contain any files (scripts, configs, templates) accessed via `.packages/<name>/` (used with the `kanon` standalone catalog entry or any custom workflow)

## Versioning

Use [semantic versioning](https://semver.org/) for Git tags:

- **MAJOR** — breaking changes (renamed tasks, removed config, changed behavior)
- **MINOR** — new features (new tasks, new config options)
- **PATCH** — bug fixes (corrected config, fixed task behavior)

Tag format: `1.0.0`, `2.1.3`, etc.

For packages that serve multiple concerns, use path-prefixed tags:

```text
refs/tags/build-conventions/1.0.0
refs/tags/linting-rules/2.1.0
```

This enables PEP 440 version constraints in manifests (e.g., `revision="refs/tags/build-conventions/~=1.0.0"`).

## Registering a Package

To make a package available through Kanon, add a `<project>` entry to a manifest XML file in your manifest repository:

```xml
<project name="my-package"
         path=".packages/my-package"
         remote="origin"
         revision="refs/tags/1.0.0">
</project>
```

See [Creating Manifest Repos](creating-manifest-repos.md) for details on manifest structure.

## Gradle Package Guidelines

For Gradle packages auto-applied by `kanon-bootstrap.gradle`:

1. **Use `_rpmCurrentPkgDir`** to reference package-local files:

   ```groovy
   def PKG_DIR = project.ext.get('_rpmCurrentPkgDir')
   ```

2. **Do not hard-code organization-specific values.** Use project properties or `.kanon` values via `_rpmProp`:

   ```groovy
   def rpmProp = project.ext.get('_rpmProp')
   def serverUrl = rpmProp('SONAR_HOST_URL')
   ```

3. **Use `apply plugin:` for core plugins** (java, checkstyle, jacoco). Declare external plugin dependencies in `rpm-manifest.properties`.

4. **Document all provided tasks** in the package README.

### External Plugin Dependencies (rpm-manifest.properties)

If your Gradle package needs external plugins, declare them in `rpm-manifest.properties`:

```properties
# Format: plugin-id=group:artifact:version
org.sonarqube=org.sonarsource.scanner.gradle:sonarqube-gradle-plugin:4.0.0.2929
org.owasp.dependencycheck=org.owasp:dependency-check-gradle:9.0.9
```

The `kanon-bootstrap.gradle` script reads this file and adds the dependencies to the buildscript classpath before applying your package script.

## Make Package Guidelines

For Make packages auto-included by the bootstrap Makefile:

1. Define targets with `##` comments for help text:

   ```makefile
   lint: ## Run linters
   	ruff check .
   ```

2. Use variables for configurable values, not hard-coded paths.

3. Prefix internal targets with `_` to hide them from the help output.

## Marketplace Packages

Marketplace packages are a special type of package that expose Claude Code plugins via symlinks. They use `<linkfile>` elements in their manifest entries:

```xml
<project name="my-marketplace-package"
         path=".packages/my-marketplace-plugin"
         remote="origin"
         revision="refs/tags/1.0.0">
  <linkfile src="plugin-dir"
            dest="${CLAUDE_MARKETPLACES_DIR}/my-marketplace-plugin" />
</project>
```

The `<linkfile>` creates a symlink from the package's source directory to the Claude Code marketplaces directory, making the plugin discoverable.

See the [Claude Marketplaces Guide](claude-marketplaces-guide.md) for details on marketplace manifest hierarchies and the install/uninstall lifecycle.
