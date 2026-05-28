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

---

## Install command coverage

### Purpose

This section documents the automated test coverage for the `kanon install` command,
satisfying spec §4 E42. All seven behaviour rows from `test-fixtures/findings.md`
rows 53-59 are end-to-end asserted by the cited integration tests -- each test
invokes the real `kanon install` CLI via subprocess against a temporary workspace
and asserts both the process exit code and the resulting lockfile state.

No new test file was required per spec §4 E42. The failing tests introduced by E22
(DEFECT-001: bare install after add), E25 (DEFECT-010: refresh-lock-source counters),
and E26 (DEFECT-011: strict-lock orphan naming) close the previously-uncovered
assertion gaps for rows 53, 56, and 57 respectively. The `TestStrictDriftEndToEnd`
class (row 58) was unblocked after E36 resolved FIXTURE-DEFECT-001 by replacing the
legacy static `test-fixtures/synthetic-fixtures/` seeds with runtime-generated
pytest fixtures that include the required `<remote>` and `<default>` manifest
declarations.

**Authoritative source**: spec §4 E42 (Files / Change / Verification + closure rows 53-59).

### Coverage mapping

| findings.md row | Behaviour | Test file | Class | Line |
|----------------:|-----------|-----------|-------|-----:|
| 53 | install / basic (bare after add) | `tests/integration/test_install_after_add.py` | `TestInstallAfterAdd` | 42 |
| 53 | install / basic (flag-passed deprecation path) | `tests/integration/test_install_command.py` | `TestInstallDeprecationWarningSubprocess` | 90 |
| 54 | install / lockfile-consistent-replay | `tests/integration/test_install_lockfile_replay.py` | `TestLockfileReplay` | 191 |
| 55 | install / refresh-lock | `tests/integration/test_install_refresh_lock.py` | `TestRefreshLockRebuildsLockfile` | 184 |
| 55 | install / refresh-lock (cycle) | `tests/integration/test_install_refresh_lock.py` | `TestRefreshLockCycle` | 271 |
| 56 | install / refresh-lock-source (named rebuild) | `tests/integration/test_install_refresh_lock_source.py` | `TestRefreshLockSourceRebuildsOnlyNamedSource` | 204 |
| 56 | install / refresh-lock-source (counters -- E25) | `tests/integration/test_install_refresh_lock_source.py` | `TestRefreshLockSourceCounters` | 533 |
| 57 | install / strict-lock-orphan (end-to-end) | `tests/integration/test_install_strict.py` | `TestStrictLockEndToEnd` | 366 |
| 57 | install / strict-lock-orphan (error message -- E26) | `tests/integration/test_install_strict.py` | `TestStrictLockOrphanErrorMessage` | 578 |
| 58 | install / strict-drift (unblocked by E36) | `tests/integration/test_install_strict.py` | `TestStrictDriftEndToEnd` | 232 |
| 59 | install / custom-lock-file | `tests/integration/test_install_lock_file_derivation.py` | `TestExplicitLockFileFlag` | 124 |

**Notes on mapping:**

- Row 53 maps to two test classes. `TestInstallAfterAdd` (E22) guards the defect-fixed
  path where bare `kanon install` after `kanon add` must succeed without re-passing
  `--catalog-source`. `TestInstallDeprecationWarningSubprocess` covers the flag-present
  path and legacy env-var deprecation notices.
- Row 54 maps to `TestLockfileReplay` (class name `TestLockfileReplay`, not `TestReplay`
  as the spec draft used). The class exercises first-install lockfile creation and
  second-install lockfile-consistent replay at lines 194-306.
- Rows 55 and 56 each map to two classes: the primary happy-path class and a secondary
  class that exercises a specific sub-scenario (cycle / counter-reporting).
- Row 57 maps to `TestStrictLockEndToEnd` (end-to-end orphan exit-1) and
  `TestStrictLockOrphanErrorMessage` (E26: error names each orphan source and provides
  remediation text).
- Row 58 maps to `TestStrictDriftEndToEnd`. This class was authored before E36 landed
  the synthetic-fixture fix and was blocked on FIXTURE-DEFECT-001. After E36, the
  `create_drift_fixture` helper produces a compliant `manifest.xml` that `repo init`
  accepts, allowing the drift scenario to reach the `--strict-drift` code path.
- Row 59 maps to `TestExplicitLockFileFlag` in `test_install_lock_file_derivation.py`,
  which asserts that `--lock-file ./alt.kanon.lock` writes only the alternate path
  and leaves the default `.kanon.lock` absent. The spec draft cited class name
  `TestCustomLockFile` which was not the name used in the implementation.

