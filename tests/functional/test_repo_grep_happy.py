"""Happy-path functional tests for 'kanon repo grep'.

Exercises the happy path of the 'repo grep' subcommand by invoking
``kanon repo grep`` as a subprocess against a real initialized and synced
repo directory created in a temporary directory. No mocking -- these tests
use the full CLI stack against actual git operations.

The 'repo grep' subcommand searches for a pattern across all project files.
When the pattern matches at least one line in any project file, the command
exits 0 and prints the matching lines to stdout. This file verifies that
contract.

Note on AC-TEST-001 wording: the AC states "'kanon repo grep' with default
args exits 0". 'repo grep' requires at minimum a pattern argument (positional
or via -e); invoking it with zero arguments exits 1 with a usage error. The
phrase "default args" is interpreted here as the simplest invocation form --
a bare positional pattern -- which is the documented default usage. All tests
below use that form and assert exit code 0 when the pattern matches content in
a synced repository.

Covers:
- AC-TEST-001: 'kanon repo grep' with default args (positional pattern) exits 0 in a
  valid repo when the pattern matches content.
- AC-TEST-002: Every positional argument of 'repo grep' has a happy-path test.
  Positional arguments: PATTERN (first arg) and [<project>...] (optional filter).
- AC-FUNC-001: 'kanon repo grep' executes successfully with documented default behavior.
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

_GIT_USER_NAME = "Repo Grep Happy Test User"
_GIT_USER_EMAIL = "repo-grep-happy@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "grep-happy-test-project"

# CLI token constants -- every token that appears in subprocess argv
_CMD_REPO = "repo"
_FLAG_REPO_DIR = "--repo-dir"
_SUBCMD_GREP = "grep"
_FLAG_E = "-e"

# Pattern that matches the default content file written by _setup_synced_repo.
# The conftest helper writes "hello from shared conftest helper" to README.md.
_MATCH_PATTERN = "hello"

# Filename written into each project by _setup_synced_repo.
_CONTENT_FILENAME = "README.md"

# Expected exit code for all happy-path invocations where the pattern matches.
_EXPECTED_EXIT = 0

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_grep_args(repo_dir: pathlib.Path, *extra: str) -> tuple[str, ...]:
    """Return the argv tuple for a 'kanon repo grep' invocation.

    Builds the canonical argument sequence:
        repo --repo-dir <repo_dir> grep <extra...>

    Args:
        repo_dir: Path to the .repo directory.
        *extra: Additional arguments appended after the subcommand token.

    Returns:
        A tuple of string arguments suitable for passing to _run_kanon.
    """
    return (_CMD_REPO, _FLAG_REPO_DIR, str(repo_dir), _SUBCMD_GREP) + extra


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo grep with default positional pattern exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo grep' with a positional pattern exits 0.

    Verifies that invoking 'kanon repo grep <pattern>' -- the simplest,
    default-arg form of the command -- against a properly initialized and
    synced repo directory exits 0 when the pattern matches content. The
    matching lines are printed to stdout.
    """

    def test_repo_grep_positional_pattern_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep <pattern>' exits 0 when pattern matches project content.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo grep hello' with the positional pattern form. The content
        file contains the pattern, so the command must exit 0.
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
            *_build_grep_args(repo_dir, _MATCH_PATTERN),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo grep {_MATCH_PATTERN}' exited {result.returncode},"
            f" expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_grep_positional_pattern_produces_matching_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep <pattern>' prints lines that contain the pattern.

        After a successful init and sync, the content file contains the pattern.
        The stdout must include the content filename followed by the matching
        line text, confirming grep output was produced.
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
            *_build_grep_args(repo_dir, _MATCH_PATTERN),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo grep {_MATCH_PATTERN}' failed: {result.stderr!r}"
        )
        assert _CONTENT_FILENAME in result.stdout, (
            f"Expected {_CONTENT_FILENAME!r} in grep stdout (file:line output).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _MATCH_PATTERN in result.stdout, (
            f"Expected {_MATCH_PATTERN!r} in grep stdout (matching content).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_grep_with_e_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep -e <pattern>' exits 0 when pattern matches content.

        The -e flag is the explicit-pattern form of the same default behavior.
        Invoking 'kanon repo grep -e hello' must exit 0 and produce matching
        output identical to the positional form.
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
            *_build_grep_args(repo_dir, _FLAG_E, _MATCH_PATTERN),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo grep {_FLAG_E} {_MATCH_PATTERN}' exited {result.returncode},"
            f" expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo grep has a happy-path test
#
# Positional arguments for 'repo grep':
#   1. PATTERN -- the search pattern (first positional when -e is not used)
#   2. [<project>...] -- optional project name or path filter(s)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for every positional argument of 'repo grep'.

    'repo grep' accepts two kinds of positional arguments:
    1. PATTERN -- the search string (consumed as the first positional when -e
       is absent). Covered by the parametrized test below.
    2. [<project>...] -- optional project names or paths that restrict the
       search scope. Covered by the project-name and project-path tests below.
    """

    @pytest.mark.parametrize(
        ("pattern", "expected_in_stdout"),
        [
            (_MATCH_PATTERN, _CONTENT_FILENAME),
            ("shared", _CONTENT_FILENAME),
            ("conftest", _CONTENT_FILENAME),
        ],
        ids=["pattern-hello", "pattern-shared", "pattern-conftest"],
    )
    def test_repo_grep_positional_pattern_variants(
        self,
        tmp_path: pathlib.Path,
        pattern: str,
        expected_in_stdout: str,
    ) -> None:
        """Positional PATTERN argument exits 0 and produces output for matching content.

        Parametrized across three distinct search terms that all appear in the
        content file created by _setup_synced_repo. Each invocation exercises
        a genuinely different subprocess invocation with a different PATTERN
        positional argument.
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
            *_build_grep_args(repo_dir, pattern),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo grep {pattern}' exited {result.returncode},"
            f" expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert expected_in_stdout in result.stdout, (
            f"Expected {expected_in_stdout!r} in stdout for pattern {pattern!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_grep_with_project_name_positional_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep <pattern> <project>' with a project name filter exits 0.

        After a successful init and sync, passes the project name from the
        manifest as a positional argument to restrict the grep scope. The
        project's content file contains the pattern, so the command exits 0.
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
            *_build_grep_args(repo_dir, _MATCH_PATTERN, _PROJECT_NAME),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo grep {_MATCH_PATTERN} {_PROJECT_NAME}' exited {result.returncode},"
            f" expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_grep_with_project_name_produces_matching_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep <pattern> <project>' produces matching output for valid project.

        When a valid project name is supplied as a positional filter, the grep
        output must include the content filename and the matching line text.
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
            *_build_grep_args(repo_dir, _MATCH_PATTERN, _PROJECT_NAME),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo grep {_MATCH_PATTERN} {_PROJECT_NAME}' failed: {result.stderr!r}"
        )
        assert _CONTENT_FILENAME in result.stdout, (
            f"Expected {_CONTENT_FILENAME!r} in grep stdout when project filter used.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_grep_with_e_flag_and_project_name_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep -e <pattern> <project>' exits 0 for a matching synced project.

        Combines the -e flag with a positional project name argument. The
        project's content file contains the pattern, so the command exits 0.
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
            *_build_grep_args(repo_dir, _FLAG_E, _MATCH_PATTERN, _PROJECT_NAME),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'kanon repo grep {_FLAG_E} {_MATCH_PATTERN} {_PROJECT_NAME}'"
            f" exited {result.returncode}, expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepHappyChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo grep'.

    Verifies that successful 'kanon repo grep' invocations do not write Python
    tracebacks or 'Error:' prefixed messages to stdout, and that stderr does
    not contain Python exception tracebacks on a successful run. Also verifies
    that matching output appears on stdout (not stderr).
    """

    def test_repo_grep_success_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo grep' must not emit Python tracebacks to stdout.

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
            *_build_grep_args(repo_dir, _MATCH_PATTERN),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo grep {_MATCH_PATTERN}' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of successful 'kanon repo grep'.\n  stdout: {result.stdout!r}"
        )

    def test_repo_grep_success_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo grep' must not emit 'Error:' prefix to stdout.

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
            *_build_grep_args(repo_dir, _MATCH_PATTERN),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo grep {_MATCH_PATTERN}' failed: {result.stderr!r}"
        )
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful 'kanon repo grep':"
                f" {line!r}\n  stdout: {result.stdout!r}"
            )

    def test_repo_grep_success_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo grep' must not emit Python tracebacks to stderr.

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
            *_build_grep_args(repo_dir, _MATCH_PATTERN),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo grep {_MATCH_PATTERN}' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of successful 'kanon repo grep'.\n  stderr: {result.stderr!r}"
        )

    def test_repo_grep_match_output_goes_to_stdout_not_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo grep' writes matching lines to stdout, not stderr.

        The content filename must appear in stdout. Stderr must be empty on
        a successful match to ensure no cross-channel leakage of match output.
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
            *_build_grep_args(repo_dir, _MATCH_PATTERN),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite 'kanon repo grep {_MATCH_PATTERN}' failed: {result.stderr!r}"
        )
        assert _CONTENT_FILENAME in result.stdout, (
            f"Expected match output ({_CONTENT_FILENAME!r}) on stdout, not found.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stderr == "", f"Expected empty stderr for a successful grep match; got: {result.stderr!r}"
