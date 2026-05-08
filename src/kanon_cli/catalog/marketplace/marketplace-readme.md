# Kanon -- Marketplace Monorepo

A marketplace is a monorepo where each subdirectory is a Claude Code plugin. When registered with Kanon, each plugin is installed as a separate entry in `CLAUDE_MARKETPLACES_DIR`.

---

## Structure

Each plugin lives in its own subdirectory and must contain a `plugin.json`:

```
your-marketplace/
├── my-plugin/
│   ├── plugin.json       # required — plugin metadata
│   ├── CLAUDE.md         # typical — instructions for Claude Code
│   └── settings.json     # optional — hooks and permissions
├── another-plugin/
│   ├── plugin.json
│   └── CLAUDE.md
└── .github/
    └── workflows/
        └── validate.yml  # optional — CI validation
```

### `plugin.json` format

```json
{
  "name": "my-plugin",
  "description": "What this plugin does",
  "author": {
    "name": "your-github-username",
    "url": "https://github.com/your-github-username"
  },
  "version": "0.1.0",
  "keywords": []
}
```

---

## Setup

### 1. Replace the example plugin

Rename `example-plugin/` to your plugin name and update its `plugin.json`, `CLAUDE.md`, and any other files.

### 2. Validate locally

```bash
kanon validate marketplace
```

This checks every subdirectory's `plugin.json` for required fields and valid JSON.

### 3. Publish to GitHub

Push your marketplace to a GitHub repository, then register it with a Kanon manifest.

### 4. Register with Kanon

In your kanon manifest XML, add a `<project>` for your marketplace with one `<linkfile>` per plugin:

```xml
<project name="your-marketplace"
         path=".packages/your-marketplace"
         remote="your-remote"
         revision="main">
    <linkfile src="my-plugin" dest="${CLAUDE_MARKETPLACES_DIR}/your-marketplace-my-plugin" />
    <linkfile src="another-plugin" dest="${CLAUDE_MARKETPLACES_DIR}/your-marketplace-another-plugin" />
</project>
```

### 5. Enable marketplace installs in `.kanon`

```properties
KANON_MARKETPLACE_INSTALL=true
CLAUDE_MARKETPLACES_DIR=${HOME}/.claude-marketplaces
```

Then run `kanon install .kanon`.

### 6. Commit

Commit `plugin.json` files and any plugin contents to your repository. Add `.packages/` and `.kanon-data/` to `.gitignore`.

---

## Adding More Plugins

Add a new subdirectory with a `plugin.json`. No manifest changes needed if the `<linkfile>` entries in your Kanon XML already reference it, or add a new `<linkfile>` if not.

---

## CI Validation

The included `.github/workflows/validate.yml.template` is a ready-to-use GitHub Actions workflow. Copy it to `.github/workflows/validate.yml` in your marketplace repo to run `kanon validate marketplace` on every push and pull request:

```bash
cp .github/workflows/validate.yml.template .github/workflows/validate.yml
```

This catches missing or malformed `plugin.json` files early.

---

## Troubleshooting

- **`kanon validate marketplace` reports missing fields** -- Edit the `plugin.json` and ensure `name`, `description`, `author`, `version`, and `keywords` are all present.
- **Plugin not appearing after `kanon install`** -- Confirm `KANON_MARKETPLACE_INSTALL=true` in `.kanon` and that the plugin has a `<linkfile>` in the manifest XML.
- **Authentication errors during sync** -- If you use SSH for Git auth, configure the HTTPS-to-SSH rewrite globally: `git config --global url."git@github.com:".insteadOf "https://github.com/"`.
