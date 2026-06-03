# Catalogs explained

A **manifest repo** is a git repository whose `repo-specs/` directory contains
installable kanon dependency definitions. When you point kanon at a manifest
repo via `--catalog-source`, you are pointing it at the catalog itself -- there
is no separate "catalog" entity inside the repository, and no `catalog/<name>/`
subdirectory model. The repository is the catalog; each `*-marketplace.xml`
file under `repo-specs/**` is a catalog entry.

## What is a manifest repo?

A manifest repo (also called a **catalog repo**) is a git repository that
exposes installable kanon dependencies. Its structure is:

```text
repo-specs/
  my-library-marketplace.xml
  another-tool-marketplace.xml
  ...
```

Each `*-marketplace.xml` file is a **catalog entry** -- a single dependency
definition identified by the `<name>` child of its `<catalog-metadata>` block.
The `<name>` value is the **entry name**. There is exactly one
`<catalog-metadata>` block per XML file, and entry names must be unique across
the manifest repo.

When you install a catalog entry, kanon writes a source block into your
`.kanon` file using the **source name** -- a normalized form of the entry name
derived by lowercasing it and replacing every `-` with `_`. For example, the
entry name `My-Library` becomes the source name `my_library`, and kanon writes
the triple `KANON_SOURCE_my_library_URL` (and related keys) into your `.kanon`
file.

A **catalog source** is a `<git-url>@<ref>` value that identifies a manifest
repo at a specific revision. You pass it via `--catalog-source` or the
`KANON_CATALOG_SOURCE` environment variable. For example:

```text
https://example.com/org/manifest-repo.git@main
```

kanon does not ship a built-in catalog. There is no default catalog source
after the bootstrap deprecation. Your organization hosts its own manifest repo
(or uses a shared community one), and you tell kanon where to find it.

## Who runs manifest repos?

Any team or individual can run a manifest repo. The manifest repo model is
vendor-agnostic: it requires only a git host that supports standard `git clone`
and `git ls-remote` operations.

Common arrangements include:

- A platform engineering team that maintains a shared internal catalog for their
  organization.
- A project team that publishes a manifest repo alongside the libraries or tools
  they own, so consumers can install them with `kanon add`.
- An open-source project that ships a public manifest repo any organization can
  point `--catalog-source` at.
- Individual developers who maintain a personal manifest repo for their own
  scripts and utilities.

No registry, no central authority, and no approval process are required. If you
control a git repository and can push `*-marketplace.xml` files to it, you can
run a manifest repo.

See [creating-manifest-repos.md](creating-manifest-repos.md) for a complete
guide to authoring and publishing your own catalog entries.

## How to find a manifest repo to point at

If you need dependencies managed by another team or project, the manifest repo
URL is the starting point. Here are the most reliable ways to find it:

1. **Ask the team that owns the dependencies.** The team that builds and
   releases the software you want to install is the authoritative source for
   its manifest repo URL. Check their project README or internal documentation
   first.

2. **Look for repos with a `repo-specs/` directory.** Manifest repos are
   identifiable by the presence of a `repo-specs/` directory containing
   `*-marketplace.xml` files. Searching your organization's git host for
   repositories with this structure will surface available catalogs.

3. **Consult the project that built the dependency.** Open-source projects
   that publish kanon-compatible releases typically document the catalog source
   URL in their README or contributing guide.

Once you have a manifest repo URL and a ref (branch name, tag, or commit SHA),
combine them as `<git-url>@<ref>` to form the catalog source value.

## Worked example

This example lists every available dependency in a manifest repo and then adds
one to your `.kanon` file.

```bash
# List every catalog entry in the manifest repo
kanon list --catalog-source https://example.com/org/manifest-repo.git@main
```

Sample output:

```text
my-library
another-tool
```

```bash
# Add one entry (kanon resolves the latest PEP 440 tag automatically)
kanon add my-library --catalog-source https://example.com/org/manifest-repo.git@main

# Or export the catalog source so every command uses it automatically
export KANON_CATALOG_SOURCE=https://example.com/org/manifest-repo.git@main
kanon list
kanon add my-library
```

After `kanon add`, your `.kanon` file contains a source block keyed on the
derived source name (e.g., `KANON_SOURCE_my_library_URL`).

## See also

- [creating-manifest-repos.md](creating-manifest-repos.md) -- author and
  publish your own manifest repo
- [configuration.md](configuration.md) -- full reference for `--catalog-source`
  and `KANON_CATALOG_SOURCE`, including the complete precedence chain
- [list-and-add.md](list-and-add.md) -- full reference for `kanon list`,
  `kanon add`, and `kanon remove`, including all flags and error scenarios
