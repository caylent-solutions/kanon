"""Tests verifying the kanon-cli wheel contains all required files.

Builds the wheel from the project build system and inspects its contents
to confirm every .py file from src/kanon_cli/repo/ and all non-Python
runtime files are packaged correctly.

AC-TEST-001: Test builds the wheel successfully
AC-TEST-002: Test verifies every root .py file from repo/ is in the wheel
AC-TEST-003: Test verifies every subcmds .py file from repo/subcmds/ is in the wheel
AC-TEST-004: Test verifies non-Python runtime files are in the wheel
AC-TEST-005: Test verifies the wheel version matches pyproject.toml
AC-TEST-006: All test assertions are meaningful and can actually fail
"""

import pathlib
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Generator

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).parents[3]
"""Root of the kanon repository (3 levels up from tests/unit/repo/)."""

EXPECTED_WHEEL_VERSION = "1.2.0"

# Wheel package prefix for kanon_cli.repo files
_REPO_PREFIX = "kanon_cli/repo/"
_SUBCMDS_PREFIX = "kanon_cli/repo/subcmds/"

# The 25 root Python files (excluding __init__.py) per AC-TEST-002.
# Source: SPEC-repo-to-kanon-migration.md, section 2.1
ROOT_PYTHON_FILES = [
    "color.py",
    "command.py",
    "editor.py",
    "error.py",
    "event_log.py",
    "fetch.py",
    "git_command.py",
    "git_config.py",
    "git_refs.py",
    "git_superproject.py",
    "git_trace2_event_log.py",
    "git_trace2_event_log_base.py",
    "hooks.py",
    "main.py",
    "manifest_xml.py",
    "pager.py",
    "platform_utils.py",
    "platform_utils_win32.py",
    "progress.py",
    "project.py",
    "repo_logging.py",
    "repo_trace.py",
    "ssh.py",
    "version_constraints.py",
    "wrapper.py",
]

# The 28 subcmd Python files including __init__.py per AC-TEST-003.
# Source: SPEC-repo-to-kanon-migration.md, section 2.1
SUBCMD_PYTHON_FILES = [
    "__init__.py",
    "abandon.py",
    "branches.py",
    "checkout.py",
    "cherry_pick.py",
    "diff.py",
    "diffmanifests.py",
    "download.py",
    "envsubst.py",
    "forall.py",
    "gc.py",
    "grep.py",
    "help.py",
    "info.py",
    "init.py",
    "list.py",
    "manifest.py",
    "overview.py",
    "prune.py",
    "rebase.py",
    "selfupdate.py",
    "smartsync.py",
    "stage.py",
    "start.py",
    "status.py",
    "sync.py",
    "upload.py",
]

