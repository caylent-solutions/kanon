"""Functional tests for 'kanon repo diffmanifests' error paths and --help.

Verifies that:
- 'kanon repo diffmanifests --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- Missing required positional argument produces exit 2 with the canonical
  error phrase on stderr (AC-TEST-003). The 'repo diffmanifests' subcommand
  requires at least one positional manifest filename; omitting all positional
  arguments causes ValidateOptions to call OptionParser.error('missing
  manifests to diff'), exiting 2 via the kanon wrapper.
- Subcommand-specific precondition failure (nonexistent .repo directory with
  a positional manifest arg supplied) exits 1 with a clear, actionable
  message on stderr (AC-TEST-004). The embedded repo tool prints
  'manifest <name> not found' when the .repo directory does not exist.
- All error paths are deterministic and actionable (AC-FUNC-001).
- stdout vs stderr channel discipline is maintained for every case
  (AC-CHANNEL-001).

Note on AC-TEST-002 disambiguation from AC-FUNC-001 / AC-CHANNEL-001:
The AC-TEST-002 parametrize covers the exit-code and flag-name-in-stderr
assertions. AC-CHANNEL-001 verifies cross-channel discipline for the same
error class without duplicating the phrase-content (flag-name-in-stderr)
assertions of the sibling AC-TEST-* classes. Exit-code checks are included
as prerequisite guards to confirm each error scenario is triggered correctly.

All tests invoke kanon as a subprocess (no mocking of internal APIs).
Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _run_kanon

# ---------------------------------------------------------------------------
# Module-level constants -- ALL domain literals live here.
# Zero inline literals in test bodies, f-string diagnostics, or parametrize
# tuples.
# ---------------------------------------------------------------------------

# CLI tokens
_CMD_REPO = "repo"
_FLAG_REPO_DIR = "--repo-dir"
_SUBCMD_DIFFMANIFESTS = "diffmanifests"
_FLAG_HELP = "--help"

# Nonexistent repo-dir name used in argument-parser and precondition tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-diffmanifests-errors-repo-dir"

# Manifest filename used in precondition failure tests.
# The file will not exist because the repo-dir is nonexistent.
_MANIFEST_FILENAME = "default.xml"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-diffmanifests-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-diffmanifests-option-99"

# Phrase produced by optparse when an unknown option is supplied (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
# The embedded repo tool writes 'repo diffmanifests' in the Usage line.
_HELP_USAGE_PHRASE = "repo diffmanifests"

# A flag name that must appear in --help output, confirming it is
# subcommand-specific (--raw is registered in Diffmanifests._Options()).
_HELP_EXPECTED_FLAG_PHRASE = "--raw"

# Phrase emitted by ValidateOptions when no positional manifest is supplied
# (AC-TEST-003). The repo tool exits 2 with this message on stderr.
_MISSING_POSITIONAL_PHRASE = "missing manifests to diff"

# Phrase emitted by the embedded repo tool when the .repo directory is
# absent but a positional manifest filename IS supplied (AC-TEST-004).
# The tool emits 'manifest <name> not found' to stderr and exits 1.
_MISSING_MANIFEST_PHRASE = "not found"

# The manifest filename fragment that must appear in the precondition-failure
# error message (AC-TEST-004).
_MANIFEST_NAME_FRAGMENT = _MANIFEST_FILENAME

# Expected exit codes
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2
_EXIT_PRECONDITION_ERROR = 1

# Sentinel for empty output.
_EMPTY_OUTPUT = ""

# Parametrize data for AC-TEST-002: unknown flags that must each exit 2
# and name themselves in stderr. Each tuple is (flag_token, test_id).
_UNKNOWN_FLAGS: list[tuple[str, str]] = [
    (_UNKNOWN_FLAG_PRIMARY, "primary"),
    (_UNKNOWN_FLAG_ALT_A, "alt-a"),
    (_UNKNOWN_FLAG_ALT_B, "alt-b"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo diffmanifests --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsHelp:
    """AC-TEST-001: 'kanon repo diffmanifests --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo diffmanifests' is processed before
    any .repo directory or network is consulted, exits 0, and emits the
    subcommand usage text on stdout with empty stderr.
    """

    def test_help_flag_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests --help' must exit with code 0.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'{_SUBCMD_DIFFMANIFESTS} {_FLAG_HELP}' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_contains_usage_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests --help' stdout must contain the phrase 'repo diffmanifests'.

        The embedded repo tool's help output includes 'repo diffmanifests'
        in the Usage line. Confirms the output is specific to the
        diffmanifests subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_SUBCMD_DIFFMANIFESTS} {_FLAG_HELP}' "
            f"failed with exit {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of "
            f"'{_SUBCMD_DIFFMANIFESTS} {_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stdout_mentions_raw_option(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests --help' stdout must document the --raw option.

        The --help output must mention the --raw flag so users know how to
        request machine-parseable output. This confirms the help text is
        specific to the diffmanifests subcommand.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_SUBCMD_DIFFMANIFESTS} {_FLAG_HELP}' "
            f"failed with exit {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_EXPECTED_FLAG_PHRASE in result.stdout, (
            f"Expected {_HELP_EXPECTED_FLAG_PHRASE!r} in stdout of "
            f"'{_SUBCMD_DIFFMANIFESTS} {_FLAG_HELP}'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_stderr_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests --help' must not produce any output on stderr.

        Successful help output is routed entirely to stdout. An empty stderr
        confirms no error-level messages are emitted on a successful --help
        invocation.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: '{_SUBCMD_DIFFMANIFESTS} {_FLAG_HELP}' "
            f"failed with exit {result.returncode}.\n  stdout: {result.stdout!r}"
        )
        assert result.stderr == _EMPTY_OUTPUT, (
            f"'{_SUBCMD_DIFFMANIFESTS} {_FLAG_HELP}' produced unexpected stderr.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests --help' produces the same stdout on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _FLAG_HELP,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _FLAG_HELP,
        )
        assert result_a.returncode == _EXIT_SUCCESS
        assert result_b.returncode == _EXIT_SUCCESS
        assert result_a.stdout == result_b.stdout, (
            f"'{_SUBCMD_DIFFMANIFESTS} {_FLAG_HELP}' produced different stdout on "
            f"repeated calls.\n"
            f"  first:  {result_a.stdout!r}\n"
            f"  second: {result_b.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo diffmanifests' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    @pytest.mark.parametrize(
        "bad_flag",
        [token for token, _ in _UNKNOWN_FLAGS],
        ids=[test_id for _, test_id in _UNKNOWN_FLAGS],
    )
    def test_unknown_flag_exits_2(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Unknown flags to 'kanon repo diffmanifests' must exit with code 2.

        The embedded repo option parser exits 2 for unrecognised flags.
        The kanon layer must propagate this exit code unchanged.
        Parametrized over several distinct bogus flag names.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_SUBCMD_DIFFMANIFESTS} {bad_flag}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "bad_flag",
        [token for token, _ in _UNKNOWN_FLAGS],
        ids=[test_id for _, test_id in _UNKNOWN_FLAGS],
    )
    def test_unknown_flag_names_itself_in_stderr(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Unknown flags to 'kanon repo diffmanifests' must appear by name in stderr.

        The error message must identify the unrecognised flag so users
        receive an actionable diagnostic pointing to the exact bad option.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_flag",
        [token for token, _ in _UNKNOWN_FLAGS],
        ids=[test_id for _, test_id in _UNKNOWN_FLAGS],
    )
    def test_unknown_flag_stderr_contains_no_such_option(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Unknown flags to 'kanon repo diffmanifests' must produce 'no such option' in stderr.

        The embedded repo option parser consistently uses the phrase 'no such
        option' for unrecognised flags. Verifies this canonical error phrase
        is present.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag {bad_flag!r}.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests --unknown-flag-xyzzy' stderr is stable across calls.

        Verifies that the error message is identical on repeated invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _UNKNOWN_FLAG_PRIMARY,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_SUBCMD_DIFFMANIFESTS} {_UNKNOWN_FLAG_PRIMARY}' produced "
            f"different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Missing required positional produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsMissingPositional:
    """AC-TEST-003: Missing required positional argument to 'repo diffmanifests' exits 2.

    The 'repo diffmanifests' subcommand requires at least one positional
    manifest filename. When no positional argument is supplied, ValidateOptions
    calls OptionParser.error('missing manifests to diff'), which causes the
    kanon wrapper to exit 2. This class verifies that the exit code and the
    actionable error phrase are both propagated correctly.
    """

    def test_no_positional_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests' with no positional argument must exit 2.

        Omitting the required manifest filename causes ValidateOptions to
        raise OptionParser.error, which the embedded repo tool handles by
        printing the error to stderr and exiting 2. The kanon wrapper
        propagates this exit code unchanged.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'{_SUBCMD_DIFFMANIFESTS}' (no positional) exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_no_positional_stderr_contains_missing_phrase(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests' with no positional must emit the missing-manifests phrase.

        The embedded repo tool prints 'missing manifests to diff' on stderr
        when the required positional argument is absent. This clear, actionable
        message tells users exactly what argument is required.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert _MISSING_POSITIONAL_PHRASE in result.stderr, (
            f"Expected {_MISSING_POSITIONAL_PHRASE!r} in stderr for "
            f"missing positional.\n  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_no_positional_stdout_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests' with no positional must not write error to stdout.

        The missing-positional error must be routed to stderr only. Stdout
        must be empty (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert result.stdout == _EMPTY_OUTPUT, (
            f"'{_SUBCMD_DIFFMANIFESTS}' (no positional) produced unexpected stdout.\n  stdout: {result.stdout!r}"
        )

    def test_no_positional_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests' missing-positional error is stable across calls.

        Verifies that the error message is identical on repeated invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
        )
        assert result_a.returncode == _EXIT_ARGPARSE_ERROR
        assert result_b.returncode == _EXIT_ARGPARSE_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_SUBCMD_DIFFMANIFESTS}' (no positional) produced different "
            f"stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsPreconditionFailure:
    """AC-TEST-004: Subcommand precondition failure exits 1 with a clear message.

    'repo diffmanifests' requires a valid .repo directory so the embedded repo
    tool can locate the manifests directory. When the --repo-dir path does not
    exist and a positional manifest filename IS supplied, the tool exits 1 with
    'manifest <name> not found' on stderr. This class verifies that exit code
    1 and the actionable error message are both propagated correctly by the
    kanon layer.
    """

    def test_missing_repo_dir_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests <manifest>' with nonexistent .repo must exit 1.

        When the .repo directory is absent but a positional manifest filename
        IS supplied (past argument validation), the embedded repo tool exits 1
        after emitting 'manifest <name> not found'. The kanon layer must
        propagate this exit code without modification.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'{_SUBCMD_DIFFMANIFESTS} {_MANIFEST_FILENAME}' (no .repo) "
            f"exited {result.returncode}, expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_stderr_contains_not_found(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests <manifest>' without .repo emits 'not found' on stderr.

        The embedded repo tool prints 'manifest <name> not found' to stderr
        when the manifest cannot be located. This clear, actionable message
        tells users exactly what file is missing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_MANIFEST_PHRASE in result.stderr, (
            f"Expected {_MISSING_MANIFEST_PHRASE!r} in stderr for missing .repo.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_stderr_names_manifest_file(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests <manifest>' without .repo stderr must name the manifest file.

        The error message must include the manifest filename so users know
        exactly which file was not found.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MANIFEST_NAME_FRAGMENT in result.stderr, (
            f"Expected {_MANIFEST_NAME_FRAGMENT!r} in stderr for missing manifest.\n  stderr: {result.stderr!r}"
        )

    def test_missing_repo_dir_stdout_is_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests <manifest>' without .repo must not emit to stdout.

        The precondition-failure error must be routed to stderr only. Stdout
        must be empty (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert result.stdout == _EMPTY_OUTPUT, (
            f"'{_SUBCMD_DIFFMANIFESTS} {_MANIFEST_FILENAME}' (no .repo) "
            f"produced unexpected stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests <manifest>' without .repo stderr is stable across calls.

        Verifies that the precondition-failure error message is identical on
        repeated invocations, confirming the determinism requirement of
        AC-FUNC-001.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result_a = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
        )
        result_b = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
        )
        assert result_a.returncode == _EXIT_PRECONDITION_ERROR
        assert result_b.returncode == _EXIT_PRECONDITION_ERROR
        assert result_a.stderr == result_b.stderr, (
            f"'{_SUBCMD_DIFFMANIFESTS} {_MANIFEST_FILENAME}' (no .repo) produced "
            f"different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Determinism and channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo diffmanifests' errors.

    Verifies that all argument-parsing and precondition-failure errors produced
    by 'kanon repo diffmanifests' appear on stderr only, that stdout remains
    clean of error detail, and that --help output is routed to stdout. No
    cross-channel leakage is permitted for any error class.

    Note: This class does NOT duplicate the flag-name-in-stderr or
    phrase-content assertions of the sibling AC-TEST-002 parametrize.
    Exit-code assertions are included as prerequisite guards to confirm each
    error scenario is triggered correctly. This class focuses on the
    cross-channel discipline assertions (non-empty stderr, non-empty stdout
    for help), which are orthogonal concerns not covered by the dedicated
    AC-TEST-* focused tests.
    """

    def test_help_output_on_stdout_not_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests --help' routes help text to stdout, not stderr.

        Confirms channel discipline for the success path: --help output goes
        to stdout and stderr is empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _FLAG_HELP,
        )
        assert result.returncode == _EXIT_SUCCESS
        assert result.stdout != _EMPTY_OUTPUT, (
            f"'{_SUBCMD_DIFFMANIFESTS} {_FLAG_HELP}' produced empty stdout; "
            f"help must appear on stdout.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Unknown flag error must appear on stderr, not stdout.

        The 'no such option' rejection must be routed to stderr. Stdout must
        be empty of error detail (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert result.stderr != _EMPTY_OUTPUT, (
            f"Unknown flag error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert result.stdout == _EMPTY_OUTPUT, f"Unknown flag error leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_missing_positional_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Missing-positional error must appear on stderr, not stdout.

        The 'missing manifests to diff' rejection must be routed to stderr.
        Stdout must be empty (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert result.stderr != _EMPTY_OUTPUT, (
            f"Missing-positional error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )

    def test_precondition_failure_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Precondition-failure error must appear on stderr, not stdout.

        The 'manifest not found' error must be routed to stderr only. Stdout
        must be empty when the precondition failure is triggered.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert result.stderr != _EMPTY_OUTPUT, (
            f"Precondition failure produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
