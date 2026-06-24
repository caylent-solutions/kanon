"""Tests for pre-push hook configuration.

Validates that the git-hooks/pre-push script includes all required checks
according to E0-F9-S1-T2 requirements:

- AC-FUNC-001: Pre-push hook runs unit tests including repo module
- AC-FUNC-002: Pre-push hook runs integration tests
- AC-FUNC-003: Pre-push hook runs ruff lint check
- AC-FUNC-004: Pre-push hook runs security scan
- AC-FUNC-005: Pre-push hook fails on any check failure
- AC-FUNC-006: No mechanism to bypass pre-push hook exists
- AC-LINT-001: Hook configuration is valid
"""

import pathlib
import re
import stat

import pytest

REPO_ROOT = pathlib.Path(__file__).parents[2]
PRE_PUSH_HOOK = REPO_ROOT / "git-hooks" / "pre-push"
MAKEFILE = REPO_ROOT / "Makefile"


def _hook_content() -> str:
    """Read and return the pre-push hook script contents."""
    return PRE_PUSH_HOOK.read_text(encoding="utf-8")


def _makefile_content() -> str:
    """Read and return the Makefile contents."""
    return MAKEFILE.read_text(encoding="utf-8")


@pytest.mark.unit
def test_pre_push_hook_file_exists():
    """Validate that the pre-push hook file exists.

    Given: A git-hooks directory
    When: The pre-push file is checked
    Then: The file exists and is a regular file

    AC-LINT-001
    """
    assert PRE_PUSH_HOOK.is_file(), f"Pre-push hook must exist at: {PRE_PUSH_HOOK}"


@pytest.mark.unit
def test_pre_push_hook_is_executable():
    """Validate that the pre-push hook file is executable.

    Given: The pre-push hook file exists
    When: Its permissions are inspected
    Then: The file is executable

    AC-LINT-001
    """
    mode = PRE_PUSH_HOOK.stat().st_mode
    assert mode & stat.S_IXUSR, f"Pre-push hook must be executable: {PRE_PUSH_HOOK}"


@pytest.mark.unit
def test_pre_push_hook_uses_bash_shebang():
    """Validate that the pre-push hook uses a bash shebang.

    Given: The pre-push hook script
    When: The first line is inspected
    Then: It starts with #!/bin/bash or #!/usr/bin/env bash

    AC-LINT-001
    """
    content = _hook_content()
    first_line = content.splitlines()[0]
    assert first_line.startswith("#!/"), f"Pre-push hook must start with a shebang, got: {first_line!r}"
    assert "bash" in first_line, f"Pre-push hook shebang must reference bash, got: {first_line!r}"


@pytest.mark.unit
def test_pre_push_hook_runs_unit_tests():
    """Validate that the pre-push hook runs unit tests.

    Given: The pre-push hook script
    When: Its contents are inspected
    Then: It invokes the unit test target (make test-unit or pytest -m unit)

    AC-FUNC-001
    """
    content = _hook_content()
    has_unit_tests = "make test-unit" in content or "pytest -m unit" in content
    assert has_unit_tests, (
        f"Pre-push hook must run unit tests via 'make test-unit' or 'pytest -m unit'. Hook content:\n{content}"
    )


@pytest.mark.unit
def test_pre_push_hook_runs_integration_tests():
    """Validate that the pre-push hook runs integration tests.

    Given: The pre-push hook script
    When: Its contents are inspected
    Then: It invokes the integration test target (make test-integration or pytest -m integration)

    AC-FUNC-002
    """
    content = _hook_content()
    has_integration_tests = "make test-integration" in content or "pytest -m integration" in content
    assert has_integration_tests, (
        "Pre-push hook must run integration tests via 'make test-integration' or "
        f"'pytest -m integration'. Hook content:\n{content}"
    )


@pytest.mark.unit
def test_pre_push_hook_runs_lint():
    """Validate that the pre-push hook runs lint checks.

    Given: The pre-push hook script
    When: Its contents are inspected
    Then: It invokes a lint target (make lint or ruff check)

    AC-FUNC-003
    """
    content = _hook_content()
    has_lint = "make lint" in content or "ruff check" in content
    assert has_lint, f"Pre-push hook must run lint via 'make lint' or 'ruff check'. Hook content:\n{content}"


@pytest.mark.unit
def test_pre_push_hook_runs_security_scan():
    """Validate that the pre-push hook runs a security scan.

    Given: The pre-push hook script
    When: Its contents are inspected
    Then: It invokes a security scan target (make security-scan, bandit, or similar)

    AC-FUNC-004
    """
    content = _hook_content()
    has_security = "make security-scan" in content or "bandit" in content
    assert has_security, (
        f"Pre-push hook must run a security scan via 'make security-scan' or 'bandit'. Hook content:\n{content}"
    )


