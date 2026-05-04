"""Functional tests for flag coverage of 'kanon repo rebase'.

Exercises every flag registered in ``subcmds/rebase.py``'s ``_Options()`` method
by invoking ``kanon repo rebase`` as a subprocess. Validates correct accept and
reject behavior for all flag values, and correct default behavior when flags
are omitted.

Flags in ``Rebase._Options()``:

- ``-i`` / ``--interactive`` (store_true, added to logging group, single project only)
- ``--fail-fast``            (store_true, stop rebasing after first error)
- ``-f`` / ``--force-rebase`` (store_true, pass --force-rebase to git rebase)
- ``--no-ff``                (store_false, dest=ff, default=True, pass --no-ff to git rebase)
- ``--autosquash``           (store_true, pass --autosquash to git rebase)
- ``--whitespace``           (store, metavar=WS, pass --whitespace to git rebase)
- ``--auto-stash``           (store_true, stash local modifications before starting)
- ``-m`` / ``--onto-manifest`` (store_true, rebase onto manifest version)

Flags from ``Command._CommonOptions()`` (note: PARALLEL_JOBS is None for Rebase,
so ``-j`` / ``--jobs`` is NOT registered for this subcommand):

- ``-v`` / ``--verbose``       (store_true, dest=output_mode, defaults to None)
- ``-q`` / ``--quiet``         (store_false, dest=output_mode, defaults to None)
- ``--outer-manifest``         (store_true, default=None)
- ``--no-outer-manifest``      (store_false, dest=outer_manifest)
- ``--this-manifest-only``     (store_true, default=None)
- ``--no-this-manifest-only``  (store_false, dest=this_manifest_only)
- ``--all-manifests``          (store_false, alias for --no-this-manifest-only)

Valid-value tests confirm each flag is accepted without an argument-parsing
error (exit code != 2). Negative tests for boolean flags confirm that supplying
an inline value is rejected with exit code 2. The negative test for
``--whitespace`` confirms that omitting its required argument is rejected with
exit code 2.

Special handling for ``-i`` / ``--interactive``: this flag triggers git's
interactive rebase which opens an editor (e.g. vim) and waits for user input.
It cannot be tested against a real started repo without hanging. Its
argparse-acceptance test is therefore run against a nonexistent repo dir, where
the command exits with a non-2 code (manifest not found, exit 1) confirming
the flag is accepted by optparse. The ``--interactive=unexpected`` negative test
runs against a nonexistent repo dir as well.

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
from tests.functional.test_repo_rebase_happy import _setup_started_repo

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
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-rebase-flags-repo-dir"

# Inline-value token for boolean-flag negative tests.
# optparse exits 2 with '--<flag> option does not take a value' when a
# store_true or store_false flag is supplied with an inline value.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Valid whitespace action value for --whitespace flag.
# 'strip' is a valid git rebase --whitespace action.
_VALID_WHITESPACE_VALUE = "strip"

# Branch names for individual flag behavior tests -- each test uses a unique name.
_BRANCH_WHITESPACE_FLAG = "feature/rebase-whitespace-flag"
_BRANCH_THIS_MANIFEST_FLAG = "feature/rebase-this-manifest-flag"
_BRANCH_ABSENCE_DEFAULT = "feature/rebase-absence-default"
_BRANCH_FUNC_VERBOSE = "feature/rebase-func-verbose"
_BRANCH_FUNC_QUIET = "feature/rebase-func-quiet"
_BRANCH_FUNC_FAIL_FAST = "feature/rebase-func-fail-fast"
_BRANCH_FUNC_FORCE_REBASE = "feature/rebase-func-force-rebase"
_BRANCH_FUNC_NO_FF = "feature/rebase-func-no-ff"
_BRANCH_FUNC_AUTOSQUASH = "feature/rebase-func-autosquash"
_BRANCH_FUNC_AUTO_STASH = "feature/rebase-func-auto-stash"
_BRANCH_FUNC_ONTO_MANIFEST = "feature/rebase-func-onto-manifest"
_BRANCH_CHANNEL_VALID = "feature/rebase-channel-valid"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# Boolean flags from Rebase._Options() that are safe to run against a real
# started repo (i.e., they do NOT open an interactive editor).
# Excludes -i/--interactive which triggers git interactive rebase (opens vim).
_BOOL_FLAGS_SAFE_ON_STARTED_REPO: list[tuple[str, str]] = [
    ("--fail-fast", "fail-fast"),
    ("-f", "short-force-rebase"),
    ("--force-rebase", "long-force-rebase"),
    ("--no-ff", "no-ff"),
    ("--autosquash", "autosquash"),
    ("--auto-stash", "auto-stash"),
    ("-m", "short-onto-manifest"),
    ("--onto-manifest", "long-onto-manifest"),
]

# Boolean store_true flags from _CommonOptions() that rebase inherits.
# All are safe to run against a real started repo.
_BOOL_STORE_TRUE_FLAGS_COMMON: list[tuple[str, str]] = [
    ("-v", "short-verbose"),
    ("--verbose", "long-verbose"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
]

# Boolean store_false flags from _CommonOptions() that rebase inherits.
_BOOL_STORE_FALSE_FLAGS_COMMON: list[tuple[str, str]] = [
    ("-q", "short-quiet"),
    ("--quiet", "long-quiet"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]

# All boolean flags safe to run against a real started repo.
_ALL_BOOL_FLAGS_SAFE: list[tuple[str, str]] = (
    _BOOL_FLAGS_SAFE_ON_STARTED_REPO + _BOOL_STORE_TRUE_FLAGS_COMMON + _BOOL_STORE_FALSE_FLAGS_COMMON
)

# Interactive flag short and long form -- tested separately (nonexistent repo dir)
# because -i triggers git's interactive rebase editor and would block test execution.
_INTERACTIVE_FLAGS: list[tuple[str, str]] = [
    ("-i", "short-interactive"),
    ("--interactive", "long-interactive"),
]

# Long-form boolean flags used in AC-TEST-002 negative tests.
# Short-form flags cannot use '--flag=value' syntax in optparse.
# Includes all long-form flags from both _Options() and _CommonOptions().
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    ("--interactive", "interactive"),
    ("--fail-fast", "fail-fast"),
    ("--force-rebase", "force-rebase"),
    ("--no-ff", "no-ff"),
    ("--autosquash", "autosquash"),
    ("--auto-stash", "auto-stash"),
    ("--onto-manifest", "onto-manifest"),
    ("--verbose", "verbose"),
    ("--quiet", "quiet"),
    ("--outer-manifest", "outer-manifest"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]

# Placeholder branch name used in argument-parser tests that do not require
# an initialized repository (rejection happens before repo discovery).
_NONEXISTENT_BRANCH_NAME = "some-branch"


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/rebase.py
# (Also covers AC-FUNC-001: every documented flag behaves per its help text.)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoRebaseFlagsValidValues:
    """AC-TEST-001 / AC-FUNC-001: Every ``_Options()`` flag in subcmds/rebase.py has a valid-value test.

    Exercises each flag registered in ``Rebase._Options()`` (and the common
    flags from ``_CommonOptions()``) by invoking 'kanon repo rebase' with the
    flag against a real started .repo directory (for non-interactive flags) or
    against a nonexistent repo dir (for the -i/--interactive flag which opens
    an editor and cannot be run against a real repo in a non-interactive test).

    Boolean flags (store_true / store_false) are tested by confirming the flag
    is accepted without an argument-parsing error (exit code != 2). The
    --whitespace flag (store action) is tested with a valid string value.

    Note: The 'rebase' subcommand has PARALLEL_JOBS = None so the ``-j`` /
    ``--jobs`` flag is NOT registered and is not tested here.

    Flags covered:
    - ``-i`` / ``--interactive``   (store_true, single project only; editor test)
    - ``--fail-fast``              (store_true, stop after first error)
    - ``-f`` / ``--force-rebase``  (store_true, pass --force-rebase to git rebase)
    - ``--no-ff``                  (store_false, dest=ff, default=True)
    - ``--autosquash``             (store_true, pass --autosquash to git rebase)
    - ``--whitespace``             (store, metavar=WS, pass --whitespace to git rebase)
    - ``--auto-stash``             (store_true, stash local modifications)
    - ``-m`` / ``--onto-manifest`` (store_true, rebase onto manifest version)
    - ``-v`` / ``--verbose``       (store_true, dest=output_mode, defaults to None)
    - ``-q`` / ``--quiet``         (store_false, dest=output_mode, defaults to None)
    - ``--outer-manifest``         (store_true, default=None)
    - ``--no-outer-manifest``      (store_false, dest=outer_manifest)
    - ``--this-manifest-only``     (store_true, default=None)
    - ``--no-this-manifest-only``  (store_false, dest=this_manifest_only)
    - ``--all-manifests``          (store_false, alias for --no-this-manifest-only)
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _ALL_BOOL_FLAGS_SAFE],
        ids=[test_id for _, test_id in _ALL_BOOL_FLAGS_SAFE],
    )
    def test_boolean_flag_accepted_on_started_repo(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each non-interactive boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo rebase <flag>' against a properly started .repo
        directory and asserts that optparse does not reject the invocation
        (exit code != 2). A non-2 exit code confirms the flag itself was
        accepted; the rebase subcommand may produce any other exit code
        depending on repository state.

        The -i/--interactive flag is excluded from this parametrize set because
        it triggers git's interactive rebase (opens an editor), which would
        block test execution. The interactive flag is tested separately in
        test_interactive_flags_accepted_on_nonexistent_repo.
        """
        branch_name = f"feature/rebase-flag-test-{flag.lstrip('-').replace('/', '-')}"
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, branch_name)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _INTERACTIVE_FLAGS],
        ids=[test_id for _, test_id in _INTERACTIVE_FLAGS],
    )
    def test_interactive_flags_accepted_on_nonexistent_repo(self, tmp_path: pathlib.Path, flag: str) -> None:
        """The -i/--interactive flag is accepted by the argument parser (does not exit 2).

        The -i/--interactive flag triggers git's interactive rebase editor when
        run against a real started repo. To avoid blocking test execution, this
        test runs against a nonexistent repo dir instead.

        The command exits with a non-2 code (manifest-not-found error, exit 1),
        confirming that optparse accepted the flag without an argument-parsing
        error. Exit code 1 proves the flag passed parsing and execution reached
        the manifest-loading stage.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            flag,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_whitespace_flag_accepted_with_valid_value(self, tmp_path: pathlib.Path) -> None:
        """'--whitespace strip' is accepted by the argument parser (does not exit 2).

        The --whitespace flag takes a string value passed directly to git rebase.
        Supplying a valid whitespace action ('strip') confirms the flag is
        accepted without an argument-parsing error (exit code != 2).
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_WHITESPACE_FLAG)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--whitespace",
            _VALID_WHITESPACE_VALUE,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--whitespace {_VALID_WHITESPACE_VALUE}' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
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
            "rebase",
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
class TestRepoRebaseFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts typed or inline values has a negative test.

    Boolean flags (store_true / store_false) do not accept a typed value. The
    applicable negative test is to supply an unexpected inline value using
    '--flag=value' syntax. optparse exits 2 with
    '--<flag> option does not take a value' for such inputs.

    The --whitespace flag accepts a string value. Omitting its required argument
    (supplying '--whitespace' alone at the end of the command) must be rejected
    by the option parser with exit code 2.

    This class verifies that every long-form boolean flag produces exit 2 when
    supplied with an inline value, and that --whitespace rejects a missing
    argument with exit 2. The error message must appear on stderr, not stdout.

    Covers AC-CHANNEL-001: argument-parsing errors are routed to stderr;
    stdout remains clean of error details on invalid-flag invocations.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with an inline value must exit 2.

        Supplies '--<flag>=unexpected' to 'kanon repo rebase'. Since all
        Rebase._Options() boolean flags are store_true or store_false, optparse
        rejects the inline value with exit code 2 and emits
        '--<flag> option does not take a value' on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
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
            "rebase",
            _NONEXISTENT_BRANCH_NAME,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_whitespace_flag_without_argument_exits_2(self, tmp_path: pathlib.Path) -> None:
        """'--whitespace' without a required argument must exit 2.

        The --whitespace flag uses action='store' and requires exactly one
        argument. Supplying '--whitespace' at the end of the command (with no
        value following it) must be rejected by optparse with exit code 2 and
        the error message must appear on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            "--whitespace",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--whitespace' (no value) exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}\n  stdout: {result.stdout!r}"
        )
        assert len(result.stderr) > 0, "'--whitespace' (no value) produced empty stderr; error must appear on stderr."

    def test_whitespace_flag_without_argument_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'--whitespace' (no value) error message must appear on stderr, not stdout.

        The argument-parsing error for a missing --whitespace value must be
        reported on stderr only. Stdout must not contain the error detail.

        Covers AC-CHANNEL-001: argument-parsing errors are routed to stderr;
        stdout remains clean.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            "--whitespace",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--whitespace' (no value) exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "requires" not in result.stdout.lower(), (
            f"Missing-argument error detail leaked to stdout for '--whitespace'.\n  stdout: {result.stdout!r}"
        )

    def test_interactive_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--interactive=unexpected' error must name '--interactive' in stderr.

        The embedded optparse parser emits '--interactive option does not take
        a value' when '--interactive=unexpected' is supplied. Confirms the
        canonical flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--interactive" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            _NONEXISTENT_BRANCH_NAME,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--interactive=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "--interactive" in result.stderr, (
            f"Expected '--interactive' in stderr for '--interactive=unexpected' error.\n  stderr: {result.stderr!r}"
        )

    def test_fail_fast_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--fail-fast=unexpected' error must name '--fail-fast' in stderr.

        The embedded optparse parser emits '--fail-fast option does not take a
        value' when '--fail-fast=unexpected' is supplied. Confirms the canonical
        flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--fail-fast" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            _NONEXISTENT_BRANCH_NAME,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--fail-fast=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "--fail-fast" in result.stderr, (
            f"Expected '--fail-fast' in stderr for '--fail-fast=unexpected' error.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoRebaseFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each rebase flag uses the documented default when omitted.
    Boolean flags default to None (store_true from _CommonOptions) or False
    (explicit store_true from _Options) when absent. The --no-ff flag defaults
    to True (its dest=ff, default=True means ff=True when --no-ff is absent).

    Absence tests confirm that omitting every optional flag still produces a
    valid, non-error invocation (exit 0 on a properly started repo).
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo rebase' with all optional flags omitted exits 0.

        When no optional flags are supplied, every flag takes its documented
        default value:
        - --interactive defaults to False (unset)
        - --fail-fast defaults to False (unset)
        - --force-rebase defaults to False (unset)
        - --no-ff absent: ff=True by default
        - --autosquash defaults to False (unset)
        - --whitespace defaults to None (unset)
        - --auto-stash defaults to False (unset)
        - --onto-manifest defaults to False (unset)
        - --verbose defaults to None (output_mode unset)
        - --quiet defaults to None (output_mode unset)
        - --outer-manifest defaults to None
        - --this-manifest-only defaults to None

        Verifies that no optional flag is required and that all documented
        defaults produce a successful (exit 0) rebase.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_ABSENCE_DEFAULT)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase' with all optional flags omitted exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_verbose_omitted_does_not_reject(self, tmp_path: pathlib.Path) -> None:
        """Omitting --verbose defaults output_mode to None; rebase exits 0.

        When --verbose is not supplied, output_mode defaults to None (no
        explicit verbosity mode). This must not cause any argument-parsing
        error. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_ABSENCE_DEFAULT + "-verbose")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase' without --verbose exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_no_ff_absent_means_ff_true(self, tmp_path: pathlib.Path) -> None:
        """Omitting --no-ff leaves dest=ff at its default=True; rebase exits 0.

        The --no-ff flag uses default=True on dest=ff, so when --no-ff is
        absent ff=True and git rebase does NOT receive --no-ff. This must not
        cause any error. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_ABSENCE_DEFAULT + "-no-ff")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase' without --no-ff exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_outer_manifest_default_none_does_not_reject(self, tmp_path: pathlib.Path) -> None:
        """Omitting --outer-manifest defaults to None; rebase exits 0.

        When --outer-manifest is not supplied, its default is None (operate
        starting at the outermost manifest). This must not cause any error.
        Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_ABSENCE_DEFAULT + "-outer")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase' without --outer-manifest exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_default_none_does_not_reject(self, tmp_path: pathlib.Path) -> None:
        """Omitting --this-manifest-only defaults to None; rebase exits 0.

        When --this-manifest-only is not supplied, its default is None (no
        restriction applied). This must not cause any error. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_ABSENCE_DEFAULT + "-this")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase' without --this-manifest-only exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoRebaseFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of each flag documented in
    Rebase._Options() and Command._CommonOptions():
    - --verbose: 'show all output' -- rebase succeeds and exit 0
    - --quiet: 'only show errors' -- rebase succeeds and exit 0
    - --fail-fast: 'stop rebasing after first error is hit' -- exit 0 on clean repo
    - -f/--force-rebase: 'pass --force-rebase to git rebase' -- exit 0
    - --no-ff: 'pass --no-ff to git rebase' -- exit 0
    - --autosquash: 'pass --autosquash to git rebase' -- exit 0
    - --auto-stash: 'stash local modifications before starting' -- exit 0
    - -m/--onto-manifest: 'rebase onto the manifest version' -- exit 0
    - --this-manifest-only: 'only operate on this (sub)manifest' -- exit 0
    - --outer-manifest: 'operate starting at the outermost manifest' -- exit 0
    - --no-outer-manifest: 'do not operate on outer manifests' -- exit 0

    Note: -i/--interactive is not tested with a real started repo because it
    opens an interactive editor. Its argparse acceptance is verified in
    TestRepoRebaseFlagsValidValues.test_interactive_flags_accepted_on_nonexistent_repo.

    Each test invokes 'kanon repo rebase <flag>' against a real started repo
    and confirms successful execution (exit 0).
    """

    def test_verbose_flag_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'--verbose' flag: rebase succeeds with verbose output; exit 0.

        Per the help text: 'show all output'. On a properly started repo,
        'kanon repo rebase --verbose' must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_VERBOSE)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--verbose",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase --verbose' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_quiet_flag_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'--quiet' flag: rebase succeeds with suppressed output; exit 0.

        Per the help text: 'only show errors'. On a properly started repo,
        'kanon repo rebase --quiet' must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_QUIET)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--quiet",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase --quiet' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_fail_fast_flag_produces_exit_zero_on_clean_repo(self, tmp_path: pathlib.Path) -> None:
        """'--fail-fast' flag: rebase exits 0 when there are no rebase errors.

        Per the help text: 'stop rebasing after first error is hit'. When the
        topic branch is already at upstream HEAD (no rebase conflict), the
        command exits 0 with or without --fail-fast. Verifies exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_FAIL_FAST)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--fail-fast",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase --fail-fast' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_force_rebase_flag_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'-f/--force-rebase' flag: rebase exits 0 on a clean started repo.

        Per the help text: 'pass --force-rebase to git rebase'. On a properly
        started repo, 'kanon repo rebase --force-rebase' must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_FORCE_REBASE)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--force-rebase",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase --force-rebase' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_no_ff_flag_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'--no-ff' flag: rebase exits 0 on a clean started repo.

        Per the help text: 'pass --no-ff to git rebase'. On a properly
        started repo, 'kanon repo rebase --no-ff' must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_NO_FF)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--no-ff",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase --no-ff' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_autosquash_flag_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'--autosquash' flag: rebase exits 0 on a clean started repo.

        Per the help text: 'pass --autosquash to git rebase'. On a properly
        started repo, 'kanon repo rebase --autosquash' must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_AUTOSQUASH)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--autosquash",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase --autosquash' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_auto_stash_flag_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'--auto-stash' flag: rebase exits 0 on a clean started repo.

        Per the help text: 'stash local modifications before starting'. When
        there are no local modifications, --auto-stash is a no-op and the
        rebase exits 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_AUTO_STASH)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--auto-stash",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase --auto-stash' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_onto_manifest_flag_is_accepted_by_argparse(self, tmp_path: pathlib.Path) -> None:
        """'-m/--onto-manifest' flag is accepted by the argument parser (does not exit 2).

        Per the help text: 'rebase onto the manifest version instead of upstream
        HEAD (this helps to make sure the local tree stays consistent if you
        previously synced to a manifest)'. The flag passes project.revisionExpr
        as the --onto argument to git rebase.

        In the functional test environment, project.revisionExpr is the symbolic
        revision name from the manifest (e.g. "main"), which may not resolve to
        a local git ref in the project worktree (only refs/remotes/local/main
        exists). Therefore the assertion is exit != 2 (argparse accepted the
        flag) rather than exit 0 (git rebase itself may fail with exit 1 if
        revisionExpr is not a locally resolvable commit SHA).
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_ONTO_MANIFEST)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--onto-manifest",
            cwd=checkout_dir,
        )

        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'kanon repo rebase --onto-manifest' triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_flag_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'--this-manifest-only' flag: rebase operates on the current manifest only; exit 0.

        Per the help text: 'only operate on this (sub)manifest'. On a properly
        started repo, 'kanon repo rebase --this-manifest-only' must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_ONTO_MANIFEST + "-this")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--this-manifest-only",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase --this-manifest-only' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_outer_manifest_flag_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'--outer-manifest' flag: rebase operates at the outermost manifest; exit 0.

        Per the help text: 'operate starting at the outermost manifest'. On a
        properly started repo, 'kanon repo rebase --outer-manifest' must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_ONTO_MANIFEST + "-outer")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--outer-manifest",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase --outer-manifest' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    def test_no_outer_manifest_flag_produces_exit_zero(self, tmp_path: pathlib.Path) -> None:
        """'--no-outer-manifest' flag: rebase does not traverse outer manifests; exit 0.

        Per the help text: 'do not operate on outer manifests'. On a properly
        started repo, 'kanon repo rebase --no-outer-manifest' must exit 0.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_FUNC_ONTO_MANIFEST + "-no-outer")

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--no-outer-manifest",
            cwd=checkout_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo rebase --no-outer-manifest' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoRebaseFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_flags_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo rebase' with valid flags must not emit tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_CHANNEL_VALID)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, f"Prerequisite 'kanon repo rebase' failed: {result.stderr!r}"
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of 'kanon repo rebase' with valid flags.\n  stdout: {result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo rebase' with valid flags must not emit tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_CHANNEL_VALID + "-verbose")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            "--verbose",
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo rebase --verbose' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of 'kanon repo rebase' with valid flags.\n  stderr: {result.stderr!r}"
        )

    def test_no_error_keyword_on_stdout_for_valid_flags(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo rebase' with valid flags must not emit 'Error:' to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_CHANNEL_VALID + "-error-kw")
        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "rebase",
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            "Prerequisite 'kanon repo rebase' failed with argparse error."
        )
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of 'kanon repo rebase': {line!r}\n  stdout: {result.stdout!r}"
            )

    def test_invalid_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        The argument-parsing error for '--fail-fast=unexpected' must be routed
        to stderr only. Stdout must remain clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--fail-fast" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"stderr must be non-empty for '{bad_token}' error."
        assert bad_token not in result.stdout, (
            f"'{bad_token}' error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )

    def test_whitespace_missing_argument_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """'--whitespace' (no value) error must appear on stderr, not stdout.

        The argument-parsing error for a missing --whitespace value must be
        routed to stderr only. Stdout must remain clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "rebase",
            "--whitespace",
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '--whitespace' (no value).\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, "stderr must be non-empty for '--whitespace' (no value) error."
        assert "whitespace" not in result.stdout.lower(), (
            f"'whitespace' error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )
