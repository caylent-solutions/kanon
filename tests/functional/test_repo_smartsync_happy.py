"""Happy-path functional tests for 'kanon repo smartsync'.

Exercises the happy path of the 'repo smartsync' subcommand by invoking
``kanon repo smartsync`` as a subprocess against a real initialized repo
directory created in a temporary directory. No mocking of the kanon CLI
stack -- these tests use the full CLI against actual git operations.

The 'repo smartsync' subcommand is a shortcut for 'repo sync -s'. It fetches
the approved manifest from a manifest server via XMLRPC, writes it as
``smart_sync_override.xml`` inside the manifest project worktree, and then
performs a regular sync against that manifest. This test file spins up a
real Python ``xmlrpc.server.SimpleXMLRPCServer`` in a background thread to
service the ``GetApprovedManifest`` call and supply a valid manifest XML string.

Setup pattern (using conftest helpers):
  1. Call ``_setup_synced_repo`` to create bare repos, run ``repo init`` and
     ``repo sync``, and return a fully synced checkout directory.
  2. Patch ``.repo/manifests/default.xml`` in place to add a
     ``<manifest-server url="http://127.0.0.1:{port}"/>`` element so that
     the smartsync XMLRPC lookup can succeed.
  3. Run ``kanon repo smartsync`` against the patched checkout.

On success, 'kanon repo smartsync' prints
"repo sync has finished successfully." to stdout and exits 0, identical to
'repo sync'. It also prints "Using manifest server ..." to stdout before
the sync begins.

AC wording note: AC-TEST-001 states "'kanon repo smartsync' with default
args exits 0 in a valid repo." Because smartsync requires a manifest-server
element in the manifest and a live XMLRPC endpoint, this file patches the
manifests/default.xml file (written by repo init) to insert the
<manifest-server> element and starts a background Python XMLRPC server that
returns a valid approved manifest string.

AC-TEST-002 states "every positional argument of 'repo smartsync' has a
happy-path test." The positional arguments accepted by smartsync (inherited
from sync) are optional ``[<project>...]`` references. Both project-name and
project-path forms are exercised via @pytest.mark.parametrize with ids.

Covers:
- AC-TEST-001: 'kanon repo smartsync' with default args exits 0 in a valid
  repo.
- AC-TEST-002: Every positional argument of 'repo smartsync' has a happy-path
  test.
- AC-FUNC-001: 'kanon repo smartsync' executes successfully with documented
  default behavior (exit 0, success phrase on stdout).
- AC-CHANNEL-001: stdout vs stderr channel discipline (no cross-channel
  leakage). Stderr is non-empty on a successful smartsync run because the
  embedded repo tool logs a ".netrc credentials lookup" notice to stderr.

Tests are decorated with @pytest.mark.functional.
"""

import os
import pathlib
import subprocess

import pytest

from tests.functional.conftest import (
    _CLI_COMMAND_PHRASE,
    _CLI_FLAG_JOBS_ONE,
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _CLI_TOKEN_SMARTSYNC,
    _ERROR_PREFIX,
    _PROJECT_NAME,
    _PROJECT_PATH,
    _SUCCESS_PHRASE,
    _TRACEBACK_MARKER,
    _build_smartsync_state,
    _run_kanon,
)

# ---------------------------------------------------------------------------
# Module-level constants -- no hard-coded domain literals in test logic
# ---------------------------------------------------------------------------

# Phrase expected in stdout at the start of a successful smartsync when a
# manifest server is configured.
_MANIFEST_SERVER_PHRASE = "Using manifest server"

# Sentinel for detecting empty output strings.
_EMPTY_OUTPUT = ""

