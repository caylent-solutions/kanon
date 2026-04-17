"""Tests for pyproject.toml build configuration.

Validates that the wheel build configuration includes the repo package,
all subpackages, non-Python runtime files, and that the project version
is set correctly.
"""

import pathlib
import tomllib

import pytest

REPO_ROOT = pathlib.Path(__file__).parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

REQUIRED_PACKAGES = [
    "src/kanon_cli",
    "src/kanon_cli/repo",
    "src/kanon_cli/repo/subcmds",
]

REQUIRED_ARTIFACTS = [
    "repo",
    "git_ssh",
    "requirements.json",
]

REQUIRED_ARTIFACT_GLOBS = [
    "hooks/*",
]


def _load_pyproject() -> dict:
    """Load and parse pyproject.toml from the repo root.

    Returns:
        Parsed TOML content as a dict.

    Raises:
        AssertionError: If pyproject.toml does not exist.
    """
    assert PYPROJECT_PATH.is_file(), f"pyproject.toml must exist at {PYPROJECT_PATH}"
    with PYPROJECT_PATH.open("rb") as fh:
        return tomllib.load(fh)


@pytest.mark.unit
def test_project_version_is_valid_semver() -> None:
    """Verify that the project version in pyproject.toml is a valid SemVer string.

    Given: pyproject.toml exists at the repo root
    When: the [project] version field is read
    Then: it matches MAJOR.MINOR.PATCH (no v-prefix)
    """
    import re

    data = _load_pyproject()
    actual = data["project"]["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[.\-+].+)?", actual), (
        f"[project] version must be a valid SemVer string (MAJOR.MINOR.PATCH), got {actual!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("package", REQUIRED_PACKAGES)
def test_wheel_includes_package(package: str) -> None:
    """Verify that each required package path is listed in the wheel packages.

    Given: pyproject.toml exists at the repo root
    When: [tool.hatch.build.targets.wheel] packages list is read
    Then: each required package path is present
    """
    data = _load_pyproject()
    packages = data["tool"]["hatch"]["build"]["targets"]["wheel"].get("packages", [])
    assert package in packages, f"Expected wheel packages to include '{package}', got: {packages}"


@pytest.mark.unit
@pytest.mark.parametrize("artifact", REQUIRED_ARTIFACTS)
def test_wheel_includes_non_python_artifact(artifact: str) -> None:
    """Verify that each required non-Python artifact path is in the wheel include list.

    Given: pyproject.toml exists at the repo root
    When: [tool.hatch.build.targets.wheel] include list is read
    Then: each required non-Python artifact is present
    """
    data = _load_pyproject()
    wheel_cfg = data["tool"]["hatch"]["build"]["targets"]["wheel"]
    include = wheel_cfg.get("include", [])
    assert artifact in include, f"Expected wheel include to contain '{artifact}', got: {include}"


@pytest.mark.unit
@pytest.mark.parametrize("glob_pattern", REQUIRED_ARTIFACT_GLOBS)
def test_wheel_includes_non_python_glob(glob_pattern: str) -> None:
    """Verify that required glob patterns for non-Python files appear in wheel include.

    Given: pyproject.toml exists at the repo root
    When: [tool.hatch.build.targets.wheel] include list is read
    Then: each required glob pattern is present
    """
    data = _load_pyproject()
    wheel_cfg = data["tool"]["hatch"]["build"]["targets"]["wheel"]
    include = wheel_cfg.get("include", [])
    assert glob_pattern in include, f"Expected wheel include to contain glob '{glob_pattern}', got: {include}"


@pytest.mark.unit
def test_no_repo_console_scripts_entry() -> None:
    """Verify that no 'repo' console_scripts entry exists in [project.scripts].

    Given: pyproject.toml exists at the repo root
    When: [project.scripts] section is read
    Then: there is no key named 'repo'
    """
    data = _load_pyproject()
    scripts = data.get("project", {}).get("scripts", {})
    assert "repo" not in scripts, f"[project.scripts] must not contain a 'repo' entry, found: {scripts}"
