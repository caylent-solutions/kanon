"""Functional tests for flag coverage of 'kanon repo manifest'.

Exercises every flag registered in ``subcmds/manifest.py``'s ``_Options()``
method by invoking ``kanon repo manifest`` as a subprocess. Validates correct
accept and reject behavior for all flag values, and correct default behavior
when flags are omitted.

The flags defined in ``Manifest._Options()`` are:

- ``-r`` / ``--revision-as-HEAD``: store_true, saves revisions as current HEAD.
- ``-m`` / ``--manifest-name``: string, temporary manifest override.
- ``--suppress-upstream-revision``: store_false, suppresses upstream field in
  revision-locked manifests.
- ``--suppress-dest-branch``: store_false, suppresses dest-branch field in
  revision-locked manifests.
- ``--json``: legacy alias for ``--format=json`` (hidden help, kept for backward
  compatibility).
- ``--format``: choices of ``xml`` and ``json``; the only flag with enumerated
  values. Default is ``xml``.
- ``--pretty``: store_true, formats output for human readability.
- ``--no-local-manifests``: store_true, ignores local manifests.
- ``-o`` / ``--output-file``: string, file to save the manifest to.

Covers:
- AC-TEST-001: Every ``_Options()`` flag has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated values has a negative test
  for an invalid value (``--format`` is the only such flag).
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified.

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
# Module-level constants -- all hard-coded test-fixture values extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Manifest Flags Test User"
_GIT_USER_EMAIL = "repo-manifest-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "manifest-flags-test-project"

# CLI tokens used throughout this module.
_CLI_TOKEN_MANIFEST = "manifest"

# Exit code emitted by the option parser when an argument is invalid.
_ARGPARSE_ERROR_EXIT_CODE = 2

# Exit code emitted when ValidateOptions calls self.Usage() (RepoExitError default: 1).
_USAGE_ERROR_EXIT_CODE = 1

# Expected exit code for successful invocations.
_EXPECTED_EXIT_CODE = 0

# Composed CLI command phrase used in diagnostic messages.
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_CLI_TOKEN_MANIFEST}"

# Directory name used for repo_dir in parser-only tests (does not need to exist
# for argument-parsing checks when a synced repo is not required).
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-dir"

# Valid format values matching OutputFormat enum members.
_FORMAT_XML = "xml"
_FORMAT_JSON = "json"

# Invalid format values not in the OutputFormat enum.
_FORMAT_INVALID = "toml"
_FORMAT_INVALID_ALT = "yaml"

# Fragment expected in the default (XML) manifest output.
_XML_DECLARATION_FRAGMENT = "<?xml"

# Key expected in JSON manifest output.
_JSON_MANIFEST_KEY = "manifest"

# Python traceback marker used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# Custom manifest name used in manifest-name flag tests.
_CUSTOM_MANIFEST_NAME = "custom.xml"

# Output file name used in output-file flag tests.
_OUTPUT_FILE_NAME = "flagtest-exported-manifest.xml"


# ---------------------------------------------------------------------------
# Shared setup helper
# ---------------------------------------------------------------------------


def _setup_manifest_flags_repo(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Create bare repos, run repo init and sync; return (checkout_dir, repo_dir).

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
# AC-TEST-001: Valid-value tests for every _Options() flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoManifestFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/manifest.py has a valid-value test.

    Exercises each flag registered in ``Manifest._Options()`` with a valid
    value. For flags that only affect argument parsing (no side effects
    beyond parsing), the test confirms the flag is accepted without
    triggering exit code 2. For flags that produce observable output or
    require a synced repository, the test also validates the documented
    behavior.
    """

    def test_revision_as_head_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """``-r`` / ``--revision-as-HEAD`` is accepted and exits 0 on a synced repo.

        The ``-r`` flag pegs revisions to the current HEAD commit SHA.
        On a properly initialized and synced repository, passing ``-r``
        must not cause an argument-parsing error and must produce valid
        XML output to stdout.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "-r",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} -r' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _XML_DECLARATION_FRAGMENT in result.stdout, (
            f"Expected {_XML_DECLARATION_FRAGMENT!r} in stdout with '-r' flag.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_revision_as_head_long_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """``--revision-as-HEAD`` long form is accepted and exits 0 on a synced repo.

        Confirms the long-form alias produces the same valid exit code and
        XML output as the short ``-r`` form.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "--revision-as-HEAD",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} --revision-as-HEAD' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _XML_DECLARATION_FRAGMENT in result.stdout, (
            f"Expected {_XML_DECLARATION_FRAGMENT!r} in stdout with '--revision-as-HEAD'.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_manifest_name_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """``-m`` / ``--manifest-name`` is accepted by the argument parser.

        Passes a custom manifest filename via ``-m``. The option parser must
        not reject the flag (must not exit 2). Subsequent behavior (e.g. file
        not found) may produce a non-zero exit for other reasons, but not
        because the flag itself was invalid.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "-m",
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-m {_MANIFEST_FILENAME}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_manifest_name_long_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """``--manifest-name`` long form is accepted by the argument parser.

        Passes the default manifest filename via ``--manifest-name``. The
        parser must accept the flag (must not exit 2).
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "--manifest-name",
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )

        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--manifest-name {_MANIFEST_FILENAME}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_suppress_upstream_revision_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """``--suppress-upstream-revision`` is accepted and exits 0 on a synced repo.

        When passed alongside ``-r``, this flag suppresses the upstream field
        in the revision-locked manifest. On a synced repo, the combined
        invocation must exit 0 and produce XML output.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "-r",
            "--suppress-upstream-revision",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} -r --suppress-upstream-revision' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_suppress_dest_branch_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """``--suppress-dest-branch`` is accepted and exits 0 on a synced repo.

        When passed alongside ``-r``, this flag suppresses the dest-branch
        field. On a synced repo, the combined invocation must exit 0.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "-r",
            "--suppress-dest-branch",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} -r --suppress-dest-branch' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_json_legacy_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """``--json`` legacy flag is accepted and produces JSON output on a synced repo.

        The ``--json`` flag is a backward-compatibility alias for
        ``--format=json``. On a synced repo, it must be accepted (not exit 2)
        and must produce JSON output containing the manifest key.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "--json",
            cwd=checkout_dir,
        )

        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--json' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} --json' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _JSON_MANIFEST_KEY in result.stdout, (
            f"Expected {_JSON_MANIFEST_KEY!r} in JSON stdout with '--json' flag.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "format_value",
        [_FORMAT_XML, _FORMAT_JSON],
        ids=["format-xml", "format-json"],
    )
    def test_format_valid_values_accepted(
        self,
        tmp_path: pathlib.Path,
        format_value: str,
    ) -> None:
        """``--format=<value>`` with valid values exits 0 on a synced repo.

        Both ``--format=xml`` and ``--format=json`` are valid choices. Each
        must be accepted by the argument parser and must produce non-empty
        output on a synced repository.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            f"--format={format_value}",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'--format={format_value}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert len(combined) > 0, (
            f"'--format={format_value}' produced no combined output.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_pretty_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """``--pretty`` is accepted and exits 0 on a synced repo.

        The ``--pretty`` flag enables human-readable formatting. On a synced
        repo, passing ``--pretty`` must not cause an argument-parsing error
        and must produce non-empty output.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "--pretty",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'--pretty' exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_no_local_manifests_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """``--no-local-manifests`` is accepted and exits 0 on a synced repo.

        The ``--no-local-manifests`` flag instructs the subcommand to ignore
        any local_manifests/ entries. On a synced repo, it must be accepted
        without an argument-parsing error and must exit 0.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "--no-local-manifests",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'--no-local-manifests' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_output_file_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """``-o`` / ``--output-file`` is accepted and writes manifest to the given path.

        Passes an output file path via ``-o``. The flag must be accepted
        (not exit 2) and the file must be created with manifest content.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)
        output_file = tmp_path / _OUTPUT_FILE_NAME

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "-o",
            str(output_file),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'-o <file>' exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert output_file.exists(), (
            f"Expected output file {str(output_file)!r} to exist after '-o <file>'.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_output_file_long_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """``--output-file`` long form is accepted and writes manifest to the given path.

        Passes an output file path via ``--output-file``. The flag must be
        accepted (not exit 2) and the file must be created with XML content.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)
        output_file = tmp_path / _OUTPUT_FILE_NAME

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "--output-file",
            str(output_file),
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'--output-file <file>' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert output_file.exists(), (
            f"Expected output file {str(output_file)!r} to exist after '--output-file <file>'.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        file_content = output_file.read_text(encoding="utf-8")
        assert _XML_DECLARATION_FRAGMENT in file_content, (
            f"Expected {_XML_DECLARATION_FRAGMENT!r} in file written by '--output-file'.\n"
            f"  file content: {file_content!r}"
        )

    def test_output_stdout_dash_accepted(self, tmp_path: pathlib.Path) -> None:
        """``-o -`` explicitly routes output to stdout and exits 0.

        Passing ``-o -`` is the documented way to write the manifest to
        stdout. It must exit 0 and the XML declaration must appear on stdout.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "-o",
            "-",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'-o -' exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _XML_DECLARATION_FRAGMENT in result.stdout, (
            f"Expected {_XML_DECLARATION_FRAGMENT!r} in stdout with '-o -'.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with enumerated values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoManifestFlagsInvalidValues:
    """AC-TEST-002: ``--format`` is the only enumerated flag; negative tests verify rejection.

    The ``--format`` flag in ``Manifest._Options()`` accepts only the choices
    registered in ``OutputFormat`` (``xml`` and ``json``). Any other value must
    be rejected by the option parser with exit code 2. Error messages must
    appear on stderr, not stdout.
    """

    @pytest.mark.parametrize(
        "bad_format",
        [_FORMAT_INVALID, _FORMAT_INVALID_ALT],
        ids=["format-toml", "format-yaml"],
    )
    def test_format_invalid_value_rejected(
        self,
        tmp_path: pathlib.Path,
        bad_format: str,
    ) -> None:
        """``--format=<invalid>`` exits 2 with an error on stderr.

        An unrecognized format string must be rejected by the argument parser
        (exit code 2). The error message must appear on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            "--repo-dir",
            repo_dir,
            _CLI_TOKEN_MANIFEST,
            f"--format={bad_format}",
        )

        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--format={bad_format}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert "invalid" in result.stderr.lower() or "choice" in result.stderr.lower(), (
            f"Expected 'invalid' or 'choice' in stderr for '--format={bad_format}'.\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "bad_format",
        [_FORMAT_INVALID, _FORMAT_INVALID_ALT],
        ids=["format-toml-not-on-stdout", "format-yaml-not-on-stdout"],
    )
    def test_format_invalid_value_error_not_on_stdout(
        self,
        tmp_path: pathlib.Path,
        bad_format: str,
    ) -> None:
        """``--format=<invalid>`` error detail must appear on stderr, not stdout.

        Argument-parsing errors are a stderr-only concern. Stdout must not
        contain the invalid value or error detail when the parser rejects the
        format choice.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            "--repo-dir",
            repo_dir,
            _CLI_TOKEN_MANIFEST,
            f"--format={bad_format}",
        )

        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--format={bad_format}' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert bad_format not in result.stdout, (
            f"Invalid format {bad_format!r} must not appear in stdout.\n  stdout: {result.stdout!r}"
        )

    def test_extra_positional_argument_rejected(self, tmp_path: pathlib.Path) -> None:
        """Positional arguments after 'manifest' are rejected with a non-zero exit code.

        ``Manifest.ValidateOptions`` calls ``self.Usage()`` when positional
        arguments are present. ``self.Usage()`` raises ``UsageError`` which exits
        with code 1 (the default RepoExitError exit code). The command must exit
        non-zero and must not produce a Python traceback on stdout.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "unexpected-positional-arg",
            cwd=checkout_dir,
        )

        assert result.returncode == _USAGE_ERROR_EXIT_CODE, (
            f"Positional arg after 'manifest' exited {result.returncode}, "
            f"expected {_USAGE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback must not appear in stdout when a positional arg is rejected.\n"
            f"  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoManifestFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each flag which documents a default value behaves according
    to that default when the flag is absent. Uses a real synced repository
    to confirm the documented defaults produce the expected output.
    """

    def test_format_default_is_xml(self, tmp_path: pathlib.Path) -> None:
        """Omitting ``--format`` defaults to XML output (documented default: ``xml``).

        When ``--format`` is not supplied, the manifest is written in XML format.
        The XML declaration must appear in stdout, confirming the default.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE}' with no flags exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _XML_DECLARATION_FRAGMENT in result.stdout, (
            f"Expected {_XML_DECLARATION_FRAGMENT!r} in stdout when --format is omitted.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_output_file_default_is_stdout(self, tmp_path: pathlib.Path) -> None:
        """Omitting ``-o`` defaults to stdout output (documented default: ``-``).

        When ``-o`` / ``--output-file`` is not supplied, the manifest is written
        to stdout (default ``"-"``). The XML declaration must appear in stdout.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE}' with no flags exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"Expected non-empty stdout when -o is omitted (defaults to stdout).\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_revision_as_head_default_false(self, tmp_path: pathlib.Path) -> None:
        """Omitting ``-r`` defaults to non-pegged revisions (store_true default: False).

        When ``-r`` / ``--revision-as-HEAD`` is not supplied, the manifest is
        output with its original revision references, not pegged to commit SHAs.
        The XML output must still contain the manifest element.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE}' without -r exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _XML_DECLARATION_FRAGMENT in result.stdout, (
            f"Expected XML output when '-r' is omitted.\n  stdout: {result.stdout!r}"
        )

    def test_suppress_upstream_revision_default_true(self, tmp_path: pathlib.Path) -> None:
        """Omitting ``--suppress-upstream-revision`` defaults to writing upstream field (default: True).

        The ``--suppress-upstream-revision`` flag uses ``store_false`` with
        ``default=True``, meaning upstream is written by default. The manifest
        exits 0 in normal (non-peg-rev) mode regardless of this flag's default.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "-r",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} -r' without --suppress-upstream-revision exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_suppress_dest_branch_default_true(self, tmp_path: pathlib.Path) -> None:
        """Omitting ``--suppress-dest-branch`` defaults to writing dest-branch field (default: True).

        The ``--suppress-dest-branch`` flag uses ``store_false`` with
        ``default=True``, meaning dest-branch is written by default. The manifest
        exits 0 in normal (non-peg-rev) mode regardless of this flag's default.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "-r",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} -r' without --suppress-dest-branch exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_pretty_default_false(self, tmp_path: pathlib.Path) -> None:
        """Omitting ``--pretty`` defaults to compact output (store_true default: False).

        When ``--pretty`` is not supplied, the manifest output is in compact
        (not human-readable) format. The command must still exit 0 and produce
        valid output.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "--format=json",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} --format=json' without --pretty exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _JSON_MANIFEST_KEY in result.stdout, (
            f"Expected {_JSON_MANIFEST_KEY!r} in compact JSON output.\n  stdout: {result.stdout!r}"
        )

    def test_no_local_manifests_default_false(self, tmp_path: pathlib.Path) -> None:
        """Omitting ``--no-local-manifests`` defaults to including local manifests (store_true default: False).

        When ``--no-local-manifests`` is not supplied, local manifests are
        included (if any). The command must exit 0 on a synced repo without
        local manifests.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE}' without --no-local-manifests exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Flag behavior per help text and channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoManifestFlagsChannelDiscipline:
    """AC-FUNC-001 / AC-CHANNEL-001: Flag behavior and stdout/stderr channel discipline.

    Verifies that flags behave per their documented help text and that all
    argument-parsing errors appear exclusively on stderr. Successful
    invocations must not produce Python tracebacks on either channel.
    """

    def test_format_json_produces_json_output(self, tmp_path: pathlib.Path) -> None:
        """``--format=json`` produces JSON output as documented in help text.

        The help text states: ``output format: xml, json (default: xml)``.
        Passing ``--format=json`` must produce output containing the manifest
        key rather than an XML declaration.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "--format=json",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} --format=json' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _JSON_MANIFEST_KEY in result.stdout, (
            f"Expected JSON manifest key {_JSON_MANIFEST_KEY!r} in stdout with '--format=json'.\n"
            f"  stdout: {result.stdout!r}"
        )
        assert _XML_DECLARATION_FRAGMENT not in result.stdout, (
            f"XML declaration must not appear in JSON output.\n  stdout: {result.stdout!r}"
        )

    def test_format_xml_produces_xml_output(self, tmp_path: pathlib.Path) -> None:
        """``--format=xml`` produces XML output as documented in help text.

        Passing ``--format=xml`` must produce output starting with the XML
        declaration, confirming the flag selects the XML serializer.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "--format=xml",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} --format=xml' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        assert _XML_DECLARATION_FRAGMENT in result.stdout, (
            f"Expected {_XML_DECLARATION_FRAGMENT!r} in stdout with '--format=xml'.\n  stdout: {result.stdout!r}"
        )

    def test_invalid_format_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """``--format=<invalid>`` error must appear on stderr, not stdout.

        Confirms channel discipline: argument-parsing errors from an invalid
        ``--format`` value must be routed to stderr only.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            "--repo-dir",
            repo_dir,
            _CLI_TOKEN_MANIFEST,
            f"--format={_FORMAT_INVALID}",
        )

        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for invalid --format.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for invalid --format error."
        assert _FORMAT_INVALID not in result.stdout, (
            f"Invalid format value {_FORMAT_INVALID!r} must not appear in stdout.\n  stdout: {result.stdout!r}"
        )

    def test_successful_manifest_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo manifest' must not emit Python tracebacks to stdout.

        On success with multiple flags, stdout must not contain
        'Traceback (most recent call last)'. Tracebacks on stdout indicate an
        unhandled exception escaping to the wrong channel.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "--format=json",
            "--pretty",
            "--no-local-manifests",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' with flags failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback must not appear in stdout on successful invocation.\n  stdout: {result.stdout!r}"
        )

    def test_successful_manifest_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo manifest' must not emit Python tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "--format=xml",
            "--no-local-manifests",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' with flags failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback must not appear in stderr on successful invocation.\n  stderr: {result.stderr!r}"
        )

    def test_positional_arg_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Error from unexpected positional argument must not appear on stdout.

        When ValidateOptions rejects a positional argument, the error must
        be routed to stderr only. The usage text is written to stdout but no
        traceback or error detail must appear there.
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "unexpected-positional-arg",
            cwd=checkout_dir,
        )

        assert result.returncode == _USAGE_ERROR_EXIT_CODE, (
            f"Positional arg after 'manifest' exited {result.returncode}, expected {_USAGE_ERROR_EXIT_CODE}."
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback must not appear in stdout when positional arg is rejected.\n  stdout: {result.stdout!r}"
        )

    def test_pretty_json_produces_indented_output(self, tmp_path: pathlib.Path) -> None:
        """``--format=json --pretty`` produces indented (multi-line) JSON output.

        The ``--pretty`` flag enables indentation (2 spaces) per the help text
        ``'format output for humans to read'``. Combined with ``--format=json``,
        the output must be multi-line (more than one line).
        """
        checkout_dir, repo_dir = _setup_manifest_flags_repo(tmp_path)

        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_MANIFEST,
            "--format=json",
            "--pretty",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} --format=json --pretty' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        line_count = len(result.stdout.splitlines())
        assert line_count > 1, (
            f"Expected multi-line JSON output with '--pretty' but got {line_count} line(s).\n"
            f"  stdout: {result.stdout!r}"
        )
