# Test Coverage Reference

This document describes the test coverage structure for the kanon CLI,
including synthetic-fixture helpers introduced in E36 and the pytest
fixtures that downstream Epics E42 and E48 consume.

---

## Synthetic-fixture helpers

### Overview

The synthetic-fixture helpers supersede the legacy
`test-fixtures/synthetic-fixtures/` static seed files. Where the legacy
seeds were static files checked in to the repository, the new helpers are
Python functions that materialise a fresh bare git repository at runtime
inside a pytest-provided temporary directory. This removes the need to
maintain committed binary-adjacent git state and gives each test an
isolated, reproducible fixture.

The relocation was introduced by spec §4 E36 (amended 2026-05-27) to fix
FIXTURE-DEFECT-001: the legacy static seeds omitted the `<remote>` and
`<default>` elements required by the repo-tool manifest schema, causing
`repo init` to reject the manifest with a parse error. Downstream Epics
E42 and E48 consume the new pytest fixtures via the ergonomic interface
described below.

### Helper modules

#### `tests/integration/fixtures/synthetic/drift.py`

Exports `create_drift_fixture(tmp_path: pathlib.Path) -> pathlib.Path`.

Materialises a bare git repository whose `manifest.xml` declares
`<remote>` and `<default>` elements **before** any `<project>` element,
satisfying the repo-tool schema requirement. The fetch URL uses the RFC
6761 `.invalid` TLD (`https://test.invalid/x`) which is guaranteed
non-routable, preventing accidental network access during test runs.

Typical use (direct call):

```python
from tests.integration.fixtures.synthetic.drift import create_drift_fixture

bare_path = create_drift_fixture(tmp_path)
```

#### `tests/integration/fixtures/synthetic/upgrade_versioned.py`

Exports
`create_upgrade_versioned_repo_fixture(tmp_path: pathlib.Path) -> pathlib.Path`.

Materialises a bare git repository with the same compliant `manifest.xml`
structure and additionally carries 3 PEP 440-valid annotated tags:
`0.1.0`, `0.2.0`, and `1.0.0`. Each tag is created on a distinct commit
so that tag ordering in the git history is deterministic. The three-tag
set exercises:

- Single-version-bump upgrade detection: `0.1.0` -> `0.2.0`
- Multi-version-bump upgrade detection: `0.1.0` -> `1.0.0`

Typical use (direct call):

```python
from tests.integration.fixtures.synthetic.upgrade_versioned import (
    create_upgrade_versioned_repo_fixture,
)

bare_path = create_upgrade_versioned_repo_fixture(tmp_path)
```

### Pytest fixtures

#### `tests/integration/fixtures/synthetic/conftest.py`

Defines two function-scoped pytest fixtures that are auto-discovered by
pytest for any test file under `tests/integration/fixtures/synthetic/`:

**`synthetic_drift_repo(tmp_path) -> pathlib.Path`**

Wraps `create_drift_fixture`. Returns the absolute path to a
freshly-materialised bare git repo with a compliant `manifest.xml`.
Because the fixture is function-scoped (the pytest default), each
consuming test receives a fresh bare repo isolated under its own
`tmp_path` directory.

**`synthetic_upgrade_versioned_repo(tmp_path) -> pathlib.Path`**

Wraps `create_upgrade_versioned_repo_fixture`. Returns the absolute path
to a freshly-materialised bare git repo with a compliant `manifest.xml`
and annotated tags `0.1.0`, `0.2.0`, and `1.0.0`. Function-scoped for
the same isolation guarantee.

These fixtures are the recommended interface for scenario-automation tests
in downstream Epics E42 and E48. Tests that need the helper functions
directly can still import them from the helper modules.

### Failing-test-first guards

Two integration test files verify both the helper functions and the pytest
fixtures via `repo init` schema acceptance:

**`tests/integration/test_synthetic_drift_fixture.py`**

Guards the `create_drift_fixture` helper. Invokes the helper directly via
`tmp_path`, reads `manifest.xml` from the bare repo using
`git show HEAD:manifest.xml`, asserts that `<remote>` and `<default>`
appear before `<project>`, and asserts that `repo init` exits 0 via
`run_from_args`.

**`tests/integration/test_synthetic_upgrade_versioned_fixture.py`**

Guards the `create_upgrade_versioned_repo_fixture` helper. Performs the
same schema-acceptance assertions as the drift guard and additionally
asserts that all three annotated tags (`0.1.0`, `0.2.0`, `1.0.0`) are
present via `git tag --list`.

**`tests/integration/fixtures/synthetic/test_synthetic_pytest_fixtures.py`**

Guards the pytest fixtures by name. Exercises `synthetic_drift_repo` and
`synthetic_upgrade_versioned_repo` as pytest fixture parameters, asserts
each returned path exists and is a directory, verifies manifest structural
correctness, and asserts `repo init` exit 0. These tests fail with
`FixtureLookupError` before `conftest.py` is authored and pass after.

### Legacy seed relocation note

The legacy `test-fixtures/synthetic-fixtures/` directory contained static
git-state seeds used by pre-E36 integration tests. Those seeds lacked the
`<remote>` and `<default>` manifest declarations required by the repo-tool
schema. The helper modules in
`tests/integration/fixtures/synthetic/` replace those seeds entirely.
Downstream Epics E42 and E48 reference only the new pytest fixtures;
no test in the current suite imports from `test-fixtures/synthetic-fixtures/`.

---

## Remove command coverage

### Purpose

This section documents the automated test coverage for the `kanon remove` command,
satisfying spec §4 E39. All seven behaviour rows from `test-fixtures/findings.md`
rows 46-52 are fully covered by existing integration tests; no new test was
required per spec §4 E39. The rows below are end-to-end asserted by the cited
integration tests -- each test invokes the real `kanon remove` CLI via subprocess
against a temporary `.kanon` file and asserts both the process exit code and the
resulting file state.

### Coverage mapping

| findings.md row | Behaviour | Test file | Class | Line |
|----------------:|-----------|-----------|-------|-----:|
| 46 | remove / single | `tests/integration/test_remove_core.py` | `TestRemoveCoreHappyPath` | 112 |
| 47 | remove / multiple | `tests/integration/test_remove_core.py` | `TestRemoveCoreErrorPaths` | 226 |
| 48 | remove / by-canonical | `tests/integration/test_remove_core.py` | `TestRemoveCoreHappyPath` | 112 |
| 49 | remove / by-original | `tests/integration/test_remove_core.py` | `TestRemoveCoreHappyPath` | 112 |
| 50 | remove / force-absent | `tests/integration/test_remove_force_integration.py` | `TestRemoveForceIntegration` | 75 |
| 51 | remove / dry-run | `tests/integration/test_remove_dry_run.py` | `TestRemoveDryRunBasic` | 89 |
| 52 | remove / atomicity | `tests/integration/test_remove_core.py` | `TestRemoveCoreErrorPaths` | 226 |

**Notes on row mapping:**

- Rows 46, 48, 49 all map to `TestRemoveCoreHappyPath`. Row 46 is covered by
  `test_source_name_input_removes_block`. Row 48 (by-canonical / entry-name form)
  is covered by `test_entry_name_input_removes_block`, which inputs `Foo-Bar` and
  asserts normalisation to `foo_bar`. Row 49 (by-original / source-name form) is
  covered by `test_source_name_input_removes_block`, which inputs `foo_bar` directly.
- Row 47 (multiple sources) is covered by `TestRemoveCoreErrorPaths`
  via `test_multi_source_all_removed_when_all_valid`, which removes two sources in
  one invocation.
- Row 52 (atomicity) is covered by `TestRemoveCoreErrorPaths` via
  `test_atomicity_file_unchanged_when_one_name_fails`, which asserts the file is
  not written when one of multiple requested sources is absent.

### Verification command

```
pytest tests/integration/test_remove_*.py -v
```

### Verification result

27 passed, 0 failed (2026-05-28). All three test files collected 27 tests total:
14 from `test_remove_core.py`, 1 from `test_remove_force_integration.py`, and
12 from `test_remove_dry_run.py`.

**Authoritative source**: spec §4 E39 (Files / Change / Verification + closure rows 46-52).