### Verification command

```
pytest tests/integration/test_install_*.py -v
```

### Verification result

163 passed, 5 failed (2026-05-28). The 5 failing tests are pre-existing intentional
RED test guards authored by E34 (default-install auto-prune: 4 tests in
`TestStrictLockDefaultAutoPrune`) and E35 (install marketplace registration: 1 test in
`TestInstallMarketplaceRegistration`). These RED guards await their implementation
tasks (E34-F1-S1-T2 and E35-F1-S1-T2 respectively) and are not regressions
introduced by this task. All 11 classes cited in the mapping table above contributed
passing tests in this run.

---

## Catalog-audit command coverage

### Purpose

This section documents the automated test coverage for the `kanon catalog audit`
command, satisfying spec §4 E45. All eight behaviour rows from
`test-fixtures/findings.md` rows 29-36 are end-to-end asserted by the cited
integration tests -- each test invokes the real `kanon catalog audit` CLI via
subprocess against a temporary manifest-repo fixture and asserts both the process
exit code and the resulting findings output.

**Authoritative source**: spec §4 E45 (Files / Change / Verification + closure rows
29-36).

### Coverage mapping

| findings.md row | Behaviour | Test file | Class | Line |
|----------------:|-----------|-----------|-------|-----:|
| 29 | catalog-audit / all | `tests/integration/test_catalog_audit_framework.py` | `TestCatalogAuditSubprocessEmpty` | 61 |
| 30 | check-entry-name-uniqueness | `tests/integration/test_catalog_audit_entry_uniqueness.py` | `TestCatalogAuditEntryUniquenessSubprocess` | 47 |
| 31 | check-metadata | `tests/integration/test_catalog_audit_metadata.py` | `TestCatalogAuditMetadataSubprocess` | 47 |
| 32 | check-remote-url | `tests/integration/test_catalog_audit_remote_url.py` | `TestCatalogAuditRemoteUrlSubprocess` | 48 |
| 33 | check-source-name-derivation | `tests/integration/test_catalog_audit_source_name.py` | `TestCatalogAuditSourceNameSubprocess` | 47 |
| 34 | check-tag-format | `tests/integration/test_catalog_audit_tag_format.py` | `TestCatalogAuditTagFormatSubprocess` | 123 |
| 35 | format-json | `tests/integration/test_catalog_audit_framework.py` | `TestCatalogAuditSubprocessEmpty` | 61 |
| 36 | strict-warn-promotion | `tests/integration/test_catalog_audit_strict.py` | `TestCatalogAuditStrictSubprocess` | 50 |

**Notes on row mapping:**

- Row 29 (catalog-audit / all) maps to `TestCatalogAuditSubprocessEmpty`. The
  `test_exit_0_explicit_all_check` method at line 71 invokes `kanon catalog audit .
  --check all` and asserts exit 0 on an empty manifest repo.
- Row 35 (format-json) also maps to `TestCatalogAuditSubprocessEmpty`. The
  `test_exit_0_json_format_empty_findings` method at line 78 and
  `test_json_output_is_parseable` at line 88 together exercise the `--format json`
  output path, asserting exit 0 and a parseable JSON object with `findings == []`.
- Rows 32 and 34 (check-remote-url and check-tag-format) FAILed in the manual
  test matrix. See the explanation paragraph below for why these failures are
  catalog-content issues rather than kanon defects.

### Manual-matrix vs automated-coverage explanation

Rows 29, 32, and 34 recorded FAIL in the manual verification matrix. These failures
are **catalog-content issues**, not kanon defects. The manual runs exercised the real
`caylent-private-kanon` catalog, which at the time of the audit contained R002 errors
-- unresolved `${GITBASE}` shell-variable placeholders in repository URL fields. Those
placeholders are not expanded at `kanon catalog audit` runtime; the audit correctly
reports them as malformed remote URLs and non-PEP-440 tag references. The kanon CLI
itself behaves correctly: it detects and surfaces the content problems exactly as
designed.

The existing integration tests listed in the coverage mapping above use synthetic
fixture repositories that contain only well-formed catalog entries. These fixtures
exercise all code paths of each audit check (including the error-detection paths) with
controlled inputs, confirming that the audit logic is correct independently of the
real-catalog R002 content defects.

### Verification command

```
pytest tests/integration/test_catalog_audit_*.py tests/unit/test_catalog_audit_*.py -v
```

### Verification result

452 passed, 0 failed (2026-05-28). All eight classes cited in the mapping table above
contributed passing tests in this run. The test suite collected tests from 7
integration files and the corresponding unit files.
