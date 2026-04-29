"""Functional tests for 'kanon repo selfupdate' in embedded mode.

Exercises the behavior of the 'repo selfupdate' subcommand by invoking
``kanon repo selfupdate`` as a subprocess against a real initialized repo
directory created in a temporary directory. No mocking -- these tests use
the full CLI stack against actual git operations.

The 'repo selfupdate' subcommand is disabled in embedded mode. When invoked
through the kanon CLI (EMBEDDED mode), the command detects that selfupdate
is unavailable, emits ``SELFUPDATE_EMBEDDED_MESSAGE`` to stderr, and exits 1.
Updated per E2-F2-S2-T2: exit code is 1 (not 0) to signal selfupdate is
disabled. stdout is empty on all invocations.

AC wording note: AC-TEST-002 states "every positional argument of 'repo
selfupdate' has a happy-path test." The upstream 'repo selfupdate'
subcommand accepts no positional arguments -- its helpUsage is ``%%prog``
with no positional tokens. To satisfy AC-TEST-002 in spirit, this file
exercises both of the two distinct invocation forms created by the
optional ``--no-repo-verify`` flag: the default form (repo_verify=True)
and the explicit ``--no-repo-verify`` form (repo_verify=False). Both
forms exit 1 and emit the embedded message to stderr; the parametrized
class asserts this for each form.

Covers:
- AC-TEST-001: 'kanon repo selfupdate' with default args exits 1 in a
  valid repo (disabled in embedded mode).
- AC-TEST-002: Every invocation form of 'repo selfupdate' has a
  test (default args and --no-repo-verify).
- AC-FUNC-001: 'kanon repo selfupdate' exits 1 with documented behavior
  (embedded message on stderr, non-zero exit code).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel
  leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib
import subprocess

import pytest

from kanon_cli.constants import SELFUPDATE_EMBEDDED_MESSAGE
from tests.functional.conftest import (
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- no hard-coded domain literals in test logic
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Selfupdate Happy Test User"
_GIT_USER_EMAIL = "repo-selfupdate-happy@example.com"
_PROJECT_PATH = "selfupdate-test-project"

# CLI token for the selfupdate subcommand
_CLI_TOKEN_SELFUPDATE = "selfupdate"

# Option flag for skipping repo source code verification
_CLI_FLAG_NO_REPO_VERIFY = "--no-repo-verify"

# Expected exit code for all embedded-mode invocations.
# Updated per E2-F2-S2-T2: selfupdate exits 1 in embedded mode.
_EXPECTED_EXIT = 1

# Composed CLI command phrase for diagnostic messages (no inline literals)
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_CLI_TOKEN_SELFUPDATE}"

# Expected stdout for a successful selfupdate invocation (empty in embedded mode)
_EXPECTED_STDOUT = ""

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Parametrize tuples for AC-TEST-002: two distinct invocation forms
_INVOCATION_FORMS = [
    pytest.param((), id="default-args"),
    pytest.param((_CLI_FLAG_NO_REPO_VERIFY,), id="no-repo-verify"),
]

# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-TEST-002: happy-path tests for all invocation forms
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateInvocationFormHappyPath:
    """AC-TEST-001 / AC-TEST-002: tests for distinct invocation forms of 'repo selfupdate'.

    'repo selfupdate' accepts no positional arguments (helpUsage is '%%prog').
    To satisfy AC-TEST-001 and AC-TEST-002, this class exercises the two
    distinct invocation forms created by the optional ``--no-repo-verify``
    flag: the default form (repo_verify=True implicitly) and the explicit
    ``--no-repo-verify`` form. Both forms enter embedded-mode detection and
    exit 1 (updated per E2-F2-S2-T2) with empty stdout.

    The [default-args] parametrize variant covers AC-TEST-001: 'kanon repo
    selfupdate' with default args exits 1 in embedded mode (selfupdate disabled).
    """

    @pytest.mark.parametrize("extra_args", _INVOCATION_FORMS)
    def test_repo_selfupdate_invocation_form_exits_zero(
        self,
        tmp_path: pathlib.Path,
        extra_args: tuple,
    ) -> None:
        """'kanon repo selfupdate [--no-repo-verify]' exits 1 for each invocation form.

        Parametrized over the two forms: (default-args) no extra flags, and
        (no-repo-verify) with the ``--no-repo-verify`` flag. Both forms must
        exit 1 in a valid initialized repo because embedded-mode detection
        short-circuits before any flag-dependent logic is reached.
        Updated per E2-F2-S2-T2: selfupdate exits 1 in embedded mode.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SELFUPDATE,
            *extra_args,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'{_CLI_COMMAND_PHRASE} {extra_args}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("extra_args", _INVOCATION_FORMS)
    def test_repo_selfupdate_invocation_form_emits_embedded_message(
        self,
        tmp_path: pathlib.Path,
        extra_args: tuple,
    ) -> None:
        """'kanon repo selfupdate [--no-repo-verify]' emits the embedded message on stderr.

        Both invocation forms must emit SELFUPDATE_EMBEDDED_MESSAGE to stderr
        because embedded-mode detection fires before any flag-dependent path.
        """
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SELFUPDATE,
            *extra_args,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE} {extra_args}' failed: {result.stderr!r}"
        )
        assert SELFUPDATE_EMBEDDED_MESSAGE in result.stderr, (
            f"Expected {SELFUPDATE_EMBEDDED_MESSAGE!r} in stderr of '{_CLI_COMMAND_PHRASE} {extra_args}'.\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSelfupdateChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo selfupdate'.

    Verifies that 'kanon repo selfupdate' invocations in embedded mode do not write
    Python tracebacks or content to stdout, and that stderr contains the embedded
    message but no traceback. Updated per E2-F2-S2-T2: exit code is 1.

    stdout discipline: stdout is exactly the empty string (all output routes to stderr
    in embedded mode).
    stderr discipline: stderr contains the embedded message but no traceback.

    All channel assertions share a single class-scoped fixture invocation to avoid
    redundant git setup.
    """

    @pytest.fixture(scope="class")
    def channel_result(self, tmp_path_factory: pytest.TempPathFactory) -> subprocess.CompletedProcess:
        """Run 'kanon repo selfupdate' once and return the CompletedProcess.

        Uses tmp_path_factory for a class-scoped fixture: setup and CLI
        invocation execute once, and all channel assertions share the result
        without repeating the expensive git operations.

        Returns:
            The CompletedProcess from 'kanon repo selfupdate' with default args.

        Raises:
            AssertionError: When the prerequisite setup (init/sync) fails.
        """
        tmp_path = tmp_path_factory.mktemp("channel_discipline")
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_path=_PROJECT_PATH,
        )

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SELFUPDATE,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_selfupdate_success_stdout_is_empty(self, channel_result: subprocess.CompletedProcess) -> None:
        """'kanon repo selfupdate' in embedded mode must produce empty stdout.

        In embedded mode all output routes to stderr. stdout must equal the
        empty string -- any non-empty stdout indicates output leaked to the
        wrong channel.
        """
        assert channel_result.stdout == _EXPECTED_STDOUT, (
            f"Expected empty stdout from '{_CLI_COMMAND_PHRASE}'.\n  stdout: {channel_result.stdout!r}"
        )

    def test_repo_selfupdate_success_has_no_traceback_on_stderr(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """'kanon repo selfupdate' in embedded mode must not emit Python tracebacks to stderr.

        stderr must not contain 'Traceback (most recent call last)'.
        The embedded message (and kanon error suffix) are the expected content
        on stderr; a traceback would indicate an unhandled exception escaped.
        """
        assert _TRACEBACK_MARKER not in channel_result.stderr, (
            f"Python traceback found in stderr of '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stderr: {channel_result.stderr!r}"
        )
