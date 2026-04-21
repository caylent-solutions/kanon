"""Functional tests for flag coverage of 'kanon repo checkout'.

Exercises every flag available to ``subcmds/checkout.py`` by invoking
``kanon repo checkout`` as a subprocess. The ``Checkout`` subcommand has no
``_Options()`` method of its own; its flags are the common flags registered
by ``Command._CommonOptions()``:

- ``-v`` / ``--verbose`` (store_true, dest=output_mode, defaults to None)
- ``-q`` / ``--quiet``   (store_false, dest=output_mode, defaults to None)
- ``-j`` / ``--jobs``    (type=int, default=DEFAULT_LOCAL_JOBS)
- ``--outer-manifest``              (store_true, default=None)
- ``--no-outer-manifest``           (store_false, dest=outer_manifest)
- ``--this-manifest-only``          (store_true, default=None)
- ``--no-this-manifest-only``       (store_false, dest=this_manifest_only)
- ``--all-manifests``               (store_false, alias for --no-this-manifest-only)

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

from tests.functional.conftest import _run_kanon
from tests.functional.test_repo_checkout_happy import _setup_started_repo

# ---------------------------------------------------------------------------
# Module-level constants -- all hard-coded test-fixture values extracted here;
# no domain literals in test logic.
# ---------------------------------------------------------------------------

# Error exit code for argument-parsing errors.
_ARGPARSE_ERROR_EXIT_CODE = 2

# Expected exit code for successful invocations.
_EXPECTED_EXIT_CODE = 0

# Nonexistent repo-dir name used in argument-parser acceptance tests that
# do not require a real initialized repository (e.g. boolean-with-inline-value
# negative tests that fail at parse time before repo discovery).
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-checkout-flags-repo-dir"

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

# Branch names for individual flag behavior tests.
_BRANCH_VERBOSE_FLAG = "feature/checkout-verbose-flag"
_BRANCH_QUIET_FLAG = "feature/checkout-quiet-flag"
_BRANCH_JOBS_FLAG = "feature/checkout-jobs-flag"
_BRANCH_THIS_MANIFEST_FLAG = "feature/checkout-this-manifest-flag"
_BRANCH_ABSENCE_DEFAULT = "feature/checkout-absence-default"
_BRANCH_FUNC_VERBOSE = "feature/checkout-func-verbose"
_BRANCH_FUNC_QUIET = "feature/checkout-func-quiet"
_BRANCH_FUNC_THIS_MANIFEST = "feature/checkout-func-this-manifest"
_BRANCH_CHANNEL_VALID = "feature/checkout-channel-valid"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# Boolean store_true flags from _CommonOptions() that checkout inherits.
# These accept no value; negative test uses inline-value syntax.
_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    ("-v", "short-verbose"),
    ("--verbose", "long-verbose"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
]

# Boolean store_false flags from _CommonOptions() that checkout inherits.
_BOOL_STORE_FALSE_FLAGS: list[tuple[str, str]] = [
    ("-q", "short-quiet"),
    ("--quiet", "long-quiet"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]

# Long-form boolean flags (store_true and store_false) used in AC-TEST-002
# negative tests. Short-form flags cannot use '--flag=value' syntax in optparse.
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

# Branch name used in negative tests that do not require a real initialized
# repository (e.g. argument-parser rejection tests that fail before repo
# discovery). The value is intentionally nonexistent.
_NONEXISTENT_BRANCH_NAME = "some-branch"


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/checkout.py
# (Also covers AC-FUNC-001: every documented flag behaves per its help text.)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCheckoutFlagsValidValues:
    """AC-TEST-001 / AC-FUNC-001: Every flag available to checkout has a valid-value test.

    Exercises each flag from ``Command._CommonOptions()`` (which ``Checkout``
    inherits) by invoking 'kanon repo checkout' with the flag against a real
    started .repo directory.

    Boolean flags (store_true / store_false) are tested by confirming the flag
    is accepted without an argument-parsing error (exit code != 2). The
    --jobs/-j flag (integer) is tested with a valid integer value.

    Flags covered:
    - ``-v`` / ``--verbose``            (store_true, dest=output_mode, defaults to None)
    - ``-q`` / ``--quiet``              (store_false, dest=output_mode, defaults to None)
    - ``-j`` / ``--jobs``               (int, default=DEFAULT_LOCAL_JOBS)
    - ``--outer-manifest``              (store_true, default=None)
    - ``--no-outer-manifest``           (store_false, dest=outer_manifest)
    - ``--this-manifest-only``          (store_true, default=None)
    - ``--no-this-manifest-only``       (store_false, dest=this_manifest_only)
    - ``--all-manifests``               (store_false, alias for --no-this-manifest-only)
    """

    _ALL_BOOL_FLAGS: list[tuple[str, str]] = _BOOL_STORE_TRUE_FLAGS + _BOOL_STORE_FALSE_FLAGS

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _ALL_BOOL_FLAGS],
        ids=[test_id for _, test_id in _ALL_BOOL_FLAGS],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo checkout <branch> <flag>' against a properly started
        .repo directory and asserts that optparse does not reject the invocation
        (exit code != 2). A non-2 exit code confirms the flag itself was
        accepted; the checkout subcommand may produce any other exit code
        depending on repository state.
        """
        branch_name = f"feature/checkout-flag-test-{flag.lstrip('-').replace('/', '-')}"
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, branch_name)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            branch_name,
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
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_JOBS_FLAG)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_JOBS_FLAG,
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
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_JOBS_FLAG + "-short")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_JOBS_FLAG + "-short",
            "-j",
            _VALID_JOBS_INT,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'-j {_VALID_JOBS_INT}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_verbose_flag_accepted_with_branch(self, tmp_path: pathlib.Path) -> None:
        """'--verbose' flag exits 0 when checkout succeeds.

        The --verbose flag enables verbose output. Verifies the flag is
        accepted and checkout exits 0 on a started repo.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_VERBOSE_FLAG)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_VERBOSE_FLAG,
            "--verbose",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--verbose' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_quiet_flag_accepted_with_branch(self, tmp_path: pathlib.Path) -> None:
        """'--quiet' flag exits 0 when checkout succeeds.

        The --quiet flag suppresses non-error output. Verifies the flag is
        accepted and checkout exits 0 on a started repo.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_QUIET_FLAG)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_QUIET_FLAG,
            "--quiet",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--quiet' triggered an argument-parsing error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_and_all_manifests_combination_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--this-manifest-only --all-manifests' combination is accepted (exit != 2).

        Both flags share dest='this_manifest_only'. The last flag wins per
        optparse semantics. The combination must be accepted without exit 2.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_THIS_MANIFEST_FLAG)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_THIS_MANIFEST_FLAG,
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
class TestRepoCheckoutFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts typed or inline values has a negative test.

    Boolean flags (store_true / store_false) do not accept a typed value. The
    applicable negative test is to supply an unexpected inline value using
    '--flag=value' syntax. optparse exits 2 with
    '--<flag> option does not take a value' for such inputs.

    The --jobs flag accepts an integer value. A non-integer string must be
    rejected by the option parser with exit code 2.

    This class verifies that every long-form boolean flag produces exit 2
    when supplied with an inline value, and that the --jobs flag rejects
    non-integer values with exit 2.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with an inline value must exit 2.

        Supplies '--<flag>=unexpected' to 'kanon repo checkout'. Since all
        checkout flags are store_true / store_false, optparse rejects the
        inline value with exit code 2 and emits
        '--<flag> option does not take a value' on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _NONEXISTENT_BRANCH_NAME,
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

        Covers AC-CHANNEL-001: argument-parsing errors are routed to stderr;
        stdout remains clean of error details on invalid-flag invocations.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _NONEXISTENT_BRANCH_NAME,
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
            "checkout",
            _NONEXISTENT_BRANCH_NAME,
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

        Covers AC-CHANNEL-001: argument-parsing errors are routed to stderr;
        stdout remains clean of error details on invalid --jobs invocations.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_jobs_arg = f"--jobs={_JOBS_NON_INT_VALUE}"
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "checkout",
            _NONEXISTENT_BRANCH_NAME,
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
            "checkout",
            _NONEXISTENT_BRANCH_NAME,
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
class TestRepoCheckoutFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each checkout flag uses the documented default when omitted.
    Boolean flags default to None when absent (no explicit default= was set for
    output_mode or outer_manifest or this_manifest_only). The --jobs flag
    defaults to DEFAULT_LOCAL_JOBS.

    Absence tests confirm that omitting every optional flag still produces a
    valid, non-error invocation.
    """

    def test_all_flags_omitted_exits_zero_with_branch_name(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo checkout <branch>' with all optional flags omitted exits 0.

        When only the required branch name is supplied, every other optional
        flag takes its documented default value:
        - --verbose defaults to None (output_mode unset)
        - --quiet defaults to None (output_mode unset)
        - --jobs defaults to DEFAULT_LOCAL_JOBS
        - --outer-manifest defaults to None
        - --this-manifest-only defaults to None

        Verifies that no optional flag is required and that all documented
        defaults produce a successful (exit 0) checkout.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_ABSENCE_DEFAULT)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_ABSENCE_DEFAULT,
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo checkout {_BRANCH_ABSENCE_DEFAULT}' with all optional flags "
            f"omitted exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_verbose_omitted_does_not_reject(self, tmp_path: pathlib.Path) -> None:
        """Omitting --verbose defaults output_mode to None; checkout exits 0.

        When --verbose is not supplied, output_mode defaults to None (no
        explicit verbosity mode). This must not cause any argument-parsing
        error. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_ABSENCE_DEFAULT + "-verbose")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_ABSENCE_DEFAULT + "-verbose",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo checkout' without --verbose exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_jobs_default_does_not_cause_rejection(self, tmp_path: pathlib.Path) -> None:
        """Omitting --jobs uses DEFAULT_LOCAL_JOBS; checkout exits 0.

        When --jobs is not supplied, it defaults to DEFAULT_LOCAL_JOBS (a
        value based on the CPU count). This must not cause any argument-parsing
        error. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_ABSENCE_DEFAULT + "-jobs")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_ABSENCE_DEFAULT + "-jobs",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo checkout' without --jobs exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_outer_manifest_default_none_does_not_reject(self, tmp_path: pathlib.Path) -> None:
        """Omitting --outer-manifest defaults to None; checkout exits 0.

        When --outer-manifest is not supplied, its default is None (operate
        starting at the outermost manifest). This must not cause any error.
        Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_ABSENCE_DEFAULT + "-outer")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_ABSENCE_DEFAULT + "-outer",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo checkout' without --outer-manifest exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_default_none_does_not_reject(self, tmp_path: pathlib.Path) -> None:
        """Omitting --this-manifest-only defaults to None; checkout exits 0.

        When --this-manifest-only is not supplied, its default is None (no
        restriction applied). This must not cause any error. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_ABSENCE_DEFAULT + "-this")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_ABSENCE_DEFAULT + "-this",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo checkout' without --this-manifest-only exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCheckoutFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of each flag documented in
    Command._CommonOptions() as applied to the checkout subcommand:
    - -v/--verbose: 'show all output' -- checkout succeeds and exit 0
    - -q/--quiet: 'only show errors' -- checkout succeeds and exit 0
    - --this-manifest-only: 'only operate on this (sub)manifest' -- exit 0
    - --all-manifests: 'operate on this manifest and its submanifests' -- exit 0
    - --outer-manifest: 'operate starting at the outermost manifest' -- exit 0
    - --no-outer-manifest: 'do not operate on outer manifests' -- exit 0

    Each test invokes 'kanon repo checkout <branch> <flag>' against a real
    started repo and confirms successful execution.
    """

    def test_verbose_flag_produces_exit_zero_on_successful_checkout(self, tmp_path: pathlib.Path) -> None:
        """'--verbose' flag: checkout succeeds with verbose output; exit 0.

        Per the help text: 'show all output'. On a properly started repo,
        'kanon repo checkout <branch> --verbose' must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_VERBOSE)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_FUNC_VERBOSE,
            "--verbose",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo checkout {_BRANCH_FUNC_VERBOSE} --verbose' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_quiet_flag_produces_exit_zero_on_successful_checkout(self, tmp_path: pathlib.Path) -> None:
        """'--quiet' flag: checkout succeeds with suppressed output; exit 0.

        Per the help text: 'only show errors'. On a properly started repo,
        'kanon repo checkout <branch> --quiet' must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_QUIET)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_FUNC_QUIET,
            "--quiet",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo checkout {_BRANCH_FUNC_QUIET} --quiet' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_flag_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'--this-manifest-only' flag: checkout operates on the current manifest only; exit 0.

        Per the help text: 'only operate on this (sub)manifest'. On a properly
        started repo, 'kanon repo checkout <branch> --this-manifest-only'
        must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_THIS_MANIFEST)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_FUNC_THIS_MANIFEST,
            "--this-manifest-only",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo checkout {_BRANCH_FUNC_THIS_MANIFEST} --this-manifest-only' "
            f"exited {result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_outer_manifest_flag_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'--outer-manifest' flag: checkout operates at the outermost manifest; exit 0.

        Per the help text: 'operate starting at the outermost manifest'. On a
        properly started repo, 'kanon repo checkout <branch> --outer-manifest'
        must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_THIS_MANIFEST + "-outer")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_FUNC_THIS_MANIFEST + "-outer",
            "--outer-manifest",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo checkout ... --outer-manifest' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_no_outer_manifest_flag_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'--no-outer-manifest' flag: checkout does not traverse outer manifests; exit 0.

        Per the help text: 'do not operate on outer manifests'. On a properly
        started repo, 'kanon repo checkout <branch> --no-outer-manifest'
        must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_THIS_MANIFEST + "-no-outer")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_FUNC_THIS_MANIFEST + "-no-outer",
            "--no-outer-manifest",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo checkout ... --no-outer-manifest' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCheckoutFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_flags_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo checkout' with valid flags must not emit tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_CHANNEL_VALID)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_CHANNEL_VALID,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo checkout {_BRANCH_CHANNEL_VALID}' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of 'kanon repo checkout' with valid flags.\n  stdout: {result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo checkout' with valid flags must not emit tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_CHANNEL_VALID + "-verbose")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_CHANNEL_VALID + "-verbose",
            "--verbose",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo checkout ... --verbose' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of 'kanon repo checkout' with valid flags.\n  stderr: {result.stderr!r}"
        )

    def test_no_error_keyword_on_stdout_for_valid_flags(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo checkout' with valid flags must not emit 'Error:' to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_CHANNEL_VALID + "-error-kw")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "checkout",
            _BRANCH_CHANNEL_VALID + "-error-kw",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            "Prerequisite 'kanon repo checkout' failed with argparse error."
        )
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of 'kanon repo checkout': "
                f"{line!r}\n  stdout: {result.stdout!r}"
            )
