# Creating Packages

How to create automation packages that Kanon manifest repositories can reference.

## What is a Package?

A Kanon package is a Git repository containing automation scripts, configuration files, or tooling that gets synced into a consumer project's `.packages/` directory. Packages are versioned with Git tags and referenced by manifest XML files.

## Package Structure

A package repository can contain any combination of automation artifacts:

```text
my-package/
├── scripts/                   # Automation scripts (shell, Python, etc.)
├── config/                    # Optional: configuration files (checkstyle, etc.)
├── README.md                  # Package documentation
└── CHANGELOG.md               # Version history
```

Packages contain any files (scripts, configs, templates) accessed via `.packages/<name>/`.

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
