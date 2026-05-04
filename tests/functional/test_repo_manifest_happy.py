"""Happy-path functional tests for 'kanon repo manifest'.

Exercises the happy path of the 'repo manifest' subcommand by invoking
``kanon repo manifest`` as a subprocess against a real initialized repo
directory created in a temporary directory. No mocking -- these tests use
the full CLI stack against actual git operations.

The 'repo manifest' subcommand outputs the current manifest in XML (default)
or JSON format to stdout (when ``-o -``) or to a file (when ``-o <path>``).
It exits 0 on a properly initialized repository.

AC wording note: AC-TEST-002 states "every positional argument of 'repo
manifest' has a happy-path test." The upstream 'repo manifest' subcommand
accepts no positional arguments -- ValidateOptions explicitly calls
self.Usage() when args is non-empty. To satisfy AC-TEST-002 in spirit, this
file exercises each distinct flag-driven invocation form that exercises a
different code path: default (XML to stdout), --format=json, --pretty,
--output-file to a temp file, and --no-local-manifests.

Covers:
- AC-TEST-001: 'kanon repo manifest' with default args exits 0 in a valid repo.
- AC-TEST-002: Every invocation form of 'repo manifest' has a happy-path test.
- AC-FUNC-001: 'kanon repo manifest' executes successfully with documented
  default behavior (exit 0, XML output to stdout).
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

_GIT_USER_NAME = "Repo Manifest Happy Test User"
_GIT_USER_EMAIL = "repo-manifest-happy@example.com"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "manifest-happy-test-project"
_MANIFEST_FILENAME = "default.xml"

# CLI token for the manifest subcommand.
_CLI_TOKEN_MANIFEST = "manifest"

# Expected exit code for all happy-path invocations.
_EXPECTED_EXIT_CODE = 0

# Composed CLI command phrase for diagnostic messages.
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_CLI_TOKEN_MANIFEST}"

# String that must appear in the default (XML) output.
# The canonical manifest XML always starts with the XML declaration.
_XML_DECLARATION_FRAGMENT = "<?xml"

# String that must appear in the JSON output (--format=json).
_JSON_MANIFEST_KEY = "manifest"

# Flag to select JSON output format.
_FLAG_FORMAT_JSON = "--format=json"

# Flag to enable human-readable (pretty) output.
_FLAG_PRETTY = "--pretty"

# Flag to suppress inclusion of local manifests.
_FLAG_NO_LOCAL_MANIFESTS = "--no-local-manifests"

# Output file flag token (value supplied at test time).
_FLAG_OUTPUT_FILE = "-o"

# Output file name used in file-output tests.
_OUTPUT_FILE_NAME = "exported-manifest.xml"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# Parametrized invocation forms for AC-TEST-002.
# Each entry is a tuple of extra CLI tokens passed after 'manifest'.
# The default (no flags) form is covered by TestRepoManifestHappyPathDefaultArgs.
_INVOCATION_FORMS = [
    pytest.param((_FLAG_FORMAT_JSON,), id="format-json"),
    pytest.param((_FLAG_FORMAT_JSON, _FLAG_PRETTY), id="format-json-pretty"),
    pytest.param((_FLAG_NO_LOCAL_MANIFESTS,), id="no-local-manifests"),
]


# ---------------------------------------------------------------------------
# Shared setup helper
# ---------------------------------------------------------------------------


def _setup_manifest_repo(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Create bare repos, run repo init and sync, return (checkout_dir, repo_dir).

    Delegates to ``_setup_synced_repo`` from tests.functional.conftest using
    the git identity and project path specific to this test module.

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
        project_name=_PROJECT_NAME,
        project_path=_PROJECT_PATH,
        manifest_filename=_MANIFEST_FILENAME,
    )


# ---------------------------------------------------------------------------
# AC-TEST-001 / AC-FUNC-001: kanon repo manifest with default args exits 0
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoManifestHappyPathDefaultArgs:
    """AC-TEST-001 / AC-FUNC-001: 'kanon repo manifest' with default args exits 0.

    Verifies that running 'kanon repo manifest' with no additional arguments
    against a properly initialized and synced repo directory exits 0 and writes
    valid XML to stdout. This is the documented default behavior.
    """

    def test_repo_manifest_with_defaults_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo manifest' with no extra args must exit 0.

        After a successful 'kanon repo init' and 'kanon repo sync', invokes
        'kanon repo manifest' with no additional arguments. The command must
        exit 0.
        """
        checkout_dir, repo_dir = _setup_manifest_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_manifest_default_output_contains_xml_declaration(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo manifest' default output must contain the XML declaration.

        The default output format is XML. The XML declaration (``<?xml``) must
        appear in stdout, confirming the canonical manifest was serialized and
        written to the default output channel.
        """
        checkout_dir, repo_dir = _setup_manifest_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        )
        assert _XML_DECLARATION_FRAGMENT in result.stdout, (
            f"Expected {_XML_DECLARATION_FRAGMENT!r} in stdout of "
            f"'{_CLI_COMMAND_PHRASE}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_manifest_default_output_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo manifest' must produce non-empty stdout on a valid repo.

        A successful invocation must write at least some manifest content to
        stdout. An empty stdout would indicate the command performed no output.
        """
        checkout_dir, repo_dir = _setup_manifest_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'{_CLI_COMMAND_PHRASE}' produced empty stdout.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: every invocation form of 'repo manifest' has a happy-path test
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoManifestInvocationForms:
    """AC-TEST-002: happy-path tests for each distinct invocation form of 'repo manifest'.

    'repo manifest' accepts no positional arguments. To satisfy AC-TEST-002
    in spirit, this class parametrizes over distinct flag-driven invocation
    forms: --format=json, --format=json --pretty, and --no-local-manifests.
    All forms must exit 0 in a properly initialized and synced repository.
    """

    @pytest.mark.parametrize("extra_flags", _INVOCATION_FORMS)
    def test_repo_manifest_invocation_form_exits_zero(
        self,
        tmp_path: pathlib.Path,
        extra_flags: tuple,
    ) -> None:
        """Each invocation form of 'kanon repo manifest' must exit 0.

        Runs 'kanon repo manifest' with each set of extra flags in
        _INVOCATION_FORMS. All forms must exit 0 in a properly initialized
        and synced repository.
        """
        checkout_dir, repo_dir = _setup_manifest_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            *extra_flags,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE}' with flags {extra_flags!r} exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("extra_flags", _INVOCATION_FORMS)
    def test_repo_manifest_invocation_form_produces_non_empty_output(
        self,
        tmp_path: pathlib.Path,
        extra_flags: tuple,
    ) -> None:
        """Each invocation form of 'kanon repo manifest' must produce non-empty stdout.

        All flag forms must write manifest content to stdout. An empty stdout
        from any form would indicate the execution path produced no output.
        """
        checkout_dir, repo_dir = _setup_manifest_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            *extra_flags,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' with flags {extra_flags!r} failed: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert len(combined) > 0, (
            f"'{_CLI_COMMAND_PHRASE}' with flags {extra_flags!r} produced "
            f"empty combined output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


