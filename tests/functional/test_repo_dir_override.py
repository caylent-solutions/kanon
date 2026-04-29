"""Functional tests for KANON_REPO_DIR env-var override semantics.

Verifies the three documented precedence cases for the repo directory
resolution via real subprocess invocations against a bare git manifest
repository.

The ``--repo-dir`` flag and ``KANON_REPO_DIR`` env var both accept a PATH to
the ``.repo`` directory itself (i.e. the directory that ``repo init`` creates
or that existing repo commands require). For ``repo init``, the specified path
becomes the ``.repo`` directory; the manifest topdir is the parent of that path.

Three cases:

1. AC-FUNC-001 (flag-only): ``--repo-dir=<path>`` with no ``KANON_REPO_DIR``
   env var creates ``.repo`` at the flag path.
2. AC-FUNC-002 (env-only): ``KANON_REPO_DIR=<path>`` with no flag creates
   ``.repo`` at the env-var path.
3. AC-FUNC-003 (flag-wins): when both are supplied the flag value wins and
   the env-var path is NOT created.

Tests are decorated with @pytest.mark.functional.
"""

import os
import pathlib

import pytest

from tests.functional.conftest import (
    _create_bare_content_repo,
    _create_manifest_repo,
    _run_kanon,
)

# ---------------------------------------------------------------------------
# Module-level constants -- no hard-coded values in test logic
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Dir Override Test User"
_GIT_USER_EMAIL = "repo-dir-override@example.com"
_MANIFEST_FILENAME = "default.xml"
_CONTENT_FILE_NAME = "README.md"
_CONTENT_FILE_TEXT = "hello from repo-dir-override test"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "override-test-project"
_GIT_BRANCH = "main"

# Sentinel directory name used inside tmp_path for repo isolation
_REPOS_SUBDIR = "repos"

# kanon CLI tokens
_CLI_TOKEN_REPO = "repo"
_CLI_TOKEN_INIT = "init"
_CLI_FLAG_REPO_DIR = "--repo-dir"
_CLI_FLAG_NO_VERIFY = "--no-repo-verify"
_CLI_FLAG_URL = "-u"
_CLI_FLAG_BRANCH = "-b"
_CLI_FLAG_MANIFEST = "-m"

# Name of the .repo directory created by repo init
_REPO_DOT_DIR = ".repo"

# The KANON_REPO_DIR env-var name (must match the constant in the source)
_KANON_REPO_DIR_ENV = "KANON_REPO_DIR"


# ---------------------------------------------------------------------------
# Fixture helper -- shared bare-repo setup
# ---------------------------------------------------------------------------


def _setup_manifest_url(tmp_path: pathlib.Path) -> str:
    """Create bare content and manifest repos and return the manifest URL.

    Args:
        tmp_path: pytest-provided temporary directory.

    Returns:
        A ``file://`` URL pointing at the bare manifest repository.
    """
    repos_dir = tmp_path / _REPOS_SUBDIR
    repos_dir.mkdir()

    bare_content = _create_bare_content_repo(
        repos_dir,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_NAME,
        content_file_name=_CONTENT_FILE_NAME,
        content_file_text=_CONTENT_FILE_TEXT,
    )
    fetch_base = f"file://{bare_content.parent}"
    manifest_bare = _create_manifest_repo(
        repos_dir,
        fetch_base,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
        manifest_filename=_MANIFEST_FILENAME,
        branch=_GIT_BRANCH,
    )
    return f"file://{manifest_bare}"


