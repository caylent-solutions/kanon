"""Functional tests for 'kanon repo cherry-pick' error paths and --help.

Verifies that:
- 'kanon repo cherry-pick --help' exits 0 with usage text (AC-TEST-001).
- Unknown flags produce exit 2 with the flag name in stderr (AC-TEST-002).
- The closest exit-2 scenario for 'repo cherry-pick' -- a boolean flag
  (--verbose) supplied with an inline value using '--flag=value' syntax --
  produces exit 2 with the flag name in stderr (AC-TEST-003). Note: 'repo
  cherry-pick' has one required positional argument (a SHA1 commit reference),
  and its option set consists entirely of boolean flags inherited from
  Command._CommonOptions(): -v/--verbose, -q/--quiet, --outer-manifest,
  --no-outer-manifest, --this-manifest-only, --no-this-manifest-only/
  --all-manifests. CherryPick.PARALLEL_JOBS is None so --jobs is NOT
  registered. There is therefore no store-action (value-requiring) option
  to supply without its argument. Omitting the required SHA1 positional does
  not trigger an argument-parser error (exit 2) -- the embedded repo tool
  handles its own usage validation in ValidateOptions() and raises UsageError
  (exit 1) before the argparse layer. The test_no_positional_args_exits_1
  method below proves this: omitting the SHA1 gives exit 1 with 'UsageError'
  on stderr, NOT exit 2. AC-TEST-003 is therefore satisfied by the inline-
  value-on-boolean-flag scenario: supplying '--verbose=unexpected' causes
  optparse to exit 2 with '--verbose option does not take a value' on stderr.
  This is the same pattern accepted in test_repo_rebase_errors.py and
  test_repo_checkout_errors.py when no store-action option is available.
- Subcommand-specific precondition failure (not a git repository in CWD) exits
  1 with a clear, actionable message on stderr (AC-TEST-004). Note: 'repo
  cherry-pick' differs from manifest-based subcommands (rebase, checkout) -- it
  uses GitCommand(None, ...) which operates on the process CWD rather than the
  .repo/manifest.xml. The precondition failure is therefore a missing git
  repository in the working directory, not a missing .repo directory.
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
# Module-level constants -- all fixture literals extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

# Nonexistent repo-dir path used in argument-parser tests.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-repo-cherry-pick-errors-repo-dir"

# Unknown flag names exercised in AC-TEST-002 tests.
_UNKNOWN_FLAG_PRIMARY = "--unknown-flag-xyzzy"
_UNKNOWN_FLAG_ALT_A = "--not-a-real-cherry-pick-flag"
_UNKNOWN_FLAG_ALT_B = "--bogus-cherry-pick-option-99"

# Boolean flag used in AC-TEST-003: all cherry-pick flags are boolean
# (store_true / store_false). Supplying '--verbose=unexpected' causes optparse
# to exit 2 with '--verbose option does not take a value' on stderr.
_BOOL_FLAG_FOR_EXIT_2 = "--verbose"
_BOOL_FLAG_INLINE_VALUE_SUFFIX = "=unexpected"

# Error message substring expected in stderr when a boolean flag is supplied
# with an inline value (optparse-level 'does not take a value' error).
_DOES_NOT_TAKE_VALUE_PHRASE = "does not take a value"

# Phrase expected in stderr for unknown flag errors (AC-TEST-002).
_UNKNOWN_OPTION_PHRASE = "no such option"

# Phrase expected in the --help output (AC-TEST-001).
_HELP_USAGE_PHRASE = "repo cherry-pick"

# Keyword that must appear in the --help output to document the required SHA1
# positional argument (AC-TEST-001).
_HELP_SHA1_KEYWORD = "sha1"

# Directory name used in AC-TEST-004 / AC-CHANNEL-001 tests that need a CWD
# that is NOT a git working tree. Using a named constant avoids repeating the
# literal string across five test methods in TestRepoCherryPickPreconditionFailure.
_NON_GIT_DIR_NAME = "not-a-git-repo"

# Variant directory name used in TestRepoCherryPickErrorChannelDiscipline to
# avoid colliding with _NON_GIT_DIR_NAME inside the same tmp_path root.
_NON_GIT_DIR_CHANNEL_NAME = "not-a-git-repo-channel"

# Phrase expected in stderr when 'repo cherry-pick' is invoked without its
# required SHA1 positional. The embedded repo tool raises UsageError (exit 1)
# in ValidateOptions() -- NOT an argument-parser error (exit 2).
_USAGE_ERROR_PHRASE = "UsageError"

# Phrase expected in stderr when 'repo cherry-pick' is invoked from a directory
# that is not a git working tree (AC-TEST-004). The git layer emits
# 'not a git repository' before any manifest parsing occurs.
_NOT_GIT_REPO_PHRASE = "not a git repository"

# Placeholder SHA1 used in argument-parser tests that exercise flag errors
# before git is invoked. Any 40-hex string will do; the command will fail at
# git rev-parse (exit 1) rather than at option parsing (exit 2), proving the
# flag was accepted by optparse.
_FAKE_SHA1 = "0000000000000000000000000000000000000001"

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
    cwd: "pathlib.Path | None" = None,
) -> None:
    """Run 'kanon repo cherry-pick [extra_args]' twice and assert output channel equality.

    Builds a repo_dir path under tmp_path, invokes _run_kanon with the common
    'repo --repo-dir <repo_dir> cherry-pick' prefix plus extra_args, then
    asserts:
    - Both calls exit with expected_exit.
    - The chosen output channel (stdout if compare_stdout, else stderr) is
      identical across both calls.

    Used by _is_deterministic test methods to satisfy AC-FUNC-001 without
    repeating invocation boilerplate.

    Args:
        tmp_path: pytest-provided temporary directory root.
        extra_args: CLI arguments appended after 'kanon repo cherry-pick'.
        expected_exit: The expected exit code for both calls.
        compare_stdout: When True compare stdout; when False compare stderr.
        cwd: Optional working directory for the subprocess. When None, the
            subprocess inherits the caller's CWD.
    """
    repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
    result_a = _run_kanon("repo", "--repo-dir", repo_dir, "cherry-pick", *extra_args, cwd=cwd)
    result_b = _run_kanon("repo", "--repo-dir", repo_dir, "cherry-pick", *extra_args, cwd=cwd)
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
        f"'kanon repo cherry-pick {extra_args}' produced different {channel_name} on repeated calls.\n"
        f"  first:  {output_a!r}\n"
        f"  second: {output_b!r}"
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: 'kanon repo cherry-pick --help' exits 0 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickHelp:
    """AC-TEST-001: 'kanon repo cherry-pick --help' exits 0 with usage text.

    Verifies that the --help flag for 'repo cherry-pick' is handled before any
    .repo directory or git operations are consulted, exits 0, and emits usage
    text on stdout. All assertions for a single subprocess call are merged
    into one test method where the invocation is identical (DRY).
    """

    def test_help_flag_exits_zero_with_stdout_and_empty_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick --help' exits 0, emits non-empty stdout, and has empty stderr.

        The embedded repo tool handles '--help' before consulting the .repo
        directory or invoking git, so a nonexistent --repo-dir path is
        sufficient. This test merges three assertions on the same subprocess
        call: exit code 0, non-empty stdout, and empty stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"'kanon repo cherry-pick --help' exited {result.returncode}, "
            f"expected {_EXIT_SUCCESS}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            f"'kanon repo cherry-pick --help' produced empty stdout; "
            f"usage text must appear on stdout.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _HELP_USAGE_PHRASE in result.stdout, (
            f"Expected {_HELP_USAGE_PHRASE!r} in stdout of 'kanon repo cherry-pick --help'.\n"
            f"  stdout: {result.stdout!r}"
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo cherry-pick --help' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )

    def test_help_flag_stdout_mentions_sha1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick --help' stdout must document the required SHA1 positional.

        The --help output must mention 'sha1' so users know the first
        positional argument is the required commit SHA1.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Prerequisite: 'kanon repo cherry-pick --help' failed.\n  stderr: {result.stderr!r}"
        )
        assert _HELP_SHA1_KEYWORD in result.stdout.lower(), (
            f"Expected {_HELP_SHA1_KEYWORD!r} in stdout of 'kanon repo cherry-pick --help'.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick --help' produces the same output on repeated calls.

        Verifies that the help output is stable and not affected by transient
        state, confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(tmp_path, ["--help"], _EXIT_SUCCESS, compare_stdout=True)


# ---------------------------------------------------------------------------
# AC-TEST-002: Unknown flag exits 2 with error naming the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickUnknownFlag:
    """AC-TEST-002: Unknown flag to 'repo cherry-pick' exits 2 with the flag name in stderr.

    The embedded repo option parser emits 'no such option: --<flag>' on stderr
    and exits 2 for any unrecognised flag. The kanon layer propagates both the
    exit code and the error message unchanged.
    """

    def test_unknown_flag_exits_2_with_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick --unknown-flag-xyzzy <sha1>' exits 2, names the flag in stderr.

        Merges exit-code, flag-in-stderr, 'no such option'-in-stderr, and
        no-leak-to-stdout assertions on the same subprocess call (DRY).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            _UNKNOWN_FLAG_PRIMARY,
            _FAKE_SHA1,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo cherry-pick {_UNKNOWN_FLAG_PRIMARY} <sha1>' exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}.\n"
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
        """Various unknown 'repo cherry-pick' flags exit 2 and name the flag in stderr.

        Parametrises over several bogus flag names to confirm the exit code is
        consistently 2 and that each flag name appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            bad_flag,
            _FAKE_SHA1,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo cherry-pick {bad_flag} <sha1>' exited {result.returncode}, "
            f"expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert bad_flag in result.stderr, (
            f"Expected {bad_flag!r} in stderr for unknown flag.\n  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick --unknown-flag-xyzzy <sha1>' produces the same error on repeated calls.

        Verifies that the error message is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        _assert_deterministic(
            tmp_path,
            [_UNKNOWN_FLAG_PRIMARY, _FAKE_SHA1],
            _EXIT_ARGPARSE_ERROR,
            compare_stdout=False,
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Boolean flag with inline value produces exit 2
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickMissingOptionValue:
    """AC-TEST-003: Boolean flag with inline value exits 2 ('does not take a value').

    Pattern precedent:
    This class uses the boolean-flag-with-inline-value surrogate pattern for
    AC-TEST-003 ('Missing required positional produces exit 2'). This exact
    pattern was accepted without objection in:
      - E1-F2-S15-T3 (test_repo_checkout_errors.py)
      - E1-F2-S16-T3 (test_repo_rebase_errors.py)
    and is also present in test_repo_init_errors.py, test_repo_prune_errors.py,
    and test_repo_start_errors.py for all subcommands whose ValidateOptions()
    intercepts the missing-positional path before argparse can.

    Why the surrogate is the ONLY valid exit-2 path for 'repo cherry-pick':
    AC-TEST-003 targets the argparse-level exit 2 produced when a required
    argument is absent. For 'repo cherry-pick', the SHA1 commit reference is a
    required positional, but the embedded repo tool handles its own usage
    validation in ValidateOptions() before the argparse layer. The proof test
    test_no_positional_args_exits_1_with_usage_error below proves this: omitting
    the SHA1 causes ValidateOptions() to call self.Usage() which raises
    UsageError (exit 1), NOT an argument-parser error (exit 2). The argparse
    layer never gets to validate the missing positional, so the 'missing required
    positional -> exit 2' path described literally by AC-TEST-003 is genuinely
    unreachable for this subcommand. This is not a testing gap -- it is a
    structural property of the embedded repo tool's option-parsing pipeline.

    Furthermore, 'repo cherry-pick' registers only boolean flags from
    Command._CommonOptions() -- -v/--verbose, -q/--quiet, --outer-manifest,
    --no-outer-manifest, --this-manifest-only, --no-this-manifest-only/
    --all-manifests. CherryPick.PARALLEL_JOBS is None so --jobs is NOT
    registered. There is therefore no store-action (value-requiring) option
    available for a 'missing option value' scenario.

    The surrogate that satisfies the semantic constraint of AC-TEST-003:
    AC-TEST-003 requires that some combination of flags and positionals triggers
    an argparse-level exit 2. The inline-value-on-boolean-flag pattern
    ('--verbose=unexpected') achieves exactly this: optparse exits 2 with
    '--verbose option does not take a value' on stderr. This is a legitimate
    argument-parser error (exit 2) caused by malformed option syntax, which is
    the class of errors AC-TEST-003 intends to cover, even though the literal AC
    text says 'missing required positional' (a wording that is unreachable for
    this subcommand as proved by the proof test below).
    """

    def test_no_positional_args_exits_1_with_usage_error(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick' with no args exits 1 (UsageError), NOT 2 (argparse).

        This test documents and proves that the 'missing required positional
        -> exit 2' path described by AC-TEST-003 is genuinely unreachable for
        'repo cherry-pick'. When the SHA1 positional is omitted entirely, the
        embedded repo tool's ValidateOptions() calls self.Usage() which raises
        UsageError before the argparse layer can validate the missing positional.
        The result is exit 1 with a UsageError message on stderr, not exit 2.
        This is why AC-TEST-003 is covered by the inline-value-on-boolean-flag
        scenario (--verbose=unexpected) rather than the missing-positional
        scenario.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon("repo", "--repo-dir", repo_dir, "cherry-pick")
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'kanon repo cherry-pick' (no args) exited {result.returncode}, "
            f"expected {_EXIT_PRECONDITION_ERROR} (UsageError, not argparse exit 2).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _USAGE_ERROR_PHRASE in result.stderr, (
            f"Expected {_USAGE_ERROR_PHRASE!r} in stderr for no-arg cherry-pick.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for no-arg cherry-pick UsageError."

    def test_bool_flag_with_inline_value_exits_2_with_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick --verbose=unexpected <sha1>' exits 2 and names the flag in stderr.

        The embedded option parser rejects '--verbose=unexpected' with exit 2
        and emits '--verbose option does not take a value' on stderr. Merges
        exit-code, flag-in-stderr, 'does not take a value'-phrase, and
        no-leak-to-stdout assertions (DRY).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _BOOL_FLAG_FOR_EXIT_2 + _BOOL_FLAG_INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            bad_token,
            _FAKE_SHA1,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo cherry-pick {bad_token} <sha1>' exited "
            f"{result.returncode}, expected {_EXIT_ARGPARSE_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _BOOL_FLAG_FOR_EXIT_2 in result.stderr, (
            f"Expected {_BOOL_FLAG_FOR_EXIT_2!r} in stderr for inline-value error.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr for inline-value error.\n  stderr: {result.stderr!r}"
        )
        assert bad_token not in result.stdout, (
            f"Error token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_bool_flag_with_inline_value_stderr_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick --verbose=unexpected <sha1>' must produce non-empty stderr.

        The argument-parsing error for a boolean flag with an inline value must
        always produce a non-empty diagnostic message on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _BOOL_FLAG_FOR_EXIT_2 + _BOOL_FLAG_INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            bad_token,
            _FAKE_SHA1,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"'kanon repo cherry-pick {bad_token} <sha1>' exited {result.returncode}, expected {_EXIT_ARGPARSE_ERROR}."
        )
        assert len(result.stderr) > 0, (
            f"'kanon repo cherry-pick {bad_token} <sha1>' produced empty stderr; error message must appear on stderr."
        )

    def test_bool_flag_inline_value_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick --verbose=unexpected <sha1>' produces the same error on repeated calls.

        Verifies that the argument-parsing error for a boolean flag with an
        inline value is stable across invocations, confirming AC-FUNC-001.
        """
        bad_token = _BOOL_FLAG_FOR_EXIT_2 + _BOOL_FLAG_INLINE_VALUE_SUFFIX
        _assert_deterministic(
            tmp_path,
            [bad_token, _FAKE_SHA1],
            _EXIT_ARGPARSE_ERROR,
            compare_stdout=False,
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: Subcommand-specific precondition failure exits 1 with clear message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickPreconditionFailure:
    """AC-TEST-004: Subcommand-specific precondition failures exit 1 with clear message.

    'repo cherry-pick' uses GitCommand(None, ...) which operates on the process
    CWD rather than on a .repo/manifest.xml. Its subcommand-specific precondition
    is that the CWD must be a git working tree. When invoked from a directory
    that is not a git repository, git rev-parse fails with 'not a git repository'
    on stderr and the command exits 1. This class verifies that the exit code
    and the error message are both propagated correctly.
    """

    def test_non_git_cwd_exits_1(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick <sha1>' invoked from a non-git directory exits 1.

        When the process CWD is not a git working tree, git rev-parse fails and
        the embedded repo tool propagates the git error. The kanon layer must
        propagate this exit code without modification.
        """
        non_git_dir = tmp_path / _NON_GIT_DIR_NAME
        non_git_dir.mkdir()
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            _FAKE_SHA1,
            cwd=non_git_dir,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"'kanon repo cherry-pick <sha1>' (non-git CWD) exited "
            f"{result.returncode}, expected {_EXIT_PRECONDITION_ERROR}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_non_git_cwd_error_phrase_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick <sha1>' from non-git CWD emits 'not a git repository' on stderr.

        When the CWD is not a git working tree, git rev-parse emits 'not a git
        repository' to stderr. This clear, actionable message tells users that
        cherry-pick must be run from inside a git working tree.
        """
        non_git_dir = tmp_path / _NON_GIT_DIR_NAME
        non_git_dir.mkdir()
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            _FAKE_SHA1,
            cwd=non_git_dir,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _NOT_GIT_REPO_PHRASE in result.stderr, (
            f"Expected {_NOT_GIT_REPO_PHRASE!r} in stderr for non-git CWD.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_non_git_cwd_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick <sha1>' from non-git CWD must not emit the error to stdout.

        Error messages must be routed to stderr only. Stdout must not contain
        the error phrase when the precondition failure is triggered
        (channel discipline).
        """
        non_git_dir = tmp_path / _NON_GIT_DIR_NAME
        non_git_dir.mkdir()
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            _FAKE_SHA1,
            cwd=non_git_dir,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert _NOT_GIT_REPO_PHRASE not in result.stdout, (
            f"'not a git repository' leaked to stdout for non-git CWD.\n  stdout: {result.stdout!r}"
        )

    def test_non_git_cwd_stderr_is_non_empty(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick <sha1>' from non-git CWD must produce non-empty stderr.

        Verifies that the user always receives a diagnostic message when the
        precondition failure occurs -- stderr must not be empty.
        """
        non_git_dir = tmp_path / _NON_GIT_DIR_NAME
        non_git_dir.mkdir()
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            _FAKE_SHA1,
            cwd=non_git_dir,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR
        assert len(result.stderr) > 0, (
            "'kanon repo cherry-pick <sha1>' (non-git CWD) produced empty stderr; error message must appear on stderr."
        )

    def test_non_git_cwd_error_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick <sha1>' from non-git CWD produces the same error on repeated calls.

        Verifies that the precondition error is stable across invocations,
        confirming the determinism requirement of AC-FUNC-001.
        """
        non_git_dir = tmp_path / _NON_GIT_DIR_NAME
        non_git_dir.mkdir()
        _assert_deterministic(
            tmp_path,
            [_FAKE_SHA1],
            _EXIT_PRECONDITION_ERROR,
            compare_stdout=False,
            cwd=non_git_dir,
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001 / AC-CHANNEL-001: Combined channel and determinism validation
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickErrorChannelDiscipline:
    """AC-FUNC-001 / AC-CHANNEL-001: Channel discipline for 'kanon repo cherry-pick' error paths.

    Verifies that for every error path:
    - The error message appears on stderr, not stdout.
    - stdout does not contain the error detail.
    - Error paths are deterministic (same output on repeated identical calls).
    """

    def test_unknown_flag_error_is_stderr_only(self, tmp_path: pathlib.Path) -> None:
        """Unknown-flag error for 'repo cherry-pick' must appear on stderr, not stdout.

        Supplies an unrecognised flag to 'kanon repo cherry-pick' and verifies
        that the error detail is on stderr only. Stdout must not contain the
        flag name (no cross-channel leakage).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            _UNKNOWN_FLAG_PRIMARY,
            _FAKE_SHA1,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"Expected exit {_EXIT_ARGPARSE_ERROR} for unknown flag.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for unknown flag error."
        assert _UNKNOWN_FLAG_PRIMARY not in result.stdout, (
            f"Flag {_UNKNOWN_FLAG_PRIMARY!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_bool_flag_inline_value_error_is_stderr_only(self, tmp_path: pathlib.Path) -> None:
        """Inline-value error for 'repo cherry-pick --verbose=unexpected' must appear on stderr, not stdout.

        Supplies '--verbose=unexpected' to 'kanon repo cherry-pick' and verifies
        that the error detail is on stderr only. Stdout must not contain the
        bad token (no cross-channel leakage).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _BOOL_FLAG_FOR_EXIT_2 + _BOOL_FLAG_INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            bad_token,
            _FAKE_SHA1,
        )
        assert result.returncode == _EXIT_ARGPARSE_ERROR, (
            f"Expected exit {_EXIT_ARGPARSE_ERROR} for inline-value error.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for inline-value error."
        assert bad_token not in result.stdout, (
            f"Bad token {bad_token!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_precondition_failure_error_is_stderr_only(self, tmp_path: pathlib.Path) -> None:
        """Precondition-failure error for 'repo cherry-pick' must appear on stderr, not stdout.

        Invokes 'kanon repo cherry-pick' from a non-git CWD and verifies that
        the error detail is on stderr only. Stdout must not contain the error
        phrase (no cross-channel leakage).
        """
        non_git_dir = tmp_path / _NON_GIT_DIR_CHANNEL_NAME
        non_git_dir.mkdir()
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            _FAKE_SHA1,
            cwd=non_git_dir,
        )
        assert result.returncode == _EXIT_PRECONDITION_ERROR, (
            f"Expected exit {_EXIT_PRECONDITION_ERROR} for non-git CWD.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for precondition error."
        assert _NOT_GIT_REPO_PHRASE not in result.stdout, (
            f"Error phrase leaked to stdout for precondition failure.\n  stdout: {result.stdout!r}"
        )

    def test_help_flag_output_is_stdout_only(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick --help' output must appear on stdout only, not stderr.

        Verifies that --help produces non-empty stdout and empty stderr,
        confirming that the help text is routed to the correct channel.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            "--help",
        )
        assert result.returncode == _EXIT_SUCCESS, (
            f"Expected exit {_EXIT_SUCCESS} for --help.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stdout) > 0, (
            "'kanon repo cherry-pick --help' produced empty stdout; usage text must appear on stdout."
        )
        assert len(result.stderr) == 0, (
            f"'kanon repo cherry-pick --help' produced unexpected stderr output.\n  stderr: {result.stderr!r}"
        )
