"""Integration tests for kanon install deprecation warnings visible in subprocess context.

Verifies that the legacy REPO_URL / REPO_REV deprecation message is written to
stderr when 'kanon install' is invoked as a subprocess with no -W flag, so that
end users and CI logs see the migration notice regardless of Python's active
warning filter.

AC-TEST-001: REPO_URL set => deprecation message on stderr
AC-TEST-002: REPO_REV set => deprecation message on stderr naming REPO_REV
AC-TEST-003: Both set => single combined deprecation message on stderr
AC-TEST-004: Neither set => no deprecation text on stderr
AC-TEST-005: Unit-level warnings.warn() call is preserved (tested via unit suite)
"""

import os
import pathlib
import subprocess
import sys

import pytest


_TEST_REPO_URL = "https://example.com/repo.git"
_TEST_KANON_SOURCE_URL = "https://example.com/manifest.git"
_TEST_GITBASE_URL = "https://example.com/"
_TEST_REPO_REV = "v2.0.0"

_VALID_KANONENV_CONTENT = (
    f"GITBASE={_TEST_GITBASE_URL}\n"
    "KANON_MARKETPLACE_INSTALL=false\n"
    f"KANON_SOURCE_test_URL={_TEST_KANON_SOURCE_URL}\n"
    "KANON_SOURCE_test_REVISION=main\n"
    "KANON_SOURCE_test_PATH=repo-specs/test.xml\n"
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"


def _build_env(extra: "dict[str, str]") -> "dict[str, str]":
    """Build a subprocess environment inheriting the current process env plus overrides.

    Ensures PYTHONPATH includes the source tree so the subprocess resolves
    kanon_cli from the current source rather than any installed version.

    Args:
        extra: Additional environment variables merged on top of os.environ.

    Returns:
        A new dict suitable for passing as subprocess env.
    """
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_str = str(_SRC_DIR)
    path_entries = [src_str] + [p for p in existing_pythonpath.split(os.pathsep) if p and p != src_str]
    env["PYTHONPATH"] = os.pathsep.join(path_entries)
    env.update(extra)
    return env


def _run_install_subprocess(
    kanonenv_path: pathlib.Path,
    extra_env: "dict[str, str]",
) -> subprocess.CompletedProcess:
    """Run 'kanon install <kanonenv_path>' in a subprocess with no -W flag.

    The install will fail when it tries to clone the remote git repo, but the
    deprecation warning must be emitted to stderr before any network call.

    Args:
        kanonenv_path: Absolute path to the .kanon file to pass to install.
        extra_env: Additional environment variables (e.g. REPO_URL, REPO_REV).

    Returns:
        CompletedProcess with captured stdout and stderr.
    """
    env = _build_env(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", "install", str(kanonenv_path)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.mark.integration
class TestInstallDeprecationWarningSubprocess:
    """Verify legacy env-var deprecation notices reach stderr in subprocess context.

    Python's default warning filter suppresses DeprecationWarning when running
    as a subprocess (no -W all flag).  The install command must therefore write
    the same message directly to sys.stderr so end users and CI logs see the
    migration notice unconditionally.
    """

    @pytest.fixture()
    def kanonenv(self, tmp_path: pathlib.Path) -> pathlib.Path:
        """Write a minimal valid .kanon file and return its absolute path."""
        kanonenv_path = tmp_path / ".kanon"
        kanonenv_path.write_text(_VALID_KANONENV_CONTENT)
        return kanonenv_path

    @pytest.mark.parametrize(
        "env_var,env_value,other_var",
        [
            ("REPO_URL", _TEST_REPO_URL, "REPO_REV"),
            ("REPO_REV", _TEST_REPO_REV, "REPO_URL"),
        ],
    )
    def test_single_legacy_var_writes_deprecation_to_stderr(
        self,
        kanonenv: pathlib.Path,
        env_var: str,
        env_value: str,
        other_var: str,
    ) -> None:
        """AC-TEST-001/AC-TEST-002: Setting a single legacy env var writes its name to stderr without -W flag."""
        result = _run_install_subprocess(
            kanonenv,
            extra_env={env_var: env_value, other_var: ""},
        )

        assert env_var in result.stderr, (
            f"Expected {env_var!r} in stderr when {env_var} is set (no -W flag), got stderr={result.stderr!r}"
        )
        assert "--catalog-source" in result.stderr, (
            f"Expected '--catalog-source' migration hint in stderr, got stderr={result.stderr!r}"
        )

    def test_both_set_writes_single_combined_deprecation_to_stderr(self, kanonenv: pathlib.Path) -> None:
        """AC-TEST-003: Both REPO_URL and REPO_REV set => single combined message on stderr."""
        result = _run_install_subprocess(
            kanonenv,
            extra_env={
                "REPO_URL": _TEST_REPO_URL,
                "REPO_REV": _TEST_REPO_REV,
            },
        )

        assert "REPO_URL" in result.stderr, (
            f"Expected 'REPO_URL' in combined stderr message, got stderr={result.stderr!r}"
        )
        assert "REPO_REV" in result.stderr, (
            f"Expected 'REPO_REV' in combined stderr message, got stderr={result.stderr!r}"
        )

        # The message must be a single combined notice (not two separate lines each naming only one var).
        # Count how many lines contain the deprecation keyword to verify a single emission.
        deprecation_lines = [
            line for line in result.stderr.splitlines() if "deprecated" in line.lower() or "catalog-source" in line
        ]
        assert len(deprecation_lines) == 1, (
            f"Expected exactly one combined deprecation line, got {len(deprecation_lines)}: {deprecation_lines!r}"
        )

    def test_neither_set_no_deprecation_on_stderr(self, kanonenv: pathlib.Path) -> None:
        """AC-TEST-004: Neither REPO_URL nor REPO_REV set => no deprecation text on stderr."""
        # Explicitly remove the legacy vars from the environment.
        env = _build_env({})
        env.pop("REPO_URL", None)
        env.pop("REPO_REV", None)

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install", str(kanonenv)],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

        deprecation_lines = [
            line for line in result.stderr.splitlines() if "deprecated" in line.lower() or "catalog-source" in line
        ]
        assert len(deprecation_lines) == 0, (
            f"Expected no deprecation output when neither REPO_URL nor REPO_REV is set, got: {deprecation_lines!r}"
        )