def _run_init(
    manifest_url: str,
    repo_dir: pathlib.Path,
    checkout_dir: pathlib.Path,
    extra_env: "dict | None" = None,
    full_env: "dict | None" = None,
) -> "object":
    """Invoke ``kanon repo --repo-dir=<repo_dir> init ...`` as a subprocess.

    Passes ``--repo-dir`` as an explicit CLI flag pointing at ``repo_dir``.

    Args:
        manifest_url: The ``file://`` URL of the bare manifest repository.
        repo_dir: Path that will become the ``.repo`` directory.
        checkout_dir: Working directory for the subprocess.
        extra_env: Additional env vars merged on top of the current environment.
        full_env: Full replacement environment dict (mutually exclusive with
            ``extra_env``).

    Returns:
        The ``subprocess.CompletedProcess`` result.
    """
    return _run_kanon(
        _CLI_TOKEN_REPO,
        _CLI_FLAG_REPO_DIR,
        str(repo_dir),
        _CLI_TOKEN_INIT,
        _CLI_FLAG_NO_VERIFY,
        _CLI_FLAG_URL,
        manifest_url,
        _CLI_FLAG_BRANCH,
        _GIT_BRANCH,
        _CLI_FLAG_MANIFEST,
        _MANIFEST_FILENAME,
        cwd=checkout_dir,
        extra_env=extra_env,
        env=full_env,
    )


def _run_init_no_flag(
    manifest_url: str,
    checkout_dir: pathlib.Path,
    extra_env: "dict | None" = None,
) -> "object":
    """Invoke ``kanon repo init ...`` WITHOUT ``--repo-dir`` as a subprocess.

    The repo directory is resolved solely from ``KANON_REPO_DIR`` (or the
    compiled-in default when the env var is absent).

    Args:
        manifest_url: The ``file://`` URL of the bare manifest repository.
        checkout_dir: Working directory for the subprocess.
        extra_env: Additional env vars merged on top of the current environment.

    Returns:
        The ``subprocess.CompletedProcess`` result.
    """
    return _run_kanon(
        _CLI_TOKEN_REPO,
        _CLI_TOKEN_INIT,
        _CLI_FLAG_NO_VERIFY,
        _CLI_FLAG_URL,
        manifest_url,
        _CLI_FLAG_BRANCH,
        _GIT_BRANCH,
        _CLI_FLAG_MANIFEST,
        _MANIFEST_FILENAME,
        cwd=checkout_dir,
        extra_env=extra_env,
    )


