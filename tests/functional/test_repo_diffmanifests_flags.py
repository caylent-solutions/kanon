"""Functional tests for flag coverage of 'kanon repo diffmanifests'.

Exercises every flag registered in ``subcmds/diffmanifests.py``'s ``_Options()``
method by invoking ``kanon repo diffmanifests`` as a subprocess. Validates correct
accept and reject behavior for all flag values, and correct default behavior when
flags are omitted.

Flags in ``Diffmanifests._Options()``:

Boolean store_true flag -- accepted without an argument; rejected with inline
value (``--flag=value`` syntax, optparse exits 2):
- ``--raw``                      (store_true): display raw diff

Boolean store_false flag -- accepted without an argument; rejected with inline
value; inverts the ``color`` dest:
- ``--no-color``                 (store_false, dest=color, default=True): disable colour

String flag -- requires exactly one argument; optparse exits 2 when supplied
without an argument:
- ``--pretty-format <FORMAT>``   (store, string): custom git pretty format string

AC-TEST-002 note: ``--raw`` and ``--no-color`` are boolean flags; the negative
test supplies them with an inline value (``--raw=unexpected``), which optparse
rejects with exit code 2 and emits '--<flag> option does not take a value' on
stderr. ``--pretty-format`` requires exactly one argument; the negative test
invokes it with no argument (placing it last), which optparse rejects with exit
code 2 and emits '--pretty-format option requires 1 argument' on stderr. No
flag accepts an enumerated keyword set, so there are no enum-constraint negative
tests.

AC-TEST-003 note: When ``--raw`` is omitted the default is ``None`` (formatted
diff path). When ``--no-color`` is omitted the default is ``True`` (colour
enabled). When ``--pretty-format`` is omitted the default is ``None`` (one-line
log format). All omitted-flag scenarios are verified on a valid synced repo.

Covers:
- AC-TEST-001: Every ``_Options()`` flag in subcmds/diffmanifests.py has a
  valid-value test.
- AC-TEST-002: Every flag that accepts enumerated values has a negative test
  for an invalid value.
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
# Module-level constants -- all domain literals must appear here only.
# No inline literals in test bodies, f-string diagnostics, or parametrize
# tuples.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Diffmanifests Flags Test User"
_GIT_USER_EMAIL = "repo-diffmanifests-flags@example.com"
_MANIFEST_FILENAME = "default.xml"
_PROJECT_NAME = "content-bare"
_PROJECT_PATH = "diffmanifests-flags-test-project"

# CLI token constants -- every token referenced in test logic.
_CMD_REPO = "repo"
_FLAG_REPO_DIR = "--repo-dir"
_SUBCMD_DIFFMANIFESTS = "diffmanifests"

# Flag tokens from Diffmanifests._Options()
_CLI_FLAG_RAW = "--raw"
_CLI_FLAG_NO_COLOR = "--no-color"
_CLI_FLAG_PRETTY_FORMAT = "--pretty-format"

# A valid git pretty-format string used in valid-value tests.
_PRETTY_FORMAT_VALUE = "%h"

# Inline-value suffix used in negative tests for boolean flags.
# optparse exits 2 with '--<flag> option does not take a value'.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Exit codes
_EXPECTED_EXIT_CODE = 0
_ARGPARSE_ERROR_EXIT_CODE = 2

# Phrases verified in channel-discipline and negative-test assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"
_ERROR_PREFIX = "Error:"
_DOES_NOT_TAKE_VALUE_PHRASE = "does not take a value"
_REQUIRES_ARGUMENT_PHRASE = "requires 1 argument"

# Nonexistent repo-dir name used in argument-parser acceptance tests.
# The command exits 2 for argument-parsing errors regardless of repo state.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-diffmanifests-flags-repo-dir"

# Sentinel for empty combined output (no diff emitted for identical manifests).
_EMPTY_OUTPUT = ""

# ---------------------------------------------------------------------------
# Parametrize data tables -- all tuples use flag constants.
#
# AC-TEST-001 valid-value parametrize: one entry per flag.
# Each entry: (flag_token_or_compound, test_id).
# ---------------------------------------------------------------------------

# Boolean flags: accepted standalone (no argument).
_BOOL_FLAGS_VALID: list[tuple[str, str]] = [
    (_CLI_FLAG_RAW, "raw"),
    (_CLI_FLAG_NO_COLOR, "no-color"),
]

# String flag with a required argument: compound token '--flag=value'.
_STRING_FLAGS_VALID: list[tuple[str, str]] = [
    (f"{_CLI_FLAG_PRETTY_FORMAT}={_PRETTY_FORMAT_VALUE}", "pretty-format"),
]

# Combined valid-flag list for AC-TEST-001 parametrize.
_ALL_FLAGS_VALID: list[tuple[str, str]] = _BOOL_FLAGS_VALID + _STRING_FLAGS_VALID

# AC-TEST-002 negative-value parametrize for boolean flags.
# Each entry: (long_flag_token, test_id).
_BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST: list[tuple[str, str]] = [
    (_CLI_FLAG_RAW, "raw"),
    (_CLI_FLAG_NO_COLOR, "no-color"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` flag in subcmds/diffmanifests.py has a valid-value test.

    Exercises each flag registered in ``Diffmanifests._Options()`` by invoking
    'kanon repo diffmanifests' with the flag against a real synced .repo
    directory. Parametrized over all three flags:

    - ``--raw`` (boolean store_true): accepted without argument.
    - ``--no-color`` (boolean store_false): accepted without argument.
    - ``--pretty-format=<FORMAT>`` (string): accepted with a valid format string.

    Valid-value tests confirm exit code == 0 (flag accepted AND command
    succeeds on identical manifests). All parametrize tuples reference constants.
    """

    @pytest.mark.parametrize(
        "flag_token",
        [token for token, _ in _ALL_FLAGS_VALID],
        ids=[test_id for _, test_id in _ALL_FLAGS_VALID],
    )
    def test_flag_accepted_exits_zero_on_synced_repo(self, tmp_path: pathlib.Path, flag_token: str) -> None:
        """Each _Options() flag is accepted and exits 0 on a synced repo.

        Invokes 'kanon repo diffmanifests <flag> default.xml' against a fully
        synced repo with identical manifests. All three flags (--raw,
        --no-color, --pretty-format=<fmt>) must exit 0 when the manifests
        are identical -- the flag controls output format only, not correctness.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFFMANIFESTS,
            flag_token,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Flag {flag_token!r} exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_raw_flag_produces_no_output_on_identical_manifests(self, tmp_path: pathlib.Path) -> None:
        """'--raw' flag produces empty combined output when manifests are identical.

        The --raw flag selects the machine-parseable diff format. When the two
        manifests are identical (comparing default.xml against itself), no
        projects differ and combined stdout+stderr must be empty even with
        --raw active.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFFMANIFESTS,
            _CLI_FLAG_RAW,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: {_CLI_FLAG_RAW!r} exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout == _EMPTY_OUTPUT and result.stderr == _EMPTY_OUTPUT, (
            f"{_CLI_FLAG_RAW!r} produced unexpected output for identical manifests.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_no_color_flag_produces_no_output_on_identical_manifests(self, tmp_path: pathlib.Path) -> None:
        """'--no-color' flag produces empty combined output when manifests are identical.

        The --no-color flag disables ANSI colour codes in the diff output.
        When manifests are identical, no diff lines are emitted regardless of
        the colour setting. Both stdout and stderr must be empty.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFFMANIFESTS,
            _CLI_FLAG_NO_COLOR,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: {_CLI_FLAG_NO_COLOR!r} exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout == _EMPTY_OUTPUT and result.stderr == _EMPTY_OUTPUT, (
            f"{_CLI_FLAG_NO_COLOR!r} produced unexpected output for identical manifests.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_pretty_format_flag_produces_no_output_on_identical_manifests(self, tmp_path: pathlib.Path) -> None:
        """'--pretty-format=<fmt>' produces empty combined output when manifests are identical.

        The --pretty-format flag customises git log formatting for per-project
        commit diffs. When manifests are identical, no commit diffs exist and
        the flag has no visible effect. Both stdout and stderr must be empty.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFFMANIFESTS,
            f"{_CLI_FLAG_PRETTY_FORMAT}={_PRETTY_FORMAT_VALUE}",
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: {_CLI_FLAG_PRETTY_FORMAT!r} exited {result.returncode}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout == _EMPTY_OUTPUT and result.stderr == _EMPTY_OUTPUT, (
            f"{_CLI_FLAG_PRETTY_FORMAT!r}={_PRETTY_FORMAT_VALUE!r} produced unexpected output "
            f"for identical manifests.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for invalid flag values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsFlagsInvalidValues:
    """AC-TEST-002: Flags that reject invalid values exit 2 with error on stderr.

    The applicable negative tests for 'kanon repo diffmanifests':

    - Boolean flags (``--raw``, ``--no-color``): supply an inline value using
      the ``--flag=value`` syntax. optparse exits 2 with '--<flag> option does
      not take a value' on stderr.

    - String flag (``--pretty-format``): supply the flag without a required
      argument (placed last with no following token). optparse exits 2 with
      '--pretty-format option requires 1 argument' on stderr.

    No flag accepts an enumerated keyword set, so enum-constraint tests are not
    applicable here. The class documents this in the class docstring rather than
    remaining silent about the AC scope.
    """

    @pytest.mark.parametrize(
        "flag_token",
        [token for token, _ in _BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag_token: str) -> None:
        """Boolean flag with inline value must exit 2.

        Supplies '--<flag>=unexpected' to 'kanon repo diffmanifests'. Since
        ``--raw`` and ``--no-color`` are store_true / store_false flags,
        optparse rejects the inline value with exit code 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag_token + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag_token",
        [token for token, _ in _BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_error_on_stderr(self, tmp_path: pathlib.Path, flag_token: str) -> None:
        """Boolean flag with inline value must emit error on stderr, not stdout.

        The argument-parsing error for '--<flag>=unexpected' must appear on
        stderr. Stdout must not contain the error token (channel discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag_token + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert result.stderr != _EMPTY_OUTPUT and bad_token not in result.stdout, (
            f"'{bad_token}' error discipline failed: "
            f"stderr empty={result.stderr == _EMPTY_OUTPUT!r}, "
            f"token in stdout={bad_token in result.stdout!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag_token",
        [token for token, _ in _BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _BOOL_FLAGS_FOR_INLINE_VALUE_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_stderr_names_does_not_take_a_value(
        self, tmp_path: pathlib.Path, flag_token: str
    ) -> None:
        """Boolean flag with inline value must emit 'does not take a value' on stderr.

        optparse consistently uses '{phrase}' for store_true / store_false
        flags supplied with an inline value. Confirms the canonical phrase
        appears in stderr.
        """.format(phrase=_DOES_NOT_TAKE_VALUE_PHRASE)
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag_token + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _DOES_NOT_TAKE_VALUE_PHRASE in result.stderr, (
            f"Expected '{_DOES_NOT_TAKE_VALUE_PHRASE}' in stderr for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )

    def test_pretty_format_without_argument_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'--pretty-format' with no argument must exit 2.

        The --pretty-format flag requires exactly one argument. When supplied
        without a following token (placed last), optparse exits 2 with
        '--pretty-format option requires 1 argument' on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _CLI_FLAG_PRETTY_FORMAT,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"{_CLI_FLAG_PRETTY_FORMAT!r} (no argument) exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_pretty_format_without_argument_stderr_names_requires_1_argument(self, tmp_path: pathlib.Path) -> None:
        """'--pretty-format' with no argument must emit 'requires 1 argument' on stderr.

        optparse emits '--pretty-format option requires 1 argument' when the
        string flag is supplied without an argument. Confirms this canonical
        phrase appears in stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _CLI_FLAG_PRETTY_FORMAT,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: {_CLI_FLAG_PRETTY_FORMAT!r} exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert _REQUIRES_ARGUMENT_PHRASE in result.stderr, (
            f"Expected '{_REQUIRES_ARGUMENT_PHRASE}' in stderr for "
            f"{_CLI_FLAG_PRETTY_FORMAT!r} (no argument).\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_pretty_format_without_argument_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'--pretty-format' with no argument must emit error on stderr, not stdout.

        The argument-parsing error for a missing required argument must appear
        on stderr only. Stdout must remain empty on a pure argument-parsing
        error.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            _CLI_FLAG_PRETTY_FORMAT,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: {_CLI_FLAG_PRETTY_FORMAT!r} exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert result.stderr != _EMPTY_OUTPUT and result.stdout == _EMPTY_OUTPUT, (
            f"Channel discipline failed for {_CLI_FLAG_PRETTY_FORMAT!r} (no argument): "
            f"stderr empty={result.stderr == _EMPTY_OUTPUT!r}, "
            f"stdout non-empty={result.stdout != _EMPTY_OUTPUT!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each Diffmanifests._Options() flag uses its documented default
    when omitted:
    - ``--raw`` (dest='raw'): defaults to None / falsy (formatted diff path).
    - ``--no-color`` (dest='color', default=True): colour is enabled by default.
    - ``--pretty-format`` (dest='pretty_format'): defaults to None (one-line log).

    Absence tests confirm that omitting every optional flag produces a valid,
    successful invocation (exit 0) on a real synced repo with identical
    manifests, and that combined stdout and stderr are both empty.
    """

    def test_all_flags_omitted_exits_zero_with_empty_output(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo diffmanifests' with all optional flags omitted exits 0 with empty output.

        When no optional flags are supplied, each flag takes its default value:
        - --raw defaults to None (formatted diff output path).
        - --no-color defaults such that color is True (colour enabled).
        - --pretty-format defaults to None (one-line format).

        Verifies that no flag is required, all documented defaults produce
        a successful (exit 0) invocation on identical manifests, and that
        both stdout and stderr are empty.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFFMANIFESTS,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_SUBCMD_DIFFMANIFESTS}' with all flags omitted exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
        assert result.stdout == _EMPTY_OUTPUT and result.stderr == _EMPTY_OUTPUT, (
            f"'{_SUBCMD_DIFFMANIFESTS}' with all flags omitted produced unexpected output "
            f"for identical manifests.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional semantics of each flag documented in
    Diffmanifests._Options():

    - ``--raw``: Displays the diff in machine-parseable format. Accepted by the
      parser and exits 0 on identical manifests.
    - ``--no-color``: Disables ANSI colour codes. Accepted by the parser and
      exits 0 on identical manifests.
    - ``--pretty-format <FORMAT>``: Customises git log format for per-project
      commit diffs. Accepted by the parser and exits 0 on identical manifests.

    All tests use a real synced repo with identical manifests so the flags'
    output-format effects are exercised without requiring actual project diffs.
    """

    @pytest.mark.parametrize(
        "flag_token",
        [token for token, _ in _ALL_FLAGS_VALID],
        ids=[test_id for _, test_id in _ALL_FLAGS_VALID],
    )
    def test_flag_does_not_cause_argparse_error(self, tmp_path: pathlib.Path, flag_token: str) -> None:
        """Each documented flag is accepted by the argument parser (exit 0).

        Invokes 'kanon repo diffmanifests <flag> default.xml' against a fully
        synced repo. Each flag must be accepted by the argument parser (exit
        code exactly 0 on identical manifests). A non-zero exit code indicates
        either an argument-parsing failure or a runtime error.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFFMANIFESTS,
            flag_token,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Flag {flag_token!r} triggered an argument-parsing or runtime error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_raw_and_no_color_combined_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'--raw --no-color' combination exits 0 on identical manifests.

        The --raw and --no-color flags are orthogonal: --raw selects the output
        format and --no-color disables colour within that format. Combining them
        is valid per the help text and must exit 0 on identical manifests.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFFMANIFESTS,
            _CLI_FLAG_RAW,
            _CLI_FLAG_NO_COLOR,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_FLAG_RAW} {_CLI_FLAG_NO_COLOR}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_raw_and_pretty_format_combined_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'--raw --pretty-format=<fmt>' combination exits 0 on identical manifests.

        The --raw and --pretty-format flags are orthogonal: --raw selects the
        raw output path and --pretty-format customises the git log format string
        within that path. Combining them is valid per the help text and must
        exit 0 on identical manifests.
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
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFFMANIFESTS,
            _CLI_FLAG_RAW,
            f"{_CLI_FLAG_PRETTY_FORMAT}={_PRETTY_FORMAT_VALUE}",
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_FLAG_RAW} {_CLI_FLAG_PRETTY_FORMAT}={_PRETTY_FORMAT_VALUE}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoDiffmanifestsFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks or
    '{prefix}' prefixed error messages to stdout, and that argument-parsing
    errors appear on stderr only. No cross-channel leakage is permitted.
    """.format(prefix=_ERROR_PREFIX)

    def test_valid_flag_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful flag invocation must not emit Python tracebacks to stdout.

        On success with --raw on a synced repo, stdout must not contain
        '{marker}'. Tracebacks on stdout indicate an unhandled exception that
        escaped to the wrong channel.
        """.format(marker=_TRACEBACK_MARKER)
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFFMANIFESTS,
            _CLI_FLAG_RAW,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: {_CLI_FLAG_RAW!r} exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of "
            f"'{_SUBCMD_DIFFMANIFESTS} {_CLI_FLAG_RAW}'.\n  stdout: {result.stdout!r}"
        )

    def test_valid_flag_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful flag invocation must not emit Python tracebacks to stderr.

        On success with --no-color on a synced repo, stderr must not contain
        '{marker}'. A traceback on stderr during a successful run indicates an
        unhandled exception was swallowed rather than propagated correctly.
        """.format(marker=_TRACEBACK_MARKER)
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFFMANIFESTS,
            _CLI_FLAG_NO_COLOR,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: {_CLI_FLAG_NO_COLOR!r} exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of "
            f"'{_SUBCMD_DIFFMANIFESTS} {_CLI_FLAG_NO_COLOR}'.\n  stderr: {result.stderr!r}"
        )

    def test_invalid_bool_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        The argument-parsing error for '--raw=unexpected' must be routed to
        stderr only. Stdout must remain empty on a pure argument-parsing error.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = _CLI_FLAG_RAW + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            repo_dir,
            _SUBCMD_DIFFMANIFESTS,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert result.stderr != _EMPTY_OUTPUT and result.stdout == _EMPTY_OUTPUT, (
            f"Channel discipline failed: stderr empty={result.stderr == _EMPTY_OUTPUT!r}, "
            f"stdout non-empty={result.stdout != _EMPTY_OUTPUT!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_valid_flags_invocation_no_error_prefix_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful flag invocation must not emit '{prefix}' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation with --no-color and --raw must not produce any line
        starting with '{prefix}' on stdout.
        """.format(prefix=_ERROR_PREFIX)
        checkout_dir, repo_dir = _setup_synced_repo(
            tmp_path,
            git_user_name=_GIT_USER_NAME,
            git_user_email=_GIT_USER_EMAIL,
            project_name=_PROJECT_NAME,
            project_path=_PROJECT_PATH,
            manifest_filename=_MANIFEST_FILENAME,
        )
        result = _run_kanon(
            _CMD_REPO,
            _FLAG_REPO_DIR,
            str(repo_dir),
            _SUBCMD_DIFFMANIFESTS,
            _CLI_FLAG_NO_COLOR,
            _CLI_FLAG_RAW,
            _MANIFEST_FILENAME,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite: '{_CLI_FLAG_NO_COLOR} {_CLI_FLAG_RAW}' exited {result.returncode}.\n  stderr: {result.stderr!r}"
        )
        error_lines = [line for line in result.stdout.splitlines() if line.startswith(_ERROR_PREFIX)]
        assert error_lines == [], (
            f"'{_ERROR_PREFIX}' lines found in stdout: {error_lines!r}\n  stdout: {result.stdout!r}"
        )