# Non-Python runtime files relative to kanon_cli/repo/ per AC-TEST-004.
# Source: SPEC-repo-to-kanon-migration.md, section 2.1, Non-Python files table
NON_PYTHON_RUNTIME_FILES = [
    "repo",
    "git_ssh",
    "hooks/commit-msg",
    "hooks/pre-auto-gc",
    "requirements.json",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_UV_EXECUTABLE = shutil.which("uv")


def _build_wheel(tmp_dir: pathlib.Path) -> pathlib.Path:
    """Build the kanon-cli wheel into tmp_dir via ``uv build --wheel``.

    Invokes ``uv`` as the build driver so the test is independent of the
    interpreter or virtualenv running pytest: ``uv`` resolves the project's
    declared build-system requirements (hatchling) from its own managed cache
    and runs the PEP 517 backend. The caller does not need to have ``build``
    or ``hatchling`` installed in the current Python environment -- only
    ``uv`` on PATH.

    Args:
        tmp_dir: Temporary directory to write the wheel into.

    Returns:
        Path to the built .whl file.

    Raises:
        RuntimeError: If ``uv`` is not on PATH, if ``uv build`` exits non-zero,
            or if no ``.whl`` file appears in tmp_dir on successful exit.
    """
    if _UV_EXECUTABLE is None:
        raise RuntimeError(
            "The 'uv' executable is required to build the kanon-cli wheel but was not found on PATH. "
            "Install uv (https://docs.astral.sh/uv/) and ensure it is reachable from the test runner's PATH."
        )
    result = subprocess.run(
        [_UV_EXECUTABLE, "build", "--wheel", "--out-dir", str(tmp_dir)],
        capture_output=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    if result.returncode != 0:
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(
            f"uv build --wheel failed with exit code {result.returncode}.\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )
    wheels = list(tmp_dir.glob("*.whl"))
    if not wheels:
        raise RuntimeError(
            f"uv build reported success but no .whl file found in {tmp_dir}. "
            f"Directory contents: {sorted(p.name for p in tmp_dir.iterdir())!r}"
        )
    return wheels[0]


def _unique_wheel_names(wheel_path: pathlib.Path) -> set[str]:
    """Return the set of unique file names in the wheel archive.

    Args:
        wheel_path: Path to the .whl file.

    Returns:
        Set of unique entry names found in the wheel zip archive.

    Raises:
        RuntimeError: If the wheel file cannot be opened as a zip archive.
    """
    try:
        with zipfile.ZipFile(wheel_path) as whl:
            return set(whl.namelist())
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Failed to open wheel as zip archive: {wheel_path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Session-scoped wheel fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built_wheel() -> Generator[pathlib.Path, None, None]:
    """Build the wheel once for the module and return its path.

    Builds into a temporary directory that persists for the module scope.
    The temporary directory is cleaned up automatically after all tests
    in this module complete.

    Returns:
        Path to the built .whl file.

    Raises:
        RuntimeError: If the build fails or produces no wheel file.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        wheel_path = _build_wheel(pathlib.Path(tmp_dir))
        yield wheel_path


@pytest.fixture(scope="module")
def wheel_names(built_wheel: pathlib.Path) -> set[str]:
    """Return the set of unique file names in the built wheel.

    Args:
        built_wheel: Path to the built .whl file.

    Returns:
        Set of unique entry names in the wheel archive.
    """
    return _unique_wheel_names(built_wheel)


# ---------------------------------------------------------------------------
# AC-TEST-001: Wheel builds successfully
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_wheel_builds_successfully(built_wheel: pathlib.Path) -> None:
    """Verify the wheel builds without error and produces a valid .whl file.

    AC-TEST-001: Test builds the wheel successfully.

    Given: The kanon project source is present at REPO_ROOT
    When: The wheel is built using the project build system
    Then: A .whl file is created and is a valid zip archive
    """
    assert built_wheel.exists(), f"Expected wheel file to exist at {built_wheel} but it does not"
    assert built_wheel.suffix == ".whl", f"Expected a .whl file but got: {built_wheel}"
    # Verify it's a readable zip archive
    assert zipfile.is_zipfile(built_wheel), (
        f"Built file {built_wheel} is not a valid zip archive. The wheel may be corrupted or the build failed silently."
    )


# ---------------------------------------------------------------------------
# AC-TEST-005: Wheel version matches pyproject.toml
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_wheel_version_matches_pyproject(built_wheel: pathlib.Path) -> None:
    """Verify the wheel filename encodes the version declared in pyproject.toml.

    AC-TEST-005: Test verifies the wheel version matches EXPECTED_WHEEL_VERSION.

    Given: The wheel was built from the current pyproject.toml
    When: The wheel filename is inspected
    Then: The version segment of the filename equals EXPECTED_WHEEL_VERSION
    """
    # Wheel filenames follow the pattern: {name}-{version}-{pythontag}-...whl
    filename = built_wheel.name
    parts = filename.split("-")
    assert len(parts) >= 2, (
        f"Wheel filename '{filename}' does not follow the expected "
        "'{name}-{version}-...' pattern. Cannot extract version."
    )
    actual_version = parts[1]
    assert actual_version == EXPECTED_WHEEL_VERSION, (
        f"Expected wheel version '{EXPECTED_WHEEL_VERSION}' but got '{actual_version}' "
        f"from wheel filename '{filename}'. Update pyproject.toml [project] version."
    )


# ---------------------------------------------------------------------------
# AC-TEST-002: All 25 root .py files from repo/ are in the wheel
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("filename", ROOT_PYTHON_FILES)
def test_wheel_contains_root_repo_py_file(wheel_names: set[str], filename: str) -> None:
    """Verify each of the 25 root .py files from src/kanon_cli/repo/ is in the wheel.

    AC-TEST-002: Test verifies all 25 root .py files from repo/ are in the wheel.

    Given: The wheel was built from the current project configuration
    When: The wheel contents are inspected
    Then: The file kanon_cli/repo/<filename> is present in the wheel
    """
    wheel_entry = f"{_REPO_PREFIX}{filename}"
    assert wheel_entry in wheel_names, (
        f"Expected '{wheel_entry}' to be present in the wheel but it was not found. "
        f"Check [tool.hatch.build.targets.wheel] packages in pyproject.toml includes "
        f"'src/kanon_cli/repo'. Wheel contains {len(wheel_names)} entries."
    )


@pytest.mark.unit
def test_wheel_contains_root_repo_init_py(wheel_names: set[str]) -> None:
    """Verify the repo package __init__.py is present in the wheel.

    AC-TEST-002: The repo package __init__.py must be included as part of the package.

    Given: The wheel was built from the current project configuration
    When: The wheel contents are inspected
    Then: kanon_cli/repo/__init__.py is present in the wheel
    """
    wheel_entry = f"{_REPO_PREFIX}__init__.py"
    assert wheel_entry in wheel_names, (
        f"Expected '{wheel_entry}' to be present in the wheel but it was not found. "
        f"Check [tool.hatch.build.targets.wheel] packages in pyproject.toml includes "
        f"'src/kanon_cli/repo'."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003: All 28 subcmds .py files from repo/subcmds/ are in the wheel
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("filename", SUBCMD_PYTHON_FILES)
def test_wheel_contains_subcmds_py_file(wheel_names: set[str], filename: str) -> None:
    """Verify each of the 28 subcmds .py files from src/kanon_cli/repo/subcmds/ is in the wheel.

    AC-TEST-003: Test verifies all 28 subcmds .py files from repo/subcmds/ are in the wheel.

    Given: The wheel was built from the current project configuration
    When: The wheel contents are inspected
    Then: The file kanon_cli/repo/subcmds/<filename> is present in the wheel
    """
    wheel_entry = f"{_SUBCMDS_PREFIX}{filename}"
    assert wheel_entry in wheel_names, (
        f"Expected '{wheel_entry}' to be present in the wheel but it was not found. "
        f"Check [tool.hatch.build.targets.wheel] packages in pyproject.toml includes "
        f"'src/kanon_cli/repo/subcmds'. Wheel contains {len(wheel_names)} entries."
    )


# ---------------------------------------------------------------------------
# AC-TEST-004: Non-Python runtime files are in the wheel
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("relative_path", NON_PYTHON_RUNTIME_FILES)
def test_wheel_contains_non_python_runtime_file(wheel_names: set[str], relative_path: str) -> None:
    """Verify each non-Python runtime file is present in the wheel.

    AC-TEST-004: Test verifies non-Python runtime files are in the wheel
    (repo, git_ssh, hooks/commit-msg, hooks/pre-auto-gc, requirements.json).

    Given: The wheel was built from the current project configuration
    When: The wheel contents are inspected
    Then: The file kanon_cli/repo/<relative_path> is present in the wheel
    """
    wheel_entry = f"{_REPO_PREFIX}{relative_path}"
    assert wheel_entry in wheel_names, (
        f"Expected non-Python runtime file '{wheel_entry}' to be present in the wheel "
        f"but it was not found. Check [tool.hatch.build.targets.wheel] include list "
        f"in pyproject.toml contains the appropriate pattern for '{relative_path}'."
    )