# ---------------------------------------------------------------------------
# AC-FUNC-001: flag-only
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDirFlagOnly:
    """``kanon repo --repo-dir=<path> init`` with no ``KANON_REPO_DIR`` env var."""

    def test_flag_only_creates_repo_at_flag_path(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001: ``.repo`` is created at the ``--repo-dir`` flag path.

        Invokes ``kanon repo --repo-dir=<flag_repo_dir> init ...`` in an
        environment that does NOT contain ``KANON_REPO_DIR``. Asserts that
        ``flag_repo_dir`` exists as a directory (the ``.repo`` directory is
        created there by repo init).
        """
        manifest_url = _setup_manifest_url(tmp_path)

        checkout_dir = tmp_path / "flag-only-checkout"
        checkout_dir.mkdir()
        flag_repo_dir = checkout_dir / _REPO_DOT_DIR

        clean_env = {k: v for k, v in os.environ.items() if k != _KANON_REPO_DIR_ENV}

        result = _run_init(
            manifest_url=manifest_url,
            repo_dir=flag_repo_dir,
            checkout_dir=checkout_dir,
            full_env=clean_env,
        )

        assert result.returncode == 0, (
            f"kanon repo init exited {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert flag_repo_dir.is_dir(), (
            f"Expected {flag_repo_dir} to exist after "
            f"'kanon repo --repo-dir={flag_repo_dir} init'."
            f" stdout: {result.stdout!r}  stderr: {result.stderr!r}"
        )

    def test_flag_only_creates_repo_at_custom_flag_path(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001: a non-default flag path is used when no env var is set.

        Uses a custom ``.repo`` path that is NOT cwd/``.repo`` to confirm that
        the flag value is passed through to the underlying repo tool.
        """
        manifest_url = _setup_manifest_url(tmp_path)

        checkout_dir = tmp_path / "flag-only-custom-checkout"
        checkout_dir.mkdir()
        custom_parent = tmp_path / "custom-parent"
        custom_parent.mkdir()
        flag_repo_dir = custom_parent / _REPO_DOT_DIR

        clean_env = {k: v for k, v in os.environ.items() if k != _KANON_REPO_DIR_ENV}

        result = _run_init(
            manifest_url=manifest_url,
            repo_dir=flag_repo_dir,
            checkout_dir=custom_parent,
            full_env=clean_env,
        )

        assert result.returncode == 0, (
            f"kanon repo init exited {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert flag_repo_dir.is_dir(), (
            f"Expected {flag_repo_dir} to exist after custom --repo-dir init."
            f" stdout: {result.stdout!r}  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-002: env-only
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDirEnvOnly:
    """``KANON_REPO_DIR=<path> kanon repo init`` with no ``--repo-dir`` flag."""

    def test_env_only_creates_repo_at_env_path(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-002: ``.repo`` is created at the ``KANON_REPO_DIR`` env-var path.

        Invokes ``kanon repo init ...`` without ``--repo-dir``, but with
        ``KANON_REPO_DIR`` set in the subprocess environment. Asserts that
        the ``.repo`` directory is created at the env-var path.
        """
        manifest_url = _setup_manifest_url(tmp_path)

        checkout_dir = tmp_path / "env-only-checkout"
        checkout_dir.mkdir()
        env_repo_dir = checkout_dir / _REPO_DOT_DIR

        result = _run_init_no_flag(
            manifest_url=manifest_url,
            checkout_dir=checkout_dir,
            extra_env={_KANON_REPO_DIR_ENV: str(env_repo_dir)},
        )

        assert result.returncode == 0, (
            f"kanon repo init exited {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert env_repo_dir.is_dir(), (
            f"Expected {env_repo_dir} to exist after "
            f"'KANON_REPO_DIR={env_repo_dir} kanon repo init'."
            f" stdout: {result.stdout!r}  stderr: {result.stderr!r}"
        )

    def test_env_only_custom_path_is_used(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-002: a non-default env-var path is honoured when no flag is set."""
        manifest_url = _setup_manifest_url(tmp_path)

        custom_parent = tmp_path / "env-custom-parent"
        custom_parent.mkdir()
        env_repo_dir = custom_parent / _REPO_DOT_DIR

        result = _run_init_no_flag(
            manifest_url=manifest_url,
            checkout_dir=custom_parent,
            extra_env={_KANON_REPO_DIR_ENV: str(env_repo_dir)},
        )

        assert result.returncode == 0, (
            f"kanon repo init exited {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert env_repo_dir.is_dir(), (
            f"Expected {env_repo_dir} to exist for env-only custom-path test."
            f" stdout: {result.stdout!r}  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-003: flag wins over env
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDirFlagWins:
    """``--repo-dir`` flag wins over ``KANON_REPO_DIR`` when both are present."""

    def test_flag_wins_creates_repo_at_flag_path_not_env_path(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-003: ``.repo`` is at the flag path; env-var path is NOT created.

        Invokes ``kanon repo --repo-dir=<flag_path> init ...`` with
        ``KANON_REPO_DIR=<env_path>`` set. Asserts that the flag path is used
        and the env-var path does NOT exist.

        The env-var path and flag path must be different directories so the
        assertion is meaningful.
        """
        manifest_url = _setup_manifest_url(tmp_path)

        flag_parent = tmp_path / "flag-wins-flag-parent"
        flag_parent.mkdir()
        flag_repo_dir = flag_parent / _REPO_DOT_DIR

        env_parent = tmp_path / "flag-wins-env-parent"
        env_parent.mkdir()
        env_repo_dir = env_parent / _REPO_DOT_DIR

        result = _run_init(
            manifest_url=manifest_url,
            repo_dir=flag_repo_dir,
            checkout_dir=flag_parent,
            extra_env={_KANON_REPO_DIR_ENV: str(env_repo_dir)},
        )

        assert result.returncode == 0, (
            f"kanon repo init exited {result.returncode}.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

        assert flag_repo_dir.is_dir(), (
            f"Expected {flag_repo_dir} to exist when --repo-dir was supplied."
            f" stdout: {result.stdout!r}  stderr: {result.stderr!r}"
        )

        assert not env_repo_dir.exists(), (
            f"Did NOT expect {env_repo_dir} to exist; flag should have overridden env var."
        )
