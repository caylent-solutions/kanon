"""Guard test: verifies the CI workflow runs the operator-path scenario tests
on every PR.

Parses `.github/workflows/pr-validation.yml` and the `Makefile` from the
project root (derived at runtime from this file's own path -- no hard-coded
absolute paths) and asserts:

1. The workflow triggers on `pull_request` events.
2. A job in the workflow invokes `make test-scenarios` or
   `make test-operator-path`, so the operator-path scenario tests run on
   every PR.
3. The invoked make target selects the `scenario` marker (cross-checked
   against the Makefile recipe), confirming the assertion is end-to-end and
   not a superficial string match on the workflow alone.

These assertions fail if a future edit removes the `scenario-tests` job or
renames the make target without updating the CI wiring, acting as a
regression guard for E50-F1-S1-T2.
"""

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Project-root resolution (no hard-coded absolute paths)
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Return the project root by walking up from this file's location.

    This file lives at <project_root>/tests/functional/..., so the root is
    three levels up.
    """
    here = Path(__file__).resolve()
    # tests/functional/test_ci_runs_operator_path_tests.py -> project root
    root = here.parent.parent.parent
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise FileNotFoundError(
            f"ERROR: pyproject.toml not found at expected location {pyproject}. "
            "The project root could not be determined from this file's path. "
            "Ensure this file lives at <project_root>/tests/functional/."
        )
    return root


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def project_root() -> Path:
    return _project_root()


@pytest.fixture(scope="module")
def workflow_data(project_root: Path) -> dict:
    """Parse and return the pr-validation.yml workflow as a Python dict."""
    workflow_path = project_root / ".github" / "workflows" / "pr-validation.yml"
    if not workflow_path.is_file():
        raise FileNotFoundError(
            f"ERROR: PR validation workflow not found at {workflow_path}. "
            "Expected the workflow at .github/workflows/pr-validation.yml. "
            "Confirm the workflow file exists and the path is correct."
        )
    with workflow_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(
            f"ERROR: Parsed workflow at {workflow_path} is not a YAML mapping. "
            f"Got {type(data).__name__}. The workflow file may be malformed."
        )
    return data


@pytest.fixture(scope="module")
def makefile_lines(project_root: Path) -> list[str]:
    """Read and return the Makefile lines."""
    makefile_path = project_root / "Makefile"
    if not makefile_path.is_file():
        raise FileNotFoundError(
            f"ERROR: Makefile not found at {makefile_path}. Ensure a Makefile exists at the project root."
        )
    return makefile_path.read_text(encoding="utf-8").splitlines()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_recipe_lines(makefile_lines: list[str], target: str) -> list[str]:
    """Return the tab-indented recipe lines that belong to a given Make target.

    Scans forward from the first line that starts with '<target>:' and
    collects tab-indented lines, stopping at the next target or non-blank,
    non-comment, non-tab line.
    """
    in_target = False
    recipe: list[str] = []
    for line in makefile_lines:
        if line.startswith(f"{target}:"):
            in_target = True
            continue
        if in_target:
            if line.startswith("\t"):
                recipe.append(line.lstrip("\t"))
            elif line == "" or line.startswith("#"):
                continue
            else:
                break
    return recipe


def _job_run_commands(job: dict) -> list[str]:
    """Extract all `run:` command strings from a workflow job's steps."""
    commands: list[str] = []
    for step in job.get("steps", []) or []:
        run_value = step.get("run")
        if run_value and isinstance(run_value, str):
            commands.append(run_value)
    return commands


# ---------------------------------------------------------------------------
# Guard tests
# ---------------------------------------------------------------------------


@pytest.mark.functional
def test_ci_workflow_triggers_on_pull_request(workflow_data: dict) -> None:
    """The workflow must define a pull_request trigger.

    This assertion fails if the on: section is removed or the pull_request
    trigger is dropped, which would mean the operator-path tests no longer
    run on PRs.
    """
    on_section = workflow_data.get("on") or workflow_data.get(True)
    assert on_section is not None, (
        "ERROR: The workflow has no 'on:' trigger section. "
        "The pr-validation.yml workflow must define an 'on: pull_request' trigger "
        "so the operator-path tests run on every PR. "
        "Add 'on:\\n  pull_request:' to the workflow."
    )
    # YAML parses bare `on` as Python True; handle both forms.
    if isinstance(on_section, dict):
        has_pull_request = "pull_request" in on_section
    elif isinstance(on_section, list):
        has_pull_request = "pull_request" in on_section
    else:
        has_pull_request = on_section == "pull_request"
    assert has_pull_request, (
        f"ERROR: The workflow 'on:' section does not include 'pull_request'. "
        f"Found: {on_section!r}. "
        "Add 'pull_request:' under 'on:' so the scenario/operator-path tests "
        "run on every PR to the feat branch."
    )


@pytest.mark.functional
def test_ci_workflow_invokes_scenario_tests(workflow_data: dict, makefile_lines: list[str]) -> None:
    """A CI job must invoke make test-scenarios or make test-operator-path.

    This is the primary guard: it fails if the scenario-tests job is removed,
    or if its run: step no longer calls a make target that exercises the
    operator-path scenario tests. The assertion is end-to-end: it also
    cross-checks the Makefile to confirm the invoked target selects the
    scenario marker, not just that the string appears in the workflow.

    Spec reference: E50-F1-S1-T2 AC-FUNC-001, AC-FUNC-003.
    """
    jobs: dict = workflow_data.get("jobs") or {}
    assert jobs, (
        "ERROR: The workflow has no 'jobs:' section. "
        "The pr-validation.yml workflow must define at least one job that runs "
        "the operator-path scenario tests. "
        "Add a 'scenario-tests:' job (or equivalent) that invokes "
        "'make test-scenarios' or 'make test-operator-path'."
    )

    # Collect all run: commands across all jobs and track which jobs contain them.
    operator_path_targets = {"make test-scenarios", "make test-operator-path"}
    matching_jobs: list[str] = []
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        run_commands = _job_run_commands(job)
        for cmd in run_commands:
            # Normalise whitespace for matching.
            stripped = cmd.strip()
            for target in operator_path_targets:
                if target in stripped:
                    matching_jobs.append(job_id)
                    break

    assert matching_jobs, (
        f"ERROR: No job in '{list(jobs.keys())}' invokes 'make test-scenarios' "
        "or 'make test-operator-path'. "
        "The operator-path scenario tests (E49) must run on every PR. "
        "Add a job with a run: step that calls one of these make targets."
    )

    # Cross-check: verify the invoked make target exercises the scenario marker.
    # Determine which make target(s) are called and confirm each one's Makefile
    # recipe references pytest with the 'scenario' marker or scenario test paths.
    for job_id in matching_jobs:
        job = jobs[job_id]
        for cmd in _job_run_commands(job):
            stripped = cmd.strip()
            invoked_target: str | None = None
            if "make test-scenarios" in stripped:
                invoked_target = "test-scenarios"
            elif "make test-operator-path" in stripped:
                invoked_target = "test-operator-path"
            if invoked_target is None:
                continue
            recipe = _collect_recipe_lines(makefile_lines, invoked_target)
            assert recipe, (
                f"ERROR: Make target '{invoked_target}' (invoked by job '{job_id}') "
                f"has no recipe lines in the Makefile. "
                "The target must have a recipe that runs pytest with the "
                "'scenario' marker or explicit operator-path test paths."
            )
            combined_recipe = " ".join(recipe)
            assert "pytest" in combined_recipe, (
                f"ERROR: Make target '{invoked_target}' recipe does not invoke "
                f"pytest. Recipe: {recipe}. "
                "The target must run pytest to exercise the operator-path tests."
            )
            assert "scenario" in combined_recipe, (
                f"ERROR: Make target '{invoked_target}' recipe does not reference "
                f"the 'scenario' marker or scenario test paths. "
                f"Recipe: {recipe}. "
                "The target must select the operator-path tests via the "
                "'scenario' marker (e.g., '-m scenario') or by explicit path to "
                "tests/scenarios/. End-to-end CI coverage of the operator-path "
                "tests requires this Makefile wiring to be present."
            )


@pytest.mark.functional
def test_ci_scenario_tests_job_uses_shell_bash(workflow_data: dict) -> None:
    """Every run: step in scenario-related jobs must use shell: bash.

    This ensures failures are surfaced immediately and the shell configuration
    matches the workspace GitHub-workflow standards (CLAUDE.md).

    Spec reference: E50-F1-S1-T2 AC-FUNC-002.
    """
    jobs: dict = workflow_data.get("jobs") or {}
    operator_path_targets = {"make test-scenarios", "make test-operator-path"}

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        run_commands = _job_run_commands(job)
        job_invokes_scenario = any(target in cmd.strip() for cmd in run_commands for target in operator_path_targets)
        if not job_invokes_scenario:
            continue
        # This job runs operator-path/scenario tests -- check every run: step.
        for step in job.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            if "run" not in step:
                continue
            shell = step.get("shell")
            assert shell == "bash", (
                f"ERROR: Step '{step.get('name', '<unnamed>')}' in job '{job_id}' "
                f"has shell: {shell!r} instead of 'bash'. "
                "All run: steps in CI jobs that invoke the operator-path tests "
                "must use 'shell: bash' (CLAUDE.md GitHub Workflows -- Shell "
                "Configuration). "
                "Add 'shell: bash' to the offending step."
            )
