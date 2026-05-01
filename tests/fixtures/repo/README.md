# Test Fixtures

Golden reference files for git-repo test suite.

## Files

| File | Format | Purpose |
|---|---|---|
| `sample-manifest.xml` | XML | Representative repo tool manifest with remotes, defaults, and projects. Used by `conftest.py::mock_manifest_xml` and manifest parsing tests. |
| `sample-project-config.json` | JSON | Representative project configuration with name, path, remote, and revision fields. Used by `conftest.py::mock_project_config` and project config tests. |
| `linter-test-bad.md` | Markdown | Intentionally invalid Markdown for markdownlint config testing (E0-F1-S2-T2). |
| `linter-test-bad.invalid-yaml` | YAML (extension obfuscated) | Intentionally invalid YAML for yamllint config testing (E0-F1-S2-T3). The file extension is `.invalid-yaml` rather than `.yml` so the pre-commit yamllint hook (which only matches `.yml`/`.yaml`) does not lint the deliberately-broken fixture; the yamllint unit test passes the file path explicitly to the `yamllint` CLI, which lints by content regardless of extension. |
| `linter-test-bad.py` | Python | Intentionally invalid Python for ruff config testing (E0-F1-S2-T1). |
| `test.gitconfig` | Git config | Git configuration fixture for upstream tests. |

## Conventions

- Fixture files are **golden files** — their content is the expected reference.
- Do not modify fixture files without updating corresponding tests.
- New fixtures should be documented in this table.
