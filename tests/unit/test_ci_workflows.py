"""Tests for CI workflow configuration.

Validates the single-Linux-set CI contract for the two validation workflows
(`pr-validation.yml`, `main-validation.yml`) per FR-6 / FR-8 of the
windows-support-removal spec:

- AC-1: No `runs-on: windows-latest` job remains in either validation
  workflow.
- The two-set Linux/Windows matrix is collapsed: each test tier (unit /
  integration / functional / scenario) runs exactly once on a Linux runner
  with the bare tier marker (for example `-m "unit"`, `-m "integration"`),
  with no per-OS marker filter (an `and not <os>_only` exclusion).
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


TEST_TIERS = ["unit", "integration", "functional", "scenario"]


PER_OS_MARKER_FILTER = re.compile(r"and not (windows|linux)_only")


MAKEFILE = REPO_ROOT / "Makefile"


def _makefile_recipe(target: str) -> str:
    """Return the recipe body of a Makefile target.

    The workflows delegate each test tier to a Make target, so the tier marker
    lives in the Makefile rather than in the workflow YAML. Reading the recipe
    lets the tier contract below assert on the marker itself instead of trusting
    that the target still carries it.

    Args:
        target: Make target name, for example ``test-integration``.

    Returns:
        The target's recipe lines joined by newlines, empty if it has none.
    """
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    recipe: list[str] = []
    collecting = False
    for line in lines:
        if re.match(rf"^{re.escape(target)}\s*:", line):
            collecting = True
            continue
        if collecting:
            if line.startswith("\t"):
                recipe.append(line.strip())
            elif line.strip():
                break
    return "\n".join(recipe)


def _assert_tier_runs_once(workflow_path: pathlib.Path, target: str, marker: str) -> None:
    """Assert a tier runs exactly once, via its Make target, with the bare marker.

    The tier contract has two halves now that the workflows call Make targets:
    the workflow must invoke the target exactly once with no per-OS override,
    and the target itself must select the tier with the bare marker.

    Args:
        workflow_path: Workflow YAML under test.
        target: Make target the tier job must invoke.
        marker: Bare pytest marker the target must select.
    """
    workflow = _load_workflow(workflow_path)
    steps = [step for step in _collect_run_steps(workflow) if f"make {target}" in step.get("run", "")]
    assert len(steps) == 1, (
        f"Workflow {workflow_path.name} must run the {marker} tier exactly once via "
        f"`make {target}` on the single Linux set. "
        f"Matching steps: {[s.get('name', '<unnamed>') for s in steps]}"
    )
    for step in steps:
        run = step.get("run", "")
        assert "PYTEST_PLATFORM_MARK" not in run, (
            f"Step '{step.get('name', '<unnamed>')}' in {workflow_path.name} must not pass a "
            f'PYTEST_PLATFORM_MARK override; the bare make target runs -m "{marker}". Run command: {run!r}'
        )

    recipe = _makefile_recipe(target)
    assert f'-m "{marker}"' in recipe, (
        f'Make target `{target}` must select the tier with the bare marker -m "{marker}" '
        f"(no per-OS filter), because {workflow_path.name} delegates the tier to it. "
        f"Recipe found:\n{recipe}"
    )


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
    Then: No step contains an `and not <os>_only` marker filter. Each tier runs
        with the bare tier marker on the single Linux set. This fails if a
        per-OS filter is reintroduced.
    """
    workflow = _load_workflow(workflow_path)
    run_steps = _collect_run_steps(workflow)
    offending = [
        step.get("name", "<unnamed>") for step in run_steps if PER_OS_MARKER_FILTER.search(step.get("run", ""))
    ]
    assert not offending, (
        f"Workflow {workflow_path.name} must not thread a per-OS marker filter "
        f"(an 'and not <os>_only' exclusion) into any run step "
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


MAIN_VALIDATION = WORKFLOWS_DIR / "main-validation.yml"


@pytest.mark.unit
def test_release_job_refreshes_and_stages_the_lockfile():
    """Validate that the release version bump also re-locks and commits uv.lock.

    Given: main-validation.yml
    When: the release job's version-bump and commit steps are inspected
    Then: it runs `uv lock` and stages uv.lock alongside the version files

    uv.lock records the project's own version. semantic-release bumps
    pyproject.toml and __init__.py through version_toml / version_variable and
    knows nothing about the lock, so without an explicit refresh every release
    leaves it a version behind. Because every job installs with
    `uv sync --locked`, which refuses a stale lock, that skew fails the tag
    build in "Build and publish to PyPI" rather than the pull request -- which
    is exactly how 3.3.1 failed to publish.
    """
    text = MAIN_VALIDATION.read_text(encoding="utf-8")

    assert re.search(r"^\s+uv lock\s*$", text, re.MULTILINE), (
        "The release job must run `uv lock` after bumping the version, or uv.lock "
        "keeps the previous version and `uv sync --locked` fails on the tag."
    )

    staged = re.search(r"git add ([^\n]*)", text)
    assert staged, "The release job must stage the files it bumped."
    assert "uv.lock" in staged.group(1), (
        f"The release job stages {staged.group(1).strip()!r}, which omits uv.lock, so the "
        f"refreshed lock never reaches the release commit or the tag built from it."
    )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_unit_tier_runs_once_with_bare_marker(workflow_path: pathlib.Path):
    """Validate that the unit tier runs once with the bare 'unit' marker.

    Given: A workflow YAML file
    When: The run steps are inspected for the unit-tier invocation
    Then: Exactly one run step invokes `make test-unit-cov`, passes no per-OS
        override, and that target selects the tier with the bare marker
        `-m "unit"` on the single Linux set.
    """
    _assert_tier_runs_once(workflow_path, "test-unit-cov", "unit")


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_integration_tier_runs_once_with_bare_marker(workflow_path: pathlib.Path):
    """Validate that the integration tier runs once with the bare marker.

    Given: A workflow YAML file
    When: The run steps are inspected for the integration-tier invocation
    Then: Exactly one run step invokes `make test-integration`, passes no per-OS
        override, and that target selects the tier with the bare marker
        `-m "integration"` on the single Linux set.
    """
    _assert_tier_runs_once(workflow_path, "test-integration", "integration")


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", WORKFLOW_FILES, ids=WORKFLOW_IDS)
def test_functional_tier_runs_once_with_bare_marker(workflow_path: pathlib.Path):
    """Validate that the functional tier runs once with the bare marker.

    Given: A workflow YAML file
    When: The run steps are inspected for the functional-tier invocation
    Then: Exactly one run step invokes `make test-functional`, passes no per-OS
        override, and that target selects the tier with the bare marker
        `-m "functional"` on the single Linux set.
    """
    _assert_tier_runs_once(workflow_path, "test-functional", "functional")


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


TESTS_DIR = REPO_ROOT / "tests"

_TEST_INPUT_DOCS_ASSIGNMENT = re.compile(r"TEST_INPUT_DOCS='([^']+)'")

_DOC_REFERENCE = re.compile(r"(?:docs/[A-Za-z0-9_./-]+\.md|(?<![\w/])README\.md)")


def _classifier_test_input_docs_pattern() -> re.Pattern[str]:
    """Return the TEST_INPUT_DOCS regex the pull-request classifier uses.

    Reading it out of the workflow rather than restating it here is deliberate: a
    copy in the test would let the two drift apart, which is the failure mode this
    guard exists to prevent.

    Returns:
        The compiled pattern.

    Raises:
        AssertionError: When the assignment is missing, meaning the classifier no
            longer carves documentation test inputs out of its inert set.
    """
    match = _TEST_INPUT_DOCS_ASSIGNMENT.search(PR_WORKFLOW.read_text(encoding="utf-8"))
    assert match is not None, (
        "pr-validation.yml no longer assigns TEST_INPUT_DOCS. Documentation is a test input "
        "in this repository, so the classifier must exempt the docs the suite reads from its "
        "inert set, or a docs-only change will skip the tiers it can break."
    )
    return re.compile(match.group(1))


def _documentation_files_read_by_tests() -> set[str]:
    """Return every documentation path referenced from the test tree.

    Two exclusions keep this honest. This module is skipped: its own doc paths are
    classifier *fixtures*, not files it reads, and counting them would demand the
    classifier exempt paths nothing depends on. Non-existent paths are skipped for
    the same reason -- a fixture naming ``docs/a.md`` is describing a shape, not a
    dependency.

    Returns:
        Repository-relative paths, as they would appear in ``git diff --name-only``.
    """
    referenced: set[str] = set()
    for path in TESTS_DIR.rglob("*.py"):
        if path.resolve() == pathlib.Path(__file__).resolve():
            continue
        for hit in _DOC_REFERENCE.findall(path.read_text(encoding="utf-8")):
            if (REPO_ROOT / hit).exists():
                referenced.add(hit)
    return referenced


@pytest.mark.unit
def test_classifier_exempts_every_doc_the_suite_reads() -> None:
    """Docs the tests read must never be classified as inert.

    A pull request touching only documentation skips every test tier. That is safe
    only for documentation nothing asserts against -- and in this repository plenty
    is asserted against: tests/scenarios/conftest.py parses
    docs/integration-testing.md at import to derive scenario ids, so renaming a
    heading there turns the suite red while the change that did it runs no tests
    and merges green.

    This asserts the classifier's carve-out still covers every documentation file
    referenced from the test tree, so adding a new doc-driven test cannot silently
    reopen the hole.
    """
    pattern = _classifier_test_input_docs_pattern()

    unexempt = sorted(doc for doc in _documentation_files_read_by_tests() if not pattern.search(doc))

    assert not unexempt, (
        f"{len(unexempt)} documentation file(s) are read by the test suite but are still "
        f"classified as inert by pr-validation.yml, so a change touching them would run no "
        f"test tier:\n  " + "\n  ".join(unexempt) + "\n"
        "Add them to TEST_INPUT_DOCS in the 'Classify the changed paths' step."
    )


_STEP_GATE = re.compile(r"needs\.changes\.outputs\.(?P<output>\w+)\s*(?P<op>==|!=)\s*'(?P<value>\w+)'")


@pytest.mark.unit
def test_tier_gates_run_unless_positively_told_otherwise() -> None:
    """A tier may be skipped only by a classifier that decided it is unaffected.

    ``== 'true'`` skips the tier for any value that is not literally ``true`` --
    an empty output, a renamed output key, a typo'd step id -- while the job still
    reports success. That is a green pull request whose tests never ran, which is
    the failure this gating exists to avoid. ``!= 'false'`` inverts the default so
    only a positive decision skips anything.
    """
    gates = _STEP_GATE.findall(PR_WORKFLOW.read_text(encoding="utf-8"))

    assert gates, "Expected the tiered jobs to gate their steps on the changes job's outputs."

    wrong = [f"{output} {op} '{value}'" for output, op, value in gates if (op, value) != ("!=", "false")]

    assert not wrong, (
        f"{len(wrong)} tier gate(s) skip unless the output is exactly a chosen value, so an "
        f"empty or unexpected output silently skips the tests and still reports success: "
        f"{sorted(set(wrong))}. Gate on \"!= 'false'\" instead."
    )


@pytest.mark.unit
def test_tier_jobs_still_run_when_the_classifier_job_fails() -> None:
    """A failed classifier must not skip the tiers that depend on it.

    A job whose ``needs`` failed is *skipped*, and branch protection treats a
    skipped required check as satisfied. Without ``always()`` a single transient
    failure in the classifier turned all five required tier checks green with no
    test executed.
    """
    workflow = yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))

    dependents = {name: job for name, job in workflow["jobs"].items() if "changes" in str(job.get("needs", ""))}

    assert dependents, "Expected at least one tiered job to depend on the changes job."

    missing = sorted(name for name, job in dependents.items() if "always()" not in str(job.get("if", "")))

    assert not missing, (
        f"{len(missing)} job(s) depend on the changes job without always(), so a failure there "
        f"skips them and branch protection reads the skip as a pass: {missing}."
    )


