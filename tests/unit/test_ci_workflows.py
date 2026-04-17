"""Tests for CI workflow configuration.

Validates that the GitHub Actions workflow files include the repo module
in the CI test and lint pipeline according to E0-F9-S1-T1 requirements:

- AC-FUNC-001: CI workflow includes repo module unit tests in test matrix
- AC-FUNC-002: CI workflow runs integration tests parallel with unit tests
- AC-FUNC-003: CI workflow ruff check covers src/kanon_cli/repo/
- AC-FUNC-004: CI workflow ruff format check covers src/kanon_cli/repo/
- AC-FUNC-005: All workflow run steps use shell: bash
- AC-FUNC-006: Workflow changes follow existing conventions
- AC-LINT-001: Workflow YAML is valid
"""

import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
PR_WORKFLOW = WORKFLOWS_DIR / "pr-validation.yml"
MAIN_WORKFLOW = WORKFLOWS_DIR / "main-validation.yml"

WORKFLOW_FILES = [PR_WORKFLOW, MAIN_WORKFLOW]


def _load_workflow(path: pathlib.Path) -> dict:
    """Load and parse a workflow YAML file.

    Args:
        path: Path to the workflow YAML file.

    Returns:
        Parsed YAML as a dict.
    """
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _collect_run_steps(workflow: dict) -> list[dict]:
    """Collect all steps that have a 'run' key from all jobs in a workflow.

    Args:
        workflow: Parsed workflow dict.

    Returns:
        List of step dicts that contain a 'run' key.
    """
    steps = []
    for job in workflow.get("jobs", {}).values():
        for step in job.get("steps", []):
            if "run" in step:
                steps.append(step)
    return steps


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=["pr-validation", "main-validation"])
def test_workflow_yaml_is_valid(workflow_path: pathlib.Path):
    """Validate that each workflow YAML file is valid and parsable.

    Given: A workflow YAML file exists
    When: The file is loaded with yaml.safe_load
    Then: It parses without error and contains a 'jobs' key

    AC-LINT-001
    """
    assert workflow_path.is_file(), f"Workflow file must exist: {workflow_path}"
    workflow = _load_workflow(workflow_path)
    assert isinstance(workflow, dict), f"Workflow must be a dict: {workflow_path}"
    assert "jobs" in workflow, f"Workflow must contain 'jobs' key: {workflow_path}"


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=["pr-validation", "main-validation"])
def test_all_run_steps_use_shell_bash(workflow_path: pathlib.Path):
    """Validate that every run step in each workflow uses shell: bash.

    Given: A workflow YAML file with run steps
    When: Each run step's shell attribute is inspected
    Then: Every run step has shell: bash

    AC-FUNC-005
    """
    workflow = _load_workflow(workflow_path)
    run_steps = _collect_run_steps(workflow)
    assert run_steps, f"Workflow must contain at least one run step: {workflow_path}"
    for step in run_steps:
        step_name = step.get("name", "<unnamed>")
        assert step.get("shell") == "bash", (
            f"Step '{step_name}' in {workflow_path.name} must use shell: bash, got: {step.get('shell')!r}"
        )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=["pr-validation", "main-validation"])
def test_workflow_has_integration_tests_job(workflow_path: pathlib.Path):
    """Validate that each workflow includes an integration tests job.

    Given: A workflow YAML file
    When: The jobs are inspected
    Then: A job named 'integration' (or similar) exists that runs integration tests

    AC-FUNC-002
    """
    workflow = _load_workflow(workflow_path)
    jobs = workflow.get("jobs", {})
    integration_jobs = {name: job for name, job in jobs.items() if "integration" in name.lower()}
    assert integration_jobs, (
        f"Workflow {workflow_path.name} must contain an integration tests job. Found jobs: {list(jobs.keys())}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=["pr-validation", "main-validation"])
def test_integration_job_runs_in_parallel_with_unit_tests(workflow_path: pathlib.Path):
    """Validate that integration tests job runs in parallel with unit tests.

    Given: A workflow YAML with both validate (unit) and integration jobs
    When: The 'needs' dependency of the integration job is inspected
    Then: The integration job does NOT depend on the validate job (runs in parallel)

    AC-FUNC-002
    """
    workflow = _load_workflow(workflow_path)
    jobs = workflow.get("jobs", {})
    integration_jobs = {name: job for name, job in jobs.items() if "integration" in name.lower()}
    assert integration_jobs, f"No integration job found in {workflow_path.name}"

    unit_job_names = {name for name in jobs if "validate" in name.lower()}

    for job_name, job in integration_jobs.items():
        needs = job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        for unit_job in unit_job_names:
            assert unit_job not in needs, (
                f"Integration job '{job_name}' in {workflow_path.name} must not depend on "
                f"unit tests job '{unit_job}' -- they should run in parallel. "
                f"'needs': {needs}"
            )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=["pr-validation", "main-validation"])
