# Vendored `repo` — deviations from upstream

`src/kanon_cli/repo/` is a vendored fork of Google's
[`git-repo`](https://gerrit.googlesource.com/git-repo/), embedded as a Python
package by commit `e5a43e5` ("embed rpm-git-repo as kanon_cli.repo").

## No upstream base revision is recorded

**This is the gap, and it is not resolved by this file.** No upstream commit SHA,
release tag, `REPO_REV`, version constant or NOTICE file exists anywhere in the
tree, so the fork cannot be diffed against upstream. That means an upstream
security fix cannot be located, assessed, or absorbed without first
reconstructing the base by hand.

Establishing it would mean diffing this tree against successive upstream releases
until the closest match emerges — archaeology across 32 files with an uncertain
result. It has not been attempted. **If anyone ever does establish it, record it
here first.**

What follows is the deviations we *know* about, so a reviewer can at least see
where this tree departs from upstream behaviour, and so a future resync has a
starting list.

## Known deviations

### Absolute `dest` for `<linkfile>` and `<copyfile>`

Upstream `_CheckLocalPath` has no `abs_ok` parameter and documents the opposite
rule — *"Copying from paths outside of the project or to paths outside of the
repo client is not allowed"*. This fork permits an absolute `dest`.

- `abs_ok` for `<linkfile>` arrived with the original embed (`e5a43e5`), so it
  has never matched upstream.
- `9c592c9` extended it to `<copyfile>`.
- The containment boundary in `_ResolveAbsDest` (`project.py`) is fork-local and
  has no upstream counterpart. It exists because a manifest is fetched from a
  remote repository, so an unconfined absolute `dest` is an arbitrary-file-write
  primitive. See [`docs/security-model.md`](../../../docs/security-model.md).

`docs/repo/manifest-format.md` is a vendored upstream document that has been
edited to describe this fork's behaviour rather than upstream's.

### `repo envsubst` subcommand

`subcmds/envsubst.py` does not exist upstream. It expands `${VAR}` / `$VAR`
references in a manifest before sync, which is how kanon parameterises manifests
per consumer.

### PEP 440 version constraints

`version_constraints.py` is fork-local, with call sites in `manifest_xml.py` and
`project.py`. Upstream resolves a `revision` as a git ref; this fork additionally
accepts PEP 440 constraints (`~=1.0`, `>=1.2,<2.0`) and resolves them against the
available tags.

### Signal-handler restore in `forall`

`963fe6d` skips restoring a signal handler when `signal.getsignal()` returned
`None`. Upstream passes that value straight to `signal.signal()`, which raises
`TypeError` when the installed handler was not set from Python.

## Constraints this tree is under

- **Excluded from the no-comments lint gate** (`tools/lint/check_no_comments.py`),
  so `#` comments are permitted here and nowhere else in first-party Python.
- **Excluded from bandit** (`Makefile`, `-x src/kanon_cli/repo`).
- **Omitted from the coverage gate** (`pyproject.toml`, `[tool.coverage.run]`),
  and covered by its own test tier, `make test-unit-vendored`.
- **Excluded from the ruff pre-commit hook** (`.pre-commit-config.yaml`).

Taken together, first-party code written *into* this tree — the containment
helper is the clearest example — is covered by no static-analysis or coverage
gate. Keep fork-local logic minimal and prefer putting it in `kanon_cli/core/`
where the gates apply.
