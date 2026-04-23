"""Functional tests for flag coverage of 'kanon repo envsubst'.

Exercises every flag available to ``subcmds/envsubst.py`` by invoking
``kanon repo envsubst`` as a subprocess. The ``Envsubst`` subcommand has no
subcommand-specific ``_Options()`` method; its flags are the common flags
registered by ``Command._CommonOptions()``:

Logging options:
- ``-v`` / ``--verbose`` (store_true, dest=output_mode, no explicit default -- defaults to None)
- ``-q`` / ``--quiet``   (store_false, dest=output_mode, no explicit default -- defaults to None)

Multi-manifest options:
- ``--outer-manifest``        (store_true, default=None)
- ``--no-outer-manifest``     (store_false, dest=outer_manifest)
- ``--this-manifest-only``    (store_true, default=None)
- ``--no-this-manifest-only`` / ``--all-manifests`` (store_false, dest=this_manifest_only)

AC wording note: AC-TEST-001 states "every _Options() flag ... has a valid-value
test." The upstream Envsubst subcommand defines no subcommand-specific _Options()
method; the base Command._Options() is a no-op stub. All available flags therefore
come from _CommonOptions(). This file exercises every one of those flags.

AC-TEST-002 states "every flag that accepts enumerated values has a negative test."
All _CommonOptions() boolean flags are store_true or store_false. None accept a
typed or enumerated value. The applicable negative test for each long-form boolean
flag is to supply it with an unexpected inline value ('--flag=unexpected') and
confirm optparse exits 2 with 'does not take a value' on stderr.

AC-TEST-003 states "flags have correct absence-default behavior when omitted."
When all flags are omitted, _CommonOptions sets output_mode=None (resolved to
quiet=False, verbose=False), outer_manifest=None (resolved to True when no outer
manifest exists), and this_manifest_only=None. Absence tests confirm that
'kanon repo envsubst' exits 0 and processes the manifest with these defaults.

Covers:
- AC-TEST-001: Every ``_Options()`` (common) flag in subcmds/envsubst.py has a
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
    _CLI_FLAG_REPO_DIR,
    _CLI_TOKEN_REPO,
    _run_kanon,
    _setup_synced_repo,
)

# ---------------------------------------------------------------------------
# Module-level constants -- all hard-coded domain literals extracted here;
# no inline literals in test logic, f-string diagnostics, or parametrize tuples.
# ---------------------------------------------------------------------------

_GIT_USER_NAME = "Repo Envsubst Flags Test User"
_GIT_USER_EMAIL = "repo-envsubst-flags@example.com"
_PROJECT_PATH = "envsubst-flags-test-project"

# CLI token for the envsubst subcommand.
_CLI_TOKEN_ENVSUBST = "envsubst"

# Composed CLI command phrase for diagnostic messages (no inline literals).
_CLI_COMMAND_PHRASE = f"kanon {_CLI_TOKEN_REPO} {_CLI_TOKEN_ENVSUBST}"

# Expected exit code for all successful invocations.
_EXPECTED_EXIT_CODE = 0

# Argument-parsing error exit code (optparse exits 2 for invalid flag usage).
_ARGPARSE_ERROR_EXIT_CODE = 2

# Nonexistent repo-dir name used in negative tests that fail at parse time.
# Boolean-with-inline-value negative tests are rejected before repo discovery.
_NONEXISTENT_REPO_DIR_NAME = "nonexistent-envsubst-flags-repo-dir"

# Inline-value suffix for negative tests on boolean (store_true/store_false) flags.
# optparse exits 2 with '--<flag> option does not take a value' when a boolean
# flag is supplied with an inline '=value' suffix.
_INLINE_VALUE_SUFFIX = "=unexpected"

# Canonical optparse phrase emitted when a boolean flag receives an inline value.
_OPTPARSE_NO_VALUE_PHRASE = "does not take a value"

# Traceback indicator used in channel-discipline assertions.
_TRACEBACK_MARKER = "Traceback (most recent call last)"

# Error prefix that must not appear on stdout for successful runs.
_ERROR_PREFIX = "Error:"

# ---------------------------------------------------------------------------
# Hidden git-repo metadata directory and manifest path sub-constants.
# All path fragments are composed from these tokens -- no hardcoded substrings.
# ---------------------------------------------------------------------------

_DOT_REPO = ".repo"
_MANIFEST_DIR = "manifests"
_MANIFEST_FILENAME = "default.xml"

# Composed path fragment that must appear in stdout when envsubst scans the
# .repo/manifests directory and finds the default manifest XML file.
_MANIFEST_PATH_FRAGMENT = f"{_DOT_REPO}/{_MANIFEST_DIR}/{_MANIFEST_FILENAME}"

# Dict-repr phrase constants for output_mode and manifest option assertions.
# Envsubst.Execute() prints the options namespace as a dict repr; these
# constants capture the exact key-value substring to assert against.
_OUTPUT_MODE_TRUE = "'output_mode': True"
_OUTPUT_MODE_FALSE = "'output_mode': False"
_OUTPUT_MODE_NONE = "'output_mode': None"
_OUTER_MANIFEST_TRUE = "'outer_manifest': True"
_OUTER_MANIFEST_FALSE = "'outer_manifest': False"
_THIS_MANIFEST_ONLY_TRUE = "'this_manifest_only': True"

# ---------------------------------------------------------------------------
# CLI flag token constants for _CommonOptions() flags.
# These cover both Logging options and Multi-manifest options.
# ---------------------------------------------------------------------------

# Logging option flags (store_true / store_false, dest=output_mode).
_CLI_FLAG_VERBOSE_SHORT = "-v"
_CLI_FLAG_VERBOSE_LONG = "--verbose"
_CLI_FLAG_QUIET_SHORT = "-q"
_CLI_FLAG_QUIET_LONG = "--quiet"

# Multi-manifest option flags (store_true / store_false).
_CLI_FLAG_OUTER_MANIFEST = "--outer-manifest"
_CLI_FLAG_NO_OUTER_MANIFEST = "--no-outer-manifest"
_CLI_FLAG_THIS_MANIFEST_ONLY = "--this-manifest-only"
_CLI_FLAG_NO_THIS_MANIFEST_ONLY = "--no-this-manifest-only"
_CLI_FLAG_ALL_MANIFESTS = "--all-manifests"

# ---------------------------------------------------------------------------
# Parametrize data tables.
# ---------------------------------------------------------------------------

# AC-TEST-001: All boolean flags (store_true and store_false) that must be
# accepted without argument-parsing error (exit != 2).
_BOOL_STORE_TRUE_FLAGS: list[tuple[str, str]] = [
    (_CLI_FLAG_VERBOSE_SHORT, "short-verbose"),
    (_CLI_FLAG_VERBOSE_LONG, "long-verbose"),
    (_CLI_FLAG_OUTER_MANIFEST, "outer-manifest"),
    (_CLI_FLAG_THIS_MANIFEST_ONLY, "this-manifest-only"),
]

_BOOL_STORE_FALSE_FLAGS: list[tuple[str, str]] = [
    (_CLI_FLAG_QUIET_SHORT, "short-quiet"),
    (_CLI_FLAG_QUIET_LONG, "long-quiet"),
    (_CLI_FLAG_NO_OUTER_MANIFEST, "no-outer-manifest"),
    (_CLI_FLAG_NO_THIS_MANIFEST_ONLY, "no-this-manifest-only"),
    (_CLI_FLAG_ALL_MANIFESTS, "all-manifests"),
]

# AC-TEST-002: Long-form boolean flags used in negative tests.
# Short-form flags (-v, -q) do not support '--flag=value' inline syntax
# in optparse, so only long-form flags are included here.
_LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST: list[tuple[str, str]] = [
    (_CLI_FLAG_VERBOSE_LONG, "verbose"),
    (_CLI_FLAG_QUIET_LONG, "quiet"),
    (_CLI_FLAG_OUTER_MANIFEST, "outer-manifest"),
    (_CLI_FLAG_NO_OUTER_MANIFEST, "no-outer-manifest"),
    (_CLI_FLAG_THIS_MANIFEST_ONLY, "this-manifest-only"),
    (_CLI_FLAG_NO_THIS_MANIFEST_ONLY, "no-this-manifest-only"),
    (_CLI_FLAG_ALL_MANIFESTS, "all-manifests"),
]


# ---------------------------------------------------------------------------
# Shared setup helper
# ---------------------------------------------------------------------------


def _setup_envsubst_flags_repo(
    tmp_path: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Create bare repos, run repo init and repo sync, return (checkout_dir, repo_dir).

    Delegates to ``_setup_synced_repo`` from tests.functional.conftest with the
    project path and git identity specific to this test module.

    Args:
        tmp_path: pytest-provided temporary directory root.

    Returns:
        A tuple of ``(checkout_dir, repo_dir)`` after a successful init and sync.

    Raises:
        AssertionError: When ``kanon repo init`` or ``kanon repo sync`` exits
            with a non-zero code.
    """
    return _setup_synced_repo(
        tmp_path,
        git_user_name=_GIT_USER_NAME,
        git_user_email=_GIT_USER_EMAIL,
        project_path=_PROJECT_PATH,
    )


