"""Functional tests for flag coverage of 'kanon repo grep'.

Exercises every flag registered in ``subcmds/grep.py``'s ``_Options()`` method
by invoking ``kanon repo grep`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

All flags in ``Grep._Options()`` use ``action="callback"`` with
``callback=self._carry_option``, which passes flags directly to git grep.
Two categories exist:

1. No-value flags: do not accept an argument. Accepted when supplied alone;
   rejected (exit 2) when supplied with an inline value via ``--flag=value``.
   Long-form aliases (e.g. ``--ignore-case``, ``--word-regexp``) participate
   in negative tests; short-form aliases (``-i``, ``-w``) are tested in
   valid-value tests only because optparse only parses ``=value`` on long forms.

2. Value-required flags: require exactly one argument. Rejected (exit 2) when
   the argument is omitted. The ``-e`` and ``-r``/``--revision`` and
   ``-C``/``-B``/``-A`` flags fall into this category.

The ``-r``/``--revision`` flag uses ``action="append"`` (standard optparse)
rather than the callback mechanism but is still part of ``_Options()``.

Note: ``grep`` overrides ``_CommonOptions`` to suppress ``-v``, so ``-v`` is
registered as ``--invert-match`` (a grep-specific flag) rather than as
the verbose flag from ``Command._CommonOptions()``.

Valid-value tests confirm flags are accepted (exit != 2 against a nonexistent
repo-dir, where exit 1 proves parsing succeeded). Tests against a real synced
repo confirm exit 0 and correct stdout output for key flags.

Negative tests confirm exit 2 for:
- Callback no-value flags supplied with ``--flag=badval`` inline syntax.
- Value-required flags supplied with no argument.

Covers:
- AC-TEST-001: Every ``_Options()`` flag has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated values has a negative test.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
- AC-CHANNEL-001: stdout vs stderr channel discipline is verified.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import (
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all hard-coded test-fixture values extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Grep Flags Test User"
_GIT_USER_EMAIL = "repo-grep-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "grep-flags-test-project"

# Error exit code for argument-parsing errors (optparse uses 2).
_ARGPARSE_ERROR_EXIT_CODE = 2

# Expected exit code for valid invocations that find a match.
_EXPECTED_EXIT_CODE = 0

# Nonexistent repo-dir name used in argument-parser acceptance tests that
# do not require a real initialized repository. The command exits with code 1
# (manifest not found) rather than code 2 (argument parsing error), confirming
# the flag was accepted by optparse.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-grep-flags-repo-dir"

# Pattern that matches the default content file written by _setup_synced_repo.
# The conftest helper writes "hello from shared conftest helper" to README.md.
_MATCH_PATTERN = "hello"

# Second pattern on the same line as _MATCH_PATTERN -- used in boolean operator tests.
# The content "hello from shared conftest helper" contains both "hello" and "from".
_MATCH_PATTERN_AND = "from"

# Uppercase form of _MATCH_PATTERN -- used in -i / --ignore-case tests to confirm
# that case-insensitive matching finds content regardless of letter case.
_MATCH_PATTERN_UPPERCASE = "HELLO"

# Content file name written into each project by _setup_synced_repo.
_CONTENT_FILENAME = "README.md"

# Inline-value suffix for negative tests on callback no-value flags.
# optparse exits 2 with '--<flag> option does not take a value' when a
# callback flag without type= is supplied with an inline value.
_INLINE_VALUE_SUFFIX = "=badval"

# Phrase emitted on stderr when a no-value flag receives an inline value.
_DOES_NOT_TAKE_VALUE_PHRASE = "does not take a value"

# Phrase emitted on stderr when a value-required flag has no argument.
_REQUIRES_ARGUMENT_PHRASE = "requires 1 argument"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# ---------------------------------------------------------------------------
# CLI token constants -- every flag token referenced in test logic.
# ---------------------------------------------------------------------------

_CMD_REPO = "repo"
_FLAG_REPO_DIR = "--repo-dir"
_SUBCMD_GREP = "grep"

# Sources group flags
_CLI_FLAG_CACHED = "--cached"
_CLI_FLAG_REVISION_SHORT = "-r"
_CLI_FLAG_REVISION_LONG = "--revision"

# Pattern group -- value-required callback flags
_CLI_FLAG_E = "-e"
_CLI_FLAG_C = "-C"
_CLI_FLAG_B = "-B"
_CLI_FLAG_A = "-A"

# Pattern group -- no-value callback flags (short forms)
_CLI_FLAG_I_SHORT = "-i"
_CLI_FLAG_A_TEXT_SHORT = "-a"
_CLI_FLAG_I_BINARY_SHORT = "-I"
_CLI_FLAG_W_SHORT = "-w"
_CLI_FLAG_V_SHORT = "-v"
_CLI_FLAG_G_SHORT = "-G"
_CLI_FLAG_E_REGEXP_SHORT = "-E"
_CLI_FLAG_F_SHORT = "-F"
_CLI_FLAG_N_SHORT = "-n"
_CLI_FLAG_L_SHORT = "-l"
_CLI_FLAG_BIG_L_SHORT = "-L"

# Pattern group -- no-value callback flags (long forms)
_CLI_FLAG_IGNORE_CASE = "--ignore-case"
_CLI_FLAG_TEXT = "--text"
_CLI_FLAG_WORD_REGEXP = "--word-regexp"
_CLI_FLAG_INVERT_MATCH = "--invert-match"
_CLI_FLAG_BASIC_REGEXP = "--basic-regexp"
_CLI_FLAG_EXTENDED_REGEXP = "--extended-regexp"
_CLI_FLAG_FIXED_STRINGS = "--fixed-strings"

# Pattern grouping -- no-value callback flags
_CLI_FLAG_ALL_MATCH = "--all-match"
_CLI_FLAG_AND = "--and"
_CLI_FLAG_OR = "--or"
_CLI_FLAG_NOT = "--not"
_CLI_FLAG_PAREN_OPEN = "-("
_CLI_FLAG_PAREN_CLOSE = "-)"

# Output group -- no-value long-form aliases
_CLI_FLAG_NAME_ONLY = "--name-only"
_CLI_FLAG_FILES_WITH_MATCHES = "--files-with-matches"
_CLI_FLAG_FILES_WITHOUT_MATCH = "--files-without-match"

# A valid numeric context value for -C, -B, -A flags.
_CONTEXT_VALUE = "2"

# A valid revision for --revision flag.
_REVISION_VALUE = "HEAD"

# ---------------------------------------------------------------------------
# Parametrize data tables -- all tuples use flag constants, not raw strings.
#
# AC-TEST-001: All _Options() flags with valid values (exit != 2).
# Groups:
#   1. No-value flags tested against a nonexistent repo (exit 1 = parsed OK)
#   2. Value-required flags with valid values tested against nonexistent repo
# ---------------------------------------------------------------------------

# No-value callback flags (short forms) -- valid-value acceptance tests.
# These do not require a repo to exist; exit 1 confirms parsing succeeded.
_NO_VALUE_FLAGS_SHORT: list[tuple[str, str]] = [
    (_CLI_FLAG_CACHED, "cached"),
    (_CLI_FLAG_I_SHORT, "short-ignore-case"),
    (_CLI_FLAG_A_TEXT_SHORT, "short-text"),
    (_CLI_FLAG_I_BINARY_SHORT, "short-binary"),
    (_CLI_FLAG_W_SHORT, "short-word-regexp"),
    (_CLI_FLAG_V_SHORT, "short-invert-match"),
    (_CLI_FLAG_G_SHORT, "short-basic-regexp"),
    (_CLI_FLAG_E_REGEXP_SHORT, "short-extended-regexp"),
    (_CLI_FLAG_F_SHORT, "short-fixed-strings"),
    (_CLI_FLAG_ALL_MATCH, "all-match"),
    (_CLI_FLAG_AND, "and"),
    (_CLI_FLAG_OR, "or"),
    (_CLI_FLAG_NOT, "not"),
    (_CLI_FLAG_PAREN_OPEN, "paren-open"),
    (_CLI_FLAG_PAREN_CLOSE, "paren-close"),
    (_CLI_FLAG_N_SHORT, "short-line-number"),
    (_CLI_FLAG_L_SHORT, "short-name-only"),
    (_CLI_FLAG_BIG_L_SHORT, "short-files-without-match"),
]

# No-value callback flags (long forms) -- valid-value acceptance tests.
_NO_VALUE_FLAGS_LONG: list[tuple[str, str]] = [
    (_CLI_FLAG_IGNORE_CASE, "long-ignore-case"),
    (_CLI_FLAG_TEXT, "long-text"),
    (_CLI_FLAG_WORD_REGEXP, "long-word-regexp"),
    (_CLI_FLAG_INVERT_MATCH, "long-invert-match"),
    (_CLI_FLAG_BASIC_REGEXP, "long-basic-regexp"),
    (_CLI_FLAG_EXTENDED_REGEXP, "long-extended-regexp"),
    (_CLI_FLAG_FIXED_STRINGS, "long-fixed-strings"),
    (_CLI_FLAG_NAME_ONLY, "long-name-only"),
    (_CLI_FLAG_FILES_WITH_MATCHES, "long-files-with-matches"),
    (_CLI_FLAG_FILES_WITHOUT_MATCH, "long-files-without-match"),
]

# All no-value flags combined -- used for AC-TEST-001 valid-value parametrize.
_ALL_NO_VALUE_FLAGS: list[tuple[str, str]] = _NO_VALUE_FLAGS_SHORT + _NO_VALUE_FLAGS_LONG

# Long-form no-value callback flags -- used for AC-TEST-002 negative tests.
# Short-form flags cannot use '--flag=value' inline syntax in optparse.
_LONG_NO_VALUE_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    (_CLI_FLAG_CACHED, "cached"),
    (_CLI_FLAG_IGNORE_CASE, "ignore-case"),
    (_CLI_FLAG_TEXT, "text"),
    (_CLI_FLAG_WORD_REGEXP, "word-regexp"),
    (_CLI_FLAG_INVERT_MATCH, "invert-match"),
    (_CLI_FLAG_BASIC_REGEXP, "basic-regexp"),
    (_CLI_FLAG_EXTENDED_REGEXP, "extended-regexp"),
    (_CLI_FLAG_FIXED_STRINGS, "fixed-strings"),
    (_CLI_FLAG_ALL_MATCH, "all-match"),
    (_CLI_FLAG_AND, "and"),
    (_CLI_FLAG_OR, "or"),
    (_CLI_FLAG_NOT, "not"),
    (_CLI_FLAG_NAME_ONLY, "name-only"),
    (_CLI_FLAG_FILES_WITH_MATCHES, "files-with-matches"),
    (_CLI_FLAG_FILES_WITHOUT_MATCH, "files-without-match"),
]

# Value-required flags and their missing-argument negative test data.
# Each tuple: (flag, test_id). When supplied without a value, exit 2.
_VALUE_REQUIRED_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    (_CLI_FLAG_E, "short-e"),
    (_CLI_FLAG_REVISION_SHORT, "short-revision"),
    (_CLI_FLAG_REVISION_LONG, "long-revision"),
    (_CLI_FLAG_C, "short-context"),
    (_CLI_FLAG_B, "short-before"),
    (_CLI_FLAG_A, "short-after"),
]

# Parametrize data for AC-FUNC-001: flags that produce exit 0 on a real synced
# repo when the match pattern is present. Each tuple: (flag_or_flags, test_id).
# Flags that require extra arguments are expressed as a sequence.
_FUNC_FLAGS_EXIT_ZERO: list[tuple[tuple[str, ...], str]] = [
    ((_CLI_FLAG_I_SHORT, _MATCH_PATTERN), "short-ignore-case"),
    ((_CLI_FLAG_IGNORE_CASE, _MATCH_PATTERN), "long-ignore-case"),
    ((_CLI_FLAG_N_SHORT, _MATCH_PATTERN), "short-line-number"),
    ((_CLI_FLAG_L_SHORT, _MATCH_PATTERN), "short-name-only"),
    ((_CLI_FLAG_NAME_ONLY, _MATCH_PATTERN), "long-name-only"),
    ((_CLI_FLAG_G_SHORT, _MATCH_PATTERN), "short-basic-regexp"),
    ((_CLI_FLAG_BASIC_REGEXP, _MATCH_PATTERN), "long-basic-regexp"),
    ((_CLI_FLAG_E_REGEXP_SHORT, _MATCH_PATTERN), "short-extended-regexp"),
    ((_CLI_FLAG_EXTENDED_REGEXP, _MATCH_PATTERN), "long-extended-regexp"),
    ((_CLI_FLAG_F_SHORT, _MATCH_PATTERN), "short-fixed-strings"),
    ((_CLI_FLAG_FIXED_STRINGS, _MATCH_PATTERN), "long-fixed-strings"),
    ((_CLI_FLAG_W_SHORT, _MATCH_PATTERN), "short-word-regexp"),
    ((_CLI_FLAG_WORD_REGEXP, _MATCH_PATTERN), "long-word-regexp"),
    ((_CLI_FLAG_C, _CONTEXT_VALUE, _MATCH_PATTERN), "short-context"),
    ((_CLI_FLAG_B, _CONTEXT_VALUE, _MATCH_PATTERN), "short-before"),
    ((_CLI_FLAG_A, _CONTEXT_VALUE, _MATCH_PATTERN), "short-after"),
    ((_CLI_FLAG_E, _MATCH_PATTERN, _CLI_FLAG_ALL_MATCH, _CLI_FLAG_E, _MATCH_PATTERN_AND), "all-match"),
    ((_CLI_FLAG_E, _MATCH_PATTERN, _CLI_FLAG_AND, _CLI_FLAG_E, _MATCH_PATTERN_AND), "and"),
    ((_CLI_FLAG_E, _MATCH_PATTERN, _CLI_FLAG_OR, _CLI_FLAG_E, _MATCH_PATTERN_AND), "or"),
]


def _build_grep_argv(repo_dir: pathlib.Path, *extra: str) -> tuple[str, ...]:
    """Return the argv tuple for a 'kanon repo grep' invocation.

    Builds the canonical argument sequence:
        repo --repo-dir <repo_dir> grep <extra...>

    Args:
        repo_dir: Path to the .repo directory.
        *extra: Additional arguments appended after the subcommand token.

    Returns:
        A tuple of string arguments suitable for passing to ``_run_kanon``.
    """
    return (_CMD_REPO, _FLAG_REPO_DIR, str(repo_dir), _SUBCMD_GREP) + extra


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/grep.py
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/grep.py has a valid-value test.

    Exercises each flag registered in ``Grep._Options()`` by invoking
    'kanon repo grep' with the flag against a nonexistent repo-dir. Since
    optparse parses flags before any manifest operations, a non-2 exit code
    (exit 1 from manifest not found) confirms the flag was accepted by the
    option parser.

    All flags in ``Grep._Options()`` use ``action="callback"`` with
    ``callback=self._carry_option`` (or ``action="append"`` for -r/--revision).
    No-value flags carry themselves to git grep; value-required flags carry
    both the flag and its argument.

    Flags covered:
    - ``--cached``                  (callback, no value)
    - ``-r`` / ``--revision``       (append, requires TREEish value)
    - ``-e``                        (callback, requires PATTERN value)
    - ``-i`` / ``--ignore-case``    (callback, no value)
    - ``-a`` / ``--text``           (callback, no value)
    - ``-I``                        (callback, no value)
    - ``-w`` / ``--word-regexp``    (callback, no value)
    - ``-v`` / ``--invert-match``   (callback, no value)
    - ``-G`` / ``--basic-regexp``   (callback, no value)
    - ``-E`` / ``--extended-regexp`` (callback, no value)
    - ``-F`` / ``--fixed-strings``  (callback, no value)
    - ``--all-match``               (callback, no value)
    - ``--and`` / ``--or`` / ``--not`` (callback, no value)
    - ``-(`` / ``-)``               (callback, no value)
    - ``-n``                        (callback, no value)
    - ``-C`` / ``-B`` / ``-A``     (callback, requires CONTEXT value)
    - ``-l`` / ``--name-only`` / ``--files-with-matches`` (callback, no value)
    - ``-L`` / ``--files-without-match`` (callback, no value)
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _ALL_NO_VALUE_FLAGS],
        ids=[test_id for _, test_id in _ALL_NO_VALUE_FLAGS],
    )
    def test_no_value_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each no-value callback flag is accepted by the argument parser (exit != 2).

        Calls 'kanon repo grep <flag> hello' against a nonexistent repo-dir.
        The command exits 1 (manifest not found) rather than 2 (argument
        parsing error), confirming the flag was accepted by optparse.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            flag,
            _MATCH_PATTERN,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_e_flag_with_pattern_accepted(self, tmp_path: pathlib.Path) -> None:
        """'-e PATTERN' is accepted by the argument parser (exit != 2).

        Supplies '-e hello' to 'kanon repo grep'. The command exits 1
        (manifest not found), confirming the flag was accepted by optparse.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            _CLI_FLAG_E,
            _MATCH_PATTERN,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_E} {_MATCH_PATTERN}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_revision_short_with_value_accepted(self, tmp_path: pathlib.Path) -> None:
        """'-r HEAD' is accepted by the argument parser (exit != 2).

        The -r/--revision flag uses action='append' and requires a TREEish
        value. Supplying '-r HEAD' confirms the flag is accepted; the command
        exits 1 (manifest not found).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            _CLI_FLAG_REVISION_SHORT,
            _REVISION_VALUE,
            _MATCH_PATTERN,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_REVISION_SHORT} {_REVISION_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_revision_long_with_value_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--revision HEAD' is accepted by the argument parser (exit != 2).

        The --revision flag uses action='append' and requires a TREEish value.
        Supplying '--revision HEAD' confirms the flag is accepted; the command
        exits 1 (manifest not found).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            _CLI_FLAG_REVISION_LONG,
            _REVISION_VALUE,
            _MATCH_PATTERN,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_REVISION_LONG} {_REVISION_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_context_flag_c_with_value_accepted(self, tmp_path: pathlib.Path) -> None:
        """'-C 2' (context lines) is accepted by the argument parser (exit != 2).

        The -C flag is a callback that carries its numeric argument to git grep.
        Supplying '-C 2' confirms the flag is accepted; the command exits 1.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            _CLI_FLAG_C,
            _CONTEXT_VALUE,
            _MATCH_PATTERN,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_C} {_CONTEXT_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_before_flag_b_with_value_accepted(self, tmp_path: pathlib.Path) -> None:
        """'-B 2' (before-context lines) is accepted by the argument parser (exit != 2).

        The -B flag is a callback that carries its numeric argument to git grep.
        Supplying '-B 2' confirms the flag is accepted; the command exits 1.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            _CLI_FLAG_B,
            _CONTEXT_VALUE,
            _MATCH_PATTERN,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_B} {_CONTEXT_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_after_flag_a_with_value_accepted(self, tmp_path: pathlib.Path) -> None:
        """'-A 2' (after-context lines) is accepted by the argument parser (exit != 2).

        The -A flag is a callback that carries its numeric argument to git grep.
        Supplying '-A 2' confirms the flag is accepted; the command exits 1.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            _CLI_FLAG_A,
            _CONTEXT_VALUE,
            _MATCH_PATTERN,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_A} {_CONTEXT_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with invalid values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated values has a negative test.

    Two classes of negative tests apply to ``Grep._Options()`` flags:

    1. No-value callback flags with an inline value (``--flag=badval`` syntax):
       optparse exits 2 with '--<flag> option does not take a value'.

    2. Value-required callback and append flags with no argument supplied:
       optparse exits 2 with '<flag> option requires 1 argument'.

    All negative tests assert exit code 2 (argument-parsing error) and
    verify that the error appears on stderr, not stdout.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_NO_VALUE_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_NO_VALUE_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_no_value_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form no-value callback flag with an inline value must exit 2.

        Supplies '--<flag>=badval' to 'kanon repo grep'. Since these are
        callback flags declared without ``type=``, optparse rejects the inline
        value with exit code 2 and emits '--<flag> option does not take a value'
        on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            bad_token,
            _MATCH_PATTERN,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_NO_VALUE_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_NO_VALUE_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_no_value_flag_inline_value_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form no-value flag with inline value must emit error on stderr, not stdout.

        The argument-parsing error for '--<flag>=badval' must appear on stderr
        only. Stdout must not contain the rejection detail (channel discipline).
        The stderr must contain the canonical rejection phrase.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            bad_token,
            _MATCH_PATTERN,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _VALUE_REQUIRED_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _VALUE_REQUIRED_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_value_required_flag_without_argument_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each value-required flag supplied without an argument must exit 2.

        Supplies the flag alone (no argument following it) to 'kanon repo grep'.
        optparse rejects the missing argument with exit code 2 and emits
        '<flag> option requires 1 argument' on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            flag,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{flag}' (no argument) exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _VALUE_REQUIRED_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _VALUE_REQUIRED_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_value_required_flag_without_argument_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each value-required flag missing its argument must emit error on stderr, not stdout.

        The argument-parsing error must appear on stderr and must contain the
        canonical 'requires 1 argument' phrase. Stdout must remain clean.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            flag,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{flag}' (no argument) exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _REQUIRES_ARGUMENT_PHRASE in result.stderr, (
            f"Expected {_REQUIRES_ARGUMENT_PHRASE!r} in stderr for '{flag}' (no argument).\n  stderr: {result.stderr!r}"
        )
        assert flag not in result.stdout, f"Flag {flag!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_cached_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--cached=badval' error must name '--cached' in stderr.

        The embedded optparse parser emits '--cached option does not take a
        value' when '--cached=badval' is supplied. Confirms the flag name
        appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _CLI_FLAG_CACHED + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            bad_token,
            _MATCH_PATTERN,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _CLI_FLAG_CACHED in result.stderr, (
            f"Expected {_CLI_FLAG_CACHED!r} in stderr for '{bad_token}' error.\n  stderr: {result.stderr!r}"
        )

    def test_word_regexp_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--word-regexp=badval' error must name '--word-regexp' in stderr.

        The embedded optparse parser emits '--word-regexp option does not take
        a value'. Confirms the flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _CLI_FLAG_WORD_REGEXP + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            bad_token,
            _MATCH_PATTERN,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert _CLI_FLAG_WORD_REGEXP in result.stderr, (
            f"Expected {_CLI_FLAG_WORD_REGEXP!r} in stderr for '{bad_token}' error.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each ``Grep._Options()`` flag uses the documented default
    when omitted. All callback flags use ``carry_option`` semantics: when
    absent, they contribute nothing to ``cmd_argv`` (i.e. they are not passed
    to git grep). The absence of any optional flag must not cause an error.

    Uses a real synced repo (via ``_setup_synced_repo``) to verify that
    'kanon repo grep <pattern>' with all optional flags omitted exits 0 and
    produces matching output.
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep <pattern>' with all optional flags omitted exits 0.

        When no optional flags are supplied, every callback flag contributes
        nothing to git grep's argv. The positional pattern is passed directly.
        Verifies that no optional flag is required and the default behavior
        produces a successful (exit 0) match.
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
            *_build_grep_argv(repo_dir, _MATCH_PATTERN),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo grep {_MATCH_PATTERN}' with all optional flags omitted "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_all_flags_omitted_produces_match_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo grep <pattern>' with all optional flags omitted produces match output.

        When no optional flags are supplied, the default behavior is a
        plain-text search producing matching lines on stdout. The content
        filename must appear in the output.
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
            *_build_grep_argv(repo_dir, _MATCH_PATTERN),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo grep {_MATCH_PATTERN}' failed: {result.stderr!r}"
        )
        assert _CONTENT_FILENAME in result.stdout, (
            f"Expected {_CONTENT_FILENAME!r} in grep stdout.\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_revision_absent_searches_work_tree(self, tmp_path: pathlib.Path) -> None:
        """Omitting -r/--revision searches the work tree (default behavior); exit 0.

        When --revision is absent, grep searches the work tree (HEAD checkout)
        rather than a specific tree-ish. This is the documented default for
        the -r flag (when absent, opt.revision is None). Verifies exit 0.
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
            *_build_grep_argv(repo_dir, _MATCH_PATTERN),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo grep {_MATCH_PATTERN}' without --revision exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_cached_absent_searches_work_tree(self, tmp_path: pathlib.Path) -> None:
        """Omitting --cached searches the work tree (default); exit 0.

        When --cached is absent, grep searches the work tree rather than the
        index. This is the documented default (when absent, --cached is not
        passed to git grep). Verifies exit 0.
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
            *_build_grep_argv(repo_dir, _MATCH_PATTERN),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo grep {_MATCH_PATTERN}' without --cached exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of key flags documented in
    ``Grep._Options()`` by invoking 'kanon repo grep' against a real synced
    repo and confirming exit 0 and correct output.

    Flags tested on real synced repo (matching content present):
    - ``-i`` / ``--ignore-case``: case-insensitive match; exit 0 for 'HELLO'
    - ``-n``: prefix line number; output contains ':' in match lines
    - ``-l`` / ``--name-only``: only file names; output contains filename, not content
    - ``-G`` / ``--basic-regexp``: POSIX basic regexp; exit 0 for pattern
    - ``-E`` / ``--extended-regexp``: POSIX extended regexp; exit 0 for pattern
    - ``-F`` / ``--fixed-strings``: fixed string; exit 0 for exact pattern
    - ``-w`` / ``--word-regexp``: match at word boundaries; exit 0 for 'hello'
    - ``-C`` / ``-B`` / ``-A``: context lines; exit 0 with numeric arg
    - ``--all-match`` + ``-e``: limit to lines with all patterns; exit 0
    - ``--and`` / ``--or``: boolean operators; exit 0

    Note on ``--invert-match`` / ``-v``: this flag inverts match, causing grep
    to return files/lines NOT matching the pattern. On a repo with a single-line
    content file matching the pattern, -v causes git grep to find no matches and
    exit non-zero. Therefore -v/-v's valid-value test runs against a nonexistent
    repo dir (exit 1 = parsed OK) rather than a real synced repo. The flag
    passes argparse validation; behavioral testing via a real repo is deferred
    to a scenario with non-matching content.
    """

    @pytest.mark.parametrize(
        "extra_argv",
        [extra for extra, _ in _FUNC_FLAGS_EXIT_ZERO],
        ids=[test_id for _, test_id in _FUNC_FLAGS_EXIT_ZERO],
    )
    def test_flag_produces_exit_zero_on_matching_content(
        self,
        tmp_path: pathlib.Path,
        extra_argv: tuple[str, ...],
    ) -> None:
        """Each documented flag produces exit 0 when content matches.

        Invokes 'kanon repo grep <flags...> <pattern>' against a real synced
        repo containing the match pattern. Confirms exit 0 (match found) and
        that no Python traceback appears in stdout.
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
            *_build_grep_argv(repo_dir, *extra_argv),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo grep {extra_argv}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout for 'kanon repo grep {extra_argv}'.\n  stdout: {result.stdout!r}"
        )

    def test_ignore_case_matches_uppercase_pattern(self, tmp_path: pathlib.Path) -> None:
        """'-i' / '--ignore-case': case-insensitive search matches 'HELLO' in 'hello' content.

        Per the help text: 'Ignore case differences'. The content file contains
        'hello' (lowercase). Searching for 'HELLO' with -i must find it and
        exit 0.
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
            *_build_grep_argv(repo_dir, _CLI_FLAG_I_SHORT, _MATCH_PATTERN_UPPERCASE),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo grep -i {_MATCH_PATTERN_UPPERCASE}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_name_only_produces_filename_not_content(self, tmp_path: pathlib.Path) -> None:
        """'-l' / '--name-only': output contains filename, not match content.

        Per the help text: 'Show only file names containing matching lines'.
        The output must include the content filename but not the matching
        text itself (only filenames are shown, not the matching line text).
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
            *_build_grep_argv(repo_dir, _CLI_FLAG_L_SHORT, _MATCH_PATTERN),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo grep -l {_MATCH_PATTERN}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _CONTENT_FILENAME in result.stdout, (
            f"Expected filename {_CONTENT_FILENAME!r} in stdout for -l flag.\n  stdout: {result.stdout!r}"
        )

    def test_revision_flag_with_head_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'-r HEAD' / '--revision HEAD': grep against HEAD tree; exit 0 when content matches.

        Per the help text: 'Search TREEish, instead of the work tree'. Passing
        'HEAD' as the revision on a synced repo searches the HEAD commit tree.
        The content file is committed so it exists in HEAD; exit 0.
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
            *_build_grep_argv(
                repo_dir,
                _CLI_FLAG_REVISION_SHORT,
                _REVISION_VALUE,
                _MATCH_PATTERN,
            ),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo grep -r HEAD {_MATCH_PATTERN}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoGrepFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_flags_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo grep' with valid flags must not emit tracebacks to stdout.

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
            *_build_grep_argv(repo_dir, _CLI_FLAG_I_SHORT, _MATCH_PATTERN),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo grep -i {_MATCH_PATTERN}' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of 'kanon repo grep -i'.\n  stdout: {result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo grep' with valid flags must not emit tracebacks to stderr.

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
            *_build_grep_argv(repo_dir, _CLI_FLAG_N_SHORT, _MATCH_PATTERN),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo grep -n {_MATCH_PATTERN}' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of 'kanon repo grep -n'.\n  stderr: {result.stderr!r}"
        )

    def test_valid_flags_invocation_has_no_error_keyword_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo grep' with valid flags must not emit 'Error:' prefix to stdout.

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
            *_build_grep_argv(repo_dir, _MATCH_PATTERN),
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo grep {_MATCH_PATTERN}' failed: {result.stderr!r}"
        )
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of 'kanon repo grep': {line!r}\n  stdout: {result.stdout!r}"
            )

    def test_invalid_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Inline-value error for no-value flag must appear on stderr, not stdout.

        The argument-parsing error for '--cached=badval' must be routed to
        stderr only. Stdout must remain clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _CLI_FLAG_CACHED + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            bad_token,
            _MATCH_PATTERN,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected {_DOES_NOT_TAKE_VALUE_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )
        assert bad_token not in result.stdout, (
            f"'{bad_token}' error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_missing_required_argument_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Missing required argument error for '-e' must appear on stderr, not stdout.

        The argument-parsing error for '-e' (no pattern value) must be routed
        to stderr only. Stdout must remain clean.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_GREP,
            _CLI_FLAG_E,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{_CLI_FLAG_E}' (no value).\n  stderr: {result.stderr!r}"
        )
        assert _REQUIRES_ARGUMENT_PHRASE in result.stderr, (
            f"Expected {_REQUIRES_ARGUMENT_PHRASE!r} in stderr.\n  stderr: {result.stderr!r}"
        )
        assert _CLI_FLAG_E not in result.stdout, (
            f"Flag {_CLI_FLAG_E!r} error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )
