"""Guard test: verifies Make/pyproject wiring for the scenario marker and
operator-path test targets cannot silently regress.

Parses pyproject.toml and Makefile from the project root (derived from
this file's own location -- no hard-coded absolute paths) and asserts:

1. The 'scenario' pytest marker is registered in
   [tool.pytest.ini_options].markers.
2. 'make test' runs the full suite (no -m filter that would exclude
   scenario tests).
3. 'make test-scenarios' selects the 'scenario' marker.
4. 'make test-operator-path' exists, is listed in .PHONY, and has a
   '## ' help string consistent with existing targets.
"""

import tomllib
from pathlib import Path

import pytest


def _project_root() -> Path:
    """Return the project root by walking up from this file."""
    here = Path(__file__).resolve()

    root = here.parent.parent.parent
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise FileNotFoundError(
            f"ERROR: pyproject.toml not found at expected location {pyproject}. "
            "The project root could not be determined from this file's path. "
            "Ensure this file lives at <project_root>/tests/functional/."
        )
    return root


def _load_pyproject(root: Path) -> dict:
    """Parse pyproject.toml and return the parsed dict."""
    pyproject_path = root / "pyproject.toml"
    with pyproject_path.open("rb") as fh:
        return tomllib.load(fh)


def _load_makefile_lines(root: Path) -> list[str]:
    """Read the Makefile and return its lines."""
    makefile_path = root / "Makefile"
    if not makefile_path.is_file():
        raise FileNotFoundError(
            f"ERROR: Makefile not found at {makefile_path}. Ensure a Makefile exists at the project root."
        )
    return makefile_path.read_text(encoding="utf-8").splitlines()


@pytest.fixture(scope="module")
def project_root() -> Path:
    return _project_root()


@pytest.fixture(scope="module")
def pyproject_data(project_root: Path) -> dict:
    return _load_pyproject(project_root)


@pytest.fixture(scope="module")
def makefile_lines(project_root: Path) -> list[str]:
    return _load_makefile_lines(project_root)


@pytest.mark.functional
def test_scenario_marker_registered_in_pyproject(pyproject_data: dict) -> None:
    """AC-FUNC-001: 'scenario' marker must appear in
    [tool.pytest.ini_options].markers.
    """
    markers: list[str] = pyproject_data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("markers", [])
    assert markers, (
        "ERROR: [tool.pytest.ini_options].markers is empty or absent in "
        "pyproject.toml. At least the 'scenario' marker must be registered."
    )
    scenario_entries = [m for m in markers if m.startswith("scenario:")]
    assert len(scenario_entries) == 1, (
        f"ERROR: Expected exactly one 'scenario:' entry in "
        f"[tool.pytest.ini_options].markers, found {len(scenario_entries)}. "
        f"Registered markers: {markers}. "
        "Register 'scenario: ...' in pyproject.toml."
    )


@pytest.mark.functional
def test_make_test_runs_full_suite(makefile_lines: list[str]) -> None:
    """AC-FUNC-002: 'make test' must run the full pytest suite (no -m filter
    that would silently exclude scenario/operator-path tests).
    """
    recipe_lines = _collect_recipe_lines(makefile_lines, "test")
    assert recipe_lines, (
        "ERROR: No recipe lines found for 'test:' target in Makefile. "
        "Ensure a 'test:' target with a pytest invocation exists."
    )

    pytest_lines = [ln for ln in recipe_lines if "pytest" in ln]
    assert pytest_lines, (
        f"ERROR: 'test:' target recipe does not contain a pytest invocation. Recipe lines: {recipe_lines}."
    )
    for line in pytest_lines:
        assert "-m " not in line and "-m\t" not in line, (
            f"ERROR: 'make test' recipe line '{line}' applies a -m marker "
            "filter, which would exclude scenario/operator-path tests. "
            "Remove the -m filter so 'make test' runs the full suite."
        )


@pytest.mark.functional
def test_make_test_scenarios_selects_scenario_marker(makefile_lines: list[str]) -> None:
    """AC-FUNC-002: 'make test-scenarios' must select the 'scenario' marker."""
    recipe_lines = _collect_recipe_lines(makefile_lines, "test-scenarios")
    assert recipe_lines, (
        "ERROR: No recipe lines found for 'test-scenarios:' target in Makefile. "
        "Add a 'test-scenarios:' target that runs 'uv run pytest -m scenario'."
    )
    combined = " ".join(recipe_lines)

    selects_scenario = "-m scenario" in combined or "-m 'scenario" in combined or '-m "scenario' in combined
    assert selects_scenario, (
        f"ERROR: 'make test-scenarios' recipe does not select the 'scenario' "
        f"marker. Recipe: {recipe_lines}. "
        'The recipe must select the scenario marker (e.g. -m "scenario").'
    )