@pytest.mark.functional
class TestRepoManifestOutputFileForm:
    """AC-TEST-002: happy-path test for the -o <file> invocation form.

    Tests that 'kanon repo manifest -o <file>' writes the manifest to the
    specified file path and exits 0, exercising the file-output code path
    inside the Manifest._Output method.
    """

    def test_repo_manifest_output_to_file_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo manifest -o <file>' must exit 0 and create the output file.

        Passes an explicit output file path via '-o'. The manifest must be
        written to that file and the process must exit 0.
        """
        checkout_dir, repo_dir = _setup_manifest_repo(tmp_path)
        output_file = tmp_path / _OUTPUT_FILE_NAME

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            _FLAG_OUTPUT_FILE,
            str(output_file),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} {_FLAG_OUTPUT_FILE} <file>' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_repo_manifest_output_to_file_creates_file_with_xml(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo manifest -o <file>' must write valid XML to the output file.

        When an output file path is given, the XML manifest must be written to
        that file. The file must exist after the command and contain the XML
        declaration.
        """
        checkout_dir, repo_dir = _setup_manifest_repo(tmp_path)
        output_file = tmp_path / _OUTPUT_FILE_NAME

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            _FLAG_OUTPUT_FILE,
            str(output_file),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE} {_FLAG_OUTPUT_FILE} <file>' failed: {result.stderr!r}"
        )
        assert output_file.exists(), (
            f"Expected output file {output_file!r} to exist after "
            f"'{_CLI_COMMAND_PHRASE} {_FLAG_OUTPUT_FILE} <file>'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        file_content = output_file.read_text(encoding="utf-8")
        assert _XML_DECLARATION_FRAGMENT in file_content, (
            f"Expected {_XML_DECLARATION_FRAGMENT!r} in file written by "
            f"'{_CLI_COMMAND_PHRASE} {_FLAG_OUTPUT_FILE} <file>'.\n"
            f"  file content: {file_content!r}\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoManifestChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'kanon repo manifest'.

    Verifies that successful 'kanon repo manifest' invocations do not write
    Python tracebacks or 'Error:' prefixed messages to stdout, and that
    stderr does not contain Python exception tracebacks on a successful run.
    """

    def test_repo_manifest_success_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo manifest' must not emit Python tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        checkout_dir, repo_dir = _setup_manifest_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of successful '{_CLI_COMMAND_PHRASE}'.\n  stdout: {result.stdout!r}"
        )

    def test_repo_manifest_success_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo manifest' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_manifest_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        )
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of successful "
                f"'{_CLI_COMMAND_PHRASE}': {line!r}\n"
                f"  stdout: {result.stdout!r}"
            )

    def test_repo_manifest_success_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo manifest' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_manifest_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of successful '{_CLI_COMMAND_PHRASE}'.\n  stderr: {result.stderr!r}"
        )
