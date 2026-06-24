# Coming From pip / npm / cargo

If you already work with another package manager, this guide maps the concepts
and commands you know onto the kanon model.

## Audience

This guide is for engineers who are comfortable with one or more of:

- **pip / Python packaging** (`pip`, `pipenv`, `poetry`, `uv`)
- **npm / Node.js packaging** (`npm`, `yarn`, `pnpm`)
- **cargo / Rust packaging** (`cargo`)

...and who want to understand how the same operations map to kanon.

## Translation table

| Concept | pip | npm | cargo | kanon |
| --- | --- | --- | --- | --- |
| Install deps | pip install -r req.txt | npm ci | cargo build | kanon install |
| Declare file | req.txt | pkg.json | Cargo.toml | .kanon |
| Lockfile | Pipfile.lock | pkg-lock.json | Cargo.lock | .kanon.lock |
| Registry | PyPI | npm registry | crates.io | manifest repo |
| Search | pip search | npm search | cargo search | kanon search |
| Add | pip install x==1.0 | npm i x@1.0 | cargo add x@1.0 | kanon add x@1.0 |
| Outdated | pip list -o | npm outdated | cargo outdated | kanon outdated |

## Where the model differs

**kanon has no central registry.**

In pip, npm, and cargo there is a well-known central index (PyPI, npm registry,
crates.io) that every user connects to by default. You can mirror or proxy it,
but the central instance exists and its URL is baked into the tooling.

kanon deliberately has no such central instance. Instead:

- Each workspace declares its own **catalog source** -- a git repository URL
  that acts as the package catalog for that workspace.
- The catalog source is chosen by the operator (your team, your organization)
  and configured per workspace.
- There is no kanon-operated registry, no shared public index, and no default
  URL embedded in the tool.

This means:

- Two teams can use different catalogs without conflicting.
- A catalog can be hosted on any git provider (or a self-hosted server).
- Catalog contents are versioned, auditable, and entirely under your control.
- `kanon search` and `kanon add` operate against YOUR configured catalog, not a
  shared global one.

For details on how to configure and point to a catalog, see
[Catalogs explained](catalogs-explained.md).

## Worked translation example

The scenario: **add `package-a` at version `1.4.2` to the current project.**

### pip

```shell
pip install "package-a==1.4.2"
# Then pin it:
pip freeze > requirements.txt
```

### npm

```shell
npm install package-a@1.4.2
# package.json and package-lock.json are updated automatically.
```

### cargo

```shell
cargo add package-a --version 1.4.2
# Cargo.toml and Cargo.lock are updated automatically.
```

### kanon

```shell
# Ensure your workspace is configured with a catalog source first:
# KANON_CATALOG_SOURCE=https://example.com/org/manifest-repo.git@main

kanon add package-a@1.4.2
# .kanon and .kanon.lock are updated automatically.
```

The kanon command follows the same pattern as the others: declare the package
name and version constraint, and the tool resolves, fetches, and pins the
result.

## See also

- [list-and-add.md](list-and-add.md) -- Full reference for `kanon search` and
  `kanon add`.
- [lockfile.md](lockfile.md) -- How `.kanon.lock` is structured and when it is
  regenerated.
- [catalogs-explained.md](catalogs-explained.md) -- How catalog sources work,
  how to configure them, and how to author your own.
