# Catalogs Explained

## What is a manifest repo?

A manifest repo is a git repository whose `repo-specs/` directory exposes
installable kanon dependencies. It acts as a catalog of packages that kanon
can install into a project's `.kanon` file. Each entry in the catalog
describes a dependency -- its name, version tags, source URL, and the
template `.kanon` file a user receives when they install the package.

kanon does not ship a built-in catalog. Your organization hosts its own
manifest repo (or uses a shared community one), and you point kanon at it
via the `--catalog-source` flag or the `KANON_CATALOG_SOURCE` environment
variable.

## How to find a manifest repo

Ask your platform team or the kanon catalog author for the manifest repo URL.
The URL follows the format:

```
<git-url>@<ref>
```

For example:

```
https://github.com/example-org/kanon-catalog.git@main
```

You can then use it as:

```bash
kanon list --catalog-source https://github.com/example-org/kanon-catalog.git@main
```

Or export it as an environment variable so every kanon command uses it
automatically:

```bash
export KANON_CATALOG_SOURCE=https://github.com/example-org/kanon-catalog.git@main
kanon list
```

See `docs/creating-manifest-repos.md` for instructions on creating your own
manifest repo.

## What does the missing-catalog-source error mean?

When you see the following error, kanon could not determine which catalog to
use because neither `--catalog-source` nor `KANON_CATALOG_SOURCE` was set:

```
ERROR: <command> requires a catalog source.
Provide one of:
  --catalog-source <git-url>@<ref>      # e.g. --catalog-source https://example.com/org/manifest-repo.git@main
  KANON_CATALOG_SOURCE=<git-url>@<ref>  # set as env var, then re-run
The CLI flag takes precedence when both are set.
A catalog source identifies a manifest repo (a git repository whose
repo-specs/ directory exposes installable kanon dependencies).
See docs/catalogs-explained.md for what a manifest repo is and how to find one.
See docs/configuration.md for the full configuration reference.
```

To fix this error, supply a catalog source using one of the two methods shown
in the message. The `--catalog-source` flag is accepted by all catalog-requiring
commands (`list`, `add`, `outdated`, `why`, `catalog audit`). The
`KANON_CATALOG_SOURCE` environment variable is a convenient alternative when
you always work against the same catalog.

The commands `kanon install` and `kanon doctor` may additionally fall back to
the `[catalog].source` field recorded in the lockfile when neither flag nor
env var is set. See `docs/configuration.md` for the full precedence chain.
