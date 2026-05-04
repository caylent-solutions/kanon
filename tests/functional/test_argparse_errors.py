"""Functional tests for argparse error surface across every kanon entry point.

Verifies that:
- Unknown flag '--xyz' exits 2 and stderr names the flag (AC-TEST-001).
- Invalid integer type '--jobs=abc' exits 2 with 'invalid int' in the error
  message (AC-TEST-002).
- Empty invocation 'kanon' exits 2 with usage text (AC-TEST-003).
- Unknown subcommand 'kanon foo' exits 2 with an error message (AC-TEST-004).
- The '--' sentinel forwards remaining args to the repo tool (AC-TEST-005).
- argparse produces deterministic, user-actionable messages for every error
  class (AC-FUNC-001).
- stdout vs stderr channel discipline is maintained (AC-CHANNEL-001).

All tests invoke kanon as a subprocess (no mocking of internal APIs).
Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import _run_kanon

# ---------------------------------------------------------------------------
# NOTE: _run_kanon is imported from tests.functional.conftest (canonical
# definition). No _git helper is needed for most tests here because argparse
# errors are triggered before any .repo directory is consulted.
#
# AC-TEST-005 and AC-TEST-002 require a nonexistent-path fixture so the repo
# tool's argument parser is invoked (the 'kanon repo' subcommand parses its
# remaining argv with the embedded repo option parser, which runs before
# consulting the .repo directory structure for argument-validation errors).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def nonexistent_repo_dir(tmp_path: pathlib.Path) -> str:
    """Return a guaranteed-nonexistent path under tmp_path for --repo-dir tests.

    The embedded repo tool parses its arguments before consulting the .repo
    directory, so tests that exercise argument-type validation supply this
    nonexistent sentinel to satisfy the --repo-dir argument without requiring
    a real .repo directory on disk.
    """
    return str(tmp_path / "nonexistent-argparse-errors-repo-dir")


# ---------------------------------------------------------------------------
# AC-TEST-001: Unknown flag '--xyz' exits 2 and stderr names the flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestUnknownFlagError:
    """AC-TEST-001: Unknown flag '--xyz' exits 2 and stderr names the flag."""

    def test_unknown_flag_exits_2(self) -> None:
        """'kanon --xyz' must exit with code 2 (argparse argument error)."""
        result = _run_kanon("--xyz")
        assert result.returncode == 2, (
            f"'kanon --xyz' exited {result.returncode}, expected 2.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_unknown_flag_names_the_flag_in_stderr(self) -> None:
        """'kanon --xyz' stderr must contain the unrecognised flag name '--xyz'."""
        result = _run_kanon("--xyz")
        assert result.returncode == 2
        assert "--xyz" in result.stderr, (
            f"Expected '--xyz' in stderr for unrecognised flag.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_unknown_flag_error_on_stderr(self) -> None:
        """'kanon --xyz' must write the error message to stderr, not stdout."""
        result = _run_kanon("--xyz")
        assert result.returncode == 2
        assert len(result.stderr) > 0, (
            f"'kanon --xyz' produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "unknown_flag",
        [
            "--xyz",
            "--not-a-real-flag",
            "--bogus-option",
        ],
    )
    def test_various_unknown_flags_exit_2(self, unknown_flag: str) -> None:
        """Various unknown top-level flags must all exit with code 2.

        Parametrises over several bogus flag names to confirm that the exit
        code is consistently 2 (argparse error) for every unrecognised flag.
        """
        result = _run_kanon(unknown_flag)
        assert result.returncode == 2, (
            f"'kanon {unknown_flag}' exited {result.returncode}, expected 2.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "unknown_flag",
        [
            "--xyz",
            "--not-a-real-flag",
            "--bogus-option",
        ],
    )
    def test_various_unknown_flags_name_flag_in_stderr(self, unknown_flag: str) -> None:
        """Various unknown flags must appear by name in stderr.

        Confirms that argparse includes the specific flag name in the error
        message so users receive an actionable diagnostic.
        """
        result = _run_kanon(unknown_flag)
        assert result.returncode == 2
        assert unknown_flag in result.stderr, (
            f"Expected {unknown_flag!r} in stderr for unrecognised flag.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Invalid type '--jobs=abc' exits 2 with 'invalid int' in message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestInvalidIntTypeError:
    """AC-TEST-002: '--jobs=abc' exits 2 with 'invalid int' in the error message.

    The '--jobs' flag is parsed by the embedded repo option parser for the
    'sync' subcommand. The repo tool exits 2 and emits an 'invalid integer
    value' message when the argument cannot be coerced to int. The kanon layer
    propagates the exit code and the error message unchanged.
    """

    def test_jobs_abc_exits_2(self, nonexistent_repo_dir: str) -> None:
        """'kanon repo sync --jobs=abc' must exit 2 (invalid int type error)."""
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            "sync",
            "--jobs=abc",
        )
        assert result.returncode == 2, (
            f"'kanon repo sync --jobs=abc' exited {result.returncode}, expected 2.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_jobs_abc_error_contains_invalid_int(self, nonexistent_repo_dir: str) -> None:
        """'kanon repo sync --jobs=abc' stderr must contain 'invalid int' text.

        The embedded repo option parser emits 'invalid integer value: ...' when
        a non-numeric value is supplied for --jobs. Verifies that the combined
        stderr output includes the phrase 'invalid int' so users know the value
        type is wrong.
        """
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            "sync",
            "--jobs=abc",
        )
        assert result.returncode == 2
        combined = result.stdout + result.stderr
        assert "invalid int" in combined.lower(), (
            f"Expected 'invalid int' in output for '--jobs=abc'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_jobs_abc_error_names_the_bad_value(self, nonexistent_repo_dir: str) -> None:
        """'kanon repo sync --jobs=abc' stderr must name the invalid value 'abc'.

        Verifies that the error message is specific enough to tell the user
        exactly which value was rejected.
        """
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            "sync",
            "--jobs=abc",
        )
        assert result.returncode == 2
        combined = result.stdout + result.stderr
        assert "abc" in combined, (
            f"Expected the bad value 'abc' to appear in the output.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "bad_value",
        [
            "abc",
            "notanumber",
            "one",
        ],
    )
    def test_jobs_various_non_int_values_exit_2(self, nonexistent_repo_dir: str, bad_value: str) -> None:
        """Various non-integer values for '--jobs' must all exit 2.

        Parametrises over several non-numeric values to confirm that the exit
        code is consistently 2 for every invalid integer argument.
        """
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            "sync",
            f"--jobs={bad_value}",
        )
        assert result.returncode == 2, (
            f"'kanon repo sync --jobs={bad_value}' exited {result.returncode}, expected 2.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Empty invocation 'kanon' exits 2 with usage text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestEmptyInvocationError:
    """AC-TEST-003: Empty invocation 'kanon' exits 2 with usage text."""

    def test_empty_invocation_exits_2(self) -> None:
        """'kanon' invoked with no arguments must exit with code 2."""
        result = _run_kanon()
        assert result.returncode == 2, (
            f"'kanon' with no arguments exited {result.returncode}, expected 2.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_empty_invocation_contains_usage(self) -> None:
        """'kanon' invoked with no arguments must produce output containing 'usage'.

        The help text printed by 'kanon' (no arguments) must include the word
        'usage' so users understand they need to supply a subcommand.
        """
        result = _run_kanon()
        assert result.returncode == 2
        combined = result.stdout + result.stderr
        assert "usage" in combined.lower(), (
            f"'kanon' output does not contain 'usage'.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_empty_invocation_lists_subcommands(self) -> None:
        """'kanon' with no arguments must list the available subcommands.

        Confirms that the help output is informative enough to tell users
        what subcommands are available.
        """
        result = _run_kanon()
        assert result.returncode == 2
        combined = result.stdout + result.stderr
        for subcommand in ("bootstrap", "install", "clean", "validate", "repo"):
            assert subcommand in combined, (
                f"'kanon' output does not mention subcommand {subcommand!r}.\n"
                f"  stdout: {result.stdout!r}\n"
                f"  stderr: {result.stderr!r}"
            )

    def test_empty_invocation_produces_non_empty_output(self) -> None:
        """'kanon' with no arguments must produce non-empty output (stdout or stderr)."""
        result = _run_kanon()
        assert result.returncode == 2
        combined = result.stdout + result.stderr
        assert len(combined) > 0, "'kanon' with no arguments produced empty output on both stdout and stderr."


# ---------------------------------------------------------------------------
# AC-TEST-004: Unknown subcommand 'kanon foo' exits 2 with error message
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestUnknownSubcommandError:
    """AC-TEST-004: Unknown subcommand 'kanon foo' exits 2 with an error message."""

    def test_unknown_subcommand_exits_2(self) -> None:
        """'kanon foo' must exit with code 2 (argparse subcommand error)."""
        result = _run_kanon("foo")
        assert result.returncode == 2, (
            f"'kanon foo' exited {result.returncode}, expected 2.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_unknown_subcommand_error_on_stderr(self) -> None:
        """'kanon foo' must write the error message to stderr."""
        result = _run_kanon("foo")
        assert result.returncode == 2
        assert len(result.stderr) > 0, (
            f"'kanon foo' produced empty stderr; error must appear on stderr.\n  stdout: {result.stdout!r}"
        )

    def test_unknown_subcommand_names_the_subcommand_in_stderr(self) -> None:
        """'kanon foo' stderr must contain the invalid subcommand name 'foo'."""
        result = _run_kanon("foo")
        assert result.returncode == 2
        assert "foo" in result.stderr, (
            f"Expected 'foo' in stderr for unknown subcommand.\n"
            f"  stderr: {result.stderr!r}\n"
            f"  stdout: {result.stdout!r}"
        )

    @pytest.mark.parametrize(
        "bad_subcommand",
        [
            "foo",
            "notacommand",
            "xyz123",
        ],
    )
    def test_various_unknown_subcommands_exit_2(self, bad_subcommand: str) -> None:
        """Various unknown subcommand names must all exit with code 2.

        Parametrises over several bogus subcommand names to confirm that the
        exit code is consistently 2 for every unrecognised top-level subcommand.
        """
        result = _run_kanon(bad_subcommand)
        assert result.returncode == 2, (
            f"'kanon {bad_subcommand}' exited {result.returncode}, expected 2.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "bad_subcommand",
        [
            "foo",
            "notacommand",
            "xyz123",
        ],
    )
    def test_various_unknown_subcommands_name_the_command_in_stderr(self, bad_subcommand: str) -> None:
        """Various unknown subcommands must appear by name in stderr.

        Confirms that argparse includes the specific subcommand name in the
        error message so users receive an actionable diagnostic.
        """
        result = _run_kanon(bad_subcommand)
        assert result.returncode == 2
        assert bad_subcommand in result.stderr, (
            f"Expected {bad_subcommand!r} in stderr for unknown subcommand.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-005: '--' sentinel for repo passthrough forwards remaining args
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestSentinelForwardsArgs:
    """AC-TEST-005: '--' sentinel forwards remaining args to the repo tool.

    The '--' separator causes kanon's argparse to stop consuming arguments;
    everything after it is forwarded verbatim to the repo tool. Tests here
    verify that forwarding is correct for both valid and invalid arguments,
    confirming that the sentinel does not silently drop or transform its
    trailing argv.
    """

    def test_sentinel_forwards_invalid_int_to_repo(self, nonexistent_repo_dir: str) -> None:
        """'kanon repo -- sync --jobs=abc' must still exit 2 for invalid int.

        When '--' is placed before 'sync --jobs=abc', the sentinel must not
        swallow the argument. The invalid integer value must reach the repo
        tool's argument parser, which exits 2 with an error message.
        """
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            "--",
            "sync",
            "--jobs=abc",
        )
        assert result.returncode == 2, (
            f"'kanon repo -- sync --jobs=abc' exited {result.returncode}, expected 2.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_sentinel_forwards_invalid_int_error_contains_invalid_int(self, nonexistent_repo_dir: str) -> None:
        """After '--', invalid '--jobs=abc' must produce 'invalid int' in the output.

        Confirms that the error message from the repo tool's argument parser
        propagates through the sentinel forwarding path unchanged.
        """
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            "--",
            "sync",
            "--jobs=abc",
        )
        assert result.returncode == 2
        combined = result.stdout + result.stderr
        assert "invalid int" in combined.lower(), (
            f"Expected 'invalid int' in output after '--' sentinel forwarding.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_sentinel_forwards_unknown_repo_subcommand(self, nonexistent_repo_dir: str) -> None:
        """'kanon repo -- no-such-subcommand' forwards the bogus subcommand.

        The '--' sentinel must not interpret or reject the trailing argv.
        An unknown subcommand name after '--' must reach the repo tool and
        produce the 'is not a repo command' error with exit code 1.
        """
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            "--",
            "no-such-subcommand-sentinel-test",
        )
        assert result.returncode == 1, (
            f"Expected exit code 1 for unknown repo subcommand after '--', "
            f"got {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert "is not a repo command" in result.stderr, (
            f"Expected 'is not a repo command' in stderr after '--' sentinel.\n  stderr: {result.stderr!r}"
        )

    def test_sentinel_with_no_trailing_args_forwards_empty_argv(self, nonexistent_repo_dir: str) -> None:
        """'kanon repo -- ' with nothing after '--' forwards an empty argv.

        When '--' is supplied with no trailing arguments, the repo tool
        receives an empty argv. For the 'sync' equivalent this results in a
        manifest parse error (not an argparse error), but the key assertion is
        that kanon itself does not exit 2 for a missing-subcommand argument
        error -- it delegates to the repo tool entirely.
        """
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            "--",
        )
        # The repo tool receives empty argv and may exit non-zero for any
        # reason; kanon must NOT intercept with its own exit code 2 (argparse).
        # The kanon argparse layer itself should not error out on an empty
        # remaining argv after '--'.
        assert result.returncode != 2 or "unrecognized arguments" not in result.stderr, (
            f"kanon's own argparse rejected '--' with empty trailing argv "
            f"as an unrecognised argument error (exit 2).\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: argparse produces deterministic, user-actionable error messages
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestDeterministicErrorMessages:
    """AC-FUNC-001: argparse produces deterministic, user-actionable error messages.

    Verifies that every error class always produces a non-empty error message
    on stderr and that messages are stable across repeated invocations.
    """

    def test_unknown_flag_message_is_stable(self) -> None:
        """'kanon --xyz' produces the same error message on repeated calls."""
        result_a = _run_kanon("--xyz")
        result_b = _run_kanon("--xyz")
        assert result_a.returncode == 2
        assert result_b.returncode == 2
        assert result_a.stderr == result_b.stderr, (
            f"'kanon --xyz' produced different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )

    def test_empty_invocation_message_is_stable(self) -> None:
        """'kanon' with no arguments produces the same output on repeated calls."""
        result_a = _run_kanon()
        result_b = _run_kanon()
        assert result_a.returncode == 2
        assert result_b.returncode == 2
        combined_a = result_a.stdout + result_a.stderr
        combined_b = result_b.stdout + result_b.stderr
        assert combined_a == combined_b, (
            f"'kanon' produced different output on repeated calls.\n  first:  {combined_a!r}\n  second: {combined_b!r}"
        )

    def test_unknown_subcommand_message_is_stable(self) -> None:
        """'kanon badsub' produces the same error message on repeated calls."""
        result_a = _run_kanon("badsub")
        result_b = _run_kanon("badsub")
        assert result_a.returncode == 2
        assert result_b.returncode == 2
        assert result_a.stderr == result_b.stderr, (
            f"'kanon badsub' produced different stderr on repeated calls.\n"
            f"  first:  {result_a.stderr!r}\n"
            f"  second: {result_b.stderr!r}"
        )

    def test_every_error_class_produces_non_empty_message(self, nonexistent_repo_dir: str) -> None:
        """Every argparse error class must produce a non-empty combined output.

        Exercises four distinct argparse error classes (unknown top-level flag,
        empty invocation, unknown subcommand, invalid int type) and asserts
        that each produces non-empty combined output so users always receive
        diagnostic text.
        """
        cases = [
            (("--xyz",), {}),
            ((), {}),
            (("badsub",), {}),
            (
                ("repo", "--repo-dir", nonexistent_repo_dir, "sync", "--jobs=abc"),
                {},
            ),
        ]
        for args, kwargs in cases:
            result = _run_kanon(*args, **kwargs)
            combined = result.stdout + result.stderr
            assert len(combined) > 0, (
                f"'kanon {list(args)}' produced empty output; expected a diagnostic message.\n"
                f"  returncode: {result.returncode}"
            )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline for error scenarios
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestErrorChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr discipline -- errors on stderr, not stdout.

    Verifies that argparse error output for unknown flags, unknown subcommands,
    and invalid-type arguments appears on stderr and does not bleed onto stdout.
    The empty-invocation case is the only exception: kanon calls
    parser.print_help() which writes to stdout by default (standard argparse
    behaviour).
    """

    def test_unknown_flag_error_not_on_stdout(self) -> None:
        """'kanon --xyz' must not leak the error message onto stdout."""
        result = _run_kanon("--xyz")
        assert result.returncode == 2
        assert len(result.stdout) == 0, f"'kanon --xyz' produced unexpected stdout output.\n  stdout: {result.stdout!r}"

    def test_unknown_subcommand_error_not_on_stdout(self) -> None:
        """'kanon foo' must not leak the error message onto stdout."""
        result = _run_kanon("foo")
        assert result.returncode == 2
        assert len(result.stdout) == 0, f"'kanon foo' produced unexpected stdout output.\n  stdout: {result.stdout!r}"

    def test_unknown_flag_error_on_stderr(self) -> None:
        """'kanon --xyz' must write its error message to stderr."""
        result = _run_kanon("--xyz")
        assert result.returncode == 2
        assert len(result.stderr) > 0, (
            f"'kanon --xyz' produced empty stderr; argparse error must appear on stderr.\n  stdout: {result.stdout!r}"
        )

    def test_unknown_subcommand_error_on_stderr(self) -> None:
        """'kanon foo' must write its error message to stderr."""
        result = _run_kanon("foo")
        assert result.returncode == 2
        assert len(result.stderr) > 0, (
            f"'kanon foo' produced empty stderr; argparse error must appear on stderr.\n  stdout: {result.stdout!r}"
        )

    def test_invalid_int_error_on_stderr(self, nonexistent_repo_dir: str) -> None:
        """'kanon repo sync --jobs=abc' must surface the error on stderr."""
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            "sync",
            "--jobs=abc",
        )
        assert result.returncode == 2
        assert len(result.stderr) > 0, (
            f"'kanon repo sync --jobs=abc' produced empty stderr; error must appear on stderr.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_invalid_int_error_not_on_stdout(self, nonexistent_repo_dir: str) -> None:
        """'kanon repo sync --jobs=abc' must not leak the error message onto stdout."""
        result = _run_kanon(
            "repo",
            "--repo-dir",
            nonexistent_repo_dir,
            "sync",
            "--jobs=abc",
        )
        assert result.returncode == 2
        assert len(result.stdout) == 0, (
            f"'kanon repo sync --jobs=abc' produced unexpected stdout output.\n  stdout: {result.stdout!r}"
        )

    def test_empty_invocation_writes_usage_to_stdout(self) -> None:
        """'kanon' with no arguments must write usage help text to stdout.

        argparse's print_help() writes to stdout by default. The empty
        invocation handler calls parser.print_help() before exiting 2, so
        the usage text must appear on stdout (not stderr). This is standard
        argparse behaviour for the no-subcommand case.
        """
        result = _run_kanon()
        assert result.returncode == 2
        assert len(result.stdout) > 0, (
            f"'kanon' with no arguments produced empty stdout; usage help must appear on stdout.\n"
            f"  stderr: {result.stderr!r}"
        )
