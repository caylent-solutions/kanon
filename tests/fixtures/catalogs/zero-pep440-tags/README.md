# Fixture: zero-pep440-tags

This fixture directory provides the static source files for the `zero-pep440-tags`
manifest-repo fixture used by `tests/integration/test_add_zero_tags.py`.

## Purpose

Exercises the default-spec loud-error path in `kanon add` (spec Section 4.2,
step 4): when the operator omits `@<spec>` and the manifest repo has either
zero tags total or zero PEP 440-valid tags, the command must exit non-zero
with the spec-verbatim error message.

## Subcases

The integration tests build two in-memory bare git repos from this content:

1. **Zero-tags-total** -- a git repo whose only content is committed but has
   no git tags at all. The `git ls-remote --tags` query returns an empty list.

2. **Zero-PEP-440-tags** -- a git repo with non-PEP-440 tags only (e.g.
   `release-2024`, `ops-marker`). The query returns tags, but none of their
   last `/`-delimited path components parse as `packaging.version.Version`.

## Contents

- `repo-specs/entry-a/entry-a-marketplace.xml` -- minimal valid marketplace
  XML so that the fixture catalog is non-empty and `kanon add entry-a` can
  attempt entry resolution before hitting the tag-selection error.

## Test setup

`tests/integration/test_add_zero_tags.py` uses `conftest.py`-style helpers to
build temporary bare git repos from the XML files above, apply (or omit) tags,
clone them to a `file://` URL, and invoke `kanon add entry-a` via subprocess.
The static files here are copied into each temporary repo at setup time.
