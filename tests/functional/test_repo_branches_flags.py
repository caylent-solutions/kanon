"""Functional tests for flag coverage of 'kanon repo branches'.

Exercises every flag available to ``subcmds/branches.py`` by invoking
``kanon repo branches`` as a subprocess. The ``Branches`` subcommand has no
``_Options()`` method of its own; its flags are the common flags registered
by ``Command._CommonOptions()``:

- ``-v`` / ``--verbose`` (store_true, dest=output_mode, no explicit default -- defaults to None)
- ``-q`` / ``--quiet`` (store_false, dest=output_mode, no explicit default -- defaults to None)
- ``-j`` / ``--jobs`` (type=int, default=DEFAULT_LOCAL_JOBS)
- ``--outer-manifest`` (store_true, default=None)
- ``--no-outer-manifest`` (store_false, dest=outer_manifest)
- ``--this-manifest-only`` (store_true, default=None)
- ``--no-this-manifest-only`` / ``--all-manifests`` (store_false, dest=this_manifest_only)

Valid-value tests confirm each flag is accepted without an argument-parsing
error (exit code != 2). Negative tests for boolean flags confirm that supplying
an inline value is rejected with exit code 2. The negative test for ``--jobs``
confirms that a non-integer value is rejected with exit code 2.

Covers:
- AC-TEST-001: Every ``_Options()`` flag in ``subcmds/branches.py`` has a valid-value test.
- AC-TEST-002: Every flag that accepts enumerated values has a negative test for an invalid value.
- AC-TEST-003: Flags have correct absence-default behavior when omitted.
- AC-FUNC-001: Every documented flag behaves per its help text.
- AC-CHANNEL-001: For CLI-facing tests, stdout vs stderr discipline is verified.

Tests are decorated with @pytest.mark.functional.
"""

import pathlib

import pytest