def test_integration_job_invokes_integration_mark(workflow_path: pathlib.Path):
    """Validate that the integration job runs pytest with the integration marker.

    Given: A workflow with an integration job
    When: The run steps of that job are inspected
    Then: At least one step runs pytest with '-m integration'

    AC-FUNC-002
    """
    workflow = _load_workflow(workflow_path)
    jobs = workflow.get("jobs", {})
    integration_jobs = {name: job for name, job in jobs.items() if "integration" in name.lower()}
    assert integration_jobs, f"No integration job found in {workflow_path.name}"

    for job_name, job in integration_jobs.items():
        run_commands = [step.get("run", "") for step in job.get("steps", []) if "run" in step]
        full_run_text = "\n".join(run_commands)
        assert "-m integration" in full_run_text, (
            f"Integration job '{job_name}' in {workflow_path.name} must run "
            f"pytest with '-m integration'. Run steps found:\n{full_run_text}"
        )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=["pr-validation", "main-validation"])
def test_unit_tests_step_runs_with_unit_marker(workflow_path: pathlib.Path):
    """Validate that the unit tests step uses the 'unit' pytest marker.

    Given: A workflow YAML file
    When: The run steps are inspected
    Then: A step exists that runs pytest with '-m unit'

    AC-FUNC-001
    """
    workflow = _load_workflow(workflow_path)
    jobs = workflow.get("jobs", {})
    found = False
    for job in jobs.values():
        for step in job.get("steps", []):
            run = step.get("run", "")
            if "pytest" in run and "-m unit" in run:
                found = True
                break
        if found:
            break
    assert found, (
        f"Workflow {workflow_path.name} must have a step that runs pytest with '-m unit'. "
        "This ensures the unit test matrix includes all unit tests."
    )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=["pr-validation", "main-validation"])
def test_ruff_check_covers_src_repo(workflow_path: pathlib.Path):
    """Validate that the ruff check step covers src/kanon_cli/repo/.

    Given: A workflow YAML file
    When: The run steps are inspected for ruff check invocations
    Then: The ruff check command covers src/ (which includes src/kanon_cli/repo/)
    or uses make lint which does the same

    AC-FUNC-003
    """
    workflow = _load_workflow(workflow_path)
    run_steps = _collect_run_steps(workflow)
    lint_steps = [step for step in run_steps if "ruff" in step.get("run", "") or "make lint" in step.get("run", "")]
    assert lint_steps, f"Workflow {workflow_path.name} must have a ruff check or make lint step"
    # Each lint step must cover src/ (which includes src/kanon_cli/repo/)
    for step in lint_steps:
        run = step.get("run", "")
        step_name = step.get("name", "<unnamed>")
        if "ruff check" in run:
            covers_src = (
                "src/" in run
                or "src/kanon_cli/repo" in run
                or run.strip().endswith("ruff check .")
                or re.search(r"ruff check\s+\.$", run.strip())
                or re.search(r"ruff check\s+src", run)
            )
            assert covers_src, (
                f"Step '{step_name}' in {workflow_path.name}: ruff check must cover src/ "
                f"(including src/kanon_cli/repo/). Run command: {run!r}"
            )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=["pr-validation", "main-validation"])
def test_ruff_format_check_covers_src_repo(workflow_path: pathlib.Path):
    """Validate that the ruff format check step covers src/kanon_cli/repo/.

    Given: A workflow YAML file
    When: The run steps are inspected for ruff format check invocations
    Then: The ruff format --check command covers src/ (which includes src/kanon_cli/repo/)
    or uses make lint which does the same

    AC-FUNC-004
    """
    workflow = _load_workflow(workflow_path)
    run_steps = _collect_run_steps(workflow)
    format_steps = [
        step
        for step in run_steps
        if ("ruff format" in step.get("run", "") and "--check" in step.get("run", ""))
        or "make lint" in step.get("run", "")
        or "make format-check" in step.get("run", "")
    ]
    assert format_steps, f"Workflow {workflow_path.name} must have a ruff format --check or make lint step"
    for step in format_steps:
        run = step.get("run", "")
        step_name = step.get("name", "<unnamed>")
        if "ruff format" in run and "--check" in run:
            covers_src = (
                "src/" in run
                or "src/kanon_cli/repo" in run
                or run.strip().endswith("ruff format --check .")
                or re.search(r"ruff format\s+--check\s+\.$", run.strip())
                or re.search(r"ruff format\s+--check\s+src", run)
            )
            assert covers_src, (
                f"Step '{step_name}' in {workflow_path.name}: ruff format --check must cover src/ "
                f"(including src/kanon_cli/repo/). Run command: {run!r}"
            )
