"""Tests for CI workflow configuration.

Validates the single-Linux-set CI contract for the two validation workflows
(`pr-validation.yml`, `main-validation.yml`) per FR-6 / FR-8 of the
windows-support-removal spec:

- AC-1: No `runs-on: windows-latest` job remains in either validation
  workflow.
- The two-set Linux/Windows matrix is collapsed: each test tier (unit /
  integration / functional / scenario) runs exactly once on a Linux runner
  with the bare tier marker (for example `-m "unit"`, `-m "integration"`),
  with no per-OS marker filter (`and not windows_only` / `and not
  linux_only`).
- Surviving conventions are preserved: every `run` step uses `shell: bash`,
  the workflow YAML is valid, the integration job runs in parallel with the
  unit job, and the ruff check / format-check steps cover `src/`.

The contract assertions below fail if a `windows-latest` leg or a per-OS
marker filter is reintroduced into either workflow.
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
WORKFLOW_IDS = ["pr-validation", "main-validation"]

# The four test tiers that must each run exactly once on the single Linux set.
TEST_TIERS = ["unit", "integration", "functional", "scenario"]

# Matches a per-OS marker filter that the single-Linux-set contract forbids,
# for example `unit and not windows_only` or `scenario and not linux_only`.
PER_OS_MARKER_FILTER = re.compile(r"and not (windows_only|linux_only)")


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


def _job_run_text(job: dict) -> str:
    """Concatenate the `run` text of every run step in a job.

    Args:
        job: Parsed job dict.

    Returns:
        Newline-joined `run` command text for the job.
    """
    return "\n".join(step.get("run", "") for step in job.get("steps", []) if "run" in step)


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_workflow_yaml_is_valid(workflow_path: pathlib.Path):
    """Validate that each workflow YAML file is valid and parsable.

    Given: A workflow YAML file exists
    When: The file is loaded with yaml.safe_load
    Then: It parses without error and contains a 'jobs' key
    """
    assert workflow_path.is_file(), f"Workflow file must exist: {workflow_path}"
    workflow = _load_workflow(workflow_path)
    assert isinstance(workflow, dict), f"Workflow must be a dict: {workflow_path}"
    assert "jobs" in workflow, f"Workflow must contain 'jobs' key: {workflow_path}"


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_all_run_steps_use_shell_bash(workflow_path: pathlib.Path):
    """Validate that every run step in each workflow uses shell: bash.

    Given: A workflow YAML file with run steps
    When: Each run step's shell attribute is inspected
    Then: Every run step has shell: bash so it fails the job on non-zero exit
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
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_no_windows_latest_runner(workflow_path: pathlib.Path):
    """Validate that no job targets the windows-latest runner (AC-1, FR-6).

    Given: A workflow YAML file
    When: The `runs-on` of every job is inspected
    Then: No job runs on `windows-latest`; the two-set matrix is collapsed to a
        single Linux set. This fails if a Windows leg is reintroduced.
    """
    workflow = _load_workflow(workflow_path)
    jobs = workflow.get("jobs", {})
    assert jobs, f"Workflow {workflow_path.name} must contain jobs"
    windows_jobs = {name: job.get("runs-on") for name, job in jobs.items() if job.get("runs-on") == "windows-latest"}
    assert not windows_jobs, (
        f"Workflow {workflow_path.name} must not contain any windows-latest job "
        f"(single-Linux-set contract, FR-6/AC-1). Offending jobs: {sorted(windows_jobs)}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_no_per_os_marker_filter(workflow_path: pathlib.Path):
    """Validate that no run step threads a per-OS pytest marker filter (FR-6).

    Given: A workflow YAML file
    When: Every run step's command text is inspected
    Then: No step contains an `and not windows_only` / `and not linux_only`
        marker filter. Each tier runs with the bare tier marker on the single
        Linux set. This fails if a per-OS filter is reintroduced.
    """
    workflow = _load_workflow(workflow_path)
    run_steps = _collect_run_steps(workflow)
    offending = [
        step.get("name", "<unnamed>") for step in run_steps if PER_OS_MARKER_FILTER.search(step.get("run", ""))
    ]
    assert not offending, (
        f"Workflow {workflow_path.name} must not thread a per-OS marker filter "
        f"('and not windows_only' / 'and not linux_only') into any run step "
        f"(single-Linux-set contract, FR-6). Offending steps: {offending}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_workflow_has_integration_tests_job(workflow_path: pathlib.Path):
    """Validate that each workflow includes exactly one integration tests job.

    Given: A workflow YAML file
    When: The jobs are inspected
    Then: Exactly one job whose name references 'integration' exists, since the
        Windows integration leg is removed and only the Linux leg survives.
    """
    workflow = _load_workflow(workflow_path)
    jobs = workflow.get("jobs", {})
    integration_jobs = {name: job for name, job in jobs.items() if "integration" in name.lower()}
    assert len(integration_jobs) == 1, (
        f"Workflow {workflow_path.name} must contain exactly one integration tests job "
        f"(single Linux leg). Found: {sorted(integration_jobs)}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_integration_job_runs_in_parallel_with_unit_tests(workflow_path: pathlib.Path):
    """Validate that the integration tests job runs in parallel with unit tests.

    Given: A workflow YAML with both a unit-tests job and an integration job
    When: The 'needs' dependency of the integration job is inspected
    Then: The integration job does NOT depend on the unit-tests job (parallel)
    """
    workflow = _load_workflow(workflow_path)
    jobs = workflow.get("jobs", {})
    integration_jobs = {name: job for name, job in jobs.items() if "integration" in name.lower()}
    assert integration_jobs, f"No integration job found in {workflow_path.name}"

    unit_job_names = {name for name in jobs if "unit" in name.lower()}

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
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_unit_tier_runs_once_with_bare_marker(workflow_path: pathlib.Path):
    """Validate that the unit tier runs once with the bare 'unit' marker.

    Given: A workflow YAML file
    When: The run steps are inspected for the unit-tier pytest invocation
    Then: Exactly one run step selects the unit tier with the bare marker
        `-m "unit"` (no per-OS filter), on the single Linux set.
    """
    workflow = _load_workflow(workflow_path)
    run_steps = _collect_run_steps(workflow)
    bare_unit = re.compile(r'-m "unit"')
    unit_steps = [step for step in run_steps if bare_unit.search(step.get("run", ""))]
    assert len(unit_steps) == 1, (
        f'Workflow {workflow_path.name} must run the unit tier exactly once with the bare marker -m "unit" '
        f"on the single Linux set. Matching steps: {[s.get('name', '<unnamed>') for s in unit_steps]}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_integration_tier_runs_once_with_bare_marker(workflow_path: pathlib.Path):
    """Validate that the integration tier runs once with the bare marker.

    Given: A workflow YAML file
    When: The integration job's run steps are inspected
    Then: The integration job runs pytest with the bare marker `-m "integration"`
        (no per-OS filter), on the single Linux set.
    """
    workflow = _load_workflow(workflow_path)
    jobs = workflow.get("jobs", {})
    integration_jobs = {name: job for name, job in jobs.items() if "integration" in name.lower()}
    assert len(integration_jobs) == 1, f"Expected exactly one integration job in {workflow_path.name}"

    bare_integration = re.compile(r'-m "integration"')
    for job_name, job in integration_jobs.items():
        run_text = _job_run_text(job)
        assert bare_integration.search(run_text), (
            f"Integration job '{job_name}' in {workflow_path.name} must run pytest with the bare "
            f'marker -m "integration" (no per-OS filter). Run steps found:\n{run_text}'
        )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_functional_tier_runs_once_with_bare_marker(workflow_path: pathlib.Path):
    """Validate that the functional tier runs once with the bare marker.

    Given: A workflow YAML file
    When: The run steps are inspected for the functional-tier pytest invocation
    Then: Exactly one run step selects the functional tier with the bare marker
        `-m "functional"` (no per-OS filter), on the single Linux set.
    """
    workflow = _load_workflow(workflow_path)
    run_steps = _collect_run_steps(workflow)
    bare_functional = re.compile(r'-m "functional"')
    functional_steps = [step for step in run_steps if bare_functional.search(step.get("run", ""))]
    assert len(functional_steps) == 1, (
        f"Workflow {workflow_path.name} must run the functional tier exactly once with the bare "
        f'marker -m "functional" on the single Linux set. '
        f"Matching steps: {[s.get('name', '<unnamed>') for s in functional_steps]}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_scenario_tier_runs_once_without_platform_override(workflow_path: pathlib.Path):
    """Validate that the scenario tier runs once with no per-OS override.

    Given: A workflow YAML file
    When: The run steps are inspected for the scenario-tier invocation
    Then: Exactly one run step invokes `make test-scenarios` and no scenario
        run step passes a `PYTEST_PLATFORM_MARK` override, so the make target
        expands to the bare marker `-m "scenario"` on the single Linux set.
    """
    workflow = _load_workflow(workflow_path)
    run_steps = _collect_run_steps(workflow)
    scenario_steps = [step for step in run_steps if "test-scenarios" in step.get("run", "")]
    assert len(scenario_steps) == 1, (
        f"Workflow {workflow_path.name} must run the scenario tier exactly once via "
        f"`make test-scenarios` on the single Linux set. "
        f"Matching steps: {[s.get('name', '<unnamed>') for s in scenario_steps]}"
    )
    for step in scenario_steps:
        run = step.get("run", "")
        assert "PYTEST_PLATFORM_MARK" not in run, (
            f"Scenario step '{step.get('name', '<unnamed>')}' in {workflow_path.name} must not pass a "
            f'PYTEST_PLATFORM_MARK override; the bare make target runs -m "scenario". Run command: {run!r}'
        )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
@pytest.mark.parametrize("tier", TEST_TIERS)
def test_each_tier_runs_exactly_once(workflow_path: pathlib.Path, tier: str):
    """Validate that each test tier is invoked on exactly one runner.

    Given: A workflow YAML file and a test tier
    When: The jobs whose name references the tier are counted
    Then: Exactly one job runs the tier, proving the Windows leg was removed and
        the tier is not duplicated across two OS sets.
    """
    workflow = _load_workflow(workflow_path)
    jobs = workflow.get("jobs", {})
    tier_jobs = {name: job for name, job in jobs.items() if tier in name.lower()}
    assert len(tier_jobs) == 1, (
        f"Workflow {workflow_path.name} must run the '{tier}' tier in exactly one job "
        f"(single Linux set). Found: {sorted(tier_jobs)}"
    )
    only_job = next(iter(tier_jobs.values()))
    assert only_job.get("runs-on") != "windows-latest", (
        f"The '{tier}' tier job in {workflow_path.name} must not run on windows-latest"
    )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_ruff_check_covers_src_repo(workflow_path: pathlib.Path):
    """Validate that the ruff check step covers src/kanon_cli/repo/.

    Given: A workflow YAML file
    When: The run steps are inspected for ruff check invocations
    Then: The ruff check command covers src/ (which includes src/kanon_cli/repo/)
        or uses make lint which does the same
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
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_ruff_format_check_covers_src_repo(workflow_path: pathlib.Path):
    """Validate that the ruff format check step covers src/kanon_cli/repo/.

    Given: A workflow YAML file
    When: The run steps are inspected for ruff format check invocations
    Then: The ruff format --check command covers src/ (which includes src/kanon_cli/repo/)
        or uses make lint which does the same
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
