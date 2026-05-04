"""Happy-path functional tests for 'kanon repo diff'.

Exercises the happy path of the 'repo diff' subcommand by invoking
``kanon repo diff`` as a subprocess against a real initialized and synced
repo directory created in a temporary directory. No mocking -- these tests
use the full CLI stack against actual git operations.

The 'repo diff' subcommand shows uncommitted changes across all projects. On
a freshly synced repository with no uncommitted changes, the command exits 0
and produces no diff output. When a project path filter is supplied as a
positional argument, the diff is restricted to that project.

Note on AC-TEST-001 wording: the AC states "'kanon repo diff' with default
args exits 0". 'repo diff' accepts zero positional arguments (all projects
are checked by default), so the simplest invocation form uses no extra
arguments at all. All tests below use a freshly synced repository with no
uncommitted changes so exit code 0 is deterministic.

Covers:
- AC-TEST-001: 'kanon repo diff' with default args exits 0 in a valid repo.
- AC-TEST-002: Every positional argument of 'repo diff' has a happy-path test.
  Positional arguments: [<project>...] (optional project name or path filter).
- AC-FUNC-001: 'kanon repo diff' executes successfully with documented default
  behavior.
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import (
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in test logic)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Diff Happy Test User"
_GIT_USER_EMAIL = "repo-diff-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "diff-happy-test-project"

# CLI token constants -- every token that appears in subprocess argv
_CMD_REPO = "repo"
_FLAG_REPO_DIR = "--repo-dir"
_SUBCMD_DIFF = "diff"
_FLAG_ABSOLUTE = "-u"

# Expected exit code for all happy-path invocations.
_EXPECTED_EXIT = 0

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_diff_args(repo_dir: pathlib.Path, *extra: str) -> tuple:
    """Return the argv tuple for a 'kanon repo diff' invocation.

    Builds the canonical argument sequence:
        repo --repo-dir <repo_dir> diff <extra...>

    Args:
        repo_dir: Path to the .repo directory.
        *extra: Additional arguments appended after the subcommand token.

    Returns:
        A tuple of string arguments suitable for passing to _run_kanon.
    """
    return (_CMD_REPO, _FLAG_REPO_DIR, str(repo_dir), _SUBCMD_DIFF) + extra


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo diff with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo diff' with default args exits 0.

    Verifies that invoking 'kanon repo diff' with no additional arguments
    against a properly initialized and synced repo directory exits 0. A
    freshly synced repository has no uncommitted changes so the diff is
    empty and the command exits with success.
    """

    def test_repo_diff_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff' with no extra args must exit 0.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo diff' with no additional arguments. The freshly synced
        repository has no uncommitted changes so the command must exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            *_build_diff_args(repo_dir),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo diff' exited {result.returncode}, expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_diff_on_fresh_repo_produces_no_diff_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff' on a clean repo must produce no diff output.

        A freshly synced repository has no uncommitted changes in any project.
        The diff subcommand must exit 0 and produce no diff lines on stdout.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            *_build_diff_args(repo_dir),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo diff' failed with exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout == "", (
            f"Expected empty stdout from 'kanon repo diff' on a clean repo.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_diff_with_absolute_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff -u' with the absolute flag exits 0 on a clean repo.

        The -u / --absolute flag causes 'repo diff' to emit file paths relative
        to the repository root rather than the project root. On a clean repo
        with no uncommitted changes, the command must still exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            *_build_diff_args(repo_dir, _FLAG_ABSOLUTE),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo diff {_FLAG_ABSOLUTE}' exited {result.returncode},"
            f" expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo diff has a happy-path test
#
# Positional arguments for 'repo diff':
#   [<project>...] -- optional project names or paths that restrict the diff scope
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for every positional argument of 'repo diff'.

    'repo diff' accepts one kind of positional argument:
    [<project>...] -- optional project names or paths that restrict the diff
    to a subset of projects. When supplied with a valid project name in a clean
    repository, the command must exit 0.
    """

    def test_repo_diff_with_project_name_positional_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff <project>' with a project name positional arg exits 0.

        After a successful 'kanon repo init' and 'kanon repo sync', passes the
        project name from the manifest as a positional argument to restrict the
        diff scope. The project has no uncommitted changes, so the command must
        exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            *_build_diff_args(repo_dir, _PROJECT_NAME),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo diff {_PROJECT_NAME}' exited {result.returncode},"
            f" expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_diff_with_project_name_produces_no_diff_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff <project>' on a clean project produces no diff output.

        When a project name is supplied as a positional filter and the project
        has no uncommitted changes, the command must exit 0 and produce no diff
        output on stdout.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            *_build_diff_args(repo_dir, _PROJECT_NAME),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo diff {_PROJECT_NAME}' failed: {result.stderr!r}"
        )
        assert result.stdout == "", (
            f"Expected empty stdout from 'kanon repo diff {_PROJECT_NAME}' on a clean project.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_diff_with_project_path_positional_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diff <path>' with the project path positional arg exits 0.

        Verifies that passing a project by its path (as an alternative to the
        project name) also exits 0, exercising the path-based resolution branch
        inside the 'diff' subcommand's GetProjects call.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            *_build_diff_args(repo_dir, _PROJECT_PATH),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo diff {_PROJECT_PATH}' (path form) exited {result.returncode},"
            f" expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "project_arg",
        [_PROJECT_NAME, _PROJECT_PATH],
        ids=["by-name", "by-path"],
    )
    def test_repo_diff_project_filter_variants_exit_zero(
        self,
        tmp_path: pathlib.Path,
        project_arg: str,
    ) -> None:
        """Positional project filter (name or path) exits 0 on a clean synced repo.

        Parametrized across the two forms of the project positional argument:
        the manifest project name and the project path. Both must exit 0 when
        the project has no uncommitted changes.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            *_build_diff_args(repo_dir, project_arg),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo diff {project_arg}' exited {result.returncode},"
            f" expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffHappyChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo diff'.

    Verifies that successful 'kanon repo diff' invocations do not write Python
    tracebacks or 'Error:' prefixed messages to stdout, and that stderr does
    not contain Python exception tracebacks on a successful run.
    """

    def test_repo_diff_success_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo diff' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            *_build_diff_args(repo_dir),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, f"Prerequisite 'kanon repo diff' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo diff'.\n  stdout: {result.stdout!r}"
        )

    def test_repo_diff_success_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo diff' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            *_build_diff_args(repo_dir),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, f"Prerequisite 'kanon repo diff' failed: {result.stderr!r}"
        assert _ERROR_PREFIX not in result.stdout, (
            f"'{_ERROR_PREFIX}' found in stdout of successful 'kanon repo diff'.\n  stdout: {result.stdout!r}"
        )

    def test_repo_diff_success_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo diff' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            *_build_diff_args(repo_dir),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, f"Prerequisite 'kanon repo diff' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo diff'.\n  stderr: {result.stderr!r}"
        )

    def test_repo_diff_success_has_empty_stderr_on_clean_repo(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo diff' on a clean repo must produce empty stderr.

        When there are no uncommitted changes in any project, the diff
        subcommand produces no output and must emit nothing to stderr.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )

        result = _run_kanon(
            *_build_diff_args(repo_dir),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, f"Prerequisite 'kanon repo diff' failed: {result.stderr!r}"
        assert result.stderr == "", (
            f"Expected empty stderr for successful 'kanon repo diff' on a clean repo; got: {result.stderr!r}"
        )