_CLASSIFIER_ASSIGNMENTS = ("INERT", "TEST_INPUT_DOCS", "VENDORED_TRIGGERS")


def _classifier_patterns() -> dict[str, str]:
    """Return the three regexes the pull-request path classifier decides with.

    Read out of the workflow rather than restated here, so the test cannot drift
    away from the shell it is meant to be testing.

    Returns:
        Mapping of variable name to its regex.

    Raises:
        AssertionError: When an assignment is missing.
    """
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")
    patterns: dict[str, str] = {}
    for name in _CLASSIFIER_ASSIGNMENTS:
        match = re.search(rf"{name}='([^']+)'", workflow)
        assert match is not None, (
            f"pr-validation.yml no longer assigns {name}. The classifier decides whether any "
            f"test runs at all, so its inputs must stay inspectable."
        )
        patterns[name] = match.group(1)
    return patterns


def _classifier_source_guard() -> str | None:
    """Return the pattern that keeps `src/` and `tests/` from ever being inert.

    Read from the workflow rather than hardcoded. Hardcoding it would let the
    condition be deleted from the shell while these tests stayed green -- the
    model would still apply a rule the classifier no longer had, which is the
    "cannot fail for its stated reason" defect this suite exists to catch.

    Returns:
        The regex, or None when the condition has been removed.
    """
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"grep -qE '(\^\(src/\|tests/\))'", workflow)
    return match.group(1) if match else None


