"""Operator-path subprocess test: kanon install with no .kanon file.

Verifies that when `kanon install` is run in a directory that has no .kanon
file (and none in any parent directory reachable from the temp directory),
the CLI:

1. Exits with a non-zero exit code (fail-fast on missing config).
2. Emits remediation text containing `kanon add` (the golden path).
3. Does NOT contain the deprecated `kanon bootstrap` command in its output.

AC-1 (spec AC-4, FR-2): non-zero exit + `kanon add` in combined output.
AC-2 (spec AC-5, FR-2): `bootstrap` absent from combined output.
AC-3 (spec AC-13, FR-2): genuine RED confirmed by running against un-patched code.
"""

import os
import pathlib
import subprocess
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"


def _build_env() -> dict[str, str]:
    """Build a subprocess environment with the source tree on PYTHONPATH.

    Returns:
        A new dict inheriting the current process env, with PYTHONPATH set
        so the subprocess resolves kanon_cli from the current source tree.
    """
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_str = str(_SRC_DIR)
    path_entries = [src_str] + [p for p in existing_pythonpath.split(os.pathsep) if p and p != src_str]
    env["PYTHONPATH"] = os.pathsep.join(path_entries)
    return env


@pytest.mark.integration
class TestInstallNoKanonRemediation:
    """Verify the no-.kanon error directs operators to `kanon add`, not `kanon bootstrap`."""

    def test_install_without_kanon_exits_nonzero(self, tmp_path: pathlib.Path) -> None:
        """Running kanon install in an empty directory must exit non-zero (AC-1)."""
        empty_dir = tmp_path / "project"
        empty_dir.mkdir()
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(empty_dir),
            env=_build_env(),
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0, (
            f"Expected non-zero exit when no .kanon is present; got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert combined, "Expected error output when no .kanon is present; got empty combined output."

    def test_install_without_kanon_suggests_kanon_add(self, tmp_path: pathlib.Path) -> None:
        """Error output must contain 'kanon add' as the golden-path remediation (AC-1)."""
        empty_dir = tmp_path / "project"
        empty_dir.mkdir()
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(empty_dir),
            env=_build_env(),
        )
        combined = result.stdout + result.stderr
        assert "kanon add" in combined, (
            f"Expected 'kanon add' in combined output when no .kanon is present.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_install_without_kanon_does_not_mention_bootstrap(self, tmp_path: pathlib.Path) -> None:
        """Error output must NOT contain 'bootstrap' (deprecated command) (AC-2)."""
        empty_dir = tmp_path / "project"
        empty_dir.mkdir()
        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(empty_dir),
            env=_build_env(),
        )
        combined = result.stdout + result.stderr
        assert "bootstrap" not in combined, (
            f"Expected 'bootstrap' to be absent from combined output when no .kanon is present.\n"
            f"Combined output contains 'bootstrap'.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
