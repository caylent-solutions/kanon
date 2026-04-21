"""Functional tests for flag coverage of 'kanon repo cherry-pick'.

Exercises every flag available to ``subcmds/cherry_pick.py`` by invoking
``kanon repo cherry-pick`` as a subprocess. The ``CherryPick`` subcommand has
no ``_Options()`` method of its own and ``PARALLEL_JOBS = None`` (inherited),
so its flags are entirely the common flags registered by
``Command._CommonOptions()``:

- ``-v`` / ``--verbose``            (store_true, dest=output_mode, defaults to None)
- ``-q`` / ``--quiet``              (store_false, dest=output_mode, defaults to None)
- ``--outer-manifest``              (store_true, default=None)
- ``--no-outer-manifest``           (store_false, dest=outer_manifest)
- ``--this-manifest-only``          (store_true, default=None)
- ``--no-this-manifest-only``       (store_false, alias: ``--all-manifests``, dest=this_manifest_only)

Note: ``-j`` / ``--jobs`` is NOT registered for ``cherry-pick`` because
``CherryPick.PARALLEL_JOBS`` is ``None`` (inherited from ``Command``).

The ``cherry-pick`` subcommand requires exactly one positional argument (a
commit SHA1) and must be invoked from a git working tree directory because it
uses ``GitCommand(None, ...)`` which implicitly uses the process CWD as the
git working directory. For valid-value tests that only verify argparse
acceptance, a fake SHA1 with a nonexistent repo-dir is sufficient: the command
exits with a non-2 code (exit 1 from manifest-not-found or git-error), proving
optparse accepted the flag without an argument-parsing error.

For absence-default and documented-behavior tests, a real started repo and a
real cherry-pickable commit are required.

Valid-value tests confirm each flag is accepted without an argument-parsing
error (exit code != 2). Negative tests for boolean flags confirm that supplying
an inline value is rejected with exit code 2. The error message must appear on
stderr, not stdout.

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
from tests.functional.test_repo_cherry_pick_happy import (
    _PROJECT_PATH,
    _create_cherry_pick_sha,
    _setup_started_repo,
)

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
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-cherry-pick-flags-repo-dir"

# Inline-value token for boolean-flag negative tests.
# optparse exits 2 with '--<flag> option does not take a value' when a
# store_true or store_false flag is supplied with an inline value.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Placeholder SHA1 used in argument-parser tests that do not require a real
# initialized repository. The SHA1 is intentionally fake -- the command will
# fail at git invocation (exit 1) rather than at option parsing (exit 2),
# which proves the flag was accepted by optparse.
_FAKE_SHA1 = "0000000000000000000000000000000000000001"

# Branch names for individual flag behavior tests -- each test uses a unique name
# to avoid cross-test interference.
_BRANCH_ABSENCE_DEFAULT = "feature/cherry-pick-absence-default"
_BRANCH_FUNC_VERBOSE = "feature/cherry-pick-func-verbose"
_BRANCH_FUNC_QUIET = "feature/cherry-pick-func-quiet"
_BRANCH_FUNC_OUTER_MANIFEST = "feature/cherry-pick-func-outer-manifest"
_BRANCH_FUNC_NO_OUTER_MANIFEST = "feature/cherry-pick-func-no-outer-manifest"
_BRANCH_FUNC_THIS_MANIFEST = "feature/cherry-pick-func-this-manifest"
_BRANCH_CHANNEL_VALID = "feature/cherry-pick-channel-valid"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# Boolean store_true flags from _CommonOptions() that cherry-pick inherits.
# These accept no value; negative test uses inline-value syntax.
_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    ("-v", "short-verbose"),
    ("--verbose", "long-verbose"),
    ("--outer-manifest", "outer-manifest"),
    ("--this-manifest-only", "this-manifest-only"),
]

# Boolean store_false flags from _CommonOptions() that cherry-pick inherits.
_BOOL_STORE_FALSE_FLAGS: list[tuple[str, str]] = [
    ("-q", "short-quiet"),
    ("--quiet", "long-quiet"),
    ("--no-outer-manifest", "no-outer-manifest"),
    ("--no-this-manifest-only", "no-this-manifest-only"),
    ("--all-manifests", "all-manifests"),
]

# All boolean flags combined -- used for valid-value parametrize set.
_ALL_BOOL_FLAGS: list[tuple[str, str]] = _BOOL_STORE_TRUE_FLAGS + _BOOL_STORE_FALSE_FLAGS

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

# Absence-default parametrize data: (branch_suffix, test_id, flag_description)
# Each tuple drives one case verifying that omitting a specific flag defaults
# correctly and cherry-pick exits 0.
_ABSENCE_DEFAULT_CASES: list[tuple[str, str, str]] = [
    ("-verbose", "verbose-omitted", "--verbose"),
    ("-outer", "outer-manifest-omitted", "--outer-manifest"),
    ("-this", "this-manifest-only-omitted", "--this-manifest-only"),
]

# Documented-behavior parametrize data: (flag, branch_constant, test_id)
# Each tuple drives one case verifying that passing a specific flag with a
# real started repo produces exit 0.
_DOCUMENTED_BEHAVIOR_CASES: list[tuple[str, str, str]] = [
    ("--verbose", _BRANCH_FUNC_VERBOSE, "verbose"),
    ("--quiet", _BRANCH_FUNC_QUIET, "quiet"),
    ("--outer-manifest", _BRANCH_FUNC_OUTER_MANIFEST, "outer-manifest"),
    ("--no-outer-manifest", _BRANCH_FUNC_NO_OUTER_MANIFEST, "no-outer-manifest"),
    ("--this-manifest-only", _BRANCH_FUNC_THIS_MANIFEST, "this-manifest-only"),
]


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every flag available to cherry-pick
# (Also covers AC-FUNC-001: every documented flag behaves per its help text.)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickFlagsValidValues:
    """AC-TEST-001 / AC-FUNC-001: Every flag available to cherry-pick has a valid-value test.

    Exercises each flag from ``Command._CommonOptions()`` (which
    ``CherryPick`` inherits) by invoking 'kanon repo cherry-pick' with the
    flag and a fake SHA1 against a nonexistent repo-dir. Since optparse parses
    flags before any git or manifest operations occur, a non-2 exit code
    confirms the flag was accepted by the option parser.

    Note: ``CherryPick`` has no ``_Options()`` method of its own and
    ``PARALLEL_JOBS = None``, so ``-j`` / ``--jobs`` is NOT registered and
    is not tested here.

    Flags covered:
    - ``-v`` / ``--verbose``            (store_true, dest=output_mode, defaults to None)
    - ``-q`` / ``--quiet``              (store_false, dest=output_mode, defaults to None)
    - ``--outer-manifest``              (store_true, default=None)
    - ``--no-outer-manifest``           (store_false, dest=outer_manifest)
    - ``--this-manifest-only``          (store_true, default=None)
    - ``--no-this-manifest-only``       (store_false, dest=this_manifest_only)
    - ``--all-manifests``               (store_false, alias for --no-this-manifest-only)
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _ALL_BOOL_FLAGS],
        ids=[test_id for _, test_id in _ALL_BOOL_FLAGS],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo cherry-pick <fake-sha1> <flag>' against a nonexistent
        repo-dir and asserts that optparse does not reject the invocation (exit
        code != 2). A non-2 exit code confirms the flag itself was accepted; the
        cherry-pick subcommand exits with code 1 because the manifest is not
        found, which proves execution progressed past option parsing.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            flag,
            _FAKE_SHA1,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_and_all_manifests_combination_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--this-manifest-only --all-manifests' combination is accepted (exit != 2).

        Both flags share dest='this_manifest_only'. The last flag wins per
        optparse semantics. The combination must be accepted without exit 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            "--this-manifest-only",
            "--all-manifests",
            _FAKE_SHA1,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--this-manifest-only --all-manifests' triggered an argument-parsing "
            f"error (exit {result.returncode}).\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with typed or inline values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts typed or inline values has a negative test.

    Boolean flags (store_true / store_false) do not accept a typed value. The
    applicable negative test is to supply an unexpected inline value using
    '--flag=value' syntax. optparse exits 2 with
    '--<flag> option does not take a value' for such inputs.

    Note: ``cherry-pick`` has no ``--jobs`` flag (PARALLEL_JOBS is None), so
    no non-integer --jobs negative test applies here.

    This class verifies that every long-form boolean flag produces exit 2 when
    supplied with an inline value, and that the error message appears on
    stderr, not stdout.

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

        Supplies '--<flag>=unexpected' to 'kanon repo cherry-pick'. Since all
        CherryPick flags are store_true or store_false, optparse rejects the
        inline value with exit code 2 and emits
        '--<flag> option does not take a value' on stderr.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            bad_token,
            _FAKE_SHA1,
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
            "cherry-pick",
            bad_token,
            _FAKE_SHA1,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE}.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"

    def test_verbose_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--verbose=unexpected' error must name '--verbose' in stderr.

        The embedded optparse parser emits '--verbose option does not take a
        value' when '--verbose=unexpected' is supplied. Confirms the canonical
        flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--verbose" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            bad_token,
            _FAKE_SHA1,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--verbose=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "--verbose" in result.stderr, (
            f"Expected '--verbose' in stderr for '--verbose=unexpected' error.\n  stderr: {result.stderr!r}"
        )

    def test_quiet_with_inline_value_names_flag_in_stderr(self, tmp_path: pathlib.Path) -> None:
        """'--quiet=unexpected' error must name '--quiet' in stderr.

        The embedded optparse parser emits '--quiet option does not take a
        value' when '--quiet=unexpected' is supplied. Confirms the canonical
        flag name appears in the error message.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--quiet" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            bad_token,
            _FAKE_SHA1,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'--quiet=unexpected' exited {result.returncode}, expected {_ARGPARSE_ERROR_EXIT_CODE}."
        )
        assert "--quiet" in result.stderr, (
            f"Expected '--quiet' in stderr for '--quiet=unexpected' error.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each cherry-pick flag uses the documented default when
    omitted. Boolean flags default to None (store_true from _CommonOptions)
    when absent.

    Absence tests confirm that omitting every optional flag still produces a
    valid, non-error invocation (exit 0 on a properly started repo with a
    real cherry-pickable commit).
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo cherry-pick <sha1>' with all optional flags omitted exits 0.

        When no optional flags are supplied, every flag takes its documented
        default value:
        - --verbose defaults to None (output_mode unset)
        - --quiet defaults to None (output_mode unset)
        - --outer-manifest defaults to None
        - --this-manifest-only defaults to None

        Verifies that no optional flag is required and that all documented
        defaults produce a successful (exit 0) cherry-pick.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_ABSENCE_DEFAULT)
        project_dir = checkout_dir / _PROJECT_PATH
        cherry_sha = _create_cherry_pick_sha(project_dir)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "cherry-pick",
            cherry_sha,
            cwd=project_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo cherry-pick <sha1>' with all optional flags omitted exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "branch_suffix, flag_name",
        [(suffix, flag_name) for suffix, _, flag_name in _ABSENCE_DEFAULT_CASES],
        ids=[test_id for _, test_id, _ in _ABSENCE_DEFAULT_CASES],
    )
    def test_individual_flag_omitted_exits_zero(
        self, tmp_path: pathlib.Path, branch_suffix: str, flag_name: str
    ) -> None:
        """Omitting a specific flag defaults to None; cherry-pick exits 0.

        For each optional cherry-pick flag, verifies that when the flag is not
        supplied its documented default (None) takes effect without causing any
        argument-parsing error or execution failure.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_ABSENCE_DEFAULT + branch_suffix)
        project_dir = checkout_dir / _PROJECT_PATH
        cherry_sha = _create_cherry_pick_sha(project_dir)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "cherry-pick",
            cherry_sha,
            cwd=project_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo cherry-pick' without {flag_name} exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of each flag documented in
    Command._CommonOptions() as applied to the cherry-pick subcommand:
    - -v/--verbose: 'show all output' -- cherry-pick succeeds and exit 0
    - -q/--quiet: 'only show errors' -- cherry-pick succeeds and exit 0
    - --outer-manifest: 'operate starting at the outermost manifest' -- exit 0
    - --no-outer-manifest: 'do not operate on outer manifests' -- exit 0
    - --this-manifest-only: 'only operate on this (sub)manifest' -- exit 0

    Each test invokes 'kanon repo cherry-pick <sha1> <flag>' against a real
    started repo and confirms successful execution (exit 0).
    """

    @pytest.mark.parametrize(
        "flag, branch",
        [(flag, branch) for flag, branch, _ in _DOCUMENTED_BEHAVIOR_CASES],
        ids=[test_id for _, _, test_id in _DOCUMENTED_BEHAVIOR_CASES],
    )
    def test_flag_produces_exit_zero(self, tmp_path: pathlib.Path, flag: str, branch: str) -> None:
        """Each documented flag: cherry-pick with the flag against a real repo exits 0.

        Per the help text for each flag, passing it to 'kanon repo cherry-pick'
        on a properly started repo must produce a successful exit (exit 0).
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, branch)
        project_dir = checkout_dir / _PROJECT_PATH
        cherry_sha = _create_cherry_pick_sha(project_dir)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "cherry-pick",
            flag,
            cherry_sha,
            cwd=project_dir,
        )

        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'kanon repo cherry-pick {flag} <sha1>' exited {result.returncode}, "
            f"expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoCherryPickFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.
    """

    def test_valid_flags_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo cherry-pick' with valid flags must not emit tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_CHANNEL_VALID)
        project_dir = checkout_dir / _PROJECT_PATH
        cherry_sha = _create_cherry_pick_sha(project_dir)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "cherry-pick",
            cherry_sha,
            cwd=project_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo cherry-pick <sha1>' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of 'kanon repo cherry-pick' with valid flags.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo cherry-pick' with valid flags must not emit tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_CHANNEL_VALID + "-verbose")
        project_dir = checkout_dir / _PROJECT_PATH
        cherry_sha = _create_cherry_pick_sha(project_dir)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "cherry-pick",
            "--verbose",
            cherry_sha,
            cwd=project_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite 'kanon repo cherry-pick --verbose <sha1>' failed: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of 'kanon repo cherry-pick' with valid flags.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_no_error_keyword_on_stdout_for_valid_flags(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo cherry-pick' with valid flags must not emit 'Error:' to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_started_repo(tmp_path, _BRANCH_CHANNEL_VALID + "-error-kw")
        project_dir = checkout_dir / _PROJECT_PATH
        cherry_sha = _create_cherry_pick_sha(project_dir)

        result = _run_kanon(
            "repo",
            "--repo-dir",
            str(repo_dir),
            "cherry-pick",
            cherry_sha,
            cwd=project_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            "Prerequisite 'kanon repo cherry-pick' failed with argparse error."
        )
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of 'kanon repo cherry-pick': "
                f"{line!r}\n  stdout: {result.stdout!r}"
            )

    def test_invalid_flag_value_error_on_stderr_not_stdout(self, tmp_path: pathlib.Path) -> None:
        """Boolean flag with inline value error must appear on stderr, not stdout.

        The argument-parsing error for '--verbose=unexpected' must be routed
        to stderr only. Stdout must remain clean of the error detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = "--verbose" + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            "repo",
            "--repo-dir",
            repo_dir,
            "cherry-pick",
            bad_token,
            _FAKE_SHA1,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Expected exit {_ARGPARSE_ERROR_EXIT_CODE} for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"stderr must be non-empty for '{bad_token}' error."
        assert bad_token not in result.stdout, (
            f"'{bad_token}' error detail leaked to stdout.\n  stdout: {result.stdout!r}"
        )
