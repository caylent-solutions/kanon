"""Happy-path functional tests for 'kanon repo envsubst'.

Exercises the happy path of the 'repo envsubst' subcommand by invoking
``kanon repo envsubst`` as a subprocess against a real initialized repo
directory created in a temporary directory. No mocking -- these tests use
the full CLI stack against actual git operations.

The 'repo envsubst' subcommand substitutes environment variable placeholders
of the form ``${VAR_NAME}`` in all XML manifest files found under
``.repo/manifests/**/*.xml``. On the first run, a ``.bak`` backup is created
alongside each processed manifest. Subsequent runs leave the ``.bak``
untouched. The command exits 0 and prints the matched file paths to stdout.

AC wording note: AC-TEST-002 states "every positional argument of 'repo
envsubst' has a happy-path test." The upstream 'repo envsubst' subcommand
accepts no positional arguments -- its helpUsage is ``%prog`` with no
positional tokens. To satisfy AC-TEST-002 in spirit, this file exercises
both distinct invocation forms created by the optional ``--verbose`` flag:
the default form (no flags) and the explicit ``--verbose`` form. Both forms
exit 0 and emit the manifest path to stdout; the parametrized class asserts
this for each form.

Covers:
- AC-TEST-001: 'kanon repo envsubst' with default args exits 0 in a valid repo.
- AC-TEST-002: Every invocation form of 'repo envsubst' has a happy-path test
  (default args and --verbose).
- AC-FUNC-001: 'kanon repo envsubst' executes successfully with documented
  default behavior (exit 0, manifest file path printed to stdout).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel leakage).

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import (
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- no hard-coded domain literals in test logic
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Envsubst Happy Test User"
_GIT_USER_EMAIL = "repo-envsubst-happy@example.com"
_PROJECT_PATH = "envsubst-test-project"

# CLI token for the envsubst subcommand
_CLI_TOKEN_ENVSUBST = "envsubst"

# Optional flag that produces verbose output from the embedded tool
_CLI_FLAG_VERBOSE = "--verbose"

# Expected exit code for all happy-path invocations
_EXPECTED_EXIT = 0

# Composed CLI command phrase for diagnostic messages (no inline literals)
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_CLI_TOKEN_ENVSUBST}"

# Phrase that must appear in stdout when envsubst processes a manifest file.
# The Execute() method in Envsubst always prints this prefix before the options
# dict and positional args.
_EXECUTES_PHRASE = "Executing envsubst"

# Hidden git-repo metadata directory that repo tools use
_DOT_REPO = ".repo"

# Manifest directory name within the .repo directory
_MANIFEST_DIR = "manifests"

# Manifest filename for the default manifest
_MANIFEST_FILENAME = "default.xml"

# Manifest path fragment that must appear in stdout when envsubst scans the
# .repo/manifests directory and finds the default manifest XML file.
_MANIFEST_PATH_FRAGMENT = f"{_DOT_REPO}/{_MANIFEST_DIR}/{_MANIFEST_FILENAME}"

# BAK file suffix created by envsubst to preserve the pre-substitution baseline.
_BAK_SUFFIX = ".bak"

# Traceback indicator used in channel-discipline assertions
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs
_ERROR_PREFIX = "Error:"

# Parametrize tuples for AC-TEST-002: non-default invocation forms.
# Form 1: --verbose flag (changes output_mode but exits 0 in the same way).
# Default-args coverage is provided by TestRepoEnvsubstHappyPathDefaultArgs.
_INVOCATION_FORMS = [
    pytest.param((_CLI_FLAG_VERBOSE,), id="verbose-flag"),
]


# ---------------------------------------------------------------------------
# Shared setup helper
# ---------------------------------------------------------------------------


def _setup_envsubst_repo(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Create bare repos, run repo init and repo sync, return (checkout_dir, repo_dir).

    Delegates to ``_setup_synced_repo`` from tests.functional.conftest with the
    project path and git identity specific to this test module.

    Args:
        tmp_path: pytest-provided temporary directory root.

    Returns:
        A tuple of ``(checkout_dir, repo_dir)`` after a successful init and sync.

    Raises:
        AssertionError: When ``kanon repo init`` or ``kanon repo sync`` exits
            with a non-zero code.
    """
    return _setup_synced_repo(
        tmp_path,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_path=_PROJECT_PATH,
    )


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo envsubst with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo envsubst' with default args exits 0.

    Verifies that 'kanon repo envsubst' with no additional arguments against a
    properly initialized repo directory exits 0, prints the manifest path to
    stdout, and produces a .bak backup alongside the processed manifest file.
    This is the documented default behavior.
    """

    def test_repo_envsubst_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst' with no extra args must exit 0.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo envsubst' with no additional arguments. The command must
        process the manifest XML and exit 0.
        """
        checkout_dir, repo_dir = _setup_envsubst_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'{_CLI_COMMAND_PHRASE}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_envsubst_prints_executing_phrase_to_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst' must print the execution-start phrase to stdout.

        The Execute() method always prints 'Executing envsubst' followed by the
        options dict and positional args. This verifies the documented console
        output is present on a successful run.
        """
        checkout_dir, repo_dir = _setup_envsubst_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        assert _EXECUTES_PHRASE in result.stdout, (
            f"Expected {_EXECUTES_PHRASE!r} in stdout of '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_envsubst_prints_manifest_path_to_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst' must print each matched manifest path to stdout.

        After processing, the Execute() method prints the path of each matched
        XML file. A freshly initialized repo has exactly one manifest file at
        '.repo/manifests/default.xml', which must appear in stdout.
        """
        checkout_dir, repo_dir = _setup_envsubst_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        assert _MANIFEST_PATH_FRAGMENT in result.stdout, (
            f"Expected {_MANIFEST_PATH_FRAGMENT!r} in stdout of '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_envsubst_creates_bak_backup_on_first_run(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst' must create a .bak file alongside the manifest.

        The first run of envsubst must produce a '<manifest>.bak' backup file
        in the same directory as the processed manifest, preserving the
        pre-substitution baseline for the user.
        """
        checkout_dir, repo_dir = _setup_envsubst_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        bak_path = repo_dir / _MANIFEST_DIR / f"{_MANIFEST_FILENAME}{_BAK_SUFFIX}"
        assert bak_path.exists(), (
            f"Expected .bak file at {bak_path!r} after first '{_CLI_COMMAND_PHRASE}' run.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every invocation form of 'repo envsubst' has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstInvocationForms:
    """AC-TEST-002: happy-path test for each distinct invocation form of 'repo envsubst'.

    'repo envsubst' accepts no positional arguments (helpUsage: ``%prog``).
    To satisfy AC-TEST-002 in spirit, this class parametrizes over the two
    distinct invocation forms: default (no flags) and --verbose. Both forms
    exit 0 and print the manifest path to stdout.
    """

    @pytest.mark.parametrize("extra_flags", _INVOCATION_FORMS)
    def test_repo_envsubst_invocation_form_exits_zero(
        self,
        tmp_path: pathlib.Path,
        extra_flags: tuple,
    ) -> None:
        """Each invocation form of 'kanon repo envsubst' must exit 0.

        Runs 'kanon repo envsubst' with each set of extra flags in
        _INVOCATION_FORMS. All forms must exit 0 in a properly initialized
        and synced repository.
        """
        checkout_dir, repo_dir = _setup_envsubst_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            *extra_flags,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"'{_CLI_COMMAND_PHRASE}' with flags {extra_flags!r} exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("extra_flags", _INVOCATION_FORMS)
    def test_repo_envsubst_invocation_form_prints_manifest_path(
        self,
        tmp_path: pathlib.Path,
        extra_flags: tuple,
    ) -> None:
        """Each invocation form of 'kanon repo envsubst' must print the manifest path.

        Runs 'kanon repo envsubst' with each set of extra flags in
        _INVOCATION_FORMS. All forms must include the manifest path fragment
        in stdout, confirming the manifest was processed.
        """
        checkout_dir, repo_dir = _setup_envsubst_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            *extra_flags,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' with flags {extra_flags!r} failed: {result.stderr!r}"
        )
        assert _MANIFEST_PATH_FRAGMENT in result.stdout, (
            f"Expected {_MANIFEST_PATH_FRAGMENT!r} in stdout of "
            f"'{_CLI_COMMAND_PHRASE}' with flags {extra_flags!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstHappyChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo envsubst'.

    Verifies that successful 'kanon repo envsubst' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    def test_repo_envsubst_success_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo envsubst' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        checkout_dir, repo_dir = _setup_envsubst_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of successful '{_CLI_COMMAND_PHRASE}'.\n  stdout: {result.stdout!r}"
        )

    def test_repo_envsubst_success_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo envsubst' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_envsubst_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'{_CLI_COMMAND_PHRASE}': {line!r}\n"
                f"  stdout: {result.stdout!r}"
            )

    def test_repo_envsubst_success_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo envsubst' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_envsubst_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT, f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of successful '{_CLI_COMMAND_PHRASE}'.\n  stderr: {result.stderr!r}"
        )
