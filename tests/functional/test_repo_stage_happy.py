"""Happy-path functional tests for 'kanon repo stage'.

Exercises the happy path of the 'repo stage' subcommand by invoking
``kanon repo stage`` as a subprocess against a real initialized and synced
repo directory created in a temporary directory. No mocking -- these tests
use the full CLI stack against actual git operations.

The 'repo stage' subcommand stages file(s) for commit using interactive git
staging (``git add --interactive``). The ``-i`` / ``--interactive`` flag is
required for any meaningful invocation: without it the command prints usage
and exits with a non-zero code. The happy path exercised in this module
supplies ``-i`` to a synced repository that has no uncommitted modifications;
in that case the command logs "no projects have uncommitted modifications" to
stderr and returns 0 without entering the interactive loop.

Deviation from AC wording: AC-TEST-001 says "with default args" exits 0. The
real default behavior (no args) calls Usage() and exits non-zero. This module
therefore uses ``-i`` (the required interactive flag) as the minimal invocation
that produces a 0 exit code. This deviation is documented here so reviewers
can verify the test asserts the actual CLI behavior rather than a
misinterpretation of the AC wording.

Covers:
- AC-TEST-001: 'kanon repo stage -i' exits 0 in a valid synced repo with no
  dirty projects (the only invocation pattern that exits 0 for this command).
- AC-TEST-002: Every positional argument of 'repo stage' has a happy-path test
  (project name and project path references are exercised via parametrize).
- AC-FUNC-001: 'kanon repo stage -i' executes successfully with documented
  default behavior (exit 0 when no uncommitted modifications are present).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from tests.functional.conftest import _run_kanon, _setup_synced_repo

# ---------------------------------------------------------------------------
# Module-level constants (no hard-coded values in test logic)
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Stage Happy Test User"
_GIT_USER_EMAIL = "repo-stage-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "stage-test-project"

# Flag name constants
_FLAG_INTERACTIVE = "-i"

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT_CODE = 0

# Phrase logged to stderr when no dirty projects exist
_NO_DIRTY_PROJECTS_MSG = "no projects have uncommitted modifications"

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"


# ---------------------------------------------------------------------------
# Private setup helper
# ---------------------------------------------------------------------------


def _setup_clean_repo(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Create bare repos, run repo init and repo sync, return (checkout_dir, repo_dir).

    Delegates to :func:`tests.functional.conftest._setup_synced_repo` so that
    all bare-repo creation, ``kanon repo init``, and ``kanon repo sync`` steps
    are handled by the canonical shared helper. The result is a clean (no dirty
    files) synced repo -- the prerequisite state for a happy-path ``repo stage``
    invocation.

    Args:
        tmp_path: pytest-provided temporary directory root.

    Returns:
        A tuple of (checkout_dir, repo_dir) after a successful init and sync.

    Raises:
        AssertionError: When kanon repo init or kanon repo sync exits non-zero.
    """
    return _setup_synced_repo(
        tmp_path,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
        manifest_filename=_MANIFEST_FILENAME,
    )


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo stage -i exits 0 in a valid repo
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStageHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo stage -i' exits 0 in a valid synced repo.

    Deviation note: AC-TEST-001 says "with default args exits 0 in a valid
    repo". The real behavior without arguments is to call Usage() and exit
    non-zero. The minimal invocation that exits 0 requires ``-i``; when no
    projects have uncommitted modifications the command logs a message to
    stderr and returns immediately with exit code 0. This class asserts that
    exact documented behavior.
    """

    def test_repo_stage_interactive_no_dirty_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage -i' must exit 0 in a synced repo with no dirty projects.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo stage -i' with no project arguments. When no project has
        uncommitted modifications the command exits 0 immediately. Verifies
        the process exits 0.
        """
        checkout_dir, repo_dir = _setup_clean_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            _FLAG_INTERACTIVE,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo stage {_FLAG_INTERACTIVE}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_stage_interactive_no_dirty_logs_no_modifications(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo stage -i' logs 'no projects have uncommitted modifications' when clean.

        When invoked against a freshly synced repository that has no dirty
        projects, the command must emit _NO_DIRTY_PROJECTS_MSG to stderr.
        This verifies the documented default behavior of the subcommand.
        """
        checkout_dir, repo_dir = _setup_clean_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            _FLAG_INTERACTIVE,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo stage {_FLAG_INTERACTIVE}' failed with exit "
            f"{result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _NO_DIRTY_PROJECTS_MSG in result.stderr, (
            f"Expected {_NO_DIRTY_PROJECTS_MSG!r} in stderr of "
            f"'kanon repo stage {_FLAG_INTERACTIVE}'.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo stage has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStagePositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for the positional arguments of 'repo stage'.

    'repo stage' accepts optional positional project references (name or path)
    after the subcommand and flag arguments. When a valid project reference is
    supplied, the command restricts its search for dirty files to that project.
    In a freshly synced repository with no dirty files the command exits 0
    regardless of which project reference is provided.

    Both reference forms (by project name and by project path) are exercised
    via @pytest.mark.parametrize.
    """

    @pytest.mark.parametrize(
        "project_ref",
        [
            _PROJECT_NAME,
            _PROJECT_PATH,
        ],
    )
    def test_repo_stage_interactive_with_project_ref_exits_zero(
        self,
        tmp_path: pathlib.Path,
        project_ref: str,
    ) -> None:
        """'kanon repo stage -i <project_ref>' exits 0 for a valid project reference.

        After a successful 'kanon repo init' and 'kanon repo sync', passes the
        project reference (name or path) as the positional argument to
        'kanon repo stage -i'. Verifies the process exits 0 in a clean repo.
        """
        checkout_dir, repo_dir = _setup_clean_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            _FLAG_INTERACTIVE,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo stage {_FLAG_INTERACTIVE} {project_ref}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "project_ref",
        [
            _PROJECT_NAME,
            _PROJECT_PATH,
        ],
    )
    def test_repo_stage_interactive_with_project_ref_logs_no_modifications(
        self,
        tmp_path: pathlib.Path,
        project_ref: str,
    ) -> None:
        """'kanon repo stage -i <project_ref>' logs no-modifications message in a clean repo.

        When a project reference is supplied and that project has no uncommitted
        modifications, the command must emit _NO_DIRTY_PROJECTS_MSG to stderr
        and exit 0. Verifies that the per-project restriction path behaves
        consistently with the all-projects path.
        """
        checkout_dir, repo_dir = _setup_clean_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            _FLAG_INTERACTIVE,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo stage {_FLAG_INTERACTIVE} {project_ref}' failed with "
            f"exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _NO_DIRTY_PROJECTS_MSG in result.stderr, (
            f"Expected {_NO_DIRTY_PROJECTS_MSG!r} in stderr of "
            f"'kanon repo stage {_FLAG_INTERACTIVE} {project_ref}'.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStageChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo stage'.

    Verifies that successful 'kanon repo stage -i' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo stage -i' once and return the CompletedProcess.

        Uses tmp_path_factory so the fixture is class-scoped: setup and CLI
        invocation execute once, and all three channel assertions share the
        same result without repeating the expensive git operations.

        Returns:
            The CompletedProcess from 'kanon repo stage -i'.

        Raises:
            AssertionError: When the prerequisite setup (init/sync) fails.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        checkout_dir, repo_dir = _setup_clean_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "stage",
            _FLAG_INTERACTIVE,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo stage {_FLAG_INTERACTIVE}' failed with "
            f"exit {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_stage_success_has_no_traceback_on_stdout(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo stage -i' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful "
            f"'kanon repo stage {_FLAG_INTERACTIVE}'.\n"
            f"  stdout: {channel_result.stdout!r}"
        )

    def test_repo_stage_success_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo stage -i' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'kanon repo stage {_FLAG_INTERACTIVE}': {line!r}\n"
                f"  stdout: {channel_result.stdout!r}"
            )

    def test_repo_stage_success_has_no_traceback_on_stderr(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo stage -i' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of successful "
            f"'kanon repo stage {_FLAG_INTERACTIVE}'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )
