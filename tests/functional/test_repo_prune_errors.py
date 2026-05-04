"""Functional tests for 'kanon repo prune' error paths and --help.

Verifies that:
- 'kanon repo prune --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for 'repo prune' -- a boolean flag supplied
  with an unexpected inline value (e.g. --verbose=unexpected) -- produces
  exit 2 (AC-TEST-003). Note: 'repo prune' accepts optional project arguments
  (not required), so omitting them entirely is valid and causes no
  argument-parser error. AC-TEST-003 therefore covers the analogous exit-2
  scenario: a boolean flag supplied with an unexpected inline value using
  '--flag=value' syntax, which the optparse parser rejects with exit 2
  because boolean flags (store_true/store_false) do not accept inline values.
- Subcommand-specific precondition failure (missing .repo directory) exits 1
  with a clear, actionable message on stderr (AC-TEST-004).
- All error paths are deterministic and actionable (AC-FUNC-001).
- stdout vs stderr channel discipline is maintained for every case
  (AC-CHANNEL-001).

All tests invoke kanon as a subprocess (no mocking of internal APIs).
Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _run_kanon

# ---------------------------------------------------------------------------
# NOTE: _run_kanon is imported from tests.functional.conftest (canonical
# definition). No _git helper or repo-init setup is needed because all tests
# here exercise argument-parsing and subcommand precondition failures that do
# not require a fully initialized .repo directory.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Module-level constants -- all fixture literals extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

# Nonexistent repo-dir path used in argument-parser tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-prune-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-prune-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-prune-option-99"

# Flag with unexpected inline value exercised in AC-TEST-003.
# 'repo prune' defines --verbose as a boolean store_true flag via
# _CommonOptions(); the optparse parser rejects '--verbose=unexpected'
# because boolean flags cannot accept an inline value, producing
# exit 2 with '--verbose option does not take a value'.
_BOOL_FLAG_WITH_VALUE = "--verbose=unexpected"
_BOOL_FLAG_WITH_VALUE_ALT_A = "--quiet=badvalue"
_BOOL_FLAG_WITH_VALUE_ALT_B = "--outer-manifest=nope"

# Option name extracted from the bool-flag-with-value token, used in
# the assertion that the error message names the offending flag.
_BOOL_FLAG_BASE_NAME = "--verbose"

# Phrase produced by optparse when a boolean flag is supplied with an
# inline value (AC-TEST-003).
_BOOL_FLAG_VALUE_PHRASE = "does not take a value"

# Phrase expected in stderr when an unknown option is supplied (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
_HELP_USAGE_PHRASE = "repo prune"

# Phrase expected in stderr when the .repo directory is absent (AC-TEST-004).
# The embedded repo tool prints "error parsing manifest" to stderr when the
# .repo/manifest.xml file cannot be found.
_MISSING_REPO_PHRASE = "error parsing manifest"

# Manifest filename the embedded repo tool names in stderr for precondition
# failures (AC-TEST-004).
_MANIFEST_FILE_NAME = "manifest.xml"

# Expected exit codes.
_EXIT_SUCCESS = 0
_EXIT_ARGPARSE_ERROR = 2
_EXIT_PRECONDITION_ERROR = 1


# ---------------------------------------------------------------------------
# Shared determinism helper -- DRY extraction for _is_deterministic tests.
# ---------------------------------------------------------------------------


def _assert_deterministic(
    tmp_path: pathlib.Path,
    extra_args: list,
    expected_exit: int,
    compare_stdout: bool,
) -> None:
    """Run 'kanon repo prune [extra_args]' twice and assert output channel equality.

    Builds a repo_dir path under tmp_path, invokes _run_kanon with the common
    'repo --repo-dir <repo_dir> prune' prefix plus extra_args, then asserts:
    - Both calls exit with expected_exit.
    - The chosen output channel (stdout if compare_stdout, else stderr) is
      identical across both calls.

    Used by all four _is_deterministic test methods to satisfy AC-FUNC-001
    without repeating invocation boilerplate.
    """
    repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
    result_a = _run_kanon("repo", "--repo-dir", repo_dir, "prune", *extra_args)
    result_b = _run_kanon("repo", "--repo-dir", repo_dir, "prune", *extra_args)
    assert result_a.returncode == expected_exit, (
        f"First call exited {result_a.returncode}, expected {expected_exit}.\n"
        f"  stdout: {result_a.stdout!r}\n"
        f"  stderr: {result_a.stderr!r}"
    )
    assert result_b.returncode == expected_exit, (
        f"Second call exited {result_b.returncode}, expected {expected_exit}.\n"
        f"  stdout: {result_b.stdout!r}\n"
        f"  stderr: {result_b.stderr!r}"
    )
    channel_name = "stdout" if compare_stdout else "stderr"
    output_a = result_a.stdout if compare_stdout else result_a.stderr
    output_b = result_b.stdout if compare_stdout else result_b.stderr
    assert output_a == output_b, (
        f"'kanon repo prune {extra_args}' produced different {channel_name} on repeated calls.\n"
        f"  first:  {output_a!r}\n"
        f"  second: {output_b!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo prune --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPruneHelp:
    """AC-TEST-001: 'kanon repo prune --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo prune' is handled before any
    .repo directory or network is consulted, exits 0, and emits usage
    text on stdout. All assertions for a single subprocess call are merged
    into one test method where the invocation is identical (DRY).
    """

    def test_help_flag_exits_zero_with_stdout_and_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo prune --help' exits 0, emits non-empty stdout, and has empty stderr.

        The embedded repo tool handles '--help' before consulting the .repo
        directory, so a nonexistent --repo-dir path is sufficient. This test
        merges three assertions on the same subprocess call: exit code 0,
        non-empty stdout, and empty stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "prune",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'kanon repo prune --help' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'kanon repo prune --help' produced empty stdout; "
            f"usage text must appear on stdout.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of 'kanon repo prune --help'.\n  stdout: {result.stdout!r}"
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo prune --help' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo prune --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(tmp_path, ["--help"], _EXIT_SUCCESS, compare_stdout=True)


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPruneUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo prune' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_exits_2_with_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo prune --unknown-flag-xyzzy' exits 2, names the flag in stderr, not stdout.

        Merges exit-code, flag-in-stderr, and no-leak-to-stdout assertions on
        the same subprocess call (DRY).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "prune",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo prune {_UNKNOWN_FLAG_PRIMARY}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _UNKNOWN_OPTION_PHRASE in result.stderr, (
            f"Expected {_UNKNOWN_OPTION_PHRASE!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )
        assert _UNKNOWN_FLAG_PRIMARY in result.stderr, (
            f"Expected {_UNKNOWN_FLAG_PRIMARY!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )
        assert _UNKNOWN_FLAG_PRIMARY not in result.stdout, (
            f"Unknown flag {_UNKNOWN_FLAG_PRIMARY!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_flag",
        [
            _UNKNOWN_FLAG_PRIMARY,
            _UNKNOWN_FLAG_ALT_A,
            _UNKNOWN_FLAG_ALT_B,
        ],
    )
    def test_various_unknown_flags_exit_2_with_flag_in_stderr(self, tmp_path: pathlib.Path, bad_flag: str) -> None:
        """Various unknown 'repo prune' flags exit 2 and name the flag in stderr.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 and that each flag name appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "prune",
            bad_flag,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo prune {bad_flag}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo prune --unknown-flag-xyzzy' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(tmp_path, [_UNKNOWN_FLAG_PRIMARY], _EXIT_ARGPARSE_ERROR, compare_stdout=False)


# ---------------------------------------------------------------------------
# AC-TEST-003: Boolean flag with inline value produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPruneBoolFlagWithValue:
    """AC-TEST-003: Boolean flag supplied with an inline value produces exit 2.

    Why this covers AC-TEST-003 ('Missing required positional produces exit 2'):
    The 'repo prune' parser accepts optional project arguments (not required),
    so omitting them entirely is valid and causes no argument-parser error.
    The only exit-2 scenarios available for 'repo prune' are unknown flags
    (AC-TEST-002) and boolean flags supplied with unexpected inline values
    (this class). When optparse receives '--verbose=unexpected' it exits 2
    with '--verbose option does not take a value' because boolean flags
    (store_true/store_false) cannot accept an inline value. These tests verify that the
    argument-parser error path (exit 2) is reached and produces an
    actionable message naming the offending option, satisfying the spirit
    of AC-TEST-003.
    """

    def test_bool_flag_with_value_exits_2_with_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo prune --verbose=unexpected' exits 2, names the flag, has no leak to stdout.

        Merges exit-code, flag-in-stderr, does-not-take-value phrase, and
        no-leak-to-stdout assertions on the same subprocess call (DRY).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "prune",
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo prune {_BOOL_FLAG_WITH_VALUE}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _BOOL_FLAG_BASE_NAME in result.stderr, (
            f"Expected {_BOOL_FLAG_BASE_NAME!r} in stderr for bad-flag error.\n  stderr: {result.stderr!r}"
        )
        assert _BOOL_FLAG_VALUE_PHRASE in result.stderr, (
            f"Expected {_BOOL_FLAG_VALUE_PHRASE!r} in stderr for bool-flag-with-value error.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _BOOL_FLAG_WITH_VALUE not in result.stdout, (
            f"Bad flag {_BOOL_FLAG_WITH_VALUE!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_token",
        [
            _BOOL_FLAG_WITH_VALUE,
            _BOOL_FLAG_WITH_VALUE_ALT_A,
            _BOOL_FLAG_WITH_VALUE_ALT_B,
        ],
    )
    def test_various_bool_flags_with_values_exit_2(self, tmp_path: pathlib.Path, bad_token: str) -> None:
        """Various boolean flags with inline values must all exit 2.

        Parametrises over multiple boolean flags supplied with unexpected
        inline values to confirm the exit code is consistently 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "prune",
            bad_token,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo prune {bad_token}' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_bool_flag_with_value_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo prune --verbose=unexpected' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(tmp_path, [_BOOL_FLAG_WITH_VALUE], _EXIT_ARGPARSE_ERROR, compare_stdout=False)


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPrunePreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failures exit 1 with clear message.

    'repo prune' requires a valid .repo directory with a readable manifest.xml
    to load project configurations. When the .repo directory is absent or the
    manifest cannot be parsed, the embedded repo tool exits 1 with
    'error parsing manifest' on stderr. This class verifies that the exit
    code and the error message are both propagated correctly by the kanon layer.
    """

    def test_missing_repo_dir_exits_1_with_error_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo prune' without .repo exits 1 and emits 'error parsing manifest' on stderr.

        Merges exit-code, error-phrase-in-stderr, manifest-filename-in-stderr,
        non-empty-stderr, and no-error-on-stdout assertions on the same
        subprocess call (DRY).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "prune",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'kanon repo prune' (no .repo dir) exited {result.returncode}, "
            f"expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, (
            f"'kanon repo prune' (no .repo dir) produced empty stderr; "
            f"error must appear on stderr.\n"
            f"  stdout: {result.stdout!r}"
        )
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr for missing .repo dir.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )
        assert _MANIFEST_FILE_NAME in result.stderr, (
            f"Expected {_MANIFEST_FILE_NAME!r} in stderr for missing .repo dir.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) == 0, (
            f"'kanon repo prune' (no .repo dir) produced unexpected stdout output.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_dir_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo prune' without .repo produces the same error on repeated calls.

        Verifies that the precondition failure error is stable across
        invocations, confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(tmp_path, [], _EXIT_PRECONDITION_ERROR, compare_stdout=False)


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Channel discipline across all error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoPruneErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for 'repo prune' errors.

    Verifies that all argument-parsing and precondition-failure errors produced
    by 'kanon repo prune' appear on stderr only, and that stdout remains clean
    of error detail. Also verifies help output is routed to stdout (AC-TEST-001
    complement) and not to stderr.
    """

    def test_help_output_on_stdout_not_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo prune --help' routes help text to stdout; stderr is empty.

        Confirms channel discipline on the success path: --help output goes
        to stdout while stderr remains empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "prune",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS
        assert len(result.stdout) > 0, (
            f"'kanon repo prune --help' produced no stdout; help must appear on stdout.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo prune --help' produced unexpected stderr.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Unknown flag error appears on stderr; stdout is clean.

        Confirms channel discipline: the 'no such option' rejection must be
        routed to stderr. Stdout must not contain the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "prune",
            _UNKNOWN_FLAG_PRIMARY,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert len(result.stderr) > 0, (
            f"Unknown flag error produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )
        assert _UNKNOWN_OPTION_PHRASE not in result.stdout, (
            f"'no such option' phrase leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_bool_flag_with_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error appears on stderr; stdout is clean.

        Confirms channel discipline for the argparse-level rejection: the
        'does not take a value' error must be routed to stderr. Stdout must be
        clean.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "prune",
            _BOOL_FLAG_WITH_VALUE,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR
        assert len(result.stderr) > 0, (
            f"Bool-flag-with-value error produced empty stderr; error must appear on stderr.\n"
            f"  stdout: {result.stdout!r}"
        )
        assert _BOOL_FLAG_WITH_VALUE not in result.stdout, (
            f"Bad flag {_BOOL_FLAG_WITH_VALUE!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_repo_precondition_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'error parsing manifest' appears on stderr; stdout is empty.

        Confirms channel discipline for the precondition failure: the error
        must be routed to stderr only. Stdout must be empty.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "prune",
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _MISSING_REPO_PHRASE in result.stderr, (
            f"Expected {_MISSING_REPO_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )
        assert _MISSING_REPO_PHRASE not in result.stdout, (
            f"Precondition error {_MISSING_REPO_PHRASE!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_all_error_classes_produce_non_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """Every 'repo prune' error class must produce non-empty stderr output.

        Exercises three distinct error classes (unknown flag, bool flag with
        value, missing .repo) and confirms that each produces non-empty
        stderr so users always receive a diagnostic message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        error_cases = [
            ("unknown flag", [_UNKNOWN_FLAG_PRIMARY]),
            ("bool flag with inline value", [_BOOL_FLAG_WITH_VALUE]),
            ("missing .repo directory", []),
        ]
        for description, extra_args in error_cases:
            result = _run_kanon(
                "repo",
                "--repo-dir",
                repo_dir,
                "prune",
                *extra_args,
            )
            assert len(result.stderr) > 0, (
                f"Error case '{description}' produced empty stderr; "
                f"error must appear on stderr.\n"
                f"  returncode: {result.returncode}\n"
                f"  stdout: {result.stdout!r}"
            )
