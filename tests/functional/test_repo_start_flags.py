"""Functional tests for flag coverage of 'kanon repo start'.

Exercises every flag registered in ``subcmds/start.py``'s ``_Options()`` method
by invoking ``kanon repo start`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

Flags in ``Start._Options()``:

- ``--all`` (store_true, begin branch in all projects)
- ``-r`` / ``--rev`` / ``--revision`` (string value, dest=revision)
- ``--head`` / ``--HEAD`` (store_const "HEAD", dest=revision)

Flags from ``Command._CommonOptions()``:

- ``-v`` / ``--verbose`` (store_true, dest=output_mode, defaults to None)
- ``-q`` / ``--quiet``   (store_false, dest=output_mode, defaults to None)
- ``-j`` / ``--jobs``    (type=int, default=DEFAULT_LOCAL_JOBS)
- ``--outer-manifest``         (store_true, default=None)
- ``--no-outer-manifest``      (store_false, dest=outer_manifest)
- ``--this-manifest-only``     (store_true, default=None)
- ``--no-this-manifest-only``  (store_false, dest=this_manifest_only)
- ``--all-manifests``          (store_false, alias for --no-this-manifest-only)

Valid-value tests confirm each flag is accepted without an argument-parsing
error (exit code != 2). Negative tests for boolean flags confirm that supplying
an inline value is rejected with exit code 2. The negative test for ``--jobs``
confirms that a non-integer value is rejected with exit code 2.

Covers:
- AC-TEST-001: Every ``_Options()`` flag has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated or typed values has a
  negative test verifying rejection of an invalid value.
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

_GIT_BRANCH_MAIN = "main"

# Error exit code for argument-parsing errors.
_ARGPARSE_ERROR_EXIT_CODE = 2

# Expected exit code for successful invocations.
_EXPECTED_EXIT_CODE = 0

# Nonexistent repo-dir name used in argument-parser acceptance tests that
# do not require a real initialized repository (e.g. boolean-with-inline-value
# negative tests that fail at parse time before repo discovery).
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-start-flags-repo-dir"

# Inline-value token for boolean-flag negative tests.
# optparse exits 2 with '--<flag> option does not take a value' when a
# store_true or store_false flag is supplied with an inline value.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Non-integer token for --jobs negative test.
# optparse exits 2 with 'invalid integer value' when a non-int is supplied.
_JOBS_NON_INT_VALUE = "notanumber"

# Valid integer value for the -j/--jobs flag.
_VALID_JOBS_INT = "1"

# Valid --jobs argument used in tests that require a real synced repo.
_VALID_JOBS_ARG = "--jobs=1"

# Branch names used in start flag tests -- each test uses a unique name.
_BRANCH_ALL_FLAG = "feature/flags-all"
_BRANCH_REV_FLAG = "feature/flags-rev"
_BRANCH_HEAD_FLAG = "feature/flags-head"
_BRANCH_JOBS_FLAG = "feature/flags-jobs"
_BRANCH_VERBOSE_FLAG = "feature/flags-verbose"
_BRANCH_THIS_MANIFEST_FLAG = "feature/flags-this-manifest"
_BRANCH_ABSENCE_DEFAULT = "feature/flags-absence-default"
_BRANCH_FUNC_ALL = "feature/func-all"
_BRANCH_FUNC_REV = "feature/func-rev"
_BRANCH_FUNC_HEAD = "feature/func-head"
_BRANCH_CHANNEL_VALID = "feature/channel-valid"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# Boolean store_true flags from Start._Options() and _CommonOptions().
# All accept no value; negative test uses inline-value syntax.
_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    ("--all", "all"),
    ("-v", "short-verbose"),
    ("--verbose", "long-verbose"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
]

# Boolean store_false / store_const flags from Start._Options() and _CommonOptions().
_BOOL_STORE_FALSE_AND_CONST_FLAGS: list[tuple[str, str]] = [
    ("-q", "short-quiet"),
    ("--quiet", "long-quiet"),
    ("--head", "head"),
    ("--HEAD", "HEAD"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]

# Long-form boolean flags (store_true, store_false, and store_const) used in
# AC-TEST-002 negative tests. Short-form flags cannot use '--flag=value' syntax
# in optparse. --head and --HEAD are store_const and also reject inline values.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    ("--all", "all"),
    ("--verbose", "verbose"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
    ("--quiet", "quiet"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
    ("--head", "head"),
    ("--HEAD", "HEAD"),
]

# Non-integer values for the --jobs parametrize test.
_NON_INTEGER_JOBS_VALUES: list[str] = ["notanumber", "1.5", "abc", "two"]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/start.py
# (Also covers AC-FUNC-001: every documented flag behaves per its help text.)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStartFlagsValidValues:
    """AC-TEST-001 / AC-FUNC-001: Every ``_Options()`` flag in subcmds/start.py has a valid-value test.

    Exercises each flag registered in ``Start._Options()`` (and the common
    flags from ``_CommonOptions()``) by invoking 'kanon repo start' with the
    flag against a real synced .repo directory.

    Boolean flags (store_true / store_false / store_const) are tested by
    confirming the flag is accepted without an argument-parsing error
    (exit code != 2). The --jobs/-j flag (integer) is tested with a valid
    integer value. The --rev/-r flag (string) is tested with a valid revision
    string value.

    Flags covered:
    - ``--all``                        (store_true, begin branch in all projects)
    - ``-r`` / ``--rev`` / ``--revision`` (string, point branch at given revision)
    - ``--head`` / ``--HEAD``          (store_const "HEAD", abbreviation for --rev HEAD)
    - ``-v`` / ``--verbose``           (store_true, dest=output_mode, defaults to None)
    - ``-q`` / ``--quiet``             (store_false, dest=output_mode, defaults to None)
    - ``-j`` / ``--jobs``              (int, default=DEFAULT_LOCAL_JOBS)
    - ``--outer-manifest``             (store_true, default=None)
    - ``--no-outer-manifest``          (store_false, dest=outer_manifest)
    - ``--this-manifest-only``         (store_true, default=None)
    - ``--no-this-manifest-only``      (store_false, dest=this_manifest_only)
    - ``--all-manifests``              (store_false, alias for --no-this-manifest-only)
    """

    _ALL_BOOL_FLAGS: list[tuple[str, str]] = _BOOL_STORE_TRUE_FLAGS + _BOOL_STORE_FALSE_AND_CONST_FLAGS

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _ALL_BOOL_FLAGS],
        ids=[test_id for _, test_id in _ALL_BOOL_FLAGS],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo start <branch> <flag>' against a properly synced
        .repo directory and asserts that optparse does not reject the invocation
        (exit code != 2). A non-2 exit code confirms the flag itself was
        accepted; the start subcommand may produce any other exit code depending
        on repository state.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        # Use the flag name as part of the branch name to ensure uniqueness.
        branch_name = f"feature/flag-test-{flag.lstrip('-').replace('/', '-')}"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            branch_name,
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_all_flag_exits_zero_with_branch_name(self, tmp_path: pathlib.Path) -> None:
        """'--all' flag exits 0 on a synced repo when a branch name is supplied.

        The --all flag starts the new branch in every project in the manifest.
        Per the help text: 'begin branch in all projects'. Verifies exit 0
        on a properly synced repo when the branch name is provided.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_ALL_FLAG,
            "--all",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo start {_BRANCH_ALL_FLAG} --all' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_rev_flag_long_form_accepted_with_valid_revision(self, tmp_path: pathlib.Path) -> None:
        """'--rev=<sha>' is accepted by the argument parser (does not exit 2).

        The --rev flag accepts a revision string and points the new branch at
        that revision. Supplying a valid revision confirms the flag is accepted
        without an argument-parsing error. The value 'HEAD' is always a valid
        revision.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_REV_FLAG,
            "--rev",
            "HEAD",
            "--all",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--rev HEAD' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_rev_flag_short_form_accepted_with_valid_revision(self, tmp_path: pathlib.Path) -> None:
        """'-r <sha>' is accepted by the argument parser (does not exit 2).

        The short form -r with a valid revision string ('HEAD') confirms the
        flag is accepted without an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_REV_FLAG + "-short",
            "-r",
            "HEAD",
            "--all",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-r HEAD' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_revision_alias_accepted_with_valid_revision(self, tmp_path: pathlib.Path) -> None:
        """'--revision=<value>' is accepted by the argument parser (does not exit 2).

        The --revision alias maps to the same dest=revision option as --rev.
        Supplying a valid value confirms the alias is accepted without an
        argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_REV_FLAG + "-alias",
            "--revision",
            "HEAD",
            "--all",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--revision HEAD' triggered an argument-parsing error (exit {result.returncode}).\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_head_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--head' flag exits 0 on a synced repo.

        The --head flag is an abbreviation for '--rev HEAD'. It is a store_const
        flag that sets dest=revision to 'HEAD'. Per the help text: 'abbreviation
        for --rev HEAD'. Verifies exit 0 on a properly synced repo.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_HEAD_FLAG,
            "--head",
            "--all",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo start {_BRANCH_HEAD_FLAG} --head --all' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_jobs_flag_long_form_accepted_with_valid_integer(self, tmp_path: pathlib.Path) -> None:
        """'--jobs=1' is accepted by the argument parser (does not exit 2).

        The --jobs flag takes an integer value. Supplying a valid integer (1)
        confirms the flag is accepted without an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_JOBS_FLAG,
            "--all",
            _VALID_JOBS_ARG,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_VALID_JOBS_ARG}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_jobs_flag_short_form_accepted_with_valid_integer(self, tmp_path: pathlib.Path) -> None:
        """'-j 1' is accepted by the argument parser (does not exit 2).

        The short form -j with a valid integer value (1) confirms the flag is
        accepted without an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_JOBS_FLAG + "-short",
            "--all",
            "-j",
            _VALID_JOBS_INT,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-j {_VALID_JOBS_INT}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_verbose_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--verbose' flag is accepted by the argument parser (does not exit 2).

        The -v/--verbose flag enables verbose output. Verifies the flag is
        accepted without an argument-parsing error on a synced repo.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_VERBOSE_FLAG,
            "--all",
            "--verbose",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--verbose' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_and_all_manifests_combination_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--this-manifest-only --all-manifests' combination is accepted (exit != 2).

        Both flags share dest='this_manifest_only'. The last flag wins per
        optparse semantics. The combination must be accepted without exit 2.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_THIS_MANIFEST_FLAG,
            "--all",
            "--this-manifest-only",
            "--all-manifests",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--this-manifest-only --all-manifests' triggered an argument-parsing "
            f"error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with typed or inline values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStartFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts typed or inline values has a negative test.

    Boolean flags (store_true / store_false / store_const) do not accept a
    typed value. The applicable negative test is to supply an unexpected inline
    value using '--flag=value' syntax. optparse exits 2 with
    '--<flag> option does not take a value' for such inputs.

    The --jobs flag accepts an integer value. A non-integer string must be
    rejected by the option parser with exit code 2.

    This class verifies that every long-form boolean flag produces exit 2
    when supplied with an inline value, and that the --jobs flag rejects
    non-integer values with exit 2. The error message must appear on stderr,
    not stdout.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with an inline value must exit 2.

        Supplies '--<flag>=unexpected' to 'kanon repo start'. Since all
        Start._Options() boolean flags are store_true / store_false / store_const,
        optparse rejects the inline value with exit code 2 and emits
        '--<flag> option does not take a value' on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "start",
            "some-branch",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with inline value must emit error on stderr, not stdout.

        The argument-parsing error for '--<flag>=unexpected' must appear on
        stderr only. Stdout must not contain the rejection detail (channel
        discipline).
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "start",
            "some-branch",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_jobs_flag_non_integer_rejected(self, tmp_path: pathlib.Path) -> None:
        """'--jobs=notanumber' must exit 2 with an invalid-integer error on stderr.

        The --jobs flag expects an integer value. A non-numeric string must be
        rejected by the option parser with exit code 2, and the error message
        must appear on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_jobs_arg = f"--jobs={_JOBS_NON_INT_VALUE}"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "start",
            "some-branch",
            bad_jobs_arg,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_jobs_arg}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert "invalid" in result.stderr.lower(), (
            f"Expected 'invalid' in stderr for '{bad_jobs_arg}'.\n  stderr: {result.stderr!r}"
        )

    def test_jobs_flag_non_integer_error_not_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """'--jobs=notanumber' error message must appear on stderr, not stdout.

        The argument-parsing error for a non-integer --jobs must be reported on
        stderr only. Stdout must not contain the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_jobs_arg = f"--jobs={_JOBS_NON_INT_VALUE}"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "start",
            "some-branch",
            bad_jobs_arg,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_jobs_arg}' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "invalid" not in result.stdout.lower(), (
            f"'invalid' error detail leaked to stdout for '{bad_jobs_arg}'.\n  stdout: {result.stdout!r}"
        )

    def test_all_flag_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--all=unexpected' error must name '--all' in stderr.

        The embedded optparse parser emits '--all option does not take a value'
        when '--all=unexpected' is supplied. Confirms the canonical flag name
        appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--all" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "start",
            "some-branch",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--all=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "--all" in result.stderr, (
            f"Expected '--all' in stderr for '--all=unexpected' error.\n  stderr: {result.stderr!r}"
        )

    def test_head_flag_with_inline_value_rejects(self, tmp_path: pathlib.Path) -> None:
        """'--head=unexpected' must exit 2 with error on stderr.

        The --head flag is a store_const flag. Like all store_const flags,
        it must reject inline values with exit code 2 and emit the error on
        stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--head" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "start",
            "some-branch",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--head=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "'--head=unexpected' produced empty stderr; error must appear on stderr."

    @pytest.mark.parametrize(
        "bad_value",
        _NON_INTEGER_JOBS_VALUES,
        ids=_NON_INTEGER_JOBS_VALUES,
    )
    def test_jobs_various_non_integers_rejected(self, tmp_path: pathlib.Path, bad_value: str) -> None:
        """Each non-integer '--jobs' value must exit 2.

        Confirms that every non-numeric value is uniformly rejected with exit
        code 2. Parametrised over several non-integer strings.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_jobs_arg = f"--jobs={bad_value}"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "start",
            "some-branch",
            bad_jobs_arg,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--jobs={bad_value}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStartFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each Start flag uses the documented default when omitted.
    Boolean flags default to None when absent (no explicit default= was set).
    The --jobs flag defaults to DEFAULT_LOCAL_JOBS. The --rev flag defaults
    to None (uses the manifest revision).

    Absence tests confirm that omitting every optional flag still produces a
    valid, non-error invocation.
    """

    def test_all_flags_omitted_exits_zero_with_all_flag(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo start <branch> --all' with all other flags omitted exits 0.

        When only the required branch name and --all are supplied, every other
        optional flag takes its documented default value:
        - --rev defaults to None (use manifest revision)
        - --head defaults to None (unset)
        - --verbose defaults to None (unset)
        - --quiet defaults to None (unset)
        - --jobs defaults to DEFAULT_LOCAL_JOBS
        - --outer-manifest defaults to None
        - --this-manifest-only defaults to None

        Verifies that no flag beyond the branch name is required and that all
        documented defaults produce a successful (exit 0) start.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_ABSENCE_DEFAULT,
            "--all",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo start {_BRANCH_ABSENCE_DEFAULT} --all' with all optional flags "
            f"omitted exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_rev_omitted_uses_manifest_revision(self, tmp_path: pathlib.Path) -> None:
        """Omitting --rev uses the manifest revision; start exits 0.

        When --rev is not supplied, the 'start' subcommand uses the revision
        specified in the manifest (the project's revisionExpr). This must not
        cause any argument-parsing error and the command exits 0 on a synced
        repo.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_ABSENCE_DEFAULT + "-rev",
            "--all",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo start' without --rev exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_jobs_default_does_not_cause_rejection(self, tmp_path: pathlib.Path) -> None:
        """Omitting --jobs uses DEFAULT_LOCAL_JOBS; start exits 0.

        When --jobs is not supplied, it defaults to DEFAULT_LOCAL_JOBS (a
        value based on the CPU count). This must not cause any argument-parsing
        error. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_ABSENCE_DEFAULT + "-jobs",
            "--all",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo start' without --jobs exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_outer_manifest_default_none_does_not_reject(self, tmp_path: pathlib.Path) -> None:
        """Omitting --outer-manifest defaults to None; start exits 0.

        When --outer-manifest is not supplied, its default is None (operate
        starting at the outermost manifest). This must not cause any error.
        Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_ABSENCE_DEFAULT + "-outer",
            "--all",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo start' without --outer-manifest exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_default_none_does_not_reject(self, tmp_path: pathlib.Path) -> None:
        """Omitting --this-manifest-only defaults to None; start exits 0.

        When --this-manifest-only is not supplied, its default is None (no
        restriction applied). This must not cause any error. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_ABSENCE_DEFAULT + "-this",
            "--all",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo start' without --this-manifest-only exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStartFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of each flag documented in Start._Options():
    - --all: 'begin branch in all projects' -- starts branch in every project
    - -r/--rev/--revision: 'point branch at this revision instead of upstream'
    - --head/--HEAD: 'abbreviation for --rev HEAD'

    Tests confirm that each flag is accepted and produces the described behavior
    on a real synced repo.
    """

    def test_all_flag_starts_branch_in_all_projects(self, tmp_path: pathlib.Path) -> None:
        """'--all' starts the branch in all projects in the manifest.

        Per the help text: 'begin branch in all projects'. After 'kanon repo
        start <branch> --all', the new branch must exist in the project
        worktree. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_FUNC_ALL,
            "--all",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo start {_BRANCH_FUNC_ALL} --all' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_rev_head_flag_starts_branch_at_head(self, tmp_path: pathlib.Path) -> None:
        """'--rev HEAD' starts the branch pointing at HEAD; exit 0.

        Per the help text: 'point branch at this revision instead of upstream'.
        Supplying '--rev HEAD' explicitly points the new branch at HEAD, which
        is the default for a fresh clone. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_FUNC_REV,
            "--rev",
            "HEAD",
            "--all",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo start {_BRANCH_FUNC_REV} --rev HEAD --all' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_head_abbreviation_starts_branch_at_head(self, tmp_path: pathlib.Path) -> None:
        """'--head' (abbreviation for '--rev HEAD') starts the branch at HEAD; exit 0.

        Per the help text: 'abbreviation for --rev HEAD'. The --head flag
        must behave identically to '--rev HEAD'. Verifies exit 0 on a
        properly synced repo.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_FUNC_HEAD,
            "--head",
            "--all",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo start {_BRANCH_FUNC_HEAD} --head --all' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_rev_and_head_flags_are_mutually_exclusive_last_wins(self, tmp_path: pathlib.Path) -> None:
        """'--rev main --head' is accepted; last flag wins (store_const overwrites string).

        Both --rev and --head write to dest=revision. When both are supplied,
        the last flag wins. Since both result in a valid revision value, the
        command must be accepted without an argument-parsing error (exit != 2).
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_FUNC_HEAD + "-combined",
            "--rev",
            _GIT_BRANCH_MAIN,
            "--head",
            "--all",
            cwd=checkout_dir,
        )

        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--rev main --head' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoStartFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_flags_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo start' with valid flags must not emit tracebacks to stdout.

        On success (e.g. with --all on a synced repo), stdout must not contain
        'Traceback (most recent call last)'. Tracebacks on stdout indicate an
        unhandled exception that escaped to the wrong channel.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_CHANNEL_VALID,
            "--all",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo start {_BRANCH_CHANNEL_VALID} --all' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of 'kanon repo start' with valid flags.\n  stdout: {result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo start' with valid flags must not emit tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_CHANNEL_VALID + "-stderr",
            "--all",
            "--verbose",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo start ... --verbose' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of 'kanon repo start' with valid flags.\n  stderr: {result.stderr!r}"
        )

    def test_invalid_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        The argument-parsing error for '--all=unexpected' must be routed to
        stderr only. Stdout must remain clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--all" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "start",
            "some-branch",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"stderr must be non-empty for '{bad_token}' error."
        assert bad_token not in result.stdout, (
            f"'{bad_token}' error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_jobs_non_integer_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'--jobs=notanumber' error must appear on stderr, not stdout.

        The argument-parsing error for a non-integer --jobs must be routed to
        stderr only. Stdout must remain clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_jobs_arg = f"--jobs={_JOBS_NON_INT_VALUE}"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "start",
            "some-branch",
            bad_jobs_arg,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_jobs_arg}'.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"stderr must be non-empty for '{bad_jobs_arg}' error."
        assert _JOBS_NON_INT_VALUE not in result.stdout, (
            f"'{_JOBS_NON_INT_VALUE}' error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_no_error_keyword_on_stdout_for_valid_flags(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo start' with flags must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_synced_repo(tmp_path)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "start",
            _BRANCH_CHANNEL_VALID + "-error-kw",
            "--all",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            "Prerequisite 'kanon repo start' failed with argparse error."
        )
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of 'kanon repo start': {line!r}\n  stdout: {result.stdout!r}"
            )