@pytest.mark.functional
def test_make_test_operator_path_target_exists(makefile_lines: list[str]) -> None:
    """AC-FUNC-003: 'make test-operator-path' target must exist."""
    target_lines = [ln for ln in makefile_lines if ln.startswith("test-operator-path:")]
    assert target_lines, (
        "ERROR: 'test-operator-path:' target not found in Makefile. "
        "Add a 'test-operator-path:' target to the Makefile so the operator-"
        "path scenario tests have a dedicated fast lane."
    )


@pytest.mark.functional
def test_make_test_operator_path_in_phony(makefile_lines: list[str]) -> None:
    """AC-FUNC-003: 'test-operator-path' must be listed in .PHONY."""
    phony_lines = [ln for ln in makefile_lines if ln.startswith(".PHONY:")]
    assert phony_lines, (
        "ERROR: No .PHONY declaration found in Makefile. Add a .PHONY line that includes 'test-operator-path'."
    )
    phony_targets = " ".join(phony_lines)
    assert "test-operator-path" in phony_targets, (
        f"ERROR: 'test-operator-path' is not listed in .PHONY. "
        f"Current .PHONY declaration: {phony_lines}. "
        "Add 'test-operator-path' to the .PHONY line."
    )


@pytest.mark.functional
def test_make_test_operator_path_has_help_string(makefile_lines: list[str]) -> None:
    """AC-FUNC-003: 'test-operator-path' target must have a '## ' help string."""
    target_lines = [ln for ln in makefile_lines if ln.startswith("test-operator-path:")]
    assert target_lines, (
        "ERROR: 'test-operator-path:' target not found in Makefile. Add the target before checking for its help string."
    )
    has_help = any("## " in ln for ln in target_lines)
    assert has_help, (
        f"ERROR: 'test-operator-path:' target line does not contain a '## ' "
        f"help string. Found: {target_lines}. "
        "Add '## <description>' to the target line so 'make help' includes it."
    )


@pytest.mark.functional
def test_make_test_operator_path_runs_scenario_marker(makefile_lines: list[str]) -> None:
    """AC-FUNC-003: 'make test-operator-path' recipe must invoke pytest with
    '-m scenario' (or a more specific operator-path subset marker) so the
    E49 operator-path tests actually run.
    """
    recipe_lines = _collect_recipe_lines(makefile_lines, "test-operator-path")
    assert recipe_lines, (
        "ERROR: 'test-operator-path:' target has no recipe lines in Makefile. "
        "Add a recipe that runs 'uv run pytest -m scenario' (or a subset) "
        "so the operator-path tests execute."
    )
    combined = " ".join(recipe_lines)
    assert "pytest" in combined, f"ERROR: 'test-operator-path' recipe does not invoke pytest. Recipe: {recipe_lines}."
    assert "scenario" in combined, (
        f"ERROR: 'test-operator-path' recipe does not reference the 'scenario' "
        f"marker or scenario test paths. Recipe: {recipe_lines}. "
        "The recipe must run the scenario tests (e.g., '-m scenario' or "
        "an explicit path to tests/scenarios/)."
    )


@pytest.mark.functional
def test_operator_path_test_files_exist(project_root: Path) -> None:
    """AC-FUNC-002: The E49 operator-path scenario test files must exist so
    'make test-scenarios' actually executes them.
    """
    expected_files = [
        "tests/scenarios/test_why_url_path.py",
        "tests/scenarios/test_doctor_cache.py",
        "tests/scenarios/test_rls_exact_vs_range.py",
    ]
    missing = [rel for rel in expected_files if not (project_root / rel).is_file()]
    assert not missing, (
        f"ERROR: The following E49 operator-path scenario test files are "
        f"missing from the repository: {missing}. "
        "These files must exist for 'make test-scenarios' to exercise the "
        "operator-path behaviors. Verify that the E49 feature tasks have been "
        "completed and their test files are committed to the branch."
    )


def _collect_recipe_lines(makefile_lines: list[str], target: str) -> list[str]:
    """Return the tab-indented recipe lines that belong to a given Make target.

    Scans forward from the first line that starts with '<target>:' and
    collects lines that begin with a tab (recipe lines), stopping when a
    non-empty, non-tab, non-comment line is encountered (next target or
    directive).
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
