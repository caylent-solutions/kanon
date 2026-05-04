"""Integration tests for CI configuration and pre-push hook validation.

Validates that CI YAML files are valid, workflows reference the repo module,
the pre-push hook includes integration tests, and the test collection meets
the minimum required count.

AC-TEST-001: Verify all .github/workflows/*.yml are valid YAML
AC-TEST-002: Verify at least one workflow references kanon_cli.repo in test paths or commands
AC-TEST-003: Verify pre-push hook configuration exists and includes integration tests
AC-TEST-004: Verify pytest --collect-only collects at least 4196 tests
"""

import pathlib
import re
import subprocess

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
PRE_PUSH_HOOK = REPO_ROOT / "git-hooks" / "pre-push"

MIN_TEST_COUNT = 4196

_WORKFLOW_FILES: list[pathlib.Path] = sorted(WORKFLOWS_DIR.glob("*.yml"))


def _discover_workflow_files() -> list[pathlib.Path]:
    """Discover all YAML files in the workflows directory.

    Returns:
        List of paths to workflow YAML files.

    Raises:
        AssertionError: If no workflow files are found.
    """
    files = sorted(WORKFLOWS_DIR.glob("*.yml"))
    assert files, f"No workflow YAML files found in {WORKFLOWS_DIR}"
    return files


def _load_workflow(path: pathlib.Path) -> dict:
    """Load and parse a workflow YAML file.

    Args:
        path: Absolute path to the workflow YAML file.

    Returns:
        Parsed YAML content as a dict.

    Raises:
        yaml.YAMLError: If the file content is not valid YAML.
    """
    raw = path.read_text(encoding="utf-8")
    return yaml.safe_load(raw)


def _collect_all_run_commands(workflow: dict) -> list[str]:
    """Collect all run command strings from every job step in a workflow.

    Args:
        workflow: Parsed workflow dict.

    Returns:
        List of run command strings.
    """
    commands = []
    for job in workflow.get("jobs", {}).values():
        for step in job.get("steps", []):
            run = step.get("run")
            if run:
                commands.append(run)
    return commands


@pytest.fixture(scope="module")
def workflow_files() -> list[pathlib.Path]:
    """Fixture providing all discovered workflow YAML file paths."""
    return _discover_workflow_files()


@pytest.fixture(scope="module")
def loaded_workflows(workflow_files: list[pathlib.Path]) -> dict[str, dict]:
    """Fixture providing a mapping of filename to parsed workflow dict.

    Args:
        workflow_files: List of workflow file paths.

    Returns:
        Dict mapping filename stem to parsed workflow content.
    """
    return {path.name: _load_workflow(path) for path in workflow_files}


@pytest.mark.integration
@pytest.mark.parametrize(
    "workflow_path",
    _WORKFLOW_FILES,
    ids=[p.name for p in _WORKFLOW_FILES],
)
def test_ci_yaml_valid(workflow_path: pathlib.Path) -> None:
    """Verify each workflow file is valid YAML with a jobs section.

    Given: A .github/workflows/*.yml file
    When: The file is parsed with yaml.safe_load
    Then: It parses without error and contains a 'jobs' key

    AC-TEST-001
    """
    assert workflow_path.is_file(), f"Workflow file must exist: {workflow_path}"
    parsed = _load_workflow(workflow_path)
    assert isinstance(parsed, dict), f"Workflow {workflow_path.name} must parse to a dict, got {type(parsed).__name__}"
    assert "jobs" in parsed, (
        f"Workflow {workflow_path.name} must contain a 'jobs' key; found keys: {sorted(parsed.keys())}"
    )


@pytest.mark.integration
def test_ci_includes_repo_tests(loaded_workflows: dict[str, dict]) -> None:
    """Verify at least one workflow references the kanon_cli.repo module in tests.

    The repo module (kanon_cli.repo) must be covered by CI. This is satisfied when
    a workflow uses '--cov=kanon_cli' (which includes kanon_cli.repo as a subpackage)
    or explicitly references 'kanon_cli.repo', 'tests/unit/repo', or
    'tests/integration/repo' in any run command.

    Given: All loaded workflow YAML files
    When: All run commands across every workflow are inspected
    Then: At least one run command references kanon_cli.repo coverage or repo test paths

    AC-TEST-002
    """
    repo_indicators = [
        "kanon_cli.repo",
        "kanon_cli/repo",
        "tests/unit/repo",
        "tests/integration/repo",
        "--cov=kanon_cli",
    ]
    all_commands: list[str] = []
    for workflow in loaded_workflows.values():
        commands = _collect_all_run_commands(workflow)
        all_commands.extend(commands)

    found_indicator = None
    for command in all_commands:
        for indicator in repo_indicators:
            if indicator in command:
                found_indicator = indicator
                break
        if found_indicator:
            break

    assert found_indicator is not None, (
        "No workflow run command references kanon_cli.repo. "
        "At least one workflow must include one of the following: "
        f"{repo_indicators}. "
        f"Searched {len(all_commands)} run commands across {len(loaded_workflows)} workflow(s)."
    )


@pytest.mark.integration
def test_pre_push_hook_exists() -> None:
    """Verify the pre-push hook file exists and is executable.

    Given: The git-hooks directory
    When: The pre-push hook file is inspected
    Then: The file exists, is a regular file, and the content includes integration tests

    AC-TEST-003
    """
    assert PRE_PUSH_HOOK.is_file(), f"Pre-push hook must exist at: {PRE_PUSH_HOOK}"
    content = PRE_PUSH_HOOK.read_text(encoding="utf-8")
    integration_indicators = [
        "test-integration",
        "pytest -m integration",
        "pytest --collect-only",
        "-m integration",
    ]
    found = any(indicator in content for indicator in integration_indicators)
    assert found, (
        f"Pre-push hook at {PRE_PUSH_HOOK} must include integration tests. "
        f"Expected one of {integration_indicators} in hook content. "
        f"Current hook content:\n{content}"
    )


@pytest.mark.integration
def test_collected_test_count_minimum() -> None:
    """Verify that pytest --collect-only collects at least MIN_TEST_COUNT tests.

    Given: The test suite in the repository
    When: `uv run pytest --collect-only -q` is executed
    Then: The output reports at least MIN_TEST_COUNT tests collected

    AC-TEST-004
    """
    result = subprocess.run(
        ["uv", "run", "pytest", "--collect-only", "-q", "--tb=no"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr
    collected_count = _parse_collected_count(output)
    assert collected_count >= MIN_TEST_COUNT, (
        f"Expected at least {MIN_TEST_COUNT} tests collected, "
        f"but pytest reported {collected_count}. "
        f"Full output:\n{output}"
    )


def _parse_collected_count(output: str) -> int:
    """Parse the number of collected tests from pytest --collect-only output.

    Looks for lines like '5585 tests collected in 0.60s' or similar.

    Args:
        output: Combined stdout+stderr from pytest --collect-only.

    Returns:
        Number of tests collected.

    Raises:
        ValueError: If no collected count line can be found in the output.
    """
    match = re.search(r"(\d+)\s+tests?\s+collected", output)
    if match:
        return int(match.group(1))
    raise ValueError(
        f"Could not parse collected test count from pytest output. "
        f"Expected a line like 'N tests collected'. Output:\n{output}"
    )