# Expected exit code for all happy-path invocations.
_EXPECTED_EXIT_CODE = 0


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo smartsync with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSmartSyncHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo smartsync' with default args.

    Verifies that 'kanon repo smartsync' with no project-name arguments
    against a properly initialized and synced repo directory exits 0 and
    emits the documented completion message on stdout. A class-scoped XMLRPC
    server thread services the GetApprovedManifest call and returns a valid
    manifest XML string. The conftest _setup_synced_repo helper is used for
    the initial init + sync setup; the manifest is then patched in place to
    add the <manifest-server> element before smartsync is invoked.
    """

    @pytest.fixture(scope="class")
    def smartsync_default_state(
        self,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> "dict":
        """Set up XMLRPC server, synced checkout, and patch the manifest.

        Uses _setup_synced_repo to create the bare repos, run kanon repo init
        and kanon repo sync. Then:
          - Reads the fetch-base URL from the synced manifest.
          - Starts a SimpleXMLRPCServer in a daemon thread.
          - Patches .repo/manifests/default.xml to include <manifest-server>.

        Yields a dict with: checkout_dir, repo_dir.

        After the tests complete, shuts down the XMLRPC server.
        """
        tmp_path = tmp_path_factory.mktemp("smartsync_default")
        checkout_dir, repo_dir, rpc_server = _build_smartsync_state(tmp_path)

        yield {"checkout_dir": checkout_dir, "repo_dir": repo_dir}

        rpc_server.shutdown()

    def test_repo_smartsync_default_exits_zero(self, smartsync_default_state: "dict") -> None:
        """'kanon repo smartsync' with no extra args must exit 0 in a valid repo.

        After a successful 'kanon repo init' and 'kanon repo sync' (via
        _setup_synced_repo) and manifest patch, runs 'kanon repo smartsync'
        with no positional arguments. The XMLRPC server returns a valid
        approved manifest so the command must exit 0.
        """
        checkout_dir = smartsync_default_state["checkout_dir"]
        repo_dir = smartsync_default_state["repo_dir"]

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_smartsync_default_emits_success_phrase(self, smartsync_default_state: "dict") -> None:
        """'kanon repo smartsync' must emit the documented completion message.

        On success, 'repo smartsync' prints "repo sync has finished
        successfully." to stdout. Verifies this phrase appears after a
        smartsync of an already initialized and synced repository.
        """
        checkout_dir = smartsync_default_state["checkout_dir"]
        repo_dir = smartsync_default_state["repo_dir"]

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed with exit "
            f"{result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _SUCCESS_PHRASE in result.stdout, (
            f"Expected {_SUCCESS_PHRASE!r} in stdout of '{_CLI_COMMAND_PHRASE}' "
            f"with default args.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_smartsync_default_emits_manifest_server_phrase(self, smartsync_default_state: "dict") -> None:
        """'kanon repo smartsync' must announce the manifest server on stdout.

        On success, 'repo smartsync' prints "Using manifest server ..." to
        stdout before the sync begins. Verifies this phrase appears to confirm
        the manifest server lookup path was exercised.
        """
        checkout_dir = smartsync_default_state["checkout_dir"]
        repo_dir = smartsync_default_state["repo_dir"]

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        )
        assert _MANIFEST_SERVER_PHRASE in result.stdout, (
            f"Expected {_MANIFEST_SERVER_PHRASE!r} in stdout of "
            f"'{_CLI_COMMAND_PHRASE}' to confirm manifest server path.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every positional argument of repo smartsync has a happy-path
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSmartSyncPositionalArgHappyPath:
    """AC-TEST-002: happy-path tests for the positional arguments of 'repo smartsync'.

    'repo smartsync' accepts optional ``[<project>...]`` positional arguments
    that restrict the sync to specific projects. Projects can be specified by
    name or by their relative path in the checkout. Both forms are exercised
    via @pytest.mark.parametrize with display ids. A class-scoped XMLRPC
    server and repo setup are shared across all parametrize invocations.
    """

    @pytest.fixture(scope="class")
    def smartsync_positional_state(
        self,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> "dict":
        """Set up XMLRPC server, synced checkout, and patch the manifest.

        Uses _setup_synced_repo for the initial init + sync. Then patches the
        manifest and starts the XMLRPC server before yielding state.

        Yields a dict with: checkout_dir, repo_dir.
        """
        tmp_path = tmp_path_factory.mktemp("smartsync_positional")
        checkout_dir, repo_dir, rpc_server = _build_smartsync_state(tmp_path)

        yield {"checkout_dir": checkout_dir, "repo_dir": repo_dir}

        rpc_server.shutdown()

    @pytest.mark.parametrize(
        "project_ref",
        [
            _PROJECT_NAME,
            _PROJECT_PATH,
        ],
        ids=["by-project-name", "by-project-path"],
    )
    def test_repo_smartsync_with_project_ref_emits_success_phrase(
        self,
        smartsync_positional_state: "dict",
        project_ref: str,
    ) -> None:
        """'kanon repo smartsync <project_ref>' emits the success phrase on stdout.

        After a successful init and first sync, re-syncing with a positional
        project reference must produce "repo sync has finished successfully."
        on stdout, confirming the sync completed normally.
        """
        checkout_dir = smartsync_positional_state["checkout_dir"]
        repo_dir = smartsync_positional_state["repo_dir"]

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            project_ref,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE} {project_ref}' failed: {result.stderr!r}"
        )
        assert _SUCCESS_PHRASE in result.stdout, (
            f"Expected {_SUCCESS_PHRASE!r} in stdout of "
            f"'{_CLI_COMMAND_PHRASE} {project_ref}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoSmartSyncChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo smartsync'.

    Verifies that successful 'kanon repo smartsync' invocations do not emit
    Python tracebacks to stdout or stderr, and do not write 'Error:' prefixed
    messages to stdout. The unique orthogonal channel property verified here
    is that stderr is non-empty: on a successful smartsync the embedded repo
    tool logs a credentials-lookup notice (e.g. "No credentials found for
    127.0.0.1 in .netrc") to stderr, so stderr must not be empty.

    All channel assertions share a single class-scoped fixture invocation to
    avoid redundant git setup.
    """

    @pytest.fixture(scope="class")
    def channel_result(
        self,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> subprocess.CompletedProcess:
        """Run 'kanon repo smartsync' once and return the CompletedProcess.

        Uses tmp_path_factory for a class-scoped fixture: setup and CLI
        invocation execute once, and all channel assertions share the result
        without repeating the expensive git operations.

        Returns:
            The CompletedProcess from 'kanon repo smartsync' with no
            positional args.

        Raises:
            AssertionError: When the prerequisite setup or the smartsync
                invocation fails.
        """
        tmp_path = tmp_path_factory.mktemp("smartsync_channel")
        checkout_dir, repo_dir, rpc_server = _build_smartsync_state(tmp_path)

        # The credentials-lookup notice (`No credentials found for
        # <host> in .netrc`) is only emitted when `~/.netrc` opens
        # successfully but lacks an entry for the manifest-server host.
        # When `HOME` points at a fresh tmp dir with no `.netrc`,
        # `netrc.netrc()` raises OSError and the lookup branch is
        # skipped silently. Seed an empty `.netrc` in `HOME` so the
        # netrc.netrc() succeeds and the no-entry branch runs,
        # producing the documented stderr line.
        netrc_seed = pathlib.Path(os.environ["HOME"]) / ".netrc"
        netrc_seed.parent.mkdir(parents=True, exist_ok=True)
        netrc_seed.touch(exist_ok=True)
        os.chmod(netrc_seed, 0o600)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_SMARTSYNC,
            _CLI_FLAG_JOBS_ONE,
            cwd=checkout_dir,
        )

        rpc_server.shutdown()

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed with exit "
            f"{result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        return result

    def test_repo_smartsync_success_has_no_traceback_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo smartsync' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call
        last)'. Tracebacks on stdout indicate an unhandled exception that
        escaped to the wrong channel.
        """
        assert _TRACEBACK_MARKER not in channel_result.stdout, (
            f"Python traceback found in stdout of successful "
            f"'{_CLI_COMMAND_PHRASE}'.\n  stdout: {channel_result.stdout!r}"
        )

    def test_repo_smartsync_success_has_no_error_keyword_on_stdout(
        self, channel_result: subprocess.CompletedProcess
    ) -> None:
        """Successful 'kanon repo smartsync' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        for line in channel_result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'{_CLI_COMMAND_PHRASE}': {line!r}\n"
                f"  stdout: {channel_result.stdout!r}"
            )

    def test_repo_smartsync_success_stderr_is_non_empty(self, channel_result: subprocess.CompletedProcess) -> None:
        """Successful 'kanon repo smartsync' must emit non-empty stderr output.

        On a successful smartsync the embedded repo tool logs a credentials-
        lookup notice to stderr (e.g. "No credentials found for 127.0.0.1 in
        .netrc"), making stderr non-empty. This is the orthogonal channel
        property unique to this class -- the stdout assertions in sibling
        tests already verify the positive stdout content.
        """
        assert channel_result.stderr != _EMPTY_OUTPUT, (
            f"'{_CLI_COMMAND_PHRASE}' produced empty stderr on a successful "
            f"run; expected a credentials-lookup notice on stderr.\n"
            f"  stdout: {channel_result.stdout!r}\n"
            f"  stderr: {channel_result.stderr!r}"
        )
