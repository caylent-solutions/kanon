"""Functional tests for kanon bootstrap --catalog-source and KANON_CATALOG_SOURCE precedence.

Covers:
- AC-TEST-001: KANON_CATALOG_SOURCE env var supplies catalog source when --catalog-source omitted
- AC-TEST-002: --catalog-source overrides KANON_CATALOG_SOURCE when both set
- AC-TEST-003: Neither set uses the default (bundled) catalog
- AC-FUNC-001: CLI flag has higher precedence than env var; env var has higher precedence than default
- AC-CHANNEL-001: stdout vs stderr discipline is verified (no cross-channel leakage)
"""

import os
import pathlib
import subprocess
import sys

import pytest


def _run_kanon(
    *args: str,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Invoke kanon_cli in a subprocess and return the completed process.

    Args:
        args: CLI arguments passed after 'python -m kanon_cli'.
        cwd: Working directory for the subprocess. Defaults to None (inherits caller's cwd).
        env: Environment variables for the subprocess. Defaults to None (inherits caller's env).

    Returns:
        CompletedProcess with returncode, stdout, and stderr captured as text.
    """
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=env,
    )


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit.

    Args:
        args: Git subcommand and arguments (without the 'git' prefix).
        cwd: Working directory for the git command.

    Raises:
        RuntimeError: When the git command exits with a non-zero code.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _create_local_catalog_repo(base: pathlib.Path, package_name: str) -> pathlib.Path:
    """Create a minimal local git repo containing a catalog with one package.

    The repo has the structure:
        <base>/
          catalog/
            <package_name>/
              <package_name>-readme.md

    A single commit is created and tagged as 'v1.0.0' on branch 'main'.

    Args:
        base: Directory under which the repo is created.
        package_name: Name of the catalog package to include.

    Returns:
        Absolute path to the bare-like repo root (not the catalog/ subdir).
    """
    repo_dir = base / "catalog-repo"
    repo_dir.mkdir(parents=True)
    _git(["init", "-b", "main"], cwd=repo_dir)
    _git(["config", "user.email", "test@example.com"], cwd=repo_dir)
    _git(["config", "user.name", "Test"], cwd=repo_dir)

    catalog_pkg_dir = repo_dir / "catalog" / package_name
    catalog_pkg_dir.mkdir(parents=True)
    readme = catalog_pkg_dir / f"{package_name}-readme.md"
    readme.write_text(f"# {package_name}\n", encoding="utf-8")

    _git(["add", "."], cwd=repo_dir)
    _git(["commit", "-m", "Initial catalog commit"], cwd=repo_dir)
    _git(["tag", "-a", "v1.0.0", "-m", "Version 1.0.0"], cwd=repo_dir)

    return repo_dir


def _base_env() -> dict[str, str]:
    """Return a copy of the current environment with KANON_CATALOG_SOURCE removed.

    Returns:
        Environment dict with KANON_CATALOG_SOURCE unset.
    """
    env = os.environ.copy()
    env.pop("KANON_CATALOG_SOURCE", None)
    return env


@pytest.mark.functional
class TestCatalogSourceEnvVar:
    """AC-TEST-001: KANON_CATALOG_SOURCE env var supplies catalog source when --catalog-source omitted."""

    def test_env_var_catalog_used_for_list_when_flag_absent(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap list must use catalog from KANON_CATALOG_SOURCE when --catalog-source is absent.

        A local git repo with a uniquely named package is created. When KANON_CATALOG_SOURCE
        points to that repo and no --catalog-source flag is given, the package name must appear
        in 'kanon bootstrap list' stdout.
        """
        catalog_repo = _create_local_catalog_repo(tmp_path / "env-repo", "env-only-package")
        env = _base_env()
        env["KANON_CATALOG_SOURCE"] = f"file://{catalog_repo}@v1.0.0"

        result = _run_kanon("bootstrap", "list", env=env)

        assert result.returncode == 0, (
            f"Expected exit 0 when KANON_CATALOG_SOURCE is set, got {result.returncode}.\nstderr: {result.stderr!r}"
        )
        assert "env-only-package" in result.stdout, (
            f"Expected 'env-only-package' from KANON_CATALOG_SOURCE catalog in stdout.\nstdout: {result.stdout!r}"
        )

    def test_env_var_catalog_not_used_when_env_var_absent(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap list must NOT show a uniquely named package from an unset env var catalog.

        The bundled catalog does not contain 'env-only-package', so this name must be absent
        when KANON_CATALOG_SOURCE is not set.
        """
        env = _base_env()
        result = _run_kanon("bootstrap", "list", env=env)

        assert result.returncode == 0
        assert "env-only-package" not in result.stdout, (
            f"Did not expect 'env-only-package' in stdout when KANON_CATALOG_SOURCE is unset.\n"
            f"stdout: {result.stdout!r}"
        )

    def test_env_var_catalog_no_stderr_leakage(self, tmp_path: pathlib.Path) -> None:
        """kanon bootstrap list with KANON_CATALOG_SOURCE set must not write to stderr (AC-CHANNEL-001)."""
        catalog_repo = _create_local_catalog_repo(tmp_path / "env-repo-ch", "env-channel-package")
        env = _base_env()
        env["KANON_CATALOG_SOURCE"] = f"file://{catalog_repo}@v1.0.0"

        result = _run_kanon("bootstrap", "list", env=env)

        assert result.returncode == 0
        assert result.stderr == "", (
            f"Expected empty stderr when KANON_CATALOG_SOURCE is set and list succeeds.\nstderr: {result.stderr!r}"
        )


@pytest.mark.functional
class TestCatalogSourceFlagOverridesEnvVar:
    """AC-TEST-002: --catalog-source overrides KANON_CATALOG_SOURCE when both are set (AC-FUNC-001)."""

    def test_flag_package_visible_env_var_package_absent_when_both_set(self, tmp_path: pathlib.Path) -> None:
        """When both --catalog-source and KANON_CATALOG_SOURCE are set, the flag catalog wins.

        Two separate local catalogs are created with distinct package names. The flag
        catalog's package must appear in stdout; the env var catalog's package must be absent.
        """
        flag_catalog_repo = _create_local_catalog_repo(tmp_path / "flag-repo", "flag-catalog-package")
        env_catalog_repo = _create_local_catalog_repo(tmp_path / "env-repo", "env-catalog-package")

        env = _base_env()
        env["KANON_CATALOG_SOURCE"] = f"file://{env_catalog_repo}@v1.0.0"

        result = _run_kanon(
            "bootstrap",
            "list",
            "--catalog-source",
            f"file://{flag_catalog_repo}@v1.0.0",
            env=env,
        )

        assert result.returncode == 0, (
            f"Expected exit 0 when --catalog-source is given, got {result.returncode}.\nstderr: {result.stderr!r}"
        )
        assert "flag-catalog-package" in result.stdout, (
            f"Expected 'flag-catalog-package' from --catalog-source flag in stdout.\nstdout: {result.stdout!r}"
        )
        assert "env-catalog-package" not in result.stdout, (
            f"Did not expect 'env-catalog-package' from KANON_CATALOG_SOURCE in stdout "
            f"when --catalog-source flag is also provided.\n"
            f"stdout: {result.stdout!r}"
        )

    def test_flag_overrides_env_var_no_stderr_leakage(self, tmp_path: pathlib.Path) -> None:
        """--catalog-source overriding KANON_CATALOG_SOURCE must not produce stderr (AC-CHANNEL-001)."""
        flag_catalog_repo = _create_local_catalog_repo(tmp_path / "flag-repo-ch", "flag-ch-package")
        env_catalog_repo = _create_local_catalog_repo(tmp_path / "env-repo-ch", "env-ch-package")

        env = _base_env()
        env["KANON_CATALOG_SOURCE"] = f"file://{env_catalog_repo}@v1.0.0"

        result = _run_kanon(
            "bootstrap",
            "list",
            "--catalog-source",
            f"file://{flag_catalog_repo}@v1.0.0",
            env=env,
        )

        assert result.returncode == 0
        assert result.stderr == "", (
            f"Expected empty stderr when --catalog-source overrides KANON_CATALOG_SOURCE.\nstderr: {result.stderr!r}"
        )


@pytest.mark.functional
class TestCatalogSourceDefaultBundled:
    """AC-TEST-003: Neither --catalog-source nor KANON_CATALOG_SOURCE set uses the bundled catalog."""

    def test_bundled_catalog_contains_kanon_package(self) -> None:
        """kanon bootstrap list without any catalog source must list the bundled 'kanon' package.

        The bundled catalog ships with a 'kanon' package. When no catalog source is
        configured, that package must appear in 'kanon bootstrap list' stdout.
        """
        env = _base_env()
        result = _run_kanon("bootstrap", "list", env=env)

        assert result.returncode == 0, (
            f"Expected exit 0 with bundled catalog, got {result.returncode}.\nstderr: {result.stderr!r}"
        )
        assert "kanon" in result.stdout, (
            f"Expected 'kanon' package from bundled catalog in stdout.\nstdout: {result.stdout!r}"
        )

    def test_bundled_catalog_lists_available_packages_header(self) -> None:
        """kanon bootstrap list with bundled catalog must print 'Available packages' header."""
        env = _base_env()
        result = _run_kanon("bootstrap", "list", env=env)

        assert result.returncode == 0
        assert "Available packages" in result.stdout, (
            f"Expected 'Available packages' header in stdout.\nstdout: {result.stdout!r}"
        )

    def test_bundled_catalog_produces_no_stderr(self) -> None:
        """kanon bootstrap list with bundled catalog must not write to stderr (AC-CHANNEL-001)."""
        env = _base_env()
        result = _run_kanon("bootstrap", "list", env=env)

        assert result.returncode == 0
        assert result.stderr == "", f"Expected empty stderr with bundled catalog.\nstderr: {result.stderr!r}"
