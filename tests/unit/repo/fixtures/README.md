# Test Fixtures

Golden reference files for git-repo test suite.

## Files

| File | Format | Purpose |
|---|---|---|
| `sample-manifest.xml` | XML | Representative repo tool manifest with remotes, defaults, and projects. Used by `conftest.py::mock_manifest_xml` and manifest parsing tests. |
| `sample-project-config.json` | JSON | Representative project configuration with name, path, remote, and revision fields. Used by `conftest.py::mock_project_config` and project config tests. |
| `test.gitconfig` | Git config | Git configuration fixture for upstream tests. |

The `linter-test-bad.{md,yml,py}` fixtures live exclusively under
`tests/fixtures/repo/` (single source of truth). The
`tests/unit/repo/fixtures/` copies were deleted as part of CLAUDE.md
DRY enforcement.

## Conventions

- Fixture files are **golden files** — their content is the expected reference.
- Do not modify fixture files without updating corresponding tests.
- New fixtures should be documented in this table.