@pytest.mark.unit
def test_pre_push_hook_fails_on_unit_test_failure():
    """Validate that the pre-push hook exits non-zero on unit test failure.

    Given: The pre-push hook script
    When: Its control flow for unit tests is inspected
    Then: A failing unit test check causes the script to exit with non-zero

    AC-FUNC-005
    """
    content = _hook_content()

    has_failure_check = ("make test-unit" in content and "exit 1" in content) or (
        "pytest -m unit" in content and "exit 1" in content
    )
    assert has_failure_check, (
        f"Pre-push hook must exit with non-zero status when unit tests fail. Hook content:\n{content}"
    )


@pytest.mark.unit
def test_pre_push_hook_fails_on_integration_test_failure():
    """Validate that the pre-push hook exits non-zero on integration test failure.

    Given: The pre-push hook script
    When: Its control flow for integration tests is inspected
    Then: A failing integration test check causes the script to exit with non-zero

    AC-FUNC-005
    """
    content = _hook_content()
    has_integration = "make test-integration" in content or "pytest -m integration" in content
    has_exit = "exit 1" in content
    assert has_integration and has_exit, (
        f"Pre-push hook must exit with non-zero status when integration tests fail. Hook content:\n{content}"
    )


@pytest.mark.unit
def test_pre_push_hook_fails_on_lint_failure():
    """Validate that the pre-push hook exits non-zero on lint failure.

    Given: The pre-push hook script
    When: Its control flow for lint is inspected
    Then: A failing lint check causes the script to exit with non-zero

    AC-FUNC-005
    """
    content = _hook_content()
    has_lint = "make lint" in content or "ruff check" in content
    has_exit = "exit 1" in content
    assert has_lint and has_exit, (
        f"Pre-push hook must exit with non-zero status when lint fails. Hook content:\n{content}"
    )


@pytest.mark.unit
def test_pre_push_hook_fails_on_security_scan_failure():
    """Validate that the pre-push hook exits non-zero on security scan failure.

    Given: The pre-push hook script
    When: Its control flow for security scan is inspected
    Then: A failing security scan causes the script to exit with non-zero

    AC-FUNC-005
    """
    content = _hook_content()
    has_security = "make security-scan" in content or "bandit" in content
    has_exit = "exit 1" in content
    assert has_security and has_exit, (
        f"Pre-push hook must exit with non-zero status when security scan fails. Hook content:\n{content}"
    )


@pytest.mark.unit
def test_pre_push_hook_has_no_bypass_instructions():
    """Validate that the pre-push hook contains no bypass instructions.

    Given: The pre-push hook script
    When: Its contents are inspected
    Then: No --no-verify flag or bypass instructions are present

    AC-FUNC-006
    """
    content = _hook_content()
    bypass_patterns = ["--no-verify", "SKIP=", "PRE_COMMIT_ALLOW_NO_CONFIG"]
    for pattern in bypass_patterns:
        assert pattern not in content, (
            f"Pre-push hook must not contain bypass pattern '{pattern}'. Hook content:\n{content}"
        )


@pytest.mark.unit
def test_makefile_has_test_integration_target():
    """Validate that the Makefile has a test-integration target.

    Given: The project Makefile
    When: Its contents are inspected
    Then: A 'test-integration' target exists that runs pytest with -m integration

    AC-FUNC-002
    """
    content = _makefile_content()
    assert "test-integration:" in content, (
        f"Makefile must have a 'test-integration' target. Makefile content (first 500 chars):\n{content[:500]}"
    )


@pytest.mark.unit
def test_makefile_test_integration_uses_integration_marker():
    """Validate that the Makefile test-integration target uses the integration pytest marker.

    Given: The project Makefile with a test-integration target
    When: The target's recipe is inspected
    Then: It invokes pytest with '-m integration'

    AC-FUNC-002
    """
    content = _makefile_content()
    assert "test-integration:" in content, "Makefile must have a 'test-integration' target"

    lines = content.splitlines()
    target_idx = next((i for i, line in enumerate(lines) if line.startswith("test-integration:")), None)
    assert target_idx is not None, "test-integration target must exist in Makefile"

    recipe_lines = []
    for line in lines[target_idx + 1 :]:
        if line.startswith("\t"):
            recipe_lines.append(line)
        elif line.strip() and not line.startswith("\t"):
            break
    recipe_text = "\n".join(recipe_lines)

    assert re.search(r'-m "integration', recipe_text), (
        f"Makefile test-integration target must invoke pytest selecting the integration tier "
        f'(-m "integration[...]"). Recipe lines:\n{recipe_text}'
    )


