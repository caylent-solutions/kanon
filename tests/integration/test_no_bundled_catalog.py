"""Integration tests: assert bundled catalog is absent at runtime and in installed wheel.

AC-TEST-002: asserts runtime absence of the catalog subpath via pathlib and
  importlib.resources, plus a negative-control case asserting a known-present
  subpath IS present (so the absence assertion can fail meaningfully).
AC-CYCLE-001: end-to-end wheel build + install + import cycle asserts absence.
"""

import importlib
import pathlib
import shutil
import subprocess
import sys
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).parents[2]
"""Root of the kanon repository (2 levels up from tests/integration/)."""

_KNOWN_PRESENT_SUBPATH = "commands"
"""A subpath that must exist under kanon_cli/ so the absence test has meaningful contrast."""


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


def _create_venv(venv_dir: pathlib.Path) -> pathlib.Path:
    """Create a virtual environment and return the Python interpreter path.

    Args:
        venv_dir: Directory to create the venv in.

    Returns:
        Path to the Python interpreter inside the venv.

    Raises:
        RuntimeError: If venv creation fails or the interpreter is not found.
    """
    result = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        cwd=str(venv_dir.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"venv creation failed with exit code {result.returncode}.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    python = venv_dir / "bin" / "python"
    if not python.exists():
        raise RuntimeError(
            f"Expected Python interpreter at {python} after venv creation but not found. "
            f"Contents of {venv_dir}: {sorted(str(p) for p in venv_dir.iterdir())!r}"
        )
    return python


def _install_wheel(python: pathlib.Path, wheel_path: pathlib.Path) -> None:
    """Install the wheel into the venv identified by python.

    Args:
        python: Path to the Python interpreter of the target venv.
        wheel_path: Path to the .whl file to install.

    Raises:
        RuntimeError: If pip install fails.
    """
    result = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", str(wheel_path)],
        cwd=str(python.parent.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pip install failed with exit code {result.returncode}.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Runtime absence tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_catalog_subpath_absent_at_runtime() -> None:
    """Catalog subpath must not exist under kanon_cli/ in the running environment.

    Imports kanon_cli and walks the package directory via pathlib.
    Asserts the 'catalog' subdirectory does not exist.
    This verifies AC-FUNC-004.

    AC-TEST-002 (partial)
    """
    import kanon_cli

    package_dir = pathlib.Path(kanon_cli.__file__).parent
    catalog_path = package_dir / "catalog"
    assert not catalog_path.exists(), (
        f"Expected '{catalog_path}' to be absent at runtime (bundled catalog removed), "
        f"but it exists. Remove src/kanon_cli/catalog/ from the repository."
    )


@pytest.mark.integration
def test_catalog_subpath_absent_via_importlib_resources() -> None:
    """Catalog subpath must not be accessible via importlib.resources.files.

    Uses the modern importlib.resources API to check whether the 'catalog'
    path exists under the kanon_cli package at runtime.
    This verifies AC-FUNC-004.

    AC-TEST-002 (partial)
    """
    import kanon_cli

    pkg_files = importlib.resources.files(kanon_cli)
    catalog_traversable = pkg_files / "catalog"
    assert not catalog_traversable.is_dir(), (
        "Expected 'catalog' subpath to be absent via importlib.resources.files('kanon_cli') / "
        "'catalog', but it reports as a directory. Remove src/kanon_cli/catalog/ from the repo."
    )


@pytest.mark.integration
def test_known_present_subpath_exists_at_runtime() -> None:
    """Negative control: a known-present subpath must exist under kanon_cli/ at runtime.

    Asserts that 'kanon_cli/commands/' exists. If this test fails, the
    catalog-absent assertion is meaningless because the package itself is broken.
    This verifies AC-TEST-002's negative-control requirement.

    AC-TEST-002 (partial)
    """
    import kanon_cli

    package_dir = pathlib.Path(kanon_cli.__file__).parent
    known_path = package_dir / _KNOWN_PRESENT_SUBPATH
    assert known_path.is_dir(), (
        f"Expected '{known_path}' to exist as a directory (negative-control check), "
        f"but it was not found. The package installation may be broken."
    )


# ---------------------------------------------------------------------------
# AC-CYCLE-001: End-to-end wheel build + install + import + absence check
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_wheel_install_catalog_absent_end_to_end() -> None:
    """Build the wheel, install it in an isolated venv, assert catalog is absent.

    Full end-to-end cycle:
      1. Build the wheel from the post-deletion source tree via uv.
      2. Install the wheel into a fresh isolated venv.
      3. Run a subprocess Python assertion that kanon_cli.__file__'s parent
         has no 'catalog' subdirectory.

    This verifies AC-CYCLE-001.
    """
    with tempfile.TemporaryDirectory() as tmp_root:
        tmp_path = pathlib.Path(tmp_root)
        wheel_dir = tmp_path / "wheel"
        wheel_dir.mkdir()
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()

        wheel_path = _build_wheel(wheel_dir)
        python = _create_venv(venv_dir)
        _install_wheel(python, wheel_path)

        check_script = (
            "import kanon_cli, pathlib; "
            "p = pathlib.Path(kanon_cli.__file__).parent / 'catalog'; "
            "assert not p.exists(), "
            "f'Expected catalog absent but found: {p}'"
        )
        result = subprocess.run(
            [str(python), "-c", check_script],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"Expected catalog to be absent from installed wheel but assertion failed.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