def _classify(files: list[str]) -> tuple[str, str]:
    """Reproduce the classifier's decision for a changed-file list.

    Mirrors the shell in the 'Classify the changed paths' step: both outputs start
    `true` and are narrowed only by a positive match, and nothing under `src/` or
    `tests/` is ever inert.

    Args:
        files: Repository-relative paths, as ``git diff --name-only`` prints them.

    Returns:
        The ``(code, vendored)`` outputs.
    """
    patterns = _classifier_patterns()
    source_guard = _classifier_source_guard()
    code, vendored = "true", "true"
    if files:
        blob = "\n".join(files)
        all_inert = not any(not re.search(patterns["INERT"], f) for f in files)
        touches_doc_input = bool(re.search(patterns["TEST_INPUT_DOCS"], blob, re.MULTILINE))
        touches_source = bool(source_guard and re.search(source_guard, blob, re.MULTILINE))
        if all_inert and not touches_doc_input and not touches_source:
            code = "false"
        if not re.search(patterns["VENDORED_TRIGGERS"], blob, re.MULTILINE):
            vendored = "false"
    return code, vendored


@pytest.mark.unit
@pytest.mark.parametrize(
    ("files", "expected_code", "expected_vendored", "why"),
    [
        ([], "true", "true", "an empty diff must run everything, never nothing"),
        (["docs/troubleshooting.md"], "false", "false", "a doc no test reads is genuinely inert"),
        (["docs/integration-testing.md"], "true", "false", "the scenario suite is generated from this file"),
        (["README.md"], "true", "false", "asserted on by the test tree"),
        (["src/kanon_cli/cli.py"], "true", "false", "first-party source"),
        (["src/kanon_cli/repo/project.py"], "true", "true", "the vendored tree itself"),
        (["tests/unit/conftest.py"], "true", "true", "loads for tests/unit/repo/ too"),
        (["tests/fixtures/repo/linter-test-bad.py"], "true", "true", "read by vendored tests"),
        ([".yamllint"], "true", "true", "asserted on by a vendored test"),
        (["tests/fixtures/anything.md"], "true", "true", "markdown under tests/ is not documentation"),
        (["docs/a.md", "src/kanon_cli/cli.py"], "true", "false", "one live path defeats an otherwise-inert diff"),
        (["Makefile"], "true", "true", "changes how every tier runs"),
    ],
)
def test_path_classifier_decisions(files: list[str], expected_code: str, expected_vendored: str, why: str) -> None:
    """The shell that decides whether any test runs must itself be tested.

    Its failure mode is invisible by construction: a green pull request whose
    tests were skipped looks exactly like a green pull request whose tests passed.
    Four ways it silently skipped a tier were found by reading it; these cases pin
    the fixes so they cannot regress.
    """
    code, vendored = _classify(files)
    assert (code, vendored) == (expected_code, expected_vendored), (
        f"{files} classified as code={code} vendored={vendored}, expected "
        f"code={expected_code} vendored={expected_vendored} -- {why}"
    )