@pytest.mark.unit
def test_makefile_has_security_scan_target():
    """Validate that the Makefile has a security-scan target.

    Given: The project Makefile
    When: Its contents are inspected
    Then: A 'security-scan' target exists that runs bandit

    AC-FUNC-004
    """
    content = _makefile_content()
    assert "security-scan:" in content, (
        f"Makefile must have a 'security-scan' target. Makefile content (first 500 chars):\n{content[:500]}"
    )


def _makefile_recipe(target: str) -> str:
    """Return the recipe (tab-indented body) of a Makefile target.

    Given a target name such as 'lint-markdown', collect every recipe line
    (lines beginning with a tab) that follows the 'target:' declaration up to
    the next non-indented, non-blank line.
    """
    lines = _makefile_content().splitlines()
    target_idx = next(
        (i for i, line in enumerate(lines) if line.startswith(f"{target}:")),
        None,
    )
    assert target_idx is not None, f"Makefile must declare a '{target}' target"
    recipe_lines = []
    for line in lines[target_idx + 1 :]:
        if line.startswith("\t"):
            recipe_lines.append(line)
        elif line.strip() and not line.startswith("\t"):
            break
    return "\n".join(recipe_lines)


@pytest.mark.unit
def test_makefile_has_lint_markdown_target():
    """Validate that the Makefile exposes a 'lint-markdown' target.

    Given: The project Makefile
    When: Its contents are inspected
    Then: A 'lint-markdown' target is declared

    AC-LINT-MD-1
    """
    content = _makefile_content()
    assert "lint-markdown:" in content, f"Makefile must declare a 'lint-markdown' target. Makefile content:\n{content}"


@pytest.mark.unit
def test_makefile_lint_markdown_is_phony():
    """Validate that 'lint-markdown' is registered in the Makefile .PHONY list.

    Given: The project Makefile
    When: The .PHONY declaration is inspected
    Then: 'lint-markdown' appears as a space-delimited token on a .PHONY line

    AC-LINT-MD-1
    """
    phony_targets: list[str] = []
    for line in _makefile_content().splitlines():
        if line.startswith(".PHONY:"):
            phony_targets.extend(line[len(".PHONY:") :].split())
    assert "lint-markdown" in phony_targets, (
        f"Makefile .PHONY declaration must include 'lint-markdown'. .PHONY tokens: {phony_targets}"
    )


@pytest.mark.unit
def test_makefile_lint_markdown_recipe_scans_docs_and_readme():
    """Validate that the 'lint-markdown' recipe runs pymarkdownlnt over docs/ and README.md.

    Given: The project Makefile with a 'lint-markdown' target
    When: The target's recipe is inspected
    Then: It invokes pymarkdownlnt scanning both the docs/ tree and README.md

    AC-LINT-MD-1, AC-LINT-MD-2
    """
    recipe = _makefile_recipe("lint-markdown")
    assert "pymarkdownlnt" in recipe, f"lint-markdown recipe must invoke pymarkdownlnt. Recipe:\n{recipe}"
    assert "docs/" in recipe, f"lint-markdown recipe must scan the docs/ tree. Recipe:\n{recipe}"
    assert "README.md" in recipe, f"lint-markdown recipe must scan README.md. Recipe:\n{recipe}"


@pytest.mark.unit
def test_makefile_lint_markdown_excludes_vendored_repo_docs():
    """Validate that the 'lint-markdown' recipe excludes the vendored docs/repo/ tree.

    Given: The project Makefile with a 'lint-markdown' target
    When: The target's recipe is inspected
    Then: It passes pymarkdownlnt's --exclude (-e) option scoped to docs/repo/ so
          the embedded upstream repo-tool docs are not linted by kanon's gate
          (correct scoping of vendored content, not a rule disable)

    AC-LINT-MD-1, AC-LINT-MD-4
    """
    recipe = _makefile_recipe("lint-markdown")
    assert "docs/repo/" in recipe, f"lint-markdown recipe must exclude the vendored docs/repo/ tree. Recipe:\n{recipe}"
    assert "-e" in recipe.split() or "--exclude" in recipe, (
        f"lint-markdown recipe must use pymarkdownlnt's -e/--exclude option to scope out docs/repo/. Recipe:\n{recipe}"
    )