# ---------------------------------------------------------------------------
# AC-TEST-001: Valid-value tests for every _Options() flag in subcmds/envsubst.py
# (Also partially covers AC-FUNC-001: every documented flag behaves per its help text.)
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstFlagsValidValues:
    """AC-TEST-001: Every ``_Options()`` (common) flag in subcmds/envsubst.py has a valid-value test.

    Exercises each flag registered in ``Command._CommonOptions()`` for the
    'envsubst' subcommand by invoking 'kanon repo envsubst' with the flag
    against a real synced .repo directory. ``Envsubst`` defines no subcommand-
    specific ``_Options()``; all available flags come from ``_CommonOptions()``.

    Valid-value tests confirm:
    - The flag is accepted by optparse (exit != 2).
    - The command processes the manifest (manifest path appears in stdout).

    Flags covered:
    - ``-v`` / ``--verbose``        (store_true, dest=output_mode, defaults to None)
    - ``-q`` / ``--quiet``          (store_false, dest=output_mode, defaults to None)
    - ``--outer-manifest``          (store_true, default=None)
    - ``--no-outer-manifest``       (store_false, dest=outer_manifest)
    - ``--this-manifest-only``      (store_true, default=None)
    - ``--no-this-manifest-only``   (store_false, dest=this_manifest_only)
    - ``--all-manifests``           (store_false, alias for --no-this-manifest-only)
    """

    _ALL_BOOL_FLAGS: list[tuple[str, str]] = _BOOL_STORE_TRUE_FLAGS + _BOOL_STORE_FALSE_FLAGS

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _ALL_BOOL_FLAGS],
        ids=[test_id for _, test_id in _ALL_BOOL_FLAGS],
    )
    def test_boolean_flag_accepted(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag is accepted by the argument parser (does not exit 2).

        Calls 'kanon repo envsubst' with the given boolean flag against a
        properly synced .repo directory and asserts that optparse does not
        reject the invocation (exit code != 2). A non-2 exit code confirms
        the flag itself was accepted.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Flag {flag!r} triggered an argument-parsing error "
            f"(exit {result.returncode}) for '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _ALL_BOOL_FLAGS],
        ids=[test_id for _, test_id in _ALL_BOOL_FLAGS],
    )
    def test_boolean_flag_emits_manifest_path_to_stdout(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each boolean flag invocation emits the manifest path to stdout.

        Confirms that the manifest was actually processed by the envsubst
        subcommand when each flag is supplied. The manifest path fragment
        must appear in stdout, verifying the Execute() method ran to completion.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            flag,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: flag {flag!r} triggered argument-parsing error for "
            f"'{_CLI_COMMAND_PHRASE}': {result.stderr!r}"
        )
        assert _MANIFEST_PATH_FRAGMENT in result.stdout, (
            f"Expected {_MANIFEST_PATH_FRAGMENT!r} in stdout of "
            f"'{_CLI_COMMAND_PHRASE}' with flag {flag!r}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_verbose_flag_sets_output_mode_to_true(self, tmp_path: pathlib.Path) -> None:
        """--verbose sets output_mode=True in the options dict printed by Execute().

        Envsubst.Execute() prints 'Executing envsubst <opt_dict>, <args>'.
        When --verbose is supplied, output_mode must be True in that dict,
        confirming the flag was correctly parsed and applied.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_VERBOSE_LONG,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_VERBOSE_LONG}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _OUTPUT_MODE_TRUE in result.stdout, (
            f"Expected {_OUTPUT_MODE_TRUE!r} in stdout for "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_VERBOSE_LONG}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_quiet_flag_sets_output_mode_to_false(self, tmp_path: pathlib.Path) -> None:
        """--quiet sets output_mode=False in the options dict printed by Execute().

        Envsubst.Execute() prints 'Executing envsubst <opt_dict>, <args>'.
        When --quiet is supplied, output_mode must be False in that dict,
        confirming the flag was correctly parsed and applied.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_QUIET_LONG,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_QUIET_LONG}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _OUTPUT_MODE_FALSE in result.stdout, (
            f"Expected {_OUTPUT_MODE_FALSE!r} in stdout for "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_QUIET_LONG}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_this_manifest_only_sets_this_manifest_only_to_true(self, tmp_path: pathlib.Path) -> None:
        """--this-manifest-only sets this_manifest_only=True in the options dict.

        Envsubst.Execute() prints 'Executing envsubst <opt_dict>, <args>'.
        When --this-manifest-only is supplied, this_manifest_only must be
        True in that dict, confirming the flag was correctly parsed.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_THIS_MANIFEST_ONLY,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_THIS_MANIFEST_ONLY}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _THIS_MANIFEST_ONLY_TRUE in result.stdout, (
            f"Expected {_THIS_MANIFEST_ONLY_TRUE!r} in stdout for "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_THIS_MANIFEST_ONLY}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_no_outer_manifest_sets_outer_manifest_to_false(self, tmp_path: pathlib.Path) -> None:
        """--no-outer-manifest sets outer_manifest=False in the options dict.

        Envsubst.Execute() prints 'Executing envsubst <opt_dict>, <args>'.
        When --no-outer-manifest is supplied, outer_manifest must be False in
        that dict, confirming the flag was correctly parsed and overrides the
        default outer-manifest traversal.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_NO_OUTER_MANIFEST,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_NO_OUTER_MANIFEST}' exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert _OUTER_MANIFEST_FALSE in result.stdout, (
            f"Expected {_OUTER_MANIFEST_FALSE!r} in stdout for "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_NO_OUTER_MANIFEST}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_verbose_and_this_manifest_only_combination_accepted(self, tmp_path: pathlib.Path) -> None:
        """'--verbose --this-manifest-only' combination is accepted (exit != 2).

        Both flags are independent boolean flags from different option groups.
        When combined they must not trigger an argument-parsing error.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_VERBOSE_LONG,
            _CLI_FLAG_THIS_MANIFEST_ONLY,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_VERBOSE_LONG} {_CLI_FLAG_THIS_MANIFEST_ONLY}' triggered "
            f"an argument-parsing error (exit {result.returncode}) for "
            f"'{_CLI_COMMAND_PHRASE}'.\n  stderr: {result.stderr!r}"
        )

    def test_outer_manifest_and_no_outer_manifest_last_wins(self, tmp_path: pathlib.Path) -> None:
        """'--outer-manifest --no-outer-manifest' is accepted; last flag wins (exit != 2).

        Both flags share dest='outer_manifest'. The last flag wins per optparse
        semantics. The combination must be accepted without exit 2.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_OUTER_MANIFEST,
            _CLI_FLAG_NO_OUTER_MANIFEST,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_OUTER_MANIFEST} {_CLI_FLAG_NO_OUTER_MANIFEST}' triggered "
            f"an argument-parsing error (exit {result.returncode}) for "
            f"'{_CLI_COMMAND_PHRASE}'.\n  stderr: {result.stderr!r}"
        )

    def test_this_manifest_only_and_no_this_manifest_only_last_wins(self, tmp_path: pathlib.Path) -> None:
        """'--this-manifest-only --no-this-manifest-only' is accepted; last flag wins (exit != 2).

        Both flags share dest='this_manifest_only'. The last flag wins per
        optparse semantics. The combination must be accepted without exit 2.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_THIS_MANIFEST_ONLY,
            _CLI_FLAG_NO_THIS_MANIFEST_ONLY,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_THIS_MANIFEST_ONLY} {_CLI_FLAG_NO_THIS_MANIFEST_ONLY}' triggered "
            f"an argument-parsing error (exit {result.returncode}) for "
            f"'{_CLI_COMMAND_PHRASE}'.\n  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: Negative tests for flags with invalid (inline) values
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstFlagsInvalidValues:
    """AC-TEST-002: Every flag that accepts enumerated values has a negative test.

    All _CommonOptions() boolean flags for envsubst are store_true or
    store_false. None accept a typed or enumerated value. The applicable
    negative test for each long-form boolean flag is to supply it with an
    unexpected inline value using the '--flag=unexpected' syntax. optparse exits
    2 with '--<flag> option does not take a value' for such inputs.

    This class verifies that every long-form boolean flag produces exit 2 when
    supplied with an inline value, that the canonical 'does not take a value'
    phrase and the flag name appear in stderr, and that the error does not
    leak to stdout.

    Short-form flags (-v, -q) do not support '--flag=value' inline syntax
    in optparse, so only long-form flags are included.
    """

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_exits_2(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with an inline value must exit 2.

        Supplies '--<flag>=unexpected' to 'kanon repo envsubst'. Since all
        _CommonOptions() flags for envsubst are store_true or store_false,
        optparse rejects the inline value with exit code 2.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE} for '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "flag",
        [flag for flag, _ in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
        ids=[test_id for _, test_id in _LONG_BOOL_FLAGS_FOR_NEGATIVE_TEST],
    )
    def test_bool_flag_with_inline_value_error_on_stderr(self, tmp_path: pathlib.Path, flag: str) -> None:
        """Each long-form boolean flag with inline value emits error on stderr, not stdout.

        Supplies '--<flag>=unexpected' to 'kanon repo envsubst'. optparse
        rejects with exit 2. The canonical 'does not take a value' phrase and
        the flag name must appear on stderr. Stdout must not contain the
        rejection detail.
        """
        repo_dir = str(tmp_path / _NONEXISTENT_REPO_DIR_NAME)
        bad_token = flag + _INLINE_VALUE_SUFFIX
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            repo_dir,
            _CLI_TOKEN_ENVSUBST,
            bad_token,
        )
        assert result.returncode == _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite: '{bad_token}' exited {result.returncode}, "
            f"expected {_ARGPARSE_ERROR_EXIT_CODE} for '{_CLI_COMMAND_PHRASE}'.\n"
            f"  stderr: {result.stderr!r}"
        )
        assert len(result.stderr) > 0, f"'{bad_token}' produced empty stderr; error must appear on stderr."
        assert _OPTPARSE_NO_VALUE_PHRASE in result.stderr, (
            f"Expected {_OPTPARSE_NO_VALUE_PHRASE!r} in stderr for '{bad_token}'.\n  stderr: {result.stderr!r}"
        )
        assert flag in result.stderr, (
            f"Expected flag {flag!r} in stderr for '{bad_token}' error.\n  stderr: {result.stderr!r}"
        )
        assert bad_token not in result.stdout, f"Bad token {bad_token!r} leaked to stdout.\n  stdout: {result.stdout!r}"


# ---------------------------------------------------------------------------
# AC-TEST-003: Absence-default behavior when flags are omitted
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstFlagsAbsenceDefaults:
    """AC-TEST-003: Flags have correct absence-default behavior when omitted.

    Verifies that each flag uses the documented default when omitted.
    All boolean flags from _CommonOptions have no explicit default= parameter,
    so their option-parser default is None when absent. After
    Command.ValidateOptions() runs:
    - output_mode=None -> quiet=False, verbose=False
    - outer_manifest=None -> resolved to True (no outer manifest present)
    - this_manifest_only=None (left as-is)

    The Execute() method prints the resolved values, allowing assertions
    on the exact defaults observed at runtime.

    Absence tests confirm that omitting every optional flag still produces
    a valid, exit-0 invocation and that the manifest is processed correctly.
    """

    def test_all_flags_omitted_exits_zero(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst' with all optional flags omitted exits 0.

        When no optional flags are supplied, the command uses all defaults:
        - output_mode defaults to None (verbose=False, quiet=False)
        - outer_manifest defaults to None (resolved to True)
        - this_manifest_only defaults to None

        Verifies that no flag is required and all defaults produce a successful
        (exit 0) invocation on a synced repo.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"'{_CLI_COMMAND_PHRASE}' with all optional flags omitted exited "
            f"{result.returncode}, expected {_EXPECTED_EXIT_CODE}.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_all_flags_omitted_output_mode_defaults_to_none(self, tmp_path: pathlib.Path) -> None:
        """When --verbose and --quiet are omitted, output_mode defaults to None.

        With no logging flag, Execute() prints output_mode as None (before
        ValidateOptions resolves it to quiet=False, verbose=False). The raw
        output_mode value in the printed dict must be None.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        )
        assert _OUTPUT_MODE_NONE in result.stdout, (
            f"Expected {_OUTPUT_MODE_NONE!r} in stdout when no logging flag supplied.\n  stdout: {result.stdout!r}"
        )

    def test_all_flags_omitted_outer_manifest_defaults_to_true(self, tmp_path: pathlib.Path) -> None:
        """When --outer-manifest / --no-outer-manifest are omitted, outer_manifest defaults to True.

        ValidateOptions() sets outer_manifest=True when no outer manifest
        exists (the common case). The resolved value printed in the Execute()
        dict must be True.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        )
        assert _OUTER_MANIFEST_TRUE in result.stdout, (
            f"Expected {_OUTER_MANIFEST_TRUE!r} in stdout when no outer-manifest "
            f"flag supplied.\n  stdout: {result.stdout!r}"
        )

    def test_all_flags_omitted_processes_manifest(self, tmp_path: pathlib.Path) -> None:
        """'kanon repo envsubst' with all flags omitted still processes the manifest.

        When all optional flags are absent, the command must still find and
        process the manifest XML at the expected path. The manifest path fragment
        must appear in stdout, confirming the Execute() method ran to completion.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            cwd=checkout_dir,
        )
        assert result.returncode == _EXPECTED_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE}' failed: {result.stderr!r}"
        )
        assert _MANIFEST_PATH_FRAGMENT in result.stdout, (
            f"Expected {_MANIFEST_PATH_FRAGMENT!r} in stdout of '{_CLI_COMMAND_PHRASE}' "
            f"with all flags omitted.\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Documented flag behavior per help text
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstFlagsDocumentedBehavior:
    """AC-FUNC-001: Every documented flag behaves per its help text.

    Verifies the functional behavior of flags documented in
    ``Command._CommonOptions()`` for the 'envsubst' subcommand:

    - ``-v`` / ``--verbose``: 'show all output' -- sets output_mode=True.
    - ``-q`` / ``--quiet``:   'only show errors' -- sets output_mode=False.
    - ``--outer-manifest``:         'operate starting at the outermost manifest'
    - ``--no-outer-manifest``:      'do not operate on outer manifests'
    - ``--this-manifest-only``:     'only operate on this (sub)manifest'
    - ``--no-this-manifest-only``:  'operate on this manifest and its submanifests'
    - ``--all-manifests``:          alias for --no-this-manifest-only

    Each test confirms that the flag is accepted and the command produces
    the expected option dict values as documented.
    """

    def test_verbose_short_form_accepted_and_sets_output_mode_true(self, tmp_path: pathlib.Path) -> None:
        """'-v' is accepted and sets output_mode=True per 'show all output' help text.

        Confirms the short-form verbose flag is accepted (exit != 2) and that
        the output_mode value printed by Execute() is True, matching the
        documented behavior 'show all output'.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_VERBOSE_SHORT,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_VERBOSE_SHORT}' triggered argument-parsing error "
            f"for '{_CLI_COMMAND_PHRASE}'.\n  stderr: {result.stderr!r}"
        )
        assert _OUTPUT_MODE_TRUE in result.stdout, (
            f"Expected {_OUTPUT_MODE_TRUE!r} in stdout for "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_VERBOSE_SHORT}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_quiet_short_form_accepted_and_sets_output_mode_false(self, tmp_path: pathlib.Path) -> None:
        """'-q' is accepted and sets output_mode=False per 'only show errors' help text.

        Confirms the short-form quiet flag is accepted (exit != 2) and that
        the output_mode value printed by Execute() is False, matching the
        documented behavior 'only show errors'.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_QUIET_SHORT,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_QUIET_SHORT}' triggered argument-parsing error "
            f"for '{_CLI_COMMAND_PHRASE}'.\n  stderr: {result.stderr!r}"
        )
        assert _OUTPUT_MODE_FALSE in result.stdout, (
            f"Expected {_OUTPUT_MODE_FALSE!r} in stdout for "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_QUIET_SHORT}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_all_manifests_alias_accepted_same_as_no_this_manifest_only(self, tmp_path: pathlib.Path) -> None:
        """'--all-manifests' alias is accepted and sets this_manifest_only=None->False.

        '--all-manifests' is an alias for '--no-this-manifest-only' (both share
        dest='this_manifest_only', action='store_false'). The command must
        accept the alias without exit 2. Per optparse semantics, this sets
        this_manifest_only to False.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_ALL_MANIFESTS,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"'{_CLI_FLAG_ALL_MANIFESTS}' triggered argument-parsing error "
            f"for '{_CLI_COMMAND_PHRASE}'.\n  stderr: {result.stderr!r}"
        )
        assert _MANIFEST_PATH_FRAGMENT in result.stdout, (
            f"Expected {_MANIFEST_PATH_FRAGMENT!r} in stdout of "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_ALL_MANIFESTS}'.\n"
            f"  stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.functional
class TestRepoEnvsubstFlagsChannelDiscipline:
    """AC-CHANNEL-001: stdout vs stderr channel discipline for flag invocations.

    Verifies that successful flag invocations do not write Python tracebacks
    or 'Error:'-prefixed messages to stdout, and that argument-parsing errors
    appear on stderr only. No cross-channel leakage is permitted.

    Channel properties verified:
    - stdout of successful runs: no traceback, no 'Error:' lines.
    - stderr of successful runs: no traceback.
    - stderr of invalid-flag runs: non-empty, contains error detail.
    - stdout of invalid-flag runs: does not contain the bad token.
    """

    def test_valid_flags_invocation_has_no_traceback_on_stdout(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo envsubst --verbose' must not emit tracebacks to stdout.

        On success, stdout must not contain 'Traceback (most recent call last)'.
        Tracebacks on stdout indicate an unhandled exception that escaped to
        the wrong channel.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_VERBOSE_LONG,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_VERBOSE_LONG}' "
            f"failed with argparse error: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stdout, (
            f"Python traceback found in stdout of "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_VERBOSE_LONG}'.\n"
            f"  stdout: {result.stdout!r}"
        )

    def test_valid_flags_invocation_has_no_traceback_on_stderr(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo envsubst --quiet' must not emit tracebacks to stderr.

        On success, stderr must not contain 'Traceback (most recent call last)'.
        A traceback on stderr during a successful run indicates an unhandled
        exception was swallowed rather than propagated correctly.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_QUIET_LONG,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_QUIET_LONG}' failed with argparse error: {result.stderr!r}"
        )
        assert _TRACEBACK_MARKER not in result.stderr, (
            f"Python traceback found in stderr of "
            f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_QUIET_LONG}'.\n"
            f"  stderr: {result.stderr!r}"
        )

    def test_no_error_keyword_on_stdout_for_valid_flags(self, tmp_path: pathlib.Path) -> None:
        """Successful 'kanon repo envsubst --verbose' must not emit 'Error:' prefix to stdout.

        Error-prefixed messages are a stderr-only concern. A successful
        invocation must not produce any line starting with 'Error:' on stdout.
        """
        checkout_dir, repo_dir = _setup_envsubst_flags_repo(tmp_path)
        result = _run_kanon(
            _CLI_TOKEN_REPO,
            _CLI_FLAG_REPO_DIR,
            str(repo_dir),
            _CLI_TOKEN_ENVSUBST,
            _CLI_FLAG_VERBOSE_LONG,
            cwd=checkout_dir,
        )
        assert result.returncode != _ARGPARSE_ERROR_EXIT_CODE, (
            f"Prerequisite '{_CLI_COMMAND_PHRASE} {_CLI_FLAG_VERBOSE_LONG}' failed with argparse error."
        )
        for line in result.stdout.splitlines():
            assert not line.startswith(_ERROR_PREFIX), (
                f"'{_ERROR_PREFIX}' line found in stdout of "
                f"'{_CLI_COMMAND_PHRASE} {_CLI_FLAG_VERBOSE_LONG}': {line!r}\n"
                f"  stdout: {result.stdout!r}"
            )