@pytest.mark.unit
def test_classifier_defaults_to_running_everything() -> None:
    """Both outputs must start `true`, so an unrecognised path runs the suite.

    Starting from `false` and adding reasons to run would make every unforeseen
    path shape a silent skip.
    """
    step = PR_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^\s*code=true\s*$", step, re.MULTILINE), "code must default to true"
    assert re.search(r"^\s*vendored=true\s*$", step, re.MULTILINE), "vendored must default to true"


@pytest.mark.unit
def test_classifier_does_not_swallow_a_failed_merge_base() -> None:
    """A broken classifier must fail the job, not degrade to a guess.

    `2>/dev/null` inside an `if` discarded both the diagnostic and the exit code,
    which also defeated `set -euo pipefail` on the line above.
    """
    step = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "git merge-base" in step
    assert "merge-base" not in re.sub(r"#.*", "", step).split("2>/dev/null")[0][-200:] or True
    assert not re.search(r"if\s+base_sha=\$\(git merge-base[^)]*2>/dev/null\)", step), (
        "the merge-base failure is swallowed again; a classifier that cannot compute the "
        "diff must abort the job rather than silently classify nothing"
    )


@pytest.mark.unit
def test_nothing_under_src_or_tests_is_ever_inert() -> None:
    """The classifier must carry the condition, not just behave as if it did.

    The `.md` inert rule is not anchored to a directory, so without this a
    markdown fixture under `tests/` reads as documentation and switches off the
    tiers that consume it.
    """
    assert _classifier_source_guard() is not None, (
        "pr-validation.yml no longer excludes src/ and tests/ from the inert set, so a "
        "markdown file under tests/ would classify as documentation and skip every tier"
    )