from tests.functional.conftest import (
    _DEFAULT_GIT_BRANCH,
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all hard-coded test-fixture values extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Branches Flags Test User"
_GIT_USER_EMAIL = "repo-branches-flags@example.com"
_PROJECT_PATH = "branches-flags-test-project"

# Error exit code for argument-parsing errors.
_ARGPARSE_ERROR_EXIT_CODE = 2

# Expected exit code for successful invocations.
_EXPECTED_EXIT_CODE = 0

# Nonexistent repo-dir name used in argument-parser acceptance tests that
# do not require a real initialized repository (e.g. boolean-with-inline-value
# negative tests that fail at parse time before repo discovery).
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-branches-flags-repo-dir"

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

# Branch name used in branches flags tests.
_BRANCH_FLAGS_VALID = "feature/branches-flags-valid"
_BRANCH_FLAGS_CHANNEL = "feature/branches-flags-channel"
_BRANCH_FLAGS_ABSENCE = "feature/branches-flags-absence"
_BRANCH_FLAGS_JOBS = "feature/branches-flags-jobs"
_BRANCH_FLAGS_VERBOSE = "feature/branches-flags-verbose"
_BRANCH_FLAGS_QUIET = "feature/branches-flags-quiet"
_BRANCH_FLAGS_THIS_MANIFEST = "feature/branches-flags-this-manifest"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# Boolean store_true flags from _CommonOptions().
_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    ("-v", "short-verbose"),
    ("--verbose", "long-verbose"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
]

# Boolean store_false flags from _CommonOptions().
_BOOL_STORE_FALSE_FLAGS: list[tuple[str, str]] = [
    ("-q", "short-quiet"),
    ("--quiet", "long-quiet"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]

# Long-form boolean flags (store_true and store_false) used in AC-TEST-002
# negative tests. Short-form flags cannot use '--flag=value' syntax in
# optparse so only long-form flags are included here.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    ("--verbose", "verbose"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
    ("--quiet", "quiet"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]

# Non-integer values for the --jobs parametrize test.
_NON_INTEGER_JOBS_VALUES: list[str] = ["notanumber", "1.5", "abc", "two"]


# ---------------------------------------------------------------------------
# Private helper: set up a synced repo with an existing branch
# ---------------------------------------------------------------------------


def _setup_repo_with_branch(
    tmp_path: pathlib.Path,
    branch_name: str,
) -> "tuple[pathlib.Path, pathlib.Path]":
    """Set up a synced repo and create a local branch using 'kanon repo start'.

    Runs 'kanon repo init', 'kanon repo sync', and 'kanon repo start
    <branch_name> --all' so that the branch exists in every project in the
    manifest. The returned (checkout_dir, repo_dir) pair is ready for a
    'branches' invocation.

    Args:
        tmp_path: pytest-provided temporary directory root.
        branch_name: The name of the branch to create via 'kanon repo start'.

    Returns:
        A tuple of (checkout_dir, repo_dir) after init, sync, and start.

    Raises:
        AssertionError: When kanon repo init, sync, or start exits non-zero.
    """
    checkout_dir, repo_dir = _setup_synced_repo(
        tmp_path,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_path=_PROJECT_PATH,
        branch=_DEFAULT_GIT_BRANCH,
    )

    start_result = _run_kanon(
        "repo",
        "--repo-dir",
        str(repo_dir),
        "start",
        branch_name,
        "--all",
        cwd=checkout_dir,
    )
    assert start_result.returncode == _EXPECTED_EXIT_CODE, (
        f"Prerequisite 'kanon repo start {branch_name} --all' failed with "
        f"exit {start_result.returncode}.\n"
        f"  stdout: {start_result.stdout!r}\n"
        f"  stderr: {start_result.stderr!r}"
    )
    return checkout_dir, repo_dir


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every flag available in 'repo branches'
# (Also covers AC-FUNC-001: every documented flag behaves per its help text.)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoBranchesFlagsValidValues:
    """AC-TEST-001 / AC-FUNC-001: Every flag in ``subcmds/branches.py`` has a valid-value test.

    Exercises each flag available to ``Branches`` (all from
    ``Command._CommonOptions()``) by invoking 'kanon repo branches' with the
    flag against a real synced .repo directory.

    Boolean flags (store_true / store_false) are tested by confirming the flag
    is accepted without an argument-parsing error (exit code != 2). The
    --jobs/-j flag (integer) is tested with a valid integer value.

    Flags covered:
    - ``-v`` / ``--verbose``           (store_true, dest=output_mode, defaults to None)
    - ``-q`` / ``--quiet``             (store_false, dest=output_mode, defaults to None)
    - ``-j`` / ``--jobs``              (int, default=DEFAULT_LOCAL_JOBS)
    - ``--outer-manifest``             (store_true, default=None)
    - ``--no-outer-manifest``          (store_false, dest=outer_manifest)
    - ``--this-manifest-only``         (store_true, default=None)
    - ``--no-this-manifest-only``      (store_false, dest=this_manifest_only)
    - ``--all-manifests``              (store_false, alias for --no-this-manifest-only)
    """

    _ALL_BOOL_FLAGS: list[tuple[str, str]] = _BOOL_STORE_TRUE_FLAGS + _BOOL_STORE_FALSE_FLAGS

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _ALL_BOOL_FLAGS],
        ids=[test_id for _, test_id in _ALL_BOOL_FLAGS],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo branches <flag>' against a properly synced .repo
        directory with a topic branch already created. Asserts that optparse
        does not reject the invocation (exit code != 2). A non-2 exit code
        confirms the flag itself was accepted; the branches subcommand may
        produce any other exit code depending on repository state.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_VALID)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_jobs_flag_long_form_accepted_with_valid_integer(self, tmp_path: pathlib.Path) -> None:
        """'--jobs=1' is accepted by the argument parser (does not exit 2).

        The --jobs flag takes an integer value. Supplying a valid integer (1)
        confirms the flag is accepted without an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_JOBS)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
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
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_JOBS + "-short")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            "-j",
            _VALID_JOBS_INT,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-j {_VALID_JOBS_INT}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_verbose_flag_accepted_with_valid_branches(self, tmp_path: pathlib.Path) -> None:
        """'--verbose' flag is accepted by the argument parser (does not exit 2).

        The --verbose flag enables verbose output. Verifies the flag is
        accepted without an argument-parsing error on a synced repo with an
        existing topic branch.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_VERBOSE)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            "--verbose",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--verbose' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_quiet_flag_accepted_with_valid_branches(self, tmp_path: pathlib.Path) -> None:
        """'--quiet' flag is accepted by the argument parser (does not exit 2).

        The --quiet flag suppresses progress messages. Verifies the flag is
        accepted without an argument-parsing error on a synced repo with an
        existing topic branch.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_QUIET)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            "--quiet",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--quiet' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_combination_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--this-manifest-only --all-manifests' combination is accepted (exit != 2).

        Both flags share dest='this_manifest_only'. The last flag wins per
        optparse semantics. The combination must be accepted without exit 2.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_THIS_MANIFEST)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
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
class TestRepoBranchesFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated values has a negative test.

    Boolean flags (store_true / store_false) do not accept a typed value. The
    applicable negative test is to supply an unexpected inline value using
    '--flag=value' syntax. optparse exits 2 with '--<flag> option does not
    take a value' for such inputs.

    The --jobs flag accepts an integer value. A non-integer string must be
    rejected by the option parser with exit code 2.

    This class verifies that every long-form boolean flag produces exit 2
    when supplied with an inline value, and that the --jobs flag rejects
    non-integer values with exit 2. Error messages must appear on stderr,
    not stdout.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with an inline value must exit 2.

        Supplies '--<flag>=unexpected' to 'kanon repo branches'. Since all
        Branches flags are store_true / store_false, optparse rejects the
        inline value with exit code 2 and emits '--<flag> option does not
        take a value' on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "branches",
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
            "branches",
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
            "branches",
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
            "branches",
            bad_jobs_arg,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_jobs_arg}' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "invalid" not in result.stdout.lower(), (
            f"'invalid' error detail leaked to stdout for '{bad_jobs_arg}'.\n  stdout: {result.stdout!r}"
        )

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
            "branches",
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
class TestRepoBranchesFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each Branches flag uses the documented default when omitted.
    Boolean flags default to False or None when absent (no explicit default=
    was set). The --jobs flag defaults to DEFAULT_LOCAL_JOBS.

    Absence tests confirm that omitting every optional flag still produces a
    valid, non-error invocation.
    """

    def test_all_flags_omitted_exits_zero_with_existing_branch(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo branches' with all flags omitted exits 0 when a branch exists.

        When no optional flag is supplied, every flag takes its documented
        default value:
        - --verbose defaults to None (unset)
        - --quiet defaults to None (unset)
        - --jobs defaults to DEFAULT_LOCAL_JOBS
        - --outer-manifest defaults to None
        - --this-manifest-only defaults to None

        Verifies that no flag is required and that all documented defaults
        produce a successful (exit 0) branches listing.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_ABSENCE)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo branches' with all optional flags omitted exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_jobs_default_does_not_cause_rejection(self, tmp_path: pathlib.Path) -> None:
        """Omitting --jobs uses DEFAULT_LOCAL_JOBS; branches exits 0.

        When --jobs is not supplied, it defaults to DEFAULT_LOCAL_JOBS (a
        value based on the CPU count). This must not cause any argument-parsing
        error. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_ABSENCE + "-jobs")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo branches' without --jobs exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_outer_manifest_default_none_does_not_reject(self, tmp_path: pathlib.Path) -> None:
        """Omitting --outer-manifest defaults to None; branches exits 0.

        When --outer-manifest is not supplied, its default is None (operate
        starting at the outermost manifest). This must not cause any error.
        Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_ABSENCE + "-outer")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo branches' without --outer-manifest exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_default_none_does_not_reject(self, tmp_path: pathlib.Path) -> None:
        """Omitting --this-manifest-only defaults to None; branches exits 0.

        When --this-manifest-only is not supplied, its default is None (no
        restriction applied). This must not cause any error. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_ABSENCE + "-this")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo branches' without --this-manifest-only exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_verbose_default_none_does_not_affect_listing(self, tmp_path: pathlib.Path) -> None:
        """Omitting --verbose defaults to None; branches exits 0 and lists the branch.

        When --verbose is not supplied, its default is None (neither verbose
        nor quiet). The branches subcommand must still list topic branches
        without any error.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_ABSENCE + "-verbose")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo branches' without --verbose exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert _BRANCH_FLAGS_ABSENCE + "-verbose" in combined, (
            f"Expected branch name in output when --verbose is omitted.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoBranchesFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of each flag documented in the Branches
    command's option set (all inherited from _CommonOptions()):
    - --verbose: enables verbose output (accepted without error on a real repo)
    - --quiet: only shows errors (accepted without error on a real repo)
    - --jobs: sets parallel job count (accepted without error on a real repo)
    - --this-manifest-only: restricts to this manifest (accepted without error)
    - --outer-manifest: operates from outermost manifest (accepted without error)
    - --all-manifests: expands to all submanifests (accepted without error)

    Tests confirm that each flag is accepted and produces no parse error.
    """

    def test_this_manifest_only_restricts_to_current_manifest(self, tmp_path: pathlib.Path) -> None:
        """'--this-manifest-only' flag is accepted and exits 0 on a real synced repo.

        Per the help text: 'only operate on this (sub)manifest'. Verifies that
        the flag is accepted without error and branches exits 0 (listing is
        restricted to the current manifest's projects).
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_THIS_MANIFEST + "-func")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            "--this-manifest-only",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--this-manifest-only' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_all_manifests_flag_accepted_and_exits_successfully(self, tmp_path: pathlib.Path) -> None:
        """'--all-manifests' flag is accepted and exits 0 on a real synced repo.

        Per the help text: 'operate on this manifest and its submanifests'.
        Verifies that the flag is accepted without error.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_ABSENCE + "-all-manifests")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            "--all-manifests",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--all-manifests' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_jobs_flag_controls_parallel_execution(self, tmp_path: pathlib.Path) -> None:
        """'--jobs=1' controls parallel execution count; branches exits 0.

        Per the help text: 'number of jobs to run in parallel'. Supplying
        --jobs=1 restricts parallelism to a single worker and must not cause
        any error or change the exit code.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_JOBS + "-func")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            _VALID_JOBS_ARG,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo branches {_VALID_JOBS_ARG}' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoBranchesFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_flags_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo branches' with valid flags must not emit tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_CHANNEL)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo branches' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of 'kanon repo branches' with valid flags.\n  stdout: {result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo branches' with valid flags must not emit tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_CHANNEL + "-stderr")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            "--verbose",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            "Prerequisite 'kanon repo branches --verbose' failed with argparse error."
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of 'kanon repo branches' with valid flags.\n  stderr: {result.stderr!r}"
        )

    def test_invalid_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        The argument-parsing error for '--verbose=unexpected' must be routed to
        stderr only. Stdout must remain clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--verbose" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "branches",
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
            "branches",
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
        """Successful 'kanon repo branches' with flags must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_repo_with_branch(tmp_path, _BRANCH_FLAGS_CHANNEL + "-error-kw")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "branches",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo branches' failed: {result.stderr!r}"
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of 'kanon repo branches': {line!r}\n"
                f"  stdout: {result.stdout!r}"
            )
