"""Wheel layout tests: verify no bundled catalog is shipped in the wheel.

AC-TEST-001: builds the wheel and asserts:
  - No archive member starts with 'kanon_cli/catalog/' (AC-FUNC-002)
  - Expected core files ARE present (AC-FUNC-003)
  - '.gitignore' contains the 'src/kanon_cli/catalog/' pattern (AC-FUNC-006)
AC-TEST-003: asserts CI guard bash script exits 1 when catalog dir exists, 0 when absent.
"""

import pathlib
import shutil
import subprocess
import zipfile

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).parents[1]
"""Root of the kanon repository (1 level up from tests/)."""

_CATALOG_PREFIX = "kanon_cli/catalog/"

_EXPECTED_CORE_FILES = [
    "kanon_cli/__init__.py",
    "kanon_cli/commands/search.py",
    "kanon_cli/core/catalog.py",
    "kanon_cli/constants.py",
]

_GITIGNORE_CATALOG_PATTERN = "src/kanon_cli/catalog/"

# Minimal guard script matching the CI workflow step logic
_GUARD_SCRIPT = """\
set -euo pipefail
if [ -d "src/kanon_cli/catalog" ]; then
  echo "ERROR: src/kanon_cli/catalog/ must remain removed (see backlog/E6-F2-S1-T1)" >&2
  exit 1
fi
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_wheel(out_dir: pathlib.Path) -> pathlib.Path:
    """Build the kanon-cli wheel into out_dir via ``uv build --wheel``.

    Args:
        out_dir: Destination directory for the built wheel.

    Returns:
        Path to the .whl file produced by the build.

    Raises:
        RuntimeError: If 'uv' is not found, build exits non-zero, or no .whl is produced.
    """
    uv_executable = shutil.which("uv")
    if uv_executable is None:
        raise RuntimeError(
            "The 'uv' executable is required to build the kanon-cli wheel but was not found on PATH. "
            "Install uv (https://docs.astral.sh/uv/) and ensure it is reachable."
        )
    result = subprocess.run(
        [uv_executable, "build", "--wheel", "--out-dir", str(out_dir)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"uv build --wheel failed with exit code {result.returncode}.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    wheels = list(out_dir.glob("*.whl"))
    if not wheels:
        raise RuntimeError(f"Wheel build succeeded but no .whl file found in {out_dir}. stdout:\n{result.stdout}")
    return wheels[0]


def _wheel_names(wheel_path: pathlib.Path) -> list[str]:
    """Return all archive member names from a wheel zip file.

    Args:
        wheel_path: Path to the .whl file.

    Returns:
        List of all entry names in the archive.

    Raises:
        RuntimeError: If the wheel cannot be opened as a zip archive.
    """
    try:
        with zipfile.ZipFile(wheel_path) as zf:
            return zf.namelist()
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Cannot open wheel {wheel_path} as a zip archive: {exc}") from exc


# ---------------------------------------------------------------------------
# AC-TEST-001: Wheel layout -- no catalog, core files present, gitignore updated
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_wheel_contains_no_catalog_entries(tmp_path: pathlib.Path) -> None:
    """Built wheel must not contain any member under kanon_cli/catalog/.

    Builds the wheel and inspects the archive. Asserts no member name
    starts with 'kanon_cli/catalog/'. This verifies AC-FUNC-002.

    AC-TEST-001 (partial)
    """
    wheel_path = _build_wheel(tmp_path)
    names = _wheel_names(wheel_path)

    catalog_entries = [n for n in names if n.startswith(_CATALOG_PREFIX)]
    assert not catalog_entries, (
        f"Wheel must not contain any members under '{_CATALOG_PREFIX}', "
        f"but found: {catalog_entries}. "
        f"Remove src/kanon_cli/catalog/ from the repo and verify no hatchling "
        f"glob re-includes it."
    )


@pytest.mark.integration
def test_wheel_contains_expected_core_files(tmp_path: pathlib.Path) -> None:
    """Built wheel must contain the expected core kanon_cli files.

    Verifies that removing catalog/ does not result in a catastrophically
    empty wheel. Asserts all expected core files are present. This
    verifies AC-FUNC-003.

    AC-TEST-001 (partial)
    """
    wheel_path = _build_wheel(tmp_path)
    names = _wheel_names(wheel_path)
    names_set = set(names)

    missing = [f for f in _EXPECTED_CORE_FILES if f not in names_set]
    assert not missing, (
        f"The following expected core files are missing from the wheel: {missing}. "
        f"A missing core file indicates a broken build configuration. "
        f"Check [tool.hatch.build.targets.wheel] packages in pyproject.toml."
    )


@pytest.mark.integration
def test_gitignore_contains_catalog_pattern() -> None:
    """The .gitignore file must contain the src/kanon_cli/catalog/ pattern.

    Reads .gitignore directly and asserts the guard pattern is present.
    This verifies AC-FUNC-006.

    AC-TEST-001 (partial)
    """
    gitignore_path = REPO_ROOT / ".gitignore"
    assert gitignore_path.is_file(), f"Expected .gitignore at {gitignore_path} but it does not exist."
    content = gitignore_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]
    assert _GITIGNORE_CATALOG_PATTERN in lines, (
        f"Expected pattern '{_GITIGNORE_CATALOG_PATTERN}' to be present in .gitignore "
        f"but it was not found. Add this line to prevent accidental re-addition of the "
        f"bundled catalog directory."
    )


# ---------------------------------------------------------------------------
# AC-TEST-003: CI guard script -- exits 1 when catalog exists, 0 when absent
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ci_guard_exits_one_when_catalog_exists(tmp_path: pathlib.Path) -> None:
    """CI guard script exits 1 when src/kanon_cli/catalog/ directory exists.

    Creates a fixture directory tree containing src/kanon_cli/catalog/ and
    runs the guard script via subprocess. Asserts exit code is 1 and the
    error message appears on stderr.

    AC-TEST-003 (partial)
    """
    catalog_dir = tmp_path / "src" / "kanon_cli" / "catalog"
    catalog_dir.mkdir(parents=True)

    result = subprocess.run(
        ["bash", "-c", _GUARD_SCRIPT],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, (
        f"Expected guard script to exit 1 when src/kanon_cli/catalog/ exists, "
        f"but got exit code {result.returncode}. "
        f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )
    assert "ERROR" in result.stderr, (
        f"Expected guard script to write an ERROR message to stderr when catalog "
        f"dir exists, but stderr was: {result.stderr!r}"
    )


@pytest.mark.unit
def test_ci_guard_exits_zero_when_catalog_absent(tmp_path: pathlib.Path) -> None:
    """CI guard script exits 0 when src/kanon_cli/catalog/ directory is absent.

    Runs the guard script against an empty directory. Asserts exit code 0.

    AC-TEST-003 (partial)
    """
    result = subprocess.run(
        ["bash", "-c", _GUARD_SCRIPT],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"Expected guard script to exit 0 when src/kanon_cli/catalog/ is absent, "
        f"but got exit code {result.returncode}. "
        f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )
